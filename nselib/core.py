"""
NSESession — manages the HTTP session with NSE India.

NSE uses Akamai bot protection. The trick is:
  1. Hit the homepage first to get a valid session cookie.
  2. Use that cookie for all /api/* calls with browser-like headers.
  3. Refresh the cookie before it expires (~5 min TTL in practice).
  4. Rate-limit to 3 rps to avoid triggering NSE's throttle.
"""

import json
import time
import threading
import zipfile
import gzip
import shutil
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import NSESessionError, NSEFileUnavailableError

NSE_BASE    = "https://www.nseindia.com"
NSE_API     = f"{NSE_BASE}/api"
NSE_ARCHIVE = "https://nsearchives.nseindia.com"

# Browser-like headers that satisfy Akamai's bot check
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "Referer":         "https://www.nseindia.com/",
    "Origin":          "https://www.nseindia.com",
    "Sec-Fetch-Dest":  "empty",
    "Sec-Fetch-Mode":  "cors",
    "Sec-Fetch-Site":  "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}

_HOME_HEADERS = {
    **_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
}


class _TokenBucket:
    """Thread-safe token bucket for rate limiting."""

    def __init__(self, rate: float):
        self._rate  = rate
        self._tokens = rate
        self._last  = time.monotonic()
        self._lock  = threading.Lock()

    def consume(self) -> None:
        with self._lock:
            now     = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last  = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                time.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


class NSESession:
    """
    Manages HTTP session lifecycle with NSE India.

    Usage:
        session = NSESession("/tmp/nse_data")
        data = session.get("marketStatus")
        session.close()

        # or as context manager:
        with NSESession("/tmp/nse_data") as s:
            data = s.get("equity-stockIndices", params={"index": "NIFTY 50"})
    """

    _COOKIE_FILE = "nse_cookies.json"
    _COOKIE_TTL  = 270  # seconds; refresh before NSE's ~5min expiry

    def __init__(
        self,
        download_folder: str | Path,
        rate:        float = 3.0,
        timeout:     int   = 15,
        max_retries: int   = 5,
    ):
        self.download_folder = Path(download_folder)
        self.download_folder.mkdir(parents=True, exist_ok=True)

        self._timeout    = timeout
        self._bucket     = _TokenBucket(rate)
        self._cookie_file = self.download_folder / self._COOKIE_FILE
        self._cookie_ts: float = 0.0

        # requests.Session with automatic retry on transient errors
        self._s = requests.Session()
        self._s.headers.update(_HEADERS)

        retry = Retry(
            total            = max_retries,
            backoff_factor   = 1,
            status_forcelist = {429, 502, 503, 504},
            allowed_methods  = {"GET"},
            raise_on_status  = False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._s.mount("https://", adapter)
        self._s.mount("http://",  adapter)

        self._load_cookies()

    # ------------------------------------------------------------------ #
    #  Cookie management                                                   #
    # ------------------------------------------------------------------ #

    def _load_cookies(self) -> None:
        if self._cookie_file.exists():
            try:
                data = json.loads(self._cookie_file.read_text())
                self._cookie_ts = data.get("ts", 0.0)
                self._s.cookies.update(data.get("cookies", {}))
            except Exception:
                pass

    def _save_cookies(self) -> None:
        try:
            self._cookie_file.write_text(json.dumps({
                "ts":      self._cookie_ts,
                "cookies": dict(self._s.cookies),
            }))
        except Exception:
            pass

    def _refresh_cookies(self) -> None:
        """Visit NSE homepage to get a fresh Akamai session cookie."""
        try:
            resp = self._s.get(
                NSE_BASE,
                headers = _HOME_HEADERS,
                timeout = self._timeout,
            )
            resp.raise_for_status()
            self._cookie_ts = time.monotonic()
            self._save_cookies()
        except requests.RequestException as e:
            raise NSESessionError(
                f"Could not obtain NSE session cookie: {e}\n"
                "If running on a cloud/datacenter IP, NSE's Akamai may be blocking you. "
                "Try running from a residential IP or use a broker API as the data source."
            ) from e

    def _ensure_session(self) -> None:
        if time.monotonic() - self._cookie_ts > self._COOKIE_TTL:
            self._refresh_cookies()

    # ------------------------------------------------------------------ #
    #  Request helpers                                                     #
    # ------------------------------------------------------------------ #

    def get(self, path: str, params: dict | None = None) -> Any:
        """
        Rate-limited GET against the NSE /api/ endpoint.
        Auto-refreshes cookies on 401/403 and retries once.
        """
        self._bucket.consume()
        self._ensure_session()

        url  = f"{NSE_API}/{path.lstrip('/')}"
        resp = self._s.get(url, params=params, timeout=self._timeout)

        if resp.status_code in (401, 403):
            # Cookie expired mid-session — force refresh and retry
            self._cookie_ts = 0.0
            self._ensure_session()
            self._bucket.consume()
            resp = self._s.get(url, params=params, timeout=self._timeout)

        if resp.status_code == 404:
            raise NSEFileUnavailableError(url)

        resp.raise_for_status()
        return resp.json()

    def get_raw(self, url: str, stream: bool = False) -> requests.Response:
        """
        Rate-limited GET for archive downloads (bhavcopy, reports, etc.).
        Returns the raw Response so callers can stream or read bytes.
        """
        self._bucket.consume()
        resp = self._s.get(url, timeout=self._timeout, stream=stream)
        if resp.status_code == 404:
            raise NSEFileUnavailableError(url)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------ #
    #  File download helpers                                               #
    # ------------------------------------------------------------------ #

    def download_file(
        self,
        url:    str,
        folder: Path | None = None,
        filename: str | None = None,
    ) -> Path:
        """Download a file to disk. Returns the local Path."""
        dest_dir = folder or self.download_folder
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        fname = filename or url.split("/")[-1].split("?")[0]
        dest  = dest_dir / fname

        resp = self.get_raw(url, stream=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return dest

    def download_zip(
        self,
        url:    str,
        folder: Path | None = None,
        member: str | None  = None,
    ) -> Path:
        """
        Download a ZIP archive, extract one file (or the first file),
        delete the archive, and return the path to the extracted file.
        """
        dest_dir = folder or self.download_folder
        zip_path = self.download_file(url, folder=dest_dir)

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            target = member if member and member in names else names[0]
            zf.extract(target, path=dest_dir)

        zip_path.unlink()
        return dest_dir / target

    def download_gz(
        self,
        url:    str,
        folder: Path | None = None,
        out_name: str | None = None,
    ) -> Path:
        """Download a .gz file, decompress it, delete the archive."""
        dest_dir = folder or self.download_folder
        gz_path  = self.download_file(url, folder=dest_dir)

        out = dest_dir / (out_name or gz_path.stem)
        with gzip.open(gz_path, "rb") as f_in, open(out, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

        gz_path.unlink()
        return out

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        self._save_cookies()
        self._s.close()

    def __enter__(self) -> "NSESession":
        return self

    def __exit__(self, *_) -> None:
        self.close()
