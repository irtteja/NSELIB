from datetime import date, timedelta
from pathlib import Path
from typing import Any


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d%m%Y")


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


class DownloadsMixin:
    """Bhavcopy downloads, daily reports, and document fetches."""

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
        url = f"https://nsearchives.nseindia.com/content/cm/{filename}"
        return self._session.download_zip(url, folder=Path(folder))

    def delivery_bhavcopy(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """Delivery position bhavcopy (MTO/delivery data)."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"MTO_{_ddmmyyyy(dt)}.DAT"
        url = f"https://nsearchives.nseindia.com/archives/equities/mto/{filename}"
        return self._session.download_file(url, folder=Path(folder), filename=filename)

    def fno_bhavcopy(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """F&O bhavcopy CSV."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"BhavCopy_NSE_FO_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip"
        url = f"https://nsearchives.nseindia.com/content/fo/{filename}"
        return self._session.download_zip(url, folder=Path(folder))

    def indices_bhavcopy(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """Index daily values bhavcopy CSV."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"ind_close_all_{_ddmmyyyy(dt)}.csv"
        url = f"https://nsearchives.nseindia.com/content/indices/{filename}"
        return self._session.download_file(url, folder=Path(folder), filename=filename)

    def pr_bhavcopy(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """PR bhavcopy (all segments combined)."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"PR{_ddmmyyyy(dt)}.zip"
        url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/{filename}"
        return self._session.download_zip(url, folder=Path(folder))

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
        url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/{filename}"
        return self._session.download_zip(url, folder=Path(folder))

    def cm_mii_security_report(
        self,
        dt:     date | None = None,
        folder: str | Path  = ".",
    ) -> Path:
        """CM MII Security report — listing status, ISIN, lot sizes."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"sec_bhavdata_full_{_ddmmyyyy(dt)}.csv"
        url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/{filename}"
        return self._session.download_file(url, folder=Path(folder), filename=filename)

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
