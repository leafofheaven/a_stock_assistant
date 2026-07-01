"""Scheduled 18:00 local daily update workflow."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time
import json
import os
from pathlib import Path
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
from core.storage.duckdb_store import DuckDBStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS_PATH = PROJECT_ROOT / "data" / "runtime" / "scheduled_daily_update_status.json"
DEFAULT_LOCK_PATH = PROJECT_ROOT / "data" / "runtime" / "scheduled_daily_update.lock"
DUCKDB_LOCK_USER_MESSAGE = "DuckDB is locked by another process. Please stop other running jobs or Streamlit first."
SUCCESS_STATUSES = {"success", "warning", "success_with_notification_warning"}


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
    now: datetime | None = None,
    settings: Settings | None = None,
    step_overrides: dict[str, Callable[[], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run the scheduled daily update if schedule, state, and preflight allow it."""
    resolved_settings = settings or get_settings()
    started_at = now or datetime.now()
    status_file = Path(status_path)
    lock_file = Path(lock_path)
    logs: list[str] = []
    previous = read_scheduled_status(status_file)
    decision = should_run_scheduled_update(
        now=started_at,
        scheduled_time=scheduled_time,
        previous_status=previous,
        force=force,
        catch_up=catch_up,
        settings=resolved_settings,
    )
    base_status = _base_status(
        scheduled_time=scheduled_time,
        started_at=started_at,
        force=force,
        catch_up=catch_up,
        decision=decision,
    )
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
        with scheduled_update_lock(lock_file):
            status = {
                **base_status,
                "status": "running",
                "summary": "自动更新运行中。",
                "stage": "preflight",
            }
            write_scheduled_status(status_file, status)
            preflight = (step_overrides or {}).get("preflight", lambda: run_data_source_preflight(settings=resolved_settings))()
            logs.append(f"preflight: {preflight.get('status')}")
            status.update(
                {
                    "diagnosis_status": _diagnosis_status(preflight),
                    "duckdb_status": _duckdb_status(preflight),
                    "eastmoney_status": _eastmoney_status(preflight),
                    "suggested_action": preflight.get("suggested_action") or "；".join(preflight.get("suggestions", [])),
                }
            )
            if not preflight.get("ok"):
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
                _print_status(status, output_format)
                return status

            status = _run_heavy_steps(
                status=status,
                logs=logs,
                settings=resolved_settings,
                report_dir=report_dir,
                step_overrides=step_overrides or {},
            )
            status["finished_at"] = datetime.now().isoformat(timespec="seconds")
            notification_requested = notify and not skip_notify
            status["notification"] = _notify_if_needed(status, notify=notification_requested, dry_run=False)
            if notification_requested and status["notification"].get("email_status") in {"failed", "skipped"} and status.get("status") == "success":
                status["status"] = "warning"
                status["summary"] = f"{status['summary']} 邮件通知未完成。"
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
        return ScheduleDecision(False, "skipped", "今日已成功更新，不重复运行。", is_trade_day, already_ran, catch_up)
    return ScheduleDecision(True, "running", "已到计划时间且今日未成功更新，开始执行。", is_trade_day, already_ran, catch_up)


def is_trade_day_local(current: datetime, *, settings: Settings) -> bool:
    """Use a conservative local trade-day check, without network access."""
    return current.weekday() < 5


