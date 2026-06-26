"""Tushare data source adapter."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.config import get_settings
from core.data_sources.base import DataSourceError, StockDataSource

logger = logging.getLogger(__name__)


class TushareClient(StockDataSource):
    """Tushare implementation of the unified stock data source interface."""

    def __init__(self, token: str | None = None, pro_api: Any | None = None) -> None:
        """Create a Tushare client.

        Args:
            token: Optional Tushare token. When omitted, it is read from settings.
            pro_api: Optional injected Tushare pro API object for tests.
        """
        self.token = get_settings().tushare_token if token is None else token
        self._pro_api = pro_api

    def get_stock_basic(self) -> pd.DataFrame:
        """Return stock basic information from Tushare."""
        return self._call(
            "stock_basic",
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date,delist_date,is_hs",
        )

    def get_trade_calendar(self) -> pd.DataFrame:
        """Return the trading calendar from Tushare."""
        return self._call(
            "trade_cal",
            exchange="SSE",
            fields="exchange,cal_date,is_open,pretrade_date",
        )

    def get_daily_price(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return daily price data from Tushare."""
        return self._call("daily", start_date=start_date, end_date=end_date)

    def get_daily_basic(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return daily basic indicator data from Tushare."""
        return self._call("daily_basic", start_date=start_date, end_date=end_date)

    def get_adj_factor(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return adjustment factor data from Tushare."""
        return self._call("adj_factor", start_date=start_date, end_date=end_date)

    def _client(self) -> Any:
        """Return the underlying Tushare pro API client."""
        if self._pro_api is not None:
            return self._pro_api

        if not self.token:
            raise DataSourceError("Tushare token is required to create a Tushare client.")

        try:
            import tushare as ts
        except ImportError as exc:
            raise DataSourceError("Tushare is not installed.") from exc

        try:
            ts.set_token(self.token)
            self._pro_api = ts.pro_api()
        except Exception as exc:
            logger.exception("Failed to initialize Tushare client.")
            raise DataSourceError("Failed to initialize Tushare client.") from exc

        return self._pro_api

    def _call(self, method_name: str, **kwargs: Any) -> pd.DataFrame:
        """Call a Tushare method and validate that it returns a DataFrame."""
        try:
            method = getattr(self._client(), method_name)
            result = method(**kwargs)
        except DataSourceError:
            raise
        except Exception as exc:
            logger.exception("Tushare call failed: %s", method_name)
            raise DataSourceError(f"Tushare call failed: {method_name}") from exc

        if not isinstance(result, pd.DataFrame):
            raise DataSourceError(f"Tushare call did not return a DataFrame: {method_name}")

        logger.info("Fetched %s rows from Tushare method %s.", len(result), method_name)
        return result
