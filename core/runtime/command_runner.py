"""Whitelisted local command execution for the Streamlit console."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ALLOWED_COMMANDS: dict[str, list[str]] = {
    "doctor_daily_run": [sys.executable, "-m", "core.jobs.doctor_daily_run"],
    "update_real_data": [sys.executable, "-m", "core.jobs.update_real_data"],
    "run_full_batch_update": [sys.executable, "-m", "core.jobs.run_full_batch_update"],
    "preflight_data_source": [sys.executable, "-m", "core.jobs.preflight_data_source"],
    "diagnose_data_source_network": [sys.executable, "-m", "core.jobs.diagnose_data_source_network"],
    "run_scheduled_daily_update": [sys.executable, "-m", "core.jobs.run_scheduled_daily_update"],
    "install_scheduled_daily_update": [sys.executable, "-m", "core.jobs.install_scheduled_daily_update"],
    "uninstall_scheduled_daily_update": [sys.executable, "-m", "core.jobs.uninstall_scheduled_daily_update"],
    "run_daily_workflow": [sys.executable, "-m", "core.jobs.run_daily_workflow"],
    "run_daily_selection": [sys.executable, "-m", "core.jobs.run_daily_selection"],
    "diagnose_data_quality": [sys.executable, "-m", "core.jobs.diagnose_data_quality"],
    "diagnose_factors": [sys.executable, "-m", "core.jobs.diagnose_factors"],
    "refresh_watchlist_scores": [sys.executable, "-m", "core.jobs.refresh_watchlist_scores"],
    "diagnose_watchlist": [sys.executable, "-m", "core.jobs.diagnose_watchlist"],
    "export_watchlist": [sys.executable, "-m", "core.jobs.export_watchlist"],
    "calculate_entry_zones": [sys.executable, "-m", "core.jobs.calculate_entry_zones"],
    "diagnose_entry_zones": [sys.executable, "-m", "core.jobs.diagnose_entry_zones"],
    "export_entry_zone_report": [sys.executable, "-m", "core.jobs.export_entry_zone_report"],
    "export_daily_research_workbook": [sys.executable, "-m", "core.jobs.export_daily_research_workbook"],
    "run_lookback_analysis": [sys.executable, "-m", "core.jobs.run_lookback_analysis"],
    "generate_external_position_template": [sys.executable, "-m", "core.jobs.generate_external_position_template"],
    "import_external_trades": [sys.executable, "-m", "core.jobs.import_external_trades"],
    "import_external_positions": [sys.executable, "-m", "core.jobs.import_external_positions"],
    "match_external_positions": [sys.executable, "-m", "core.jobs.match_external_positions"],
    "diagnose_external_positions": [sys.executable, "-m", "core.jobs.diagnose_external_positions"],
    "export_external_position_report": [sys.executable, "-m", "core.jobs.export_external_position_report"],
    "clean_generated_reports": [sys.executable, "-m", "core.jobs.clean_generated_reports"],
    "backup_local_data": [sys.executable, "-m", "core.jobs.backup_local_data"],
    "list_backups": [sys.executable, "-m", "core.jobs.list_backups"],
}

SHELL_META = {";", "&&", "||", "|", "$(", "`", ">", "<"}


@dataclass(frozen=True)
class CommandResult:
    """Result from a local command execution."""

    command_key: str
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def status(self) -> str:
        """Return success/failed/timed_out for display."""
        if self.timed_out:
            return "timed_out"
        return "success" if self.returncode == 0 else "failed"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly result."""
        return {
            "command_key": self.command_key,
            "args": self.args,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "status": self.status,
        }


StreamLineCallback = Callable[[str], None]


def run_allowed_command(
    command_key: str,
    args: list[str] | None = None,
    *,
    timeout_seconds: int = 600,
    cwd: Path | str = PROJECT_ROOT,
) -> CommandResult:
    """Run a whitelisted local command without shell=True."""
    if command_key not in ALLOWED_COMMANDS:
        raise ValueError(f"Command is not allowed: {command_key}")
    safe_args = _safe_args(args or [])
    try:
        completed = subprocess.run(
            [*ALLOWED_COMMANDS[command_key], *safe_args],
            cwd=Path(cwd),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command_key=command_key,
            args=safe_args,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=f"命令超时：{timeout_seconds} 秒。",
            timed_out=True,
        )
    return CommandResult(
        command_key=command_key,
        args=safe_args,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_command_streaming(
    command_key: str,
    args: list[str] | None = None,
    *,
    timeout_seconds: int = 600,
    cwd: Path | str = PROJECT_ROOT,
    on_line: StreamLineCallback | None = None,
) -> CommandResult:
    """Run a whitelisted command and stream merged stdout/stderr line by line."""
    if command_key not in ALLOWED_COMMANDS:
        raise ValueError(f"Command is not allowed: {command_key}")
    safe_args = _safe_args(args or [])
    command = [*ALLOWED_COMMANDS[command_key], *safe_args]
    output_lines: list[str] = []
    process = subprocess.Popen(
        command,
        cwd=Path(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    timed_out = False
    try:
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.rstrip("\n")
            output_lines.append(clean)
            if on_line is not None:
                on_line(clean)
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        returncode = 124
        timeout_line = f"命令超时：{timeout_seconds} 秒。"
        output_lines.append(timeout_line)
        if on_line is not None:
            on_line(timeout_line)
    return CommandResult(
        command_key=command_key,
        args=safe_args,
        returncode=returncode,
        stdout="\n".join(output_lines),
        stderr="",
        timed_out=timed_out,
    )


def open_project_path(path: Path | str, *, project_root: Path | str = PROJECT_ROOT) -> CommandResult:
    """Open a project-local folder in Finder on macOS."""
    root = Path(project_root).resolve()
    target = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if not _is_within(target, root):
        raise ValueError("Only project-local paths can be opened.")
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {target}")
    completed = subprocess.run(
        ["open", str(target)],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    return CommandResult(
        command_key="open",
        args=[str(target)],
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _safe_args(args: list[str]) -> list[str]:
    safe: list[str] = []
    for arg in args:
        text = str(arg)
        if any(marker in text for marker in SHELL_META):
            raise ValueError("Shell syntax is not allowed in command arguments.")
        safe.append(text)
    return safe


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
