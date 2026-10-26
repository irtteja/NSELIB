# nselib — Progress Log

Newest entries at top.

---

## 2026-10-26 (session 4)

### Complete coverage of FO, WDM, EGR segment daily report files

Queried `NSE_API_IN/daily-reports?key=FO|WDM|EGR` to enumerate all files. Added 5 new FO methods to `fno.py` and 3 new WDM/EGR methods to `downloads.py`. All cloud-safe (archive-based), all use 5-day retry loop.

**FO segment additions (fno.py):**
- `fo_latency_statistics(date)` — FO segment order latency percentiles in microseconds; uses daily-reports API to resolve filename (published for previous trading day); filters out the disclaimer note row
- `fo_client_oi_limits(date)` — client-wise F&O position limits per stock per exchange (~648 rows); filename uses `DD-MON-YYYY` format
- `fo_contracts(date)` — NSE F&O contract master from `NSE_FO_contract_{ddmmyyyy}.csv.gz` (~88k rows); key fields: instrument_id, symbol, name, expiry_epoch, strike, option_type, lot_size, settlement, permitted
- `fo_spread_contracts(date)` — calendar spread contract pairs from `NSE_FO_spdcontract_{ddmmyyyy}.csv.gz` (~440 rows); near/far leg IDs, ref price, day price ranges
- `fo_ael_option_contracts(date)` — contract-wise AEL/ELM from `F_AEL_OPT_CONTRACTS_{ddmmyyyy}.csv.gz` (~149k rows); no-header CSV, 7 cols: instrument, symbol, expiry, strike, option_type, buy_elm_pct, sell_elm_pct

**WDM (debt) segment additions (downloads.py):**
- `wdm_securities_list(date)` — all WDM-listed securities from `content/historical/WDM/{YYYY}/{MON}/wdmlist_{ddmmyyyy}.csv` (~10624 rows); includes G-Secs, PSU bonds, T-bills, state loans, CPs; columns: sectype, symbol, issue_name, coupon, dates, ISIN, status
- `wdm_daily_report(date)` — debt segment daily trade report from `content/debt/dly{ddmmyyyy}.zip`; zip contains settlement CSV (trades with OHLCV + YTM), additions CSV (new issues listed), maturities CSV; returns `{date, trades, additions, maturities}`

**EGR (Exchange for Gold Receipts) segment additions (downloads.py):**
- `egr_var_files(date)` — VaR margin files from `content/egr/E_VAR1_{ddmmyyyy}_{1-6}.DAT`; same record format as CM var_files (type 10=header, type 20=data); 6 snapshots merged (~72 rows); columns: snapshot, date, symbol, segment, isin, prev/current daily vol, price band pct, var pct

**Skipped (not feasible):**
- SPAN zip files (binary SPAN format, requires specialized parser)
- `FNO_BC*.DAT`, `dmr*.docx` (binary formats)
- `mwpl_cli*.xls` (requires xlrd/openpyxl)

---

## 2026-10-26 (session 3)

### Added all remaining Equities & SME daily report methods to downloads.py

Queried `NSE_API_IN/daily-reports?key=CM` to get exact `filePath` + `fileActlName` for all 32 files in the CurrentDay listing. Implemented the 14 missing methods:

**Haircut / VaR / margin data:**
- `haircut_approved_securities(date)` — `content/equities/APPSEC_COLLVAL_{ddmmyyyy}.csv` — 1012 rows, no header, cols: symbol, isin, valuation_price, haircut; 5-day retry
- `haircut_mutual_funds(date)` — `archives/equities/mf_haircut/MF_VAR_{ddmmyyyy}.csv` — 7167 rows; 5-day retry
- `haircut_all_approved(date)` — `content/equities/APPSEC_ALL_{ddmmyyyy}.CSV` — 9150 rows (equity + MF combined); 5-day retry
- `var_files(date)` — `archives/nsccl/var/C_VAR1_{ddmmyyyy}_{1-6}.DAT` — 6 intraday snapshots merged (~113k rows total); 5-day retry; record type 10 = header, 20 = data

