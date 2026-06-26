"""Real-data E2E validation tests using temporary DuckDB and mock data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.jobs.diagnose_real_data import diagnose_real_data
from core.jobs.run_daily_selection import run_daily_selection
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
    """Real-data path should run stock pool, factors, scoring, and selection."""
    store = _store_with_mock_real_data(tmp_path)

    summary = run_daily_selection(settings=MockSettings(), store=store)

    assert "真实数据" in summary["data_source"]
    assert summary["candidate_count"] > 0
    assert summary["top_candidates"]
    assert "最新行情日期" in summary["result_location"]


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
