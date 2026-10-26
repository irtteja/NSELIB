# nselib — Tasks

Format: `- [ ]` pending · `- [x]` done · `- [~]` blocked/deferred

## Core library

- [x] NSESession with Akamai cookie handling and rate limiting
- [x] Guardian — self-healing, schema adaptation, discover, apply, verify, watch
- [x] Brain — Claude API integration for guardian
- [x] MCP server exposing all methods as tools

## F&O module (fno.py)

- [x] `option_chain(symbol)` — raw option chain
- [x] `compile_option_chain(symbol, expiry)` — flattened CE/PE per strike
- [x] `max_pain(symbol, expiry)` — min pain strike
- [x] `pcr(symbol, expiry)` — put-call ratio (fixed: ce_oi/pe_oi field names, expiry field)
- [x] `fno_lots()` — lot sizes from archive
- [x] `fetch_fno_underlying()` — all F&O eligible symbols
- [x] `futures_quote(symbol)` — all-expiry futures data
- [x] `fno_ban_list(trade_date)` — cloud-safe archive method
- [x] `participant_oi(trade_date)` — FII/DII/Client/Pro OI, cloud-safe
- [x] `participant_volume(trade_date)` — FII/DII/Client/Pro volume, cloud-safe
- [x] `get_oi_spurts_underlyings()` / `get_oi_spurts_contracts()` — OI spurts
- [x] `get_derivatives_equity_snapshot(index)` — equity derivatives snapshot

## Corporate module (corporate.py)

- [x] `financial_results(symbol, period)` — raw filing list
- [x] `financial_results_detail(symbol, consolidated)` — XBRL parsed P&L + balance sheet + cash flow + segments + attribution + meta
- [x] `financial_results_links(symbol, period)` — details URL + XBRL URL per filing (replaced broken `financial_results_pdfs()`)
- [x] `corporate_actions(symbol)` — dividends, splits, bonuses
- [x] `announcements(symbol)` — company announcements
- [x] `board_meetings(symbol)` — board meeting dates
- [x] `board_meeting_detail(xml_url)` — parsed XBRL fields from board meeting intimation XML
- [x] `shareholding_patterns(symbol)` — promoter/FII/DII/public
- [x] `annual_reports(symbol)` — annual report links
- [x] `insider_trading(symbol)` — SAST/insider filings
- [x] `event_calendar()` — market-wide event calendar
- [x] `credit_ratings(symbol)` — credit rating history
- [x] `large_deals_snapshot()` — block/bulk deal snapshot

## Quotes module (quotes.py)

- [x] `quote(symbol, series)` — live equity quote
- [x] `equity_quote(symbol)` — alias
- [x] `equity_meta_info(symbol)` — company metadata
- [x] `lookup(query, segment)` — symbol search
- [x] `get_detailed_scrip_data(symbol)` — detailed scrip info
- [x] `get_equity_master()` — full equity master list

## History module (history.py)

- [x] `fetch_equity_historical_data(symbol, from_date, to_date)` — OHLCV bhavcopy
- [x] `fetch_historical_fno_data(symbol, from_date, to_date)` — F&O historical

## Indices module (indices.py)

- [x] `list_indices()` — all NSE indices
- [x] `index_quote(index)` — live index quote
- [x] `index_constituents(index)` — index stocks with weights
- [x] `snapshot_constituents(index)` — snapshot with live prices
- [x] `fetch_historical_index_data(index, from_date, to_date)` — index OHLCV
- [x] `constituent_changes(index)` — index inclusion/exclusion history
- [x] `build_comprehensive_latest()` — full snapshot all indices

## Market module (market.py)

- [x] `status()` — market open/close status
- [x] `holidays(type)` — trading/clearing holidays
- [x] `gainers(data, count)` / `losers(data, count)` — top movers
- [x] `advance_decline(index)` — A/D ratio
- [x] `pre_open(category)` — pre-open session data
- [x] `block_deals()` / `bulk_deals()` — deal data
- [x] `market_turnover()` — segment-wise turnover
- [x] `fii_dii_trade_activity()` — FII/DII daily trade stats

## Downloads module (downloads.py)

