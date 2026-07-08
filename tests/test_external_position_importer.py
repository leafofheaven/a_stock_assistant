"""Task 65 tests for Streamlit trade-record import and position rebuild."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd

from core.external_positions.importer import (
    import_external_positions_frame,
    import_external_trades_and_rebuild_positions_frame,
    position_template_excel_bytes,
    read_uploaded_table,
    trade_template_excel_bytes,
)
from core.storage.duckdb_store import DuckDBStore


def test_trade_xlsx_template_contains_template_and_field_notes() -> None:
    """Trade template should be a dynamic XLSX with a data sheet and field notes."""
    excel = pd.ExcelFile(BytesIO(trade_template_excel_bytes()))

    assert excel.sheet_names == ["template", "字段说明"]
    template = pd.read_excel(excel, sheet_name="template")
    notes = pd.read_excel(excel, sheet_name="字段说明")
    assert {"trade_date", "ts_code", "side", "quantity", "price"}.issubset(template.columns)
    assert ["字段", "中文说明", "是否必填", "用户是否需要填写", "示例", "自动计算说明"] == notes.columns.tolist()
    side_note = notes[notes["字段"] == "side"].iloc[0]
    assert side_note["是否必填"] == "是"
    assert "buy/sell/买入/卖出" in side_note["自动计算说明"]
    amount_note = notes[notes["字段"] == "amount"].iloc[0]
    assert "quantity × price" in amount_note["自动计算说明"]


def test_position_xlsx_template_contains_template_and_field_notes() -> None:
    """Position snapshot template should also be generated dynamically."""
    excel = pd.ExcelFile(BytesIO(position_template_excel_bytes()))

    assert excel.sheet_names == ["template", "字段说明"]
    template = pd.read_excel(excel, sheet_name="template")
    notes = pd.read_excel(excel, sheet_name="字段说明")
    assert {"snapshot_date", "ts_code", "quantity", "cost_price"}.issubset(template.columns)
    assert ["字段", "中文说明", "是否必填", "用户是否需要填写", "示例", "自动计算说明"] == notes.columns.tolist()
    current_price_note = notes[notes["字段"] == "current_price"].iloc[0]
    assert current_price_note["用户是否需要填写"] == "不需要填写"
    assert "snapshot_date 当日或之前最近" in current_price_note["自动计算说明"]


def test_read_uploaded_xlsx_prefers_template_sheet() -> None:
    """Upload reader should read the template sheet when present."""
    uploaded = BytesIO(trade_template_excel_bytes())

    frame = read_uploaded_table(uploaded, "模拟交易记录模板.xlsx")

    assert "trade_date" in frame.columns
    assert "ts_code" in frame.columns


def test_read_uploaded_csv_utf8_sig() -> None:
    """Upload reader should handle CSV files with UTF-8 BOM."""
    uploaded = BytesIO("trade_date,ts_code,side,quantity,price\n20260706,000001,买入,100,10\n".encode("utf-8-sig"))

    frame = read_uploaded_table(uploaded, "trades.csv")

    assert frame.iloc[0]["side"] == "买入"


def test_trades_rebuild_weighted_cost_and_partial_sell(tmp_path: Path) -> None:
    """Buying twice and partially selling should preserve weighted cost."""
    store = _store(tmp_path)
    _seed_prices(store)
    trades = pd.DataFrame(
        [
            _trade("20260701", "000001", "buy", 100, 10, fee=0, external_id="t1"),
            _trade("20260702", "000001", "buy", 100, 20, fee=0, external_id="t2"),
            _trade("20260703", "000001", "sell", 50, 30, fee=0, external_id="t3"),
        ]
    )

    result = import_external_trades_and_rebuild_positions_frame(trades, store=store)
    positions = store.read_table("external_position_snapshots")

    assert result["status"] == "success"
    assert positions.iloc[0]["quantity"] == 150
    assert positions.iloc[0]["cost_price"] == 15
    assert positions.iloc[0]["current_price"] == 18


def test_full_sell_removes_current_position(tmp_path: Path) -> None:
    """Fully sold positions should not remain active for Task 64 holdings."""
    store = _store(tmp_path)
    _seed_prices(store)
    trades = pd.DataFrame(
        [
            _trade("20260701", "000001", "buy", 100, 10, external_id="t1"),
            _trade("20260702", "000001", "sell", 100, 11, external_id="t2"),
        ]
    )

    result = import_external_trades_and_rebuild_positions_frame(trades, store=store)
    positions = store.read_table("external_position_snapshots")

    assert result["status"] == "success"
    assert positions.empty
    assert result["current_position_count"] == 0


def test_oversell_fails_and_does_not_write(tmp_path: Path) -> None:
    """Overselling should fail atomically before writing trades or positions."""
    store = _store(tmp_path)
    _seed_prices(store)
    trades = pd.DataFrame([_trade("20260701", "000001", "sell", 100, 10, external_id="bad")])

    result = import_external_trades_and_rebuild_positions_frame(trades, store=store)

    assert result["status"] == "failed"
    assert "exceeds current holding" in result["error_rows"][0]["error"]
    assert store.read_table("external_trades").empty
    assert store.read_table("external_position_snapshots").empty


def test_chinese_side_amount_auto_and_default_account(tmp_path: Path) -> None:
    """Chinese side labels and blank amount/platform/account should normalize cleanly."""
    store = _store(tmp_path)
    _seed_prices(store)
    trades = pd.DataFrame(
        [
            {
                "trade_date": "2026-07-01",
                "ts_code": "000001",
                "side": "买入",
                "quantity": "100",
                "price": "10",
                "fee": "",
            }
        ]
    )

    result = import_external_trades_and_rebuild_positions_frame(trades, store=store)
    saved = store.read_table("external_trades")

    assert result["status"] == "success"
    assert saved.iloc[0]["side"] == "buy"
    assert saved.iloc[0]["amount"] == 1000
    assert saved.iloc[0]["platform"] == "同花顺模拟"
    assert saved.iloc[0]["account_name"] == "默认账户"


def test_position_snapshot_missing_auto_fields_is_filled_from_prices(tmp_path: Path) -> None:
    """Manual position snapshots may omit current price and PnL fields."""
    store = _store(tmp_path)
    _seed_prices(store)
    positions = pd.DataFrame(
        [
            {
                "snapshot_date": "20260706",
                "ts_code": "000001",
                "quantity": 100,
                "cost_price": 10,
            }
        ]
    )

    result = import_external_positions_frame(positions, store=store)
    saved = store.read_table("external_position_snapshots")

    assert result["status"] == "success"
    assert saved.iloc[0]["current_price"] == 18
    assert saved.iloc[0]["market_value"] == 1800
    assert saved.iloc[0]["pnl"] == 800
    assert round(saved.iloc[0]["pnl_pct"], 4) == 0.8


def test_position_snapshot_uses_price_on_or_before_snapshot_date(tmp_path: Path) -> None:
    """Position imports should not use prices after snapshot_date."""
    store = _store(tmp_path)
    _seed_prices(store)
    positions = pd.DataFrame(
        [
            {
                "snapshot_date": "20260705",
                "ts_code": "000001",
                "quantity": 100,
                "cost_price": 10,
            }
        ]
    )

    result = import_external_positions_frame(positions, store=store)
    saved = store.read_table("external_position_snapshots")

    assert result["status"] == "success"
    assert saved.iloc[0]["current_price"] == 17
    assert saved.iloc[0]["market_value"] == 1700
    assert saved.iloc[0]["pnl"] == 700
    assert round(saved.iloc[0]["pnl_pct"], 4) == 0.7


def test_position_snapshot_missing_price_warns_but_imports(tmp_path: Path) -> None:
    """Missing local price should return a warning instead of blocking manual snapshots."""
    store = _store(tmp_path)
    positions = pd.DataFrame(
        [
            {
                "snapshot_date": "20260706",
                "ts_code": "000001",
                "quantity": 100,
                "cost_price": 10,
            }
        ]
    )

    result = import_external_positions_frame(positions, store=store)
    saved = store.read_table("external_position_snapshots")

    assert result["status"] == "success"
    assert "未找到 snapshot_date 当日或之前的本地行情" in result["warning"]
    assert pd.isna(saved.iloc[0]["current_price"])


def test_trade_rebuild_warns_when_local_price_missing(tmp_path: Path) -> None:
    """Missing local price should warn but not block position rebuild."""
    store = _store(tmp_path)
    trades = pd.DataFrame([_trade("20260701", "000001", "buy", 100, 10, external_id="missing-price")])

    result = import_external_trades_and_rebuild_positions_frame(trades, store=store)
    saved = store.read_table("external_position_snapshots")

    assert result["status"] == "success"
    assert "未找到本地最新行情" in result["warning"]
    assert pd.isna(saved.iloc[0]["current_price"])


def test_duplicate_trade_import_does_not_double_position(tmp_path: Path) -> None:
    """Re-importing the same trade file should be idempotent."""
    store = _store(tmp_path)
    _seed_prices(store)
    trades = pd.DataFrame([_trade("20260701", "000001", "buy", 100, 10, external_id="same")])

    first = import_external_trades_and_rebuild_positions_frame(trades, store=store)
    second = import_external_trades_and_rebuild_positions_frame(trades, store=store)
    positions = store.read_table("external_position_snapshots")

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert positions.iloc[0]["quantity"] == 100
    assert len(store.read_table("external_trades")) == 1


def test_streamlit_source_contains_trade_import_controls() -> None:
    """Streamlit should expose trade-record import as the primary user flow."""
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")

    for phrase in [
        "下载模拟交易记录模板.xlsx",
        "上传模拟交易记录 Excel",
        "导入模拟交易记录",
        "日常只需要维护这张交易流水表",
        "高级：手动校正当前持仓",
        "下载持仓快照模板.xlsx",
        "上传持仓快照 Excel",
        "导入持仓快照",
    ]:
        assert phrase in source


def _store(tmp_path: Path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "external_position_importer.duckdb")
    store.initialize()
    return store


def _seed_prices(store: DuckDBStore) -> None:
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "平安银行",
                    "industry": "银行",
                    "market": "主板",
                    "exchange": "SZSE",
                }
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260705",
                    "open": 16.0,
                    "high": 17.5,
                    "low": 15.5,
                    "close": 17.0,
                    "pre_close": 16.0,
                    "change": 1.0,
                    "pct_chg": 6.25,
                    "vol": 1,
                    "amount": 1,
                },
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260706",
                    "open": 17.0,
                    "high": 18.5,
                    "low": 16.5,
                    "close": 18.0,
                    "pre_close": 17.0,
                    "change": 1.0,
                    "pct_chg": 5.88,
                    "vol": 1,
                    "amount": 1,
                }
            ]
        ),
    )


def _trade(trade_date: str, ts_code: str, side: str, quantity: float, price: float, fee: float = 0, external_id: str = "") -> dict[str, object]:
    return {
        "platform": "同花顺模拟",
        "account_name": "默认账户",
        "trade_date": trade_date,
        "ts_code": ts_code,
        "side": side,
        "quantity": quantity,
        "price": price,
        "amount": "",
        "fee": fee,
        "external_id": external_id,
    }
