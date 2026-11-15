import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import RUNS, app
from harness import graph


def test_homepage_starts_runs_and_links_to_dashboard(monkeypatch):
    monkeypatch.setenv("HARNESS_PLANNER", "ollama")
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Start a run" in home.text
        assert 'window.PLANNER_MODE = "ollama"' in home.text
        assert client.get("/static/home.js").status_code == 200
        assert client.get("/static/app.css").status_code == 200

        response = client.post(
            "/api/run/start",
            json={"task": "generate dataset", "dataset_options": {"max_reports": 2}},
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        dashboard = client.get(response.json()["dashboard_url"])
        assert dashboard.status_code == 200
        assert "Execution trace" in dashboard.text
        RUNS.pop(run_id, None)


def test_dashboard_and_authenticated_syscall_trace(monkeypatch):
    monkeypatch.setenv("REDBLUE_TRACE_TOKEN", "test-secret")
    with TestClient(app) as client:
        started = client.post("/api/run/start", json={"task": "generate dataset"})
        assert started.status_code == 200
        run_id = started.json()["run_id"]
        assert started.json()["trace_id"] == run_id
        assert started.json()["dashboard_url"] == f"/dashboard/{run_id}"

        page = client.get(started.json()["dashboard_url"])
        assert page.status_code == 200
        assert "Syscall events" in page.text
        assert client.get(f"/api/run/{run_id}/stream").status_code == 200
        initial_trace = client.get(f"/r3f/trace/{run_id}").json()
        hitl = next(node for node in initial_trace["nodes"] if node["type"] == "hitl_request")

        event = {
            "timestamp": "2026-11-15T12:00:00Z",
            "syscall": "openat",
            "pid": 123,
            "result": 0,
            "duration_ns": 1200,
            "parent_span_id": hitl["span_id"],
        }
        assert client.post(f"/api/run/{run_id}/syscalls", json=event).status_code == 401
        invalid_timestamp = client.post(
            f"/api/run/{run_id}/syscalls",
            json={**event, "timestamp": "not-an-iso-timestamp"},
            headers={"X-Trace-Token": "test-secret"},
        )
        assert invalid_timestamp.status_code == 422
        response = client.post(
            f"/api/run/{run_id}/syscalls",
            json=event,
            headers={"X-Trace-Token": "test-secret"},
        )
        assert response.status_code == 200
        trace = client.get(f"/r3f/trace/{run_id}").json()
        syscall = next(node for node in trace["nodes"] if node["type"] == "syscall")
        assert syscall["label"] == "openat"
        assert syscall["trace_id"] == run_id
        assert syscall["duration_ns"] == 1200
        assert syscall["parent_span_id"] == hitl["span_id"]
        assert {"from": hitl["span_id"], "to": syscall["span_id"], "relationship": "parent"} in trace["edges"]
        assert client.get(f"/api/run/{run_id}/syscalls").json()["syscalls"][0]["syscall"] == "openat"

        assert client.post(f"/api/run/{run_id}/approve").status_code == 200
        monkeypatch.setitem(graph.TOOL_REGISTRY, "build_dataset", lambda options: {"ok": True})
        resumed = client.get(f"/api/run/{run_id}/stream")
        assert resumed.status_code == 200
        assert client.get(f"/api/run/{run_id}").json()["status"] == "completed"

        trace = client.get(f"/r3f/trace/{run_id}").json()
        approval = next(node for node in trace["nodes"] if node["type"] == "approval")
        replay = next(
            node for node in trace["nodes"]
            if node["type"] == "planner" and node["attributes"].get("plan.replayed")
        )
        executor = next(node for node in trace["nodes"] if node["type"] == "executor")
        reflector = next(node for node in trace["nodes"] if node["type"] == "reflector")
        assert approval["parent_span_id"] == hitl["span_id"]
        assert replay["parent_span_id"] == approval["span_id"]
        assert executor["parent_span_id"] == replay["span_id"]
        assert reflector["parent_span_id"] == executor["span_id"]

        RUNS.pop(run_id, None)


def test_run_stream_is_single_use_unless_approval_requeues_it():
    with TestClient(app) as client:
        started = client.post("/api/run/start", json={"task": "unmatched task"})
        run_id = started.json()["run_id"]
        response = client.get(f"/api/run/{run_id}/stream")
        assert response.status_code == 200
        assert "Task does not select a supported harness tool" in response.text
        assert client.get(f"/api/run/{run_id}").json()["status"] == "failed"
        trace = client.get(f"/r3f/trace/{run_id}").json()
        assert trace["nodes"][0]["status"] == "ERROR"
        assert client.get(f"/api/run/{run_id}/stream").status_code == 409
        RUNS.pop(run_id, None)
