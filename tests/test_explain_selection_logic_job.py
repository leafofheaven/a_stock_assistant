"""Tests for the selection logic explanation command."""

from __future__ import annotations

import pandas as pd

from core.jobs.explain_selection_logic import explain_selection_logic


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rank": [1, 2],
            "ts_code": ["000001.SZ", "002475.SZ"],
            "name": ["平安银行", "立讯精密"],
            "total_score": [90.0, 80.0],
            "trend_score": [90.0, 70.0],
            "momentum_score": [85.0, 60.0],
            "liquidity_score": [80.0, 75.0],
            "fundamental_score": [88.0, 82.0],
            "volatility_score": [70.0, 65.0],
            "pe": [8.5, 22.0],
            "pb": [0.8, 3.0],
            "industry": ["银行", "消费电子"],
            "list_date": ["19910403", "20100915"],
        }
    )


def test_explain_selection_logic_markdown_output() -> None:
    """Command helper should render Markdown explanation without local reports."""
    result = explain_selection_logic(output_format="markdown", candidates=_candidates())

    assert result["status"] == "success"
    assert "综合评分公式" in result["output"]
    assert "因子说明" in result["output"]
    assert result["candidate_explanations"]


def test_explain_selection_logic_filters_by_ts_code() -> None:
    """Command helper should filter candidate explanations by ts_code."""
    result = explain_selection_logic(output_format="text", ts_code="002475.SZ", candidates=_candidates())

    explanations = result["candidate_explanations"]
    assert len(explanations) == 1
    assert explanations[0]["ts_code"] == "002475.SZ"
    assert "000001.SZ" not in result["output"]
