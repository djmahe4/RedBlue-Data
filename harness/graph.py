"""Small adaptive harness graph with explicit HITL interrupts.

The graph exposes an async event stream compatible with the FastAPI SSE layer.
If LangGraph is installed, callers can replace this adapter with a compiled
graph without changing the state or event contracts.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from tools.browser_drission import browser_fetch
from tools.ocr_nemotron import ocr_document
from tools.search_searxng import web_search


@dataclass
class HarnessState:
    task: str
    context: dict[str, Any] = field(default_factory=dict)
    pending_action: dict[str, Any] | None = None
    approved: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)
    model_config: dict[str, Any] = field(default_factory=dict)


TOOL_REQUIRES_HITL = {"browser_fetch": True, "web_search": True, "run_python": True}
TOOL_REGISTRY = {"ocr_document": ocr_document, "browser_fetch": browser_fetch, "web_search": web_search}


def _plan(state: HarnessState) -> dict[str, Any]:
    """Choose a tool from explicit task hints; no fixed multi-step sequence."""
    lowered = state.task.lower()
    if "search" in lowered:
        tool_name = "web_search"
    elif "browser" in lowered or "url" in lowered:
        tool_name = "browser_fetch"
    else:
        tool_name = "ocr_document"
    return {"tool": tool_name, "input": state.context.get("input") or state.task}


async def run_graph(state: HarnessState, *, run_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
    run_id = run_id or uuid.uuid4().hex
    plan = _plan(state)
    state.trace.append({"id": "planner", "type": "planner", "label": plan["tool"]})
    yield {"event": "planner", "run_id": run_id, "plan": plan}
    await asyncio.sleep(0)

    if TOOL_REQUIRES_HITL.get(plan["tool"], False) and not state.approved:
        state.pending_action = {"tool": plan["tool"], "url": plan["input"], "size_estimate": None}
        yield {"event": "hitl_request", "run_id": run_id, **state.pending_action}
        return

    fn = TOOL_REGISTRY.get(plan["tool"])
    if fn is None:
        raise RuntimeError(f"Unknown planned tool: {plan['tool']}")
    result = fn(plan["input"])
    state.trace.append({"id": "executor", "type": "executor", "label": plan["tool"], "tool": plan["tool"]})
    yield {"event": "executor", "run_id": run_id, "tool": plan["tool"], "result": result}
    state.trace.append({"id": "reflector", "type": "reflector", "label": "complete"})
    yield {"event": "reflector", "run_id": run_id, "note": "Tool execution completed"}
