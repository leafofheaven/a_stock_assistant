"""Tests for Task 44 position pool foundation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.jobs.export_positions import export_positions
from core.jobs.import_positions import import_positions as import_positions_job
from core.positions.position_pool import (
    build_positions_dataframe,
    create_position,
    import_positions,
    read_positions,
    update_position_status,
)
from core.storage.duckdb_store import DuckDBStore


class SampleSettings:
    """Minimal settings object for position job tests."""

    data_provider = "sample"

    def __init__(self, duckdb_path: Path) -> None:
        self.duckdb_path = duckdb_path


def test_create_position_record_and_prevent_duplicate_active_position(tmp_path: Path) -> None:
    """Creating the same active ts_code twice should skip the second record."""
    store = _store(tmp_path)

    first = create_position(
        store=store,
        ts_code="000001.SZ",
        name="平安银行",
        entry_date="20240628",
        entry_price=10.0,
        quantity=100,
        entry_reason="人工复核后记录",
        source="manual",
        entry_total_score=80,
        entry_elder_score=70,
    )
    second = create_position(store=store, ts_code="000001.SZ", entry_date="20240628", entry_price=10.2)

    positions = read_positions(store)
    assert first["status"] == "success"
    assert second["status"] == "exists"
    assert "active position" in second["message"]
    assert len(positions) == 1
    assert positions.iloc[0]["entry_total_score"] == 80


def test_update_position_status_to_reduced_and_exited(tmp_path: Path) -> None:
    """Position status should support active/reduced/exited lifecycle."""
    store = _store(tmp_path)
    create_position(store=store, ts_code="000001.SZ", entry_date="20240628", entry_price=10.0)

    reduced = update_position_status(store=store, ts_code="000001.SZ", status="reduced")
    exited = update_position_status(store=store, ts_code="000001.SZ", status="exited")

    assert reduced["status"] == "success"
    assert reduced["old_status"] == "active"
    assert exited["new_status"] == "exited"
    assert read_positions(store).iloc[0]["status"] == "exited"


def test_build_positions_dataframe_adds_latest_close_pnl_and_holding_days(tmp_path: Path) -> None:
    """Local latest close should enrich position PnL and holding days."""
    store = _store(tmp_path)
    create_position(store=store, ts_code="000001.SZ", name="平安银行", entry_date="20240601", entry_price=10.0)
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000001.SZ"],
                "trade_date": ["20240620", "20240628"],
                "open": [10, 11],
                "high": [10, 12],
                "low": [9, 10],
                "close": [11.0, 12.0],
                "vol": [1, 1],
                "amount": [1, 1],
            }
        ),
    )

    positions = build_positions_dataframe(store)

    assert positions.iloc[0]["latest_close"] == 12.0
    assert positions.iloc[0]["pnl_pct"] == pytest.approx(0.20)
    assert positions.iloc[0]["holding_days"] == 27
    assert positions.iloc[0]["data_quality_note"] == "数据可用于持仓每日跟踪"


def test_build_positions_dataframe_handles_missing_price_without_crashing(tmp_path: Path) -> None:
    """Missing latest close should produce a clear data quality note."""
    store = _store(tmp_path)
    create_position(store=store, ts_code="000001.SZ", entry_date="20240601", entry_price=10.0)

    positions = build_positions_dataframe(store)

    assert pd.isna(positions.iloc[0]["latest_close"])
    assert positions.iloc[0]["pnl_pct"] is None
    assert "行情数据不足" in positions.iloc[0]["data_quality_note"]


def test_import_positions_from_dataframe_and_job(tmp_path: Path) -> None:
    """Position imports should support DataFrame and CLI job wrapper."""
    store = _store(tmp_path)
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
            "entry_date": ["20240628"],
            "entry_price": ["10.0"],
            "quantity": ["100"],
            "entry_reason": ["观察池转持仓记录"],
            "source": ["watchlist"],
            "entry_total_score": ["80"],
            "entry_elder_score": ["70"],
            "initial_stop": ["9.2"],
            "plan": ["人工复核计划"],
        }
    )
    csv_path = tmp_path / "positions.csv"
    df.to_csv(csv_path, index=False)

    result = import_positions(df, store=store)
    job_result = import_positions_job(file_path=csv_path, store=store, settings=SampleSettings(store.db_path), dry_run=True)

    assert result["created_rows"] == 1
    assert job_result["status"] == "success"
    assert job_result["dry_run"] is True


def test_export_positions_outputs_markdown_and_csv(tmp_path: Path) -> None:
    """export_positions should write markdown/csv/json reports."""
    store = _store(tmp_path)
    create_position(store=store, ts_code="000001.SZ", name="平安银行", entry_date="20240628", entry_price=10.0)

    result = export_positions(output_dir=tmp_path, store=store, settings=SampleSettings(store.db_path))

    assert result["status"] == "success"
    assert {"markdown", "csv", "json"}.issubset(result["generated_files"])
    markdown = Path(result["generated_files"]["markdown"]).read_text(encoding="utf-8")
    csv_text = Path(result["generated_files"]["csv"]).read_text(encoding="utf-8-sig")
    assert "持仓池报告" in markdown
    assert "000001.SZ" in csv_text


def test_total_score_order_is_not_modified_by_position_pool(tmp_path: Path) -> None:
    """Position pool operations should not touch total_score ordering."""
    selection = pd.DataFrame({"ts_code": ["A", "B"], "total_score": [90, 80]}).sort_values("total_score", ascending=False)
    store = _store(tmp_path)
    create_position(store=store, ts_code="000001.SZ", entry_date="20240628", entry_price=10.0)

    assert selection["ts_code"].tolist() == ["A", "B"]
    assert selection["total_score"].tolist() == [90, 80]


def _store(tmp_path: Path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "positions.duckdb")
    store.initialize()
    return store
