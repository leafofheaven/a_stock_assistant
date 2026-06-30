"""Tests for live progress formatting and streaming command output with mock subprocesses."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.runtime import command_runner
from core.runtime.command_runner import run_command_streaming
from core.runtime.progress import ProgressState, format_progress_line, parse_progress_line


def test_progress_line_format_is_stable_and_parseable() -> None:
    """Progress lines should keep a stable prefix and parse back to state."""
    state = ProgressState(
        step="update_real_data",
        current="000001.SZ",
        success=1,
        failed=0,
        skipped=0,
        message="正在处理 平安银行",
    )

    line = format_progress_line(state)
    parsed = parse_progress_line(line)

    assert line.startswith("[progress] step=update_real_data")
    assert parsed == state
    assert parse_progress_line("normal log line") is None


def test_streaming_runner_returns_lines_incrementally(monkeypatch, tmp_path: Path) -> None:
    """Streaming runner should call on_line for every output line."""
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = iter(["line 1\n", "[progress] step=job current=a success=1 failed=0 skipped=0 message=ok\n"])

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    calls = {}

    def fake_popen(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(command_runner.subprocess, "Popen", fake_popen)
    lines: list[str] = []

    result = run_command_streaming("doctor_daily_run", ["--json"], cwd=tmp_path, on_line=lines.append)

    assert result.status == "success"
    assert lines == ["line 1", "[progress] step=job current=a success=1 failed=0 skipped=0 message=ok"]
    assert "line 1" in result.stdout
    assert calls["cmd"][1:4] == ["-m", "core.jobs.doctor_daily_run", "--json"]
    assert calls["kwargs"]["stderr"] == command_runner.subprocess.STDOUT


def test_streaming_runner_allows_task51_preflight_and_full_batch(monkeypatch, tmp_path: Path) -> None:
    """Task 51 page buttons should not fail with Command is not allowed."""
    calls: list[list[str]] = []

    class FakeProcess:
        stdout = iter(["ok\n"])

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return FakeProcess()

    monkeypatch.setattr(command_runner.subprocess, "Popen", fake_popen)

    assert run_command_streaming("preflight_data_source", cwd=tmp_path).status == "success"
    assert run_command_streaming("run_full_batch_update", ["--dry-run", "--skip-network-preflight"], cwd=tmp_path).status == "success"
    assert calls[0][1:3] == ["-m", "core.jobs.preflight_data_source"]
    assert calls[1][1:3] == ["-m", "core.jobs.run_full_batch_update"]
    assert calls[1][3:] == ["--dry-run", "--skip-network-preflight"]


def test_streaming_runner_returns_failed_status_and_logs(monkeypatch, tmp_path: Path) -> None:
    """Non-zero commands should preserve return code and output logs."""
    class FakeProcess:
        stdout = iter(["starting\n", "failed\n"])

        def wait(self, timeout=None) -> int:
            return 2

        def kill(self) -> None:
            return None

    monkeypatch.setattr(command_runner.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    result = run_command_streaming("doctor_daily_run", cwd=tmp_path)

    assert result.status == "failed"
    assert result.returncode == 2
    assert "failed" in result.stdout


def test_existing_run_allowed_command_still_uses_subprocess_run(monkeypatch, tmp_path: Path) -> None:
    """Original non-streaming command behavior should remain available."""
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    result = command_runner.run_allowed_command("doctor_daily_run", ["--json"], cwd=tmp_path)

    assert result.status == "success"
    assert result.stdout == "ok"
    assert calls["kwargs"]["capture_output"] is True
