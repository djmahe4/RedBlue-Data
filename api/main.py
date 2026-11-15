from __future__ import annotations

import hmac
import html
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from harness.graph import HarnessState, run_graph
from harness.telemetry import make_span

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="RedBlue-Data Harness")
TEMPLATES = Path(__file__).parent.parent / "templates"
RUNS: dict[str, dict[str, Any]] = {}
app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    page = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    planner_mode = html.escape(os.environ.get("HARNESS_PLANNER", "rules").strip().lower())
    return HTMLResponse(page.replace("__PLANNER_MODE__", planner_mode))


@app.post("/api/run/start")
async def start_run(payload: dict[str, Any]) -> dict[str, str]:
    run_id = uuid.uuid4().hex
    RUNS[run_id] = {
        "state": HarnessState(task=str(payload.get("task", "")), context=payload),
        "events": [],
        "syscalls": [],
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"run_id": run_id, "trace_id": run_id, "dashboard_url": f"/dashboard/{run_id}"}


@app.get("/api/run/{run_id}/stream", response_model=None)
async def stream_run(run_id: str) -> EventSourceResponse | JSONResponse:
    run = RUNS.get(run_id)
    if run is None:
        return JSONResponse({"error": "run not found"}, status_code=404)
    if run["status"] != "queued":
        return JSONResponse({"error": "run is not queued"}, status_code=409)
    run["status"] = "running"

    async def events():
        try:
            async for event in run_graph(run["state"], run_id=run_id):
                run["events"].append(event)
                if event["event"] == "hitl_request":
                    run["status"] = "awaiting_approval"
                elif event["event"] == "error":
                    run["status"] = "failed"
                yield {"event": event["event"], "data": json.dumps(event)}
            if run["status"] == "running":
                run["status"] = "completed"
        except Exception as exc:
            run["status"] = "failed"
            parent_span_id = run["events"][-1].get("span_id") if run["events"] else None
            event = make_span(
                "error",
                run_id,
                name="harness.exception",
                parent_span_id=parent_span_id,
                status="ERROR",
                attributes={
                    "exception.type": type(exc).__name__,
                    "exception.message": str(exc),
                },
                payload={"message": str(exc)},
            )
            run["events"].append(event)
            yield {"event": "error", "data": json.dumps(event)}

    return EventSourceResponse(events())


@app.post("/api/run/{run_id}/approve")
async def approve_run(run_id: str) -> JSONResponse:
    if run_id not in RUNS:
        return JSONResponse({"error": "run not found"}, status_code=404)
    run = RUNS[run_id]
    if run["status"] != "awaiting_approval":
        return JSONResponse({"error": "run is not awaiting approval"}, status_code=409)
    state = run["state"]
    pending = state.pending_action or {}
    approval_event = make_span(
        "approval",
        run_id,
        name="harness.approval",
        parent_span_id=state.trace_context.get("hitl_span_id"),
        attributes={
            "approval.decision": "approved",
            "tool.name": pending.get("tool", "unknown"),
        },
    )
    state.trace_context["approval_span_id"] = approval_event["span_id"]
    state.trace.append(approval_event)
    run["events"].append(approval_event)
    state.approved = True
    run["status"] = "queued"
    return JSONResponse({"status": "approved", "run_id": run_id})


@app.get("/api/run/{run_id}")
async def run_status(run_id: str) -> dict[str, Any]:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": run_id,
        "trace_id": run_id,
        "task": run["state"].task,
        "status": run["status"],
        "pending_action": run["state"].pending_action,
        "last_error": next(
            (event.get("message") for event in reversed(run["events"]) if event.get("event") == "error"),
            None,
        ),
        "event_count": len(run["events"]),
        "syscall_count": len(run["syscalls"]),
    }


