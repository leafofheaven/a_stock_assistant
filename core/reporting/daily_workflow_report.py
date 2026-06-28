"""Daily workflow summary report generation."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

RISK_DISCLAIMER = "仅供个人研究使用，不自动交易。"


def build_daily_workflow_report(
    *,
    started_at: datetime,
    finished_at: datetime,
    settings: Any,
    steps: dict[str, dict[str, Any]],
    overall_status: str,
    generated_files: dict[str, str],
    top_n: int,
) -> dict[str, Any]:
    """Build a structured daily workflow report from isolated step results."""
    data_quality = _step_result(steps, "diagnose_data_quality")
    factors = _step_result(steps, "diagnose_factors")
    selection = _step_result(steps, "run_daily_selection")
    selection_review = _step_result(steps, "export_selection_review")
    refresh = _step_result(steps, "refresh_watchlist_scores")
    watchlist = _step_result(steps, "diagnose_watchlist")
    watchlist_export = _step_result(steps, "export_watchlist")
    tracking = _step_result(steps, "track_watchlist")
    tracking_export = _step_result(steps, "export_watchlist_tracking")

    top_candidates = _top_candidates(selection, selection_review, top_n)
    watch_items = _watchlist_items(watchlist, refresh)
    tracking_items = _tracking_items(tracking_export)
    data_quality_scope = _data_quality_scope(data_quality, top_candidates, watch_items)
    data_quality_notes = _data_quality_notes(data_quality_scope, data_quality, factors, selection)
    files = _generated_files(generated_files, selection_review, watchlist_export, tracking_export)

    return {
        "title": "日常工作流日报",
        "overall_status": overall_status,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "data_provider": getattr(settings, "data_provider", ""),
        "duckdb_path": str(getattr(settings, "duckdb_path", "")),
        "update_ran": steps.get("update_real_data", {}).get("status") != "skipped",
        "latest_price_date": _latest_price_date(data_quality, factors, selection),
        "stock_pool_count": _stock_pool_count(factors, selection),
        "valuation_quality": _valuation_quality(data_quality),
        "data_quality_scope": data_quality_scope,
        "total_score_non_null_count": factors.get("result", {}).get("total_score_non_null_count", 0),
        "top_n": top_n,
        "top_candidates": top_candidates,
        "watchlist_summary": {
            "active_watch_count": watchlist.get("result", {}).get("active_watch_count", refresh.get("result", {}).get("active_watch_count", 0)),
            "items": watch_items,
        },
        "watchlist_tracking_summary": {
            "snapshot_count": tracking.get("result", {}).get("snapshot_count", 0),
            "items": tracking_items,
        },
        "data_quality_notes": data_quality_notes,
        "generated_files": files,
        "steps": _jsonable(steps),
        "next_steps": [
            "检查 daily_workflow 报告中的 Top 候选和观察池变化。",
            "需要复核候选时运行 python -m core.jobs.export_review_template --top-n 10。",
            "启动页面：streamlit run web/streamlit_app.py。",
        ],
        "risk_disclaimer": RISK_DISCLAIMER,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render a daily workflow report as Markdown."""
    lines = [
        "# 日常工作流日报",
        "",
        f"- 运行时间: {report['started_at']} 至 {report['finished_at']}",
        f"- 整体状态: {report['overall_status']}",
        f"- DATA_PROVIDER: {report['data_provider']}",
        f"- DuckDB 路径: {report['duckdb_path']}",
        f"- 是否更新数据: {'是' if report['update_ran'] else '否'}",
        f"- 最新行情日期: {report.get('latest_price_date') or '暂无'}",
        f"- 股票池数量: {report.get('stock_pool_count', 0)}",
        f"- 全历史 pe 完整率: {_format_rate(report['valuation_quality'].get('pe_non_null_rate'))}",
        f"- 全历史 pb 完整率: {_format_rate(report['valuation_quality'].get('pb_non_null_rate'))}",
        f"- 最新交易日 PE 完整率: {_format_rate(report['data_quality_scope'].get('latest_date_pe_non_null_rate'))}",
        f"- 最新交易日 PB 完整率: {_format_rate(report['data_quality_scope'].get('latest_date_pb_non_null_rate'))}",
        f"- 候选股票 PE/PB 缺失数量: {report['data_quality_scope'].get('candidate_pe_missing_count', 0)} / {report['data_quality_scope'].get('candidate_pb_missing_count', 0)}",
        f"- 观察池 PE/PB 缺失数量: {report['data_quality_scope'].get('watchlist_pe_missing_count', 0)} / {report['data_quality_scope'].get('watchlist_pb_missing_count', 0)}",
        f"- 综合评分非空股票数量: {report.get('total_score_non_null_count', 0)}",
        "",
        "## Top 候选股票",
        "",
        "| rank | ts_code | name | industry | close | pe | pb | total_score | fundamental_score |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        *[_candidate_line(item) for item in report["top_candidates"]],
        "",
        "## 观察池摘要",
        "",
        f"- active watch 数量: {report['watchlist_summary'].get('active_watch_count', 0)}",
        "",
        "| ts_code | name | total_score | pe | pb | latest_close | latest_trade_date |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        *[_watch_line(item) for item in report["watchlist_summary"].get("items", [])],
        "",
        "## 观察池变化摘要",
        "",
        "| ts_code | name | close_change | score_change |",
        "| --- | --- | ---: | ---: |",
        *[_tracking_line(item) for item in report["watchlist_tracking_summary"].get("items", [])],
        "",
        "## 数据质量提示",
        "",
        *_notes_lines(report["data_quality_notes"]),
        "",
        "## 生成文件",
        "",
        *_files_lines(report["generated_files"]),
        "",
        "## 下一步建议",
        "",
        *[f"- {step}" for step in report["next_steps"]],
        "",
        f"- {report['risk_disclaimer']}",
        "",
    ]
    return "\n".join(lines)


