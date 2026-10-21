from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..exceptions import NSEDataError

_STORE = Path.home() / ".nselib" / "constituents"

# Indices confirmed to return constituent stock data via the marketWatchApi.
# The other 96 indices (bond, leverage/inverse, VIX, many strategy/thematic)
# return empty constituent lists from NSE's API.
INDICES_WITH_CONSTITUENTS: list[str] = [
    "NIFTY 50", "NIFTY NEXT 50", "NIFTY 100", "NIFTY 200", "NIFTY 500",
    "NIFTY MIDCAP 50", "NIFTY MIDCAP 100", "NIFTY MIDCAP 150",
    "NIFTY SMALLCAP 500", "NIFTY SME EMERGE",
    "NIFTY BANK", "NIFTY IT", "NIFTY AUTO", "NIFTY PHARMA", "NIFTY FMCG",
    "NIFTY METAL", "NIFTY MEDIA", "NIFTY REALTY", "NIFTY ENERGY",
    "NIFTY PSU BANK", "NIFTY PSE", "NIFTY CPSE", "NIFTY MNC",
    "NIFTY COMMODITIES", "NIFTY CHEMICALS", "NIFTY CEMENT",
    "NIFTY MOBILITY", "NIFTY HOUSING", "NIFTY RURAL", "NIFTY WAVES",
    "NIFTY IPO", "NIFTY100 ESG",
    "NIFTY ALPHA 50", "NIFTY50 VALUE 20", "NIFTY50 SHARIAH",
    "NIFTY SHARIAH 25", "NIFTY500 SHARIAH",
    "NIFTY200 ALPHA 30", "NIFTY100 ALPHA 30", "NIFTY200 VALUE 30",
    "NIFTY500 VALUE 50",
]


def _index_key(index: str) -> str:
    return index.upper().replace(" ", "_").replace("&", "AND")


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _chunk_dates(from_date: date, to_date: date, days: int = 365):
    """Split a date range into chunks of at most `days` days."""
    cur = from_date
    while cur <= to_date:
        end = min(cur + timedelta(days=days - 1), to_date)
        yield cur, end
        cur = end + timedelta(days=1)