@app.post("/api/run/{run_id}/syscalls")
async def record_syscall(
    run_id: str,
    payload: dict[str, Any],
    x_trace_token: str | None = Header(default=None),
) -> dict[str, Any]:
    expected_token = os.environ.get("REDBLUE_TRACE_TOKEN")
    if not expected_token:
        raise HTTPException(status_code=503, detail="syscall trace ingestion is not configured")
    if not x_trace_token or not hmac.compare_digest(x_trace_token, expected_token):
        raise HTTPException(status_code=401, detail="invalid trace token")

    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    syscall = payload.get("syscall")
    if not isinstance(syscall, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", syscall):
        raise HTTPException(status_code=422, detail="syscall must be a valid syscall name")
    pid = payload.get("pid")
    duration_ns = payload.get("duration_ns")
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid < 0):
        raise HTTPException(status_code=422, detail="pid must be a non-negative integer")
    if duration_ns is not None and (
        isinstance(duration_ns, bool) or not isinstance(duration_ns, int) or duration_ns < 0
    ):
        raise HTTPException(status_code=422, detail="duration_ns must be a non-negative integer")
    result = payload.get("result")
    if result is not None and (isinstance(result, bool) or not isinstance(result, int)):
        raise HTTPException(status_code=422, detail="result must be an integer")
    parent_span_id = payload.get("parent_span_id")
    if parent_span_id is not None and (
        not isinstance(parent_span_id, str)
        or not re.fullmatch(r"[0-9a-fA-F]{16}", parent_span_id)
    ):
        raise HTTPException(status_code=422, detail="parent_span_id must be a 16-character hex span ID")

    timestamp = payload.get("timestamp")
    if timestamp is None:
        parsed_timestamp = datetime.now(timezone.utc)
    elif not isinstance(timestamp, str) or len(timestamp) > 64:
        raise HTTPException(status_code=422, detail="timestamp must be an ISO 8601 string of at most 64 characters")
    else:
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="timestamp must be a valid ISO 8601 value") from exc
        if parsed_timestamp.tzinfo is None:
            parsed_timestamp = parsed_timestamp.replace(tzinfo=timezone.utc)

    try:
        start_time_unix_nano = int(parsed_timestamp.timestamp() * 1_000_000_000)
    except (OverflowError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="timestamp is outside the supported range") from exc

    event = make_span(
        "syscall",
        run_id,
        name=f"syscall.{syscall}",
        parent_span_id=parent_span_id,
        status=("UNSET" if result is None else "ERROR" if result < 0 else "OK"),
        start_time_unix_nano=start_time_unix_nano,
        duration_ns=duration_ns or 0,
        attributes={
            "process.pid": pid,
            "redblue.syscall.name": syscall,
            "redblue.syscall.result": result,
            "redblue.syscall.duration_ns": duration_ns,
        },
        payload={"syscall": syscall, "pid": pid, "result": result},
    )
    run["syscalls"].append(event)
    if len(run["syscalls"]) > 10_000:
        del run["syscalls"][:-10_000]
    return {"status": "recorded", "count": len(run["syscalls"])}


@app.get("/api/run/{run_id}/syscalls")
async def list_syscalls(run_id: str) -> dict[str, Any]:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"syscalls": run["syscalls"]}


@app.patch("/api/config/tools")
async def configure_tools(payload: dict[str, Any]) -> dict[str, Any]:
    return {"tools": payload}


@app.patch("/api/config/model")
async def configure_model(payload: dict[str, Any]) -> dict[str, Any]:
    return {"model": payload}


@app.get("/r3f/trace/{run_id}")
async def trace(run_id: str) -> dict[str, list[dict[str, Any]]]:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    events = sorted(
        run["events"] + run["syscalls"],
        key=lambda event: event.get("start_time_unix_nano", 0),
    )
    nodes = []
    for index, event in enumerate(events):
        attributes = event.get("attributes", {})
        span_id = event.get("span_id") or f"{run_id}:{index}"
        nodes.append({
            "id": span_id,
            "trace_id": event.get("trace_id", run_id),
            "span_id": span_id,
            "parent_span_id": event.get("parent_span_id"),
            "name": event.get("name", event.get("event", "event")),
            "kind": event.get("kind", "INTERNAL"),
            "type": event.get("event", "event"),
            "label": (
                event.get("tool")
                or event.get("syscall")
                or event.get("plan", {}).get("tool")
                or attributes.get("tool.name")
                or event.get("name")
                or event.get("event")
            ),
            "timestamp": event.get("timestamp"),
            "start_time_unix_nano": event.get("start_time_unix_nano"),
            "end_time_unix_nano": event.get("end_time_unix_nano"),
            "duration_ns": event.get("duration_ns", 0),
            "status": event.get("status", "UNSET"),
            "attributes": attributes,
            "message": event.get("message"),
            "pid": event.get("pid"),
            "result": event.get("result"),
        })
    span_ids = {node["id"] for node in nodes}
    edges = [
        {"from": node["parent_span_id"], "to": node["id"], "relationship": "parent"}
        for node in nodes
        if node["parent_span_id"] in span_ids
    ]
    return {"nodes": nodes, "edges": edges}


@app.get("/dashboard/{run_id}", response_class=HTMLResponse)
async def dashboard(run_id: str) -> HTMLResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="run not found")
    page = (TEMPLATES / "run_dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(page.replace("__RUN_ID_JSON__", json.dumps(run_id)))


@app.get("/ui/tools", response_class=HTMLResponse)
async def tools_fragment() -> str:
    return (TEMPLATES / "_tool_toggles.html").read_text(encoding="utf-8")


@app.post("/ui/tools", response_class=HTMLResponse)
async def update_tools() -> str:
    return (TEMPLATES / "_tool_toggles.html").read_text(encoding="utf-8")


@app.get("/ui/dataset", response_class=HTMLResponse)
async def dataset_fragment() -> str:
    return (TEMPLATES / "_dataset_table.html").read_text(encoding="utf-8")
