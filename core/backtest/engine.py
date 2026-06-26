"""Lightweight daily backtest engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.backtest.metrics import (
    calculate_annual_return,
    calculate_max_drawdown,
    calculate_sharpe_ratio,
    calculate_turnover,
    calculate_win_rate,
    calculate_yearly_returns,
)
from core.backtest.rules_cn_a import can_buy, can_sell


@dataclass
class Position:
    """Mutable position state for one stock."""

    shares: float
    cost_basis: float
    buy_date: str


def run_backtest(
    price_df: pd.DataFrame,
    score_df: pd.DataFrame,
    start_date: str,
    end_date: str,
    rebalance_frequency: str = "W",
    top_n: int = 20,
    initial_cash: float = 1_000_000,
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage_rate: float = 0.0005,
) -> dict[str, Any]:
    """Run a simple daily A-share long-only backtest.

    The engine rebalances on scheduled dates using only scores whose
    ``trade_date`` is no later than the rebalance date, preventing future data
    leakage. It uses equal target weights, applies commission, stamp tax on
    sells, and slippage. Suspended stocks cannot trade, limit-up stocks cannot be
    bought, and limit-down stocks cannot be sold. T+1 is simplified by blocking
    sells on the same date as a position's latest buy.
    """
    if price_df.empty or score_df.empty or top_n <= 0:
        return _empty_result(initial_cash)

    prices = _prepare_price_df(price_df, start_date, end_date)
    scores = _prepare_score_df(score_df, start_date, end_date)
    if prices.empty or scores.empty:
        return _empty_result(initial_cash)

    trade_dates = sorted(prices["trade_date"].unique().tolist())
    rebalance_dates = set(_rebalance_dates(trade_dates, rebalance_frequency))
    price_by_date = {date: group.set_index("ts_code") for date, group in prices.groupby("trade_date")}

    cash = float(initial_cash)
    positions: dict[str, Position] = {}
    trade_records: list[dict[str, Any]] = []
    position_records: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []

    for trade_date in trade_dates:
        daily_prices = price_by_date[trade_date]
        if trade_date in rebalance_dates:
            target_codes = _select_targets(scores, trade_date, top_n)
            cash = _rebalance(
                trade_date=trade_date,
                target_codes=target_codes,
                cash=cash,
                positions=positions,
                daily_prices=daily_prices,
                trade_records=trade_records,
                commission_rate=commission_rate,
                stamp_tax_rate=stamp_tax_rate,
                slippage_rate=slippage_rate,
            )

        equity = cash + _positions_value(positions, daily_prices)
        equity_rows.append({"trade_date": trade_date, "equity": equity, "cash": cash})
        for ts_code, position in positions.items():
            if ts_code in daily_prices.index:
                close = float(daily_prices.loc[ts_code, "close"])
                position_records.append(
                    {
                        "trade_date": trade_date,
                        "ts_code": ts_code,
                        "shares": position.shares,
                        "close": close,
                        "market_value": position.shares * close,
                        "weight": (position.shares * close / equity) if equity else 0.0,
                    }
                )

    equity_curve = pd.DataFrame(equity_rows)
    trade_records_df = pd.DataFrame(trade_records)
    position_records_df = pd.DataFrame(position_records)

    return {
        "annual_return": calculate_annual_return(equity_curve),
        "max_drawdown": calculate_max_drawdown(equity_curve),
        "sharpe_ratio": calculate_sharpe_ratio(equity_curve),
        "win_rate": calculate_win_rate(trade_records_df),
        "turnover": calculate_turnover(trade_records_df, equity_curve),
        "yearly_returns": calculate_yearly_returns(equity_curve),
        "equity_curve": equity_curve,
        "trade_records": trade_records_df,
        "position_records": position_records_df,
    }


def _prepare_price_df(price_df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """Return sorted price data within the backtest window."""
    required_columns = ["ts_code", "trade_date", "close"]
    _require_columns(price_df, required_columns, "price_df")
    prices = price_df.copy()
    prices["trade_date"] = prices["trade_date"].astype(str)
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["close"])
    prices = prices[(prices["trade_date"] >= start_date) & (prices["trade_date"] <= end_date)]
    if "pre_close" not in prices.columns:
        prices["pre_close"] = prices.groupby("ts_code")["close"].shift(1)
    if "vol" not in prices.columns:
        prices["vol"] = 1
    return prices.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)


def _prepare_score_df(score_df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """Return sorted score data within the backtest window."""
    required_columns = ["ts_code", "trade_date", "total_score"]
    _require_columns(score_df, required_columns, "score_df")
    scores = score_df.copy()
    scores["trade_date"] = scores["trade_date"].astype(str)
    scores["total_score"] = pd.to_numeric(scores["total_score"], errors="coerce")
    scores = scores.dropna(subset=["total_score"])
    scores = scores[(scores["trade_date"] >= start_date) & (scores["trade_date"] <= end_date)]
    return scores.sort_values(["trade_date", "total_score"], ascending=[True, False]).reset_index(drop=True)


def _rebalance_dates(trade_dates: list[str], rebalance_frequency: str) -> list[str]:
    """Return rebalance dates from available trade dates."""
    if not trade_dates:
        return []
    if rebalance_frequency.upper().startswith("W"):
        return trade_dates[::5]
    return trade_dates


def _select_targets(scores: pd.DataFrame, trade_date: str, top_n: int) -> list[str]:
    """Select targets using only scores available no later than trade_date."""
    available = scores[scores["trade_date"] <= trade_date]
    if available.empty:
        return []
    latest_score_date = available["trade_date"].max()
    current_scores = available[available["trade_date"] == latest_score_date]
    return (
        current_scores.sort_values(["total_score", "ts_code"], ascending=[False, True])
        .head(top_n)["ts_code"]
        .tolist()
    )


def _rebalance(
    trade_date: str,
    target_codes: list[str],
    cash: float,
    positions: dict[str, Position],
    daily_prices: pd.DataFrame,
    trade_records: list[dict[str, Any]],
    commission_rate: float,
    stamp_tax_rate: float,
    slippage_rate: float,
) -> float:
    """Rebalance existing positions toward equal target weights."""
    target_set = set(target_codes)

    for ts_code in list(positions):
        if ts_code in target_set or ts_code not in daily_prices.index:
            continue
        row = daily_prices.loc[ts_code]
        position = positions[ts_code]
        if not can_sell(row, bought_today=position.buy_date == trade_date):
            continue
        cash += _sell_position(
            trade_date,
            ts_code,
            position,
            float(row["close"]),
            trade_records,
            commission_rate,
            stamp_tax_rate,
            slippage_rate,
        )
        del positions[ts_code]

    buyable_targets = [
        ts_code for ts_code in target_codes if ts_code in daily_prices.index and can_buy(daily_prices.loc[ts_code])
    ]
    if not buyable_targets:
        return cash

    portfolio_value = cash + _positions_value(positions, daily_prices)
    target_value = portfolio_value / len(buyable_targets)
    for ts_code in buyable_targets:
        row = daily_prices.loc[ts_code]
        close = float(row["close"])
        current_value = positions.get(ts_code, Position(0, close, trade_date)).shares * close
        buy_value = max(target_value - current_value, 0.0)
        if buy_value <= 0 or cash <= 0:
            continue
        cash = _buy_position(
            trade_date,
            ts_code,
            close,
            min(buy_value, cash),
            cash,
            positions,
            trade_records,
            commission_rate,
            slippage_rate,
        )
    return cash


def _buy_position(
    trade_date: str,
    ts_code: str,
    close: float,
    target_cash: float,
    cash: float,
    positions: dict[str, Position],
    trade_records: list[dict[str, Any]],
    commission_rate: float,
    slippage_rate: float,
) -> float:
    """Buy shares with available target cash and record the trade."""
    execution_price = close * (1 + slippage_rate)
    shares = target_cash / (execution_price * (1 + commission_rate))
    trade_value = shares * execution_price
    commission = trade_value * commission_rate
    total_cost = trade_value + commission
    if shares <= 0 or total_cost > cash + 1e-9:
        return cash
    existing = positions.get(ts_code)
    if existing is None:
        positions[ts_code] = Position(shares=shares, cost_basis=execution_price, buy_date=trade_date)
    else:
        combined_shares = existing.shares + shares
        existing.cost_basis = (existing.cost_basis * existing.shares + execution_price * shares) / combined_shares
        existing.shares = combined_shares
        existing.buy_date = trade_date
    trade_records.append(
        {
            "trade_date": trade_date,
            "ts_code": ts_code,
            "side": "buy",
            "shares": shares,
            "price": execution_price,
            "trade_value": trade_value,
            "commission": commission,
            "stamp_tax": 0.0,
            "slippage": close * slippage_rate * shares,
            "pnl": 0.0,
        }
    )
    return cash - total_cost


def _sell_position(
    trade_date: str,
    ts_code: str,
    position: Position,
    close: float,
    trade_records: list[dict[str, Any]],
    commission_rate: float,
    stamp_tax_rate: float,
    slippage_rate: float,
) -> float:
    """Sell a full position and return net cash proceeds."""
    execution_price = close * (1 - slippage_rate)
    trade_value = position.shares * execution_price
    commission = trade_value * commission_rate
    stamp_tax = trade_value * stamp_tax_rate
    proceeds = trade_value - commission - stamp_tax
    pnl = proceeds - position.shares * position.cost_basis
    trade_records.append(
        {
            "trade_date": trade_date,
            "ts_code": ts_code,
            "side": "sell",
            "shares": position.shares,
            "price": execution_price,
            "trade_value": trade_value,
            "commission": commission,
            "stamp_tax": stamp_tax,
            "slippage": close * slippage_rate * position.shares,
            "pnl": pnl,
        }
    )
    return proceeds


def _positions_value(positions: dict[str, Position], daily_prices: pd.DataFrame) -> float:
    """Mark positions to market using current close prices."""
    value = 0.0
    for ts_code, position in positions.items():
        if ts_code in daily_prices.index:
            value += position.shares * float(daily_prices.loc[ts_code, "close"])
    return value


def _empty_result(initial_cash: float) -> dict[str, Any]:
    """Return a complete empty backtest result structure."""
    equity_curve = pd.DataFrame(columns=["trade_date", "equity", "cash"])
    trade_records = pd.DataFrame()
    position_records = pd.DataFrame()
    return {
        "annual_return": 0.0,
        "max_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "win_rate": 0.0,
        "turnover": 0.0,
        "yearly_returns": {},
        "equity_curve": equity_curve,
        "trade_records": trade_records,
        "position_records": position_records,
    }


def _require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    """Raise a clear error when required columns are missing."""
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")
