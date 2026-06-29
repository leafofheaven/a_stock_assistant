"""Selection review report generation for candidate stock exports."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.explain.selection_logic import (
    LOGIC_VERSION,
    explain_candidate,
    explanation_to_dict,
    formula_summary,
)

SCORE_COLUMNS = [
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "volatility_score",
    "fundamental_score",
    "total_score",
]

RAW_FACTOR_COLUMNS = [
    "return_20d",
    "avg_amount_20d",
    "avg_turnover_20d",
    "volatility_20d",
    "pe_score",
]

CSV_COLUMNS = [
    "rank",
    "ts_code",
    "name",
    "industry",
    "market",
    "list_date",
    "latest_trade_date",
    "latest_close",
    "pe",
    "pb",
    "total_score",
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "volatility_score",
    "fundamental_score",
    "return_20d",
    "avg_amount_20d",
    "avg_turnover_20d",
    "volatility_20d",
    "pe_missing",
    "pb_missing",
    "elder_score",
    "action_hint",
    "elder_reason",
    "weekly_trend",
    "daily_pullback",
    "force_signal",
    "elder_ray_signal",
    "review_action",
    "data_quality_note",
    "selection_reason",
    "top_reasons",
    "weak_points",
    "logic_version",
]

REVIEW_CHECKLIST = [
    "核查最新公告。",
    "核查是否存在停牌、ST、退市风险。",
    "核查行业和主题背景。",
    "核查财务估值数据是否完整。",
    "核查近期涨跌幅是否过大。",
    "核查成交额是否持续稳定。",
    "核查是否有重大利空或监管处罚。",
    "核查当前数据是否来自 sample 或 AKShare fallback。",
]

RISK_DISCLAIMER = (
    "本报告仅用于研究与人工复核辅助，不构成投资建议，不提供目标价，"
    "不保证收益，不包含自动交易建议。"
)


def build_selection_review_report(
    *,
    metadata: dict[str, Any],
    selection_summary: dict[str, Any],
    selection_df: pd.DataFrame,
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    daily_basic_df: pd.DataFrame,
    data_quality_notes: list[str] | None = None,
    top_n: int = 20,
) -> dict[str, Any]:
    """Build a structured candidate review report from local selection data."""
    selected = _prepare_selection(selection_df, factor_df, top_n)
    notes = data_quality_notes or []
    candidates = [
        _candidate_record(row, price_df, daily_basic_df, notes)
        for row in selected.to_dict("records")
    ]
    return {
        "metadata": metadata,
        "data_source": metadata.get("data_provider", ""),
        "data_quality_notes": notes,
        "selection_summary": {
            **selection_summary,
            "exported_candidate_count": len(candidates),
            "top_n": top_n,
        },
        "candidates": candidates,
        "logic_version": LOGIC_VERSION,
        "formula_summary": formula_summary(),
        "generated_files": {},
        "risk_disclaimer": RISK_DISCLAIMER,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render a selection review report as Markdown."""
    metadata = report["metadata"]
    summary = report["selection_summary"]
    lines = [
        "# 候选股票人工复核清单",
        "",
        f"- 运行时间: {metadata.get('generated_at')}",
        f"- 当前 DATA_PROVIDER: {metadata.get('data_provider')}",
        f"- DuckDB 路径: {metadata.get('duckdb_path')}",
        f"- 是否使用真实数据: {'是' if summary.get('is_real_data') else '否'}",
        f"- 是否回退 sample: {'是' if summary.get('fallback_to_sample') else '否'}",
        f"- 最新行情日期: {summary.get('latest_price_date') or '暂无'}",
        f"- 股票池数量: {summary.get('stock_pool_count', 0)}",
        f"- 评分股票数量: {summary.get('scored_stock_count', 0)}",
        f"- 候选股票数量: {summary.get('candidate_count', 0)}",
        f"- 导出候选股票数量: {summary.get('exported_candidate_count', 0)}",
        f"- 综合评分公式: `{report.get('formula_summary')}`",
        "",
        "## Top N 候选股票总表",
        "",
        "| rank | ts_code | name | total_score | latest_close | selection_reason |",
        "| --- | --- | --- | ---: | ---: | --- |",
        *[
            "| {rank} | {ts_code} | {name} | {total_score} | {latest_close} | {selection_reason} |".format(
                **_markdown_row(candidate)
            )
            for candidate in report["candidates"]
        ],
        "",
        "## 每只候选股票详情",
        "",
    ]
    for candidate in report["candidates"]:
        lines.extend(_candidate_markdown(candidate))
    lines.extend(
        [
            "## 风险提示",
            "",
            f"- {report['risk_disclaimer']}",
            "- AKShare fallback 数据字段有限，pe/pb 可能为空，adj_factor 可能简化为 1.0。",
            "- small / medium 仍为样本级真实试运行，不是全市场生产级数据系统。",
            "",
        ]
    )
    return "\n".join(lines)


