from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from harness.graph import HarnessState, run_graph

app = FastAPI(title="RedBlue-Data Harness")
TEMPLATES = Path(__file__).parent.parent / "templates"
RUNS: dict[str, dict[str, Any]] = {}


@app.post("/api/run/start")
async def start_run(payload: dict[str, Any]) -> dict[str, str]:
    run_id = uuid.uuid4().hex
    RUNS[run_id] = {"state": HarnessState(task=str(payload.get("task", "")), context=payload), "events": []}
    return {"run_id": run_id}


@app.get("/api/run/{run_id}/stream")
async def stream_run(run_id: str) -> EventSourceResponse:
    if run_id not in RUNS:
        return EventSourceResponse(iter([{"event": "error", "data": "run not found"}]))

    async def events():
        run = RUNS[run_id]
        async for event in run_graph(run["state"], run_id=run_id):
            run["events"].append(event)
            yield {"event": event["event"], "data": json.dumps(event)}

    return EventSourceResponse(events())


@app.post("/api/run/{run_id}/approve")
async def approve_run(run_id: str) -> JSONResponse:
    if run_id not in RUNS:
        return JSONResponse({"error": "run not found"}, status_code=404)
    RUNS[run_id]["state"].approved = True
    return JSONResponse({"status": "approved", "run_id": run_id})


@app.patch("/api/config/tools")
async def configure_tools(payload: dict[str, Any]) -> dict[str, Any]:
    return {"tools": payload}


@app.patch("/api/config/model")
async def configure_model(payload: dict[str, Any]) -> dict[str, Any]:
    return {"model": payload}


@app.get("/r3f/trace/{run_id}")
async def trace(run_id: str) -> dict[str, list[dict[str, Any]]]:
    events = RUNS.get(run_id, {}).get("events", [])
    nodes = [{"id": event.get("event"), "type": event.get("event"), "label": event.get("event")} for event in events]
    edges = [{"from": nodes[index - 1]["id"], "to": node["id"], "tool": node.get("label")} for index, node in enumerate(nodes) if index]
    return {"nodes": nodes, "edges": edges}


@app.get("/ui/tools", response_class=HTMLResponse)
async def tools_fragment() -> str:
    return (TEMPLATES / "_tool_toggles.html").read_text(encoding="utf-8")


@app.post("/ui/tools", response_class=HTMLResponse)
async def update_tools() -> str:
    return (TEMPLATES / "_tool_toggles.html").read_text(encoding="utf-8")


@app.get("/ui/dataset", response_class=HTMLResponse)
async def dataset_fragment() -> str:
    return (TEMPLATES / "_dataset_table.html").read_text(encoding="utf-8")
