"""Import manual review decisions into DuckDB."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.review.decisions import import_review_decisions as import_decision_frame
from core.review.decisions import load_review_csv
from core.storage.duckdb_store import DuckDBStore


def import_review_decisions(
    *,
    file_path: Path | str,
    dry_run: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Import review decisions from a CSV file."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    df = load_review_csv(file_path)
    result = import_decision_frame(
        df,
        store=resolved_store,
        source_report_path=str(file_path),
        dry_run=dry_run,
    )
    return result


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and import review decisions."""
    parser = argparse.ArgumentParser(description="Import manual review decisions.")
    parser.add_argument("--file", required=True, help="Review template CSV path.")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing to DuckDB.")
    args = parser.parse_args(argv)
    result = import_review_decisions(file_path=args.file, dry_run=args.dry_run)
    print("人工复核结果导入摘要")
    print(f"- dry_run: {'是' if result['dry_run'] else '否'}")
    print(f"- 总行数: {result['total_rows']}")
    print(f"- 成功导入行数: {result['imported_rows']}")
    print(f"- 更新行数: {result['updated_rows']}")
    print(f"- 新增行数: {result['inserted_rows']}")
    print(f"- 跳过行数: {result['skipped_rows']}")
    if result["error_rows"]:
        print("- 错误行:")
        for item in result["error_rows"]:
            print(f"  row={item.get('row')} error={item.get('error')}")


if __name__ == "__main__":
    main()
