"""Simplified China A-share trading rules for backtesting."""

from __future__ import annotations

import pandas as pd


def is_suspended(row: pd.Series) -> bool:
    """Return whether a stock is suspended.

    This first version supports an explicit ``is_suspended`` flag and falls back
    to zero or missing volume as a suspension signal.
    """
    if "is_suspended" in row and pd.notna(row["is_suspended"]):
        return bool(row["is_suspended"])
    if "vol" in row and pd.notna(row["vol"]):
        return float(row["vol"]) <= 0
    return False


def is_limit_up(row: pd.Series, limit_pct: float = 0.10) -> bool:
    """Return whether a stock is limit-up.

    The default limit is 10%. ST, ChiNext, and STAR Market limits can be added by
    deriving ``limit_pct`` from security attributes in a later task.
    """
    if "is_limit_up" in row and pd.notna(row["is_limit_up"]):
        return bool(row["is_limit_up"])
    if not {"close", "pre_close"}.issubset(row.index) or pd.isna(row["close"]) or pd.isna(row["pre_close"]):
        return False
    return float(row["close"]) >= float(row["pre_close"]) * (1 + limit_pct) - 1e-9


def is_limit_down(row: pd.Series, limit_pct: float = 0.10) -> bool:
    """Return whether a stock is limit-down.

    The default limit is 10%. ST, ChiNext, and STAR Market limits can be added by
    deriving ``limit_pct`` from security attributes in a later task.
    """
    if "is_limit_down" in row and pd.notna(row["is_limit_down"]):
        return bool(row["is_limit_down"])
    if not {"close", "pre_close"}.issubset(row.index) or pd.isna(row["close"]) or pd.isna(row["pre_close"]):
        return False
    return float(row["close"]) <= float(row["pre_close"]) * (1 - limit_pct) + 1e-9


def can_buy(row: pd.Series) -> bool:
    """Return whether a stock can be bought on this row's trade date."""
    return not is_suspended(row) and not is_limit_up(row)


def can_sell(row: pd.Series, bought_today: bool = False) -> bool:
    """Return whether a stock can be sold on this row's trade date.

    T+1 is handled in simplified form by callers passing ``bought_today=True``
    for positions opened on the same trade date. Such positions cannot be sold
    until the next trading day. More detailed lot-level settlement can be added
    later without changing this rule boundary.
    """
    return not bought_today and not is_suspended(row) and not is_limit_down(row)
