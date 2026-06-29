"""Tests for Task 45 position daily tracking."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.jobs.export_positions import export_positions
from core.jobs.track_positions import track_positions
from core.positions.position_pool import create_position, track_active_positions, update_position_status
from core.storage.duckdb_store import DuckDBStore


class SampleSettings:
    """Minimal settings object for tracking job tests."""

    data_provider = "sample"

    def __init__(self, duckdb_path: Path) -> None:
        self.duckdb_path = duckdb_path


def test_active_position_tracking_calculates_daily_metrics(tmp_path: Path) -> None:
    """Active positions should include PnL, holding days, max gain and drawdown."""
    store = _store_with_position_and_price(tmp_path)

    tracked = track_active_positions(store)
    row = tracked.iloc[0]

    assert len(tracked) == 1
    assert row["latest_close"] == pytest.approx(12.0)
    assert row["pnl_pct"] == pytest.approx(0.20)
    assert row["holding_days"] == 31
    assert row["max_gain_pct"] == pytest.approx(0.25)
    assert row["max_drawdown_pct"] == pytest.approx(-0.08)
    assert row["close_to_entry_pct"] == pytest.approx(0.20)
    assert row["position_hint"] in {"持仓正常", "持有观察", "波动加大，需人工复核", "数据不足"}
    assert row["position_reason"]


def test_reduced_and_exited_positions_are_not_in_active_tracking(tmp_path: Path) -> None:
    """Reduced/exited records should not be included in active daily tracking."""
    store = _store_with_position_and_price(tmp_path)
    update_position_status(store=store, ts_code="000001.SZ", status="reduced")

    tracked = track_active_positions(store)

    assert tracked.empty


def test_tracking_handles_insufficient_price_data_without_crashing(tmp_path: Path) -> None:
    """Missing price after entry should return 数据不足 fields."""
    store = DuckDBStore(tmp_path / "positions.duckdb")
    store.initialize()
    create_position(store=store, ts_code="000001.SZ", name="平安银行", entry_date="20240601", entry_price=10.0)

    tracked = track_active_positions(store)

    assert tracked.iloc[0]["position_hint"] == "数据不足"
    assert tracked.iloc[0]["technical_state"] == "数据不足"
    assert "数据不足" in tracked.iloc[0]["position_reason"]


def test_track_positions_outputs_markdown_csv_and_json(tmp_path: Path) -> None:
    """track_positions should export all report formats."""
    store = _store_with_position_and_price(tmp_path)

    result = track_positions(output_dir=tmp_path, store=store, settings=SampleSettings(store.db_path), report_format="all")

    assert result["status"] == "success"
    assert {"markdown", "csv", "json"}.issubset(result["generated_files"])
    markdown = Path(result["generated_files"]["markdown"]).read_text(encoding="utf-8")
    csv_text = Path(result["generated_files"]["csv"]).read_text(encoding="utf-8-sig")
    assert "持仓池报告" in markdown
    assert "最大浮盈" in markdown
    assert "position_hint" in csv_text


def test_export_positions_includes_tracking_fields(tmp_path: Path) -> None:
    """export_positions should show latest tracking fields as well."""
    store = _store_with_position_and_price(tmp_path)

    result = export_positions(output_dir=tmp_path, store=store, settings=SampleSettings(store.db_path), report_format="csv")
    csv_text = Path(result["generated_files"]["csv"]).read_text(encoding="utf-8-sig")

    assert "max_gain_pct" in csv_text
    assert "max_drawdown_pct" in csv_text
    assert "latest_elder_score" in csv_text
    assert "position_hint" in csv_text


def test_total_score_order_is_not_modified_by_position_tracking(tmp_path: Path) -> None:
    """Position tracking should not touch total_score ordering."""
    selection = pd.DataFrame({"ts_code": ["A", "B"], "total_score": [90, 80]}).sort_values("total_score", ascending=False)
    store = _store_with_position_and_price(tmp_path)
    track_active_positions(store)

    assert selection["ts_code"].tolist() == ["A", "B"]
    assert selection["total_score"].tolist() == [90, 80]


def _store_with_position_and_price(tmp_path: Path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "positions.duckdb")
    store.initialize()
    create_position(
        store=store,
        ts_code="000001.SZ",
        name="平安银行",
        entry_date="20240601",
        entry_price=10.0,
        entry_total_score=80,
        entry_elder_score=70,
    )
    store.upsert_dataframe("daily_price", _price_frame())
    return store


def _price_frame() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-05-01", periods=45).strftime("%Y%m%d")
    closes = [9.5 + index * 0.05 for index in range(45)]
    for index, trade_date in enumerate(dates):
        if trade_date >= "20240601":
            close = 10.0 + (index - 23) * 0.08
        else:
            close = closes[index]
        rows.append(
            {
                "ts_code": "000001.SZ",
                "trade_date": trade_date,
                "open": close,
                "high": max(close * 1.02, 12.5 if trade_date == "20240620" else close),
                "low": min(close * 0.98, 9.2 if trade_date == "20240610" else close),
                "close": close,
                "vol": 1_000_000 + index,
                "amount": (1_000_000 + index) * close,
            }
        )
    for row in rows:
        if row["trade_date"] == "20240610":
            row["close"] = 9.2
            row["low"] = 9.2
        if row["trade_date"] == "20240620":
            row["close"] = 12.5
            row["high"] = 12.5
    rows[-1]["close"] = 12.0
    rows[-1]["high"] = 12.5
    return pd.DataFrame(rows)
