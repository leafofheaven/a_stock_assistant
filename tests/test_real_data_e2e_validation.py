"""Real-data E2E validation tests using temporary DuckDB and mock data."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core.jobs.diagnose_real_data import diagnose_real_data
from core.jobs.run_daily_selection import run_daily_selection
from core.jobs.run_daily_workflow import run_daily_workflow
from core.storage.duckdb_store import DuckDBStore


class MockSettings:
    """Settings-like object for E2E validation tests."""

    data_provider = "tushare"
    default_top_n = 3
    duckdb_path = Path("unused.duckdb")
    real_data_sample_symbols = "000001.SZ,600000.SH,000002.SZ"
    akshare_sample_symbols = "000001,600000,000002"

    @property
    def sample_symbols(self) -> list[str]:
        """Return Tushare-style sample symbols."""
        return ["000001.SZ", "600000.SH", "000002.SZ"]

    @property
    def akshare_symbols(self) -> list[str]:
        """Return AKShare-style sample symbols."""
        return ["000001", "600000", "000002"]


def test_diagnose_real_data_identifies_missing_database(tmp_path: Path) -> None:
    """Diagnosis should explain an empty or missing DuckDB store clearly."""
    store = DuckDBStore(tmp_path / "missing.duckdb")

    result = diagnose_real_data(settings=MockSettings(), store=store)

    assert result["data_provider"] == "tushare"
    assert result["table_rows"]["daily_price"] == 0
    assert result["latest_price_date"] is None
    assert result["is_ready_for_selection"] is False
    assert any("DuckDB 文件不存在" in reason for reason in result["reasons"])


def test_diagnose_real_data_identifies_ready_database(tmp_path: Path) -> None:
    """Diagnosis should report row counts, latest date, and sample symbol coverage."""
    store = _store_with_mock_real_data(tmp_path)

    result = diagnose_real_data(settings=MockSettings(), store=store)

    assert result["table_rows"]["stock_basic"] == 3
    assert result["table_rows"]["daily_price"] == 75
    assert result["latest_price_date"] == "20240202"
    assert all(result["sample_symbol_coverage"].values())
    assert result["missing_fields"]["daily_price"] == []
    assert result["is_ready_for_selection"] is True


def test_run_daily_selection_with_real_mock_data_generates_candidates(tmp_path: Path) -> None:
    """Real-data path should run stock pool, factors, scoring, selection, and DB persistence."""
    store = _store_with_mock_real_data(tmp_path)

    summary = run_daily_selection(settings=MockSettings(), store=store)

    assert "真实数据" in summary["data_source"]
    assert summary["candidate_count"] > 0
    assert summary["top_candidates"]
    assert "最新行情日期" in summary["result_location"]
    assert summary["factor_scores_written_rows"] > 0
    assert summary["factor_scores_written_rows"] == summary["stock_pool_count"]
    assert summary["strategy_result_written_rows"] == summary["candidate_count"]
    assert summary["local_display_selection_count"] == summary["candidate_count"]
    assert summary["wrote_to_database"] is True
    strategy_result = store.read_table("strategy_result")
    factor_scores = store.read_table("factor_scores")
    latest_strategy = strategy_result[strategy_result["trade_date"].astype(str) == summary["latest_price_date"]]
    assert len(latest_strategy) == summary["candidate_count"]
    assert len(factor_scores) == summary["scored_stock_count"]
    assert {"close", "pe", "pb", "created_at", "updated_at"}.issubset(strategy_result.columns)


def test_run_daily_selection_replaces_strategy_result_for_latest_date(tmp_path: Path) -> None:
    """Persisted strategy_result should not retain stale ranks when top_n shrinks."""
    store = _store_with_mock_real_data(tmp_path)

    first = run_daily_selection(settings=MockSettings(), store=store, top_n=3)
    second = run_daily_selection(settings=MockSettings(), store=store, top_n=1)

    strategy_result = store.read_table("strategy_result")
    latest_rows = strategy_result[strategy_result["trade_date"].astype(str) == second["latest_price_date"]]
    assert first["strategy_result_written_rows"] == 3
    assert second["strategy_result_written_rows"] == 1
    assert len(latest_rows) == 1
    assert latest_rows["rank"].tolist() == [1]


def test_run_daily_selection_falls_back_to_sample_when_real_data_insufficient(tmp_path: Path) -> None:
    """Insufficient real data should not crash and should clearly fall back to sample."""
    store = DuckDBStore(tmp_path / "partial.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "symbol": ["000001"],
                "name": ["平安银行"],
                "area": ["深圳"],
                "industry": ["银行"],
                "market": ["主板"],
                "list_date": ["19910403"],
                "delist_date": [None],
                "is_hs": ["S"],
            }
        ),
    )

    summary = run_daily_selection(settings=MockSettings(), store=store)

    assert "sample" in summary["data_source"]
    assert "已回退 sample 数据" in summary["result_location"]
    assert summary["candidate_count"] > 0


def test_run_daily_workflow_skip_update_persists_latest_strategy_result(tmp_path: Path) -> None:
    """Workflow success should include DB-persisted strategy_result rows for Streamlit."""
    store = _store_with_mock_real_data(tmp_path)
    report_dir = tmp_path / "reports"

    result = run_daily_workflow(
        skip_update=True,
        top_n=2,
        report_format="json",
        report_dir=report_dir,
        watchlist_tracking=False,
        quiet=True,
        settings=MockSettings(),
        store=store,
        step_overrides={
            "refresh_watchlist_scores": lambda: {"status": "dry_run", "updated_count": 0},
            "diagnose_watchlist": lambda: {"status": "success", "active_count": 0},
            "export_watchlist": lambda: {"status": "success", "generated_files": {"json": str(report_dir / "watchlist.json")}, "items": []},
        },
    )

    assert result["status"] == "success"
    selection_step = result["steps"]["run_daily_selection"]["result"]
    assert selection_step["local_display_selection_count"] == selection_step["candidate_count"]
    strategy_result = store.read_table("strategy_result")
    latest_trade_date = str(strategy_result["trade_date"].dropna().astype(str).max())
    latest_rows = strategy_result[strategy_result["trade_date"].astype(str) == latest_trade_date]
    payload = json.loads(Path(result["report_paths"]["json"]).read_text(encoding="utf-8"))
    assert latest_trade_date == selection_step["latest_price_date"]
    assert len(latest_rows) == 2
    assert len(payload["top_candidates"]) == len(latest_rows)


def test_run_daily_workflow_marks_partial_when_candidates_are_not_persisted(tmp_path: Path) -> None:
    """Real candidates without local display rows should not be reported as full success."""
    report_dir = tmp_path / "reports"
    result = run_daily_workflow(
        skip_update=True,
        report_format="json",
        report_dir=report_dir,
        watchlist_tracking=False,
        quiet=True,
        settings=MockSettings(),
        store=DuckDBStore(tmp_path / "empty.duckdb"),
        step_overrides={
            "diagnose_data_quality": lambda: {"status": "success", "latest_price_date": "20240202"},
            "diagnose_factors": lambda: {"total_score_non_null_count": 1},
            "run_daily_selection": lambda: {
                "is_real_data": True,
                "candidate_count": 1,
                "top_candidates": [{"rank": 1, "ts_code": "000001.SZ", "name": "平安银行", "total_score": 80.0}],
                "latest_price_date": "20240202",
                "strategy_result_written_rows": 0,
                "factor_scores_written_rows": 1,
                "local_display_selection_count": 0,
            },
            "export_selection_review": lambda: {"status": "success", "generated_files": {"json": str(report_dir / "selection_review.json")}, "report": {"candidates": []}},
            "refresh_watchlist_scores": lambda: {"status": "dry_run", "updated_count": 0},
            "diagnose_watchlist": lambda: {"status": "success", "active_count": 0},
            "export_watchlist": lambda: {"status": "success", "generated_files": {"json": str(report_dir / "watchlist.json")}, "items": []},
        },
    )

    assert result["steps"]["run_daily_selection"]["status"] == "partial_success"
    assert result["status"] == "partial_success"


def test_readme_documents_real_data_e2e_commands() -> None:
    """README should document the real-data E2E validation commands."""
    readme = Path("README.md").read_text(encoding="utf-8")

    for text in [
        "python -m core.jobs.update_real_data",
        "python -m core.jobs.diagnose_real_data",
        "python -m core.jobs.run_daily_selection",
        "streamlit run web/streamlit_app.py",
        "真实数据端到端验证",
    ]:
        assert text in readme


def _store_with_mock_real_data(tmp_path: Path) -> DuckDBStore:
    """Create a temporary DuckDB store with enough mock rows for real path tests."""
    store = DuckDBStore(tmp_path / "real-e2e.duckdb")
    store.initialize()
    symbols = ["000001.SZ", "600000.SH", "000002.SZ"]
    dates = pd.bdate_range("2024-01-01", periods=25).strftime("%Y%m%d").tolist()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            {
                "ts_code": symbols,
                "symbol": ["000001", "600000", "000002"],
                "name": ["平安银行", "浦发银行", "万科A"],
                "area": ["深圳", "上海", "深圳"],
                "industry": ["银行", "银行", "房地产"],
                "market": ["主板", "主板", "主板"],
                "list_date": ["19910403", "19991110", "19910129"],
                "delist_date": [None, None, None],
                "is_hs": ["S", "H", "S"],
            }
        ),
    )
    store.upsert_dataframe(
        "trade_calendar",
        pd.DataFrame(
            {
                "exchange": ["SSE"] * len(dates),
                "cal_date": dates,
                "is_open": [1] * len(dates),
                "pretrade_date": [None, *dates[:-1]],
            }
        ),
    )
    price_rows = []
    basic_rows = []
    adj_rows = []
    for symbol_index, symbol in enumerate(symbols):
        for day_index, trade_date in enumerate(dates):
            close = 10 + symbol_index + day_index * (0.05 + symbol_index * 0.01)
            price_rows.append(
                {
                    "ts_code": symbol,
                    "trade_date": trade_date,
                    "open": close - 0.02,
                    "high": close + 0.1,
                    "low": close - 0.1,
                    "close": close,
                    "pre_close": close - 0.05,
                    "change": 0.05,
                    "pct_chg": 0.5,
                    "vol": 1_000_000.0 + symbol_index,
                    "amount": 200_000_000.0 + day_index * 1_000_000,
                }
            )
            basic_rows.append(
                {
                    "ts_code": symbol,
                    "trade_date": trade_date,
                    "turnover_rate": 1.0 + symbol_index * 0.1,
                    "volume_ratio": 1.0,
                    "pe": 8.0 + symbol_index,
                    "pb": 0.8 + symbol_index * 0.1,
                    "ps": 1.0,
                    "total_mv": 100_000_000_000.0,
                    "circ_mv": 80_000_000_000.0,
                }
            )
            adj_rows.append({"ts_code": symbol, "trade_date": trade_date, "adj_factor": 1.0})
    store.upsert_dataframe("daily_price", pd.DataFrame(price_rows))
    store.upsert_dataframe("daily_basic", pd.DataFrame(basic_rows))
    store.upsert_dataframe("adj_factor", pd.DataFrame(adj_rows))
    return store
