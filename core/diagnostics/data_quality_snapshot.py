"""Unified read-only data quality snapshot for local DuckDB market data."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.storage.duckdb_store import DuckDBStore


WARNING_REASON = "最新交易日数据覆盖严重不足，当前结果仅供流程检查，不代表完整全市场筛选。"


def build_data_quality_snapshot(
    db_path: str | Path | None = None,
    research_trade_date: Any = "",
    latest_completed_trade_date: Any | None = None,
    configured_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Build a single read-only coverage snapshot.

    This function is the authoritative coverage source for CLI, scheduled
    updates, Streamlit, and Excel. It does not update market data or write to
    DuckDB.
    """
    store = DuckDBStore(db_path)
    with store.connect(read_only=True) as connection:
        target_date = normalize_trade_date(
            latest_completed_trade_date
            or research_trade_date
            or _scalar(connection, "SELECT MAX(CAST(trade_date AS VARCHAR)) FROM daily_price")
            or ""
        )
        research_date = normalize_trade_date(research_trade_date) or target_date
        configured_set = set(configured_symbols or _symbols(connection, "stock_basic"))
        if not configured_set:
            configured_set = set(_symbols(connection, "daily_price")) | set(_symbols(connection, "daily_basic")) | set(_symbols(connection, "adj_factor"))
        configured_count = len(configured_set)

        latest_price_symbols = _symbols_at_date(connection, "daily_price", target_date)
        latest_basic_symbols = _symbols_at_date(connection, "daily_basic", target_date)
        latest_adj_symbols = _symbols_at_date(connection, "adj_factor", target_date)
        latest_all_required = latest_price_symbols.intersection(latest_basic_symbols).intersection(latest_adj_symbols)

        latest_price_count = _count_at_date(connection, "daily_price", target_date)
        latest_basic_count = _count_at_date(connection, "daily_basic", target_date)
        latest_adj_count = _count_at_date(connection, "adj_factor", target_date)
        any_price_count = _count_any(connection, "daily_price")
        row_counts = _row_counts(connection, "daily_price")

        history_complete = [symbol for symbol in configured_set if row_counts.get(symbol, 0) >= 252]
        history_incomplete = [symbol for symbol in configured_set if 0 < row_counts.get(symbol, 0) < 252]
        history_missing = sorted(symbol for symbol in configured_set if row_counts.get(symbol, 0) <= 0)
        latest_price_configured = latest_price_symbols.intersection(configured_set)

        factor_ready = _symbols_at_date(connection, "factor_scores", target_date).intersection(configured_set)
        elder_ready = _symbols_at_date(connection, "watchlist_daily_snapshots", target_date).intersection(configured_set)
        entry_ready = _symbols_at_date(connection, "entry_zone_snapshots", target_date).intersection(configured_set)
        strategy_symbols = _symbols_at_date(connection, "strategy_result", target_date).intersection(configured_set)
        lookback_ready = {symbol for symbol in strategy_symbols if row_counts.get(symbol, 0) >= 80}

    latest_price_rate = _rate(latest_price_count, configured_count)
    status = _quality_status(latest_price_rate)
    formal_usable = status not in {"poor", "failed"}
    return {
        "data_quality_snapshot_source": "readonly_duckdb_sql",
        "data_quality_status": status,
        "formal_result_usable": formal_usable,
        "formal_result_warning_reason": "" if formal_usable else WARNING_REASON,
        "configured_symbol_count": configured_count,
        "research_trade_date": research_date,
        "latest_completed_trade_date": target_date,
        "latest_daily_price_symbol_count": latest_price_count,
        "missing_latest_daily_price_symbol_count": max(configured_count - latest_price_count, 0),
        "latest_daily_price_coverage_rate": latest_price_rate,
        "latest_daily_basic_symbol_count": latest_basic_count,
        "missing_latest_daily_basic_symbol_count": max(configured_count - latest_basic_count, 0),
        "latest_daily_basic_coverage_rate": _rate(latest_basic_count, configured_count),
        "latest_adj_factor_symbol_count": latest_adj_count,
        "missing_latest_adj_factor_symbol_count": max(configured_count - latest_adj_count, 0),
        "latest_adj_factor_coverage_rate": _rate(latest_adj_count, configured_count),
        "latest_all_required_tables_symbol_count": len(latest_all_required.intersection(configured_set)),
        "missing_latest_all_required_tables_symbol_count": max(configured_count - len(latest_all_required.intersection(configured_set)), 0),
        "latest_all_required_tables_coverage_rate": _rate(len(latest_all_required.intersection(configured_set)), configured_count),
        "any_daily_price_symbol_count": any_price_count,
        "missing_any_daily_price_symbol_count": max(configured_count - any_price_count, 0),
        "any_daily_price_coverage_rate": _rate(any_price_count, configured_count),
        "history_complete_symbol_count": len(history_complete),
        "history_incomplete_symbol_count": len(history_incomplete),
        "history_missing_symbol_count": max(configured_count - any_price_count, 0),
        "available_days_20d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 20),
        "available_days_60d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 60),
        "available_days_120d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 120),
        "available_days_252d_count": len(history_complete),
        "factor_ready_symbol_count": len(factor_ready),
        "elder_ready_symbol_count": len(elder_ready),
        "entry_zone_ready_symbol_count": len(entry_ready),
        "lookback_ready_symbol_count": len(lookback_ready),
        "missing_latest_daily_price_examples": sorted(configured_set - latest_price_configured)[:30],
        "missing_latest_daily_basic_examples": sorted(configured_set - latest_basic_symbols.intersection(configured_set))[:30],
        "missing_latest_adj_factor_examples": sorted(configured_set - latest_adj_symbols.intersection(configured_set))[:30],
        "history_missing_examples": history_missing[:30],
        "latest_updated_but_history_incomplete_count": sum(1 for symbol in latest_price_configured if row_counts.get(symbol, 0) < 252),
        "latest_updated_but_history_incomplete_examples": sorted(symbol for symbol in latest_price_configured if row_counts.get(symbol, 0) < 252)[:30],
        "history_complete_but_latest_missing_count": sum(1 for symbol in history_complete if symbol not in latest_price_configured),
        "history_complete_but_latest_missing_examples": sorted(symbol for symbol in history_complete if symbol not in latest_price_configured)[:30],
    }


