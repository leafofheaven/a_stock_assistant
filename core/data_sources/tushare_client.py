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

    def get_daily_price(
        self,
        start_date: str,
        end_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return daily price data from Tushare for all or selected symbols."""
        return self._call_market_data("daily", start_date, end_date, symbols)

    def get_daily_basic(
        self,
        start_date: str,
        end_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return daily basic indicator data from Tushare for all or selected symbols."""
        return self._call_market_data("daily_basic", start_date, end_date, symbols)

    def get_adj_factor(
        self,
        start_date: str,
        end_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return adjustment factor data from Tushare for all or selected symbols."""
        return self._call_market_data("adj_factor", start_date, end_date, symbols)

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
        return _standardize_fields(method_name, result)

    def _call_market_data(
        self,
        method_name: str,
        start_date: str,
        end_date: str,
        symbols: list[str] | None,
    ) -> pd.DataFrame:
        """Call date-range market data APIs, optionally limited to selected symbols."""
        if not symbols:
            return self._call(method_name, start_date=start_date, end_date=end_date)

        frames: list[pd.DataFrame] = []
        for symbol in symbols:
            frames.append(
                self._call(
                    method_name,
                    ts_code=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _standardize_fields(method_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with columns aligned to project DuckDB table names."""
    if df.empty:
        return df.copy()

    column_map = {
        "trade_cal": {
            "exchange": "exchange",
            "cal_date": "cal_date",
            "is_open": "is_open",
            "pretrade_date": "pretrade_date",
        },
        "daily": {
            "ts_code": "ts_code",
            "trade_date": "trade_date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "pre_close": "pre_close",
            "change": "change",
            "pct_chg": "pct_chg",
            "vol": "vol",
            "amount": "amount",
        },
        "daily_basic": {
            "ts_code": "ts_code",
            "trade_date": "trade_date",
            "turnover_rate": "turnover_rate",
            "volume_ratio": "volume_ratio",
            "pe": "pe",
            "pb": "pb",
            "ps": "ps",
            "total_mv": "total_mv",
            "circ_mv": "circ_mv",
        },
        "adj_factor": {
            "ts_code": "ts_code",
            "trade_date": "trade_date",
            "adj_factor": "adj_factor",
        },
        "stock_basic": {
            "ts_code": "ts_code",
            "symbol": "symbol",
            "name": "name",
            "area": "area",
            "industry": "industry",
            "market": "market",
            "list_date": "list_date",
            "delist_date": "delist_date",
            "is_hs": "is_hs",
        },
    }
    mapping = column_map.get(method_name)
    if not mapping:
        return df.copy()

    result = df.rename(columns=mapping).copy()
    for source_column in mapping.values():
        if source_column not in result.columns:
            result[source_column] = pd.NA
    return result[list(mapping.values())]
