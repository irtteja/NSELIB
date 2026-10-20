from datetime import date, timedelta
from pathlib import Path
from typing import Any


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d%m%Y")


def _ddmonyyyy(d: date) -> str:
    return d.strftime("%d%b%Y").upper()


def _monYYYY(d: date) -> str:
    return d.strftime("%b%Y").upper()


class DownloadsMixin:
    """Bhavcopy downloads, daily reports, and document fetches."""

    # ------------------------------------------------------------------ #
    #  Bhavcopy                                                            #
    # ------------------------------------------------------------------ #

    def equity_bhavcopy(
        self,
        dt:      date | None = None,
        dest:    str | Path  = ".",
    ) -> Path:
        """
        Download the equity bhavcopy CSV for a given date.
        dt defaults to yesterday. Returns the saved file path.
        """
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip"
        url = (
            f"https://nsearchives.nseindia.com/content/cm/{filename}"
        )
        return self._session.download_zip(url, dest=dest, filename=filename)

    def delivery_bhavcopy(
        self,
        dt:   date | None = None,
        dest: str | Path  = ".",
    ) -> Path:
        """Delivery position bhavcopy (MTO/delivery data)."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"MTO_{_ddmmyyyy(dt)}.DAT"
        url = f"https://nsearchives.nseindia.com/archives/equities/mto/{filename}"
        return self._session.download_file(url, dest=dest, filename=filename)

    def fno_bhavcopy(
        self,
        dt:   date | None = None,
        dest: str | Path  = ".",
    ) -> Path:
        """F&O bhavcopy CSV."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"BhavCopy_NSE_FO_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip"
        url = f"https://nsearchives.nseindia.com/content/fo/{filename}"
        return self._session.download_zip(url, dest=dest, filename=filename)

    def indices_bhavcopy(
        self,
        dt:   date | None = None,
        dest: str | Path  = ".",
    ) -> Path:
        """Index daily values bhavcopy CSV."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"ind_close_all_{_ddmmyyyy(dt)}.csv"
        url = f"https://nsearchives.nseindia.com/content/indices/{filename}"
        return self._session.download_file(url, dest=dest, filename=filename)

    def pr_bhavcopy(
        self,
        dt:   date | None = None,
        dest: str | Path  = ".",
    ) -> Path:
        """PR bhavcopy (all segments combined)."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"PR{_ddmmyyyy(dt)}.zip"
        url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/{filename}"
        return self._session.download_zip(url, dest=dest, filename=filename)

    # ------------------------------------------------------------------ #
    #  Daily reports                                                       #
    # ------------------------------------------------------------------ #

    def priceband_report(
        self,
        dt:   date | None = None,
        dest: str | Path  = ".",
    ) -> Path:
        """Price band (circuit limits) report for the given date."""
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"MW{_ddmmyyyy(dt)}.zip"
        url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/{filename}"
        return self._session.download_zip(url, dest=dest, filename=filename)

    def cm_mii_security_report(
        self,
        dt:   date | None = None,
        dest: str | Path  = ".",
    ) -> Path:
        """
        CM MII Security report — listing status, ISIN, lot sizes.
        """
        dt = dt or (date.today() - timedelta(days=1))
        filename = f"sec_bhavdata_full_{_ddmmyyyy(dt)}.csv"
        url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/{filename}"
        return self._session.download_file(url, dest=dest, filename=filename)

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
        url:  str,
        dest: str | Path = ".",
        filename: str | None = None,
    ) -> Path:
        """
        Download any NSE document by its full URL.
        Useful for annual reports, circular PDFs, etc.
        """
        if not filename:
            filename = url.rstrip("/").split("/")[-1] or "document"
        return self._session.download_file(url, dest=dest, filename=filename)
