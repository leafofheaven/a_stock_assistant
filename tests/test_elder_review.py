"""Tests for Elder-style technical review."""

from __future__ import annotations

import pandas as pd

from core.jobs.run_elder_review import render_elder_review_markdown, run_elder_review
from core.technical.elder import calculate_elder_indicators, build_elder_review


class SampleSettings:
    """Minimal settings object for sample review tests."""

    data_provider = "sample"
    duckdb_path = "unused.duckdb"


def test_calculate_elder_indicators_adds_ema_macd_force_and_elder_ray() -> None:
    """EMA, MACD histogram, Force Index and Elder Ray columns should be present."""
    indicators = calculate_elder_indicators(_price_frame(days=50))

    latest = indicators[indicators["ts_code"] == "000001.SZ"].iloc[-1]

    assert latest["ema13"] > 0
    assert latest["ema22"] > 0
    assert "macd_histogram" in indicators.columns
    assert "macd_histogram_slope" in indicators.columns
    assert "force_index_2d" in indicators.columns
    assert "force_index_13d" in indicators.columns
    assert latest["bull_power"] == latest["high"] - latest["ema13"]
    assert latest["bear_power"] == latest["low"] - latest["ema13"]


def test_build_elder_review_handles_insufficient_data_without_crashing() -> None:
    """Short price history should return 数据不足 instead of raising."""
    result = build_elder_review(_candidates(), _price_frame(days=10))

    assert result["action_hint"].tolist() == ["数据不足", "数据不足"]
    assert result["elder_score"].tolist() == [0, 0]


def test_elder_review_does_not_change_total_score_order() -> None:
    """Secondary review should preserve input rank and total_score ordering."""
    candidates = _candidates()
    result = build_elder_review(candidates, _price_frame(days=70))

    assert result["ts_code"].tolist() == candidates["ts_code"].tolist()
    assert result["rank"].tolist() == candidates["rank"].tolist()
    assert result["total_score"].tolist() == candidates["total_score"].tolist()
    assert "action_hint" in result.columns
    assert "elder_reason" in result.columns


def test_run_elder_review_sample_mode_returns_review_rows() -> None:
    """CLI job core should run with packaged sample data."""
    result = run_elder_review(settings=SampleSettings())

    assert result["review_count"] > 0
    assert not result["elder_review_df"].empty
    assert "elder_score" in result["elder_review_df"].columns


def test_render_elder_review_markdown_contains_action_hint() -> None:
    """Markdown rendering should include review hints and keep total_score."""
    result = {
        "data_source": "sample 数据（演示）",
        "latest_price_date": "20240131",
        "candidate_count": 1,
        "review_count": 1,
        "elder_review_df": pd.DataFrame(
            {
                "rank": [1],
                "ts_code": ["000001.SZ"],
                "name": ["平安银行"],
                "total_score": [88.0],
                "elder_score": [80],
                "action_hint": ["趋势确认，进入人工复核"],
                "elder_reason": ["周线趋势改善，日线接近 EMA。"],
            }
        ),
    }

    markdown = render_elder_review_markdown(result)

    assert "埃尔德技术复核" in markdown
    assert "total_score" in markdown
    assert "趋势确认，进入人工复核" in markdown


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rank": [1, 2],
            "ts_code": ["000001.SZ", "000002.SZ"],
            "name": ["平安银行", "万科A"],
            "industry": ["银行", "房地产"],
            "trade_date": ["20240628", "20240628"],
            "total_score": [90.0, 80.0],
        }
    )


def _price_frame(days: int = 70) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-01-01", periods=days).strftime("%Y%m%d")
    for ts_code, base, step in [("000001.SZ", 10.0, 0.08), ("000002.SZ", 12.0, 0.04)]:
        previous = base
        for index, trade_date in enumerate(dates):
            close = base + index * step
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": previous,
                    "high": close * 1.02,
                    "low": close * 0.98,
                    "close": close,
                    "vol": 1_000_000 + index * 1000,
                    "amount": (1_000_000 + index * 1000) * close,
                }
            )
            previous = close
    return pd.DataFrame(rows)
