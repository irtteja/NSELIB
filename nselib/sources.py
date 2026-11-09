"""
SourceRegistry — self-maintaining map of every NSE page, API endpoint and
archive file, rebuilt from the live site (no Claude / no human needed).

How it stays current when NSE changes the site:

  1. PAGES      sitemap.xml (+ nested sitemaps) ∪ homepage links ∪ navbar API.
                A page added to NSE's sitemap/menu appears on the next refresh.
  2. CHUNKS     every page's HTML lists its Next.js JS chunks.  Chunk filenames
                are content-hashed, so a site redeploy => new filenames => they
                are re-read automatically; unchanged chunks are skipped.
  3. SOURCES    regexes pull `/api/...`, `NextApi/...?functionName=...` and
                `nsearchives.nseindia.com/...` references out of the JS.
  4. PROBES     each concrete source is fetched live; status + response shape
                recorded.  A source that starts failing is flagged `broken`,
                one that disappears from the JS is flagged `removed`.
  5. DIFF       refresh() returns what is new / removed / broken / recovered.

Domain failover: nseindia.in is tried first (reachable from cloud IPs), then
nseindia.com.  Whichever answers is remembered in the registry file.

Registry file: ~/.nselib/sources.json     (override with `path=`)

Cloud note: only read-only GETs are issued; all calls go through the
session's rate limiter.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qsl, urlencode, quote

import requests

from .exceptions import NSEDataError

BASES = ("https://www.nseindia.in", "https://www.nseindia.com")
ARCHIVE_HOST = "https://nsearchives.nseindia.com"
DEFAULT_PATH = Path.home() / ".nselib" / "sources.json"
SEED_PATH    = Path(__file__).parent / "sources_seed.json"   # shipped snapshot for first run

# Pages under /static are CMS articles that share a handful of route templates;
# scanning every one of the ~1500 would add nothing.  We scan this many.
_STATIC_PAGE_SAMPLE = 3

_RE_LOC      = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_RE_HREF     = re.compile(r'href=["\']([^"\'#]+)["\']')
_RE_CHUNK    = re.compile(r'/?(?:_next/)?static/chunks/[A-Za-z0-9_.~%-]+\.js')
_RE_STR_API  = re.compile(r"""["'`]((?:https?://[^/"'`]+)?/?api/[^"'`\s\\]+)["'`]""")
_RE_STR_NEXT = re.compile(r"""["'`]((?:/?api/)?NextApi/[A-Za-z0-9_/]+\?[^"'`\s\\]+)["'`]""")
_RE_ARCHIVE  = re.compile(
    r"""["'`]((?:https?://nsearchives\.nseindia\.com)?/?(?:content|archives|products)/[^"'`\s\\]+?"""
    r"""\.(?:csv|zip|gz|xlsx?|json|dat|xml|txt|dbf)[^"'`\s\\]*)["'`]""")
_RE_TEMPLATE = re.compile(r"\$\{[^}]*\}")
_RE_QPARAM   = re.compile(r"([A-Za-z_]\w*)=\$\{(?:[^{}]|\{[^{}]*\})*\}")   # key=${minified expr}
_RE_PLACE    = re.compile(r"\{(\w*)\}")
_RE_DATE     = re.compile(r"(?<!\d)(?:\d{8}|\d{6})(?!\d)")   # 09112026 / 20261109 / 091126
_ASSET_EXT   = (".png", ".jpg", ".jpeg", ".svg", ".gif", ".ico", ".css", ".woff", ".woff2", ".webp")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_api(raw: str) -> str | None:
    """Reduce an `/api/...` literal to a path relative to /api/, or None."""
    raw = re.sub(r"^https?://[^/]+", "", raw)
    raw = raw.lstrip("/")
    if raw.startswith("api/"):
        raw = raw[4:]
    raw = raw.strip()
    if not raw or raw.endswith(_ASSET_EXT):
        return None
    raw = _RE_QPARAM.sub(lambda m: f"{m.group(1)}={{{m.group(1)}}}", raw)   # q=${e} -> q={q}
    return _RE_TEMPLATE.sub("{}", raw)                                      # leftovers (path segments)


def _source_key(kind: str, target: str) -> str:
    """Stable identity: API keys ignore volatile param values, keep functionName."""
    if kind == "api":
        path, _, query = target.partition("?")
        q = dict(parse_qsl(query.replace("&&", "&"), keep_blank_values=True))
        fn = q.get("functionName")
        return f"api:{path}#{fn}" if fn else f"api:{path}"
    if kind == "archive":
        return "archive:" + _RE_DATE.sub("{date}", target)
    return f"{kind}:{target}"


def _dated_default(target: str, params: dict) -> str:
    """Archive fetch: `date=` (a datetime.date) re-dates the embedded date tokens."""
    d = params.pop("date", None)
    return SourceRegistry._dated(target, d) if d is not None else target


class SourceRegistry:
    """Discovers, probes and serves every NSE source. See module docstring."""

    def __init__(self, session=None, path: str | Path | None = None,
                 timeout: int = 15, bases: tuple[str, ...] = BASES):
        self._session = session
        self._path    = Path(path) if path else DEFAULT_PATH
        self._timeout = timeout
        self._bases   = list(bases)
        self._lock    = threading.Lock()
        self._s       = (session._s if session is not None else requests.Session())
        if session is None:
            self._s.headers.update({
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
                "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
            })
        self.data = self._load()
        if self.data.get("active_base") in self._bases:
            b = self.data["active_base"]
            self._bases.remove(b)
            self._bases.insert(0, b)

    # ------------------------------------------------------------------ #
    #  Persistence                                                         #
    # ------------------------------------------------------------------ #

    def _load(self) -> dict:
        try:
            d = json.loads(self._path.read_text())
            if isinstance(d, dict) and "sources" in d:
                return d
        except Exception:
            pass
        fresh = {"version": 1, "updated": None, "active_base": None,
                 "pages": {}, "chunks": {}, "sources": {}, "history": []}
        try:                                    # first run: start from the shipped snapshot
            seed = json.loads(SEED_PATH.read_text())
            fresh["pages"]   = seed.get("pages", {})
            fresh["sources"] = seed.get("sources", {})
        except Exception:
            pass
        return fresh

    def export_seed(self, path: str | Path = SEED_PATH) -> int:
        """Write a compact snapshot (non-CMS pages + live sources, no probe data) to ship with the package."""
        pages = {p: {"origin": r.get("origin", "sitemap")} for p, r in self.data["pages"].items()
                 if not r.get("removed") and not p.startswith("/static")}
        srcs = {k: {"kind": r["kind"], "target": r["target"], "pages": r.get("pages", [])[:4]}
                for k, r in self.data["sources"].items() if not r.get("removed")}
        Path(path).write_text(json.dumps({"version": 1, "pages": pages,
                                          "sources": srcs}, indent=0, sort_keys=True))
        return len(srcs)

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True))
            tmp.replace(self._path)

    # ------------------------------------------------------------------ #
    #  HTTP with domain failover                                           #
    # ------------------------------------------------------------------ #

    def _throttle(self) -> None:
        if self._session is not None:
            try:
                self._session._bucket.consume()
            except Exception:
                pass

    def _http(self, url_or_path: str, **kw) -> requests.Response:
        """GET a path/URL, trying each NSE base until one gives a non-blocked answer."""
        if url_or_path.startswith("http"):
            u = urlparse(url_or_path)
            if u.hostname and "nsearchives" in u.hostname:
                self._throttle()
                return self._s.get(url_or_path, timeout=self._timeout, **kw)
            tail = u.path + (f"?{u.query}" if u.query else "")
        else:
            tail = "/" + url_or_path.lstrip("/")
        last: requests.Response | Exception | None = None
        for base in list(self._bases):
            self._throttle()
            try:
                r = self._s.get(base + tail, timeout=self._timeout,
                                headers={"Referer": base + "/", "Origin": base}, **kw)
            except requests.RequestException as e:
                last = e
                continue
            if r.status_code in (401, 403) or r.status_code >= 500:
                last = r
                continue
            if self.data.get("active_base") != base:
                self.data["active_base"] = base
                self._bases.remove(base)
                self._bases.insert(0, base)
            return r
        if isinstance(last, requests.Response):
            return last
        raise NSEDataError(f"All NSE domains unreachable for {tail}: {last}")

    # ------------------------------------------------------------------ #
    #  Step 1 — pages                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _path_of(url: str) -> str:
        p = urlparse(url)
        return (p.path or "/") + (f"?{p.query}" if p.query else "")

    def _collect_pages(self) -> dict[str, str]:
        """Return {path: origin} where origin is sitemap|home|nav."""
        found: dict[str, str] = {}

        def sitemap(url: str, depth: int = 0) -> None:
            try:
                r = self._http(url)
                if r.status_code != 200:
                    return
            except Exception:
                return
            for loc in _RE_LOC.findall(r.text):
                if loc.endswith(".xml") and depth < 2:
                    sitemap(loc, depth + 1)
                elif "nseindia" in loc:
                    found.setdefault(self._path_of(loc), "sitemap")

        sitemap("/sitemap.xml")

        try:
            r = self._http("/")
            if r.status_code == 200:
                for h in _RE_HREF.findall(r.text):
                    if h.startswith("/") and not h.startswith(("//", "/_next", "/next-assets")) \
                            and not h.lower().endswith(_ASSET_EXT):
                        found.setdefault(h.split("?")[0], "home")
        except Exception:
            pass

        # Navbar API — the live site menu (the first place a new section shows up)
        for key in ("mainNavigation", "footer"):
            try:
                r = self._http(f"/api/NextApi/apiStatic?functionName=getNavbarData&refkey={key}")
                if r.status_code == 200:
                    blob = json.dumps(r.json())
                    for m in re.findall(r'"(?:url|link|href|path)"\s*:\s*"(/[^"]+)"', blob):
                        found.setdefault(m.split("?")[0], "nav")
            except Exception:
                continue
        return found

    # ------------------------------------------------------------------ #
    #  Steps 2+3 — chunks and sources                                      #
    # ------------------------------------------------------------------ #

    def _fetch_text(self, path: str) -> str | None:
        try:
            r = self._http(path)
        except Exception:
            return None
        return r.text if r.status_code == 200 else None

    def _extract(self, js: str) -> list[tuple[str, str]]:
        """Return [(kind, target)] references found in a JS/HTML blob."""
        out: list[tuple[str, str]] = []
        for m in _RE_STR_API.findall(js):
            t = _norm_api(m)
            if t:
                out.append(("api", t))
        for m in _RE_STR_NEXT.findall(js):
            t = _norm_api(m if m.startswith(("api/", "/api/")) else "api/" + m.lstrip("/"))
            if t:
                out.append(("api", t))
        for m in _RE_ARCHIVE.findall(js):
            t = m
            if t.startswith("http"):
                t = t.split("nseindia.com", 1)[1]
            out.append(("archive", "/" + t.lstrip("/")))
        return out

    @staticmethod
    def _chunk_path(c: str) -> str:
        c = "/" + c.lstrip("/")
        return c if c.startswith("/_next/") else "/_next" + c

    def _read_chunk(self, cp: str) -> tuple[str, dict] | None:
        js = self._fetch_text(cp)
        if js is None:
            return None
        name = cp.rsplit("/", 1)[-1]
        nxt = {self._chunk_path(c) for c in _RE_CHUNK.findall(js)}
        nxt = sorted(c for c in nxt if c.rsplit("/", 1)[-1] != name)
        return name, {"refs": sorted(set(self._extract(js))), "next": nxt, "seen": _now()}

    def _load_chunks(self, roots: set[str], budget: int, fresh: set[str]) -> None:
        """Parallel BFS: fetch every not-yet-cached chunk reachable from `roots`."""
        frontier = {c for c in roots if c.rsplit("/", 1)[-1] not in self.data["chunks"]}
        fetched = 0
        while frontier and fetched < budget:
            batch = sorted(frontier)[: budget - fetched]
            frontier = set()
            for res in self._pmap(self._read_chunk, batch):
                fetched += 1
                if not res:
                    continue
                name, rec = res
                self.data["chunks"][name] = rec
                fresh.add(name)
                frontier.update(c for c in rec["next"]
                                if c.rsplit("/", 1)[-1] not in self.data["chunks"])

    def _closure(self, roots: list[str]) -> set[tuple[str, str]]:
        """All (kind, target) refs reachable from a page's root chunks via the cache."""
        seen: set[str] = set()
        refs: set[tuple[str, str]] = set()
        stack = [c.rsplit("/", 1)[-1] for c in roots]
        while stack:
            n = stack.pop()
            if n in seen or n not in self.data["chunks"]:
                continue
            seen.add(n)
            c = self.data["chunks"][n]
            refs.update(tuple(x) for x in c["refs"])
            stack.extend(x.rsplit("/", 1)[-1] for x in c["next"])
        return refs

    def _pmap(self, fn, items, workers: int = 8) -> list:
        from concurrent.futures import ThreadPoolExecutor
        def safe(x):
            try:
                return fn(x)
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(safe, items))

    # ------------------------------------------------------------------ #
    #  Step 4 — probes                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _shape(obj: Any) -> dict:
        if isinstance(obj, list):
            return {"type": "list", "rows": len(obj),
                    "keys": sorted(obj[0].keys())[:25] if obj and isinstance(obj[0], dict) else []}
        if isinstance(obj, dict):
            return {"type": "dict", "keys": sorted(obj.keys())[:25]}
        return {"type": type(obj).__name__}

    def _probe(self, rec: dict) -> dict:
        target = rec["target"]
        if rec["kind"] == "api" and (_RE_PLACE.search(target) or "undefined" in target):
            return {"status": "template", "ts": _now(), "params": _RE_PLACE.findall(target)}
        if rec["kind"] == "archive":
            return self._probe_archive(target)
        url = f"/api/{target}"
        try:
            r = self._http(url.replace("&&", "&"))
        except Exception as e:
            return {"status": "error", "error": str(e)[:120], "ts": _now()}
        res = {"http": r.status_code, "bytes": len(r.content), "ts": _now()}
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and rec["kind"] == "api":
            try:
                body = r.json()
                res["status"] = "ok" if body not in (None, [], {}, "") else "empty"
                res["shape"]  = self._shape(body)
            except ValueError:
                res["status"] = "non-json"
        elif r.status_code == 200 and rec["kind"] == "archive":
            res["status"] = "html-error" if b"DOCTYPE" in r.content[:50] else "ok"
        elif r.status_code == 404:
            res["status"] = "missing"
        elif r.status_code in (400, 405, 422):
            res["status"] = "needs-params"
        else:
            res["status"] = "error"
        res["content_type"] = ctype.split(";")[0]
        return res

    @staticmethod
    def _dated(target: str, d) -> str:
        """Re-date an archive path: keep each embedded date's format, swap in `d`."""
        def sub(m):
            t = m.group(0)
            if len(t) == 6:
                return d.strftime("%d%m%y")
            return d.strftime("%Y%m%d") if t.startswith("20") else d.strftime("%d%m%Y")
        return _RE_DATE.sub(sub, target)

    def _probe_archive(self, target: str) -> dict:
        """Archive files are published per trading day — try today back to D-5 (Rule 7)."""
        from datetime import date, timedelta
        dated = bool(_RE_DATE.search(target))
        days = range(0, 6) if dated else range(0, 1)
        last = {"status": "missing", "http": 404}
        for back in days:
            url = ARCHIVE_HOST + (self._dated(target, date.today() - timedelta(days=back)) if dated else target)
            try:
                r = self._http(url, stream=False)
            except Exception as e:
                return {"status": "error", "error": str(e)[:120], "ts": _now()}
            if r.status_code == 200 and b"DOCTYPE" not in r.content[:50]:
                return {"status": "ok", "http": 200, "bytes": len(r.content), "ts": _now(),
                        "resolved": url.replace(ARCHIVE_HOST, ""), "days_back": back}
            last = {"status": "missing" if r.status_code in (403, 404) else "error", "http": r.status_code}
        return {**last, "ts": _now()}

    # ------------------------------------------------------------------ #
    #  refresh()                                                           #
    # ------------------------------------------------------------------ #

    def refresh(self, probe: bool = True, chunk_budget: int = 600,
                rescan_all: bool = False, verbose: bool = False, browser: bool = False,
                observe_pages: int = 12) -> dict:
        """Re-crawl NSE and return a diff report. Safe to call repeatedly / from a thread.

        browser=True additionally opens a real browser on the busiest pages and records
        every /api/ call they make at runtime (needs playwright; see browser.py).
        """
        t0 = time.time()
        log = (lambda *a: print("[sources]", *a, flush=True)) if verbose else (lambda *a: None)
        prev_pages = set(self.data["pages"])
        prev_src   = dict(self.data["sources"])
        fresh: set[str] = set()
        if rescan_all:
            self.data["chunks"] = {}

        # 1. pages
        pages = self._collect_pages()
        if not pages:
            raise NSEDataError("No NSE pages reachable (all domains blocked?) — registry unchanged")
        now = _now()
        for p, origin in pages.items():
            rec = self.data["pages"].setdefault(p, {"first_seen": now})
            rec.update(last_seen=now, origin=origin)
        removed_pages = sorted(prev_pages - set(pages))
        for p in removed_pages:
            self.data["pages"][p]["removed"] = now
        new_pages = sorted(set(pages) - prev_pages) if prev_pages else []
        log(f"{len(pages)} pages ({len(new_pages)} new)")

        # 2+3. scan one HTML per route (all non-static pages + a sample of static ones)
        scan = [p for p in pages if not p.startswith("/static")]
        scan += [p for p in pages if p.startswith("/static")][:_STATIC_PAGE_SAMPLE]
        scan.append("/")
        found: dict[str, dict] = {}
        scan = list(dict.fromkeys(scan))
        htmls = dict(zip(scan, self._pmap(self._fetch_text, scan)))
        page_roots = {p: [self._chunk_path(c) for c in _RE_CHUNK.findall(h)]
                      for p, h in htmls.items() if h}
        self._load_chunks({c for r in page_roots.values() for c in r}, chunk_budget, fresh)
        for p, html in htmls.items():
            if not html:
                continue
            refs = set(self._extract(html)) | self._closure(page_roots[p])
            for kind, target in refs:
                rec = found.setdefault(_source_key(kind, target), {"kind": kind, "target": target, "pages": []})
                if p not in rec["pages"]:
                    rec["pages"].append(p)
        total_fetched = len(fresh)
        if browser:
            try:
                from .browser import BrowserSession
                ranked = sorted(htmls, key=lambda p: -sum(1 for f in found.values() if p in f["pages"]))
                with BrowserSession(self.data.get("active_base") or BASES[0]) as b:
                    for api_path, pgs in b.observe([p for p in ranked if htmls[p]][:observe_pages]).items():
                        t = _norm_api(api_path)
                        if t:
                            rec = found.setdefault(_source_key("api", t), {"kind": "api", "target": t, "pages": []})
                            rec["pages"] = sorted(set(rec["pages"]) | set(pgs))
                            rec["observed"] = True
            except Exception as e:           # browser is strictly additive
                log(f"browser observation skipped: {e}")
        log(f"{len(htmls)} pages scanned, {len(fresh)} new/changed chunks read, {len(found)} sources referenced")

        # merge into registry
        for key, f in found.items():
            rec = self.data["sources"].setdefault(key, {"first_seen": now, "kind": f["kind"],
                                                         "target": f["target"]})
            rec.update(kind=f["kind"], last_seen=now, pages=sorted(f["pages"])[:12])
            if f.get("observed"):
                rec["observed"] = True
            rec.pop("removed", None)
        # A source is 'removed' only if its chunks were rescanned this run and it vanished.
        removed_src = sorted(k for k in prev_src if k not in found
                             and not self.data["sources"][k].get("removed")
                             and (rescan_all or total_fetched or fresh) and self._can_judge_removal(k, found))
        for k in removed_src:
            self.data["sources"][k]["removed"] = now

        # 4. probe
        broken: list[str] = []
        recovered: list[str] = []
        if probe:
            todo = []
            for key, rec in self.data["sources"].items():
                if rec.get("removed"):
                    continue
                if (rec.get("probe") or {}).get("status") == "template" and key in prev_src:
                    continue
                todo.append(key)
            results = self._pmap(lambda k: self._probe(self.data["sources"][k]), todo, workers=6)
            for key, res in zip(todo, results):
                rec = self.data["sources"][key]
                before = (rec.get("probe") or {}).get("status")
                res = res or {"status": "error", "error": "probe crashed", "ts": _now()}
                rec["probe"] = res
                good = res["status"] in ("ok", "empty", "needs-params", "template", "non-json")
                if not good and before in ("ok", "empty"):
                    broken.append(key)
                if good and before in ("error", "missing", "html-error"):
                    recovered.append(key)
                log(f"  {res.get('status'):<12} {key}")

        new_src = sorted(k for k in found if k not in prev_src) if prev_src else []
        self.data["updated"] = now
        report = {
            "ts": now, "seconds": round(time.time() - t0, 1),
            "active_base": self.data.get("active_base"),
            "pages": len(pages), "new_pages": new_pages, "removed_pages": removed_pages,
            "sources": sum(1 for r in self.data["sources"].values() if not r.get("removed")),
            "new_sources": new_src, "removed_sources": removed_src,
            "broken": broken, "recovered": recovered,
            "chunks_read": len(fresh),
        }
        self.data["history"] = (self.data["history"] + [report])[-20:]
        self.save()
        return report

    def _can_judge_removal(self, key: str, found: dict) -> bool:
        """Only call a source removed if the chunks that used to reference it were re-read."""
        for name, c in self.data["chunks"].items():
            if any(_source_key(k, t) == key for k, t in map(tuple, c.get("refs", []))):
                return False   # a still-cached chunk references it — it's not gone
        return True

    # ------------------------------------------------------------------ #
    #  Querying + generic access                                           #
    # ------------------------------------------------------------------ #

    def sources(self, kind: str | None = None, status: str | None = None,
                include_removed: bool = False) -> list[dict]:
        """List known sources as dicts: key, kind, target, probe status, pages."""
        out = []
        for key, r in sorted(self.data["sources"].items()):
            if r.get("removed") and not include_removed:
                continue
            if kind and r["kind"] != kind:
                continue
            st = (r.get("probe") or {}).get("status")
            if status and st != status:
                continue
            out.append({"key": key, **r})
        return out

    def pages(self, prefix: str = "") -> list[str]:
        """All known live page paths, optionally filtered by prefix."""
        return sorted(p for p, r in self.data["pages"].items()
                      if not r.get("removed") and p.startswith(prefix))

    def find(self, text: str) -> list[dict]:
        """Case-insensitive substring search over source keys/targets."""
        t = text.lower()
        return [s for s in self.sources() if t in s["key"].lower() or t in s["target"].lower()]

    def fetch(self, source: str, **params) -> Any:
        """Fetch any discovered source by key or target; returns parsed JSON (api) or bytes (archive).

        `params` override/extend the query string; `{placeholder}` / `${x}` in a template
        are filled from params by name.
        """
        rec = self.data["sources"].get(source)
        if rec is None:
            hits = [s for s in self.sources() if s["target"] == source or s["key"].endswith(source)]
            if not hits:
                raise NSEDataError(f"Unknown source {source!r} — try registry.find(...) or refresh()")
            rec = hits[0]
        target = rec["target"].replace("&&", "&")
        if rec["kind"] == "api":
            missing = [k for k in _RE_PLACE.findall(target) if k and k not in params]
            if missing or "{}" in target:
                raise NSEDataError(f"{rec['target']} needs params: {missing or ['<path segment>']}")
            target = _RE_PLACE.sub(lambda m: quote(str(params.pop(m.group(1))), safe=''), target)
        else:
            target = _dated_default(target, params)
        if params:
            path, _, q = target.partition("?")
            merged = dict(parse_qsl(q, keep_blank_values=True)); merged.update(params)
            target = path + "?" + urlencode(merged)
        if rec["kind"] == "api":
            r = self._http(f"/api/{target}")
            r.raise_for_status()
            return r.json()
        r = self._http(f"{ARCHIVE_HOST}{target}")
        r.raise_for_status()
        if b"DOCTYPE" in r.content[:50]:
            raise NSEDataError(f"Archive returned an HTML error page: {target}")
        return r.content


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Refresh the NSE source registry (pages, APIs, archive files)")
    ap.add_argument("--no-probe", action="store_true", help="skip live probing of sources")
    ap.add_argument("--browser", action="store_true", help="also observe runtime API calls in a real browser")
    ap.add_argument("--rescan", action="store_true", help="forget cached JS chunks and re-read everything")
    ap.add_argument("--watch", type=int, metavar="SECONDS", help="repeat forever at this interval")
    ap.add_argument("--path", help="registry file (default ~/.nselib/sources.json)")
    ap.add_argument("--export-seed", action="store_true", help="after refreshing, rewrite nselib/sources_seed.json")
    ap.add_argument("--find", metavar="TEXT", help="print matching sources and exit")
    a = ap.parse_args()
    reg = SourceRegistry(path=a.path)
    if a.find:
        for x in reg.find(a.find):
            print(f"{(x.get('probe') or {}).get('status', '?'):<12} {x['key']}")
        return
    while True:
        rep = reg.refresh(probe=not a.no_probe, browser=a.browser, rescan_all=a.rescan, verbose=True)
        print(json.dumps({k: v for k, v in rep.items()}, indent=1))
        if a.export_seed:
            print(f"seed written: {reg.export_seed()} sources")
        if not a.watch:
            return
        time.sleep(a.watch)


if __name__ == "__main__":
    _main()
