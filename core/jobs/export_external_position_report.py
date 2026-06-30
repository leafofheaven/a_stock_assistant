"""Export external simulated position matching reports."""

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
    "platform",
    "account_name",
    "snapshot_date",
    "ts_code",
    "name",
    "quantity",
    "cost_price",
    "current_price",
    "market_value",
    "pnl",
    "pnl_pct",
    "entry_low",
    "entry_high",
    "stop_loss",
    "target_price",
    "reward_risk_ratio",
    "risk_status_cn",
    "match_note",
]

RISK_NOTE = "外部模拟持仓由用户手工导入；系统不自动交易；匹配结果仅供个人研究和复盘。"


def export_external_position_report(*, output_dir: Path | str = "reports", report_format: str = "all", settings: Settings | None = None, store: DuckDBStore | None = None, quiet: bool = False) -> dict[str, Any]:
    """Export latest external simulated position report."""
    resolved_store = store or DuckDBStore((settings or get_settings()).duckdb_path)
    resolved_store.initialize()
    positions = _latest_positions(_safe_read_table(resolved_store, "external_position_snapshots"))
    report = build_external_position_report(positions)
    files = save_external_position_report(report, output_dir=output_dir, report_format=report_format)
    if not quiet:
        print(_console_summary(report, files))
    return {"status": "success", "report": report, "generated_files": files}


def build_external_position_report(positions: pd.DataFrame) -> dict[str, Any]:
    """Build structured report data."""
    records = positions.to_dict("records") if not positions.empty else []
    risk_counts = positions["risk_status"].fillna("unknown").value_counts().to_dict() if not positions.empty and "risk_status" in positions.columns else {}
    return {
        "metadata": {"generated_at": datetime.now().isoformat(timespec="seconds")},
        "snapshot_date": _latest_date(positions, "snapshot_date"),
        "platform_count": _nunique(positions, "platform"),
        "account_count": _nunique(positions, "account_name"),
        "position_count": len(records),
        "total_market_value": _sum(positions, "market_value"),
        "total_pnl": _sum(positions, "pnl"),
        "risk_position_count": int(sum(risk_counts.get(key, 0) for key in ["near_stop_loss", "hit_stop_loss", "chased_high"])),
        "risk_counts": {str(k): int(v) for k, v in risk_counts.items()},
        "positions": records,
        "risk_note": RISK_NOTE,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render markdown report."""
    lines = [
        "# 外部模拟持仓匹配报告",
        "",
        f"- 快照日期: {report.get('snapshot_date') or '暂无'}",
        f"- 平台数量: {report.get('platform_count', 0)}",
        f"- 账户数量: {report.get('account_count', 0)}",
        f"- 持仓股票数量: {report.get('position_count', 0)}",
        f"- 总市值: {report.get('total_market_value', 0):.2f}",
        f"- 总盈亏: {report.get('total_pnl', 0):.2f}",
        f"- 风险持仓数量: {report.get('risk_position_count', 0)}",
        "",
    ]
    groups = [
        ("跌破止损", "hit_stop_loss"),
        ("接近止损", "near_stop_loss"),
        ("达到目标价", "hit_target"),
        ("成本高于买入区间", "chased_high"),
        ("正常跟踪", "normal"),
        ("数据不足", "insufficient_data"),
    ]
    for title, status in groups:
        items = [item for item in report.get("positions", []) if item.get("risk_status") == status]
        lines.extend([f"## {title}", "", _table_header()])
        lines.extend(_table_row(item) for item in items)
        if not items:
            lines.append("| 暂无 |  |  |  |  |  |  |  |  |  |  |")
        lines.append("")
    lines.extend(["## 提示", "", f"- {report['risk_note']}", ""])
    return "\n".join(lines)


def save_external_position_report(report: dict[str, Any], *, output_dir: Path | str = "reports", report_format: str = "all") -> dict[str, str]:
    """Save report files."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formats = ["markdown", "json", "csv"] if report_format == "all" else [report_format]
    paths: dict[str, str] = {}
    for fmt in formats:
        if fmt == "markdown":
            path = directory / f"external_positions_{timestamp}.md"
            path.write_text(render_markdown_report(report), encoding="utf-8")
        elif fmt == "json":
            path = directory / f"external_positions_{timestamp}.json"
            path.write_text(json.dumps(_jsonable({**report, "generated_files": paths}), ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            path = directory / f"external_positions_{timestamp}.csv"
            external_positions_to_dataframe(report.get("positions", [])).to_csv(path, index=False, encoding="utf-8-sig")
        else:
            raise ValueError("report_format must be markdown, json, csv, or all")
        paths[fmt] = str(path)
    report["generated_files"] = paths
    if "json" in paths:
        Path(paths["json"]).write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def external_positions_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert records to DataFrame."""
    df = pd.DataFrame(records)
    for column in REPORT_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[REPORT_COLUMNS]


def _latest_positions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "snapshot_date" not in df.columns:
        return pd.DataFrame()
    latest = _latest_date(df, "snapshot_date")
    return df[df["snapshot_date"].astype(str) == str(latest)].copy()


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


def _nunique(df: pd.DataFrame, column: str) -> int:
    return 0 if df.empty or column not in df.columns else int(df[column].dropna().nunique())


def _sum(df: pd.DataFrame, column: str) -> float:
    return 0.0 if df.empty or column not in df.columns else float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _table_header() -> str:
    return "| 股票代码 | 名称 | 平台 | 账户 | 数量 | 成本价 | 当前价 | 盈亏 | 买入区间 | 止损位 | 风险状态 |\n| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- |"


def _table_row(item: dict[str, Any]) -> str:
    zone = f"{_display(item.get('entry_low'))}-{_display(item.get('entry_high'))}"
    return (
        f"| {item.get('ts_code') or ''} | {item.get('name') or ''} | {item.get('platform') or ''} | {item.get('account_name') or ''} | "
        f"{_display(item.get('quantity'))} | {_display(item.get('cost_price'))} | {_display(item.get('current_price'))} | {_display(item.get('pnl'))} | "
        f"{zone} | {_display(item.get('stop_loss'))} | {item.get('risk_status_cn') or ''} |"
    )


def _display(value: Any) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "" if pd.isna(number) else f"{float(number):.2f}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is not None and not isinstance(value, (list, dict)) and pd.isna(value):
        return None
    return value


def _console_summary(report: dict[str, Any], files: dict[str, str]) -> str:
    return "\n".join(
        [
            "外部模拟持仓报告导出摘要",
            f"- 快照日期: {report.get('snapshot_date') or '暂无'}",
            f"- 持仓股票数量: {report.get('position_count', 0)}",
            f"- 风险持仓数量: {report.get('risk_position_count', 0)}",
            f"- 报告文件: {', '.join(files.values()) if files else '暂无'}",
        ]
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export external simulated position report.")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--format", choices=["markdown", "json", "csv", "all"], default="all")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    export_external_position_report(output_dir=args.output_dir, report_format=args.format, quiet=args.quiet)


if __name__ == "__main__":
    main()
