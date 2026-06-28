"""Print the current selection logic and optional candidate explanations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.explain.selection_logic import (
    explain_candidates,
    explanation_to_dict,
    get_selection_logic_summary,
    render_logic_markdown,
)
from core.reporting.selection_review_report import load_latest_selection_review_report
from core.sample_data import get_sample_dashboard_data


def explain_selection_logic(
    *,
    output_format: str = "text",
    ts_code: str | None = None,
    candidates: pd.DataFrame | None = None,
    report_dir: Path | str = "reports",
) -> dict[str, Any]:
    """Build a local explanation payload for CLI or tests.

    The command does not fetch external APIs. If no candidate rows are provided,
    it tries to load the latest local selection review report and otherwise
    falls back to sample demo candidates.
    """
    summary = get_selection_logic_summary()
    candidate_df = candidates if candidates is not None else _load_candidate_rows(report_dir)
    if ts_code and not candidate_df.empty and "ts_code" in candidate_df.columns:
        candidate_df = candidate_df[candidate_df["ts_code"].astype(str) == ts_code]
    explanations = explain_candidates(candidate_df, top_n=10)
    payload = {
        "status": "success",
        "logic": {
            "logic_version": summary.logic_version,
            "formula_summary": summary.formula_summary,
            "weights": summary.weights,
            "workflow_steps": summary.workflow_steps,
            "factor_definitions": [item.__dict__ for item in summary.factor_definitions],
            "limitations": summary.limitations,
            "source_files": summary.source_files,
        },
        "candidate_explanations": [explanation_to_dict(item) for item in explanations],
        "output": render_output(output_format, summary, explanations),
    }
    return payload


def render_output(output_format: str, summary: Any, explanations: list[Any]) -> str:
    """Render explanation payload as text, Markdown, or JSON."""
    if output_format == "markdown":
        return render_logic_markdown(summary, explanations)
    if output_format == "json":
        return json.dumps(
            {
                "logic_version": summary.logic_version,
                "formula_summary": summary.formula_summary,
                "weights": summary.weights,
                "candidate_explanations": [explanation_to_dict(item) for item in explanations],
            },
            ensure_ascii=False,
            indent=2,
        )
    lines = [
        "选股逻辑说明",
        f"- logic_version: {summary.logic_version}",
        f"- 综合评分公式: {summary.formula_summary}",
        "- 因子权重:",
    ]
    for factor_name, weight in summary.weights.items():
        lines.append(f"  - {factor_name}: {weight:.2f}")
    if explanations:
        lines.append("- 候选股票排名原因:")
        for item in explanations:
            lines.append(f"  - {item.ts_code} {item.name or ''}: {'；'.join(item.top_reasons)}")
    else:
        lines.append("- 暂无候选股票解释，可先运行 python -m core.jobs.export_selection_review --format all。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Parse CLI args and print the current selection logic explanation."""
    parser = argparse.ArgumentParser(description="Explain current selection logic.")
    parser.add_argument("--format", choices=["text", "markdown", "json"], default="text")
    parser.add_argument("--ts-code", help="Only explain one candidate ts_code.")
    parser.add_argument("--report-dir", default="reports")
    args = parser.parse_args(argv)

    result = explain_selection_logic(
        output_format=args.format,
        ts_code=args.ts_code,
        report_dir=args.report_dir,
    )
    print(result["output"])


def _load_candidate_rows(report_dir: Path | str) -> pd.DataFrame:
    latest = load_latest_selection_review_report(report_dir)
    if latest and latest.get("path"):
        try:
            payload = json.loads(Path(latest["path"]).read_text(encoding="utf-8"))
            candidates = payload.get("candidates", [])
            if candidates:
                rows = []
                for candidate in candidates:
                    row = dict(candidate)
                    row.update(candidate.get("factor_scores", {}))
                    rows.append(row)
                return pd.DataFrame(rows)
        except (OSError, json.JSONDecodeError):
            pass
    return get_sample_dashboard_data()["selection"].copy()


if __name__ == "__main__":
    main()
