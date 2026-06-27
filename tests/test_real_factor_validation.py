"""Tests for real factor validation diagnostics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.jobs.diagnose_factors import diagnose_factors
from core.jobs.run_daily_selection import run_daily_selection
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import summarize_factor_missing, summarize_update_status


class AkshareSettings:
    """Settings-like object for AKShare real-data validation tests."""

    data_provider = "akshare"
    default_top_n = 30
    duckdb_path = Path("unused.duckdb")


class SampleSettings:
    """Settings-like object for sample smoke validation."""

    data_provider = "sample"


def test_diagnose_factors_identifies_empty_duckdb(tmp_path: Path) -> None:
    """diagnose_factors should clearly identify an empty missing temporary duckdb."""
    store = DuckDBStore(tmp_path / "missing.duckdb")

    result = diagnose_factors(settings=AkshareSettings(), store=store, use_sample=False)

    assert result["data_type"] == "无数据"
    assert result["factor_calculable_count"] == 0
    assert result["total_score_non_null_count"] == 0
    assert "DuckDB 文件不存在" in result["reasons"][0]


def test_diagnose_factors_with_real_mock_data_reports_quality(tmp_path: Path) -> None:
    """diagnose_factors should summarize real factor coverage from mock DuckDB data."""
    store = _write_real_frames(tmp_path / "factors.duckdb", *_real_frames(days=80, missing_valuation=True))

    result = diagnose_factors(settings=AkshareSettings(), store=store, use_sample=False)

    assert result["data_type"] == "akshare 本地 DuckDB 真实数据"
    assert result["latest_price_date"] == "20240628"
    assert result["stock_pool_count"] == 3
    assert result["factor_calculable_count"] == 3
    assert result["total_score_non_null_count"] == 3
    assert result["factor_quality"]["total_score"]["non_null_rate"] == 1.0
    assert len(result["top_10"]) == 3
    assert any("pe/pb" in note for note in result["data_quality_notes"])


def test_factor_nan_and_missing_pe_pb_do_not_crash_akshare_flow(tmp_path: Path) -> None:
    """NaN factor inputs and empty PE/PB should not crash AKShare fallback scoring."""
    stock_basic, daily_price, daily_basic = _real_frames(days=80, missing_valuation=True)
    daily_price.loc[daily_price.index[:3], "close"] = pd.NA
    daily_basic["pe"] = pd.NA
    daily_basic["pb"] = pd.NA
    store = _write_real_frames(tmp_path / "nan-factors.duckdb", stock_basic, daily_price, daily_basic)

    result = diagnose_factors(settings=AkshareSettings(), store=store, use_sample=False)

    assert result["factor_calculable_count"] == 3
    assert result["total_score_non_null_count"] == 3
    assert result["has_anomaly"] is False


def test_insufficient_20d_60d_data_has_clear_reason(tmp_path: Path) -> None:
    """Short real history should not crash and should produce a concrete reason."""
    store = _write_real_frames(tmp_path / "short.duckdb", *_real_frames(days=10, missing_valuation=True))

    result = diagnose_factors(settings=AkshareSettings(), store=store, use_sample=False)

    assert result["factor_calculable_count"] == 0
    assert result["total_score_non_null_count"] == 0
    assert "股票池过滤后无可交易股票" in result["reasons"][0]


def test_run_daily_selection_reports_real_and_sample_status(tmp_path: Path) -> None:
    """run_daily_selection should distinguish real data and sample fallback states."""
    store = _write_real_frames(tmp_path / "selection.duckdb", *_real_frames(days=80, missing_valuation=True))

    real_summary = run_daily_selection(settings=AkshareSettings(), store=store, use_sample=False)
    sample_summary = run_daily_selection(settings=SampleSettings(), use_sample=True)

    assert real_summary["is_real_data"] is True
    assert real_summary["fallback_to_sample"] is False
    assert real_summary["factor_calculable_count"] == 3
    assert real_summary["total_score_non_null_count"] == 3
    assert "pe/pb" in real_summary["data_quality_note"]
    assert "sample" in sample_summary["data_source"]
    assert sample_summary["is_real_data"] is False


def test_streamlit_helpers_identify_sample_real_and_insufficient_data() -> None:
    """Streamlit helper should recognize sample, real, and insufficient data states."""
    factor_df = pd.DataFrame(
        {
            "trade_date": ["20240628", "20240628"],
            "trend_score": [80.0, None],
            "total_score": [70.0, 60.0],
        }
    )
    real_status = summarize_update_status(
        {
            "_data_source": "akshare 本地 DuckDB 真实数据",
            "daily_price": pd.DataFrame({"trade_date": ["20240628"]}),
            "factor_scores": factor_df,
            "strategy_result": pd.DataFrame({"trade_date": ["20240628"]}),
        }
    )
    sample_status = summarize_update_status({"_data_source": "sample 数据（演示）"})
    insufficient_status = summarize_update_status({"_data_source": "真实数据不足"})

    assert real_status["is_real_data"] is True
    assert real_status["is_sample_data"] is False
    assert real_status["factor_missing"]["trend_score"]["nan_count"] == 1
    assert summarize_factor_missing(factor_df)["total_score"]["non_null_rate"] == 1.0
    assert sample_status["is_sample_data"] is True
    assert insufficient_status["is_real_data"] is False


def test_sample_smoke_still_passes_with_factor_validation() -> None:
    """sample smoke test should remain available."""
    summary = run_daily_selection(settings=SampleSettings(), use_sample=True)

    assert "sample" in summary["data_source"]
    assert summary["candidate_count"] > 0


def _real_frames(days: int, missing_valuation: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return mock real-data frames without external Tushare, AKShare, or Eastmoney calls."""
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
            close = 10 + symbol_index + index * 0.03
            price_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": close - 0.02,
                    "high": close + 0.05,
                    "low": close - 0.05,
                    "close": close,
                    "pre_close": None,
                    "change": 0.03,
                    "pct_chg": 0.3,
                    "vol": 1000 + index,
                    "amount": 150_000_000 + symbol_index * 30_000_000,
                }
            )
            basic_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "turnover_rate": 1.0 + symbol_index * 0.2,
                    "volume_ratio": None,
                    "pe": None if missing_valuation else 8.0 + symbol_index,
                    "pb": None if missing_valuation else 0.8 + symbol_index * 0.1,
                    "ps": None,
                    "total_mv": None if missing_valuation else 10_000_000_000,
                    "circ_mv": None if missing_valuation else 8_000_000_000,
                }
            )
    return stock_basic, pd.DataFrame(price_rows), pd.DataFrame(basic_rows)


def _write_real_frames(
    db_path: Path,
    stock_basic: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
) -> DuckDBStore:
    """Write mock frames to a temporary duckdb database."""
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
