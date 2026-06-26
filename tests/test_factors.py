"""Tests for base factor calculations with mock DataFrame inputs."""

from __future__ import annotations

import math

import pandas as pd

from core.factors.fundamental import (
    calculate_pb_score,
    calculate_pe_score,
    calculate_revenue_growth,
    calculate_roe,
)
from core.factors.liquidity import calculate_avg_amount_20d, calculate_avg_turnover_20d
from core.factors.momentum import calculate_new_high_60d, calculate_relative_strength
from core.factors.trend import (
    calculate_ma_alignment,
    calculate_ma_position,
    calculate_return_20d,
    calculate_return_60d,
)
from core.factors.volatility import calculate_max_drawdown_60d, calculate_volatility_20d


def test_trend_returns_are_grouped_and_use_only_past_data() -> None:
    """Return factors should use each stock's own historical rows only."""
    prices = _price_df(days=65)

    result_20d = calculate_return_20d(prices)
    result_60d = calculate_return_60d(prices)
    row_a_20 = _row(result_20d, "000001.SZ", "20240121")
    row_b_20 = _row(result_20d, "000002.SZ", "20240121")
    row_a_60 = _row(result_60d, "000001.SZ", "20240161")

    assert math.isclose(row_a_20["return_20d"], 20 / 100)
    assert math.isclose(row_b_20["return_20d"], 20 / 200)
    assert math.isclose(row_a_60["return_60d"], 60 / 100)
    assert pd.isna(_row(result_20d, "000001.SZ", "20240120")["return_20d"])


def test_ma_position_and_alignment_handle_insufficient_data() -> None:
    """Moving-average factors should not crash when windows are incomplete."""
    short_prices = _price_df(days=10)
    long_prices = _price_df(days=65)

    short_position = calculate_ma_position(short_prices)
    alignment = calculate_ma_alignment(long_prices)

    assert short_position["ma20_position"].isna().all()
    assert pd.isna(_row(alignment, "000001.SZ", "20240159")["ma_alignment"])
    assert _row(alignment, "000001.SZ", "20240160")["ma_alignment"] == 1.0


def test_momentum_relative_strength_and_new_high() -> None:
    """Momentum factors should compare stocks to benchmark history and rolling highs."""
    prices = _price_df(days=65)
    benchmark = pd.DataFrame(
        {
            "trade_date": [f"202401{day:02d}" for day in range(1, 66)],
            "close": [100 + day * 0.5 for day in range(65)],
        }
    )

    relative_strength = calculate_relative_strength(prices, benchmark)
    new_high = calculate_new_high_60d(prices)
    row = _row(relative_strength, "000001.SZ", "20240121")
    high_row = _row(new_high, "000001.SZ", "20240160")

    assert math.isclose(row["relative_strength_20d"], (120 / 100 - 1) - (110 / 100 - 1))
    assert high_row["new_high_60d"] == 0
    assert pd.isna(_row(new_high, "000001.SZ", "20240159")["new_high_60d"])


def test_liquidity_factors_handle_missing_values() -> None:
    """Liquidity factors should average by stock and ignore missing values."""
    prices = _price_df(days=22)
    prices.loc[(prices["ts_code"] == "000001.SZ") & (prices["trade_date"] == "20240122"), "amount"] = pd.NA
    basics = _daily_basic_df(days=22)

    amount = calculate_avg_amount_20d(prices)
    turnover = calculate_avg_turnover_20d(basics)

    assert math.isclose(_row(amount, "000002.SZ", "20240122")["avg_amount_20d"], 200_000_000)
    assert math.isclose(_row(turnover, "000001.SZ", "20240122")["avg_turnover_20d"], 2.0)


def test_volatility_and_drawdown_are_grouped() -> None:
    """Risk factors should be calculated independently for each stock."""
    prices = _price_df(days=65)
    prices.loc[prices["ts_code"] == "000001.SZ", "close"] = [100, 120, *[90 + i for i in range(63)]]

    volatility = calculate_volatility_20d(prices)
    drawdown = calculate_max_drawdown_60d(prices)

    assert pd.isna(_row(volatility, "000001.SZ", "20240102")["volatility_20d"])
    assert _row(drawdown, "000001.SZ", "20240103")["max_drawdown_60d"] < 0
    assert not drawdown[drawdown["ts_code"] == "000002.SZ"]["max_drawdown_60d"].dropna().lt(0).any()


def test_fundamental_factors_use_available_columns_and_handle_missing_values() -> None:
    """Fundamental factors should work with provided columns and missing values."""
    fundamentals = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "trade_date": ["20240101", "20240102", "20240101"],
            "net_profit": [10.0, 12.0, None],
            "total_equity": [100.0, 100.0, 100.0],
            "revenue": [100.0, 120.0, 200.0],
        }
    )
    basics = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ"],
            "trade_date": ["20240101", "20240101"],
            "pe": [10.0, None],
            "pb": [2.0, -1.0],
        }
    )

    roe = calculate_roe(fundamentals)
    revenue_growth = calculate_revenue_growth(fundamentals)
    pe_score = calculate_pe_score(basics)
    pb_score = calculate_pb_score(basics)

    assert math.isclose(_row(roe, "000001.SZ", "20240101")["roe"], 0.1)
    assert math.isclose(_row(revenue_growth, "000001.SZ", "20240102")["revenue_growth"], 0.2)
    assert math.isclose(_row(pe_score, "000001.SZ", "20240101")["pe_score"], 0.1)
    assert math.isclose(_row(pb_score, "000001.SZ", "20240101")["pb_score"], 0.5)
    assert pd.isna(_row(pe_score, "000002.SZ", "20240101")["pe_score"])
    assert pd.isna(_row(pb_score, "000002.SZ", "20240101")["pb_score"])


def test_factor_functions_return_empty_dataframes_for_empty_inputs() -> None:
    """Factor functions should return DataFrames for empty inputs."""
    empty_price = pd.DataFrame(columns=["ts_code", "trade_date", "close", "amount"])
    empty_basic = pd.DataFrame(columns=["ts_code", "trade_date", "turnover_rate", "pe", "pb"])

    assert isinstance(calculate_return_20d(empty_price), pd.DataFrame)
    assert isinstance(calculate_avg_turnover_20d(empty_basic), pd.DataFrame)
    assert isinstance(calculate_roe(empty_basic), pd.DataFrame)


def _price_df(days: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for ts_code, base_close, amount in [
        ("000001.SZ", 100, 100_000_000),
        ("000002.SZ", 200, 200_000_000),
    ]:
        for index in range(days):
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": f"202401{index + 1:02d}",
                    "close": base_close + index,
                    "amount": amount,
                }
            )
    return pd.DataFrame(rows)


def _daily_basic_df(days: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for ts_code, turnover in [("000001.SZ", 2.0), ("000002.SZ", 4.0)]:
        for index in range(days):
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": f"202401{index + 1:02d}",
                    "turnover_rate": turnover,
                }
            )
    return pd.DataFrame(rows)


def _row(df: pd.DataFrame, ts_code: str, trade_date: str) -> pd.Series:
    return df[(df["ts_code"] == ts_code) & (df["trade_date"] == trade_date)].iloc[0]
