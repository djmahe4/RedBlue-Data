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
    executor = next(event for event in events if event["event"] == "executor")
    assert executor["result"] == {"options": {}}


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


def test_sandbox_does_not_create_workspace_root_on_import(tmp_path, monkeypatch):
    root = tmp_path / "not-created"
    monkeypatch.setenv("REDBLUE_WORKSPACES_ROOT", str(root))
    import harness.sandbox as sandbox
    importlib.reload(sandbox)
    assert not root.exists()
    with pytest.raises(PermissionError, match="HITL approval"):
        sandbox.run_sandbox("echo no", approved=False)
