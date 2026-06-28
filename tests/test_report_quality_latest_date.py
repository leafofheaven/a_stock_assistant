"""Tests for latest-date valuation quality reporting with mock local data."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from core.jobs.diagnose_data_quality import diagnose_data_quality
from core.jobs.diagnose_factors import diagnose_factors
from core.reporting.daily_workflow_report import build_daily_workflow_report, render_markdown_report
from core.reporting.selection_review_report import build_selection_review_report
from core.reporting.watchlist_report import build_watchlist_report
from core.review.decisions import build_watchlist_dataframe, import_review_decisions
from core.storage.duckdb_store import DuckDBStore


def _settings(tmp_path: Path) -> Any:
    return SimpleNamespace(data_provider="akshare", duckdb_path=tmp_path / "quality.duckdb")


def _date_strings(days: int) -> list[str]:
    start = datetime(2024, 1, 1)
    return [(start + timedelta(days=index)).strftime("%Y%m%d") for index in range(days)]


def _seed_quality_store(tmp_path: Path, days: int = 65) -> DuckDBStore:
    """Seed temporary DuckDB where only latest date has PE/PB."""
    store = DuckDBStore(tmp_path / "quality.duckdb")
    store.initialize()
    stocks = [
        {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "area": "深圳", "industry": "银行", "market": "深交所", "list_date": "19910403", "delist_date": None, "is_hs": None},
        {"ts_code": "002475.SZ", "symbol": "002475", "name": "立讯精密", "area": "广东", "industry": "消费电子", "market": "深交所", "list_date": "20100915", "delist_date": None, "is_hs": None},
    ]
    store.upsert_dataframe("stock_basic", pd.DataFrame(stocks))
    dates = _date_strings(days)
    price_rows: list[dict[str, Any]] = []
    basic_rows: list[dict[str, Any]] = []
    adj_rows: list[dict[str, Any]] = []
    for stock_index, stock in enumerate(stocks):
        for day_index, trade_date in enumerate(dates):
            close = 10 + stock_index * 5 + day_index * 0.1
            price_rows.append(
                {
                    "ts_code": stock["ts_code"],
                    "trade_date": trade_date,
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "pre_close": close - 0.1,
                    "change": 0.1,
                    "pct_chg": 0.5,
                    "vol": 100000,
                    "amount": 200000000 + stock_index * 10000000,
                }
            )
            is_latest = trade_date == dates[-1]
            basic_rows.append(
                {
                    "ts_code": stock["ts_code"],
                    "trade_date": trade_date,
                    "turnover_rate": 1.0,
                    "volume_ratio": None,
                    "pe": 8.0 + stock_index if is_latest else None,
                    "pb": 0.8 + stock_index * 0.1 if is_latest else None,
                    "ps": None,
                    "total_mv": 1000.0 if is_latest else None,
                    "circ_mv": 900.0 if is_latest else None,
                }
            )
            adj_rows.append({"ts_code": stock["ts_code"], "trade_date": trade_date, "adj_factor": 1.0})
    store.upsert_dataframe("daily_price", pd.DataFrame(price_rows))
    store.upsert_dataframe("daily_basic", pd.DataFrame(basic_rows))
    store.upsert_dataframe("adj_factor", pd.DataFrame(adj_rows))
    return store


def test_diagnose_data_quality_reports_historical_and_latest_date_rates(tmp_path: Path) -> None:
    """Full-history PE/PB can be low while latest trade date is complete."""
    store = _seed_quality_store(tmp_path, days=5)

    result = diagnose_data_quality(settings=_settings(tmp_path), store=store)

    assert result["daily_basic_completeness"]["pe"] < 1.0
    assert result["daily_basic_completeness"]["pb"] < 1.0
    assert result["latest_date_stock_count"] == 2
    assert result["latest_date_pe_non_null_rate"] == 1.0
    assert result["latest_date_pb_non_null_rate"] == 1.0
    assert result["latest_date_total_mv_non_null_rate"] == 1.0
    assert result["latest_date_circ_mv_non_null_rate"] == 1.0


def test_daily_workflow_report_uses_current_candidate_and_watchlist_scope(tmp_path: Path) -> None:
    """Daily report should not misreport current candidate/watchlist PE/PB missing."""
    steps = {
        "diagnose_data_quality": {
            "status": "success",
            "result": {
                "daily_basic_rows": 10,
                "latest_trade_date": "20240105",
                "latest_date_stock_count": 2,
                "latest_date_pe_non_null_rate": 1.0,
                "latest_date_pb_non_null_rate": 1.0,
                "valuation_summary": {"pe_non_null_rate": 0.2, "pb_non_null_rate": 0.2},
            },
        },
        "diagnose_factors": {
            "status": "success",
            "result": {
                "stock_pool_count": 2,
                "total_score_non_null_count": 2,
                "data_quality_notes": [
                    "部分股票 pe 缺失，缺失股票的 pe_score 与 fundamental_score 可能为空。",
                    "部分股票 pb 缺失，缺失股票的估值相关复核信息不完整。",
                ],
            },
        },
        "run_daily_selection": {"status": "success", "result": {"latest_price_date": "20240105", "top_candidates": []}},
        "export_selection_review": {
            "status": "success",
            "result": {
                "report": {
                    "candidates": [
                        {
                            "rank": 1,
                            "ts_code": "000001.SZ",
                            "name": "平安银行",
                            "industry": "银行",
                            "latest_close": 10.5,
                            "pe": 8.0,
                            "pb": 0.8,
                            "factor_scores": {"total_score": 80.0, "fundamental_score": 90.0},
                        }
                    ]
                }
            },
        },
        "refresh_watchlist_scores": {"status": "success", "result": {"items": []}},
        "diagnose_watchlist": {
            "status": "success",
            "result": {
                "active_watch_count": 1,
                "watchlist": [
                    {"ts_code": "000001.SZ", "name": "平安银行", "pe": 8.0, "pb": 0.8, "total_score": 80.0, "fundamental_score": 90.0}
                ],
            },
        },
    }

    report = build_daily_workflow_report(
        started_at=datetime(2026, 6, 28, 9, 0, 0),
        finished_at=datetime(2026, 6, 28, 9, 1, 0),
        settings=_settings(tmp_path),
        steps=steps,
        overall_status="success",
        generated_files={},
        top_n=10,
    )
    markdown = render_markdown_report(report)

    assert report["data_quality_scope"]["latest_date_pe_non_null_rate"] == 1.0
    assert report["data_quality_scope"]["candidate_pe_missing_count"] == 0
    assert report["data_quality_scope"]["watchlist_pb_missing_count"] == 0
    assert "部分股票 pe 缺失" not in markdown
    assert "部分股票 pb 缺失" not in markdown
    assert "PE/PB 当前仅补全最新交易日，历史区间估值字段可能为空。" in markdown


def test_selection_review_current_pe_pb_does_not_show_missing_note(tmp_path: Path) -> None:
    """Selection review should use the candidate's current row for PE/PB prompts."""
    price = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240105"], "close": [10.5]})
    daily_basic = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240105"], "pe": [8.0], "pb": [0.8]})
    selection = pd.DataFrame(
        {
            "rank": [1],
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
            "industry": ["银行"],
            "market": ["深交所"],
            "list_date": ["19910403"],
            "trade_date": ["20240105"],
            "total_score": [80.0],
            "fundamental_score": [90.0],
        }
    )
    report = build_selection_review_report(
        metadata={"generated_at": "2026-06-28", "data_provider": "akshare"},
        selection_summary={},
        selection_df=selection,
        factor_df=selection,
        price_df=price,
        daily_basic_df=daily_basic,
        data_quality_notes=["部分股票 pe 缺失，缺失股票的 pe_score 与 fundamental_score 可能为空。"],
        top_n=1,
    )

    note = report["candidates"][0]["data_quality_note"]
    assert "pe 缺失" not in note
    assert "pb 缺失" not in note


