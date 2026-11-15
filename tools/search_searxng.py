"""SearXNG search adapter."""
from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import urlopen

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(func):  # type: ignore[no-untyped-def]
        return func


@tool
def web_search(query: str) -> dict:
    """Query the configured local SearXNG instance."""
    base_url = os.environ.get("SEARXNG_URL", "http://localhost:8080").rstrip("/")
    url = f"{base_url}/search?{urlencode({'q': query, 'format': 'json'})}"
    try:
        with urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"SearXNG request failed: {exc}") from exc
