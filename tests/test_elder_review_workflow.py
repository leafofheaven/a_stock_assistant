"""Tests for Elder review export and manual review workflow integration."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.jobs.export_elder_review import add_confirmed_elder_to_watchlist, export_elder_review
from core.reporting.selection_review_report import build_selection_review_report, candidates_to_dataframe
from core.review.decisions import update_review_decision
from core.storage.duckdb_store import DuckDBStore
from core.technical.elder import build_elder_review


class SampleSettings:
    """Minimal sample settings for export tests."""

    data_provider = "sample"
    duckdb_path = "unused.duckdb"


def test_selection_review_carries_elder_fields() -> None:
    """selection_review JSON/CSV rows should include Elder review fields."""
    selection = _selection_with_elder()
    report = build_selection_review_report(
        metadata={"generated_at": "2026-06-29T10:00:00", "data_provider": "sample", "duckdb_path": "tmp.duckdb"},
        selection_summary={"is_real_data": False, "fallback_to_sample": False, "candidate_count": 1},
        selection_df=selection,
        factor_df=selection,
        price_df=pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240628"], "close": [10.0]}),
        daily_basic_df=pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240628"], "pe": [8.0], "pb": [0.8]}),
        top_n=1,
    )
    candidate = report["candidates"][0]
    csv_df = candidates_to_dataframe(report["candidates"])

    assert candidate["elder_score"] == 88.0
    assert candidate["action_hint"] == "趋势确认，进入人工复核"
    assert candidate["weekly_trend"] == "改善"
    assert "elder_score" in csv_df.columns
    assert csv_df.loc[0, "elder_reason"] == "周线趋势改善，日线接近 EMA。"


def test_elder_score_does_not_override_total_score_or_order() -> None:
    """Elder review should preserve original rank, total_score and order."""
    candidates = pd.DataFrame(
        {
            "rank": [1, 2],
            "ts_code": ["000001.SZ", "000002.SZ"],
            "name": ["A", "B"],
            "trade_date": ["20240628", "20240628"],
            "total_score": [90.0, 80.0],
        }
    )
    review = build_elder_review(candidates, _price_frame(days=70))

    assert review["rank"].tolist() == [1, 2]
    assert review["ts_code"].tolist() == ["000001.SZ", "000002.SZ"]
    assert review["total_score"].tolist() == [90.0, 80.0]


def test_export_elder_review_writes_csv_and_markdown(tmp_path: Path) -> None:
    """export_elder_review should generate CSV and Markdown files."""
    result = export_elder_review(output_dir=tmp_path, settings=SampleSettings())

    assert result["status"] == "success"
    assert "csv" in result["generated_files"]
    assert "markdown" in result["generated_files"]
    assert Path(result["generated_files"]["csv"]).exists()
    markdown = Path(result["generated_files"]["markdown"]).read_text(encoding="utf-8")
    assert "埃尔德技术复核" in markdown
    assert "操作建议" in markdown


def test_existing_watchlist_stock_is_not_added_twice(tmp_path: Path) -> None:
    """Confirmed Elder rows should skip stocks already active in watchlist."""
    store = DuckDBStore(tmp_path / "elder.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "symbol": ["000001"],
                "name": ["平安银行"],
                "area": [""],
                "industry": ["银行"],
                "market": ["主板"],
                "list_date": ["19910403"],
            }
        ),
    )
    update_review_decision(
        store=store,
        ts_code="000001.SZ",
        decision="watch",
        reason="已有观察池记录",
        selection_date="20240628",
    )
    review_df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240628"],
            "action_hint": ["趋势确认，进入人工复核"],
            "elder_score": [90],
            "elder_reason": ["周线趋势改善。"],
            "force_signal": ["由负转正"],
            "elder_ray_signal": ["多头增强/空头减弱"],
        }
    )

    result = add_confirmed_elder_to_watchlist(review_df, store)

    assert result["attempted"] == 1
    assert result["inserted"] == 0
    assert result["skipped_existing"] == 1
    decisions = store.read_table("review_decisions")
    assert len(decisions[decisions["ts_code"] == "000001.SZ"]) == 1


def test_export_elder_review_handles_insufficient_data(tmp_path: Path) -> None:
    """数据不足 should still produce a usable report."""
    result = export_elder_review(output_dir=tmp_path, settings=SampleSettings(), top_n=1)

    assert result["review_count"] >= 1
    assert "elder_review_df" in result


def _selection_with_elder() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rank": [1],
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
            "industry": ["银行"],
            "trade_date": ["20240628"],
            "total_score": [90.0],
            "trend_score": [90.0],
            "momentum_score": [80.0],
            "liquidity_score": [70.0],
            "fundamental_score": [60.0],
            "volatility_score": [50.0],
            "elder_score": [88.0],
            "action_hint": ["趋势确认，进入人工复核"],
            "elder_reason": ["周线趋势改善，日线接近 EMA。"],
            "weekly_trend": ["改善"],
            "daily_pullback": ["接近 EMA"],
            "force_signal": ["由负转正"],
            "elder_ray_signal": ["多头增强/空头减弱"],
            "review_action": ["加入观察池"],
        }
    )


def _price_frame(days: int = 70) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-01-01", periods=days).strftime("%Y%m%d")
    for ts_code, base in [("000001.SZ", 10.0), ("000002.SZ", 12.0)]:
        for index, trade_date in enumerate(dates):
            close = base + index * 0.05
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "high": close * 1.02,
                    "low": close * 0.98,
                    "close": close,
                    "vol": 1_000_000 + index,
                }
            )
    return pd.DataFrame(rows)
