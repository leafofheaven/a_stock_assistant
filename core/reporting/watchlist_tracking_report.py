"""Watchlist tracking change report generation."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

TRACKING_COLUMNS = [
    "ts_code",
    "name",
    "industry",
    "market",
    "list_date",
    "snapshot_date",
    "trade_date",
    "latest_trade_date",
    "current_close",
    "latest_close",
    "today_rank",
    "previous_rank",
    "rank_change",
    "selected_count_5d",
    "selected_count_10d",
    "consecutive_selected_days",
    "watch_status",
    "watch_status_label",
    "daily_note",
    "pe",
    "pb",
    "total_score",
    "fundamental_score",
    "close_change_pct",
    "score_change",
    "total_score_change",
    "pe_change",
    "pb_change",
    "trend_score_change",
    "momentum_score_change",
    "liquidity_score_change",
    "volatility_score_change",
    "data_quality_note",
    "review_prompt",
]

RISK_DISCLAIMER = "个人研究工具，结果需自行复核，不自动交易。"


def build_watchlist_tracking_report(
    *,
    metadata: dict[str, Any],
    snapshots_df: pd.DataFrame,
    latest_only: bool = True,
    since: str | None = None,
) -> dict[str, Any]:
    """Build a structured watchlist tracking report from snapshots."""
    current, baseline = _current_and_baseline(snapshots_df, latest_only=latest_only, since=since)
    records = [_tracking_record(row, baseline) for row in current.to_dict("records")]
    snapshot_date = _latest_snapshot_date(current)
    return {
        "metadata": metadata,
        "data_source": metadata.get("data_provider", ""),
        "snapshot_date": snapshot_date,
        "watchlist_count": len(records),
        "latest_only": latest_only,
        "since": since,
        "items": records,
        "generated_files": {},
        "risk_disclaimer": RISK_DISCLAIMER,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render watchlist tracking report as Markdown."""
    lines = [
        "# 观察池变化报告",
        "",
        f"- 运行时间: {report['metadata'].get('generated_at')}",
        f"- 当前数据来源: {report.get('data_source')}",
        f"- snapshot_date: {report.get('snapshot_date') or '暂无'}",
        f"- 观察池股票数量: {report.get('watchlist_count', 0)}",
        "",
        "## 当前状态与变化",
        "",
        "| ts_code | name | industry | market | list_date | pe | pb | latest_close | total_score | close_change_pct | score_change | pe_change | pb_change | data_quality_note |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        *[
            "| {ts_code} | {name} | {industry} | {market} | {list_date} | {pe} | {pb} | {latest_close} | {total_score} | {close_change_pct} | {score_change} | {pe_change} | {pb_change} | {data_quality_note} |".format(
                **_markdown_row(item)
            )
            for item in report["items"]
        ],
        "",
        "## 每只股票复核提示",
        "",
    ]
    for item in report["items"]:
        lines.extend(
            [
                f"### {item.get('ts_code')} {item.get('name')}",
                "",
                f"- industry: {item.get('industry') or '缺失'}",
                f"- market: {item.get('market') or '缺失'}",
                f"- list_date: {item.get('list_date') or '缺失'}",
                f"- pe: {_display(item.get('pe'))}",
                f"- pb: {_display(item.get('pb'))}",
                f"- fundamental_score: {_display(item.get('fundamental_score'))}",
                f"- 加入观察后价格变化: {_display(item.get('close_change_pct'))}",
                f"- 综合评分变化: {_display(item.get('score_change'))}",
                f"- pe 变化: {_display(item.get('pe_change'))}",
                f"- pb 变化: {_display(item.get('pb_change'))}",
                f"- 趋势分变化: {_display(item.get('trend_score_change'))}",
                f"- 动量分变化: {_display(item.get('momentum_score_change'))}",
                f"- 流动性分变化: {_display(item.get('liquidity_score_change'))}",
                f"- 波动率分变化: {_display(item.get('volatility_score_change'))}",
                f"- 数据质量提示: {item.get('data_quality_note') or '暂无'}",
                f"- 人工复核提示: {item.get('review_prompt')}",
                "",
            ]
        )
    lines.extend(["## 风险提示", "", f"- {report['risk_disclaimer']}", ""])
    return "\n".join(lines)


def save_watchlist_tracking_report(
    report: dict[str, Any],
    output_dir: Path | str = "reports",
    report_format: str = "all",
) -> dict[str, str]:
    """Save tracking report files and return generated paths."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formats = ["markdown", "json", "csv"] if report_format == "all" else [report_format]
    paths: dict[str, str] = {}
    for fmt in formats:
        if fmt == "markdown":
            path = directory / f"watchlist_tracking_{timestamp}.md"
            path.write_text(render_markdown_report(report), encoding="utf-8")
        elif fmt == "json":
            path = directory / f"watchlist_tracking_{timestamp}.json"
            path.write_text(json.dumps(_jsonable({**report, "generated_files": paths}), ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            path = directory / f"watchlist_tracking_{timestamp}.csv"
            tracking_to_dataframe(report["items"]).to_csv(path, index=False, encoding="utf-8-sig")
        else:
            raise ValueError("report_format must be markdown, json, csv, or all")
        paths[fmt] = str(path)
    report["generated_files"] = paths
    if "json" in paths:
        Path(paths["json"]).write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def tracking_to_dataframe(items: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert tracking items to CSV DataFrame."""
    df = pd.DataFrame(items)
    for column in TRACKING_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[TRACKING_COLUMNS]


def load_latest_watchlist_tracking_report(report_dir: Path | str = "reports") -> dict[str, Any] | None:
    """Load compact metadata from latest tracking report."""
    directory = Path(report_dir)
    if not directory.exists():
        return None
    candidates = list(directory.glob("watchlist_tracking_*.json"))
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "generated_at": payload.get("metadata", {}).get("generated_at"),
        "data_source": payload.get("data_source"),
        "snapshot_date": payload.get("snapshot_date"),
        "watchlist_count": payload.get("watchlist_count", 0),
    }


