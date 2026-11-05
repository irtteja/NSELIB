"""
Shared pytest fixtures for nselib archive method tests.

Provides a session-scoped NSE instance so the HTTP session and cookies
are created once and reused across all tests, avoiding redundant
homepage hits and rate-limit delays.
"""

import pytest
from pathlib import Path
from nselib import NSE


@pytest.fixture(scope="session")
def download_folder(tmp_path_factory):
    """Temporary directory that receives all file downloads during the test run."""
    return tmp_path_factory.mktemp("nse_data")


@pytest.fixture(scope="session")
def nse(download_folder):
    """
    Shared NSE client, created once per test session.
    Uses a temporary download folder so downloaded files don't pollute the workspace.
    """
    with NSE(str(download_folder)) as n:
        yield n
