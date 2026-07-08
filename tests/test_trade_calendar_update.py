"""Tests for Task 63 local trade-calendar maintenance."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from core.calendar.trading_calendar import resolve_update_target_trade_date, summarize_trade_calendar_status
from core.jobs.update_trade_calendar import normalize_trade_calendar, update_trade_calendar
from core.storage.duckdb_store import DuckDBStore


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_update_trade_calendar_writes_provider_rows(tmp_path) -> None:
    """Calendar job should write normalized rows from a provider."""
    store = _store(tmp_path)

    result = update_trade_calendar(
        start_date="20260706",
        end_date="20260708",
        store=store,
        provider_factory=lambda settings: _FakeCalendarProvider(pd.DataFrame({"cal_date": ["20260706", "20260707"]})),
    )

    assert result.status == "success"
    assert result.written_rows == 3
    assert result.open_day_count == 2
    written = store.read_table("trade_calendar")
    assert set(written["cal_date"].astype(str)) == {"20260706", "20260707", "20260708"}
    assert int(written.loc[written["cal_date"] == "20260708", "is_open"].iloc[0]) == 0


def test_resolver_uses_trade_calendar_after_update(tmp_path) -> None:
    """Once calendar covers today, Task 60 resolver should use trade_calendar."""
    store = _store(tmp_path)
    update_trade_calendar(
        start_date="20260706",
        end_date="20260708",
        store=store,
        provider_factory=lambda settings: _FakeCalendarProvider(pd.DataFrame({"cal_date": ["20260706", "20260707", "20260708"]})),
    )

    decision = resolve_update_target_trade_date(store, now=datetime(2026, 7, 7, 17, 0, tzinfo=SHANGHAI), cutoff_time="18:00")

    assert decision.calendar_source == "trade_calendar"
    assert decision.target_trade_date == "20260706"
    assert "尚未过安全更新时间" in decision.reason


def test_trade_calendar_after_cutoff_uses_today(tmp_path) -> None:
    """A covered trade day after cutoff should target today."""
    store = _store(tmp_path)
    update_trade_calendar(
        start_date="20260706",
        end_date="20260708",
        store=store,
        provider_factory=lambda settings: _FakeCalendarProvider(pd.DataFrame({"cal_date": ["20260706", "20260707", "20260708"]})),
    )

    decision = resolve_update_target_trade_date(store, now=datetime(2026, 7, 7, 18, 30, tzinfo=SHANGHAI), cutoff_time="18:00")

    assert decision.calendar_source == "trade_calendar"
    assert decision.target_trade_date == "20260707"


def test_trade_calendar_non_trade_day_uses_recent_completed_day(tmp_path) -> None:
    """A closed day covered by calendar should use the latest prior open date."""
    store = _store(tmp_path)
    update_trade_calendar(
        start_date="20260706",
        end_date="20260709",
        store=store,
        provider_factory=lambda settings: _FakeCalendarProvider(pd.DataFrame({"cal_date": ["20260706", "20260707"]})),
    )

    decision = resolve_update_target_trade_date(store, now=datetime(2026, 7, 8, 12, 0, tzinfo=SHANGHAI), cutoff_time="18:00")

    assert decision.calendar_source == "trade_calendar"
    assert decision.target_trade_date == "20260707"
    assert "不是 A 股交易日" in decision.reason


def test_trade_calendar_missing_falls_back_to_daily_price(tmp_path) -> None:
    """Missing calendar should still fall back to latest local price date."""
    store = _store(tmp_path)
    store.upsert_dataframe("daily_price", pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260706", "close": 10.0}]))

    decision = resolve_update_target_trade_date(store, now=datetime(2026, 7, 8, 12, 0, tzinfo=SHANGHAI), cutoff_time="18:00")

    assert decision.calendar_source == "local_price_fallback"
    assert decision.target_trade_date == "20260706"


def test_trade_calendar_status_reports_coverage(tmp_path) -> None:
    """Status helper should expose calendar coverage for Streamlit."""
    store = _store(tmp_path)
    update_trade_calendar(
        start_date="20260706",
        end_date="20260810",
        store=store,
        provider_factory=lambda settings: _FakeCalendarProvider(pd.DataFrame({"cal_date": ["20260706", "20260707", "20260710", "20260810"]})),
    )

    status = summarize_trade_calendar_status(store, now=datetime(2026, 7, 8, 12, 0, tzinfo=SHANGHAI), cutoff_time="18:00")

    assert status["calendar_exists"] is True
    assert status["coverage_start"] == "20260706"
    assert status["coverage_end"] == "20260810"
    assert status["covers_today"] is True
    assert status["covers_next_30_days"] is True
    assert status["calendar_source"] == "trade_calendar"
    assert status["recent_open_trade_date"] == "20260707"
    assert status["next_open_trade_date"] == "20260710"


def test_provider_failure_keeps_existing_calendar(tmp_path) -> None:
    """Provider failures should return warning and not clear existing rows."""
    store = _store(tmp_path)
    store.upsert_dataframe("trade_calendar", pd.DataFrame([{"exchange": "SSE", "cal_date": "20260706", "is_open": 1}]))

    result = update_trade_calendar(
        start_date="20260706",
        end_date="20260708",
        store=store,
        provider_factory=lambda settings: _FailingCalendarProvider(),
    )

    assert result.status == "warning"
    assert result.written_rows == 0
    assert len(store.read_table("trade_calendar")) == 1


def test_normalize_trade_calendar_does_not_hardcode_weekdays() -> None:
    """Closed dates are derived from provider open dates, not weekday assumptions."""
    result = normalize_trade_calendar(
        pd.DataFrame({"cal_date": ["20260706", "20260708"]}),
        start_date="20260706",
        end_date="20260708",
        exchange="SSE",
        source="fake",
    )

    by_date = dict(zip(result["cal_date"], result["is_open"]))
    assert by_date["20260706"] == 1
    assert by_date["20260707"] == 0
    assert by_date["20260708"] == 1


class _FakeCalendarProvider:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def get_trade_calendar(self) -> pd.DataFrame:
        return self.frame.copy()


class _FailingCalendarProvider:
    def get_trade_calendar(self) -> pd.DataFrame:
        raise RuntimeError("calendar endpoint unavailable")


def _store(tmp_path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "trade_calendar.duckdb")
    store.initialize()
    return store

