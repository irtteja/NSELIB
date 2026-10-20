from datetime import date, timedelta
from typing import Any


def _fmt(d: date) -> str:
    return d.strftime("%d-%b-%Y")


class MarketMixin:
    """
    Live market data: status, stock lists, gainers, losers,
    advance/decline, deals, pre-open, and holidays.
    """

    # ------------------------------------------------------------------ #
    #  Market status & holidays                                            #
    # ------------------------------------------------------------------ #

    def status(self) -> list[dict]:
        """Open/closed status for all NSE segments (CM, FO, CD, etc.)."""
        data = self._session.get("marketStatus")
        return data.get("marketState", data) if isinstance(data, dict) else data

    def holidays(self, type: str = "trading") -> dict:
        """
        Exchange holiday calendar.
        type: 'trading' | 'clearing'
        Returns dict keyed by segment (CM, FO, CD…).
        """
        return self._session.get("holiday-master", params={"type": type})

    # ------------------------------------------------------------------ #
    #  Stock universe                                                      #
    # ------------------------------------------------------------------ #

    def list_equity_stocks_by_index(self, index: str = "NIFTY 50") -> dict:
        """
        All stocks in a given index with live price and change data.
        Pass the result to gainers() / losers() / advance_decline().
        """
        return self._session.get(
            "equity-stockIndices",
            params={"index": index},
        )

    def list_etf(self) -> dict:
        """All ETFs listed on NSE."""
        return self._session.get("etf")

    def list_sme(self) -> dict:
        """SME / Emerge stocks."""
        return self._session.get("live-analysis-emerge-market")

    def list_sgb(self) -> dict:
        """Sovereign Gold Bonds."""
        return self._session.get("sovereign-gold-bond")

    # ------------------------------------------------------------------ #
    #  Gainers / losers / breadth                                         #
    # ------------------------------------------------------------------ #

    def gainers(self, data: dict, count: int | None = None) -> list[dict]:
        """
        Top gainers from a universe returned by list_equity_stocks_by_index().
        Sorted by pChange descending.
        """
        stocks = data.get("data", [])
        result = sorted(
            [s for s in stocks if s.get("pChange", 0) > 0],
            key=lambda s: s.get("pChange", 0),
            reverse=True,
        )
        return result[:count] if count else result

    def losers(self, data: dict, count: int | None = None) -> list[dict]:
        """
        Top losers. Sorted by pChange ascending (biggest loss first).
        """
        stocks = data.get("data", [])
        result = sorted(
            [s for s in stocks if s.get("pChange", 0) < 0],
            key=lambda s: s.get("pChange", 0),
        )
        return result[:count] if count else result

    def advance_decline(self, index: str = "NIFTY 50") -> dict:
        """
        Advance / decline / unchanged count for a given index.
        Computed from live stock data.
        """
        data   = self.list_equity_stocks_by_index(index)
        stocks = data.get("data", [])
        adv = sum(1 for s in stocks if s.get("pChange", 0) > 0)
        dec = sum(1 for s in stocks if s.get("pChange", 0) < 0)
        unc = sum(1 for s in stocks if s.get("pChange", 0) == 0)
        return {
            "index":    index,
            "advances": adv,
            "declines": dec,
            "unchanged": unc,
            "total":    len(stocks),
            "ratio":    round(adv / dec, 2) if dec else None,
        }

    def live_volume_gainers(self) -> dict:
        """Stocks with unusual volume surge relative to their average."""
        return self._session.get("live-analysis-volume-gainers")

    # ------------------------------------------------------------------ #
    #  Pre-open market                                                     #
    # ------------------------------------------------------------------ #

    def pre_open(self, category: str = "ALL") -> dict:
        """
        Pre-open session data (IEP, buy/sell qty, final price).
        Available 09:00–09:15 IST only.
        category: 'NIFTY 50' | 'NIFTY BANK' | 'ALL'
        """
        return self._session.get(
            "market-data-pre-open",
            params={"key": category},
        )

    # ------------------------------------------------------------------ #
    #  Block & bulk deals                                                  #
    # ------------------------------------------------------------------ #

    def block_deals(self) -> dict:
        """Today's block deals. Available during deal windows only."""
        return self._session.get("block-deal")

    def bulk_deals(
        self,
        option_type: str  = "bulk_deals",
        from_date:   date | None = None,
        to_date:     date | None = None,
    ) -> list[dict]:
        """
        Bulk / block / short-selling deals over a date range (max 365 days).
        option_type: 'bulk_deals' | 'block_deals' | 'short_selling'
        """
        to_date   = to_date   or date.today()
        from_date = from_date or (to_date - timedelta(days=7))

        if (to_date - from_date).days > 365:
            raise ValueError("Date range cannot exceed 365 days for bulk_deals()")
        if from_date > to_date:
            raise ValueError("from_date must be before to_date")

        resp = self._session.get(
            "bulk-deal-archives",
            params={
                "startDate":  _fmt(from_date),
                "endDate":    _fmt(to_date),
                "category":   option_type,
            },
        )
        return resp.get("data", resp) if isinstance(resp, dict) else resp
