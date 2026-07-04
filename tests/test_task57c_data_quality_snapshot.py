"""Tests for Task 57C unified data quality snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.diagnostics.data_quality_snapshot import build_data_quality_snapshot, normalize_trade_date
from core.jobs.refresh_data_quality_status import refresh_data_quality_status
from core.storage.duckdb_store import DuckDBStore


def test_data_quality_snapshot_counts_latest_trade_date(tmp_path: Path) -> None:
    db_path = _seed_quality_db(tmp_path)
    snapshot = build_data_quality_snapshot(db_path=db_path, research_trade_date="20260703", latest_completed_trade_date="20260703")

    assert snapshot["latest_daily_price_symbol_count"] == 68
    assert snapshot["latest_daily_price_symbol_count"] != 0


def test_data_quality_snapshot_counts_daily_basic_latest_trade_date(tmp_path: Path) -> None:
    db_path = _seed_quality_db(tmp_path)
    snapshot = build_data_quality_snapshot(db_path=db_path, research_trade_date="20260703", latest_completed_trade_date="20260703")

    assert snapshot["latest_daily_basic_symbol_count"] == 3


def test_data_quality_snapshot_counts_adj_factor_latest_trade_date(tmp_path: Path) -> None:
    db_path = _seed_quality_db(tmp_path)
    snapshot = build_data_quality_snapshot(db_path=db_path, research_trade_date="20260703", latest_completed_trade_date="20260703")

    assert snapshot["latest_adj_factor_symbol_count"] == 0


def test_data_quality_snapshot_counts_any_history_separately(tmp_path: Path) -> None:
    db_path = _seed_quality_db(tmp_path)
    snapshot = build_data_quality_snapshot(db_path=db_path, research_trade_date="20260703", latest_completed_trade_date="20260703")

    assert snapshot["any_daily_price_symbol_count"] == 4995
    assert snapshot["any_daily_price_symbol_count"] != snapshot["history_complete_symbol_count"]
    assert snapshot["any_daily_price_symbol_count"] != snapshot["latest_daily_price_symbol_count"]


def test_history_missing_uses_any_history_count(tmp_path: Path) -> None:
    db_path = _seed_quality_db(tmp_path)
    snapshot = build_data_quality_snapshot(db_path=db_path, research_trade_date="20260703", latest_completed_trade_date="20260703")

    assert snapshot["configured_symbol_count"] == 5055
    assert snapshot["history_missing_symbol_count"] == 60
    assert snapshot["missing_any_daily_price_symbol_count"] == 60


def test_history_complete_is_separate_from_any_history(tmp_path: Path) -> None:
    db_path = _seed_quality_db(tmp_path)
    snapshot = build_data_quality_snapshot(db_path=db_path, research_trade_date="20260703", latest_completed_trade_date="20260703")

    assert snapshot["history_complete_symbol_count"] == 50
    assert snapshot["any_daily_price_symbol_count"] == 4995


def test_normalize_trade_date_formats() -> None:
    assert normalize_trade_date(20260703) == "20260703"
    assert normalize_trade_date(" 20260703 ") == "20260703"
    assert normalize_trade_date("2026-07-03") == "20260703"


def test_refresh_data_quality_status_writes_status_json(tmp_path: Path, monkeypatch) -> None:
    db_path = _seed_quality_db(tmp_path)
    status_path = _status_path(tmp_path)
    monkeypatch.setattr("core.jobs.refresh_data_quality_status.get_settings", lambda: SimpleNamespace(duckdb_path=db_path))

    refresh_data_quality_status(status_path=status_path, output_format="text")
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert payload["latest_daily_price_symbol_count"] == 68
    assert payload["latest_daily_basic_symbol_count"] == 3
    assert payload["latest_adj_factor_symbol_count"] == 0
    assert payload["any_daily_price_symbol_count"] == 4995
    assert payload["history_missing_symbol_count"] == 60
    assert payload["data_quality_status"] == "poor"
    assert payload["formal_result_usable"] is False


def test_refresh_data_quality_status_is_read_only(tmp_path: Path, monkeypatch) -> None:
    db_path = _seed_quality_db(tmp_path)
    status_path = _status_path(tmp_path)
    before = DuckDBStore(db_path).read_table("daily_price").shape[0]
    monkeypatch.setattr("core.jobs.refresh_data_quality_status.get_settings", lambda: SimpleNamespace(duckdb_path=db_path))

    refresh_data_quality_status(status_path=status_path, output_format="text")

    after = DuckDBStore(db_path).read_table("daily_price").shape[0]
    assert after == before


def test_refresh_data_quality_status_prints_sql_counts(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = _seed_quality_db(tmp_path)
    status_path = _status_path(tmp_path)
    monkeypatch.setattr("core.jobs.refresh_data_quality_status.get_settings", lambda: SimpleNamespace(duckdb_path=db_path))

    refresh_data_quality_status(status_path=status_path, output_format="text")
    output = capsys.readouterr().out

    assert "daily_price trade_date 分布 top 10" in output
    assert "daily_price 20260703: 68" in output
    assert "daily_basic 20260703: 3" in output
    assert "adj_factor 20260703: 0" in output
    assert "any_daily_price_symbol_count: 4995" in output
    assert "history_missing_symbol_count: 60" in output


def _status_path(tmp_path: Path) -> Path:
    path = tmp_path / "scheduled_daily_update_status.json"
    path.write_text(
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
    return path


def _seed_quality_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "quality.duckdb"
    store = DuckDBStore(db_path)
    store.initialize()
    symbols = [f"{index:06d}.SZ" for index in range(1, 5056)]
    store.upsert_dataframe("stock_basic", pd.DataFrame({"ts_code": symbols, "symbol": [code[:6] for code in symbols], "name": symbols}))
    price_rows = []
    for index, symbol in enumerate(symbols[:4995]):
        row_count = 252 if index < 50 else 12
        latest_date = "20260703" if index < 68 else "20260702"
        for day in range(row_count):
            price_rows.append(
                {
                    "ts_code": symbol,
                    "trade_date": latest_date if day == 0 else f"2025{(day // 28) + 1:02d}{(day % 28) + 1:02d}",
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
            )
    store.upsert_dataframe("daily_price", pd.DataFrame(price_rows))
    store.upsert_dataframe(
        "daily_basic",
        pd.DataFrame({"ts_code": symbols[:3], "trade_date": ["20260703"] * 3, "turnover_rate": [1.0] * 3, "pe": [10.0] * 3, "pb": [1.0] * 3}),
    )
    return db_path
