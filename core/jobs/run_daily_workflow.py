"""One-command daily workflow for local candidate and watchlist reports."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.config import Settings, get_settings
from core.jobs.backup_local_data import backup_local_data
from core.jobs.diagnose_data_quality import diagnose_data_quality
from core.jobs.diagnose_factors import diagnose_factors
from core.jobs.diagnose_watchlist import diagnose_watchlist
from core.jobs.export_selection_review import export_selection_review
from core.jobs.export_watchlist import export_watchlist
from core.jobs.export_watchlist_tracking_report import export_watchlist_tracking_report
from core.jobs.refresh_watchlist_scores import refresh_watchlist_scores
from core.jobs.run_daily_selection import run_daily_selection
from core.jobs.track_watchlist import track_watchlist
from core.jobs.update_real_data import update_real_data
from core.reporting.daily_workflow_report import (
    build_console_summary,
    build_daily_workflow_report,
    save_daily_workflow_report,
)
from core.storage.duckdb_store import DuckDBStore

SUCCESS_STATUSES = {"success", "skipped", "dry_run"}


def run_daily_workflow(
    *,
    skip_update: bool = False,
    backup_before_run: bool = False,
    top_n: int = 10,
    report_format: str = "all",
    report_dir: Path | str = "reports",
    watchlist_tracking: bool = True,
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    step_overrides: dict[str, Callable[[], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run the daily local workflow and export a summary report."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    overrides = step_overrides or {}
    started_at = datetime.now()
    steps: dict[str, dict[str, Any]] = {}

    if backup_before_run:
        steps["backup_local_data"] = _run_step(
            "backup_local_data",
            overrides.get("backup_local_data", lambda: backup_local_data(label="before_daily_workflow", settings=resolved_settings)),
        )
    else:
        steps["backup_local_data"] = _skipped("--backup-before-run not enabled.")

    if skip_update:
        steps["update_real_data"] = _skipped("--skip-update enabled.")
    else:
        steps["update_real_data"] = _run_step(
            "update_real_data",
            overrides.get("update_real_data", lambda: update_real_data(settings=resolved_settings, store=resolved_store)),
        )

    steps["diagnose_data_quality"] = _run_step(
        "diagnose_data_quality",
        overrides.get("diagnose_data_quality", lambda: diagnose_data_quality(settings=resolved_settings, store=resolved_store)),
    )
    steps["diagnose_factors"] = _run_step(
        "diagnose_factors",
        overrides.get("diagnose_factors", lambda: diagnose_factors(settings=resolved_settings, store=resolved_store)),
    )
    steps["run_daily_selection"] = _run_step(
        "run_daily_selection",
        overrides.get("run_daily_selection", lambda: run_daily_selection(settings=resolved_settings, store=resolved_store)),
    )
    steps["export_selection_review"] = _run_step(
        "export_selection_review",
        overrides.get(
            "export_selection_review",
            lambda: export_selection_review(
                top_n=top_n,
                output_dir=report_dir,
                report_format=report_format,
                quiet=True,
                settings=resolved_settings,
                store=resolved_store,
            ),
        ),
    )
    steps["refresh_watchlist_scores"] = _run_step(
        "refresh_watchlist_scores",
        overrides.get(
            "refresh_watchlist_scores",
            lambda: refresh_watchlist_scores(quiet=True, settings=resolved_settings, store=resolved_store),
        ),
    )
    steps["diagnose_watchlist"] = _run_step(
        "diagnose_watchlist",
        overrides.get("diagnose_watchlist", lambda: diagnose_watchlist(settings=resolved_settings, store=resolved_store)),
    )
    steps["export_watchlist"] = _run_step(
        "export_watchlist",
        overrides.get(
            "export_watchlist",
            lambda: export_watchlist(
                output_dir=report_dir,
                report_format=report_format,
                quiet=True,
                settings=resolved_settings,
                store=resolved_store,
            ),
        ),
    )
    if watchlist_tracking:
        steps["track_watchlist"] = _run_step(
            "track_watchlist",
            overrides.get("track_watchlist", lambda: track_watchlist(quiet=True, settings=resolved_settings, store=resolved_store)),
        )
        steps["export_watchlist_tracking"] = _run_step(
            "export_watchlist_tracking",
            overrides.get(
                "export_watchlist_tracking",
                lambda: export_watchlist_tracking_report(
                    output_dir=report_dir,
                    report_format=report_format,
                    quiet=True,
                    settings=resolved_settings,
                    store=resolved_store,
                ),
            ),
        )
    else:
        steps["track_watchlist"] = _skipped("--no-watchlist-tracking enabled.")
        steps["export_watchlist_tracking"] = _skipped("--no-watchlist-tracking enabled.")

    finished_at = datetime.now()
    overall_status = _overall_status(steps)
    report = build_daily_workflow_report(
        started_at=started_at,
        finished_at=finished_at,
        settings=resolved_settings,
        steps=steps,
        overall_status=overall_status,
        generated_files={},
        top_n=top_n,
    )
    daily_files = save_daily_workflow_report(report, output_dir=report_dir, report_format=report_format)
    result = {
        "status": overall_status,
        "report": report,
        "report_paths": daily_files,
        "steps": steps,
    }
    if not quiet:
        print(build_console_summary(report, daily_files))
    return result


def main(argv: list[str] | None = None) -> None:
    """Parse command line arguments and run the daily workflow."""
    parser = argparse.ArgumentParser(description="Run daily local workflow and export a summary report.")
    parser.add_argument("--skip-update", action="store_true", help="Skip update_real_data.")
    parser.add_argument("--backup-before-run", action="store_true", help="Create local backup before running.")
    parser.add_argument("--top-n", type=int, default=10, help="Number of candidates for selection review.")
    parser.add_argument("--format", choices=["markdown", "json", "csv", "all"], default="all", help="Daily/report export format.")
    parser.add_argument("--report-dir", default="reports", help="Report output directory.")
    parser.add_argument("--no-watchlist-tracking", action="store_true", help="Skip watchlist tracking snapshot and report.")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    args = parser.parse_args(argv)
    run_daily_workflow(
        skip_update=args.skip_update,
        backup_before_run=args.backup_before_run,
        top_n=args.top_n,
        report_format=args.format,
        report_dir=args.report_dir,
        watchlist_tracking=not args.no_watchlist_tracking,
        quiet=args.quiet,
    )


def _run_step(name: str, func: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = func()
    except Exception as exc:
        return {"name": name, "status": "failed", "message": f"{name} failed: {exc}", "result": {"error": str(exc)}}
    status = str(result.get("status") or _infer_status(name, result))
    return {"name": name, "status": status, "message": str(result.get("message", "")), "result": result}


def _infer_status(name: str, result: dict[str, Any]) -> str:
    if name == "diagnose_data_quality":
        return "success" if result.get("status") in {None, "success"} else str(result.get("status"))
    if name == "diagnose_factors":
        return "success" if result.get("total_score_non_null_count", 0) > 0 else "partial_success"
    if name == "run_daily_selection":
        return "success" if result.get("candidate_count", 0) > 0 else "partial_success"
    if name in {"export_selection_review", "export_watchlist", "export_watchlist_tracking"}:
        return "success" if result.get("generated_files") else "partial_success"
    if name == "refresh_watchlist_scores":
        return "success" if result.get("status") in {"success", "dry_run"} else str(result.get("status", "partial_success"))
    if name == "track_watchlist":
        return "success" if result.get("snapshot_count", 0) > 0 else str(result.get("status", "partial_success"))
    if name == "backup_local_data":
        return "success" if result.get("backup_dir") else "partial_success"
    if name == "update_real_data":
        return str(result.get("status", "success"))
    if name == "diagnose_watchlist":
        return "success"
    return "success"


def _overall_status(steps: dict[str, dict[str, Any]]) -> str:
    statuses = [step.get("status", "failed") for step in steps.values()]
    if any(status == "failed" for status in statuses):
        return "partial_success" if any(status in SUCCESS_STATUSES for status in statuses) else "failed"
    if any(status == "partial_success" for status in statuses):
        return "partial_success"
    return "success"


def _skipped(message: str) -> dict[str, Any]:
    return {"status": "skipped", "message": message, "result": {"message": message}}


if __name__ == "__main__":
    main()
