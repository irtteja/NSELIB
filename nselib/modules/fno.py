import csv as _csv
import io as _io
from datetime import date, timedelta
from typing import Any

from ..exceptions import NSEDataError

_NEXTAPI  = "NextApi/apiClient/GetQuoteApi"
_ARCHIVE  = "https://nsearchives.nseindia.com"
_LOTS_URL = f"{_ARCHIVE}/content/fo/fo_mktlots.csv"

_INDEX_SYMS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}


class FnoMixin:
    """F&O: option chains, expiries, lot sizes, underlying list."""

    def option_chain(self, symbol: str) -> dict:
        """
        Full option chain for an index or stock.
        Use 'NIFTY', 'BANKNIFTY', 'FINNIFTY' for indices,
        or any F&O-eligible equity symbol.
        Returns {'data': [...], 'expiries': [...], 'strikes': [...], 'timestamp': ...}
        """
        sym = symbol.upper()
        raw = self._session.get(
            _NEXTAPI,
            params={"functionName": "getSymbolDerivativesData", "symbol": sym},
        )
        expiry_raw = self._session.get(
            _NEXTAPI,
            params={"functionName": "getOptionChainDropdown", "symbol": sym},
        )
        return {
            "data":      raw.get("data", []),
            "expiries":  expiry_raw.get("expiryDates", []),
            "strikes":   expiry_raw.get("strikePrice", []),
            "timestamp": raw.get("timestamp", ""),
        }

    def index_option_chain(self, symbol: str) -> dict:
        """Option chain specifically for index derivatives (NIFTY, BANKNIFTY…)."""
        return self.option_chain(symbol)

    def equity_option_chain(self, symbol: str) -> dict:
        """Option chain for stock options."""
        return self.option_chain(symbol)

    def compile_option_chain(self, symbol: str, expiry: str | None = None) -> list[dict]:
        """
        Flatten raw option chain into a list of strike rows, each with
        CE and PE data side-by-side plus the underlying price.

        expiry: 'DD-Mon-YYYY' (e.g. '27-Mar-2025').
                Defaults to the nearest expiry if omitted.
        """
        raw     = self.option_chain(symbol)
        records = raw.get("data", [])
        expiries = raw.get("expiries", [])

        if not records:
            raise NSEDataError(f"No option chain data returned for {symbol!r}")

        chosen = expiry or (expiries[0] if expiries else None)

        # Group CE and PE rows by (strike, expiry)
        by_strike: dict[tuple, dict] = {}
        underlying_value: float | None = None

        for rec in records:
            exp = rec.get("expiryDate", "")
            if chosen and exp.upper() != chosen.upper():
                continue

            raw_strike = rec.get("strikePrice")
            strike = float(str(raw_strike).strip()) if raw_strike is not None else None
            otype  = rec.get("optionType", "").upper()
            key    = (strike, exp)

            if key not in by_strike:
                by_strike[key] = {"strike": strike, "expiry": exp}

            if otype == "CE":
                by_strike[key].update({
                    "ce_ltp":    rec.get("lastPrice"),
                    "ce_oi":     rec.get("openInterest"),
                    "ce_chg_oi": rec.get("changeinOpenInterest"),
                    "ce_volume": rec.get("totalTradedVolume"),
                    "ce_iv":     rec.get("impliedVolatility") if "impliedVolatility" in rec else None,
                })
            elif otype == "PE":
                by_strike[key].update({
                    "pe_ltp":    rec.get("lastPrice"),
                    "pe_oi":     rec.get("openInterest"),
                    "pe_chg_oi": rec.get("changeinOpenInterest"),
                    "pe_volume": rec.get("totalTradedVolume"),
                    "pe_iv":     rec.get("impliedVolatility") if "impliedVolatility" in rec else None,
                })

            if underlying_value is None:
                underlying_value = rec.get("underlyingValue")

        rows = sorted(by_strike.values(), key=lambda r: r["strike"] or 0)
        if underlying_value is not None:
            for r in rows:
                r["underlying"] = underlying_value
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
                ce_oi = row.get("ce_oi") or 0
                pe_oi = row.get("pe_oi") or 0
                if test_strike > s:
                    pain += (test_strike - s) * ce_oi
                elif test_strike < s:
                    pain += (s - test_strike) * pe_oi
            if pain < min_pain:
                min_pain = pain
                best_strike = test_strike

        return {
            "strike":     best_strike,
            "expiry":     chain[0].get("expiry"),
            "total_pain": min_pain,
        }

    def get_futures_expiry(self, symbol: str) -> list[str]:
        """List of active expiry dates for a futures symbol."""
        raw = self._session.get(
            _NEXTAPI,
            params={"functionName": "getOptionChainDropdown", "symbol": symbol.upper()},
        )
        return raw.get("expiryDates", [])

    def fno_lots(self) -> dict[str, int]:
        """Current lot sizes for all F&O symbols (first active expiry)."""
        resp = self._session.get_raw(_LOTS_URL)
        reader = _csv.DictReader(_io.StringIO(resp.text))
        result: dict[str, int] = {}
        skip = {"UNDERLYING", "SYMBOL"}
        for row in reader:
            # CSV headers are whitespace-padded — strip all keys
            clean = {k.strip(): v.strip() for k, v in row.items()}
            sym = clean.get("SYMBOL", "")
            if not sym:
                continue
            # Take first non-empty expiry column as the current lot size
            for k, v in clean.items():
                if k not in skip and v:
                    try:
                        result[sym] = int(v)
                    except ValueError:
                        pass
                    break
        return result

    def fetch_fno_underlying(self) -> list[dict]:
        """All F&O eligible underlyings with symbol and lot size."""
        lots = self.fno_lots()
        return [{"symbol": sym, "lot_size": size} for sym, size in lots.items()]

    def futures_quote(self, symbol: str) -> dict:
        """Live derivatives data for an index or stock (all expiries)."""
        raw = self._session.get(
            _NEXTAPI,
            params={"functionName": "getSymbolDerivativesData", "symbol": symbol.upper()},
        )
        return raw

    def get_oi_spurts_underlyings(self):
        """Open interest spurts aggregated by underlying."""
        path = "live-analysis-oi-spurts-underlyings"
        return (self._guardian.guarded_get if self._guardian else self._session.get)(path, None)

    def get_oi_spurts_contracts(self):
        """Open interest spurts by individual derivative contract."""
        path = "live-analysis-oi-spurts-contracts"
        return (self._guardian.guarded_get if self._guardian else self._session.get)(path, None)

    def get_derivatives_equity_snapshot(self, index="futures"):
        """Equity derivatives snapshot. index: 'futures' or 'options'."""
        path = "snapshot-derivatives-equity"
        params = {"index": index}
        return (self._guardian.guarded_get if self._guardian else self._session.get)(path, params)

    def snapshot_derivatives_equity(self, symbol: str):
        """Fetch the derivatives snapshot (futures/options) for an equity symbol."""
        return (self._guardian.guarded_get if self._guardian else self._session.get)("snapshot-derivatives-equity", {"symbol": symbol.upper()})
