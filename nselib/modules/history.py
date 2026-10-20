from datetime import date, timedelta


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _chunk(from_date: date, to_date: date, days: int = 100):
    cur = from_date
    while cur <= to_date:
        end = min(cur + timedelta(days=days - 1), to_date)
        yield cur, end
        cur = end + timedelta(days=1)


class HistoryMixin:
    """Historical OHLCV data for equities, F&O, and VIX."""

    def fetch_equity_historical_data(
        self,
        symbol:    str,
        from_date: date | None = None,
        to_date:   date | None = None,
        series:    str = "EQ",
        days:      int | None = None,
    ) -> list[dict]:
        """
        Daily OHLCV for an equity via NSE's Next API.
        Ranges >100 days are auto-chunked. Returns oldest-first.

        Args:
            symbol:    NSE symbol e.g. 'RELIANCE'
            from_date: start date (default: 30 days before to_date)
            to_date:   end date (default: today)
            series:    series code (default 'EQ')
            days:      convenience — sets from_date = today - days
        """
        to_date = to_date or date.today()
        if days:
            from_date = to_date - timedelta(days=days)
        from_date = from_date or (to_date - timedelta(days=30))

        if from_date > to_date:
            raise ValueError("from_date must be before to_date")

        rows: list[dict] = []
        for start, end in _chunk(from_date, to_date, days=100):
            resp = self._session.get(
                "historical/cm/equity",
                params={
                    "symbol":    symbol.upper(),
                    "series":    f'["{series.upper()}"]',
                    "from":      _fmt(start),
                    "to":        _fmt(end),
                    "csv":       "false",
                },
            )
            chunk = resp.get("data", []) if isinstance(resp, dict) else []
            rows.extend(chunk)

        rows.sort(key=lambda r: r.get("mTIMESTAMP", r.get("CH_TIMESTAMP", "")))
        return rows

    def fetch_historical_fno_data(
        self,
        symbol:       str,
        instrument:   str = "FUTIDX",
        from_date:    date | None = None,
        to_date:      date | None = None,
        expiry:       str | None = None,
        option_type:  str | None = None,
        strike_price: float | None = None,
    ) -> list[dict]:
        """
        Daily F&O OHLCV + OI. Ranges >1 year are chunked.

        instrument: FUTIDX | FUTSTK | OPTIDX | OPTSTK | FUTIVX
        option_type: required for OPTIDX / OPTSTK — 'CE' | 'PE'
        """
        inst_upper = instrument.upper()
        if inst_upper in ("OPTIDX", "OPTSTK") and not option_type:
            raise ValueError(f"option_type ('CE' or 'PE') is required for {inst_upper}")

        to_date   = to_date   or date.today()
        from_date = from_date or (to_date - timedelta(days=30))

        if from_date > to_date:
            raise ValueError("from_date must be before to_date")

        rows: list[dict] = []
        for start, end in _chunk(from_date, to_date, days=364):
            params: dict = {
                "instrumentType": inst_upper,
                "symbol":         symbol.upper(),
                "from":           _fmt(start),
                "to":             _fmt(end),
            }
            if expiry:
                params["expiryDate"] = expiry
            if option_type:
                params["optionType"] = option_type.upper()
            if strike_price is not None:
                params["strikePrice"] = str(strike_price)

            resp = self._session.get("historical/fo/derivatives", params=params)
            chunk = resp.get("data", []) if isinstance(resp, dict) else []
            rows.extend(chunk)

        rows.sort(key=lambda r: r.get("FH_TIMESTAMP", r.get("Date", "")))
        return rows
