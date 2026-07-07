"""Skip and retry queue helpers for latest-data gap updates."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any


DEFAULT_SKIP_QUEUE_PATH = Path("data/runtime/missing_latest_retry_queue.json")
NO_DATA_REASONS = {"no_data", "unsupported_symbol"}
RETRY_REASONS = {"timeout", "provider_error", "connection_error", "unknown_error"}


def read_missing_latest_queue(path: str | Path = DEFAULT_SKIP_QUEUE_PATH) -> dict[str, Any]:
    queue_path = Path(path)
    if not queue_path.exists():
        return {}
    try:
        payload = json.loads(queue_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def reset_missing_latest_queue(path: str | Path = DEFAULT_SKIP_QUEUE_PATH) -> None:
    queue_path = Path(path)
    if queue_path.exists():
        queue_path.unlink()


def queue_counts(path: str | Path = DEFAULT_SKIP_QUEUE_PATH, *, trade_date: str = "") -> dict[str, int]:
    queue = _matching_queue(read_missing_latest_queue(path), trade_date)
    skip_queue = queue.get("skip_queue") or {}
    retry_queue = queue.get("retry_queue") or {}
    return {
        "skip_queue_count": len(skip_queue),
        "retry_queue_count": len(retry_queue),
        "cooldown_symbol_count": sum(1 for item in skip_queue.values() if item.get("status") == "cooldown"),
        "today_no_data_count": sum(1 for item in skip_queue.values() if item.get("reason") == "no_data"),
        "timeout_retry_count": sum(1 for item in retry_queue.values() if item.get("reason") == "timeout"),
    }


def excluded_symbols_for_main_scan(
    path: str | Path,
    *,
    trade_date: str,
    now: datetime | None = None,
    max_no_data_retries: int = 1,
    max_timeout_retries: int = 1,
    skip_cooldown_minutes: int = 60,
) -> set[str]:
    """Return symbols that should not block the current main missing-latest scan."""
    current = now or datetime.now()
    queue = _matching_queue(read_missing_latest_queue(path), trade_date)
    excluded: set[str] = set()
    for symbol, item in (queue.get("skip_queue") or {}).items():
        retry_count = int(item.get("retry_count", 0) or 0)
        if retry_count >= max(max_no_data_retries, 0) or not _cooldown_expired(item, current, skip_cooldown_minutes):
            excluded.add(str(symbol))
    for symbol, item in (queue.get("retry_queue") or {}).items():
        retry_count = int(item.get("retry_count", 0) or 0)
        if retry_count >= max(max_timeout_retries, 0) or item.get("status") in {"pending_retry", "cooldown"}:
            excluded.add(str(symbol))
    return excluded


def retry_symbols(
    path: str | Path,
    *,
    trade_date: str,
    batch_size: int,
    now: datetime | None = None,
    max_no_data_retries: int = 1,
    max_timeout_retries: int = 1,
    skip_cooldown_minutes: int = 60,
) -> list[str]:
    """Select a bounded retry batch from no_data and transient retry queues."""
    current = now or datetime.now()
    queue = _matching_queue(read_missing_latest_queue(path), trade_date)
    selected: list[str] = []
    for bucket_name, max_retries in [("retry_queue", max_timeout_retries), ("skip_queue", max_no_data_retries)]:
        bucket = queue.get(bucket_name) or {}
        for symbol, item in bucket.items():
            retry_count = int(item.get("retry_count", 0) or 0)
            if retry_count >= max(max_retries, 0):
                continue
            if bucket_name == "skip_queue" and not _cooldown_expired(item, current, skip_cooldown_minutes):
                continue
            if symbol not in selected:
                selected.append(str(symbol))
            if len(selected) >= max(1, int(batch_size or 1)):
                return selected
    return selected


def mark_retry_attempts(
    path: str | Path,
    *,
    trade_date: str,
    symbols: list[str],
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now()
    payload = _ensure_queue(path, trade_date, current)
    for symbol in symbols:
        for bucket_name in ["retry_queue", "skip_queue"]:
            bucket = payload.setdefault(bucket_name, {})
            item = bucket.get(symbol)
            if not isinstance(item, dict):
                continue
            item["retry_count"] = int(item.get("retry_count", 0) or 0) + 1
            item["last_seen_at"] = current.isoformat(timespec="seconds")
            item["status"] = "retrying"
    _write_queue(path, payload)
    return payload


def record_failure_records(
    path: str | Path,
    *,
    trade_date: str,
    failure_records: list[dict[str, Any]],
    now: datetime | None = None,
    max_no_data_retries: int = 1,
    max_timeout_retries: int = 1,
    skip_cooldown_minutes: int = 60,
) -> dict[str, Any]:
    """Persist per-symbol failures into skip/retry queues."""
    current = now or datetime.now()
    payload = _ensure_queue(path, trade_date, current)
    for record in failure_records:
        symbol = str(record.get("symbol") or record.get("ts_code") or "").strip().upper()
        reason = str(record.get("failure_type") or record.get("reason") or "unknown_error")
        if not symbol:
            continue
        if reason in NO_DATA_REASONS:
            bucket_name = "skip_queue"
            status = "cooldown"
            max_retries = max_no_data_retries
        else:
            bucket_name = "retry_queue"
            status = "pending_retry"
            max_retries = max_timeout_retries
            if reason not in RETRY_REASONS:
                reason = "unknown_error"
        bucket = payload.setdefault(bucket_name, {})
        item = bucket.get(symbol) if isinstance(bucket.get(symbol), dict) else {}
        retry_count = int(item.get("retry_count", 0) or 0)
        first_seen = item.get("first_seen_at") or current.isoformat(timespec="seconds")
        bucket[symbol] = {
            "reason": reason,
            "first_seen_at": first_seen,
            "last_seen_at": current.isoformat(timespec="seconds"),
            "retry_count": retry_count,
            "next_retry_after": (current + timedelta(minutes=max(skip_cooldown_minutes, 0))).isoformat(timespec="seconds"),
            "status": "retry_limit_reached" if retry_count >= max(max_retries, 0) else status,
            "trade_date": trade_date,
        }
    _write_queue(path, payload)
    return payload


def mark_resolved_symbols(
    path: str | Path,
    *,
    trade_date: str,
    symbols: list[str],
    reason: str = "success_after_retry",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now()
    payload = _ensure_queue(path, trade_date, current)
    resolved = payload.setdefault("resolved", {})
    for symbol in symbols:
        removed = False
        for bucket_name in ["skip_queue", "retry_queue"]:
            bucket = payload.setdefault(bucket_name, {})
            if symbol in bucket:
                bucket.pop(symbol, None)
                removed = True
        if removed:
            resolved[symbol] = {
                "resolved_at": current.isoformat(timespec="seconds"),
                "reason": reason,
                "trade_date": trade_date,
            }
    _write_queue(path, payload)
    return payload


def _matching_queue(payload: dict[str, Any], trade_date: str) -> dict[str, Any]:
    if not payload:
        return {}
    if trade_date and str(payload.get("trade_date") or "") != str(trade_date):
        return {}
    return payload


def _ensure_queue(path: str | Path, trade_date: str, now: datetime) -> dict[str, Any]:
    payload = _matching_queue(read_missing_latest_queue(path), trade_date)
    if not payload:
        payload = {
            "trade_date": trade_date,
            "run_id": "",
            "main_scan_started_at": now.isoformat(timespec="seconds"),
            "main_scan_finished_at": "",
            "skip_queue": {},
            "retry_queue": {},
            "resolved": {},
        }
    payload["trade_date"] = trade_date
    return payload


def _cooldown_expired(item: dict[str, Any], now: datetime, minutes: int) -> bool:
    if minutes <= 0:
        return True
    value = str(item.get("next_retry_after") or "")
    if not value:
        return False
    try:
        return now >= datetime.fromisoformat(value)
    except ValueError:
        return False


def _write_queue(path: str | Path, payload: dict[str, Any]) -> None:
    queue_path = Path(path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = queue_path.with_suffix(queue_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(queue_path)
