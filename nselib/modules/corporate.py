import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any

_XBRL_CRORE_TAGS = {
    "RevenueFromOperations", "OtherIncome", "Income",
    "EmployeeBenefitExpense", "FinanceCosts",
    "DepreciationDepletionAndAmortisationExpense", "OtherExpenses", "Expenses",
    "ProfitBeforeExceptionalItemsAndTax", "ExceptionalItems",
    "ProfitBeforeTax", "TaxExpense", "ProfitLossForPeriod",
    "ProfitLossForPeriodFromContinuingOperations",
    "TotalComprehensiveIncomeForPeriod",
}
_XBRL_META_TAGS = {
    "Symbol", "NameOfTheCompany", "ReportingQuarter",
    "DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod",
    "NatureOfReportStandaloneConsolidated", "LevelOfRoundingUsedInFinancialStatements",
    "WhetherResultsAreAuditedOrUnaudited",
}
_XBRL_EPS_TAGS = {
    "BasicEarningsLossPerShareFromContinuingOperations",
    "DilutedEarningsLossPerShareFromContinuingOperations",
    "BasicEarningsLossPerShareFromTotalOperations",
    "DilutedEarningsLossPerShareFromTotalOperations",
}
_ALL_XBRL_TAGS = _XBRL_CRORE_TAGS | _XBRL_META_TAGS | _XBRL_EPS_TAGS


def _parse_xbrl(xml_bytes: bytes) -> dict:
    """Parse an NSE Ind-AS XBRL file into a flat dict of financials."""
    root = ET.fromstring(xml_bytes)
    raw: dict = {}
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag in _ALL_XBRL_TAGS and tag not in raw:
            raw[tag] = (elem.text or "").strip()

    crore = 1e7
    out: dict = {}
    for k, v in raw.items():
        if not v:
            continue
        try:
            num = float(v)
            if k in _XBRL_EPS_TAGS:
                out[k] = round(num, 2)
            elif k in _XBRL_CRORE_TAGS:
                out[k] = round(num / crore, 2)
            else:
                out[k] = v
        except ValueError:
            out[k] = v
    return out


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

    def financial_results_detail(
        self,
        symbol:      str,
        consolidated: bool = True,
    ) -> list[dict]:
        """
        Structured quarterly P&L for a stock, parsed from NSE Integrated Filing XBRL.
        Returns one dict per quarter, newest first, with fields in ₹ Crores:

          symbol, company, quarter, period_start, period_end, type,
          revenue_from_operations, other_income, total_income,
          employee_costs, finance_costs, depreciation, other_expenses, total_expenses,
          ebit, pbt, tax, pat,
          eps_basic, eps_diluted

        Covers FY27 and onwards (integrated-filing-results endpoint).
        For older data use financial_results() + xbrl field.
        """
        resp = self._session.get(
            "integrated-filing-results",
            params={"symbol": symbol.upper(), "index": "equities"},
        )
        filings = resp.get("data", []) if isinstance(resp, dict) else resp

        nature = "Consolidated" if consolidated else "Standalone"
        results = []

        for filing in filings:
            if filing.get("type") != "Integrated Filing- Financials":
                continue
            if filing.get("consolidated", "").strip() != nature:
                continue
            xbrl_url = filing.get("xbrl", "")
            if not xbrl_url or xbrl_url.endswith("-"):
                continue

            try:
                r = self._session._s.get(xbrl_url, timeout=15)
                r.raise_for_status()
                xbrl = _parse_xbrl(r.content)
            except Exception:
                continue

            qe = filing.get("qe_Date", "")
            results.append({
                "symbol":                  xbrl.get("Symbol", symbol.upper()),
                "company":                 xbrl.get("NameOfTheCompany", ""),
                "quarter":                 xbrl.get("ReportingQuarter", ""),
                "period_start":            xbrl.get("DateOfStartOfReportingPeriod", ""),
                "period_end":              xbrl.get("DateOfEndOfReportingPeriod", qe),
                "type":                    nature,
                "audited":                 xbrl.get("WhetherResultsAreAuditedOrUnaudited", ""),
                "revenue_from_operations": xbrl.get("RevenueFromOperations"),
                "other_income":            xbrl.get("OtherIncome"),
                "total_income":            xbrl.get("Income"),
                "employee_costs":          xbrl.get("EmployeeBenefitExpense"),
                "finance_costs":           xbrl.get("FinanceCosts"),
                "depreciation":            xbrl.get("DepreciationDepletionAndAmortisationExpense"),
                "other_expenses":          xbrl.get("OtherExpenses"),
                "total_expenses":          xbrl.get("Expenses"),
                "ebit":                    (
                    round(xbrl["Income"] - xbrl["Expenses"] + xbrl.get("FinanceCosts", 0), 2)
                    if xbrl.get("Income") and xbrl.get("Expenses") else None
                ),
                "pbt":                     xbrl.get("ProfitBeforeTax"),
                "tax":                     xbrl.get("TaxExpense"),
                "pat":                     xbrl.get("ProfitLossForPeriod"),
                "eps_basic":               xbrl.get("BasicEarningsLossPerShareFromContinuingOperations")
                                           or xbrl.get("BasicEarningsLossPerShareFromTotalOperations"),
                "eps_diluted":             xbrl.get("DilutedEarningsLossPerShareFromContinuingOperations")
                                           or xbrl.get("DilutedEarningsLossPerShareFromTotalOperations"),
            })

        return results

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

    def credit_ratings(
        self,
        symbol: str | None = None,
        isin:   str | None = None,
    ) -> list[dict]:
        """
        Credit rating disclosures filed with NSE.
        Returns all recent filings — NSE does not support server-side filtering,
        so pass symbol or isin to filter client-side.

        Each record has: Symbol, CompanyName, ISIN, NameOfCRAgency, CreditRating,
        RatingAction, Outlook, DateofCR, CreditRatingEarlier, OutlookEarlier,
        DateOfCREarlier, BroadcastDateTime, XbrlFileName.
        """
        resp = self._session.get("corporate-credit-rating")
        data = resp if isinstance(resp, list) else resp.get("data", [])
        if symbol:
            sym = symbol.upper()
            data = [r for r in data
                    if (r.get("Symbol") or "").upper() == sym
                    or sym in (r.get("CompanyName") or "").upper()]
        if isin:
            data = [r for r in data if r.get("ISIN") == isin or r.get("ISIN_ER") == isin]
        return data

    def large_deals_snapshot(self):
        """Fetch the capital market large deals snapshot (bulk, block and short selling deals)."""
        path = "snapshot-capital-market-largedeal"
        params = {}
        return (self._guardian.guarded_get if self._guardian else self._session.get)(path, params)
