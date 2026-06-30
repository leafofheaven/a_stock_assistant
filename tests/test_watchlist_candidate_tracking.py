"""Tests for Task 48 watchlist candidate tracking with temporary duckdb mock data."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.jobs.export_watchlist_tracking import export_watchlist_tracking_report
from core.jobs.refresh_watchlist_from_selection import refresh_watchlist_from_selection
from core.jobs.track_watchlist import track_watchlist
from core.review.tracking import _build_watchlist_events, read_watchlist_daily_snapshots, read_watchlist_events
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import enrich_selection_with_watchlist_status, summarize_watchlist_snapshot


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_provider="sample",
        duckdb_path=tmp_path / "task48.duckdb",
        default_top_n=1,
        akshare_sample_symbols="",
        real_data_sample_symbols="",
        real_universe_preset="mini",
    )


def _seed_factor_scores(store: DuckDBStore) -> None:
    store.initialize()
    rows = [
        _score("000001.SZ", "20240101", 1, 90.0),
        _score("000002.SZ", "20240101", 2, 80.0),
        _score("000002.SZ", "20240102", 1, 92.0),
        _score("000001.SZ", "20240102", 2, 70.0),
        _score("000002.SZ", "20240103", 1, 93.0),
        _score("000001.SZ", "20240103", 2, 69.0),
        _score("000002.SZ", "20240104", 1, 94.0),
        _score("000001.SZ", "20240104", 2, 68.0),
        _score("000002.SZ", "20240105", 1, 95.0),
        _score("000001.SZ", "20240105", 2, 67.0),
    ]
    strategy_rows = [
        {
            "trade_date": row["trade_date"],
            "rank": row["rank"],
            "ts_code": row["ts_code"],
            "name": "平安银行" if row["ts_code"] == "000001.SZ" else "万科A",
            "industry": "银行" if row["ts_code"] == "000001.SZ" else "地产",
            "total_score": row["total_score"],
            "select_reason": "mock candidate",
            "risk_note": "mock",
        }
        for row in rows
    ]
    store.upsert_dataframe("strategy_result", pd.DataFrame(strategy_rows))
    price_rows = [
        {
            "ts_code": row["ts_code"],
            "trade_date": row["trade_date"],
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.0 + row["rank"],
            "pre_close": 10.0,
            "change": 0.2,
            "pct_chg": 1.0,
            "vol": 100000,
            "amount": 120000000,
        }
        for row in rows
    ]
    store.upsert_dataframe("daily_price", pd.DataFrame(price_rows))


def _score(ts_code: str, trade_date: str, rank: int, total_score: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "trend_score": total_score,
        "momentum_score": total_score,
        "liquidity_score": total_score,
        "volatility_score": total_score,
        "fundamental_score": total_score,
        "total_score": total_score,
        "rank": rank,
    }


def test_refresh_watchlist_from_selection_adds_new_candidate_once(tmp_path: Path) -> None:
    """Today's top candidate should enter active watch once, not duplicate on rerun."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_factor_scores(store)

    first = refresh_watchlist_from_selection(trade_date="20240101", top_n=1, quiet=True, settings=settings, store=store)
    second = refresh_watchlist_from_selection(trade_date="20240101", top_n=1, quiet=True, settings=settings, store=store)
    decisions = store.read_table("review_decisions")

    assert first["new_candidate_count"] == 1
    assert second["new_candidate_count"] == 0
    assert len(decisions[(decisions["ts_code"] == "000001.SZ") & (decisions["decision"] == "watch")]) == 1


def test_watchlist_keeps_stock_after_it_drops_out_of_top_n(tmp_path: Path) -> None:
    """A watched stock should stay tracked after dropping out of today's Top-N."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_factor_scores(store)

    refresh_watchlist_from_selection(trade_date="20240101", top_n=1, quiet=True, settings=settings, store=store)
    result = refresh_watchlist_from_selection(trade_date="20240102", top_n=1, quiet=True, settings=settings, store=store)
    snapshots = read_watchlist_daily_snapshots(store)
    day2 = snapshots[snapshots["trade_date"] == "20240102"]
    dropped = day2[day2["ts_code"] == "000001.SZ"].iloc[0]

    assert result["snapshot_count"] == 2
    assert bool(dropped["top_n_flag"]) is False
    assert dropped["today_rank"] == 2


def test_selection_counts_rank_change_and_events_are_recorded(tmp_path: Path) -> None:
    """Selection counts, consecutive days, rank changes, and events should be persisted."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_factor_scores(store)

    refresh_watchlist_from_selection(trade_date="20240101", top_n=1, quiet=True, settings=settings, store=store)
    refresh_watchlist_from_selection(trade_date="20240102", top_n=1, quiet=True, settings=settings, store=store)
    refresh_watchlist_from_selection(trade_date="20240103", top_n=1, quiet=True, settings=settings, store=store)
    refresh_watchlist_from_selection(trade_date="20240104", top_n=1, quiet=True, settings=settings, store=store)
    refresh_watchlist_from_selection(trade_date="20240105", top_n=1, quiet=True, settings=settings, store=store)
    latest = read_watchlist_daily_snapshots(store)
    row = latest[(latest["trade_date"] == "20240105") & (latest["ts_code"] == "000002.SZ")].iloc[0]
    events = read_watchlist_events(store)

    assert row["selected_count_5d"] == 4
    assert row["selected_count_10d"] == 4
    assert row["consecutive_selected_days"] == 4
    assert row["best_rank"] == 1
    assert "new_candidate" in set(events["event_type"])


def test_track_and_export_watchlist_tracking_outputs_reports(tmp_path: Path) -> None:
    """track_watchlist and export_watchlist_tracking should use Task 48 daily snapshots."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_factor_scores(store)

    track_watchlist(snapshot_date="20240102", quiet=True, settings=settings, store=store)
    result = export_watchlist_tracking_report(
        output_dir=tmp_path / "reports",
        report_format="markdown",
        quiet=True,
        settings=settings,
        store=store,
    )
    markdown = Path(result["generated_files"]["markdown"]).read_text(encoding="utf-8")

    assert "观察池变化报告" in markdown
    assert "watch_status" in result["report"]["items"][0]


def test_streamlit_watchlist_helpers_enrich_selection_rows(tmp_path: Path) -> None:
    """Streamlit helpers should expose watchlist state for today's selection table."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    _seed_factor_scores(store)
    refresh_watchlist_from_selection(trade_date="20240101", top_n=1, quiet=True, settings=settings, store=store)
    snapshot = read_watchlist_daily_snapshots(store)
    selection = pd.DataFrame([{"ts_code": "000001.SZ", "name": "平安银行", "total_score": 90.0}])

    enriched = enrich_selection_with_watchlist_status(selection, {"_watchlist_snapshot": snapshot})
    summary = summarize_watchlist_snapshot(snapshot)

    assert bool(enriched.iloc[0]["is_in_watchlist"]) is True
    assert bool(enriched.iloc[0]["suggest_add_to_watchlist"]) is False
    assert summary["total"] == 1


def test_watchlist_events_ignore_nan_rank_change(tmp_path: Path) -> None:
    """NaN rank_change should not crash event generation."""
    settings = _settings(tmp_path)
    store = DuckDBStore(settings.duckdb_path)
    store.initialize()
    snapshots = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20240102",
                "watch_status": "active_watch",
                "new_candidate_flag": False,
                "rank_change": pd.NA,
                "total_score_change": pd.NA,
            }
        ]
    )

    events = _build_watchlist_events(store=store, snapshots=snapshots, trade_date="20240102")

    assert events.empty
