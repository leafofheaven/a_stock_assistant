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
    goal: str = "",
    display_name: str = "",
    attempt_status: str | None = None,
    written_table_names: list[str] | None = None,
    written_row_count: int = 0,
    partial_update: bool = False,
    error_type: str = "",
    error_message: str = "",
    technical_details: dict[str, Any] | None = None,
    trade_date: str = "",
    status_path: str | Path = DEFAULT_STATUS_PATH,
    db_path: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one provider attempt to scheduled status JSON."""
    path = Path(status_path)
    status = read_market_status(path)
    now = datetime.now().isoformat(timespec="seconds")
    attempt = {
        "provider": provider,
        "display_name": display_name or provider,
        "goal": goal or mode,
        "mode": mode,
        "started_at": now,
        "finished_at": now,
        "status": attempt_status or ("success" if success else "failed"),
        "success": bool(success),
        "written_table_names": written_table_names or [],
        "written_row_count": int(written_row_count or 0),
        "partial_update": bool(partial_update),
        "error_type": error_type,
        "error_message": error_message,
        "technical_details": technical_details or {},
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
        refreshed = refresh_data_quality_status(status_path=path, output_format="silent", db_path=db_path)
        if partial_update:
            refreshed["latest_update_completeness"] = "partial"
            refreshed["formal_result_usable"] = False
            refreshed["formal_result_warning_reason"] = refreshed.get("formal_result_warning_reason") or "本次仅完成部分更新，当前结果不可作为正式全市场研究结果。"
            path.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return refreshed
    except Exception:
        fallback = {
            **status,
            "data_quality_snapshot_source": "unavailable",
            "data_quality_status": "unknown",
            "formal_result_usable": False,
            "formal_result_warning_reason": "数据质量快照未能刷新，当前结果不可作为正式全市场研究结果。",
        }
        path.write_text(json.dumps(fallback, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return fallback
