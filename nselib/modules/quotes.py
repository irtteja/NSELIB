from datetime import date
from typing import Any


class QuotesMixin:
    """Live quote data for individual NSE-listed stocks."""

    def quote(self, symbol: str, series: str = "EQ") -> dict:
        """
        Full quote for a symbol: OHLC, LTP, volume, market depth,
        52-week H/L, circuit limits, and last update timestamp.
        """
        return self._session.get(
            "quote-equity",
            params={"symbol": symbol.upper(), "series": series.upper()},
        )

    def equity_quote(self, symbol: str) -> dict:
        """Simplified OHLCV snapshot — date, open, high, low, close, volume."""
        raw = self.quote(symbol)
        pd  = raw.get("priceInfo", {})
        td  = raw.get("securityInfo", {})
        return {
            "symbol": symbol.upper(),
            "date":   raw.get("metadata", {}).get("lastUpdateTime", ""),
            "open":   pd.get("open"),
            "high":   pd.get("intraDayHighLow", {}).get("max"),
            "low":    pd.get("intraDayHighLow", {}).get("min"),
            "close":  pd.get("lastPrice"),
            "prev_close": pd.get("previousClose"),
            "change": pd.get("change"),
            "pct_change": pd.get("pChange"),
            "volume": raw.get("marketDeptOrderBook", {}).get("tradeInfo", {}).get("totalTradedVolume"),
        }

    def get_detailed_scrip_data(self, symbol: str, series: str = "EQ") -> dict:
        """Order book, metadata, trade info via NSE Next API."""
        return self._session.get(
            "NextApi/apiClient/getScripHeaderData",
            params={
                "symbol": symbol.upper(),
                "series": series.upper(),
                "isIndex": "false",
            },
        )

    def equity_meta_info(self, symbol: str) -> dict:
        """
        Company metadata: ISIN, available series, FnO/ETF/SLB flags,
        suspended status, market type.
        """
        return self._session.get(
            "equity-meta-info",
            params={"symbol": symbol.upper()},
        )

    def lookup(self, query: str, segment: str = "equity") -> dict:
        """
        Search by company name or symbol.
        segment: 'all' | 'equity' | 'derivatives' | 'etf' | 'others'
        """
        return self._session.get(
            "search/autocomplete",
            params={"q": query, "type": segment},
        )
