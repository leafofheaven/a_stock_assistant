"""Create a local backup of DuckDB data and optional reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.jobs.local_backup_utils import (
    backup_metadata,
    copy_path,
    copy_reports,
    file_size,
    table_counts,
    timestamp,
)


def backup_local_data(
    *,
    backup_dir: Path | str = "backups",
    include_reports: bool = False,
    label: str = "",
    dry_run: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create a local backup directory without storing .env or tokens."""
    resolved_settings = settings or get_settings()
    root = Path(backup_dir)
    backup_name = f"a_stock_backup_{timestamp()}"
    target_dir = root / backup_name
    db_path = Path(resolved_settings.duckdb_path)
    counts = table_counts(db_path)
    metadata = backup_metadata(resolved_settings, label=label)
    planned = {
        "duckdb": str(db_path),
        "reports": "reports" if include_reports else None,
        "metadata": "metadata.json",
        "table_counts": "table_counts.json",
    }
    if dry_run:
        return {
            "status": "dry_run",
            "duckdb_path": str(db_path),
            "backup_dir": str(target_dir),
            "include_reports": include_reports,
            "table_counts": counts,
            "backup_size": 0,
            "planned": planned,
            "next_steps": ["python -m core.jobs.backup_local_data --label before_change"],
        }

    target_dir.mkdir(parents=True, exist_ok=False)
    copied_size = copy_path(db_path, target_dir / "data" / "a_stock_assistant.duckdb")
    reports_size = copy_reports(Path("reports"), target_dir / "reports") if include_reports else 0
    (target_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (target_dir / "table_counts.json").write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
    total_size = copied_size + reports_size + file_size(target_dir / "metadata.json") + file_size(target_dir / "table_counts.json")
    return {
        "status": "success",
        "duckdb_path": str(db_path),
        "backup_dir": str(target_dir),
        "include_reports": include_reports,
        "table_counts": counts,
        "backup_size": total_size,
        "next_steps": ["python -m core.jobs.list_backups", f"python -m core.jobs.restore_local_data --backup-dir {target_dir} --dry-run"],
    }


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and create a local backup."""
    parser = argparse.ArgumentParser(description="Back up local DuckDB data.")
    parser.add_argument("--backup-dir", default="backups", help="Backup root directory.")
    parser.add_argument("--include-reports", action="store_true", help="Also copy reports/.")
    parser.add_argument("--label", default="", help="Optional backup label.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing backup files.")
    args = parser.parse_args(argv)
    result = backup_local_data(
        backup_dir=args.backup_dir,
        include_reports=args.include_reports,
        label=args.label,
        dry_run=args.dry_run,
    )
    print("本地备份摘要")
    print(f"- 状态: {result['status']}")
    print(f"- DuckDB 路径: {result['duckdb_path']}")
    print(f"- 备份目录: {result['backup_dir']}")
    print(f"- 是否包含 reports: {'是' if result['include_reports'] else '否'}")
    print(f"- 核心表行数: {result['table_counts']}")
    print(f"- 备份大小: {result['backup_size']} bytes")
    print("- 下一步建议:")
    for step in result["next_steps"]:
        print(f"  {step}")


if __name__ == "__main__":
    main()
