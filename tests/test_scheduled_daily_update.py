"""Tests for Task 57B scheduled daily update workflow."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace

from core.factors.scoring import DEFAULT_WEIGHTS
from core.jobs.install_scheduled_daily_update import build_launchd_plist, install_scheduled_daily_update
from core.jobs.run_scheduled_daily_update import (
    _scheduled_steps,
    read_scheduled_status,
    run_scheduled_daily_update,
    scheduled_update_lock,
    should_run_scheduled_update,
)
from core.jobs.uninstall_scheduled_daily_update import uninstall_scheduled_daily_update
from core.notifications.email import send_email_notification
from core.notifications.macos import build_macos_notification
from core.runtime.command_runner import ALLOWED_COMMANDS


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(duckdb_path=tmp_path / "mock.duckdb")


def _status_paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "runtime" / "scheduled_daily_update_status.json", tmp_path / "runtime" / "scheduled_daily_update.lock"


def _formal_success_status(trade_date: str) -> dict:
    return {
        "status": "success",
        "stage": "done",
        "trade_date": trade_date,
        "research_trade_date": trade_date,
        "formal_run": True,
        "formal_success_date": trade_date,
        "acceptance_mode": False,
        "update_limit": None,
        "allow_intraday": False,
        "intraday_warning": "",
        "workbook_exists": True,
        "workbook_path": "/tmp/daily_research.xlsx",
        "workbook_size_bytes": 1234,
    }


def _ok_preflight() -> dict:
    return {
        "ok": True,
        "status": "success",
        "duckdb": {"ok": True, "locked": False},
        "eastmoney_kline": {"ok": True, "status": "success"},
        "suggested_action": "",
    }


def _warning_preflight_with_curl() -> dict:
    return {
        "ok": True,
        "status": "warning",
        "preflight_allows_run": True,
        "preflight_warning_reason": "Python 请求失败但 curl fallback 可用",
        "curl_fallback_available": True,
        "duckdb": {"ok": True, "locked": False},
        "eastmoney_kline": {"ok": True, "status": "warning", "curl_fallback_available": True},
        "suggested_action": "Python 请求失败但 curl fallback 可用",
    }


def test_scheduled_update_skips_before_scheduled_time(tmp_path: Path) -> None:
    """Before 18:00, non-force scheduled update should skip."""
    decision = should_run_scheduled_update(
        now=datetime(2026, 7, 1, 17, 30),
        scheduled_time="18:00",
        previous_status={},
        force=False,
        catch_up=True,
        settings=_settings(tmp_path),
    )
    assert not decision.should_run
    assert decision.status == "skipped"
    assert "未到计划更新时间" in decision.summary


def test_scheduled_update_skips_if_already_success_today(tmp_path: Path) -> None:
    """A formal successful status for today should prevent duplicate runs."""
    previous = _formal_success_status("20260701")
    decision = should_run_scheduled_update(
        now=datetime(2026, 7, 1, 18, 30),
        scheduled_time="18:00",
        previous_status=previous,
        force=False,
        catch_up=True,
        settings=_settings(tmp_path),
    )
    assert not decision.should_run
    assert "今日已完成正式自动更新" in decision.summary


def test_scheduled_update_runs_after_scheduled_time_when_not_success(tmp_path: Path) -> None:
    """After 18:00, a trading day without success should run."""
    decision = should_run_scheduled_update(
        now=datetime(2026, 7, 1, 18, 30),
        scheduled_time="18:00",
        previous_status={},
        force=False,
        catch_up=True,
        settings=_settings(tmp_path),
    )
    assert decision.should_run


def test_scheduled_update_force_runs_even_if_already_success(tmp_path: Path) -> None:
    """force should bypass already-success status but still go through preflight."""
    status_path, lock_path = _status_paths(tmp_path)
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({"status": "success", "trade_date": "20260701"}), encoding="utf-8")
    called = {"backup": 0}

    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: called.update(backup=1) or {"status": "success"},
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    assert result["status"] == "success"
    assert called["backup"] == 1


def test_scheduled_update_preflight_failure_stops_before_heavy_update(tmp_path: Path) -> None:
    """Preflight failure should stop before backup/update/workbook steps."""
    status_path, lock_path = _status_paths(tmp_path)
    called = {"heavy": False}

    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": lambda: {"ok": False, "status": "failed", "message": "东方财富接口失败", "duckdb": {}, "eastmoney_kline": {}},
            "backup": lambda: called.update(heavy=True) or {"status": "success"},
        },
    )
    assert result["status"] == "failed"
    assert result["stage"] == "preflight"
    assert called["heavy"] is False


def test_preflight_warning_allows_daily_incremental_when_curl_succeeds(tmp_path: Path) -> None:
    """Python request failure with curl fallback should allow daily_incremental to continue."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        update_limit=0,
        update_data=lambda: {"status": "success", "planned_symbols": 3},
        workbook=lambda: _mock_workbook(tmp_path, strategy_rows=3),
    )
    assert result["status"] == "success"

    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _warning_preflight_with_curl,
            "backup": lambda: {"status": "success"},
            "update_data": lambda: {"status": "success", "planned_symbols": 5},
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    assert result["stage"] == "done"
    assert result["status"] == "warning"
    assert result["preflight_allows_run"] is True
    assert result["curl_fallback_available"] is True
    assert "curl fallback" in result["preflight_warning_reason"]


