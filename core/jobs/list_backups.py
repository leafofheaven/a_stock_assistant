"""List local backup directories."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from core.jobs.local_backup_utils import backup_duckdb_path, file_size, load_json


def list_backups(*, backup_dir: Path | str = "backups") -> dict[str, Any]:
    """List local backups from a backup root directory."""
    root = Path(backup_dir)
    backups: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(root.glob("a_stock_backup_*"), reverse=True):
            if not path.is_dir():
                continue
            metadata = load_json(path / "metadata.json")
            counts = load_json(path / "table_counts.json")
            db_path = backup_duckdb_path(path)
            backups.append(
                {
                    "backup_time": metadata.get("backup_time"),
                    "label": metadata.get("label", ""),
                    "git_commit": metadata.get("git", {}).get("commit"),
                    "data_provider": metadata.get("data_provider"),
                    "duckdb_exists": db_path.exists(),
                    "duckdb_size": file_size(db_path),
                    "table_counts": counts,
                    "path": str(path),
                }
            )
    return {"status": "success", "backup_dir": str(root), "backup_count": len(backups), "backups": backups}


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and print backup list."""
    parser = argparse.ArgumentParser(description="List local backups.")
    parser.add_argument("--backup-dir", default="backups", help="Backup root directory.")
    args = parser.parse_args(argv)
    result = list_backups(backup_dir=args.backup_dir)
    print("本地备份列表")
    print(f"- 备份目录: {result['backup_dir']}")
    print(f"- 备份数量: {result['backup_count']}")
    for item in result["backups"]:
        print(
            f"  {item.get('backup_time') or '未知时间'} label={item.get('label') or '无'} "
            f"commit={item.get('git_commit') or '未知'} provider={item.get('data_provider') or '未知'} "
            f"duckdb={'有' if item.get('duckdb_exists') else '无'} size={item.get('duckdb_size', 0)} "
            f"path={item.get('path')}"
        )


if __name__ == "__main__":
    main()
