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
import inspect

from .dataset_runner import generate_dataset
from tools.browser_drission import browser_fetch, browser_act, browser_run_js
from tools.ocr import ocr_document
from tools.pdf_ocr import ocr_pdf_document
from tools.search_searxng import web_search


async def caller(plan: dict[str, Any]) -> Any:
    fn = TOOL_REGISTRY.get(plan["tool"])
    if fn is None:
        raise RuntimeError(f"Unknown planned tool: {plan['tool']}")

    ainvoke = getattr(fn, "ainvoke", None)
    if callable(ainvoke):
        # Support LangChain tools without making langchain-core mandatory.
        return await ainvoke(plan["input"])
    if inspect.iscoroutinefunction(fn):
        # Native async function
        return await fn(plan["input"])
    if callable(fn):
        # Synchronous blocking function offloaded to a thread
        return await asyncio.to_thread(fn, plan["input"])

    raise TypeError(f"Tool '{plan['tool']}' is not callable")

@dataclass
class HarnessState:
    task: str
    context: dict[str, Any] = field(default_factory=dict)
    pending_action: dict[str, Any] | None = None
    approved: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)
    model_config: dict[str, Any] = field(default_factory=dict)


TOOL_REQUIRES_HITL = {
    "build_dataset": True,
    "browser_fetch": True,
    "web_search": True,
    "browser_act": True,
    "browser_run_js": True,
}
TOOL_REGISTRY = {
    "build_dataset": generate_dataset,
    "ocr_document": ocr_document,
    "ocr_pdf_document": ocr_pdf_document,
    "browser_fetch": browser_fetch,
    "web_search": web_search,
    "browser_act": browser_act,
    "browser_run_js": browser_run_js,
}


def _plan(state: HarnessState) -> dict[str, Any]:
    """Choose a tool from explicit task hints; no fixed multi-step sequence."""
    lowered = state.task.lower()
    if any(word in lowered for word in ("dataset", "report pipeline", "process reports")):
        tool_name = "build_dataset"
        tool_input = state.context.get("dataset_options", {})
    elif "search" in lowered:
        tool_name = "web_search"
        tool_input = state.context.get("input") or state.task
    elif "browser" in lowered or "url" in lowered:
        tool_name = "browser_fetch"
        tool_input = state.context.get("input") or state.task
    elif any(word in lowered for word in ("ocr", "image", "document")):
        tool_input = state.context.get("input") or state.task
        pdf_path = tool_input.get("pdf_path", "") if isinstance(tool_input, dict) else str(tool_input)
        tool_name = (
            "ocr_pdf_document"
            if str(pdf_path).lower().split("?", 1)[0].endswith(".pdf")
            else "ocr_document"
        )
    else:
        raise ValueError("Task does not select a supported harness tool")
    return {"tool": tool_name, "input": tool_input}


async def run_graph(state: HarnessState, *, run_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
    run_id = run_id or uuid.uuid4().hex
    plan = _plan(state)
    state.trace.append({"id": "planner", "type": "planner", "label": plan["tool"]})
    yield {"event": "planner", "run_id": run_id, "plan": plan}
    await asyncio.sleep(0)

    if TOOL_REQUIRES_HITL.get(plan["tool"], False) and not state.approved:
        state.pending_action = {
            "tool": plan["tool"],
            "input": plan["input"],
            "url": plan["input"] if plan["tool"].startswith("browser_") else None,
            "size_estimate": None,
        }
        yield {"event": "hitl_request", "run_id": run_id, **state.pending_action}
        return

    state.pending_action = None
    result = await caller(plan)

    state.trace.append({"id": "executor", "type": "executor", "label": plan["tool"], "tool": plan["tool"]})
    yield {"event": "executor", "run_id": run_id, "tool": plan["tool"], "result": result}
    state.trace.append({"id": "reflector", "type": "reflector", "label": "complete"})
    yield {"event": "reflector", "run_id": run_id, "note": "Tool execution completed"}
