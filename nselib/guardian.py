"""
Guardian — self-healing, self-adapting, self-discovering layer.

Three jobs:
  heal     — when a request breaks, Claude diagnoses and patches it automatically
  adapt    — tracks response structure; alerts when NSE changes field names/nesting
  discover — sniffs NSE's JS bundle for API paths not yet in nselib,
             asks Claude to generate the methods, and can write them to disk
"""

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .brain import Brain
from .core  import NSESession


# Every path nselib already knows about
_KNOWN_PATHS: set[str] = {
    "quote-equity", "equity-meta-info", "search/autocomplete",
    "NextApi/apiClient/getScripHeaderData",
    "allIndices", "equity-stockIndices",
    "historicalOR/indicesHistory", "historicalOR/chartData",
    "marketStatus", "holiday-master", "etf",
    "live-analysis-emerge-market", "sovereign-gold-bond",
    "live-analysis-volume-gainers", "market-data-pre-open",
    "block-deal", "bulk-deal-archives",
    "historical/cm/equity", "historical/fo/derivatives",
    "corporates-corporateActions", "corporates-announcements",
    "corporates-board-meetings", "corporates-financial-results",
    "corporates-shp", "annual-reports", "corporates-pit",
    "option-chain-indices", "option-chain-equities", "quote-derivative",
    "daily-reports",
}

_MODULE_FOR = {
    "quote":      "quotes",
    "equity":     "quotes",
    "search":     "quotes",
    "indices":    "indices",
    "historical": "history",
    "market":     "market",
    "holiday":    "market",
    "block":      "market",
    "bulk":       "market",
    "pre-open":   "market",
    "corporate":  "corporate",
    "annual":     "corporate",
    "option":     "fno",
    "derivative": "fno",
    "report":     "downloads",
}