def build_console_summary(report: dict[str, Any], files: dict[str, str]) -> str:
    """Return concise tracking report summary."""
    return "\n".join(
        [
            "观察池变化报告导出摘要",
            f"- 数据来源: {report['data_source']}",
            f"- snapshot_date: {report.get('snapshot_date') or '暂无'}",
            f"- 观察池股票数量: {report['watchlist_count']}",
            f"- 生成文件: {', '.join(files.values())}",
        ]
    )


def _current_and_baseline(
    snapshots_df: pd.DataFrame,
    latest_only: bool,
    since: str | None,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    if snapshots_df.empty:
        return pd.DataFrame(), {}
    df = snapshots_df.copy()
    date_col = "snapshot_date" if "snapshot_date" in df.columns else "trade_date"
    if "snapshot_date" not in df.columns and "trade_date" in df.columns:
        df["snapshot_date"] = df["trade_date"]
    if since and date_col in df.columns:
        df = df[df[date_col].astype(str) >= since]
    if df.empty:
        return pd.DataFrame(), {}
    if latest_only:
        latest = str(df[date_col].dropna().astype(str).max())
        current = df[df[date_col].astype(str) == latest].copy()
    else:
        current = df.copy()
    baseline_rows = df.sort_values(date_col).groupby("ts_code", as_index=False).head(1)
    baseline = {str(row["ts_code"]): row for row in baseline_rows.to_dict("records")}
    return current.reset_index(drop=True), baseline


def _tracking_record(row: dict[str, Any], baseline: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = baseline.get(str(row.get("ts_code")), {})
    latest_close = row.get("latest_close", row.get("current_close"))
    base_close = base.get("latest_close", base.get("current_close"))
    close_change = _pct_change(latest_close, base_close)
    total_change = _diff(row.get("total_score"), base.get("total_score"))
    pe_change = _diff(row.get("pe"), base.get("pe"))
    pb_change = _diff(row.get("pb"), base.get("pb"))
    data_quality_note = _quality_note(row.get("data_quality_note"), row.get("total_score"))
    return {
        **_jsonable(row),
        "latest_close": latest_close,
        "close_change_pct": close_change,
        "score_change": total_change,
        "total_score_change": total_change,
        "pe_change": pe_change,
        "pb_change": pb_change,
        "trend_score_change": _diff(row.get("trend_score"), base.get("trend_score")),
        "momentum_score_change": _diff(row.get("momentum_score"), base.get("momentum_score")),
        "liquidity_score_change": _diff(row.get("liquidity_score"), base.get("liquidity_score")),
        "volatility_score_change": _diff(row.get("volatility_score"), base.get("volatility_score")),
        "data_quality_note": data_quality_note,
        "review_prompt": _review_prompt(close_change, total_change, data_quality_note),
    }


def _review_prompt(close_change: float | None, total_change: float | None, note: str) -> str:
    prompts: list[str] = []
    if close_change is not None:
        direction = "上涨" if close_change >= 0 else "下跌"
        prompts.append(f"加入观察后收盘价{direction} {abs(close_change):.2%}")
    if total_change is not None:
        direction = "上升" if total_change >= 0 else "下降"
        prompts.append(f"综合评分{direction} {abs(total_change):.2f}")
    if note:
        prompts.append("数据字段缺失，需谨慎解读")
    if not prompts:
        prompts.append("当前变化数据不足，需要人工复核")
    return "；".join(prompts)


def _quality_note(value: Any, total_score: Any) -> str:
    notes = [str(value).strip()] if value and not pd.isna(value) else []
    if _optional_float(total_score) is None:
        notes.append("当前无可用综合评分")
    return "；".join(dict.fromkeys(note for note in notes if note))


def _latest_snapshot_date(df: pd.DataFrame) -> str | None:
    if df.empty or "snapshot_date" not in df.columns:
        return None
    values = df["snapshot_date"].dropna().astype(str)
    return None if values.empty else str(values.max())


def _pct_change(current: Any, previous: Any) -> float | None:
    current_value = _optional_float(current)
    previous_value = _optional_float(previous)
    if current_value is None or previous_value in {None, 0}:
        return None
    return current_value / previous_value - 1


def _diff(current: Any, previous: Any) -> float | None:
    current_value = _optional_float(current)
    previous_value = _optional_float(previous)
    if current_value is None or previous_value is None:
        return None
    return current_value - previous_value


def _markdown_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts_code": item.get("ts_code", ""),
        "name": item.get("name", ""),
        "industry": str(item.get("industry") or "").replace("|", "/"),
        "market": str(item.get("market") or "").replace("|", "/"),
        "list_date": str(item.get("list_date") or "").replace("|", "/"),
        "pe": _display(item.get("pe")),
        "pb": _display(item.get("pb")),
        "latest_close": _display(item.get("latest_close")),
        "total_score": _display(item.get("total_score")),
        "close_change_pct": _display_percent(item.get("close_change_pct")),
        "score_change": _display(item.get("score_change")),
        "total_score_change": _display(item.get("total_score_change")),
        "pe_change": _display(item.get("pe_change")),
        "pb_change": _display(item.get("pb_change")),
        "data_quality_note": str(item.get("data_quality_note", "")).replace("|", "/"),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp | datetime):
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


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _display(value: Any) -> str:
    number = _optional_float(value)
    return "暂无" if number is None else f"{number:.4f}"


def _display_percent(value: Any) -> str:
    number = _optional_float(value)
    return "暂无" if number is None else f"{number:.2%}"
