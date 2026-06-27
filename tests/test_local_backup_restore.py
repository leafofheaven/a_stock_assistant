"""Tests for local backup, restore, diagnostics, and cleanup with temporary duckdb mock data."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from core.jobs.backup_local_data import backup_local_data
from core.jobs.clean_generated_reports import clean_generated_reports
from core.jobs.diagnose_local_state import diagnose_local_state
from core.jobs.list_backups import list_backups
from core.jobs.restore_local_data import restore_local_data
from core.jobs.run_real_workflow import run_real_workflow
from core.storage.duckdb_store import DuckDBStore


def _settings(tmp_path: Path, db_name: str = "local.duckdb", token: str = "") -> Any:
    """Return sample settings for no-network tests."""
    return SimpleNamespace(
        data_provider="sample",
        duckdb_path=tmp_path / db_name,
        tushare_token=token,
        akshare_sample_symbols="",
        real_data_sample_symbols="",
        real_universe_preset="mini",
        akshare_symbols=[],
        sample_symbols=[],
        default_top_n=30,
    )


def _seed_stock(db_path: Path, ts_code: str = "000001.SZ", name: str = "mock stock") -> None:
    """Seed temporary duckdb mock stock data."""
    store = DuckDBStore(db_path)
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "symbol": ts_code.split(".")[0],
                    "name": name,
                    "area": "mock",
                    "industry": "mock",
                    "market": "mock",
                    "list_date": "20240101",
                    "delist_date": "",
                    "is_hs": "",
                }
            ]
        ),
    )


def _stock_name(db_path: Path) -> str:
    store = DuckDBStore(db_path)
    df = store.read_table("stock_basic")
    return str(df.iloc[0]["name"])


def test_backup_local_data_generates_backup_directory(tmp_path: Path) -> None:
    """backup_local_data should create a backup directory with metadata and table counts."""
    settings = _settings(tmp_path)
    _seed_stock(settings.duckdb_path)

    result = backup_local_data(backup_dir=tmp_path / "backups", label="mock", settings=settings)

    backup_path = Path(result["backup_dir"])
    assert result["status"] == "success"
    assert (backup_path / "data" / "a_stock_assistant.duckdb").exists()
    assert (backup_path / "metadata.json").exists()
    assert (backup_path / "table_counts.json").exists()
    assert result["table_counts"]["stock_basic"] == 1


def test_backup_metadata_does_not_include_token(tmp_path: Path) -> None:
    """metadata.json should not contain token values."""
    settings = _settings(tmp_path, token="secret-token")
    _seed_stock(settings.duckdb_path)

    result = backup_local_data(backup_dir=tmp_path / "backups", settings=settings)

    metadata_text = (Path(result["backup_dir"]) / "metadata.json").read_text(encoding="utf-8")
    metadata = json.loads(metadata_text)
    assert "secret-token" not in metadata_text
    assert metadata["env_summary"]["tushare_token_configured"] is True
    assert metadata["env_summary"]["tushare_token_value"] is None


def test_list_backups_lists_created_backup(tmp_path: Path) -> None:
    """list_backups should return created backups."""
    settings = _settings(tmp_path)
    _seed_stock(settings.duckdb_path)
    backup_local_data(backup_dir=tmp_path / "backups", label="mock-list", settings=settings)

    result = list_backups(backup_dir=tmp_path / "backups")

    assert result["backup_count"] == 1
    assert result["backups"][0]["label"] == "mock-list"
    assert result["backups"][0]["duckdb_exists"] is True


def test_restore_local_data_dry_run_does_not_overwrite(tmp_path: Path) -> None:
    """restore_local_data dry_run should not overwrite target database."""
    settings = _settings(tmp_path)
    _seed_stock(settings.duckdb_path, name="backup version")
    backup = backup_local_data(backup_dir=tmp_path / "backups", settings=settings)
    _seed_stock(settings.duckdb_path, name="current version")

    result = restore_local_data(
        backup_dir=backup["backup_dir"],
        target_db=settings.duckdb_path,
        dry_run=True,
        force=False,
        settings=settings,
    )

    assert result["status"] == "dry_run"
    assert result["restored"] is False
    assert _stock_name(settings.duckdb_path) == "current version"


def test_restore_local_data_force_restores_and_creates_safety_backup(tmp_path: Path) -> None:
    """restore_local_data --force should restore and create a safety backup."""
    settings = _settings(tmp_path)
    _seed_stock(settings.duckdb_path, name="backup version")
    backup = backup_local_data(backup_dir=tmp_path / "backups", settings=settings)
    _seed_stock(settings.duckdb_path, name="current version")

    result = restore_local_data(
        backup_dir=backup["backup_dir"],
        target_db=settings.duckdb_path,
        dry_run=False,
        force=True,
        settings=settings,
    )

    assert result["status"] == "success"
    assert result["restored"] is True
    assert result["safety_backup_dir"]
    assert Path(result["safety_backup_dir"]).exists()
    assert _stock_name(settings.duckdb_path) == "backup version"


def test_diagnose_local_state_outputs_table_counts(tmp_path: Path) -> None:
    """diagnose_local_state should include core table counts and local file counts."""
    settings = _settings(tmp_path)
    _seed_stock(settings.duckdb_path)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "real_workflow_mock.json").write_text("{}", encoding="utf-8")

    result = diagnose_local_state(report_dir=tmp_path / "reports", backup_dir=tmp_path / "backups", settings=settings)

    assert result["duckdb_exists"] is True
    assert result["table_counts"]["stock_basic"] == 1
    assert result["reports_count"] == 1
    assert "tracked_local_data_paths" in result


def test_clean_generated_reports_dry_run_does_not_delete(tmp_path: Path) -> None:
    """clean_generated_reports dry_run should not delete generated files."""
    reports = tmp_path / "reports"
    reports.mkdir()
    generated = reports / "watchlist_20240101_000000.json"
    custom = reports / "notes.txt"
    generated.write_text("{}", encoding="utf-8")
    custom.write_text("keep", encoding="utf-8")

    result = clean_generated_reports(report_dir=reports, dry_run=True, force=False)

    assert result["candidate_count"] == 1
    assert generated.exists()
    assert custom.exists()


def test_clean_generated_reports_force_deletes_only_generated(tmp_path: Path) -> None:
    """clean_generated_reports --force should delete known generated reports only."""
    reports = tmp_path / "reports"
    reports.mkdir()
    generated = reports / "watchlist_tracking_20240101_000000.csv"
    custom = reports / "manual.csv"
    generated.write_text("generated", encoding="utf-8")
    custom.write_text("keep", encoding="utf-8")

    result = clean_generated_reports(report_dir=reports, dry_run=False, force=True)

    assert result["deleted_count"] == 1
    assert not generated.exists()
    assert custom.exists()


def test_gitignore_contains_local_data_rules() -> None:
    """.gitignore should keep local data, reports, backups, and caches out of git."""
    content = Path(".gitignore").read_text(encoding="utf-8")

    for phrase in [".env", "data/*.duckdb", "reports/*.md", "reports/*.json", "reports/*.csv", "backups/", "**/__pycache__/", ".pytest_cache/"]:
        assert phrase in content


def test_run_real_workflow_backup_before_run(tmp_path: Path) -> None:
    """run_real_workflow --backup-before-run should record backup summary."""
    settings = _settings(tmp_path, db_name="workflow-backup.duckdb")
    _seed_stock(settings.duckdb_path)

    result = run_real_workflow(
        skip_update=True,
        no_backtest=True,
        backup_before_run=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=settings,
        step_overrides={
            "backup_local_data": lambda: backup_local_data(backup_dir=tmp_path / "backups", label="workflow", settings=settings),
            "diagnose_real_data": lambda: {"is_ready_for_selection": True, "latest_price_date": "20240131", "table_rows": {}},
            "diagnose_update_batch": lambda: {"configured_symbol_count": 1, "priced_symbol_count": 1, "coverage_rate": 1.0, "missing_symbols": []},
            "diagnose_factors": lambda: {"total_score_non_null_count": 1, "factor_quality": {}, "data_quality_notes": []},
            "run_daily_selection": lambda: {"candidate_count": 1, "latest_price_date": "20240131"},
        },
    )

    assert result["steps"]["backup_local_data"]["result"]["backup_dir"]
    assert result["report"]["summaries"]["backup_local_data"]["backup_dir"]


def test_sample_smoke_support_remains_available() -> None:
    """sample smoke test support should remain available."""
    from core.sample_data import get_sample_dashboard_data

    sample = get_sample_dashboard_data()

    assert not sample["selection"].empty
