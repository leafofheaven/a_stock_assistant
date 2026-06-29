"""Export watchlist tracking change reports."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.reporting.watchlist_tracking_report import (
    build_console_summary,
    build_watchlist_tracking_report,
    save_watchlist_tracking_report,
)
from core.review.tracking import read_watchlist_daily_snapshots, read_watchlist_snapshots
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


def export_watchlist_tracking_report(
    *,
    output_dir: Path | str = "reports",
    report_format: str = "all",
    latest_only: bool = True,
    since: str | None = None,
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Export watchlist snapshot change reports from local DuckDB data."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    snapshots = read_watchlist_daily_snapshots(resolved_store)
    if snapshots.empty:
        snapshots = read_watchlist_snapshots(resolved_store)
    snapshots = _attach_basic_fields(snapshots, resolved_store)
    report = build_watchlist_tracking_report(
        metadata={
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_provider": resolved_settings.data_provider,
            "duckdb_path": str(resolved_store.db_path),
        },
        snapshots_df=snapshots,
        latest_only=latest_only,
        since=since,
    )
    files = save_watchlist_tracking_report(report, output_dir=output_dir, report_format=report_format)
    result = {"status": "success", "report": report, "generated_files": files}
    if not quiet:
        print(build_console_summary(report, files))
    return result


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and export watchlist tracking reports."""
    parser = argparse.ArgumentParser(description="Export watchlist tracking reports.")
    parser.add_argument("--output-dir", default="reports", help="Output directory.")
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "csv", "all"],
        default="all",
        help="Report format.",
    )
    parser.add_argument("--latest-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--since", help="Only compare snapshots on or after YYYYMMDD.")
    args = parser.parse_args(argv)
    export_watchlist_tracking_report(
        output_dir=args.output_dir,
        report_format=args.format,
        latest_only=args.latest_only,
        since=args.since,
    )


def _attach_basic_fields(snapshots: pd.DataFrame, store: DuckDBStore) -> pd.DataFrame:
    """Attach descriptive local fields for report output without changing snapshots."""
    if snapshots.empty or "ts_code" not in snapshots.columns:
        return snapshots.copy()
    result = snapshots.copy()
    stock_basic = _safe_read_table(store, "stock_basic")
    if not stock_basic.empty and "ts_code" in stock_basic.columns:
        fields = ["industry", "market", "list_date"]
        columns = ["ts_code", *[field for field in fields if field in stock_basic.columns]]
        basic = stock_basic[columns].drop_duplicates(subset=["ts_code"], keep="last")
        result = result.merge(basic, on="ts_code", how="left", suffixes=("", "_stock_basic"))
        for field in fields:
            stock_field = f"{field}_stock_basic"
            if field not in result.columns:
                result[field] = pd.NA
            if stock_field in result.columns:
                result[field] = result[field].where(~result[field].map(_is_missing), result[stock_field])
                result = result.drop(columns=[stock_field])
    daily_basic = _safe_read_table(store, "daily_basic")
    if not daily_basic.empty and {"ts_code", "trade_date"}.issubset(daily_basic.columns):
        fields = ["pe", "pb"]
        rows: list[dict[str, Any]] = []
        for item in result.to_dict("records"):
            ts_code = str(item.get("ts_code", ""))
            latest_date = str(item.get("latest_trade_date") or item.get("snapshot_date") or item.get("trade_date") or "")
            latest_basic = daily_basic[daily_basic["ts_code"].astype(str) == ts_code].copy()
            if latest_date:
                latest_basic = latest_basic[latest_basic["trade_date"].astype(str) <= latest_date]
            if not latest_basic.empty:
                basic_row = latest_basic.sort_values("trade_date").iloc[-1].to_dict()
                for field in fields:
                    if _is_missing(item.get(field)):
                        item[field] = basic_row.get(field)
            rows.append(item)
        result = pd.DataFrame(rows)
    return result


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"", "nan", "none", "<na>", "null"}


if __name__ == "__main__":
    main()
