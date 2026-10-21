from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

from ..exceptions import NSEDataError


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
