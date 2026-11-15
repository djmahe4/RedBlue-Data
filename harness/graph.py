"""Small adaptive harness graph with explicit HITL interrupts.

The graph exposes an async event stream compatible with the FastAPI SSE layer.
If LangGraph is installed, callers can replace this adapter with a compiled
graph without changing the state or event contracts.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, cast

from .dataset_runner import generate_dataset
from .telemetry import make_span
from harness.planner import select_tool
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
    if not callable(fn):
        raise TypeError(f"Tool '{plan['tool']}' is not callable")
    callable_fn = cast(Callable[..., Any], fn)
    tool_input = plan["input"]
    if plan["tool"] == "build_dataset":
        return await asyncio.to_thread(callable_fn, tool_input)
    if isinstance(tool_input, dict):
        if inspect.iscoroutinefunction(callable_fn):
            return await callable_fn(**tool_input)
        return await asyncio.to_thread(callable_fn, **tool_input)
    if inspect.iscoroutinefunction(callable_fn):
        return await callable_fn(tool_input)
    return await asyncio.to_thread(callable_fn, tool_input)

@dataclass
class HarnessState:
    task: str
    context: dict[str, Any] = field(default_factory=dict)
    pending_action: dict[str, Any] | None = None
    approved: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)
    trace_context: dict[str, str] = field(default_factory=dict)
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


TOOL_DESCRIPTIONS = {
    "build_dataset": "Process reports in the configured workspace into datasets.",
    "ocr_document": "Extract text from a user-provided local image.",
    "ocr_pdf_document": "Extract PDF text and inspect visual regions.",
    "browser_fetch": "Fetch a user-provided URL; requires user approval.",
    "web_search": "Search the configured SearXNG instance; requires user approval.",
    "browser_act": "Act on a user-provided page and locator; requires approval.",
    "browser_run_js": "Run user-provided JavaScript on a page; requires approval.",
}


def _rule_plan(state: HarnessState) -> dict[str, Any]:
    """Keep deterministic routing available when model planning is disabled."""
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
    return {"tool": tool_name, "input": tool_input, "planner": "rules"}


def _tool_input(state: HarnessState, tool_name: str) -> Any:
    if tool_name == "build_dataset":
        return state.context.get("dataset_options", {})
    user_input = state.context.get("input")
    if tool_name == "web_search":
        if isinstance(user_input, dict) and "query" in user_input:
            return {"query": user_input["query"]}
        return {"query": user_input or state.task}
    if tool_name == "browser_fetch":
        if isinstance(user_input, dict):
            if "url" not in user_input:
                raise ValueError("browser_fetch input requires a url")
            return {key: user_input[key] for key in ("url", "max_scroll", "capture") if key in user_input}
        return {"url": user_input or state.task}
    if tool_name == "ocr_document":
        if isinstance(user_input, dict):
            if "image_path" in user_input:
                return {"image_path": user_input["image_path"]}
            if "path" in user_input:
                return {"image_path": user_input["path"]}
        elif isinstance(user_input, str):
            return {"image_path": user_input}
        raise ValueError("ocr_document requires an image_path")
    if tool_name == "ocr_pdf_document":
        if isinstance(user_input, dict):
            if "pdf_path" not in user_input and "path" in user_input:
                user_input = {**user_input, "pdf_path": user_input["path"]}
            if "pdf_path" not in user_input:
                raise ValueError("ocr_pdf_document requires a pdf_path")
            return {key: user_input[key] for key in ("pdf_path", "page_number") if key in user_input}
        if isinstance(user_input, str):
            return {"pdf_path": user_input}
        raise ValueError("ocr_pdf_document requires a pdf_path")
    if tool_name in {"browser_act", "browser_run_js"}:
        if not isinstance(user_input, dict):
            raise ValueError(f"{tool_name} requires structured input")
        required = {"url", "locator", "action"} if tool_name == "browser_act" else {"url", "script"}
        if not required.issubset(user_input):
            missing = ", ".join(sorted(required - user_input.keys()))
            raise ValueError(f"{tool_name} input missing required fields: {missing}")
        allowed = required | ({"value"} if tool_name == "browser_act" else {"as_expr"})
        return {key: user_input[key] for key in allowed if key in user_input}
    raise ValueError(f"No input adapter for tool: {tool_name}")


async def _plan(state: HarnessState) -> dict[str, Any]:
    planner = os.environ.get("HARNESS_PLANNER", "rules").strip().lower()
    if planner == "rules":
        return _rule_plan(state)
    if planner != "ollama":
        raise ValueError("HARNESS_PLANNER must be 'rules' or 'ollama'")

    available_tools = dict(TOOL_DESCRIPTIONS)
    user_input = state.context.get("input")
    if not isinstance(user_input, dict) or not {"url", "locator", "action"}.issubset(user_input):
        available_tools.pop("browser_act")
    if not isinstance(user_input, dict) or not {"url", "script"}.issubset(user_input):
        available_tools.pop("browser_run_js")
    tool_name = await asyncio.to_thread(select_tool, state.task, state.context, available_tools)
    return {"tool": tool_name, "input": _tool_input(state, tool_name), "planner": "ollama"}


async def run_graph(state: HarnessState, *, run_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
    run_id = run_id or uuid.uuid4().hex
    replaying = state.approved and state.pending_action is not None
    if replaying:
        pending = state.pending_action
        plan = {
            "tool": pending["tool"],
            "input": pending["input"],
            "planner": pending.get("planner", "rules"),
        }
        plan_parent = state.trace_context.get("approval_span_id") or state.trace_context.get("hitl_span_id")
        plan_event = make_span(
            "planner",
            run_id,
            name="harness.plan.replay",
            parent_span_id=plan_parent,
            attributes={
                "planner.name": plan["planner"],
                "tool.name": plan["tool"],
                "plan.replayed": True,
            },
            payload={"plan": plan},
        )
    else:
        plan_started_at = time.time_ns()
        plan_started_clock = time.perf_counter_ns()
        try:
            plan = await _plan(state)
        except Exception as exc:  # noqa: BLE001
            error_event = make_span(
                "error",
                run_id,
                name="harness.plan",
                status="ERROR",
                start_time_unix_nano=plan_started_at,
                duration_ns=time.perf_counter_ns() - plan_started_clock,
                attributes={
                    "exception.type": type(exc).__name__,
                    "exception.message": str(exc),
                },
                payload={"message": str(exc)},
            )
            state.trace.append(error_event)
            yield error_event
            return
        plan_event = make_span(
            "planner",
            run_id,
            name="harness.plan",
            start_time_unix_nano=plan_started_at,
            duration_ns=time.perf_counter_ns() - plan_started_clock,
            attributes={
                "planner.name": plan["planner"],
                "tool.name": plan["tool"],
                "tool.requires_approval": TOOL_REQUIRES_HITL.get(plan["tool"], False),
                "plan.replayed": False,
            },
            payload={"plan": plan},
        )

    state.trace.append(plan_event)
    state.trace_context["planner_span_id"] = plan_event["span_id"]
    yield plan_event
    await asyncio.sleep(0)

    if TOOL_REQUIRES_HITL.get(plan["tool"], False) and not state.approved:
        state.pending_action = {
            "tool": plan["tool"],
            "input": plan["input"],
            "planner": plan.get("planner", "rules"),
            "url": plan["input"] if plan["tool"].startswith("browser_") else None,
            "size_estimate": None,
        }
        approval_event = make_span(
            "hitl_request",
            run_id,
            name="harness.approval.request",
            parent_span_id=plan_event["span_id"],
            status="UNSET",
            attributes={
                "approval.required": True,
                "approval.state": "pending",
                "tool.name": plan["tool"],
            },
            payload=state.pending_action,
        )
        state.trace_context["hitl_span_id"] = approval_event["span_id"]
        state.trace.append(approval_event)
        yield approval_event
        return

    state.pending_action = None
    state.approved = False
    execution_started_at = time.time_ns()
    execution_started_clock = time.perf_counter_ns()
    try:
        result = await caller(plan)
    except Exception as exc:  # noqa: BLE001
        error_event = make_span(
            "error",
            run_id,
            name=f"tool.{plan['tool']}",
            parent_span_id=plan_event["span_id"],
            status="ERROR",
            start_time_unix_nano=execution_started_at,
            duration_ns=time.perf_counter_ns() - execution_started_clock,
            attributes={
                "tool.name": plan["tool"],
                "exception.type": type(exc).__name__,
                "exception.message": str(exc),
            },
            payload={"tool": plan["tool"], "message": str(exc)},
        )
        state.trace.append(error_event)
        yield error_event
        return

    executor_event = make_span(
        "executor",
        run_id,
        name=f"tool.{plan['tool']}",
        parent_span_id=plan_event["span_id"],
        start_time_unix_nano=execution_started_at,
        duration_ns=time.perf_counter_ns() - execution_started_clock,
        attributes={
            "tool.name": plan["tool"],
            "tool.result_type": type(result).__name__,
        },
        payload={"tool": plan["tool"], "result": result},
    )
    state.trace.append(executor_event)
    yield executor_event
    reflector_event = make_span(
        "reflector",
        run_id,
        name="harness.reflect",
        parent_span_id=executor_event["span_id"],
        attributes={"harness.outcome": "completed"},
        payload={"note": "Tool execution completed"},
    )
    state.trace.append(reflector_event)
    yield reflector_event
