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

    def get_snapshot_derivatives_equity(self, index: str = "futures"):
        """Equity derivatives snapshot. index: 'futures' or 'options'."""
        params = {"index": index}
        return (self._guardian.guarded_get if self._guardian else self._session.get)("snapshot-derivatives-equity", params)

    # ------------------------------------------------------------------ #
    #  Archive-based data (works from any IP)                              #
    # ------------------------------------------------------------------ #

    def fno_ban_list(self, trade_date: date | None = None) -> list[str]:
        """
        F&O securities in ban period for a given trade date.
        Defaults to most recent available trading day.
        Returns list of symbols currently banned (exceeded 95% MWPL).
        """
        from datetime import timedelta
        d = trade_date or date.today()
        for offset in range(5):
            check = d - timedelta(days=offset)
            url = (
                f"{_ARCHIVE}/archives/fo/sec_ban/fo_secban_{check.strftime('%d%m%Y')}.csv"
            )
            try:
                r = self._session._s.get(url, timeout=8)
                if r.status_code == 200 and b"DOCTYPE" not in r.content[:50]:
                    symbols = []
                    for line in r.text.splitlines()[1:]:
                        parts = line.strip().split(",")
                        if len(parts) >= 2 and parts[1].strip():
                            symbols.append(parts[1].strip())
                    return symbols
            except Exception:
                continue
        return []

    def participant_oi(self, trade_date: date | None = None) -> list[dict]:
        """
        Participant-wise Open Interest in equity derivatives (FII/DII/Client/Pro).
        Defaults to most recent available trading day.

        Each dict: participant, future_index_long, future_index_short,
          future_stock_long, future_stock_short,
          option_index_call_long, option_index_put_long,
          option_index_call_short, option_index_put_short,
          option_stock_call_long, option_stock_put_long,
          option_stock_call_short, option_stock_put_short,
          total_long, total_short
        """
        import csv as _csv2, io as _io2
        from datetime import timedelta
        d = trade_date or date.today()
        for offset in range(5):
            check = d - timedelta(days=offset)
            url = (
                f"{_ARCHIVE}/content/nsccl/"
                f"fao_participant_oi_{check.strftime('%d%m%Y')}.csv"
            )
            try:
                r = self._session._s.get(url, timeout=8)
                if r.status_code == 200 and b"DOCTYPE" not in r.content[:50]:
                    reader = _csv2.reader(_io2.StringIO(r.text))
                    rows = list(reader)
                    # row[0] = header description, row[1] = column names, rows[2:] = data
                    data_rows = [row for row in rows[2:] if row and row[0].strip() and row[0].strip() != "TOTAL"]
                    keys = [
                        "participant",
                        "future_index_long", "future_index_short",
                        "future_stock_long", "future_stock_short",
                        "option_index_call_long", "option_index_put_long",
                        "option_index_call_short", "option_index_put_short",
                        "option_stock_call_long", "option_stock_put_long",
                        "option_stock_call_short", "option_stock_put_short",
                        "total_long", "total_short",
                    ]
                    out = []
                    for row in data_rows:
                        if len(row) < 15:
                            continue
                        rec = {keys[i]: row[i].strip() for i in range(len(keys))}
                        for k in keys[1:]:
                            try:
                                rec[k] = int(rec[k].replace(",", ""))
                            except ValueError:
                                pass
                        out.append(rec)
                    return out
            except Exception:
                continue
        return []

    def participant_volume(self, trade_date: date | None = None) -> list[dict]:
        """
        Participant-wise trading volume in equity derivatives (FII/DII/Client/Pro).
        Same structure as participant_oi() but shows contracts traded (not OI).
        """
        import csv as _csv2, io as _io2
        from datetime import timedelta
        d = trade_date or date.today()
        for offset in range(5):
            check = d - timedelta(days=offset)
            url = (
                f"{_ARCHIVE}/content/nsccl/"
                f"fao_participant_vol_{check.strftime('%d%m%Y')}.csv"
            )
            try:
                r = self._session._s.get(url, timeout=8)
                if r.status_code == 200 and b"DOCTYPE" not in r.content[:50]:
                    reader = _csv2.reader(_io2.StringIO(r.text))
                    rows = list(reader)
                    data_rows = [row for row in rows[2:] if row and row[0].strip() and row[0].strip() != "TOTAL"]
                    keys = [
                        "participant",
                        "future_index_long", "future_index_short",
                        "future_stock_long", "future_stock_short",
                        "option_index_call_long", "option_index_put_long",
                        "option_index_call_short", "option_index_put_short",
                        "option_stock_call_long", "option_stock_put_long",
                        "option_stock_call_short", "option_stock_put_short",
                        "total_long", "total_short",
                    ]
                    out = []
                    for row in data_rows:
                        if len(row) < 15:
                            continue
                        rec = {keys[i]: row[i].strip() for i in range(len(keys))}
                        for k in keys[1:]:
                            try:
                                rec[k] = int(rec[k].replace(",", ""))
                            except ValueError:
                                pass
                        out.append(rec)
                    return out
            except Exception:
                continue
        return []

    def pcr(self, symbol: str, expiry: str | None = None) -> dict:
        """
        Put-Call Ratio for an index or stock options expiry.
        expiry: DD-Mon-YYYY e.g. '27-Nov-2025'. Defaults to nearest expiry.
        Returns: { expiry, total_ce_oi, total_pe_oi, pcr, symbol }
        """
        chain = self.compile_option_chain(symbol, expiry)
        if not chain:
            from ..exceptions import NSEDataError
            raise NSEDataError(f"No option chain data for {symbol}")
        expiry_used = next((r.get("expiry") for r in chain if r.get("expiry")), expiry or "")
        ce_oi = sum(r.get("ce_oi", 0) or 0 for r in chain)
        pe_oi = sum(r.get("pe_oi", 0) or 0 for r in chain)
        return {
            "symbol":       symbol.upper(),
            "expiry":       expiry_used,
            "total_ce_oi":  ce_oi,
            "total_pe_oi":  pe_oi,
            "pcr":          round(pe_oi / ce_oi, 3) if ce_oi else None,
        }
