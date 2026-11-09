import csv
import io
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from ..sources import SourceRegistry


class SourcesMixin:
    """Dynamic access to every NSE page, API and archive file the live site exposes.

    Cloud-safe: crawls nseindia.in (open to datacenter IPs) and nsearchives.nseindia.com.
    The registry rebuilds itself from the live site, so sources NSE adds later are
    reachable via `source_fetch()` without any new nselib code.
    """

    @property
    def sources(self) -> SourceRegistry:
        """The SourceRegistry bound to this session (created on first use)."""
        reg = getattr(self, "_sources_reg", None)
        if reg is None:
            reg = SourceRegistry(self._session)
            self._sources_reg = reg
        return reg

    def sources_refresh(self, probe: bool = True, browser: bool = False) -> dict:
        """Re-crawl NSE; returns {pages, sources, new_pages, new_sources, removed_sources, broken, recovered, ...}."""
        return self.sources.refresh(probe=probe, browser=browser)

    def sources_list(self, kind: str | None = None, status: str | None = None) -> list[dict]:
        """Known sources as [{key, kind, target, status, params, pages}]; kind: api|archive, status: ok|template|missing|..."""
        out = []
        for s in self.sources.sources(kind=kind, status=status):
            p = s.get("probe") or {}
            out.append({"key": s["key"], "kind": s["kind"], "target": s["target"],
                        "status": p.get("status"), "params": p.get("params", []),
                        "pages": s.get("pages", []), "first_seen": s.get("first_seen")})
        return out

    def sources_find(self, text: str) -> list[dict]:
        """Sources whose key or target contains `text` (case-insensitive)."""
        return [{"key": s["key"], "kind": s["kind"], "target": s["target"],
                 "status": (s.get("probe") or {}).get("status")} for s in self.sources.find(text)]

    def source_pages(self, prefix: str = "") -> list[str]:
        """Every live NSE page path from the sitemap/nav, optionally under `prefix` (e.g. '/market-data')."""
        return self.sources.pages(prefix)

    def source_fetch(self, source: str, params: dict | None = None, trade_date: date | None = None) -> Any:
        """Fetch any discovered source: API -> parsed JSON; archive CSV/ZIP -> list[dict]; other files -> saved-file info."""
        p = dict(params or {})
        if trade_date is not None:
            p["date"] = trade_date
        raw = self.sources.fetch(source, **p)
        if not isinstance(raw, (bytes, bytearray)):
            return raw
        return self._archive_payload(source, bytes(raw))

    def _archive_payload(self, source: str, raw: bytes) -> Any:
        name = source.rsplit("/", 1)[-1]
        low = name.lower()
        if low.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for member in zf.namelist():
                    if member.lower().endswith((".csv", ".txt", ".dat")):
                        return self._csv_rows(zf.read(member))
                dest = Path(self._session.download_folder) / name
                dest.write_bytes(raw)
                return {"saved": str(dest), "members": zf.namelist()}
        if low.endswith((".csv", ".txt", ".dat")):
            return self._csv_rows(raw)
        if low.endswith(".json"):
            import json
            return json.loads(raw)
        dest = Path(self._session.download_folder) / name
        dest.write_bytes(raw)
        return {"saved": str(dest), "bytes": len(raw)}

    @staticmethod
    def _csv_rows(raw: bytes) -> list[dict]:
        text = raw.decode("utf-8-sig", errors="replace")
        rows = []
        for r in csv.DictReader(io.StringIO(text)):
            row = {}
            for k, v in r.items():
                k = (k or "").strip()
                v = (v or "").strip() if isinstance(v, str) else v
                try:
                    n = float(v.replace(",", "")) if isinstance(v, str) and v else None
                    v = int(n) if n is not None and n.is_integer() and "." not in v else n if n is not None else v
                except ValueError:
                    pass
                row[k] = v
            rows.append(row)
        return rows
