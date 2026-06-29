"""Tests for Task 46 full HS A-share universe and tradeability filters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.data_sources.real_universe import build_full_a_share_universe
from core.config.env_file import validate_env_updates
from core.jobs.diagnose_update_batch import diagnose_update_batch
from core.jobs.update_real_data import update_real_data
from core.storage.duckdb_store import DuckDBStore
from core.strategy.selector import select_top_stocks
from core.universe.stock_pool import build_tradeable_universe


class FullSettings:
    """Settings-like object for full universe tests."""

    data_provider = "akshare"
    tushare_token = ""
    enable_akshare_fallback = False
    real_data_start_date = "20240101"
    real_data_end_date = "20240131"
    real_data_sample_symbols = ""
    akshare_sample_symbols = ""
    real_universe_preset = "full"
    real_batch_size = 2
    real_batch_sleep_seconds = 0.0
    real_max_retries = 1
    real_request_timeout_seconds = 30
    enable_real_basic_enrichment = False
    enable_real_valuation_enrichment = False
    min_listing_days = 120
    min_avg_amount_20d = 100_000_000
    min_median_amount_20d = 50_000_000
    min_latest_amount = 30_000_000
    min_traded_days_20d = 18
    include_bse = False
    duckdb_path = Path("unused.duckdb")

    @property
    def sample_symbols(self) -> list[str]:
        return []

    @property
    def akshare_symbols(self) -> list[str]:
        return []


class ExplicitSettings(FullSettings):
    """Explicit AKShare symbols should override full preset."""

    akshare_sample_symbols = "000001,600000"

    @property
    def akshare_symbols(self) -> list[str]:
        return ["000001", "600000"]


class MockFullClient:
    """Mock provider for full universe updates; no network calls."""

    def __init__(self) -> None:
        self.requested_price_symbols: list[str] = []
        self.failure_records: list[dict[str, str]] = []
        self.enrichment_records: list[dict[str, str]] = []

    def get_stock_basic(self) -> pd.DataFrame:
        """Return mixed A-share rows including excluded symbols."""
        return pd.DataFrame(
            [
                {"symbol": "000001", "name": "平安银行", "list_date": "19910403"},
                {"symbol": "600000", "name": "浦发银行", "list_date": "19991110"},
                {"symbol": "300750", "name": "宁德时代", "list_date": "20180611"},
                {"symbol": "688981", "name": "中芯国际", "list_date": "20200716"},
                {"symbol": "830799", "name": "北交所样本", "list_date": "20200101"},
                {"symbol": "000002", "name": "*ST样本", "list_date": "19910129"},
                {"symbol": "000003", "name": "退市样本", "list_date": "19910129"},
            ]
        )

    def get_trade_calendar(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-02", periods=22, freq="B").strftime("%Y%m%d")
        return pd.DataFrame({"exchange": "SSE", "cal_date": dates, "is_open": 1, "pretrade_date": pd.NA})

    def get_daily_price(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        self.requested_price_symbols.extend(symbols or [])
        return _price_rows(symbols or [], amount=150_000_000)

    def get_daily_basic(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        rows = _basic_rows(symbols or [])
        for column in ["volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]:
            rows[column] = 1.0
        return rows

    def get_adj_factor(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        return pd.DataFrame(
            [{"ts_code": _to_ts_code(symbol), "trade_date": start_date, "adj_factor": 1.0} for symbol in (symbols or [])]
        )


class BrokenBasicClient(MockFullClient):
    """Mock provider whose basic list call fails."""

    def get_stock_basic(self) -> pd.DataFrame:
        raise RuntimeError("mock basic list failure")


def test_env_validation_accepts_full_preset() -> None:
    """Local console .env validation should allow REAL_UNIVERSE_PRESET=full."""
    validate_env_updates({"REAL_UNIVERSE_PRESET": "full"})


def test_full_universe_filters_to_hs_a_shares_without_bse_or_abnormal_names() -> None:
    """full mode should mean HS A-shares, excluding BSE, ST, and delisting names."""
    universe = build_full_a_share_universe(MockFullClient().get_stock_basic(), include_bse=False)

    assert set(universe["ts_code"]) == {"000001.SZ", "600000.SH", "300750.SZ", "688981.SH"}
    assert "830799.BJ" not in set(universe["ts_code"])
    assert all("ST" not in name for name in universe["name"])
    assert {"SSE", "SZSE"}.issuperset(set(universe["exchange"]))


def test_full_update_discovers_symbols_from_stock_basic(tmp_path: Path) -> None:
    """REAL_UNIVERSE_PRESET=full should fetch symbols from provider stock_basic."""
    client = MockFullClient()
    result = update_real_data(settings=FullSettings(), store=DuckDBStore(tmp_path / "full.duckdb"), client=client)

    assert result["status"] == "success"
    assert result["total_symbols"] == 4
    assert set(result["sample_symbols"]) == {"000001", "600000", "300750", "688981"}
    assert "830799" not in client.requested_price_symbols


def test_diagnose_full_resolves_provider_basic_list_without_local_prices(tmp_path: Path) -> None:
    """diagnose_update_batch should not silently report zero configured symbols for full."""
    result = diagnose_update_batch(
        settings=FullSettings(),
        store=DuckDBStore(tmp_path / "missing.duckdb"),
        client=MockFullClient(),
    )

    assert result["sample_source"] == "REAL_UNIVERSE_PRESET=full"
    assert result["raw_symbol_count"] == 7
    assert result["excluded_bse_count"] == 1
    assert result["excluded_abnormal_count"] == 2
    assert result["base_universe_count"] == 4
    assert result["configured_symbol_count"] == 4
    assert result["priced_symbol_count"] == 0


def test_diagnose_full_provider_failure_has_clear_warning(tmp_path: Path) -> None:
    """full basic list failures should be explicit instead of silent zero."""
    result = diagnose_update_batch(
        settings=FullSettings(),
        store=DuckDBStore(tmp_path / "missing-failure.duckdb"),
        client=BrokenBasicClient(),
    )

    assert result["configured_symbol_count"] == 0
    assert any("AKShare 基础股票列表获取失败" in reason for reason in result["reasons"])


def test_explicit_akshare_symbols_take_priority_over_full(tmp_path: Path) -> None:
    """AKSHARE_SAMPLE_SYMBOLS should override REAL_UNIVERSE_PRESET=full."""
    client = MockFullClient()
    result = update_real_data(settings=ExplicitSettings(), store=DuckDBStore(tmp_path / "explicit.duckdb"), client=client)

    assert result["total_symbols"] == 2
    assert result["sample_symbols"] == ["000001", "600000"]
    assert set(client.requested_price_symbols) == {"000001", "600000"}


def test_tradeable_filter_excludes_bse_st_delisting_recent_and_liquidity() -> None:
    """Tradeable universe should apply Task 46 hard filters."""
    stocks = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "list_date": "19910403", "exchange": "SZSE"},
            {"ts_code": "830799.BJ", "symbol": "830799", "name": "北交样本", "list_date": "20200101", "exchange": "BSE"},
            {"ts_code": "000002.SZ", "symbol": "000002", "name": "*ST样本", "list_date": "19910129", "exchange": "SZSE"},
            {"ts_code": "000003.SZ", "symbol": "000003", "name": "退市样本", "list_date": "19910129", "exchange": "SZSE"},
            {"ts_code": "000004.SZ", "symbol": "000004", "name": "新股样本", "list_date": "20240101", "exchange": "SZSE"},
            {"ts_code": "000005.SZ", "symbol": "000005", "name": "低均值", "list_date": "19910129", "exchange": "SZSE"},
            {"ts_code": "000006.SZ", "symbol": "000006", "name": "低中位", "list_date": "19910129", "exchange": "SZSE"},
            {"ts_code": "000007.SZ", "symbol": "000007", "name": "低最新", "list_date": "19910129", "exchange": "SZSE"},
            {"ts_code": "000008.SZ", "symbol": "000008", "name": "成交断续", "list_date": "19910129", "exchange": "SZSE"},
        ]
    )
    price = pd.concat(
        [
            _price_rows(["000001"], amount=150_000_000),
            _price_rows(["830799"], amount=150_000_000),
            _price_rows(["000002"], amount=150_000_000),
            _price_rows(["000003"], amount=150_000_000),
            _price_rows(["000004"], amount=150_000_000),
            _price_rows(["000005"], amount=80_000_000),
            _price_rows(["000006"], amount=150_000_000, low_median=True),
            _price_rows(["000007"], amount=150_000_000, low_latest=True),
            _price_rows(["000008"], amount=150_000_000, zero_days=3),
        ],
        ignore_index=True,
    )
    basic = _basic_rows(stocks["symbol"].tolist())

    result = build_tradeable_universe(stocks, price, basic, "20240131")

    assert bool(_row(result, "000001.SZ")["is_tradeable"]) is True
    assert "BSE stock" in _row(result, "830799.BJ")["exclude_reason"]
    assert "ST stock" in _row(result, "000002.SZ")["exclude_reason"]
    assert "delisting stock" in _row(result, "000003.SZ")["exclude_reason"]
    assert "listed less than 120 days" in _row(result, "000004.SZ")["exclude_reason"]
    assert "avg amount 20d below 100 million" in _row(result, "000005.SZ")["exclude_reason"]
    assert "median amount 20d below 50000000" in _row(result, "000006.SZ")["exclude_reason"]
    assert "latest amount below 30000000" in _row(result, "000007.SZ")["exclude_reason"]
    assert "traded days 20d below 18" in _row(result, "000008.SZ")["exclude_reason"]


def test_suspended_or_no_recent_trading_is_temporary_exclusion() -> None:
    """Recent no-trading exclusion should be recalculated each run, not stored as blacklist."""
    stocks = pd.DataFrame([{"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "list_date": "19910403"}])
    basic = _basic_rows(["000001"])
    suspended = build_tradeable_universe(stocks, _price_rows(["000001"], amount=150_000_000, zero_days=4), basic, "20240131")
    resumed = build_tradeable_universe(stocks, _price_rows(["000001"], amount=150_000_000, zero_days=0), basic, "20240131")

    assert bool(_row(suspended, "000001.SZ")["is_tradeable"]) is False
    assert bool(_row(resumed, "000001.SZ")["is_tradeable"]) is True


def test_full_mode_does_not_change_existing_total_score_sorting() -> None:
    """Selection order must still be driven by total_score, not universe mode."""
    scored = pd.DataFrame(
        {
            "trade_date": ["20240131", "20240131", "20240131"],
            "ts_code": ["000001.SZ", "600000.SH", "300750.SZ"],
            "name": ["A", "B", "C"],
            "total_score": [50.0, 90.0, 70.0],
        }
    )

    selected = select_top_stocks(scored, top_n=3)

    assert selected["ts_code"].tolist() == ["600000.SH", "300750.SZ", "000001.SZ"]


def _price_rows(
    symbols: list[str],
    *,
    amount: float,
    low_median: bool = False,
    low_latest: bool = False,
    zero_days: int = 0,
) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=22, freq="B").strftime("%Y%m%d").tolist()
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        ts_code = _to_ts_code(symbol)
        for index, trade_date in enumerate(dates):
            row_amount = amount
            vol = 1000
            if low_median and index < 14:
                row_amount = 10_000_000
            if low_latest and index == len(dates) - 1:
                row_amount = 10_000_000
            if zero_days and index >= len(dates) - zero_days:
                row_amount = 0
                vol = 0
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.5,
                    "close": 10.2,
                    "vol": vol,
                    "amount": row_amount,
                }
            )
    return pd.DataFrame(rows)


def _basic_rows(symbols: list[str]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=22, freq="B").strftime("%Y%m%d").tolist()
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for trade_date in dates:
            rows.append(
                {
                    "ts_code": _to_ts_code(symbol),
                    "trade_date": trade_date,
                    "turnover_rate": 2.0,
                    "pe": 10.0,
                    "pb": 1.0,
                    "total_mv": 10_000_000_000,
                    "circ_mv": 8_000_000_000,
                }
            )
    return pd.DataFrame(rows)


def _to_ts_code(symbol: str) -> str:
    clean = str(symbol).split(".")[0]
    if clean.startswith(("4", "8", "9")):
        return f"{clean}.BJ"
    return f"{clean}.SH" if clean.startswith("6") else f"{clean}.SZ"


def _row(result: pd.DataFrame, ts_code: str) -> pd.Series:
    return result[result["ts_code"] == ts_code].iloc[0]
