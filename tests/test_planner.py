import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.planner import select_tool


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps({"message": {"content": self.content}}).encode()


def test_select_tool_uses_local_ollama_and_validates_allowlist(monkeypatch):
    monkeypatch.setenv("PLANNER_MODEL", "local-planner")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.local/")
    tools = {"web_search": "Search user query", "build_dataset": "Process local reports"}
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        body = json.loads(request.data)
        assert body["model"] == "local-planner"
        assert body["format"] == "json"
        assert body["options"]["temperature"] == 0
        return FakeResponse('{"tool":"web_search"}')

    with patch("harness.planner.urlopen", side_effect=fake_urlopen):
        selected = select_tool("search this", {"input": "example query"}, tools)

    assert selected == "web_search"
    assert requests[0][0].full_url == "http://ollama.local/api/chat"
    assert requests[0][1] == 30


def test_select_tool_rejects_tool_outside_allowlist(monkeypatch):
    monkeypatch.setenv("PLANNER_MODEL", "local-planner")
    with patch("harness.planner.urlopen", return_value=FakeResponse('{"tool":"run_code"}')):
        with pytest.raises(ValueError, match="outside the allowlist"):
            select_tool("run code", {}, {"web_search": "Search user query"})
