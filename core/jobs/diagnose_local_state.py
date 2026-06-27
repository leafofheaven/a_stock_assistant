"""Diagnose local git, data, reports, and backup state."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.jobs.local_backup_utils import file_size, git_info, table_counts, tracked_local_data_paths


def diagnose_local_state(
    *,
    report_dir: Path | str = "reports",
    backup_dir: Path | str = "backups",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return local state diagnostics for personal data protection."""
    resolved_settings = settings or get_settings()
    db_path = Path(resolved_settings.duckdb_path)
    reports = [path for path in Path(report_dir).glob("*") if path.is_file()] if Path(report_dir).exists() else []
    backups = [path for path in Path(backup_dir).glob("a_stock_backup_*") if path.is_dir()] if Path(backup_dir).exists() else []
    latest_backup = max(backups, key=lambda path: path.stat().st_mtime) if backups else None
    counts = table_counts(db_path)
    git = git_info()
    tracked = tracked_local_data_paths()
    return {
        "status": "success",
        "branch": git.get("branch"),
        "git_commit": git.get("commit"),
        "worktree_clean": git.get("is_clean"),
        "env_exists": Path(".env").exists(),
        "data_provider": resolved_settings.data_provider,
        "duckdb_exists": db_path.exists(),
        "duckdb_path": str(db_path),
        "duckdb_size": file_size(db_path),
        "table_counts": counts,
        "review_decisions_rows": counts.get("review_decisions"),
        "review_decision_history_rows": counts.get("review_decision_history"),
        "watchlist_snapshots_rows": counts.get("watchlist_snapshots"),
        "reports_count": len(reports),
        "backups_count": len(backups),
        "latest_backup_time": datetime_from_path(latest_backup) if latest_backup else None,
        "latest_backup_path": str(latest_backup) if latest_backup else None,
        "tracked_local_data_paths": tracked,
        "next_steps": ["python -m core.jobs.backup_local_data", "python -m core.jobs.list_backups"],
    }


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and print local state."""
    parser = argparse.ArgumentParser(description="Diagnose local project state.")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--backup-dir", default="backups")
    args = parser.parse_args(argv)
    result = diagnose_local_state(report_dir=args.report_dir, backup_dir=args.backup_dir)
    print("本地状态诊断摘要")
    print(f"- 当前分支: {result['branch']}")
    print(f"- 当前 git commit: {result['git_commit']}")
    print(f"- 工作区是否干净: {'是' if result['worktree_clean'] else '否'}")
    print(f"- .env 是否存在: {'是' if result['env_exists'] else '否'}")
    print(f"- DATA_PROVIDER: {result['data_provider']}")
    print(f"- DuckDB 是否存在: {'是' if result['duckdb_exists'] else '否'}")
    print(f"- DuckDB 路径: {result['duckdb_path']}")
    print(f"- DuckDB 文件大小: {result['duckdb_size']} bytes")
    print(f"- 核心表行数: {result['table_counts']}")
    print(f"- review_decisions 行数: {result['review_decisions_rows']}")
    print(f"- review_decision_history 行数: {result['review_decision_history_rows']}")
    print(f"- watchlist_snapshots 行数: {result['watchlist_snapshots_rows']}")
    print(f"- reports 文件数量: {result['reports_count']}")
    print(f"- backups 数量: {result['backups_count']}")
    print(f"- 最近备份时间: {result['latest_backup_time'] or '暂无'}")
    print(f"- 最近备份路径: {result['latest_backup_path'] or '暂无'}")
    print(f"- 被 git 跟踪的本地数据路径: {result['tracked_local_data_paths'] or '无'}")
    print("- 下一步建议:")
    for step in result["next_steps"]:
        print(f"  {step}")


def datetime_from_path(path: Path | None) -> str | None:
    """Return backup directory mtime as an ISO string."""
    if path is None:
        return None
    from datetime import datetime

    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
