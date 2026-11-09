"""
pytest suite for all archive-based nselib methods.

All tests hit nsearchives.nseindia.com only — this domain is reachable from
any IP including cloud/datacenter environments, so this suite is safe to run
in CI without a residential or VPN connection.

TEST_DATE = 2024-11-05 (Tuesday): a confirmed trading day with historical
data available on the NSE archive. It is far enough in the past that all
files are stable and will not change.

Fixtures are defined in conftest.py:
  - nse            — session-scoped NSE client
  - download_folder — temporary directory for file downloads

Test categories
---------------
1. Equity research data  (pe_ratio, week52_high_low, securities_list, …)
2. File downloads        (equity_bhavcopy, delivery_bhavcopy, full_bhavcopy_delivery, …)
3. F&O archive data      (fno_ban_list, participant_oi, fo_settlement_prices, …)
4. Rolling / no-date     (bulk_deals_archive, fno_lots, series_changes, …)
5. Market summary data   (pr_bhavcopy, market_activity_report, wdm_securities_list)
6. Historical data       (fetch_equity_historical_data via bhavcopy fallback)
"""

from datetime import date
from pathlib import Path

import pytest

from nselib import NSE

# ---------------------------------------------------------------------------
# Known stable past trading day — Tuesday 5 Nov 2024
# ---------------------------------------------------------------------------
TEST_DATE = date(2024, 11, 5)


# ===========================================================================
# 1. Equity research data (returns parsed list[dict] directly)
# ===========================================================================


def test_pe_ratio(nse):
    """P/E ratios for all listed stocks — ~2262 rows."""
    result = nse.pe_ratio(TEST_DATE)
    assert isinstance(result, list), "pe_ratio should return a list"
    assert len(result) > 100, f"Expected > 100 PE rows, got {len(result)}"
    row = result[0]
    # At least one of the known key patterns must be present
    assert any(k in row for k in ("SYMBOL", "Symbol")), (
        f"Expected SYMBOL key; got keys: {list(row.keys())[:5]}"
    )


