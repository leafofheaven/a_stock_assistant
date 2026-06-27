"""Workflow report generation for real-data daily runs."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

RISK_NOTES = [
    "当前仅为选股辅助，不构成投资建议。",
    "当前可能仅基于少量真实股票。",
    "AKShare fallback 的 pe/pb 可能为空。",
    "AKShare fallback 的 adj_factor 可能简化为 1.0。",
    "本项目不自动交易。",
]


def build_workflow_report(
    *,
    started_at: datetime,
    finished_at: datetime,
    settings: Any,
    steps: dict[str, dict[str, Any]],
    overall_status: str,
) -> dict[str, Any]:
    """Return a structured workflow report from step results."""
    backup = _step_result(steps, "backup_local_data")
    update = _step_result(steps, "update_real_data")
    real_data = _step_result(steps, "diagnose_real_data")
    batch = _step_result(steps, "diagnose_update_batch")
    factors = _step_result(steps, "diagnose_factors")
    selection = _step_result(steps, "run_daily_selection")
    backtest = _step_result(steps, "diagnose_backtest")
    selection_review = _step_result(steps, "export_selection_review")
    review_template = _step_result(steps, "export_review_template")
    watchlist = _step_result(steps, "export_watchlist")
    watchlist_tracking = _step_result(steps, "track_watchlist")
    watchlist_tracking_export = _step_result(steps, "export_watchlist_tracking")
    review_decisions = _step_result(steps, "review_decisions")
    review_history = _step_result(steps, "diagnose_review_history")
    sample_symbols = _configured_symbols(settings)

    return {
        "title": "真实运行工作流报告",
        "overall_status": overall_status,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "data_provider": getattr(settings, "data_provider", ""),
        "duckdb_path": str(getattr(settings, "duckdb_path", "")),
        "real_universe": {
            "akshare_sample_symbols": getattr(settings, "akshare_sample_symbols", ""),
            "real_data_sample_symbols": getattr(settings, "real_data_sample_symbols", ""),
            "real_universe_preset": getattr(settings, "real_universe_preset", ""),
            "configured_symbol_count": len(sample_symbols),
            "configured_symbols": sample_symbols,
        },
        "steps": _jsonable(steps),
        "summaries": {
            "backup_local_data": _backup_summary(backup),
            "update_real_data": _update_summary(update),
            "diagnose_update_batch": _batch_summary(batch),
            "diagnose_real_data": _real_data_summary(real_data),
            "diagnose_factors": _factor_summary(factors),
            "run_daily_selection": _selection_summary(selection),
            "diagnose_backtest": _backtest_summary(backtest),
            "export_selection_review": _selection_review_summary(selection_review),
            "export_review_template": _generated_files_summary(review_template),
            "export_watchlist": _generated_files_summary(watchlist),
            "track_watchlist": _watchlist_tracking_summary(watchlist_tracking),
            "export_watchlist_tracking": _generated_files_summary(watchlist_tracking_export),
            "review_decisions": _review_decisions_summary(review_decisions),
            "diagnose_review_history": _review_history_summary(review_history),
        },
        "risk_notes": RISK_NOTES,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render a workflow report as Markdown."""
    summaries = report["summaries"]
    lines = [
        f"# {report['title']}",
        "",
        f"- 运行时间: {report['started_at']} 至 {report['finished_at']}",
        f"- 整体状态: {report['overall_status']}",
        f"- 当前 DATA_PROVIDER: {report['data_provider']}",
        f"- DuckDB 路径: {report['duckdb_path']}",
        "",
        "## 真实股票配置",
        "",
        f"- AKSHARE_SAMPLE_SYMBOLS: {report['real_universe']['akshare_sample_symbols'] or '未配置'}",
        f"- REAL_UNIVERSE_PRESET: {report['real_universe']['real_universe_preset'] or '未配置'}",
        f"- 配置股票数量: {report['real_universe']['configured_symbol_count']}",
        "",
        "## backup_local_data 摘要",
        "",
        *_dict_lines(summaries["backup_local_data"]),
        "",
        "## update_real_data 摘要",
        "",
        *_dict_lines(summaries["update_real_data"]),
        "",
        "## diagnose_update_batch 摘要",
        "",
        *_dict_lines(summaries["diagnose_update_batch"]),
        "",
        "## diagnose_real_data 摘要",
        "",
        *_dict_lines(summaries["diagnose_real_data"]),
        "",
        "## diagnose_factors 摘要",
        "",
        *_dict_lines(summaries["diagnose_factors"]),
        "",
        "## run_daily_selection 摘要",
        "",
        *_dict_lines(summaries["run_daily_selection"], skip_keys={"top_candidates"}),
        "",
        "### Top 候选股票",
        "",
        *_records_lines(summaries["run_daily_selection"].get("top_candidates", [])),
        "",
        "## diagnose_backtest 摘要",
        "",
        *_dict_lines(summaries["diagnose_backtest"]),
        "",
        "## selection_review 导出摘要",
        "",
        *_dict_lines(summaries["export_selection_review"]),
        "",
        "## review_template 导出摘要",
        "",
        *_dict_lines(summaries["export_review_template"]),
        "",
        "## watchlist 导出摘要",
        "",
        *_dict_lines(summaries["export_watchlist"]),
        "",
        "## watchlist_snapshots 摘要",
        "",
        *_dict_lines(summaries["track_watchlist"]),
        "",
        "## watchlist_tracking 导出摘要",
        "",
        *_dict_lines(summaries["export_watchlist_tracking"]),
        "",
        "## review_decisions 摘要",
        "",
        *_dict_lines(summaries["review_decisions"]),
        "",
        "## review_decision_history 摘要",
        "",
        *_dict_lines(summaries["diagnose_review_history"], skip_keys={"recent_records"}),
        "",
        "### 最近复核状态变更",
        "",
        *_review_history_lines(summaries["diagnose_review_history"].get("recent_records", [])),
        "",
        "## 风险提示",
        "",
        *[f"- {note}" for note in report["risk_notes"]],
        "",
    ]
    return "\n".join(lines)


