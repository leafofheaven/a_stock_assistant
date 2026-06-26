"""AKShare data source adapter."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from core.data_sources.base import DataSourceError, StockDataSource

logger = logging.getLogger(__name__)


class AKShareClient(StockDataSource):
    """AKShare implementation of the unified stock data source interface."""

    def __init__(self, akshare_module: Any | None = None) -> None:
        """Create an AKShare client.

        Args:
            akshare_module: Optional injected AKShare-like module for tests.
        """
        self._akshare = akshare_module

    def get_stock_basic(self) -> pd.DataFrame:
        """Return stock basic information from AKShare."""
        return self._call("stock_info_a_code_name")

    def get_trade_calendar(self) -> pd.DataFrame:
        """Return the trading calendar from AKShare."""
        return self._call("tool_trade_date_hist_sina")

    def get_daily_price(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return daily price data from AKShare."""
        return self._call("stock_zh_a_daily", start_date=start_date, end_date=end_date)

    def get_daily_basic(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return daily basic indicator data from AKShare."""
        return self._call("stock_a_lg_indicator", start_date=start_date, end_date=end_date)

    def get_adj_factor(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return adjustment factor data from AKShare."""
        return self._call("stock_zh_a_daily", start_date=start_date, end_date=end_date, adjust="qfq")

    def _module(self) -> Any:
        """Return the underlying AKShare module."""
        if self._akshare is not None:
            return self._akshare

        try:
            import akshare as ak
        except ImportError as exc:
            raise DataSourceError("AKShare is not installed.") from exc

        self._akshare = ak
        return self._akshare

    def _call(self, function_name: str, **kwargs: Any) -> pd.DataFrame:
        """Call an AKShare function and validate that it returns a DataFrame."""
        try:
            function = getattr(self._module(), function_name)
            result = function(**kwargs)
        except DataSourceError:
            raise
        except Exception as exc:
            logger.exception("AKShare call failed: %s", function_name)
            raise DataSourceError(f"AKShare call failed: {function_name}") from exc

        if not isinstance(result, pd.DataFrame):
            raise DataSourceError(f"AKShare call did not return a DataFrame: {function_name}")

        logger.info("Fetched %s rows from AKShare function %s.", len(result), function_name)
        return result
