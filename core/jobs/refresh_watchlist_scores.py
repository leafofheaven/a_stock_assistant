"""Refresh active watchlist latest score snapshots from local DuckDB data."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.jobs.export_watchlist import export_watchlist
from core.review.decisions import build_watchlist_dataframe
from core.review.tracking import create_watchlist_snapshots
from core.storage.duckdb_store import DuckDBStore


def refresh_watchlist_scores(
    *,
    dry_run: bool = False,
    export_report: bool = False,
    output_dir: Path | str = "reports",
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Refresh active watch latest score view and optionally write a snapshot."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    watchlist = build_watchlist_dataframe(resolved_store, active_only=True)
    refreshed = _non_null_count(watchlist, "total_score")
    unable = int(len(watchlist) - refreshed)
    snapshot_result: dict[str, Any] | None = None
    files: dict[str, str] = {}

    if not dry_run and not watchlist.empty:
        snapshot_result = create_watchlist_snapshots(
            settings=resolved_settings,
            store=resolved_store,
            snapshot_date=_latest_snapshot_date(watchlist),
        )
    if export_report:
        export_result = export_watchlist(
            output_dir=output_dir,
            report_format="all",
            active_only=True,
            quiet=True,
            settings=resolved_settings,
            store=resolved_store,
        )
        files = export_result["generated_files"]

    result = {
        "status": "dry_run" if dry_run else "success",
        "data_provider": resolved_settings.data_provider,
        "duckdb_path": str(resolved_store.db_path),
        "active_watch_count": int(len(watchlist)),
        "refreshed_count": refreshed,
        "unable_count": unable,
        "dry_run": dry_run,
        "snapshot_written": bool(snapshot_result and snapshot_result.get("snapshot_count", 0) > 0),
        "snapshot_result": snapshot_result,
        "generated_files": files,
        "items": _items(watchlist),
        "next_steps": [
            "python -m core.jobs.diagnose_watchlist",
            "python -m core.jobs.export_watchlist --format all",
            "python -m core.jobs.track_watchlist",
        ],
    }
    if not quiet:
        print(build_console_summary(result))
    return result


def build_console_summary(result: dict[str, Any]) -> str:
    """Return concise CLI output for watchlist score refresh."""
    lines = [
        "观察池评分刷新摘要",
        f"- 当前 DATA_PROVIDER: {result.get('data_provider')}",
        f"- DuckDB 路径: {result.get('duckdb_path')}",
        f"- active watch 股票数量: {result.get('active_watch_count', 0)}",
        f"- 已刷新评分数量: {result.get('refreshed_count', 0)}",
        f"- 暂无法刷新数量: {result.get('unable_count', 0)}",
        f"- dry-run: {'是' if result.get('dry_run') else '否'}",
        f"- 是否写入 snapshot: {'是' if result.get('snapshot_written') else '否'}",
        "- 每只股票刷新结果:",
    ]
    items = result.get("items") or []
    if not items:
        lines.append("  暂无 active watch 股票。")
    for item in items:
        reason = item.get("score_missing_reason") or "已取得最新综合评分"
        lines.append(
            "  "
            f"{item.get('ts_code')} {item.get('name')} "
            f"latest_trade_date={item.get('latest_trade_date') or '暂无'} "
            f"total_score={_display(item.get('total_score'))} "
            f"reason={reason}"
        )
    if result.get("generated_files"):
        lines.append(f"- 生成报告: {', '.join(result['generated_files'].values())}")
    lines.append("- 下一步建议:")
    lines.extend(f"  - {step}" for step in result.get("next_steps", []))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Parse command line arguments and refresh watchlist scores."""
    parser = argparse.ArgumentParser(description="Refresh active watchlist latest scores from local DuckDB.")
    parser.add_argument("--dry-run", action="store_true", help="Preview latest scores without writing snapshots.")
    parser.add_argument("--export-report", action="store_true", help="Export watchlist report after refresh.")
    parser.add_argument("--output-dir", default="reports", help="Report output directory when --export-report is used.")
    args = parser.parse_args(argv)
    refresh_watchlist_scores(dry_run=args.dry_run, export_report=args.export_report, output_dir=args.output_dir)


def _items(watchlist: pd.DataFrame) -> list[dict[str, Any]]:
    if watchlist.empty:
        return []
    columns = ["ts_code", "name", "latest_trade_date", "total_score", "score_missing_reason"]
    return watchlist[[column for column in columns if column in watchlist.columns]].to_dict("records")


def _latest_snapshot_date(watchlist: pd.DataFrame) -> str:
    if watchlist.empty or "latest_trade_date" not in watchlist.columns:
        return datetime.now().strftime("%Y%m%d")
    values = watchlist["latest_trade_date"].dropna().astype(str)
    return str(values.max()) if not values.empty else datetime.now().strftime("%Y%m%d")


def _non_null_count(df: pd.DataFrame, column: str) -> int:
    if df.empty or column not in df.columns:
        return 0
    return int(pd.to_numeric(df[column], errors="coerce").notna().sum())


def _display(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "None"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


if __name__ == "__main__":
    main()
