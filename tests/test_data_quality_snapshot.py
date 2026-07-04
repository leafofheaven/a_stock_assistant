"""Tests for shared read-only data quality snapshots."""

from __future__ import annotations

import pandas as pd

from core.diagnostics.data_quality_snapshot import build_data_quality_snapshot
from core.storage.duckdb_store import DuckDBStore


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


def test_any_daily_price_symbol_count_counts_all_distinct_daily_price_symbols(tmp_path) -> None:
    """SQL snapshot should count every distinct daily_price symbol for any-history coverage."""
    db_path = tmp_path / "quality.duckdb"
    store = DuckDBStore(db_path)
    store.initialize()
    symbols = [f"{index:06d}.SZ" for index in range(1, 5056)]
    priced_symbols = symbols[:4995]
    store.upsert_dataframe("stock_basic", pd.DataFrame({"ts_code": symbols, "symbol": [code[:6] for code in symbols], "name": symbols}))
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            {
                "ts_code": priced_symbols,
                "trade_date": ["20260703"] * 68 + ["20260702"] * (len(priced_symbols) - 68),
                "open": [1.0] * len(priced_symbols),
                "high": [1.0] * len(priced_symbols),
                "low": [1.0] * len(priced_symbols),
                "close": [1.0] * len(priced_symbols),
                "pre_close": [1.0] * len(priced_symbols),
                "change": [0.0] * len(priced_symbols),
                "pct_chg": [0.0] * len(priced_symbols),
                "vol": [1.0] * len(priced_symbols),
                "amount": [1.0] * len(priced_symbols),
            }
        ),
    )

    snapshot = build_data_quality_snapshot(db_path=db_path, latest_completed_trade_date="20260703")

    assert snapshot["any_daily_price_symbol_count"] == 4995
    assert snapshot["any_daily_price_symbol_count"] != 62
    assert snapshot["missing_any_daily_price_symbol_count"] == 60


def test_latest_daily_price_symbol_count_counts_only_latest_trade_date(tmp_path) -> None:
    """SQL snapshot should count only target latest trade-date symbols."""
    db_path = tmp_path / "latest.duckdb"
    store = DuckDBStore(db_path)
    store.initialize()
    symbols = [f"{index:06d}.SZ" for index in range(1, 101)]
    store.upsert_dataframe("stock_basic", pd.DataFrame({"ts_code": symbols, "symbol": [code[:6] for code in symbols], "name": symbols}))
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            {
                "ts_code": symbols[:90],
                "trade_date": ["20260703"] * 68 + ["20260702"] * 22,
                "open": [1.0] * 90,
                "high": [1.0] * 90,
                "low": [1.0] * 90,
                "close": [1.0] * 90,
                "pre_close": [1.0] * 90,
                "change": [0.0] * 90,
                "pct_chg": [0.0] * 90,
                "vol": [1.0] * 90,
                "amount": [1.0] * 90,
            }
        ),
    )

    snapshot = build_data_quality_snapshot(db_path=db_path, latest_completed_trade_date="20260703")

    assert snapshot["latest_daily_price_symbol_count"] == 68
    assert snapshot["latest_daily_price_symbol_count"] != 0
    assert snapshot["latest_daily_price_symbol_count"] != 90


def test_history_missing_uses_any_history_not_252day_window(tmp_path) -> None:
    """Missing history should mean no daily_price rows, not less than 252 rows."""
    db_path = tmp_path / "history-missing.duckdb"
    store = DuckDBStore(db_path)
    store.initialize()
    symbols = [f"{index:06d}.SZ" for index in range(1, 11)]
    store.upsert_dataframe("stock_basic", pd.DataFrame({"ts_code": symbols, "symbol": [code[:6] for code in symbols], "name": symbols}))
    rows = []
    for index, symbol in enumerate(symbols[:8]):
        days = 252 if index < 2 else 12
        rows.extend(
            {
                "ts_code": symbol,
                "trade_date": f"202601{day + 1:02d}",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "pre_close": 1.0,
                "change": 0.0,
                "pct_chg": 0.0,
                "vol": 1.0,
                "amount": 1.0,
            }
            for day in range(days)
        )
    store.upsert_dataframe("daily_price", pd.DataFrame(rows))

    snapshot = build_data_quality_snapshot(db_path=db_path, latest_completed_trade_date="20260703")

    assert snapshot["any_daily_price_symbol_count"] == 8
    assert snapshot["history_missing_symbol_count"] == 2
    assert snapshot["history_complete_symbol_count"] == 2
    assert snapshot["history_incomplete_symbol_count"] == 6


def test_history_complete_is_separate_from_any_history_coverage(tmp_path) -> None:
    """252-day completeness must not overwrite any-history coverage."""
    db_path = tmp_path / "history-complete-separate.duckdb"
    store = DuckDBStore(db_path)
    store.initialize()
    symbols = [f"{index:06d}.SZ" for index in range(1, 6)]
    store.upsert_dataframe("stock_basic", pd.DataFrame({"ts_code": symbols, "symbol": [code[:6] for code in symbols], "name": symbols}))
    rows = []
    for index, symbol in enumerate(symbols):
        days = 252 if index == 0 else 3
        rows.extend(
            {
                "ts_code": symbol,
                "trade_date": f"202601{day + 1:02d}",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "pre_close": 1.0,
                "change": 0.0,
                "pct_chg": 0.0,
                "vol": 1.0,
                "amount": 1.0,
            }
            for day in range(days)
        )
    store.upsert_dataframe("daily_price", pd.DataFrame(rows))

    snapshot = build_data_quality_snapshot(db_path=db_path, latest_completed_trade_date="20260703")

    assert snapshot["any_daily_price_symbol_count"] == 5
    assert snapshot["history_complete_symbol_count"] == 1
