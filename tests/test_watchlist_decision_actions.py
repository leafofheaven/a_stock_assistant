"""Tests for watchlist decision actions with temporary duckdb mock data."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from core.jobs.diagnose_review_history import diagnose_review_history
from core.jobs.export_watchlist import export_watchlist
from core.jobs.run_real_workflow import run_real_workflow
from core.jobs.update_review_decision import update_review_decision
from core.review.decisions import read_review_decision_history, read_review_decisions
from core.storage.duckdb_store import DuckDBStore


def _settings(tmp_path: Path, db_name: str = "actions.duckdb") -> Any:
    """Return sample settings for no-network tests."""
    return SimpleNamespace(
        data_provider="sample",
        duckdb_path=tmp_path / db_name,
        akshare_sample_symbols="",
        real_data_sample_symbols="",
        real_universe_preset="mini",
        akshare_symbols=[],
        sample_symbols=[],
        default_top_n=30,
    )


def _seed_stock(store: DuckDBStore, ts_code: str = "002475.SZ", name: str = "立讯精密") -> None:
    """Seed temporary duckdb mock stock_basic data."""
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "symbol": ts_code.split(".")[0],
                    "name": name,
                    "area": "深圳",
                    "industry": "电子",
                    "market": "主板",
                    "list_date": "20100915",
                    "delist_date": "",
                    "is_hs": "",
                }
            ]
        ),
    )


def test_update_review_decision_can_create_record(tmp_path: Path) -> None:
    """update_review_decision should create review_decisions and history rows."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_stock(store)

    result = update_review_decision(
        ts_code="002475.SZ",
        decision="pending",
        reason="初始复核",
        reviewer="tester",
        settings=settings,
        store=store,
    )

    decisions = read_review_decisions(store)
    history = read_review_decision_history(store)
    assert result["status"] == "success"
    assert result["action_type"] == "create"
    assert result["history_written"] is True
    assert len(decisions) == 1
    assert len(history) == 1
    assert decisions.iloc[0]["decision"] == "pending"
    assert history.iloc[0]["action_type"] == "create"


def test_update_review_decision_pending_to_watch(tmp_path: Path) -> None:
    """A repeated update should change current state and append history."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_stock(store)
    update_review_decision(ts_code="002475.SZ", decision="pending", settings=settings, store=store)

    result = update_review_decision(
        ts_code="002475.SZ",
        decision="watch",
        reason="继续观察",
        notes="mock note",
        settings=settings,
        store=store,
    )

    decisions = read_review_decisions(store)
    history = read_review_decision_history(store)
    assert result["old_decision"] == "pending"
    assert result["new_decision"] == "watch"
    assert result["action_type"] == "update"
    assert len(decisions) == 1
    assert decisions.iloc[0]["decision"] == "watch"
    assert len(history) == 2


def test_update_review_decision_archive_and_reactivate(tmp_path: Path) -> None:
    """Archive and reactivate should update review_status with history."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_stock(store)
    update_review_decision(ts_code="002475.SZ", decision="watch", settings=settings, store=store)

    archived = update_review_decision(
        ts_code="002475.SZ",
        archive=True,
        reason="归档观察",
        settings=settings,
        store=store,
    )
    reactivated = update_review_decision(
        ts_code="002475.SZ",
        reactivate=True,
        reason="重新激活",
        settings=settings,
        store=store,
    )

    decisions = read_review_decisions(store)
    history = read_review_decision_history(store)
    assert archived["action_type"] == "archive"
    assert archived["new_review_status"] == "archived"
    assert reactivated["action_type"] == "reactivate"
    assert reactivated["new_review_status"] == "active"
    assert decisions.iloc[0]["review_status"] == "active"
    assert len(history) == 3


