"""AKShare spot-snapshot fallback for latest EOD market data."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

import pandas as pd

from core.data_sources.real_universe import is_bse_symbol


MARKET_CLOSE_WRITE_TIME = time(15, 10)


class SpotSnapshotUnavailable(RuntimeError):
    """Raised when AKShare spot snapshot cannot be fetched or parsed."""


class AKShareSpotSnapshotClient:
    """Fetch and normalize AKShare A-share spot snapshots.

    This fallback is intended only for latest-day EOD snapshots when historical
    K-line endpoints fail. It is not a replacement for historical daily bars.
    """

    def __init__(self, akshare_module: Any | None = None) -> None:
        self._akshare = akshare_module

    def fetch_latest(
        self,
        *,
        trade_date: str,
        symbols: list[str] | None = None,
        force: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return normalized daily_price and partial daily_basic frames."""
        current = now or datetime.now()
        if not force and current.time() < MARKET_CLOSE_WRITE_TIME:
            return {
                "status": "skipped",
                "message": "当前早于 15:10，未写入实时行情快照。",
                "daily_price": pd.DataFrame(),
                "daily_basic": pd.DataFrame(),
                "skipped_symbols": [],
                "partial_update": True,
            }

        raw = self._call_spot()
        daily_price, daily_basic, skipped = normalize_spot_snapshot(raw, trade_date=trade_date, symbols=symbols)
        status = "success" if not daily_price.empty else "failed"
        return {
            "status": status,
            "message": "AKShare 实时行情快照已转换为最新交易日 daily_price。" if status == "success" else "AKShare 实时行情快照无可写入数据。",
            "daily_price": daily_price,
            "daily_basic": daily_basic,
            "skipped_symbols": skipped,
            "partial_update": True,
            "provider": "akshare_spot_snapshot",
            "source_granularity": "eod_snapshot",
        }

    def _call_spot(self) -> pd.DataFrame:
        module = self._module()
        for function_name in ["stock_zh_a_spot_em", "stock_zh_a_spot"]:
            function = getattr(module, function_name, None)
            if function is None:
                continue
            result = function()
            if isinstance(result, pd.DataFrame):
                return result
        raise SpotSnapshotUnavailable("AKShare realtime snapshot function is unavailable.")

    def _module(self) -> Any:
        if self._akshare is not None:
            return self._akshare
        try:
            import akshare as ak
        except ImportError as exc:
            raise SpotSnapshotUnavailable("AKShare is not installed.") from exc
        self._akshare = ak
        return ak


def normalize_spot_snapshot(
    raw: pd.DataFrame,
    *,
    trade_date: str,
    symbols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Map AKShare spot columns to daily_price and partial daily_basic."""
    if raw.empty:
        return _empty_price(), _empty_basic(), []
    frame = raw.rename(
        columns={
            "代码": "symbol",
            "股票代码": "symbol",
            "code": "symbol",
            "名称": "name",
            "最新价": "close",
            "收盘": "close",
            "今开": "open",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "昨收": "pre_close",
            "成交量": "vol",
            "成交额": "amount",
            "换手率": "turnover_rate",
            "涨跌幅": "pct_chg",
            "涨跌额": "change",
            "市盈率-动态": "pe",
            "市盈率": "pe",
            "市净率": "pb",
            "总市值": "total_mv",
            "流通市值": "circ_mv",
        }
    ).copy()
    if "symbol" not in frame.columns:
        return _empty_price(), _empty_basic(), []
    wanted = {_normalize_symbol(symbol) for symbol in symbols or []}
    rows_price: list[dict[str, Any]] = []
    rows_basic: list[dict[str, Any]] = []
    skipped: list[str] = []
    for _, row in frame.iterrows():
        symbol = _normalize_symbol(row.get("symbol"))
        if not symbol or not symbol.isdigit() or len(symbol) != 6:
            continue
        if wanted and symbol not in wanted:
            continue
        if is_bse_symbol(symbol):
            skipped.append(symbol)
            continue
        close = _to_number(row.get("close"))
        amount = _to_number(row.get("amount"))
        vol = _to_number(row.get("vol"))
        if close is None or close <= 0 or ((amount is None or amount <= 0) and (vol is None or vol <= 0)):
            skipped.append(_to_ts_code(symbol))
            continue
        ts_code = _to_ts_code(symbol)
        rows_price.append(
            {
                "ts_code": ts_code,
                "trade_date": _normalize_date(trade_date),
                "open": _to_number(row.get("open")),
                "high": _to_number(row.get("high")),
                "low": _to_number(row.get("low")),
                "close": close,
                "pre_close": _to_number(row.get("pre_close")),
                "change": _to_number(row.get("change")),
                "pct_chg": _to_number(row.get("pct_chg")),
                "vol": vol,
                "amount": amount,
            }
        )
        rows_basic.append(
            {
                "ts_code": ts_code,
                "trade_date": _normalize_date(trade_date),
                "turnover_rate": _to_number(row.get("turnover_rate")),
                "volume_ratio": _to_number(row.get("volume_ratio")),
                "pe": _to_number(row.get("pe")),
                "pb": _to_number(row.get("pb")),
                "ps": pd.NA,
                "total_mv": _to_number(row.get("total_mv")),
                "circ_mv": _to_number(row.get("circ_mv")),
            }
        )
    return pd.DataFrame(rows_price, columns=_empty_price().columns), pd.DataFrame(rows_basic, columns=_empty_basic().columns), skipped


def _empty_price() -> pd.DataFrame:
    return pd.DataFrame(columns=["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"])


def _empty_basic() -> pd.DataFrame:
    return pd.DataFrame(columns=["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"])


def _normalize_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text.split(".")[0]


def _to_ts_code(symbol: str) -> str:
    clean = _normalize_symbol(symbol)
    return f"{clean}.SH" if clean.startswith("6") else f"{clean}.SZ"


def _normalize_date(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    return digits[:8]


def _to_number(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "None", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None
