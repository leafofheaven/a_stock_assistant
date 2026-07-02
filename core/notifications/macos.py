"""macOS local notification helper."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any


def build_macos_notification(title: str, message: str) -> list[str]:
    """Build a safe osascript notification command."""
    safe_title = _escape_applescript(title)[:120]
    safe_message = _escape_applescript(message)[:240]
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    return ["osascript", "-e", script]


def send_macos_notification(title: str, message: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Send a local macOS notification, returning status instead of raising."""
    command = build_macos_notification(title, message)
    if dry_run:
        return {"status": "dry_run", "command": command}
    if shutil.which("osascript") is None:
        return {"status": "skipped", "error": "osascript unavailable"}
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "error": str(exc)}
    return {
        "status": "sent" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "error": completed.stderr[:300],
    }


def _escape_applescript(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

