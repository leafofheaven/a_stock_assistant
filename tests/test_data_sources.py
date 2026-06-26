"""Tests for data source clients."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pytest

from core.data_sources.akshare_client import AKShareClient
from core.data_sources.base import DataSourceError, StockDataSource
from core.data_sources.tushare_client import TushareClient


class MockTushareProApi:
    """Mock Tushare pro API for client tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def stock_basic(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock stock basic data."""
        self.calls.append(("stock_basic", kwargs))
        return pd.DataFrame({"ts_code": ["000001.SZ"], "name": ["平安银行"]})

    def trade_cal(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock trade calendar data."""
        self.calls.append(("trade_cal", kwargs))
        return pd.DataFrame({"cal_date": ["20240102"], "is_open": [1]})

    def daily(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock daily price data."""
        self.calls.append(("daily", kwargs))
        return pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240102"], "close": [10.0]})

    def daily_basic(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock daily basic data."""
        self.calls.append(("daily_basic", kwargs))
        return pd.DataFrame({"ts_code": ["000001.SZ"], "pe": [8.5]})

    def adj_factor(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock adjustment factor data."""
        self.calls.append(("adj_factor", kwargs))
        return pd.DataFrame({"ts_code": ["000001.SZ"], "adj_factor": [1.0]})


class MockAKShareModule:
    """Mock AKShare module for client tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def stock_info_a_code_name(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock stock basic data."""
        self.calls.append(("stock_info_a_code_name", kwargs))
        return pd.DataFrame({"code": ["000001"], "name": ["平安银行"]})

    def tool_trade_date_hist_sina(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock trade calendar data."""
        self.calls.append(("tool_trade_date_hist_sina", kwargs))
        return pd.DataFrame({"trade_date": ["2024-01-02"]})

    def stock_zh_a_daily(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock daily price or adjustment data."""
        self.calls.append(("stock_zh_a_daily", kwargs))
        return pd.DataFrame({"date": ["2024-01-02"], "close": [10.0]})

    def stock_a_lg_indicator(self, **kwargs: Any) -> pd.DataFrame:
        """Return mock daily basic data."""
        self.calls.append(("stock_a_lg_indicator", kwargs))
        return pd.DataFrame({"trade_date": ["20240102"], "pe": [8.5]})


def test_data_source_clients_implement_unified_interface() -> None:
    """Concrete clients should implement the unified data source interface."""
    assert isinstance(TushareClient(token="test-token", pro_api=MockTushareProApi()), StockDataSource)
    assert isinstance(AKShareClient(akshare_module=MockAKShareModule()), StockDataSource)


def test_tushare_client_methods_return_dataframes() -> None:
    """Tushare client methods should return DataFrames from the injected API."""
    pro_api = MockTushareProApi()
    client = TushareClient(token="test-token", pro_api=pro_api)

    results = [
        client.get_stock_basic(),
        client.get_trade_calendar(),
        client.get_daily_price("20240101", "20240131"),
        client.get_daily_basic("20240101", "20240131"),
        client.get_adj_factor("20240101", "20240131"),
    ]

    assert all(isinstance(result, pd.DataFrame) for result in results)
    assert [name for name, _ in pro_api.calls] == [
        "stock_basic",
        "trade_cal",
        "daily",
        "daily_basic",
        "adj_factor",
    ]
    assert pro_api.calls[2][1] == {"start_date": "20240101", "end_date": "20240131"}


def test_tushare_client_reads_token_from_settings(monkeypatch) -> None:
    """Tushare token should be read from application settings when not injected."""
    class MockSettings:
        tushare_token = "settings-token"

    monkeypatch.setattr("core.data_sources.tushare_client.get_settings", lambda: MockSettings())

    client = TushareClient(pro_api=MockTushareProApi())

    assert client.token == "settings-token"


def test_tushare_client_requires_token_without_injected_api() -> None:
    """Tushare client should fail clearly when no token or injected API exists."""
    client = TushareClient(token="")

    with pytest.raises(DataSourceError, match="token is required"):
        client.get_stock_basic()


def test_akshare_client_methods_return_dataframes() -> None:
    """AKShare client methods should return DataFrames from the injected module."""
    akshare = MockAKShareModule()
    client = AKShareClient(akshare_module=akshare)

    results = [
        client.get_stock_basic(),
        client.get_trade_calendar(),
        client.get_daily_price("20240101", "20240131"),
        client.get_daily_basic("20240101", "20240131"),
        client.get_adj_factor("20240101", "20240131"),
    ]

    assert all(isinstance(result, pd.DataFrame) for result in results)
    assert [name for name, _ in akshare.calls] == [
        "stock_info_a_code_name",
        "tool_trade_date_hist_sina",
        "stock_zh_a_daily",
        "stock_a_lg_indicator",
        "stock_zh_a_daily",
    ]
    assert akshare.calls[2][1] == {"start_date": "20240101", "end_date": "20240131"}
    assert akshare.calls[4][1] == {
        "start_date": "20240101",
        "end_date": "20240131",
        "adjust": "qfq",
    }


def test_client_wraps_provider_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    """Provider exceptions should be logged and wrapped in DataSourceError."""
    class BrokenTushareProApi:
        def stock_basic(self, **kwargs: Any) -> pd.DataFrame:
            raise RuntimeError("provider unavailable")

    client = TushareClient(token="test-token", pro_api=BrokenTushareProApi())

    with caplog.at_level(logging.ERROR), pytest.raises(DataSourceError, match="Tushare call failed"):
        client.get_stock_basic()

    assert "Tushare call failed: stock_basic" in caplog.text


def test_client_rejects_non_dataframe_results() -> None:
    """Provider results must be pandas DataFrames."""
    class InvalidAKShareModule:
        def stock_info_a_code_name(self, **kwargs: Any) -> list[dict[str, str]]:
            return [{"code": "000001"}]

    client = AKShareClient(akshare_module=InvalidAKShareModule())

    with pytest.raises(DataSourceError, match="did not return a DataFrame"):
        client.get_stock_basic()
