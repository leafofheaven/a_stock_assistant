"""AKShare data source adapter."""

from __future__ import annotations

import logging
import json
import subprocess
from typing import Any
from urllib.parse import urlencode

import pandas as pd

from core.data_sources.base import DataSourceError, StockDataSource

logger = logging.getLogger(__name__)


class AKShareClient(StockDataSource):
    """AKShare implementation of the unified stock data source interface."""

    def __init__(
        self,
        akshare_module: Any | None = None,
        adjust: str = "qfq",
        curl_runner: Any | None = None,
    ) -> None:
        """Create an AKShare client.

        Args:
            akshare_module: Optional injected AKShare-like module for tests.
            adjust: Adjustment mode for daily price calls that support it.
            curl_runner: Optional ``subprocess.run`` compatible callable for tests.
        """
        self._akshare = akshare_module
        self.adjust = adjust
        self._curl_runner = curl_runner or subprocess.run

    def get_stock_basic(self) -> pd.DataFrame:
        """Return stock basic information from AKShare."""
        return self._call("stock_info_a_code_name")

    def get_trade_calendar(self) -> pd.DataFrame:
        """Return the trading calendar from AKShare."""
        return self._call("tool_trade_date_hist_sina")

    def get_daily_basic(
        self,
        start_date: str,
        end_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return daily basic indicator data from AKShare.

        AKShare does not provide a stable PE/PB daily-basic endpoint across
        versions. For the fallback path we derive ``turnover_rate`` from
        ``stock_zh_a_hist`` and keep PE/PB fields nullable.
        """
        hist = self._call_market_data("stock_zh_a_hist", start_date, end_date, symbols)
        if hist.empty:
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "turnover_rate",
                    "volume_ratio",
                    "pe",
                    "pb",
                    "ps",
                    "total_mv",
                    "circ_mv",
                ]
            )
        result = hist[["ts_code", "trade_date", "turnover_rate"]].copy()
        for column in ["volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]:
            result[column] = pd.NA
        return result[
            ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]
        ]

    def get_adj_factor(
        self,
        start_date: str,
        end_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return adjustment factor data from AKShare."""
        if symbols:
            rows: list[dict[str, Any]] = []
            for symbol in symbols:
                rows.append({"ts_code": _to_ts_code(symbol), "trade_date": start_date, "adj_factor": 1.0})
            logger.warning("AKShare fallback uses adj_factor=1.0 because no stable factor endpoint is used.")
            return pd.DataFrame(rows)
        logger.warning("AKShare adj_factor requested without symbols; returning empty DataFrame.")
        return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])

    def get_daily_price(
        self,
        start_date: str,
        end_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return daily price data from AKShare for all or selected symbols."""
        return self._call_market_data("stock_zh_a_hist", start_date, end_date, symbols)

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
        except AttributeError:
            logger.warning("AKShare function is unavailable: %s", function_name)
            return pd.DataFrame()
        except Exception as exc:
            logger.exception("AKShare call failed: %s", function_name)
            raise DataSourceError(f"AKShare call failed: {function_name}") from exc

        if not isinstance(result, pd.DataFrame):
            raise DataSourceError(f"AKShare call did not return a DataFrame: {function_name}")

        logger.info("Fetched %s rows from AKShare function %s.", len(result), function_name)
        return _standardize_fields(function_name, result)

    def _call_market_data(
        self,
        function_name: str,
        start_date: str,
        end_date: str,
        symbols: list[str] | None,
    ) -> pd.DataFrame:
        """Call AKShare market data APIs with optional sample symbol limiting."""
        if not symbols:
            logger.warning("AKShare market data requires explicit sample symbols; returning empty DataFrame.")
            return pd.DataFrame()

        frames: list[pd.DataFrame] = []
        for symbol in symbols:
            frame = pd.DataFrame()
            try:
                frame = self._call(
                    function_name,
                    symbol=_normalize_symbol(symbol),
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=self.adjust,
                )
            except DataSourceError as exc:
                logger.warning("AKShare %s failed for %s: %s", function_name, symbol, exc)
            if frame.empty and function_name == "stock_zh_a_hist":
                logger.warning("AKShare %s returned no usable data for %s; trying Eastmoney curl fallback.", function_name, symbol)
                frame = self._call_eastmoney_kline(symbol, start_date, end_date)
            if frame.empty:
                logger.warning("AKShare and Eastmoney curl returned empty data for %s.", symbol)
                continue
            if "ts_code" not in frame.columns or frame["ts_code"].isna().all():
                frame["ts_code"] = _to_ts_code(symbol)
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _call_eastmoney_kline(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch Eastmoney kline data through system curl when requests-based AKShare fails."""
        secid = _to_eastmoney_secid(symbol)
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": _to_eastmoney_adjust(self.adjust),
            "beg": start_date,
            "end": end_date,
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        }
        url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{urlencode(params)}"
        command = [
            "curl",
            "-4",
            "--http1.1",
            "--noproxy",
            "*",
            "-sSL",
            "-A",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "-e",
            "https://quote.eastmoney.com/",
            url,
        ]
        try:
            completed = self._curl_runner(command, capture_output=True, text=True, timeout=30, check=False)
        except Exception as exc:
            logger.warning("Eastmoney curl fallback failed for %s: %s", symbol, exc)
            return pd.DataFrame()

        if getattr(completed, "returncode", 1) != 0:
            stderr = getattr(completed, "stderr", "")
            logger.warning("Eastmoney curl fallback returned non-zero status for %s: %s", symbol, stderr)
            return pd.DataFrame()

        try:
            payload = json.loads(getattr(completed, "stdout", "") or "{}")
        except json.JSONDecodeError as exc:
            logger.warning("Eastmoney curl fallback returned invalid JSON for %s: %s", symbol, exc)
            return pd.DataFrame()

        klines = (payload.get("data") or {}).get("klines") or []
        if not klines:
            logger.warning("Eastmoney curl fallback returned no klines for %s.", symbol)
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        for line in klines:
            parts = str(line).split(",")
            if len(parts) < 11:
                logger.warning("Skipping malformed Eastmoney kline for %s: %s", symbol, line)
                continue
            rows.append(
                {
                    "ts_code": _to_ts_code(symbol),
                    "trade_date": parts[0].replace("-", ""),
                    "open": _to_number(parts[1]),
                    "close": _to_number(parts[2]),
                    "high": _to_number(parts[3]),
                    "low": _to_number(parts[4]),
                    "vol": _to_number(parts[5]),
                    "amount": _to_number(parts[6]),
                    "pct_chg": _to_number(parts[8]),
                    "change": _to_number(parts[9]),
                    "turnover_rate": _to_number(parts[10]),
                    "pre_close": pd.NA,
                }
            )
        return pd.DataFrame(
            rows,
            columns=[
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "change",
                "pct_chg",
                "vol",
                "amount",
                "turnover_rate",
            ],
        )


