"""Shared local backup and state helpers."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from app.config import Settings
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_TABLES = [
    "stock_basic",
    "trade_calendar",
    "daily_price",
    "daily_basic",
    "adj_factor",
    "factor_scores",
    "strategy_result",
    "review_decisions",
    "review_decision_history",
    "watchlist_snapshots",
]


def timestamp() -> str:
    """Return a filesystem-friendly timestamp."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def file_size(path: Path) -> int:
    """Return file size in bytes, or 0 when missing."""
    return path.stat().st_size if path.exists() else 0


def table_counts(db_path: Path | str) -> dict[str, int | None]:
    """Return row counts for known tables, using None when a table cannot be read."""
    path = Path(db_path)
    if not path.exists():
        return {table: None for table in CORE_TABLES}
    store = DuckDBStore(path)
    counts: dict[str, int | None] = {}
    for table in CORE_TABLES:
        try:
            counts[table] = int(len(store.read_table(table)))
        except DuckDBStoreError:
            counts[table] = None
    return counts


def git_info() -> dict[str, Any]:
    """Return local git branch, commit, and worktree status."""
    return {
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": _git(["rev-parse", "--short", "HEAD"]),
        "is_clean": _git(["status", "--short"]) == "",
    }


def tracked_local_data_paths() -> list[str]:
    """Return tracked local generated paths that should stay out of git."""
    output = _git(["ls-files", "data", "reports", "backups", ".env"])
    return [line for line in output.splitlines() if line.strip()]


def env_summary(settings: Settings) -> dict[str, Any]:
    """Return a safe environment summary without token values."""
    env_path = PROJECT_ROOT / ".env"
    keys: list[str] = []
    token_configured = bool(getattr(settings, "tushare_token", ""))
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            keys.append(key)
    return {
        "env_exists": env_path.exists(),
        "env_keys": sorted(set(keys)),
        "tushare_token_configured": token_configured,
        "tushare_token_value": None,
    }


def backup_metadata(settings: Settings, label: str = "") -> dict[str, Any]:
    """Build metadata for one local backup without secret values."""
    git = git_info()
    return {
        "backup_time": datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "git": git,
        "data_provider": settings.data_provider,
        "duckdb_path": str(settings.duckdb_path),
        "env_summary": env_summary(settings),
    }


def copy_path(source: Path, target: Path) -> int:
    """Copy a file and return bytes copied."""
    if not source.exists():
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return file_size(target)


def copy_reports(source_dir: Path, target_dir: Path) -> int:
    """Copy report files and return total copied bytes."""
    if not source_dir.exists():
        return 0
    total = 0
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in source_dir.rglob("*"):
        if path.is_file():
            target = target_dir / path.relative_to(source_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            total += file_size(target)
    return total


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object, returning an empty dict when unavailable."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def backup_duckdb_path(backup_dir: Path) -> Path:
    """Return the DuckDB file path inside a backup directory."""
    return backup_dir / "data" / "a_stock_assistant.duckdb"


def _git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""
