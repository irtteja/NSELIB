# nselib — Progress Log

Newest entries at top.

---

## 2026-10-23 (continued)

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