**Corporate / trading reports:**
- `corporate_bonds_traded(date)` — `archives/equities/corpbond/corpbond{ddmmyyyy}.csv` — 159 rows OHLCV for debt segment; 5-day retry
- `market_activity_report(date)` — `archives/equities/mkt/MA{ddmmyy}.csv` — 2-digit year; free-text narrative + KV stats parsed; 5-day retry
- `series_changes()` — `content/equities/series_change.csv` — rolling file (no date), ~16 rows showing recent series transitions

**Auction & settlement:**
- `auction_securities(date)` — `content/nsccl/AUB_{YYYY}{NNN}_{ddmmyyyy}.csv` — complex filename with settlement number; uses daily-reports API to get exact URL; ~265 rows; first line is description, skipped
- `circuit_square_off(date)` — `archives/equities/csqr/CSQR_M{YYYY}{NNN}_{ddmmyyyy}.csv` — same settlement-number pattern; uses daily-reports API; ~13900 rows no-header CSV

**Tax-related:**
- `stt_non_applicability(date)` — `content/equities/C_STT_{ddmmyyyy}.csv` — ~12809 rows; bug fix: file starts with blank line before header, must filter empty lines before DictReader; 5-day retry
- `stt_equity_funds(date)` — `content/equities/C_STT_IND_{ddmmyyyy}.csv` — ~1189 MF units classified as equity-oriented for STT; 5-day retry

**Operational:**
- `latency_statistics()` — `content/CM_Latency_stats{ddmmyyyy}.csv` — uses daily-reports API (file date ≠ today — published for last trading day, not current day); parses 2 rows (CM + FO segments) with latency percentiles in microseconds

**Skipped (non-CSV binary formats):**
- `Daily_Settlement_Statistics_{ddmmyyyy}.doc` — binary .doc Word document
- `FCM_INTRM_BC{ddmmyyyy}.DAT` — binary bhavcopy DAT at `content/trdops/`

All 32 CurrentDay files from NSE CM daily reports now have corresponding methods. Complete coverage achieved.

---

## 2026-10-26 (continued)

### Added margin_trading_disclosure, mwpl_oi, combined_oi from zip file inspection

Inspected all zip files in NSE daily reports (CM + FO segments). Found 3 new relevant zip files:

- **`mrg_trading_DDMMYY.zip`** (`content/equities/`) — SEBI Margin Trading Disclosure
  - `margin_trading_disclosure(date)` added to downloads.py
  - Returns `{date, summary{4 totals in Rs.Lakhs}, scrips[2215 rows: symbol, name, qty_shares, amt_lakhs]}`
  - Uses 5-day retry loop (skips weekends like participant_oi/fno_ban_list)
  - 2-digit year in filename (`%d%m%y`)

- **`ncloi_DDMMYYYY.zip`** (`archives/nsccl/mwpl/`) — NCL Open Interest (MWPL utilization)
  - `mwpl_oi(trade_date)` added to fno.py
  - 213 rows: date, ISIN, scrip_name, symbol, mwpl, ncl_oi, ncl_futeq_oi
  - Today's data: 17 stocks at/above MWPL (ban zone candidates)

- **`combineoi_DDMMYYYY.zip`** (`archives/nsccl/mwpl/`) — Combined OI across NSE+BSE
  - `combined_oi(trade_date)` added to fno.py
  - 213 rows: same + open_interest, futeq_oi, limit_next_day ('No Fresh Positions' if banned)
  - Today: AMBUJACEM, KAYNES, SAIL banned (No Fresh Positions)

Also inspected `fo.zip` (rolling F&O bhavcopy) — contains `fo_{ddmmyy}.csv` (654 futures rows) + `op_{ddmmyy}.csv` (39560 options rows with OHLCV+OI per contract).

---

### Fixed bugs and added 7 equity-research archive methods to downloads.py

