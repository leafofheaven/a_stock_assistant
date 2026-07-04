"""Read-only market data quality snapshot shared by jobs and UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


CORE_SNAPSHOT_TABLES = [
    "stock_basic",
    "daily_price",
    "daily_basic",
    "adj_factor",
    "factor_scores",
    "strategy_result",
    "entry_zone_snapshots",
    "watchlist_daily_snapshots",
]


def build_data_quality_snapshot(
    *,
    db_path: str | Path | None = None,
    store: DuckDBStore | None = None,
    tables: dict[str, pd.DataFrame] | None = None,
    configured_symbols: list[str] | None = None,
    run_date: str = "",
    research_trade_date: str = "",
    latest_completed_trade_date: str = "",
) -> dict[str, Any]:
    """Build a single read-only data quality snapshot.

    The latest-date coverage is always counted at ``latest_completed_trade_date``.
    It never mixes "any historical price exists" into latest trading-day coverage.
    """
    resolved_tables = tables if tables is not None else _read_tables(db_path=db_path, store=store)
    target_date = str(latest_completed_trade_date or research_trade_date or _latest_date(resolved_tables.get("daily_price", pd.DataFrame()), "trade_date") or "")
    symbols = list(configured_symbols or _symbols_from_table(resolved_tables.get("stock_basic", pd.DataFrame())))
    if not symbols:
        all_symbols = set()
        for table_name in ["daily_price", "daily_basic", "adj_factor"]:
            all_symbols.update(_symbols_from_table(resolved_tables.get(table_name, pd.DataFrame())))
        symbols = sorted(all_symbols)
    configured_set = set(symbols)
    denominator = len(configured_set)

    daily_price = resolved_tables.get("daily_price", pd.DataFrame())
    daily_basic = resolved_tables.get("daily_basic", pd.DataFrame())
    adj_factor = resolved_tables.get("adj_factor", pd.DataFrame())
    factor_scores = resolved_tables.get("factor_scores", pd.DataFrame())
    strategy_result = resolved_tables.get("strategy_result", pd.DataFrame())
    entry_zones = resolved_tables.get("entry_zone_snapshots", pd.DataFrame())
    watchlist_snapshots = resolved_tables.get("watchlist_daily_snapshots", pd.DataFrame())

    any_price_symbols = _symbols_from_table(daily_price).intersection(configured_set) if configured_set else _symbols_from_table(daily_price)
    latest_price_symbols = _symbols_at_date(daily_price, target_date).intersection(configured_set) if configured_set else _symbols_at_date(daily_price, target_date)
    latest_basic_symbols = _symbols_at_date(daily_basic, target_date).intersection(configured_set) if configured_set else _symbols_at_date(daily_basic, target_date)
    latest_adj_symbols = _symbols_at_date(adj_factor, target_date).intersection(configured_set) if configured_set else _symbols_at_date(adj_factor, target_date)
    latest_all_required = latest_price_symbols.intersection(latest_basic_symbols).intersection(latest_adj_symbols)

    row_counts = _row_counts(daily_price)
    history_complete = [symbol for symbol in configured_set if row_counts.get(symbol, 0) >= 252]
    history_incomplete = [symbol for symbol in configured_set if 0 < row_counts.get(symbol, 0) < 252]
    history_missing = [symbol for symbol in configured_set if row_counts.get(symbol, 0) <= 0]
    factor_ready = _symbols_at_date(factor_scores, target_date).intersection(configured_set) if configured_set else _symbols_at_date(factor_scores, target_date)
    elder_ready = _symbols_at_date(watchlist_snapshots, target_date).intersection(configured_set) if configured_set else _symbols_at_date(watchlist_snapshots, target_date)
    entry_ready = _symbols_at_date(entry_zones, target_date).intersection(configured_set) if configured_set else _symbols_at_date(entry_zones, target_date)
    strategy_symbols = _symbols_at_date(strategy_result, target_date).intersection(configured_set) if configured_set else _symbols_at_date(strategy_result, target_date)
    lookback_ready = {symbol for symbol in strategy_symbols if row_counts.get(symbol, 0) >= 80}

    denominator = denominator or len(any_price_symbols | latest_basic_symbols | latest_adj_symbols)
    price_rate = _rate(len(latest_price_symbols), denominator)
    quality_status = _quality_status(price_rate)
    formal_usable = quality_status not in {"poor", "failed"}
    warning_reason = ""
    if not formal_usable:
        warning_reason = "最新交易日数据覆盖严重不足，当前结果仅供流程检查，不代表完整全市场筛选。"

    return {
        "run_date": run_date,
        "research_trade_date": research_trade_date or target_date,
        "latest_completed_trade_date": target_date,
        "configured_symbol_count": denominator,
        "latest_daily_price_symbol_count": len(latest_price_symbols),
        "missing_latest_daily_price_symbol_count": max(denominator - len(latest_price_symbols), 0),
        "latest_daily_price_coverage_rate": price_rate,
        "latest_daily_basic_symbol_count": len(latest_basic_symbols),
        "missing_latest_daily_basic_symbol_count": max(denominator - len(latest_basic_symbols), 0),
        "latest_daily_basic_coverage_rate": _rate(len(latest_basic_symbols), denominator),
        "latest_adj_factor_symbol_count": len(latest_adj_symbols),
        "missing_latest_adj_factor_symbol_count": max(denominator - len(latest_adj_symbols), 0),
        "latest_adj_factor_coverage_rate": _rate(len(latest_adj_symbols), denominator),
        "latest_all_required_tables_symbol_count": len(latest_all_required),
        "missing_latest_all_required_tables_symbol_count": max(denominator - len(latest_all_required), 0),
        "latest_all_required_tables_coverage_rate": _rate(len(latest_all_required), denominator),
        "any_daily_price_symbol_count": len(any_price_symbols),
        "missing_any_daily_price_symbol_count": max(denominator - len(any_price_symbols), 0),
        "any_daily_price_coverage_rate": _rate(len(any_price_symbols), denominator),
        "history_complete_symbol_count": len(history_complete),
        "history_incomplete_symbol_count": len(history_incomplete),
        "history_missing_symbol_count": len(history_missing),
        "available_days_20d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 20),
        "available_days_60d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 60),
        "available_days_120d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 120),
        "available_days_252d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 252),
        "factor_ready_symbol_count": len(factor_ready),
        "elder_ready_symbol_count": len(elder_ready),
        "entry_zone_ready_symbol_count": len(entry_ready),
        "lookback_ready_symbol_count": len(lookback_ready),
        "missing_latest_daily_price_examples": sorted((configured_set or latest_price_symbols) - latest_price_symbols)[:30],
        "missing_latest_daily_basic_examples": sorted((configured_set or latest_basic_symbols) - latest_basic_symbols)[:30],
        "missing_latest_adj_factor_examples": sorted((configured_set or latest_adj_symbols) - latest_adj_symbols)[:30],
        "history_missing_examples": sorted(history_missing)[:30],
        "latest_updated_but_history_incomplete_count": sum(1 for symbol in latest_price_symbols if row_counts.get(symbol, 0) < 252),
        "latest_updated_but_history_incomplete_examples": sorted(symbol for symbol in latest_price_symbols if row_counts.get(symbol, 0) < 252)[:30],
        "history_complete_but_latest_missing_count": sum(1 for symbol in history_complete if symbol not in latest_price_symbols),
        "history_complete_but_latest_missing_examples": sorted(symbol for symbol in history_complete if symbol not in latest_price_symbols)[:30],
        "data_quality_status": quality_status,
        "formal_result_usable": formal_usable,
        "formal_result_warning_reason": warning_reason,
        "data_quality_snapshot_source": "readonly_duckdb",
    }


def classify_coverage_rate(rate: float) -> str:
    """Return UI quality label for one coverage rate."""
    return _quality_status(rate)


def _read_tables(*, db_path: str | Path | None, store: DuckDBStore | None) -> dict[str, pd.DataFrame]:
    resolved_store = store or DuckDBStore(db_path)
    tables: dict[str, pd.DataFrame] = {}
    for table_name in CORE_SNAPSHOT_TABLES:
        try:
            tables[table_name] = resolved_store.read_table(table_name)
        except DuckDBStoreError:
            tables[table_name] = pd.DataFrame()
    return tables


def _symbols_from_table(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "ts_code" not in frame.columns:
        return set()
    return set(frame["ts_code"].dropna().astype(str).tolist())


def _symbols_at_date(frame: pd.DataFrame, target_date: str) -> set[str]:
    if not target_date or frame.empty or "ts_code" not in frame.columns or "trade_date" not in frame.columns:
        return set()
    return _symbols_from_table(frame[frame["trade_date"].astype(str) == str(target_date)])


def _latest_date(frame: pd.DataFrame, column: str) -> str | None:
    if frame.empty or column not in frame.columns:
        return None
    values = frame[column].dropna().astype(str)
    if values.empty:
        return None
    return str(values.max())


def _row_counts(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty or "ts_code" not in frame.columns:
        return {}
    counts = frame.groupby(frame["ts_code"].astype(str)).size()
    return {str(symbol): int(count) for symbol, count in counts.items()}


def _rate(count: int, total: int) -> float:
    return float(count / total) if total else 0.0


def _quality_status(rate: float) -> str:
    if rate >= 0.95:
        return "ok"
    if rate >= 0.80:
        return "warning"
    return "poor"
