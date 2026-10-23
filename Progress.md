# nselib — Progress Log

Newest entries at top.

---

## 2026-10-23

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