def test_preflight_fails_when_python_and_curl_all_fail(tmp_path: Path) -> None:
    """Fatal preflight should stop before update_data."""
    status_path, lock_path = _status_paths(tmp_path)
    called = {"update": False}
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": lambda: {
                "ok": False,
                "status": "failed",
                "preflight_allows_run": False,
                "duckdb": {"ok": True, "locked": False},
                "eastmoney_kline": {"ok": False, "status": "failed", "curl_fallback_available": False},
                "message": "Python 和 curl 全部失败",
            },
            "update_data": lambda: called.update(update=True) or {"status": "success"},
        },
    )
    assert result["status"] == "failed"
    assert result["stage"] == "preflight"
    assert called["update"] is False


def test_preflight_records_curl_fallback_available(tmp_path: Path) -> None:
    """Scheduled status JSON should record curl fallback availability."""
    status_path, lock_path = _status_paths(tmp_path)
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _warning_preflight_with_curl,
            "backup": lambda: {"status": "success"},
            "update_data": lambda: {"status": "success"},
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    persisted = read_scheduled_status(status_path)
    assert result["curl_fallback_available"] is True
    assert persisted["curl_fallback_available"] is True
    assert persisted["preflight_status"] == "warning"


def test_preflight_warning_message_in_text_output(tmp_path: Path, capsys) -> None:
    """Text output should explain curl fallback warning."""
    status_path, lock_path = _status_paths(tmp_path)
    run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        output_format="text",
        step_overrides={
            "preflight": _warning_preflight_with_curl,
            "backup": lambda: {"status": "success"},
            "update_data": lambda: {"status": "success"},
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    output = capsys.readouterr().out
    assert "数据源网络诊断" in output
    assert "Python 请求失败但 curl fallback 可用" in output
    assert "curl fallback: 可用" in output


def test_scheduled_update_writes_status_json(tmp_path: Path) -> None:
    """Skipped state should still write status JSON."""
    status_path, lock_path = _status_paths(tmp_path)
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 17, 30),
        status_path=status_path,
        lock_path=lock_path,
        settings=_settings(tmp_path),
        skip_notify=True,
    )
    assert status_path.exists()
    assert read_scheduled_status(status_path)["status"] == result["status"]


def test_scheduled_update_exports_workbook_on_success(tmp_path: Path) -> None:
    """Success flow should store workbook path and size from the workbook step."""
    status_path, lock_path = _status_paths(tmp_path)
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: {"status": "success"},
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    assert result["workbook_exists"] is True
    assert result["workbook_size_bytes"] > 0


def test_scheduled_update_lock_prevents_concurrent_runs(tmp_path: Path) -> None:
    """An existing live pid lock should prevent duplicate scheduled writes."""
    status_path, lock_path = _status_paths(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        settings=_settings(tmp_path),
        skip_notify=True,
    )
    assert result["status"] == "skipped"
    assert "正在运行" in result["summary"]


def test_scheduled_update_cleans_stale_lock(tmp_path: Path) -> None:
    """A pid lock with a non-existing process should be removed automatically."""
    lock_path = tmp_path / "runtime" / "scheduled_daily_update.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(json.dumps({"pid": 99999999, "started_at": "2026-07-01T18:00:00"}), encoding="utf-8")
    with scheduled_update_lock(lock_path) as lock_info:
        assert lock_info["stale_lock_cleaned"] is True
        assert lock_path.exists()
    assert not lock_path.exists()


