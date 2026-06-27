"""Tests for selection review export with mock/sample data and temporary duckdb paths."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

import core.jobs.export_selection_review as export_module
from core.jobs.export_selection_review import export_selection_review
from core.jobs.run_real_workflow import run_real_workflow
from core.reporting.selection_review_report import (
    build_selection_review_report,
    load_latest_selection_review_report,
)
from core.sample_data import get_sample_dashboard_data
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import summarize_update_status


def _settings(tmp_path: Path) -> Any:
    """Return settings-like sample config for no-network tests."""
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


def test_export_selection_review_generates_markdown_json_and_csv(tmp_path: Path) -> None:
    """export_selection_review should generate all review report formats."""
    result = export_selection_review(
        top_n=2,
        output_dir=tmp_path / "reports",
        report_format="all",
        quiet=True,
        settings=_settings(tmp_path),
        store=DuckDBStore(tmp_path / "temporary.duckdb"),
    )

    files = result["generated_files"]
    markdown = Path(files["markdown"]).read_text(encoding="utf-8")
    payload = json.loads(Path(files["json"]).read_text(encoding="utf-8"))
    csv_text = Path(files["csv"]).read_text(encoding="utf-8-sig")

    assert "候选股票人工复核清单" in markdown
    assert "人工复核要点" in markdown
    assert "风险提示" in markdown
    assert "trend_score" in markdown
    assert payload["metadata"]
    assert payload["candidates"]
    assert payload["risk_disclaimer"]
    assert "rank,ts_code,name" in csv_text
    assert "total_score" in csv_text


def test_export_selection_review_individual_formats(tmp_path: Path) -> None:
    """Individual markdown/json/csv formats should be supported."""
    for report_format in ["markdown", "json", "csv"]:
        result = export_selection_review(
            top_n=1,
            output_dir=tmp_path / report_format,
            report_format=report_format,
            quiet=True,
            settings=_settings(tmp_path),
            store=DuckDBStore(tmp_path / f"{report_format}.duckdb"),
        )
        assert report_format in result["generated_files"]
        assert Path(result["generated_files"][report_format]).exists()


def test_missing_pe_pb_writes_data_quality_note() -> None:
    """Missing pe/pb should be explicit in candidate data quality notes."""
    data = get_sample_dashboard_data()
    daily_basic = data["daily_basic"].copy()
    daily_basic["pe"] = pd.NA
    daily_basic["pb"] = pd.NA

    report = build_selection_review_report(
        metadata={"generated_at": "2026-06-27T12:00:00", "data_provider": "akshare", "duckdb_path": "temporary duckdb"},
        selection_summary={
            "is_real_data": True,
            "fallback_to_sample": False,
            "latest_price_date": "20240131",
            "stock_pool_count": 3,
            "scored_stock_count": 3,
            "candidate_count": 3,
        },
        selection_df=data["selection"],
        factor_df=data["factor_scores"],
        price_df=data["price"],
        daily_basic_df=daily_basic,
        data_quality_notes=["AKShare fallback 的 pe/pb 可能为空。"],
        top_n=2,
    )

    assert report["candidates"][0]["missing_fields"]["pe"] is True
    assert report["candidates"][0]["missing_fields"]["pb"] is True
    assert "pe/pb 缺失" in report["candidates"][0]["data_quality_note"]


def test_export_selection_review_joins_stock_basic_fields(tmp_path: Path, monkeypatch: Any) -> None:
    """Export should fill industry/market/list_date from stock_basic when scores lack them."""
    store = DuckDBStore(tmp_path / "real.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "平安银行",
                    "area": "深圳",
                    "industry": "银行",
                    "market": "深交所",
                    "list_date": "19910403",
                    "delist_date": None,
                    "is_hs": None,
                }
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20240104"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "pre_close": [10.0],
                "change": [0.2],
                "pct_chg": [2.0],
                "vol": [1000.0],
                "amount": [150_000_000.0],
            }
        ),
    )
    store.upsert_dataframe(
        "daily_basic",
        pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20240104"],
                "turnover_rate": [1.0],
                "volume_ratio": [None],
                "pe": [None],
                "pb": [None],
                "ps": [None],
                "total_mv": [None],
                "circ_mv": [None],
            }
        ),
    )
    factor_scores = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240104"],
            "name": ["平安银行"],
            "trend_score": [80.0],
            "momentum_score": [80.0],
            "liquidity_score": [80.0],
            "volatility_score": [80.0],
            "fundamental_score": [None],
            "total_score": [88.0],
        }
    )
    monkeypatch.setattr(
        export_module,
        "run_daily_selection",
        lambda settings, store: {
            "is_real_data": True,
            "fallback_to_sample": False,
            "latest_price_date": "20240104",
            "stock_pool_count": 1,
            "scored_stock_count": 1,
            "candidate_count": 1,
        },
    )
    monkeypatch.setattr(
        export_module,
        "diagnose_factors",
        lambda settings, store: {"factor_scores_df": factor_scores, "data_quality_notes": []},
    )

    result = export_module.export_selection_review(
        top_n=1,
        output_dir=tmp_path / "reports",
        report_format="all",
        quiet=True,
        settings=SimpleNamespace(data_provider="akshare", duckdb_path=store.db_path),
        store=store,
    )

    files = result["generated_files"]
    payload = json.loads(Path(files["json"]).read_text(encoding="utf-8"))
    csv_text = Path(files["csv"]).read_text(encoding="utf-8-sig")
    markdown = Path(files["markdown"]).read_text(encoding="utf-8")
    candidate = payload["candidates"][0]

    assert candidate["industry"] == "银行"
    assert candidate["market"] == "深交所"
    assert candidate["list_date"] == "19910403"
    assert "银行" in csv_text
    assert "深交所" in csv_text
    assert "19910403" in csv_text
    assert "market: 深交所" in markdown
    assert "industry 缺失" not in candidate["data_quality_note"]
    assert "list_date 缺失" not in candidate["data_quality_note"]
    assert "pe/pb 缺失" in candidate["data_quality_note"]


def test_run_real_workflow_export_selection_review_generates_files(tmp_path: Path) -> None:
    """run_real_workflow --export-selection-review should generate review files."""
    result = run_real_workflow(
        skip_update=True,
        no_backtest=True,
        export_selection_review_report=True,
        report_dir=tmp_path / "reports",
        report_format="json",
        quiet=True,
        settings=_settings(tmp_path),
        step_overrides={
            "diagnose_real_data": lambda: {"is_ready_for_selection": True, "latest_price_date": "20240131", "table_rows": {}},
            "diagnose_update_batch": lambda: {
                "configured_symbol_count": 3,
                "priced_symbol_count": 3,
                "coverage_rate": 1.0,
                "missing_symbols": [],
            },
            "diagnose_factors": lambda: {"total_score_non_null_count": 3, "factor_quality": {}, "data_quality_notes": []},
            "run_daily_selection": lambda: {"candidate_count": 3, "latest_price_date": "20240131"},
        },
    )

    review_files = result["steps"]["export_selection_review"]["result"]["generated_files"]
    workflow_payload = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))

    assert review_files["markdown"].endswith(".md")
    assert review_files["json"].endswith(".json")
    assert review_files["csv"].endswith(".csv")
    assert workflow_payload["summaries"]["export_selection_review"]["generated_files"]


def test_streamlit_helper_reads_latest_selection_review_report(tmp_path: Path) -> None:
    """Streamlit status helpers should surface latest selection_review report."""
    export_selection_review(
        top_n=2,
        output_dir=tmp_path / "reports",
        report_format="all",
        quiet=True,
        settings=_settings(tmp_path),
        store=DuckDBStore(tmp_path / "temporary.duckdb"),
    )

    loaded = load_latest_selection_review_report(tmp_path / "reports")
    status = summarize_update_status({"_latest_selection_review_report": loaded})

    assert loaded is not None
    assert loaded["candidate_count"] == 2
    assert status["latest_selection_review_report"]["path"].endswith(".json")