def _standardize_fields(function_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with columns aligned to project DuckDB table names."""
    if df.empty:
        return df.copy()

    result = df.copy()
    if function_name == "stock_info_a_code_name":
        result = result.rename(columns={"code": "symbol"})
        if "ts_code" not in result.columns and "symbol" in result.columns:
            result["ts_code"] = result["symbol"].map(_to_ts_code)
        for column in ["area", "industry", "market", "list_date", "delist_date", "is_hs"]:
            if column not in result.columns:
                result[column] = pd.NA
        return result[
            ["ts_code", "symbol", "name", "area", "industry", "market", "list_date", "delist_date", "is_hs"]
        ]

    if function_name == "tool_trade_date_hist_sina":
        result = result.rename(columns={"trade_date": "cal_date", "date": "cal_date"})
        if "cal_date" in result.columns:
            result["cal_date"] = result["cal_date"].astype(str).str.replace("-", "", regex=False)
        result["exchange"] = "SSE"
        result["is_open"] = 1
        if "pretrade_date" not in result.columns:
            result["pretrade_date"] = pd.NA
        return result[["exchange", "cal_date", "is_open", "pretrade_date"]]

    if function_name in {"stock_zh_a_daily", "stock_zh_a_hist"}:
        result = result.rename(
            columns={
                "date": "trade_date",
                "日期": "trade_date",
                "open": "open",
                "开盘": "open",
                "close": "close",
                "收盘": "close",
                "high": "high",
                "最高": "high",
                "low": "low",
                "最低": "low",
                "volume": "vol",
                "成交量": "vol",
                "amount": "amount",
                "成交额": "amount",
                "pct_chg": "pct_chg",
                "涨跌幅": "pct_chg",
                "change": "change",
                "涨跌额": "change",
                "turnover_rate": "turnover_rate",
                "换手率": "turnover_rate",
            }
        )
        if "trade_date" in result.columns:
            result["trade_date"] = result["trade_date"].astype(str).str.replace("-", "", regex=False)
        for column in [
            "ts_code",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
            "turnover_rate",
        ]:
            if column not in result.columns:
                result[column] = pd.NA
        return result[
            [
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "change",
                "pct_chg",
                "vol",
                "amount",
                "turnover_rate",
            ]
        ]

    if function_name == "stock_a_lg_indicator":
        result = result.rename(columns={"date": "trade_date", "code": "symbol"})
        if "ts_code" not in result.columns and "symbol" in result.columns:
            result["ts_code"] = result["symbol"].map(_to_ts_code)
        if "trade_date" in result.columns:
            result["trade_date"] = result["trade_date"].astype(str).str.replace("-", "", regex=False)
        for column in ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]:
            if column not in result.columns:
                result[column] = pd.NA
        return result[
            ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]
        ]

    return result


def _normalize_symbol(symbol: str) -> str:
    """Return six-digit AKShare symbol from either ts_code or raw symbol."""
    return symbol.split(".")[0]


def _to_ts_code(symbol: str) -> str:
    """Infer project ts_code suffix from a six-digit A-share symbol."""
    clean = _normalize_symbol(str(symbol))
    suffix = "SH" if clean.startswith("6") else "SZ"
    return f"{clean}.{suffix}"


def _to_eastmoney_secid(symbol: str) -> str:
    """Return Eastmoney secid for an A-share symbol."""
    clean = _normalize_symbol(str(symbol))
    market = "1" if clean.startswith("6") else "0"
    return f"{market}.{clean}"


def _to_eastmoney_adjust(adjust: str) -> str:
    """Map AKShare adjustment names to Eastmoney fqt values."""
    return {"qfq": "1", "hfq": "2"}.get(adjust, "0")


def _to_number(value: Any) -> float | None:
    """Convert provider numeric text to float while preserving missing values."""
    if value in {"", "-", None}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