def test_scheduled_update_marks_stale_running_as_interrupted(tmp_path: Path) -> None:
    """A previous running status without a live pid should be marked recoverable."""
    status_path, lock_path = _status_paths(tmp_path)
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({"status": "running", "pid": 99999999, "trade_date": "20260701"}), encoding="utf-8")
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 17, 30),
        status_path=status_path,
        lock_path=lock_path,
        settings=_settings(tmp_path),
        skip_notify=True,
    )
    assert result["status"] == "skipped"
    assert result["previous_run_interrupted"] is True


def test_scheduled_update_handles_keyboard_interrupt(tmp_path: Path) -> None:
    """KeyboardInterrupt should write interrupted status and release the lock."""
    status_path, lock_path = _status_paths(tmp_path)
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
        },
    )
    assert result["status"] == "interrupted"
    assert not lock_path.exists()


def test_single_symbol_timeout_is_recorded_and_skipped(tmp_path: Path) -> None:
    """Update-stage timeout counters should be carried into scheduled status."""
    status_path, lock_path = _status_paths(tmp_path)
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: {"status": "success"},
            "update_data": lambda: {
                "status": "warning",
                "network_timeout_count": 1,
                "network_timeout_examples": ["601299.SH"],
                "failed_symbol_count": 1,
                "failed_symbol_examples": ["601299.SH"],
            },
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    assert result["status"] == "warning"
    assert result["network_timeout_count"] == 1
    assert result["failed_symbol_examples"] == ["601299.SH"]


def test_empty_data_symbols_are_summarized(tmp_path: Path) -> None:
    """Empty-data symbols should be summarized on status, not printed as required per-symbol logs."""
    status_path, lock_path = _status_paths(tmp_path)
    empty_symbols = ["000602.SZ", "000618.SZ", "600005.SH"]
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: {"status": "success"},
            "update_data": lambda: {
                "status": "warning",
                "empty_data_symbol_count": len(empty_symbols),
                "empty_data_symbol_examples": empty_symbols[:2],
                "update_warning_count": len(empty_symbols),
            },
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    assert result["status"] == "warning"
    assert result["empty_data_symbol_count"] == 3
    assert result["empty_data_symbol_examples"] == empty_symbols[:2]


def test_update_stage_timeout_fails_fast(tmp_path: Path) -> None:
    """A timed-out update stage should fail and stop before recompute/export stages."""
    status_path, lock_path = _status_paths(tmp_path)
    called = {"workflow": False}
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: {"status": "success"},
            "update_data": lambda: {"status": "failed", "message": "update_data 阶段超时：1 秒。", "timed_out": True},
            "workflow": lambda: called.update(workflow=True) or {"status": "success"},
        },
    )
    assert result["status"] == "failed"
    assert result["stage"] == "update_data"
    assert "超时" in result["failure_reason"]
    assert called["workflow"] is False


def test_dry_run_does_not_run_heavy_update(tmp_path: Path) -> None:
    """dry-run should not execute backup/update/workbook steps."""
    status_path, lock_path = _status_paths(tmp_path)
    called = {"heavy": False}
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        dry_run=True,
        status_path=status_path,
        lock_path=lock_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: called.update(heavy=True) or {"status": "success"},
            "update_data": lambda: called.update(heavy=True) or {"status": "success"},
        },
    )
    assert result["stage"] == "dry_run"
    assert called["heavy"] is False


def test_force_update_limit_is_passed_to_update_stage(tmp_path: Path) -> None:
    """full_backfill update_limit should become run_full_batch_update --max-symbols."""
    steps = _scheduled_steps(
        settings=_settings(tmp_path),
        workbook_path=tmp_path / "daily.xlsx",
        update_limit=50,
        update_batch_size=20,
        update_lookback_days=250,
        update_max_retries=1,
        update_mode="full_backfill",
        recent_days=5,
        max_update_symbols=0,
        continue_on_symbol_failure=True,
        stage_timeout_seconds=180,
        update_stage_timeout_seconds=180,
        verbose=False,
        research_trade_date="20260701",
    )
    update = next(step for step in steps if step.name == "update_data")
    assert "core.jobs.run_full_batch_update" in update.command
    assert update.command[update.command.index("--max-symbols") + 1] == "50"
    assert update.command[update.command.index("--batch-size") + 1] == "20"
    assert update.env == {"REAL_DATA_END_DATE": "20260701"}


