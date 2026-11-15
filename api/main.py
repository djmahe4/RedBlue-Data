from __future__ import annotations

import hmac
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

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="RedBlue-Data Harness")
TEMPLATES = Path(__file__).parent.parent / "templates"
RUNS: dict[str, dict[str, Any]] = {}
app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")


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
    return {"run_id": run_id, "dashboard_url": f"/dashboard/{run_id}"}


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
                yield {"event": event["event"], "data": json.dumps(event)}
            if run["status"] == "running":
                run["status"] = "completed"
        except Exception as exc:
            run["status"] = "failed"
            event = {"event": "error", "run_id": run_id, "message": str(exc)}
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
    run["state"].approved = True
    run["status"] = "queued"
    return JSONResponse({"status": "approved", "run_id": run_id})


@app.get("/api/run/{run_id}")
async def run_status(run_id: str) -> dict[str, Any]:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": run_id,
        "task": run["state"].task,
        "status": run["status"],
        "pending_action": run["state"].pending_action,
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

    event = {
        "timestamp": str(payload.get("timestamp") or datetime.now(timezone.utc).isoformat())[:64],
        "syscall": syscall,
        "pid": pid,
        "result": result,
        "duration_ns": duration_ns,
    }
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
    events = run["events"] + [
        {"event": "syscall", **item} for item in run["syscalls"]
    ]
    nodes = [
        {
            "id": f"{run_id}:{index}",
            "type": event.get("event", "event"),
            "label": (
                event.get("tool")
                or event.get("syscall")
                or event.get("plan", {}).get("tool")
                or event.get("event")
            ),
            "timestamp": event.get("timestamp"),
            "pid": event.get("pid"),
            "result": event.get("result"),
        }
        for index, event in enumerate(events)
    ]
    edges = [
        {"from": nodes[index - 1]["id"], "to": node["id"], "tool": node["label"]}
        for index, node in enumerate(nodes) if index
    ]
    return {"nodes": nodes, "edges": edges}


@app.get("/dashboard/{run_id}", response_class=HTMLResponse)
async def dashboard(run_id: str) -> HTMLResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="run not found")
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Run {run_id}</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 2rem; max-width: 1100px; }}
    section {{ border: 1px solid #8885; border-radius: 8px; margin: 1rem 0; padding: 1rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #8885; padding: .5rem; text-align: left; }}
    #status {{ font-weight: 700; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
  </style>
  <script>window.RUN_ID = {json.dumps(run_id)};</script>
  <script src="/static/dashboard.js" defer></script>
</head>
<body>
  <h1>Harness run</h1>
  <p>Run ID: <code>{run_id}</code> · Status: <span id="status">loading</span></p>
  <p id="task"></p>
  <button id="approve" hidden>Approve pending action</button>
  <section><h2>Execution trace</h2><ol id="trace"></ol></section>
  <section><h2>Syscall events</h2><table><thead><tr><th>Time</th><th>PID</th><th>Syscall</th><th>Result</th><th>Duration (ns)</th></tr></thead><tbody id="syscalls"></tbody></table></section>
  <section><h2>Pending action / error</h2><pre id="details">None</pre></section>
</body>
</html>"""
    return HTMLResponse(page)


@app.get("/ui/tools", response_class=HTMLResponse)
async def tools_fragment() -> str:
    return (TEMPLATES / "_tool_toggles.html").read_text(encoding="utf-8")


@app.post("/ui/tools", response_class=HTMLResponse)
async def update_tools() -> str:
    return (TEMPLATES / "_tool_toggles.html").read_text(encoding="utf-8")


@app.get("/ui/dataset", response_class=HTMLResponse)
async def dataset_fragment() -> str:
    return (TEMPLATES / "_dataset_table.html").read_text(encoding="utf-8")
