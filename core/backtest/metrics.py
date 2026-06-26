"""Backtest metric calculations."""

from __future__ import annotations

import math

import pandas as pd


def calculate_annual_return(equity_curve: pd.DataFrame) -> float:
    """Calculate annualized return from an equity curve."""
    if equity_curve.empty or len(equity_curve) < 2 or "equity" not in equity_curve.columns:
        return 0.0
    equity = pd.to_numeric(equity_curve["equity"], errors="coerce").dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    periods = len(equity) - 1
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    return float((1 + total_return) ** (252 / periods) - 1)


def calculate_max_drawdown(equity_curve: pd.DataFrame) -> float:
    """Calculate maximum drawdown from an equity curve."""
    if equity_curve.empty or "equity" not in equity_curve.columns:
        return 0.0
    equity = pd.to_numeric(equity_curve["equity"], errors="coerce").dropna()
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    return float(drawdown.min())


def calculate_sharpe_ratio(equity_curve: pd.DataFrame) -> float:
    """Calculate annualized Sharpe ratio using daily equity returns."""
    if equity_curve.empty or "equity" not in equity_curve.columns:
        return 0.0
    returns = pd.to_numeric(equity_curve["equity"], errors="coerce").pct_change().dropna()
    if returns.empty or returns.std() == 0 or math.isnan(float(returns.std())):
        return 0.0
    return float(returns.mean() / returns.std() * math.sqrt(252))


def calculate_win_rate(trade_records: pd.DataFrame) -> float:
    """Calculate win rate from sell trade realized PnL records."""
    if trade_records.empty or "side" not in trade_records.columns or "pnl" not in trade_records.columns:
        return 0.0
    sells = trade_records[trade_records["side"] == "sell"]
    if sells.empty:
        return 0.0
    return float((pd.to_numeric(sells["pnl"], errors="coerce").fillna(0) > 0).mean())


def calculate_turnover(trade_records: pd.DataFrame, equity_curve: pd.DataFrame | None = None) -> float:
    """Calculate simple turnover as traded value divided by average equity."""
    if trade_records.empty or "trade_value" not in trade_records.columns:
        return 0.0
    traded_value = pd.to_numeric(trade_records["trade_value"], errors="coerce").fillna(0).sum()
    if equity_curve is None or equity_curve.empty or "equity" not in equity_curve.columns:
        return float(traded_value)
    average_equity = pd.to_numeric(equity_curve["equity"], errors="coerce").dropna().mean()
    if not average_equity or math.isnan(float(average_equity)):
        return 0.0
    return float(traded_value / average_equity)


def calculate_yearly_returns(equity_curve: pd.DataFrame) -> dict[str, float]:
    """Calculate yearly returns from the first and last equity per calendar year."""
    if equity_curve.empty or not {"trade_date", "equity"}.issubset(equity_curve.columns):
        return {}
    df = equity_curve.copy()
    df["year"] = df["trade_date"].astype(str).str[:4]
    returns: dict[str, float] = {}
    for year, group in df.groupby("year"):
        equity = pd.to_numeric(group["equity"], errors="coerce").dropna()
        if len(equity) < 2 or equity.iloc[0] <= 0:
            returns[str(year)] = 0.0
        else:
            returns[str(year)] = float(equity.iloc[-1] / equity.iloc[0] - 1)
    return returns
