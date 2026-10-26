import csv as _csv
import io as _io
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_ARCHIVE = "https://nsearchives.nseindia.com"


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d%m%Y")


def _ddmmyy(d: date) -> str:
    return d.strftime("%d%m%y")


def _ddmonyyyy(d: date) -> str:
    return d.strftime("%d%b%Y").upper()


def _monYYYY(d: date) -> str:
    return d.strftime("%b%Y").upper()


def _trading_days(from_date: date, to_date: date) -> list[date]:
    """Yield weekdays in [from_date, to_date]. Holiday filtering is best-effort."""
    out = []
    cur = from_date
    while cur <= to_date:
        if cur.weekday() < 5:   # Mon–Fri
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _parse_csv_url(session, url: str) -> list[dict]:
    """Fetch a CSV URL directly and return list of dicts (no file written)."""
    r = session._s.get(url, timeout=15)
    r.raise_for_status()
    reader = _csv.DictReader(_io.StringIO(r.text))
    return [row for row in reader]


class DownloadsMixin:
    """Bhavcopy downloads, equity research data, and document fetches."""

    # ------------------------------------------------------------------ #
    #  Bhavcopy — single day                                              #
    # ------------------------------------------------------------------ #

    def equity_bhavcopy(
                self,
                dt:     date | None = None,
                folder: str | Path  = ".",
            ) -> Path:
            """
            Download the equity bhavcopy CSV for a given date.
            dt defaults to yesterday. Weekends roll back to the previous weekday.
            Exchange holidays (e.g. Holi 03-Mar-2026) have no file and return 404,
            so the download falls back up to 7 prior weekdays until one is found.
            Returns the saved file path.
            """
            dt = dt or (date.today() - timedelta(days=1))
    
            def _prev_weekday(d):
                d -= timedelta(days=1)
                while d.weekday() >= 5:
                    d -= timedelta(days=1)
                return d
    
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)
    
            def _dl(first_url):
                d, last_err = dt, None
                for _ in range(8):
                    filename = f"BhavCopy_NSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv.zip"
                    try:
                        return self._session.download_zip(f"{_ARCHIVE}/content/cm/{filename}", folder=Path(folder))
                    except Exception as e:
                        last_err = e
                        d = _prev_weekday(d)
                raise last_err
    
            filename = f"BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip"
            url = f"{_ARCHIVE}/content/cm/{filename}"
            return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)

    def delivery_bhavcopy(
            self,
            dt:     date | None = None,
            folder: str | Path  = ".",
        ) -> Path:
            """Delivery position bhavcopy (MTO/delivery data)."""
            dt = dt or (date.today() - timedelta(days=1))
            # NSE publishes no file on weekends or exchange holidays; roll back to the last day with a file
            for _ in range(10):
                while dt.weekday() >= 5:
                    dt -= timedelta(days=1)
                filename = f"MTO_{_ddmmyyyy(dt)}.DAT"
                url = f"{_ARCHIVE}/archives/equities/mto/{filename}"
                probe = self._session._s.get(url, stream=True)
                status = probe.status_code
                probe.close()
                if status == 404:
                    dt -= timedelta(days=1)
                    continue
                _dl = lambda u: self._session.download_file(u, folder=Path(folder), filename=filename)
                return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)
            raise FileNotFoundError("No MTO delivery file found in the last 10 days")

    def fno_bhavcopy(
            self,
            dt:     date | None = None,
            folder: str | Path  = ".",
        ) -> Path:
            """F&O bhavcopy CSV."""
            dt = dt or (date.today() - timedelta(days=1))
            # NSE publishes no bhavcopy on weekends; step back to the last weekday
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)
            filename = f"BhavCopy_NSE_FO_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip"
            url = f"{_ARCHIVE}/content/fo/{filename}"
            _dl = lambda u: self._session.download_zip(u, folder=Path(folder))
            return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)

    def indices_bhavcopy(
            self,
            dt:     date | None = None,
            folder: str | Path  = ".",
        ) -> Path:
            """Index daily values bhavcopy CSV."""
            dt = dt or (date.today() - timedelta(days=1))
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)
            filename = f"ind_close_all_{_ddmmyyyy(dt)}.csv"
            url = f"{_ARCHIVE}/content/indices/{filename}"
            _dl = lambda u: self._session.download_file(u, folder=Path(folder), filename=filename)
            return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)

    def pr_bhavcopy(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """PR bhavcopy (all segments combined). Uses 2-digit year format."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"PR{_ddmmyy(dt)}.zip"
        url = f"{_ARCHIVE}/archives/equities/bhavcopy/pr/{filename}"
        _dl = lambda u: self._session.download_zip(u, folder=Path(folder))
        return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)

    def full_bhavcopy_delivery(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """
        Full bhavcopy with delivery data for all EQ series stocks.
        Columns: SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE,
                 LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY,
                 TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
        ~3543 rows per day.
        """
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"sec_bhavdata_full_{_ddmmyyyy(dt)}.csv"
        url = f"{_ARCHIVE}/products/content/{filename}"
        _dl = lambda u: self._session.download_file(u, folder=Path(folder), filename=filename)
        return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)

    # ------------------------------------------------------------------ #
    #  Bhavcopy — bulk range                                              #
    # ------------------------------------------------------------------ #

    def bulk_equity_bhavcopy(
        self,
        from_date: date,
        to_date:   date,
        folder:    str | Path = ".",
        workers:   int = 4,
    ) -> dict[date, Path | Exception]:
        """
        Download equity bhavcopy for every trading day in [from_date, to_date].
        Downloads in parallel (workers=4 by default).
        Returns {date: Path} for successes, {date: Exception} for failures
        (holidays and market closures will 404 — those come back as exceptions).
        """
        import concurrent.futures

        days = _trading_days(from_date, to_date)
        results: dict[date, Path | Exception] = {}

        def _fetch(dt: date):
            return dt, self.equity_bhavcopy(dt=dt, folder=folder)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch, d): d for d in days}
            for fut in concurrent.futures.as_completed(futures):
                dt = futures[fut]
                try:
                    _, path = fut.result()
                    results[dt] = path
                    print(f"  ✓ {dt}")
                except Exception as exc:
                    results[dt] = exc
                    print(f"  ✗ {dt} — {exc}")

        ok  = sum(1 for v in results.values() if isinstance(v, Path))
        err = len(results) - ok
        print(f"\nDone: {ok} downloaded, {err} failed (holidays/closures)")
        return results

    # ------------------------------------------------------------------ #
    #  Equity research data (cloud-safe, archive-based)                   #
    # ------------------------------------------------------------------ #

    def pe_ratio(self, dt: date | None = None) -> list[dict]:
        """
        P/E ratio for all listed stocks for a given date.
        Returns list of dicts with keys: SYMBOL, SYMBOL P/E, ADJUSTED P/E
        ~2262 rows. Uses 2-digit year format in filename.
        dt defaults to yesterday.
        """
        dt = dt or (date.today() - timedelta(days=1))
        url = f"{_ARCHIVE}/content/equities/peDetail/PE_{_ddmmyy(dt)}.csv"
        return _parse_csv_url(self._session, url)

    def week52_high_low(self, dt: date | None = None) -> list[dict]:
        """
        52-week adjusted high and low for all NSE stocks.
        Returns list of dicts with keys:
          SYMBOL, SERIES, Adjusted_52_Week_High, 52_Week_High_Date,
          Adjusted_52_Week_Low, 52_Week_Low_DT
        ~5946 rows. Skips 2 disclaimer header rows.
        dt defaults to yesterday.
        """
        dt = dt or (date.today() - timedelta(days=1))
        for i in range(5):
            check = dt - timedelta(days=i)
            if check.weekday() >= 5:
                continue
            url = f"{_ARCHIVE}/content/CM_52_wk_High_low_{_ddmmyyyy(check)}.csv"
            r = self._session._s.get(url, timeout=15)
            if r.status_code == 404 or (len(r.content) > 10 and b"DOCTYPE" in r.content[:200]):
                continue
            r.raise_for_status()
            lines = r.text.splitlines()
            # First 2 lines are disclaimer text, not CSV header
            data_text = "\n".join(lines[2:])
            reader = _csv.DictReader(_io.StringIO(data_text))
            return [row for row in reader]
        raise FileNotFoundError("No 52-week high/low file found in the last 5 trading days")

    def short_selling(self, dt: date | None = None) -> list[dict]:
        """
        Short selling positions reported by brokers for a given date.
        Returns list of dicts with keys:
          Security Name, Symbol Name, Trade Date, Quantity
        dt defaults to yesterday.
        """
        dt = dt or (date.today() - timedelta(days=1))
        for i in range(5):
            check = dt - timedelta(days=i)
            if check.weekday() >= 5:
                continue
            url = f"{_ARCHIVE}/archives/equities/shortSelling/shortselling_{_ddmmyyyy(check)}.csv"
            r = self._session._s.get(url, timeout=15)
            if r.status_code == 404 or (len(r.content) > 10 and b"DOCTYPE" in r.content[:200]):
                continue
            r.raise_for_status()
            reader = _csv.DictReader(_io.StringIO(r.text))
            return [row for row in reader]
        raise FileNotFoundError("No short selling file found in the last 5 trading days")

    def surveillance_indicator(self, dt: date | None = None) -> list[dict]:
        """
        Surveillance indicators for listed stocks (GSM, ASM, IRP, etc.).
        Returns list of dicts with keys:
          ScripCode, Symbol, Nse Exclusive, Status, Series,
          GSM, Long_Term_ASM, Unsolicited_SMS, IRP, Short_Term_ASM, ...
        ~3211 rows. Uses 2-digit year format.
        dt defaults to yesterday.
        """
        dt = dt or (date.today() - timedelta(days=1))
        for i in range(5):
            check = dt - timedelta(days=i)
            if check.weekday() >= 5:
                continue
            url = f"{_ARCHIVE}/content/cm/REG_IND{_ddmmyy(check)}.csv"
            r = self._session._s.get(url, timeout=15)
            if r.status_code == 404 or (len(r.content) > 10 and b"DOCTYPE" in r.content[:200]):
                continue
            r.raise_for_status()
            reader = _csv.DictReader(_io.StringIO(r.text))
            return [row for row in reader]
        raise FileNotFoundError("No surveillance indicator file found in the last 5 trading days")

    def daily_volatility(self, dt: date | None = None) -> list[dict]:
        """
        Daily and annualised volatility for all NSE-listed stocks.
        Computed using EWMA (lambda=0.995) on log returns.

        Returns list of dicts:
          symbol, close, prev_close, log_return,
          prev_daily_vol, current_daily_vol, annualised_vol
        ~5104 rows per day.
        dt defaults to today (published intraday).
        """
        dt = dt or date.today()
        url = f"{_ARCHIVE}/archives/nsccl/volt/CMVOLT_{_ddmmyyyy(dt)}.CSV"
        r = self._session._s.get(url, timeout=15)
        r.raise_for_status()
        reader = _csv.DictReader(_io.StringIO(r.text))
        out = []
        for row in reader:
            try:
                out.append({
                    "symbol":           (row.get("Symbol") or "").strip(),
                    "close":            float(row.get("Underlying Close Price (A)") or 0),
                    "prev_close":       float(row.get("Underlying Previous Day Close Price (B)") or 0),
                    "log_return":       float(row.get("Underlying Log Returns (C) = LN(A/B)") or 0),
                    "prev_daily_vol":   float(row.get("Previous Day Underlying Volatility (D)") or 0),
                    "current_daily_vol":float(row.get("Current Day Underlying Daily Volatility (E) = Sqrt(0.995*D*D + 0.005*C*C)") or 0),
                    "annualised_vol":   float(row.get("Underlying Annualised Volatility (F) = E*Sqrt(365)") or 0),
                })
            except (ValueError, KeyError):
                continue
        return out

    def securities_list(self, dt: date | None = None) -> list[dict]:
        """Complete list of securities with their trading series, price band, and surveillance remarks.

        Published daily; includes all series (EQ, BE, BZ, ST, etc.) with GSM/ASM flags.

        Returns: [{symbol, series, security_name, band, remarks}]
        """
        base = dt or (date.today() - timedelta(days=1))
        r = None
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/content/equities/sec_list_{_ddmmyyyy(check)}.csv"
            try:
                resp = self._session._s.get(url, timeout=15)
                if resp.status_code == 200 and b"DOCTYPE" not in resp.content[:50]:
                    r = resp
                    break
            except Exception:
                continue
        if not r:
            raise FileNotFoundError(f"securities_list: no file found near {base}")
        reader = _csv.DictReader(_io.StringIO(r.text))
        out = []
        for row in reader:
            sym = (row.get("Symbol") or "").strip()
            if not sym:
                continue
            out.append({
                "symbol":        sym,
                "series":        (row.get("Series") or "").strip(),
                "security_name": (row.get("Security Name") or "").strip(),
                "band":          (row.get("Band") or "").strip(),
                "remarks":       (row.get("Remarks") or "").strip().strip('"'),
            })
        return out

    def priceband_changes(self, dt: date | None = None) -> list[dict]:
        """
        Price band changes effective from the next trading date.
        Returns list of dicts: symbol, series, security_name, from_band, to_band
        dt defaults to today.
        """
        dt = dt or date.today()
        url = f"{_ARCHIVE}/content/equities/eq_band_changes_{_ddmmyyyy(dt)}.csv"
        r = self._session._s.get(url, timeout=15)
        r.raise_for_status()
        reader = _csv.DictReader(_io.StringIO(r.text))
        out = []
        for row in reader:
            sym = (row.get("Symbol") or "").strip()
            if not sym:
                continue
            out.append({
                "symbol":        sym,
                "series":        (row.get("Series") or "").strip(),
                "security_name": (row.get("Security Name") or "").strip(),
                "from_band":     (row.get("From") or "").strip(),
                "to_band":       (row.get("To") or "").strip(),
            })
        return out

    def sme_bhavcopy(self, dt: date | None = None) -> list[dict]:
        """
        SME (Small & Medium Enterprises) segment daily bhavcopy.
        Returns list of dicts: symbol, series, security, prev_close, open, high,
                               low, close, traded_value, traded_qty, hi_52wk, lo_52wk
        ~440 rows per day. dt defaults to most recent available trading day.
        """
        base = dt or (date.today() - timedelta(days=1))
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/archives/sme/bhavcopy/sme{_ddmmyyyy(check)}.csv"
            try:
                r = self._session._s.get(url, timeout=15)
                if r.status_code != 200 or b"DOCTYPE" in r.content[:50]:
                    continue
                reader = _csv.DictReader(_io.StringIO(r.text))
                out = []
                for row in reader:
                    sym = (row.get("SYMBOL") or "").strip()
                    if not sym:
                        continue
                    def _f(k, _row=row): return float((_row.get(k) or "0").strip() or 0)
                    out.append({
                        "symbol":       sym,
                        "series":       (row.get("SERIES") or "").strip(),
                        "security":     (row.get("SECURITY") or "").strip(),
                        "prev_close":   _f("PREV_CL_PR"),
                        "open":         _f("OPEN_PRICE"),
                        "high":         _f("HIGH_PRICE"),
                        "low":          _f("LOW_PRICE"),
                        "close":        _f("CLOSE_PRICE"),
                        "traded_value": _f("NET_TRDVAL"),
                        "traded_qty":   _f("NET_TRDQTY"),
                        "hi_52wk":      _f("HI_52_WK"),
                        "lo_52wk":      _f("LO_52_WK"),
                    })
                return out
            except Exception:
                continue
        return []

    def sme_price_band(self, dt: date | None = None) -> list[dict]:
        """
        SME segment complete price band list.
        Returns list of dicts: symbol, series, name, band, remarks
        dt defaults to most recent available trading day.
        """
        base = dt or (date.today() - timedelta(days=1))
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/sme/content/price_band/archieves/sme_bands_complete_{_ddmmyyyy(check)}.csv"
            try:
                r = self._session._s.get(url, timeout=15)
                if r.status_code == 200 and b"DOCTYPE" not in r.content[:50]:
                    reader = _csv.DictReader(_io.StringIO(r.text))
                    return [row for row in reader]
            except Exception:
                continue
        return []

    def bulk_deals_archive(self) -> list[dict]:
        """
        Today's bulk deals (rolling file — always reflects the current trading day).
        Returns list of dicts with keys:
          Date, Symbol, Security Name, Client Name, Buy/Sell,
          Quantity Traded, Trade Price / Wght. Avg. Price, Remarks
        Cloud-safe: uses nsearchives.nseindia.com.
        """
        url = f"{_ARCHIVE}/content/equities/bulk.csv"
        return _parse_csv_url(self._session, url)

    def block_deals_archive(self) -> list[dict]:
        """
        Today's block deals (rolling file — always reflects the current trading day).
        Same schema as bulk_deals_archive().
        Cloud-safe: uses nsearchives.nseindia.com.
        """
        url = f"{_ARCHIVE}/content/equities/block.csv"
        return _parse_csv_url(self._session, url)

    def margin_trading_disclosure(self, dt: date | None = None) -> dict:
        """
        SEBI margin trading disclosure for a given date.
        Published for previous trading day. Uses 2-digit year format.

        Returns dict with:
          'date'    : reporting date string
          'summary' : {total_outstanding_start, fresh_exposure, exposure_liquidated,
                       net_outstanding_end}  — all in Rs. Lakhs
          'scrips'  : list of dicts {symbol, name, qty_shares, amt_lakhs}
        """
        import zipfile as _zipfile
        base = dt or (date.today() - timedelta(days=1))
        raw = None
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/content/equities/mrg_trading_{_ddmmyy(check)}.zip"
            try:
                r = self._session._s.get(url, timeout=15)
                if r.status_code == 200 and b"DOCTYPE" not in r.content[:50]:
                    with _zipfile.ZipFile(_io.BytesIO(r.content)) as zf:
                        raw = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
                    break
            except Exception:
                continue
        if raw is None:
            return {"date": "", "summary": {}, "scrips": []}

        lines = raw.splitlines()
        report_date = lines[0].split("Reporting date")[-1].strip().rstrip(",").strip()

        # Summary rows: lines 3-6 have Sr.No., Particulars, Rs. In Lakhs
        summary_keys = [
            "total_outstanding_start",
            "fresh_exposure",
            "exposure_liquidated",
            "net_outstanding_end",
        ]
        summary: dict = {}
        summary_idx = 0
        for line in lines[3:9]:
            parts = [p.strip() for p in line.split(",")]
            if parts[0].isdigit() and summary_idx < 4:
                try:
                    summary[summary_keys[summary_idx]] = float(parts[2])
                except (ValueError, IndexError):
                    pass
                summary_idx += 1

        # Scrip data: find header row, then read CSV from there
        scrip_start = next(
            (i for i, l in enumerate(lines) if l.startswith("Symbol,")), None
        )
        scrips: list[dict] = []
        if scrip_start is not None:
            reader = _csv.DictReader(_io.StringIO("\n".join(lines[scrip_start:])))
            for row in reader:
                sym = (row.get("Symbol") or "").strip()
                if not sym:
                    continue
                try:
                    qty = int(row.get("Qty Fin by all the members(No.of Shares)", "0").replace(",", "") or 0)
                except ValueError:
                    qty = 0
                try:
                    amt = float(row.get("Amt Fin by all the members(Rs. In Lakhs)", "0").replace(",", "") or 0)
                except ValueError:
                    amt = 0.0
                scrips.append({
                    "symbol": sym,
                    "name":   (row.get("Name") or "").strip(),
                    "qty_shares": qty,
                    "amt_lakhs":  amt,
                })

        return {"date": report_date, "summary": summary, "scrips": scrips}

    # ------------------------------------------------------------------ #
    #  Daily reports                                                       #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Haircut / VaR / margin files                                       #
    # ------------------------------------------------------------------ #

    def haircut_approved_securities(self, dt: date | None = None) -> list[dict]:
        """Haircut (VaR margin) for NSCCL-approved securities — ~4000 rows.

        Returns: [{symbol, isin, valuation_price, haircut}]
        """
        base = dt or (date.today() - timedelta(days=1))
        r = None
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/content/equities/APPSEC_COLLVAL_{_ddmmyyyy(check)}.csv"
            try:
                resp = self._session._s.get(url, timeout=15)
                if resp.status_code == 200 and b"DOCTYPE" not in resp.content[:50]:
                    r = resp
                    break
            except Exception:
                continue
        if not r:
            raise FileNotFoundError(f"haircut_approved_securities: no file found near {base}")
        out = []
        for line in r.text.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                try:
                    out.append({
                        "symbol":          parts[1],
                        "isin":            parts[2],
                        "valuation_price": float(parts[3]),
                        "haircut":         float(parts[4]),
                    })
                except (ValueError, IndexError):
                    continue
        return out

    def haircut_mutual_funds(self, dt: date | None = None) -> list[dict]:
        """Haircut for mutual fund units accepted as collateral — all MF ISIN rows.

        Returns: [{isin, symbol, series, type, haircut, nav}]
        """
        base = dt or (date.today() - timedelta(days=1))
        r = None
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/archives/equities/mf_haircut/MF_VAR_{_ddmmyyyy(check)}.csv"
            try:
                resp = self._session._s.get(url, timeout=15)
                if resp.status_code == 200 and b"DOCTYPE" not in resp.content[:50]:
                    r = resp
                    break
            except Exception:
                continue
        if not r:
            raise FileNotFoundError(f"haircut_mutual_funds: no file found near {base}")
        reader = _csv.DictReader(_io.StringIO(r.text))
        out = []
        for row in reader:
            try:
                out.append({
                    "isin":    (row.get("ISIN") or "").strip(),
                    "symbol":  (row.get("SYMBOL") or "").strip(),
                    "series":  (row.get("SERIES") or "").strip(),
                    "type":    (row.get("TYPE") or "").strip(),
                    "haircut": float((row.get("HAIRCUT") or "0").strip() or 0),
                    "nav":     float((row.get("NAV") or "0").strip() or 0),
                })
            except (ValueError, TypeError):
                continue
        return out

    def haircut_all_approved(self, dt: date | None = None) -> list[dict]:
        """Haircut for ALL approved securities (equity + MF combined) — ~4000 rows.

        Returns: [{symbol, isin, valuation_price, haircut}]
        """
        base = dt or (date.today() - timedelta(days=1))
        r = None
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/content/equities/APPSEC_ALL_{_ddmmyyyy(check)}.CSV"
            try:
                resp = self._session._s.get(url, timeout=15)
                if resp.status_code == 200 and b"DOCTYPE" not in resp.content[:50]:
                    r = resp
                    break
            except Exception:
                continue
        if not r:
            raise FileNotFoundError(f"haircut_all_approved: no file found near {base}")
        reader = _csv.DictReader(_io.StringIO(r.text))
        out = []
        for row in reader:
            sym = (row.get("Symbol") or "").strip()
            if not sym:
                continue
            try:
                out.append({
                    "symbol":          sym,
                    "isin":            (row.get("ISIN") or "").strip(),
                    "valuation_price": float((row.get("Valuation Price") or "0").strip() or 0),
                    "haircut":         float((row.get("Applicable Haircut") or "0").strip() or 0),
                })
            except (ValueError, TypeError):
                continue
        return out

    def var_files(self, dt: date | None = None) -> list[dict]:
        """VaR (Value at Risk) margin data for all securities — 6 intraday snapshots.

        NSE publishes 6 VaR files per day (_1 = begin-of-day, _2-5 = intraday, _6 = end-of-day).
        Returns all 6 merged; each row has a 'snapshot' field (1–6).

        Returns: [{snapshot, symbol, series, isin, short_term_var, index_var, applicable_var, ...}]
        """
        base = dt or (date.today() - timedelta(days=1))
        # Find the most recent trading day that has VaR files
        found_dt = None
        for offset in range(5):
            check = base - timedelta(days=offset)
            test_url = f"{_ARCHIVE}/archives/nsccl/var/C_VAR1_{_ddmmyyyy(check)}_1.DAT"
            try:
                resp = self._session._s.get(test_url, timeout=15)
                if resp.status_code == 200 and b"DOCTYPE" not in resp.content[:50]:
                    found_dt = check
                    break
            except Exception:
                continue
        if not found_dt:
            raise FileNotFoundError(f"var_files: no files found near {base}")
        out = []
        for snap in range(1, 7):
            url = f"{_ARCHIVE}/archives/nsccl/var/C_VAR1_{_ddmmyyyy(found_dt)}_{snap}.DAT"
            r = self._session._s.get(url, timeout=15)
            if r.status_code != 200:
                continue
            for line in r.text.splitlines():
                parts = line.strip().split(",")
                if not parts or parts[0] != "20":
                    continue
                if len(parts) < 10:
                    continue
                try:
                    out.append({
                        "snapshot":         snap,
                        "symbol":           parts[1],
                        "series":           parts[2],
                        "isin":             parts[3],
                        "price_scan_range": float(parts[4] or 0),
                        "short_term_var":   float(parts[5] or 0),
                        "index_var":        float(parts[6] or 0),
                        "applicable_var":   float(parts[7] or 0),
                        "adhoc_margin":     float(parts[8] or 0),
                        "total_var":        float(parts[9] or 0),
                    })
                except (ValueError, IndexError):
                    continue
        return out

    # ------------------------------------------------------------------ #
    #  Corporate / trading reports                                         #
    # ------------------------------------------------------------------ #

    def corporate_bonds_traded(self, dt: date | None = None) -> list[dict]:
        """Corporate bonds traded on NSE for the given date.

        Returns: [{symbol, security, series, prev_close, open, high, low, close,
                   traded_value, traded_qty, trades, hi_52wk, lo_52wk}]
        """
        base = dt or (date.today() - timedelta(days=1))
        r = None
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/archives/equities/corpbond/corpbond{_ddmmyyyy(check)}.csv"
            try:
                resp = self._session._s.get(url, timeout=15)
                if resp.status_code == 200 and b"DOCTYPE" not in resp.content[:50]:
                    r = resp
                    break
            except Exception:
                continue
        if not r:
            raise FileNotFoundError(f"corporate_bonds_traded: no file found near {base}")
        rows = list(_csv.DictReader(_io.StringIO(r.text)))
        out = []
        for row in rows:
            sym = (row.get("SYMBOL") or "").strip()
            if not sym:
                continue
            def _f(k): return float((row.get(k) or "0").strip().replace(",", "") or 0)
            out.append({
                "symbol":       sym,
                "security":     (row.get("SECURITY") or "").strip(),
                "series":       (row.get("SERIES") or "").strip(),
                "prev_close":   _f("PREV_CL_PR"),
                "open":         _f("OPEN_PRICE"),
                "high":         _f("HIGH_PRICE"),
                "low":          _f("LOW_PRICE"),
                "close":        _f("CLOSE_PRICE"),
                "traded_value": _f("NET_TRDVAL"),
                "traded_qty":   int(_f("NET_TRDQTY")),
                "trades":       int(_f("TRADES")),
                "hi_52wk":      _f("HI_52_WK"),
                "lo_52wk":      _f("LO_52_WK"),
            })
        return out

    def market_activity_report(self, dt: date | None = None) -> dict:
        """Market Activity Report — daily market summary statistics.

        Returns: {date, traded_value_cr, traded_qty_lakhs, num_trades,
                  market_cap_cr, text (raw narrative)}
        """
        base = dt or (date.today() - timedelta(days=1))
        r = None
        found_dt = base
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/archives/equities/mkt/MA{_ddmmyy(check)}.csv"
            try:
                resp = self._session._s.get(url, timeout=15)
                if resp.status_code == 200 and b"DOCTYPE" not in resp.content[:50]:
                    r = resp
                    found_dt = check
                    break
            except Exception:
                continue
        if not r:
            raise FileNotFoundError(f"market_activity_report: no file found near {base}")
        text = r.text

        def _extract(label: str) -> str | None:
            for line in text.splitlines():
                if label.lower() in line.lower():
                    parts = line.split(",")
                    for p in reversed(parts):
                        v = p.strip().replace(",", "")
                        try:
                            float(v)
                            return v
                        except ValueError:
                            continue
            return None

        return {
            "date":              found_dt.isoformat(),
            "traded_value_cr":   _extract("Traded Value"),
            "traded_qty_lakhs":  _extract("Traded Quantity"),
            "num_trades":        _extract("Number of Trades"),
            "market_cap_cr":     _extract("Market Capitalisation"),
            "text":              text.strip(),
        }

    def series_changes(self) -> list[dict]:
        """Recent series changes for NSE-listed securities (rolling file, no date param).

        Returns: [{symbol, security, from_series, to_series, change_date, remarks}]
        """
        url = f"{_ARCHIVE}/content/equities/series_change.csv"
        rows = _parse_csv_url(self._session, url)
        out = []
        for row in rows:
            sym = (row.get("Symbol") or "").strip()
            if not sym:
                continue
            out.append({
                "symbol":      sym,
                "security":    (row.get("Security") or "").strip(),
                "from_series": (row.get("From Series") or "").strip(),
                "to_series":   (row.get("To Series") or "").strip(),
                "change_date": (row.get("Change Date") or "").strip(),
                "remarks":     (row.get("Remarks") or "").strip(),
            })
        return out

    def auction_securities(self, dt: date | None = None) -> dict:
        """List of securities confirmed for auction on the given date.

        NSE filename contains the settlement number (e.g. AUB_2026200_26102026.csv);
        this method queries the daily-reports API to find the correct URL.

        Returns: {settlement_ref, auction_date, securities: [{symbol, series, total_qty}]}
        """
        import re
        dt = dt or date.today()
        # Find the file URL via the daily-reports metadata API
        try:
            r_meta = self._session._s.get(
                "https://www.nseindia.in/api/daily-reports?key=CM", timeout=15
            )
            data = r_meta.json()
            items = data.get("CurrentDay", []) + data.get("PreviousDay", [])
            aub_item = next(
                (i for i in items if (i.get("fileActlName") or "").startswith("AUB_")),
                None,
            )
            if aub_item:
                file_url = aub_item["filePath"].rstrip("/") + "/" + aub_item["fileActlName"]
                settlement_ref = re.search(r"AUB_(\d+)_", aub_item["fileActlName"])
                settlement_ref = settlement_ref.group(1) if settlement_ref else ""
            else:
                settlement_ref = ""
                file_url = None
        except Exception:
            file_url = None
            settlement_ref = ""

        if not file_url:
            raise FileNotFoundError("Could not locate auction securities file via NSE API")

        r = self._session._s.get(file_url, timeout=15)
        r.raise_for_status()
        lines = r.text.splitlines()
        # First line is description, skip it; data starts after header "Sr No,Symbol,..."
        header_idx = next((i for i, l in enumerate(lines) if l.startswith("Sr No,")), 1)
        rows = _csv.DictReader(_io.StringIO("\n".join(lines[header_idx:])))
        securities = []
        for row in rows:
            sym = (row.get("Symbol") or "").strip()
            if not sym:
                continue
            try:
                qty = int((row.get("Total Qty") or "0").strip().replace(",", "") or 0)
            except ValueError:
                qty = 0
            securities.append({
                "symbol":    sym,
                "series":    (row.get("Series") or "").strip(),
                "total_qty": qty,
            })
        return {
            "settlement_ref": settlement_ref,
            "auction_date":   dt.isoformat(),
            "securities":     securities,
        }

    def stt_non_applicability(self, dt: date | None = None) -> list[dict]:
        """STT Non-applicability Report — securities exempt from STT.

        Returns: [{symbol, series, description, isin}]
        """
        base = dt or (date.today() - timedelta(days=1))
        r = None
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/content/equities/C_STT_{_ddmmyyyy(check)}.csv"
            try:
                resp = self._session._s.get(url, timeout=15)
                if resp.status_code == 200 and b"DOCTYPE" not in resp.content[:50]:
                    r = resp
                    break
            except Exception:
                continue
        if not r:
            raise FileNotFoundError(f"stt_non_applicability: no file found near {base}")
        # File starts with a blank line before the header row — skip empty lines
        lines = [l for l in r.text.splitlines() if l.strip()]
        reader = _csv.DictReader(_io.StringIO("\n".join(lines)))
        out = []
        for row in reader:
            sym = (row.get("SYMBOL") or "").strip()
            if not sym:
                continue
            out.append({
                "symbol":      sym,
                "series":      (row.get("SERIES") or "").strip(),
                "description": (row.get("DESCRIPTION") or "").strip(),
                "isin":        (row.get("ISIN") or "").strip(),
            })
        return out

    def stt_equity_funds(self, dt: date | None = None) -> list[dict]:
        """STT Equity Oriented Funds — mutual funds classified as equity-oriented for STT.

        Returns: [{symbol, series, isin, sec_desc, stt_indicator}]
        """
        base = dt or (date.today() - timedelta(days=1))
        r = None
        for offset in range(5):
            check = base - timedelta(days=offset)
            url = f"{_ARCHIVE}/content/equities/C_STT_IND_{_ddmmyyyy(check)}.csv"
            try:
                resp = self._session._s.get(url, timeout=15)
                if resp.status_code == 200 and b"DOCTYPE" not in resp.content[:50]:
                    r = resp
                    break
            except Exception:
                continue
        if not r:
            raise FileNotFoundError(f"stt_equity_funds: no file found near {base}")
        rows = list(_csv.DictReader(_io.StringIO(r.text)))
        out = []
        for row in rows:
            sym = (row.get("SYMBOL") or "").strip()
            if not sym:
                continue
            out.append({
                "symbol":        sym,
                "series":        (row.get("SERIES") or "").strip(),
                "isin":          (row.get("ISIN") or "").strip(),
                "sec_desc":      (row.get("Sec Desc") or "").strip(),
                "stt_indicator": (row.get("STT Indicator") or "").strip(),
            })
        return out

    def circuit_square_off(self, dt: date | None = None) -> list[dict]:
        """Circuit Square-off (CSQR) — securities squared off at circuit price.

        Returns: [{symbol, series, settlement_type, settlement_no, price}]
        """
        import re
        dt = dt or (date.today() - timedelta(days=1))
        # Filename: CSQR_M{YYYY}{NNN}_{ddmmyyyy}.csv — settlement number via API
        try:
            r_meta = self._session._s.get(
                "https://www.nseindia.in/api/daily-reports?key=CM", timeout=15
            )
            data = r_meta.json()
            items = data.get("CurrentDay", []) + data.get("PreviousDay", [])
            csqr_item = next(
                (i for i in items if (i.get("fileActlName") or "").startswith("CSQR_")),
                None,
            )
            if csqr_item:
                file_url = csqr_item["filePath"].rstrip("/") + "/" + csqr_item["fileActlName"]
            else:
                file_url = None
        except Exception:
            file_url = None

        if not file_url:
            raise FileNotFoundError("Could not locate circuit square-off file via NSE API")

        r = self._session._s.get(file_url, timeout=15)
        r.raise_for_status()
        out = []
        for line in r.text.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                out.append({
                    "symbol":          parts[0],
                    "series":          parts[1],
                    "settlement_type": parts[2],
                    "settlement_no":   parts[3],
                    "price":           float(parts[4] or 0),
                })
            except (ValueError, IndexError):
                continue
        return out

    def latency_statistics(self) -> dict:
        """CM segment latency statistics — most recent published file (rolling).

        Returns: {observation_date, rows: [{segment, min_us, mean_us, p50_us, p90_us,
                   p99_us, max_us, order_messages}]}
        """
        # The file is not dated by today but by last available trading day;
        # use the daily-reports API to get the exact filename.
        try:
            r_meta = self._session._s.get(
                "https://www.nseindia.in/api/daily-reports?key=CM", timeout=15
            )
            data = r_meta.json()
            items = data.get("CurrentDay", []) + data.get("PreviousDay", [])
            lat_item = next(
                (i for i in items if "latency" in (i.get("fileActlName") or "").lower()),
                None,
            )
            if lat_item:
                file_url = lat_item["filePath"].rstrip("/") + "/" + lat_item["fileActlName"]
            else:
                file_url = None
        except Exception:
            file_url = None

        if not file_url:
            raise FileNotFoundError("Could not locate latency statistics file via NSE API")

        r = self._session._s.get(file_url, timeout=15)
        r.raise_for_status()
        lines = [l for l in r.text.splitlines() if l.strip()]
        obs_date = ""
        import re
        m = re.search(r"'(\d{2}-[A-Z]{3}-\d{4})'", lines[0]) if lines else None
        if m:
            obs_date = m.group(1)
        rows = []
        if len(lines) > 1:
            reader = _csv.DictReader(_io.StringIO("\n".join(lines[1:])))
            for row in reader:
                def _f(k): return float((row.get(k) or "0").strip().split("M")[0] or 0)
                seg = (row.get("Segment") or "").strip()
                if not seg:
                    continue
                rows.append({
                    "segment":          seg,
                    "min_us":           _f("Min"),
                    "mean_us":          _f("Mean"),
                    "p50_us":           _f("50%ile"),
                    "p90_us":           _f("90%ile"),
                    "p99_us":           _f("99%ile"),
                    "max_us":           _f("Max"),
                    "order_messages":   (row.get("No. of Order Messages (Million msgs)") or "").strip(),
                })
        return {"observation_date": obs_date, "rows": rows}

    def priceband_report(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """Price band (circuit limits) report for the given date."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"MW{_ddmmyyyy(dt)}.zip"
        url = f"{_ARCHIVE}/archives/equities/bhavcopy/{filename}"
        _dl = lambda u: self._session.download_zip(u, folder=Path(folder))
        return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)

    def cm_mii_security_report(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """CM MII Security report — OHLCV + delivery % for all EQ series stocks."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"sec_bhavdata_full_{_ddmmyyyy(dt)}.csv"
        url = f"{_ARCHIVE}/products/content/{filename}"
        _dl = lambda u: self._session.download_file(u, folder=Path(folder), filename=filename)
        return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)

    # ------------------------------------------------------------------ #
    #  Reports metadata & document download                               #
    # ------------------------------------------------------------------ #

    def fetch_daily_reports_file_metadata(self, category: str = "ALL") -> list[dict]:
        """
        Metadata for today's published daily report files.
        category: 'ALL' | 'TRADING' | 'CLEARING' | 'SURVEILLANCE' …
        """
        resp = self._session.get("daily-reports", params={"key": category})
        return resp.get("data", resp) if isinstance(resp, dict) else resp

    def download_document(
        self,
        url:      str,
        folder:   str | Path = ".",
        filename: str | None = None,
    ) -> Path:
        """
        Download any NSE document by its full URL.
        Useful for annual reports, circular PDFs, etc.
        """
        if not filename:
            filename = url.rstrip("/").split("/")[-1] or "document"
        return self._session.download_file(url, folder=Path(folder), filename=filename)

    def wdm_securities_list(self, dt: date | None = None) -> list[dict]:
        """Debt segment (WDM) — complete list of securities available for trading.

        Includes government securities, corporate bonds, T-bills, state loans, etc.
        Returns [{sectype, symbol, issue_name, issue_desc, coupon_pct, issue_date,
                  mat_date, last_ip_dt, next_ip_dt, cpn_freq, last_traded_date,
                  last_traded_price, isin, status}].
        ~6000+ rows.
        """
        import csv as _csv2, io as _io2
        base = dt or date.today()
        for offset in range(5):
            check = base - timedelta(days=offset)
            if check.weekday() >= 5:
                continue
            ds = check.strftime("%d%m%Y")
            yr = check.strftime("%Y")
            mn = check.strftime("%b").upper()
            url = f"{_ARCHIVE}/content/historical/WDM/{yr}/{mn}/wdmlist_{ds}.csv"
            try:
                r = self._session._s.get(url, timeout=20)
                if r.status_code == 200 and b"DOCTYPE" not in r.content[:50]:
                    reader = _csv2.DictReader(_io2.StringIO(r.text))
                    out = []
                    for row in reader:
                        sym = (row.get("SECURITY") or "").strip()
                        if not sym:
                            continue
                        out.append({
                            "sectype":           (row.get("SECTYPE") or "").strip(),
                            "symbol":            sym,
                            "issue_name":        (row.get("ISSUE_NAME") or "").strip(),
                            "issue_desc":        (row.get("ISSUE_DESC") or "").strip(),
                            "issue_date":        (row.get("ISSUE_DATE") or "").strip(),
                            "mat_date":          (row.get("MAT_DATE") or "").strip(),
                            "last_ip_dt":        (row.get("Last IP Dt") or "").strip(),
                            "next_ip_dt":        (row.get("Next IP Dt") or "").strip(),
                            "cpn_freq":          (row.get("Cpn Freq") or "").strip(),
                            "last_traded_date":  (row.get("Last Traded Date") or "").strip(),
                            "last_traded_price": (row.get("Last Traded Price (in Rs.)") or "").strip(),
                            "isin":              (row.get("ISIN NO.") or "").strip(),
                            "status":            (row.get("STATUS") or "").strip(),
                        })
                    if out:
                        return out
            except Exception:
                continue
        return []

    def wdm_daily_report(self, dt: date | None = None) -> dict:
        """Debt segment (WDM) daily trade report.

        Returns {date, trades: [{trade_date, sectype, symbol, issue_name, settl_days,
                trade_type, num_trades, traded_value_cr, low, high, last, vwap, wtd_ytm}],
                additions: [{sectype, symbol, issue, issue_desc, coupon, issue_date,
                             mat_date, next_ip_date, cpn_freq, rating, listed}],
                maturities: list}.
        Zip contains settlement CSV + additions/maturities CSVs.
        """
        import csv as _csv2, io as _io2, zipfile as _zf
        base = dt or date.today()
        for offset in range(5):
            check = base - timedelta(days=offset)
            if check.weekday() >= 5:
                continue
            ds = check.strftime("%d%m%Y")
            ddmm = check.strftime("%d%m")
            url = f"{_ARCHIVE}/content/debt/dly{ds}.zip"
            try:
                r = self._session._s.get(url, timeout=30)
                if r.status_code == 200 and b"DOCTYPE" not in r.content[:50]:
                    with _zf.ZipFile(_io2.BytesIO(r.content)) as z:
                        names = z.namelist()

                        # Trade settlement CSV
                        sett_name = next((n for n in names if n.startswith("trd") and n.endswith("_sett.csv")), None)
                        trades = []
                        if sett_name:
                            text = z.read(sett_name).decode("utf-8", errors="replace")
                            reader = _csv2.DictReader(_io2.StringIO(text))
                            for row in reader:
                                sym = (row.get("Security") or "").strip()
                                if not sym:
                                    continue
                                trades.append({
                                    "trade_date":      (row.get("Trade date") or "").strip(),
                                    "sectype":         (row.get("Sectype") or "").strip(),
                                    "symbol":          sym,
                                    "issue_name":      (row.get("Issue Name") or "").strip(),
                                    "settl_days":      (row.get("Settl Days") or "").strip(),
                                    "trade_type":      (row.get("Trade Type") or "").strip(),
                                    "num_trades":      (row.get("No.of Trades") or "").strip(),
                                    "traded_value_cr": (row.get("Traded Value (Rs.Cr.)") or "").strip(),
                                    "low":             (row.get("Low Price/Rate") or "").strip(),
                                    "high":            (row.get("High Price/Rate") or "").strip(),
                                    "last":            (row.get("Last Traded Price/Rate") or "").strip(),
                                    "vwap":            (row.get("Value Weighted Average Price/Rate") or "").strip(),
                                    "wtd_ytm":         (row.get("Weighted YTM") or "").strip(),
                                })

                        def _parse_csv_z(name_prefix):
                            nm = next((n for n in names if n.startswith(name_prefix) and n.endswith(".csv")), None)
                            if not nm:
                                return []
                            text = z.read(nm).decode("utf-8", errors="replace")
                            lines = [l for l in text.splitlines() if l.strip()]
                            if not lines:
                                return []
                            # Skip first line if it looks like a title (not a proper header)
                            if lines[0].startswith(",,,"):
                                lines = lines[1:]
                            reader = _csv2.DictReader(_io2.StringIO("\n".join(lines)))
                            out = []
                            for row in reader:
                                sym2 = (row.get("Security") or "").strip()
                                if not sym2:
                                    continue
                                out.append({k.strip(): (v or "").strip() for k, v in row.items() if k and k.strip()})
                            return out

                        return {
                            "date":       check.isoformat(),
                            "trades":     trades,
                            "additions":  _parse_csv_z("add"),
                            "maturities": _parse_csv_z("mat"),
                        }
            except Exception:
                continue
        return {"date": None, "trades": [], "additions": [], "maturities": []}

    def egr_var_files(self, dt: date | None = None) -> list[dict]:
        """EGR segment (Exchange for Gold Receipts) VaR margin files.

        Merges all 6 intraday VaR snapshots (begin-day through 5th intra-day).
        Same format as CM var_files: record type 10 = header row, 20 = data row.
        Returns [{snapshot, date, symbol, segment, isin, prev_daily_vol,
                  current_daily_vol, annualised_vol, price_band_pct}].
        """
        import io as _io2
        base = dt or date.today()
        for offset in range(5):
            check = base - timedelta(days=offset)
            if check.weekday() >= 5:
                continue
            ds = check.strftime("%d%m%Y")
            rows = []
            found_any = False
            for snap in range(1, 7):
                url = f"{_ARCHIVE}/content/egr/E_VAR1_{ds}_{snap}.DAT"
                try:
                    r = self._session._s.get(url, timeout=15)
                    if r.status_code != 200 or b"DOCTYPE" in r.content[:50]:
                        continue
                    found_any = True
                    for line in r.text.splitlines():
                        parts = line.split(",")
                        if not parts or parts[0] != "20":
                            continue
                        if len(parts) < 10:
                            continue
                        rows.append({
                            "snapshot":        snap,
                            "date":            ds,
                            "symbol":          parts[1].strip(),
                            "segment":         parts[2].strip(),
                            "isin":            parts[3].strip(),
                            "prev_daily_vol":  parts[4].strip(),
                            "daily_vol_added": parts[5].strip(),
                            "price_band_pct":  parts[6].strip(),
                            "current_daily_vol": parts[7].strip(),
                            "annualised_vol":  parts[8].strip(),
                            "var_pct":         parts[9].strip(),
                        })
                except Exception:
                    continue
            if found_any:
                return rows
        return []
