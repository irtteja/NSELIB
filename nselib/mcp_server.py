"""
nselib MCP server — exposes all NSE data methods as Claude tools.

Run on your laptop (residential IP) and connect to any Claude session:

    # Start the server
    python -m nselib.mcp_server

    # Or via entry point (after pip install)
    nselib-mcp

Then add to Claude Code:
    claude mcp add nselib -- python -m nselib.mcp_server

All NSE calls happen from your machine, bypassing cloud IP blocks.
"""

import json
from datetime import date, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from .nse import NSE

mcp = FastMCP("nselib", instructions=(
    "NSE India data server. Provides live quotes, indices, option chains, "
    "historical data, corporate events, and market breadth for NSE-listed instruments."
))

_nse = NSE()


def _json(obj: Any) -> str:
    def default(o):
        if isinstance(o, date):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=default, ensure_ascii=False)


# ── Quotes ────────────────────────────────────────────────────────────────

@mcp.tool()
def equity_quote(symbol: str) -> str:
    """Live OHLCV snapshot for an NSE equity. symbol e.g. RELIANCE, TCS, INFY."""
    return _json(_nse.equity_quote(symbol))


@mcp.tool()
def full_quote(symbol: str, series: str = "EQ") -> str:
    """Full NSE quote: OHLC, LTP, depth, 52w H/L, circuit limits. symbol e.g. RELIANCE."""
    return _json(_nse.quote(symbol, series))


@mcp.tool()
def equity_meta_info(symbol: str) -> str:
    """Company metadata: ISIN, series, FnO/ETF flags, suspended status."""
    return _json(_nse.equity_meta_info(symbol))


@mcp.tool()
def lookup(query: str, segment: str = "equity") -> str:
    """Search NSE by company name or symbol. segment: equity | derivatives | etf | all."""
    return _json(_nse.lookup(query, segment))


# ── Indices ───────────────────────────────────────────────────────────────

@mcp.tool()
def list_indices() -> str:
    """All 139 NSE indices with live value, change, P/E, P/B, advances/declines."""
    return _json(_nse.list_indices())


@mcp.tool()
def index_quote(index: str) -> str:
    """Live quote for one index. index e.g. 'NIFTY 50', 'NIFTY BANK', 'NIFTY IT'."""
    return _json(_nse.index_quote(index))


@mcp.tool()
def fetch_historical_index_data(
    index: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """
    Daily OHLC + turnover for an NSE index.
    index e.g. 'NIFTY 50'. Dates as YYYY-MM-DD. Defaults to last 30 days.
    """
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date)   if to_date   else None
    return _json(_nse.fetch_historical_index_data(index, from_date=fd, to_date=td))



# ── Market ────────────────────────────────────────────────────────────────

@mcp.tool()
def market_status() -> str:
    """Open/closed status for all NSE segments (CM, FO, CD, etc.)."""
    return _json(_nse.status())


@mcp.tool()
def holidays(type: str = "trading") -> str:
    """Exchange holiday calendar. type: trading | clearing."""
    return _json(_nse.holidays(type))


@mcp.tool()
def list_equity_stocks_by_index(index: str = "NIFTY 50") -> str:
    """All stocks in an index with live price and change. index e.g. 'NIFTY 50'."""
    return _json(_nse.list_equity_stocks_by_index(index))


@mcp.tool()
def top_gainers(index: str = "NIFTY 50", count: int = 10) -> str:
    """Top gainers in an index. Returns top `count` stocks sorted by % change."""
    data = _nse.list_equity_stocks_by_index(index)
    return _json(_nse.gainers(data, count))


@mcp.tool()
def top_losers(index: str = "NIFTY 50", count: int = 10) -> str:
    """Top losers in an index. Returns top `count` stocks sorted by % loss."""
    data = _nse.list_equity_stocks_by_index(index)
    return _json(_nse.losers(data, count))


@mcp.tool()
def advance_decline(index: str = "NIFTY 50") -> str:
    """Advance/decline/unchanged count and ratio for an index."""
    return _json(_nse.advance_decline(index))


@mcp.tool()
def pre_open(category: str = "ALL") -> str:
    """Pre-open IEP and order data (09:00–09:15 IST). category: NIFTY 50 | NIFTY BANK | ALL."""
    return _json(_nse.pre_open(category))


@mcp.tool()
def live_volume_gainers() -> str:
    """Stocks with unusual volume surge relative to their average."""
    return _json(_nse.live_volume_gainers())


@mcp.tool()
def block_deals() -> str:
    """Today's block deals."""
    return _json(_nse.block_deals())