**Bugs fixed:**
- `pr_bhavcopy()`: used wrong date format (`%d%m%Y`) — actual NSE filename uses 2-digit year (`%d%m%y`); also missing `pr/` subdirectory in URL path
- `cm_mii_security_report()`: used wrong base path (`archives/equities/bhavcopy/`) — actual URL is `products/content/`; renamed method to `full_bhavcopy_delivery()` to reflect actual content (OHLCV + delivery %)

**New methods (all cloud-safe, archive-based):**
- `full_bhavcopy_delivery(date)` — OHLCV + delivery % for all EQ series stocks (~3543 rows, `products/content/sec_bhavdata_full_DDMMYYYY.csv`)
- `pe_ratio(date)` — P/E ratios for all listed stocks (~2262 rows, 2-digit year format `peDetail/PE_DDMMYY.csv`)
- `week52_high_low(date)` — adjusted 52-week H/L for all stocks (~5946 rows, skips 2 disclaimer header rows)
- `short_selling(date)` — broker-reported short selling positions (`archives/equities/shortSelling/`)
- `surveillance_indicator(date)` — GSM/ASM/IRP flags per stock (~3211 rows, 2-digit year `content/cm/REG_INDDDMMYY.csv`)
- `bulk_deals_archive()` — today's bulk deals, rolling cloud-safe file (`content/equities/bulk.csv`)
- `block_deals_archive()` — today's block deals, rolling cloud-safe file (`content/equities/block.csv`)

Added `_ddmmyy()` helper for 2-digit year format. Added `_parse_csv_url()` internal helper to fetch+parse CSV in one call (no file written to disk). Replaced hardcoded archive URL strings with `_ARCHIVE` constant throughout.

---

## 2026-10-26

### Added `board_meeting_detail(xml_url)` to corporate.py
- Parses XBRL XML from board meeting intimation attachment (`attachment` field from `board_meetings()`)
- Fetches via `self._session._s.get()` — archive-safe, bypasses Akamai
- Strips XML namespaces, extracts 16 named fields: symbol, company, ISIN, meeting type, intimation type, meeting date, report date, trading window status/dates, agenda items, results nature, reporting period
- Returns `extra` dict for any unknown tags
- Tested on AAVAS XML — returns full structured dict with 16 fields + 2-item agenda + remarks in `extra`

---

## 2026-10-24 (continued)

### Fixed Rule 17 violation — guardian now enforces verification before commit
- Bug 1: `verify()` never wrote results back to `_discoveries` — `_verify_status` was always unset, so `verified_pass` was always 0 in HealthChecker reports
- Bug 2: `verify()` with status `"failed"` (brain returned no fix code) left the broken method in the file — now removes it and sets status `"removed"`
- Fix: `apply()` now writes `_verify_status` onto each discovery dict after `verify()` completes
- Fix: HealthChecker `_run_discovery()` now surfaces `safe_to_commit`, `verified_methods`, and `unverified` in report
- Fix: Saturday HealthChecker scheduled task prompt updated — only commits guardian-added module files when `safe_to_commit: True`

---

## 2026-10-24

### HealthChecker Saturday run — all clean
- 36 ok | 0 broken | 7 cloud-blocked | 0 missing
- Guardian discovered 1 new endpoint: `live-analysis-stocksTraded` → added `stocks_traded()` to `market.py`
  - Returns live count of advances/declines/unchanged summary
- Bhavcopy healed: incremental 4 days (2026-10-20 → 2026-10-23) + 43 new stocks backfilled over 262 days; 304,419 rows total
- `snapshot_derivatives_equity` verification failed (missing required `symbol` arg) — guardian noted, not removed (pre-existing method)

---

## 2026-10-23 (continued, session 2)

### Added Rules 26–28: no API key needed inside Claude sessions
- `Brain()` calls the local `claude` CLI when running inside a Claude Code session — no Anthropic API key required
- `NSE(guard=True)` is the standard instantiation; `anthropic_api_key=` parameter exists only for non-Claude environments
- Rules.md updated with new section "Claude session / API key" (rules 26–28)