def save_daily_workflow_report(
    report: dict[str, Any],
    *,
    output_dir: Path | str = "reports",
    report_format: str = "all",
) -> dict[str, str]:
    """Save daily workflow report files and return generated paths."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formats = ["markdown", "json", "csv"] if report_format == "all" else [report_format]
    if report_format == "markdown":
        formats = ["markdown", "json"]
    paths: dict[str, str] = {}
    for fmt in formats:
        if fmt == "markdown":
            path = directory / f"daily_workflow_{timestamp}.md"
            path.write_text(render_markdown_report(report), encoding="utf-8")
        elif fmt == "json":
            path = directory / f"daily_workflow_{timestamp}.json"
            path.write_text(json.dumps(_jsonable({**report, "generated_files": {**report.get("generated_files", {}), **paths}}), ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            path = directory / f"daily_workflow_{timestamp}.csv"
            daily_workflow_to_dataframe(report).to_csv(path, index=False, encoding="utf-8-sig")
        else:
            raise ValueError("report_format must be markdown, json, csv, or all")
        paths[fmt] = str(path)
    report["generated_files"] = {**report.get("generated_files", {}), **paths}
    if "json" in paths:
        Path(paths["json"]).write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def daily_workflow_to_dataframe(report: dict[str, Any]) -> pd.DataFrame:
    """Return a compact CSV summary for the daily workflow."""
    rows: list[dict[str, Any]] = []
    for item in report.get("top_candidates", []):
        rows.append({"section": "top_candidate", **item})
    for item in report.get("watchlist_summary", {}).get("items", []):
        rows.append({"section": "watchlist", **item})
    for item in report.get("watchlist_tracking_summary", {}).get("items", []):
        rows.append({"section": "watchlist_tracking", **item})
    if not rows:
        rows.append(
            {
                "section": "summary",
                "overall_status": report.get("overall_status"),
                "latest_price_date": report.get("latest_price_date"),
                "stock_pool_count": report.get("stock_pool_count"),
            }
        )
    return pd.DataFrame(rows)


def load_latest_daily_workflow_report(report_dir: Path | str = "reports") -> dict[str, Any] | None:
    """Load compact metadata from the newest daily workflow report."""
    directory = Path(report_dir)
    if not directory.exists():
        return None
    candidates = list(directory.glob("daily_workflow_*.json"))
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "run_time": payload.get("finished_at") or payload.get("started_at"),
        "overall_status": payload.get("overall_status"),
        "data_provider": payload.get("data_provider"),
        "latest_price_date": payload.get("latest_price_date"),
        "top_candidates": payload.get("top_candidates", [])[:10],
        "watchlist": payload.get("watchlist_summary", {}).get("items", []),
    }


def build_console_summary(report: dict[str, Any], files: dict[str, str]) -> str:
    """Return concise console output for a daily workflow run."""
    return "\n".join(
        [
            "日常工作流摘要",
            f"- 整体状态: {report['overall_status']}",
            f"- 数据来源: {report['data_provider']}",
            f"- 最新行情日期: {report.get('latest_price_date') or '暂无'}",
            f"- Top 候选数量: {len(report.get('top_candidates', []))}",
            f"- active watch 数量: {report['watchlist_summary'].get('active_watch_count', 0)}",
            f"- 报告文件: {', '.join(files.values())}",
        ]
    )


def _step_result(steps: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    return steps.get(name, {"status": "skipped", "result": {}})


def _top_candidates(selection_step: dict[str, Any], review_step: dict[str, Any], top_n: int) -> list[dict[str, Any]]:
    review_report = review_step.get("result", {}).get("report", {})
    candidates = review_report.get("candidates", [])
    if candidates:
        return [_candidate_record(item) for item in candidates[:top_n]]
    return [_candidate_record(item) for item in selection_step.get("result", {}).get("top_candidates", [])[:top_n]]


def _candidate_record(item: dict[str, Any]) -> dict[str, Any]:
    scores = item.get("factor_scores", {}) if isinstance(item.get("factor_scores"), dict) else {}
    return {
        "rank": item.get("rank"),
        "ts_code": item.get("ts_code"),
        "name": item.get("name"),
        "industry": item.get("industry"),
        "close": item.get("latest_close") or item.get("close"),
        "pe": item.get("pe"),
        "pb": item.get("pb"),
        "total_score": item.get("total_score") if item.get("total_score") is not None else scores.get("total_score"),
        "fundamental_score": item.get("fundamental_score") if item.get("fundamental_score") is not None else scores.get("fundamental_score"),
    }


def _watchlist_items(watchlist_step: dict[str, Any], refresh_step: dict[str, Any]) -> list[dict[str, Any]]:
    items = watchlist_step.get("result", {}).get("watchlist", [])
    if not items:
        items = refresh_step.get("result", {}).get("items", [])
    return [
        {
            "ts_code": item.get("ts_code"),
            "name": item.get("name"),
            "latest_trade_date": item.get("latest_trade_date"),
            "latest_close": item.get("latest_close"),
            "total_score": item.get("total_score"),
            "pe": item.get("pe"),
            "pb": item.get("pb"),
            "fundamental_score": item.get("fundamental_score"),
            "score_missing_reason": item.get("score_missing_reason"),
        }
        for item in items
    ]


def _tracking_items(tracking_export_step: dict[str, Any]) -> list[dict[str, Any]]:
    items = tracking_export_step.get("result", {}).get("report", {}).get("items", [])
    return [
        {
            "ts_code": item.get("ts_code"),
            "name": item.get("name"),
            "close_change": item.get("close_change_pct"),
            "score_change": item.get("score_change", item.get("total_score_change")),
        }
        for item in items
    ]


def _data_quality_scope(
    data_quality_step: dict[str, Any],
    top_candidates: list[dict[str, Any]],
    watch_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return current-date and current-list data quality scope."""
    result = data_quality_step.get("result", {})
    return {
        "latest_trade_date": result.get("latest_trade_date"),
        "historical_daily_basic_rows": result.get("daily_basic_rows", 0),
        "historical_pe_non_null_rate": result.get("valuation_summary", {}).get("pe_non_null_rate"),
        "historical_pb_non_null_rate": result.get("valuation_summary", {}).get("pb_non_null_rate"),
        "latest_date_rows": result.get("latest_date_stock_count", 0),
        "latest_date_pe_non_null_rate": result.get("latest_date_pe_non_null_rate", result.get("valuation_summary", {}).get("pe_non_null_rate")),
        "latest_date_pb_non_null_rate": result.get("latest_date_pb_non_null_rate", result.get("valuation_summary", {}).get("pb_non_null_rate")),
        "latest_date_total_mv_non_null_rate": result.get("latest_date_total_mv_non_null_rate"),
        "latest_date_circ_mv_non_null_rate": result.get("latest_date_circ_mv_non_null_rate"),
        "candidate_pe_missing_count": _missing_count(top_candidates, "pe"),
        "candidate_pb_missing_count": _missing_count(top_candidates, "pb"),
        "watchlist_pe_missing_count": _missing_count(watch_items, "pe"),
        "watchlist_pb_missing_count": _missing_count(watch_items, "pb"),
    }


