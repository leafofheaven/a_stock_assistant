"""Tests for selection strategy and portfolio construction."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from core.strategy.portfolio import build_equal_weight_portfolio
from core.strategy.selector import select_top_stocks


def test_select_top_stocks_sorts_by_total_score() -> None:
    """Stocks should be selected by descending total_score."""
    selected = select_top_stocks(_scored_df(), top_n=2)
    first_date = selected[selected["trade_date"] == "20240101"]

    assert first_date["ts_code"].tolist() == ["000002.SZ", "000001.SZ"]
    assert first_date["total_score"].tolist() == [90.0, 80.0]


def test_select_top_stocks_selects_each_trade_date_independently() -> None:
    """Each trade_date should receive its own top_n selection."""
    selected = select_top_stocks(_scored_df(), top_n=1)

    assert selected["trade_date"].tolist() == ["20240101", "20240102"]
    assert selected["ts_code"].tolist() == ["000002.SZ", "000005.SZ"]


def test_select_top_stocks_excludes_missing_total_score() -> None:
    """Rows with missing total_score should not be selected."""
    selected = select_top_stocks(_scored_df(), top_n=5)

    assert "000003.SZ" not in selected["ts_code"].tolist()


def test_select_top_stocks_handles_top_n_larger_than_available() -> None:
    """top_n larger than available valid rows should not crash."""
    selected = select_top_stocks(_scored_df(), top_n=99)

    assert len(selected[selected["trade_date"] == "20240101"]) == 2
    assert len(selected[selected["trade_date"] == "20240102"]) == 2


def test_select_top_stocks_generates_rank_reason_and_risk_note() -> None:
    """Selection should include rank, select_reason, and risk_note."""
    selected = select_top_stocks(_scored_df(), top_n=2)
    first_date = selected[selected["trade_date"] == "20240101"]

    assert first_date["rank"].tolist() == [1, 2]
    assert first_date["select_reason"].str.len().gt(0).all()
    assert first_date["risk_note"].str.len().gt(0).all()


def test_build_equal_weight_portfolio_limits_positions() -> None:
    """Portfolio should keep only rank-leading max_positions per date."""
    selected = select_top_stocks(_scored_df(), top_n=3)
    portfolio = build_equal_weight_portfolio(selected, max_positions=1)

    assert len(portfolio[portfolio["trade_date"] == "20240101"]) == 1
    assert len(portfolio[portfolio["trade_date"] == "20240102"]) == 1
    assert portfolio["rank"].tolist() == [1, 1]


def test_build_equal_weight_portfolio_weights_sum_to_one_by_date() -> None:
    """Each trade_date should have weights summing to 1."""
    selected = select_top_stocks(_scored_df(), top_n=2)
    portfolio = build_equal_weight_portfolio(selected, max_positions=2)

    for _, group in portfolio.groupby("trade_date"):
        assert math.isclose(group["weight"].sum(), 1.0)
        assert group["weight"].nunique() == 1


def test_empty_inputs_return_expected_columns() -> None:
    """Empty selection and portfolio inputs should not crash."""
    selected = select_top_stocks(pd.DataFrame(columns=["trade_date", "ts_code", "total_score"]))
    portfolio = build_equal_weight_portfolio(pd.DataFrame(columns=["trade_date", "rank", "ts_code"]))

    assert selected.empty
    assert "select_reason" in selected.columns
    assert portfolio.empty
    assert "weight" in portfolio.columns


def test_partial_missing_optional_fields_are_preserved() -> None:
    """Missing optional fields should be added rather than causing failure."""
    scored = pd.DataFrame(
        {
            "trade_date": ["20240101"],
            "ts_code": ["000001.SZ"],
            "total_score": [80.0],
        }
    )

    selected = select_top_stocks(scored)
    portfolio = build_equal_weight_portfolio(selected)

    assert pd.isna(selected.loc[0, "name"])
    assert portfolio.loc[0, "weight"] == 1.0


def test_required_fields_are_validated() -> None:
    """Missing required fields should raise a clear error."""
    with pytest.raises(ValueError, match="total_score"):
        select_top_stocks(pd.DataFrame({"trade_date": ["20240101"], "ts_code": ["000001.SZ"]}))

    with pytest.raises(ValueError, match="rank"):
        build_equal_weight_portfolio(pd.DataFrame({"trade_date": ["20240101"], "ts_code": ["000001.SZ"]}))


def _scored_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("20240101", "000001.SZ", "平安银行", "银行", 80, 70, 60, 50, 80, 80),
            _row("20240101", "000002.SZ", "万科A", "地产", 90, 80, 80, 60, 35, 90),
            _row("20240101", "000003.SZ", "缺分", "制造", 70, 70, 70, 70, 70, None),
            _row("20240102", "000004.SZ", "宁德时代", "电池", 60, 70, 80, 90, 60, 75),
            _row("20240102", "000005.SZ", "招商银行", "银行", 90, 90, 80, 70, 80, 95),
        ]
    )


def _row(
    trade_date: str,
    ts_code: str,
    name: str,
    industry: str,
    trend_score: float,
    momentum_score: float,
    liquidity_score: float,
    fundamental_score: float,
    volatility_score: float,
    total_score: float | None,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "ts_code": ts_code,
        "name": name,
        "industry": industry,
        "trend_score": trend_score,
        "momentum_score": momentum_score,
        "liquidity_score": liquidity_score,
        "fundamental_score": fundamental_score,
        "volatility_score": volatility_score,
        "total_score": total_score,
    }
