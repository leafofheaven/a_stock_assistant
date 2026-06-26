"""Tests for minimal real Tushare ingestion without external API calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.jobs.run_daily_selection import run_daily_selection
from core.jobs.update_real_data import update_real_data
from core.storage.duckdb_store import DuckDBStore


class MockSettings:
    """Settings-like object for real ingestion tests."""

    tushare_token = "mock-token"
    data_provider = "tushare"
    real_data_start_date = "20240101"
    real_data_end_date = "20240105"
    real_data_sample_symbols = "000001.SZ,600000.SH"

    @property
    def sample_symbols(self) -> list[str]:
        """Return mock sample symbols."""
        return ["000001.SZ", "600000.SH"]


class EmptyTokenSettings(MockSettings):
    """Settings-like object with no Tushare token."""

    tushare_token = ""


class MockTushareClient:
    """Mock Tushare client returning project-shaped DataFrames."""

    def get_stock_basic(self) -> pd.DataFrame:
        """Return mock stock basic data."""
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "600000.SH", "000002.SZ"],
                "symbol": ["000001", "600000", "000002"],
                "name": ["平安银行", "浦发银行", "万科A"],
                "area": ["深圳", "上海", "深圳"],
                "industry": ["银行", "银行", "房地产"],
                "market": ["主板", "主板", "主板"],
                "list_date": ["19910403", "19991110", "19910129"],
                "delist_date": [None, None, None],
                "is_hs": ["S", "H", "S"],
            }
        )

    def get_trade_calendar(self) -> pd.DataFrame:
        """Return mock trade calendar data."""
        return pd.DataFrame(
            {
                "exchange": ["SSE", "SSE"],
                "cal_date": ["20240102", "20240103"],
                "is_open": [1, 1],
                "pretrade_date": ["20231229", "20240102"],
            }
        )

    def get_daily_price(self, start_date: str, end_date: str, symbols: list[str]) -> pd.DataFrame:
        """Return mock daily prices for requested sample symbols."""
        return pd.DataFrame(
            {
                "ts_code": symbols,
                "trade_date": [start_date, end_date],
                "open": [10.0, 8.0],
                "high": [10.5, 8.3],
                "low": [9.8, 7.9],
                "close": [10.2, 8.1],
                "pre_close": [10.0, 8.0],
                "change": [0.2, 0.1],
                "pct_chg": [2.0, 1.25],
                "vol": [1000.0, 900.0],
                "amount": [100000.0, 90000.0],
            }
        )

    def get_daily_basic(self, start_date: str, end_date: str, symbols: list[str]) -> pd.DataFrame:
        """Return mock daily basic data."""
        return pd.DataFrame(
            {
                "ts_code": symbols,
                "trade_date": [start_date, end_date],
                "turnover_rate": [1.0, 1.1],
                "volume_ratio": [0.9, 1.0],
                "pe": [8.5, 7.9],
                "pb": [0.8, 0.7],
                "ps": [1.2, 1.1],
                "total_mv": [100.0, 90.0],
                "circ_mv": [80.0, 70.0],
            }
        )

    def get_adj_factor(self, start_date: str, end_date: str, symbols: list[str]) -> pd.DataFrame:
        """Return mock adjustment factors."""
        return pd.DataFrame(
            {
                "ts_code": symbols,
                "trade_date": [start_date, end_date],
                "adj_factor": [1.0, 1.0],
            }
        )


def test_update_real_data_skips_clearly_without_token() -> None:
    """Missing token should produce a clear skipped summary instead of crashing."""
    result = update_real_data(settings=EmptyTokenSettings())

    assert result["status"] == "skipped"
    assert "TUSHARE_TOKEN 为空" in result["message"]
    assert all(row_count == 0 for row_count in result["written_rows"].values())


def test_update_real_data_writes_mock_frames_to_temp_duckdb(tmp_path: Path) -> None:
    """Real ingestion should upsert mock Tushare frames into a temporary DuckDB."""
    store = DuckDBStore(tmp_path / "real.duckdb")

    result = update_real_data(settings=MockSettings(), store=store, client=MockTushareClient())

    assert result["status"] == "success"
    assert result["written_rows"]["stock_basic"] == 2
    assert result["written_rows"]["daily_price"] == 2
    assert store.read_table("stock_basic")["ts_code"].tolist() == ["000001.SZ", "600000.SH"]
    assert set(store.read_table("daily_price").columns).issuperset({"ts_code", "trade_date", "close"})
    assert len(store.read_table("adj_factor")) == 2


def test_run_daily_selection_still_uses_sample_when_real_data_missing(tmp_path: Path) -> None:
    """Daily selection smoke should still work when real DuckDB data is unavailable."""
    store = DuckDBStore(tmp_path / "empty.duckdb")

    summary = run_daily_selection(settings=MockSettings(), store=store)

    assert "sample" in summary["data_source"]
    assert summary["candidate_count"] > 0


def test_no_real_token_is_committed() -> None:
    """Repository examples must not contain a real Tushare token."""
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "TUSHARE_TOKEN=" in env_example
    token_line = next(line for line in env_example.splitlines() if line.startswith("TUSHARE_TOKEN="))
    assert token_line == "TUSHARE_TOKEN="