def save_selection_review_report(
    report: dict[str, Any],
    output_dir: Path | str = "reports",
    report_format: str = "all",
) -> dict[str, str]:
    """Save selection review report files and return generated paths."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formats = ["markdown", "json", "csv"] if report_format == "all" else [report_format]
    paths: dict[str, str] = {}
    for fmt in formats:
        if fmt == "markdown":
            path = directory / f"selection_review_{timestamp}.md"
            path.write_text(render_markdown_report(report), encoding="utf-8")
        elif fmt == "json":
            path = directory / f"selection_review_{timestamp}.json"
            payload = {**report, "generated_files": paths}
            path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            path = directory / f"selection_review_{timestamp}.csv"
            candidates_to_dataframe(report["candidates"]).to_csv(path, index=False, encoding="utf-8-sig")
        else:
            raise ValueError("report_format must be markdown, json, csv, or all")
        paths[fmt] = str(path)
    report["generated_files"] = paths
    if "json" in paths:
        json_path = Path(paths["json"])
        json_path.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def candidates_to_dataframe(candidates: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert candidate records to a flat CSV-friendly DataFrame."""
    rows = []
    for candidate in candidates:
        row = {
            "rank": candidate.get("rank"),
            "ts_code": candidate.get("ts_code"),
            "name": candidate.get("name"),
            "industry": candidate.get("industry"),
            "market": candidate.get("market"),
            "list_date": candidate.get("list_date"),
            "latest_trade_date": candidate.get("latest_trade_date"),
            "latest_close": candidate.get("latest_close"),
            "pe": candidate.get("pe"),
            "pb": candidate.get("pb"),
            "selection_reason": candidate.get("selection_reason"),
            "data_quality_note": candidate.get("data_quality_note"),
            "pe_missing": candidate.get("missing_fields", {}).get("pe", True),
            "pb_missing": candidate.get("missing_fields", {}).get("pb", True),
            "elder_score": candidate.get("elder_score"),
            "action_hint": candidate.get("action_hint"),
            "elder_reason": candidate.get("elder_reason"),
            "weekly_trend": candidate.get("weekly_trend"),
            "daily_pullback": candidate.get("daily_pullback"),
            "force_signal": candidate.get("force_signal"),
            "elder_ray_signal": candidate.get("elder_ray_signal"),
            "review_action": candidate.get("review_action"),
            "top_reasons": "；".join(candidate.get("top_reasons", [])),
            "weak_points": "；".join(candidate.get("weak_points", [])),
            "logic_version": candidate.get("logic_version"),
        }
        row.update(candidate.get("factor_scores", {}))
        row.update(candidate.get("raw_factors", {}))
        rows.append(row)
    df = pd.DataFrame(rows)
    for column in CSV_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[CSV_COLUMNS]


def load_latest_selection_review_report(report_dir: Path | str = "reports") -> dict[str, Any] | None:
    """Load a compact summary from the latest selection review JSON report."""
    directory = Path(report_dir)
    if not directory.exists():
        return None
    candidates = list(directory.glob("selection_review_*.json"))
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("selection_summary", {})
    return {
        "path": str(path),
        "generated_at": payload.get("metadata", {}).get("generated_at"),
        "data_source": payload.get("data_source"),
        "candidate_count": summary.get("exported_candidate_count", len(payload.get("candidates", []))),
        "latest_price_date": summary.get("latest_price_date"),
        "fallback_to_sample": summary.get("fallback_to_sample"),
    }


