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

    def event_calendar(self) -> list[dict]:
        """
        Comprehensive upcoming corporate event calendar from NSE.
        Returns all companies with scheduled board meetings, results announcements,
        dividends, AGMs, etc. across the current results season (~19 dates, ~490 entries).
        Each record has: symbol, companyName, purpose, bm_date (dd-MMM-YYYY).
        Unlike board_meetings(), this endpoint returns the full forward-looking calendar
        rather than only the 20 most-recently-filed meeting notices.
        """
        resp = self._session.get("event-calendar")
        return resp if isinstance(resp, list) else resp.get("data", resp)

    def corporate_pledge_data(self, symbol=None, from_date=None, to_date=None, index='equities'):
        """Promoter shares pledge data."""
        params = {'index': index}
        if symbol:
            params['symbol'] = symbol.upper()
        if from_date:
            params['from_date'] = from_date
        if to_date:
            params['to_date'] = to_date
        return (self._guardian.guarded_get if self._guardian else self._session.get)('corporate-pledgedata', params)

    def corporate_voting_results(self, symbol=None, from_date=None, to_date=None, index='equities'):
        """Shareholder voting results."""
        params = {'index': index}
        if symbol:
            params['symbol'] = symbol.upper()
        if from_date:
            params['from_date'] = from_date
        if to_date:
            params['to_date'] = to_date
        return (self._guardian.guarded_get if self._guardian else self._session.get)('corporate-voting-results', params)

    def corporate_actions_rights(self, symbol=None, from_date=None, to_date=None):
        """Rights issue corporate actions."""
        params = {'index': 'equities', 'subject': 'rights'}
        if symbol:
            params['symbol'] = symbol.upper()
        if from_date:
            params['from_date'] = from_date
        if to_date:
            params['to_date'] = to_date
        return (self._guardian.guarded_get if self._guardian else self._session.get)('corporates-corporateActions', params)

    def insider_trading_pit(self, symbol=None, from_date=None, to_date=None):
        """Insider trading disclosures (SEBI PIT)."""
        params = {'index': 'equities'}
        if symbol:
            params['symbol'] = symbol.upper()
        if from_date:
            params['from_date'] = from_date
        if to_date:
            params['to_date'] = to_date
        return (self._guardian.guarded_get if self._guardian else self._session.get)('corporates-pit', params)

    def sast_reg29(self, symbol=None, from_date=None, to_date=None, index='equities'):
        """SAST Regulation 29 substantial acquisition disclosures."""
        params = {'index': index}
        if symbol:
            params['symbol'] = symbol.upper()
        if from_date:
            params['from_date'] = from_date
        if to_date:
            params['to_date'] = to_date
        return (self._guardian.guarded_get if self._guardian else self._session.get)('corporate-sast-reg29', params)
