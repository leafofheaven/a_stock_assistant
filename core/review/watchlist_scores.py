"""Shared watchlist latest score enrichment helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.jobs.run_daily_selection import _calculate_minimal_real_scores
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.universe.stock_pool import build_tradeable_universe

SCORE_COLUMNS = [
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "fundamental_score",
    "volatility_score",
    "total_score",
    "return_20d",
    "avg_amount_20d",
    "avg_turnover_20d",
    "volatility_20d",
]

WATCHLIST_LATEST_COLUMNS = [
    "industry",
    "market",
    "list_date",
    "latest_trade_date",
    "latest_close",
    "pe",
    "pb",
    *SCORE_COLUMNS,
    "score_source",
    "score_missing_reason",
    "data_quality_note",
]


def enrich_watchlist_latest_fields(
    decisions: pd.DataFrame,
    *,
    store: DuckDBStore,
    settings: Settings | None = None,
) -> pd.DataFrame:
    """Attach latest local price, valuation, basic fields, and scores to watch decisions.

    The helper never accesses external APIs. It first uses locally stored
    factor_scores or strategy_result. If no stored score exists for a watched
    stock, it tries the existing minimal real-data scoring pipeline against
    local DuckDB tables only.
    """
    if decisions.empty:
        return _empty_result(decisions)

    resolved_settings = settings or get_settings()
    stock_basic = _safe_read_table(store, "stock_basic")
    daily_price = _safe_read_table(store, "daily_price")
    daily_basic = _safe_read_table(store, "daily_basic")
    stored_scores = _stored_scores(store)
    computed_scores = _computed_scores(
        stock_basic=stock_basic,
        daily_price=daily_price,
        daily_basic=daily_basic,
        settings=resolved_settings,
    )

    rows: list[dict[str, Any]] = []
    for row in decisions.to_dict("records"):
        rows.append(
            _enrich_row(
                row=row,
                stock_basic=stock_basic,
                daily_price=daily_price,
                daily_basic=daily_basic,
                stored_scores=stored_scores,
                computed_scores=computed_scores,
            )
        )
    return pd.DataFrame(rows)


def latest_trade_date_from_store(store: DuckDBStore) -> str:
    """Return latest local daily_price trade_date or today when no price exists."""
    daily_price = _safe_read_table(store, "daily_price")
    if not daily_price.empty and "trade_date" in daily_price.columns:
        values = daily_price["trade_date"].dropna().astype(str)
        if not values.empty:
            return str(values.max())
    return datetime.now().strftime("%Y%m%d")


def _enrich_row(
    *,
    row: dict[str, Any],
    stock_basic: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
    stored_scores: pd.DataFrame,
    computed_scores: pd.DataFrame,
) -> dict[str, Any]:
    ts_code = str(row.get("ts_code", ""))
    latest_price = _latest_row(daily_price, ts_code, "trade_date")
    latest_trade_date = _clean_text(latest_price.get("trade_date"))
    latest_basic = _latest_row(daily_basic, ts_code, "trade_date", cutoff=latest_trade_date)
    stock_info = _latest_row(stock_basic, ts_code, "ts_code")
    stored_score = _latest_row(stored_scores, ts_code, "trade_date", cutoff=latest_trade_date)
    computed_score = _latest_row(computed_scores, ts_code, "trade_date", cutoff=latest_trade_date)
    score = stored_score or computed_score
    score_source = "stored" if stored_score else ("computed" if computed_score else "")
    total_score = _optional_float(score.get("total_score"))
    missing_reason = _score_missing_reason(
        ts_code=ts_code,
        latest_price=latest_price,
        daily_price=daily_price,
        daily_basic=daily_basic,
        stored_scores=stored_scores,
        computed_scores=computed_scores,
        total_score=total_score,
    )
    quality_note = _data_quality_note(
        row.get("data_quality_note"),
        stock_info=stock_info,
        latest_basic=latest_basic,
        total_score=total_score,
        score_missing_reason=missing_reason,
    )
    enriched = {
        **row,
        "name": _clean_text(row.get("name")) or _clean_text(stock_info.get("name")) or score.get("name"),
        "industry": stock_info.get("industry") or score.get("industry"),
        "market": stock_info.get("market"),
        "list_date": stock_info.get("list_date"),
        "latest_trade_date": latest_trade_date or score.get("trade_date") or row.get("selection_date"),
        "latest_close": _optional_float(latest_price.get("close")),
        "pe": _optional_float(latest_basic.get("pe")),
        "pb": _optional_float(latest_basic.get("pb")),
        "score_source": score_source,
        "score_missing_reason": missing_reason,
        "data_quality_note": quality_note,
    }
    for column in SCORE_COLUMNS:
        enriched[column] = _optional_float(score.get(column))
    return enriched


def _stored_scores(store: DuckDBStore) -> pd.DataFrame:
    frames = [_safe_read_table(store, "factor_scores"), _safe_read_table(store, "strategy_result")]
    available = [frame for frame in frames if not frame.empty and "ts_code" in frame.columns]
    if not available:
        return pd.DataFrame()
    return pd.concat(available, ignore_index=True, sort=False)


def _computed_scores(
    *,
    stock_basic: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
    settings: Settings,
) -> pd.DataFrame:
    if stock_basic.empty or daily_price.empty or daily_basic.empty or "trade_date" not in daily_price.columns:
        return pd.DataFrame()
    latest_trade_date = str(daily_price["trade_date"].dropna().astype(str).max())
    if not latest_trade_date:
        return pd.DataFrame()
    try:
        is_akshare = settings.data_provider == "akshare"
        universe = build_tradeable_universe(
            stock_basic,
            daily_price,
            daily_basic,
            latest_trade_date,
            allow_missing_list_date_with_price_history=is_akshare,
            min_price_history_days=60,
            allow_missing_valuation=is_akshare,
        )
        tradeable = universe[universe["is_tradeable"].fillna(False)].copy()
        if tradeable.empty:
            return pd.DataFrame()
        return _calculate_minimal_real_scores(daily_price, daily_basic, tradeable, latest_trade_date)
    except Exception:
        return pd.DataFrame()


def _score_missing_reason(
    *,
    ts_code: str,
    latest_price: dict[str, Any],
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
    stored_scores: pd.DataFrame,
    computed_scores: pd.DataFrame,
    total_score: float | None,
) -> str:
    if total_score is not None:
        return ""
    if not latest_price:
        return "缺少本地行情数据，无法刷新综合评分"
    price_rows = _stock_rows(daily_price, ts_code)
    if len(price_rows) < 20:
        return "本地行情交易日不足 20 日，无法计算基础评分"
    basic_rows = _stock_rows(daily_basic, ts_code)
    if basic_rows.empty:
        return "缺少 daily_basic 数据，估值和换手字段不可用"
    if _stock_rows(stored_scores, ts_code).empty and _stock_rows(computed_scores, ts_code).empty:
        return "当前股票不在最新可交易股票池或本地评分结果中"
    return "当前无可用综合评分"


def _data_quality_note(
    value: Any,
    *,
    stock_info: dict[str, Any],
    latest_basic: dict[str, Any],
    total_score: float | None,
    score_missing_reason: str,
) -> str:
    notes = [_clean_text(value)] if _clean_text(value) else []
    pe_missing = _optional_float(latest_basic.get("pe")) is None
    pb_missing = _optional_float(latest_basic.get("pb")) is None
    notes = _filter_existing_quality_notes(notes, valuation_missing=pe_missing or pb_missing, score_missing=total_score is None)
    if score_missing_reason:
        notes.append("当前无可用综合评分")
        notes.append(score_missing_reason)
    if not _clean_text(stock_info.get("industry")):
        notes.append("industry 缺失")
    if not _clean_text(stock_info.get("market")):
        notes.append("market 缺失")
    if not _clean_text(stock_info.get("list_date")):
        notes.append("list_date 缺失")
    if pe_missing:
        notes.append("pe 缺失")
    if pb_missing:
        notes.append("pb 缺失")
    return "；".join(dict.fromkeys(note for note in notes if note))


def _filter_existing_quality_notes(
    notes: list[str],
    *,
    valuation_missing: bool,
    score_missing: bool,
) -> list[str]:
    valuation_phrases = [
        "pe 全部缺失",
        "pb 全部缺失",
        "部分股票 pe 缺失",
        "部分股票 pb 缺失",
        "pe/pb 可能为空",
        "pe/pb 缺失",
        "pe 缺失",
        "pb 缺失",
        "估值相关复核信息不完整",
    ]
    score_phrases = [
        "当前无可用综合评分",
        "fundamental_score 可能为空",
        "fundamental_score 为空原因",
        "基本面分项可能偏低或为空",
        "pe_score 与 fundamental_score 可能为空",
        "基本面数据缺失",
    ]
    filtered: list[str] = []
    for note in notes:
        text = _clean_text(note)
        if not text:
            continue
        if not valuation_missing and any(phrase in text for phrase in valuation_phrases):
            continue
        if not score_missing and any(phrase in text for phrase in score_phrases):
            continue
        filtered.append(text)
    return filtered


def _latest_row(df: pd.DataFrame, ts_code: str, date_col: str, cutoff: str | None = None) -> dict[str, Any]:
    if df.empty or "ts_code" not in df.columns or date_col not in df.columns:
        return {}
    rows = df[df["ts_code"].astype(str) == ts_code].copy()
    if cutoff and date_col != "ts_code":
        rows = rows[rows[date_col].astype(str) <= str(cutoff)]
    if rows.empty:
        return {}
    return rows.sort_values(date_col).iloc[-1].to_dict()


def _stock_rows(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    if df.empty or "ts_code" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["ts_code"].astype(str) == ts_code].copy()


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _empty_result(decisions: pd.DataFrame) -> pd.DataFrame:
    result = decisions.copy()
    for column in WATCHLIST_LATEST_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>", "null"} else text