def build_console_summary(report: dict[str, Any], files: dict[str, str]) -> str:
    """Return a concise console summary for selection review export."""
    summary = report["selection_summary"]
    return "\n".join(
        [
            "候选股票复核导出摘要",
            f"- 数据来源: {report['data_source']}",
            f"- 是否使用真实数据: {'是' if summary.get('is_real_data') else '否'}",
            f"- 是否回退 sample: {'是' if summary.get('fallback_to_sample') else '否'}",
            f"- 最新行情日期: {summary.get('latest_price_date') or '暂无'}",
            f"- 导出候选股票数量: {summary.get('exported_candidate_count', 0)}",
            f"- 生成文件: {', '.join(files.values())}",
        ]
    )


def _prepare_selection(selection_df: pd.DataFrame, factor_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if selection_df.empty:
        return pd.DataFrame()
    selected = selection_df.copy().head(max(top_n, 0))
    if not factor_df.empty and {"ts_code", "trade_date"}.issubset(factor_df.columns):
        raw_cols = ["ts_code", "trade_date", *RAW_FACTOR_COLUMNS]
        raw = factor_df[[column for column in raw_cols if column in factor_df.columns]].copy()
        selected = selected.merge(raw, on=["ts_code", "trade_date"], how="left")
    return selected


def _candidate_record(
    row: dict[str, Any],
    price_df: pd.DataFrame,
    daily_basic_df: pd.DataFrame,
    data_quality_notes: list[str],
) -> dict[str, Any]:
    ts_code = str(row.get("ts_code", ""))
    latest_trade_date = str(row.get("trade_date", "") or "")
    latest_price = _latest_price_row(price_df, ts_code, latest_trade_date)
    latest_basic = _latest_basic_row(daily_basic_df, ts_code, latest_trade_date)
    missing = {
        "pe": _is_missing(latest_basic.get("pe")),
        "pb": _is_missing(latest_basic.get("pb")),
        "industry": _is_missing(row.get("industry")),
        "market": _is_missing(row.get("market")),
        "list_date": _is_missing(row.get("list_date")),
    }
    factor_scores = {column: _optional_float(row.get(column)) for column in SCORE_COLUMNS}
    raw_factors = {column: _optional_float(row.get(column)) for column in RAW_FACTOR_COLUMNS}
    data_quality_note = _candidate_quality_note(missing, data_quality_notes, factor_scores)
    explanation_input = {
        **row,
        "pe": latest_basic.get("pe"),
        "pb": latest_basic.get("pb"),
    }
    explanation = explain_candidate(explanation_input)
    return {
        "ts_code": ts_code,
        "name": row.get("name"),
        "industry": row.get("industry"),
        "market": row.get("market"),
        "list_date": row.get("list_date"),
        "rank": _optional_int(row.get("rank")),
        "latest_trade_date": latest_trade_date,
        "latest_close": _optional_float(latest_price.get("close")),
        "pe": _optional_float(latest_basic.get("pe")),
        "pb": _optional_float(latest_basic.get("pb")),
        "total_score": _optional_float(row.get("total_score")),
        "factor_scores": factor_scores,
        "raw_factors": raw_factors,
        "missing_fields": missing,
        "selection_reason": _selection_reason(row, missing),
        "factor_contributions": explanation.factor_contributions,
        "top_reasons": explanation.top_reasons,
        "weak_points": explanation.weak_points,
        "logic_version": explanation.logic_version,
        "formula_summary": explanation.formula_summary,
        "selection_logic": explanation_to_dict(explanation),
        "elder_score": _optional_float(row.get("elder_score")),
        "action_hint": row.get("action_hint"),
        "elder_reason": row.get("elder_reason"),
        "weekly_trend": row.get("weekly_trend"),
        "daily_pullback": row.get("daily_pullback"),
        "force_signal": row.get("force_signal"),
        "elder_ray_signal": row.get("elder_ray_signal"),
        "review_action": row.get("review_action"),
        "review_checklist": REVIEW_CHECKLIST,
        "data_quality_note": data_quality_note,
        "select_reason": row.get("select_reason"),
        "risk_note": row.get("risk_note"),
    }


def _selection_reason(row: dict[str, Any], missing: dict[str, bool]) -> str:
    reasons: list[str] = []
    score_labels = [
        ("trend_score", "趋势分较高"),
        ("momentum_score", "动量分较高"),
        ("liquidity_score", "近 20 日成交额满足流动性要求"),
        ("volatility_score", "波动率分较高"),
    ]
    for column, label in score_labels:
        value = _optional_float(row.get(column))
        if value is not None and value >= 70:
            reasons.append(label)
    if missing.get("pe") or missing.get("pb"):
        reasons.append("基本面数据缺失，需人工补充核查")
        reasons.append("AKShare fallback 下 pe/pb 为空，基本面分项可信度有限")
    if not reasons:
        score = _optional_float(row.get("total_score"))
        if score is not None:
            reasons.append(f"综合评分排序靠前，综合分 {score:.2f}")
        else:
            reasons.append("候选结果来自当前选股流程，需人工复核")
    return "；".join(dict.fromkeys(reasons))


def _candidate_quality_note(
    missing: dict[str, bool],
    notes: list[str],
    factor_scores: dict[str, float | None],
) -> str:
    valuation_missing = bool(missing.get("pe") or missing.get("pb"))
    fundamental_missing = _is_missing(factor_scores.get("fundamental_score"))
    values = [
        note
        for note in notes
        if _keep_global_quality_note(note, valuation_missing, fundamental_missing)
    ]
    if missing.get("pe") or missing.get("pb"):
        values.append("pe/pb 缺失，估值相关结论需人工补充核查。")
    if missing.get("industry"):
        values.append("industry 缺失，行业复核需人工补充。")
    if missing.get("market"):
        values.append("market 缺失，交易市场需人工补充。")
    if missing.get("list_date"):
        values.append("list_date 缺失，上市时长需结合行情历史判断。")
    return "；".join(dict.fromkeys(str(value) for value in values if value))


def _keep_global_quality_note(note: Any, valuation_missing: bool, fundamental_missing: bool) -> bool:
    """Keep global notes only when they still apply to the current candidate."""
    text = str(note or "").strip()
    if not text:
        return False
    valuation_phrases = [
        "pe 全部缺失",
        "pb 全部缺失",
        "部分股票 pe 缺失",
        "部分股票 pb 缺失",
        "pe/pb 可能为空",
        "pe/pb 缺失",
        "估值相关复核信息不完整",
    ]
    fundamental_phrases = [
        "fundamental_score 可能为空",
        "fundamental_score 为空原因",
        "基本面分项可能偏低或为空",
        "pe_score 与 fundamental_score 可能为空",
    ]
    if not valuation_missing and any(phrase in text for phrase in valuation_phrases):
        return False
    if not fundamental_missing and any(phrase in text for phrase in fundamental_phrases):
        return False
    return True


def _candidate_markdown(candidate: dict[str, Any]) -> list[str]:
    scores = candidate["factor_scores"]
    raw = candidate["raw_factors"]
    missing = candidate["missing_fields"]
    return [
        f"### {candidate.get('rank')}. {candidate.get('ts_code')} {candidate.get('name')}",
        "",
        f"- latest_trade_date: {candidate.get('latest_trade_date') or '暂无'}",
        f"- industry: {candidate.get('industry') or '缺失'}",
        f"- market: {candidate.get('market') or '缺失'}",
        f"- list_date: {candidate.get('list_date') or '缺失'}",
        f"- latest_close: {_display(candidate.get('latest_close'))}",
        f"- pe: {_display(candidate.get('pe'))}",
        f"- pb: {_display(candidate.get('pb'))}",
        f"- total_score: {_display(candidate.get('total_score'))}",
        f"- elder_score: {_display(candidate.get('elder_score'))}",
        f"- 埃尔德操作建议: {candidate.get('review_action') or '暂无'}",
        f"- 埃尔德状态: {candidate.get('action_hint') or '暂无'}",
        f"- 埃尔德原因: {candidate.get('elder_reason') or '暂无'}",
        f"- 周线趋势: {candidate.get('weekly_trend') or '暂无'}",
        f"- 日线回调: {candidate.get('daily_pullback') or '暂无'}",
        f"- Force Index: {candidate.get('force_signal') or '暂无'}",
        f"- Elder Ray: {candidate.get('elder_ray_signal') or '暂无'}",
        f"- trend_score: {_display(scores.get('trend_score'))}",
        f"- momentum_score: {_display(scores.get('momentum_score'))}",
        f"- liquidity_score: {_display(scores.get('liquidity_score'))}",
        f"- volatility_score: {_display(scores.get('volatility_score'))}",
        f"- fundamental_score: {_display(scores.get('fundamental_score'))}",
        f"- return_20d: {_display(raw.get('return_20d'))}",
        f"- avg_amount_20d: {_display(raw.get('avg_amount_20d'))}",
        f"- avg_turnover_20d: {_display(raw.get('avg_turnover_20d'))}",
        f"- volatility_20d: {_display(raw.get('volatility_20d'))}",
        f"- pe_score: {_display(raw.get('pe_score'))}",
        f"- pe 是否缺失: {'是' if missing.get('pe') else '否'}",
        f"- pb 是否缺失: {'是' if missing.get('pb') else '否'}",
        f"- 数据质量提示: {candidate.get('data_quality_note') or '暂无'}",
        f"- 入选原因摘要: {candidate.get('selection_reason')}",
        f"- 当前选股逻辑版本: {candidate.get('logic_version')}",
        f"- 综合评分公式: `{candidate.get('formula_summary')}`",
        f"- 主要贡献因子: {'；'.join(candidate.get('top_reasons', [])) or '暂无'}",
        f"- 弱项 / 复核要点: {'；'.join(candidate.get('weak_points', [])) or '暂无明显低分项'}",
        "",
        "因子加权贡献：",
        *[
            f"- {column}: {_display(value)}"
            for column, value in candidate.get("factor_contributions", {}).items()
        ],
        "",
        "人工复核要点：",
        *[f"- {item}" for item in candidate["review_checklist"]],
        "",
    ]


def _markdown_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": candidate.get("rank", ""),
        "ts_code": candidate.get("ts_code", ""),
        "name": candidate.get("name", ""),
        "total_score": _display(candidate.get("total_score")),
        "latest_close": _display(candidate.get("latest_close")),
        "selection_reason": str(candidate.get("selection_reason", "")).replace("|", "/"),
    }


