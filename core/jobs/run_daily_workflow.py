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
from core.jobs.doctor_daily_run import doctor_daily_run
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
from core.runtime.progress import ProgressCallback, emit_progress, print_progress
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
    doctor_before_run: bool = False,
    doctor_after_run: bool = False,
    stop_on_doctor_failure: bool = False,
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    step_overrides: dict[str, Callable[[], dict[str, Any]]] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the daily local workflow and export a summary report."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    overrides = step_overrides or {}
    started_at = datetime.now()
    steps: dict[str, dict[str, Any]] = {}
    emit_progress(progress, step="run_daily_workflow", current="start", message="开始一键日常工作流。")

    if doctor_before_run:
        steps["doctor_before_run"] = _run_progress_step(
            "doctor_before_run",
            overrides.get(
                "doctor_before_run",
                lambda: doctor_daily_run(pre_run=True, settings=resolved_settings, store=resolved_store),
            ),
            progress=progress,
        )
        if stop_on_doctor_failure and steps["doctor_before_run"]["status"] == "failed":
            finished_at = datetime.now()
            return _finish_workflow(
                started_at=started_at,
                finished_at=finished_at,
                settings=resolved_settings,
                steps=steps,
                top_n=top_n,
                report_dir=report_dir,
                report_format=report_format,
                quiet=quiet,
                progress=progress,
            )
    else:
        steps["doctor_before_run"] = _skipped("--doctor-before-run not enabled.")

    if backup_before_run:
        steps["backup_local_data"] = _run_progress_step(
            "backup_local_data",
            overrides.get("backup_local_data", lambda: backup_local_data(label="before_daily_workflow", settings=resolved_settings)),
            progress=progress,
        )
    else:
        steps["backup_local_data"] = _skipped("--backup-before-run not enabled.")

    if skip_update:
        steps["update_real_data"] = _skipped("--skip-update enabled.")
    else:
        steps["update_real_data"] = _run_progress_step(
            "update_real_data",
            overrides.get("update_real_data", lambda: update_real_data(settings=resolved_settings, store=resolved_store, progress=progress)),
            progress=progress,
        )

    steps["diagnose_data_quality"] = _run_progress_step(
        "diagnose_data_quality",
        overrides.get("diagnose_data_quality", lambda: diagnose_data_quality(settings=resolved_settings, store=resolved_store)),
        progress=progress,
    )
    steps["diagnose_factors"] = _run_progress_step(
        "diagnose_factors",
        overrides.get("diagnose_factors", lambda: diagnose_factors(settings=resolved_settings, store=resolved_store)),
        progress=progress,
    )
    steps["run_daily_selection"] = _run_progress_step(
        "run_daily_selection",
        overrides.get("run_daily_selection", lambda: run_daily_selection(settings=resolved_settings, store=resolved_store)),
        progress=progress,
    )
    steps["export_selection_review"] = _run_progress_step(
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
        progress=progress,
    )
    steps["refresh_watchlist_scores"] = _run_progress_step(
        "refresh_watchlist_scores",
        overrides.get(
            "refresh_watchlist_scores",
            lambda: refresh_watchlist_scores(quiet=True, settings=resolved_settings, store=resolved_store),
        ),
        progress=progress,
    )
    steps["diagnose_watchlist"] = _run_progress_step(
        "diagnose_watchlist",
        overrides.get("diagnose_watchlist", lambda: diagnose_watchlist(settings=resolved_settings, store=resolved_store)),
        progress=progress,
    )
    steps["export_watchlist"] = _run_progress_step(
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
        progress=progress,
    )
    if watchlist_tracking:
        steps["track_watchlist"] = _run_progress_step(
            "track_watchlist",
            overrides.get("track_watchlist", lambda: track_watchlist(quiet=True, settings=resolved_settings, store=resolved_store)),
            progress=progress,
        )
        steps["export_watchlist_tracking"] = _run_progress_step(
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
            progress=progress,
        )
    else:
        steps["track_watchlist"] = _skipped("--no-watchlist-tracking enabled.")
        steps["export_watchlist_tracking"] = _skipped("--no-watchlist-tracking enabled.")

    if doctor_after_run:
        steps["doctor_after_run"] = _run_progress_step(
            "doctor_after_run",
            overrides.get(
                "doctor_after_run",
                lambda: doctor_daily_run(post_run=True, settings=resolved_settings, store=resolved_store),
            ),
            progress=progress,
        )
    else:
        steps["doctor_after_run"] = _skipped("--doctor-after-run not enabled.")

    finished_at = datetime.now()
    return _finish_workflow(
        started_at=started_at,
        finished_at=finished_at,
        settings=resolved_settings,
        steps=steps,
        top_n=top_n,
        report_dir=report_dir,
        report_format=report_format,
        quiet=quiet,
        progress=progress,
    )


