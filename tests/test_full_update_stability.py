"""Tests for Task 47 full-universe update stability and resume behavior."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.data_sources.base import DataSourceError
from core.jobs.diagnose_update_batch import diagnose_update_batch
from core.jobs.update_real_data import update_real_data
from core.runtime.progress import ProgressState
from core.storage.duckdb_store import DuckDBStore
from core.strategy.selector import select_top_stocks
from web.streamlit_app import build_date_status, summarize_update_status


class FullUpdateSettings:
    """Settings-like object for full update stability tests."""

    data_provider = "akshare"
    tushare_token = ""
    enable_akshare_fallback = False
    real_data_start_date = "20230101"
    real_data_end_date = "20240131"
    real_data_sample_symbols = ""
    akshare_sample_symbols = ""
    akshare_adjust = "qfq"
    real_universe_preset = "full"
    real_batch_size = 10
    real_batch_sleep_seconds = 0.0
    real_max_retries = 1
    real_request_timeout_seconds = 30
    full_update_batch_size = 2
    full_update_lookback_days = 40
    full_update_max_retries = 2
    full_update_sleep_seconds = 0.0
    full_update_resume = True
    enable_real_basic_enrichment = False
    enable_real_valuation_enrichment = False
    include_bse = False
    duckdb_path = Path("unused.duckdb")

    @property
    def sample_symbols(self) -> list[str]:
        return []

    @property
    def akshare_symbols(self) -> list[str]:
        return []


class NoResumeSettings(FullUpdateSettings):
    """Disable resume for one test path."""

    full_update_resume = False


class FullUpdateClient:
    """Mock AKShare-like client with controllable batch failures."""

    def __init__(self, fail_price_once_for: str | None = None) -> None:
        self.fail_price_once_for = fail_price_once_for
        self.failed_once = False
        self.price_batches: list[list[str]] = []
        self.price_requests: list[tuple[str, str, list[str]]] = []
        self.failure_records: list[dict[str, str]] = []
        self.enrichment_records: list[dict[str, str]] = []

    def get_stock_basic(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"symbol": "000001", "name": "平安银行", "list_date": "19910403"},
                {"symbol": "600000", "name": "浦发银行", "list_date": "19991110"},
                {"symbol": "300750", "name": "宁德时代", "list_date": "20180611"},
                {"symbol": "688981", "name": "中芯国际", "list_date": "20200716"},
            ]
        )

    def get_trade_calendar(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-02", periods=22, freq="B").strftime("%Y%m%d")
        return pd.DataFrame({"exchange": "SSE", "cal_date": dates, "is_open": 1, "pretrade_date": pd.NA})

    def get_daily_price(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        batch = symbols or []
        self.price_batches.append(batch)
        self.price_requests.append((start_date, end_date, batch))
        if self.fail_price_once_for in batch and not self.failed_once:
            self.failed_once = True
            raise DataSourceError("temporary mock failure")
        return _price_rows(batch, end_date=end_date)

    def get_daily_basic(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        rows = [{"ts_code": _to_ts_code(symbol), "trade_date": end_date, "turnover_rate": 1.0} for symbol in (symbols or [])]
        result = pd.DataFrame(rows)
        for column in ["volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]:
            result[column] = 1.0
        return result

    def get_adj_factor(self, start_date: str, end_date: str, symbols: list[str] | None = None) -> pd.DataFrame:
        return pd.DataFrame(
            [{"ts_code": _to_ts_code(symbol), "trade_date": end_date, "adj_factor": 1.0} for symbol in (symbols or [])]
        )


class BlockingBasicEnrichmentClient(FullUpdateClient):
    """Client that fails if per-symbol basic enrichment is called."""

    def enrich_stock_basic(self, stock_basic: pd.DataFrame, symbols: list[str] | None = None) -> pd.DataFrame:
        raise AssertionError("stock_individual_info_em should not run in full mode by default")


def test_full_update_uses_batches_and_progress(tmp_path: Path) -> None:
    """full mode should split requests into batches and emit readable progress."""
    client = FullUpdateClient()
    progress: list[ProgressState] = []

    result = update_real_data(
        settings=FullUpdateSettings(),
        store=DuckDBStore(tmp_path / "full-batch.duckdb"),
        client=client,
        progress=progress.append,
    )

    assert result["status"] == "success"
    assert result["total_symbols"] == 4
    assert result["effective_batch_size"] == 2
    assert result["full_update_lookback_days"] == 40
    assert client.price_batches == [["000001", "600000"], ["300750", "688981"]]
    assert any(state.step == "daily_price" and "第 1/2 批" in state.message for state in progress)
    assert any(state.step == "daily_price" and state.success >= 2 for state in progress)
    assert any("开始解析 沪深 A 股全市场" in state.message for state in progress)
    assert not any("开始更新 0 只样本股票" in state.message for state in progress)


def test_full_update_skips_per_symbol_basic_enrichment_by_default(tmp_path: Path) -> None:
    """full mode should not call stock_individual_info_em before market data updates."""
    client = BlockingBasicEnrichmentClient()

    result = update_real_data(
        settings=FullUpdateSettings(),
        store=DuckDBStore(tmp_path / "full-no-basic-enrichment.duckdb"),
        client=client,
    )

    assert result["status"] == "success"
    assert result["success_symbols"] == 4
    assert client.price_batches


def test_full_update_resume_skips_symbols_already_current(tmp_path: Path) -> None:
    """Resume mode should skip symbols whose local daily_price already reaches end_date."""
    store = DuckDBStore(tmp_path / "full-resume.duckdb")
    store.initialize()
    store.upsert_dataframe("daily_price", _price_rows(["000001"], end_date="20240131"))
    store.upsert_dataframe("daily_basic", _daily_basic_rows(["000001"], trade_date="20240131"))
    store.upsert_dataframe("adj_factor", _adj_factor_rows(["000001"], trade_date="20240131"))
    client = FullUpdateClient()

    result = update_real_data(settings=FullUpdateSettings(), store=store, client=client)

    requested = [symbol for batch in client.price_batches for symbol in batch]
    assert "000001" not in requested
    assert result["skipped_symbols"] == 1
    assert result["failed_symbols"] == 0
    assert result["completion_rate"] == 1.0


def test_full_update_global_max_date_does_not_hide_missing_symbols(tmp_path: Path) -> None:
    """A current global max trade date must not skip full-universe symbols with no rows."""
    store = DuckDBStore(tmp_path / "full-global-max.duckdb")
    store.initialize()
    store.upsert_dataframe("daily_price", _price_rows(["000001"], end_date="20240131"))
    store.upsert_dataframe("daily_basic", _daily_basic_rows(["000001"], trade_date="20240131"))
    store.upsert_dataframe("adj_factor", _adj_factor_rows(["000001"], trade_date="20240131"))
    client = FullUpdateClient()

    result = update_real_data(settings=FullUpdateSettings(), store=store, client=client)

    requested = [symbol for batch in client.price_batches for symbol in batch]
    assert "000001" not in requested
    assert {"600000", "300750", "688981"}.issubset(set(requested))
    assert result["skipped_symbols"] == 1
    assert result["initial_update_symbols"] == 3
    assert result["full_universe_symbol_count"] == 4


def test_full_update_missing_daily_basic_or_adj_factor_enters_incremental_queue(tmp_path: Path) -> None:
    """A symbol with current daily_price but missing companion tables should still update."""
    store = DuckDBStore(tmp_path / "full-companion-missing.duckdb")
    store.initialize()
    store.upsert_dataframe("daily_price", _price_rows(["000001"], end_date="20240131"))
    client = FullUpdateClient()

    result = update_real_data(settings=FullUpdateSettings(), store=store, client=client)

    requested = [symbol for batch in client.price_batches for symbol in batch]
    assert "000001" in requested
    assert result["incremental_update_symbols"] >= 1


def test_full_update_stale_symbol_uses_incremental_gap_start(tmp_path: Path) -> None:
    """Symbols with existing rows should request only the missing recent window."""
    store = DuckDBStore(tmp_path / "full-gap.duckdb")
    store.initialize()
    store.upsert_dataframe("daily_price", _price_rows(["000001"], end_date="20240115"))
    store.upsert_dataframe("daily_basic", _daily_basic_rows(["000001"], trade_date="20240115"))
    store.upsert_dataframe("adj_factor", _adj_factor_rows(["000001"], trade_date="20240115"))
    client = FullUpdateClient()

    update_real_data(settings=FullUpdateSettings(), store=store, client=client)

    starts_for_000001 = [start for start, _end, batch in client.price_requests if "000001" in batch]
    assert starts_for_000001 == ["20240116"]


def test_full_update_retry_keeps_task_running(tmp_path: Path) -> None:
    """A transient batch failure should be retried without aborting the full update."""
    client = FullUpdateClient(fail_price_once_for="600000")

    result = update_real_data(
        settings=FullUpdateSettings(),
        store=DuckDBStore(tmp_path / "full-retry.duckdb"),
        client=client,
    )

    assert client.failed_once is True
    assert result["status"] == "success"
    assert result["failed_symbols"] == 0
    assert result["success_symbols"] == 4


def test_diagnose_update_batch_reports_stale_full_symbols(tmp_path: Path) -> None:
    """Batch diagnostics should distinguish missing and stale full-universe symbols."""
    store = DuckDBStore(tmp_path / "full-stale.duckdb")
    store.initialize()
    store.upsert_dataframe("daily_price", _price_rows(["000001"], end_date="20240131"))
    store.upsert_dataframe("daily_basic", _daily_basic_rows(["000001"], trade_date="20240131"))
    store.upsert_dataframe("adj_factor", _adj_factor_rows(["000001"], trade_date="20240131"))
    store.upsert_dataframe("daily_price", _price_rows(["600000"], end_date="20240115"))

    result = diagnose_update_batch(settings=FullUpdateSettings(), store=store, client=FullUpdateClient())

    assert result["configured_symbol_count"] == 4
    assert result["priced_symbol_count"] == 2
    assert result["stale_symbol_count"] == 1
    assert result["stale_symbols"] == ["600000.SH"]
    assert set(result["missing_symbols"]) == {"300750.SZ", "688981.SH"}


def test_full_update_without_resume_refetches_existing_symbols(tmp_path: Path) -> None:
    """Disabling resume should refetch symbols even if local data is current."""
    store = DuckDBStore(tmp_path / "full-no-resume.duckdb")
    store.initialize()
    store.upsert_dataframe("daily_price", _price_rows(["000001"], end_date="20240131"))
    store.upsert_dataframe("daily_basic", _daily_basic_rows(["000001"], trade_date="20240131"))
    store.upsert_dataframe("adj_factor", _adj_factor_rows(["000001"], trade_date="20240131"))
    client = FullUpdateClient()

    result = update_real_data(settings=NoResumeSettings(), store=store, client=client)

    requested = [symbol for batch in client.price_batches for symbol in batch]
    assert "000001" in requested
    assert result["skipped_symbols"] == 0


def test_full_update_does_not_change_total_score_sorting() -> None:
    """Task 47 update stability work must not alter selection ordering."""
    scored = pd.DataFrame(
        [
            {"trade_date": "20240131", "ts_code": "000001.SZ", "total_score": 90.0},
            {"trade_date": "20240131", "ts_code": "600000.SH", "total_score": 95.0},
            {"trade_date": "20240131", "ts_code": "300750.SZ", "total_score": 80.0},
        ]
    )

    selected = select_top_stocks(scored, top_n=3)

    assert selected["ts_code"].tolist() == ["600000.SH", "000001.SZ", "300750.SZ"]


def test_streamlit_full_status_does_not_treat_global_max_date_as_complete() -> None:
    """Dashboard status should flag low full-universe coverage despite current max date."""
    status = build_date_status(
        {
            "DATA_PROVIDER": "akshare",
            "AKSHARE_SAMPLE_SYMBOLS": "",
            "REAL_UNIVERSE_PRESET": "full",
            "REAL_DATA_START_DATE": "20240101",
            "REAL_DATA_END_DATE": "20260626",
        },
        {
            "latest_price_date": "20260626",
            "latest_factor_date": "20260626",
            "latest_selection_date": "20260626",
            "configured_symbol_count": 4987,
            "priced_symbol_count": 139,
            "missing_symbol_count": 4848,
            "stale_symbol_count": 0,
        },
    )

    assert status["warning"] is True
    assert "全市场数据未完成" in status["message"]
    assert "数据库最新行情日期已达到或晚于参数结束日期" not in status["message"]


def test_streamlit_summary_exposes_full_coverage_counts() -> None:
    """Dashboard summary should expose coverage and missing counts for full mode."""
    result = summarize_update_status(
        {
            "_configured_symbol_count": 4987,
            "_priced_symbol_count": 139,
            "_missing_symbol_count": 4848,
            "_stale_symbol_count": 0,
            "_coverage_rate": 139 / 4987,
            "_batch_status": "全市场数据未完成",
            "daily_price": pd.DataFrame({"trade_date": ["20260626"]}),
            "factor_scores": pd.DataFrame(),
            "strategy_result": pd.DataFrame(),
        }
    )

    assert result["configured_symbol_count"] == 4987
    assert result["priced_symbol_count"] == 139
    assert result["missing_symbol_count"] == 4848
    assert result["batch_status"] == "全市场数据未完成"


def _price_rows(symbols: list[str], *, end_date: str) -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-01-02", end=pd.to_datetime(end_date), freq="B").strftime("%Y%m%d")
    for symbol in symbols:
        for trade_date in dates:
            rows.append(
                {
                    "ts_code": _to_ts_code(symbol),
                    "trade_date": trade_date,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "pre_close": 10.0,
                    "change": 0.5,
                    "pct_chg": 5.0,
                    "vol": 1_000_000,
                    "amount": 150_000_000,
                }
            )
    return pd.DataFrame(rows)


def _daily_basic_rows(symbols: list[str], *, trade_date: str) -> pd.DataFrame:
    result = pd.DataFrame([{"ts_code": _to_ts_code(symbol), "trade_date": trade_date, "turnover_rate": 1.0} for symbol in symbols])
    for column in ["volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"]:
        result[column] = 1.0
    return result


def _adj_factor_rows(symbols: list[str], *, trade_date: str) -> pd.DataFrame:
    return pd.DataFrame([{"ts_code": _to_ts_code(symbol), "trade_date": trade_date, "adj_factor": 1.0} for symbol in symbols])


def _to_ts_code(symbol: str) -> str:
    clean = str(symbol).strip()
    if "." in clean:
        return clean
    return f"{clean}.SH" if clean.startswith("6") or clean.startswith("688") else f"{clean}.SZ"
