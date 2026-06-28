"""Tests for Task 29 watchlist latest score refresh with temporary DuckDB data."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from core.jobs.diagnose_watchlist import diagnose_watchlist
from core.jobs.export_watchlist import export_watchlist
from core.jobs.export_watchlist_tracking_report import export_watchlist_tracking_report
from core.jobs.refresh_watchlist_scores import refresh_watchlist_scores
from core.jobs.track_watchlist import track_watchlist
from core.review.decisions import import_review_decisions
from core.review.tracking import read_watchlist_snapshots
from core.storage.duckdb_store import DuckDBStore


def _settings(tmp_path: Path) -> Any:
    """Return settings-like object for local no-network tests."""
    return SimpleNamespace(
        data_provider="akshare",
        duckdb_path=tmp_path / "watchlist-refresh.duckdb",
        default_top_n=30,
    )


def _seed_watchlist_store(tmp_path: Path, *, with_score: bool = True) -> DuckDBStore:
    """Create a temporary DuckDB with one active watch stock and mock local data."""
    store = DuckDBStore(tmp_path / "watchlist-refresh.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": "002475.SZ",
                    "symbol": "002475",
                    "name": "立讯精密",
                    "area": "广东",
                    "industry": "消费电子",
                    "market": "深交所",
                    "list_date": "20100915",
                    "delist_date": None,
                    "is_hs": None,
                }
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {
                    "ts_code": "002475.SZ",
                    "trade_date": "20240628",
                    "open": 29.0,
                    "high": 30.5,
                    "low": 28.5,
                    "close": 30.0,
                    "pre_close": 29.2,
                    "change": 0.8,
                    "pct_chg": 2.74,
                    "vol": 100000,
                    "amount": 300000000,
                }
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": "002475.SZ",
                    "trade_date": "20240628",
                    "turnover_rate": 1.8,
                    "volume_ratio": None,
                    "pe": 22.5,
                    "pb": 3.1,
                    "ps": None,
                    "total_mv": 210000000000,
                    "circ_mv": 205000000000,
                }
            ]
        ),
    )
    if with_score:
        store.upsert_dataframe(
            "factor_scores",
            pd.DataFrame(
                [
                    {
                        "ts_code": "002475.SZ",
                        "trade_date": "20240628",
                        "trend_score": 70.0,
                        "momentum_score": 65.0,
                        "liquidity_score": 75.0,
                        "fundamental_score": 82.0,
                        "volatility_score": 55.0,
                        "total_score": 64.01,
                    }
                ]
            ),
        )
    import_review_decisions(
        pd.DataFrame(
            [
                {
                    "ts_code": "002475.SZ",
                    "name": "立讯精密",
                    "selection_date": "20260627",
                    "decision": "watch",
                    "reason": "测试加入观察",
                    "notes": "关注评分变化",
                    "reviewer": "tester",
                    "data_quality_note": "当前无可用综合评分",
                }
            ]
        ),
        store=store,
    )
    return store


def test_diagnose_watchlist_uses_latest_local_score(tmp_path: Path) -> None:
    """diagnose_watchlist should use latest local factor_scores for active watch."""
    settings = _settings(tmp_path)
    store = _seed_watchlist_store(tmp_path, with_score=True)

    result = diagnose_watchlist(settings=settings, store=store)
    item = result["watchlist"][0]

    assert item["total_score"] == 64.01
    assert item["latest_trade_date"] == "20240628"
    assert item["pe"] == 22.5
    assert item["pb"] == 3.1
    assert item["fundamental_score"] == 82.0
    assert "当前无可用综合评分" not in str(item["data_quality_note"])


def test_export_watchlist_contains_score_and_valuation_fields(tmp_path: Path) -> None:
    """watchlist CSV/JSON/Markdown should include latest score, PE/PB, and factor fields."""
    settings = _settings(tmp_path)
    store = _seed_watchlist_store(tmp_path, with_score=True)

    result = export_watchlist(output_dir=tmp_path / "reports", report_format="all", quiet=True, settings=settings, store=store)
    payload = json.loads(Path(result["generated_files"]["json"]).read_text(encoding="utf-8"))
    csv_text = Path(result["generated_files"]["csv"]).read_text(encoding="utf-8-sig")
    markdown = Path(result["generated_files"]["markdown"]).read_text(encoding="utf-8")
    item = payload["watchlist"][0]

    assert item["total_score"] == 64.01
    assert item["pe"] == 22.5
    assert item["pb"] == 3.1
    assert item["fundamental_score"] == 82.0
    assert "score_missing_reason" in csv_text
    assert "fundamental_score" in markdown
    assert "当前无可用综合评分" not in str(item["data_quality_note"])


def test_missing_score_has_specific_reason(tmp_path: Path) -> None:
    """Missing latest score should produce a specific local reason."""
    settings = _settings(tmp_path)
    store = _seed_watchlist_store(tmp_path, with_score=False)
    with store.connect() as connection:
        connection.execute("DELETE FROM daily_price")

    result = diagnose_watchlist(settings=settings, store=store)
    item = result["watchlist"][0]

    assert item["total_score"] is None
    assert item["score_missing_reason"]
    assert "缺少本地行情数据" in item["score_missing_reason"]


def test_refresh_watchlist_scores_dry_run_does_not_write_snapshot(tmp_path: Path) -> None:
    """--dry-run should preview latest scores without writing watchlist_snapshots."""
    settings = _settings(tmp_path)
    store = _seed_watchlist_store(tmp_path, with_score=True)

    result = refresh_watchlist_scores(dry_run=True, quiet=True, settings=settings, store=store)
    snapshots = read_watchlist_snapshots(store)

    assert result["refreshed_count"] == 1
    assert result["snapshot_written"] is False
    assert snapshots.empty


def test_refresh_watchlist_scores_writes_latest_snapshot(tmp_path: Path) -> None:
    """refresh_watchlist_scores should write latest score, PE/PB, and close to snapshots."""
    settings = _settings(tmp_path)
    store = _seed_watchlist_store(tmp_path, with_score=True)

    result = refresh_watchlist_scores(quiet=True, settings=settings, store=store)
    snapshots = read_watchlist_snapshots(store)

    assert result["snapshot_written"] is True
    assert snapshots.iloc[0]["total_score"] == 64.01
    assert snapshots.iloc[0]["pe"] == 22.5
    assert snapshots.iloc[0]["pb"] == 3.1
    assert snapshots.iloc[0]["latest_close"] == 30.0


def test_track_watchlist_report_contains_score_pe_pb_changes(tmp_path: Path) -> None:
    """Tracking report should include score_change, pe_change, and pb_change."""
    settings = _settings(tmp_path)
    store = _seed_watchlist_store(tmp_path, with_score=True)
    track_watchlist(snapshot_date="20240627", quiet=True, settings=settings, store=store)
    store.upsert_dataframe(
        "daily_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": "002475.SZ",
                    "trade_date": "20240628",
                    "turnover_rate": 1.8,
                    "volume_ratio": None,
                    "pe": 24.5,
                    "pb": 3.4,
                    "ps": None,
                    "total_mv": 210000000000,
                    "circ_mv": 205000000000,
                }
            ]
        ),
    )
    store.upsert_dataframe(
        "factor_scores",
        pd.DataFrame(
            [
                {
                    "ts_code": "002475.SZ",
                    "trade_date": "20240628",
                    "trend_score": 72.0,
                    "momentum_score": 66.0,
                    "liquidity_score": 76.0,
                    "fundamental_score": 84.0,
                    "volatility_score": 56.0,
                    "total_score": 68.01,
                }
            ]
        ),
    )
    track_watchlist(snapshot_date="20240628", quiet=True, settings=settings, store=store)

    result = export_watchlist_tracking_report(output_dir=tmp_path / "reports", report_format="all", quiet=True, settings=settings, store=store)
    payload = json.loads(Path(result["generated_files"]["json"]).read_text(encoding="utf-8"))
    csv_text = Path(result["generated_files"]["csv"]).read_text(encoding="utf-8-sig")
    item = payload["items"][0]

    assert item["score_change"] == 4.0
    assert item["pe_change"] == 2.0
    assert item["pb_change"] == 0.2999999999999998
    assert "score_change" in csv_text
    assert "pe_change" in csv_text
    assert "pb_change" in csv_text
