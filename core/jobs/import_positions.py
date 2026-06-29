"""Import local position pool records from CSV."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.positions.position_pool import import_positions as import_positions_frame
from core.positions.position_pool import load_positions_csv
from core.storage.duckdb_store import DuckDBStore


DEFAULT_TEMPLATE_PATH = Path("docs/templates/positions_import_template.csv")


def import_positions(
    *,
    file_path: Path | str | None = None,
    dry_run: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Import position records from CSV, or return template guidance."""
    if file_path is None:
        return {
            "status": "no_file",
            "message": f"请使用 --file 指定 CSV。模板: {DEFAULT_TEMPLATE_PATH}",
            "template_path": str(DEFAULT_TEMPLATE_PATH),
            "dry_run": dry_run,
        }
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    df = load_positions_csv(file_path)
    result = import_positions_frame(df, store=resolved_store, dry_run=dry_run)
    result["status"] = "success"
    result["file_path"] = str(file_path)
    return result


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and import positions."""
    parser = argparse.ArgumentParser(description="Import local position records.")
    parser.add_argument("--file", help="Position import CSV path.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = import_positions(file_path=args.file, dry_run=args.dry_run)
    print("持仓导入摘要")
    if result.get("status") == "no_file":
        print(f"- {result['message']}")
        return
    print(f"- dry_run: {'是' if result['dry_run'] else '否'}")
    print(f"- 总行数: {result['total_rows']}")
    print(f"- 新建行数: {result['created_rows']}")
    print(f"- 已存在 active 跳过行数: {result['existing_rows']}")
    print(f"- 跳过行数: {result['skipped_rows']}")
    if result["error_rows"]:
        print("- 错误行:")
        for item in result["error_rows"]:
            print(f"  row={item.get('row')} error={item.get('error')}")


if __name__ == "__main__":
    main()