class IndicesMixin:
    """Index values, names, and historical data."""

    def list_indices(self) -> dict:
        """All NSE indices with live values, change, and turnover."""
        return self._session.get("allIndices")

    def index_quote(self, index: str) -> dict:
        """
        Live quote for a specific index by name.
        e.g. index_quote("NIFTY 50"), index_quote("NIFTY BANK")
        """
        data = self.list_indices()
        for item in data.get("data", []):
            if item.get("index", "").upper() == index.upper():
                return item
        raise NSEDataError(f"Index not found: {index!r}. Use list_indices() to see all names.")

    def index_constituents(self, index: str) -> list[dict]:
        """
        Live prices for all stocks in a given index.
        e.g. index_constituents("NIFTY 50"), index_constituents("NIFTY BANK")

        Each record has: symbol, companyName, lastPrice, change, pChange,
        open, dayHigh, dayLow, previousClose, totalTradedVolume,
        totalTradedValue, yearHigh, yearLow, perChange30d, perChange365d.

        The first record is the index itself; the rest are its constituent stocks.
        """
        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/marketWatchApi"
            f"?functionName=getIndicesData&symbol={quote(index)}"
        )
        resp = self._session.get_raw(url)
        data = resp.json()
        return data.get("data", {}).get("data", [])

    # ------------------------------------------------------------------ #
    #  Constituent tracking                                               #
    # ------------------------------------------------------------------ #

    def snapshot_constituents(self, index: str) -> dict:
        """
        Fetch live constituents, save a dated snapshot, and return a diff
        vs the previous snapshot.

        Snapshots are stored in ~/.nselib/constituents/.
        The diff shows which symbols were added or removed since the last
        snapshot — empty lists mean no change.

        Returns:
            {
                "index":    "NIFTY 50",
                "date":     "2026-10-21",
                "symbols":  ["RELIANCE", "TCS", ...],   # current full list
                "added":    [...],                        # new since last run
                "removed":  [...],                        # gone since last run
                "first_run": True/False,
            }
        """
        key      = _index_key(index)
        today    = date.today().isoformat()
        _STORE.mkdir(parents=True, exist_ok=True)

        history_file  = _STORE / f"{key}_history.json"
        snapshot_file = _STORE / f"{key}_latest.json"

        # fetch live constituents (skip first entry — that's the index itself)
        raw      = self.index_constituents(index)
        symbols  = sorted(
            r["symbol"] for r in raw
            if r.get("symbol") and r.get("symbol") != index
        )

        # load previous snapshot if it exists
        prev_symbols: list[str] = []
        first_run = not snapshot_file.exists()
        if not first_run:
            prev_symbols = json.loads(snapshot_file.read_text()).get("symbols", [])

        added   = sorted(set(symbols) - set(prev_symbols))
        removed = sorted(set(prev_symbols) - set(symbols))

        # save new snapshot
        snapshot = {"index": index, "date": today, "symbols": symbols}
        snapshot_file.write_text(json.dumps(snapshot, indent=2))

        # append to history only when something changed (or first run)
        if first_run or added or removed:
            history: list[dict] = []
            if history_file.exists():
                history = json.loads(history_file.read_text())
            history.append({
                "date":    today,
                "added":   added,
                "removed": removed,
                "total":   len(symbols),
            })
            history_file.write_text(json.dumps(history, indent=2))

        return {
            "index":     index,
            "date":      today,
            "symbols":   symbols,
            "added":     added,
            "removed":   removed,
            "first_run": first_run,
        }

    def constituent_history(self, index: str) -> list[dict]:
        """
        Return the full changelog of constituent additions and removals
        for an index, oldest first.

        Each entry: {"date", "added": [...], "removed": [...], "total": N}

        Returns [] if snapshot_constituents() has never been called for
        this index.
        """
        history_file = _STORE / f"{_index_key(index)}_history.json"
        if not history_file.exists():
            return []
        return json.loads(history_file.read_text())

    def snapshot_all_constituents(self, workers: int = 4) -> dict[str, dict]:
        """
        Snapshot constituents for all 41 indices that expose stock-level
        data via NSE's API, in parallel.

        Returns {index_name: snapshot_result} where each value is the same
        dict that snapshot_constituents() returns for a single index.
        Indices that fail (network error etc.) are included with an
        "error" key instead.
        """
        import concurrent.futures

        results: dict[str, dict] = {}

        def _snap(idx: str):
            try:
                return idx, self.snapshot_constituents(idx)
            except Exception as exc:
                return idx, {"index": idx, "error": str(exc)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_snap, idx): idx for idx in INDICES_WITH_CONSTITUENTS}
            for fut in concurrent.futures.as_completed(futures):
                idx, result = fut.result()
                results[idx] = result
                changed = bool(result.get("added") or result.get("removed"))
                status  = "CHANGED" if changed else ("FIRST" if result.get("first_run") else "ok")
                err     = result.get("error", "")
                print(f"  [{status:7s}] {idx}" + (f" — {err}" if err else ""))

        return results

    def constituent_changes(self, index: str) -> dict:
        """
        Return only the most recent change record for an index.
        Useful for a quick check: did anything change since last run?

        Returns {} if no history exists yet.
        """
        history = self.constituent_history(index)
        return history[-1] if history else {}

    def fetch_index_names(self) -> dict[str, str]:
        """Return {short_name: full_name} mapping for all indices."""
        data = self.list_indices()
        return {
            item.get("indexSymbol", ""): item.get("index", "")
            for item in data.get("data", [])
        }

    def fetch_historical_index_data(
        self,
        index:     str,
        from_date: date | None = None,
        to_date:   date | None = None,
    ) -> list[dict]:
        """
        Daily OHLC + turnover for an index. Ranges >1 year are
        automatically chunked. Returns oldest-first.
        """
        to_date   = to_date   or date.today()
        from_date = from_date or (to_date - timedelta(days=30))

        rows: list[dict] = []
        for start, end in _chunk_dates(from_date, to_date, days=364):
            resp = self._session.get(
                "historicalOR/indicesHistory",
                params={
                    "indexType": index,
                    "from":      _fmt(start),
                    "to":        _fmt(end),
                },
            )
            chunk = resp.get("data", resp) if isinstance(resp, dict) else resp
            if isinstance(chunk, list):
                rows.extend(chunk)

        rows.sort(key=lambda r: r.get("HistoricalDate", r.get("Date", "")))
        return rows

    def fetch_historical_vix_data(
        self,
        from_date: date | None = None,
        to_date:   date | None = None,
    ) -> list[dict]:
        """
        Daily India VIX history. Ranges >1 year are chunked.
        Returns newest-first (matches NSE's default sort).
        """
        to_date   = to_date   or date.today()
        from_date = from_date or (to_date - timedelta(days=30))

        rows: list[dict] = []
        for start, end in _chunk_dates(from_date, to_date, days=364):
            resp = self._session.get(
                "historicalOR/chartData",
                params={
                    "indexType": "INDIA VIX",
                    "from":      _fmt(start),
                    "to":        _fmt(end),
                },
            )
            chunk = resp.get("grapthData", resp.get("data", [])) if isinstance(resp, dict) else resp
            if isinstance(chunk, list):
                rows.extend(chunk)

        return rows
