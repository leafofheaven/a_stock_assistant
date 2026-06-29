"""Track active local positions with daily price and Elder state."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.positions.position_pool import track_active_positions
from core.reporting.positions_report import build_console_summary, build_positions_report, save_positions_report
from core.storage.duckdb_store import DuckDBStore


def track_positions(
    *,
    output_dir: Path | str = "reports",
    report_format: str = "all",
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Track active positions and export daily tracking reports."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    tracked = track_active_positions(resolved_store)
    report = build_positions_report(
        metadata={
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_provider": resolved_settings.data_provider,
            "duckdb_path": str(resolved_store.db_path),
            "report_type": "position_tracking",
        },
        positions_df=tracked,
        active_only=True,
    )
    files = save_positions_report(report, output_dir=output_dir, report_format=report_format)
    if not quiet:
        print("持仓每日跟踪摘要")
        print(build_console_summary(report, files))
    return {"status": "success", "tracked_df": tracked, "report": report, "generated_files": files}


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and track active positions."""
    parser = argparse.ArgumentParser(description="Track active local positions.")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--format", choices=["markdown", "json", "csv", "all"], default="all")
    args = parser.parse_args(argv)
    track_positions(output_dir=args.output_dir, report_format=args.format)


if __name__ == "__main__":
    main()
