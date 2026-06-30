"""Export entry zone snapshots as local reports."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError

REPORT_COLUMNS = [
    "ts_code",
    "name",
    "trade_date",
    "close",
    "entry_low",
    "entry_high",
    "stop_loss",
    "target_price",
    "reward_risk_ratio",
    "chase_risk_cn",
    "entry_zone_status_cn",
    "price_action_note",
    "source",
]

RISK_NOTE = "买入区间、止损位、目标价位仅供个人研究和人工复核；不自动交易，不构成收益保证。"


def export_entry_zone_report(
    *,
    output_dir: Path | str = "reports",
    report_format: str = "all",
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """Export the latest entry zone snapshots."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    snapshots = _latest_snapshots(_safe_read_table(resolved_store, "entry_zone_snapshots"))
    report = build_entry_zone_report(
        metadata={
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_provider": resolved_settings.data_provider,
            "duckdb_path": str(resolved_store.db_path),
        },
        snapshots=snapshots,
    )
    files = save_entry_zone_report(report, output_dir=output_dir, report_format=report_format)
    if not quiet:
        print(_console_summary(report, files))
    return {"status": "success" if snapshots is not None else "partial_success", "report": report, "generated_files": files}


def build_entry_zone_report(*, metadata: dict[str, Any], snapshots: pd.DataFrame) -> dict[str, Any]:
    """Build structured entry zone report data."""
    records = snapshots.to_dict("records") if isinstance(snapshots, pd.DataFrame) and not snapshots.empty else []
    status_counts = {}
    if records:
        status_counts = {str(key): int(value) for key, value in snapshots["entry_zone_status"].fillna("unknown").value_counts().items()}
    return {
        "metadata": metadata,
        "trade_date": _latest_date(snapshots, "trade_date") if isinstance(snapshots, pd.DataFrame) else None,
        "stock_count": len(records),
        "in_zone_count": status_counts.get("in_zone", 0),
        "near_zone_count": status_counts.get("near_zone", 0),
        "above_zone_count": status_counts.get("above_zone", 0),
        "weak_no_entry_count": status_counts.get("weak_no_entry", 0),
        "insufficient_data_count": status_counts.get("insufficient_data", 0),
        "high_chase_risk_count": _count_equals(snapshots, "chase_risk", "high"),
        "items": records,
        "risk_note": RISK_NOTE,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render the entry zone report as Markdown."""
    lines = [
        "# 买入区间分析报告",
        "",
        f"- 运行时间: {report['metadata'].get('generated_at')}",
        f"- 当前数据来源: {report['metadata'].get('data_provider')}",
        f"- 计算日期: {report.get('trade_date') or '暂无'}",
        f"- 股票数量: {report.get('stock_count', 0)}",
        f"- 位于买入区间数量: {report.get('in_zone_count', 0)}",
        f"- 接近买入区间数量: {report.get('near_zone_count', 0)}",
        f"- 高追高风险数量: {report.get('high_chase_risk_count', 0)}",
        f"- 趋势偏弱数量: {report.get('weak_no_entry_count', 0)}",
        "",
    ]
    groups = [
        ("位于买入区间", "in_zone"),
        ("接近买入区间", "near_zone"),
        ("等待回调 / 短线过热", "above_zone"),
        ("趋势偏弱", "weak_no_entry"),
        ("数据不足", "insufficient_data"),
    ]
    for title, status in groups:
        items = [item for item in report.get("items", []) if item.get("entry_zone_status") == status]
        lines.extend([f"## {title}", "", _table_header()])
        lines.extend(_table_row(item) for item in items)
        if not items:
            lines.append("| 暂无 |  |  |  |  |  |  |  |  |")
        lines.append("")
    lines.extend(["## 说明", "", f"- {report['risk_note']}", ""])
    return "\n".join(lines)


def save_entry_zone_report(
    report: dict[str, Any],
    *,
    output_dir: Path | str = "reports",
    report_format: str = "all",
) -> dict[str, str]:
    """Save entry zone report files."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formats = ["markdown", "json", "csv"] if report_format == "all" else [report_format]
    paths: dict[str, str] = {}
    for fmt in formats:
        if fmt == "markdown":
            path = directory / f"entry_zone_{timestamp}.md"
            path.write_text(render_markdown_report(report), encoding="utf-8")
        elif fmt == "json":
            path = directory / f"entry_zone_{timestamp}.json"
            path.write_text(json.dumps(_jsonable({**report, "generated_files": paths}), ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            path = directory / f"entry_zone_{timestamp}.csv"
            entry_zone_to_dataframe(report.get("items", [])).to_csv(path, index=False, encoding="utf-8-sig")
        else:
            raise ValueError("report_format must be markdown, json, csv, or all")
        paths[fmt] = str(path)
    report["generated_files"] = paths
    if "json" in paths:
        Path(paths["json"]).write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def entry_zone_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert entry zone records to CSV DataFrame."""
    df = pd.DataFrame(records)
    for column in REPORT_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[REPORT_COLUMNS]


def _latest_snapshots(snapshots: pd.DataFrame) -> pd.DataFrame:
    if snapshots.empty or "trade_date" not in snapshots.columns:
        return pd.DataFrame()
    latest = _latest_date(snapshots, "trade_date")
    return snapshots[snapshots["trade_date"].astype(str) == str(latest)].copy()


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _latest_date(df: pd.DataFrame, column: str) -> str | None:
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    return None if values.empty else str(values.max())


def _count_equals(df: pd.DataFrame, column: str, value: str) -> int:
    if not isinstance(df, pd.DataFrame) or df.empty or column not in df.columns:
        return 0
    return int((df[column].astype(str) == value).sum())


def _table_header() -> str:
    return "| 股票代码 | 名称 | 当前价 | 买入区间 | 止损位 | 目标价位 | 盈亏比 | 追高风险 | 状态 | 说明 |\n| --- | --- | ---: | --- | ---: | ---: | ---: | --- | --- | --- |"


def _table_row(item: dict[str, Any]) -> str:
    zone = f"{_display(item.get('entry_low'))}-{_display(item.get('entry_high'))}"
    return (
        f"| {item.get('ts_code') or ''} | {item.get('name') or ''} | {_display(item.get('close'))} | {zone} | "
        f"{_display(item.get('stop_loss'))} | {_display(item.get('target_price'))} | {_display(item.get('reward_risk_ratio'))} | "
        f"{item.get('chase_risk_cn') or ''} | {item.get('entry_zone_status_cn') or ''} | {item.get('price_action_note') or ''} |"
    )


def _display(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    return f"{float(numeric):.2f}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value) if value is not None and not isinstance(value, (list, dict)) else False:
        return None
    return value


def _console_summary(report: dict[str, Any], files: dict[str, str]) -> str:
    return "\n".join(
        [
            "买入区间报告导出摘要",
            f"- 计算日期: {report.get('trade_date') or '暂无'}",
            f"- 股票数量: {report.get('stock_count', 0)}",
            f"- 位于买入区间数量: {report.get('in_zone_count', 0)}",
            f"- 接近买入区间数量: {report.get('near_zone_count', 0)}",
            f"- 高追高风险数量: {report.get('high_chase_risk_count', 0)}",
            f"- 报告文件: {', '.join(files.values()) if files else '暂无'}",
        ]
    )


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and export entry zone report."""
    parser = argparse.ArgumentParser(description="Export entry zone reports.")
    parser.add_argument("--output-dir", default="reports", help="Output directory.")
    parser.add_argument("--format", choices=["markdown", "json", "csv", "all"], default="all", help="Report format.")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    args = parser.parse_args(argv)
    export_entry_zone_report(output_dir=args.output_dir, report_format=args.format, quiet=args.quiet)


if __name__ == "__main__":
    main()