def _data_quality_notes(scope: dict[str, Any], *steps: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for step in steps:
        result = step.get("result", {})
        for key in ["data_quality_notes", "data_quality_note", "reasons"]:
            value = result.get(key)
            if isinstance(value, list):
                notes.extend(str(item) for item in value if item)
            elif value:
                notes.append(str(value))
    filtered = [
        note
        for note in notes
        if not _is_stale_valuation_note(note, scope)
    ]
    historical_pe = scope.get("latest_date_pe_non_null_rate") != scope.get("historical_pe_non_null_rate")
    if _current_scope_complete(scope) and _has_historical_valuation_gap(steps):
        filtered.append("PE/PB 当前仅补全最新交易日，历史区间估值字段可能为空。")
    elif historical_pe:
        filtered.append("PE/PB 当前优先按最新交易日和当前列表口径解读。")
    return list(dict.fromkeys(filtered))


def _missing_count(items: list[dict[str, Any]], column: str) -> int:
    return sum(1 for item in items if _is_missing(item.get(column)))


def _current_scope_complete(scope: dict[str, Any]) -> bool:
    return (
        float(scope.get("latest_date_pe_non_null_rate") or 0.0) >= 1.0
        and float(scope.get("latest_date_pb_non_null_rate") or 0.0) >= 1.0
        and int(scope.get("candidate_pe_missing_count") or 0) == 0
        and int(scope.get("candidate_pb_missing_count") or 0) == 0
        and int(scope.get("watchlist_pe_missing_count") or 0) == 0
        and int(scope.get("watchlist_pb_missing_count") or 0) == 0
    )


def _has_historical_valuation_gap(steps: tuple[dict[str, Any], ...]) -> bool:
    for step in steps:
        result = step.get("result", {})
        summary = result.get("valuation_summary", {})
        if float(summary.get("pe_non_null_rate") or 0.0) < 1.0 or float(summary.get("pb_non_null_rate") or 0.0) < 1.0:
            return True
        notes = result.get("data_quality_notes", [])
        if isinstance(notes, list) and any("历史区间估值字段可能为空" in str(note) for note in notes):
            return True
    return False


def _is_stale_valuation_note(note: str, scope: dict[str, Any]) -> bool:
    if not _current_scope_complete(scope):
        return False
    stale_phrases = [
        "部分股票 pe 缺失",
        "部分股票 pb 缺失",
        "缺失股票的 pe_score",
        "缺失股票的估值相关复核信息不完整",
        "最新交易日部分股票 pe 缺失",
        "最新交易日部分股票 pb 缺失",
    ]
    return any(phrase in note for phrase in stale_phrases)


def _generated_files(base: dict[str, str], *steps: dict[str, Any]) -> dict[str, str]:
    files = dict(base)
    for step in steps:
        for key, path in (step.get("result", {}).get("generated_files") or {}).items():
            files[f"{step.get('name', 'step')}_{key}"] = str(path)
    return files


def _valuation_quality(data_quality_step: dict[str, Any]) -> dict[str, Any]:
    result = data_quality_step.get("result", {})
    summary = result.get("valuation_summary", {})
    return {
        "pe_non_null_rate": summary.get("pe_non_null_rate", _field_rate(result, "daily_basic", "pe")),
        "pb_non_null_rate": summary.get("pb_non_null_rate", _field_rate(result, "daily_basic", "pb")),
    }


def _field_rate(result: dict[str, Any], group: str, field: str) -> float | None:
    fields = result.get("field_completeness", {}).get(group, {})
    return fields.get(field, {}).get("non_null_rate") if isinstance(fields.get(field), dict) else None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"", "nan", "none", "<na>", "null"}


