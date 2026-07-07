"""Task 57I missing-latest skip/retry queue tests."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.jobs.doctor_daily_run import doctor_daily_run, render_console
from core.jobs.market_data_progress import read_market_data_progress
from core.jobs.missing_latest_retry_queue import (
    excluded_symbols_for_main_scan,
    queue_counts,
    read_missing_latest_queue,
    record_failure_records,
    retry_symbols,
)
from core.jobs.update_market_data import _continue_missing_latest_symbol_plan, run_batched_update_parent, update_market_data
from core.storage.duckdb_store import DuckDBStore


def test_no_data_stock_enters_skip_queue(tmp_path: Path) -> None:
    queue_path = tmp_path / "missing_latest_retry_queue.json"

    record_failure_records(
        queue_path,
        trade_date="20260706",
        failure_records=[{"symbol": "000024.SZ", "failure_type": "no_data"}],
    )

    queue = read_missing_latest_queue(queue_path)
    assert queue["skip_queue"]["000024.SZ"]["reason"] == "no_data"
    assert queue["skip_queue"]["000024.SZ"]["status"] == "cooldown"
    assert queue_counts(queue_path, trade_date="20260706")["skip_queue_count"] == 1


def test_continue_missing_latest_skips_skip_queue_and_moves_forward(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, ["000024.SZ", "000025.SZ", "000026.SZ"])
    queue_path = tmp_path / "queue.json"
    record_failure_records(queue_path, trade_date="20260706", failure_records=[{"symbol": "000024.SZ", "failure_type": "no_data"}])

    plan = _continue_missing_latest_symbol_plan(
        end_date="20260706",
        symbols=["000024.SZ", "000025.SZ", "000026.SZ"],
        store=store,
        batch_size=1,
        skip_queue_path=queue_path,
        respect_skip_queue=True,
    )

    assert plan["symbols"] == ["000025.SZ"]
    assert plan["queue_excluded_symbol_count"] == 1


def test_success_stock_disappears_from_gap_plan(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, ["000001.SZ", "000002.SZ"])
    store.upsert_dataframe("daily_price", _price_rows(["000001.SZ"], "20260706"))
    store.upsert_dataframe("daily_basic", pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260706", "turnover_rate": 1.0}]))

    plan = _continue_missing_latest_symbol_plan(
        end_date="20260706",
        symbols=["000001.SZ", "000002.SZ"],
        store=store,
        batch_size=10,
        skip_queue_path=tmp_path / "queue.json",
    )

    assert plan["symbols"] == ["000002.SZ"]
    assert "000001.SZ" not in plan["symbols"]


def test_retry_skip_queue_has_limited_attempts(tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    record_failure_records(queue_path, trade_date="20260706", failure_records=[{"symbol": "688280.SH", "failure_type": "timeout"}])

    assert retry_symbols(queue_path, trade_date="20260706", batch_size=10, max_timeout_retries=1) == ["688280.SH"]
    from core.jobs.missing_latest_retry_queue import mark_retry_attempts

    mark_retry_attempts(queue_path, trade_date="20260706", symbols=["688280.SH"])
    assert retry_symbols(queue_path, trade_date="20260706", batch_size=10, max_timeout_retries=1) == []


def test_timeout_batch_does_not_mark_whole_batch_no_data(tmp_path: Path, monkeypatch) -> None:
    store = _seed_store(tmp_path, ["000001.SZ", "000002.SZ"])
    progress_path = tmp_path / "progress.json"
    queue_path = tmp_path / "queue.json"
    args = _args(tmp_path, progress_path=progress_path, queue_path=queue_path, symbols="000001.SZ,000002.SZ")
    fake = _TimeoutProcess()
    monkeypatch.setattr("core.jobs.update_market_data.subprocess.Popen", lambda *a, **k: fake)
    monkeypatch.setattr("core.jobs.update_market_data.os.killpg", lambda *a, **k: None)

    result = run_batched_update_parent(args=args, settings=_settings(store))

    assert result["status"] == "interrupted"
    assert read_missing_latest_queue(queue_path) == {}


def test_keyboard_interrupt_cleans_child_and_progress(tmp_path: Path, monkeypatch) -> None:
    store = _seed_store(tmp_path, ["000001.SZ"])
    progress_path = tmp_path / "progress.json"
    args = _args(tmp_path, progress_path=progress_path, queue_path=tmp_path / "queue.json", symbols="000001.SZ")
    fake = _KeyboardInterruptProcess()
    monkeypatch.setattr("core.jobs.update_market_data.subprocess.Popen", lambda *a, **k: fake)
    monkeypatch.setattr("core.jobs.update_market_data.os.killpg", lambda *a, **k: None)

    result = run_batched_update_parent(args=args, settings=_settings(store))
    progress = read_market_data_progress(progress_path)

    assert result["status"] == "interrupted"
    assert result["interrupted_by_user"] is True
    assert fake.returncode in {-15, -9}
    assert progress["running"] is False
    assert progress["interrupted_by_user"] is True
    assert all(item.get("status") != "running" for item in progress.get("provider_progress", []))


def test_update_market_data_records_no_data_queue(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, ["000024.SZ"])
    queue_path = tmp_path / "queue.json"

    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260706",
        symbols=["000024.SZ"],
        batch_size=1,
        continue_missing_latest=True,
        settings=_settings(store),
        status_path=tmp_path / "status.json",
        progress_path=tmp_path / "progress.json",
        skip_queue_path=queue_path,
        baostock_client=_NoDataClient(),
    )

    queue = read_missing_latest_queue(queue_path)
    assert "000024.SZ" in queue["skip_queue"]


def test_doctor_daily_run_shows_queue_counts_and_fileprovider_warning(tmp_path: Path, monkeypatch) -> None:
    db_dir = tmp_path / "Documents" / "股票" / "data"
    db_dir.mkdir(parents=True)
    store = DuckDBStore(db_dir / "a_stock_assistant.duckdb")
    store.initialize()
    store.upsert_dataframe("stock_basic", pd.DataFrame([{"ts_code": "000024.SZ", "symbol": "000024", "name": "mock"}]))
    queue_path = tmp_path / "queue.json"
    record_failure_records(queue_path, trade_date="20260706", failure_records=[{"symbol": "000024.SZ", "failure_type": "no_data"}])
    monkeypatch.setattr("core.jobs.doctor_daily_run.DEFAULT_SKIP_QUEUE_PATH", queue_path)

    result = doctor_daily_run(settings=_settings(store), store=store, root=tmp_path)
    output = render_console(result)

    assert "本轮 no_data 冷却队列: 1" in output
    assert "待 retry 队列: 0" in output
    assert "duckdb_fileprovider_risk" in output
    assert "FileProvider" in output


def test_fileprovider_risk_path_produces_warning(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "Documents" / "a_stock_assistant.duckdb")
    store.initialize()

    result = doctor_daily_run(settings=_settings(store), store=store, root=tmp_path)
    risk = next(item for item in result["checks"] if item["name"] == "duckdb_fileprovider_risk")

    assert risk["status"] == "WARNING"


class _NoDataClient:
    def get_daily_price(self, **kwargs):
        symbols = list(kwargs.get("symbols") or [])
        return {
            "status": "failed",
            "daily_price": pd.DataFrame(columns=["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]),
            "daily_basic": pd.DataFrame(),
            "failure_records": [{"symbol": symbol, "failure_type": "no_data"} for symbol in symbols],
            "failure_summary": {"no_data": len(symbols)},
            "failure_examples": {"no_data": symbols[:20]},
            "partial_update": True,
        }


class _TimeoutProcess:
    pid = 12345
    returncode = None

    def communicate(self, timeout=None):
        if timeout == 1:
            raise subprocess.TimeoutExpired(cmd="mock", timeout=timeout)
        self.returncode = -15
        return "", ""

    def wait(self, timeout=None):
        self.returncode = -15
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class _KeyboardInterruptProcess(_TimeoutProcess):
    def communicate(self, timeout=None):
        raise KeyboardInterrupt


def _args(tmp_path: Path, *, progress_path: Path, queue_path: Path, symbols: str) -> argparse.Namespace:
    return argparse.Namespace(
        goal="latest",
        mode="daily_incremental",
        provider="baostock",
        start_date="",
        end_date="20260706",
        symbols=symbols,
        batch_size=2,
        update_limit=0,
        batch_timeout_seconds=1,
        symbol_timeout_seconds=1,
        continue_missing_latest=True,
        respect_skip_queue=True,
        retry_skip_queue=False,
        max_no_data_retries=1,
        max_timeout_retries=1,
        skip_queue_path=queue_path,
        reset_skip_queue=False,
        skip_cooldown_minutes=60,
        force_snapshot=False,
        progress_path=progress_path,
        status_path=tmp_path / "status.json",
    )


def _seed_store(tmp_path: Path, symbols: list[str]) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "task57i.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame([{"ts_code": symbol, "symbol": symbol.split(".")[0], "name": symbol} for symbol in symbols]),
    )
    return store


def _price_rows(symbols: list[str], trade_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_code": symbol,
                "trade_date": trade_date,
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "pre_close": 9,
                "change": 1,
                "pct_chg": 1,
                "vol": 1000,
                "amount": 10000,
            }
            for symbol in symbols
        ]
    )


def _settings(store: DuckDBStore) -> SimpleNamespace:
    return SimpleNamespace(
        data_provider="akshare",
        duckdb_path=store.db_path,
        data_dir=store.db_path.parent,
        akshare_symbols=[],
        sample_symbols=[],
        real_universe_preset="full",
        akshare_sample_symbols="",
        full_update_lookback_days=250,
        tushare_token="",
        enable_real_basic_enrichment=False,
        enable_real_valuation_enrichment=False,
        real_data_end_date="20260706",
    )