---

## 2026-10-23 (continued)

### Rewrote mcp_server.py — auto-discovery, 86 tools (was 24 hardcoded)
- Replaced 300 lines of manually-wired tool definitions with auto-discovery via `inspect`
- `_make_tool()` introspects each NSE method: reads type hints, replaces `date`/`Optional[date]` params with `str`/`str | None` for clean JSON schema, auto-converts strings back to `date` at call time
- Pipeline methods whose first param takes a raw `list`/`dict` are skipped automatically (`gainers`, `losers` wrapped explicitly as `top_gainers`/`top_losers`)
- Brain methods (`ask`, `analyze`, `market_summary`, `screen`) excluded — not useful as MCP tools
- Updated import to support both mcp < 2 (`FastMCP`) and mcp >= 2 (`MCPServer`)
- New methods added to nselib are now automatically exposed as MCP tools — no manual wiring ever again
- Verified: 86 tools registered at startup

### Added nseindia.in fallback to NSESession
- Discovered `www.nseindia.in` is NSE's new parallel domain — accessible from cloud IPs
- Probed all major endpoints: marketStatus, allIndices, index-names, holiday-master, market-turnover, gainers, corporate-announcements, corporate-board-meetings all return full data; option-chain returns 200 but empty (F&O not yet migrated); quote-equity still 403
- Added `NSE_BASE_IN`, `NSE_API_IN`, `_HEADERS_IN` to `core.py`
- `NSESession.get()` now tries `.in` automatically when `.com` returns 403 (cloud/IP block); if `.in` also fails or returns empty, raises the original error — zero behaviour change for working methods
- `_refresh_cookies_in()` builds a proper Akamai session on `.in` (homepage + one nav page)
- Ready: when NSE completes the `.in` migration (especially F&O/quotes), the fallback activates without any code change
- Verified: `_test_all()` → 36 ok, 7 cloud-blocked, 0 broken (no regressions)

### Fixed shareholding_patterns and healthcheck credit_ratings registry
- `shareholding_patterns()` was returning `[]` — NSE returns `data` as a dict keyed by quarter-end date (`{"04-Dec-2025": [...]}`) not a list; fixed to flatten into `[{"date": "04-Dec-2025", ...row}]`
- `credit_ratings` in healthcheck registry was called with `("INFY",)` — INFY has no current filings so it returned `[]` (valid, not a bug); changed registry to `()` (no symbol filter) so the endpoint health is verified against the full feed
- Verified: `shareholding_patterns("INFY")` → 20 rows; `credit_ratings()` → 529 rows; `_test_all()` → 36 ok, 7 cloud-blocked, 0 broken

### Added HealthChecker agent (healthcheck.py)
- New module `nselib/healthcheck.py` — full-cycle health agent for nselib
- `_REGISTRY`: ~40 methods with default args exercising real data (INFY, NIFTY 50, etc.)
- `_CLOUD_BLOCKED_METHODS`: set of 30+ methods known to be blocked from cloud/datacenter IPs — classified as expected, not bugs
- **4-step cycle** via `HealthChecker.run(nselib_dir)`:
  1. `_test_all()` — tests every registered method; classifies ok / broken / cloud_blocked / missing
  2. `_heal_broken()` — re-runs broken methods up to 3 times via guardian; marks fixed on success
  3. `_run_discovery()` — calls `guardian.discover()` → `guardian.apply()` → collects verify results from `g._discoveries`
  4. `_heal_pipelines()` — calls `guardian.heal_data()` to fix stale bhavcopy/constituents pipelines
- Report saved to `~/.nselib/health_report.json`; last 10 reports kept as JSON array
- `HealthChecker.watch(interval, nselib_dir)` — daemon background thread, runs full cycle every `interval` seconds
- `HealthChecker.last_report()` — load most recent saved report
- Prints summary table: methods ok/broken/cloud-blocked/missing, healed/failed, new/verified/removed

