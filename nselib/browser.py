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
import random
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .exceptions import NSEDataError

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_API_RE = re.compile(r"^https?://[^/]*nseindia\.(?:com|in)/api/(.+)$")

# Injected before every page navigation — patches the most common
# Playwright/Chromium fingerprints that Akamai checks for.
_STEALTH_JS = """
// 1. Remove navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// 2. Realistic plugin list
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const arr = [
      {name: 'Chrome PDF Plugin',     filename: 'internal-pdf-viewer', description: 'Portable Document Format'},
      {name: 'Chrome PDF Viewer',     filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''},
      {name: 'Native Client',         filename: 'internal-nacl-plugin', description: ''},
    ];
    arr.__proto__ = PluginArray.prototype;
    return arr;
  }
});

// 3. India-first language list
Object.defineProperty(navigator, 'languages', {get: () => ['en-IN', 'en-GB', 'en']});

// 4. Chrome runtime object (headless omits it)
if (!window.chrome) window.chrome = {runtime: {}};

// 5. Permissions API — headless returns 'denied' for notifications
const origQuery = window.Permissions && window.Permissions.prototype.query;
if (origQuery) {
  window.Permissions.prototype.query = function(params) {
    if (params.name === 'notifications') {
      return Promise.resolve({state: Notification.permission});
    }
    return origQuery.call(this, params);
  };
}

// 6. Realistic screen dimensions
Object.defineProperty(screen, 'width',       {get: () => 1920});
Object.defineProperty(screen, 'height',      {get: () => 1080});
Object.defineProperty(screen, 'availWidth',  {get: () => 1920});
Object.defineProperty(screen, 'availHeight', {get: () => 1040});
Object.defineProperty(window, 'outerWidth',  {get: () => 1920});
Object.defineProperty(window, 'outerHeight', {get: () => 1080});

// 7. chrome.app automation flags
if (window.chrome && !window.chrome.app) {
  window.chrome.app = {
    isInstalled: false,
    getDetails:      function() { return null; },
    getIsInstalled:  function() { return false; },
    runningState:    function() { return 'cannot_run'; },
  };
}
"""

_EXTRA_HEADERS = {
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT":             "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":  "document",
    "Sec-Fetch-Mode":  "navigate",
    "Sec-Fetch-Site":  "none",
    "Sec-Fetch-User":  "?1",
}


def _chromium_path() -> str | None:
    for p in (os.environ.get("NSELIB_CHROMIUM"), "/opt/pw-browsers/chromium"):
        if p and Path(p).is_file():
            return p
    return None


def _jitter(lo: float = 0.8, hi: float = 2.2) -> int:
    """Random wait in ms, human-pace range."""
    return int(random.uniform(lo, hi) * 1000)


class BrowserSession:
    """Warm headless Chromium session with fingerprint normalisation.

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
        kw: dict[str, Any] = dict(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-web-security",
                "--window-size=1920,1080",
            ],
        )
        if (exe := _chromium_path()):
            kw["executable_path"] = exe
        self._browser = self._pw.chromium.launch(**kw)
        self._ctx = self._browser.new_context(
            user_agent=_UA,
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers=_EXTRA_HEADERS,
        )
        self._ctx.add_init_script(_STEALTH_JS)
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

    def _warm_scroll(self) -> None:
        """Simulate a human reading the page — random scroll with pauses."""
        for _ in range(random.randint(2, 4)):
            dist = random.randint(200, 700)
            self._page.evaluate(f"window.scrollBy(0, {dist})")
            self._page.wait_for_timeout(_jitter(0.4, 1.2))

    def harvest_cookies(self) -> dict[str, str]:
        """Visit the homepage as a user would; return the resulting cookie jar."""
        self._goto("/")
        self._page.wait_for_timeout(_jitter(1.2, 2.5))
        self._warm_scroll()
        self._page.wait_for_timeout(_jitter(0.5, 1.5))
        host = urlparse(self.base).hostname or ""
        return {c["name"]: c["value"] for c in self._ctx.cookies()
                if host.split(".", 1)[-1] in c["domain"]}

    def fetch_json(self, path: str) -> Any:
        """fetch() from inside the page so the browser's own cookies/headers apply."""
        if self._page.url in ("about:blank", ""):
            self._goto("/")
            self._page.wait_for_timeout(_jitter(1.0, 2.0))
        self._page.wait_for_timeout(_jitter(0.3, 0.9))   # inter-request pause
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
                self._page.wait_for_timeout(_jitter(1.0, 2.0))
                self._warm_scroll()
                self._page.wait_for_timeout(_jitter(0.5, 1.2))
            except Exception:
                continue
        self._page.remove_listener("request", on_request)
        return seen
