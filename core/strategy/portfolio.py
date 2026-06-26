"""Portfolio construction helpers."""

from __future__ import annotations

import pandas as pd

from core.strategy.selector import OUTPUT_COLUMNS

PORTFOLIO_COLUMNS = [*OUTPUT_COLUMNS, "weight"]


def build_equal_weight_portfolio(selected_df: pd.DataFrame, max_positions: int = 20) -> pd.DataFrame:
    """Build an equal-weight portfolio for each trade date.

    The function sorts by ``trade_date`` and ``rank``, keeps at most
    ``max_positions`` rows per date, and assigns each remaining position the same
    weight. Empty input or non-positive ``max_positions`` returns an empty
    portfolio with the expected columns.
    """
    if max_positions <= 0 or selected_df.empty:
        return pd.DataFrame(columns=PORTFOLIO_COLUMNS)
    _require_columns(selected_df, ["trade_date", "rank", "ts_code"])

    df = selected_df.copy()
    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df = df.dropna(subset=["rank"])
    if df.empty:
        return pd.DataFrame(columns=PORTFOLIO_COLUMNS)

    df = df.sort_values(["trade_date", "rank", "ts_code"], ascending=[True, True, True])
    portfolio = df.groupby("trade_date", group_keys=False).head(max_positions).copy()
    counts = portfolio.groupby("trade_date")["ts_code"].transform("count")
    portfolio["weight"] = 1.0 / counts
    return portfolio[PORTFOLIO_COLUMNS].reset_index(drop=True)


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    """Raise a clear error when required columns are missing."""
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"selected_df is missing required columns: {', '.join(missing)}")
