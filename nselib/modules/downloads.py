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
        dt defaults to yesterday. Returns the saved file path.
        """
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip"
        url = f"{_ARCHIVE}/content/cm/{filename}"
        _dl = lambda u: self._session.download_zip(u, folder=Path(folder))
        return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)

    def delivery_bhavcopy(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """Delivery position bhavcopy (MTO/delivery data)."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"MTO_{_ddmmyyyy(dt)}.DAT"
        url = f"{_ARCHIVE}/archives/equities/mto/{filename}"
        _dl = lambda u: self._session.download_file(u, folder=Path(folder), filename=filename)
        return self._guardian.guarded_archive(url, _dl) if self._guardian else _dl(url)

    def fno_bhavcopy(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """F&O bhavcopy CSV."""
        dt = dt or (date.today() - timedelta(days=1))
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
        url = f"{_ARCHIVE}/content/CM_52_wk_High_low_{_ddmmyyyy(dt)}.csv"
        r = self._session._s.get(url, timeout=15)
        r.raise_for_status()
        lines = r.text.splitlines()
        # First 2 lines are disclaimer text, not CSV header
        data_text = "\n".join(lines[2:])
        reader = _csv.DictReader(_io.StringIO(data_text))
        return [row for row in reader]

    def short_selling(self, dt: date | None = None) -> list[dict]:
        """
        Short selling positions reported by brokers for a given date.
        Returns list of dicts with keys:
          Security Name, Symbol Name, Trade Date, Quantity
        dt defaults to yesterday.
        """
        dt = dt or (date.today() - timedelta(days=1))
        url = f"{_ARCHIVE}/archives/equities/shortSelling/shortselling_{_ddmmyyyy(dt)}.csv"
        return _parse_csv_url(self._session, url)

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
        url = f"{_ARCHIVE}/content/cm/REG_IND{_ddmmyy(dt)}.csv"
        return _parse_csv_url(self._session, url)

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

    # ------------------------------------------------------------------ #
    #  Daily reports                                                       #
    # ------------------------------------------------------------------ #

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
