"""Tests for selection logic explanations and report integration."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.explain.selection_logic import (
    explain_candidate,
    explain_candidates,
    factor_contributions,
    formula_summary,
    get_factor_definitions,
    get_selection_logic_summary,
)
from core.factors.scoring import DEFAULT_WEIGHTS
from core.reporting.selection_review_report import (
    build_selection_review_report,
    candidates_to_dataframe,
    render_markdown_report,
    save_selection_review_report,
)
from core.strategy.selector import select_top_stocks


def test_factor_definitions_match_current_default_weights() -> None:
    """Definitions should cover all current score columns and weights."""
    definitions = get_factor_definitions()

    assert {item.factor_name for item in definitions} == set(DEFAULT_WEIGHTS)
    assert sum(item.weight for item in definitions) == 1.0
    assert "total_score" in formula_summary()
    for column, weight in DEFAULT_WEIGHTS.items():
        assert f"{column} * {weight:.2f}" in formula_summary()


def test_selection_logic_summary_lists_workflow_and_source_files() -> None:
    """Summary should explain workflow, limitations, and code sources."""
    summary = get_selection_logic_summary()

    assert summary.weights == DEFAULT_WEIGHTS
    assert any("按 total_score" in step for step in summary.workflow_steps)
    assert "core/factors/scoring.py" in summary.source_files
    assert any("不改变评分公式" in item for item in summary.limitations)


def test_candidate_factor_contributions_and_reasons() -> None:
    """Candidate explanation should calculate weighted contributions."""
    row = {
        "rank": 1,
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "trend_score": 100,
        "momentum_score": 80,
        "liquidity_score": 60,
        "fundamental_score": 40,
        "volatility_score": 20,
        "total_score": 67,
        "pe": 8.5,
        "pb": 0.8,
        "industry": "银行",
        "list_date": "19910403",
    }

    contributions = factor_contributions(row)
    explanation = explain_candidate(row)

    assert contributions["trend_score"] == 30.0
    assert contributions["momentum_score"] == 16.0
    assert any("综合评分靠前" in reason for reason in explanation.top_reasons)
    assert "当前候选行关键评分字段可用" in explanation.data_quality_note


def test_missing_candidate_fields_become_weak_points() -> None:
    """Missing valuation or fundamental fields should be explicit."""
    explanation = explain_candidate(
        {
            "ts_code": "000002.SZ",
            "name": "万科A",
            "trend_score": 70,
            "momentum_score": 65,
            "liquidity_score": 80,
            "fundamental_score": None,
            "volatility_score": 75,
            "total_score": 60,
            "pe": None,
            "pb": None,
        }
    )

    assert any("基本面分" in item for item in explanation.weak_points)
    assert "pe 缺失" in explanation.data_quality_note
    assert "fundamental_score 缺失" in explanation.data_quality_note


def test_explainer_does_not_change_selection_order() -> None:
    """Explanations should preserve the selected ranking order."""
    scored = pd.DataFrame(
        {
            "trade_date": ["20240131", "20240131", "20240131"],
            "ts_code": ["000003.SZ", "000001.SZ", "000002.SZ"],
            "name": ["C", "A", "B"],
            "total_score": [70, 90, 80],
            "trend_score": [70, 90, 80],
            "momentum_score": [70, 90, 80],
            "liquidity_score": [70, 90, 80],
            "fundamental_score": [70, 90, 80],
            "volatility_score": [70, 90, 80],
        }
    )

    selected = select_top_stocks(scored, top_n=3)
    explanations = explain_candidates(selected, top_n=3)

    assert selected["ts_code"].tolist() == ["000001.SZ", "000002.SZ", "000003.SZ"]
    assert [item.ts_code for item in explanations] == selected["ts_code"].tolist()


def test_selection_review_report_contains_logic_fields(tmp_path: Path) -> None:
    """Selection review JSON/Markdown/CSV should include explanation fields."""
    selection = pd.DataFrame(
        {
            "trade_date": ["20240131"],
            "rank": [1],
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
            "industry": ["银行"],
            "market": ["深交所"],
            "list_date": ["19910403"],
            "total_score": [88.0],
            "trend_score": [90.0],
            "momentum_score": [80.0],
            "liquidity_score": [85.0],
            "fundamental_score": [70.0],
            "volatility_score": [60.0],
        }
    )
    daily_basic = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240131"], "pe": [8.5], "pb": [0.8]})
    report = build_selection_review_report(
        metadata={"generated_at": "2026-06-28T12:00:00", "data_provider": "akshare", "duckdb_path": "tmp.duckdb"},
        selection_summary={"is_real_data": True, "fallback_to_sample": False, "candidate_count": 1},
        selection_df=selection,
        factor_df=selection,
        price_df=pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240131"], "close": [10.0]}),
        daily_basic_df=daily_basic,
        data_quality_notes=[],
        top_n=1,
    )

    candidate = report["candidates"][0]
    markdown = render_markdown_report(report)
    csv_df = candidates_to_dataframe(report["candidates"])
    files = save_selection_review_report(report, output_dir=tmp_path, report_format="all")

    assert candidate["factor_contributions"]["trend_score"] == 27.0
    assert candidate["top_reasons"]
    assert candidate["logic_version"]
    assert "综合评分公式" in markdown
    assert "主要贡献因子" in markdown
    assert "top_reasons" in csv_df.columns
    assert Path(files["json"]).exists()