def _latest_price_date(*steps: dict[str, Any]) -> str | None:
    for step in steps:
        result = step.get("result", {})
        value = result.get("latest_price_date") or result.get("latest_trade_date")
        if value:
            return str(value)
    return None


def _stock_pool_count(factors_step: dict[str, Any], selection_step: dict[str, Any]) -> int:
    return int(factors_step.get("result", {}).get("stock_pool_count") or selection_step.get("result", {}).get("stock_pool_count") or 0)


def _candidate_line(item: dict[str, Any]) -> str:
    return "| {rank} | {ts_code} | {name} | {industry} | {close} | {pe} | {pb} | {total_score} | {fundamental_score} |".format(
        rank=item.get("rank") or "",
        ts_code=item.get("ts_code") or "",
        name=item.get("name") or "",
        industry=item.get("industry") or "",
        close=_display(item.get("close")),
        pe=_display(item.get("pe")),
        pb=_display(item.get("pb")),
        total_score=_display(item.get("total_score")),
        fundamental_score=_display(item.get("fundamental_score")),
    )


def _watch_line(item: dict[str, Any]) -> str:
    return "| {ts_code} | {name} | {total_score} | {pe} | {pb} | {latest_close} | {latest_trade_date} |".format(
        ts_code=item.get("ts_code") or "",
        name=item.get("name") or "",
        total_score=_display(item.get("total_score")),
        pe=_display(item.get("pe")),
        pb=_display(item.get("pb")),
        latest_close=_display(item.get("latest_close")),
        latest_trade_date=item.get("latest_trade_date") or "",
    )


def _tracking_line(item: dict[str, Any]) -> str:
    return "| {ts_code} | {name} | {close_change} | {score_change} |".format(
        ts_code=item.get("ts_code") or "",
        name=item.get("name") or "",
        close_change=_display(item.get("close_change")),
        score_change=_display(item.get("score_change")),
    )


def _notes_lines(notes: list[str]) -> list[str]:
    return [f"- {note}" for note in notes] if notes else ["- 暂无。"]


def _files_lines(files: dict[str, str]) -> list[str]:
    return [f"- {kind}: {path}" for kind, path in files.items()] if files else ["- 暂无。"]


def _format_rate(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "暂无"
        number = float(value)
        if number > 1:
            number /= 100
        return f"{number:.2%}"
    except (TypeError, ValueError):
        return str(value)


def _display(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "暂无"
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, pd.Series):
        return value.to_list()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items() if not str(key).endswith("_df")}
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
