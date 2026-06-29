"""Tests for Elder review historical validation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.jobs.backtest_elder_review import (
    backtest_elder_review,
    build_elder_backtest_details,
    calculate_forward_metrics,
    elder_score_group,
    save_elder_backtest_report,
    summarize_elder_backtest,
)


class SampleSettings:
    """Minimal sample settings for backtest tests."""

    data_provider = "sample"
    duckdb_path = "unused.duckdb"


def test_forward_return_and_max_drawdown_gain_calculation() -> None:
    """Forward metrics should use rows after the signal date."""
    prices = pd.DataFrame({"close": [100, 105, 95, 110, 120, 130, 125, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 300]})

    metrics = calculate_forward_metrics(prices, 0)

    assert metrics["forward_return_5d"] == pytest.approx(0.30)
    assert metrics["forward_return_10d"] == pytest.approx(0.70)
    assert metrics["forward_return_20d"] == pytest.approx(2.00)
    assert metrics["max_drawdown_20d"] == pytest.approx(-0.05)
    assert metrics["max_gain_20d"] == pytest.approx(2.00)


def test_elder_score_group_buckets() -> None:
    """elder_score should be grouped into stable top/middle/bottom buckets."""
    assert elder_score_group(90) == "top"
    assert elder_score_group(60) == "middle"
    assert elder_score_group(20) == "bottom"
    assert elder_score_group(None) == "unknown"


def test_group_summaries_for_elder_score_and_action_hint() -> None:
    """Backtest summaries should aggregate by score group and action_hint."""
    details = pd.DataFrame(
        {
            "elder_score_group": ["top", "bottom"],
            "action_hint": ["趋势确认，进入人工复核", "趋势偏弱，暂缓"],
            "forward_return_5d": [0.10, -0.05],
            "forward_return_10d": [0.12, -0.04],
            "forward_return_20d": [0.20, -0.10],
            "max_drawdown_20d": [-0.03, -0.12],
            "max_gain_20d": [0.25, 0.02],
        }
    )

    summary = summarize_elder_backtest(details)

    score_groups = {row["group"]: row for row in summary["elder_score_group_summary"]}
    action_groups = {row["group"]: row for row in summary["action_hint_summary"]}
    assert score_groups["top"]["avg_forward_return_20d"] == pytest.approx(0.20)
    assert score_groups["bottom"]["hit_rate_5d"] == 0.0
    assert action_groups["趋势确认，进入人工复核"]["count"] == 1


def test_insufficient_data_returns_empty_details() -> None:
    """Short history should not raise and should return an empty details frame."""
    details = build_elder_backtest_details(_price_frame(days=20))

    assert details.empty


def test_signal_generation_does_not_use_future_rows(monkeypatch) -> None:
    """Each signal should be calculated from history ending at the signal date."""
    seen_latest_dates: list[str] = []

    def fake_classify(latest: pd.Series, previous: pd.Series, weekly_row: pd.Series | None):
        seen_latest_dates.append(str(latest["trade_date"]))
        return (
            80,
            "趋势确认，进入人工复核",
            "测试信号。",
            {
                "weekly_trend": "改善",
                "daily_pullback": "接近 EMA",
                "force_signal": "偏强",
                "elder_ray_signal": "多头增强/空头减弱",
            },
        )

    monkeypatch.setattr("core.jobs.backtest_elder_review._classify_elder_state", fake_classify)

    details = build_elder_backtest_details(_price_frame(days=60), min_history_rows=35, min_forward_rows=20)

    assert not details.empty
    assert seen_latest_dates
    assert seen_latest_dates == details["signal_date"].astype(str).tolist()


def test_backtest_elder_review_sample_mode_writes_reports(tmp_path: Path) -> None:
    """Sample mode should create a usable historical backtest result."""
    result = backtest_elder_review(output_dir=tmp_path, settings=SampleSettings(), report_format="all")

    assert result["data_source"] == "sample 数据（演示）"
    assert result["sample_stock_count"] > 0
    assert {"markdown", "csv", "json"}.issubset(result["generated_files"])
    assert all(Path(path).exists() for path in result["generated_files"].values())


def test_save_elder_backtest_report_outputs_markdown_and_csv(tmp_path: Path) -> None:
    """Markdown and CSV report files should be generated from details."""
    result = {
        "generated_at": "2026-06-29T10:00:00",
        "data_source": "sample 数据（演示）",
        "start_date": "20240101",
        "end_date": "20240630",
        "sample_stock_count": 1,
        "valid_signal_count": 1,
        "elder_score_group_summary": [],
        "action_hint_summary": [],
        "has_reverse_signal": False,
        "skip_reasons": ["无"],
        "risk_note": "该回看只用于个人研究，不构成交易建议。",
        "details_df": pd.DataFrame({"ts_code": ["000001.SZ"], "forward_return_5d": [0.01]}),
    }

    files = save_elder_backtest_report(result, output_dir=tmp_path, report_format="all")

    markdown = Path(files["markdown"]).read_text(encoding="utf-8")
    csv_text = Path(files["csv"]).read_text(encoding="utf-8-sig")
    assert "埃尔德复核历史回看" in markdown
    assert "forward_return_5d" in csv_text


def _price_frame(days: int = 70) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-01-01", periods=days).strftime("%Y%m%d")
    for ts_code, base in [("000001.SZ", 10.0), ("000002.SZ", 20.0)]:
        for index, trade_date in enumerate(dates):
            close = base + index * 0.08
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "name": "样本",
                    "high": close * 1.02,
                    "low": close * 0.98,
                    "close": close,
                    "vol": 1_000_000 + index,
                    "amount": (1_000_000 + index) * close,
                }
            )
    return pd.DataFrame(rows)
