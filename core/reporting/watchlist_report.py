"""Watchlist report generation for reviewed candidates."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

RISK_DISCLAIMER = (
    "观察池仅记录人工复核结论，不构成投资建议，不提供目标价，"
    "不保证收益，不包含自动交易建议。"
)

WATCHLIST_COLUMNS = [
    "ts_code",
    "name",
    "selection_date",
    "review_date",
    "decision",
    "reviewer",
    "reason",
    "notes",
    "latest_trade_date",
    "latest_close",
    "total_score",
    "data_quality_note",
]


def build_watchlist_report(
    *,
    metadata: dict[str, Any],
    watchlist_df: pd.DataFrame,
    active_only: bool = True,
) -> dict[str, Any]:
    """Build a structured watchlist report."""
    records = _records(watchlist_df)
    return {
        "metadata": metadata,
        "data_source": metadata.get("data_provider", ""),
        "active_only": active_only,
        "watchlist_count": len(records),
        "watchlist": records,
        "generated_files": {},
        "risk_disclaimer": RISK_DISCLAIMER,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render watchlist report as Markdown."""
    metadata = report["metadata"]
    lines = [
        "# 观察池报告",
        "",
        f"- 运行时间: {metadata.get('generated_at')}",
        f"- 当前数据来源: {metadata.get('data_provider')}",
        f"- 观察池股票数量: {report.get('watchlist_count', 0)}",
        "",
        "## 观察池总表",
        "",
        "| ts_code | name | decision | reviewer | latest_trade_date | latest_close | total_score | reason |",
        "| --- | --- | --- | --- | --- | ---: | ---: | --- |",
        *[
            "| {ts_code} | {name} | {decision} | {reviewer} | {latest_trade_date} | {latest_close} | {total_score} | {reason} |".format(
                **_markdown_row(item)
            )
            for item in report["watchlist"]
        ],
        "",
        "## 每只股票详情",
        "",
    ]
    for item in report["watchlist"]:
        lines.extend(
            [
                f"### {item.get('ts_code')} {item.get('name')}",
                "",
                f"- selection_date: {item.get('selection_date') or '暂无'}",
                f"- review_date: {item.get('review_date') or '暂无'}",
                f"- decision: {item.get('decision') or '暂无'}",
                f"- reviewer: {item.get('reviewer') or '暂无'}",
                f"- reason: {item.get('reason') or '暂无'}",
                f"- notes: {item.get('notes') or '暂无'}",
                f"- 最新行情日期: {item.get('latest_trade_date') or '暂无'}",
                f"- 最新收盘价: {_display(item.get('latest_close'))}",
                f"- 当前评分: {_display(item.get('total_score'))}",
                f"- 数据质量提示: {item.get('data_quality_note') or '暂无'}",
                "",
            ]
        )
    lines.extend(["## 风险提示", "", f"- {report['risk_disclaimer']}", ""])
    return "\n".join(lines)


def save_watchlist_report(
    report: dict[str, Any],
    output_dir: Path | str = "reports",
    report_format: str = "all",
) -> dict[str, str]:
    """Save watchlist report files and return paths."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formats = ["markdown", "json", "csv"] if report_format == "all" else [report_format]
    paths: dict[str, str] = {}
    for fmt in formats:
        if fmt == "markdown":
            path = directory / f"watchlist_{timestamp}.md"
            path.write_text(render_markdown_report(report), encoding="utf-8")
        elif fmt == "json":
            path = directory / f"watchlist_{timestamp}.json"
            path.write_text(json.dumps(_jsonable({**report, "generated_files": paths}), ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            path = directory / f"watchlist_{timestamp}.csv"
            watchlist_to_dataframe(report["watchlist"]).to_csv(path, index=False, encoding="utf-8-sig")
        else:
            raise ValueError("report_format must be markdown, json, csv, or all")
        paths[fmt] = str(path)
    report["generated_files"] = paths
    if "json" in paths:
        Path(paths["json"]).write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def watchlist_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert watchlist records to CSV DataFrame."""
    df = pd.DataFrame(records)
    for column in WATCHLIST_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[WATCHLIST_COLUMNS]


def load_latest_watchlist_report(report_dir: Path | str = "reports") -> dict[str, Any] | None:
    """Load compact summary from the latest watchlist JSON report."""
    directory = Path(report_dir)
    if not directory.exists():
        return None
    candidates = list(directory.glob("watchlist_*.json"))
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "generated_at": payload.get("metadata", {}).get("generated_at"),
        "data_source": payload.get("data_source"),
        "watchlist_count": payload.get("watchlist_count", 0),
    }


def build_console_summary(report: dict[str, Any], files: dict[str, str]) -> str:
    """Return concise watchlist export summary."""
    return "\n".join(
        [
            "观察池导出摘要",
            f"- 数据来源: {report['data_source']}",
            f"- 观察池股票数量: {report['watchlist_count']}",
            f"- 生成文件: {', '.join(files.values())}",
        ]
    )


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [_jsonable(row) for row in df.to_dict("records")]


def _markdown_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts_code": item.get("ts_code", ""),
        "name": item.get("name", ""),
        "decision": item.get("decision", ""),
        "reviewer": item.get("reviewer", ""),
        "latest_trade_date": item.get("latest_trade_date", ""),
        "latest_close": _display(item.get("latest_close")),
        "total_score": _display(item.get("total_score")),
        "reason": str(item.get("reason", "")).replace("|", "/"),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def _display(value: Any) -> str:
    if value is None or pd.isna(value):
        return "暂无"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
