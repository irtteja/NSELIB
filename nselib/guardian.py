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

_CATALOGUE_FILE = Path(__file__).parent / "endpoints.json"


def _load_catalogue() -> dict:
    """Return the endpoint catalogue, or empty dict if unavailable."""
    try:
        if _CATALOGUE_FILE.exists():
            return json.loads(_CATALOGUE_FILE.read_text()).get("endpoints", {})
    except Exception:
        pass
    return {}

from .brain import Brain
from .core  import NSESession
from .exceptions import NSEFileUnavailableError


# Every path nselib currently uses (kept up to date)
_KNOWN_PATHS: set[str] = {
    # quotes
    "NextApi/apiClient/GetQuoteApi",
    "top-corp-info",
    # indices
    "allIndices",
    "historicalOR/indicesHistory",
    # market
    "marketStatus", "holiday-master", "etf",
    "live-analysis-volume-gainers", "market-data-pre-open",
    "block-deal", "historicalOR/bulk-block-short-deals",
    # history
    "historicalOR/cm/equity", "historicalOR/fo/derivatives",
    # corporate
    "corporates-corporateActions",
    "corporate-announcements",
    "corporate-board-meetings",
    "corporates-financial-results",
    "annual-reports", "corporates-pit", "event-calendar",
    # fno
    "NextApi/apiClient/GetQuoteApi",
    # downloads / misc
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

    def __init__(self, session: NSESession, brain: Brain,
                 patches_file: str | Path | None = None):
        self._session     = session
        self._brain       = brain
        self._raw_get     = session.get   # original get, captured before any monkey-patch
        self._lock        = threading.Lock()
        self._patches:       dict[str, dict]        = {}   # path → {headers, params, new_path}
        self._schema_remaps: dict[str, dict[str,str]] = {}   # path → {api_key: nselib_key}
        self._schema:        dict[str, set]           = {}   # path → last-seen top-level keys
        self._heal_log:      list[dict]               = []   # what was healed and when
        self._discoveries: list[dict]      = []   # new endpoints Claude found
        self._patches_file: Path | None = Path(patches_file) if patches_file else None
        self._load_patches()

    # ------------------------------------------------------------------ #
    #  Persistent patches                                                #
    # ------------------------------------------------------------------ #

    def _load_patches(self) -> None:
        if not self._patches_file or not self._patches_file.exists():
            return
        try:
            data = json.loads(self._patches_file.read_text())
            self._patches       = data.get("patches", {})
            self._schema_remaps = data.get("schema_remaps", {})
            if data.get("cookie_ttl"):
                self._session._COOKIE_TTL = data["cookie_ttl"]
            loaded = len(self._patches)
            if loaded:
                print(f"[Guardian] Loaded {loaded} saved patch(es) from {self._patches_file}")
        except Exception as e:
            print(f"[Guardian] Could not load patches file: {e}")

    def _save_patches(self) -> None:
        if not self._patches_file:
            return
        try:
            self._patches_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "patches":       self._patches,
                "schema_remaps": self._schema_remaps,
                "cookie_ttl":    self._session._COOKIE_TTL,
                "saved_at":      datetime.now().isoformat(),
            }
            self._patches_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[Guardian] Could not save patches file: {e}")

    # ------------------------------------------------------------------ #
    #  Heal                                                               #
    # ------------------------------------------------------------------ #

    def guarded_get(self, path: str, params: dict | None = None) -> Any:
        """
        Drop-in replacement for NSESession.get().
        Automatically heals broken responses via Claude.
        """
        try:
            resp = self._apply_and_get(path, params)
        except NSEFileUnavailableError as e:
            resp = self._heal(path, params, {"error": "404", "url": str(e)})
            if isinstance(resp, dict):
                resp = self._check_and_heal_schema(path, resp)
            return resp

        if self._is_broken(resp):
            resp = self._heal(path, params, resp)

        if isinstance(resp, dict):
            resp = self._check_and_heal_schema(path, resp)

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
            return self._raw_get(effective_path, merged_params or None)
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

        # Build a compact catalogue summary for Brain to reason over
        catalogue = _load_catalogue()
        catalogue_lines = "\n".join(
            f"  {p}: {meta.get('purpose', '')} | method={meta.get('nselib_method')} | params={meta.get('params', [])}"
            for p, meta in catalogue.items()
        )
        catalogue_section = (
            f"\nKnown NSE endpoints (from live catalogue):\n{catalogue_lines}\n"
            if catalogue_lines else ""
        )

        prompt = (
            f"An NSE India API call returned an empty or error response.\n"
            f"  path:     {path}\n"
            f"  params:   {json.dumps(params or {})}\n"
            f"  response: {bad_resp!r}\n"
            f"{catalogue_section}\n"
            f"IMPORTANT: Paths are relative — do NOT include '/api/' prefix. "
            f"NSESession.get() prepends 'https://www.nseindia.com/api/' automatically.\n"
            f"Use the catalogue above to find the correct or alternative path. "
            f"If the failed path looks like a renamed version of a known endpoint "
            f"(e.g. 'corporates-x' vs 'corporate-x', 'historical' vs 'historicalOR'), "
            f"suggest the corrected path.\n\n"
            f"Reply with ONLY valid JSON:\n"
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
            self._save_patches()

        print(f"[Guardian] Patch applied: {fix.get('explanation', 'unknown')}")
        return self._apply_and_get(path, params)

    # ------------------------------------------------------------------ #
    #  Adapt — schema drift detection + healing                          #
    # ------------------------------------------------------------------ #

    def _check_and_heal_schema(self, path: str, resp: dict) -> dict:
        """
        1. Apply any previously saved key remaps (fast path, no LLM).
        2. Detect drift vs last-seen keys.
        3. Fuzzy-match removed keys → new keys; fall back to Brain for
           anything that can't be resolved heuristically.
        4. Persist the remap so future calls are transparent.
        Returns the (possibly remapped) response dict.
        """
        # Apply saved remaps so existing nselib code keeps working
        saved = self._schema_remaps.get(path)
        if saved:
            resp = self._remap_dict(resp, saved)

        keys = set(resp.keys())
        prev = self._schema.get(path)

        if prev is not None and keys != prev:
            removed = prev - keys
            added   = keys - prev

            if removed:
                remap: dict[str, str] = {}
                unmatched: list[str] = []

                for old_k in removed:
                    match = self._fuzzy_key_match(old_k, added)
                    if match:
                        remap[match] = old_k   # rename new API key → old nselib key
                        print(f"[Guardian] Schema remap '{path}': '{match}' → '{old_k}'")
                    else:
                        unmatched.append(old_k)

                if unmatched and self._brain:
                    brain_remap = self._heal_schema_brain(path, unmatched, added, resp)
                    remap.update(brain_remap)
                    unmatched = [k for k in unmatched if k not in {v for v in brain_remap.values()}]

                if unmatched:
                    print(f"[Guardian] Schema drift on '{path}' — unmapped keys: {sorted(unmatched)}")

                if remap:
                    with self._lock:
                        merged = {**self._schema_remaps.get(path, {}), **remap}
                        self._schema_remaps[path] = merged
                        self._save_patches()
                    resp = self._remap_dict(resp, remap)

            elif added:
                # Only new keys — no breakage, just log
                print(f"[Guardian] Schema expanded on '{path}': new keys {sorted(added)}")

        self._schema[path] = set(resp.keys())
        return resp

    def _heal_schema_brain(
        self,
        path: str,
        removed: list[str],
        added:   set[str],
        sample:  dict,
    ) -> dict[str, str]:
        """Ask Brain to map ambiguous removed keys to their new equivalents."""
        prompt = (
            f"NSE API path '{path}' response changed.\n"
            f"Keys nselib expects but are now missing: {sorted(removed)}\n"
            f"New keys in the response: {sorted(added)}\n"
            f"Full response keys: {sorted(sample.keys())}\n\n"
            f"For each missing key, find its replacement in the new keys "
            f"(or null if truly gone). Reply ONLY with JSON:\n"
            f"{{\"<new_api_key>\": \"<old_nselib_key>\", ...}}"
        )
        raw  = self._brain.ask(prompt)
        data = self._parse_json(raw) or {}
        result = {}
        for new_k, old_k in data.items():
            if old_k and isinstance(old_k, str) and new_k in added:
                result[new_k] = old_k
                print(f"[Guardian] Brain schema remap '{path}': '{new_k}' → '{old_k}'")
        return result

    @staticmethod
    def _remap_dict(resp: dict, remap: dict[str, str]) -> dict:
        """Rename keys in resp according to remap {current_key: desired_key}."""
        return {remap.get(k, k): v for k, v in resp.items()}

    @staticmethod
    def _fuzzy_key_match(target: str, candidates: set[str]) -> str | None:
        """
        Return the best match for `target` from `candidates`, or None.
        Tries (in order): normalised exact, substring containment, edit distance ≤ 2.
        """
        if not candidates:
            return None

        def norm(k: str) -> str:
            return re.sub(r"[_\-]", "", k.lower())

        t = norm(target)

        # 1. normalised exact match
        for c in candidates:
            if norm(c) == t:
                return c

        # 2. one normalised form contains the other
        for c in candidates:
            cn = norm(c)
            if t in cn or cn in t:
                return c

        # 3. edit distance ≤ 2 (Levenshtein)
        def _lev(a: str, b: str) -> int:
            dp = list(range(len(b) + 1))
            for ch_a in a:
                prev, dp[0] = dp[0], dp[0] + 1
                for j, ch_b in enumerate(b, 1):
                    prev, dp[j] = dp[j], prev if ch_a == ch_b else 1 + min(prev, dp[j], dp[j-1])
            return dp[len(b)]

        best, best_d = None, 3
        for c in candidates:
            d = _lev(t, norm(c))
            if d < best_d:
                best, best_d = c, d
        return best

    # ------------------------------------------------------------------ #
    #  Discover                                                            #
    # ------------------------------------------------------------------ #

    def discover(self) -> list[dict]:
        """
        Ask Claude to suggest NSE API endpoints not yet in nselib, then
        probe each candidate directly to confirm it's live.
        Works on any IP — no JS bundle scraping needed.
        Returns list of discovery dicts with confirmed live endpoints.
        """
        print("[Guardian] Asking Claude for undiscovered NSE endpoints…")

        prompt = (
            f"You are an expert on NSE India's undocumented REST API at "
            f"https://www.nseindia.com/api/\n\n"
            f"nselib already knows these paths:\n"
            f"{json.dumps(sorted(_KNOWN_PATHS), indent=2)}\n\n"
            f"List the TOP 20 most useful NSE API paths that nselib is likely MISSING. "
            f"Be specific and high-confidence only — paths you are fairly certain exist "
            f"(not guesses). Focus on: FII/DII data, put-call ratio, OI analysis, "
            f"52-week data, circuit breakers, deliverable positions, VIX, "
            f"currency/commodity derivatives that definitely exist.\n\n"
            f"Reply ONLY with a JSON array of up to 20 candidate paths "
            f"(relative, no /api/ prefix):\n"
            f'["path1", "path2", ...]'
        )

        raw = self._brain.ask(prompt)
        candidates = self._parse_json(raw)
        if not isinstance(candidates, list):
            print("[Guardian] No candidates returned.")
            return []

        candidates = [p for p in candidates if isinstance(p, str) and p not in _KNOWN_PATHS]
        print(f"[Guardian] {len(candidates)} candidate(s) to probe: {candidates}")

        # Probe each candidate directly — only keep ones that return real data
        live: list[str] = []
        for path in candidates:
            try:
                resp = self._raw_get(path, None)
                if resp and not self._is_broken(resp):
                    live.append(path)
                    print(f"[Guardian]   ✓ live: {path}")
            except Exception:
                pass  # 404 or error — skip

        if not live:
            print("[Guardian] No live new endpoints confirmed.")
            return []

        print(f"[Guardian] Confirmed {len(live)} new endpoint(s). Generating methods…")

        gen_prompt = (
            f"These NSE API endpoints are confirmed live and not yet in nselib:\n"
            f"{json.dumps(live, indent=2)}\n\n"
            f"For each one, generate a Python mixin method. "
            f"IMPORTANT: paths are relative — NSESession.get() adds the /api/ prefix automatically. "
            f"Reply with ONLY a valid JSON array:\n"
            f"[\n"
            f"  {{\n"
            f'    "path": "the-endpoint-path",\n'
            f'    "module": "quotes|indices|market|history|corporate|fno|downloads",\n'
            f'    "method_name": "snake_case_name",\n'
            f'    "method_code": "def method_name(self, ...):\\n    ..."\n'
            f"  }}\n"
            f"]"
        )

        raw2 = self._brain.ask(gen_prompt)
        discoveries = self._parse_json(raw2)
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
