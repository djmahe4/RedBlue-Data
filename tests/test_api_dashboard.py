import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import RUNS, app


def test_dashboard_and_authenticated_syscall_trace(monkeypatch):
    monkeypatch.setenv("REDBLUE_TRACE_TOKEN", "test-secret")
    with TestClient(app) as client:
        started = client.post("/api/run/start", json={"task": "generate dataset"})
        assert started.status_code == 200
        run_id = started.json()["run_id"]
        assert started.json()["dashboard_url"] == f"/dashboard/{run_id}"

        page = client.get(started.json()["dashboard_url"])
        assert page.status_code == 200
        assert "Syscall events" in page.text

        event = {
            "timestamp": "2026-11-15T12:00:00Z",
            "syscall": "openat",
            "pid": 123,
            "result": 0,
            "duration_ns": 1200,
        }
        assert client.post(f"/api/run/{run_id}/syscalls", json=event).status_code == 401
        response = client.post(
            f"/api/run/{run_id}/syscalls",
            json=event,
            headers={"X-Trace-Token": "test-secret"},
        )
        assert response.status_code == 200
        trace = client.get(f"/r3f/trace/{run_id}").json()
        assert trace["nodes"][-1]["label"] == "openat"
        assert client.get(f"/api/run/{run_id}/syscalls").json()["syscalls"] == [event]

        RUNS.pop(run_id, None)


def test_run_stream_is_single_use_unless_approval_requeues_it():
    with TestClient(app) as client:
        started = client.post("/api/run/start", json={"task": "unmatched task"})
        run_id = started.json()["run_id"]
        response = client.get(f"/api/run/{run_id}/stream")
        assert response.status_code == 200
        assert "Task does not select a supported harness tool" in response.text
        assert client.get(f"/api/run/{run_id}/stream").status_code == 409
        RUNS.pop(run_id, None)
