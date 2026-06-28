"""Tests for whitelisted local command execution helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.runtime import command_runner
from core.runtime.command_runner import open_project_path, run_allowed_command


def test_command_runner_allows_whitelisted_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Whitelisted commands should run through subprocess without shell=True."""
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    result = run_allowed_command("doctor_daily_run", ["--json"], cwd=tmp_path)

    assert result.status == "success"
    assert calls["cmd"][1:4] == ["-m", "core.jobs.doctor_daily_run", "--json"]
    assert calls["kwargs"]["cwd"] == tmp_path
    assert calls["kwargs"]["check"] is False


def test_command_runner_rejects_unlisted_command() -> None:
    """Arbitrary commands should be rejected."""
    with pytest.raises(ValueError):
        run_allowed_command("rm", ["-rf", "reports"])


def test_command_runner_rejects_shell_syntax() -> None:
    """Shell control operators should not be accepted in args."""
    with pytest.raises(ValueError):
        run_allowed_command("doctor_daily_run", ["--json", "&&", "rm"])


def test_open_project_path_allows_project_local_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """open_project_path should only open existing project-local paths."""
    reports = tmp_path / "reports"
    reports.mkdir()
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    result = open_project_path(reports, project_root=tmp_path)

    assert result.status == "success"
    assert calls["cmd"] == ["open", str(reports.resolve())]


def test_open_project_path_rejects_outside_path(tmp_path: Path) -> None:
    """Opening arbitrary paths outside the project should be rejected."""
    outside = tmp_path.parent

    with pytest.raises(ValueError):
        open_project_path(outside, project_root=tmp_path)
