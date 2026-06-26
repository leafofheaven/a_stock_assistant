"""Fundamental factor calculations."""

from __future__ import annotations

import pandas as pd


def calculate_roe(fundamental_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate ROE from an existing roe column or net profit divided by equity."""
    df = _prepare_fundamental_df(fundamental_df)
    factor_name = "roe"
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])

    if "roe" in df.columns:
        df[factor_name] = pd.to_numeric(df["roe"], errors="coerce")
    elif {"net_profit", "total_equity"}.issubset(df.columns):
        net_profit = pd.to_numeric(df["net_profit"], errors="coerce")
        total_equity = pd.to_numeric(df["total_equity"], errors="coerce")
        df[factor_name] = net_profit / total_equity
    else:
        df[factor_name] = pd.NA
    return df[["ts_code", "trade_date", factor_name]]


def calculate_pe_score(daily_basic_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate a simple PE valuation factor where lower positive PE is better."""
    return _calculate_inverse_positive_factor(daily_basic_df, source_column="pe", factor_name="pe_score")


def calculate_pb_score(daily_basic_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate a simple PB valuation factor where lower positive PB is better."""
    return _calculate_inverse_positive_factor(daily_basic_df, source_column="pb", factor_name="pb_score")


def calculate_revenue_growth(fundamental_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate revenue growth from an existing column or trailing revenue history."""
    df = _prepare_fundamental_df(fundamental_df)
    factor_name = "revenue_growth"
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])

    if "revenue_growth" in df.columns:
        df[factor_name] = pd.to_numeric(df["revenue_growth"], errors="coerce")
    elif "revenue" in df.columns:
        revenue = pd.to_numeric(df["revenue"], errors="coerce")
        df[factor_name] = revenue.groupby(df["ts_code"]).pct_change()
    else:
        df[factor_name] = pd.NA
    return df[["ts_code", "trade_date", factor_name]]


def _calculate_inverse_positive_factor(
    df: pd.DataFrame,
    source_column: str,
    factor_name: str,
) -> pd.DataFrame:
    """Calculate an inverse valuation factor for positive source values."""
    prepared = _prepare_fundamental_df(df)
    if prepared.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", factor_name])
    if source_column not in prepared.columns:
        prepared[factor_name] = pd.NA
        return prepared[["ts_code", "trade_date", factor_name]]

    values = pd.to_numeric(prepared[source_column], errors="coerce")
    prepared[factor_name] = 1 / values.where(values > 0)
    return prepared[["ts_code", "trade_date", factor_name]]


def _prepare_fundamental_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return sorted fundamental data with required key columns."""
    required_columns = ["ts_code", "trade_date"]
    if df.empty:
        return pd.DataFrame(columns=required_columns)
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(f"df is missing required columns: {', '.join(missing)}")
    return df.copy().sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
