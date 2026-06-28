"""Lightweight progress line helpers for CLI and Streamlit command output."""

from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Any, Callable

PROGRESS_PREFIX = "[progress]"


@dataclass(frozen=True)
class ProgressState:
    """Structured progress state emitted by long-running local commands."""

    step: str
    current: str = ""
    success: int = 0
    failed: int = 0
    skipped: int = 0
    message: str = ""


ProgressCallback = Callable[[ProgressState], None]


def format_progress_line(state: ProgressState) -> str:
    """Format one stable machine-readable progress line."""
    fields = {
        "step": state.step,
        "current": state.current,
        "success": state.success,
        "failed": state.failed,
        "skipped": state.skipped,
        "message": state.message,
    }
    parts = [PROGRESS_PREFIX]
    for key, value in fields.items():
        parts.append(f"{key}={shlex.quote(str(value))}")
    return " ".join(parts)


def parse_progress_line(line: str) -> ProgressState | None:
    """Parse a formatted progress line, returning None for normal log lines."""
    text = str(line).strip()
    if not text.startswith(PROGRESS_PREFIX):
        return None
    try:
        parts = shlex.split(text)
    except ValueError:
        return None
    values: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values[key] = value
    return ProgressState(
        step=values.get("step", ""),
        current=values.get("current", ""),
        success=_to_int(values.get("success")),
        failed=_to_int(values.get("failed")),
        skipped=_to_int(values.get("skipped")),
        message=values.get("message", ""),
    )


def print_progress(state: ProgressState) -> None:
    """Print one progress line with flushing for streaming consumers."""
    print(format_progress_line(state), flush=True)


def emit_progress(
    callback: ProgressCallback | None,
    *,
    step: str,
    current: str = "",
    success: int = 0,
    failed: int = 0,
    skipped: int = 0,
    message: str = "",
) -> ProgressState:
    """Create a ProgressState and send it to an optional callback."""
    state = ProgressState(
        step=step,
        current=current,
        success=success,
        failed=failed,
        skipped=skipped,
        message=message,
    )
    if callback is not None:
        callback(state)
    return state


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
