"""Tests for real workflow reporting with mock steps and temporary duckdb paths."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.jobs.run_real_workflow import run_real_workflow
from core.reporting.workflow_report import load_latest_workflow_report
from web.streamlit_app import _workflow_status_message


def _settings(tmp_path: Path) -> Any:
    """Return settings-like object for workflow tests."""
    return SimpleNamespace(
        data_provider="akshare",
        duckdb_path=tmp_path / "temporary.duckdb",
        akshare_sample_symbols="000001,600000,000002",
        real_data_sample_symbols="000001.SZ,600000.SH,000002.SZ",
        real_universe_preset="mini",
        akshare_symbols=["000001", "600000", "000002"],
        sample_symbols=["000001.SZ", "600000.SH", "000002.SZ"],
    )


def _mock_steps() -> dict[str, Any]:
    """Return successful mock workflow steps."""
    return {
        "diagnose_real_data": lambda: {
            "is_ready_for_selection": True,
            "latest_price_date": "20240628",
            "table_rows": {
                "stock_basic": 3,
                "trade_calendar": 117,
                "daily_price": 351,
                "daily_basic": 351,
                "adj_factor": 3,
            },
            "reasons": [],
        },
        "diagnose_update_batch": lambda: {
            "configured_symbol_count": 3,
            "priced_symbol_count": 3,
            "coverage_rate": 1.0,
            "missing_symbols": [],
        },
        "diagnose_factors": lambda: {
            "stock_pool_count": 3,
            "factor_calculable_count": 3,
            "total_score_non_null_count": 3,
            "factor_quality": {"total_score": {"non_null_rate": 1.0, "nan_count": 0}},
            "data_quality_notes": ["AKShare fallback 的 pe/pb 可能为空。"],
            "reasons": [],
        },
        "run_daily_selection": lambda: {
            "candidate_count": 3,
            "is_real_data": True,
            "fallback_to_sample": False,
            "latest_price_date": "20240628",
            "top_candidates": [{"rank": 1, "ts_code": "000001.SZ", "name": "平安银行", "total_score": 88.0}],
            "result_location": "mock real data selection",
        },
        "diagnose_backtest": lambda: {
            "portfolio_built": True,
            "equity_curve_rows": 20,
            "start_date": "20240401",
            "end_date": "20240628",
            "stock_count": 3,
            "metrics": {
                "annual_return": 0.1,
                "max_drawdown": -0.05,
                "sharpe_ratio": 1.2,
                "win_rate": 0.55,
                "turnover": 0.3,
            },
            "reasons": [],
        },
    }


def test_run_real_workflow_skip_update_generates_markdown_report(tmp_path: Path) -> None:
    """run_real_workflow --skip-update should generate a markdown report."""
    result = run_real_workflow(
        skip_update=True,
        report_dir=tmp_path / "reports",
        report_format="markdown",
        quiet=True,
        settings=_settings(tmp_path),
        step_overrides=_mock_steps(),
    )

    report_path = Path(result["report_path"])
    content = report_path.read_text(encoding="utf-8")

    assert result["status"] == "success"
    assert report_path.suffix == ".md"
    assert "真实运行工作流报告" in content
    assert "update_real_data 摘要" in content
    assert "diagnose_factors 摘要" in content
    assert "不构成投资建议" in content
    assert report_path.with_suffix(".json").exists()


def test_run_real_workflow_json_report_has_structured_fields(tmp_path: Path) -> None:
    """JSON report should contain structured summaries for later dashboard use."""
    result = run_real_workflow(
        skip_update=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=_settings(tmp_path),
        step_overrides=_mock_steps(),
    )

    payload = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))

    assert payload["overall_status"] == "success"
    assert payload["summaries"]["run_daily_selection"]["candidate_count"] == 3
    assert payload["summaries"]["diagnose_update_batch"]["coverage_rate"] == 1.0
    assert payload["risk_notes"]


def test_failed_step_still_generates_report(tmp_path: Path) -> None:
    """A failed step should not prevent final report generation."""
    steps = _mock_steps()

    def fail_factors() -> dict[str, Any]:
        raise RuntimeError("mock factor failure")

    steps["diagnose_factors"] = fail_factors

    result = run_real_workflow(
        skip_update=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=_settings(tmp_path),
        step_overrides=steps,
    )
    payload = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))

    assert result["status"] == "failed"
    assert payload["steps"]["diagnose_factors"]["status"] == "failed"
    assert Path(result["report_path"]).exists()


def test_partial_success_can_continue_to_later_diagnostics(tmp_path: Path) -> None:
    """partial_success status should allow later diagnostics to run."""
    steps = _mock_steps()
    steps["diagnose_update_batch"] = lambda: {
        "configured_symbol_count": 3,
        "priced_symbol_count": 2,
        "coverage_rate": 2 / 3,
        "missing_symbols": ["600000.SH"],
    }

    result = run_real_workflow(
        skip_update=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=_settings(tmp_path),
        step_overrides=steps,
    )

    assert result["status"] == "partial_success"
    assert result["steps"]["run_daily_selection"]["status"] == "success"


def test_no_backtest_skips_backtest_step(tmp_path: Path) -> None:
    """--no-backtest should not run diagnose_backtest."""
    result = run_real_workflow(
        skip_update=True,
        no_backtest=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=_settings(tmp_path),
        step_overrides=_mock_steps(),
    )

    assert result["steps"]["diagnose_backtest"]["status"] == "skipped"


def test_streamlit_helper_reads_latest_workflow_report(tmp_path: Path) -> None:
    """Streamlit helper should read the latest workflow report for status display."""
    result = run_real_workflow(
        skip_update=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=_settings(tmp_path),
        step_overrides=_mock_steps(),
    )

    loaded = load_latest_workflow_report(tmp_path / "reports")
    message = _workflow_status_message(loaded)

    assert loaded is not None
    assert loaded["path"] == result["report_path"]
    assert loaded["candidate_count"] == 3
    assert "最近 workflow 报告状态" in message


def test_streamlit_helper_reads_markdown_sidecar_report(tmp_path: Path) -> None:
    """Markdown reports should have a JSON sidecar for dashboard summaries."""
    run_real_workflow(
        skip_update=True,
        report_dir=tmp_path / "reports",
        report_format="markdown",
        quiet=True,
        settings=_settings(tmp_path),
        step_overrides=_mock_steps(),
    )

    loaded = load_latest_workflow_report(tmp_path / "reports")

    assert loaded is not None
    assert loaded["overall_status"] == "success"
    assert loaded["candidate_count"] == 3
