"""Tests for real universe presets and batch update diagnostics with temporary duckdb."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.data_sources.universe_presets import get_universe_preset, to_ts_code
from core.jobs.diagnose_update_batch import diagnose_update_batch
from core.jobs.run_daily_selection import run_daily_selection
from core.jobs.update_real_data import update_real_data
from core.storage.duckdb_store import DuckDBStore


class BatchSettings:
    """Settings-like object for batch update tests."""

    data_provider = "akshare"
    tushare_token = ""
    enable_akshare_fallback = False
    real_data_start_date = "20240101"
    real_data_end_date = "20240105"
    real_data_sample_symbols = ""
    akshare_sample_symbols = "000001,600000,000002"
    real_universe_preset = "mini"
    real_batch_size = 2
    real_batch_sleep_seconds = 0.0
    real_max_retries = 1
    real_request_timeout_seconds = 30
    duckdb_path = Path("unused.duckdb")
    default_top_n = 30

    @property
    def sample_symbols(self) -> list[str]:
        """Return no Tushare symbols."""
        return []

    @property
    def akshare_symbols(self) -> list[str]:
        """Return explicit AKShare symbols or preset symbols."""
        explicit = [symbol.strip() for symbol in self.akshare_sample_symbols.split(",") if symbol.strip()]
        if explicit:
            return explicit
        return get_universe_preset(self.real_universe_preset)


class SmallPresetSettings(BatchSettings):
    """Settings using the small preset."""

    akshare_sample_symbols = ""
    real_universe_preset = "small"


class SampleSettings:
    """Settings-like object for sample smoke test."""

    data_provider = "sample"


class MockBatchClient:
    """Mock data client with per-symbol failures; no real network calls."""

    def __init__(self, fail_symbols: set[str] | None = None, empty_all: bool = False) -> None:
        self.fail_symbols = fail_symbols or set()
        self.empty_all = empty_all
        self.failure_records: list[dict[str, str]] = []

    def get_stock_basic(self) -> pd.DataFrame:
        """Return stock basic rows for known symbols."""
        symbols = ["000001", "600000", "000002", *get_universe_preset("small")]
        unique = list(dict.fromkeys(symbols))
        return pd.DataFrame(
            [
                {
                    "ts_code": to_ts_code(symbol),
                    "symbol": symbol,
                    "name": f"样本{symbol}",
                    "area": None,
                    "industry": "测试",
                    "market": None,
                    "list_date": None,
                    "delist_date": None,
                    "is_hs": None,
                }
                for symbol in unique
            ]
        )

    def get_trade_calendar(self) -> pd.DataFrame:
        """Return a small trade calendar."""
        return pd.DataFrame(
            {
                "exchange": ["SSE"] * 3,
                "cal_date": ["20240102", "20240103", "20240104"],
                "is_open": [1, 1, 1],
                "pretrade_date": [None, "20240102", "20240103"],
            }
        )

    def get_daily_price(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        """Return daily price rows for successful symbols."""
        return self._daily_rows(symbols or [], include_price=True)

    def get_daily_basic(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        """Return daily basic rows for successful symbols."""
        rows = self._daily_rows(symbols or [], include_price=False)
        if rows.empty:
            return pd.DataFrame(
                columns=["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]
            )
        rows["turnover_rate"] = 1.0
        for column in ["volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]:
            rows[column] = pd.NA
        return rows[["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]]

    def get_adj_factor(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        """Return default adj factors."""
        rows = [
            {"ts_code": to_ts_code(symbol), "trade_date": start_date, "adj_factor": 1.0}
            for symbol in (symbols or [])
            if not self._should_fail(symbol)
        ]
        return pd.DataFrame(rows)

    def _daily_rows(self, symbols: list[str], include_price: bool) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for symbol in symbols:
            if self._should_fail(symbol):
                self.failure_records.append(
                    {
                        "symbol": to_ts_code(symbol),
                        "provider": "akshare",
                        "failed_stage": "stock_zh_a_hist",
                        "error_message": "mock failure",
                    }
                )
                continue
            for index, trade_date in enumerate(["20240102", "20240103", "20240104"]):
                row: dict[str, Any] = {"ts_code": to_ts_code(symbol), "trade_date": trade_date}
                if include_price:
                    row.update(
                        {
                            "open": 10 + index,
                            "high": 10.5 + index,
                            "low": 9.5 + index,
                            "close": 10.2 + index,
                            "pre_close": None,
                            "change": 0.1,
                            "pct_chg": 1.0,
                            "vol": 1000,
                            "amount": 150_000_000,
                        }
                    )
                rows.append(row)
        return pd.DataFrame(rows)

    def _should_fail(self, symbol: str) -> bool:
        return self.empty_all or symbol in self.fail_symbols or to_ts_code(symbol) in self.fail_symbols


def test_universe_presets_include_expected_sizes_and_markets() -> None:
    """mini, small, and medium presets should be static and progressively larger."""
    mini = get_universe_preset("mini")
    small = get_universe_preset("small")
    medium = get_universe_preset("medium")

    assert len(mini) == 3
    assert len(small) >= 30
    assert len(medium) >= 100
    assert "300750" in medium
    assert "688981" in medium
    assert to_ts_code("600000") == "600000.SH"
    assert to_ts_code("300750") == "300750.SZ"


def test_akshare_sample_symbols_take_priority_over_preset(tmp_path: Path) -> None:
    """Explicit AKSHARE_SAMPLE_SYMBOLS should override REAL_UNIVERSE_PRESET."""
    store = DuckDBStore(tmp_path / "priority.duckdb")

    result = update_real_data(settings=BatchSettings(), store=store, client=MockBatchClient())

    assert result["total_symbols"] == 3
    assert result["sample_symbols"] == ["000001", "600000", "000002"]
    assert result["status"] == "success"


def test_preset_symbols_are_used_when_akshare_symbols_empty(tmp_path: Path) -> None:
    """Empty AKSHARE_SAMPLE_SYMBOLS should use REAL_UNIVERSE_PRESET."""
    store = DuckDBStore(tmp_path / "preset.duckdb")

    result = update_real_data(settings=SmallPresetSettings(), store=store, client=MockBatchClient())

    assert result["total_symbols"] >= 30
    assert result["success_symbols"] >= 30
    assert result["status"] == "success"


def test_partial_symbol_failure_returns_partial_success(tmp_path: Path) -> None:
    """One failed symbol should not prevent successful symbols from being written."""
    store = DuckDBStore(tmp_path / "partial.duckdb")
    client = MockBatchClient(fail_symbols={"600000"})

    result = update_real_data(settings=BatchSettings(), store=store, client=client)

    assert result["status"] == "partial_success"
    assert result["success_symbols"] == 2
    assert result["failed_symbols"] == 1
    assert "600000.SH" in result["empty_data_symbols"]
    assert result["failure_records"]
    assert len(store.read_table("daily_price")) == 6


def test_all_symbol_failures_return_failed(tmp_path: Path) -> None:
    """All failed symbols should return failed status with clear records."""
    store = DuckDBStore(tmp_path / "failed.duckdb")

    result = update_real_data(settings=BatchSettings(), store=store, client=MockBatchClient(empty_all=True))

    assert result["status"] == "failed"
    assert result["success_symbols"] == 0
    assert result["failed_symbols"] == 3
    assert len(result["failure_records"]) >= 3


def test_repeated_batch_update_does_not_duplicate_rows(tmp_path: Path) -> None:
    """Repeated update should upsert by keys instead of appending duplicates."""
    store = DuckDBStore(tmp_path / "repeat.duckdb")
    client = MockBatchClient()

    first = update_real_data(settings=BatchSettings(), store=store, client=client)
    second = update_real_data(settings=BatchSettings(), store=store, client=client)

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert len(store.read_table("daily_price")) == 9


def test_diagnose_update_batch_reports_coverage(tmp_path: Path) -> None:
    """diagnose_update_batch should report coverage after a partial update."""
    store = DuckDBStore(tmp_path / "diagnose.duckdb")
    update_real_data(settings=BatchSettings(), store=store, client=MockBatchClient(fail_symbols={"600000"}))

    result = diagnose_update_batch(settings=BatchSettings(), store=store)

    assert result["sample_source"] == "AKSHARE_SAMPLE_SYMBOLS"
    assert result["configured_symbol_count"] == 3
    assert result["priced_symbol_count"] == 2
    assert result["coverage_rate"] == 2 / 3
    assert result["missing_symbols"] == ["600000.SH"]
    assert result["factor_ready_count"] == 0


def test_sample_smoke_still_runs_with_batch_update_work() -> None:
    """sample smoke test should remain available."""
    summary = run_daily_selection(settings=SampleSettings(), use_sample=True)

    assert "sample" in summary["data_source"]
    assert summary["candidate_count"] > 0