def test_scheduled_update_defaults_to_daily_incremental(tmp_path: Path) -> None:
    """The default scheduled update should use the lightweight daily_incremental stage."""
    steps = _scheduled_steps(
        settings=_settings(tmp_path),
        workbook_path=tmp_path / "daily.xlsx",
        update_limit=0,
        update_batch_size=20,
        update_lookback_days=250,
        update_max_retries=1,
        update_mode="daily_incremental",
        recent_days=5,
        max_update_symbols=0,
        continue_on_symbol_failure=True,
        stage_timeout_seconds=180,
        update_stage_timeout_seconds=180,
        verbose=False,
        research_trade_date="20260701",
    )
    update = next(step for step in steps if step.name == "update_data")
    assert "core.jobs.update_real_data" in update.command
    assert update.env["FULL_UPDATE_MODE"] == "stale_only"
    assert update.env["FULL_UPDATE_LOOKBACK_DAYS"] == "5"
    assert update.env["REAL_DATA_END_DATE"] == "20260701"
    assert update.env["FULL_UPDATE_MAX_SYMBOLS"] == "800"
    assert "core.jobs.run_full_batch_update" not in update.command


def test_text_mode_prints_start_immediately(tmp_path: Path, capsys) -> None:
    """Text mode should print startup lines before heavy work."""
    status_path, lock_path = _status_paths(tmp_path)
    run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 17, 30),
        status_path=status_path,
        lock_path=lock_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        output_format="text",
        update_limit=50,
    )
    output = capsys.readouterr().out
    assert "收盘后自动更新" in output
    assert "阶段: 启动" in output
    assert "update_limit=50" in output


def test_text_mode_prints_each_stage_with_flush(tmp_path: Path, capsys) -> None:
    """Force text run should show all scheduled stage labels."""
    status_path, lock_path = _status_paths(tmp_path)
    run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        output_format="text",
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: {"status": "success"},
            "update_data": lambda: {"status": "success", "planned_symbols": 50},
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    output = capsys.readouterr().out
    for phrase in ["阶段: 检查运行锁", "阶段: DuckDB read_only 检查", "阶段: 数据源网络诊断", "阶段: 备份 DuckDB", "阶段: 更新数据", "阶段: 运行日常工作流", "阶段: 埃尔德复核", "阶段: 买入区间", "阶段: 观察池跟踪", "阶段: 导出每日研究 Excel", "阶段: 通知", "阶段: 完成"]:
        assert phrase in output


def test_stage_status_written_before_heavy_work(tmp_path: Path) -> None:
    """Each stage should write running status before executing its body."""
    status_path, lock_path = _status_paths(tmp_path)
    observed: dict[str, str] = {}

    def backup_step() -> dict:
        observed.update(read_scheduled_status(status_path))
        return {"status": "success"}

    run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": backup_step,
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    assert observed["status"] == "running"
    assert observed["stage"] == "backup"
    assert observed["last_heartbeat_at"]


def test_stage_timeout_exits_and_releases_lock(tmp_path: Path) -> None:
    """Subprocess stage timeout should fail fast and release the lock."""
    from core.jobs.run_scheduled_daily_update import _run_module_stage

    status_path, lock_path = _status_paths(tmp_path)
    status = {"stage": "update_data", "current_stage": "update_data", "last_heartbeat_at": "", "processed_symbol_count": 0, "total_symbol_count": 0}
    result = _run_module_stage(
        "update_data",
        [os.sys.executable, "-c", "import time; time.sleep(5)"],
        1,
        status=status,
        status_path=status_path,
        output_format="text",
    )
    assert result["status"] == "failed"
    assert result["timed_out"] is True
    assert "超时" in result["message"]


def test_heartbeat_updates_during_long_stage(tmp_path: Path) -> None:
    """Heartbeat parser should update progress counters while a stage is running."""
    from core.jobs.run_scheduled_daily_update import _update_heartbeat_from_line

    status = {"processed_symbol_count": 0, "failed_symbol_count": 0, "skipped_symbol_count": 0}
    _update_heartbeat_from_line(status, "[progress] step=daily_price current=000001 success=3 failed=1 skipped=46 message='x'")
    assert status["processed_symbol_count"] == 3
    assert status["failed_symbol_count"] == 1
    assert status["skipped_symbol_count"] == 46
    assert status["last_heartbeat_at"]


