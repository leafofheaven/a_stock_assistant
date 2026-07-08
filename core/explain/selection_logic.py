"""Explain the current stock selection logic without changing strategy output."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

import pandas as pd

from core.factors.scoring import DEFAULT_WEIGHTS

LOGIC_VERSION = "selection-logic-v1"

FACTOR_LABELS: dict[str, str] = {
    "trend_score": "趋势",
    "momentum_score": "动量",
    "liquidity_score": "流动性",
    "fundamental_score": "基本面",
    "volatility_score": "波动风险",
}

FACTOR_DEFINITION_TEXT: dict[str, dict[str, str]] = {
    "trend_score": {
        "meaning": "观察近 20 日 / 60 日涨跌幅、均线位置和均线排列，反映中短期趋势状态。",
        "input_fields": "daily_price.close, trade_date",
        "calculation_hint": "由趋势类基础因子横截面标准化为 0-100 分。",
        "score_direction": "分数越高，当前规则下趋势表现越靠前。",
        "data_quality_notes": "行情交易日不足时，部分趋势因子可能为空。",
    },
    "momentum_score": {
        "meaning": "观察相对强弱和 60 日新高情况，反映价格动量。",
        "input_fields": "daily_price.close, trade_date",
        "calculation_hint": "由动量类基础因子横截面标准化为 0-100 分。",
        "score_direction": "分数越高，当前规则下动量表现越靠前。",
        "data_quality_notes": "样本交易日不足 60 日时，新高相关因子可能为空。",
    },
    "liquidity_score": {
        "meaning": "观察近 20 日成交额和换手率，反映交易活跃度。",
        "input_fields": "daily_price.amount, daily_basic.turnover_rate",
        "calculation_hint": "由流动性类基础因子横截面标准化为 0-100 分。",
        "score_direction": "分数越高，当前规则下流动性越好。",
        "data_quality_notes": "成交额或换手率缺失时，流动性分项可能偏低或为空。",
    },
    "fundamental_score": {
        "meaning": "观察当前已实现的估值字段质量，最小真实评分路径主要来自市盈率倒数指标。",
        "input_fields": "daily_basic.pe；daily_basic.pb 作为估值参考；daily_basic.total_mv / daily_basic.circ_mv 若未来数据源提供，仅作扩展或诊断字段。",
        "calculation_hint": "由基本面类基础因子横截面标准化为 0-100 分。",
        "score_direction": "分数越高，当前规则下基本面 / 估值分项越靠前。",
        "data_quality_notes": "total_mv / circ_mv 在当前免费数据源下可能为空，当前不作为硬性股票池过滤门槛；PE 缺失会影响基本面分项。",
    },
    "volatility_score": {
        "meaning": "观察近 20 日波动率和 60 日最大回撤，反映风险暴露。",
        "input_fields": "daily_price.close",
        "calculation_hint": "波动较低、回撤较小的股票通常获得更高风险分。",
        "score_direction": "分数越高，当前规则下波动风险越低。",
        "data_quality_notes": "行情交易日不足时，波动和回撤因子可能为空。",
    },
}


@dataclass(frozen=True)
class FactorDefinition:
    """Readable definition for one score component."""

    factor_name: str
    display_name: str
    weight: float
    meaning: str
    input_fields: str
    calculation_hint: str
    score_direction: str
    data_quality_notes: str


@dataclass(frozen=True)
class SelectionLogicSummary:
    """Current selection workflow and formula summary."""

    logic_version: str
    formula_summary: str
    weights: dict[str, float]
    workflow_steps: list[str]
    factor_definitions: list[FactorDefinition]
    limitations: list[str]
    source_files: list[str]


@dataclass(frozen=True)
class CandidateExplanation:
    """Candidate-level explanation based on the exported score row."""

    ts_code: str
    name: str | None
    rank: int | None
    total_score: float | None
    factor_scores: dict[str, float | None]
    factor_contributions: dict[str, float]
    top_reasons: list[str]
    weak_points: list[str]
    data_quality_note: str
    logic_version: str
    formula_summary: str


def get_factor_definitions() -> list[FactorDefinition]:
    """Return the factor definitions matching the current scoring columns."""
    definitions: list[FactorDefinition] = []
    for factor_name, weight in DEFAULT_WEIGHTS.items():
        text = FACTOR_DEFINITION_TEXT[factor_name]
        definitions.append(
            FactorDefinition(
                factor_name=factor_name,
                display_name=FACTOR_LABELS[factor_name],
                weight=weight,
                meaning=text["meaning"],
                input_fields=text["input_fields"],
                calculation_hint=text["calculation_hint"],
                score_direction=text["score_direction"],
                data_quality_notes=text["data_quality_notes"],
            )
        )
    return definitions


def get_selection_logic_summary() -> SelectionLogicSummary:
    """Return the current selection workflow, weights, formula, and limitations."""
    return SelectionLogicSummary(
        logic_version=LOGIC_VERSION,
        formula_summary=formula_summary(),
        weights=dict(DEFAULT_WEIGHTS),
        workflow_steps=[
            "读取本地 DuckDB 或 sample 数据，不在解释环节访问外部 API。",
            "构建可交易股票池，排除 ST、停牌、上市交易日不足、流动性不足等样本。",
            "按 ts_code 和 trade_date 计算基础因子，并在同一 trade_date 内横截面标准化为 0-100 分。",
            "使用固定权重计算 total_score，缺失分项在总分计算中按 0 处理。",
            "每个 trade_date 内按 total_score 从高到低排序，输出 Top N 候选股票。",
            "候选结果只用于人工复核、观察池管理和本地研究。",
        ],
        factor_definitions=get_factor_definitions(),
        limitations=[
            "当前解释层不改变评分公式、权重、排序或候选结果。",
            "AKShare fallback 下 adj_factor 可能简化为 1.0，历史 PE/PB 可能不完整。",
            "当前真实数据链路主要用于少量股票本地试运行，不做全市场生产级下载。",
            "评分是候选排序辅助，不代表收益保证，也不会触发自动交易。",
        ],
        source_files=[
            "core/factors/scoring.py",
            "core/strategy/selector.py",
            "core/jobs/diagnose_factors.py",
            "core/jobs/run_daily_selection.py",
            "core/reporting/selection_review_report.py",
            "core/explain/selection_logic.py",
        ],
    )


def formula_summary() -> str:
    """Return the exact total_score formula from current default weights."""
    parts = [f"{column} * {weight:.2f}" for column, weight in DEFAULT_WEIGHTS.items()]
    return "total_score = " + " + ".join(parts)


def factor_contributions(row: Mapping[str, Any]) -> dict[str, float]:
    """Return weighted score contributions for one candidate row."""
    contributions: dict[str, float] = {}
    for column, weight in DEFAULT_WEIGHTS.items():
        value = _optional_float(row.get(column))
        contributions[column] = round((value or 0.0) * weight, 4)
    return contributions


def explain_candidate(row: Mapping[str, Any]) -> CandidateExplanation:
    """Explain one candidate row using current factor weights.

    Missing component scores are shown as weak points. Contribution values use
    the same missing-as-zero convention as ``calculate_total_score``.
    """
    scores = {column: _optional_float(row.get(column)) for column in DEFAULT_WEIGHTS}
    contributions = factor_contributions(row)
    top_reasons = _top_reasons(row, scores, contributions)
    weak_points = _weak_points(row, scores)
    quality_note = _candidate_data_quality_note(row, scores)
    return CandidateExplanation(
        ts_code=str(row.get("ts_code", "") or ""),
        name=_optional_string(row.get("name")),
        rank=_optional_int(row.get("rank")),
        total_score=_optional_float(row.get("total_score")),
        factor_scores=scores,
        factor_contributions=contributions,
        top_reasons=top_reasons,
        weak_points=weak_points,
        data_quality_note=quality_note,
        logic_version=LOGIC_VERSION,
        formula_summary=formula_summary(),
    )


def explain_candidates(candidate_df: pd.DataFrame, top_n: int = 10) -> list[CandidateExplanation]:
    """Explain top candidates without mutating input order or strategy output."""
    if candidate_df.empty:
        return []
    df = candidate_df.copy()
    if "rank" in df.columns:
        df = df.sort_values(["rank", "ts_code"], ascending=[True, True], na_position="last")
    elif "total_score" in df.columns:
        df = df.sort_values(["total_score", "ts_code"], ascending=[False, True], na_position="last")
    return [explain_candidate(row) for row in df.head(max(top_n, 0)).to_dict("records")]


def explanation_to_dict(explanation: CandidateExplanation) -> dict[str, Any]:
    """Convert a candidate explanation dataclass to a JSON-friendly dict."""
    return asdict(explanation)


def explanations_to_dataframe(explanations: list[CandidateExplanation]) -> pd.DataFrame:
    """Return a compact table for UI rendering."""
    return pd.DataFrame(
        [
            {
                "rank": item.rank,
                "ts_code": item.ts_code,
                "name": item.name,
                "total_score": item.total_score,
                "top_reasons": "；".join(item.top_reasons),
                "weak_points": "；".join(item.weak_points),
                **{f"{column}_contribution": value for column, value in item.factor_contributions.items()},
            }
            for item in explanations
        ]
    )


def render_logic_markdown(
    summary: SelectionLogicSummary | None = None,
    explanations: list[CandidateExplanation] | None = None,
) -> str:
    """Render selection logic and optional candidate explanations as Markdown."""
    resolved = summary or get_selection_logic_summary()
    lines = [
        "# 选股逻辑说明",
        "",
        f"- logic_version: {resolved.logic_version}",
        f"- 综合评分公式: `{resolved.formula_summary}`",
        "- 仅供个人研究使用，不自动交易。",
        "",
        "## 因子说明",
        "",
        "| 因子 | 权重 | 说明 | 数据字段 |",
        "| --- | ---: | --- | --- |",
    ]
    for item in resolved.factor_definitions:
        lines.append(
            f"| {item.display_name} `{item.factor_name}` | {item.weight:.2f} | {item.meaning} | {item.input_fields} |"
        )
    lines.extend(["", "## 选股流程", ""])
    lines.extend(f"- {step}" for step in resolved.workflow_steps)
    lines.extend(["", "## 当前限制", ""])
    lines.extend(f"- {item}" for item in resolved.limitations)
    lines.extend(["", "## 相关源码", ""])
    lines.extend(f"- `{path}`" for path in resolved.source_files)
    if explanations:
        lines.extend(["", "## 候选股票排名原因", ""])
        for item in explanations:
            lines.extend(
                [
                    f"### {item.rank or '-'} {item.ts_code} {item.name or ''}".strip(),
                    "",
                    f"- total_score: {_display(item.total_score)}",
                    f"- 主要贡献因子: {'；'.join(item.top_reasons)}",
                    f"- 弱项 / 复核要点: {'；'.join(item.weak_points) if item.weak_points else '暂无明显低分项'}",
                    f"- 数据质量提示: {item.data_quality_note}",
                    "",
                ]
            )
    return "\n".join(lines)


def _top_reasons(
    row: Mapping[str, Any],
    scores: dict[str, float | None],
    contributions: dict[str, float],
) -> list[str]:
    total_score = _optional_float(row.get("total_score"))
    ranked = sorted(contributions.items(), key=lambda item: item[1], reverse=True)
    reasons: list[str] = []
    if total_score is not None:
        reasons.append(f"当前规则下综合评分靠前，综合分 {total_score:.2f}，适合作为人工复核候选")
    for column, contribution in ranked[:2]:
        score = scores.get(column)
        if score is None or contribution <= 0:
            continue
        reasons.append(f"{FACTOR_LABELS[column]}贡献 {contribution:.2f} 分（原始分 {score:.2f}，权重 {DEFAULT_WEIGHTS[column]:.2f}）")
    if len(reasons) == 0:
        reasons.append("候选来自当前排序结果，需结合数据质量人工复核")
    return reasons


def _weak_points(row: Mapping[str, Any], scores: dict[str, float | None]) -> list[str]:
    weak: list[str] = []
    for column, score in scores.items():
        if score is None:
            weak.append(f"{FACTOR_LABELS[column]}分缺失")
        elif score < 40:
            weak.append(f"{FACTOR_LABELS[column]}分偏低（{score:.2f}）")
    pe_missing = _is_missing(row.get("pe"))
    pb_missing = _is_missing(row.get("pb"))
    if pe_missing:
        weak.append("PE 缺失，估值复核需补充")
    if pb_missing:
        weak.append("PB 缺失，估值复核需补充")
    return weak


def _candidate_data_quality_note(row: Mapping[str, Any], scores: dict[str, float | None]) -> str:
    notes: list[str] = []
    if _is_missing(row.get("industry")):
        notes.append("industry 缺失")
    if _is_missing(row.get("list_date")):
        notes.append("list_date 缺失")
    if _is_missing(row.get("pe")):
        notes.append("pe 缺失")
    if _is_missing(row.get("pb")):
        notes.append("pb 缺失")
    if scores.get("fundamental_score") is None:
        notes.append("fundamental_score 缺失，基本面分项贡献按 0 处理")
    if not notes:
        return "当前候选行关键评分字段可用。"
    return "；".join(notes)


def _optional_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    return int(value)


def _optional_string(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return str(value)


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
