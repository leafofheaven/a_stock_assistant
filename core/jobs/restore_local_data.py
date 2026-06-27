"""Restore local DuckDB data from a backup directory."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.jobs.backup_local_data import backup_local_data
from core.jobs.local_backup_utils import backup_duckdb_path, copy_path, table_counts


def restore_local_data(
    *,
    backup_dir: Path | str,
    target_db: Path | str | None = None,
    force: bool = False,
    dry_run: bool = True,
    create_safety_backup: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Restore DuckDB from a local backup, defaulting to dry-run."""
    settings = settings or get_settings()
    source_dir = Path(backup_dir)
    source_db = backup_duckdb_path(source_dir)
    resolved_target = Path(target_db) if target_db is not None else Path(settings.duckdb_path)
    if not source_dir.exists() or not source_db.exists():
        return {
            "status": "failed",
            "message": f"备份目录无效或缺少 DuckDB: {source_dir}",
            "backup_dir": str(source_dir),
            "target_db": str(resolved_target),
            "restored": False,
        }
    current_counts = table_counts(resolved_target)
    backup_counts = table_counts(source_db)
    result = {
        "status": "dry_run" if dry_run or not force else "success",
        "backup_dir": str(source_dir),
        "source_db": str(source_db),
        "target_db": str(resolved_target),
        "current_table_counts": current_counts,
        "backup_table_counts": backup_counts,
        "safety_backup_dir": None,
        "restored": False,
    }
    if dry_run or not force:
        result["message"] = "dry-run 或未设置 --force，未覆盖当前数据库。"
        return result
    if create_safety_backup and resolved_target.exists():
        safety = backup_local_data(
            backup_dir=source_dir.parent,
            include_reports=False,
            label="safety_before_restore",
            dry_run=False,
            settings=settings,
        )
        result["safety_backup_dir"] = safety.get("backup_dir")
    copy_path(source_db, resolved_target)
    result["restored"] = True
    result["message"] = "已恢复 DuckDB。"
    return result


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and restore local DuckDB."""
    parser = argparse.ArgumentParser(description="Restore local DuckDB from backup.")
    parser.add_argument("--backup-dir", required=True, help="Backup directory.")
    parser.add_argument("--target-db", default=None, help="Target DuckDB path.")
    parser.add_argument("--force", action="store_true", help="Actually overwrite target DuckDB.")
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--create-safety-backup", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    dry_run = args.dry_run and not args.force
    result = restore_local_data(
        backup_dir=args.backup_dir,
        target_db=args.target_db,
        force=args.force,
        dry_run=dry_run,
        create_safety_backup=args.create_safety_backup,
    )
    print("本地恢复摘要")
    print(f"- 状态: {result['status']}")
    if result.get("message"):
        print(f"- 说明: {result['message']}")
    print(f"- 备份目录: {result['backup_dir']}")
    print(f"- 目标数据库: {result['target_db']}")
    print(f"- 当前库表行数: {result.get('current_table_counts')}")
    print(f"- 备份库表行数: {result.get('backup_table_counts')}")
    print(f"- safety backup: {result.get('safety_backup_dir') or '无'}")
    print(f"- 是否恢复: {'是' if result.get('restored') else '否'}")


if __name__ == "__main__":
    main()
