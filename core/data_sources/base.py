"""Common data source interfaces and errors."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataSourceError(RuntimeError):
    """Raised when a data source call fails or returns an invalid result."""


class StockDataSource(ABC):
    """Unified interface for A-share market data providers."""

    @abstractmethod
    def get_stock_basic(self) -> pd.DataFrame:
        """Return A-share stock basic information."""

    @abstractmethod
    def get_trade_calendar(self) -> pd.DataFrame:
        """Return exchange trading calendar data."""

    @abstractmethod
    def get_daily_price(
        self,
        start_date: str,
        end_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return daily price data for the given date range."""

    @abstractmethod
    def get_daily_basic(
        self,
        start_date: str,
        end_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return daily valuation and trading indicator data."""

    @abstractmethod
    def get_adj_factor(
        self,
        start_date: str,
        end_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return adjustment factor data for the given date range."""