def save_workflow_report(
    report: dict[str, Any],
    report_dir: Path | str = "reports",
    report_format: str = "markdown",
) -> Path:
    """Save a workflow report and return the created path."""
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if report_format == "json":
        path = directory / f"real_workflow_{timestamp}.json"
        path.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    if report_format != "markdown":
        raise ValueError("report_format must be markdown or json")
    path = directory / f"real_workflow_{timestamp}.md"
    path.write_text(render_markdown_report(report), encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(_jsonable(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def find_latest_workflow_report(report_dir: Path | str = "reports") -> Path | None:
    """Return the newest workflow report path when one exists."""
    directory = Path(report_dir)
    if not directory.exists():
        return None
    candidates = [
        path
        for pattern in ("real_workflow_*.json", "real_workflow_*.md")
        for path in directory.glob(pattern)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_latest_workflow_report(report_dir: Path | str = "reports") -> dict[str, Any] | None:
    """Load a compact summary from the newest workflow report."""
    path = find_latest_workflow_report(report_dir)
    if path is None:
        return None
    if path.suffix == ".md" and path.with_suffix(".json").exists():
        path = path.with_suffix(".json")
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        summaries = payload.get("summaries", {})
        return {
            "path": str(path),
            "run_time": payload.get("finished_at") or payload.get("started_at"),
            "overall_status": payload.get("overall_status"),
            "data_provider": payload.get("data_provider"),
            "latest_price_date": summaries.get("diagnose_real_data", {}).get("latest_price_date")
            or summaries.get("run_daily_selection", {}).get("latest_price_date"),
            "coverage_rate": summaries.get("diagnose_update_batch", {}).get("coverage_rate"),
            "candidate_count": summaries.get("run_daily_selection", {}).get("candidate_count"),
            "fallback_to_sample": summaries.get("run_daily_selection", {}).get("fallback_to_sample"),
        }
    return {
        "path": str(path),
        "run_time": _timestamp_from_name(path),
        "overall_status": "见 Markdown 报告",
        "data_provider": None,
        "latest_price_date": None,
        "coverage_rate": None,
        "candidate_count": None,
        "fallback_to_sample": None,
    }


def build_console_summary(report: dict[str, Any], report_path: Path) -> str:
    """Return a concise console summary for a workflow run."""
    selection = report["summaries"]["run_daily_selection"]
    real_data = report["summaries"]["diagnose_real_data"]
    return "\n".join(
        [
            "真实运行工作流摘要",
            f"- 整体状态: {report['overall_status']}",
            f"- 数据来源: {report['data_provider']}",
            f"- 最新行情日期: {real_data.get('latest_price_date') or selection.get('latest_price_date') or '暂无'}",
            f"- 候选股票数量: {selection.get('candidate_count', 0)}",
            f"- 是否回退 sample: {'是' if selection.get('fallback_to_sample') else '否'}",
            f"- 报告文件: {report_path}",
        ]
    )


def _step_result(steps: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    return steps.get(name, {"status": "skipped", "result": {}})


def _update_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    written = result.get("written_rows", {})
    return {
        "status": step.get("status"),
        "message": result.get("message", step.get("message", "")),
        "success_symbols": result.get("success_symbols", 0),
        "failed_symbols": result.get("failed_symbols", 0),
        "daily_price_written_rows": written.get("daily_price", 0),
        "daily_basic_written_rows": written.get("daily_basic", 0),
    }


def _backup_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    return {
        "status": step.get("status"),
        "backup_dir": result.get("backup_dir"),
        "include_reports": result.get("include_reports"),
        "backup_size": result.get("backup_size"),
    }


def _batch_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    return {
        "status": step.get("status"),
        "coverage_rate": result.get("coverage_rate", 0.0),
        "priced_symbol_count": result.get("priced_symbol_count", 0),
        "missing_symbol_count": len(result.get("missing_symbols", [])),
    }


def _real_data_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    return {
        "status": step.get("status"),
        "latest_price_date": result.get("latest_price_date"),
        "table_rows": result.get("table_rows", {}),
        "is_ready_for_selection": result.get("is_ready_for_selection", False),
        "reasons": result.get("reasons", []),
    }


def _factor_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    return {
        "status": step.get("status"),
        "stock_pool_count": result.get("stock_pool_count", 0),
        "factor_calculable_count": result.get("factor_calculable_count", 0),
        "total_score_non_null_count": result.get("total_score_non_null_count", 0),
        "factor_quality": result.get("factor_quality", {}),
        "data_quality_notes": result.get("data_quality_notes", []),
        "reasons": result.get("reasons", []),
    }


def _selection_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    return {
        "status": step.get("status"),
        "is_real_data": result.get("is_real_data", False),
        "fallback_to_sample": result.get("fallback_to_sample", False),
        "latest_price_date": result.get("latest_price_date"),
        "candidate_count": result.get("candidate_count", 0),
        "top_candidates": result.get("top_candidates", []),
        "data_quality_note": result.get("data_quality_note", ""),
        "result_location": result.get("result_location", ""),
    }


def _backtest_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    return {
        "status": step.get("status"),
        "can_backtest": bool(result.get("portfolio_built") and result.get("equity_curve_rows", 0) > 0),
        "start_date": result.get("start_date"),
        "end_date": result.get("end_date"),
        "stock_count": result.get("stock_count", 0),
        "metrics": result.get("metrics", {}),
        "reasons": result.get("reasons", []),
    }


def _selection_review_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    report = result.get("report", {})
    summary = report.get("selection_summary", {})
    return {
        "status": step.get("status"),
        "candidate_count": summary.get("exported_candidate_count", 0),
        "generated_files": result.get("generated_files", {}),
    }


def _generated_files_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    return {
        "status": step.get("status"),
        "row_count": result.get("row_count"),
        "generated_files": result.get("generated_files", {}),
    }


def _watchlist_tracking_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    return {
        "status": step.get("status"),
        "active_watch_count": result.get("active_watch_count", 0),
        "snapshot_count": result.get("snapshot_count", 0),
        "missing_price_count": result.get("missing_price_count", 0),
        "missing_score_count": result.get("missing_score_count", 0),
        "snapshot_date": result.get("snapshot_date"),
        "generated_files": result.get("generated_files", {}),
    }


def _review_decisions_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    return {
        "status": step.get("status"),
        "total_rows": result.get("total_rows", 0),
        "active_watch_count": result.get("active_watch_count", 0),
        "decision_counts": result.get("decision_counts", {}),
    }


def _review_history_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result", {})
    records = result.get("records", [])
    return {
        "status": step.get("status"),
        "history_rows": result.get("history_rows", 0),
        "recent_records": records[:5],
    }


def _dict_lines(values: dict[str, Any], skip_keys: set[str] | None = None) -> list[str]:
    skip = skip_keys or set()
    lines: list[str] = []
    for key, value in values.items():
        if key in skip:
            continue
        lines.append(f"- {key}: {_format_value(value)}")
    return lines or ["- 暂无。"]


def _records_lines(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return ["- 暂无。"]
    lines = []
    for item in records:
        rank = item.get("rank", "")
        ts_code = item.get("ts_code", "")
        name = item.get("name", "")
        score = item.get("total_score", "")
        lines.append(f"- {rank}. {ts_code} {name} total_score={score}")
    return lines


def _review_history_lines(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return ["- 暂无。"]
    lines = []
    for item in records:
        lines.append(
            "- {created_at} {ts_code} {name} action={action_type} {old_decision}->{new_decision} status={old_status}->{new_status}".format(
                created_at=item.get("created_at", ""),
                ts_code=item.get("ts_code", ""),
                name=item.get("name", ""),
                action_type=item.get("action_type", ""),
                old_decision=item.get("old_decision") or "暂无",
                new_decision=item.get("new_decision") or "暂无",
                old_status=item.get("old_review_status") or "暂无",
                new_status=item.get("new_review_status") or "暂无",
            )
        )
    return lines


def _format_value(value: Any) -> str:
    if isinstance(value, dict | list):
        return json.dumps(_jsonable(value), ensure_ascii=False)
    if value is None:
        return "暂无"
    return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, pd.Series):
        return value.to_list()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items() if not str(key).endswith("_df")}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
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
        return None
    return value


def _configured_symbols(settings: Any) -> list[str]:
    if getattr(settings, "data_provider", "") == "akshare":
        return list(getattr(settings, "akshare_symbols", []))
    return list(getattr(settings, "sample_symbols", []))


def _timestamp_from_name(path: Path) -> str | None:
    prefix = "real_workflow_"
    stem = path.stem
    if not stem.startswith(prefix):
        return None
    return stem.removeprefix(prefix)