def test_force_update_limit_50_finishes_in_test(tmp_path: Path) -> None:
    """Mocked force run with update_limit=50 should finish without real network calls."""
    status_path, lock_path = _status_paths(tmp_path)
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 1, 18, 30),
        force=True,
        update_limit=50,
        stage_timeout_seconds=180,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: {"status": "success"},
            "update_data": lambda: {"status": "success", "planned_symbols": 50},
            "workflow": lambda: {"status": "success", "candidate_count": 2},
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": lambda: _mock_workbook(tmp_path),
        },
    )
    assert result["status"] == "success"
    assert not lock_path.exists()


def test_final_status_counts_from_workbook_step(tmp_path: Path) -> None:
    """Top-level counts should come from the workbook step when available."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        workbook=lambda: _mock_workbook(
            tmp_path,
            trade_date="20260701",
            strategy_rows=10,
            elder_rows=50,
            entry_zone_rows=20,
            watchlist_rows=50,
            external_position_rows=0,
        ),
    )
    assert result["candidate_count"] == 10
    assert result["elder_review_count"] == 50
    assert result["entry_zone_count"] == 20
    assert result["watchlist_count"] == 50
    assert result["external_position_count"] == 0


def test_final_status_dates_distinguish_run_and_research_trade_date(tmp_path: Path) -> None:
    """Run date and research trade date should not be conflated."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 2, 1, 5),
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260701"),
    )
    assert result["run_date"] == "20260702"
    assert result["research_trade_date"] == "20260701"
    assert result["latest_completed_trade_date"] == "20260701"
    assert result["trade_date"] == "20260701"


def test_update_limit_sets_acceptance_mode(tmp_path: Path, capsys) -> None:
    """Small update_limit force runs should be marked as acceptance mode."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(tmp_path, status_path, lock_path, update_limit=50, output_format="text")
    output = capsys.readouterr().out
    assert result["acceptance_mode"] is True
    assert result["update_limit"] == 50
    assert result["formal_run"] is False
    assert result["formal_success_date"] == ""
    assert "本次为小批量验收运行" in output


def test_acceptance_run_does_not_block_formal_scheduled_run(tmp_path: Path) -> None:
    """A prior update-limit acceptance run must not block the 18:00 formal run."""
    previous = {
        **_formal_success_status("20260701"),
        "formal_run": False,
        "formal_success_date": "",
        "acceptance_mode": True,
        "update_limit": 500,
    }
    decision = should_run_scheduled_update(
        now=datetime(2026, 7, 2, 18, 0, 4),
        scheduled_time="18:00",
        previous_status=previous,
        force=False,
        catch_up=True,
        settings=_settings(tmp_path),
    )
    assert decision.should_run
    assert decision.already_ran_today is False


def test_intraday_run_does_not_block_formal_scheduled_run(tmp_path: Path) -> None:
    """A prior --allow-intraday run must not block the formal close-time run."""
    previous = {
        **_formal_success_status("20260702"),
        "formal_run": False,
        "formal_success_date": "",
        "allow_intraday": True,
        "intraday_warning": "盘中强制运行，结果可能基于未完成交易日数据，不代表正式收盘后结果。",
    }
    decision = should_run_scheduled_update(
        now=datetime(2026, 7, 2, 18, 30),
        scheduled_time="18:00",
        previous_status=previous,
        force=False,
        catch_up=True,
        settings=_settings(tmp_path),
    )
    assert decision.should_run


def test_update_limit_run_does_not_set_formal_success(tmp_path: Path) -> None:
    """update_limit runs should not write formal_success_date."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(tmp_path, status_path, lock_path, update_limit=300)
    assert result["acceptance_mode"] is True
    assert result["formal_run"] is False
    assert result["formal_success_date"] == ""


def test_formal_success_blocks_duplicate_formal_run(tmp_path: Path) -> None:
    """Only a completed formal run with workbook metadata should block duplicates."""
    previous = _formal_success_status("20260702")
    decision = should_run_scheduled_update(
        now=datetime(2026, 7, 2, 18, 30),
        scheduled_time="18:00",
        previous_status=previous,
        force=False,
        catch_up=True,
        settings=_settings(tmp_path),
    )
    assert not decision.should_run
    assert decision.already_ran_today is True


