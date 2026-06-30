"""Match imported external positions with local entry zones and watchlist."""

from __future__ import annotations

import argparse
from typing import Any

from app.config import Settings, get_settings
from core.external_positions.importer import match_external_positions as match_positions
from core.storage.duckdb_store import DuckDBStore


def match_external_positions(*, settings: Settings | None = None, store: DuckDBStore | None = None, quiet: bool = False) -> dict[str, Any]:
    """Re-match imported external position snapshots."""
    resolved_store = store or DuckDBStore((settings or get_settings()).duckdb_path)
    result = match_positions(resolved_store)
    if not quiet:
        print("外部持仓匹配摘要")
        print(f"- 状态: {result.get('status')}")
        print(f"- 匹配行数: {result.get('matched_rows', 0)}")
        print(f"- 说明: {result.get('message')}")
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Match external simulated positions.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    match_external_positions(quiet=args.quiet)


if __name__ == "__main__":
    main()

