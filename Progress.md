# nselib — Progress Log

Newest entries at top.

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