def test_skipped_status_from_acceptance_state_does_not_clear_previous_formal_fields(tmp_path: Path) -> None:
    """A skipped before-time status should preserve previous formal_success_date."""
    status_path, lock_path = _status_paths(tmp_path)
    status_path.parent.mkdir(parents=True)
    previous = _formal_success_status("20260701")
    previous.update({"acceptance_mode": True, "update_limit": 500, "status": "success", "trade_date": "20260702"})
    status_path.write_text(json.dumps(previous), encoding="utf-8")
    result = run_scheduled_daily_update(
        now=datetime(2026, 7, 2, 17, 30),
        status_path=status_path,
        lock_path=lock_path,
        settings=_settings(tmp_path),
        skip_notify=True,
    )
    assert result["status"] == "skipped"
    assert result["formal_success_date"] == "20260701"


def test_workflow_skipped_steps_not_mixed_with_skipped_symbols(tmp_path: Path) -> None:
    """Workflow skipped step count and update skipped symbols must stay separate."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        update_data=lambda: {"status": "warning", "update_skipped_symbol_count": 5001, "empty_data_symbol_count": 17},
        workflow=lambda: {"status": "success", "candidate_count": 10, "workflow_skipped_step_count": 3},
    )
    assert result["update_skipped_symbol_count"] == 5001
    assert result["skipped_symbol_count"] == 5001
    assert result["workflow_skipped_step_count"] == 3


def test_daily_incremental_partial_symbol_failures_continue_workflow(tmp_path: Path) -> None:
    """daily_incremental should continue to workbook when only some symbols fail."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        update_limit=0,
        update_data=lambda: {
            "status": "warning",
            "failed_symbol_count": 2,
            "failed_symbol_examples": ["000001.SZ", "600000.SH"],
            "update_skipped_symbol_count": 0,
        },
        workbook=lambda: _mock_workbook(tmp_path, strategy_rows=10),
    )
    assert result["status"] == "warning"
    assert result["stage"] == "done"
    assert result["workbook_exists"] is True
    assert result["update_failed_symbol_count"] == 2
    assert result["update_failed_symbol_examples"] == ["000001.SZ", "600000.SH"]
    assert result["update_continued_after_partial_failure"] is True


def test_empty_data_examples_are_clean_symbol_codes() -> None:
    """Example arrays should contain clean stock codes only."""
    from core.jobs.run_scheduled_daily_update import _parse_update_output

    parsed = _parse_update_output("- 空数据股票: 17 只，样例: 000788.SZ, 000789.SZ\n- 失败数量: 17")
    assert parsed["empty_data_symbol_examples"] == ["000788.SZ", "000789.SZ"]
    assert all("样例" not in item and "只" not in item for item in parsed["empty_data_symbol_examples"])


def test_warning_does_not_reset_success_counts(tmp_path: Path) -> None:
    """Update warning should keep successful workbook counts on the final status."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        update_data=lambda: {"status": "warning", "empty_data_symbol_count": 17, "update_skipped_symbol_count": 5001},
        workbook=lambda: _mock_workbook(
            tmp_path,
            strategy_rows=10,
            elder_rows=50,
            entry_zone_rows=20,
            watchlist_rows=50,
            external_position_rows=0,
        ),
    )
    assert result["status"] == "warning"
    assert result["candidate_count"] == 10
    assert result["elder_review_count"] == 50
    assert result["entry_zone_count"] == 20
    assert result["watchlist_count"] == 50


def test_force_before_scheduled_time_uses_previous_completed_trade_date_by_default(tmp_path: Path) -> None:
    """force before 18:00 should default to the previous completed trade day."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 2, 9, 52),
        update_limit=0,
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260702"),
    )
    assert result["run_date"] == "20260702"
    assert result["research_trade_date"] == "20260701"
    assert result["latest_completed_trade_date"] == "20260701"
    assert result["trade_date"] == "20260701"
    assert result["intraday_warning"] == ""
    assert result["formal_run"] is False
    assert result["formal_success_date"] == ""
    assert "不会阻止 18:00" in result["formal_run_note"]


