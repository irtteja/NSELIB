# nselib — Claude Session Bootstrap

Read these files at the start of every session, in order:

1. `PRD.md` — what the library is and must do
2. `Design.md` — architecture, modules, data flow
3. `Rules.md` — constraints every contributor must follow
4. `Tasks.md` — pending work items (check off when done)
5. `Progress.md` — dated log of decisions and changes

## Quick orientation

- Library: `nselib/` — Python package wrapping NSE India APIs
- Entry point: `nselib/nse.py` → `NSE` class (inherits all mixins)
- Modules: `nselib/modules/` — corporate, fno, history, indices, market, quotes, downloads
- Session: `nselib/core.py` → `NSESession` — manages Akamai cookies, rate-limiting
- Self-healing: `nselib/guardian.py` → `Guardian` — intercepts failures, patches via Claude
- Brain: `nselib/brain.py` — Claude API calls used by guardian for diagnosis and code generation
- Patches persist: `~/.nselib/patches.json` | Log: `~/.nselib/guardian_log.json`

## NSE IP restriction

NSE live API (`www.nseindia.com/api/*`) is blocked from cloud/datacenter IPs.
Only `nsearchives.nseindia.com` is accessible from any IP.
All methods that must work from cloud must use archive URLs.

## Key invariant

Every new method added via `guardian.apply()` MUST be wrapped with guardian.
Archive-based methods use `self._session._s.get(url)` directly (bypasses Akamai check).