def normalize_trade_date(value: Any) -> str:
    """Normalize common trade-date values into compact YYYYMMDD text."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else text


def trade_date_distribution(db_path: str | Path | None, table_name: str) -> list[dict[str, Any]]:
    """Return top 10 trade-date distribution rows for debugging."""
    store = DuckDBStore(db_path)
    try:
        with store.connect(read_only=True) as connection:
            rows = connection.execute(
                f"""
                SELECT trade_date, COUNT(DISTINCT ts_code) AS symbol_count
                FROM {table_name}
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT 10
                """
            ).fetchall()
    except Exception:
        return []
    return [{"trade_date": str(row[0]), "symbol_count": int(row[1] or 0)} for row in rows]


def debug_sql_counts(db_path: str | Path | None, target_date: Any) -> dict[str, Any]:
    """Return explicit SQL self-check counts for refresh command output."""
    date_text = normalize_trade_date(target_date)
    store = DuckDBStore(db_path)
    result: dict[str, Any] = {}
    try:
        with store.connect(read_only=True) as connection:
            for table_name in ["daily_price", "daily_basic", "adj_factor"]:
                result[f"{table_name}_latest_count"] = _count_at_date(connection, table_name, date_text)
                result[f"{table_name}_distribution"] = trade_date_distribution(db_path, table_name)
            result["any_daily_price_symbol_count"] = _count_any(connection, "daily_price")
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _symbols(connection: Any, table_name: str) -> set[str]:
    try:
        frame = connection.execute(f"SELECT DISTINCT ts_code FROM {table_name} WHERE ts_code IS NOT NULL").fetchdf()
    except Exception:
        return set()
    if frame.empty or "ts_code" not in frame.columns:
        return set()
    return set(frame["ts_code"].dropna().astype(str).tolist())


def _symbols_at_date(connection: Any, table_name: str, target_date: str) -> set[str]:
    if not target_date:
        return set()
    try:
        frame = connection.execute(
            f"""
            SELECT DISTINCT ts_code
            FROM {table_name}
            WHERE ts_code IS NOT NULL
              AND replace(CAST(trade_date AS VARCHAR), '-', '') = ?
            """,
            [target_date],
        ).fetchdf()
    except Exception:
        return set()
    if frame.empty or "ts_code" not in frame.columns:
        return set()
    return set(frame["ts_code"].dropna().astype(str).tolist())


def _count_at_date(connection: Any, table_name: str, target_date: str) -> int:
    if not target_date:
        return 0
    try:
        return int(
            connection.execute(
                f"""
                SELECT COUNT(DISTINCT ts_code)
                FROM {table_name}
                WHERE replace(CAST(trade_date AS VARCHAR), '-', '') = ?
                """,
                [target_date],
            ).fetchone()[0]
            or 0
        )
    except Exception:
        return 0


def _count_any(connection: Any, table_name: str) -> int:
    try:
        return int(connection.execute(f"SELECT COUNT(DISTINCT ts_code) FROM {table_name}").fetchone()[0] or 0)
    except Exception:
        return 0


def _row_counts(connection: Any, table_name: str) -> dict[str, int]:
    try:
        frame = connection.execute(
            f"""
            SELECT ts_code, COUNT(*) AS row_count
            FROM {table_name}
            WHERE ts_code IS NOT NULL
            GROUP BY ts_code
            """
        ).fetchdf()
    except Exception:
        return {}
    if frame.empty or "ts_code" not in frame.columns or "row_count" not in frame.columns:
        return {}
    return {str(row["ts_code"]): int(row["row_count"] or 0) for _, row in frame.iterrows()}


def _scalar(connection: Any, query: str) -> Any:
    try:
        row = connection.execute(query).fetchone()
    except Exception:
        return None
    return row[0] if row else None


def _rate(count: int, total: int) -> float:
    return float(count / total) if total else 0.0


def _quality_status(rate: float) -> str:
    if rate >= 0.95:
        return "ok"
    if rate >= 0.80:
        return "warning"
    return "poor"
