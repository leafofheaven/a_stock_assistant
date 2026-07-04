"""Refresh scheduled daily update data-quality fields from local DuckDB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from core.diagnostics.data_quality_snapshot import build_data_quality_snapshot, normalize_trade_date
from core.storage.duckdb_store import DuckDBStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS_PATH = PROJECT_ROOT / "data" / "runtime" / "scheduled_daily_update_status.json"


def refresh_data_quality_status(
    *,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    output_format: str = "text",
) -> dict[str, Any]:
    """Read-only refresh of scheduled update quality fields, then update status JSON."""
    path = Path(status_path)
    status = _read_status(path)
    settings = get_settings()
    research_trade_date = normalize_trade_date(status.get("research_trade_date") or status.get("trade_date") or "")
    latest_completed_trade_date = normalize_trade_date(status.get("latest_completed_trade_date") or research_trade_date)
    snapshot = build_data_quality_snapshot(
        db_path=settings.duckdb_path,
        research_trade_date=research_trade_date,
        latest_completed_trade_date=latest_completed_trade_date,
        run_date=str(status.get("run_date") or ""),
    )
    refreshed = {**status, **snapshot}
    if path.exists() or status:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if output_format == "json":
        print(json.dumps(refreshed, ensure_ascii=False, indent=2, default=str))
    else:
        _print_text(refreshed, settings.duckdb_path)
    return refreshed


def _read_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _print_text(status: dict[str, Any], db_path: Path) -> None:
    trade_date = status.get("latest_completed_trade_date") or status.get("research_trade_date") or "暂无"
    sql_debug = _read_sql_debug_counts(db_path, str(trade_date))
    print("数据质量状态刷新")
    print(f"- db_path: {db_path}")
    print(f"- research_trade_date: {status.get('research_trade_date') or '暂无'}")
    print(f"- latest_completed_trade_date: {trade_date}")
    print(f"- configured_symbol_count: {status.get('configured_symbol_count', 0)}")
    _print_trade_date_distribution("daily_price", sql_debug.get("daily_price_distribution", []))
    _print_trade_date_distribution("daily_basic", sql_debug.get("daily_basic_distribution", []))
    _print_trade_date_distribution("adj_factor", sql_debug.get("adj_factor_distribution", []))
    print("- read_only SQL counts:")
    print(f"  daily_price {trade_date}: {sql_debug.get('daily_price_latest_count', 0)}")
    print(f"  daily_basic {trade_date}: {sql_debug.get('daily_basic_latest_count', 0)}")
    print(f"  adj_factor {trade_date}: {sql_debug.get('adj_factor_latest_count', 0)}")
    print(f"  any_daily_price_symbol_count: {sql_debug.get('any_daily_price_symbol_count', 0)}")
    print(f"- daily_price {trade_date}: {status.get('latest_daily_price_symbol_count', 0)}")
    print(f"- daily_basic {trade_date}: {status.get('latest_daily_basic_symbol_count', 0)}")
    print(f"- adj_factor {trade_date}: {status.get('latest_adj_factor_symbol_count', 0)}")
    print(f"- any_daily_price_symbol_count: {status.get('any_daily_price_symbol_count', 0)}")
    print(f"- data_quality_status: {status.get('data_quality_status') or 'unknown'}")
    print(f"- formal_result_usable: {bool(status.get('formal_result_usable'))}")


def _read_sql_debug_counts(db_path: Path, trade_date: str) -> dict[str, Any]:
    """Return explicit read-only SQL counts used to verify snapshot coverage."""
    result: dict[str, Any] = {}
    store = DuckDBStore(db_path)
    try:
        with store.connect(read_only=True) as connection:
            for table_name in ["daily_price", "daily_basic", "adj_factor"]:
                result[f"{table_name}_distribution"] = _trade_date_distribution(connection, table_name)
                result[f"{table_name}_latest_count"] = _latest_symbol_count(connection, table_name, trade_date)
            result["any_daily_price_symbol_count"] = _any_symbol_count(connection, "daily_price")
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _trade_date_distribution(connection: Any, table_name: str) -> list[dict[str, Any]]:
    try:
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


def _latest_symbol_count(connection: Any, table_name: str, trade_date: str) -> int:
    try:
        return int(
            connection.execute(
                f"""
                SELECT COUNT(DISTINCT ts_code)
                FROM {table_name}
                WHERE replace(CAST(trade_date AS VARCHAR), '-', '') = ?
                """,
                [trade_date],
            ).fetchone()[0]
            or 0
        )
    except Exception:
        return 0


def _any_symbol_count(connection: Any, table_name: str) -> int:
    try:
        return int(connection.execute(f"SELECT COUNT(DISTINCT ts_code) FROM {table_name}").fetchone()[0] or 0)
    except Exception:
        return 0


def _print_trade_date_distribution(table_name: str, rows: list[dict[str, Any]]) -> None:
    print(f"- {table_name} trade_date 分布 top 10:")
    if not rows:
        print("  暂无")
        return
    for row in rows:
        print(f"  {row.get('trade_date')}: {row.get('symbol_count', 0)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh scheduled update data-quality status from DuckDB.")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--status-path", default=str(DEFAULT_STATUS_PATH))
    args = parser.parse_args()
    refresh_data_quality_status(status_path=args.status_path, output_format=args.format)


if __name__ == "__main__":
    main()
