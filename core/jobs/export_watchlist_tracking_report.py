"""Export watchlist tracking change reports."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.reporting.watchlist_tracking_report import (
    build_console_summary,
    build_watchlist_tracking_report,
    save_watchlist_tracking_report,
)
from core.review.tracking import read_watchlist_snapshots
from core.storage.duckdb_store import DuckDBStore


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
    snapshots = read_watchlist_snapshots(resolved_store)
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


if __name__ == "__main__":
    main()
