"""
Real-browser layer for NSE (Playwright + Chromium).  Optional — used only when:

  * plain HTTP is blocked on every NSE domain (Akamai wants a browser-minted
    cookie / sensor token), via `harvest_cookies()` / `fetch_json()`; or
  * the registry wants to see what a page *actually* calls at runtime, via
    `observe()` — this catches endpoints assembled dynamically that no static
    JS scan can see.

Install:  pip install playwright   (Chromium: `playwright install chromium`,
or point NSELIB_CHROMIUM at an existing binary — /opt/pw-browsers/chromium is
auto-detected).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .exceptions import NSEDataError

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_API_RE = re.compile(r"^https?://[^/]*nseindia\.(?:com|in)/api/(.+)$")


def _chromium_path() -> str | None:
    for p in (os.environ.get("NSELIB_CHROMIUM"), "/opt/pw-browsers/chromium"):
        if p and Path(p).is_file():
            return p
    return None


class BrowserSession:
    """Plain headless Chromium — no fingerprint masking or automation-flag hiding.

        with BrowserSession("https://www.nseindia.in") as b:
            cookies = b.harvest_cookies()
            data    = b.fetch_json("/api/NextApi/apiClient?functionName=getMarketTurnover")
            seen    = b.observe(["/market-data/live-equity-market"])
    """

    def __init__(self, base: str = "https://www.nseindia.in", timeout_ms: int = 30_000):
        self.base = base.rstrip("/")
        self._timeout = timeout_ms
        self._pw = self._browser = self._ctx = self._page = None

    def __enter__(self) -> "BrowserSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise NSEDataError("Browser mode needs playwright: pip install playwright") from e
        self._pw = sync_playwright().start()
        kw: dict[str, Any] = dict(headless=True, args=["--no-sandbox"])
        if (exe := _chromium_path()):
            kw["executable_path"] = exe
        self._browser = self._pw.chromium.launch(**kw)
        self._ctx = self._browser.new_context(
            user_agent=_UA, locale="en-IN", timezone_id="Asia/Kolkata",
            viewport={"width": 1920, "height": 1080})
        self._page = self._ctx.new_page()
        self._page.set_default_timeout(self._timeout)
        return self

    def __exit__(self, *_) -> None:
        for obj in (self._browser,):
            try:
                obj and obj.close()
            except Exception:
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------ #

    def _goto(self, path: str) -> None:
        self._page.goto(self.base + path, wait_until="networkidle")

    def harvest_cookies(self) -> dict[str, str]:
        """Load the homepage like a user would and return the resulting cookie jar."""
        self._goto("/")
        self._page.wait_for_timeout(1500)
        host = urlparse(self.base).hostname or ""
        return {c["name"]: c["value"] for c in self._ctx.cookies()
                if host.split(".", 1)[-1] in c["domain"]}

    def fetch_json(self, path: str) -> Any:
        """fetch() from inside the page, so the browser's own cookies/headers apply."""
        if self._page.url in ("about:blank", ""):
            self._goto("/")
        res = self._page.evaluate(
            """async (u) => { const r = await fetch(u, {credentials: 'include'});
                              return {status: r.status, text: await r.text()}; }""",
            self.base + path)
        if res["status"] != 200:
            raise NSEDataError(f"{path} -> HTTP {res['status']} (browser)")
        import json
        return json.loads(res["text"])

    def observe(self, pages: list[str], settle_ms: int = 2500) -> dict[str, list[str]]:
        """Visit pages; return {api_path_with_query: [pages that called it]} for every /api/ call seen."""
        seen: dict[str, list[str]] = {}
        current = {"p": ""}

        def on_request(req):
            m = _API_RE.match(req.url)
            if m:
                seen.setdefault(m.group(1), [])
                if current["p"] not in seen[m.group(1)]:
                    seen[m.group(1)].append(current["p"])

        self._page.on("request", on_request)
        for p in pages:
            current["p"] = p
            try:
                self._goto(p)
                self._page.wait_for_timeout(settle_ms)
                self._page.evaluate("window.scrollBy(0, 800)")
                self._page.wait_for_timeout(800)
            except Exception:
                continue
        self._page.remove_listener("request", on_request)
        return seen
