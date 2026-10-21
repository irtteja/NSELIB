from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..exceptions import NSEDataError

_STORE = Path.home() / ".nselib" / "constituents"

# All 137 NSE indices (by indexSymbol) confirmed to return constituent stock data
# via the marketWatchApi. Only INDIA VIX and NIFTY50 USD have no constituent data.
# Use snapshot_all_constituents() to iterate all of these at once.
INDICES_WITH_CONSTITUENTS: list[str] = [
    "BHARATBOND-APR30", "BHARATBOND-APR31", "BHARATBOND-APR32", "BHARATBOND-APR33",
    "NIFTY 100", "NIFTY 200", "NIFTY 50", "NIFTY 500",
    "NIFTY ALPHA 50", "NIFTY ALPHALOWVOL", "NIFTY AQL 30", "NIFTY AQLV 30",
    "NIFTY AUTO", "NIFTY BANK", "NIFTY CAPITAL MKT", "NIFTY CEMENT",
    "NIFTY CHEMICALS", "NIFTY COMMODITIES", "NIFTY CONSR DURBL", "NIFTY CONSUMPTION",
    "NIFTY COREHOUSING", "NIFTY CORP MAATR", "NIFTY CPSE",
    "NIFTY DIV OPPS 50", "NIFTY ENERGY", "NIFTY EV",
    "NIFTY FIN SERVICE", "NIFTY FINSEREXBNK", "NIFTY FINSRV25 50", "NIFTY FMCG",
    "NIFTY FPI 150", "NIFTY GROWSECT 15",
    "NIFTY GS 10YR", "NIFTY GS 10YR CLN", "NIFTY GS 11 15YR",
    "NIFTY GS 15YRPLUS", "NIFTY GS 4 8YR", "NIFTY GS 8 13YR", "NIFTY GS COMPSITE",
    "NIFTY HEALTHCARE", "NIFTY HIGHBETA 50", "NIFTY HOUSING",
    "NIFTY IND DEFENCE", "NIFTY IND DIGITAL", "NIFTY IND TOURISM",
    "NIFTY INDIA MFG", "NIFTY INFRA", "NIFTY INFRALOG", "NIFTY INTERNET",
    "NIFTY IPO", "NIFTY IT", "NIFTY LARGEMID250", "NIFTY LOW VOL 50",
    "NIFTY M150 QLTY50", "NIFTY MEDIA", "NIFTY METAL",
    "NIFTY MICROCAP250", "NIFTY MID LIQ 15", "NIFTY MID SELECT",
    "NIFTY MIDCAP 100", "NIFTY MIDCAP 150", "NIFTY MIDCAP 50",
    "NIFTY MIDSMALL 50 50", "NIFTY MIDSML 400", "NIFTY MIDSML HLTH",
    "NIFTY MNC", "NIFTY MOBILITY", "NIFTY MS FIN SERV", "NIFTY MS IND CONS",
    "NIFTY MS IT TELCM", "NIFTY MULTI INFRA", "NIFTY MULTI MFG", "NIFTY MULTI MQ 50",
    "NIFTY NEW CONSUMP", "NIFTY NEXT 50", "NIFTY NONCYC CONS",
    "NIFTY OIL AND GAS", "NIFTY PHARMA", "NIFTY PSE", "NIFTY PSU BANK",
    "NIFTY PVT BANK", "NIFTY QLTY LV 30", "NIFTY RAILWAYSPSU", "NIFTY REALTY",
    "NIFTY REITS REALTY", "NIFTY RURAL", "NIFTY SERV SECTOR",
    "NIFTY SHARIAH 25", "NIFTY SMALLCAP 500", "NIFTY SME EMERGE",
    "NIFTY SML250 Q50", "NIFTY SMLCAP 100", "NIFTY SMLCAP 250", "NIFTY SMLCAP 50",
    "NIFTY TATA 25 CAP", "NIFTY TMMQ 50", "NIFTY TOP 10 EW", "NIFTY TOP 15 EW",
    "NIFTY TOP 20 EW", "NIFTY TOTAL MKT", "NIFTY TRANS LOGIS", "NIFTY WAVES",
    "NIFTY100 ALPHA 30", "NIFTY100 ENH ESG", "NIFTY100 EQL WGT", "NIFTY100 ESG",
    "NIFTY100 LIQ 15", "NIFTY100 LOWVOL30", "NIFTY100 QUALTY30", "NIFTY100ESGSECLDR",
    "NIFTY200 ALPHA 30", "NIFTY200 QUALTY30", "NIFTY200 VALUE 30", "NIFTY200MOMENTM30",
    "NIFTY50 DIV POINT", "NIFTY50 EQL WGT", "NIFTY50 PR 1X INV", "NIFTY50 PR 2X LEV",
    "NIFTY50 SHARIAH", "NIFTY50 TR 1X INV", "NIFTY50 TR 2X LEV", "NIFTY50 VALUE 20",
    "NIFTY500 EW", "NIFTY500 FLEXICAP", "NIFTY500 HEALTH", "NIFTY500 LMS EQL",
    "NIFTY500 LOWVOL50", "NIFTY500 MQVLV50", "NIFTY500 MULTICAP", "NIFTY500 QLTY50",
    "NIFTY500 SHARIAH", "NIFTY500 VALUE 50", "NIFTY500MOMENTM50",
    "NIFTYCONGLOMERATE", "NIFTYM150MOMNTM50", "NIFTYMS400 MQ 100", "NIFTYSML250MQ 100",
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

    def _resolve_index_symbol(self, index: str) -> str:
        """
        Resolve a display name or abbreviation to the API symbol (indexSymbol).
        NSE uses abbreviated symbols (e.g. 'NIFTY FIN SERVICE') in the constituent
        API but full display names (e.g. 'NIFTY FINANCIAL SERVICES') in allIndices.
        Accepts either form.
        """
        data = self.list_indices()
        index_up = index.upper()
        for item in data.get("data", []):
            if (item.get("index", "").upper() == index_up or
                    item.get("indexSymbol", "").upper() == index_up):
                return item.get("indexSymbol", index)
        return index  # pass through unchanged if not found

    def index_constituents(self, index: str) -> list[dict]:
        """
        Live prices for all stocks in a given index.
        Accepts both the full display name (e.g. "NIFTY FINANCIAL SERVICES")
        and the abbreviated symbol (e.g. "NIFTY FIN SERVICE").

        Each record has: symbol, companyName, lastPrice, change, pChange,
        open, dayHigh, dayLow, previousClose, totalTradedVolume,
        totalTradedValue, yearHigh, yearLow, perChange30d, perChange365d.

        The first record is the index itself; the rest are its constituent stocks.
        """
        symbol = self._resolve_index_symbol(index)
        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/marketWatchApi"
            f"?functionName=getIndicesData&symbol={quote(symbol)}"
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
        # resolve to indexSymbol so the key and filtering are always consistent
        symbol   = self._resolve_index_symbol(index)
        key      = _index_key(symbol)
        today    = date.today().isoformat()
        _STORE.mkdir(parents=True, exist_ok=True)

        history_file  = _STORE / f"{key}_history.json"
        snapshot_file = _STORE / f"{key}_latest.json"

        # fetch live constituents (first record is the index itself — skip it)
        raw      = self.index_constituents(symbol)
        symbols  = sorted(
            r["symbol"] for r in raw
            if r.get("symbol") and r.get("symbol") != symbol
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
        symbol = self._resolve_index_symbol(index)
        history_file = _STORE / f"{_index_key(symbol)}_history.json"
        if not history_file.exists():
            return []
        return json.loads(history_file.read_text())

    def snapshot_all_constituents(self, workers: int = 4) -> dict[str, dict]:
        """
        Snapshot constituents for every NSE index that exposes stock-level data.
        Uses the live allIndices list (indexSymbol field) so no hardcoded names
        are needed — works correctly even as NSE adds or renames indices.

        Returns {indexSymbol: snapshot_result}. Indices that return an empty
        constituent list or fail are included with an "error" key instead.
        """
        import concurrent.futures

        # build {indexSymbol: display_name} map from live allIndices
        all_data  = self.list_indices().get("data", [])
        index_map = {
            item["indexSymbol"]: item["index"]
            for item in all_data
            if item.get("indexSymbol")
        }

        results: dict[str, dict] = {}

        def _snap(symbol: str):
            try:
                result = self.snapshot_constituents(symbol)
                if not result.get("symbols"):
                    return symbol, {"index": symbol, "error": "no constituent data"}
                return symbol, result
            except Exception as exc:
                return symbol, {"index": symbol, "error": str(exc)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_snap, sym): sym for sym in index_map}
            for fut in concurrent.futures.as_completed(futures):
                sym, result = fut.result()
                results[sym] = result
                changed = bool(result.get("added") or result.get("removed"))
                status  = "CHANGED" if changed else ("FIRST" if result.get("first_run") else "ok")
                err     = result.get("error", "")
                print(f"  [{status:7s}] {sym}" + (f" — {err}" if err else ""))

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
