"""Diagnose Streamlit startup blockers without mutating local data."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path
from typing import Any

import duckdb

from app.config import Settings, get_settings
from core.storage.duckdb_store import DUCKDB_LOCK_MESSAGE, is_duckdb_lock_error

CORE_TABLES = ["stock_basic", "daily_price", "daily_basic", "factor_scores", "strategy_result", "review_decisions"]
LOCK_HINT = "DuckDB is locked by another process. Please stop other running jobs or Streamlit first."


def diagnose_streamlit_startup(
    *,
    settings: Settings | None = None,
    port: int = 8501,
) -> dict[str, Any]:
    """Return Streamlit startup diagnostics without writing to DuckDB."""
    resolved_settings = settings or get_settings()
    db_path = Path(resolved_settings.duckdb_path)
    holders = _duckdb_holders(db_path)
    read_only = _read_only_check(db_path)
    port_status = _port_status(port)
    branch = _git_branch()
    return {
        "branch": branch,
        "duckdb_path": str(db_path),
        "duckdb_exists": db_path.exists(),
        "duckdb_holders": holders,
        "duckdb_locked": read_only["locked"],
        "duckdb_read_only_ok": read_only["ok"],
        "duckdb_error": read_only["error"],
        "core_tables": read_only["tables"],
        "port": port,
        "port_in_use": port_status["in_use"],
        "port_error": port_status["error"],
        "suggestions": _suggestions(db_path, holders, read_only, port_status),
    }


def build_console_summary(result: dict[str, Any]) -> str:
    """Render startup diagnostics for terminal output."""
    lines = [
        "Streamlit 启动诊断",
        f"- 当前分支: {result.get('branch') or '未知'}",
        f"- DuckDB 路径: {result.get('duckdb_path')}",
        f"- DuckDB 文件存在: {'是' if result.get('duckdb_exists') else '否'}",
        f"- DuckDB read_only 可打开: {'是' if result.get('duckdb_read_only_ok') else '否'}",
        f"- DuckDB 是否被锁: {'是' if result.get('duckdb_locked') else '否'}",
        f"- 8501 端口被占用: {'是' if result.get('port_in_use') else '否'}",
    ]
    if result.get("duckdb_error"):
        lines.append(f"- DuckDB 错误: {result['duckdb_error']}")
    holders = result.get("duckdb_holders") or []
    if holders:
        lines.append("- DuckDB 占用进程:")
        for holder in holders:
            lines.append(f"  - {holder.get('command')} pid={holder.get('pid')} raw={holder.get('raw')}")
    tables = result.get("core_tables") or {}
    if tables:
        lines.append("- 核心表状态:")
        for table, exists in tables.items():
            lines.append(f"  - {table}: {'存在' if exists else '缺失'}")
    suggestions = result.get("suggestions") or []
    if suggestions:
        lines.append("- 建议:")
        lines.extend(f"  - {item}" for item in suggestions)
    return "\n".join(lines)


def main() -> None:
    """Print startup diagnostics."""
    print(build_console_summary(diagnose_streamlit_startup()))


def _read_only_check(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"ok": False, "locked": False, "error": "DuckDB 文件不存在。", "tables": {}}
    try:
        with duckdb.connect(str(db_path), read_only=True) as connection:
            rows = connection.execute("SHOW TABLES").fetchall()
            names = {str(row[0]) for row in rows}
        return {"ok": True, "locked": False, "error": "", "tables": {table: table in names for table in CORE_TABLES}}
    except Exception as exc:
        return {
            "ok": False,
            "locked": is_duckdb_lock_error(exc),
            "error": DUCKDB_LOCK_MESSAGE if is_duckdb_lock_error(exc) else str(exc),
            "tables": {},
        }


def _duckdb_holders(db_path: Path) -> list[dict[str, str]]:
    if not db_path.exists():
        return []
    try:
        result = subprocess.run(
            ["lsof", str(db_path)],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    holders: list[dict[str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        holders.append({"command": parts[0], "pid": parts[1], "raw": line})
    return holders


def _port_status(port: int) -> dict[str, Any]:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return {"in_use": True, "error": ""}
    except ConnectionRefusedError:
        return {"in_use": False, "error": ""}
    except OSError as exc:
        return {"in_use": False, "error": str(exc)}


def _git_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _suggestions(
    db_path: Path,
    holders: list[dict[str, str]],
    read_only: dict[str, Any],
    port_status: dict[str, Any],
) -> list[str]:
    suggestions: list[str] = []
    if read_only.get("locked"):
        suggestions.append(DUCKDB_LOCK_MESSAGE)
        suggestions.append(f"运行 lsof {db_path} 查看占用进程。")
    if any(str(item.get("command", "")).lower().startswith(("fileprovi", "fileproviderd")) for item in holders):
        suggestions.append("DuckDB may be locked by macOS FileProvider or cloud sync. Consider moving the database to a non-synced local directory.")
    if port_status.get("in_use"):
        suggestions.append("8501 端口已被占用；请关闭旧 Streamlit，或换一个端口启动。")
    if not db_path.exists():
        suggestions.append("DuckDB 文件不存在；页面会显示 sample / 空状态，可先运行数据更新。")
    if not suggestions:
        suggestions.append("未发现明显启动阻塞；可运行 scripts/start_streamlit_safe.py 启动页面。")
    return suggestions


if __name__ == "__main__":
    main()
