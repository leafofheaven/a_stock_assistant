"""Resolve A-share update target dates from local trading calendar data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class UpdateTargetTradeDate:
    """Decision for the trade date a data update should target."""

    target_trade_date: str
    reason: str
    today: str
    is_today_trade_day: bool
    latest_completed_trade_date: str
    cutoff_time: str
    calendar_source: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/Streamlit friendly payload."""
        return asdict(self)


def summarize_trade_calendar_status(
    store: Any,
    now: datetime | None = None,
    exchange: str = "SSE",
    cutoff_time: str = "18:00",
) -> dict[str, Any]:
    """Return a read-only status summary for the local trade calendar."""
    current = _to_shanghai_time(now or datetime.now(tz=SHANGHAI_TZ))
    today = current.strftime("%Y%m%d")
    calendar = _read_trade_calendar(store, exchange)
    decision = resolve_update_target_trade_date(store, now=current, cutoff_time=cutoff_time, calendar_market=exchange)
    if calendar.empty or "cal_date" not in calendar.columns:
        return {
            "calendar_exists": False,
            "calendar_source": decision.calendar_source,
            "exchange": exchange,
            "coverage_start": "",
            "coverage_end": "",
            "covers_today": False,
            "covers_next_30_days": False,
            "recent_open_trade_date": decision.latest_completed_trade_date,
            "next_open_trade_date": "",
            "target_trade_date": decision.target_trade_date,
            "reason": decision.reason,
        }
    frame = calendar.copy()
    frame["cal_date"] = frame["cal_date"].map(_compact_date)
    frame = frame[frame["cal_date"].astype(str).str.len() == 8]
    dates = sorted(frame["cal_date"].dropna().astype(str).unique())
    open_dates = _open_dates(frame)
    next_30 = (current + timedelta(days=30)).strftime("%Y%m%d")
    return {
        "calendar_exists": bool(dates),
        "calendar_source": decision.calendar_source,
        "exchange": exchange,
        "coverage_start": dates[0] if dates else "",
        "coverage_end": dates[-1] if dates else "",
        "covers_today": today in set(dates),
        "covers_next_30_days": bool(dates and dates[-1] >= next_30),
        "recent_open_trade_date": _latest_open_date_on_or_before(open_dates, today),
        "next_open_trade_date": _next_open_date_after(open_dates, today),
        "target_trade_date": decision.target_trade_date,
        "reason": decision.reason,
    }


def resolve_update_target_trade_date(
    store: Any,
    now: datetime | None = None,
    cutoff_time: str = "18:00",
    calendar_market: str = "SSE",
) -> UpdateTargetTradeDate:
    """Resolve the A-share trade date that should be updated now.

    The decision is deliberately conservative: it uses the local trade_calendar
    table when it covers today's date, and otherwise falls back to the latest
    local daily_price date instead of guessing from natural calendar days.
    """
    current = _to_shanghai_time(now or datetime.now(tz=SHANGHAI_TZ))
    today = current.strftime("%Y%m%d")
    cutoff = _parse_cutoff_time(cutoff_time)
    calendar = _read_trade_calendar(store, calendar_market)
    if not calendar.empty and _calendar_covers(calendar, today):
        open_dates = _open_dates(calendar)
        is_today_trade_day = today in open_dates
        if is_today_trade_day and current.time() >= cutoff:
            return UpdateTargetTradeDate(
                target_trade_date=today,
                reason=f"今天是 A 股交易日，且已过安全更新时间 {cutoff_time}，计划更新目标为今天。",
                today=today,
                is_today_trade_day=True,
                latest_completed_trade_date=today,
                cutoff_time=cutoff_time,
                calendar_source="trade_calendar",
            )
        completed = _previous_open_date(open_dates, today)
        if not completed:
            return _fallback_decision(store, today, cutoff_time, "交易日历没有早于当前日期的已完成交易日，使用本地最新行情日作为保守更新目标。")
        if is_today_trade_day:
            reason = f"今天是 A 股交易日，但尚未过安全更新时间 {cutoff_time}，继续使用上一交易日 {completed}。"
        else:
            reason = f"今天不是 A 股交易日，计划更新目标为最近已完成交易日 {completed}。"
        return UpdateTargetTradeDate(
            target_trade_date=completed,
            reason=reason,
            today=today,
            is_today_trade_day=is_today_trade_day,
            latest_completed_trade_date=completed,
            cutoff_time=cutoff_time,
            calendar_source="trade_calendar",
        )

    return _fallback_decision(store, today, cutoff_time, "交易日历缺失或未覆盖当前日期，使用本地最新行情日作为保守更新目标。")


def _fallback_decision(store: Any, today: str, cutoff_time: str, reason: str) -> UpdateTargetTradeDate:
    fallback = _latest_daily_price_date(store)
    return UpdateTargetTradeDate(
        target_trade_date=fallback,
        reason=reason,
        today=today,
        is_today_trade_day=False,
        latest_completed_trade_date=fallback,
        cutoff_time=cutoff_time,
        calendar_source="local_price_fallback",
    )


def _to_shanghai_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TZ)
    return value.astimezone(SHANGHAI_TZ)


def _parse_cutoff_time(value: str) -> time:
    hour, minute = value.split(":", maxsplit=1)
    return time(hour=int(hour), minute=int(minute[:2]))


def _read_trade_calendar(store: Any, market: str) -> pd.DataFrame:
    try:
        with store.connect(read_only=True) as connection:
            return connection.execute(
                """
                SELECT cal_date, is_open, exchange
                FROM trade_calendar
                WHERE exchange = ? OR exchange IS NULL OR exchange = ''
                """,
                [market],
            ).fetchdf()
    except Exception:
        return pd.DataFrame()


def _calendar_covers(calendar: pd.DataFrame, today: str) -> bool:
    if calendar.empty or "cal_date" not in calendar.columns:
        return False
    dates = calendar["cal_date"].map(_compact_date).dropna()
    return bool((dates == today).any())


def _open_dates(calendar: pd.DataFrame) -> list[str]:
    if calendar.empty or not {"cal_date", "is_open"}.issubset(calendar.columns):
        return []
    frame = calendar.copy()
    frame["cal_date"] = frame["cal_date"].map(_compact_date)
    frame["is_open"] = pd.to_numeric(frame["is_open"], errors="coerce").fillna(0).astype(int)
    return sorted(frame.loc[frame["is_open"] == 1, "cal_date"].dropna().astype(str).unique())


def _previous_open_date(open_dates: list[str], today: str) -> str:
    previous = [date for date in open_dates if date < today]
    if previous:
        return previous[-1]
    return ""


def _latest_open_date_on_or_before(open_dates: list[str], today: str) -> str:
    candidates = [date for date in open_dates if date <= today]
    return candidates[-1] if candidates else ""


def _next_open_date_after(open_dates: list[str], today: str) -> str:
    candidates = [date for date in open_dates if date > today]
    return candidates[0] if candidates else ""


def _latest_daily_price_date(store: Any) -> str:
    try:
        with store.connect(read_only=True) as connection:
            row = connection.execute(
                "SELECT MAX(replace(CAST(trade_date AS VARCHAR), '-', '')) FROM daily_price"
            ).fetchone()
    except Exception:
        return ""
    return str(row[0] or "") if row else ""


def _compact_date(value: Any) -> str:
    text = str(value or "").strip()
    return text.replace("-", "")[:8] if text else ""
