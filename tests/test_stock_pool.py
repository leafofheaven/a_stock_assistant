"""Tests for stock pool construction."""

from __future__ import annotations

import pandas as pd

from core.universe.stock_pool import build_tradeable_universe


def test_build_tradeable_universe_outputs_required_columns() -> None:
    """Universe output should include the required project fields."""
    result = build_tradeable_universe(
        stock_basic=_stock_basic(),
        daily_price=_daily_price(),
        daily_basic=_daily_basic(),
        trade_date="20240131",
    )

    assert list(result.columns) == [
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


def test_build_tradeable_universe_keeps_tradeable_stock() -> None:
    """A liquid, seasoned, non-ST stock with complete data should be tradeable."""
    result = build_tradeable_universe(_stock_basic(), _daily_price(), _daily_basic(), "20240131")

    row = _row(result, "000001.SZ")

    assert bool(row["is_tradeable"]) is True
    assert row["exclude_reason"] == ""
    assert row["avg_amount_20d"] == 150_000_000
    assert row["avg_turnover_20d"] == 2.0


def test_build_tradeable_universe_excludes_st_stock() -> None:
    """ST and *ST names should be excluded."""
    result = build_tradeable_universe(_stock_basic(), _daily_price(), _daily_basic(), "20240131")

    assert "ST stock" in _row(result, "000002.SZ")["exclude_reason"]
    assert bool(_row(result, "000002.SZ")["is_tradeable"]) is False


def test_build_tradeable_universe_excludes_suspended_on_trade_date() -> None:
    """Stocks suspended on the target trade date should be excluded."""
    result = build_tradeable_universe(_stock_basic(), _daily_price(), _daily_basic(), "20240131")

    row = _row(result, "000003.SZ")

    assert bool(row["is_tradeable"]) is False
    assert "suspended" in row["exclude_reason"]


def test_build_tradeable_universe_excludes_recent_listing() -> None:
    """Stocks listed less than 120 calendar days should be excluded."""
    result = build_tradeable_universe(_stock_basic(), _daily_price(), _daily_basic(), "20240131")

    row = _row(result, "000004.SZ")

    assert bool(row["is_tradeable"]) is False
    assert "listed less than 120 days" in row["exclude_reason"]


def test_build_tradeable_universe_excludes_low_liquidity() -> None:
    """Stocks with low recent average amount should be excluded."""
    result = build_tradeable_universe(_stock_basic(), _daily_price(), _daily_basic(), "20240131")

    row = _row(result, "000005.SZ")

    assert bool(row["is_tradeable"]) is False
    assert "avg amount 20d below 100 million" in row["exclude_reason"]


def test_build_tradeable_universe_excludes_too_many_suspended_days() -> None:
    """Stocks suspended more than three days in the recent window should be excluded."""
    result = build_tradeable_universe(_stock_basic(), _daily_price(), _daily_basic(), "20240131")

    row = _row(result, "000006.SZ")

    assert bool(row["is_tradeable"]) is False
    assert "suspended more than 3 days in 20d" in row["exclude_reason"]


def test_build_tradeable_universe_excludes_severe_financial_missing() -> None:
    """Stocks with severely missing daily basic data should be excluded."""
    result = build_tradeable_universe(_stock_basic(), _daily_price(), _daily_basic(), "20240131")

    row = _row(result, "000007.SZ")

    assert bool(row["is_tradeable"]) is False
    assert "severe financial data missing" in row["exclude_reason"]


def _stock_basic() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "list_date": "19910403"},
            {"ts_code": "000002.SZ", "name": "*ST测试", "industry": "地产", "list_date": "19910129"},
            {"ts_code": "000003.SZ", "name": "停牌测试", "industry": "制造", "list_date": "19910129"},
            {"ts_code": "000004.SZ", "name": "新股测试", "industry": "科技", "list_date": "20231201"},
            {"ts_code": "000005.SZ", "name": "低流动", "industry": "制造", "list_date": "19910129"},
            {"ts_code": "000006.SZ", "name": "多停牌", "industry": "制造", "list_date": "19910129"},
            {"ts_code": "000007.SZ", "name": "缺财务", "industry": "制造", "list_date": "19910129"},
        ]
    )


def _daily_price() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2024-01-02", periods=22, freq="B").strftime("%Y%m%d").tolist()
    for ts_code in _stock_basic()["ts_code"]:
        for index, trade_date in enumerate(dates):
            amount = 150_000_000
            volume = 1000
            is_suspended = False
            if ts_code == "000005.SZ":
                amount = 50_000_000
            if ts_code == "000006.SZ" and index >= len(dates) - 4:
                volume = 0
                is_suspended = True
            if ts_code == "000003.SZ" and trade_date == "20240131":
                volume = 0
                is_suspended = True
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "close": 10.0,
                    "vol": volume,
                    "amount": amount,
                    "is_suspended": is_suspended,
                }
            )
    return pd.DataFrame(rows)


def _daily_basic() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2024-01-02", periods=22, freq="B").strftime("%Y%m%d").tolist()
    for ts_code in _stock_basic()["ts_code"]:
        for trade_date in dates:
            row = {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "turnover_rate": 2.0,
                "pe": 10.0,
                "pb": 1.0,
                "total_mv": 20_000_000_000,
                "circ_mv": 15_000_000_000,
            }
            if ts_code == "000007.SZ":
                row.update({"pe": None, "pb": None, "total_mv": None, "circ_mv": None})
            rows.append(row)
    return pd.DataFrame(rows)


def _row(result: pd.DataFrame, ts_code: str) -> pd.Series:
    return result[result["ts_code"] == ts_code].iloc[0]
