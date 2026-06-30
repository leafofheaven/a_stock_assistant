"""Tests for Task 49 entry zone calculations and commands."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.entry_zones.calculator import add_technical_indicators, calculate_entry_zones_for_targets
from core.jobs.calculate_entry_zones import calculate_entry_zones
from core.jobs.diagnose_entry_zones import diagnose_entry_zones
from core.jobs.export_entry_zone_report import export_entry_zone_report
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import enrich_with_entry_zone_fields


def test_ema_support_resistance_and_atr_calculation() -> None:
    """EMA, support/resistance, and ATR should match pandas rolling formulas."""
    price = _price_frame(["000001.SZ"], days=70)

    result = add_technical_indicators(price)
    stock = result[result["ts_code"] == "000001.SZ"].reset_index(drop=True)

    close = price["close"]
    assert stock.loc[69, "ema13"] == close.ewm(span=13, adjust=False).mean().iloc[69]
    assert stock.loc[69, "ema22"] == close.ewm(span=22, adjust=False).mean().iloc[69]
    assert stock.loc[69, "ema60"] == close.ewm(span=60, adjust=False).mean().iloc[69]
    assert stock.loc[69, "support_20d"] == price["low"].iloc[50:70].min()
    assert stock.loc[69, "resistance_60d"] == price["high"].iloc[10:70].max()
    assert pd.notna(stock.loc[69, "atr_14"])


def test_entry_zone_outputs_prices_and_reward_risk() -> None:
    """Entry zone should produce stop, target, and reward/risk values."""
    price = _price_frame(["000001.SZ"], days=70)
    targets = pd.DataFrame({"ts_code": ["000001.SZ"], "name": ["平安银行"]})

    result = calculate_entry_zones_for_targets(price, targets)
    row = result.iloc[0]

    assert row["entry_low"] <= row["entry_high"]
    assert row["stop_loss"] < row["entry_mid"]
    assert row["target_price"] > row["entry_mid"]
    assert row["reward_risk_ratio"] > 0
    assert row["entry_zone_status"] in {"in_zone", "near_zone", "above_zone", "below_zone"}


def test_overheated_and_weak_statuses_are_stable() -> None:
    """Overheated stocks should be high chase risk; weak trends should be weak_no_entry."""
    overheated = _price_frame(["000001.SZ"], days=70)
    overheated.loc[69, ["close", "high", "low"]] = [200.0, 202.0, 198.0]
    weak = _price_frame(["000002.SZ"], days=70, start_close=80.0, drift=-0.4)
    price = pd.concat([overheated, weak], ignore_index=True)
    targets = pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "name": ["强势股", "弱势股"]})

    result = calculate_entry_zones_for_targets(price, targets)
    hot = result[result["ts_code"] == "000001.SZ"].iloc[0]
    weak_row = result[result["ts_code"] == "000002.SZ"].iloc[0]

    assert hot["chase_risk"] == "high"
    assert hot["entry_zone_status"] == "above_zone"
    assert weak_row["entry_zone_status"] == "weak_no_entry"


def test_insufficient_data_does_not_crash() -> None:
    """Stocks with fewer than 20 rows should be marked insufficient_data."""
    price = _price_frame(["000001.SZ"], days=10)
    targets = pd.DataFrame({"ts_code": ["000001.SZ"], "name": ["平安银行"]})

    result = calculate_entry_zones_for_targets(price, targets)

    assert result.iloc[0]["entry_zone_status"] == "insufficient_data"
    assert "数据不足" in result.iloc[0]["risk_note"]


def test_calculate_diagnose_and_export_entry_zones_with_temp_duckdb(tmp_path: Path) -> None:
    """Commands should write snapshots, diagnose counts, and export reports."""
    store = _seed_store(tmp_path)
    before = store.read_table("strategy_result").sort_values("rank")["ts_code"].tolist()

    calc = calculate_entry_zones(settings=_settings(store), store=store, quiet=True)
    diag = diagnose_entry_zones(settings=_settings(store), store=store, quiet=True)
    report = export_entry_zone_report(output_dir=tmp_path / "reports", settings=_settings(store), store=store, quiet=True)
    after = store.read_table("strategy_result").sort_values("rank")["ts_code"].tolist()

    assert calc["written_rows"] >= 2
    assert diag["calculated_count"] >= 2
    assert "markdown" in report["generated_files"]
    assert "csv" in report["generated_files"]
    assert Path(report["generated_files"]["markdown"]).exists()
    assert before == after


def test_strategy_result_empty_is_clear_without_sample_fallback(tmp_path: Path) -> None:
    """Empty strategy_result should not fall back to sample during entry zone calculation."""
    store = DuckDBStore(tmp_path / "empty.duckdb")
    store.initialize()
    store.upsert_dataframe("daily_price", _price_frame(["000001.SZ"], days=30))

    result = calculate_entry_zones(settings=_settings(store), store=store, quiet=True)

    assert result["status"] == "partial_success"
    assert result["written_rows"] == 0
    assert "sample" not in result["message"].lower()


def test_streamlit_helper_attaches_entry_zone_fields() -> None:
    """Streamlit helper should merge latest entry zone fields without changing order."""
    selection = pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "rank": [1, 2]})
    zones = pd.DataFrame(
        {
            "ts_code": ["000002.SZ", "000001.SZ"],
            "trade_date": ["20240131", "20240131"],
            "entry_low": [20.0, 10.0],
            "entry_high": [21.0, 11.0],
            "entry_zone_status_cn": ["接近买入区间", "位于买入区间"],
        }
    )

    result = enrich_with_entry_zone_fields(selection, {"entry_zone_snapshots": zones})

    assert result["ts_code"].tolist() == ["000001.SZ", "000002.SZ"]
    assert result["entry_low"].tolist() == [10.0, 20.0]


def _seed_store(tmp_path: Path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "entry-zone.duckdb")
    store.initialize()
    symbols = ["000001.SZ", "000002.SZ"]
    store.upsert_dataframe("daily_price", _price_frame(symbols, days=70))
    store.upsert_dataframe(
        "strategy_result",
        pd.DataFrame(
            [
                {"trade_date": "20240409", "rank": 1, "ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "total_score": 80.0},
                {"trade_date": "20240409", "rank": 2, "ts_code": "000002.SZ", "name": "万科A", "industry": "地产", "total_score": 70.0},
            ]
        ),
    )
    store.upsert_dataframe(
        "review_decisions",
        pd.DataFrame(
            [
                {
                    "decision_id": "watch-000002",
                    "ts_code": "000002.SZ",
                    "name": "万科A",
                    "selection_date": "20240409",
                    "review_date": "20240409",
                    "decision": "watch",
                    "review_status": "active",
                    "reason": "观察",
                    "created_at": pd.Timestamp("2024-04-09"),
                    "updated_at": pd.Timestamp("2024-04-09"),
                }
            ]
        ),
    )
    return store


def _settings(store: DuckDBStore) -> SimpleNamespace:
    return SimpleNamespace(data_provider="akshare", duckdb_path=store.db_path)


def _price_frame(symbols: list[str], *, days: int, start_close: float = 10.0, drift: float = 0.2) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-01-01", periods=days).strftime("%Y%m%d").tolist()
    for offset, symbol in enumerate(symbols):
        for index, trade_date in enumerate(dates):
            close = start_close + offset * 5 + index * drift
            rows.append(
                {
                    "ts_code": symbol,
                    "trade_date": trade_date,
                    "open": close - 0.1,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "pre_close": close - drift,
                    "change": drift,
                    "pct_chg": 1.0,
                    "vol": 1_000_000.0,
                    "amount": 200_000_000.0,
                }
            )
    return pd.DataFrame(rows)