def test_watchlist_current_pe_pb_and_score_do_not_show_missing_note(tmp_path: Path) -> None:
    """Watchlist report should not show missing valuation or score when current values exist."""
    store = _seed_quality_store(tmp_path, days=5)
    latest = _date_strings(5)[-1]
    store.upsert_dataframe(
        "factor_scores",
        pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": [latest], "trend_score": [80.0], "momentum_score": [80.0], "liquidity_score": [80.0], "volatility_score": [80.0], "fundamental_score": [90.0], "total_score": [88.0]}),
    )
    import_review_decisions(
        pd.DataFrame({"ts_code": ["000001.SZ"], "name": ["平安银行"], "selection_date": [latest], "decision": ["watch"], "reason": ["观察"], "notes": [""], "reviewer": ["tester"], "data_quality_note": ["当前无可用综合评分；部分股票 pe 缺失"]}),
        store=store,
    )

    watchlist_df = build_watchlist_dataframe(store)
    report = build_watchlist_report(metadata={"generated_at": "2026-06-28", "data_provider": "akshare"}, watchlist_df=watchlist_df)
    note = report["watchlist"][0]["data_quality_note"]

    assert report["watchlist"][0]["pe"] == 8.0
    assert report["watchlist"][0]["pb"] == 0.8
    assert report["watchlist"][0]["total_score"] == 88.0
    assert "当前无可用综合评分" not in note
    assert "pe 缺失" not in note


def test_diagnose_factors_latest_date_complete_does_not_emit_partial_missing_note(tmp_path: Path) -> None:
    """Factor diagnostics should avoid all-history PE/PB warnings when latest date is complete."""
    store = _seed_quality_store(tmp_path, days=65)

    result = diagnose_factors(settings=_settings(tmp_path), store=store, use_sample=False)
    notes = "\n".join(result["data_quality_notes"])

    assert result["factor_quality"]["fundamental_score"]["non_null_rate"] == 1.0
    assert "部分股票 pe 缺失" not in notes
    assert "部分股票 pb 缺失" not in notes
    assert "历史区间估值字段可能为空" in notes
