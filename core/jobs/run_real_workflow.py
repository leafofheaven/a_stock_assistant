"""Unified real-data workflow command with report export."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.config import Settings, get_settings
from core.jobs.diagnose_backtest import diagnose_backtest
from core.jobs.diagnose_factors import diagnose_factors
from core.jobs.diagnose_real_data import diagnose_real_data
from core.jobs.diagnose_review_history import diagnose_review_history
from core.jobs.diagnose_update_batch import diagnose_update_batch
from core.jobs.export_review_template import export_review_template
from core.jobs.export_selection_review import export_selection_review
from core.jobs.export_watchlist import export_watchlist
from core.jobs.export_watchlist_tracking_report import export_watchlist_tracking_report
from core.jobs.run_daily_selection import run_daily_selection
from core.jobs.track_watchlist import track_watchlist
from core.jobs.update_real_data import update_real_data
from core.review.decisions import summarize_review_decisions
from core.storage.duckdb_store import DuckDBStore
from core.reporting.workflow_report import (
    build_console_summary,
    build_workflow_report,
    save_workflow_report,
)

SUCCESS_STATUSES = {"success", "partial_success", "skipped"}


def run_real_workflow(
    *,
    skip_update: bool = False,
    no_backtest: bool = False,
    report_dir: Path | str = "reports",
    report_format: str = "markdown",
    export_selection_review_report: bool = False,
    export_review_template_report: bool = False,
    export_watchlist_report: bool = False,
    track_watchlist_enabled: bool = False,
    export_watchlist_tracking_report_enabled: bool = False,
    diagnose_review_history_enabled: bool = False,
    quiet: bool = False,
    settings: Settings | None = None,
    step_overrides: dict[str, Callable[[], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run the real-data workflow and export a Markdown or JSON report.

    Each step is isolated so one failure produces a failed step record while
    later diagnostics still run where possible. The workflow does not fetch any
    new data source beyond the existing update job and never places trades.
    """
    resolved_settings = settings or get_settings()
    overrides = step_overrides or {}
    started_at = datetime.now()
    steps: dict[str, dict[str, Any]] = {}

    if skip_update:
        steps["update_real_data"] = {
            "status": "skipped",
            "message": "--skip-update enabled.",
            "result": {"message": "已跳过 update_real_data。"},
        }
    else:
        steps["update_real_data"] = _run_step(
            "update_real_data",
            overrides.get("update_real_data", lambda: update_real_data(settings=resolved_settings)),
        )

    steps["diagnose_real_data"] = _run_step(
        "diagnose_real_data",
        overrides.get("diagnose_real_data", lambda: diagnose_real_data(settings=resolved_settings)),
    )
    steps["diagnose_update_batch"] = _run_step(
        "diagnose_update_batch",
        overrides.get("diagnose_update_batch", lambda: diagnose_update_batch(settings=resolved_settings)),
    )
    steps["diagnose_factors"] = _run_step(
        "diagnose_factors",
        overrides.get("diagnose_factors", lambda: diagnose_factors(settings=resolved_settings)),
    )
    steps["run_daily_selection"] = _run_step(
        "run_daily_selection",
        overrides.get("run_daily_selection", lambda: run_daily_selection(settings=resolved_settings)),
    )
    if no_backtest:
        steps["diagnose_backtest"] = {
            "status": "skipped",
            "message": "--no-backtest enabled.",
            "result": {"message": "已跳过 diagnose_backtest。"},
        }
    else:
        steps["diagnose_backtest"] = _run_step(
            "diagnose_backtest",
            overrides.get("diagnose_backtest", lambda: diagnose_backtest(settings=resolved_settings)),
        )
    if export_selection_review_report:
        steps["export_selection_review"] = _run_step(
            "export_selection_review",
            overrides.get(
                "export_selection_review",
                lambda: export_selection_review(
                    output_dir=report_dir,
                    report_format="all",
                    quiet=True,
                    settings=resolved_settings,
                ),
            ),
        )
    else:
        steps["export_selection_review"] = {
            "status": "skipped",
            "message": "--export-selection-review not enabled.",
            "result": {"message": "已跳过 selection_review 导出。"},
        }
    if export_review_template_report:
        steps["export_review_template"] = _run_step(
            "export_review_template",
            overrides.get(
                "export_review_template",
                lambda: export_review_template(output_dir=report_dir, quiet=True, settings=resolved_settings),
            ),
        )
    else:
        steps["export_review_template"] = {
            "status": "skipped",
            "message": "--export-review-template not enabled.",
            "result": {"message": "已跳过 review_template 导出。"},
        }
    if export_watchlist_report:
        steps["export_watchlist"] = _run_step(
            "export_watchlist",
            overrides.get(
                "export_watchlist",
                lambda: export_watchlist(output_dir=report_dir, report_format="all", quiet=True, settings=resolved_settings),
            ),
        )
    else:
        steps["export_watchlist"] = {
            "status": "skipped",
            "message": "--export-watchlist not enabled.",
            "result": {"message": "已跳过 watchlist 导出。"},
        }
    if track_watchlist_enabled:
        steps["track_watchlist"] = _run_step(
            "track_watchlist",
            overrides.get(
                "track_watchlist",
                lambda: track_watchlist(
                    output_dir=report_dir,
                    export_report=False,
                    quiet=True,
                    settings=resolved_settings,
                ),
            ),
        )
    else:
        steps["track_watchlist"] = {
            "status": "skipped",
            "message": "--track-watchlist not enabled.",
            "result": {"message": "已跳过观察池跟踪。"},
        }
    if export_watchlist_tracking_report_enabled:
        steps["export_watchlist_tracking"] = _run_step(
            "export_watchlist_tracking",
            overrides.get(
                "export_watchlist_tracking",
                lambda: export_watchlist_tracking_report(
                    output_dir=report_dir,
                    report_format="all",
                    quiet=True,
                    settings=resolved_settings,
                ),
            ),
        )
    else:
        steps["export_watchlist_tracking"] = {
            "status": "skipped",
            "message": "--export-watchlist-tracking not enabled.",
            "result": {"message": "已跳过观察池变化报告导出。"},
        }
    steps["review_decisions"] = _run_step(
        "review_decisions",
        overrides.get(
            "review_decisions",
            lambda: summarize_review_decisions(DuckDBStore(resolved_settings.duckdb_path)),
        ),
    )
    if diagnose_review_history_enabled:
        steps["diagnose_review_history"] = _run_step(
            "diagnose_review_history",
            overrides.get(
                "diagnose_review_history",
                lambda: diagnose_review_history(settings=resolved_settings, limit=10),
            ),
        )
    else:
        steps["diagnose_review_history"] = {
            "status": "skipped",
            "message": "--diagnose-review-history not enabled.",
            "result": {"message": "已跳过复核历史诊断。"},
        }

    finished_at = datetime.now()
    overall_status = _overall_status(steps)
    report = build_workflow_report(
        started_at=started_at,
        finished_at=finished_at,
        settings=resolved_settings,
        steps=steps,
        overall_status=overall_status,
    )
    report_path = save_workflow_report(report, report_dir=report_dir, report_format=report_format)
    result = {
        "status": overall_status,
        "report_path": str(report_path),
        "steps": steps,
        "report": report,
    }
    if not quiet:
        print(build_console_summary(report, report_path))
    return result


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and run the workflow."""
    parser = argparse.ArgumentParser(description="Run real-data workflow and export a report.")
    parser.add_argument("--skip-update", action="store_true", help="Skip update_real_data.")
    parser.add_argument("--no-backtest", action="store_true", help="Skip diagnose_backtest.")
    parser.add_argument("--report-dir", default="reports", help="Report output directory.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Report format.")
    parser.add_argument(
        "--export-selection-review",
        action="store_true",
        help="Also export candidate stock review reports.",
    )
    parser.add_argument(
        "--export-review-template",
        action="store_true",
        help="Also export manual review template CSV.",
    )
    parser.add_argument(
        "--export-watchlist",
        action="store_true",
        help="Also export watchlist reports.",
    )
    parser.add_argument(
        "--track-watchlist",
        action="store_true",
        help="Also create watchlist tracking snapshots.",
    )
    parser.add_argument(
        "--export-watchlist-tracking",
        action="store_true",
        help="Also export watchlist tracking change reports.",
    )
    parser.add_argument(
        "--diagnose-review-history",
        action="store_true",
        help="Also diagnose review decision history.",
    )
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    args = parser.parse_args(argv)

    run_real_workflow(
        skip_update=args.skip_update,
        no_backtest=args.no_backtest,
        report_dir=args.report_dir,
        report_format=args.format,
        export_selection_review_report=args.export_selection_review,
        export_review_template_report=args.export_review_template,
        export_watchlist_report=args.export_watchlist,
        track_watchlist_enabled=args.track_watchlist,
        export_watchlist_tracking_report_enabled=args.export_watchlist_tracking,
        diagnose_review_history_enabled=args.diagnose_review_history,
        quiet=args.quiet,
    )


def _run_step(name: str, func: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run one workflow step and convert exceptions into failed records."""
    try:
        result = func()
    except Exception as exc:
        return {"status": "failed", "message": f"{name} failed: {exc}", "result": {"error": str(exc)}}
    status = str(result.get("status") or _infer_status(name, result))
    return {"status": status, "message": str(result.get("message", "")), "result": result}


