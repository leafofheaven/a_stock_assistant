"""Export Elder review reports and optionally stage confirmed names for watchlist."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.jobs.run_elder_review import render_elder_review_markdown, run_elder_review
from core.review.decisions import read_review_decisions
from core.review.decisions import update_review_decision as upsert_review_decision
from core.storage.duckdb_store import DuckDBStore


EXPORT_COLUMNS = [
    "rank",
    "ts_code",
    "name",
    "industry",
    "trade_date",
    "total_score",
    "elder_score",
    "action_hint",
    "review_action",
    "elder_reason",
    "weekly_trend",
    "daily_pullback",
    "force_signal",
    "elder_ray_signal",
    "decision",
    "reason",
    "notes",
    "reviewer",
]


def export_elder_review(
    *,
    output_dir: Path | str = "reports",
    report_format: str = "all",
    top_n: int = 10,
    add_confirmed_to_watchlist: bool = False,
    dry_run: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Export Elder review output and optionally add confirmed names to watchlist.

    The default path only writes local report files. It never changes
    ``total_score`` or candidate order. Passing ``add_confirmed_to_watchlist``
    writes ``watch`` review decisions only for rows whose technical status is
    ``趋势确认，进入人工复核`` and skips stocks already present in the active
    watchlist.
    """
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    result = run_elder_review(settings=resolved_settings, store=resolved_store, top_n=top_n)
    review_df = _with_manual_review_columns(result["elder_review_df"])
    files = save_elder_review_report(
        {
            **result,
            "elder_review_df": review_df,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        output_dir=output_dir,
        report_format=report_format,
    )
    watchlist_result = {"attempted": 0, "inserted": 0, "skipped_existing": 0, "dry_run": dry_run, "records": []}
    if add_confirmed_to_watchlist:
        watchlist_result = add_confirmed_elder_to_watchlist(review_df, resolved_store, dry_run=dry_run)
    return {
        "status": "success",
        "review_count": int(len(review_df)),
        "generated_files": files,
        "watchlist_result": watchlist_result,
        "elder_review_df": review_df,
    }


def add_confirmed_elder_to_watchlist(
    review_df: pd.DataFrame,
    store: DuckDBStore,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add confirmed Elder review rows to watchlist, skipping existing active watch rows."""
    confirmed = review_df[review_df["action_hint"] == "趋势确认，进入人工复核"].copy() if "action_hint" in review_df.columns else pd.DataFrame()
    existing = read_review_decisions(store)
    existing_watch = set()
    if not existing.empty:
        mask = (existing["decision"] == "watch") & (existing["review_status"].fillna("active") == "active")
        existing_watch = set(existing.loc[mask, "ts_code"].astype(str))
    records: list[dict[str, Any]] = []
    inserted = 0
    skipped_existing = 0
    for row in confirmed.to_dict("records"):
        ts_code = str(row.get("ts_code") or "")
        if not ts_code:
            continue
        if ts_code in existing_watch:
            skipped_existing += 1
            records.append({"ts_code": ts_code, "status": "skipped_existing"})
            continue
        reason = f"埃尔德复核：{row.get('action_hint')}。{row.get('elder_reason')}"
        notes = f"elder_score={row.get('elder_score')}；Force={row.get('force_signal')}；Elder Ray={row.get('elder_ray_signal')}"
        result = upsert_review_decision(
            store=store,
            ts_code=ts_code,
            decision="watch",
            reason=reason,
            notes=notes,
            reviewer="elder_review",
            selection_date=str(row.get("trade_date") or ""),
            dry_run=dry_run,
        )
        inserted += 0 if dry_run else int(result.get("status") == "success")
        records.append({"ts_code": ts_code, "status": result.get("status"), "message": result.get("message")})
    return {
        "attempted": int(len(confirmed)),
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "dry_run": dry_run,
        "records": records,
    }


def save_elder_review_report(
    result: dict[str, Any],
    output_dir: Path | str = "reports",
    report_format: str = "all",
) -> dict[str, str]:
    """Save Elder review report files and return generated paths."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formats = ["markdown", "csv"] if report_format == "all" else [report_format]
    paths: dict[str, str] = {}
    for fmt in formats:
        if fmt == "markdown":
            path = directory / f"elder_review_{timestamp}.md"
            path.write_text(render_elder_review_markdown(result), encoding="utf-8")
        elif fmt == "csv":
            path = directory / f"elder_review_{timestamp}.csv"
            dataframe = result["elder_review_df"].copy()
            for column in EXPORT_COLUMNS:
                if column not in dataframe.columns:
                    dataframe[column] = pd.NA
            dataframe[EXPORT_COLUMNS].to_csv(path, index=False, encoding="utf-8-sig")
        elif fmt == "json":
            path = directory / f"elder_review_{timestamp}.json"
            payload = {**result, "elder_review_df": result["elder_review_df"].to_dict("records")}
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        else:
            raise ValueError("report_format must be markdown, csv, json, or all")
        paths[fmt] = str(path)
    return paths


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and export Elder review reports."""
    parser = argparse.ArgumentParser(description="Export Elder review reports.")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--format", choices=["markdown", "csv", "json", "all"], default="all")
    parser.add_argument("--add-confirmed-to-watchlist", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = export_elder_review(
        top_n=args.top_n,
        output_dir=args.output_dir,
        report_format=args.format,
        add_confirmed_to_watchlist=args.add_confirmed_to_watchlist,
        dry_run=args.dry_run,
    )
    print("埃尔德复核导出摘要")
    print(f"- 状态: {result['status']}")
    print(f"- 复核股票数量: {result['review_count']}")
    print(f"- 生成文件: {', '.join(result['generated_files'].values())}")
    watch = result["watchlist_result"]
    print(f"- 加入观察池尝试数: {watch['attempted']}")
    print(f"- 新增观察池数量: {watch['inserted']}")
    print(f"- 已存在跳过数量: {watch['skipped_existing']}")
    print(f"- dry_run: {'是' if watch['dry_run'] else '否'}")


def _with_manual_review_columns(review_df: pd.DataFrame) -> pd.DataFrame:
    """Add manual-review CSV helper columns to Elder review rows."""
    if review_df.empty:
        return review_df.copy()
    df = review_df.copy()
    df["decision"] = df["review_action"].map({"加入观察池": "watch"}).fillna("pending")
    df["reason"] = df.apply(lambda row: f"埃尔德复核：{row.get('action_hint')}。{row.get('elder_reason')}", axis=1)
    df["notes"] = df.apply(
        lambda row: f"weekly={row.get('weekly_trend')}；pullback={row.get('daily_pullback')}；force={row.get('force_signal')}；elder_ray={row.get('elder_ray_signal')}",
        axis=1,
    )
    df["reviewer"] = "elder_review"
    return df


if __name__ == "__main__":
    main()
