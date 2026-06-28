"""Best-effort valuation enrichment adapters for local real-data trials."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any
from urllib.parse import urlencode

import pandas as pd

logger = logging.getLogger(__name__)

VALUATION_COLUMNS = ["ts_code", "pe", "pb", "total_mv", "circ_mv", "volume_ratio", "valuation_source"]


class ValuationEnricher:
    """Fetch PE/PB style valuation snapshots without affecting market data updates."""

    def __init__(
        self,
        akshare_module: Any | None = None,
        curl_runner: Any | None = None,
        request_timeout_seconds: int = 30,
    ) -> None:
        """Create a best-effort valuation enricher."""
        self._akshare = akshare_module
        self._curl_runner = curl_runner or subprocess.run
        self.request_timeout_seconds = request_timeout_seconds

    def fetch_latest_valuation(self, symbols: list[str]) -> tuple[pd.DataFrame, list[dict[str, str]]]:
        """Return latest valuation rows and compact warnings for configured symbols."""
        requested = [_to_ts_code(symbol) for symbol in symbols]
        warnings: list[dict[str, str]] = []
        akshare_frame, akshare_warnings = self._fetch_akshare_snapshot(requested)
        warnings.extend(akshare_warnings)
        if _covers_any_requested(akshare_frame, requested):
            return _filter_requested(akshare_frame, requested), warnings

        eastmoney_frame, eastmoney_warnings = self._fetch_eastmoney_quote(requested)
        warnings.extend(eastmoney_warnings)
        return _filter_requested(eastmoney_frame, requested), warnings

    def _module(self) -> Any:
        if self._akshare is not None:
            return self._akshare
        import akshare as ak

        self._akshare = ak
        return self._akshare

    def _fetch_akshare_snapshot(self, requested: list[str]) -> tuple[pd.DataFrame, list[dict[str, str]]]:
        warnings: list[dict[str, str]] = []
        try:
            module = self._module()
        except Exception as exc:
            return pd.DataFrame(columns=VALUATION_COLUMNS), [_warning("ALL", "akshare_valuation_snapshot", str(exc))]

        for function_name in ["stock_zh_a_spot_em", "stock_zh_a_spot"]:
            function = getattr(module, function_name, None)
            if function is None:
                warnings.append(_warning("ALL", "akshare_valuation_snapshot_unavailable", f"AKShare function is unavailable: {function_name}"))
                continue
            try:
                raw = function()
            except Exception as exc:
                warnings.append(_warning("ALL", "akshare_valuation_snapshot", f"{type(exc).__name__}: {exc}"))
                logger.warning("AKShare valuation snapshot failed: %s", exc)
                continue
            if not isinstance(raw, pd.DataFrame) or raw.empty:
                warnings.append(_warning("ALL", "akshare_valuation_snapshot", f"{function_name} returned empty data"))
                continue
            parsed = parse_akshare_snapshot(raw)
            parsed["valuation_source"] = function_name
            filtered = _filter_requested(parsed, requested)
            if not filtered.empty:
                return filtered, warnings
        return pd.DataFrame(columns=VALUATION_COLUMNS), warnings

    def _fetch_eastmoney_quote(self, requested: list[str]) -> tuple[pd.DataFrame, list[dict[str, str]]]:
        if not requested:
            return pd.DataFrame(columns=VALUATION_COLUMNS), []
        params = {
            "fltt": "2",
            "invt": "2",
            "np": "1",
            "secids": ",".join(_to_eastmoney_secid(symbol) for symbol in requested),
            "fields": "f12,f9,f23,f20,f21,f10",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        }
        url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?{urlencode(params)}"
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
            return pd.DataFrame(columns=VALUATION_COLUMNS), [_warning("ALL", "eastmoney_valuation_curl", f"{type(exc).__name__}: {exc}")]
        if getattr(completed, "returncode", 1) != 0:
            return pd.DataFrame(columns=VALUATION_COLUMNS), [_warning("ALL", "eastmoney_valuation_curl", str(getattr(completed, "stderr", "")))]
        try:
            payload = json.loads(getattr(completed, "stdout", "") or "{}")
        except json.JSONDecodeError as exc:
            return pd.DataFrame(columns=VALUATION_COLUMNS), [_warning("ALL", "eastmoney_valuation_curl", f"JSONDecodeError: {exc}")]
        rows = (payload.get("data") or {}).get("diff") or []
        if not rows:
            return pd.DataFrame(columns=VALUATION_COLUMNS), [_warning("ALL", "eastmoney_valuation_curl", "Eastmoney quote returned empty data")]
        parsed = parse_eastmoney_quote(rows)
        return _filter_requested(parsed, requested), []


def parse_akshare_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """Map AKShare spot snapshot columns to internal valuation fields."""
    if df.empty:
        return pd.DataFrame(columns=VALUATION_COLUMNS)
    result = pd.DataFrame()
    code_col = _first_existing(df, ["ts_code", "symbol", "代码", "股票代码", "code"])
    if not code_col:
        return pd.DataFrame(columns=VALUATION_COLUMNS)
    result["ts_code"] = df[code_col].map(_to_ts_code)
    mappings = {
        "pe": ["pe", "市盈率", "市盈率-动态", "动态市盈率", "市盈(动)", "f9"],
        "pb": ["pb", "市净率", "市净率LF", "市净率MRQ", "f23"],
        "total_mv": ["total_mv", "总市值", "总市值-元", "f20"],
        "circ_mv": ["circ_mv", "流通市值", "流通市值-元", "f21"],
        "volume_ratio": ["volume_ratio", "量比", "f10"],
    }
    for target, candidates in mappings.items():
        column = _first_existing(df, candidates)
        result[target] = df[column].map(_to_number) if column else pd.NA
    result["valuation_source"] = "akshare_snapshot"
    return result[VALUATION_COLUMNS]


def parse_eastmoney_quote(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Map Eastmoney quote JSON rows to internal valuation fields."""
    parsed = [
        {
            "ts_code": _to_ts_code(item.get("f12") or item.get("symbol") or item.get("代码")),
            "pe": _to_number(item.get("f9")),
            "pb": _to_number(item.get("f23")),
            "total_mv": _to_number(item.get("f20")),
            "circ_mv": _to_number(item.get("f21")),
            "volume_ratio": _to_number(item.get("f10")),
            "valuation_source": "eastmoney_quote_curl",
        }
        for item in rows
    ]
    return pd.DataFrame(parsed, columns=VALUATION_COLUMNS)


