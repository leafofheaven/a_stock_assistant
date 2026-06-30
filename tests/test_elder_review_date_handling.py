"""Tests for Task 52 Elder review date handling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.jobs.track_watchlist import track_watchlist
from core.review.tracking import read_watchlist_daily_snapshots
from core.storage.duckdb_store import DuckDBStore
from core.technical.elder import build_elder_review
from web.streamlit_app import _safe_read_dashboard_price_history


def test_elder_review_uses_stock_latest_available_date_before_global_latest() -> None:
    """A stock with long history ending before the global latest date should still be reviewed."""
    candidate = pd.DataFrame(
        [{"rank": 1, "ts_code": "603986.SH", "name": "兆易创新", "trade_date": "20260630", "total_score": 68.0}]
    )
    price = pd.concat(
        [
            _price_frame("603986.SH", "2024-03-01", 599, end_override="20260626"),
            _price_frame("000725.SZ", "2024-03-01", 601, end_override="20260630"),
        ],
        ignore_index=True,
    )

    review = build_elder_review(candidate, price)
    row = review.iloc[0]

    assert row["review_date"] == "20260626"
    assert row["price_row_count"] >= 120
    assert row["action_hint"] != "数据不足"
    assert "日线数据不足" not in str(row["elder_reason"])
    assert "使用该股票最新可用日期 20260626 复核" in str(row["elder_reason"])


def test_elder_review_only_marks_daily_insufficient_for_short_history() -> None:
    """Only genuinely short daily history should produce 日线数据不足."""
    candidate = pd.DataFrame(
        [{"rank": 1, "ts_code": "000001.SZ", "name": "平安银行", "trade_date": "20260630", "total_score": 80.0}]
    )

    review = build_elder_review(candidate, _price_frame("000001.SZ", "2026-06-01", 10))

    assert review.iloc[0]["action_hint"] == "数据不足"
    assert "日线数据不足" in str(review.iloc[0]["elder_reason"])


def test_elder_review_distinguishes_weekly_sample_insufficient_from_daily_insufficient() -> None:
    """Daily data can be enough while weekly/long-cycle samples are still insufficient."""
    candidate = pd.DataFrame(
        [{"rank": 1, "ts_code": "000001.SZ", "name": "平安银行", "trade_date": "20260430", "total_score": 80.0}]
    )

    review = build_elder_review(candidate, _price_frame("000001.SZ", "2026-03-02", 40), min_daily_rows=35)

    assert review.iloc[0]["action_hint"] == "数据不足"
    assert "周线样本不足" in str(review.iloc[0]["elder_reason"])
    assert "日线数据不足" not in str(review.iloc[0]["elder_reason"])


def test_streamlit_reads_complete_price_history_for_current_selection(tmp_path: Path) -> None:
    """Dashboard helper should not rely on a truncated full-universe daily_price sample."""
    store = DuckDBStore(tmp_path / "elder-dashboard.duckdb")
    store.initialize()
    filler = _price_frame("000001.SZ", "2024-01-01", 80)
    target = _price_frame("603986.SH", "2024-01-01", 120)
    store.upsert_dataframe("daily_price", pd.concat([filler, target], ignore_index=True))
    selection = pd.DataFrame([{"ts_code": "603986.SH", "trade_date": "20260630", "rank": 1, "total_score": 68.0}])

    focused = _safe_read_dashboard_price_history(store, {"strategy_result": selection, "daily_price": filler})

    assert set(focused["ts_code"].unique()) == {"603986.SH"}
    assert len(focused) == 120


def test_track_watchlist_refreshes_old_daily_insufficient_elder_snapshot(tmp_path: Path) -> None:
    """Tracking rerun should replace stale 日线数据不足 Elder fields for the same date."""
    settings = SimpleNamespace(data_provider="akshare", duckdb_path=tmp_path / "watch.duckdb", default_top_n=10)
    store = DuckDBStore(settings.duckdb_path)
    store.initialize()
    store.upsert_dataframe(
        "strategy_result",
        pd.DataFrame(
            [
                {
                    "trade_date": "20260630",
                    "rank": 1,
                    "ts_code": "603986.SH",
                    "name": "兆易创新",
                    "industry": "半导体",
                    "total_score": 68.0,
                }
            ]
        ),
    )
    store.upsert_dataframe("daily_price", _price_frame("603986.SH", "2024-03-01", 599, end_override="20260626"))
    store.upsert_dataframe(
        "review_decisions",
        pd.DataFrame(
            [
                {
                    "decision_id": "603986.SH-20260630",
                    "ts_code": "603986.SH",
                    "name": "兆易创新",
                    "decision": "watch",
                    "reason": "测试观察",
                    "selection_date": "20260630",
                    "review_date": "20260630",
                    "review_status": "active",
                }
            ]
        ),
    )
    track_watchlist(snapshot_date="20260630", quiet=True, settings=settings, store=store)

    snapshot = read_watchlist_daily_snapshots(store)
    row = snapshot[(snapshot["ts_code"] == "603986.SH") & (snapshot["trade_date"] == "20260630")].iloc[0]

    assert row["elder_score"] != 0
    assert "日线数据不足" not in str(row["elder_reason"])


def _price_frame(ts_code: str, start: str, days: int, end_override: str | None = None) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=days).strftime("%Y%m%d").tolist()
    if end_override:
        dates[-1] = end_override
    rows = []
    previous = 10.0
    for index, trade_date in enumerate(dates):
        close = 10.0 + index * 0.05
        rows.append(
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "open": previous,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "pre_close": previous,
                "change": close - previous,
                "pct_chg": (close / previous - 1) * 100 if previous else 0.0,
                "vol": 1_000_000 + index,
                "amount": close * (1_000_000 + index),
            }
        )
        previous = close
    return pd.DataFrame(rows)
