from datetime import date, timedelta
from typing import Any


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


class CorporateMixin:
    """Corporate events: actions, announcements, results, filings."""

    def corporate_actions(
        self,
        symbol:    str | None = None,
        from_date: date | None = None,
        to_date:   date | None = None,
        series:    str = "EQ",
        segment:   str = "equities",
    ) -> list[dict]:
        """
        Dividends, splits, bonuses, rights issues, buy-backs.
        segment: 'equities' | 'sme' | 'debt'
        Omit symbol to get all upcoming actions.
        """
        to_date   = to_date   or date.today()
        from_date = from_date or (to_date - timedelta(days=30))
        params: dict = {
            "index":  segment,
            "series": series.upper(),
            "from":   _fmt(from_date),
            "to":     _fmt(to_date),
        }
        if symbol:
            params["symbol"] = symbol.upper()
        resp = self._session.get("corporates-corporateActions", params=params)
        return resp if isinstance(resp, list) else resp.get("data", resp)

    def announcements(
        self,
        symbol:   str | None = None,
        index:    str = "equities",
        from_date: date | None = None,
        to_date:   date | None = None,
    ) -> list[dict]:
        """
        Exchange announcements / disclosures.
        index: 'equities' | 'sme' | 'debt' | 'mf' | 'invit'
        """
        to_date   = to_date   or date.today()
        from_date = from_date or (to_date - timedelta(days=7))
        params: dict = {
            "index": index,
            "from":  _fmt(from_date),
            "to":    _fmt(to_date),
        }
        if symbol:
            params["symbol"] = symbol.upper()
        resp = self._session.get("corporate-announcements", params=params)
        return resp if isinstance(resp, list) else resp.get("data", resp)

    def board_meetings(
        self,
        symbol:    str | None = None,
        from_date: date | None = None,
        to_date:   date | None = None,
    ) -> list[dict]:
        """Scheduled and past board meetings with agenda."""
        to_date   = to_date   or date.today()
        from_date = from_date or (to_date - timedelta(days=30))
        params: dict = {
            "index": "equities",
            "from":  _fmt(from_date),
            "to":    _fmt(to_date),
        }
        if symbol:
            params["symbol"] = symbol.upper()
        resp = self._session.get("corporate-board-meetings", params=params)
        return resp if isinstance(resp, list) else resp.get("data", resp)

    def financial_results(
        self,
        symbol:    str | None = None,
        period:    str = "Quarterly",
        from_date: date | None = None,
        to_date:   date | None = None,
    ) -> list[dict]:
        """
        Quarterly / annual results filings.
        period: 'Quarterly' | 'Annual' | 'Six Month' | 'Others'
        """
        to_date   = to_date   or date.today()
        from_date = from_date or (to_date - timedelta(days=90))
        params: dict = {
            "index":  "equities",
            "period": period,
            "from":   _fmt(from_date),
            "to":     _fmt(to_date),
        }
        if symbol:
            params["symbol"] = symbol.upper()
        resp = self._session.get("corporates-financial-results", params=params)
        return resp if isinstance(resp, list) else resp.get("data", resp)

    def shareholding_patterns(
        self,
        symbol: str,
        from_date: date | None = None,
        to_date:   date | None = None,
    ) -> list[dict]:
        """
        Quarterly shareholding pattern (promoter / FII / DII / public).
        """
        resp = self._session.get(
            "top-corp-info",
            params={"symbol": symbol.upper(), "market": "equities"},
        )
        shp = resp.get("shareholdings_patterns", {}) if isinstance(resp, dict) else {}
        if isinstance(shp, dict):
            shp = shp.get("data", shp.get("shareholding", []))
        return shp if isinstance(shp, list) else []

    def annual_reports(self, symbol: str) -> list[dict]:
        """List of annual report PDFs for a company."""
        resp = self._session.get(
            "annual-reports",
            params={"symbol": symbol.upper(), "index": "cm"},
        )
        return resp if isinstance(resp, list) else resp.get("data", resp)

    def insider_trading(
        self,
        symbol:    str | None = None,
        from_date: date | None = None,
        to_date:   date | None = None,
    ) -> list[dict]:
        """
        SEBI insider trading disclosures (SAST / PIT).
        Pass a symbol for best results — NSE returns empty without one
        unless there happen to be bulk market-wide disclosures in the window.
        Default window is 90 days.
        """
        to_date   = to_date   or date.today()
        from_date = from_date or (to_date - timedelta(days=90))
        params: dict = {
            "from": _fmt(from_date),
            "to":   _fmt(to_date),
        }
        if symbol:
            params["symbol"] = symbol.upper()
        resp = self._session.get("corporates-pit", params=params)
        return resp if isinstance(resp, list) else resp.get("data", resp)
