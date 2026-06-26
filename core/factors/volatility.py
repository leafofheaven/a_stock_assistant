"""Volatility factor calculations."""

from __future__ import annotations

import pandas as pd


def calculate_volatility_20d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate trailing 20-day standard deviation of daily returns by stock."""
    df = _prepare_price_df(price_df)
    factor_name = "volatility_20d"
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])

    close = pd.to_numeric(df["close"], errors="coerce")
    returns = close.groupby(df["ts_code"]).pct_change()
    df[factor_name] = returns.groupby(df["ts_code"]).transform(
        lambda series: series.rolling(window=20, min_periods=2).std()
    )
    return df[["ts_code", "trade_date", factor_name]]


def calculate_max_drawdown_60d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate trailing 60-day maximum drawdown by stock."""
    df = _prepare_price_df(price_df)
    factor_name = "max_drawdown_60d"
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])

    close = pd.to_numeric(df["close"], errors="coerce")
    rolling_high = close.groupby(df["ts_code"]).transform(
        lambda series: series.rolling(window=60, min_periods=2).max()
    )
    drawdown = close / rolling_high - 1
    df[factor_name] = drawdown.groupby(df["ts_code"]).transform(
        lambda series: series.rolling(window=60, min_periods=2).min()
    )
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
