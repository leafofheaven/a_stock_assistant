"""BaoStock fallback client for historical daily_price data."""

from __future__ import annotations

from typing import Any

import pandas as pd


class BaoStockUnavailable(RuntimeError):
    """Raised when BaoStock is not installed or returns an unusable response."""


class BaoStockClient:
    """Small BaoStock adapter focused on daily_price fallback data."""

    def __init__(self, baostock_module: Any | None = None) -> None:
        self._baostock = baostock_module

    def get_daily_price(
        self,
        *,
        start_date: str,
        end_date: str,
        symbols: list[str],
        adjustflag: str = "2",
        limit: int = 0,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Fetch daily bars for symbols and return a normalized frame."""
        module = self._module()
        login = module.login()
        if getattr(login, "error_code", "0") != "0":
            raise BaoStockUnavailable(f"BaoStock login failed: {getattr(login, 'error_msg', '')}")
        frames: list[pd.DataFrame] = []
        failures: list[dict[str, str]] = []
        try:
            planned_symbols = symbols[: limit or None]
            total = len(planned_symbols)
            for index, symbol in enumerate(planned_symbols, start=1):
                query_symbol = _to_baostock_code(symbol)
                try:
                    result = module.query_history_k_data_plus(
                        query_symbol,
                        "date,code,open,high,low,close,preclose,volume,amount,pctChg",
                        start_date=_to_dash_date(start_date),
                        end_date=_to_dash_date(end_date),
                        frequency="d",
                        adjustflag=adjustflag,
                    )
                except Exception as exc:
                    failures.append({"symbol": _to_ts_code(symbol), "error_message": f"{type(exc).__name__}: {exc}"})
                    _emit_progress(progress_callback, symbol=symbol, status="failed", written_rows=0, processed_symbol_count=index, total_symbol_count=total)
                    continue
                if getattr(result, "error_code", "0") != "0":
                    failures.append({"symbol": _to_ts_code(symbol), "error_message": str(getattr(result, "error_msg", ""))})
                    _emit_progress(progress_callback, symbol=symbol, status="failed", written_rows=0, processed_symbol_count=index, total_symbol_count=total)
                    continue
                rows: list[list[Any]] = []
                fields = list(getattr(result, "fields", []) or [])
                while result.next():
                    rows.append(result.get_row_data())
                if not rows:
                    _emit_progress(progress_callback, symbol=symbol, status="skipped", written_rows=0, processed_symbol_count=index, total_symbol_count=total)
                    continue
                frame = pd.DataFrame(rows, columns=fields)
                frames.append(_normalize_baostock_frame(frame))
                _emit_progress(progress_callback, symbol=symbol, status="success", written_rows=len(rows), processed_symbol_count=index, total_symbol_count=total)
        finally:
            logout = getattr(module, "logout", None)
            if callable(logout):
                logout()
        data = pd.concat(frames, ignore_index=True) if frames else _empty_price()
        return {
            "status": "success" if failures == [] else "partial_success" if not data.empty else "failed",
            "daily_price": data,
            "failure_records": failures,
            "provider": "baostock",
            "partial_update": True,
        }

    def _module(self) -> Any:
        if self._baostock is not None:
            return self._baostock
        try:
            import baostock as bs
        except ImportError as exc:
            raise BaoStockUnavailable("BaoStock is not installed.") from exc
        self._baostock = bs
        return bs


def _normalize_baostock_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _empty_price()
    result = frame.rename(
        columns={
            "date": "trade_date",
            "code": "symbol",
            "preclose": "pre_close",
            "volume": "vol",
            "pctChg": "pct_chg",
        }
    ).copy()
    result["trade_date"] = result.get("trade_date", "").astype(str).str.replace("-", "", regex=False)
    result["ts_code"] = result.get("symbol", "").map(_baostock_to_ts_code)
    result["change"] = pd.to_numeric(result.get("close"), errors="coerce") - pd.to_numeric(result.get("pre_close"), errors="coerce")
    for column in ["open", "high", "low", "close", "pre_close", "vol", "amount", "pct_chg", "change"]:
        if column not in result.columns:
            result[column] = pd.NA
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result[["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]]


def _empty_price() -> pd.DataFrame:
    return pd.DataFrame(columns=["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"])


def _to_baostock_code(symbol: str) -> str:
    clean = str(symbol).strip().upper()
    if clean.startswith(("sh.", "sz.")):
        return clean.lower()
    code = clean.split(".")[0]
    prefix = "sh" if code.startswith("6") else "sz"
    return f"{prefix}.{code}"


def _baostock_to_ts_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "." in text:
        prefix, code = text.split(".", 1)
        return f"{code.upper()}.SH" if prefix == "sh" else f"{code.upper()}.SZ"
    return _to_ts_code(text)


def _to_ts_code(symbol: str) -> str:
    code = str(symbol).strip().upper().split(".")[0]
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def _to_dash_date(value: str) -> str:
    text = str(value or "").strip()
    if "-" in text:
        return text
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) >= 8 else text


def _emit_progress(callback: Any | None, **payload: Any) -> None:
    if callback is None:
        return
    try:
        callback(**payload)
    except Exception:
        return
