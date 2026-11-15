"""Browser agent for agentic browsing with HITL gating."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(func):  # type: ignore[no-untyped-def]
        return func

from DrissionPage import Chromium, ChromiumOptions
from DrissionPage.items import ChromiumElement, NoneElement, MixTab, ChromiumTab
from DrissionPage.errors import PageDisconnectedError, WaitTimeoutError
from typing import cast, Any


@dataclass
class Browser:
    """Reusable browser with navigation HITL gating."""

    url: str | None = None
    headless: bool = False
    page_load_timeout: float = 30.0
    listen_targets: set[str] | None = None          # e.g. {'api.example.com', '/ajax'}
    scroll_to_bottom: bool = False
    max_scrolls: int = 15
    auto_handle_alerts: bool = False
    _tab: Any = field(init=False, repr=False, default=None)
    _browser: Any = field(init=False, repr=False, default=None)

    def __enter__(self) -> "Browser":
        co = ChromiumOptions()
        co.headless(self.headless)
        co.set_load_mode("eager")
        co.set_timeouts(base=10, page_load=self.page_load_timeout)
        self._browser = Chromium(co)
        # latest_tab types as MixTab | str | None; force to the tab type.
        self._tab = cast(ChromiumTab, self._browser.latest_tab)
        if self.auto_handle_alerts:
            self._tab.set.auto_handle_alert(True)     # ✓ now resolves
        return self

    def __exit__(self, *exc) -> None:
        if self._browser:
            try:
                self._browser.quit()
            except Exception:
                pass

    # =====================================================================
    # Navigation (HITL-gated upstream)
    # =====================================================================
    def navigate(self, target: str) -> None:
        if self.listen_targets:
            self._tab.listen.start(*self.listen_targets)   # must start before get()
        try:
            self._tab.get(target)                          # cannot hang now
        finally:
            self.url = target

    def back(self) -> None:
        self._tab.back()

    def forward(self) -> None:
        self._tab.forward()

    # =====================================================================
    # Element location & action
    # =====================================================================
    def _as_element(self, ele) -> ChromiumElement | None:
        """Narrow ele() output to ChromiumElement or None (never str)."""
        if ele is None or isinstance(ele, (str, NoneElement)):
            return None
        return cast(ChromiumElement, ele)

    def find(self, locator: str, index: int = 1, timeout: float | None = None):
        """First matching element, or None. Locators: 'tag:xxx', '@attr=...',
        'css:...', 'xpath:...', 'text:...', or bare css/xpath/text auto-match."""
        return self._as_element(self._tab.ele(locator, index=index, timeout=timeout))

    def find_all(self, locator: str, timeout: float | None = None):
        return self._tab.eles(locator, timeout=timeout)

    def act(self, locator: str, action: str, value: str | None = None) -> dict:
        ele = self._as_element(self._tab.ele(locator, timeout=5))  # ChromiumElement | None
        if ele is None:
            return {"ok": False, "reason": "element not found", "locator": locator}
        try:
            if action == "click":
                ele.click()
            elif action == "right_click":
                ele.click.right()
            elif action == "input":
                ele.clear()
                ele.input(value)
            elif action == "set_value":
                if value is None:
                    return {"ok": False, "reason": "value required for set_value"}
                ele.set.value(value)
            elif action == "set_property":
                if value is None:
                    return {"ok": False, "reason": "value required for set_property"}
                ele.set.property("property", value)
            elif action == "hover":
                ele.hover()
            elif action == "clear":
                ele.clear()
            else:
                return {"ok": False, "reason": f"unknown action {action!r}"}
        except PageDisconnectedError as e:
            return {"ok": False, "reason": "page disconnected", "detail": str(e)}
        return {"ok": True, "locator": locator, "action": action}

    def eval_js(self, script: str, as_expr: bool = False, args=None,
                timeout: float | None = None) -> Any:
        """Run arbitrary JS in page context (expression if as_expr, else statements)."""
        return self._tab.run_js(script, as_expr=as_expr, args=args, timetout=timeout)

    def eval_element_js(self, locator: str, script: str, as_expr: bool = False) -> Any:
        """Run JS scoped to an element — `this` === the element."""
        ele = self._as_element(self._tab.ele(locator, timeout=5))
        if ele is None:
            return None
        return ele.run_js(script, as_expr=as_expr)

    def eval_js_loaded(self, script: str, timeout: float | None = None) -> Any:
        """Run JS only after the page is fully loaded."""
        return self._tab.run_js_loaded(script, timeout=timeout)

    def eval_async_js(self, script: str) -> Any:
        """Fire-and-forget async JS (does not wait)."""
        return self._tab.run_async_js(script)

    # =====================================================================
    # Scrolling & lazy content
    # =====================================================================
    def scroll(self, to_bottom: bool = True) -> None:
        """Force lazy content. Returns when height stops growing."""
        last_h = 0
        for _ in range(self.max_scrolls):
            self._tab.scroll.to_bottom()
            h = self._tab.run_js(
                "return document.scrollingElement.scrollHeight", as_expr=True
            )
            if h == last_h:
                break
            last_h = h

    def scroll_to(self, locator: str, center: bool = True) -> bool:
        ele = cast(ChromiumElement, self._as_element(self._tab.ele(locator, timeout=3)))
        if ele is None:
            return False
        ele.scroll.to_see(center=center if center else None)
        return True

    # =====================================================================
    # State: cookies + storage
    # =====================================================================
    def get_state(self) -> dict:
        return {
            "cookies": self._tab.cookies(),
            "local": self._tab.local_storage(),
            "session": self._tab.session_storage(),
        }

    def restore_state(self, cookies=None, local=None, session_=None) -> None:
        for c in cookies or []:
            self._tab.set.cookies(c)                    # dict/str/list/Cookie accepted
        for k, v in (local or {}).items():
            self._tab.set.local_storage(item=k, value=v)  # v=False deletes key
        for k, v in (session_ or {}).items():
            self._tab.set.session_storage(item=k, value=v)

    def get_cookie(self, name: str, all_info: bool = True):
        return self._tab.cookie(name, all_info=all_info)

    # =====================================================================
    # Network capture
    # =====================================================================
    def network_packets(self, timeout: float = 10) -> list[dict[str, Any]]:
        """Collect captured requests/responses after navigation."""
        if not self.listen_targets:
            return []
        try:
            packets = self._tab.listen.wait(           # fit_count=False -> return what we got
                count=3, timeout=timeout, fit_count=False
            )
        except (WaitTimeoutError, PageDisconnectedError):
            return []

        if not isinstance(packets, list):
            packets = [packets]
        return [
            {
                "method": p.method,
                "url": p.url,
                "status": getattr(p.response, "status", None),
                "res_type": p.resourceType,
                "data": p.data,                        # JSON-deserialized response body
                "failed": p.is_failed,
            }
            for p in packets
        ]

    # =====================================================================
    # Waiting (deterministic, no blind sleeps)
    # =====================================================================
    def wait_visible(self, locator: str, timeout: float | None = None) -> bool:
        return self._tab.wait.ele_displayed(locator, timeout=timeout)

    def wait_hidden(self, locator: str, timeout: float | None = None) -> bool:
        return self._tab.wait.ele_hidden(locator, timeout=timeout)

    def wait_exists(self, locator: str, timeout: float | None = None) -> bool:
        return self._tab.wait.ele_displayed(locator, timeout=timeout) or \
               bool(self._tab.ele(locator, timeout=timeout or 0.1))

    def wait_load_complete(self, timeout: float | None = None) -> bool:
        return bool(self._tab.wait.load_complete(timeout=timeout))

    def wait_doc_ready(self) -> bool:
        return bool(self._tab.wait.doc_loaded(timeout=self.page_load_timeout))

    # =====================================================================
    # Tab orchestration
    # =====================================================================
    def new_tab(self, target: str | None = None, background: bool = False) -> str:
        return self._browser.new_tab(url=target, background=background)

    def wait_new_tab(self, timeout: float = 5):
        return self._browser.wait.new_tab(timeout=timeout)

    def activate(self, tab_id) -> None:
        self._tab = self._browser.get_tab(tab_id)
        self._browser.activate_tab(tab_id)

    def close_tab(self, tab_id) -> None:
        t = self._browser.get_tab(tab_id)
        t.close()

    # =====================================================================
    # Screenshots (base64 for vision agents)
    # =====================================================================
    def screenshot(self, full_page: bool = False) -> str:
        """Return PNG as base64 (no file I/O)."""
        return self._tab.get_screenshot(as_base64="png", full_page=full_page)

    def _to_base64(self, out: str | bytes) -> str:
        return out if isinstance(out, str) else out.decode()

    def screenshot(self, full_page: bool = False) -> str:
        """Return PNG as base64 (no file I/O)."""
        return self._to_base64(self._tab.get_screenshot(as_base64="png", full_page=full_page))

    def screenshot_element(self, locator: str, center: bool = True) -> str | None:
        ele = cast(ChromiumElement, self._as_element(self._tab.ele(locator, timeout=3)))
        if ele is None:
            return None
        return self._to_base64(ele.get_screenshot(as_base64="png", scroll_to_center=center))

    # =====================================================================
    # Downloads
    # =====================================================================
    def download(self, url: str, save_path: str,
                 rename: str | None = None, timeout: float = 120) -> dict:
        mission = self._browser.latest_tab.download.by_browser(
            url, save_path=save_path, rename=rename, file_exists="rename",
        )
        ok = mission.wait(timeout=timeout)
        return {
            "ok": bool(ok),
            "state": mission.state,
            "path": str(mission.path),
            "total": mission.total,
        }

    # =====================================================================
    # Alerts
    # =====================================================================
    def handle_alert(self, accept: bool = True) -> Any:
        return self._tab.handle_alert(accept=accept)

    # =====================================================================
    # Snapshot / read-only introspection
    # =====================================================================
    def snapshot(self) -> dict[str, Any]:
        """Final content + metadata for the agent."""
        doc_ready = self.wait_doc_ready()
        return {
            "url": self._tab.url,
            "title": self._tab.title,
            "doc_ready": doc_ready,
            "html_len": len(self._tab.html),
            "html": self._tab.html,
        }


# =====================================================================
# Exposed LangChain tools (HITL gate kept in the caller)
# =====================================================================
@tool
def browser_fetch(url: str, max_scroll: int = 15, capture: bool = True) -> dict[str, Any]:
    """Fetch a rendered page, optionally capture matching network responses,
    scroll lazy content, and return the DOM + state. External navigation is
    always HITL-gated by the caller."""
    with Browser(
        url=url,
        listen_targets={"api", "xhr", "ajax"} if capture else None,
        scroll_to_bottom=True,
        max_scrolls=max_scroll,
        auto_handle_alerts=True,
    ) as browser:
        browser.navigate(url)
        if browser.scroll_to_bottom:
            browser.scroll()
        return {
            "page": browser.snapshot(),
            "network": browser.network_packets() if capture else [],
            "state": browser.get_state(),
        }


@tool
def browser_act(url: str, locator: str, action: str,
                value: str | None = None) -> dict[str, Any]:
    """Perform an element action on a freshly-loaded page and return the
    resulting DOM snapshot. Caller is responsible for HITL gating navigation."""
    with Browser(url=url, listen_targets=None, auto_handle_alerts=True) as browser:
        browser.navigate(url)
        result = browser.act(locator, action, value)
        return {
            "result": result,
            "page": browser.snapshot(),
            "network": browser.network_packets(timeout=2),
        }

@tool
def browser_run_js(url: str, script: str, as_expr: bool = False) -> dict[str, Any]:
    """Execute arbitrary JavaScript in page context and return the result plus
    the post-JS DOM snapshot. Navigation is HITL-gated by the caller."""
    with Browser(url=url, listen_targets=None) as browser:
        browser.navigate(url)
        out = browser.eval_js(script, as_expr=as_expr)
        return {"js_result": out, "page": browser.snapshot()}
