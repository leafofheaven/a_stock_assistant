"""Clean generated report files with dry-run default."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

GENERATED_PATTERNS = [
    "real_workflow_*.md",
    "real_workflow_*.json",
    "selection_review_*.md",
    "selection_review_*.json",
    "selection_review_*.csv",
    "review_template_*.csv",
    "watchlist_*.md",
    "watchlist_*.json",
    "watchlist_*.csv",
    "watchlist_tracking_*.md",
    "watchlist_tracking_*.json",
    "watchlist_tracking_*.csv",
]


def clean_generated_reports(
    *,
    report_dir: Path | str = "reports",
    older_than_days: int | None = None,
    dry_run: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Clean known generated report files, defaulting to dry-run."""
    directory = Path(report_dir)
    cutoff = datetime.now() - timedelta(days=older_than_days) if older_than_days is not None else None
    files = _candidate_files(directory, cutoff)
    deleted: list[str] = []
    if force and not dry_run:
        for path in files:
            path.unlink()
            deleted.append(str(path))
    return {
        "status": "success",
        "report_dir": str(directory),
        "dry_run": dry_run or not force,
        "force": force,
        "older_than_days": older_than_days,
        "candidate_count": len(files),
        "deleted_count": len(deleted),
        "files": [str(path) for path in files],
        "deleted_files": deleted,
    }


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and clean generated reports."""
    parser = argparse.ArgumentParser(description="Clean generated report files.")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--older-than-days", type=int)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force", action="store_true", help="Actually delete matching generated files.")
    args = parser.parse_args(argv)
    dry_run = args.dry_run and not args.force
    result = clean_generated_reports(
        report_dir=args.report_dir,
        older_than_days=args.older_than_days,
        dry_run=dry_run,
        force=args.force,
    )
    print("生成报告清理摘要")
    print(f"- 报告目录: {result['report_dir']}")
    print(f"- dry-run: {'是' if result['dry_run'] else '否'}")
    print(f"- 匹配文件数量: {result['candidate_count']}")
    print(f"- 已删除数量: {result['deleted_count']}")
    for path in result["files"]:
        print(f"  {path}")


def _candidate_files(directory: Path, cutoff: datetime | None) -> list[Path]:
    if not directory.exists():
        return []
    found: dict[Path, None] = {}
    for pattern in GENERATED_PATTERNS:
        for path in directory.glob(pattern):
            if not path.is_file():
                continue
            if cutoff and datetime.fromtimestamp(path.stat().st_mtime) >= cutoff:
                continue
            found[path] = None
    return sorted(found)


if __name__ == "__main__":
    main()