def _latest_price_row(price_df: pd.DataFrame, ts_code: str, trade_date: str) -> dict[str, Any]:
    if price_df.empty or not {"ts_code", "trade_date"}.issubset(price_df.columns):
        return {}
    rows = price_df[price_df["ts_code"].astype(str) == ts_code].copy()
    if trade_date:
        rows = rows[rows["trade_date"].astype(str) <= trade_date]
    if rows.empty:
        return {}
    rows = rows.sort_values("trade_date")
    return rows.iloc[-1].to_dict()


def _latest_basic_row(daily_basic_df: pd.DataFrame, ts_code: str, trade_date: str) -> dict[str, Any]:
    if daily_basic_df.empty or not {"ts_code", "trade_date"}.issubset(daily_basic_df.columns):
        return {}
    rows = daily_basic_df[daily_basic_df["ts_code"].astype(str) == ts_code].copy()
    if trade_date:
        rows = rows[rows["trade_date"].astype(str) <= trade_date]
    if rows.empty:
        return {}
    rows = rows.sort_values("trade_date")
    return rows.iloc[-1].to_dict()


def _jsonable(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, pd.Series):
        return value.to_list()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
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
    if _is_missing(value):
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    return int(value)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"", "nan", "none", "<na>", "null"}


def _display(value: Any) -> str:
    if value is None:
        return "暂无"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