class Guardian:
    """
    Sits between nselib and NSE's servers.

    Usage
    -----
    Automatic (recommended) — pass ``guard=True`` to NSE()::

        with NSE(anthropic_api_key="sk-ant-...", guard=True) as nse:
            nse.equity_quote("RELIANCE")   # heals itself if something breaks

    Manual::

        g = Guardian(nse._session, nse._brain)
        data = g.guarded_get("quote-equity", {"symbol": "RELIANCE"})

    Discovery::

        new = g.discover()          # finds new endpoints on NSE
        g.apply("/path/to/nselib")  # writes generated methods to module files
        g.watch(interval=3600)      # run discover() in background every hour
    """

    def __init__(self, session: NSESession, brain: Brain):
        self._session     = session
        self._brain       = brain
        self._lock        = threading.Lock()
        self._patches:    dict[str, dict]  = {}   # path → {headers, params, new_path}
        self._schema:     dict[str, set]   = {}   # path → last-seen top-level keys
        self._heal_log:   list[dict]       = []   # what was healed and when
        self._discoveries: list[dict]      = []   # new endpoints Claude found

    # ------------------------------------------------------------------ #
    #  Heal                                                               #
    # ------------------------------------------------------------------ #

    def guarded_get(self, path: str, params: dict | None = None) -> Any:
        """
        Drop-in replacement for NSESession.get().
        Automatically heals broken responses via Claude.
        """
        resp = self._apply_and_get(path, params)

        if self._is_broken(resp):
            resp = self._heal(path, params, resp)

        if isinstance(resp, dict):
            self._check_schema(path, resp)

        return resp

    def _apply_and_get(self, path: str, params: dict | None) -> Any:
        patch = self._patches.get(path, {})
        effective_path = patch.get("new_path", path)
        merged_params  = {**(params or {}), **patch.get("params", {})}

        sess = self._session._s
        old_headers = dict(sess.headers)
        if patch.get("headers"):
            sess.headers.update(patch["headers"])

        try:
            return self._session.get(effective_path, merged_params or None)
        finally:
            if patch.get("headers"):
                sess.headers.clear()
                sess.headers.update(old_headers)

    def _is_broken(self, resp: Any) -> bool:
        if resp is None:
            return True
        if isinstance(resp, dict) and not resp:
            return True
        if isinstance(resp, list) and not resp:
            return True
        return False

    def _heal(self, path: str, params: dict | None, bad_resp: Any) -> Any:
        print(f"[Guardian] '{path}' returned empty/error — asking Claude to diagnose…")

        prompt = (
            f"An NSE API call returned an empty or error response.\n"
            f"  path:     {path}\n"
            f"  params:   {json.dumps(params or {})}\n"
            f"  response: {bad_resp!r}\n"
            f"  headers sent: {json.dumps(dict(self._session._s.headers))}\n\n"
            f"Diagnose and suggest a fix. Reply with ONLY valid JSON:\n"
            f"{{\n"
            f'  "new_path": null_or_string,\n'
            f'  "extra_headers": {{}},\n'
            f'  "extra_params": {{}},\n'
            f'  "cookie_ttl_seconds": null_or_int,\n'
            f'  "explanation": "one sentence"\n'
            f"}}"
        )

        fix_raw = self._brain.ask(prompt)
        fix = self._parse_json(fix_raw) or {}

        patch: dict = {}
        if fix.get("new_path"):
            patch["new_path"] = fix["new_path"]
        if fix.get("extra_headers"):
            patch["headers"] = fix["extra_headers"]
        if fix.get("extra_params"):
            patch["params"] = fix["extra_params"]

        with self._lock:
            if patch:
                self._patches[path] = patch
            if fix.get("cookie_ttl_seconds"):
                self._session._COOKIE_TTL = fix["cookie_ttl_seconds"]
            self._heal_log.append({
                "ts":          datetime.now().isoformat(),
                "path":        path,
                "explanation": fix.get("explanation", ""),
                "patch":       patch,
            })

        print(f"[Guardian] Patch applied: {fix.get('explanation', 'unknown')}")
        return self._apply_and_get(path, params)

    # ------------------------------------------------------------------ #
    #  Adapt — schema drift detection                                     #
    # ------------------------------------------------------------------ #

    def _check_schema(self, path: str, resp: dict) -> None:
        keys = set(resp.keys())
        prev = self._schema.get(path)
        if prev is not None and keys != prev:
            added   = keys - prev
            removed = prev - keys
            msg = f"[Guardian] Schema drift on '{path}'"
            if added:
                msg += f" — NEW keys: {sorted(added)}"
            if removed:
                msg += f" — REMOVED keys: {sorted(removed)}"
            print(msg)
        self._schema[path] = keys

    # ------------------------------------------------------------------ #
    #  Discover                                                            #
    # ------------------------------------------------------------------ #

    def discover(self) -> list[dict]:
        """
        Fetch NSE's JS bundle, extract API paths, compare against
        what nselib already knows, and ask Claude to generate methods
        for anything new. Returns list of discovery dicts.
        """
        print("[Guardian] Fetching NSE JS bundle…")
        js = self._fetch_nse_js()
        if not js:
            print("[Guardian] Could not fetch NSE JS (likely blocked on this IP).")
            return []

        found   = self._extract_api_paths(js)
        new     = found - _KNOWN_PATHS

        if not new:
            print("[Guardian] No new endpoints found.")
            return []

        print(f"[Guardian] {len(new)} new path(s) found: {sorted(new)}")

        prompt = (
            f"These NSE API endpoint paths are new — not yet in our Python library:\n"
            f"{json.dumps(sorted(new), indent=2)}\n\n"
            f"For each one that looks like a real data endpoint (skip assets/fonts/images), "
            f"generate a Python method. Reply with ONLY a valid JSON array:\n"
            f"[\n"
            f"  {{\n"
            f'    "path": "the-endpoint-path",\n'
            f'    "module": "quotes|indices|market|history|corporate|fno|downloads",\n'
            f'    "method_name": "snake_case_name",\n'
            f'    "method_code": "def method_name(self, ...):\\n    ..."\n'
            f"  }}\n"
            f"]"
        )

        raw = self._brain.ask(prompt)
        discoveries = self._parse_json(raw)
        if not isinstance(discoveries, list):
            discoveries = []

        with self._lock:
            self._discoveries.extend(discoveries)
            _KNOWN_PATHS.update(d["path"] for d in discoveries if "path" in d)

        return discoveries

    def apply(self, nselib_dir: str | Path) -> list[str]:
        """
        Write methods generated by discover() into the right module files.
        Returns a list of files that were modified.
        """
        base     = Path(nselib_dir) / "nselib" / "modules"
        modified: list[str] = []

        for d in self._discoveries:
            module = d.get("module", "")
            code   = d.get("method_code", "").strip()
            if not module or not code:
                continue

            target = base / f"{module}.py"
            if not target.exists():
                print(f"[Guardian] Module file not found: {target}")
                continue

            current = target.read_text()
            if d.get("method_name") and d["method_name"] in current:
                print(f"[Guardian] '{d['method_name']}' already exists in {module}.py — skipping.")
                continue

            indented = "\n    ".join(code.splitlines())
            updated  = current.rstrip("\n") + f"\n\n    {indented}\n"
            target.write_text(updated)
            modified.append(str(target))
            print(f"[Guardian] Added '{d.get('method_name')}' to {module}.py")

        return modified

    def watch(self, interval: int = 3600) -> None:
        """
        Run discover() in a background thread every `interval` seconds.
        New endpoints are printed; call apply() manually to write them.
        """
        def _loop():
            while True:
                time.sleep(interval)
                found = self.discover()
                if found:
                    names = [d.get("method_name", d.get("path")) for d in found]
                    print(f"[Guardian] New methods ready to apply: {names}")

        t = threading.Thread(target=_loop, daemon=True, name="guardian-discover")
        t.start()
        print(f"[Guardian] Discovery thread started — checking every {interval}s.")

    # ------------------------------------------------------------------ #
    #  Reporting                                                           #
    # ------------------------------------------------------------------ #

    def report(self) -> dict:
        """Full summary of what the Guardian has done this session."""
        return {
            "heals":       self._heal_log,
            "patches":     self._patches,
            "discoveries": self._discoveries,
            "schema":      {p: sorted(k) for p, k in self._schema.items()},
        }

    # ------------------------------------------------------------------ #
    #  Internals                                                           #
    # ------------------------------------------------------------------ #

    def _fetch_nse_js(self) -> str:
        try:
            sess = self._session._s
            home = sess.get("https://www.nseindia.com/", timeout=15)
            # Pick first chunked JS file from Next.js build
            matches = re.findall(
                r'src=["\']?(/_next/static/chunks/[^"\'>\s]+\.js)["\']?',
                home.text,
            )
            if not matches:
                return ""
            js_url  = "https://www.nseindia.com" + matches[0]
            js_resp = sess.get(js_url, timeout=20)
            return js_resp.text
        except Exception as e:
            print(f"[Guardian] JS fetch error: {e}")
            return ""

    def _extract_api_paths(self, js: str) -> set[str]:
        """Pull candidate API path strings out of NSE's JS bundle."""
        # Match quoted strings that look like kebab-case API paths
        raw = re.findall(r'["\`]([a-zA-Z][a-zA-Z0-9/_-]{4,60})["\`]', js)
        paths: set[str] = set()
        for p in raw:
            # Must look like an API path: contains a hyphen or slash, no dots/spaces
            if ("/" in p or "-" in p) and "." not in p and " " not in p:
                paths.add(p.lstrip("/"))
        return paths

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Extract and parse JSON from Claude's response (may be wrapped in markdown)."""
        try:
            return json.loads(text)
        except Exception:
            pass
        # Try extracting from ```json ... ``` or bare { } / [ ]
        for pattern in (r"```json\s*([\s\S]+?)```", r"(\{[\s\S]+\})", r"(\[[\s\S]+\])"):
            m = re.search(pattern, text)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    pass
        return None
