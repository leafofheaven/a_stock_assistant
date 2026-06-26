"""Tests for DuckDB storage operations."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


def test_initialize_creates_core_tables(tmp_path: Path) -> None:
    """Schema initialization should create all project tables in a temp database."""
    store = DuckDBStore(tmp_path / "test.duckdb")

    store.initialize()

    with store.connect() as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }

    assert {
        "stock_basic",
        "trade_calendar",
        "daily_price",
        "daily_basic",
        "adj_factor",
        "factor_values",
        "factor_scores",
        "strategy_result",
        "backtest_result",
    }.issubset(table_names)


def test_write_dataframe_appends_rows(tmp_path: Path) -> None:
    """write_dataframe should append rows to an initialized table."""
    store = DuckDBStore(tmp_path / "test.duckdb")
    store.initialize()
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "symbol": ["000001"],
            "name": ["平安银行"],
            "area": ["深圳"],
            "industry": ["银行"],
            "market": ["主板"],
            "list_date": ["19910403"],
            "delist_date": [None],
            "is_hs": ["S"],
        }
    )

    inserted = store.write_dataframe("stock_basic", df)
    result = store.read_table("stock_basic")

    assert inserted == 1
    assert result.loc[0, "ts_code"] == "000001.SZ"
    assert result.loc[0, "name"] == "平安银行"


def test_upsert_dataframe_replaces_existing_key_rows(tmp_path: Path) -> None:
    """upsert_dataframe should replace rows with matching table keys."""
    store = DuckDBStore(tmp_path / "test.duckdb")
    store.initialize()
    initial = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240102"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "pre_close": [10.0],
            "change": [0.2],
            "pct_chg": [2.0],
            "vol": [1000.0],
            "amount": [100000.0],
        }
    )
    updated = initial.assign(close=[10.8], amount=[120000.0])

    store.upsert_dataframe("daily_price", initial)
    store.upsert_dataframe("daily_price", updated)
    result = store.read_table("daily_price")

    assert len(result) == 1
    assert result.loc[0, "close"] == 10.8
    assert result.loc[0, "amount"] == 120000.0


def test_read_date_range_filters_by_trade_date(tmp_path: Path) -> None:
    """read_date_range should return rows inside the requested inclusive range."""
    store = DuckDBStore(tmp_path / "test.duckdb")
    store.initialize()
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "trade_date": ["20240102", "20240103", "20240104"],
            "pe": [8.0, 8.1, 8.2],
            "pb": [0.8, 0.81, 0.82],
            "ps": [1.0, 1.1, 1.2],
            "turnover_rate": [1.0, 1.1, 1.2],
            "volume_ratio": [0.9, 1.0, 1.1],
            "total_mv": [100.0, 101.0, 102.0],
            "circ_mv": [80.0, 81.0, 82.0],
        }
    )

    store.upsert_dataframe("daily_basic", df)
    result = store.read_date_range("daily_basic", "20240103", "20240104")

    assert result["trade_date"].tolist() == ["20240103", "20240104"]


def test_store_uses_configured_duckdb_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DuckDBStore should read DUCKDB_PATH from app settings when no path is provided."""
    configured_path = tmp_path / "configured.duckdb"

    class MockSettings:
        duckdb_path = configured_path

    monkeypatch.setattr("core.storage.duckdb_store.get_settings", lambda: MockSettings())

    store = DuckDBStore()
    store.initialize()

    assert store.db_path == configured_path
    assert configured_path.exists()


def test_rejects_unknown_table_names(tmp_path: Path) -> None:
    """Store methods should reject unknown table names before SQL execution."""
    store = DuckDBStore(tmp_path / "test.duckdb")
    store.initialize()

    with pytest.raises(DuckDBStoreError, match="Unsupported table"):
        store.read_table("not_a_table")


def test_upsert_requires_key_columns(tmp_path: Path) -> None:
    """Incremental upsert should fail clearly when key columns are missing."""
    store = DuckDBStore(tmp_path / "test.duckdb")
    store.initialize()

    with pytest.raises(DuckDBStoreError, match="missing key columns"):
        store.upsert_dataframe("daily_price", pd.DataFrame({"ts_code": ["000001.SZ"]}))
