"""Tests for AKShare fallback data source support."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.data_sources.akshare_client import AKShareClient
from core.data_sources.base import DataSourceError
from core.data_sources.provider import select_data_provider
from core.jobs.run_daily_selection import run_daily_selection
from core.jobs.update_real_data import update_real_data
from core.storage.duckdb_store import DuckDBStore


class MockSettings:
    """Settings-like object for provider selection tests."""

    tushare_token = "mock-token"
    data_provider = "tushare"
    enable_akshare_fallback = False
    real_data_start_date = "20240101"
    real_data_end_date = "20240105"
    real_data_sample_symbols = "000001.SZ,600000.SH"
    akshare_sample_symbols = "000001,600000"
    akshare_adjust = "qfq"

    @property
    def sample_symbols(self) -> list[str]:
        """Return Tushare-style sample symbols."""
        return ["000001.SZ", "600000.SH"]

    @property
    def akshare_symbols(self) -> list[str]:
        """Return AKShare-style sample symbols."""
        return ["000001", "600000"]


class AkshareSettings(MockSettings):
    """Settings-like object selecting AKShare directly."""

    data_provider = "akshare"


class FallbackSettings(MockSettings):
    """Settings-like object enabling AKShare fallback."""

    enable_akshare_fallback = True


class EmptyTokenFallbackSettings(FallbackSettings):
    """Settings-like object with no Tushare token and fallback enabled."""

    tushare_token = ""


class MockAKShareModule:
    """Mock AKShare module; no real network calls."""

    def __init__(self, empty: bool = False) -> None:
        self.empty = empty
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def stock_info_a_code_name(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock AKShare stock basic data."""
        self.calls.append(("stock_info_a_code_name", kwargs))
        if self.empty:
            return pd.DataFrame()
        return pd.DataFrame({"code": ["000001", "600000"], "name": ["平安银行", "浦发银行"]})

    def tool_trade_date_hist_sina(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock AKShare calendar data."""
        self.calls.append(("tool_trade_date_hist_sina", kwargs))
        if self.empty:
            return pd.DataFrame()
        return pd.DataFrame({"trade_date": ["2024-01-02", "2024-01-03"]})

    def stock_zh_a_daily(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock AKShare daily data."""
        self.calls.append(("stock_zh_a_daily", kwargs))
        if self.empty:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "date": ["2024-01-02"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "volume": [1000.0],
                "amount": [100000.0],
            }
        )

    def stock_a_lg_indicator(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock AKShare valuation data."""
        self.calls.append(("stock_a_lg_indicator", kwargs))
        if self.empty:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "code": [kwargs.get("symbol", "000001")],
                "trade_date": ["20240102"],
                "pe": [8.5],
                "pb": [0.8],
                "turnover_rate": [1.0],
            }
        )


class BrokenTushareClient:
    """Mock primary client that fails like a provider outage."""

    def get_stock_basic(self) -> pd.DataFrame:
        """Fail during the first provider call."""
        raise DataSourceError("mock tushare failure")

    def get_trade_calendar(self) -> pd.DataFrame:
        """Unused."""
        return pd.DataFrame()

    def get_daily_price(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        """Unused."""
        return pd.DataFrame()

    def get_daily_basic(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        """Unused."""
        return pd.DataFrame()

    def get_adj_factor(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        """Unused."""
        return pd.DataFrame()


def test_data_provider_akshare_selects_akshare_client() -> None:
    """DATA_PROVIDER=akshare should select AKShareClient."""
    selection = select_data_provider(AkshareSettings())

    assert selection.provider_name == "akshare"
    assert isinstance(selection.primary, AKShareClient)
    assert selection.fallback is None


def test_tushare_provider_can_enable_akshare_fallback() -> None:
    """ENABLE_AKSHARE_FALLBACK=true should attach AKShare fallback to Tushare."""
    selection = select_data_provider(FallbackSettings())

    assert selection.provider_name == "tushare"
    assert isinstance(selection.fallback, AKShareClient)
    assert selection.fallback_name == "akshare"


def test_akshare_field_mapping_uses_project_columns() -> None:
    """AKShare client should map provider fields to project table columns."""
    module = MockAKShareModule()
    client = AKShareClient(akshare_module=module)

    stock_basic = client.get_stock_basic()
    trade_calendar = client.get_trade_calendar()
    daily_price = client.get_daily_price("20240101", "20240105", ["000001"])
    daily_basic = client.get_daily_basic("20240101", "20240105", ["000001"])
    adj_factor = client.get_adj_factor("20240101", "20240105", ["000001"])

    assert stock_basic["ts_code"].tolist() == ["000001.SZ", "600000.SH"]
    assert trade_calendar["cal_date"].tolist() == ["20240102", "20240103"]
    assert daily_price.loc[0, "ts_code"] == "000001.SZ"
    assert {"ts_code", "trade_date", "pe", "pb"}.issubset(daily_basic.columns)
    assert adj_factor.loc[0, "adj_factor"] == 1.0


def test_akshare_empty_data_is_handled_clearly(tmp_path: Path) -> None:
    """Empty AKShare frames should not crash ingestion."""
    store = DuckDBStore(tmp_path / "ak-empty.duckdb")
    client = AKShareClient(akshare_module=MockAKShareModule(empty=True))

    result = update_real_data(settings=AkshareSettings(), store=store, client=client)

    assert result["status"] == "success"
    assert result["data_source"] == "akshare"
    assert result["written_rows"]["stock_basic"] == 0
    assert result["written_rows"]["trade_calendar"] == 0
    assert result["written_rows"]["daily_price"] == 0
    assert result["written_rows"]["daily_basic"] == 0


def test_akshare_fallback_runs_when_tushare_fails(tmp_path: Path) -> None:
    """Tushare failure should fall back to AKShare when enabled."""
    store = DuckDBStore(tmp_path / "fallback.duckdb")
    fallback = AKShareClient(akshare_module=MockAKShareModule())

    result = update_real_data(
        settings=FallbackSettings(),
        store=store,
        client=BrokenTushareClient(),
        fallback_client=fallback,
    )

    assert result["status"] == "success"
    assert result["data_source"] == "akshare"
    assert result["written_rows"]["stock_basic"] == 2
    assert len(store.read_table("daily_price")) == 2


def test_empty_tushare_token_can_use_akshare_fallback(tmp_path: Path) -> None:
    """No Tushare token should still allow AKShare fallback when enabled."""
    store = DuckDBStore(tmp_path / "fallback-token.duckdb")
    fallback = AKShareClient(akshare_module=MockAKShareModule())

    result = update_real_data(
        settings=EmptyTokenFallbackSettings(),
        store=store,
        fallback_client=fallback,
    )

    assert result["status"] == "success"
    assert result["data_source"] == "akshare"
    assert "TUSHARE_TOKEN 为空" in result["message"]


def test_sample_smoke_still_runs_with_akshare_work_present(tmp_path: Path) -> None:
    """Sample daily selection smoke test must remain available."""
    summary = run_daily_selection(settings=AkshareSettings(), store=DuckDBStore(tmp_path / "missing.duckdb"))

    assert "sample" in summary["data_source"]
    assert summary["candidate_count"] > 0