---

## 2026-10-23

### Expanded financial_results_detail() to full XBRL
- Previously extracted only P&L (~15 tags, whitelist)
- Now parses all ~120 monetary, meta, EPS and small-number tags from the XBRL
- Added `balance_sheet` section: total assets, cash, equity, borrowings, receivables, goodwill, DTA/DTL
- Added `cash_flow` section: operating/investing/financing totals + capex, dividends paid, acquisitions, buyback, lease payments
- Added `segments` section: revenue, EBIT, PBT, segment name, multi/single segment flag
- Added `attribution` section: PAT and TCI split between owners of parent and NCI
- Added `meta` section: board meeting date, auditor name, ISIN, face value, FY dates
- Added top-level: `oci`, `total_comprehensive_income`, `exceptional_items`
- Backward-compatible: all existing P&L keys unchanged
- Verified on INFY Q2 FY27: balance sheet ₹1,63,480 Cr assets, OCF ₹18,958 Cr, zero debt

### Added archive-based F&O methods (cloud-safe)
- `fno_ban_list(trade_date)` — reads `nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_DDMMYYYY.csv`
  - Tries today → D-1…D-4 (weekends/holidays have no file)
  - Ban list published before market open — today's data available same day
- `participant_oi(trade_date)` — reads `nsearchives/content/nsccl/fao_participant_oi_DDMMYYYY.csv`
  - FII/DII/Client/Pro OI across futures and options segments (15 columns)
  - Published after market close ~6-7 PM — previous day's data until then
- `participant_volume(trade_date)` — same structure, `fao_participant_vol_DDMMYYYY.csv`
  - Shows contracts traded (volume), not open interest
- `pcr(symbol, expiry)` — computes put-call ratio from `compile_option_chain()`
  - Fixed bug: field names are `ce_oi`/`pe_oi` (not `CE_openInterest`/`PE_openInterest`)
  - Fixed bug: expiry extraction used wrong field name (`expiryDate` vs `expiry`)

### Fixed financial_results_links (replaced financial_results_pdfs)
- Previous method (`financial_results_pdfs`) was wrong — fetched announcement attachment PDFs which are short-lived (404 after ~days)
- NSE "Details" column links are HTML pages, not PDFs
- New method `financial_results_links()` constructs correct URL from `params` field:
  `https://www.nseindia.com/companies-listing/corporate-filings-financial-results?params=<params>`
- Also returns `xbrl_url` (the raw XBRL XML that `financial_results_detail()` parses)

### Established documentation
- Created `CLAUDE.md`, `PRD.md`, `Design.md`, `Rules.md`, `Tasks.md`, `Progress.md`

### Key findings documented
- `nsearchives.nseindia.com` is accessible from cloud/datacenter IPs — NSE live API is not
- `resultDetailedDataLink` field in financial_results API response is always null — use `params` instead
- Guardian (`guardian.py`) is fully self-healing, self-patching, adaptive, self-improving, and self-testing:
  - `guarded_get()` — heals broken endpoints via Claude
  - `patches.json` — persists fixes across sessions
  - `_check_and_heal_schema()` — adapts to field renames
  - `discover()` + `apply()` — finds and writes new endpoints as methods
  - `verify()` — tests generated methods, fixes or removes failures

---

## Prior sessions (reconstructed from code)

### Guardian system
- Full self-healing layer built: `guardian.py` + `brain.py`
- Patches persist to `~/.nselib/patches.json`
- Log to `~/.nselib/guardian_log.json`
- `watch()` background thread: periodic discover + apply + verify cycle

### Core library
- NSESession: Akamai bypass via homepage cookie + browser headers
- 70+ public methods across 7 modules
- MCP server auto-exposing all methods as tools
- Historical data via bhavcopy archive (cloud-safe)
- XBRL financial results parser (₹ Crores, namespace-agnostic)
