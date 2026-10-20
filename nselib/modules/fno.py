from datetime import date, timedelta
from typing import Any

from ..exceptions import NSEDataError


class FnoMixin:
    """F&O: option chains, expiries, lot sizes, underlying list."""

    def option_chain(self, symbol: str) -> dict:
        """
        Full option chain for an index or stock.
        Use 'NIFTY', 'BANKNIFTY', 'FINNIFTY' for indices,
        or any F&O-eligible equity symbol.
        """
        sym = symbol.upper()
        try:
            return self._session.get(
                "option-chain-indices",
                params={"symbol": sym},
            )
        except Exception:
            return self._session.get(
                "option-chain-equities",
                params={"symbol": sym},
            )

    def index_option_chain(self, symbol: str) -> dict:
        """Option chain specifically for index derivatives (NIFTY, BANKNIFTY…)."""
        return self._session.get(
            "option-chain-indices",
            params={"symbol": symbol.upper()},
        )

    def equity_option_chain(self, symbol: str) -> dict:
        """Option chain for stock options."""
        return self._session.get(
            "option-chain-equities",
            params={"symbol": symbol.upper()},
        )

    def compile_option_chain(self, symbol: str, expiry: str | None = None) -> list[dict]:
        """
        Flatten raw option chain into a list of strike rows, each with
        CE and PE data side-by-side plus the underlying price.

        expiry: 'DD-Mon-YYYY' (e.g. '27-Mar-2025').
                Defaults to the nearest expiry if omitted.
        """
        raw = self.option_chain(symbol)
        records: list[dict] = raw.get("records", {}).get("data", [])
        expiries: list[str] = raw.get("records", {}).get("expiryDates", [])

        if not records:
            raise NSEDataError(f"No option chain data returned for {symbol!r}")

        chosen = expiry or (expiries[0] if expiries else None)

        rows: list[dict] = []
        for rec in records:
            if chosen and rec.get("expiryDate", "").upper() != chosen.upper():
                continue
            ce = rec.get("CE", {})
            pe = rec.get("PE", {})
            rows.append({
                "strike":          rec.get("strikePrice"),
                "expiry":          rec.get("expiryDate"),
                "ce_ltp":          ce.get("lastPrice"),
                "ce_oi":           ce.get("openInterest"),
                "ce_chg_oi":       ce.get("changeinOpenInterest"),
                "ce_volume":       ce.get("totalTradedVolume"),
                "ce_iv":           ce.get("impliedVolatility"),
                "pe_ltp":          pe.get("lastPrice"),
                "pe_oi":           pe.get("openInterest"),
                "pe_chg_oi":       pe.get("changeinOpenInterest"),
                "pe_volume":       pe.get("totalTradedVolume"),
                "pe_iv":           pe.get("impliedVolatility"),
            })
        return rows

    def max_pain(self, symbol: str, expiry: str | None = None) -> dict:
        """
        Max pain strike — the strike where total option buyer loss is maximum.
        Returns {'strike': float, 'expiry': str, 'total_pain': float}.
        """
        chain = self.compile_option_chain(symbol, expiry)
        if not chain:
            raise NSEDataError(f"Empty chain for {symbol!r}")

        strikes = [r["strike"] for r in chain if r["strike"] is not None]
        best_strike: float | None = None
        min_pain = float("inf")

        for test_strike in strikes:
            pain = 0.0
            for row in chain:
                s = row["strike"]
                if s is None:
                    continue
                ce_oi = row["ce_oi"] or 0
                pe_oi = row["pe_oi"] or 0
                if test_strike > s:
                    pain += (test_strike - s) * ce_oi
                elif test_strike < s:
                    pain += (s - test_strike) * pe_oi
            if pain < min_pain:
                min_pain = pain
                best_strike = test_strike

        return {
            "strike":      best_strike,
            "expiry":      chain[0].get("expiry"),
            "total_pain":  min_pain,
        }

    def get_futures_expiry(self, symbol: str) -> list[str]:
        """List of active expiry dates for a futures symbol."""
        raw = self.index_option_chain(symbol) if symbol.upper() in (
            "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"
        ) else self.equity_option_chain(symbol)
        return raw.get("records", {}).get("expiryDates", [])

    def fno_lots(self) -> dict:
        """Current lot sizes for all F&O symbols."""
        resp = self._session.get("equity-stockIndices", params={"index": "SECURITIES IN F&O"})
        stocks = resp.get("data", [])
        return {
            s.get("symbol", ""): s
            for s in stocks
            if s.get("symbol")
        }

    def fetch_fno_underlying(self) -> list[dict]:
        """All F&O eligible underlyings with live price and lot data."""
        resp = self._session.get("equity-stockIndices", params={"index": "SECURITIES IN F&O"})
        return resp.get("data", [])

    def futures_quote(self, symbol: str) -> dict:
        """Live futures quote for an index or stock."""
        return self._session.get(
            "quote-derivative",
            params={"symbol": symbol.upper()},
        )
