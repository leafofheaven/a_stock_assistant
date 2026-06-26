"""Liquidity factor calculations."""

from __future__ import annotations

import pandas as pd


def calculate_avg_amount_20d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate trailing 20-day average transaction amount by stock."""
    df = _prepare_df(price_df, value_column="amount")
    factor_name = "avg_amount_20d"
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])

    values = pd.to_numeric(df["amount"], errors="coerce")
    df[factor_name] = values.groupby(df["ts_code"]).transform(
        lambda series: series.rolling(window=20, min_periods=1).mean()
    )
    return df[["ts_code", "trade_date", factor_name]]


def calculate_avg_turnover_20d(daily_basic_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate trailing 20-day average turnover rate by stock."""
    df = _prepare_df(daily_basic_df, value_column="turnover_rate")
    factor_name = "avg_turnover_20d"
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])

    values = pd.to_numeric(df["turnover_rate"], errors="coerce")
    df[factor_name] = values.groupby(df["ts_code"]).transform(
        lambda series: series.rolling(window=20, min_periods=1).mean()
    )
    return df[["ts_code", "trade_date", factor_name]]


def _prepare_df(df: pd.DataFrame, value_column: str) -> pd.DataFrame:
    """Return sorted data with required liquidity columns."""
    required_columns = ["ts_code", "trade_date", value_column]
    if df.empty:
        return pd.DataFrame(columns=required_columns)
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(f"df is missing required columns: {', '.join(missing)}")
    return df.copy().sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
