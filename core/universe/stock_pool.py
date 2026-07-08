"""Tradeable A-share universe construction."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

OUTPUT_COLUMNS = [
    "ts_code",
    "name",
    "industry",
    "list_date",
    "trade_date",
    "avg_amount_20d",
    "median_amount_20d",
    "latest_amount",
    "traded_days_20d",
    "avg_turnover_20d",
    "is_tradeable",
    "exclude_reason",
]


def build_tradeable_universe(
    stock_basic: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
    trade_date: str,
    allow_missing_list_date_with_price_history: bool = True,
    min_price_history_days: int = 60,
    allow_missing_valuation: bool = False,
    min_listing_days: int = 120,
    min_avg_amount_20d: float = 100_000_000,
    min_median_amount_20d: float = 50_000_000,
    min_latest_amount: float = 30_000_000,
    min_traded_days_20d: int = 18,
    include_bse: bool = False,
) -> pd.DataFrame:
    """Build the tradeable stock universe for a given trade date.

    The function keeps one output row per stock in ``stock_basic`` and records
    every exclusion reason instead of dropping rows silently.
    Missing listing dates can be validated with local price history because
    several free data sources do not provide complete ``list_date`` fields.
    Market-cap fields are diagnostic only and are not hard tradeability gates.
    """
    if stock_basic.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    price_window = _latest_rows_until(daily_price, "trade_date", trade_date, window=20)
    basic_window = _latest_rows_until(daily_basic, "trade_date", trade_date, window=20)
    price_on_trade_date = _rows_on_date(daily_price, "trade_date", trade_date)

    rows: list[dict[str, object]] = []
    for stock in stock_basic.to_dict("records"):
        ts_code = str(stock.get("ts_code", ""))
        name = str(stock.get("name", ""))
        industry = stock.get("industry")
        list_date = str(stock.get("list_date", ""))
        reasons: list[str] = []

        stock_price_window = price_window[price_window["ts_code"] == ts_code]
        stock_basic_window = basic_window[basic_window["ts_code"] == ts_code]
        latest_price = price_on_trade_date[price_on_trade_date["ts_code"] == ts_code]
        stock_price_history = _rows_until(daily_price, "trade_date", trade_date, ts_code)

        avg_amount_20d = _mean_or_none(stock_price_window, "amount")
        median_amount_20d = _median_or_none(stock_price_window, "amount")
        latest_amount = _latest_amount(latest_price)
        traded_days_20d = _traded_days(stock_price_window)
        avg_turnover_20d = _mean_or_none(stock_basic_window, "turnover_rate")

        if _is_st_stock(name):
            reasons.append("ST stock")

        if _is_delisting_stock(name):
            reasons.append("delisting stock")

        if _is_bse_stock(ts_code, stock) and not include_bse:
            reasons.append("BSE stock")

        if _is_suspended_on_trade_date(latest_price):
            reasons.append("suspended")

        if _listed_less_than_days(
            list_date,
            trade_date,
            days=min_listing_days,
            price_history_days=len(stock_price_history),
            allow_missing_list_date_with_price_history=allow_missing_list_date_with_price_history,
            min_price_history_days=min_price_history_days,
        ):
            reasons.append(f"listed less than {min_listing_days} days")

        if traded_days_20d < min_traded_days_20d:
            reasons.append(f"traded days 20d below {min_traded_days_20d}")

        if avg_amount_20d is None or avg_amount_20d < min_avg_amount_20d:
            if int(min_avg_amount_20d) == 100_000_000:
                reasons.append("avg amount 20d below 100 million")
            else:
                reasons.append(f"avg amount 20d below {int(min_avg_amount_20d)}")

        if median_amount_20d is None or median_amount_20d < min_median_amount_20d:
            reasons.append(f"median amount 20d below {int(min_median_amount_20d)}")

        if latest_amount is None or latest_amount < min_latest_amount:
            reasons.append(f"latest amount below {int(min_latest_amount)}")

        if _suspended_days(stock_price_window) > 3:
            reasons.append("suspended more than 3 days in 20d")

        if _has_severe_financial_missing(stock_basic_window, allow_missing_valuation=allow_missing_valuation):
            reasons.append("severe financial data missing")

        rows.append(
            {
                "ts_code": ts_code,
                "name": name,
                "industry": industry,
                "list_date": list_date,
                "trade_date": trade_date,
                "avg_amount_20d": avg_amount_20d,
                "median_amount_20d": median_amount_20d,
                "latest_amount": latest_amount,
                "traded_days_20d": traded_days_20d,
                "avg_turnover_20d": avg_turnover_20d,
                "is_tradeable": not reasons,
                "exclude_reason": "; ".join(reasons),
            }
        )

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def _latest_rows_until(df: pd.DataFrame, date_column: str, trade_date: str, window: int) -> pd.DataFrame:
    """Return up to ``window`` rows per stock with dates no later than trade_date."""
    if df.empty or date_column not in df.columns or "ts_code" not in df.columns:
        return pd.DataFrame(columns=df.columns)

    eligible = df[df[date_column].astype(str) <= trade_date].copy()
    if eligible.empty:
        return eligible

    eligible = eligible.sort_values(["ts_code", date_column])
    return eligible.groupby("ts_code", group_keys=False).tail(window)


def _rows_on_date(df: pd.DataFrame, date_column: str, trade_date: str) -> pd.DataFrame:
    """Return rows matching the requested trade date."""
    if df.empty or date_column not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df[date_column].astype(str) == trade_date]


def _rows_until(df: pd.DataFrame, date_column: str, trade_date: str, ts_code: str) -> pd.DataFrame:
    """Return all rows for a stock with dates no later than trade_date."""
    if df.empty or date_column not in df.columns or "ts_code" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[(df["ts_code"] == ts_code) & (df[date_column].astype(str) <= trade_date)]


def _mean_or_none(df: pd.DataFrame, column: str) -> float | None:
    """Return a numeric mean or None when there is no usable data."""
    if df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.mean())


def _median_or_none(df: pd.DataFrame, column: str) -> float | None:
    """Return a numeric median or None when there is no usable data."""
    if df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    values = values[values > 0]
    if values.empty:
        return None
    return float(values.median())


def _latest_amount(price_rows: pd.DataFrame) -> float | None:
    """Return latest trade-date amount when available."""
    if price_rows.empty or "amount" not in price_rows.columns:
        return None
    values = pd.to_numeric(price_rows["amount"], errors="coerce").dropna()
    values = values[values > 0]
    if values.empty:
        return None
    return float(values.iloc[-1])


def _traded_days(price_window: pd.DataFrame) -> int:
    """Count recent days with positive volume and amount."""
    if price_window.empty:
        return 0
    if "vol" in price_window.columns:
        vol = pd.to_numeric(price_window["vol"], errors="coerce").fillna(0)
    else:
        vol = pd.Series([1] * len(price_window), index=price_window.index)
    if "amount" in price_window.columns:
        amount = pd.to_numeric(price_window["amount"], errors="coerce").fillna(0)
    else:
        amount = pd.Series([1] * len(price_window), index=price_window.index)
    return int(((vol > 0) & (amount > 0)).sum())


def _is_st_stock(name: str) -> bool:
    """Return whether a stock name indicates ST status."""
    normalized = name.upper().replace(" ", "")
    return "ST" in normalized


def _is_delisting_stock(name: str) -> bool:
    """Return whether a stock name indicates delisting or abnormal trading."""
    normalized = name.upper().replace(" ", "")
    return any(token in normalized for token in ["退市", "退", "PT"])


def _is_bse_stock(ts_code: str, stock: dict[str, object]) -> bool:
    """Return whether a stock is BSE/BJ by exchange, suffix, or prefix."""
    exchange = str(stock.get("exchange", "")).upper()
    symbol = str(stock.get("symbol", "") or ts_code.split(".")[0])
    return exchange in {"BSE", "BJ"} or ts_code.endswith((".BJ", ".BSE")) or symbol.startswith(("4", "8", "9"))


def _is_suspended_on_trade_date(price_rows: pd.DataFrame) -> bool:
    """Return whether the stock is suspended on the target trade date."""
    if price_rows.empty:
        return True
    if "is_suspended" in price_rows.columns:
        suspended = price_rows["is_suspended"].fillna(False).astype(bool)
        return bool(suspended.all())
    if "vol" in price_rows.columns:
        volume = pd.to_numeric(price_rows["vol"], errors="coerce").fillna(0)
        return bool((volume <= 0).all())
    return False


def _listed_less_than_days(
    list_date: str,
    trade_date: str,
    days: int,
    price_history_days: int = 0,
    allow_missing_list_date_with_price_history: bool = False,
    min_price_history_days: int = 60,
) -> bool:
    """Return whether the stock has been listed for less than the required days."""
    listed_at = _parse_yyyymmdd(list_date)
    traded_at = _parse_yyyymmdd(trade_date)
    if listed_at is None or traded_at is None:
        if allow_missing_list_date_with_price_history:
            return price_history_days < min_price_history_days
        return True
    return (traded_at - listed_at).days < days


def _parse_yyyymmdd(value: str) -> datetime | None:
    """Parse a YYYYMMDD date string."""
    try:
        return datetime.strptime(str(value), "%Y%m%d")
    except (TypeError, ValueError):
        return None


def _suspended_days(price_window: pd.DataFrame) -> int:
    """Count suspended days in a recent price window."""
    if price_window.empty:
        return 20
    if "is_suspended" in price_window.columns:
        return int(price_window["is_suspended"].fillna(False).astype(bool).sum())
    if "vol" in price_window.columns:
        volume = pd.to_numeric(price_window["vol"], errors="coerce").fillna(0)
        return int((volume <= 0).sum())
    return 0


def _has_severe_financial_missing(daily_basic_window: pd.DataFrame, allow_missing_valuation: bool = False) -> bool:
    """Return whether key daily basic indicators are severely missing."""
    required_columns = ["turnover_rate"]
    if daily_basic_window.empty:
        return True
    missing_columns = [column for column in required_columns if column not in daily_basic_window.columns]
    if missing_columns and not allow_missing_valuation:
        return True
    if allow_missing_valuation:
        if "turnover_rate" not in daily_basic_window.columns:
            return True
        turnover = pd.to_numeric(daily_basic_window["turnover_rate"], errors="coerce")
        return bool(turnover.dropna().empty)

    required_values = daily_basic_window[required_columns].apply(pd.to_numeric, errors="coerce")
    return bool(required_values.isna().mean().max() > 0.5)
