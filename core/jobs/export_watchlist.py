"""Export manual review watchlist reports."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.reporting.watchlist_report import build_console_summary, build_watchlist_report, save_watchlist_report
from core.review.decisions import build_watchlist_dataframe
from core.storage.duckdb_store import DuckDBStore


def export_watchlist(
    *,
    output_dir: Path | str = "reports",
    report_format: str = "all",
    active_only: bool = True,
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Export current watchlist to markdown/json/csv."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    watchlist = build_watchlist_dataframe(resolved_store, active_only=active_only)
    report = build_watchlist_report(
        metadata={
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_provider": resolved_settings.data_provider,
            "duckdb_path": str(resolved_store.db_path),
        },
        watchlist_df=watchlist,
        active_only=active_only,
    )
    files = save_watchlist_report(report, output_dir=output_dir, report_format=report_format)
    if not quiet:
        print(build_console_summary(report, files))
    return {"status": "success", "report": report, "generated_files": files}


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and export watchlist reports."""
    parser = argparse.ArgumentParser(description="Export watchlist reports.")
    parser.add_argument("--output-dir", default="reports", help="Output directory.")
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "csv", "all"],
        default="all",
        help="Report format.",
    )
    parser.add_argument("--active-only", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    export_watchlist(output_dir=args.output_dir, report_format=args.format, active_only=args.active_only)


if __name__ == "__main__":
    main()
