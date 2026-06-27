"""Tests for review decision import and watchlist management with temporary duckdb."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from core.jobs.diagnose_watchlist import diagnose_watchlist
from core.jobs.export_review_template import export_review_template
from core.jobs.export_watchlist import export_watchlist
from core.jobs.import_review_decisions import import_review_decisions
from core.jobs.run_real_workflow import run_real_workflow
from core.reporting.watchlist_report import load_latest_watchlist_report
from core.review.decisions import read_review_decisions
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import summarize_update_status


def _settings(tmp_path: Path) -> Any:
    """Return sample settings for no-network tests."""
    return SimpleNamespace(
        data_provider="sample",
        duckdb_path=tmp_path / "temporary.duckdb",
        akshare_sample_symbols="",
        real_data_sample_symbols="",
        real_universe_preset="mini",
        akshare_symbols=[],
        sample_symbols=[],
        default_top_n=30,
    )


def _write_template(
    path: Path,
    decision: str = "watch",
    reason: str = "人工复核通过",
    notes: str = "temporary duckdb mock note",
    reviewer: str = "tester",
) -> None:
    """Write a minimal review decision CSV."""
    pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "name": "演示银行A",
                "selection_date": "20240131",
                "total_score": 86.5,
                "trend_score": 82.0,
                "momentum_score": 78.0,
                "liquidity_score": 90.0,
                "volatility_score": 88.0,
                "fundamental_score": 84.0,
                "decision": decision,
                "reason": reason,
                "notes": notes,
                "reviewer": reviewer,
            }
        ]
    ).to_csv(path, index=False)


def test_review_decisions_table_can_be_created(tmp_path: Path) -> None:
    """review_decisions table should be created by the storage schema."""
    store = DuckDBStore(tmp_path / "reviews.duckdb")
    store.initialize()

    reviews = read_review_decisions(store)

    assert reviews.empty
    assert "decision" in reviews.columns


def test_export_review_template_generates_csv(tmp_path: Path) -> None:
    """export_review_template should generate a CSV template from sample candidates."""
    result = export_review_template(
        top_n=2,
        output_dir=tmp_path / "reports",
        quiet=True,
        settings=_settings(tmp_path),
        store=DuckDBStore(tmp_path / "template.duckdb"),
    )

    csv_path = Path(result["generated_files"]["csv"])
    content = csv_path.read_text(encoding="utf-8-sig")

    assert result["row_count"] == 2
    assert "ts_code,name,selection_date" in content
    assert "pending" in content


def test_import_review_decisions_valid_and_duplicate_updates(tmp_path: Path) -> None:
    """Valid decisions should import, and duplicate imports should update not duplicate."""
    store = DuckDBStore(tmp_path / "import.duckdb")
    csv_path = tmp_path / "review_template.csv"
    _write_template(csv_path, decision="watch", reason="first reason")

    first = import_review_decisions(file_path=csv_path, store=store)
    _write_template(csv_path, decision="watch", reason="updated reason")
    second = import_review_decisions(file_path=csv_path, store=store)
    reviews = read_review_decisions(store)

    assert first["imported_rows"] == 1
    assert first["inserted_rows"] == 1
    assert second["updated_rows"] == 1
    assert len(reviews) == 1
    assert reviews.iloc[0]["reason"] == "updated reason"


def test_import_review_decisions_saves_reason_notes_and_reviewer(tmp_path: Path) -> None:
    """Import should persist reason, notes, and reviewer fields."""
    store = DuckDBStore(tmp_path / "fields.duckdb")
    csv_path = tmp_path / "fields.csv"
    _write_template(csv_path, reason="测试加入观察", notes="重点跟踪订单变化", reviewer="wanghao")

    import_review_decisions(file_path=csv_path, store=store)
    reviews = read_review_decisions(store)

    assert reviews.iloc[0]["reason"] == "测试加入观察"
    assert reviews.iloc[0]["notes"] == "重点跟踪订单变化"
    assert reviews.iloc[0]["reviewer"] == "wanghao"


def test_duplicate_import_updates_reason_notes_and_reviewer(tmp_path: Path) -> None:
    """Duplicate import should update review text fields when new values exist."""
    store = DuckDBStore(tmp_path / "update-fields.duckdb")
    csv_path = tmp_path / "update-fields.csv"
    _write_template(csv_path, reason="old reason", notes="old notes", reviewer="old reviewer")
    import_review_decisions(file_path=csv_path, store=store)
    _write_template(csv_path, reason="new reason", notes="new notes", reviewer="new reviewer")

    import_review_decisions(file_path=csv_path, store=store)
    reviews = read_review_decisions(store)

    assert reviews.iloc[0]["reason"] == "new reason"
    assert reviews.iloc[0]["notes"] == "new notes"
    assert reviews.iloc[0]["reviewer"] == "new reviewer"


def test_nan_cells_do_not_clear_existing_review_text(tmp_path: Path) -> None:
    """NaN-like cells should not overwrite existing reason/notes/reviewer."""
    store = DuckDBStore(tmp_path / "nan-preserve.duckdb")
    csv_path = tmp_path / "nan-preserve.csv"
    _write_template(csv_path, reason="keep reason", notes="keep notes", reviewer="keep reviewer")
    import_review_decisions(file_path=csv_path, store=store)
    _write_template(csv_path, reason="NaN", notes="NaN", reviewer="NaN")

    import_review_decisions(file_path=csv_path, store=store)
    reviews = read_review_decisions(store)

    assert reviews.iloc[0]["reason"] == "keep reason"
    assert reviews.iloc[0]["notes"] == "keep notes"
    assert reviews.iloc[0]["reviewer"] == "keep reviewer"


def test_invalid_decision_does_not_crash_entire_import(tmp_path: Path) -> None:
    """Illegal decision should be reported and skipped clearly."""
    store = DuckDBStore(tmp_path / "invalid.duckdb")
    csv_path = tmp_path / "invalid.csv"
    _write_template(csv_path, decision="buy_now")

    result = import_review_decisions(file_path=csv_path, store=store)

    assert result["imported_rows"] == 0
    assert result["skipped_rows"] == 1
    assert "非法 decision" in result["error_rows"][0]["error"]


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    """--dry-run should validate without writing review_decisions."""
    store = DuckDBStore(tmp_path / "dryrun.duckdb")
    csv_path = tmp_path / "dryrun.csv"
    _write_template(csv_path)

    result = import_review_decisions(file_path=csv_path, dry_run=True, store=store)
    reviews = read_review_decisions(store)

    assert result["dry_run"] is True
    assert result["imported_rows"] == 0
    assert reviews.empty


def test_diagnose_watchlist_outputs_active_watch(tmp_path: Path) -> None:
    """diagnose_watchlist should list active watch decisions."""
    store = DuckDBStore(tmp_path / "watch.duckdb")
    csv_path = tmp_path / "watch.csv"
    _write_template(csv_path)
    import_review_decisions(file_path=csv_path, store=store)

    result = diagnose_watchlist(settings=_settings(tmp_path), store=store)

    assert result["active_watch_count"] == 1
    assert result["watchlist"][0]["ts_code"] == "000001.SZ"
    assert result["watchlist"][0]["reason"] == "人工复核通过"
    assert result["watchlist"][0]["notes"] == "temporary duckdb mock note"
    assert result["watchlist"][0]["reviewer"] == "tester"
    assert result["watchlist"][0]["total_score"] is None
    assert result["watchlist"][0]["data_quality_note"] == "当前无可用综合评分"


def test_export_watchlist_generates_markdown_json_csv(tmp_path: Path) -> None:
    """export_watchlist should generate all requested report files."""
    store = DuckDBStore(tmp_path / "watchlist.duckdb")
    csv_path = tmp_path / "watchlist.csv"
    _write_template(csv_path)
    import_review_decisions(file_path=csv_path, store=store)

    result = export_watchlist(
        output_dir=tmp_path / "reports",
        report_format="all",
        quiet=True,
        settings=_settings(tmp_path),
        store=store,
    )

    assert Path(result["generated_files"]["markdown"]).exists()
    assert Path(result["generated_files"]["json"]).exists()
    assert Path(result["generated_files"]["csv"]).exists()
    assert result["report"]["watchlist_count"] == 1
    markdown = Path(result["generated_files"]["markdown"]).read_text(encoding="utf-8")
    csv_text = Path(result["generated_files"]["csv"]).read_text(encoding="utf-8-sig")
    assert "人工复核通过" in markdown
    assert "当前无可用综合评分" in markdown
    assert "reason" in csv_text
    assert "data_quality_note" in csv_text


def test_run_real_workflow_exports_review_template_and_watchlist(tmp_path: Path) -> None:
    """run_real_workflow flags should export review template and watchlist reports."""
    store = DuckDBStore(tmp_path / "workflow.duckdb")
    csv_path = tmp_path / "workflow.csv"
    _write_template(csv_path)
    import_review_decisions(file_path=csv_path, store=store)

    result = run_real_workflow(
        skip_update=True,
        no_backtest=True,
        export_review_template_report=True,
        export_watchlist_report=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=_settings(tmp_path),
        step_overrides={
            "diagnose_real_data": lambda: {"is_ready_for_selection": True, "latest_price_date": "20240131", "table_rows": {}},
            "diagnose_update_batch": lambda: {"configured_symbol_count": 3, "priced_symbol_count": 3, "coverage_rate": 1.0, "missing_symbols": []},
            "diagnose_factors": lambda: {"total_score_non_null_count": 3, "factor_quality": {}, "data_quality_notes": []},
            "run_daily_selection": lambda: {"candidate_count": 3, "latest_price_date": "20240131"},
            "review_decisions": lambda: {"total_rows": 1, "active_watch_count": 1, "decision_counts": {"watch": 1}},
        },
    )

    assert result["steps"]["export_review_template"]["result"]["generated_files"]["csv"].endswith(".csv")
    assert result["steps"]["export_watchlist"]["result"]["generated_files"]["json"].endswith(".json")


def test_streamlit_helper_can_read_watchlist_report(tmp_path: Path) -> None:
    """Streamlit status helper should surface latest watchlist report metadata."""
    store = DuckDBStore(tmp_path / "streamlit.duckdb")
    csv_path = tmp_path / "streamlit.csv"
    _write_template(csv_path)
    import_review_decisions(file_path=csv_path, store=store)
    export_watchlist(output_dir=tmp_path / "reports", quiet=True, settings=_settings(tmp_path), store=store)

    loaded = load_latest_watchlist_report(tmp_path / "reports")
    status = summarize_update_status({"_latest_watchlist_report": loaded})

    assert loaded is not None
    assert loaded["watchlist_count"] == 1
    assert status["latest_watchlist_report"]["path"].endswith(".json")