@mcp.tool()
def bulk_deals(
    from_date: str | None = None,
    to_date: str | None = None,
    option_type: str = "bulk_deals",
) -> str:
    """
    Bulk/block/short-selling deals over a date range.
    option_type: bulk_deals | block_deals | short_selling. Dates as YYYY-MM-DD.
    """
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date)   if to_date   else None
    return _json(_nse.bulk_deals(option_type=option_type, from_date=fd, to_date=td))


# ── History ───────────────────────────────────────────────────────────────

@mcp.tool()
def fetch_equity_historical_data(
    symbol: str,
    from_date: str | None = None,
    to_date: str | None = None,
    days: int | None = None,
    series: str = "EQ",
) -> str:
    """
    Historical daily OHLCV for an equity.
    symbol e.g. RELIANCE. Dates as YYYY-MM-DD. Use days=30 for last N days.
    """
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date)   if to_date   else None
    return _json(_nse.fetch_equity_historical_data(symbol, from_date=fd, to_date=td, days=days, series=series))


@mcp.tool()
def fetch_historical_fno_data(
    symbol: str,
    from_date: str | None = None,
    to_date: str | None = None,
    instrument: str = "FUTIDX",
    expiry_date: str | None = None,
    strike_price: str = "-",
    option_type: str = "CE",
) -> str:
    """
    Historical F&O derivatives data.
    symbol e.g. NIFTY. instrument: FUTIDX | FUTSTK | OPTIDX | OPTSTK.
    """
    fd = date.fromisoformat(from_date)    if from_date    else None
    td = date.fromisoformat(to_date)      if to_date      else None
    ed = date.fromisoformat(expiry_date)  if expiry_date  else None
    return _json(_nse.fetch_historical_fno_data(
        symbol, from_date=fd, to_date=td,
        instrument_type=instrument, expiry_date=ed,
        strike_price=strike_price, option_type=option_type,
    ))


# ── Corporate ─────────────────────────────────────────────────────────────

@mcp.tool()
def corporate_actions(
    symbol: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """Dividends, splits, bonuses, rights issues. Omit symbol for all upcoming."""
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date)   if to_date   else None
    return _json(_nse.corporate_actions(symbol=symbol, from_date=fd, to_date=td))


@mcp.tool()
def announcements(
    symbol: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """Exchange announcements and disclosures. Omit symbol for all."""
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date)   if to_date   else None
    return _json(_nse.announcements(symbol=symbol, from_date=fd, to_date=td))


@mcp.tool()
def board_meetings(
    symbol: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """Scheduled and past board meetings with agenda."""
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date)   if to_date   else None
    return _json(_nse.board_meetings(symbol=symbol, from_date=fd, to_date=td))


@mcp.tool()
def financial_results(
    symbol: str | None = None,
    period: str = "Quarterly",
) -> str:
    """Quarterly/annual results filings. period: Quarterly | Annual | Six Month."""
    return _json(_nse.financial_results(symbol=symbol, period=period))


@mcp.tool()
def shareholding_patterns(symbol: str) -> str:
    """Quarterly shareholding pattern: promoter/FII/DII/public for a symbol."""
    return _json(_nse.shareholding_patterns(symbol))


@mcp.tool()
def annual_reports(symbol: str) -> str:
    """List of annual report PDFs for a company."""
    return _json(_nse.annual_reports(symbol))


@mcp.tool()
def insider_trading(
    symbol: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """SEBI insider trading (SAST) disclosures."""
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date)   if to_date   else None
    return _json(_nse.insider_trading(symbol=symbol, from_date=fd, to_date=td))


# ── F&O ───────────────────────────────────────────────────────────────────

@mcp.tool()
def option_chain(symbol: str) -> str:
    """Full option chain. Use NIFTY/BANKNIFTY for indices or any F&O equity symbol."""
    return _json(_nse.option_chain(symbol))


@mcp.tool()
def compile_option_chain(symbol: str, expiry: str | None = None) -> str:
    """
    Flattened option chain: strike rows with CE/PE data side-by-side.
    expiry as DD-Mon-YYYY e.g. '27-Nov-2025'. Defaults to nearest expiry.
    """
    return _json(_nse.compile_option_chain(symbol, expiry))


@mcp.tool()
def max_pain(symbol: str, expiry: str | None = None) -> str:
    """Max pain strike for an options expiry."""
    return _json(_nse.max_pain(symbol, expiry))


@mcp.tool()
def futures_quote(symbol: str) -> str:
    """Live futures quote for an index or stock."""
    return _json(_nse.futures_quote(symbol))


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
