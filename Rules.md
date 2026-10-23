# nselib — Rules

Hard constraints. Apply to all code, human or AI-generated.

## Architecture

1. Every new module method MUST be added to the correct mixin class (not to `NSE` directly).
2. Every method added via `guardian.apply()` MUST use `self._guardian.guarded_get()` if a guardian is attached, falling back to `self._session.get()`. Pattern:
   ```python
   return (self._guardian.guarded_get if self._guardian else self._session.get)(path, params)
   ```
3. Never import inside module-level scope what's already imported in `nselib/__init__.py`.
4. `NSESession._s` (raw requests.Session) is for archive URLs only. Never use it for live NSE API calls.

## Cloud / IP compatibility

5. Every method that hits `nsearchives.nseindia.com` is cloud-safe. Mark it clearly in docstring or Design.md.
6. Every method that hits `www.nseindia.com/api/` or `NextApi/` is cloud-blocked. Document this fact.
7. Archive methods MUST implement date fallback: try today, then D-1…D-4 (5 attempts). NSE doesn't publish on weekends/holidays.
8. Archive methods MUST check `b"DOCTYPE" not in r.content[:50]` before parsing — NSE returns HTML error pages for missing files.

## Data contracts

9. All methods return `list[dict]` or `dict`. Never return raw strings, bytes, or unparsed JSON.
10. Numeric fields from CSV (OI, volume, lot sizes) MUST be cast to `int` or `float`. Never return `"1,23,456"` as a string.
11. `financial_results_detail()` MUST return values in ₹ Crores (divide raw XBRL values by 10_000_000).
12. Option chain field names: `ce_ltp`, `ce_oi`, `ce_chg_oi`, `ce_volume`, `ce_iv`, `pe_*` (same). Do not rename.

## Guardian / self-healing

13. Patches MUST be saved to `~/.nselib/patches.json` after every successful heal.
14. Guardian log MUST be written to `~/.nselib/guardian_log.json`.
15. `verify()` gets at most 3 Claude fix attempts per method. Remove after 3 failures.
16. `discover()` MUST probe candidate endpoints live before generating method code — never generate code for unverified endpoints.

## Testing

17. Before marking any new method as working in `Tasks.md` or `Progress.md`, call it and confirm it returns non-empty data.
18. Archive-based methods must be tested with a known past date (not just `date.today()`) to confirm parsing is correct.

## Documentation

19. Update `Tasks.md` (check off) and `Progress.md` (add dated entry) after **every** change — no exceptions, even small fixes. Do it in the same commit as the code change.
20. After any `guardian.watch()`, `guardian.apply()`, or `guardian.verify()` run, read `~/.nselib/guardian_log.json` and record significant discoveries in `Progress.md`: new methods written, endpoints healed, methods removed after failed verification. Commit the log entry alongside any changed module files.
21. Do not use lorem ipsum or placeholder content anywhere.
22. Method docstrings: one line describing what it returns, not what it does internally. Include return type example if non-obvious.

## Naming

23. F&O ban list method: `fno_ban_list()` (not `fo_ban_list`, `ban_list`, `get_ban_list`).
24. Participant data: `participant_oi()` and `participant_volume()` — not "FII data" or "institutional".
25. PCR method: `pcr(symbol, expiry)` — not `put_call_ratio`.
