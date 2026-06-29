"""Refresh watchlist membership from today's local selection results."""

from __future__ import annotations

import argparse
from typing import Any

from app.config import Settings, get_settings
from core.review.tracking import refresh_watchlist_from_selection as refresh_from_selection
from core.storage.duckdb_store import DuckDBStore


def refresh_watchlist_from_selection(
    *,
    trade_date: str | None = None,
    top_n: int | None = None,
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Refresh active watchlist candidates using local selection data only."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    result = refresh_from_selection(
        settings=resolved_settings,
        store=resolved_store,
        trade_date=trade_date,
        top_n=top_n,
    )
    if not quiet:
        print(build_console_summary(result))
    return result


def build_console_summary(result: dict[str, Any]) -> str:
    """Return a concise console summary for the refresh command."""
    counts = result.get("status_counts") or {}
    lines = [
        "观察池候选刷新摘要",
        f"- 当前 DATA_PROVIDER: {result.get('data_provider')}",
        f"- DuckDB 路径: {result.get('duckdb_path')}",
        f"- trade_date: {result.get('trade_date') or '暂无'}",
        f"- 今日候选数量: {result.get('candidate_count', 0)}",
        f"- 今日新入选观察池: {result.get('new_candidate_count', 0)}",
        f"- active watch 数量: {result.get('active_watch_count', 0)}",
        f"- 每日快照数量: {result.get('snapshot_count', 0)}",
        f"- 事件数量: {result.get('event_count', 0)}",
        f"- 状态: {result.get('status')}",
        "- 分层数量:",
    ]
    for key, label in [
        ("new_candidate", "新入选"),
        ("strong_watch", "重点观察"),
        ("active_watch", "正常观察"),
        ("wait_pullback", "等待回调"),
        ("near_buy_zone", "接近买入区间"),
        ("overheated", "短线过热"),
        ("weakening", "走势转弱"),
        ("invalidated", "逻辑失效"),
    ]:
        lines.append(f"  - {label}: {counts.get(key, 0)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and refresh watchlist candidate tracking."""
    parser = argparse.ArgumentParser(description="Refresh watchlist from local selection results.")
    parser.add_argument("--trade-date", help="Selection date in YYYYMMDD. Defaults to latest local selection date.")
    parser.add_argument("--top-n", type=int, help="Candidate count to track. Defaults to DEFAULT_TOP_N.")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    args = parser.parse_args(argv)
    refresh_watchlist_from_selection(trade_date=args.trade_date, top_n=args.top_n, quiet=args.quiet)


if __name__ == "__main__":
    main()
