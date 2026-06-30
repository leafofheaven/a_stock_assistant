"""Tests for Task 51 full batch update UI precheck helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.jobs.run_full_batch_update import run_full_batch_update
from core.runtime.data_source_preflight import (
    check_duckdb_access,
    check_eastmoney_kline,
    detect_proxy_settings,
)
from scripts.verify_task import VERIFY_COMMANDS
from web.streamlit_app import build_full_batch_update_args, summarize_full_batch_update_result


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["curl"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_proxy_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proxy detection should report Clash-like and socks/http/https proxies."""
    monkeypatch.setattr(
        "urllib.request.getproxies",
        lambda: {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7897", "all": "socks5://localhost:7890"},
    )

    result = detect_proxy_settings()

    assert result["has_proxy"] is True
    assert "127.0.0.1:7897" in str(result["proxies"])
    assert "socks" in str(result["proxies"])


def test_eastmoney_precheck_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eastmoney concrete kline API should pass only when rc=0 and klines are present."""
    payload = {"rc": 0, "data": {"klines": ["2024-01-02,1,2,3,1,100,1000,0,0,0,1"]}}
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _completed(stdout=json.dumps(payload)))

    result = check_eastmoney_kline()

    assert result["ok"] is True
    assert result["kline_count"] == 1


@pytest.mark.parametrize(
    "completed",
    [
        _completed(stdout=""),
        _completed(stdout="not json"),
        _completed(stdout=json.dumps({"rc": 1, "data": {"klines": ["x"]}})),
        _completed(stdout=json.dumps({"rc": 0, "data": {"klines": []}})),
        subprocess.TimeoutExpired(cmd=["curl"], timeout=1),
    ],
)
def test_eastmoney_precheck_failure(monkeypatch: pytest.MonkeyPatch, completed: object) -> None:
    """Empty, non-JSON, rc failure, empty klines, and connection exceptions should fail."""
    def fake_run(*args, **kwargs):
        if isinstance(completed, BaseException):
            raise completed
        return completed

    monkeypatch.setattr("subprocess.run", fake_run)

    result = check_eastmoney_kline()

    assert result["ok"] is False
    assert "东方财富 K 线接口当前不可用" in result["message"]


def test_precheck_failure_does_not_start_update(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preflight failure should block update_real_data."""
    called = {"update": False}
    monkeypatch.setattr(
        "core.jobs.run_full_batch_update.run_data_source_preflight",
        lambda **kwargs: {"ok": False, "status": "failed", "message": "precheck_failure"},
    )
    monkeypatch.setattr(
        "core.jobs.run_full_batch_update.update_real_data",
        lambda **kwargs: called.update(update=True) or {"status": "success"},
    )

    result = run_full_batch_update(preflight=True)

    assert result["status"] == "failed"
    assert result["message"] == "precheck_failure"
    assert called["update"] is False


def test_duckdb_lock_blocks_update(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """DuckDB lock detection should return the friendly lock message."""
    db_path = tmp_path / "locked.duckdb"
    db_path.write_bytes(b"")
    monkeypatch.setattr("duckdb.connect", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Conflicting lock")))

    result = check_duckdb_access(db_path)

    assert result["ok"] is False
    assert result["locked"] is True
    assert "DuckDB is locked by another process" in result["message"]


def test_page_params_to_update_config() -> None:
    """Page controls should map to the bounded full update CLI parameters."""
    args = build_full_batch_update_args(
        mode_label="优先补缺数据股票",
        max_symbols=500,
        batch_size=50,
        lookback_days=250,
        max_retries=1,
        skip_empty_unavailable=True,
        preflight=True,
    )

    assert args == [
        "--mode",
        "missing_first",
        "--max-symbols",
        "500",
        "--batch-size",
        "50",
        "--lookback-days",
        "250",
        "--max-retries",
        "1",
    ]


def test_update_summary_metrics() -> None:
    """Summary helper should calculate coverage and before/after deltas."""
    before = {"priced_symbol_count": 100, "missing_symbol_count": 50, "selection_ready_count": 90, "coverage_rate": 0.50}
    after = {"priced_symbol_count": 120, "missing_symbol_count": 30, "selection_ready_count": 110, "coverage_rate": 0.60}
    result = {
        "planned_count": 50,
        "success_symbols": 30,
        "failed_symbols": 2,
        "empty_data_symbols": ["000024.SZ"],
        "deferred_symbols": 4800,
        "written_rows": {"daily_price": 1000, "daily_basic": 1000, "adj_factor": 20},
    }

    summary = summarize_full_batch_update_result(before, after, result)

    assert summary["本次新增覆盖股票数量"] == 20
    assert summary["本次失败股票数量"] == 2
    assert summary["本次空数据股票数量"] == 1
    assert summary["本次未处理股票数量"] == 4800
    assert summary["覆盖率变化"] == "50.00% -> 60.00%"


def test_wording_no_misleading_skipped() -> None:
    """Task 51 page wording should use unprocessed wording for full deferred symbols."""
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")

    assert "本次未处理数量" in source
    assert "本次未纳入计划" in source
    assert "已跳过数量" not in source


def test_streamlit_import_has_no_side_effect() -> None:
    """Importing the Streamlit module should not auto-run update_real_data."""
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    load_section = source.split("def load_dashboard_data", 1)[-1].split("def _computed_real_dashboard_data", 1)[0]

    assert "update_real_data(" not in load_section


def test_verify_task51_clean_workspace_command_list() -> None:
    """Task51 verification should use no-report dry-run commands and clean generated reports."""
    commands = VERIFY_COMMANDS["task51"]
    flattened = " ".join(" ".join(command) for command in commands)

    assert "preflight_data_source" in flattened
    assert "--skip-network" in flattened
    assert "run_full_batch_update" in flattened
    assert "--dry-run" in flattened
    assert "clean_generated_reports" in flattened


def test_run_full_batch_update_dry_run_uses_runtime_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run should validate page parameters without calling update_real_data."""
    called = {"update": False}
    monkeypatch.setattr("core.jobs.run_full_batch_update.run_data_source_preflight", lambda **kwargs: {"ok": True, "status": "success"})
    monkeypatch.setattr("core.jobs.run_full_batch_update.update_real_data", lambda **kwargs: called.update(update=True) or {"status": "success"})
    settings = SimpleNamespace(
        model_copy=lambda update: SimpleNamespace(**update),
    )

    result = run_full_batch_update(
        mode="stale_first",
        max_symbols=200,
        batch_size=20,
        lookback_days=120,
        max_retries=0,
        dry_run=True,
        settings=settings,  # type: ignore[arg-type]
    )

    assert result["status"] == "success"
    assert result["settings"]["mode"] == "stale_first"
    assert called["update"] is False
