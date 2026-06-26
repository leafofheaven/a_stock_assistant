"""Tests for backtest engine, metrics, and A-share rules."""

from __future__ import annotations

import math

import pandas as pd

from core.backtest.engine import run_backtest
from core.backtest.metrics import (
    calculate_annual_return,
    calculate_max_drawdown,
    calculate_sharpe_ratio,
    calculate_turnover,
    calculate_win_rate,
    calculate_yearly_returns,
)
from core.backtest.rules_cn_a import can_buy, can_sell, is_limit_down, is_limit_up, is_suspended


def test_run_backtest_returns_required_outputs() -> None:
    """run_backtest should execute and return all required result keys."""
    result = run_backtest(_price_df(), _score_df(), "20240101", "20240115", top_n=2)

    for key in [
        "annual_return",
        "max_drawdown",
        "sharpe_ratio",
        "win_rate",
        "turnover",
        "yearly_returns",
        "equity_curve",
        "trade_records",
        "position_records",
    ]:
        assert key in result
    assert not result["equity_curve"].empty
    assert not result["trade_records"].empty
    assert not result["position_records"].empty


def test_weekly_rebalance_and_top_n_are_used() -> None:
    """Weekly rebalance should trade on scheduled dates and respect top_n."""
    result = run_backtest(_price_df(), _score_df(), "20240101", "20240115", top_n=1)
    trades = result["trade_records"]
    positions = result["position_records"]

    assert set(trades["trade_date"]).issubset({"20240101", "20240106", "20240111"})
    assert positions.groupby("trade_date")["ts_code"].nunique().max() == 1


def test_equal_weight_positions_are_created() -> None:
    """Initial portfolio should be close to equal weighted for selected stocks."""
    result = run_backtest(_price_df(), _score_df(), "20240101", "20240115", top_n=2)
    first_positions = result["position_records"]
    first_positions = first_positions[first_positions["trade_date"] == "20240101"]

    assert len(first_positions) == 2
    assert first_positions["weight"].between(0.49, 0.51).all()


def test_costs_affect_backtest_result() -> None:
    """Fees, stamp tax, and slippage should reduce final equity."""
    no_cost = run_backtest(
        _price_df(),
        _score_df(),
        "20240101",
        "20240115",
        top_n=2,
        commission_rate=0,
        stamp_tax_rate=0,
        slippage_rate=0,
    )
    with_cost = run_backtest(_price_df(), _score_df(), "20240101", "20240115", top_n=2)

    assert with_cost["equity_curve"]["equity"].iloc[-1] < no_cost["equity_curve"]["equity"].iloc[-1]


def test_suspended_limit_up_and_limit_down_rules_affect_trading() -> None:
    """Suspension and limit rules should block invalid buy and sell actions."""
    prices = _price_df()
    scores = _score_df()
    prices.loc[(prices["ts_code"] == "000002.SZ") & (prices["trade_date"] == "20240101"), "is_limit_up"] = True
    prices.loc[(prices["ts_code"] == "000001.SZ") & (prices["trade_date"] == "20240106"), "is_limit_down"] = True
    prices.loc[(prices["ts_code"] == "000003.SZ") & (prices["trade_date"] == "20240106"), "is_suspended"] = True
    scores.loc[(scores["ts_code"] == "000001.SZ") & (scores["trade_date"] == "20240106"), "total_score"] = 0
    scores.loc[(scores["ts_code"] == "000003.SZ") & (scores["trade_date"] == "20240106"), "total_score"] = 100

    result = run_backtest(prices, scores, "20240101", "20240115", top_n=2)
    trades = result["trade_records"]

    first_day_buys = trades[(trades["trade_date"] == "20240101") & (trades["side"] == "buy")]
    assert "000002.SZ" not in first_day_buys["ts_code"].tolist()
    assert not ((trades["trade_date"] == "20240106") & (trades["ts_code"] == "000001.SZ") & (trades["side"] == "sell")).any()
    assert not ((trades["trade_date"] == "20240106") & (trades["ts_code"] == "000003.SZ") & (trades["side"] == "buy")).any()


def test_empty_data_does_not_crash() -> None:
    """Empty price or score data should return an empty complete result."""
    result = run_backtest(
        pd.DataFrame(columns=["ts_code", "trade_date", "close"]),
        pd.DataFrame(columns=["ts_code", "trade_date", "total_score"]),
        "20240101",
        "20240115",
    )

    assert result["annual_return"] == 0.0
    assert result["equity_curve"].empty


def test_backtest_does_not_use_future_scores() -> None:
    """Scores after the current rebalance date must not affect earlier trades."""
    prices = _price_df()
    scores = _score_df()
    scores.loc[(scores["ts_code"] == "000003.SZ") & (scores["trade_date"] == "20240106"), "total_score"] = 999

    result = run_backtest(prices, scores, "20240101", "20240105", top_n=1)
    trades = result["trade_records"]

    assert trades.iloc[0]["ts_code"] == "000001.SZ"


def test_rules_cn_a_helpers() -> None:
    """A-share rule helpers should identify blocked trade rows."""
    suspended = pd.Series({"is_suspended": True, "close": 10, "pre_close": 10, "vol": 0})
    limit_up = pd.Series({"close": 11, "pre_close": 10, "vol": 100})
    limit_down = pd.Series({"close": 9, "pre_close": 10, "vol": 100})

    assert is_suspended(suspended)
    assert is_limit_up(limit_up)
    assert is_limit_down(limit_down)
    assert not can_buy(limit_up)
    assert not can_sell(limit_down)
    assert not can_sell(pd.Series({"close": 10, "pre_close": 10, "vol": 100}), bought_today=True)


def test_metric_functions() -> None:
    """Metric functions should return stable values for small data."""
    equity_curve = pd.DataFrame(
        {"trade_date": ["20240101", "20240102", "20250102"], "equity": [100, 110, 105]}
    )
    trades = pd.DataFrame(
        {"side": ["sell", "sell"], "pnl": [10, -5], "trade_value": [100, 100]}
    )

    assert calculate_annual_return(equity_curve) != 0
    assert calculate_max_drawdown(equity_curve) < 0
    assert isinstance(calculate_sharpe_ratio(equity_curve), float)
    assert calculate_win_rate(trades) == 0.5
    assert calculate_turnover(trades, equity_curve) > 0
    assert set(calculate_yearly_returns(equity_curve)) == {"2024", "2025"}


def _price_df() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = [f"202401{day:02d}" for day in range(1, 16)]
    for ts_code, base in [("000001.SZ", 10.0), ("000002.SZ", 20.0), ("000003.SZ", 30.0)]:
        for index, trade_date in enumerate(dates):
            close = base + index * (1 if ts_code != "000003.SZ" else -0.2)
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "close": close,
                    "pre_close": close - 0.1,
                    "vol": 1000,
                    "is_suspended": False,
                    "is_limit_up": False,
                    "is_limit_down": False,
                }
            )
    return pd.DataFrame(rows)


def _score_df() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for trade_date in ["20240101", "20240106", "20240111"]:
        rows.extend(
            [
                {"ts_code": "000001.SZ", "trade_date": trade_date, "total_score": 90},
                {"ts_code": "000002.SZ", "trade_date": trade_date, "total_score": 80},
                {"ts_code": "000003.SZ", "trade_date": trade_date, "total_score": 70},
            ]
        )
    return pd.DataFrame(rows)
