"""Update one manual review decision and record local history."""

from __future__ import annotations

import argparse
from typing import Any

from app.config import Settings, get_settings
from core.review.decisions import update_review_decision as update_decision
from core.storage.duckdb_store import DuckDBStore


def update_review_decision(
    *,
    ts_code: str,
    decision: str | None = None,
    reason: str = "",
    notes: str = "",
    reviewer: str = "",
    archive: bool = False,
    reactivate: bool = False,
    selection_date: str | None = None,
    dry_run: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Update or create a local review decision without external API access."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    result = update_decision(
        store=resolved_store,
        ts_code=ts_code,
        decision=decision,
        reason=reason,
        notes=notes,
        reviewer=reviewer,
        archive=archive,
        reactivate=reactivate,
        selection_date=selection_date,
        dry_run=dry_run,
    )
    result["data_provider"] = resolved_settings.data_provider
    result["duckdb_path"] = str(resolved_store.db_path)
    return result


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and update one review decision."""
    parser = argparse.ArgumentParser(description="Update one local review decision.")
    parser.add_argument("--ts-code", required=True, help="Stock ts_code, for example 002475.SZ.")
    parser.add_argument("--decision", choices=["watch", "pass", "exclude", "needs_data", "pending"])
    parser.add_argument("--reason", default="", help="Review reason.")
    parser.add_argument("--notes", default="", help="Review notes.")
    parser.add_argument("--reviewer", default="", help="Reviewer name.")
    parser.add_argument("--archive", action="store_true", help="Set review_status to archived.")
    parser.add_argument("--reactivate", action="store_true", help="Set review_status to active.")
    parser.add_argument("--selection-date", help="Selection date for the decision row.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    args = parser.parse_args(argv)

    result = update_review_decision(
        ts_code=args.ts_code,
        decision=args.decision,
        reason=args.reason,
        notes=args.notes,
        reviewer=args.reviewer,
        archive=args.archive,
        reactivate=args.reactivate,
        selection_date=args.selection_date,
        dry_run=args.dry_run,
    )
    print("复核状态调整摘要")
    print(f"- 当前 DATA_PROVIDER: {result.get('data_provider')}")
    print(f"- DuckDB 路径: {result.get('duckdb_path')}")
    print(f"- 状态: {result.get('status')}")
    if result.get("message"):
        print(f"- 说明: {result['message']}")
    print(f"- ts_code: {result.get('ts_code')}")
    print(f"- name: {result.get('name') or '暂无'}")
    print(f"- old_decision: {result.get('old_decision') or '暂无'}")
    print(f"- new_decision: {result.get('new_decision') or '暂无'}")
    print(f"- old_review_status: {result.get('old_review_status') or '暂无'}")
    print(f"- new_review_status: {result.get('new_review_status') or '暂无'}")
    print(f"- reason: {result.get('reason') or '暂无'}")
    print(f"- notes: {result.get('notes') or '暂无'}")
    print(f"- reviewer: {result.get('reviewer') or '暂无'}")
    print(f"- action_type: {result.get('action_type') or '暂无'}")
    print(f"- 是否写入 history: {'是' if result.get('history_written') else '否'}")


if __name__ == "__main__":
    main()
