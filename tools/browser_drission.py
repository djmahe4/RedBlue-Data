"""Browser fetch adapter. External navigation is always HITL-gated."""
from __future__ import annotations

from typing import Any

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(func):  # type: ignore[no-untyped-def]
        return func


@tool
def browser_fetch(url: str) -> dict[str, Any]:
    """Fetch rendered page text through a local Chromium CDP session."""
    try:
        from DrissionPage import ChromiumPage
    except ImportError as exc:
        raise RuntimeError("DrissionPage is required for browser_fetch") from exc

    page = ChromiumPage()
    try:
        page.get(url)
        return {"url": url, "title": page.title, "text": page.html}
    finally:
        page.quit()
