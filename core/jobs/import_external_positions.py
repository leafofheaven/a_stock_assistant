"""Import external simulated position snapshot CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.external_positions.importer import import_external_positions_frame, read_csv_file
from core.storage.duckdb_store import DuckDBStore


def import_external_positions(*, file: Path | str | None = None, settings: Settings | None = None, store: DuckDBStore | None = None, dry_run: bool = False, quiet: bool = False) -> dict[str, Any]:
    """Import an external simulated position snapshot CSV file."""
    if file is None:
        result = {"status": "partial_success", "message": "请使用 --file 指定 external_position_snapshots CSV 文件。", "imported_rows": 0}
        if not quiet:
            print(result["message"])
        return result
    resolved_store = store or DuckDBStore((settings or get_settings()).duckdb_path)
    df = read_csv_file(file)
    result = import_external_positions_frame(df, store=resolved_store, source_file=str(file), dry_run=dry_run)
    if not quiet:
        _print_summary(result)
    return result


def _print_summary(result: dict[str, Any]) -> None:
    print("外部持仓快照导入摘要")
    for key in ["status", "total_rows", "imported_rows", "inserted_rows", "updated_rows", "skipped_rows"]:
        print(f"- {key}: {result.get(key)}")
    if result.get("error_rows"):
        print(f"- error_rows: {result['error_rows']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import external simulated positions.")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    import_external_positions(file=args.file, dry_run=args.dry_run, quiet=args.quiet)


if __name__ == "__main__":
    main()

