"""AKShare data source adapter."""

from __future__ import annotations

import logging
import json
import subprocess
from typing import Any
from urllib.parse import urlencode

import pandas as pd

from core.data_sources.base import DataSourceError, StockDataSource
from core.data_sources.real_universe import exchange_from_symbol
from core.data_sources.valuation_enrichment import ValuationEnricher, merge_latest_valuation

logger = logging.getLogger(__name__)


class AKShareClient(StockDataSource):
    """AKShare implementation of the unified stock data source interface."""

    def __init__(
        self,
        akshare_module: Any | None = None,
        adjust: str = "qfq",
        curl_runner: Any | None = None,
        request_timeout_seconds: int = 30,
        enable_basic_enrichment: bool = True,
        enable_valuation_enrichment: bool = True,
    ) -> None:
        """Create an AKShare client.

        Args:
            akshare_module: Optional injected AKShare-like module for tests.
            adjust: Adjustment mode for daily price calls that support it.
            curl_runner: Optional ``subprocess.run`` compatible callable for tests.
            request_timeout_seconds: Timeout for the system curl fallback.
            enable_basic_enrichment: Whether to try optional basic-info enrichment.
            enable_valuation_enrichment: Whether to try optional valuation enrichment.
        """
        self._akshare = akshare_module
        self.adjust = adjust
        self._curl_runner = curl_runner or subprocess.run
        self.request_timeout_seconds = request_timeout_seconds
        self.enable_basic_enrichment = enable_basic_enrichment
        self.enable_valuation_enrichment = enable_valuation_enrichment
        self.failure_records: list[dict[str, str]] = []
        self.enrichment_records: list[dict[str, str]] = []
        self._logged_enrichment_warnings: set[tuple[str, str]] = set()

    def get_stock_basic(self) -> pd.DataFrame:
        """Return stock basic information from AKShare."""
        return self._call("stock_info_a_code_name")

    def get_full_a_share_basic_excluding_bse(self) -> pd.DataFrame:
        """Return HS A-share basic rows without AKShare BSE stock-info calls."""
        frame, error_message = self._fetch_eastmoney_hs_basic_list()
        if error_message:
            raise DataSourceError(error_message)
        return frame

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
        if self.enable_valuation_enrichment and symbols:
            result = self._merge_valuation_enrichment(result, symbols, start_date, end_date)
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

    def enrich_stock_basic(self, stock_basic: pd.DataFrame, symbols: list[str] | None = None) -> pd.DataFrame:
        """Fill optional stock_basic fields from AKShare when stable endpoints are available.

        The enrichment is best-effort. If an AKShare endpoint is unavailable or
        fails for one symbol, that symbol keeps the original basic information
        and the failure is recorded for diagnostics.
        """
        if not self.enable_basic_enrichment or stock_basic.empty:
            return stock_basic
        result = stock_basic.copy()
        if "ts_code" not in result.columns:
            return result
        symbol_list = symbols or result["ts_code"].dropna().astype(str).tolist()
        for symbol in symbol_list:
            ts_code = _to_ts_code(symbol)
            info, error_message = self._call_optional_raw("stock_individual_info_em", symbol=_normalize_symbol(symbol))
            if error_message:
                message = _sanitize_basic_enrichment_error(error_message)
                self._record_enrichment(ts_code, "stock_basic_enrichment", message)
                self._log_enrichment_warning_once("stock_basic_enrichment", message)
                continue
            try:
                values = _parse_individual_info(info)
            except Exception as exc:
                message = _sanitize_basic_enrichment_error(f"{type(exc).__name__}: {exc}")
                self._record_enrichment(ts_code, "stock_basic_enrichment", message)
                self._log_enrichment_warning_once("stock_basic_enrichment", message)
                continue
            if not values or not any(_not_missing_value(values.get(column)) for column in ["area", "industry", "market", "list_date", "delist_date", "is_hs"]):
                message = "某股票基础信息补全字段缺失，已跳过增强字段并保留 stock_basic 原有字段。"
                self._record_enrichment(ts_code, "stock_basic_enrichment", message)
                self._log_enrichment_warning_once("stock_basic_enrichment", message)
                continue
            mask = result["ts_code"].astype(str) == ts_code
            if not mask.any():
                continue
            for column in ["area", "industry", "market", "list_date", "delist_date", "is_hs"]:
                value = values.get(column)
                if _not_missing_value(value):
                    result.loc[mask, column] = value
            if (result.loc[mask, "market"].isna() | (result.loc[mask, "market"].astype(str).str.strip() == "")).any():
                result.loc[mask, "market"] = _market_from_ts_code(ts_code)
        return result

    def enrich_daily_basic_valuation(self, daily_basic: pd.DataFrame, symbols: list[str] | None = None) -> pd.DataFrame:
        """Fill PE/PB and market-cap fields on local daily_basic rows when possible."""
        if not self.enable_valuation_enrichment or daily_basic.empty:
            return daily_basic
        if symbols is None:
            symbols = daily_basic.get("ts_code", pd.Series(dtype="object")).dropna().astype(str).unique().tolist()
        if not symbols:
            return daily_basic
        start_date = str(daily_basic["trade_date"].dropna().astype(str).min()) if "trade_date" in daily_basic.columns else ""
        end_date = str(daily_basic["trade_date"].dropna().astype(str).max()) if "trade_date" in daily_basic.columns else ""
        return self._merge_valuation_enrichment(daily_basic, symbols, start_date, end_date)

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
        result = self._call_raw(function_name, **kwargs)
        logger.info("Fetched %s rows from AKShare function %s.", len(result), function_name)
        return _standardize_fields(function_name, result)

    def _call_raw(self, function_name: str, **kwargs: Any) -> pd.DataFrame:
        """Call an AKShare function and return the raw DataFrame."""
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

        return result

    def _call_optional_raw(self, function_name: str, **kwargs: Any) -> tuple[pd.DataFrame, str]:
        """Call an optional AKShare enrichment function without noisy tracebacks."""
        try:
            function = getattr(self._module(), function_name)
        except DataSourceError as exc:
            return pd.DataFrame(), str(exc)
        except AttributeError:
            return pd.DataFrame(), f"AKShare function is unavailable: {function_name}"
        try:
            result = function(**kwargs)
        except _optional_network_errors() as exc:
            return pd.DataFrame(), f"{type(exc).__name__}: {exc}"
        except (KeyError, ValueError) as exc:
            return pd.DataFrame(), f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            return pd.DataFrame(), f"{type(exc).__name__}: {exc}"
        if not isinstance(result, pd.DataFrame):
            return pd.DataFrame(), f"AKShare call did not return a DataFrame: {function_name}"
        return result, ""

    def _merge_valuation_enrichment(
        self,
        daily_basic: pd.DataFrame,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Merge optional PE/PB and market-cap data into derived daily_basic rows."""
        if daily_basic.empty:
            return daily_basic
        has_lg_indicator = hasattr(self._module(), "stock_a_lg_indicator")
        if not has_lg_indicator:
            self._record_enrichment(
                "ALL",
                "daily_basic_valuation_enrichment_unavailable",
                "AKShare function is unavailable: stock_a_lg_indicator",
            )
            logger.warning("AKShare stock_a_lg_indicator unavailable; trying valuation snapshot fallback.")
        frames: list[pd.DataFrame] = []
        if has_lg_indicator:
            for symbol in symbols:
                ts_code = _to_ts_code(symbol)
                raw_frame, error_message = self._call_optional_raw("stock_a_lg_indicator", symbol=_normalize_symbol(symbol))
                if error_message:
                    self._record_enrichment(ts_code, "daily_basic_valuation_enrichment", error_message)
                    logger.warning("AKShare valuation enrichment failed for %s: %s", symbol, error_message)
                    continue
                raw = _standardize_fields("stock_a_lg_indicator", raw_frame)
                if raw.empty:
                    self._record_enrichment(ts_code, "daily_basic_valuation_enrichment", "stock_a_lg_indicator returned empty data")
                    continue
                if "trade_date" in raw.columns:
                    raw = raw[
                        (raw["trade_date"].astype(str) >= start_date)
                        & (raw["trade_date"].astype(str) <= end_date)
                    ].copy()
                else:
                    raw["trade_date"] = end_date
                raw["ts_code"] = ts_code
                frames.append(raw)
        if not frames:
            snapshot, warnings = ValuationEnricher(
                akshare_module=self._module(),
                curl_runner=self._curl_runner,
                request_timeout_seconds=self.request_timeout_seconds,
            ).fetch_latest_valuation(symbols)
            for warning in warnings:
                self._record_enrichment(
                    warning["symbol"],
                    warning["failed_stage"],
                    warning["error_message"],
                )
            if snapshot.empty:
                return daily_basic
            covered = set(snapshot["ts_code"].dropna().astype(str))
            for symbol in symbols:
                ts_code = _to_ts_code(symbol)
                if ts_code not in covered:
                    self._record_enrichment(ts_code, "daily_basic_valuation_enrichment_missing", "No PE/PB valuation snapshot available")
            enriched = merge_latest_valuation(daily_basic, snapshot)
            return enriched
        valuation = pd.concat(frames, ignore_index=True)
        merge_columns = ["ts_code", "trade_date", "pe", "pb", "ps", "total_mv", "circ_mv", "volume_ratio"]
        for column in merge_columns:
            if column not in valuation.columns:
                valuation[column] = pd.NA
        merged = daily_basic.merge(
            valuation[merge_columns],
            on=["ts_code", "trade_date"],
            how="left",
            suffixes=("", "_enriched"),
        )
        for column in ["pe", "pb", "ps", "total_mv", "circ_mv", "volume_ratio"]:
            enriched = f"{column}_enriched"
            if enriched in merged.columns:
                merged[column] = merged[column].where(merged[column].map(_not_missing_value), merged[enriched])
                merged = merged.drop(columns=[enriched])
        return merged

    def _record_failure(self, symbol: str, stage: str, message: str) -> None:
        """Record one symbol-level failure for batch diagnostics."""
        self.failure_records.append(
            {
                "symbol": _to_ts_code(symbol),
                "provider": "akshare",
                "failed_stage": stage,
                "error_message": message,
            }
        )

    def _record_enrichment(self, symbol: str, stage: str, message: str) -> None:
        """Record optional enrichment warnings separately from main data failures."""
        self.enrichment_records.append(
            {
                "symbol": _to_ts_code(symbol) if symbol != "ALL" else "ALL",
                "provider": "akshare",
                "failed_stage": stage,
                "error_message": message,
            }
        )

    def _log_enrichment_warning_once(self, stage: str, message: str) -> None:
        """Log repeated optional enrichment warnings once to avoid console noise."""
        key = (stage, message)
        if key in self._logged_enrichment_warnings:
            logger.info("AKShare optional enrichment warning repeated for %s: %s", stage, message)
            return
        self._logged_enrichment_warnings.add(key)
        logger.warning("AKShare optional enrichment warning for %s: %s", stage, message)

    def _fetch_eastmoney_hs_basic_list(self) -> tuple[pd.DataFrame, str]:
        """Fetch a compact Shanghai/Shenzhen A-share list via system curl."""
        page_size = 100
        rows: list[dict[str, Any]] = []
        for page in range(1, 100):
            params = {
                "pn": str(page),
                "pz": str(page_size),
                "po": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12,f14",
            }
            url = f"https://push2.eastmoney.com/api/qt/clist/get?{urlencode(params)}"
            command = [
                "curl",
                "-4",
                "--http1.1",
                "--noproxy",
                "*",
                "-sSL",
                "--max-time",
                str(max(1, int(self.request_timeout_seconds))),
                "-A",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "-e",
                "https://quote.eastmoney.com/",
                url,
            ]
            try:
                completed = self._curl_runner(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.request_timeout_seconds + 5,
                )
            except subprocess.TimeoutExpired as exc:
                return pd.DataFrame(), f"Eastmoney HS stock list timeout: {exc}"
            except Exception as exc:
                return pd.DataFrame(), f"Eastmoney HS stock list failed: {type(exc).__name__}: {exc}"
            if getattr(completed, "returncode", 1) != 0:
                stderr = str(getattr(completed, "stderr", "") or "").strip()
                return pd.DataFrame(), f"Eastmoney HS stock list curl failed: {stderr}"
            try:
                payload = json.loads(getattr(completed, "stdout", "") or "{}")
            except json.JSONDecodeError as exc:
                return pd.DataFrame(), f"Eastmoney HS stock list JSONDecodeError: {exc}"
            page_rows = ((payload.get("data") or {}).get("diff") or [])
            if not page_rows:
                break
            rows.extend(page_rows)
            if len(page_rows) < page_size:
                break
        if not rows:
            return pd.DataFrame(), "Eastmoney HS stock list returned empty data"
        parsed = []
        for item in rows:
            symbol = str(item.get("f12") or "").strip()
            if not symbol:
                continue
            ts_code = _to_ts_code(symbol)
            parsed.append(
                {
                    "symbol": symbol,
                    "ts_code": ts_code,
                    "name": str(item.get("f14") or "").strip(),
                    "market": _market_from_ts_code(ts_code),
                    "exchange": exchange_from_symbol(symbol),
                    "list_date": pd.NA,
                }
            )
        result = pd.DataFrame(parsed)
        if not result.empty and "ts_code" in result.columns:
            result = result.drop_duplicates("ts_code", keep="last").reset_index(drop=True)
        return result, ""

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
            error_message = ""
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
                error_message = str(exc)
                logger.warning("AKShare %s failed for %s: %s", function_name, symbol, exc)
            if frame.empty and function_name == "stock_zh_a_hist":
                logger.warning("AKShare %s returned no usable data for %s; trying Eastmoney curl fallback.", function_name, symbol)
                frame = self._call_eastmoney_kline(symbol, start_date, end_date)
            if frame.empty:
                self.failure_records.append(
                    {
                        "symbol": _to_ts_code(symbol),
                        "provider": "akshare",
                        "failed_stage": function_name,
                        "error_message": error_message or "empty data after AKShare and Eastmoney curl fallback",
                    }
                )
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
            completed = self._curl_runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.request_timeout_seconds,
                check=False,
            )
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
        for column in ["area", "industry", "market", "exchange", "list_date", "delist_date", "is_hs"]:
            if column not in result.columns:
                result[column] = pd.NA
        result["market"] = result["market"].combine_first(result["ts_code"].map(_market_from_ts_code))
        result["exchange"] = result["exchange"].where(result["exchange"].map(_not_missing_value), result["symbol"].map(exchange_from_symbol))
        return result[
            ["ts_code", "symbol", "name", "area", "industry", "market", "exchange", "list_date", "delist_date", "is_hs"]
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
        result = result.rename(
            columns={
                "date": "trade_date",
                "日期": "trade_date",
                "code": "symbol",
                "股票代码": "symbol",
                "pe": "pe",
                "市盈率": "pe",
                "pb": "pb",
                "市净率": "pb",
                "ps": "ps",
                "市销率": "ps",
                "total_mv": "total_mv",
                "总市值": "total_mv",
                "circ_mv": "circ_mv",
                "流通市值": "circ_mv",
                "volume_ratio": "volume_ratio",
                "量比": "volume_ratio",
            }
        )
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


def _market_from_ts_code(ts_code: str) -> str:
    """Return a compact market label inferred from ts_code."""
    code = str(ts_code)
    return "上交所" if code.endswith(".SH") else "深交所"


def _optional_network_errors() -> tuple[type[BaseException], ...]:
    """Return optional network exception classes without requiring requests."""
    try:
        from requests.exceptions import RequestException, Timeout

        return (Timeout, RequestException)
    except Exception:
        return ()


def _parse_individual_info(df: pd.DataFrame) -> dict[str, Any]:
    """Parse AKShare stock_individual_info_em rows into stock_basic fields."""
    normalized = normalize_basic_enrichment_frame(df)
    if normalized.empty:
        return {}
    raw = {
        str(row.get("item", "")).strip(): row.get("value")
        for row in normalized.to_dict("records")
    }
    industry = _first_value(raw, ["行业", "所属行业", "行业分类"])
    area = _first_value(raw, ["地区", "地域", "省份"])
    market = _first_value(raw, ["市场", "交易所", "上市地点"])
    list_date = _clean_date(_first_value(raw, ["上市时间", "上市日期", "上市日"]))
    return {
        "area": area,
        "industry": industry,
        "market": market,
        "list_date": list_date,
        "delist_date": _clean_date(_first_value(raw, ["退市日期", "摘牌日期"])),
        "is_hs": _first_value(raw, ["是否沪深港通", "沪深港通"]),
    }


def normalize_basic_enrichment_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize AKShare individual-info frames to item/value/extra columns.

    AKShare ``stock_individual_info_em`` has changed shapes across versions.
    This helper never assigns a fixed number of column names to the raw frame.
    Instead it inspects the existing columns and returns a standard structure
    with ``item`` and ``value`` columns, plus optional ``extra`` and
    ``source_columns`` for diagnostics.
    """
    standard_columns = ["item", "value", "extra", "source_columns"]
    if df.empty:
        return pd.DataFrame(columns=standard_columns)
    raw = df.copy()
    source_columns = [str(column).strip() for column in raw.columns]
    raw.columns = source_columns
    item_col = _first_existing(raw, ["item", "项目", "指标", "字段", "名称", "name"])
    value_col = _first_existing(raw, ["value", "值", "数值", "内容", "结果"])
    if item_col == value_col:
        value_col = None
    extra_col = _first_existing(raw, ["extra", "备注", "单位", "说明"])
    if not item_col or not value_col:
        inferred_item, inferred_value, inferred_extra = _infer_basic_enrichment_columns(raw)
        item_col = item_col or inferred_item
        value_col = value_col or inferred_value
        extra_col = extra_col or inferred_extra
    if not item_col or not value_col:
        return pd.DataFrame(columns=standard_columns)
    result = pd.DataFrame(
        {
            "item": raw[item_col],
            "value": raw[value_col],
            "extra": raw[extra_col] if extra_col and extra_col in raw.columns else pd.NA,
            "source_columns": [",".join(source_columns)] * len(raw),
        }
    )
    result["item"] = result["item"].astype(str).str.strip()
    result = result[result["item"] != ""].reset_index(drop=True)
    return result[standard_columns]


def _sanitize_basic_enrichment_error(message: str) -> str:
    """Return a user-facing optional basic-info enrichment warning."""
    text = str(message or "")
    if "Length mismatch" in text or "Expected axis" in text:
        return "AKShare 基础增强字段缺失，已使用基础股票信息兜底。"
    if "unavailable" in text or "not return a DataFrame" in text:
        return "AKShare 基础信息增强接口不可用，已使用基础股票信息兜底。"
    return "AKShare 基础信息增强失败，已使用基础股票信息兜底。"


def _infer_basic_enrichment_columns(df: pd.DataFrame) -> tuple[str | None, str | None, str | None]:
    """Infer item/value/extra columns from AKShare individual-info frames."""
    if len(df.columns) < 2:
        return None, None, None
    columns = [str(column) for column in df.columns]
    known_items = {"行业", "所属行业", "行业分类", "地区", "地域", "省份", "市场", "交易所", "上市时间", "上市日期", "上市日"}
    best_pair: tuple[str, str] | None = None
    best_score = -1
    for item_col in columns:
        item_values = set(df[item_col].dropna().astype(str).str.strip())
        score = len(item_values.intersection(known_items))
        for value_col in columns:
            if item_col == value_col:
                continue
            if score > best_score:
                best_pair = (item_col, value_col)
                best_score = score
    if best_pair and best_score > 0:
        extra = next((column for column in columns if column not in best_pair), None)
        return best_pair[0], best_pair[1], extra
    extra = columns[2] if len(columns) >= 3 else None
    return columns[0], columns[1], extra


def _first_existing(df: pd.DataFrame, columns: list[str]) -> str | None:
    """Return the first existing column name."""
    for column in columns:
        if column in df.columns:
            return column
    return None


def _first_value(mapping: dict[str, Any], keys: list[str]) -> Any:
    """Return the first non-empty value for candidate keys."""
    for key in keys:
        value = mapping.get(key)
        if _not_missing_value(value):
            return value
    return pd.NA


def _clean_date(value: Any) -> Any:
    """Normalize provider dates to YYYYMMDD strings when possible."""
    if not _not_missing_value(value):
        return pd.NA
    text = str(value).strip()
    if not text:
        return pd.NA
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else text


def _not_missing_value(value: Any) -> bool:
    """Return whether a provider value should be treated as present."""
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip() != ""


def _to_number(value: Any) -> float | None:
    """Convert provider numeric text to float while preserving missing values."""
    if value in {"", "-", None}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
