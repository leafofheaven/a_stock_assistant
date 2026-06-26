"""Trend factor calculations."""

from __future__ import annotations

import pandas as pd


def calculate_return_20d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate 20-trading-day return by stock without using future data."""
    return _calculate_return(price_df, window=20, factor_name="return_20d")


def calculate_return_60d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate 60-trading-day return by stock without using future data."""
    return _calculate_return(price_df, window=60, factor_name="return_60d")


def calculate_ma_position(price_df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Calculate close price position relative to its moving average."""
    df = _prepare_price_df(price_df)
    factor_name = f"ma{window}_position"
    if df.empty:
        return _empty_factor(factor_name)

    close = pd.to_numeric(df["close"], errors="coerce")
    moving_average = close.groupby(df["ts_code"]).transform(
        lambda series: series.rolling(window=window, min_periods=window).mean()
    )
    df[factor_name] = close / moving_average - 1
    return df[["ts_code", "trade_date", factor_name]]


def calculate_ma_alignment(price_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate whether MA5 is above MA20 and MA20 is above MA60."""
    df = _prepare_price_df(price_df)
    factor_name = "ma_alignment"
    if df.empty:
        return _empty_factor(factor_name)

    close = pd.to_numeric(df["close"], errors="coerce")
    ma5 = close.groupby(df["ts_code"]).transform(lambda s: s.rolling(window=5, min_periods=5).mean())
    ma20 = close.groupby(df["ts_code"]).transform(
        lambda s: s.rolling(window=20, min_periods=20).mean()
    )
    ma60 = close.groupby(df["ts_code"]).transform(
        lambda s: s.rolling(window=60, min_periods=60).mean()
    )
    df[factor_name] = ((ma5 > ma20) & (ma20 > ma60)).astype(float)
    df.loc[ma5.isna() | ma20.isna() | ma60.isna(), factor_name] = pd.NA
    return df[["ts_code", "trade_date", factor_name]]


def _calculate_return(price_df: pd.DataFrame, window: int, factor_name: str) -> pd.DataFrame:
    """Calculate a trailing return for a given window."""
    df = _prepare_price_df(price_df)
    if df.empty:
        return _empty_factor(factor_name)

    close = pd.to_numeric(df["close"], errors="coerce")
    previous_close = close.groupby(df["ts_code"]).shift(window)
    df[factor_name] = close / previous_close - 1
    return df[["ts_code", "trade_date", factor_name]]


def _prepare_price_df(price_df: pd.DataFrame) -> pd.DataFrame:
    """Return price data sorted by stock and date with required columns."""
    required_columns = ["ts_code", "trade_date", "close"]
    if price_df.empty:
        return pd.DataFrame(columns=required_columns)
    missing = [column for column in required_columns if column not in price_df.columns]
    if missing:
        raise ValueError(f"price_df is missing required columns: {', '.join(missing)}")
    return price_df.copy().sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _empty_factor(factor_name: str) -> pd.DataFrame:
    """Return an empty factor DataFrame with standard columns."""
    return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])
