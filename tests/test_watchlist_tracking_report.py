"""Tests for watchlist tracking snapshots and reports with temporary duckdb mock data."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from core.jobs.export_watchlist_tracking_report import export_watchlist_tracking_report
from core.jobs.import_review_decisions import import_review_decisions
from core.jobs.run_real_workflow import run_real_workflow
from core.jobs.track_watchlist import track_watchlist
from core.reporting.watchlist_tracking_report import load_latest_watchlist_tracking_report
from core.review.tracking import create_watchlist_snapshots, read_watchlist_snapshots
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import summarize_update_status


def _settings(tmp_path: Path, db_name: str = "tracking.duckdb") -> Any:
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


def _write_review_csv(path: Path, ts_code: str = "000001.SZ", name: str = "演示银行A") -> None:
    """Write a minimal active watch decision CSV."""
    pd.DataFrame(
        [
            {
                "ts_code": ts_code,
                "name": name,
                "selection_date": "20240131",
                "decision": "watch",
                "reason": "mock 加入观察",
                "notes": "temporary duckdb mock note",
                "reviewer": "tester",
            }
        ]
    ).to_csv(path, index=False)


def _seed_watch_decision(store: DuckDBStore, tmp_path: Path, ts_code: str = "000001.SZ") -> None:
    csv_path = tmp_path / f"review_{ts_code}.csv"
    _write_review_csv(csv_path, ts_code=ts_code)
    import_review_decisions(file_path=csv_path, store=store)


def _seed_price_and_scores(
    store: DuckDBStore,
    *,
    trade_date: str = "20240201",
    close: float = 12.0,
    total_score: float = 85.0,
    ts_code: str = "000001.SZ",
) -> None:
    store.initialize()
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": close - 0.5,
                    "high": close + 0.5,
                    "low": close - 1,
                    "close": close,
                    "pre_close": close - 0.2,
                    "change": 0.2,
                    "pct_chg": 1.0,
                    "vol": 100000,
                    "amount": 120000000,
                }
            ]
        ),
    )
    store.upsert_dataframe(
        "factor_scores",
        pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "trend_score": total_score - 2,
                    "momentum_score": total_score - 3,
                    "liquidity_score": total_score - 4,
                    "volatility_score": total_score - 5,
                    "fundamental_score": total_score - 6,
                    "total_score": total_score,
                }
            ]
        ),
    )


def test_watchlist_snapshots_table_can_be_created(tmp_path: Path) -> None:
    """watchlist_snapshots table should be created by the storage schema."""
    store = DuckDBStore(tmp_path / "schema.duckdb")
    store.initialize()

    snapshots = read_watchlist_snapshots(store)

    assert snapshots.empty
    assert "snapshot_date" in snapshots.columns
    assert "total_score" in snapshots.columns


def test_track_watchlist_creates_snapshot_for_active_watch(tmp_path: Path) -> None:
    """track_watchlist should create a snapshot for active watch stocks."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_watch_decision(store, tmp_path)
    _seed_price_and_scores(store)

    result = track_watchlist(snapshot_date="20240201", quiet=True, settings=settings, store=store)

    snapshots = read_watchlist_snapshots(store)
    assert result["snapshot_count"] == 1
    assert result["missing_price_count"] == 0
    assert result["missing_score_count"] == 0
    assert snapshots.iloc[0]["ts_code"] == "000001.SZ"
    assert snapshots.iloc[0]["latest_close"] == 12.0
    assert snapshots.iloc[0]["total_score"] == 85.0


def test_track_watchlist_handles_no_active_watch(tmp_path: Path) -> None:
    """No active watch stocks should return a clear skipped status."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    store.initialize()

    result = track_watchlist(quiet=True, settings=settings, store=store)

    assert result["status"] == "skipped"
    assert result["active_watch_count"] == 0
    assert "暂无 active watch" in result["message"]


def test_track_watchlist_marks_missing_price_and_score(tmp_path: Path) -> None:
    """Missing local price and score data should not crash snapshot creation."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_watch_decision(store, tmp_path)

    result = track_watchlist(snapshot_date="20240201", quiet=True, settings=settings, store=store)
    snapshots = read_watchlist_snapshots(store)

    assert result["snapshot_count"] == 1
    assert result["missing_price_count"] == 1
    assert result["missing_score_count"] == 1
    assert "缺少当前行情" in snapshots.iloc[0]["data_quality_note"]
    assert "当前无可用综合评分" in snapshots.iloc[0]["data_quality_note"]


