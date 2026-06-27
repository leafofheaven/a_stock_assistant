"""Diagnose local manual review decision history."""

from __future__ import annotations

import argparse
from typing import Any

from app.config import Settings, get_settings
from core.review.decisions import summarize_review_history
from core.storage.duckdb_store import DuckDBStore


def diagnose_review_history(
    *,
    ts_code: str | None = None,
    limit: int = 50,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Return local review history diagnostics without external API access."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    summary = summarize_review_history(resolved_store, ts_code=ts_code, limit=limit)
    return {
        "status": "success",
        "data_provider": resolved_settings.data_provider,
        "duckdb_path": str(resolved_store.db_path),
        "ts_code": ts_code,
        "history_rows": summary["history_rows"],
        "records": summary["records"],
        "next_steps": [
            "python -m core.jobs.update_review_decision --ts-code 002475.SZ --decision watch --reason \"继续观察\"",
            "python -m core.jobs.export_watchlist --format all",
        ],
    }


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and print review history diagnostics."""
    parser = argparse.ArgumentParser(description="Diagnose review decision history.")
    parser.add_argument("--ts-code", help="Filter by ts_code.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum rows to print.")
    args = parser.parse_args(argv)
    result = diagnose_review_history(ts_code=args.ts_code, limit=args.limit)

    print("复核历史诊断摘要")
    print(f"- 当前 DATA_PROVIDER: {result['data_provider']}")
    print(f"- DuckDB 路径: {result['duckdb_path']}")
    print(f"- review_decision_history 行数: {result['history_rows']}")
    if result.get("ts_code"):
        print(f"- 股票代码: {result['ts_code']}")
    print("- 最近变更记录:")
    if result["records"]:
        for item in result["records"]:
            print(
                f"  {item.get('created_at')} {item.get('ts_code')} {item.get('name')} "
                f"action={item.get('action_type')} old_decision={item.get('old_decision') or '暂无'} "
                f"new_decision={item.get('new_decision') or '暂无'} "
                f"old_status={item.get('old_review_status') or '暂无'} "
                f"new_status={item.get('new_review_status') or '暂无'} "
                f"reason={item.get('reason') or '暂无'}"
            )
    else:
        print("  暂无复核历史。")
    print("- 下一步建议:")
    for step in result["next_steps"]:
        print(f"  {step}")


if __name__ == "__main__":
    main()
