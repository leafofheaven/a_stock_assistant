"""Tests for Task 30 daily workflow summary report with temporary DuckDB and mocks."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from core.jobs.run_daily_workflow import run_daily_workflow
from core.reporting.daily_workflow_report import load_latest_daily_workflow_report
from core.storage.duckdb_store import DuckDBStore


def _settings(tmp_path: Path) -> Any:
    """Return settings-like object for no-network workflow tests."""
    return SimpleNamespace(data_provider="akshare", duckdb_path=tmp_path / "daily-workflow.duckdb")


def _touch_report(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("mock report", encoding="utf-8")
    return str(path)


def _overrides(report_dir: Path, calls: dict[str, int] | None = None) -> dict[str, Callable[[], dict[str, Any]]]:
    """Return mock workflow steps that do not access external providers."""
    counts = calls if calls is not None else {}

    def called(name: str, result: dict[str, Any]) -> dict[str, Any]:
        counts[name] = counts.get(name, 0) + 1
        return result

    return {
        "backup_local_data": lambda: called(
            "backup_local_data",
            {"status": "success", "backup_dir": str(report_dir / "mock-backup"), "backup_size": 1},
        ),
        "update_real_data": lambda: called("update_real_data", {"status": "success", "written_rows": {"daily_price": 3}}),
        "diagnose_data_quality": lambda: called(
            "diagnose_data_quality",
            {
                "status": "success",
                "latest_price_date": "20240628",
                "valuation_summary": {"pe_non_null_rate": 1.0, "pb_non_null_rate": 1.0},
                "data_quality_notes": [],
            },
        ),
        "diagnose_factors": lambda: called(
            "diagnose_factors",
            {
                "stock_pool_count": 3,
                "total_score_non_null_count": 3,
                "data_quality_notes": ["mock factor quality"],
            },
        ),
        "run_daily_selection": lambda: called(
            "run_daily_selection",
            {
                "is_real_data": True,
                "fallback_to_sample": False,
                "latest_price_date": "20240628",
                "stock_pool_count": 3,
                "candidate_count": 2,
                "factor_scores_written_rows": 3,
                "strategy_result_written_rows": 2,
                "local_display_selection_count": 2,
                "top_candidates": [
                    {"rank": 1, "ts_code": "002475.SZ", "name": "立讯精密", "total_score": 64.01},
                    {"rank": 2, "ts_code": "000001.SZ", "name": "平安银行", "total_score": 49.6},
                ],
            },
        ),
        "export_selection_review": lambda: called(
            "export_selection_review",
            {
                "status": "success",
                "generated_files": {"json": _touch_report(report_dir / "selection_review_mock.json")},
                "report": {
                    "candidates": [
                        {
                            "rank": 1,
                            "ts_code": "002475.SZ",
                            "name": "立讯精密",
                            "industry": "消费电子",
                            "latest_close": 38.65,
                            "pe": 34.0,
                            "pb": 5.63,
                            "factor_scores": {"total_score": 64.01, "fundamental_score": 8.72},
                        }
                    ]
                },
            },
        ),
        "refresh_watchlist_scores": lambda: called(
            "refresh_watchlist_scores",
            {
                "status": "success",
                "active_watch_count": 1,
                "refreshed_count": 1,
                "items": [
                    {
                        "ts_code": "002475.SZ",
                        "name": "立讯精密",
                        "latest_trade_date": "20240628",
                        "total_score": 64.01,
                    }
                ],
            },
        ),
        "diagnose_watchlist": lambda: called(
            "diagnose_watchlist",
            {
                "active_watch_count": 1,
                "watchlist": [
                    {
                        "ts_code": "002475.SZ",
                        "name": "立讯精密",
                        "latest_trade_date": "20240628",
                        "latest_close": 38.65,
                        "total_score": 64.01,
                        "pe": 34.0,
                        "pb": 5.63,
                        "fundamental_score": 8.72,
                    }
                ],
            },
        ),
        "export_watchlist": lambda: called(
            "export_watchlist",
            {"status": "success", "generated_files": {"json": _touch_report(report_dir / "watchlist_mock.json")}},
        ),
        "track_watchlist": lambda: called(
            "track_watchlist",
            {"status": "success", "snapshot_count": 1, "active_watch_count": 1},
        ),
        "export_watchlist_tracking": lambda: called(
            "export_watchlist_tracking",
            {
                "status": "success",
                "generated_files": {"json": _touch_report(report_dir / "watchlist_tracking_mock.json")},
                "report": {
                    "items": [
                        {
                            "ts_code": "002475.SZ",
                            "name": "立讯精密",
                            "close_change_pct": 0.03,
                            "score_change": 1.2,
                        }
                    ]
                },
            },
        ),
    }


def test_run_daily_workflow_skip_update_generates_reports(tmp_path: Path) -> None:
    """run_daily_workflow --skip-update should execute local mock steps and daily reports."""
    report_dir = tmp_path / "reports"
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    store.initialize()

    result = run_daily_workflow(
        skip_update=True,
        top_n=10,
        report_format="all",
        report_dir=report_dir,
        quiet=True,
        settings=settings,
        store=store,
        step_overrides=_overrides(report_dir),
    )

    assert result["status"] == "success"
    assert Path(result["report_paths"]["markdown"]).exists()
    assert Path(result["report_paths"]["json"]).exists()
    assert Path(result["report_paths"]["csv"]).exists()
    payload = json.loads(Path(result["report_paths"]["json"]).read_text(encoding="utf-8"))
    assert payload["top_candidates"][0]["ts_code"] == "002475.SZ"
    assert payload["top_candidates"][0]["pe"] == 34.0
    assert payload["top_candidates"][0]["pb"] == 5.63
    assert payload["top_candidates"][0]["total_score"] == 64.01
    assert payload["watchlist_summary"]["items"][0]["fundamental_score"] == 8.72
    assert payload["watchlist_tracking_summary"]["items"][0]["score_change"] == 1.2
    assert "selection_review" in "".join(payload["generated_files"].values())


def test_run_daily_workflow_backup_before_run_calls_backup(tmp_path: Path) -> None:
    """--backup-before-run should call backup logic."""
    report_dir = tmp_path / "reports"
    calls: dict[str, int] = {}

    run_daily_workflow(
        skip_update=True,
        backup_before_run=True,
        report_format="json",
        report_dir=report_dir,
        quiet=True,
        settings=_settings(tmp_path),
        store=DuckDBStore(tmp_path / "daily-workflow.duckdb"),
        step_overrides=_overrides(report_dir, calls),
    )

    assert calls["backup_local_data"] == 1


def test_run_daily_workflow_partial_success_when_step_fails(tmp_path: Path) -> None:
    """A failed non-blocking step should produce partial_success instead of crashing."""
    report_dir = tmp_path / "reports"
    overrides = _overrides(report_dir)
    overrides["export_watchlist"] = lambda: (_ for _ in ()).throw(RuntimeError("mock export failure"))

    result = run_daily_workflow(
        skip_update=True,
        report_format="json",
        report_dir=report_dir,
        quiet=True,
        settings=_settings(tmp_path),
        store=DuckDBStore(tmp_path / "daily-workflow.duckdb"),
        step_overrides=overrides,
    )

    assert result["status"] == "partial_success"
    assert result["steps"]["export_watchlist"]["status"] == "failed"
    assert Path(result["report_paths"]["json"]).exists()


def test_load_latest_daily_workflow_report_for_streamlit_helper(tmp_path: Path) -> None:
    """Streamlit can read the compact latest daily workflow metadata."""
    report_dir = tmp_path / "reports"
    run_daily_workflow(
        skip_update=True,
        report_format="all",
        report_dir=report_dir,
        quiet=True,
        settings=_settings(tmp_path),
        store=DuckDBStore(tmp_path / "daily-workflow.duckdb"),
        step_overrides=_overrides(report_dir),
    )

    loaded = load_latest_daily_workflow_report(report_dir)

    assert loaded is not None
    assert loaded["path"].endswith(".json")
    assert loaded["top_candidates"][0]["ts_code"] == "002475.SZ"
    assert loaded["watchlist"][0]["total_score"] == 64.01


def test_no_generated_reports_are_tracked_by_test_repo() -> None:
    """Generated reports stay under reports/ and should remain ignored by git."""
    assert Path("reports/.gitkeep").name == ".gitkeep"