def test_repeated_updates_do_not_duplicate_current_decision(tmp_path: Path) -> None:
    """Repeated updates should keep one current review_decisions row."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_stock(store)

    update_review_decision(ts_code="002475.SZ", decision="watch", settings=settings, store=store)
    update_review_decision(ts_code="002475.SZ", decision="needs_data", settings=settings, store=store)
    update_review_decision(ts_code="002475.SZ", decision="exclude", settings=settings, store=store)

    decisions = read_review_decisions(store)
    history = read_review_decision_history(store)
    assert len(decisions) == 1
    assert decisions.iloc[0]["decision"] == "exclude"
    assert len(history) == 3


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    """--dry-run should preview without writing review_decisions or history."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_stock(store)

    result = update_review_decision(
        ts_code="002475.SZ",
        decision="watch",
        dry_run=True,
        settings=settings,
        store=store,
    )

    assert result["status"] == "dry_run"
    assert result["history_written"] is False
    assert read_review_decisions(store).empty
    assert read_review_decision_history(store).empty


def test_unknown_ts_code_returns_clear_failure(tmp_path: Path) -> None:
    """A completely unknown code should fail clearly without network calls."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    store.initialize()

    result = update_review_decision(ts_code="999999.SZ", decision="watch", settings=settings, store=store)

    assert result["status"] == "failed"
    assert "不存在" in result["message"]
    assert read_review_decision_history(store).empty


def test_diagnose_review_history_outputs_records(tmp_path: Path) -> None:
    """diagnose_review_history should return recent mock history rows."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_stock(store)
    update_review_decision(ts_code="002475.SZ", decision="watch", reason="继续观察", settings=settings, store=store)

    result = diagnose_review_history(ts_code="002475.SZ", settings=settings, store=store)

    assert result["status"] == "success"
    assert result["history_rows"] == 1
    assert result["records"][0]["ts_code"] == "002475.SZ"


def test_export_watchlist_contains_history_count(tmp_path: Path) -> None:
    """export_watchlist should include history metadata in JSON and CSV outputs."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_stock(store)
    update_review_decision(ts_code="002475.SZ", decision="watch", reason="继续观察", settings=settings, store=store)

    result = export_watchlist(
        output_dir=tmp_path / "reports",
        report_format="all",
        quiet=True,
        settings=settings,
        store=store,
    )

    csv_text = Path(result["generated_files"]["csv"]).read_text(encoding="utf-8-sig")
    assert result["report"]["watchlist"][0]["history_count"] == 1
    assert "latest_action_type" in csv_text
    assert "history_count" in csv_text


def test_run_real_workflow_diagnose_review_history(tmp_path: Path) -> None:
    """run_real_workflow --diagnose-review-history should report history rows."""
    settings = _settings(tmp_path, db_name="workflow-actions.duckdb")
    store = DuckDBStore(settings.duckdb_path)
    _seed_stock(store)
    update_review_decision(ts_code="002475.SZ", decision="watch", settings=settings, store=store)

    result = run_real_workflow(
        skip_update=True,
        no_backtest=True,
        diagnose_review_history_enabled=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=settings,
        step_overrides={
            "diagnose_real_data": lambda: {"is_ready_for_selection": True, "latest_price_date": "20240131", "table_rows": {}},
            "diagnose_update_batch": lambda: {"configured_symbol_count": 1, "priced_symbol_count": 1, "coverage_rate": 1.0, "missing_symbols": []},
            "diagnose_factors": lambda: {"total_score_non_null_count": 1, "factor_quality": {}, "data_quality_notes": []},
            "run_daily_selection": lambda: {"candidate_count": 1, "latest_price_date": "20240131"},
        },
    )

    assert result["steps"]["diagnose_review_history"]["result"]["history_rows"] == 1
    assert result["report"]["summaries"]["diagnose_review_history"]["history_rows"] == 1


def test_sample_smoke_support_remains_available() -> None:
    """sample smoke test support should remain available."""
    from core.sample_data import get_sample_dashboard_data

    sample = get_sample_dashboard_data()

    assert not sample["selection"].empty
