"""Tests for real backtest validation diagnostics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.jobs.diagnose_backtest import diagnose_backtest
from core.jobs.run_daily_selection import run_daily_selection
from core.storage.duckdb_store import DuckDBStore


class AkshareSettings:
    """Settings-like object for AKShare real backtest tests."""

    data_provider = "akshare"
    default_top_n = 30
    duckdb_path = Path("unused.duckdb")


class SampleSettings:
    """Settings-like object for sample smoke tests."""

    data_provider = "sample"
    duckdb_path = Path("unused.duckdb")


def test_diagnose_backtest_identifies_empty_duckdb(tmp_path: Path) -> None:
    """diagnose_backtest should clearly identify an empty missing temporary duckdb."""
    store = DuckDBStore(tmp_path / "missing.duckdb")

    result = diagnose_backtest(settings=AkshareSettings(), store=store, use_sample=False)

    assert result["data_type"] == "无数据"
    assert result["equity_curve_rows"] == 0
    assert result["portfolio_built"] is False
    assert "DuckDB 文件不存在" in result["reasons"][0]


def test_diagnose_backtest_runs_on_real_mock_data(tmp_path: Path) -> None:
    """diagnose_backtest should run a minimal backtest from mock real data."""
    store = _write_real_frames(tmp_path / "backtest.duckdb", *_real_frames(days=80))

    result = diagnose_backtest(settings=AkshareSettings(), store=store, use_sample=False)

    assert result["data_type"] == "akshare 本地 DuckDB 真实数据"
    assert result["stock_count"] == 3
    assert result["price_row_count"] == 240
    assert result["score_stock_count"] == 3
    assert result["portfolio_built"] is True
    for key in ["annual_return", "max_drawdown", "sharpe_ratio", "win_rate", "turnover"]:
        assert result["metrics"][key] is not None
    assert result["equity_curve_rows"] > 0
    assert result["trade_records_rows"] > 0
    assert result["position_records_rows"] > 0
    assert result["has_anomaly"] is False
    assert any("少量样本真实数据试运行" in note for note in result["data_quality_notes"])


def test_diagnose_backtest_reports_insufficient_data(tmp_path: Path) -> None:
    """Short histories should produce clear reasons instead of crashing."""
    store = _write_real_frames(tmp_path / "short.duckdb", *_real_frames(days=10))

    result = diagnose_backtest(settings=AkshareSettings(), store=store, use_sample=False)

    assert result["equity_curve_rows"] == 0
    assert result["portfolio_built"] is False
    assert result["reasons"]


def test_run_daily_selection_reports_backtest_readiness(tmp_path: Path) -> None:
    """Daily selection summary should expose whether current scores can be backtested."""
    store = _write_real_frames(tmp_path / "selection.duckdb", *_real_frames(days=80))

    result = run_daily_selection(settings=AkshareSettings(), store=store, use_sample=False)

    assert result["backtest_ready"] is True
    assert "diagnose_backtest" in result["backtest_note"]


def test_sample_smoke_still_passes_with_backtest_validation() -> None:
    """sample smoke test should remain available."""
    summary = run_daily_selection(settings=SampleSettings(), use_sample=True)
    diagnostic = diagnose_backtest(settings=SampleSettings())

    assert "sample" in summary["data_source"]
    assert summary["candidate_count"] > 0
    assert diagnostic["data_type"] == "sample 数据（演示）"
    assert diagnostic["equity_curve_rows"] > 0


def _real_frames(days: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return mock real-data frames without Tushare, AKShare, or Eastmoney calls."""
    symbols = [
        ("000001.SZ", "平安银行", "银行"),
        ("600000.SH", "浦发银行", "银行"),
        ("000002.SZ", "万科A", "地产"),
    ]
    stock_basic = pd.DataFrame(
        [
            {
                "ts_code": ts_code,
                "symbol": ts_code.split(".")[0],
                "name": name,
                "area": None,
                "industry": industry,
                "market": None,
                "list_date": None,
                "delist_date": None,
                "is_hs": None,
            }
            for ts_code, name, industry in symbols
        ]
    )
    dates = pd.bdate_range(end="2024-06-28", periods=days).strftime("%Y%m%d").tolist()
    price_rows: list[dict[str, object]] = []
    basic_rows: list[dict[str, object]] = []
    for symbol_index, (ts_code, _, _) in enumerate(symbols):
        for index, trade_date in enumerate(dates):
            close = 10 + symbol_index + index * (0.02 + symbol_index * 0.005)
            price_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": close - 0.02,
                    "high": close + 0.05,
                    "low": close - 0.05,
                    "close": close,
                    "pre_close": None,
                    "change": 0.02,
                    "pct_chg": 0.2,
                    "vol": 1000 + index,
                    "amount": 150_000_000 + symbol_index * 40_000_000,
                }
            )
            basic_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "turnover_rate": 1.0 + symbol_index * 0.2,
                    "volume_ratio": None,
                    "pe": None,
                    "pb": None,
                    "ps": None,
                    "total_mv": None,
                    "circ_mv": None,
                }
            )
    return stock_basic, pd.DataFrame(price_rows), pd.DataFrame(basic_rows)


def _write_real_frames(
    db_path: Path,
    stock_basic: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
) -> DuckDBStore:
    """Write mock frames into a temporary duckdb database."""
    store = DuckDBStore(db_path)
    store.initialize()
    store.upsert_dataframe("stock_basic", stock_basic)
    store.upsert_dataframe("daily_price", daily_price)
    store.upsert_dataframe("daily_basic", daily_basic)
    store.upsert_dataframe(
        "adj_factor",
        pd.DataFrame(
            {
                "ts_code": stock_basic["ts_code"],
                "trade_date": [str(daily_price["trade_date"].max())] * len(stock_basic),
                "adj_factor": [1.0] * len(stock_basic),
            }
        ),
    )
    return store
