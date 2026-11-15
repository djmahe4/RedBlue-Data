import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness import graph
from harness.dataset_runner import generate_dataset
from tools.browser_drission import Browser
import tools.browser_drission as browser_module


def test_browser_eval_js_forwards_timeout():
    browser = Browser()
    calls = []
    browser._tab = SimpleNamespace(run_js=lambda *args, **kwargs: calls.append(kwargs) or "ok")

    assert browser.eval_js("1", timeout=3) == "ok"
    assert calls == [{"as_expr": False, "args": None, "timeout": 3}]


def test_optional_browser_dependency_reports_clear_error(monkeypatch):
    monkeypatch.setattr(browser_module, "_DRISSION_IMPORT_ERROR", ImportError("missing"))
    with pytest.raises(RuntimeError, match="optional DrissionPage dependency"):
        Browser().__enter__()


def test_dataset_request_pauses_for_approval():
    state = graph.HarnessState(
        task="generate dataset",
        context={"dataset_options": {"max_reports": 2}},
    )

    async def collect():
        return [event async for event in graph.run_graph(state)]

    events = asyncio.run(collect())
    assert events[0]["plan"]["tool"] == "build_dataset"
    assert events[1]["event"] == "hitl_request"
    assert events[1]["input"] == {"max_reports": 2}


def test_approved_dataset_runs_through_harness(monkeypatch):
    state = graph.HarnessState(task="generate dataset", approved=True)
    monkeypatch.setitem(graph.TOOL_REGISTRY, "build_dataset", lambda options: {"options": options})

    async def collect():
        return [event async for event in graph.run_graph(state)]

    events = asyncio.run(collect())
    planner = next(event for event in events if event["event"] == "planner")
    executor = next(event for event in events if event["event"] == "executor")
    reflector = next(event for event in events if event["event"] == "reflector")
    assert executor["result"] == {"options": {}}
    assert planner["trace_id"] == executor["trace_id"] == reflector["trace_id"]
    assert executor["parent_span_id"] == planner["span_id"]
    assert reflector["parent_span_id"] == executor["span_id"]
    assert executor["duration_ns"] >= 0
    assert executor["attributes"]["tool.name"] == "build_dataset"


def test_tool_failure_emits_error_span_with_exception_attributes(monkeypatch):
    def fail_ocr(**kwargs):
        raise RuntimeError("OCR backend unavailable")

    monkeypatch.setitem(graph.TOOL_REGISTRY, "ocr_document", fail_ocr)
    state = graph.HarnessState(
        task="ocr image",
        context={"input": {"image_path": "scan.png"}},
    )

    async def collect():
        return [event async for event in graph.run_graph(state)]

    events = asyncio.run(collect())
    planner = next(event for event in events if event["event"] == "planner")
    error = events[-1]
    assert error["event"] == "error"
    assert error["name"] == "tool.ocr_document"
    assert error["status"] == "ERROR"
    assert error["parent_span_id"] == planner["span_id"]
    assert error["attributes"]["exception.type"] == "RuntimeError"
    assert error["attributes"]["exception.message"] == "OCR backend unavailable"


def test_generate_dataset_uses_workspace_process_not_docker(tmp_path, monkeypatch):
    monkeypatch.setenv("REDBLUE_WORKSPACE", str(tmp_path))
    completed = SimpleNamespace(returncode=0, stdout="done", stderr="")
    with patch("harness.dataset_runner.subprocess.run", return_value=completed) as run:
        result = generate_dataset({"max_reports": 3, "output_dir": "output", "skip_ocr": False})

    command = run.call_args.args[0]
    assert "docker" not in command
    assert "--max_reports" in command
    assert run.call_args.kwargs["cwd"] == tmp_path
    assert run.call_args.kwargs["env"]["SKIP_OCR"] == "false"
    assert result["returncode"] == 0


def test_generate_dataset_rejects_output_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("REDBLUE_WORKSPACE", str(tmp_path))
    with pytest.raises(ValueError, match="inside the configured workspace"):
        generate_dataset({"output_dir": "../outside"})


def test_browser_navigation_requires_approval():
    state = graph.HarnessState(task="browser https://example.test")

    async def collect():
        return [event async for event in graph.run_graph(state)]

    events = asyncio.run(collect())
    assert events[-1]["event"] == "hitl_request"
    assert events[-1]["tool"] == "browser_fetch"


def test_ollama_plan_is_approved_then_replayed_without_replanning(monkeypatch):
    monkeypatch.setenv("HARNESS_PLANNER", "ollama")
    selections = []

    def choose_tool(task, context, tools):
        selections.append((task, context, tools))
        return "browser_fetch"

    monkeypatch.setattr(graph, "select_tool", choose_tool)
    state = graph.HarnessState(
        task="inspect this site",
        context={"input": {"url": "https://example.test"}},
    )

    async def collect():
        return [event async for event in graph.run_graph(state)]

    first_events = asyncio.run(collect())
    assert first_events[-1]["event"] == "hitl_request"
    assert first_events[-1]["planner"] == "ollama"
    assert first_events[0]["trace_id"] == first_events[-1]["trace_id"]
    assert first_events[-1]["parent_span_id"] == first_events[0]["span_id"]
    assert first_events[-1]["status"] == "UNSET"
    approved_input = first_events[-1]["input"]
    state.approved = True
    calls = []
    monkeypatch.setitem(
        graph.TOOL_REGISTRY,
        "browser_fetch",
        lambda url: calls.append(url) or {"url": url},
    )
    monkeypatch.setattr(graph, "select_tool", lambda *args: pytest.fail("replanned after approval"))

    second_events = asyncio.run(collect())
    assert not any(event["event"] == "hitl_request" for event in second_events)
    assert second_events[0]["plan"]["input"] == approved_input
    assert second_events[0]["attributes"]["plan.replayed"] is True
    executor = next(event for event in second_events if event["event"] == "executor")
    assert executor["parent_span_id"] == second_events[0]["span_id"]
    assert calls == ["https://example.test"]
    assert len(selections) == 1


def test_caller_passes_structured_input_as_keyword_arguments(monkeypatch):
    received = {}

    def fake_browser_act(url, locator, action):
        received.update(url=url, locator=locator, action=action)
        return {"ok": True}

    monkeypatch.setitem(graph.TOOL_REGISTRY, "browser_act", fake_browser_act)
    result = asyncio.run(graph.caller({
        "tool": "browser_act",
        "input": {"url": "https://example.test", "locator": "#confirm", "action": "click"},
    }))

    assert result == {"ok": True}
    assert received == {"url": "https://example.test", "locator": "#confirm", "action": "click"}


def test_sandbox_does_not_create_workspace_root_on_import(tmp_path, monkeypatch):
    root = tmp_path / "not-created"
    monkeypatch.setenv("REDBLUE_WORKSPACES_ROOT", str(root))
    import harness.sandbox as sandbox
    importlib.reload(sandbox)
    assert not root.exists()
    with pytest.raises(PermissionError, match="HITL approval"):
        sandbox.run_sandbox("echo no", approved=False)
