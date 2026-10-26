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
                 patches_file: str | Path | None = None,
                 log_file: str | Path | None = None):
        self._session     = session
        self._brain       = brain
        self._raw_get     = session.get   # original get, captured before any monkey-patch
        self._lock        = threading.Lock()
        self._patches:       dict[str, dict]          = {}
        self._schema_remaps: dict[str, dict[str, str]] = {}
        self._schema:        dict[str, set]            = {}
        self._heal_log:      list[dict]                = []
        self._discoveries:   list[dict]                = []
        self._patches_file: Path | None = Path(patches_file) if patches_file else None
        # persistent audit log — defaults to ~/.nselib/guardian_log.json
        self._log_file: Path = (
            Path(log_file) if log_file
            else Path.home() / ".nselib" / "guardian_log.json"
        )
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

    def _log(self, event: str, **kwargs) -> None:
        """Append one event to the persistent guardian_log.json."""
        entry = {"ts": datetime.now().isoformat(), "event": event, **kwargs}
        try:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            log: list = []
            if self._log_file.exists():
                try:
                    log = json.loads(self._log_file.read_text())
                except Exception:
                    log = []
            log.append(entry)
            self._log_file.write_text(json.dumps(log, indent=2))
        except Exception as exc:
            print(f"[Guardian] Could not write log: {exc}")

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

    # ------------------------------------------------------------------ #
    #  Archive heal — guarded_archive + URL-pattern repair                #
    # ------------------------------------------------------------------ #

    def guarded_archive(
        self,
        url:    str,
        action: "Any | None" = None,
    ) -> Any:
        """
        Execute action(url) — an archive request against nsearchives.nseindia.com.

        On NSEFileUnavailableError (404), asks Brain to infer the new URL pattern,
        patches the calling method's source code, and retries with the corrected URL.

        action: any callable(str) -> Any.
                Defaults to self._session.get_raw (returns raw Response).
                Pass self._session.download_zip / download_file / download_gz
                when the caller needs a different download helper.

        Usage in archive methods::

            _dl = lambda u: self._session.download_zip(u, folder=Path(folder))
            return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)
        """
        import inspect
        caller = inspect.stack()[1]
        _action = action if action is not None else self._session.get_raw
        try:
            return _action(url)
        except NSEFileUnavailableError:
            new_url = self._heal_archive_url(url, caller.filename, caller.function)
            return _action(new_url)

    def _heal_archive_url(
        self, url: str, caller_file: str, caller_name: str
    ) -> str:
        """Ask Brain to fix a broken archive URL and patch the source."""
        print(
            f"[Guardian] Archive 404 in {Path(caller_file).name}/{caller_name} "
            "— asking Claude to fix URL pattern…"
        )
        source = self._extract_method_source(caller_file, caller_name)
        prompt = (
            f"An NSE archive file returned 404 (file not found).\n"
            f"  URL: {url}\n"
            f"  Method: {caller_name} in {Path(caller_file).name}\n\n"
            f"Method source:\n{source}\n\n"
            f"NSE occasionally changes archive paths or filename formats "
            f"(e.g. folder rename, added prefix/suffix, date-format change).\n"
            f"Suggest the corrected URL for this specific request, and if the "
            f"URL construction pattern has changed provide the full corrected "
            f"method code so the pattern is fixed for all future calls.\n\n"
            f"Reply ONLY with JSON:\n"
            f'{{"new_url": "corrected-url-or-null", '
            f'"fixed_code": "corrected-method-or-null", '
            f'"explanation": "one sentence"}}'
        )
        fix_raw = self._brain.ask(prompt)
        fix     = self._parse_json(fix_raw) or {}
        new_url = fix.get("new_url", "")

        if fix.get("fixed_code") and source:
            self._patch_method_source(caller_file, source, fix["fixed_code"])

        if new_url:
            print(f"[Guardian] Archive URL healed: {fix.get('explanation', '')}")
            self._log(
                "heal_archive",
                url=url, new_url=new_url,
                method=caller_name,
                explanation=fix.get("explanation", ""),
            )
            return new_url

        raise NSEFileUnavailableError(url)

    def _extract_method_source(self, filepath: str, method_name: str) -> str:
        """Return the source of a method from a file, or '' on failure."""
        try:
            text = Path(filepath).read_text()
            m = re.search(
                rf"(    def {re.escape(method_name)}\b.*?)(?=\n    def |\Z)",
                text, re.DOTALL,
            )
            return m.group(1) if m else ""
        except Exception:
            return ""

    def _patch_method_source(
        self, filepath: str, old_source: str, new_code: str
    ) -> None:
        """Replace a method's source in-place."""
        try:
            text = Path(filepath).read_text()
            old  = old_source.rstrip()
            new  = "    " + new_code.strip().replace("\n", "\n    ")
            updated = text.replace(old, new, 1)
            if updated != text:
                Path(filepath).write_text(updated)
                print(f"[Guardian] Patched archive method in {Path(filepath).name}")
                self._log("patch_archive", filepath=filepath,
                          snippet=old_source[:80])
        except Exception as e:
            print(f"[Guardian] Could not patch archive source: {e}")

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
            entry = {
                "ts":          datetime.now().isoformat(),
                "path":        path,
                "explanation": fix.get("explanation", ""),
                "patch":       patch,
            }
            self._heal_log.append(entry)
            self._save_patches()

        self._log("heal", path=path, patch=patch,
                  explanation=fix.get("explanation", ""))
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
                    self._log("adapt", path=path, remap=remap)
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

    def discover(self, focus: str | None = None) -> list[dict]:
        """
        Ask Claude to suggest NSE API endpoints not yet in nselib, then
        probe each candidate directly to confirm it's live.
        Works on any IP — no JS bundle scraping needed.
        Returns list of discovery dicts with confirmed live endpoints.

        Args:
            focus: Optional area to target, e.g.
                   "insider trading, block/bulk deals, corporate governance".
                   When None, uses the default broad discovery prompt.
        """
        print("[Guardian] Asking Claude for undiscovered NSE endpoints…")

        focus_line = (
            f"Focus specifically on: {focus}"
            if focus else
            "Focus on: FII/DII data, put-call ratio, OI analysis, "
            "52-week data, circuit breakers, deliverable positions, VIX, "
            "currency/commodity derivatives that definitely exist."
        )

        prompt = (
            f"You are an expert on NSE India's undocumented REST API at "
            f"https://www.nseindia.com/api/\n\n"
            f"nselib already knows these paths:\n"
            f"{json.dumps(sorted(_KNOWN_PATHS), indent=2)}\n\n"
            f"List the TOP 20 most useful NSE API paths that nselib is likely MISSING. "
            f"Be specific and high-confidence only — paths you are fairly certain exist "
            f"(not guesses). {focus_line}\n\n"
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
            f"For each one, generate a Python mixin method.\n"
            f"IMPORTANT RULES:\n"
            f"1. Paths are relative — do NOT include '/api/' prefix.\n"
            f"2. ALWAYS call self._guardian.guarded_get(path, params) instead of "
            f"self._session.get(path, params). This ensures every new method gets "
            f"automatic self-healing, schema drift detection, and retry on failure.\n"
            f"3. If self._guardian is None, fall back to self._session.get(path, params).\n"
            f"Example call pattern:\n"
            f"  data = (self._guardian.guarded_get if self._guardian else self._session.get)"
            f"(\"the-path\", params)\n\n"
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

        self._log("discover",
                  live_endpoints=live,
                  methods_generated=[d.get("method_name") for d in discoveries])
        return discoveries

    def apply(self, nselib_dir: str | Path, nse_instance=None) -> list[str]:
        """
        Write methods generated by discover() into the right module files,
        then automatically verify each one. Methods that fail and cannot be
        fixed are removed from the file before returning.

        Ensures every generated method routes through guarded_get() so it
        gets automatic self-healing and schema drift detection from day one.
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

            # Guarantee Guardian wrapping — replace any bare _session.get calls
            # with the guarded version so self-healing applies from day one.
            code = code.replace(
                "self._session.get(",
                "(self._guardian.guarded_get if self._guardian else self._session.get)(",
            )

            indented = "\n    ".join(code.splitlines())
            updated  = current.rstrip("\n") + f"\n\n    {indented}\n"
            target.write_text(updated)
            modified.append(str(target))
            self._log("apply", method=d.get("method_name"),
                      module=module, path=d.get("path"))
            print(f"[Guardian] Added '{d.get('method_name')}' to {module}.py (guardian-wrapped)")

        if self._discoveries:
            print(f"[Guardian] Verifying {len(self._discoveries)} new method(s)…")
            results = self.verify(nselib_dir, nse_instance=nse_instance)
            # write status back onto each discovery so HealthChecker can read it
            verify_map = {r["method"]: r["status"] for r in results}
            for d in self._discoveries:
                d["_verify_status"] = verify_map.get(d.get("method_name"), "skipped")
            passed  = sum(1 for r in results if r["status"] in ("pass", "fixed"))
            removed = sum(1 for r in results if r["status"] == "removed")
            failed  = sum(1 for r in results if r["status"] == "failed")
            print(f"[Guardian] Verification: {passed} pass, {removed} removed, {failed} failed")

        return modified

    def verify(self, nselib_dir: str | Path, nse_instance=None) -> list[dict]:
        """
        Test every method written by apply(). For each one:
          1. Call it with no args (or minimal sample args)
          2. If it returns non-empty data → PASS
          3. If it fails or returns empty → ask Claude to fix the method and rewrite it

        Returns a list of {method, status, detail} dicts.
        """
        import importlib, inspect, sys as _sys

        base    = Path(nselib_dir) / "nselib" / "modules"
        results = []

        # reuse a live NSE instance if provided, otherwise use session directly
        from .nse import NSE as _NSE
        nse = nse_instance or _NSE.__new__(_NSE)
        if nse_instance is None:
            nse._session = self._session
            nse._brain   = self._brain
            nse._guardian = self

        for d in self._discoveries:
            method_name = d.get("method_name")
            module      = d.get("module")
            path        = d.get("path", "")
            if not method_name or not module:
                continue

            # reload the module so the newly written method is importable
            mod_path = f"nselib.modules.{module}"
            try:
                if mod_path in _sys.modules:
                    importlib.reload(_sys.modules[mod_path])
            except Exception:
                pass

            method = getattr(nse, method_name, None)
            if method is None:
                results.append({"method": method_name, "status": "missing",
                                "detail": "method not found on NSE instance after reload"})
                self._log("verify", method=method_name, status="missing")
                continue

            # call with no args; catch any error
            try:
                resp = method()
                if resp and not self._is_broken(resp):
                    results.append({"method": method_name, "status": "pass",
                                    "detail": f"returned {type(resp).__name__}"})
                    self._log("verify", method=method_name, status="pass")
                    print(f"[Guardian] ✓ {method_name}")
                    continue
                else:
                    raise ValueError("empty response")
            except Exception as exc:
                print(f"[Guardian] ✗ {method_name} failed: {exc} — asking Claude to fix…")

                target      = base / f"{module}.py"
                last_error  = str(exc)
                last_code   = d.get("method_code", "")
                status      = "failed"
                detail      = f"unfixable: {last_error}"
                max_attempts = 3

                for attempt in range(max_attempts):
                    attempt_label = f"attempt {attempt + 1}/{max_attempts}"
                    fix_prompt = (
                        f"The nselib method `{method_name}` for NSE path `{path}` "
                        f"failed when called with no arguments ({attempt_label}).\n"
                        f"Error: {last_error}\n\n"
                        f"Current (broken) implementation:\n{last_code}\n\n"
                        f"Fix the method so it works with sensible defaults for any "
                        f"required parameters. Use guarded_get pattern. "
                        f"Reply with ONLY the corrected method code (no JSON wrapper)."
                    )
                    fixed_code = self._brain.ask(fix_prompt).strip()
                    fixed_code = re.sub(r"^```python\s*|^```\s*|```$", "",
                                        fixed_code, flags=re.MULTILINE).strip()

                    if not fixed_code or not target.exists():
                        # no fix generated — remove the broken method from the file
                        if target.exists():
                            file_text    = target.read_text()
                            bad_indented = "\n    ".join(last_code.strip().splitlines())
                            cleaned      = file_text.replace(f"\n\n    {bad_indented}\n", "", 1)
                            if cleaned != file_text:
                                target.write_text(cleaned)
                                print(f"[Guardian] ✗ {method_name} — no fix generated, removed from file")
                        detail = f"removed: no fix generated ({last_error})"
                        status = "removed"
                        break

                    old_indented = "\n    ".join(last_code.strip().splitlines())
                    new_indented = "\n    ".join(fixed_code.splitlines())
                    current      = target.read_text()
                    updated      = current.replace(f"    {old_indented}", f"    {new_indented}", 1)
                    if updated == current:
                        detail = f"fix generated but could not splice into file ({last_error})"
                        break

                    target.write_text(updated)
                    d["method_code"] = fixed_code
                    print(f"[Guardian] Spliced fix for {method_name} ({attempt_label}) — re-testing…")

                    try:
                        if mod_path in _sys.modules:
                            importlib.reload(_sys.modules[mod_path])
                        method2 = getattr(nse, method_name, None)
                        resp2   = method2() if method2 else None
                        if resp2 and not self._is_broken(resp2):
                            detail = f"fixed and verified ({attempt_label})"
                            status = "fixed"
                            print(f"[Guardian] ✓ {method_name} (fixed on {attempt_label})")
                            break
                        else:
                            last_error = "empty response after fix"
                            last_code  = fixed_code
                            print(f"[Guardian] ✗ {method_name} still empty ({attempt_label}), retrying…")
                    except Exception as retest_exc:
                        last_error = str(retest_exc)
                        last_code  = fixed_code
                        print(f"[Guardian] ✗ {method_name} still failing ({attempt_label}): "
                              f"{retest_exc} — retrying…")
                else:
                    # all attempts exhausted — remove the method from the file
                    print(f"[Guardian] ✗ {method_name} could not be fixed after {max_attempts} "
                          f"attempts — removing from file")
                    file_text    = target.read_text()
                    bad_indented = "\n    ".join(last_code.strip().splitlines())
                    file_text    = file_text.replace(f"\n\n    {bad_indented}\n", "", 1)
                    target.write_text(file_text)
                    detail = f"removed: {max_attempts} fix attempts failed — {last_error}"
                    status = "removed"

                results.append({"method": method_name, "status": status, "detail": detail})
                self._log("verify", method=method_name, status=status,
                          error=str(exc), detail=detail)

        return results

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
    #  Data pipeline health — bhavcopy + constituents                    #
    # ------------------------------------------------------------------ #

    def check_health(self) -> dict:
        """
        Check the health of both data pipelines.

        Returns a dict with keys 'bhav' and 'constituents', each containing:
          - status: 'ok' or 'stale'
          - last_date / last_snapshot: most recent date found
          - detail: human-readable explanation
        """
        import csv
        from datetime import date, timedelta
        from .modules.indices import _STORE, _BHAV_DIR

        result = {}

        # --- bhavcopy ---
        out_file = _BHAV_DIR / "constituents_1y.csv"
        expected = (date.today() - timedelta(days=1)).isoformat()
        if not out_file.exists():
            result["bhav"] = {"status": "stale", "last_date": None,
                              "detail": "constituents_1y.csv not found"}
        else:
            with open(out_file, newline="") as f:
                dates = [r["TradDt"] for r in csv.DictReader(f) if r.get("TradDt")]
            last = max(dates) if dates else None
            if last and last >= expected:
                result["bhav"] = {"status": "ok", "last_date": last,
                                  "detail": f"up to date ({last})"}
            else:
                result["bhav"] = {"status": "stale", "last_date": last,
                                  "detail": f"last date {last}, expected >= {expected}"}

        # --- constituents ---
        import json as _json
        comp = _STORE / "Comprehensive_latest.json"
        if not comp.exists():
            result["constituents"] = {"status": "stale", "last_snapshot": None,
                                      "detail": "Comprehensive_latest.json not found"}
        else:
            data = _json.loads(comp.read_text())
            snap_date = data.get("date")
            n_idx     = data.get("total_indices", 0)
            n_stocks  = data.get("total_stocks", 0)
            if snap_date and n_idx >= 60:
                result["constituents"] = {
                    "status": "ok", "last_snapshot": snap_date,
                    "detail": f"{n_idx} indices, {n_stocks} stocks as of {snap_date}",
                }
            else:
                result["constituents"] = {
                    "status": "stale", "last_snapshot": snap_date,
                    "detail": f"only {n_idx} indices found (expected ≥ 60)",
                }

        for name, info in result.items():
            icon = "✓" if info["status"] == "ok" else "✗"
            print(f"[Guardian] {icon} {name}: {info['detail']}")

        return result

    def heal_data(self, nse_instance=None) -> dict:
        """
        Fix any stale data pipelines found by check_health().

        Pass an NSE instance to reuse its session; if omitted, a fresh one
        is created using the Guardian's own session.

        Returns the health dict after healing.
        """
        health = self.check_health()

        # import here to avoid circular imports at module load
        from .nse import NSE as _NSE

        nse = nse_instance or _NSE.__new__(_NSE)
        if nse_instance is None:
            nse._session = self._session
            nse._brain   = self._brain

        if health.get("bhav", {}).get("status") == "stale":
            print("[Guardian] Healing bhavcopy…")
            try:
                nse.fetch_constituent_bhav_history(workers=4)
                self._log("data_heal", pipeline="bhav", status="healed")
                print("[Guardian] Bhavcopy healed.")
            except Exception as exc:
                self._log("data_heal", pipeline="bhav", status="failed", error=str(exc))
                print(f"[Guardian] Bhavcopy heal failed: {exc}")

        if health.get("constituents", {}).get("status") == "stale":
            print("[Guardian] Healing constituents…")
            try:
                nse.snapshot_all_constituents(workers=4)
                self._log("data_heal", pipeline="constituents", status="healed")
                print("[Guardian] Constituents healed.")
            except Exception as exc:
                self._log("data_heal", pipeline="constituents", status="failed", error=str(exc))
                print(f"[Guardian] Constituents heal failed: {exc}")

        return self.check_health()

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
            "data_health": self.check_health(),
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