def test_intraday_daily_incremental_does_not_set_formal_success_date(tmp_path: Path) -> None:
    """A before-scheduled daily_incremental force run must not count as formal success."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 3, 9, 52),
        update_limit=0,
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260703"),
    )
    assert result["status"] == "success"
    assert result["formal_run"] is False
    assert result["formal_success_date"] == ""
    assert result["workbook_exists"] is True
    assert result["research_trade_date"] == "20260702"


def test_before_scheduled_time_uses_previous_completed_trade_date_unless_allow_intraday(tmp_path: Path) -> None:
    """Before scheduled time should use previous completed date unless allow-intraday is explicit."""
    status_path, lock_path = _status_paths(tmp_path)
    default_result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 3, 9, 52),
        update_limit=0,
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260703"),
    )
    intraday_result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 3, 9, 52),
        update_limit=0,
        allow_intraday=True,
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260703"),
    )
    assert default_result["research_trade_date"] == "20260702"
    assert intraday_result["research_trade_date"] == "20260703"
    assert intraday_result["formal_run"] is False


def test_intraday_force_does_not_block_1800_formal_run(tmp_path: Path) -> None:
    """A successful intraday force run should not make 18:00 already_ran_today true."""
    status_path, lock_path = _status_paths(tmp_path)
    intraday = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 3, 9, 52),
        update_limit=0,
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260703"),
    )
    assert intraday["formal_run"] is False

    decision = should_run_scheduled_update(
        now=datetime(2026, 7, 3, 18, 1),
        scheduled_time="18:00",
        previous_status=read_scheduled_status(status_path),
        force=False,
        catch_up=True,
        settings=_settings(tmp_path),
    )
    assert decision.should_run is True
    assert decision.already_ran_today is False


def test_allow_intraday_uses_current_trade_date_with_warning(tmp_path: Path, capsys) -> None:
    """--allow-intraday may use current trade date but must warn clearly."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 2, 9, 52),
        update_limit=0,
        allow_intraday=True,
        output_format="text",
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260702"),
    )
    output = capsys.readouterr().out
    assert result["research_trade_date"] == "20260702"
    assert "盘中强制运行" in result["intraday_warning"]
    assert "盘中强制运行" in output
    assert result["formal_run"] is False
    assert result["formal_success_date"] == ""


