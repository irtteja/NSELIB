# nselib — Design Document

## Class Hierarchy

```
NSE (nse.py)
 ├── QuotesMixin        (modules/quotes.py)
 ├── MarketMixin        (modules/market.py)
 ├── HistoryMixin       (modules/history.py)
 ├── IndicesMixin       (modules/indices.py)
 ├── FnoMixin           (modules/fno.py)
 ├── CorporateMixin     (modules/corporate.py)
 ├── DownloadsMixin     (modules/downloads.py)
 └── SourcesMixin       (modules/sources.py)
```

`NSE.__init__` creates an `NSESession`, optionally a `Guardian`, and passes both to all mixins via `self._session` and `self._guardian`.

## NSESession (core.py)

Manages the HTTP session against NSE India:
- Hits NSE homepage on init to obtain Akamai session cookies
- Cookie TTL ~5 min — auto-refreshes via background thread
- Rate-limited to 3 req/s
- `.get(path, params)` — hits `/api/<path>` with browser headers
- `.get_raw(url)` — hits arbitrary URL (used for archive files)
- `._s` — raw `requests.Session` (used by archive methods that skip Akamai handling)

**Two API bases:**
- `https://www.nseindia.com/api/` — live data, blocked from cloud IPs
- `https://nsearchives.nseindia.com/` — archive files, open to any IP

**NextApi base** (used by some F&O methods):
- `NextApi/apiClient/GetQuoteApi` — parameterised via `functionName`

## Guardian (guardian.py)

Self-healing layer — wraps `session.get()` calls.

```
guardian.guarded_get(path, params)
  │
  ├── try session.get()
  ├── on failure → brain.diagnose(path, error) → patched path/params
  ├── retry with patch → confirm fix
  ├── save patch to ~/.nselib/patches.json
  └── return data

guardian._check_and_heal_schema(data, method_name)
  ├── compare returned keys to expected schema
  ├── fuzzy-match renamed fields
  ├── brain fallback for ambiguous renames
  └── save remap to patches.json

guardian.discover()
  ├── ask brain what endpoints are missing
  ├── probe each candidate live
  └── return confirmed endpoints

guardian.apply(endpoints)
  ├── ask brain to generate method code
  ├── write to appropriate module file
  └── guarantee guardian wrapping

guardian.verify()
  ├── run each generated method
  ├── on failure → brain.fix() up to 3 attempts
  └── remove unfixable methods

guardian.watch(interval)
  └── background thread: discover() + apply() + verify() on interval
```

Patches file: `~/.nselib/patches.json`
Log file: `~/.nselib/guardian_log.json`

## Brain (brain.py)

Thin wrapper around the Claude API. Called by guardian for:
- Diagnosing broken endpoints
- Fuzzy-matching ambiguous schema renames
- Generating new method code
- Fixing failing methods

## SourceRegistry (sources.py) — dynamic discovery, no Claude needed

Self-maintaining map of every NSE page, API endpoint and archive file. `www.nseindia.in` is a Next.js
site reachable from cloud IPs; the registry reads it the way a browser would:

```
sitemap.xml (+nested) ∪ homepage links ∪ navbar API   → pages (~1.8k, ~230 app routes)
page HTML → /_next/static/chunks/*.js (content-hashed) → follow lazy chunks (BFS, cached by hash)
JS text  → /api/..., NextApi/...?functionName=..., nsearchives content/archives/products/*.csv|zip|…
probe    → GET each concrete source: ok | empty | template | needs-params | missing | error
diff     → new_pages, new_sources, removed_sources, broken, recovered   (history kept, last 20)
```

- A site redeploy changes chunk hashes ⇒ only changed chunks are re-read; new endpoints appear in the diff.
- `key` identity: APIs by path + `functionName`; dated archive files collapse to `{date}` templates
  (probe walks today → D-5, Rule 7). `?x=${e}` becomes `{x}` so `source_fetch(key, {"x": ...})` fills it.
- Domain failover `.in` → `.com`, active base remembered; `NSESession` does the same (`_prefer_in`).
- `refresh(browser=True)` additionally records runtime `/api/` calls from a real browser (`browser.py`,
  optional Playwright, no fingerprint masking) — catches dynamically-built URLs.
- Runs unattended: `Guardian.watch()` and `HealthChecker.run()` call it; `python -m nselib.sources --watch 3600`;
  `.github/workflows/refresh-sources.yml` re-crawls daily and commits `nselib/sources_seed.json`
  (shipped snapshot used on first run).
- Generic access (cloud-safe for `.in` + archives): `nse.sources_list/find()`, `source_pages()`,
  `source_fetch(key, params, trade_date)`, `sources_refresh()`. MCP exposes them automatically.
- Registry file: `~/.nselib/sources.json`.

## Module: fno.py

### Archive-based methods (cloud-safe)
- `fno_ban_list(trade_date)` — `nsearchives/archives/fo/sec_ban/fo_secban_DDMMYYYY.csv`
- `participant_oi(trade_date)` — `nsearchives/content/nsccl/fao_participant_oi_DDMMYYYY.csv`
- `participant_volume(trade_date)` — `nsearchives/content/nsccl/fao_participant_vol_DDMMYYYY.csv`
- `fno_lots()` — `nsearchives/content/fo/fo_mktlots.csv`

### Live methods (blocked from cloud)
- `option_chain(symbol)` — raw option chain via NextApi
- `compile_option_chain(symbol, expiry)` — flattened CE/PE rows per strike
- `max_pain(symbol, expiry)` — min total pain strike
- `pcr(symbol, expiry)` — put-call ratio from compiled chain
- `futures_quote(symbol)` — all expiry futures data

### Timing note
- Ban list: published before market open (same-day data)
- Participant OI/Volume: published after market close (~6-7 PM) — previous day until then

## Module: corporate.py

### Key methods
- `financial_results(symbol, period, from_date, to_date)` — raw filing list
- `financial_results_detail(symbol, consolidated)` — XBRL parsed → P&L in ₹ Crores
- `financial_results_links(symbol, period, from_date, to_date)` — NSE details URL + XBRL URL per filing
- `corporate_actions(symbol, from_date, to_date)` — dividends, splits, bonuses
- `shareholding_patterns(symbol)` — promoter/FII/DII/public %

### financial_results_detail flow
```
financial_results() → xbrl field URL
  → fetch XBRL XML
  → parse namespace-agnostic
  → extract P&L line items (revenue, EBITDA, PAT, EPS)
  → return list[dict] sorted by period descending
```

### financial_results_links
- `details_url` = `https://www.nseindia.com/companies-listing/corporate-filings-financial-results?params=<params>`
- `xbrl_url` = raw XBRL XML URL from API response `xbrl` field
- `params` field is always present in financial_results() response

## Module: history.py

- `fetch_equity_historical_data(symbol, from_date, to_date, series)` — OHLCV from bhavcopy
- `fetch_historical_fno_data(symbol, from_date, to_date)` — F&O historical data
- Uses bhavcopy CSVs from NSE archive — cloud-safe

## MCP Server (mcp_server.py)

Exposes all NSE methods as MCP tools. Auto-generated from method signatures.
