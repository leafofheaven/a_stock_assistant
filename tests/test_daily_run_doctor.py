"""Tests for Task 32 daily run doctor with temporary DuckDB and workflow integration."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pandas as pd

from core.jobs.doctor_daily_run import doctor_daily_run
from core.jobs.run_daily_workflow import run_daily_workflow
from core.storage.duckdb_store import DuckDBStore


def _settings(tmp_path: Path) -> Any:
    return SimpleNamespace(
        data_provider="akshare",
        data_dir=tmp_path / "data",
        duckdb_path=tmp_path / "data" / "doctor.duckdb",
        akshare_sample_symbols="000001,600000,000002",
        real_universe_preset="mini",
        enable_real_basic_enrichment=True,
        enable_real_valuation_enrichment=True,
        sample_symbols=["000001.SZ", "600000.SH", "000002.SZ"],
        akshare_symbols=["000001", "600000", "000002"],
    )


def _initialized_store(settings: Any) -> DuckDBStore:
    store = DuckDBStore(settings.duckdb_path)
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "industry": "银行", "market": "主板", "list_date": "19910403"},
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20240628", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "amount": 100000000.0},
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_basic",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20240628", "turnover_rate": 1.2, "pe": 5.6, "pb": 0.7, "total_mv": 100.0, "circ_mv": 90.0},
            ]
        ),
    )
    return store


def test_doctor_daily_run_checks_env_and_missing_duckdb(tmp_path: Path) -> None:
    """doctor_daily_run should report missing .env and DuckDB with clear actions."""
    settings = _settings(tmp_path)
    result = doctor_daily_run(settings=settings, store=DuckDBStore(settings.duckdb_path), root=tmp_path)

    assert result["status"] == "failed"
    checks = {item["name"]: item for item in result["checks"]}
    assert checks[".env"]["status"] == "WARNING"
    assert checks["duckdb_path"]["status"] == "FAILED"
    assert "update_real_data" in checks["duckdb_path"]["recommendation"]


def test_doctor_daily_run_warns_and_fix_safe_restores_gitkeep(tmp_path: Path) -> None:
    """--fix-safe should recreate reports/.gitkeep without deleting DuckDB."""
    settings = _settings(tmp_path)
    store = _initialized_store(settings)
    db_path = Path(settings.duckdb_path)
    before_size = db_path.stat().st_size

    warning = doctor_daily_run(settings=settings, store=store, root=tmp_path)
    assert {item["name"]: item for item in warning["checks"]}["reports_gitkeep"]["status"] == "WARNING"

    fixed = doctor_daily_run(fix_safe=True, settings=settings, store=store, root=tmp_path)

    assert (tmp_path / "reports" / ".gitkeep").exists()
    assert db_path.exists()
    assert db_path.stat().st_size == before_size
    assert any("reports/.gitkeep" in item for item in fixed["fixes"])


def test_doctor_daily_run_detects_tracked_local_path_risk(tmp_path: Path, monkeypatch: Any) -> None:
    """Tracked reports/data/backups/.env risks should be reported."""
    from core.jobs import doctor_daily_run as doctor_module

    settings = _settings(tmp_path)
    store = _initialized_store(settings)
    (tmp_path / ".env").write_text("DATA_PROVIDER=akshare\n", encoding="utf-8")
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "reports" / ".gitkeep").write_text("", encoding="utf-8")
    monkeypatch.setattr(doctor_module, "_tracked_local_data_paths", lambda root: ["reports/.gitkeep", "data/doctor.duckdb"])

    result = doctor_module.doctor_daily_run(settings=settings, store=store, root=tmp_path)

    tracked = {item["name"]: item for item in result["checks"]}["tracked_local_paths"]
    assert tracked["status"] == "FAILED"
    assert "data/doctor.duckdb" in tracked["message"]


def test_doctor_daily_run_reports_latest_files_and_pe_pb_rates(tmp_path: Path) -> None:
    """doctor_daily_run should find latest reports and latest-date PE/PB completeness."""
    settings = _settings(tmp_path)
    store = _initialized_store(settings)
    (tmp_path / ".env").write_text("DATA_PROVIDER=akshare\n", encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / ".gitkeep").write_text("", encoding="utf-8")
    (reports / "daily_workflow_20240628_120000.json").write_text("{}", encoding="utf-8")
    (reports / "selection_review_20240628_120000.json").write_text("{}", encoding="utf-8")
    (reports / "watchlist_20240628_120000.json").write_text("{}", encoding="utf-8")

    result = doctor_daily_run(settings=settings, store=store, root=tmp_path)
    checks = {item["name"]: item for item in result["checks"]}

    assert checks["latest_daily_workflow_report"]["status"] == "OK"
    assert "20240628" in checks["latest_selection_review_report"]["message"]
    assert checks["latest_pe_pb"]["status"] == "OK"
    assert "100.00%" in checks["latest_pe_pb"]["message"]


def test_run_daily_workflow_doctor_before_run_records_summary(tmp_path: Path) -> None:
    """run_daily_workflow --doctor-before-run should include doctor summary in reports."""
    report_dir = tmp_path / "reports"
    settings = _settings(tmp_path)
    store = _initialized_store(settings)
    overrides = _workflow_overrides(report_dir)
    overrides["doctor_before_run"] = lambda: {
        "status": "warning",
        "summary": {"ok": 10, "warning": 1, "failed": 0},
        "next_steps": ["python -m core.jobs.doctor_daily_run --fix-safe"],
    }

    result = run_daily_workflow(
        skip_update=True,
        doctor_before_run=True,
        report_format="json",
        report_dir=report_dir,
        watchlist_tracking=False,
        quiet=True,
        settings=settings,
        store=store,
        step_overrides=overrides,
    )

    assert result["status"] == "partial_success"
    assert result["report"]["doctor_summary"]["overall_status"] == "warning"
    payload = json.loads(Path(result["report_paths"]["json"]).read_text(encoding="utf-8"))
    assert payload["doctor_summary"]["doctor_before_run"]["summary"]["warning"] == 1


def _workflow_overrides(report_dir: Path) -> dict[str, Callable[[], dict[str, Any]]]:
    def touch(name: str) -> str:
        path = report_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        return str(path)

    return {
        "diagnose_data_quality": lambda: {
            "status": "success",
            "latest_trade_date": "20240628",
            "valuation_summary": {"pe_non_null_rate": 1.0, "pb_non_null_rate": 1.0},
            "latest_date_pe_non_null_rate": 1.0,
            "latest_date_pb_non_null_rate": 1.0,
            "data_quality_notes": [],
        },
        "diagnose_factors": lambda: {"status": "success", "stock_pool_count": 1, "total_score_non_null_count": 1},
        "run_daily_selection": lambda: {
            "status": "success",
            "is_real_data": True,
            "fallback_to_sample": False,
            "candidate_count": 1,
            "top_candidates": [{"rank": 1, "ts_code": "000001.SZ", "name": "平安银行", "total_score": 80.0}],
        },
        "export_selection_review": lambda: {
            "status": "success",
            "generated_files": {"json": touch("selection_review_mock.json")},
            "report": {"candidates": [{"rank": 1, "ts_code": "000001.SZ", "name": "平安银行", "pe": 5.6, "pb": 0.7}]},
        },
        "refresh_watchlist_scores": lambda: {"status": "success", "active_watch_count": 0, "items": []},
        "diagnose_watchlist": lambda: {"status": "success", "active_watch_count": 0, "watchlist": []},
        "export_watchlist": lambda: {"status": "success", "generated_files": {"json": touch("watchlist_mock.json")}},
    }
