"""Position pool report rendering."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json

import pandas as pd


POSITION_REPORT_COLUMNS = [
    "ts_code",
    "name",
    "entry_date",
    "entry_price",
    "quantity",
    "latest_trade_date",
    "latest_close",
    "pnl_pct",
    "holding_days",
    "max_gain_pct",
    "max_drawdown_pct",
    "close_to_entry_pct",
    "latest_elder_score",
    "weekly_trend",
    "daily_pullback",
    "force_signal",
    "elder_ray_signal",
    "technical_state",
    "position_hint",
    "position_reason",
    "source",
    "entry_reason",
    "status",
    "entry_total_score",
    "entry_elder_score",
    "initial_stop",
    "plan",
    "data_quality_note",
]


def build_positions_report(
    *,
    metadata: dict[str, Any],
    positions_df: pd.DataFrame,
    active_only: bool = False,
) -> dict[str, Any]:
    """Build a serializable report payload for local positions."""
    display = _display_frame(positions_df)
    return {
        "metadata": metadata,
        "active_only": active_only,
        "position_count": int(len(display)),
        "status_counts": _status_counts(display),
        "positions": display.to_dict("records"),
        "note": "仅供个人研究使用，不自动交易。",
    }


def save_positions_report(
    report: dict[str, Any],
    *,
    output_dir: Path | str = "reports",
    report_format: str = "all",
) -> dict[str, str]:
    """Save position report as Markdown/CSV/JSON."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formats = ["markdown", "csv", "json"] if report_format == "all" else [report_format]
    paths: dict[str, str] = {}
    df = pd.DataFrame(report.get("positions", []))
    for fmt in formats:
        if fmt == "markdown":
            path = directory / f"positions_{timestamp}.md"
            path.write_text(render_positions_markdown(report), encoding="utf-8")
        elif fmt == "csv":
            path = directory / f"positions_{timestamp}.csv"
            df.to_csv(path, index=False, encoding="utf-8-sig")
        elif fmt == "json":
            path = directory / f"positions_{timestamp}.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        else:
            raise ValueError("report_format must be markdown, csv, json, or all")
        paths[fmt] = str(path)
    return paths


def render_positions_markdown(report: dict[str, Any]) -> str:
    """Render position pool report as Markdown."""
    lines = [
        "# 持仓池报告",
        "",
        f"- 生成时间: {report.get('metadata', {}).get('generated_at', '')}",
        f"- 数据来源: {report.get('metadata', {}).get('data_provider', '')}",
        f"- 持仓记录数量: {report.get('position_count', 0)}",
        f"- active_only: {'是' if report.get('active_only') else '否'}",
        f"- 提示: {report.get('note', '仅供个人研究使用，不自动交易。')}",
        "",
    ]
    positions = report.get("positions", [])
    if not positions:
        lines.append("暂无持仓记录。")
        return "\n".join(lines)
    lines.extend(
        [
            "| 股票代码 | 股票名称 | 买入日期 | 买入价 | 最新收盘价 | 当前盈亏% | 最大浮盈% | 最大回撤% | 持仓天数 | 最新Elder | 技术状态 | 持仓提示 | 状态 | 原因 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for item in positions:
        lines.append(
            "| {ts_code} | {name} | {entry_date} | {entry_price} | {latest_close} | {pnl_pct} | {max_gain} | {max_drawdown} | {holding_days} | {elder_score} | {technical_state} | {position_hint} | {status} | {reason} |".format(
                ts_code=item.get("ts_code") or "",
                name=item.get("name") or "",
                entry_date=item.get("entry_date") or "",
                entry_price=_fmt_number(item.get("entry_price")),
                latest_close=_fmt_number(item.get("latest_close")),
                pnl_pct=_fmt_pct(item.get("pnl_pct")),
                max_gain=_fmt_pct(item.get("max_gain_pct")),
                max_drawdown=_fmt_pct(item.get("max_drawdown_pct")),
                holding_days=item.get("holding_days") if item.get("holding_days") is not None else "暂无",
                elder_score=_fmt_number(item.get("latest_elder_score")),
                technical_state=item.get("technical_state") or "",
                position_hint=item.get("position_hint") or "",
                status=item.get("status") or "",
                reason=item.get("position_reason") or item.get("data_quality_note") or "",
            )
        )
    return "\n".join(lines)


def build_console_summary(report: dict[str, Any], files: dict[str, str]) -> str:
    """Build console summary for export_positions."""
    lines = [
        "持仓池导出摘要",
        f"- 持仓记录数量: {report.get('position_count', 0)}",
        "- 已包含每日跟踪字段: latest_close, pnl_pct, max_gain_pct, max_drawdown_pct, latest_elder_score, position_hint。",
        f"- 生成文件: {', '.join(files.values()) if files else '无'}",
        f"- 提示: {report.get('note', '仅供个人研究使用，不自动交易。')}",
    ]
    return "\n".join(lines)


def _display_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=POSITION_REPORT_COLUMNS)
    result = df.copy()
    for column in POSITION_REPORT_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result[POSITION_REPORT_COLUMNS]


def _status_counts(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "status" not in df.columns:
        return {}
    return {str(key): int(value) for key, value in df["status"].fillna("active").value_counts().to_dict().items()}


def _fmt_number(value: Any) -> str:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return "暂无"
    if pd.isna(converted):
        return "暂无"
    return f"{converted:.2f}"


def _fmt_pct(value: Any) -> str:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return "暂无"
    if pd.isna(converted):
        return "暂无"
    return f"{converted:.2%}"
