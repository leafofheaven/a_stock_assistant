"""Tests for external simulated position import and matching."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.external_positions.importer import (
    import_external_positions_frame,
    import_external_trades_frame,
    match_external_positions,
    normalize_ts_code,
    parse_number,
    position_template_frame,
    trade_template_frame,
)
from core.jobs.export_external_position_report import export_external_position_report, external_positions_to_dataframe
from core.jobs.generate_external_position_template import generate_external_position_template
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import latest_external_positions, parse_external_position_text


def test_normalize_ts_code_rejects_bse_and_maps_sh_sz() -> None:
    """Common A-share symbols should normalize while BSE codes are rejected."""
    assert normalize_ts_code("000725") == ("000725.SZ", None)
    assert normalize_ts_code("300001") == ("300001.SZ", None)
    assert normalize_ts_code("603986") == ("603986.SH", None)
    assert normalize_ts_code("688981") == ("688981.SH", None)
    assert normalize_ts_code("430001")[1] == "unsupported_bse"
    assert normalize_ts_code("830000.BJ")[1] == "unsupported_bse"


def test_parse_number_handles_commas_and_percent() -> None:
    """Numeric parser should handle common exported CSV formats."""
    assert parse_number("1,000") == 1000.0
    assert parse_number("3.87%") == 0.0387
    assert parse_number("") is None


def test_generate_external_position_template_writes_csv_files(tmp_path: Path) -> None:
    """Template command helper should generate trade and position CSV templates."""
    result = generate_external_position_template(output_dir=tmp_path, quiet=True)

    assert result["status"] == "success"
    assert (tmp_path / "external_trades_template.csv").exists()
    assert (tmp_path / "external_position_snapshots_template.csv").exists()
    assert "ts_code" in trade_template_frame().columns
    assert "cost_price" in position_template_frame().columns


def test_import_external_trades_is_idempotent(tmp_path: Path) -> None:
    """Repeated trade imports should update the same stable row instead of duplicating it."""
    store = _store(tmp_path)
    trades = trade_template_frame()

    first = import_external_trades_frame(trades, store=store, source_file="trades.csv")
    second = import_external_trades_frame(trades, store=store, source_file="trades.csv")
    saved = store.read_table("external_trades")

    assert first["inserted_rows"] == 1
    assert second["updated_rows"] == 1
    assert len(saved) == 1


def test_import_external_positions_missing_required_field_fails(tmp_path: Path) -> None:
    """Missing required CSV columns should return a clear failed result."""
    store = _store(tmp_path)

    result = import_external_positions_frame(pd.DataFrame({"ts_code": ["000725"]}), store=store)

    assert result["status"] == "failed"
    assert "missing required columns" in result["error_rows"][0]["error"]


def test_import_external_positions_matches_entry_zone_and_risk_statuses(tmp_path: Path) -> None:
    """Position snapshots should match entry zones, watchlist state, and risk statuses."""
    store = _store(tmp_path)
    _seed_market_context(store)
    positions = pd.DataFrame(
        [
            _position("000725", "京东方A", 7.5, 7.5),
            _position("603986", "兆易创新", 7.5, 6.95),
            _position("000001", "平安银行", 7.2, 6.7),
            _position("000002", "万科A", 7.5, 10.5),
            _position("300001", "特锐德", 9.0, 9.0),
            _position("600000", "浦发银行", 7.0, 7.2),
            _position("999999", "未知股票", 7.0, 7.2),
        ]
    )

    result = import_external_positions_frame(positions, store=store, source_file="positions.csv")
    saved = store.read_table("external_position_snapshots")
    statuses = dict(zip(saved["ts_code"], saved["risk_status"]))

    assert result["status"] == "success"
    assert statuses["000725.SZ"] == "entered_in_zone"
    assert statuses["603986.SH"] == "near_stop_loss"
    assert statuses["000001.SZ"] == "hit_stop_loss"
    assert statuses["000002.SZ"] == "hit_target"
    assert statuses["300001.SZ"] == "chased_high"
    assert statuses["600000.SH"] == "insufficient_data"
    assert "unknown_symbol" in saved[saved["ts_code"] == "999999.SH"].iloc[0]["match_note"]
    assert "已匹配观察池" in saved[saved["ts_code"] == "000725.SZ"].iloc[0]["match_note"]


def test_match_external_positions_refreshes_existing_rows(tmp_path: Path) -> None:
    """Re-match command helper should rewrite imported snapshots with latest local context."""
    store = _store(tmp_path)
    _seed_market_context(store)
    import_external_positions_frame(pd.DataFrame([_position("000725", "京东方A", 7.5, 7.5)]), store=store)

    result = match_external_positions(store)

    assert result["status"] == "success"
    assert result["matched_rows"] == 1


def test_export_external_position_report_writes_markdown_json_csv(tmp_path: Path) -> None:
    """Report exporter should produce all supported formats."""
    store = _store(tmp_path)
    _seed_market_context(store)
    import_external_positions_frame(pd.DataFrame([_position("000725", "京东方A", 7.5, 7.5)]), store=store)

    result = export_external_position_report(output_dir=tmp_path, report_format="all", store=store, quiet=True)

    assert result["status"] == "success"
    assert set(result["generated_files"]) == {"markdown", "json", "csv"}
    assert "risk_status_cn" in external_positions_to_dataframe(result["report"]["positions"]).columns


def test_streamlit_external_position_helpers() -> None:
    """Streamlit helpers should parse pasted data and select latest snapshots."""
    parsed = parse_external_position_text("ts_code,quantity\n000725,100\n")
    snapshots = pd.DataFrame(
        {
            "snapshot_date": ["20260629", "20260630"],
            "ts_code": ["000001.SZ", "000725.SZ"],
        }
    )

    latest = latest_external_positions({"external_position_snapshots": snapshots})

    assert parsed["ts_code"].tolist() == ["000725"]
    assert latest["ts_code"].tolist() == ["000725.SZ"]


def test_external_position_sources_do_not_use_cookie_or_auto_trade() -> None:
    """Task 50 code should stay file-import only and avoid auto trading integrations."""
    source = Path("core/external_positions/importer.py").read_text(encoding="utf-8")

    assert "requests" not in source
    assert "cookie" not in source.lower()
    assert "broker" not in source.lower()


def _store(tmp_path: Path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "external_positions.duckdb")
    store.initialize()
    return store


def _position(symbol: str, name: str, cost_price: float, current_price: float) -> dict[str, object]:
    return {
        "platform": "同花顺模拟",
        "account_name": "默认账户",
        "snapshot_date": "20260630",
        "ts_code": symbol,
        "name": name,
        "quantity": 1000,
        "cost_price": cost_price,
        "current_price": current_price,
        "market_value": current_price * 1000,
        "pnl": (current_price - cost_price) * 1000,
        "pnl_pct": (current_price - cost_price) / cost_price,
        "note": "模拟持仓",
    }


def _seed_market_context(store: DuckDBStore) -> None:
    stock_rows = [
        {"ts_code": "000725.SZ", "symbol": "000725", "name": "京东方A", "industry": "面板", "market": "主板", "exchange": "SZSE"},
        {"ts_code": "603986.SH", "symbol": "603986", "name": "兆易创新", "industry": "半导体", "market": "主板", "exchange": "SSE"},
        {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "industry": "银行", "market": "主板", "exchange": "SZSE"},
        {"ts_code": "000002.SZ", "symbol": "000002", "name": "万科A", "industry": "地产", "market": "主板", "exchange": "SZSE"},
        {"ts_code": "300001.SZ", "symbol": "300001", "name": "特锐德", "industry": "电气设备", "market": "创业板", "exchange": "SZSE"},
        {"ts_code": "600000.SH", "symbol": "600000", "name": "浦发银行", "industry": "银行", "market": "主板", "exchange": "SSE"},
    ]
    store.upsert_dataframe("stock_basic", pd.DataFrame(stock_rows))
    price_rows = [
        {"ts_code": row["ts_code"], "trade_date": "20260630", "open": 7.0, "high": 8.0, "low": 6.8, "close": 7.2, "pre_close": 7.0, "change": 0.2, "pct_chg": 2.8, "vol": 1, "amount": 1}
        for row in stock_rows
    ]
    store.upsert_dataframe("daily_price", pd.DataFrame(price_rows))
    zones = pd.DataFrame(
        [
            _zone("000725.SZ", 7.0, 8.0, 6.8, 10.0, "low"),
            _zone("603986.SH", 7.0, 8.0, 6.8, 10.0, "low"),
            _zone("000001.SZ", 7.0, 8.0, 6.8, 10.0, "low"),
            _zone("000002.SZ", 7.0, 8.0, 6.8, 10.0, "low"),
            _zone("300001.SZ", 7.0, 8.0, 6.8, 10.0, "high"),
        ]
    )
    store.upsert_dataframe("entry_zone_snapshots", zones)
    store.upsert_dataframe(
        "review_decisions",
        pd.DataFrame(
            [
                {
                    "decision_id": "test-watch-000725",
                    "ts_code": "000725.SZ",
                    "name": "京东方A",
                    "decision": "watch",
                    "reason": "外部模拟匹配测试",
                    "selection_date": "20260630",
                    "review_date": "20260630",
                    "review_status": "active",
                }
            ]
        ),
    )


def _zone(ts_code: str, low: float, high: float, stop: float, target: float, chase_risk: str) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "name": ts_code,
        "trade_date": "20260630",
        "close": (low + high) / 2,
        "ema13": 7.4,
        "ema22": 7.3,
        "ema60": 7.0,
        "support_20d": low,
        "support_60d": low,
        "resistance_20d": target,
        "resistance_60d": target,
        "nearest_support": low,
        "nearest_resistance": target,
        "atr_14": 0.4,
        "volatility_pct": 0.05,
        "entry_low": low,
        "entry_high": high,
        "entry_mid": (low + high) / 2,
        "stop_loss": stop,
        "target_price": target,
        "risk_pct": 0.08,
        "reward_pct": 0.2,
        "reward_risk_ratio": 2.5,
        "entry_zone_status": "in_zone",
        "chase_risk": chase_risk,
        "price_action_note": "测试",
        "entry_reason": "测试",
        "risk_note": "测试",
        "source": "test",
    }
