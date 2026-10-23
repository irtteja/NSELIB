# nselib — Product Requirements Document

## Purpose

A Python library that provides clean, Pythonic access to NSE India market data — quotes, F&O, corporate filings, historical data, indices — with built-in self-healing so it stays functional without manual maintenance when NSE changes its APIs.

## Goals

1. **Full coverage** — every significant NSE data category exposed as typed Python methods
2. **Resilient** — auto-heals broken endpoints, adapts to schema drift, discovers new endpoints
3. **Cloud-usable** — all critical data accessible from datacenter/cloud IPs (not just residential)
4. **Zero-config** — works out of the box; guardian heals silently in the background
5. **MCP-ready** — exposes all methods as MCP tools for use by AI agents

## Non-goals

- No order placement / trading (read-only data only)
- No BSE or other exchanges (NSE only)
- No paid/subscription data
- No real-time websocket streaming (polling/request-response only)

## Data Categories

| Category | Module | Cloud IP? |
|---|---|---|
| Equity quotes (live) | quotes.py | ❌ blocked |
| Historical OHLCV | history.py | ✅ bhavcopy archive |
| Index quotes & constituents | indices.py | ❌ blocked |
| Market status, gainers/losers, pre-open | market.py | ❌ blocked |
| F&O option chain, max pain, PCR | fno.py | ❌ blocked (chain) |
| F&O ban list | fno.py | ✅ archive |
| Participant OI / Volume (FII/DII) | fno.py | ✅ archive |
| Lot sizes | fno.py | ✅ archive |
| Corporate actions, announcements | corporate.py | ❌ blocked |
| Financial results (XBRL parsed) | corporate.py | ❌ blocked |
| Shareholding patterns | corporate.py | ❌ blocked |
| Bhavcopy downloads | downloads.py | ✅ archive |

## User Profiles

- **Quant / algo trader** — needs option chain, PCR, participant OI, historical OHLCV
- **Fundamental analyst** — needs financial results (XBRL), shareholding, corporate actions
- **AI agent** — needs MCP server exposing all methods as tools

## Success Criteria

- All methods in scope return structured Python dicts/lists, not raw HTML/JSON
- Guardian heals ≥90% of endpoint breaks without human intervention
- Archive-based methods work reliably from any IP
- XBRL parser produces P&L in ₹ Crores across ≥4 quarters for any F&O-eligible stock
