"""Momentum factor calculations."""

from __future__ import annotations

import pandas as pd


def calculate_relative_strength(price_df: pd.DataFrame, benchmark_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate 20-day stock return minus 20-day benchmark return."""
    price = _prepare_price_df(price_df)
    factor_name = "relative_strength_20d"
    if price.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])

    benchmark = _prepare_benchmark_df(benchmark_df)
    stock_close = pd.to_numeric(price["close"], errors="coerce")
    price["stock_return_20d"] = stock_close / stock_close.groupby(price["ts_code"]).shift(20) - 1

    benchmark_close = pd.to_numeric(benchmark["close"], errors="coerce")
    benchmark["benchmark_return_20d"] = benchmark_close / benchmark_close.shift(20) - 1
    merged = price.merge(
        benchmark[["trade_date", "benchmark_return_20d"]],
        on="trade_date",
        how="left",
    )
    merged[factor_name] = merged["stock_return_20d"] - merged["benchmark_return_20d"]
    return merged[["ts_code", "trade_date", factor_name]]


def calculate_new_high_60d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate close price position relative to trailing 60-day high."""
    df = _prepare_price_df(price_df)
    factor_name = "new_high_60d"
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])

    close = pd.to_numeric(df["close"], errors="coerce")
    rolling_high = close.groupby(df["ts_code"]).transform(
        lambda series: series.rolling(window=60, min_periods=60).max()
    )
    df[factor_name] = close / rolling_high - 1
    return df[["ts_code", "trade_date", factor_name]]


def _prepare_price_df(price_df: pd.DataFrame) -> pd.DataFrame:
    """Return sorted stock price data with required columns."""
    required_columns = ["ts_code", "trade_date", "close"]
    if price_df.empty:
        return pd.DataFrame(columns=required_columns)
    missing = [column for column in required_columns if column not in price_df.columns]
    if missing:
        raise ValueError(f"price_df is missing required columns: {', '.join(missing)}")
    return price_df.copy().sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _prepare_benchmark_df(benchmark_df: pd.DataFrame) -> pd.DataFrame:
    """Return sorted benchmark data with required columns."""
    required_columns = ["trade_date", "close"]
    if benchmark_df.empty:
        return pd.DataFrame(columns=required_columns)
    missing = [column for column in required_columns if column not in benchmark_df.columns]
    if missing:
        raise ValueError(f"benchmark_df is missing required columns: {', '.join(missing)}")
    return benchmark_df.copy().sort_values("trade_date").reset_index(drop=True)
