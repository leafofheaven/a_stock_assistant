"""Create watchlist tracking snapshots from local DuckDB data."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.reporting.watchlist_tracking_report import (
    build_watchlist_tracking_report,
    save_watchlist_tracking_report,
)
from core.review.tracking import (
    create_watchlist_snapshots,
    read_watchlist_daily_snapshots,
    read_watchlist_snapshots,
    refresh_watchlist_from_selection,
)
from core.storage.duckdb_store import DuckDBStore


def track_watchlist(
    *,
    snapshot_date: str | None = None,
    output_dir: Path | str = "reports",
    export_report: bool = False,
    report_format: str = "all",
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Create watchlist snapshots and optionally export a tracking report."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    candidate_result = refresh_watchlist_from_selection(
        settings=resolved_settings,
        store=resolved_store,
        trade_date=snapshot_date,
    )
    result = create_watchlist_snapshots(
        settings=resolved_settings,
        store=resolved_store,
        snapshot_date=snapshot_date,
    )
    files: dict[str, str] = {}
    report: dict[str, Any] | None = None
    if export_report:
        snapshots = read_watchlist_daily_snapshots(resolved_store)
        if snapshots.empty:
            snapshots = read_watchlist_snapshots(resolved_store)
        report = build_watchlist_tracking_report(
            metadata={
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "data_provider": resolved_settings.data_provider,
                "duckdb_path": str(resolved_store.db_path),
            },
            snapshots_df=snapshots,
            latest_only=True,
        )
        files = save_watchlist_tracking_report(report, output_dir=output_dir, report_format=report_format)

    result = {
        **result,
        "candidate_tracking": candidate_result,
        "daily_snapshot_count": candidate_result.get("snapshot_count", 0),
        "watch_status_counts": candidate_result.get("status_counts", {}),
        "event_count": candidate_result.get("event_count", 0),
        "generated_files": files,
        "report": report,
        "output_dir": str(output_dir),
    }
    if not quiet:
        print(build_console_summary(result))
    return result


def build_console_summary(result: dict[str, Any]) -> str:
    """Return a concise console summary for watchlist tracking."""
    lines = [
        "观察池跟踪摘要",
        f"- 当前 DATA_PROVIDER: {result.get('data_provider')}",
        f"- DuckDB 路径: {result.get('duckdb_path')}",
        f"- active watch 股票数量: {result.get('active_watch_count', 0)}",
        f"- 成功生成 snapshot 数量: {result.get('snapshot_count', 0)}",
        f"- 每日候选跟踪 snapshot 数量: {result.get('daily_snapshot_count', 0)}",
        f"- 观察池事件数量: {result.get('event_count', 0)}",
        f"- 缺少行情股票数量: {result.get('missing_price_count', 0)}",
        f"- 缺少评分股票数量: {result.get('missing_score_count', 0)}",
        f"- snapshot_date: {result.get('snapshot_date') or '暂无'}",
        f"- 状态: {result.get('status')}",
    ]
    if result.get("message"):
        lines.append(f"- 说明: {result['message']}")
    if result.get("generated_files"):
        lines.append(f"- 生成报告: {', '.join(result['generated_files'].values())}")
    counts = result.get("watch_status_counts") or {}
    if counts:
        lines.append("- 观察池分层:")
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
    next_steps = result.get("next_steps") or []
    if next_steps:
        lines.append("- 下一步建议:")
        lines.extend(f"  - {step}" for step in next_steps)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and create watchlist snapshots."""
    parser = argparse.ArgumentParser(description="Track active watchlist stocks.")
    parser.add_argument("--snapshot-date", help="Snapshot date in YYYYMMDD. Defaults to latest local trade_date.")
    parser.add_argument("--output-dir", default="reports", help="Report output directory.")
    parser.add_argument("--export-report", action="store_true", help="Export tracking report after snapshot creation.")
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "csv", "all"],
        default="all",
        help="Report format when --export-report is enabled.",
    )
    args = parser.parse_args(argv)
    track_watchlist(
        snapshot_date=args.snapshot_date,
        output_dir=args.output_dir,
        export_report=args.export_report,
        report_format=args.format,
    )


if __name__ == "__main__":
    main()
