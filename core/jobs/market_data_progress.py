"""Progress JSON helpers for market-data update jobs."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


DEFAULT_PROGRESS_PATH = Path("data/runtime/market_data_update_progress.json")


class MarketDataProgressWriter:
    """Atomically write lightweight update progress for Streamlit polling."""

    def __init__(self, path: str | Path = DEFAULT_PROGRESS_PATH) -> None:
        self.path = Path(path)
        self.state: dict[str, Any] = {}

    def start(self, *, goal: str, provider: str, total_symbol_count: int) -> None:
        now = _now()
        self.state = {
            "running": True,
            "status": "running",
            "goal": goal,
            "provider": provider,
            "started_at": now,
            "last_heartbeat_at": now,
            "finished_at": "",
            "current_provider": "",
            "current_provider_display_name": "",
            "current_symbol": "",
            "processed_symbol_count": 0,
            "total_symbol_count": int(total_symbol_count or 0),
            "success_symbol_count": 0,
            "failed_symbol_count": 0,
            "skipped_symbol_count": 0,
            "written_row_count": 0,
            "pending_symbol_count": int(total_symbol_count or 0),
            "already_latest_symbol_count": 0,
            "failure_summary": {},
            "failure_examples": {},
            "provider_progress": [],
            "suggested_action": "",
        }
        self.write()

    def start_provider(
        self,
        provider: str,
        display_name: str,
        *,
        total_symbol_count: int,
        pending_symbol_count: int | None = None,
        already_latest_symbol_count: int | None = None,
    ) -> None:
        self._provider(provider, display_name).update(
            {
                "status": "running",
                "processed_symbol_count": 0,
                "total_symbol_count": int(total_symbol_count or 0),
                "success_symbol_count": 0,
                "failed_symbol_count": 0,
                "skipped_symbol_count": 0,
                "written_row_count": 0,
                "failure_summary": {},
                "failure_examples": {},
            }
        )
        update = {
            "running": True,
            "status": "running",
            "current_provider": provider,
            "current_provider_display_name": display_name,
            "current_symbol": "",
            "last_heartbeat_at": _now(),
        }
        if pending_symbol_count is not None:
            update["pending_symbol_count"] = int(pending_symbol_count or 0)
        if already_latest_symbol_count is not None:
            update["already_latest_symbol_count"] = int(already_latest_symbol_count or 0)
        self.state.update(update)
        self.write()

    def update_symbol(
        self,
        provider: str,
        display_name: str,
        *,
        symbol: str,
        status: str,
        written_rows: int = 0,
        processed_symbol_count: int | None = None,
        total_symbol_count: int | None = None,
        failure_type: str = "",
    ) -> None:
        provider_state = self._provider(provider, display_name)
        provider_state["status"] = "running"
        if total_symbol_count is not None:
            provider_state["total_symbol_count"] = int(total_symbol_count or 0)
        if processed_symbol_count is None:
            provider_state["processed_symbol_count"] = int(provider_state.get("processed_symbol_count", 0) or 0) + 1
        else:
            provider_state["processed_symbol_count"] = int(processed_symbol_count or 0)
        if status == "success":
            provider_state["success_symbol_count"] = int(provider_state.get("success_symbol_count", 0) or 0) + 1
        elif status == "failed":
            provider_state["failed_symbol_count"] = int(provider_state.get("failed_symbol_count", 0) or 0) + 1
        elif status == "skipped":
            provider_state["skipped_symbol_count"] = int(provider_state.get("skipped_symbol_count", 0) or 0) + 1
        if failure_type:
            _record_failure(provider_state, failure_type, symbol)
        provider_state["written_row_count"] = int(provider_state.get("written_row_count", 0) or 0) + int(written_rows or 0)
        self._sync_totals(provider_state, symbol)
        self.write()

    def finish_provider(
        self,
        provider: str,
        display_name: str,
        *,
        status: str,
        written_rows: int = 0,
        processed_symbol_count: int | None = None,
        total_symbol_count: int | None = None,
        failure_summary: dict[str, int] | None = None,
        failure_examples: dict[str, list[str]] | None = None,
    ) -> None:
        provider_state = self._provider(provider, display_name)
        provider_state["status"] = status
        if total_symbol_count is not None:
            provider_state["total_symbol_count"] = int(total_symbol_count or 0)
        if processed_symbol_count is not None:
            provider_state["processed_symbol_count"] = int(processed_symbol_count or 0)
        if written_rows:
            provider_state["written_row_count"] = int(written_rows or 0)
        if failure_summary is not None:
            provider_state["failure_summary"] = {str(key): int(value or 0) for key, value in failure_summary.items()}
        if failure_examples is not None:
            provider_state["failure_examples"] = {
                str(key): [str(item) for item in list(value or [])[:20]]
                for key, value in failure_examples.items()
            }
        self._sync_totals(provider_state, self.state.get("current_symbol", ""))
        self.write()

    def finish(self, *, status: str, suggested_action: str = "") -> None:
        now = _now()
        self.state.update(
            {
                "running": False,
                "status": status,
                "last_heartbeat_at": now,
                "finished_at": now,
                "suggested_action": suggested_action,
            }
        )
        self.write()

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)

    def _provider(self, provider: str, display_name: str) -> dict[str, Any]:
        providers = self.state.setdefault("provider_progress", [])
        for item in providers:
            if item.get("provider") == provider:
                item["display_name"] = display_name
                return item
        item = {
            "provider": provider,
            "display_name": display_name,
            "status": "pending",
            "processed_symbol_count": 0,
            "total_symbol_count": int(self.state.get("total_symbol_count", 0) or 0),
            "success_symbol_count": 0,
            "failed_symbol_count": 0,
            "skipped_symbol_count": 0,
            "written_row_count": 0,
            "failure_summary": {},
            "failure_examples": {},
        }
        providers.append(item)
        return item

    def _sync_totals(self, provider_state: dict[str, Any], symbol: str) -> None:
        self.state.update(
            {
                "current_provider": provider_state.get("provider", ""),
                "current_provider_display_name": provider_state.get("display_name", ""),
                "current_symbol": symbol,
                "processed_symbol_count": int(provider_state.get("processed_symbol_count", 0) or 0),
                "total_symbol_count": int(provider_state.get("total_symbol_count", 0) or 0),
                "success_symbol_count": int(provider_state.get("success_symbol_count", 0) or 0),
                "failed_symbol_count": int(provider_state.get("failed_symbol_count", 0) or 0),
                "skipped_symbol_count": int(provider_state.get("skipped_symbol_count", 0) or 0),
                "written_row_count": int(provider_state.get("written_row_count", 0) or 0),
                "failure_summary": dict(provider_state.get("failure_summary") or {}),
                "failure_examples": dict(provider_state.get("failure_examples") or {}),
                "last_heartbeat_at": _now(),
            }
        )


def read_market_data_progress(path: str | Path = DEFAULT_PROGRESS_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _record_failure(provider_state: dict[str, Any], failure_type: str, symbol: str) -> None:
    summary = provider_state.setdefault("failure_summary", {})
    examples = provider_state.setdefault("failure_examples", {})
    summary[failure_type] = int(summary.get(failure_type, 0) or 0) + 1
    bucket = examples.setdefault(failure_type, [])
    clean_symbol = str(symbol or "")
    if clean_symbol and len(bucket) < 20 and clean_symbol not in bucket:
        bucket.append(clean_symbol)