def test_allow_intraday_sets_formal_run_false(tmp_path: Path) -> None:
    """--allow-intraday should always stay outside formal close-time success."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 2, 9, 52),
        update_limit=0,
        allow_intraday=True,
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260702"),
    )
    assert result["allow_intraday"] is True
    assert result["formal_run"] is False
    assert result["formal_success_date"] == ""


def test_scheduled_after_1800_uses_current_trade_date(tmp_path: Path) -> None:
    """After scheduled time, current trade day is considered completed."""
    status_path, lock_path = _status_paths(tmp_path)
    result = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 2, 18, 30),
        update_limit=0,
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260702"),
    )
    assert result["research_trade_date"] == "20260702"
    assert result["latest_completed_trade_date"] == "20260702"
    assert result["formal_run"] is True
    assert result["formal_success_date"] == "20260702"


def test_formal_success_only_after_scheduled_time(tmp_path: Path) -> None:
    """Only after scheduled time may a completed run write formal_success_date."""
    status_path, lock_path = _status_paths(tmp_path)
    before = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 2, 9, 52),
        update_limit=0,
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260702"),
    )
    assert before["formal_run"] is False
    assert before["formal_success_date"] == ""

    after = _successful_scheduled_run(
        tmp_path,
        status_path,
        lock_path,
        now=datetime(2026, 7, 2, 18, 30),
        update_limit=0,
        workbook=lambda: _mock_workbook(tmp_path, trade_date="20260702"),
    )
    assert after["formal_run"] is True
    assert after["formal_success_date"] == "20260702"


def test_macos_notification_builds_safe_message() -> None:
    """macOS notification command should escape quotes and newlines."""
    command = build_macos_notification('标题 "A"', "第一行\n第二行")
    joined = " ".join(command)
    assert "osascript" in command[0]
    assert '\\"A\\"' in joined
    assert "\n" not in joined


def test_email_notification_disabled_by_default() -> None:
    """Email notification should be disabled by default."""
    result = send_email_notification(subject="x", body="y", env={})
    assert result["status"] == "disabled"


def test_email_notification_masks_sensitive_config() -> None:
    """Email failure status should not expose SMTP password-like text."""
    result = send_email_notification(
        subject="x",
        body="y",
        env={"NOTIFY_EMAIL_ENABLED": "true", "SMTP_PASSWORD": "secret-password"},
    )
    assert result["status"] == "skipped"
    assert "secret-password" not in json.dumps(result)


def test_install_scheduled_daily_update_generates_launchd_plist(tmp_path: Path) -> None:
    """LaunchAgent dry-run should include 18:00, project dir, venv python, and catch-up command."""
    result = install_scheduled_daily_update(
        scheduled_time="18:00",
        project_dir=tmp_path,
        python_path=tmp_path / ".venv" / "bin" / "python",
        plist_dir=tmp_path,
        dry_run=True,
    )
    plist = result["plist"]
    assert result["status"] == "dry_run"
    assert "<key>Hour</key>" in plist and "<integer>18</integer>" in plist
    assert str(tmp_path) in plist
    assert "run_scheduled_daily_update" in plist
    assert "--catch-up" in plist
    assert "--update-mode" in plist
    assert "daily_incremental" in plist


def test_uninstall_scheduled_daily_update_dry_run(tmp_path: Path) -> None:
    """Uninstall dry-run should not modify user LaunchAgents."""
    result = uninstall_scheduled_daily_update(plist_dir=tmp_path, dry_run=True)
    assert result["status"] == "dry_run"
    assert "不修改系统" in result["message"]


def test_streamlit_shows_scheduled_update_status_and_download() -> None:
    """Streamlit should show scheduled status, download, and manual catch-up controls."""
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    assert "自动更新状态" in source
    assert "下载最新自动更新 Excel" in source
    assert "手动补跑一次自动更新" in source
    assert "run_scheduled_daily_update" in ALLOWED_COMMANDS
    assert "install_scheduled_daily_update" in ALLOWED_COMMANDS
    assert "uninstall_scheduled_daily_update" in ALLOWED_COMMANDS


def test_no_algorithm_changes() -> None:
    """Task 57B should not alter scoring, selection, Elder, or entry-zone logic."""
    assert DEFAULT_WEIGHTS == {
        "trend_score": 0.30,
        "momentum_score": 0.20,
        "liquidity_score": 0.20,
        "fundamental_score": 0.15,
        "volatility_score": 0.15,
    }
    root = Path(__file__).resolve().parents[1]
    selection_source = (root / "core" / "strategy" / "selector.py").read_text(encoding="utf-8")
    elder_source = (root / "core" / "technical" / "elder.py").read_text(encoding="utf-8")
    entry_zone_source = (root / "core" / "entry_zones" / "calculator.py").read_text(encoding="utf-8")
    assert 'sort_values(["trade_date", "total_score", "ts_code"], ascending=[True, False, True])' in selection_source
    assert "does not replace or\n    modify ``total_score``" in elder_source
    assert "calculate_entry_zones_for_targets" in entry_zone_source


def _successful_scheduled_run(
    tmp_path: Path,
    status_path: Path,
    lock_path: Path,
    *,
    now: datetime | None = None,
    update_limit: int = 50,
    output_format: str = "json",
    allow_intraday: bool = False,
    update_data=None,
    workflow=None,
    workbook=None,
) -> dict:
    return run_scheduled_daily_update(
        now=now or datetime(2026, 7, 2, 1, 5),
        force=True,
        update_limit=update_limit,
        allow_intraday=allow_intraday,
        status_path=status_path,
        lock_path=lock_path,
        report_dir=tmp_path,
        settings=_settings(tmp_path),
        skip_notify=True,
        output_format=output_format,
        step_overrides={
            "preflight": _ok_preflight,
            "backup": lambda: {"status": "success"},
            "update_data": update_data or (lambda: {"status": "success", "update_skipped_symbol_count": 0}),
            "workflow": workflow or (lambda: {"status": "success", "candidate_count": 2}),
            "elder_review": lambda: {"status": "success", "review_count": 2},
            "entry_zone": lambda: {"status": "success", "calculated_count": 2},
            "watchlist": lambda: {"status": "success", "snapshot_count": 1},
            "workbook": workbook or (lambda: _mock_workbook(tmp_path)),
        },
    )


def _mock_workbook(
    tmp_path: Path,
    *,
    trade_date: str = "20260701",
    strategy_rows: int = 2,
    elder_rows: int = 2,
    entry_zone_rows: int = 2,
    watchlist_rows: int = 1,
    external_position_rows: int = 0,
) -> dict:
    path = tmp_path / "daily_research_mock.xlsx"
    path.write_bytes(b"mock")
    return {
        "status": "success",
        "trade_date": trade_date,
        "output_path": path,
        "strategy_rows": strategy_rows,
        "elder_rows": elder_rows,
        "entry_zone_rows": entry_zone_rows,
        "watchlist_rows": watchlist_rows,
        "external_position_rows": external_position_rows,
    }
