"""Runtime status helpers for market-data provider attempts."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from core.jobs.refresh_data_quality_status import DEFAULT_STATUS_PATH, refresh_data_quality_status


def read_market_status(status_path: str | Path = DEFAULT_STATUS_PATH) -> dict[str, Any]:
    path = Path(status_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def record_provider_attempt(
    *,
    provider: str,
    mode: str,
    success: bool,
    written_table_names: list[str] | None = None,
    written_row_count: int = 0,
    partial_update: bool = False,
    error_type: str = "",
    error_message: str = "",
    trade_date: str = "",
    status_path: str | Path = DEFAULT_STATUS_PATH,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one provider attempt to scheduled status JSON."""
    path = Path(status_path)
    status = read_market_status(path)
    now = datetime.now().isoformat(timespec="seconds")
    attempt = {
        "provider": provider,
        "mode": mode,
        "started_at": now,
        "finished_at": now,
        "success": bool(success),
        "written_table_names": written_table_names or [],
        "written_row_count": int(written_row_count or 0),
        "partial_update": bool(partial_update),
        "error_type": error_type,
        "error_message": error_message,
    }
    if extra:
        attempt.update(extra)
        status.update(extra)
    attempts = list(status.get("provider_attempts") or [])
    attempts.append(attempt)
    status["provider_attempts"] = attempts[-50:]
    if success:
        status["latest_success_provider"] = provider
        if trade_date:
            status["latest_success_trade_date"] = trade_date
        status["latest_provider_failure_reason"] = ""
    else:
        status["latest_provider_failure_reason"] = error_message
    status["latest_update_completeness"] = "partial" if partial_update else "complete"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    try:
        return refresh_data_quality_status(status_path=path, output_format="silent")
    except TypeError:
        return status
    except Exception:
        return status
