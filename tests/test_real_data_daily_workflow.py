"""Tests for real-data daily workflow compatibility with temporary DuckDB."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.jobs.diagnose_real_data import diagnose_real_data
from core.jobs.run_daily_selection import run_daily_selection
from core.jobs.update_real_data import update_real_data
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import describe_dashboard_data_source


class WorkflowSettings:
    """Settings-like object for daily workflow tests."""

    tushare_token = "mock-token"
    data_provider = "tushare"
    default_top_n = 3
    duckdb_path = Path("unused.duckdb")
    real_data_start_date = "20240101"
    real_data_end_date = "20240202"
    real_data_sample_symbols = "000001.SZ,600000.SH,000002.SZ"
    akshare_sample_symbols = "000001,600000,000002"

    @property
    def sample_symbols(self) -> list[str]:
        """Return Tushare-style sample symbols."""
        return ["000001.SZ", "600000.SH", "000002.SZ"]

    @property
    def akshare_symbols(self) -> list[str]:
        """Return AKShare-style sample symbols."""
        return ["000001", "600000", "000002"]


class MockDailyClient:
    """Mock provider returning enough rows for a daily update."""

    def __init__(self, missing_daily_basic_fields: bool = False) -> None:
        self.missing_daily_basic_fields = missing_daily_basic_fields

    def get_stock_basic(self) -> pd.DataFrame:
        """Return stock basic rows."""
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
        """Return calendar rows."""
        dates = _dates()
        return pd.DataFrame(
            {
                "exchange": ["SSE"] * len(dates),
                "cal_date": dates,
                "is_open": [1] * len(dates),
                "pretrade_date": [None, *dates[:-1]],
            }
        )

    def get_daily_price(self, start_date: str, end_date: str, symbols: list[str]) -> pd.DataFrame:
        """Return daily price rows for sample symbols."""
        rows = []
        for symbol_index, symbol in enumerate(symbols):
            for day_index, trade_date in enumerate(_dates()):
                close = 10 + symbol_index + day_index * 0.05
                rows.append(
                    {
                        "ts_code": symbol,
                        "trade_date": trade_date,
                        "open": close - 0.01,
                        "high": close + 0.1,
                        "low": close - 0.1,
                        "close": close,
                        "pre_close": close - 0.05,
                        "change": 0.05,
                        "pct_chg": 0.5,
                        "vol": 1_000_000.0,
                        "amount": 200_000_000.0 + day_index,
                    }
                )
        return pd.DataFrame(rows)

    def get_daily_basic(self, start_date: str, end_date: str, symbols: list[str]) -> pd.DataFrame:
        """Return daily basic rows, optionally missing non-key fields."""
        rows = []
        for symbol in symbols:
            for trade_date in _dates():
                row = {
                    "ts_code": symbol,
                    "trade_date": trade_date,
                    "turnover_rate": 1.0,
                    "pe": 8.0,
                }
                if not self.missing_daily_basic_fields:
                    row.update(
                        {
                            "volume_ratio": 1.0,
                            "pb": 0.8,
                            "ps": 1.0,
                            "total_mv": 100_000_000_000.0,
                            "circ_mv": 80_000_000_000.0,
                        }
                    )
                rows.append(row)
        return pd.DataFrame(rows)

    def get_adj_factor(self, start_date: str, end_date: str, symbols: list[str]) -> pd.DataFrame:
        """Return adjustment factor rows."""
        return pd.DataFrame(
            [
                {"ts_code": symbol, "trade_date": trade_date, "adj_factor": 1.0}
                for symbol in symbols
                for trade_date in _dates()
            ]
        )


def test_repeated_update_does_not_duplicate_rows(tmp_path: Path) -> None:
    """Repeated updates should upsert by keys rather than append duplicates."""
    store = DuckDBStore(tmp_path / "daily.duckdb")
    settings = WorkflowSettings()
    client = MockDailyClient()

    first = update_real_data(settings=settings, store=store, client=client)
    second = update_real_data(settings=settings, store=store, client=client)

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert first["after_rows"] == second["after_rows"]
    assert len(store.read_table("daily_price")) == len(_dates()) * 3


def test_missing_provider_fields_are_filled_before_write(tmp_path: Path) -> None:
    """Missing non-key fields should become nullable table columns, not crashes."""
    store = DuckDBStore(tmp_path / "missing-fields.duckdb")

    result = update_real_data(
        settings=WorkflowSettings(),
        store=store,
        client=MockDailyClient(missing_daily_basic_fields=True),
    )

    daily_basic = store.read_table("daily_basic")
    assert result["status"] == "success"
    assert "pb" in daily_basic.columns
    assert daily_basic["pb"].isna().all()


def test_run_daily_selection_real_data_insufficient_does_not_crash(tmp_path: Path) -> None:
    """Partial real data should clearly fall back to sample."""
    store = DuckDBStore(tmp_path / "partial.duckdb")
    store.initialize()

    summary = run_daily_selection(settings=WorkflowSettings(), store=store)

    assert "sample" in summary["data_source"]
    assert summary["fallback_to_sample"] is True
    assert "真实数据不足，已回退 sample 数据" in summary["result_location"]


def test_diagnose_real_data_output_structure(tmp_path: Path) -> None:
    """Diagnosis should include row counts, field checks, readiness, and next steps."""
    store = DuckDBStore(tmp_path / "diagnose.duckdb")
    update_real_data(settings=WorkflowSettings(), store=store, client=MockDailyClient())

    result = diagnose_real_data(settings=WorkflowSettings(), store=store)

    assert result["table_rows"]["daily_price"] == len(_dates()) * 3
    assert result["latest_price_date"] == _dates()[-1]
    assert "daily_basic" in result["missing_fields"]
    assert "is_ready_for_selection" in result
    assert result["next_steps"]


def test_streamlit_helper_identifies_sample_real_and_insufficient_data() -> None:
    """Streamlit helper should label sample, real, and insufficient states."""
    sample = describe_dashboard_data_source({"data_source": "sample 数据（演示）", "tables": {}})
    real = describe_dashboard_data_source(
        {
            "data_source": "tushare 本地 DuckDB 真实数据",
            "tables": {"daily_price": pd.DataFrame({"trade_date": ["20240101", "20240105"]})},
        }
    )
    insufficient = describe_dashboard_data_source({"data_source": "tushare 本地 DuckDB 真实数据", "tables": {}})

    assert "演示数据" in sample["message"]
    assert "最新交易日期：20240105" in real["message"]
    assert "真实数据不足" in insufficient["message"]


def _dates() -> list[str]:
    """Return deterministic business dates for mock daily workflow data."""
    return pd.bdate_range("2024-01-01", periods=25).strftime("%Y%m%d").tolist()
