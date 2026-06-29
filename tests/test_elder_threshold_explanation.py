"""Tests for Task 43 Elder explanation and layered backtest summaries."""

from __future__ import annotations

import pandas as pd

from core.jobs.backtest_elder_review import build_elder_backtest_details, render_elder_backtest_markdown, summarize_elder_backtest, total_score_group
from core.technical.elder import build_elder_review


def test_elder_reason_does_not_present_score_as_buy_priority() -> None:
    """Trend confirmation should explain rhythm and keep original 排序."""
    candidates = _candidates()
    review = build_elder_review(candidates, _price_frame(days=80))

    assert review["ts_code"].tolist() == candidates["ts_code"].tolist()
    assert review["total_score"].tolist() == candidates["total_score"].tolist()
    assert not review["elder_reason"].str.contains("买入优先级|收益预测", regex=True).all()
    assert review["elder_reason"].str.contains("技术节奏|回撤风险|追高风险|继续观察|暂缓", regex=True).any()


def test_short_overheat_explanation_is_not_simple_exclusion() -> None:
    """Overheat wording should mention pullback risk and not equal weak trend."""
    overheat = _overheat_candidate_frame()
    review = build_elder_review(_candidates().head(1), overheat)

    reason = str(review.iloc[0]["elder_reason"])
    assert review.iloc[0]["action_hint"] == "短线过热，不追"
    assert "短期回撤风险" in reason
    assert "不等于中期趋势转弱" in reason
    assert "等待回调" in reason


def test_total_score_group_buckets_are_stable() -> None:
    """Layered backtest should have stable total_score groups."""
    assert total_score_group(80) == "high"
    assert total_score_group(55) == "middle"
    assert total_score_group(20) == "low"
    assert total_score_group(None) == "unknown"


def test_layered_backtest_summarizes_total_score_and_market_stage() -> None:
    """Backtest summaries should include candidate, total_score and market-stage layers."""
    details = pd.DataFrame(
        {
            "rank": [1, 2, pd.NA],
            "total_score": [80.0, 50.0, pd.NA],
            "total_score_group": ["high", "middle", "unknown"],
            "market_stage": ["strong", "weak", "range"],
            "elder_score_group": ["top", "middle", "bottom"],
            "action_hint": ["趋势确认，进入人工复核", "短线过热，不追", "趋势偏弱，暂缓"],
            "forward_return_5d": [0.02, -0.01, 0.0],
            "forward_return_10d": [0.03, -0.02, 0.01],
            "forward_return_20d": [0.04, 0.05, -0.01],
            "max_drawdown_20d": [-0.02, -0.08, -0.04],
            "max_gain_20d": [0.06, 0.12, 0.02],
        }
    )

    summary = summarize_elder_backtest(details)

    assert summary["candidate_signal_count"] == 2
    assert {row["group"] for row in summary["total_score_group_summary"]} == {"high", "middle", "unknown"}
    assert {row["group"] for row in summary["market_stage_summary"]} == {"range", "strong", "weak"}
    assert any("strong/趋势确认" in row["group"] for row in summary["market_stage_action_hint_summary"])


def test_build_elder_backtest_details_adds_layer_columns_without_changing_order() -> None:
    """Historical detail rows should include layered fields and preserve score inputs."""
    details = build_elder_backtest_details(_price_frame(days=70), min_history_rows=35, min_forward_rows=20)

    assert not details.empty
    assert {"total_score", "total_score_group", "market_stage"}.issubset(details.columns)
    assert set(details["total_score_group"].dropna().unique()).issubset({"high", "middle", "low", "unknown"})
    assert set(details["market_stage"].dropna().unique()).issubset({"strong", "range", "weak", "unknown"})


def test_markdown_contains_layered_explanation_sections() -> None:
    """Markdown report should include Task 43 explanation and layered sections."""
    result = {
        "generated_at": "2026-06-29T10:00:00",
        "data_source": "sample 数据（演示）",
        "start_date": "20240101",
        "end_date": "20240630",
        "sample_stock_count": 1,
        "valid_signal_count": 1,
        "candidate_signal_count": 1,
        "elder_score_group_summary": [],
        "action_hint_summary": [],
        "candidate_action_hint_summary": [],
        "total_score_group_summary": [],
        "market_stage_summary": [],
        "market_stage_action_hint_summary": [],
        "has_reverse_signal": False,
        "skip_reasons": ["无"],
        "risk_note": "该回看只用于个人研究，不构成交易建议。",
    }

    markdown = render_elder_backtest_markdown(result)

    assert "技术状态 / 节奏复核分" in markdown
    assert "total_score 分层后的 elder 表现" in markdown
    assert "市场阶段分层表现" in markdown
    assert "短期回撤风险偏高" in markdown


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rank": [1, 2],
            "ts_code": ["000001.SZ", "000002.SZ"],
            "name": ["A", "B"],
            "industry": ["银行", "地产"],
            "trade_date": ["20240628", "20240628"],
            "total_score": [90.0, 70.0],
        }
    )


def _price_frame(days: int = 70) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-01-01", periods=days).strftime("%Y%m%d")
    for ts_code, base, total_score in [("000001.SZ", 10.0, 90.0), ("000002.SZ", 20.0, 55.0)]:
        for index, trade_date in enumerate(dates):
            close = base + index * 0.08
            rows.append(
                {
                    "rank": 1 if ts_code == "000001.SZ" else 2,
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "name": "样本",
                    "high": close * 1.02,
                    "low": close * 0.98,
                    "close": close,
                    "vol": 1_000_000 + index,
                    "amount": (1_000_000 + index) * close,
                    "total_score": total_score,
                }
            )
    return pd.DataFrame(rows)


def _overheat_candidate_frame() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-01-01", periods=90).strftime("%Y%m%d")
    close = 10.0
    for index, trade_date in enumerate(dates):
        close = close * (1.002 if index < 70 else 1.035)
        rows.append(
            {
                "ts_code": "000001.SZ",
                "trade_date": trade_date,
                "high": close * 1.03,
                "low": close * 0.99,
                "close": close,
                "vol": 1_000_000 + index,
            }
        )
    return pd.DataFrame(rows)