def _infer_status(name: str, result: dict[str, Any]) -> str:
    """Infer a step status for existing diagnostics that do not expose one."""
    if name == "diagnose_real_data":
        return "success" if result.get("is_ready_for_selection") else "partial_success"
    if name == "diagnose_update_batch":
        if result.get("priced_symbol_count", 0) == 0 and result.get("configured_symbol_count", 0) > 0:
            return "failed"
        return "partial_success" if result.get("missing_symbols") else "success"
    if name == "diagnose_factors":
        return "success" if result.get("total_score_non_null_count", 0) > 0 else "partial_success"
    if name == "run_daily_selection":
        return "success" if result.get("candidate_count", 0) > 0 else "partial_success"
    if name == "diagnose_backtest":
        return "success" if result.get("equity_curve_rows", 0) > 0 else "partial_success"
    if name == "export_selection_review":
        return "success" if result.get("generated_files") else "partial_success"
    if name == "export_review_template":
        return "success" if result.get("generated_files") else "partial_success"
    if name == "export_watchlist":
        return "success" if result.get("generated_files") else "partial_success"
    if name == "track_watchlist":
        return "success" if result.get("snapshot_count", 0) > 0 else str(result.get("status", "partial_success"))
    if name == "export_watchlist_tracking":
        return "success" if result.get("generated_files") else "partial_success"
    if name == "review_decisions":
        return "success"
    if name == "diagnose_review_history":
        return "success"
    return "success"


def _overall_status(steps: dict[str, dict[str, Any]]) -> str:
    """Return overall workflow status from step statuses."""
    statuses = [step.get("status", "failed") for step in steps.values()]
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "partial_success" for status in statuses):
        return "partial_success"
    return "success"


if __name__ == "__main__":
    main()