@contextmanager
def scheduled_update_lock(lock_path: str | Path) -> Iterator[None]:
    """Create a lightweight pid lock and prevent concurrent scheduled writes."""
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid", 0))
        except Exception:
            pid = 0
        if pid and _pid_exists(pid):
            raise RuntimeError("已有自动更新任务正在运行。")
    path.write_text(json.dumps({"pid": os.getpid(), "started_at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False), encoding="utf-8")
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


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
    step_overrides: dict[str, Callable[[], dict[str, Any]]],
) -> dict[str, Any]:
    store = DuckDBStore(settings.duckdb_path)
    steps: dict[str, dict[str, Any]] = {}
    for stage, default in [
        ("backup", lambda: backup_local_data(label="scheduled_daily_update", settings=settings)),
        ("workflow", lambda: run_daily_workflow(backup_before_run=False, report_format="all", settings=settings, store=store, quiet=True)),
        ("elder_review", lambda: run_elder_review(settings=settings, store=store)),
        ("entry_zone", lambda: calculate_entry_zones(settings=settings, store=store, quiet=True)),
        ("watchlist", lambda: track_watchlist(settings=settings, store=store, quiet=True)),
        ("workbook", lambda: export_daily_research_workbook(output_path=_workbook_output_path(report_dir), settings=settings, store=store).__dict__),
    ]:
        status["stage"] = stage
        result = step_overrides.get(stage, default)()
        steps[stage] = result if isinstance(result, dict) else {"status": "success", "result": result}
        logs.append(f"{stage}: {steps[stage].get('status', 'success')}")
        if str(steps[stage].get("status", "success")).lower() == "failed":
            status.update(
                {
                    "status": "failed",
                    "summary": f"自动更新在 {stage} 阶段失败。",
                    "failure_reason": str(steps[stage].get("message") or steps[stage].get("error") or "unknown"),
                    "logs": logs,
                    "steps": steps,
                }
            )
            return status
    workbook = steps.get("workbook", {})
    workbook_path = Path(str(workbook.get("output_path", ""))) if workbook.get("output_path") else Path()
    status.update(
        {
            "status": "success",
            "summary": "每日自动更新完成。",
            "stage": "done",
            "candidate_count": _candidate_count(steps),
            "elder_review_count": int(steps.get("elder_review", {}).get("review_count", 0)),
            "entry_zone_count": int(steps.get("entry_zone", {}).get("calculated_count", 0)),
            "watchlist_count": int(steps.get("watchlist", {}).get("snapshot_count", steps.get("watchlist", {}).get("daily_snapshot_count", 0))),
            "external_position_count": int(workbook.get("external_position_rows", 0)),
            "workbook_path": str(workbook_path) if workbook_path else "",
            "workbook_exists": bool(workbook_path and workbook_path.exists()),
            "workbook_size_bytes": workbook_path.stat().st_size if workbook_path and workbook_path.exists() else 0,
            "steps": steps,
            "logs": logs,
        }
    )
    return status


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


def _base_status(*, scheduled_time: str, started_at: datetime, force: bool, catch_up: bool, decision: ScheduleDecision) -> dict[str, Any]:
    return {
        "status": "running",
        "summary": decision.summary,
        "scheduled_time": scheduled_time,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": "",
        "trade_date": started_at.strftime("%Y%m%d"),
        "is_trade_day": decision.is_trade_day,
        "catch_up": catch_up,
        "force": force,
        "already_ran_today": decision.already_ran_today,
        "stage": "start",
        "failure_reason": "",
        "suggested_action": "",
        "diagnosis_status": "",
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
        "notification": {"macos_notification": "skipped", "email_enabled": False, "email_status": "disabled", "email_error": ""},
        "logs": [],
    }


def _already_success_today(previous: dict[str, Any], current: datetime) -> bool:
    return previous.get("status") in SUCCESS_STATUSES and str(previous.get("trade_date")) == current.strftime("%Y%m%d")


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _diagnosis_status(preflight: dict[str, Any]) -> str:
    return "ok" if preflight.get("ok") else "failed"


def _duckdb_status(preflight: dict[str, Any]) -> str:
    duckdb = preflight.get("duckdb", {})
    return "locked" if duckdb.get("locked") else ("ok" if duckdb.get("ok") else "failed")


def _eastmoney_status(preflight: dict[str, Any]) -> str:
    eastmoney = preflight.get("eastmoney_kline", {})
    return "ok" if eastmoney.get("ok") else ("skipped" if eastmoney.get("status") == "skipped" else "failed")


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
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return
    print("收盘后自动更新")
    print(f"- 整体状态: {status.get('status')}")
    print(f"- 计划时间: {status.get('scheduled_time')}")
    print(f"- 实际开始: {status.get('started_at')}")
    print(f"- 完成时间: {status.get('finished_at') or '暂无'}")
    print(f"- 交易日期: {status.get('trade_date')}")
    print(f"- 数据源诊断: {status.get('diagnosis_status') or '暂无'}")
    print(f"- DuckDB: {status.get('duckdb_status') or '暂无'}")
    print(f"- 今日候选: {status.get('candidate_count', 0)}")
    print(f"- 埃尔德复核: {status.get('elder_review_count', 0)}")
    print(f"- 买入区间: {status.get('entry_zone_count', 0)}")
    print(f"- 观察池: {status.get('watchlist_count', 0)}")
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
