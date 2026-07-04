"""Refresh scheduled daily update data-quality fields from local DuckDB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from core.diagnostics.data_quality_snapshot import build_data_quality_snapshot, debug_sql_counts, normalize_trade_date

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
    )
    refreshed = {**status, **snapshot}
    if path.exists() or status:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if output_format == "silent":
        return refreshed
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
    trade_date = str(status.get("latest_completed_trade_date") or status.get("research_trade_date") or "")
    debug = debug_sql_counts(db_path, trade_date)
    print("数据质量状态刷新")
    print(f"- db_path: {db_path}")
    print(f"- research_trade_date: {status.get('research_trade_date') or '暂无'}")
    print(f"- latest_completed_trade_date: {trade_date or '暂无'}")
    print(f"- configured_symbol_count: {status.get('configured_symbol_count', 0)}")
    for table_name in ["daily_price", "daily_basic", "adj_factor"]:
        _print_distribution(table_name, debug.get(f"{table_name}_distribution", []))
    print("- read_only SQL counts:")
    print(f"  daily_price {trade_date}: {debug.get('daily_price_latest_count', 0)}")
    print(f"  daily_basic {trade_date}: {debug.get('daily_basic_latest_count', 0)}")
    print(f"  adj_factor {trade_date}: {debug.get('adj_factor_latest_count', 0)}")
    print(f"  any_daily_price_symbol_count: {debug.get('any_daily_price_symbol_count', 0)}")
    print(f"- daily_price {trade_date}: {status.get('latest_daily_price_symbol_count', 0)}")
    print(f"- daily_basic {trade_date}: {status.get('latest_daily_basic_symbol_count', 0)}")
    print(f"- adj_factor {trade_date}: {status.get('latest_adj_factor_symbol_count', 0)}")
    print(f"- any_daily_price_symbol_count: {status.get('any_daily_price_symbol_count', 0)}")
    print(f"- history_missing_symbol_count: {status.get('history_missing_symbol_count', 0)}")
    print(f"- data_quality_status: {status.get('data_quality_status') or 'unknown'}")
    print(f"- formal_result_usable: {bool(status.get('formal_result_usable'))}")


def _print_distribution(table_name: str, rows: list[dict[str, Any]]) -> None:
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
