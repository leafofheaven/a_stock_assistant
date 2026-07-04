"""Tests for shared read-only data quality snapshots."""

from __future__ import annotations

import pandas as pd

from core.diagnostics.data_quality_snapshot import build_data_quality_snapshot


def test_latest_coverage_counts_only_latest_trade_date() -> None:
    """Latest coverage must not count symbols that only have older history."""
    tables = {
        "stock_basic": pd.DataFrame({"ts_code": [f"00000{i}.SZ" for i in range(1, 6)]}),
        "daily_price": pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
                "trade_date": ["20260703", "20260702", "20260701", "20260630"],
                "close": [1, 2, 3, 4],
            }
        ),
        "daily_basic": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260703"]}),
        "adj_factor": pd.DataFrame({"ts_code": [], "trade_date": []}),
    }

    snapshot = build_data_quality_snapshot(tables=tables, latest_completed_trade_date="20260703")

    assert snapshot["configured_symbol_count"] == 5
    assert snapshot["latest_daily_price_symbol_count"] == 1
    assert snapshot["missing_latest_daily_price_symbol_count"] == 4
    assert snapshot["latest_daily_price_coverage_rate"] == 0.2
    assert snapshot["data_quality_status"] == "poor"


def test_any_history_coverage_is_named_separately() -> None:
    """Any historical price coverage should use any_daily_price fields."""
    tables = {
        "stock_basic": pd.DataFrame({"ts_code": [f"00000{i}.SZ" for i in range(1, 6)]}),
        "daily_price": pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
                "trade_date": ["20260703", "20260702", "20260701", "20260630"],
            }
        ),
    }

    snapshot = build_data_quality_snapshot(tables=tables, latest_completed_trade_date="20260703")

    assert snapshot["any_daily_price_symbol_count"] == 4
    assert snapshot["missing_any_daily_price_symbol_count"] == 1
    assert snapshot["any_daily_price_coverage_rate"] == 0.8
    assert snapshot["latest_daily_price_symbol_count"] == 1


def test_zero_count_cannot_have_high_latest_coverage() -> None:
    """Zero latest symbols must produce zero latest coverage."""
    tables = {
        "stock_basic": pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"]}),
        "daily_price": pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "trade_date": ["20260702", "20260702"]}),
    }

    snapshot = build_data_quality_snapshot(tables=tables, latest_completed_trade_date="20260703")

    assert snapshot["latest_daily_price_symbol_count"] == 0
    assert snapshot["latest_daily_price_coverage_rate"] == 0.0
    assert snapshot["formal_result_usable"] is False


def test_data_quality_snapshot_counts_daily_price_by_trade_date_string() -> None:
    """String trade_date rows should be counted exactly for latest coverage."""
    symbols = [f"{index:06d}.SZ" for index in range(1, 101)]
    tables = {
        "stock_basic": pd.DataFrame({"ts_code": symbols}),
        "daily_price": pd.DataFrame(
            {
                "ts_code": symbols[:68] + symbols[68:90],
                "trade_date": ["20260703"] * 68 + ["20260702"] * 22,
            }
        ),
    }

    snapshot = build_data_quality_snapshot(tables=tables, latest_completed_trade_date="20260703")

    assert snapshot["latest_daily_price_symbol_count"] == 68
    assert snapshot["any_daily_price_symbol_count"] == 90


def test_data_quality_snapshot_counts_daily_price_exact_trade_date() -> None:
    """Latest daily_price count should use exact normalized trade_date equality."""
    test_data_quality_snapshot_counts_daily_price_by_trade_date_string()


def test_data_quality_snapshot_counts_daily_basic_by_trade_date_string() -> None:
    """daily_basic latest rows should be counted by the same trade-date rule."""
    symbols = [f"{index:06d}.SZ" for index in range(1, 11)]
    tables = {
        "stock_basic": pd.DataFrame({"ts_code": symbols}),
        "daily_basic": pd.DataFrame({"ts_code": symbols[:3], "trade_date": ["20260703"] * 3}),
    }

    snapshot = build_data_quality_snapshot(tables=tables, latest_completed_trade_date="20260703")

    assert snapshot["latest_daily_basic_symbol_count"] == 3


def test_data_quality_snapshot_counts_daily_basic_exact_trade_date() -> None:
    """Latest daily_basic count should use exact normalized trade_date equality."""
    test_data_quality_snapshot_counts_daily_basic_by_trade_date_string()


def test_data_quality_snapshot_normalizes_trade_date() -> None:
    """Latest coverage should support int, compact string, and dashed string dates."""
    tables = {
        "stock_basic": pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"]}),
        "daily_price": pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
                "trade_date": [20260703, "20260703", "2026-07-03"],
            }
        ),
    }

    snapshot = build_data_quality_snapshot(tables=tables, latest_completed_trade_date="20260703")

    assert snapshot["latest_daily_price_symbol_count"] == 3


def test_data_quality_snapshot_normalizes_trade_date_formats() -> None:
    """Latest coverage should normalize integer, compact string, and dashed dates."""
    test_data_quality_snapshot_normalizes_trade_date()