def merge_latest_valuation(daily_basic: pd.DataFrame, valuation: pd.DataFrame) -> pd.DataFrame:
    """Fill valuation fields on each stock's latest daily_basic row only."""
    if daily_basic.empty or valuation.empty or "ts_code" not in daily_basic.columns:
        return daily_basic.copy()
    result = daily_basic.copy()
    if "trade_date" not in result.columns:
        return result
    latest_dates = result.dropna(subset=["trade_date"]).groupby("ts_code")["trade_date"].max().to_dict()
    updates = valuation.copy()
    updates["trade_date"] = updates["ts_code"].map(latest_dates)
    updates = updates.dropna(subset=["trade_date"])
    if updates.empty:
        return result
    fields = ["pe", "pb", "total_mv", "circ_mv", "volume_ratio"]
    merged = result.merge(
        updates[["ts_code", "trade_date", *fields]],
        on=["ts_code", "trade_date"],
        how="left",
        suffixes=("", "_valuation"),
    )
    for field in fields:
        enriched = f"{field}_valuation"
        if enriched in merged.columns:
            enriched_values = merged[enriched]
            merged[field] = merged[field].where(~merged[field].map(_is_missing), enriched_values)
            merged = merged.drop(columns=[enriched])
    return merged


def _filter_requested(df: pd.DataFrame, requested: list[str]) -> pd.DataFrame:
    if df.empty or "ts_code" not in df.columns:
        return pd.DataFrame(columns=VALUATION_COLUMNS)
    requested_set = set(requested)
    result = df[df["ts_code"].astype(str).isin(requested_set)].copy()
    return result[VALUATION_COLUMNS] if not result.empty else pd.DataFrame(columns=VALUATION_COLUMNS)


def _covers_any_requested(df: pd.DataFrame, requested: list[str]) -> bool:
    if df.empty or "ts_code" not in df.columns:
        return False
    return bool(set(df["ts_code"].dropna().astype(str)).intersection(requested))


def _first_existing(df: pd.DataFrame, columns: list[str]) -> str | None:
    for column in columns:
        if column in df.columns:
            return column
    return None


def _to_ts_code(symbol: Any) -> str:
    clean = str(symbol or "").strip()
    if "." in clean:
        return clean.upper()
    clean = clean.zfill(6) if clean.isdigit() else clean
    suffix = "SH" if clean.startswith("6") else "SZ"
    return f"{clean}.{suffix}"


def _to_eastmoney_secid(symbol: str) -> str:
    clean = str(symbol).split(".")[0]
    market = "1" if clean.startswith("6") else "0"
    return f"{market}.{clean}"


def _to_number(value: Any) -> float | None:
    if value in {"", "-", "--", None}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"", "nan", "none", "<na>", "null"}


def _warning(symbol: str, stage: str, message: str) -> dict[str, str]:
    return {
        "symbol": symbol,
        "provider": "valuation_enrichment",
        "failed_stage": stage,
        "error_message": message,
    }