def _finish_workflow(
    *,
    started_at: datetime,
    finished_at: datetime,
    settings: Settings,
    steps: dict[str, dict[str, Any]],
    top_n: int,
    report_dir: Path | str,
    report_format: str,
    quiet: bool,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Build, save, and optionally print the daily workflow report."""
    overall_status = _overall_status(steps)
    report = build_daily_workflow_report(
        started_at=started_at,
        finished_at=finished_at,
        settings=settings,
        steps=steps,
        overall_status=overall_status,
        generated_files={},
        top_n=top_n,
    )
    daily_files = save_daily_workflow_report(report, output_dir=report_dir, report_format=report_format)
    emit_progress(
        progress,
        step="run_daily_workflow",
        current="finish",
        success=sum(1 for step in steps.values() if step.get("status") in SUCCESS_STATUSES),
        failed=sum(1 for step in steps.values() if step.get("status") == "failed"),
        skipped=sum(1 for step in steps.values() if step.get("status") == "skipped"),
        message=f"工作流完成，状态 {overall_status}，报告 {', '.join(daily_files.values())}。",
    )
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
    parser.add_argument("--doctor-before-run", action="store_true", help="Run doctor_daily_run before the workflow.")
    parser.add_argument("--doctor-after-run", action="store_true", help="Run doctor_daily_run after the workflow.")
    parser.add_argument("--stop-on-doctor-failure", action="store_true", help="Stop if the pre-run doctor fails.")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    args = parser.parse_args(argv)
    run_daily_workflow(
        skip_update=args.skip_update,
        backup_before_run=args.backup_before_run,
        top_n=args.top_n,
        report_format=args.format,
        report_dir=args.report_dir,
        watchlist_tracking=not args.no_watchlist_tracking,
        doctor_before_run=args.doctor_before_run,
        doctor_after_run=args.doctor_after_run,
        stop_on_doctor_failure=args.stop_on_doctor_failure,
        quiet=args.quiet,
        progress=print_progress,
    )


def _run_progress_step(
    name: str,
    func: Callable[[], dict[str, Any]],
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run one workflow step and emit start/finish progress lines."""
    emit_progress(progress, step=name, current=name, message=f"开始执行 {name}。")
    result = _run_step(name, func)
    status = result.get("status", "failed")
    emit_progress(
        progress,
        step=name,
        current=name,
        success=1 if status in SUCCESS_STATUSES else 0,
        failed=1 if status == "failed" else 0,
        skipped=1 if status == "skipped" else 0,
        message=f"完成 {name}，状态 {status}。",
    )
    return result


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
    if name in {"doctor_before_run", "doctor_after_run"}:
        return str(result.get("status", "success"))
    return "success"


def _overall_status(steps: dict[str, dict[str, Any]]) -> str:
    statuses = [step.get("status", "failed") for step in steps.values()]
    if any(status == "failed" for status in statuses):
        return "partial_success" if any(status in SUCCESS_STATUSES for status in statuses) else "failed"
    if any(status == "warning" for status in statuses):
        return "partial_success"
    if any(status == "partial_success" for status in statuses):
        return "partial_success"
    return "success"


def _skipped(message: str) -> dict[str, Any]:
    return {"status": "skipped", "message": message, "result": {"message": message}}


if __name__ == "__main__":
    main()
