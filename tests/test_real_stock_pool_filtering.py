"""Tests for real-data stock pool filtering with AKShare fallback data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.jobs.run_daily_selection import run_daily_selection
from core.storage.duckdb_store import DuckDBStore
from core.universe.stock_pool import build_tradeable_universe


class AkshareSettings:
    """Settings-like object for real-data selection tests."""

    data_provider = "akshare"
    default_top_n = 30
    duckdb_path = Path("unused.duckdb")


def test_akshare_fallback_missing_list_date_and_valuation_do_not_empty_universe() -> None:
    """AKShare fallback data with missing list_date and PE/PB should still validate."""
    stock_basic, daily_price, daily_basic = _akshare_like_frames()
    trade_date = str(daily_price["trade_date"].max())

    result = build_tradeable_universe(
        stock_basic,
        daily_price,
        daily_basic,
        trade_date,
        allow_missing_list_date_with_price_history=True,
        allow_missing_valuation=True,
        min_price_history_days=60,
    )

    tradeable = result[result["is_tradeable"].fillna(False)]
    assert len(tradeable) == 3
    assert tradeable["exclude_reason"].tolist() == ["", "", ""]
    assert tradeable["avg_amount_20d"].min() > 100_000_000


def test_default_stock_pool_rules_use_price_history_and_do_not_require_market_cap() -> None:
    """Default filtering should match current free-data fields and not empty the universe."""
    stock_basic, daily_price, daily_basic = _akshare_like_frames()
    trade_date = str(daily_price["trade_date"].max())

    result = build_tradeable_universe(stock_basic, daily_price, daily_basic, trade_date)

    assert result["is_tradeable"].sum() == 3
    assert not result["exclude_reason"].str.contains("listed less than 120 days").any()
    assert not result["exclude_reason"].str.contains("severe financial data missing").any()


def test_run_daily_selection_uses_latest_real_trade_date_not_system_date(tmp_path: Path) -> None:
    """Real-data selection should use max(daily_price.trade_date) as selection date."""
    store = _write_real_frames(tmp_path / "real-selection.duckdb", *_akshare_like_frames())

    summary = run_daily_selection(settings=AkshareSettings(), store=store, use_sample=False)

    assert summary["candidate_count"] > 0
    assert summary["fallback_to_sample"] is False
    assert summary["latest_price_date"] == "20240628"
    assert summary["selection_date"] == "20240628"
    assert summary["data_source"] == "akshare 本地 DuckDB 真实数据"


def test_run_daily_selection_reports_exclude_reason_when_universe_is_empty(tmp_path: Path) -> None:
    """Empty real-data universe summaries should include per-stock exclusion diagnostics."""
    stock_basic, daily_price, daily_basic = _akshare_like_frames(amount=50_000_000)
    store = _write_real_frames(tmp_path / "empty-universe.duckdb", stock_basic, daily_price, daily_basic)

    summary = run_daily_selection(settings=AkshareSettings(), store=store, use_sample=False)

    assert summary["candidate_count"] == 0
    diagnostics = summary["universe_diagnostics"]
    assert len(diagnostics) == 3
    assert diagnostics[0]["latest_trade_date"] == "20240628"
    assert diagnostics[0]["list_date"] is None
    assert diagnostics[0]["available_price_days"] == 117
    assert diagnostics[0]["pe_missing"] is True
    assert diagnostics[0]["pb_missing"] is True
    assert "avg amount 20d below 100 million" in diagnostics[0]["exclude_reason"]


def test_sample_smoke_still_passes_with_real_filtering_changes(tmp_path: Path) -> None:
    """Sample smoke test should remain available."""
    summary = run_daily_selection(settings=AkshareSettings(), store=DuckDBStore(tmp_path / "missing.duckdb"))

    assert "sample" in summary["data_source"]
    assert summary["candidate_count"] > 0


def _akshare_like_frames(amount: float = 150_000_000) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return frames shaped like the current AKShare/Eastmoney fallback output."""
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
    dates = pd.bdate_range(end="2024-06-28", periods=117).strftime("%Y%m%d").tolist()
    price_rows: list[dict[str, object]] = []
    basic_rows: list[dict[str, object]] = []
    for symbol_index, (ts_code, _, _) in enumerate(symbols):
        for index, trade_date in enumerate(dates):
            close = 10 + symbol_index + index * 0.01
            price_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": close - 0.02,
                    "high": close + 0.05,
                    "low": close - 0.05,
                    "close": close,
                    "pre_close": None,
                    "change": 0.01,
                    "pct_chg": 0.1,
                    "vol": 1000 + index,
                    "amount": amount + symbol_index * 10_000_000,
                }
            )
            basic_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "turnover_rate": 1.0 + symbol_index * 0.1,
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
    """Write minimal real-data frames into a temporary DuckDB database."""
    store = DuckDBStore(db_path)
    store.initialize()
    store.upsert_dataframe("stock_basic", stock_basic)
    store.upsert_dataframe("daily_price", daily_price)
    store.upsert_dataframe("daily_basic", daily_basic)
    return store
