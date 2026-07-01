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
    read_scheduled_status,
    run_scheduled_daily_update,
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


def _ok_preflight() -> dict:
    return {
        "ok": True,
        "status": "success",
        "duckdb": {"ok": True, "locked": False},
        "eastmoney_kline": {"ok": True, "status": "success"},
        "suggested_action": "",
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
    """A successful status for today should prevent duplicate runs."""
    previous = {"status": "success", "trade_date": "20260701"}
    decision = should_run_scheduled_update(
        now=datetime(2026, 7, 1, 18, 30),
        scheduled_time="18:00",
        previous_status=previous,
        force=False,
        catch_up=True,
        settings=_settings(tmp_path),
    )
    assert not decision.should_run
    assert "今日已成功更新" in decision.summary


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


def _mock_workbook(tmp_path: Path) -> dict:
    path = tmp_path / "daily_research_mock.xlsx"
    path.write_bytes(b"mock")
    return {"status": "success", "output_path": path, "external_position_rows": 0}