def test_week52_high_low(nse):
    """52-week adjusted high / low for all NSE stocks — ~5946 rows."""
    result = nse.week52_high_low(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 100, f"Expected > 100 rows, got {len(result)}"
    row = result[0]
    assert any(k in row for k in ("SYMBOL", "Symbol")), (
        f"Expected SYMBOL key; got keys: {list(row.keys())[:5]}"
    )


def test_surveillance_indicator(nse):
    """GSM / ASM / IRP surveillance flags — ~3211 rows."""
    result = nse.surveillance_indicator(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 100, f"Expected > 100 surveillance rows, got {len(result)}"
    row = result[0]
    assert any(k in row for k in ("Symbol", "SYMBOL", "ScripCode")), (
        f"Expected Symbol key; got keys: {list(row.keys())[:5]}"
    )


def test_securities_list(nse):
    """All listed securities with series, price band, remarks — ~3598 rows."""
    result = nse.securities_list(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 100
    row = result[0]
    assert "symbol" in row, f"Expected 'symbol' key; got {list(row.keys())}"
    assert "series" in row
    assert "security_name" in row


def test_daily_volatility(nse):
    """EWMA daily + annualised volatility for all CM stocks — ~5000 rows."""
    result = nse.daily_volatility(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 100, f"Expected > 100 volatility rows, got {len(result)}"
    row = result[0]
    assert "symbol" in row
    assert "current_daily_vol" in row
    assert "annualised_vol" in row


def test_short_selling(nse):
    """Broker-reported short selling positions — may be empty on low-volume days."""
    result = nse.short_selling(TEST_DATE)
    assert isinstance(result, list)
    # Short selling data can be empty on certain dates; just verify type
    if result:
        row = result[0]
        assert any(k in row for k in ("Symbol Name", "Security Name", "SYMBOL")), (
            f"Expected symbol key; got keys: {list(row.keys())[:5]}"
        )


def test_haircut_approved_securities(nse):
    """NSCCL haircut % for approved equities — ~1000 rows."""
    result = nse.haircut_approved_securities(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 50, f"Expected > 50 rows, got {len(result)}"
    row = result[0]
    assert "symbol" in row
    assert "haircut" in row
    assert "isin" in row


def test_haircut_mutual_funds(nse):
    """Haircut for MF units accepted as collateral — ~7000 rows."""
    result = nse.haircut_mutual_funds(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 100, f"Expected > 100 rows, got {len(result)}"
    row = result[0]
    assert "isin" in row
    assert "haircut" in row


def test_corporate_bonds_traded(nse):
    """Corporate bonds OHLCV on NSE — typically ~150 bonds per day."""
    try:
        result = nse.corporate_bonds_traded(TEST_DATE)
    except FileNotFoundError:
        pytest.skip("Corporate bonds file not available on NSE archives for TEST_DATE")
    assert isinstance(result, list)
    if result:
        row = result[0]
        assert "symbol" in row
        assert "close" in row


def test_sme_bhavcopy(nse):
    """SME segment daily OHLCV — ~440 rows or empty if no data for date."""
    result = nse.sme_bhavcopy(TEST_DATE)
    assert isinstance(result, list)
    if result:
        row = result[0]
        assert "symbol" in row
        assert "close" in row
        assert "traded_qty" in row


def test_stt_non_applicability(nse):
    """Securities exempt from STT — ~12800 rows."""
    result = nse.stt_non_applicability(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 100, f"Expected > 100 STT rows, got {len(result)}"
    row = result[0]
    assert "symbol" in row
    assert "isin" in row


def test_stt_equity_funds(nse):
    """MF units classified as equity-oriented for STT — ~1189 rows."""
    result = nse.stt_equity_funds(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 50, f"Expected > 50 rows, got {len(result)}"
    row = result[0]
    assert "symbol" in row
    assert "isin" in row


# ===========================================================================
# 2. File downloads (return Path to downloaded / extracted file)
# ===========================================================================


def test_equity_bhavcopy_download(nse, download_folder):
    """
    Equity bhavcopy download — returns Path to extracted CSV inside ZIP.
    The file must exist and contain data (> 50 KB for a full trading day).
    """
    result = nse.equity_bhavcopy(TEST_DATE, folder=download_folder)
    assert isinstance(result, Path), (
        f"equity_bhavcopy should return a Path, got {type(result)}"
    )
    assert result.exists(), f"Downloaded file not found: {result}"
    assert result.stat().st_size > 50_000, (
        f"File too small ({result.stat().st_size} bytes) — may be corrupt or empty"
    )


def test_delivery_bhavcopy_download(nse, download_folder):
    """MTO delivery data download — returns Path to downloaded file."""
    result = nse.delivery_bhavcopy(TEST_DATE, folder=download_folder)
    assert isinstance(result, Path), (
        f"delivery_bhavcopy should return a Path, got {type(result)}"
    )
    assert result.exists(), f"Downloaded file not found: {result}"
    assert result.stat().st_size > 1_000, (
        f"File too small ({result.stat().st_size} bytes)"
    )


def test_full_bhavcopy_delivery_download(nse, download_folder):
    """
    Full bhavcopy with delivery % — returns Path to downloaded CSV.
    Contains ~3543 rows with OHLCV + delivery data.
    """
    result = nse.full_bhavcopy_delivery(TEST_DATE, folder=download_folder)
    assert isinstance(result, Path), (
        f"full_bhavcopy_delivery should return a Path, got {type(result)}"
    )
    assert result.exists(), f"Downloaded file not found: {result}"
    assert result.stat().st_size > 100_000, (
        f"File too small ({result.stat().st_size} bytes)"
    )


def test_fno_bhavcopy_download(nse, download_folder):
    """F&O bhavcopy ZIP download — returns Path to extracted CSV."""
    result = nse.fno_bhavcopy(TEST_DATE, folder=download_folder)
    assert isinstance(result, Path), (
        f"fno_bhavcopy should return a Path, got {type(result)}"
    )
    assert result.exists(), f"Downloaded file not found: {result}"
    assert result.stat().st_size > 10_000, (
        f"File too small ({result.stat().st_size} bytes)"
    )


def test_indices_bhavcopy_download(nse, download_folder):
    """Index daily values bhavcopy — returns Path to downloaded CSV."""
    result = nse.indices_bhavcopy(TEST_DATE, folder=download_folder)
    assert isinstance(result, Path), (
        f"indices_bhavcopy should return a Path, got {type(result)}"
    )
    assert result.exists(), f"Downloaded file not found: {result}"
    assert result.stat().st_size > 1_000, (
        f"File too small ({result.stat().st_size} bytes)"
    )


# ===========================================================================
# 3. F&O archive data (all use nsearchives.nseindia.com)
# ===========================================================================


def test_fno_ban_list(nse):
    """
    F&O securities in ban period.
    May be an empty list (no securities banned) — just verify the type.
    """
    result = nse.fno_ban_list(TEST_DATE)
    assert isinstance(result, list), f"fno_ban_list should return a list, got {type(result)}"
    # Each element is a symbol string when the list is non-empty
    for sym in result:
        assert isinstance(sym, str), f"Ban list items should be strings, got {type(sym)}"


def test_participant_oi(nse):
    """
    Participant-wise Open Interest (FII/DII/Client/Pro) — 4 participant rows.
    """
    result = nse.participant_oi(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) >= 1, "Expected at least 1 participant row"
    row = result[0]
    expected_keys = {
        "participant",
        "future_index_long", "future_index_short",
        "total_long", "total_short",
    }
    missing = expected_keys - set(row.keys())
    assert not missing, f"Missing keys in participant_oi row: {missing}"
    # Participant names should be non-empty strings
    assert row["participant"], "Participant name should not be empty"


def test_participant_volume(nse):
    """Participant-wise trading volume — same structure as participant_oi."""
    result = nse.participant_volume(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) >= 1
    row = result[0]
    assert "participant" in row
    assert "total_long" in row
    assert "total_short" in row


def test_mwpl_oi(nse):
    """MWPL NCL Open Interest — stocks near/above MWPL limit."""
    result = nse.mwpl_oi(TEST_DATE)
    assert isinstance(result, list)
    # May be short on some dates but should normally have entries
    if result:
        row = result[0]
        expected_keys = {"date", "isin", "scrip_name", "symbol", "mwpl", "ncl_oi", "ncl_futeq_oi"}
        missing = expected_keys - set(row.keys())
        assert not missing, f"Missing keys in mwpl_oi row: {missing}"
        assert row["symbol"], "Symbol should not be empty"


def test_combined_oi(nse):
    """Combined OI across NSE+BSE with MWPL utilization."""
    result = nse.combined_oi(TEST_DATE)
    assert isinstance(result, list)
    if result:
        row = result[0]
        expected_keys = {"date", "isin", "symbol", "mwpl", "open_interest", "limit_next_day"}
        missing = expected_keys - set(row.keys())
        assert not missing, f"Missing keys in combined_oi row: {missing}"


def test_fo_settlement_prices(nse):
    """Daily MTM settlement prices for all F&O contracts — ~1316 rows."""
    result = nse.fo_settlement_prices(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 50, f"Expected > 50 settlement price rows, got {len(result)}"
    row = result[0]
    expected_keys = {"date", "instrument", "underlying", "expiry", "settlement_price"}
    missing = expected_keys - set(row.keys())
    assert not missing, f"Missing keys in fo_settlement_prices row: {missing}"
    assert row["underlying"], "Underlying should not be empty"
    assert isinstance(row["settlement_price"], float)


def test_fo_daily_volatility(nse):
    """EWMA daily + annualised volatility for F&O underlying stocks — ~224 rows."""
    result = nse.fo_daily_volatility(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 20, f"Expected > 20 FO volatility rows, got {len(result)}"
    row = result[0]
    assert "symbol" in row
    assert "current_daily_vol" in row
    assert "annualised_vol" in row


def test_fo_exposure_limits(nse):
    """ELM + additional margin % per F&O symbol — ~426 rows."""
    result = nse.fo_exposure_limits(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 20, f"Expected > 20 ELM rows, got {len(result)}"
    row = result[0]
    assert "symbol" in row
    assert "normal_elm_pct" in row
    assert "total_elm_pct" in row


def test_fo_delta_equivalent_oi(nse):
    """Combined delta-equivalent OI across NSE+BSE — ~222 rows."""
    result = nse.fo_delta_equivalent_oi(TEST_DATE)
    assert isinstance(result, list)
    if result:
        row = result[0]
        assert "symbol" in row
        assert "delta_eq_oi" in row


def test_fo_market_activity(nse):
    """
    F&O bhavcopy from archive ZIP — futures (~650 rows) + options (~21626 rows).
    """
    result = nse.fo_market_activity(TEST_DATE)
    assert isinstance(result, dict), f"fo_market_activity should return a dict, got {type(result)}"
    assert "futures" in result
    assert "options" in result
    assert isinstance(result["futures"], list)
    assert isinstance(result["options"], list)
    assert len(result["futures"]) > 50, (
        f"Expected > 50 futures rows, got {len(result['futures'])}"
    )
    assert len(result["options"]) > 500, (
        f"Expected > 500 options rows, got {len(result['options'])}"
    )
    # Spot-check structure
    fut = result["futures"][0]
    assert "symbol" in fut
    assert "instrument" in fut
    opt = result["options"][0]
    assert "symbol" in opt
    assert "option_type" in opt


def test_fo_index_position_limits(nse):
    """Index derivatives position limits per investor category — ~30 rows."""
    result = nse.fo_index_position_limits(TEST_DATE)
    assert isinstance(result, list)
    if result:
        row = result[0]
        assert "index" in row
        assert "category" in row
        assert "qty_limit" in row


def test_fo_top10_clearing_members(nse):
    """Top 10 clearing members by equity derivatives volume — at least 10 rows."""
    result = nse.fo_top10_clearing_members(TEST_DATE)
    assert isinstance(result, list)
    if result:
        assert len(result) >= 10
        row = result[0]
        assert "rank" in row
        assert "total_vol" in row


def test_fo_contracts(nse):
    """F&O contract master file — all active contracts with lot size, ISIN (~88k rows)."""
    result = nse.fo_contracts(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 1000, (
        f"Expected > 1000 F&O contract rows, got {len(result)}"
    )
    row = result[0]
    assert "symbol" in row
    assert "lot_size" in row
    assert "isin" in row
    assert "expiry_epoch" in row


def test_fo_client_oi_limits(nse):
    """Client-wise position limits for F&O stocks — ~648 rows."""
    result = nse.fo_client_oi_limits(TEST_DATE)
    assert isinstance(result, list)
    if result:
        row = result[0]
        assert "symbol" in row
        assert "client_limit" in row


def test_fo_contract_delta(nse):
    """NCL delta factors per F&O contract — ~149k rows."""
    result = nse.fo_contract_delta(TEST_DATE)
    assert isinstance(result, list)
    if not result:
        pytest.skip("Contract delta file not available on NSE archives for TEST_DATE")
    assert len(result) > 100, f"Expected > 100 delta rows, got {len(result)}"
    row = result[0]
    assert "symbol" in row
    assert "delta_factor" in row
    assert "expiry" in row


def test_fo_spread_contracts(nse):
    """Calendar spread contract definitions with price ranges — ~440 rows."""
    result = nse.fo_spread_contracts(TEST_DATE)
    assert isinstance(result, list)
    if result:
        row = result[0]
        assert "symbol" in row
        assert "near_leg_id" in row
        assert "far_leg_id" in row


# ===========================================================================
# 4. Rolling / no-date archive files
# ===========================================================================


def test_fno_lots(nse):
    """Current lot sizes for all F&O symbols — dict of symbol -> lot size."""
    result = nse.fno_lots()
    assert isinstance(result, dict), f"fno_lots should return a dict, got {type(result)}"
    assert len(result) > 50, f"Expected > 50 F&O symbols, got {len(result)}"
    # Lot sizes should be positive integers
    for sym, lot in list(result.items())[:5]:
        assert isinstance(sym, str), f"Symbol should be string, got {type(sym)}"
        assert isinstance(lot, int) and lot > 0, (
            f"Lot size for {sym} should be positive int, got {lot}"
        )


def test_bulk_deals_archive(nse):
    """
    Today's bulk deals (rolling file — reflects current trading day).
    May be empty outside market hours / on weekends; just verify type and structure.
    """
    result = nse.bulk_deals_archive()
    assert isinstance(result, list)
    if result:
        row = result[0]
        assert any(k in row for k in ("Symbol", "SYMBOL", "Security Name")), (
            f"Expected symbol/security key; got keys: {list(row.keys())[:5]}"
        )


def test_block_deals_archive(nse):
    """Today's block deals (rolling file) — may be empty; verify type."""
    result = nse.block_deals_archive()
    assert isinstance(result, list)
    if result:
        row = result[0]
        assert any(k in row for k in ("Symbol", "SYMBOL", "Security Name")), (
            f"Expected symbol/security key; got keys: {list(row.keys())[:5]}"
        )


def test_series_changes(nse):
    """Recent series changes for NSE-listed securities — rolling file."""
    result = nse.series_changes()
    assert isinstance(result, list)
    # This rolling file is typically non-empty; check structure if present
    if result:
        row = result[0]
        assert "symbol" in row
        assert "from_series" in row
        assert "to_series" in row


# ===========================================================================
# 5. Market summary data
# ===========================================================================


def test_pr_bhavcopy(nse):
    """
    PR bhavcopy ZIP — parsed into 12 categories.
    At least bhavcopy and circuit_hitters keys must be present and non-empty.
    """
    result = nse.pr_bhavcopy(TEST_DATE)
    assert isinstance(result, dict), f"pr_bhavcopy should return a dict, got {type(result)}"
    expected_keys = {
        "announcements", "corporate_actions", "circuit_hitters",
        "board_meetings", "bhavcopy", "gainers_losers",
        "new_highs_lows", "market_cap", "top_by_value",
    }
    missing = expected_keys - set(result.keys())
    assert not missing, f"Missing keys in pr_bhavcopy result: {missing}"
    # bhavcopy sub-list should be non-empty on a trading day
    assert isinstance(result["bhavcopy"], list)
    assert len(result["bhavcopy"]) > 0, "pr_bhavcopy['bhavcopy'] should not be empty"


def test_market_activity_report(nse):
    """Daily market summary statistics — traded value, qty, trades, market cap."""
    result = nse.market_activity_report(TEST_DATE)
    assert isinstance(result, dict), (
        f"market_activity_report should return a dict, got {type(result)}"
    )
    assert "date" in result
    assert "text" in result
    assert result["date"], "date field should not be empty"
    assert len(result["text"]) > 0, "text field should not be empty"


def test_wdm_securities_list(nse):
    """WDM debt securities — G-Secs, bonds, T-bills, state loans — ~6000+ rows."""
    result = nse.wdm_securities_list(TEST_DATE)
    assert isinstance(result, list)
    assert len(result) > 100, f"Expected > 100 WDM securities, got {len(result)}"
    row = result[0]
    assert "symbol" in row
    assert "isin" in row
    assert "mat_date" in row


def test_wdm_daily_report(nse):
    """WDM daily trade report — trades, additions, maturities."""
    result = nse.wdm_daily_report(TEST_DATE)
    assert isinstance(result, dict)
    assert "trades" in result
    assert "additions" in result
    assert "maturities" in result
    assert isinstance(result["trades"], list)


# ===========================================================================
# 6. Historical data via archive fallback
# ===========================================================================


def test_fetch_equity_historical_data_archive(nse):
    """
    Equity historical OHLCV — the method tries the NSE API first and falls
    back to the daily bhavcopy archive when blocked (cloud/datacenter IP).
    Either path produces the same list[dict] structure.
    """
    from_date = date(2024, 11, 1)
    to_date = date(2024, 11, 5)

    result = nse.fetch_equity_historical_data("RELIANCE", from_date=from_date, to_date=to_date)
    assert isinstance(result, list), (
        f"fetch_equity_historical_data should return a list, got {type(result)}"
    )
    assert len(result) >= 1, "Expected at least 1 OHLCV row for RELIANCE in the date range"

    row = result[0]
    # API path uses CH_* keys; archive path uses our normalised keys
    has_api_keys  = "CH_SYMBOL" in row or "mTIMESTAMP" in row
    has_arch_keys = "symbol" in row and "close" in row
    assert has_api_keys or has_arch_keys, (
        f"Row does not look like OHLCV data; keys: {list(row.keys())[:8]}"
    )
