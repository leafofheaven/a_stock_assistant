"""Export local position pool reports."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.positions.position_pool import build_positions_dataframe
from core.reporting.positions_report import build_console_summary, build_positions_report, save_positions_report
from core.storage.duckdb_store import DuckDBStore


def export_positions(
    *,
    output_dir: Path | str = "reports",
    report_format: str = "all",
    active_only: bool = False,
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Export local position pool to markdown/csv/json."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    positions = build_positions_dataframe(resolved_store, active_only=active_only)
    report = build_positions_report(
        metadata={
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_provider": resolved_settings.data_provider,
            "duckdb_path": str(resolved_store.db_path),
        },
        positions_df=positions,
        active_only=active_only,
    )
    files = save_positions_report(report, output_dir=output_dir, report_format=report_format)
    if not quiet:
        print(build_console_summary(report, files))
    return {"status": "success", "report": report, "generated_files": files}


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and export positions."""
    parser = argparse.ArgumentParser(description="Export local position pool reports.")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--format", choices=["markdown", "json", "csv", "all"], default="all")
    parser.add_argument("--active-only", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args(argv)
    export_positions(output_dir=args.output_dir, report_format=args.format, active_only=args.active_only)


if __name__ == "__main__":
    main()