def test_repeated_tracking_same_date_updates_not_duplicates(tmp_path: Path) -> None:
    """Repeated tracking for the same ts_code and snapshot_date should update rows."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_watch_decision(store, tmp_path)
    _seed_price_and_scores(store, close=12.0, total_score=85.0)
    track_watchlist(snapshot_date="20240201", quiet=True, settings=settings, store=store)
    _seed_price_and_scores(store, close=13.0, total_score=88.0)

    track_watchlist(snapshot_date="20240201", quiet=True, settings=settings, store=store)
    snapshots = read_watchlist_snapshots(store)

    assert len(snapshots) == 1
    assert snapshots.iloc[0]["latest_close"] == 13.0
    assert snapshots.iloc[0]["total_score"] == 88.0


def test_export_watchlist_tracking_report_generates_all_formats(tmp_path: Path) -> None:
    """export_watchlist_tracking_report should generate markdown, json, and csv files."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_watch_decision(store, tmp_path)
    _seed_price_and_scores(store, trade_date="20240131", close=10.0, total_score=80.0)
    track_watchlist(snapshot_date="20240131", quiet=True, settings=settings, store=store)
    _seed_price_and_scores(store, trade_date="20240201", close=12.0, total_score=85.0)
    track_watchlist(snapshot_date="20240201", quiet=True, settings=settings, store=store)

    result = export_watchlist_tracking_report(
        output_dir=tmp_path / "reports",
        report_format="all",
        quiet=True,
        settings=settings,
        store=store,
    )

    files = result["generated_files"]
    markdown = Path(files["markdown"]).read_text(encoding="utf-8")
    payload = json.loads(Path(files["json"]).read_text(encoding="utf-8"))
    csv_text = Path(files["csv"]).read_text(encoding="utf-8-sig")
    assert "close_change_pct" in markdown
    assert "total_score_change" in csv_text
    assert payload["items"][0]["close_change_pct"] == 0.19999999999999996
    assert payload["items"][0]["total_score_change"] == 5.0
    forbidden = ["买入建议", "卖出建议", "强烈推荐", "目标价", "保证收益", "自动交易建议"]
    assert not any(phrase in markdown for phrase in forbidden)


def test_export_report_marks_missing_total_score_quality_note(tmp_path: Path) -> None:
    """total_score missing should produce a clear data_quality_note."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_watch_decision(store, tmp_path)
    track_watchlist(snapshot_date="20240201", quiet=True, settings=settings, store=store)

    result = export_watchlist_tracking_report(
        output_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=settings,
        store=store,
    )

    payload = json.loads(Path(result["generated_files"]["json"]).read_text(encoding="utf-8"))
    assert payload["items"][0]["total_score"] is None
    assert payload["items"][0]["data_quality_note"]
    assert "当前无可用综合评分" in payload["items"][0]["data_quality_note"]


def test_run_real_workflow_tracks_and_exports_watchlist_tracking(tmp_path: Path) -> None:
    """run_real_workflow flags should create snapshots and export tracking reports."""
    settings = _settings(tmp_path, db_name="workflow-tracking.duckdb")
    store = DuckDBStore(settings.duckdb_path)
    _seed_watch_decision(store, tmp_path)
    _seed_price_and_scores(store)

    result = run_real_workflow(
        skip_update=True,
        no_backtest=True,
        track_watchlist_enabled=True,
        export_watchlist_tracking_report_enabled=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=settings,
        step_overrides={
            "diagnose_real_data": lambda: {"is_ready_for_selection": True, "latest_price_date": "20240201", "table_rows": {}},
            "diagnose_update_batch": lambda: {"configured_symbol_count": 1, "priced_symbol_count": 1, "coverage_rate": 1.0, "missing_symbols": []},
            "diagnose_factors": lambda: {"total_score_non_null_count": 1, "factor_quality": {}, "data_quality_notes": []},
            "run_daily_selection": lambda: {"candidate_count": 1, "latest_price_date": "20240201"},
        },
    )

    assert result["steps"]["track_watchlist"]["result"]["snapshot_count"] == 1
    assert result["steps"]["export_watchlist_tracking"]["result"]["generated_files"]["json"].endswith(".json")
    assert result["report"]["summaries"]["track_watchlist"]["snapshot_count"] == 1


def test_streamlit_helper_can_read_watchlist_tracking_report(tmp_path: Path) -> None:
    """Streamlit status helper should surface latest tracking report metadata."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_watch_decision(store, tmp_path)
    _seed_price_and_scores(store)
    track_watchlist(snapshot_date="20240201", quiet=True, settings=settings, store=store)
    export_watchlist_tracking_report(output_dir=tmp_path / "reports", quiet=True, settings=settings, store=store)

    loaded = load_latest_watchlist_tracking_report(tmp_path / "reports")
    status = summarize_update_status({"_latest_watchlist_tracking_report": loaded})

    assert loaded is not None
    assert loaded["watchlist_count"] == 1
    assert status["latest_watchlist_tracking_report"]["path"].endswith(".json")


def test_create_watchlist_snapshots_uses_mock_data_without_network(tmp_path: Path) -> None:
    """create_watchlist_snapshots should use temporary duckdb mock rows only."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_watch_decision(store, tmp_path)
    _seed_price_and_scores(store)

    result = create_watchlist_snapshots(settings=settings, store=store, snapshot_date="20240201")

    assert result["data_provider"] == "sample"
    assert result["snapshot_count"] == 1
