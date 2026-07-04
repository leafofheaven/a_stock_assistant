"""Scheduled 18:00 local daily update workflow."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time as time_module
from typing import Any, Callable, Iterator

from app.config import Settings, get_settings
from core.jobs.backup_local_data import backup_local_data
from core.jobs.calculate_entry_zones import calculate_entry_zones
from core.jobs.export_daily_research_workbook import export_daily_research_workbook
from core.jobs.run_daily_workflow import run_daily_workflow
from core.jobs.run_elder_review import run_elder_review
from core.jobs.track_watchlist import track_watchlist
from core.notifications.email import send_email_notification
from core.notifications.macos import send_macos_notification
from core.runtime.data_source_preflight import run_data_source_preflight
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS_PATH = PROJECT_ROOT / "data" / "runtime" / "scheduled_daily_update_status.json"
DEFAULT_LOCK_PATH = PROJECT_ROOT / "data" / "runtime" / "scheduled_daily_update.lock"
DUCKDB_LOCK_USER_MESSAGE = "DuckDB is locked by another process. Please stop other running jobs or Streamlit first."
SUCCESS_STATUSES = {"success", "warning", "success_with_notification_warning"}
WARNING_STATUSES = {"warning", "partial_success", "success_with_warnings"}
DEFAULT_UPDATE_LIMIT = 0
DEFAULT_UPDATE_BATCH_SIZE = 50
DEFAULT_UPDATE_LOOKBACK_DAYS = 250
DEFAULT_UPDATE_MAX_RETRIES = 1
DEFAULT_DAILY_INCREMENTAL_RECENT_DAYS = 5
DEFAULT_DAILY_INCREMENTAL_MAX_SYMBOLS = 800
DEFAULT_STAGE_TIMEOUT_SECONDS = 900
# Environment counterpart: FULL_BATCH_UPDATE_TIMEOUT_SECONDS.
DEFAULT_UPDATE_STAGE_TIMEOUT_SECONDS = 1800
DEFAULT_LOCK_STALE_SECONDS = 6 * 60 * 60
DEFAULT_HEARTBEAT_SECONDS = 10


@dataclass(frozen=True)
class StageCommand:
    name: str
    command: list[str]
    timeout_seconds: int
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class ScheduleDecision:
    should_run: bool
    status: str
    summary: str
    is_trade_day: bool
    already_ran_today: bool
    catch_up: bool


def run_scheduled_daily_update(
    *,
    scheduled_time: str = "18:00",
    catch_up: bool = True,
    force: bool = False,
    dry_run: bool = False,
    notify: bool = True,
    skip_notify: bool = False,
    output_format: str = "text",
    status_path: str | Path = DEFAULT_STATUS_PATH,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    report_dir: str | Path = "reports",
    update_limit: int = DEFAULT_UPDATE_LIMIT,
    update_batch_size: int = DEFAULT_UPDATE_BATCH_SIZE,
    update_lookback_days: int = DEFAULT_UPDATE_LOOKBACK_DAYS,
    update_max_retries: int = DEFAULT_UPDATE_MAX_RETRIES,
    update_mode: str = "daily_incremental",
    recent_days: int = DEFAULT_DAILY_INCREMENTAL_RECENT_DAYS,
    max_update_symbols: int = 0,
    continue_on_symbol_failure: bool = True,
    stage_timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS,
    update_stage_timeout_seconds: int | None = None,
    verbose: bool = False,
    allow_intraday: bool = False,
    now: datetime | None = None,
    settings: Settings | None = None,
    step_overrides: dict[str, Callable[[], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run the scheduled daily update if schedule, state, and preflight allow it."""
    resolved_settings = settings or get_settings()
    update_mode = _normalize_update_mode(update_mode)
    started_at = now or datetime.now()
    status_file = Path(status_path)
    lock_file = Path(lock_path)
    logs: list[str] = []
    if output_format == "text":
        print("收盘后自动更新", flush=True)
    _emit_stage(
        output_format,
        "启动",
        f"force={str(force).lower()}, dry_run={str(dry_run).lower()}, update_limit={update_limit}, stage_timeout_seconds={stage_timeout_seconds}, allow_intraday={str(allow_intraday).lower()}",
    )
    _emit_stage(output_format, "检查上次运行状态", str(status_file))
    previous = read_scheduled_status(status_file)
    previous_run_interrupted = _previous_run_interrupted(previous, lock_file)
    previous_formal_success_date = str(previous.get("formal_success_date") or "")
    _emit_stage(output_format, "判断交易日", started_at.strftime("%Y-%m-%d"))
    decision = should_run_scheduled_update(
        now=started_at,
        scheduled_time=scheduled_time,
        previous_status=previous,
        force=force,
        catch_up=catch_up,
        settings=resolved_settings,
    )
    completed_trade_date = _latest_completed_trade_date(started_at, scheduled_time=scheduled_time, allow_intraday=allow_intraday, settings=resolved_settings)
    intraday_warning = _intraday_warning(started_at, scheduled_time=scheduled_time, allow_intraday=allow_intraday, settings=resolved_settings)
    after_scheduled_time = _is_after_scheduled_time(started_at, scheduled_time)
    formal_run_note = _formal_run_note(started_at, scheduled_time=scheduled_time)
    _emit_stage(output_format, "检查是否已到计划时间", decision.summary)
    base_status = _base_status(
        scheduled_time=scheduled_time,
        started_at=started_at,
        force=force,
        catch_up=catch_up,
        decision=decision,
        previous_run_interrupted=previous_run_interrupted,
        research_trade_date=completed_trade_date,
        intraday_warning=intraday_warning,
        allow_intraday=allow_intraday,
        previous_formal_success_date=previous_formal_success_date,
    )
    base_status["update_limit"] = int(update_limit) if int(update_limit) > 0 else None
    base_status["acceptance_mode"] = int(update_limit) > 0
    base_status["formal_run"] = _is_formal_run(
        update_limit=update_limit,
        allow_intraday=allow_intraday,
        intraday_warning=intraday_warning,
        dry_run=dry_run,
        after_scheduled_time=after_scheduled_time,
    )
    base_status["formal_run_note"] = formal_run_note
    base_status["update_mode"] = update_mode
    base_status["recent_days"] = int(recent_days)
    base_status["max_update_symbols"] = int(max_update_symbols)
    base_status["continue_on_symbol_failure"] = bool(continue_on_symbol_failure)
    if not decision.should_run and not force:
        status = {
            **base_status,
            "status": decision.status,
            "summary": decision.summary,
            "stage": "skipped",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_scheduled_status(status_file, status)
        _print_status(status, output_format)
        return status

    try:
        _emit_stage(output_format, "检查运行锁", str(lock_file))
        with scheduled_update_lock(lock_file) as lock_info:
            status = {
                **base_status,
                "status": "running",
                "summary": "自动更新运行中。",
                "stage": "preflight",
                "stale_lock_cleaned": bool(lock_info.get("stale_lock_cleaned")),
            }
            write_scheduled_status(status_file, status)
            _emit_stage(output_format, "DuckDB read_only 检查", "作为数据源预检的一部分执行。")
            _emit_stage(output_format, "数据源网络诊断", "开始。")
            preflight = (step_overrides or {}).get("preflight", lambda: run_data_source_preflight(settings=resolved_settings))()
            logs.append(f"preflight: {preflight.get('status')}")
            status.update(
                {
                    "diagnosis_status": _diagnosis_status(preflight),
                    "preflight_status": _diagnosis_status(preflight),
                    "preflight_allows_run": _preflight_allows_run(preflight),
                    "preflight_warning_reason": str(preflight.get("preflight_warning_reason") or ""),
                    "curl_fallback_available": bool(preflight.get("curl_fallback_available")),
                    "duckdb_status": _duckdb_status(preflight),
                    "eastmoney_status": _eastmoney_status(preflight),
                    "suggested_action": preflight.get("suggested_action") or "；".join(preflight.get("suggestions", [])),
                }
            )
            if status.get("preflight_warning_reason"):
                _emit_stage(output_format, "数据源网络诊断", f"{status['diagnosis_status']}：{status['preflight_warning_reason']}，继续执行 {update_mode}。")
            if not status["preflight_allows_run"]:
                status.update(
                    {
                        "status": "failed",
                        "summary": "数据源预检失败，未启动重型数据更新。",
                        "stage": "preflight",
                        "failure_reason": preflight.get("message", "preflight failed"),
                        "finished_at": datetime.now().isoformat(timespec="seconds"),
                        "logs": logs,
                    }
                )
                write_scheduled_status(status_file, status)
                _notify_if_needed(status, notify=notify and not skip_notify, dry_run=dry_run)
                _print_status(status, output_format)
                return status

            if dry_run:
                status.update(
                    {
                        "status": "skipped",
                        "summary": "dry-run：预检通过，将执行备份、数据更新、重算、埃尔德复核、买入区间、观察池跟踪和 Excel 导出。",
                        "stage": "dry_run",
                        "finished_at": datetime.now().isoformat(timespec="seconds"),
                        "logs": logs,
                    }
                )
                write_scheduled_status(status_file, status)
                _emit_stage(output_format, "完成", "dry-run 未执行重型更新。")
                _print_status(status, output_format)
                return status

            status = _run_heavy_steps(
                status=status,
                logs=logs,
                settings=resolved_settings,
                report_dir=report_dir,
                status_path=status_file,
                update_limit=update_limit,
                update_batch_size=update_batch_size,
                update_lookback_days=update_lookback_days,
                update_max_retries=update_max_retries,
                update_mode=update_mode,
                recent_days=recent_days,
                max_update_symbols=max_update_symbols,
                continue_on_symbol_failure=continue_on_symbol_failure,
                stage_timeout_seconds=stage_timeout_seconds,
                update_stage_timeout_seconds=update_stage_timeout_seconds
                or int(getattr(resolved_settings, "full_batch_update_timeout_seconds", DEFAULT_UPDATE_STAGE_TIMEOUT_SECONDS) or DEFAULT_UPDATE_STAGE_TIMEOUT_SECONDS),
                verbose=verbose,
                output_format=output_format,
                research_trade_date=completed_trade_date,
                step_overrides=step_overrides or {},
            )
            status["finished_at"] = datetime.now().isoformat(timespec="seconds")
            notification_requested = notify and not skip_notify
            _emit_stage(output_format, "通知", "发送本地通知。")
            status["notification"] = _notify_if_needed(status, notify=notification_requested, dry_run=False)
            if notification_requested and status["notification"].get("email_status") in {"failed", "skipped"} and status.get("status") == "success":
                status["status"] = "warning"
                status["summary"] = f"{status['summary']} 邮件通知未完成。"
            write_scheduled_status(status_file, status)
            _emit_stage(output_format, "完成", status.get("summary", ""))
            _print_status(status, output_format)
            return status
    except KeyboardInterrupt:
        status = {
            **base_status,
            "status": "interrupted",
            "summary": "用户中断自动更新。",
            "stage": "interrupted",
            "failure_reason": "用户中断自动更新。",
            "suggested_action": "已释放 lock，可稍后重新运行自动更新。",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
        _safe_unlink(lock_file)
        write_scheduled_status(status_file, status)
        _print_status(status, output_format)
        return status
    except RuntimeError as exc:
        status = {
            **base_status,
            "status": "skipped",
            "summary": str(exc),
            "stage": "lock",
            "failure_reason": str(exc),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_scheduled_status(status_file, status)
        _print_status(status, output_format)
        return status


def should_run_scheduled_update(
    *,
    now: datetime,
    scheduled_time: str,
    previous_status: dict[str, Any],
    force: bool,
    catch_up: bool,
    settings: Settings,
) -> ScheduleDecision:
    """Decide whether the scheduled workflow should run."""
    is_trade_day = is_trade_day_local(now, settings=settings)
    already_ran = _already_success_today(previous_status, now)
    if force:
        return ScheduleDecision(True, "running", "force 已启用，忽略时间和已运行状态。", is_trade_day, already_ran, catch_up)
    if not is_trade_day:
        return ScheduleDecision(False, "skipped", "非交易日，跳过自动更新。", is_trade_day, already_ran, catch_up)
    scheduled = _parse_time(scheduled_time)
    if now.time() < scheduled:
        return ScheduleDecision(False, "skipped", "未到计划更新时间。", is_trade_day, already_ran, catch_up)
    if already_ran:
        return ScheduleDecision(False, "skipped", "今日已完成正式自动更新，不重复运行。", is_trade_day, already_ran, catch_up)
    return ScheduleDecision(True, "running", "已到计划时间且今日未成功更新，开始执行。", is_trade_day, already_ran, catch_up)


def is_trade_day_local(current: datetime, *, settings: Settings) -> bool:
    """Use a conservative local trade-day check, without network access."""
    return current.weekday() < 5


@contextmanager
def scheduled_update_lock(lock_path: str | Path) -> Iterator[dict[str, Any]]:
    """Create a lightweight pid lock and prevent concurrent scheduled writes."""
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_info = {"stale_lock_cleaned": False}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid", 0))
            started_at = str(payload.get("started_at") or "")
        except Exception:
            pid = 0
            started_at = ""
        if pid and _pid_exists(pid):
            if _lock_age_seconds(started_at) > DEFAULT_LOCK_STALE_SECONDS:
                raise RuntimeError("已有自动更新任务运行时间过长。请确认后停止旧任务或手动清理 lock。")
            raise RuntimeError("已有自动更新任务正在运行。")
        _safe_unlink(path)
        lock_info["stale_lock_cleaned"] = True
    path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "command": "python -m core.jobs.run_scheduled_daily_update",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        yield lock_info
    finally:
        _safe_unlink(path)


def read_scheduled_status(path: str | Path = DEFAULT_STATUS_PATH) -> dict[str, Any]:
    """Read scheduled update status JSON."""
    status_path = Path(path)
    if not status_path.exists():
        return {}
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "failed", "summary": "自动更新状态文件损坏。"}


def write_scheduled_status(path: str | Path, status: dict[str, Any]) -> None:
    """Write scheduled update status JSON."""
    status_path = Path(path)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(_mask_sensitive(status), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _run_heavy_steps(
    *,
    status: dict[str, Any],
    logs: list[str],
    settings: Settings,
    report_dir: str | Path,
    status_path: str | Path,
    update_limit: int,
    update_batch_size: int,
    update_lookback_days: int,
    update_max_retries: int,
    update_mode: str,
    recent_days: int,
    max_update_symbols: int,
    continue_on_symbol_failure: bool,
    stage_timeout_seconds: int,
    update_stage_timeout_seconds: int,
    verbose: bool,
    output_format: str,
    research_trade_date: str,
    step_overrides: dict[str, Callable[[], dict[str, Any]]],
) -> dict[str, Any]:
    steps: dict[str, dict[str, Any]] = {}
    workbook_path = _workbook_output_path(report_dir)
    for stage_spec in _scheduled_steps(
        settings=settings,
        workbook_path=workbook_path,
        update_limit=update_limit,
        update_batch_size=update_batch_size,
        update_lookback_days=update_lookback_days,
        update_max_retries=update_max_retries,
        update_mode=update_mode,
        recent_days=recent_days,
        max_update_symbols=max_update_symbols,
        continue_on_symbol_failure=continue_on_symbol_failure,
        stage_timeout_seconds=stage_timeout_seconds,
        update_stage_timeout_seconds=update_stage_timeout_seconds,
        verbose=verbose,
        research_trade_date=research_trade_date,
    ):
        stage = stage_spec.name
        status["stage"] = stage
        status["current_stage"] = stage
        status["stage_started_at"] = datetime.now().isoformat(timespec="seconds")
        status["last_heartbeat_at"] = status["stage_started_at"]
        status["summary"] = f"自动更新运行中：{stage}。"
        write_scheduled_status(status_path, status)
        _emit_stage(output_format, _stage_label(stage), _stage_detail(stage, update_limit, stage_spec.timeout_seconds))
        started = time_module.monotonic()
        if stage == "update_data" and step_overrides and "update_data" not in step_overrides:
            result = {"status": "success", "message": "test override: update_data skipped"}
        else:
            result = step_overrides[stage]() if stage in step_overrides else _run_module_stage(
                stage,
                stage_spec.command,
                stage_spec.timeout_seconds,
                env=stage_spec.env,
                status=status,
                status_path=status_path,
                output_format=output_format,
            )
        steps[stage] = result if isinstance(result, dict) else {"status": "success", "result": result}
        steps[stage]["elapsed_seconds"] = round(time_module.monotonic() - started, 3)
        logs.append(f"{stage}: {steps[stage].get('status', 'success')}")
        _merge_update_stage_summary(status, stage, steps[stage])
        if stage == "update_data":
            quality = _run_data_quality_gate(
                settings=settings,
                research_trade_date=research_trade_date,
                step_overrides=step_overrides,
            )
            status.update(quality)
        status["steps"] = steps
        status["last_heartbeat_at"] = datetime.now().isoformat(timespec="seconds")
        write_scheduled_status(status_path, status)
        if str(steps[stage].get("status", "success")).lower() == "failed":
            status.update(
                {
                    "status": "failed",
                    "summary": f"自动更新在 {stage} 阶段失败。",
                    "failure_reason": str(steps[stage].get("message") or steps[stage].get("error") or "unknown"),
                    "suggested_action": _suggested_action_for_stage(stage, steps[stage]),
                    "logs": logs,
                    "steps": steps,
                }
            )
            return status
    workbook = steps.get("workbook", {})
    workbook_path = Path(str(workbook.get("output_path", ""))) if workbook.get("output_path") else Path()
    research_trade_date = _research_trade_date(steps, status)
    workflow_step_count = _workflow_skipped_step_count(steps)
    quality_status = str(status.get("data_quality_status") or "ok").lower()
    final_status = "warning" if _has_update_warnings(status, steps) or quality_status in {"warning", "poor"} else "success"
    if quality_status in {"poor", "failed"}:
        summary = "流程完成，但最新交易日数据覆盖严重不足，当前结果仅供流程检查，不代表完整全市场筛选结果。"
    elif final_status == "success":
        summary = "每日自动更新完成。"
    else:
        summary = "每日自动更新完成，部分股票空数据、超时或数据质量 warning 已记录。"
    status.update(
        {
            "status": final_status,
            "summary": summary,
            "stage": "done",
            "trade_date": research_trade_date,
            "research_trade_date": research_trade_date,
            "latest_completed_trade_date": research_trade_date,
            "candidate_count": _workbook_or_step_count(workbook, "strategy_rows", _candidate_count(steps)),
            "elder_review_count": _workbook_or_step_count(workbook, "elder_rows", int(steps.get("elder_review", {}).get("review_count", 0))),
            "entry_zone_count": _workbook_or_step_count(workbook, "entry_zone_rows", int(steps.get("entry_zone", {}).get("calculated_count", 0))),
            "watchlist_count": _workbook_or_step_count(
                workbook,
                "watchlist_rows",
                int(steps.get("watchlist", {}).get("snapshot_count", steps.get("watchlist", {}).get("daily_snapshot_count", 0))),
            ),
            "external_position_count": _workbook_or_step_count(workbook, "external_position_rows", 0),
            "workflow_skipped_step_count": workflow_step_count,
            "workbook_path": str(workbook_path) if workbook_path else "",
            "workbook_exists": bool(workbook_path and workbook_path.exists()),
            "workbook_size_bytes": workbook_path.stat().st_size if workbook_path and workbook_path.exists() else 0,
            "steps": steps,
            "logs": logs,
        }
    )
    if _status_counts_as_formal_success(status):
        status["formal_success_date"] = research_trade_date
    return status


def _scheduled_steps(
    *,
    settings: Settings,
    workbook_path: Path,
    update_limit: int,
    update_batch_size: int,
    update_lookback_days: int,
    update_max_retries: int,
    update_mode: str,
    recent_days: int,
    max_update_symbols: int,
    continue_on_symbol_failure: bool,
    stage_timeout_seconds: int,
    update_stage_timeout_seconds: int,
    verbose: bool,
    research_trade_date: str,
) -> list[StageCommand]:
    """Return bounded subprocess-backed scheduled stages."""
    update_mode = _normalize_update_mode(update_mode)
    update_stage = _update_stage_command(
        update_mode=update_mode,
        update_limit=update_limit,
        update_batch_size=update_batch_size,
        update_lookback_days=update_lookback_days,
        update_max_retries=update_max_retries,
        recent_days=recent_days,
        max_update_symbols=max_update_symbols,
        continue_on_symbol_failure=continue_on_symbol_failure,
        verbose=verbose,
        research_trade_date=research_trade_date,
        timeout_seconds=update_stage_timeout_seconds,
    )
    steps = [
        StageCommand("backup", [sys.executable, "-m", "core.jobs.backup_local_data", "--label", "scheduled_daily_update"], stage_timeout_seconds),
        update_stage,
        StageCommand("workflow", [sys.executable, "-m", "core.jobs.run_daily_workflow", "--doctor-before-run", "--skip-update", "--format", "all"], stage_timeout_seconds),
        StageCommand("elder_review", [sys.executable, "-m", "core.jobs.run_elder_review"], stage_timeout_seconds),
        StageCommand("entry_zone", [sys.executable, "-m", "core.jobs.calculate_entry_zones"], stage_timeout_seconds),
        StageCommand("watchlist", [sys.executable, "-m", "core.jobs.track_watchlist"], stage_timeout_seconds),
    ]
    if bool(getattr(settings, "run_lookback_after_daily_update", False)):
        steps.append(
            StageCommand(
                "lookback_analysis",
                [sys.executable, "-m", "core.jobs.run_lookback_analysis", "--as-of", research_trade_date, "--format", "text"],
                stage_timeout_seconds,
            )
        )
    steps.append(StageCommand("workbook", [sys.executable, "-m", "core.jobs.export_daily_research_workbook", "--trade-date", research_trade_date, "--output", str(workbook_path)], stage_timeout_seconds))
    return steps


def _update_stage_command(
    *,
    update_mode: str,
    update_limit: int,
    update_batch_size: int,
    update_lookback_days: int,
    update_max_retries: int,
    recent_days: int,
    max_update_symbols: int,
    continue_on_symbol_failure: bool,
    verbose: bool,
    research_trade_date: str,
    timeout_seconds: int,
) -> StageCommand:
    """Build the scheduled update stage command for daily incremental or manual backfill."""
    update_mode = _normalize_update_mode(update_mode)
    if update_mode == "full_backfill":
        update_args = [
            "--mode",
            "missing_first",
            "--batch-size",
            str(max(1, int(update_batch_size))),
            "--lookback-days",
            str(max(1, int(update_lookback_days))),
            "--max-retries",
            str(max(1, int(update_max_retries))),
            "--skip-network-preflight",
        ]
        if int(update_limit) > 0:
            update_args.extend(["--max-symbols", str(max(1, int(update_limit)))])
        if verbose:
            update_args.append("--verbose")
        return StageCommand(
            "update_data",
            [sys.executable, "-m", "core.jobs.run_full_batch_update", *update_args],
            timeout_seconds,
            env={"REAL_DATA_END_DATE": research_trade_date},
        )

    effective_max = int(update_limit) if int(update_limit) > 0 else int(max_update_symbols or DEFAULT_DAILY_INCREMENTAL_MAX_SYMBOLS)
    env = {
        "DATA_PROVIDER": "akshare",
        "AKSHARE_SAMPLE_SYMBOLS": "",
        "REAL_UNIVERSE_PRESET": "full",
        "REAL_DATA_END_DATE": research_trade_date,
        "FULL_UPDATE_MODE": "stale_only",
        "FULL_UPDATE_BATCH_SIZE": str(max(1, int(update_batch_size))),
        "FULL_UPDATE_LOOKBACK_DAYS": str(max(1, int(recent_days))),
        "FULL_UPDATE_MAX_RETRIES": str(max(0, int(update_max_retries))),
        "FULL_UPDATE_MAX_SYMBOLS": str(max(0, effective_max)),
        "FULL_UPDATE_MAX_BATCHES": "0",
        "FULL_UPDATE_RESUME": "true",
        "FULL_UPDATE_SKIP_EMPTY_UNAVAILABLE": "true",
        "FULL_ENABLE_STOCK_BASIC_ENRICHMENT": "false",
        "FULL_ENABLE_VALUATION_ENRICHMENT": "false",
    }
    if continue_on_symbol_failure:
        env["SCHEDULED_UPDATE_CONTINUE_ON_SYMBOL_FAILURE"] = "true"
    return StageCommand(
        "update_data",
        [sys.executable, "-m", "core.jobs.update_real_data"],
        timeout_seconds,
        env=env,
    )


def _normalize_update_mode(value: str) -> str:
    """Normalize scheduled update mode."""
    value = str(value or "daily_incremental").strip().lower()
    return value if value in {"daily_incremental", "full_backfill"} else "daily_incremental"


def _run_module_stage(
    stage: str,
    command: list[str],
    timeout_seconds: int,
    *,
    env: dict[str, str] | None = None,
    status: dict[str, Any],
    status_path: str | Path,
    output_format: str,
) -> dict[str, Any]:
    """Run one scheduled stage in a subprocess with a hard timeout."""
    started = time_module.monotonic()
    output_lines: list[str] = []
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    last_heartbeat = time_module.monotonic()
    timed_out = False
    returncode: int | None = None
    assert process.stdout is not None
    while True:
        now = time_module.monotonic()
        if now - started > max(1, int(timeout_seconds)):
            timed_out = True
            process.kill()
            returncode = 124
            break
        readable, _, _ = select.select([process.stdout], [], [], 0.5)
        if readable:
            line = process.stdout.readline()
            if line:
                clean = line.rstrip("\n")
                output_lines.append(clean)
                _emit_child_line(output_format, clean)
                _update_heartbeat_from_line(status, clean, stage=stage)
        if now - last_heartbeat >= DEFAULT_HEARTBEAT_SECONDS:
            _write_heartbeat(status, status_path)
            _emit_stage(output_format, f"{_stage_label(stage)} heartbeat", _heartbeat_detail(status))
            last_heartbeat = now
        returncode = process.poll()
        if returncode is not None:
            remaining = process.stdout.read()
            if remaining:
                for clean in remaining.splitlines():
                    output_lines.append(clean)
                    _emit_child_line(output_format, clean)
                    _update_heartbeat_from_line(status, clean, stage=stage)
            break
    stdout = "\n".join(output_lines)
    stderr = ""
    if timed_out:
        _write_heartbeat(status, status_path)
        return {
            "status": "failed",
            "message": f"{stage} 阶段超时：{timeout_seconds} 秒。",
            "error": f"TimeoutExpired: stage exceeded {timeout_seconds} seconds",
            "returncode": 124,
            "timed_out": True,
            "stdout_tail": _tail_text(stdout),
            "stderr_tail": "",
            "elapsed_seconds": round(time_module.monotonic() - started, 3),
        }
    result: dict[str, Any] = {
        "status": "success" if returncode == 0 else "failed",
        "returncode": int(returncode or 0),
        "stdout_tail": _tail_text(stdout),
        "stderr_tail": _tail_text(stderr),
        "elapsed_seconds": round(time_module.monotonic() - started, 3),
    }
    if stage == "update_data":
        result.update(_parse_update_output(stdout))
        if result["status"] == "success" and int(result.get("failed_symbol_count", 0) or 0) > 0:
            result["status"] = "warning"
    if stage == "workbook":
        result.update(_parse_workbook_output(stdout))
    if returncode != 0:
        result["message"] = f"{stage} 阶段命令失败，returncode={returncode}。"
    return result


def _parse_update_output(stdout: str) -> dict[str, Any]:
    """Extract compact update counters from update_real_data or run_full_batch_update output."""
    mapping = {
        "full_universe_count": "full 股票池数量",
        "planned_symbols": "本次计划处理",
        "planned_count": "本次计划",
        "success_symbols": "成功数量",
        "success_symbols_alt": "成功",
        "raw_failed_symbol_count": "失败数量",
        "raw_failed_symbol_count_alt": "失败",
        "update_skipped_symbol_count": "本次未处理数量",
        "deferred_symbols": "暂未处理",
    }
    parsed: dict[str, Any] = {}
    for key, label in mapping.items():
        value = _extract_int_after_label(stdout, label)
        if value is not None:
            parsed[key] = value
    empty_count = _extract_int_after_label(stdout, "空数据股票")
    if empty_count is None:
        empty_count = 0
    if "success_symbols" not in parsed and "success_symbols_alt" in parsed:
        parsed["success_symbols"] = parsed["success_symbols_alt"]
    if "planned_symbols" not in parsed and "planned_count" in parsed:
        parsed["planned_symbols"] = parsed["planned_count"]
    if "update_skipped_symbol_count" not in parsed and "deferred_symbols" in parsed:
        parsed["update_skipped_symbol_count"] = parsed["deferred_symbols"]
    if "raw_failed_symbol_count" not in parsed and "raw_failed_symbol_count_alt" in parsed:
        parsed["raw_failed_symbol_count"] = parsed["raw_failed_symbol_count_alt"]
    raw_failed = int(parsed.get("raw_failed_symbol_count", 0) or 0)
    parsed["empty_data_symbol_count"] = int(empty_count or 0)
    parsed["empty_data_symbol_examples"] = _extract_examples(stdout, "空数据股票")
    parsed["unavailable_symbol_count"] = max(raw_failed, int(empty_count or 0))
    parsed["network_failed_symbol_count"] = max(raw_failed - int(empty_count or 0), 0)
    parsed["failed_symbol_count"] = parsed["network_failed_symbol_count"]
    parsed["failed_symbol_examples"] = _extract_examples(stdout, "失败股票")
    parsed["update_warning_count"] = parsed["unavailable_symbol_count"]
    parsed["update_warning_examples"] = parsed.get("failed_symbol_examples") or parsed.get("empty_data_symbol_examples") or []
    return parsed


def _extract_int_after_label(text: str, label: str) -> int | None:
    for line in text.splitlines():
        if label in line:
            tail = line.split(label, 1)[1]
            match = re.search(r"\d+", tail)
            if match:
                return int(match.group(0))
    return None


def _extract_examples(text: str, label: str) -> list[str]:
    for line in text.splitlines():
        if label in line:
            codes = re.findall(r"\b\d{6}\.(?:SZ|SH|BJ)\b", line)
            if codes:
                return codes[:10]
            tail = line.split("样例:", 1)[-1] if "样例:" in line else line.split(":", 1)[-1]
            return [item.strip() for item in tail.split(",") if item.strip() and "只" not in item][:10]
    return []


def _parse_workbook_output(stdout: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in stdout.splitlines():
        if line.startswith("输出文件:"):
            result["output_path"] = line.split(":", 1)[1].strip()
        elif line.startswith("研究日期:"):
            result["trade_date"] = line.split(":", 1)[1].strip()
        elif line.startswith("今日候选:"):
            result["strategy_rows"] = _extract_int_after_label(line, "今日候选") or 0
        elif line.startswith("埃尔德复核:"):
            result["elder_rows"] = _extract_int_after_label(line, "埃尔德复核") or 0
        elif line.startswith("买入区间:"):
            result["entry_zone_rows"] = _extract_int_after_label(line, "买入区间") or 0
        elif line.startswith("观察池:"):
            result["watchlist_rows"] = _extract_int_after_label(line, "观察池") or 0
        elif line.startswith("外部模拟持仓:"):
            result["external_position_rows"] = _extract_int_after_label(line, "外部模拟持仓") or 0
    return result


def _emit_stage(output_format: str, stage: str, detail: str = "") -> None:
    """Print a user-visible stage line immediately in text mode."""
    if output_format != "text":
        return
    if detail:
        print(f"- 阶段: {stage} | {detail}", flush=True)
    else:
        print(f"- 阶段: {stage}", flush=True)


def _emit_child_line(output_format: str, line: str) -> None:
    """Stream a child command line to the console in text mode."""
    if output_format != "text":
        return
    if not line:
        return
    print(f"  {line}", flush=True)


def _write_heartbeat(status: dict[str, Any], status_path: str | Path) -> None:
    status["last_heartbeat_at"] = datetime.now().isoformat(timespec="seconds")
    write_scheduled_status(status_path, status)


def _update_heartbeat_from_line(status: dict[str, Any], line: str, *, stage: str = "") -> None:
    """Parse known progress/summary lines into heartbeat counters."""
    stage = stage or "update_data"
    status["last_heartbeat_at"] = datetime.now().isoformat(timespec="seconds")
    if "本次计划处理" in line or "本次计划" in line:
        value = _extract_int_after_label(line, "本次计划处理")
        if value is None:
            value = _extract_int_after_label(line, "本次计划")
        if value is not None:
            status["total_symbol_count"] = value
    if "成功数量" in line or "成功" in line:
        value = _extract_int_after_label(line, "成功数量")
        if value is None:
            value = _extract_int_after_label(line, "成功")
        if value is not None:
            status["processed_symbol_count"] = value
    if "失败数量" in line:
        value = _extract_int_after_label(line, "失败数量")
        if value is not None:
            if stage == "update_data":
                status["unavailable_symbol_count"] = value
            else:
                status["failed_symbol_count"] = value
    if "本次未处理数量" in line:
        value = _extract_int_after_label(line, "本次未处理数量")
        if value is not None:
            status["update_skipped_symbol_count"] = value
            status["skipped_symbol_count"] = value
    if "[progress]" in line:
        progress_targets = [("success=", "processed_symbol_count")]
        if stage == "update_data":
            progress_targets.extend([("failed=", "unavailable_symbol_count"), ("skipped=", "update_skipped_symbol_count")])
        elif stage == "workflow":
            progress_targets.extend([("skipped=", "workflow_skipped_step_count")])
        else:
            progress_targets.extend([("failed=", "failed_symbol_count")])
        for key, status_key in progress_targets:
            value = _extract_progress_int(line, key)
            if value is not None:
                status[status_key] = value
                if status_key == "unavailable_symbol_count":
                    status["failed_symbol_count"] = value
                if status_key == "update_skipped_symbol_count":
                    status["skipped_symbol_count"] = value


def _extract_progress_int(line: str, token: str) -> int | None:
    if token not in line:
        return None
    tail = line.split(token, 1)[1].split(" ", 1)[0].strip("',")
    try:
        return int(tail)
    except ValueError:
        return None


def _heartbeat_detail(status: dict[str, Any]) -> str:
    return (
        f"processed={status.get('processed_symbol_count', 0)}, "
        f"total={status.get('total_symbol_count', 0)}, "
        f"failed={status.get('failed_symbol_count', 0)}, "
        f"skipped={status.get('skipped_symbol_count', 0)}"
    )


def _stage_label(stage: str) -> str:
    return {
        "backup": "备份 DuckDB",
        "update_data": "更新数据",
        "workflow": "运行日常工作流",
        "elder_review": "埃尔德复核",
        "entry_zone": "买入区间",
        "watchlist": "观察池跟踪",
        "lookback_analysis": "自动回看分析",
        "workbook": "导出每日研究 Excel",
        "done": "完成",
    }.get(stage, stage)


def _stage_detail(stage: str, update_limit: int, timeout_seconds: int) -> str:
    if stage == "update_data":
        limit_text = str(update_limit) if int(update_limit) > 0 else "formal_unlimited"
        return f"update_limit={limit_text}, timeout={timeout_seconds}s"
    return f"timeout={timeout_seconds}s"


def _tail_text(text: str, max_lines: int = 80) -> str:
    lines = str(text or "").splitlines()
    return "\n".join(lines[-max_lines:])


def _merge_update_stage_summary(status: dict[str, Any], stage: str, result: dict[str, Any]) -> None:
    """Merge update counters into the top-level scheduled status."""
    if stage != "update_data":
        return
    status["data_update_elapsed_seconds"] = result.get("elapsed_seconds", 0)
    for key in [
        "empty_data_symbol_count",
        "empty_data_symbol_examples",
        "network_timeout_count",
        "network_timeout_examples",
        "update_skipped_symbol_count",
        "unavailable_symbol_count",
        "network_failed_symbol_count",
        "failed_symbol_count",
        "failed_symbol_examples",
        "update_warning_count",
        "update_warning_examples",
        "planned_symbols",
        "success_symbols",
    ]:
        if key in result:
            status[key] = result[key]
    if "update_skipped_symbol_count" in result:
        status["skipped_symbol_count"] = result["update_skipped_symbol_count"]
    status["update_failed_symbol_count"] = int(status.get("failed_symbol_count", 0) or 0)
    status["update_failed_symbol_examples"] = list(status.get("failed_symbol_examples", []) or [])
    status["update_continued_after_partial_failure"] = bool(
        int(status.get("empty_data_symbol_count", 0) or 0) > 0
        or int(status.get("network_timeout_count", 0) or 0) > 0
        or int(status.get("unavailable_symbol_count", 0) or 0) > 0
        or int(status.get("failed_symbol_count", 0) or 0) > 0
    )


def _run_data_quality_gate(
    *,
    settings: Settings,
    research_trade_date: str,
    step_overrides: dict[str, Callable[[], dict[str, Any]]],
) -> dict[str, Any]:
    """Return latest-date market data quality metrics for formal-result gating."""
    if "data_quality_gate" in step_overrides:
        return _normalize_data_quality_gate(step_overrides["data_quality_gate"](), research_trade_date)
    if step_overrides:
        return _normalize_data_quality_gate({"data_quality_status": "ok", "formal_result_usable": True}, research_trade_date)
    return _collect_latest_data_quality(settings=settings, research_trade_date=research_trade_date)


def _collect_latest_data_quality(*, settings: Settings, research_trade_date: str) -> dict[str, Any]:
    """Collect latest date coverage from local DuckDB without external API access."""
    store = DuckDBStore(getattr(settings, "duckdb_path", None))
    try:
        stock_basic = store.read_table("stock_basic")
    except DuckDBStoreError:
        stock_basic = _empty_frame()
    try:
        daily_price = store.read_table("daily_price")
    except DuckDBStoreError:
        daily_price = _empty_frame()
    try:
        daily_basic = store.read_table("daily_basic")
    except DuckDBStoreError:
        daily_basic = _empty_frame()
    try:
        adj_factor = store.read_table("adj_factor")
    except DuckDBStoreError:
        adj_factor = _empty_frame()
    try:
        factor_scores = store.read_table("factor_scores")
    except DuckDBStoreError:
        factor_scores = _empty_frame()
    try:
        strategy_result = store.read_table("strategy_result")
    except DuckDBStoreError:
        strategy_result = _empty_frame()
    try:
        entry_zones = store.read_table("entry_zone_snapshots")
    except DuckDBStoreError:
        entry_zones = _empty_frame()
    try:
        watchlist_snapshots = store.read_table("watchlist_daily_snapshots")
    except DuckDBStoreError:
        watchlist_snapshots = _empty_frame()

    configured_symbols = _symbols_from_table(stock_basic)
    if not configured_symbols:
        configured_symbols = sorted(
            _symbols_from_table(daily_price)
            | _symbols_from_table(daily_basic)
            | _symbols_from_table(adj_factor)
        )
    return _build_latest_quality_metrics(
        configured_symbols=list(configured_symbols),
        daily_price=daily_price,
        daily_basic=daily_basic,
        adj_factor=adj_factor,
        factor_scores=factor_scores,
        strategy_result=strategy_result,
        entry_zones=entry_zones,
        watchlist_snapshots=watchlist_snapshots,
        research_trade_date=research_trade_date,
    )


def _empty_frame() -> Any:
    try:
        import pandas as pd

        return pd.DataFrame()
    except Exception:
        return []


def _symbols_from_table(frame: Any) -> set[str]:
    if not hasattr(frame, "empty") or frame.empty or "ts_code" not in frame.columns:
        return set()
    return set(frame["ts_code"].dropna().astype(str).tolist())


def _symbols_at_date(frame: Any, trade_date: str) -> set[str]:
    if not hasattr(frame, "empty") or frame.empty or "ts_code" not in frame.columns or "trade_date" not in frame.columns:
        return set()
    rows = frame[frame["trade_date"].astype(str) == str(trade_date)]
    return _symbols_from_table(rows)


def _build_latest_quality_metrics(
    *,
    configured_symbols: list[str],
    daily_price: Any,
    daily_basic: Any,
    adj_factor: Any,
    factor_scores: Any | None = None,
    strategy_result: Any | None = None,
    entry_zones: Any | None = None,
    watchlist_snapshots: Any | None = None,
    research_trade_date: str,
) -> dict[str, Any]:
    configured_set = set(configured_symbols)
    configured_count = len(configured_set)
    price_symbols = _symbols_at_date(daily_price, research_trade_date).intersection(configured_set) if configured_set else _symbols_at_date(daily_price, research_trade_date)
    basic_symbols = _symbols_at_date(daily_basic, research_trade_date).intersection(configured_set) if configured_set else _symbols_at_date(daily_basic, research_trade_date)
    adj_symbols = _symbols_at_date(adj_factor, research_trade_date).intersection(configured_set) if configured_set else _symbols_at_date(adj_factor, research_trade_date)
    all_symbols = price_symbols.intersection(basic_symbols).intersection(adj_symbols)
    denominator = configured_count or max(len(price_symbols | basic_symbols | adj_symbols), 1)
    row_counts = _daily_price_row_counts(daily_price)
    history_complete = [symbol for symbol in configured_set if row_counts.get(symbol, 0) >= 252]
    history_incomplete = [symbol for symbol in configured_set if 0 < row_counts.get(symbol, 0) < 252]
    history_missing = [symbol for symbol in configured_set if row_counts.get(symbol, 0) <= 0]
    factor_symbols = _symbols_at_date(factor_scores, research_trade_date).intersection(configured_set) if factor_scores is not None else set()
    elder_symbols = _symbols_at_date(watchlist_snapshots, research_trade_date).intersection(configured_set) if watchlist_snapshots is not None else set()
    entry_zone_symbols = _symbols_at_date(entry_zones, research_trade_date).intersection(configured_set) if entry_zones is not None else set()
    strategy_symbols = _symbols_at_date(strategy_result, research_trade_date).intersection(configured_set) if strategy_result is not None else set()
    lookback_symbols = {symbol for symbol in strategy_symbols if row_counts.get(symbol, 0) >= 80}
    latest_updated_but_history_incomplete = sorted(symbol for symbol in price_symbols if row_counts.get(symbol, 0) < 252)
    history_complete_but_latest_missing = sorted(symbol for symbol in history_complete if symbol not in price_symbols)
    metrics = {
        "latest_completed_trade_date": research_trade_date,
        "configured_symbol_count": configured_count,
        "latest_daily_price_symbol_count": len(price_symbols),
        "missing_latest_daily_price_symbol_count": max(denominator - len(price_symbols), 0),
        "missing_latest_daily_price_examples": sorted((configured_set or price_symbols) - price_symbols)[:30],
        "latest_daily_price_coverage_rate": len(price_symbols) / denominator if denominator else 0.0,
        "latest_daily_basic_symbol_count": len(basic_symbols),
        "missing_latest_daily_basic_symbol_count": max(denominator - len(basic_symbols), 0),
        "missing_latest_daily_basic_examples": sorted((configured_set or basic_symbols) - basic_symbols)[:30],
        "latest_daily_basic_coverage_rate": len(basic_symbols) / denominator if denominator else 0.0,
        "latest_adj_factor_symbol_count": len(adj_symbols),
        "missing_latest_adj_factor_symbol_count": max(denominator - len(adj_symbols), 0),
        "missing_latest_adj_factor_examples": sorted((configured_set or adj_symbols) - adj_symbols)[:30],
        "latest_adj_factor_coverage_rate": len(adj_symbols) / denominator if denominator else 0.0,
        "latest_all_required_tables_symbol_count": len(all_symbols),
        "missing_latest_all_required_tables_symbol_count": max(denominator - len(all_symbols), 0),
        "latest_all_required_tables_coverage_rate": len(all_symbols) / denominator if denominator else 0.0,
        "history_complete_symbol_count": len(history_complete),
        "history_incomplete_symbol_count": len(history_incomplete),
        "history_missing_symbol_count": len(history_missing),
        "history_missing_examples": sorted(history_missing)[:30],
        "available_days_20d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 20),
        "available_days_60d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 60),
        "available_days_120d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 120),
        "available_days_252d_count": sum(1 for symbol in configured_set if row_counts.get(symbol, 0) >= 252),
        "factor_ready_symbol_count": len(factor_symbols),
        "elder_ready_symbol_count": len(elder_symbols),
        "entry_zone_ready_symbol_count": len(entry_zone_symbols),
        "lookback_ready_symbol_count": len(lookback_symbols),
        "latest_updated_but_history_incomplete_examples": latest_updated_but_history_incomplete[:30],
        "history_complete_but_latest_missing_examples": history_complete_but_latest_missing[:30],
        "latest_updated_but_history_incomplete_count": len(latest_updated_but_history_incomplete),
        "history_complete_but_latest_missing_count": len(history_complete_but_latest_missing),
    }
    return _normalize_data_quality_gate(metrics, research_trade_date)


def _daily_price_row_counts(frame: Any) -> dict[str, int]:
    if not hasattr(frame, "empty") or frame.empty or "ts_code" not in frame.columns:
        return {}
    counts = frame.groupby(frame["ts_code"].astype(str)).size()
    return {str(symbol): int(count) for symbol, count in counts.items()}


def _normalize_data_quality_gate(payload: dict[str, Any], research_trade_date: str) -> dict[str, Any]:
    """Normalize quality metrics and derive formal-result usability."""
    result = dict(payload or {})
    result.setdefault("latest_completed_trade_date", research_trade_date)
    for key in [
        "latest_daily_price_symbol_count",
        "missing_latest_daily_price_symbol_count",
        "latest_daily_basic_symbol_count",
        "missing_latest_daily_basic_symbol_count",
        "latest_adj_factor_symbol_count",
        "missing_latest_adj_factor_symbol_count",
        "latest_all_required_tables_symbol_count",
        "missing_latest_all_required_tables_symbol_count",
    ]:
        result[key] = _positive_int(result.get(key))
    for key in [
        "latest_daily_price_coverage_rate",
        "latest_daily_basic_coverage_rate",
        "latest_adj_factor_coverage_rate",
        "latest_all_required_tables_coverage_rate",
    ]:
        try:
            result[key] = float(result.get(key) or 0.0)
        except (TypeError, ValueError):
            result[key] = 0.0
    price_rate = float(result.get("latest_daily_price_coverage_rate", 0.0) or 0.0)
    if str(result.get("data_quality_status") or "").strip():
        quality_status = str(result["data_quality_status"]).lower()
    elif price_rate >= 0.95:
        quality_status = "ok"
    elif price_rate >= 0.80:
        quality_status = "warning"
    else:
        quality_status = "poor"
    result["data_quality_status"] = quality_status
    result["formal_result_usable"] = bool(result.get("formal_result_usable", quality_status not in {"poor", "failed"}))
    if quality_status in {"poor", "failed"}:
        result["formal_result_usable"] = False
        result.setdefault("formal_result_warning_reason", "流程完成，但最新交易日数据覆盖严重不足，当前结果仅供流程检查，不代表完整全市场筛选结果。")
    else:
        result.setdefault("formal_result_warning_reason", "")
    return result


def _has_update_warnings(status: dict[str, Any], steps: dict[str, dict[str, Any]]) -> bool:
    update = steps.get("update_data", {})
    return (
        str(update.get("status", "")).lower() in WARNING_STATUSES
        or str(status.get("diagnosis_status", "")).lower() in {"warning", "partial"}
        or bool(status.get("preflight_warning_reason"))
        or int(status.get("empty_data_symbol_count", 0) or 0) > 0
        or int(status.get("network_timeout_count", 0) or 0) > 0
        or int(status.get("unavailable_symbol_count", 0) or 0) > 0
        or int(status.get("failed_symbol_count", 0) or 0) > 0
    )


def _suggested_action_for_stage(stage: str, result: dict[str, Any]) -> str:
    if result.get("timed_out"):
        return "检查网络 / 降低批量规模 / 使用手机热点 / 稍后重试。"
    if stage == "preflight":
        return "先修复数据源预检问题，再重新运行。"
    if stage == "update_data":
        return "查看数据更新阶段输出，必要时降低 --update-limit 或稍后重试。"
    return "查看该阶段输出后重试。"


def _notify_if_needed(status: dict[str, Any], *, notify: bool, dry_run: bool) -> dict[str, Any]:
    if not notify:
        return {"macos_notification": "skipped", "email_enabled": False, "email_status": "skipped", "email_error": ""}
    success = status.get("status") in SUCCESS_STATUSES
    title = "A股选股助手：每日自动更新完成" if success else "A股选股助手：每日自动更新失败"
    message = (
        f"交易日期：{status.get('trade_date') or '暂无'} 今日候选：{status.get('candidate_count', 0)} "
        f"观察池：{status.get('watchlist_count', 0)}"
        if success
        else f"失败阶段：{status.get('stage')} 原因：{status.get('failure_reason') or status.get('summary')}"
    )
    macos = send_macos_notification(title, message, dry_run=dry_run)
    email = send_email_notification(
        subject=f"{title} - {status.get('trade_date') or ''}",
        body=f"{status.get('summary')}\n{status.get('suggested_action') or ''}",
        attachment_path=status.get("workbook_path") or None,
        dry_run=dry_run,
    )
    return {
        "macos_notification": macos.get("status", "skipped"),
        "email_enabled": bool(email.get("enabled")),
        "email_status": email.get("status", "disabled"),
        "email_error": email.get("error", ""),
    }


def _base_status(
    *,
    scheduled_time: str,
    started_at: datetime,
    force: bool,
    catch_up: bool,
    decision: ScheduleDecision,
    previous_run_interrupted: bool,
    research_trade_date: str,
    intraday_warning: str,
    allow_intraday: bool,
    previous_formal_success_date: str,
) -> dict[str, Any]:
    return {
        "status": "running",
        "summary": decision.summary,
        "pid": os.getpid(),
        "scheduled_time": scheduled_time,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": "",
        "run_date": started_at.strftime("%Y%m%d"),
        "trade_date": research_trade_date,
        "research_trade_date": research_trade_date,
        "latest_completed_trade_date": research_trade_date,
        "intraday_warning": intraday_warning,
        "allow_intraday": allow_intraday,
        "formal_run": False,
        "formal_run_note": "",
        "formal_success_date": previous_formal_success_date,
        "acceptance_mode": False,
        "update_limit": None,
        "update_mode": "daily_incremental",
        "recent_days": DEFAULT_DAILY_INCREMENTAL_RECENT_DAYS,
        "max_update_symbols": 0,
        "continue_on_symbol_failure": True,
        "is_trade_day": decision.is_trade_day,
        "catch_up": catch_up,
        "force": force,
        "already_ran_today": decision.already_ran_today,
        "previous_run_interrupted": previous_run_interrupted,
        "stale_lock_cleaned": False,
        "stage": "start",
        "current_stage": "start",
        "stage_started_at": "",
        "last_heartbeat_at": started_at.isoformat(timespec="seconds"),
        "failure_reason": "",
        "suggested_action": "",
        "diagnosis_status": "",
        "preflight_status": "",
        "preflight_allows_run": False,
        "preflight_warning_reason": "",
        "curl_fallback_available": False,
        "duckdb_status": "",
        "eastmoney_status": "",
        "candidate_count": 0,
        "elder_review_count": 0,
        "entry_zone_count": 0,
        "watchlist_count": 0,
        "external_position_count": 0,
        "workbook_path": "",
        "workbook_exists": False,
        "workbook_size_bytes": 0,
        "empty_data_symbol_count": 0,
        "empty_data_symbol_examples": [],
        "network_timeout_count": 0,
        "network_timeout_examples": [],
        "skipped_symbol_count": 0,
        "update_skipped_symbol_count": 0,
        "workflow_skipped_step_count": 0,
        "unavailable_symbol_count": 0,
        "network_failed_symbol_count": 0,
        "failed_symbol_count": 0,
        "failed_symbol_examples": [],
        "update_failed_symbol_count": 0,
        "update_failed_symbol_examples": [],
        "update_continued_after_partial_failure": False,
        "update_warning_count": 0,
        "update_warning_examples": [],
        "data_update_elapsed_seconds": 0,
        "data_quality_status": "",
        "formal_result_usable": False,
        "formal_result_warning_reason": "",
        "latest_daily_price_symbol_count": 0,
        "missing_latest_daily_price_symbol_count": 0,
        "latest_daily_price_coverage_rate": 0.0,
        "latest_daily_basic_symbol_count": 0,
        "missing_latest_daily_basic_symbol_count": 0,
        "latest_daily_basic_coverage_rate": 0.0,
        "latest_adj_factor_symbol_count": 0,
        "missing_latest_adj_factor_symbol_count": 0,
        "latest_adj_factor_coverage_rate": 0.0,
        "latest_all_required_tables_symbol_count": 0,
        "latest_all_required_tables_coverage_rate": 0.0,
        "processed_symbol_count": 0,
        "total_symbol_count": 0,
        "notification": {"macos_notification": "skipped", "email_enabled": False, "email_status": "disabled", "email_error": ""},
        "logs": [],
    }


def _already_success_today(previous: dict[str, Any], current: datetime) -> bool:
    return _is_formal_success_for_date(previous, current.strftime("%Y%m%d"))


def _is_formal_success_for_date(previous: dict[str, Any], trade_date: str) -> bool:
    """Return whether a previous status represents a completed formal daily run."""
    if previous.get("status") not in SUCCESS_STATUSES:
        return False
    if str(previous.get("stage") or "") != "done":
        return False
    if bool(previous.get("acceptance_mode")):
        return False
    if _positive_int(previous.get("update_limit")):
        return False
    if bool(previous.get("allow_intraday")):
        return False
    if str(previous.get("intraday_warning") or "").strip():
        return False
    if not bool(previous.get("workbook_exists")):
        return False
    if not str(previous.get("workbook_path") or "").strip():
        return False
    if _positive_int(previous.get("workbook_size_bytes")) <= 0:
        return False
    if str(previous.get("data_quality_status") or "").lower() in {"poor", "failed"}:
        return False
    if previous.get("formal_result_usable") is False:
        return False
    formal_date = str(previous.get("formal_success_date") or "")
    if formal_date:
        return formal_date == trade_date
    if bool(previous.get("formal_run")):
        return str(previous.get("trade_date") or previous.get("research_trade_date") or "") == trade_date
    return False


def _is_formal_run(
    *,
    update_limit: int,
    allow_intraday: bool,
    intraday_warning: str,
    dry_run: bool,
    after_scheduled_time: bool,
) -> bool:
    return (
        after_scheduled_time
        and not dry_run
        and int(update_limit) <= 0
        and not allow_intraday
        and not str(intraday_warning or "").strip()
    )


def _status_counts_as_formal_success(status: dict[str, Any]) -> bool:
    return _is_formal_success_for_date(status, str(status.get("research_trade_date") or status.get("trade_date") or ""))


def _positive_int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return max(0, int(value))
    except Exception:
        return 0


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def _is_after_scheduled_time(current: datetime, scheduled_time: str) -> bool:
    """Return whether current local time is at or after the configured scheduled time."""
    return current.time() >= _parse_time(scheduled_time)


def _formal_run_note(current: datetime, *, scheduled_time: str) -> str:
    """Return a user-facing note when the run cannot count as a formal close-time run."""
    if _is_after_scheduled_time(current, scheduled_time):
        return ""
    return "盘中运行不计入正式自动更新成功，不会阻止 18:00 收盘后更新。"


def _latest_completed_trade_date(current: datetime, *, scheduled_time: str, allow_intraday: bool, settings: Settings) -> str:
    """Return the latest completed trade date for scheduled research outputs."""
    scheduled = _parse_time(scheduled_time)
    if allow_intraday and is_trade_day_local(current, settings=settings):
        return current.strftime("%Y%m%d")
    if is_trade_day_local(current, settings=settings) and current.time() >= scheduled:
        return current.strftime("%Y%m%d")
    day = current.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.strftime("%Y%m%d")


def _intraday_warning(current: datetime, *, scheduled_time: str, allow_intraday: bool, settings: Settings) -> str:
    """Return a warning when the caller explicitly allows intraday data."""
    if allow_intraday and is_trade_day_local(current, settings=settings) and current.time() < _parse_time(scheduled_time):
        return "盘中强制运行，结果可能基于未完成交易日数据，不代表正式收盘后结果。"
    return ""


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _previous_run_interrupted(previous: dict[str, Any], lock_path: Path) -> bool:
    """Return whether the previous running status has no live process."""
    if previous.get("status") != "running":
        return False
    pid = int(previous.get("pid") or _lock_pid(lock_path) or 0)
    heartbeat_age = _lock_age_seconds(str(previous.get("last_heartbeat_at") or ""))
    return not (pid and _pid_exists(pid)) or heartbeat_age > DEFAULT_LOCK_STALE_SECONDS


def _lock_pid(lock_path: Path) -> int:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        return int(payload.get("pid") or 0)
    except Exception:
        return 0


def _lock_age_seconds(started_at: str) -> float:
    if not started_at:
        return 0.0
    try:
        return max(0.0, (datetime.now() - datetime.fromisoformat(started_at)).total_seconds())
    except ValueError:
        return 0.0


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _diagnosis_status(preflight: dict[str, Any]) -> str:
    status = str(preflight.get("status") or "").lower()
    if status in {"warning", "partial"}:
        return "warning"
    return "ok" if preflight.get("ok") else "failed"


def _preflight_allows_run(preflight: dict[str, Any]) -> bool:
    """Return whether preflight should allow the scheduled workflow to continue."""
    if "preflight_allows_run" in preflight:
        return bool(preflight.get("preflight_allows_run"))
    return bool(preflight.get("ok"))


def _duckdb_status(preflight: dict[str, Any]) -> str:
    duckdb = preflight.get("duckdb", {})
    return "locked" if duckdb.get("locked") else ("ok" if duckdb.get("ok") else "failed")


def _eastmoney_status(preflight: dict[str, Any]) -> str:
    eastmoney = preflight.get("eastmoney_kline", {})
    status = str(eastmoney.get("status") or "").lower()
    if status in {"warning", "partial"}:
        return "partial"
    return "ok" if eastmoney.get("ok") else ("skipped" if status == "skipped" else "failed")


def _workbook_output_path(report_dir: str | Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(report_dir) / f"daily_research_{timestamp}.xlsx"


def _candidate_count(steps: dict[str, dict[str, Any]]) -> int:
    workflow = steps.get("workflow", {})
    report = workflow.get("report", {}) if isinstance(workflow, dict) else {}
    if isinstance(report, dict):
        candidates = report.get("top_candidates") or []
        if candidates:
            return int(len(candidates))
    return int(workflow.get("candidate_count", 0) or 0)


def _workbook_or_step_count(workbook: dict[str, Any], key: str, fallback: int) -> int:
    """Return a count from the workbook step first, falling back to stage results."""
    value = workbook.get(key)
    if value is None:
        return int(fallback or 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return int(fallback or 0)


def _research_trade_date(steps: dict[str, dict[str, Any]], status: dict[str, Any]) -> str:
    """Resolve the research trade date from workbook/workflow output."""
    status_date = str(status.get("research_trade_date") or "").strip()
    if status_date:
        return status_date
    workbook_date = str(steps.get("workbook", {}).get("trade_date") or "").strip()
    if workbook_date:
        return workbook_date
    workflow = steps.get("workflow", {})
    for key in ["research_trade_date", "latest_completed_trade_date", "trade_date"]:
        value = str(workflow.get(key) or "").strip()
        if value:
            return value
    return str(status.get("trade_date") or status.get("run_date") or "")


def _workflow_skipped_step_count(steps: dict[str, dict[str, Any]]) -> int:
    """Return workflow-level skipped step count without mixing it with symbols."""
    workflow = steps.get("workflow", {})
    for key in ["workflow_skipped_step_count", "skipped_step_count", "skipped_steps"]:
        value = workflow.get(key)
        if isinstance(value, list):
            return len(value)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def _mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***" if _sensitive_key(key) else _mask_sensitive(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_sensitive(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str) and "sk-" in value:
        return value.split("sk-", 1)[0] + "sk-***"
    return value


def _sensitive_key(key: str) -> bool:
    return any(marker in str(key).lower() for marker in ("password", "token", "secret", "key"))


def _print_status(status: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(_mask_sensitive(status), ensure_ascii=False, indent=2, default=str))
        return
    print("收盘后自动更新")
    print(f"- 整体状态: {status.get('status')}")
    print(f"- 计划时间: {status.get('scheduled_time')}")
    print(f"- 实际开始: {status.get('started_at')}")
    print(f"- 完成时间: {status.get('finished_at') or '暂无'}")
    print(f"- 运行日期: {status.get('run_date') or status.get('trade_date')}")
    print(f"- 研究交易日: {status.get('research_trade_date') or status.get('trade_date')}")
    print(f"- 更新模式: {status.get('update_mode') or 'daily_incremental'}")
    if status.get("intraday_warning"):
        print(f"- 盘中提示: {status.get('intraday_warning')}")
    elif status.get("formal_run_note"):
        print(f"- 盘中提示: {status.get('formal_run_note')}")
    if status.get("acceptance_mode"):
        print(f"- 验收模式: 本次为小批量验收运行，update_limit={status.get('update_limit')}，不代表正式全市场自动更新结果。")
    print(f"- 数据源诊断: {status.get('diagnosis_status') or '暂无'}")
    if status.get("preflight_warning_reason"):
        print(f"- 预检提示: {status.get('preflight_warning_reason')}")
    if status.get("curl_fallback_available"):
        print("- curl fallback: 可用")
    print(f"- DuckDB: {status.get('duckdb_status') or '暂无'}")
    print(f"- 今日候选: {status.get('candidate_count', 0)}")
    print(f"- 埃尔德复核: {status.get('elder_review_count', 0)}")
    print(f"- 买入区间: {status.get('entry_zone_count', 0)}")
    print(f"- 观察池: {status.get('watchlist_count', 0)}")
    if status.get("data_quality_status"):
        print(f"- 数据质量等级: {status.get('data_quality_status')}")
        print(f"- 最新交易日 daily_price 覆盖率: {float(status.get('latest_daily_price_coverage_rate', 0.0) or 0.0):.2%}")
        print(f"- 最新交易日 daily_basic 覆盖率: {float(status.get('latest_daily_basic_coverage_rate', 0.0) or 0.0):.2%}")
        print(f"- 最新交易日 adj_factor 覆盖率: {float(status.get('latest_adj_factor_coverage_rate', 0.0) or 0.0):.2%}")
        print(f"- 正式全市场研究结果可用: {'是' if status.get('formal_result_usable') else '否'}")
        if status.get("formal_result_warning_reason"):
            print(f"- 数据质量提示: {status.get('formal_result_warning_reason')}")
    if status.get("stage"):
        print(f"- 当前/最后阶段: {status.get('stage')}")
    if status.get("empty_data_symbol_count") or status.get("network_timeout_count") or status.get("failed_symbol_count"):
        print(
            f"- 数据更新提示: 空数据 {status.get('empty_data_symbol_count', 0)}，"
            f"超时 {status.get('network_timeout_count', 0)}，失败 {status.get('failed_symbol_count', 0)}，"
            f"本次未处理 {status.get('update_skipped_symbol_count', status.get('skipped_symbol_count', 0))}"
        )
        examples = status.get("update_warning_examples") or status.get("failed_symbol_examples") or status.get("empty_data_symbol_examples") or []
        if examples:
            print(f"- 样例: {', '.join(map(str, examples[:10]))}")
    if status.get("previous_run_interrupted"):
        print("- 上次状态: 上一次自动更新可能异常中断，本次已按可恢复状态继续。")
    if status.get("stale_lock_cleaned"):
        print("- Lock: 已清理残留 lock。")
    print(f"- 每日研究 Excel: {status.get('workbook_path') or '暂无'}")
    notification = status.get("notification", {})
    print(f"- 通知: macOS {notification.get('macos_notification', 'skipped')}, email {notification.get('email_status', 'disabled')}")
    if status.get("failure_reason"):
        print(f"- 原因: {status.get('failure_reason')}")
    if status.get("suggested_action"):
        print(f"- 建议: {status.get('suggested_action')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run scheduled local daily update.")
    parser.add_argument("--scheduled-time", default="18:00")
    parser.add_argument("--catch-up", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-notify", action="store_true")
    parser.add_argument("--notify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--status-path", default=str(DEFAULT_STATUS_PATH))
    parser.add_argument("--lock-path", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--update-limit", type=int, default=DEFAULT_UPDATE_LIMIT, help="Maximum full-universe symbols to process in the update stage.")
    parser.add_argument("--update-batch-size", type=int, default=DEFAULT_UPDATE_BATCH_SIZE)
    parser.add_argument("--update-lookback-days", type=int, default=DEFAULT_UPDATE_LOOKBACK_DAYS)
    parser.add_argument("--update-max-retries", type=int, default=DEFAULT_UPDATE_MAX_RETRIES)
    parser.add_argument("--update-mode", choices=["daily_incremental", "full_backfill"], default="daily_incremental")
    parser.add_argument("--recent-days", type=int, default=DEFAULT_DAILY_INCREMENTAL_RECENT_DAYS)
    parser.add_argument("--max-update-symbols", type=int, default=0)
    parser.add_argument("--continue-on-symbol-failure", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--stage-timeout-seconds", type=int, default=DEFAULT_STAGE_TIMEOUT_SECONDS)
    parser.add_argument("--update-stage-timeout-seconds", type=int, default=None)
    parser.add_argument("--verbose", action="store_true", help="Print verbose per-symbol update details when supported.")
    parser.add_argument("--allow-intraday", action="store_true", help="Allow using the current trading day before the scheduled close-time run.")
    args = parser.parse_args(argv)
    run_scheduled_daily_update(
        scheduled_time=args.scheduled_time,
        catch_up=args.catch_up,
        force=args.force,
        dry_run=args.dry_run,
        notify=args.notify,
        skip_notify=args.skip_notify,
        output_format=args.format,
        status_path=args.status_path,
        lock_path=args.lock_path,
        report_dir=args.report_dir,
        update_limit=args.update_limit,
        update_batch_size=args.update_batch_size,
        update_lookback_days=args.update_lookback_days,
        update_max_retries=args.update_max_retries,
        update_mode=args.update_mode,
        recent_days=args.recent_days,
        max_update_symbols=args.max_update_symbols,
        continue_on_symbol_failure=args.continue_on_symbol_failure,
        stage_timeout_seconds=args.stage_timeout_seconds,
        update_stage_timeout_seconds=args.update_stage_timeout_seconds,
        verbose=args.verbose,
        allow_intraday=args.allow_intraday,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
