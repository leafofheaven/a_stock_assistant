"""Task 60 update-target date tests."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from core.calendar.trading_calendar import resolve_update_target_trade_date
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import _status_latest_coverage_frame, _status_page_quality_snapshot, resolve_streamlit_research_dates


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_trade_day_before_cutoff_uses_previous_trade_date(tmp_path) -> None:
    store = _store_with_calendar(tmp_path)

    result = resolve_update_target_trade_date(
        store,
        now=datetime(2026, 7, 7, 17, 0, tzinfo=SHANGHAI),
        cutoff_time="18:00",
    )

    assert result.target_trade_date == "20260706"
    assert result.is_today_trade_day is True
    assert result.calendar_source == "trade_calendar"
    assert "尚未过安全更新时间" in result.reason


def test_trade_day_after_cutoff_uses_today(tmp_path) -> None:
    store = _store_with_calendar(tmp_path)

    result = resolve_update_target_trade_date(
        store,
        now=datetime(2026, 7, 7, 18, 30, tzinfo=SHANGHAI),
        cutoff_time="18:00",
    )

    assert result.target_trade_date == "20260707"
    assert result.latest_completed_trade_date == "20260707"
    assert "已过安全更新时间" in result.reason


def test_non_trade_day_uses_recent_completed_trade_date(tmp_path) -> None:
    store = _store_with_calendar(tmp_path)

    result = resolve_update_target_trade_date(
        store,
        now=datetime(2026, 7, 11, 10, 0, tzinfo=SHANGHAI),
        cutoff_time="18:00",
    )

    assert result.target_trade_date == "20260710"
    assert result.is_today_trade_day is False
    assert "不是 A 股交易日" in result.reason


def test_missing_calendar_falls_back_to_latest_daily_price(tmp_path) -> None:
    store = DuckDBStore(tmp_path / "calendar_missing.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20260706", "close": 10.0},
                {"ts_code": "000002.SZ", "trade_date": "20260705", "close": 9.0},
            ]
        ),
    )

    result = resolve_update_target_trade_date(
        store,
        now=datetime(2026, 7, 8, 18, 30, tzinfo=SHANGHAI),
        cutoff_time="18:00",
    )

    assert result.target_trade_date == "20260706"
    assert result.calendar_source == "local_price_fallback"
    assert "交易日历缺失" in result.reason


def test_naive_and_non_shanghai_datetime_use_shanghai_timezone(tmp_path) -> None:
    store = _store_with_calendar(tmp_path)

    naive = resolve_update_target_trade_date(
        store,
        now=datetime(2026, 7, 7, 17, 0),
        cutoff_time="18:00",
    )
    utc_after_cutoff = resolve_update_target_trade_date(
        store,
        now=datetime(2026, 7, 7, 10, 30, tzinfo=timezone.utc),
        cutoff_time="18:00",
    )

    assert naive.today == "20260707"
    assert naive.target_trade_date == "20260706"
    assert utc_after_cutoff.today == "20260707"
    assert utc_after_cutoff.target_trade_date == "20260707"


def test_calendar_without_previous_open_date_falls_back_not_future(tmp_path) -> None:
    store = DuckDBStore(tmp_path / "future_only_calendar.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "trade_calendar",
        pd.DataFrame(
            [
                {"exchange": "SSE", "cal_date": "20260708", "is_open": 0},
                {"exchange": "SSE", "cal_date": "20260709", "is_open": 1},
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260706", "close": 10.0}]),
    )

    result = resolve_update_target_trade_date(
        store,
        now=datetime(2026, 7, 8, 10, 0, tzinfo=SHANGHAI),
        cutoff_time="18:00",
    )

    assert result.target_trade_date == "20260706"
    assert result.target_trade_date != "20260709"
    assert result.calendar_source == "local_price_fallback"
    assert "没有早于当前日期的已完成交易日" in result.reason


def test_streamlit_status_uses_calendar_target_without_planned_zero_as_current(tmp_path, monkeypatch) -> None:
    store = _store_with_calendar(tmp_path)
    monkeypatch.setattr(
        "web.streamlit_app.resolve_update_target_trade_date",
        lambda *args, **kwargs: type(
            "Decision",
            (),
            {
                "to_dict": lambda self: {
                    "target_trade_date": "20260707",
                    "reason": "今天是 A 股交易日，且已过安全更新时间 18:00，计划更新目标为今天。",
                    "calendar_source": "trade_calendar",
                }
            },
        )(),
    )
    tables = {
        "_duckdb_path": str(store.db_path),
        "daily_price": pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "trade_date": ["20260706", "20260706"]}),
        "daily_basic": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260706"]}),
        "adj_factor": pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260706"]}),
    }
    scheduled = {
        "latest_completed_trade_date": "20260707",
        "configured_symbol_count": 5055,
        "latest_daily_price_symbol_count": 0,
    }
    legacy = {"latest_trade_date": "20260706", "latest_selection_date": "20260706", "configured_symbol_count": 5055}

    dates = resolve_streamlit_research_dates(tables, scheduled, legacy)
    snapshot = _status_page_quality_snapshot(tables, scheduled, legacy)
    frame = _status_latest_coverage_frame(snapshot)

    assert dates["planned_update_target_date"] == "20260707"
    assert dates["current_research_trade_date"] == "20260706"
    assert snapshot["latest_daily_price_symbol_count"] == 2
    assert frame.iloc[0]["已覆盖"] == "2 / 2"
    assert "当前研究仍使用 20260706" in snapshot["formal_result_warning_reason"]


def _store_with_calendar(tmp_path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "calendar.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "trade_calendar",
        pd.DataFrame(
            [
                {"exchange": "SSE", "cal_date": "20260706", "is_open": 1},
                {"exchange": "SSE", "cal_date": "20260707", "is_open": 1},
                {"exchange": "SSE", "cal_date": "20260708", "is_open": 1},
                {"exchange": "SSE", "cal_date": "20260710", "is_open": 1},
                {"exchange": "SSE", "cal_date": "20260711", "is_open": 0},
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20260706", "close": 10.0},
                {"ts_code": "000002.SZ", "trade_date": "20260706", "close": 11.0},
            ]
        ),
    )
    return store
