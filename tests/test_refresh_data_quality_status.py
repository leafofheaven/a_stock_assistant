"""Tests for refreshing scheduled data-quality status."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.jobs.refresh_data_quality_status import refresh_data_quality_status
from core.storage.duckdb_store import DuckDBStore


def test_refresh_data_quality_status_outputs_actual_counts(tmp_path: Path, monkeypatch, capsys) -> None:
    """Refresh command should print actual latest-date counts from DuckDB."""
    db_path, status_path = _seed_quality_db(tmp_path)
    monkeypatch.setattr("core.jobs.refresh_data_quality_status.get_settings", lambda: SimpleNamespace(duckdb_path=db_path))

    result = refresh_data_quality_status(status_path=status_path, output_format="text")
    output = capsys.readouterr().out

    assert result["latest_daily_price_symbol_count"] == 68
    assert result["latest_daily_basic_symbol_count"] == 3
    assert result["latest_adj_factor_symbol_count"] == 0
    assert result["any_daily_price_symbol_count"] == 90
    assert "daily_price 20260703: 68" in output
    assert "daily_basic 20260703: 3" in output
    assert "formal_result_usable: False" in output


def test_refresh_data_quality_status_writes_actual_counts(tmp_path: Path, monkeypatch, capsys) -> None:
    """Refresh command should write and print actual latest-date counts."""
    test_refresh_data_quality_status_outputs_actual_counts(tmp_path, monkeypatch, capsys)


def test_refresh_data_quality_status_updates_status_json(tmp_path: Path, monkeypatch) -> None:
    """Refresh command should write data-quality fields back to status JSON."""
    db_path, status_path = _seed_quality_db(tmp_path)
    monkeypatch.setattr("core.jobs.refresh_data_quality_status.get_settings", lambda: SimpleNamespace(duckdb_path=db_path))

    refresh_data_quality_status(status_path=status_path, output_format="text")
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert payload["data_quality_status"] == "poor"
    assert payload["formal_result_usable"] is False
    assert payload["latest_completed_trade_date"] == "20260703"
    assert payload["latest_daily_price_symbol_count"] == 68
    assert payload["latest_daily_basic_symbol_count"] == 3
    assert payload["latest_adj_factor_symbol_count"] == 0
    assert payload["any_daily_price_symbol_count"] == 90


def _seed_quality_db(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "quality.duckdb"
    status_path = tmp_path / "scheduled_daily_update_status.json"
    store = DuckDBStore(db_path)
    store.initialize()
    symbols = [f"{index:06d}.SZ" for index in range(1, 101)]
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            {
                "ts_code": symbols,
                "symbol": [code[:6] for code in symbols],
                "name": [f"股票{index}" for index in range(1, 101)],
                "market": ["主板"] * 100,
                "exchange": ["SZSE"] * 100,
            }
        ),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {
                    "ts_code": symbol,
                    "trade_date": "20260703" if index < 68 else "20260702",
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "pre_close": 1.0,
                    "change": 0.0,
                    "pct_chg": 0.0,
                    "vol": 1.0,
                    "amount": 1.0,
                }
                for index, symbol in enumerate(symbols[:90])
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_basic",
        pd.DataFrame(
            {
                "ts_code": symbols[:3],
                "trade_date": ["20260703"] * 3,
                "turnover_rate": [1.0] * 3,
                "pe": [10.0] * 3,
                "pb": [1.0] * 3,
            }
        ),
    )
    status_path.write_text(
        json.dumps(
            {
                "status": "warning",
                "stage": "done",
                "run_date": "20260704",
                "research_trade_date": "20260703",
                "latest_completed_trade_date": "20260703",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return db_path, status_path