- [x] `equity_bhavcopy(date)` — equity bhavcopy CSV
- [x] `delivery_bhavcopy(date)` — delivery data CSV
- [x] `fno_bhavcopy(date)` — F&O bhavcopy
- [x] `indices_bhavcopy(date)` — indices bhavcopy
- [x] `bulk_equity_bhavcopy(from_date, to_date)` — multi-day download
- [x] `pr_bhavcopy(date)` — fixed: 2-digit year (`%d%m%y`) + `pr/` subdirectory in path
- [x] `cm_mii_security_report(date)` → renamed to `full_bhavcopy_delivery(date)` — fixed base path to `products/content/`
- [x] `full_bhavcopy_delivery(date)` — OHLCV + delivery % (3543 rows, cloud-safe)
- [x] `pe_ratio(date)` — P/E ratios for all listed stocks (~2262 rows)
- [x] `week52_high_low(date)` — 52-week adjusted H/L for all stocks (~5946 rows)
- [x] `short_selling(date)` — broker-reported short selling positions
- [x] `surveillance_indicator(date)` — GSM/ASM/IRP flags per stock (~3211 rows)
- [x] `bulk_deals_archive()` — today's bulk deals, rolling cloud-safe file
- [x] `block_deals_archive()` — today's block deals, rolling cloud-safe file
- [x] `margin_trading_disclosure(date)` — scrip-wise margin financing data + summary (2215 scrips)
- [x] `daily_volatility(date)` — EWMA daily + annualised volatility for all stocks (~4955 rows)
- [x] `priceband_changes(date)` — price band changes effective next trading day
- [x] `sme_bhavcopy(date)` — SME segment daily OHLCV + 52-week H/L (~467 rows)
- [x] `sme_price_band(date)` — SME segment complete price band list (~583 rows)
- [x] `haircut_approved_securities(date)` — NSCCL haircut % for approved equities (~1000 rows)
- [x] `haircut_mutual_funds(date)` — haircut for MF units accepted as collateral (~7000 rows)
- [x] `haircut_all_approved(date)` — combined haircut for all approved securities (~9000 rows)
- [x] `var_files(date)` — VaR margin data, 6 intraday snapshots merged (~113k rows)
- [x] `corporate_bonds_traded(date)` — corporate bonds OHLCV traded on NSE (~159 rows)
- [x] `market_activity_report(date)` — daily market summary stats (traded value, qty, trades, mkt cap)
- [x] `series_changes()` — rolling file: recent EQ/BE/SM series changes (~16 rows)
- [x] `auction_securities(date)` — securities confirmed for auction (uses daily-reports API for settlement no.)
- [x] `stt_non_applicability(date)` — securities exempt from STT (~12800 rows)
- [x] `stt_equity_funds(date)` — MF units classified as equity-oriented for STT (~1189 rows)
- [x] `circuit_square_off(date)` — securities squared off at circuit price (~13900 rows)
- [x] `latency_statistics()` — CM segment order latency percentiles (uses daily-reports API for filename)
- [x] `securities_list(date)` — all listed securities with series, price band, GSM/ASM remarks (~3598 rows)

## F&O module daily report files (fno.py)

- [x] `fo_settlement_prices(date)` — MTM settlement prices for all F&O contracts (~1316 rows)
- [x] `fo_daily_volatility(date)` — EWMA volatility for F&O underlyings (~224 rows)
- [x] `fo_exposure_limits(date)` — ELM + additional margin % per symbol/instrument (~426 rows)
- [x] `fo_delta_equivalent_oi(date)` — combined delta-equivalent OI across NSE+BSE (~222 rows)
- [x] `fo_contract_delta(date)` — NCL delta factors per F&O contract (~149k rows)
- [x] `fo_top10_clearing_members(date)` — top 10 clearing members by equity derivatives volume
- [x] `fo_index_position_limits(date)` — index derivatives position limits per investor category (~30 rows)
- [x] `fo_market_activity(date)` — complete F&O bhavcopy: futures (650 rows) + options (21626 rows)

## F&O module additions (fno.py)

- [x] `mwpl_oi(trade_date)` — NCL Open Interest / MWPL utilization (213 rows, flags ban-zone stocks)
- [x] `combined_oi(trade_date)` — Combined OI across NSE+BSE; shows which stocks have "No Fresh Positions"

## Health-check agent (healthcheck.py)

- [x] `HealthChecker` — full-cycle agent: test all methods → heal broken → discover/apply/verify → heal pipelines
- [x] `HealthChecker.run(nselib_dir)` — one-shot full cycle, returns + writes JSON report
- [x] `HealthChecker.watch(interval, nselib_dir)` — background daemon thread
- [x] `HealthChecker.last_report()` — load most recent saved report
- [ ] Expose `nse.health_check()` convenience wrapper on NSE class
- [ ] Add `HealthChecker` to `nselib/__init__.py` exports

## Rules / documentation

- [x] Rule 26–28: No API key needed in Claude sessions — documented in Rules.md

## Pending / future

- [ ] `vix_history(from_date, to_date)` — India VIX historical data from archive
- [ ] `fii_dii_historical(from_date, to_date)` — FII/DII historical from archive
- [ ] `circuit_breaker_history()` — stocks hitting upper/lower circuit
- [ ] `options_oi_history(symbol, expiry)` — EOD OI per strike over time
- [ ] Test suite — pytest covering all archive-based methods with known past dates
- [ ] CI — run tests on push, alert if >10% methods break
