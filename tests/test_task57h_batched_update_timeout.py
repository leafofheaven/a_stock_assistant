"""Task 57H batched market update timeout and recovery tests."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.jobs.doctor_daily_run import doctor_daily_run, render_console
from core.jobs.market_data_progress import MarketDataProgressWriter, read_market_data_progress
from core.jobs.update_market_data import (
    _continue_missing_latest_symbol_plan,
    run_batched_update_parent,
    update_market_data,
)
from core.storage.duckdb_store import DuckDBStore


def test_continue_missing_latest_selects_missing_price_or_basic_only(tmp_path: Path) -> None:
    """Continue mode should not reprocess symbols with both latest price and basic."""
    store = _seed_store(tmp_path, ["000001.SZ", "000002.SZ", "000003.SZ"])
    store.upsert_dataframe("daily_price", _price_rows(["000001.SZ", "000002.SZ"], "20260706"))
    store.upsert_dataframe("daily_basic", pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260706", "turnover_rate": 1.0}]))

    plan = _continue_missing_latest_symbol_plan(
        end_date="20260706",
        symbols=["000001.SZ", "000002.SZ", "000003.SZ"],
        store=store,
        batch_size=10,
    )

    assert plan["symbols"] == ["000003.SZ", "000002.SZ"]
    assert plan["already_latest_symbol_count"] == 1
    assert plan["missing_latest_price_symbol_count"] == 1
    assert plan["missing_latest_basic_symbol_count"] == 2


def test_update_market_data_continue_missing_latest_limits_to_batch_size(tmp_path: Path) -> None:
    """batch_size should limit the actual batch selected for continue-missing-latest."""
    store = _seed_store(tmp_path, ["000001.SZ", "000002.SZ", "000003.SZ"])
    module = _RecordingBaoStockModule()

    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260706",
        symbols=["000001.SZ", "000002.SZ", "000003.SZ"],
        batch_size=2,
        continue_missing_latest=True,
        settings=_settings(store),
        status_path=tmp_path / "status.json",
        progress_path=tmp_path / "progress.json",
        baostock_client=_BaoStockClient(module),
    )

    assert module.queried_codes == ["sz.000001", "sz.000002"]


def test_parent_timeout_writes_interrupted_progress(tmp_path: Path, monkeypatch) -> None:
    """Parent process should mark progress interrupted and avoid stale running=true."""
    store = _seed_store(tmp_path, ["000001.SZ"])
    progress_path = tmp_path / "progress.json"
    args = argparse.Namespace(
        goal="latest",
        mode="daily_incremental",
        provider="baostock",
        start_date="",
        end_date="20260706",
        symbols="000001.SZ",
        batch_size=1,
        update_limit=0,
        batch_timeout_seconds=1,
        symbol_timeout_seconds=1,
        continue_missing_latest=True,
        force_snapshot=False,
        progress_path=progress_path,
        status_path=tmp_path / "status.json",
    )
    fake = _TimeoutProcess()
    monkeypatch.setattr("core.jobs.update_market_data.subprocess.Popen", lambda *a, **k: fake)
    monkeypatch.setattr("core.jobs.update_market_data.os.killpg", lambda *a, **k: None)

    result = run_batched_update_parent(args=args, settings=_settings(store))
    progress = read_market_data_progress(progress_path)

    assert result["status"] == "interrupted"
    assert result["stale_detected"] is True
    assert progress["running"] is False
    assert progress["status"] == "interrupted"
    assert progress["timeout"] is True
    assert all(item["status"] != "running" for item in progress.get("provider_progress", []))


def test_progress_finish_clears_running_provider(tmp_path: Path) -> None:
    """provider_progress should not retain running after interruption."""
    progress_path = tmp_path / "progress.json"
    writer = MarketDataProgressWriter(progress_path)
    writer.start(goal="latest", provider="baostock", total_symbol_count=1)
    writer.start_provider("baostock", "历史行情兜底", total_symbol_count=1)
    writer.finish(status="interrupted", stale_detected=True, timeout=True)

    payload = read_market_data_progress(progress_path)

    assert payload["running"] is False
    assert payload["provider_progress"][0]["status"] == "interrupted"
    assert payload["stale_detected"] is True


def test_doctor_daily_run_reports_latest_coverage_counts(tmp_path: Path) -> None:
    """Doctor output should show coverage counts instead of only max trade_date."""
    store = _seed_store(tmp_path, ["000001.SZ", "000002.SZ", "000003.SZ"])
    store.upsert_dataframe("daily_price", _price_rows(["000001.SZ"], "20260706"))
    store.upsert_dataframe("daily_basic", pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260706", "turnover_rate": 1.0}]))

    result = doctor_daily_run(settings=_settings(store), store=store, root=tmp_path)
    output = render_console(result)

    assert "latest_coverage_counts" in output
    assert "daily_price 覆盖数: 1 / 3" in output
    assert "daily_basic 覆盖数: 1 / 3" in output
    assert "缺口数量: 2" in output


def test_streamlit_latest_update_uses_batched_continue_missing() -> None:
    """Streamlit latest button should call bounded continue-missing-latest updates."""
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")

    assert '"--batch-size"' in source
    assert '"100"' in source
    assert '"--batch-timeout-seconds"' in source
    assert '"--continue-missing-latest"' in source


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


class _BaoStockClient:
    def __init__(self, module):
        self.module = module

    def get_daily_price(self, **kwargs):
        return self.module.get_daily_price(**kwargs)


class _RecordingBaoStockModule:
    def __init__(self):
        self.queried_codes: list[str] = []

    def get_daily_price(self, *, symbols, progress_callback=None, **kwargs):
        rows = []
        for index, symbol in enumerate(symbols, start=1):
            code = symbol.split(".")[0]
            self.queried_codes.append(f"sz.{code}")
            rows.append(
                {
                    "ts_code": symbol,
                    "trade_date": kwargs.get("end_date", "20260706"),
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
            )
            if progress_callback:
                progress_callback(symbol=symbol, status="success", written_rows=1, processed_symbol_count=index, total_symbol_count=len(symbols))
        return {
            "status": "success",
            "daily_price": pd.DataFrame(rows),
            "daily_basic": pd.DataFrame([{"ts_code": row["ts_code"], "trade_date": row["trade_date"], "turnover_rate": 1.0} for row in rows]),
            "failure_summary": {},
            "failure_examples": {},
            "partial_update": True,
        }


def _seed_store(tmp_path: Path, symbols: list[str]) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "task57h.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": symbol,
                    "symbol": symbol.split(".")[0],
                    "name": symbol,
                    "market": "主板",
                    "exchange": "SZSE",
                }
                for symbol in symbols
            ]
        ),
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
