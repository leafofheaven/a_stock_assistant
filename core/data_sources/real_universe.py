"""Real A-share universe helpers for controlled local full-mode updates."""

from __future__ import annotations

from typing import Any

import pandas as pd


FULL_UNIVERSE_PRESET = "full"
FULL_UNIVERSE_LABEL = "沪深 A 股全市场，不含北交所"

STANDARD_COLUMNS = [
    "ts_code",
    "symbol",
    "name",
    "market",
    "exchange",
    "list_date",
]


def is_full_universe_preset(preset: str | None) -> bool:
    """Return whether the configured preset requests the full HS A-share universe."""
    return str(preset or "").strip().lower() == FULL_UNIVERSE_PRESET


def build_full_a_share_universe(raw_stock_basic: pd.DataFrame, include_bse: bool = False) -> pd.DataFrame:
    """Normalize and filter AKShare stock-basic rows to the full HS A-share universe.

    The first version intentionally excludes BSE/BJ stocks. It only keeps
    Shanghai and Shenzhen main board, ChiNext, and STAR Market symbols. ST,
    delisting-board, and obviously abnormal names are removed at the rule level
    before market-data download.
    """
    normalized = normalize_stock_basic_frame(raw_stock_basic)
    if normalized.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    result = normalized.copy()
    if not include_bse:
        result = result[result["exchange"] != "BSE"].copy()
    result = result[~result["name"].map(is_rule_excluded_name)].copy()
    result = result[result["exchange"].isin(["SSE", "SZSE"])].copy()
    return result.drop_duplicates("ts_code", keep="last").reset_index(drop=True)


def resolve_full_a_share_universe(raw_stock_basic: pd.DataFrame, include_bse: bool = False) -> dict[str, Any]:
    """Return full-universe rows plus diagnostic counts.

    The result is intentionally plain dict data so jobs can pass it through
    command output, JSON reports, and tests without importing a custom class.
    """
    normalized = normalize_stock_basic_frame(raw_stock_basic)
    if normalized.empty:
        return {
            "source": "REAL_UNIVERSE_PRESET=full",
            "label": FULL_UNIVERSE_LABEL,
            "stock_basic": pd.DataFrame(columns=STANDARD_COLUMNS),
            "symbols": [],
            "ts_codes": [],
            "raw_symbol_count": 0,
            "excluded_bse_count": 0,
            "excluded_abnormal_count": 0,
            "base_universe_count": 0,
            "warnings": ["AKShare 基础股票列表为空，full 股票池暂不可用。"],
        }

    bse_mask = normalized["exchange"].eq("BSE")
    abnormal_mask = normalized["name"].map(is_rule_excluded_name)
    result = normalized.copy()
    if not include_bse:
        result = result[~bse_mask].copy()
    result = result[~result["name"].map(is_rule_excluded_name)].copy()
    result = result[result["exchange"].isin(["SSE", "SZSE"])].copy()
    result = result.drop_duplicates("ts_code", keep="last").reset_index(drop=True)
    return {
        "source": "REAL_UNIVERSE_PRESET=full",
        "label": FULL_UNIVERSE_LABEL,
        "stock_basic": result,
        "symbols": result["symbol"].dropna().astype(str).tolist() if "symbol" in result.columns else [],
        "ts_codes": result["ts_code"].dropna().astype(str).tolist() if "ts_code" in result.columns else [],
        "raw_symbol_count": int(len(normalized)),
        "excluded_bse_count": int(bse_mask.sum()) if not include_bse else 0,
        "excluded_abnormal_count": int((~bse_mask & abnormal_mask).sum()) if not include_bse else int(abnormal_mask.sum()),
        "base_universe_count": int(len(result)),
        "warnings": [] if not result.empty else ["full 股票池过滤后为空，请检查 AKShare 基础列表返回结构。"],
    }


def normalize_stock_basic_frame(raw_stock_basic: pd.DataFrame) -> pd.DataFrame:
    """Return stock-basic rows with stable project columns."""
    if raw_stock_basic.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    result = raw_stock_basic.copy()
    result = result.rename(
        columns={
            "code": "symbol",
            "代码": "symbol",
            "股票代码": "symbol",
            "名称": "name",
            "股票简称": "name",
            "上市日期": "list_date",
            "上市时间": "list_date",
            "板块": "market",
            "市场": "market",
        }
    )
    if "symbol" not in result.columns and "ts_code" in result.columns:
        result["symbol"] = result["ts_code"].astype(str).str.split(".").str[0]
    if "ts_code" not in result.columns and "symbol" in result.columns:
        result["ts_code"] = result["symbol"].map(to_ts_code)
    for column in STANDARD_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA

    result["symbol"] = result["symbol"].astype(str).str.strip().str.split(".").str[0]
    result = result[result["symbol"].str.fullmatch(r"\d{6}", na=False)].copy()
    result["ts_code"] = result["symbol"].map(to_ts_code)
    result["exchange"] = result["symbol"].map(exchange_from_symbol)
    result["market"] = result["market"].where(result["market"].map(_has_value), result["symbol"].map(market_from_symbol))
    result["list_date"] = result["list_date"].map(_normalize_date_value)
    result["name"] = result["name"].fillna("").astype(str).str.strip()
    return result[STANDARD_COLUMNS].reset_index(drop=True)


def is_rule_excluded_name(name: Any) -> bool:
    """Return whether a stock name is rule-excluded before market-data download."""
    text = str(name or "").upper().replace(" ", "")
    if not text:
        return False
    return any(token in text for token in ["ST", "*ST", "退市", "退", "PT"])


def is_bse_symbol(symbol: str) -> bool:
    """Return whether a symbol belongs to BSE/BJ by common A-share prefixes."""
    clean = str(symbol).strip().split(".")[0]
    suffix = str(symbol).strip().split(".")[-1].upper() if "." in str(symbol) else ""
    return suffix in {"BJ", "BSE"} or clean.startswith(("4", "8", "9"))


def exchange_from_symbol(symbol: str) -> str:
    """Return project exchange code for a six-digit symbol."""
    clean = str(symbol).strip().split(".")[0]
    if is_bse_symbol(clean):
        return "BSE"
    if clean.startswith("6"):
        return "SSE"
    return "SZSE"


def market_from_symbol(symbol: str) -> str:
    """Return a coarse market segment label for common A-share prefixes."""
    clean = str(symbol).strip().split(".")[0]
    if is_bse_symbol(clean):
        return "北交所"
    if clean.startswith("688"):
        return "科创板"
    if clean.startswith(("300", "301")):
        return "创业板"
    return "主板"


def to_ts_code(symbol: str) -> str:
    """Normalize a raw symbol to project ts_code, excluding BSE by suffix only."""
    clean = str(symbol).strip()
    if "." in clean:
        return clean
    if is_bse_symbol(clean):
        return f"{clean}.BJ"
    suffix = "SH" if clean.startswith("6") else "SZ"
    return f"{clean}.{suffix}"


def _normalize_date_value(value: Any) -> Any:
    """Normalize list-date values to YYYYMMDD while keeping missing values empty."""
    if not _has_value(value):
        return pd.NA
    text = str(value).strip().replace("-", "").replace("/", "")
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    return str(value).strip()


def _has_value(value: Any) -> bool:
    """Return whether a value should be considered non-empty."""
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip() != ""
