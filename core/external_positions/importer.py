"""Import and match external simulated trades and position snapshots."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
import uuid

import pandas as pd

from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError

TRADE_COLUMNS = [
    "platform",
    "account_name",
    "trade_date",
    "ts_code",
    "name",
    "side",
    "quantity",
    "price",
    "amount",
    "fee",
    "note",
    "external_id",
]

POSITION_COLUMNS = [
    "platform",
    "account_name",
    "snapshot_date",
    "ts_code",
    "name",
    "quantity",
    "cost_price",
    "current_price",
    "market_value",
    "pnl",
    "pnl_pct",
    "note",
]

TRADE_TABLE_COLUMNS = [
    "id",
    *TRADE_COLUMNS,
    "matched_plan_id",
    "matched_entry_zone_date",
    "created_at",
    "updated_at",
]

POSITION_TABLE_COLUMNS = [
    "id",
    *POSITION_COLUMNS,
    "matched_plan_id",
    "matched_entry_zone_date",
    "stop_loss",
    "target_price",
    "entry_low",
    "entry_high",
    "reward_risk_ratio",
    "position_status",
    "risk_status",
    "risk_status_cn",
    "match_note",
    "created_at",
    "updated_at",
]

RISK_STATUS_CN = {
    "hit_stop_loss": "已跌破止损",
    "near_stop_loss": "接近止损",
    "hit_target": "已达到目标价",
    "chased_high": "成本高于买入区间",
    "entered_in_zone": "已进入买入区间",
    "insufficient_data": "数据不足",
    "normal": "正常跟踪",
}


def trade_template_frame() -> pd.DataFrame:
    """Return a CSV template for external trades."""
    return pd.DataFrame(
        [
            {
                "platform": "同花顺模拟",
                "account_name": "默认账户",
                "trade_date": "2026-06-30",
                "ts_code": "000725.SZ",
                "name": "京东方A",
                "side": "buy",
                "quantity": 10000,
                "price": 7.50,
                "amount": 75000,
                "fee": 0,
                "note": "根据观察池计划买入",
                "external_id": "",
            }
        ],
        columns=TRADE_COLUMNS,
    )


def trade_template_excel_bytes() -> bytes:
    """Return an XLSX template for simulated trade records."""
    return _template_excel_bytes(trade_template_frame(), _trade_field_notes())


def position_template_frame() -> pd.DataFrame:
    """Return a CSV template for external position snapshots."""
    return pd.DataFrame(
        [
            {
                "platform": "同花顺模拟",
                "account_name": "默认账户",
                "snapshot_date": "2026-06-30",
                "ts_code": "000725.SZ",
                "name": "京东方A",
                "quantity": 10000,
                "cost_price": 7.50,
                "current_price": 7.79,
                "market_value": 77900,
                "pnl": 2900,
                "pnl_pct": "3.87%",
                "note": "外部模拟持仓",
            }
        ],
        columns=POSITION_COLUMNS,
    )


def position_template_excel_bytes() -> bytes:
    """Return an XLSX template for simulated position snapshots."""
    return _template_excel_bytes(position_template_frame(), _position_field_notes())


def read_uploaded_table(file_obj: Any, filename: str = "") -> pd.DataFrame:
    """Read an uploaded CSV/XLSX table for Streamlit and tests."""
    name = (filename or getattr(file_obj, "name", "") or "").lower()
    if name.endswith((".xlsx", ".xls")):
        excel = pd.ExcelFile(file_obj)
        sheet = "template" if "template" in excel.sheet_names else excel.sheet_names[0]
        frame = pd.read_excel(excel, sheet_name=sheet, dtype=str, keep_default_na=False)
    else:
        data = file_obj.read() if hasattr(file_obj, "read") else file_obj
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            frame = pd.read_csv(BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig")
        except UnicodeDecodeError:
            frame = pd.read_csv(BytesIO(data), dtype=str, keep_default_na=False, encoding="gbk")
    if frame.empty:
        raise ValueError("上传文件为空。")
    if not len(frame.columns):
        raise ValueError("上传文件没有字段列。")
    return frame


def normalize_ts_code(value: Any) -> tuple[str | None, str | None]:
    """Normalize common A-share codes and reject BSE codes by default."""
    text = str(value or "").strip().upper()
    if not text:
        return None, "missing_ts_code"
    if "." in text:
        symbol, suffix = text.split(".", 1)
    else:
        symbol, suffix = text, ""
    symbol = "".join(ch for ch in symbol if ch.isdigit())
    if len(symbol) != 6:
        return None, "invalid_ts_code"
    if symbol.startswith(("4", "8")) or suffix in {"BJ", "BSE"}:
        return None, "unsupported_bse"
    if suffix in {"SZ", "SH"}:
        return f"{symbol}.{suffix}", None
    if symbol.startswith(("0", "2", "3")):
        return f"{symbol}.SZ", None
    if symbol.startswith(("5", "6", "9")):
        return f"{symbol}.SH", None
    return None, "invalid_ts_code"


def parse_number(value: Any) -> float | None:
    """Parse numeric strings, including Chinese percentage strings."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1].strip()
    try:
        number = float(text)
    except ValueError:
        return None
    return number / 100 if is_percent else number


def import_external_trades_frame(
    df: pd.DataFrame,
    *,
    store: DuckDBStore,
    source_file: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate and import external trade rows into DuckDB."""
    store.initialize()
    errors = _missing_columns(df, ["trade_date", "ts_code", "side", "quantity", "price"])
    if errors:
        return _import_result("trades", len(df), 0, 0, 0, len(df), errors, dry_run=dry_run)
    rows, row_errors = _normalize_trade_rows(df)
    existing = _safe_read_table(store, "external_trades")
    existing_ids = set(existing.get("id", [])) if not existing.empty else set()
    inserted = len([row for row in rows if row["id"] not in existing_ids])
    updated = len(rows) - inserted
    if not dry_run and rows:
        store.upsert_dataframe("external_trades", pd.DataFrame(rows, columns=TRADE_TABLE_COLUMNS))
        _write_batch(store, "trades", source_file, rows, inserted, updated, row_errors)
    return _import_result("trades", len(df), len(rows), inserted, updated, len(row_errors), row_errors, dry_run=dry_run)


def import_external_trades_and_rebuild_positions_frame(
    df: pd.DataFrame,
    *,
    store: DuckDBStore,
    source_file: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import simulated trades and rebuild current positions from all trade rows."""
    store.initialize()
    errors = _missing_columns(df, ["trade_date", "ts_code", "side", "quantity", "price"])
    if errors:
        return _trade_rebuild_result("failed", len(df), 0, 0, [], "", "", errors, dry_run=dry_run)
    rows, row_errors = _normalize_trade_rows(df)
    if row_errors:
        return _trade_rebuild_result("failed", len(df), 0, 0, [], "", "", row_errors, dry_run=dry_run)
    existing = _safe_read_table(store, "external_trades")
    combined = _combined_trade_rows(existing, rows)
    positions, rebuild_errors = rebuild_external_positions_from_trades(combined, store=store)
    if rebuild_errors:
        return _trade_rebuild_result("failed", len(df), 0, 0, [], "", "", rebuild_errors, dry_run=dry_run)

    existing_ids = set(existing.get("id", [])) if not existing.empty else set()
    inserted = len([row for row in rows if row["id"] not in existing_ids])
    updated = len(rows) - inserted
    affected_keys = sorted({(row["platform"], row["account_name"], row["ts_code"]) for row in rows})
    affected_symbols = sorted({row["ts_code"] for row in rows})
    current_positions = positions[positions["quantity"].map(parse_number).fillna(0) > 0].copy() if not positions.empty else positions
    if not dry_run:
        if rows:
            store.upsert_dataframe("external_trades", pd.DataFrame(rows, columns=TRADE_TABLE_COLUMNS))
            _delete_position_snapshots_for_keys(store, affected_keys)
        if not current_positions.empty:
            matched = match_position_rows(current_positions, store=store)
            store.upsert_dataframe("external_position_snapshots", matched[POSITION_TABLE_COLUMNS])
        _write_batch(store, "trades_rebuild_positions", source_file, rows, inserted, updated, [])
    latest_trade_date = max([str(row.get("trade_date") or "") for row in rows], default="")
    snapshot_date = _latest_daily_price_date(store) or latest_trade_date
    result = _trade_rebuild_result(
        "success",
        len(df),
        len(rows),
        0,
        affected_symbols,
        latest_trade_date,
        snapshot_date,
        [],
        dry_run=dry_run,
    )
    result.update(
        {
            "inserted_rows": inserted,
            "updated_rows": updated,
            "rebuilt_position_rows": int(len(current_positions)),
            "current_position_count": int(len(current_positions)),
            "target_trade_table": "external_trades",
            "target_position_table": "external_position_snapshots",
            "warning": _trade_rebuild_warning(current_positions),
        }
    )
    return result


def rebuild_external_positions_from_trades(trades: pd.DataFrame, *, store: DuckDBStore) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Rebuild current positions from normalized trade rows."""
    if trades.empty:
        return pd.DataFrame(columns=POSITION_TABLE_COLUMNS), []
    frame = trades.copy()
    frame["_order"] = range(len(frame))
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    frame = frame.sort_values(["platform", "account_name", "ts_code", "trade_date", "_order"])
    price_map = _latest_price_detail_map(_safe_read_table(store, "daily_price"))
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    now = datetime.now().replace(microsecond=0)
    snapshot_date = _latest_daily_price_date(store) or str(frame["trade_date"].max())
    stock_basic = _safe_read_table(store, "stock_basic")
    for (platform, account_name, code), group in frame.groupby(["platform", "account_name", "ts_code"], dropna=False):
        quantity = 0.0
        cost_price = 0.0
        latest_name = ""
        for _, trade in group.iterrows():
            side = str(trade.get("side") or "").lower()
            trade_qty = parse_number(trade.get("quantity")) or 0.0
            price = parse_number(trade.get("price")) or 0.0
            fee = parse_number(trade.get("fee")) or 0.0
            latest_name = _text(trade.get("name")) or latest_name
            if side == "buy":
                new_qty = quantity + trade_qty
                total_cost = quantity * cost_price + trade_qty * price + fee
                cost_price = total_cost / new_qty if new_qty else 0.0
                quantity = new_qty
            elif side == "sell":
                if trade_qty > quantity + 1e-8:
                    errors.append(
                        {
                            "row": int(trade.get("_order", 0)) + 2,
                            "field": "quantity",
                            "error": f"sell quantity exceeds current holding for {code}",
                        }
                    )
                    break
                quantity -= trade_qty
                if quantity <= 1e-8:
                    quantity = 0.0
        if errors:
            continue
        if quantity <= 0:
            continue
        code_text = str(code)
        price_detail = price_map.get(code_text, {})
        current_price = price_detail.get("close")
        stock_info = _lookup_stock(stock_basic, code_text)
        name = latest_name or (stock_info or {}).get("name") or ""
        row = {
            "id": _stable_id("position", platform, account_name, snapshot_date, code_text),
            "platform": platform,
            "account_name": account_name,
            "snapshot_date": snapshot_date,
            "ts_code": code_text,
            "name": name,
            "quantity": quantity,
            "cost_price": cost_price,
            "current_price": current_price,
            "market_value": quantity * current_price if current_price is not None else None,
            "pnl": (current_price - cost_price) * quantity if current_price is not None else None,
            "pnl_pct": (current_price / cost_price - 1) if current_price is not None and cost_price else None,
            "note": "由模拟交易记录自动重建",
            "matched_plan_id": None,
            "matched_entry_zone_date": None,
            "stop_loss": None,
            "target_price": None,
            "entry_low": None,
            "entry_high": None,
            "reward_risk_ratio": None,
            "position_status": "active",
            "risk_status": "insufficient_data",
            "risk_status_cn": RISK_STATUS_CN["insufficient_data"],
            "match_note": "由交易流水自动重建。" if current_price is not None else "由交易流水自动重建；未找到本地行情，盈亏字段暂缺。",
            "created_at": now,
            "updated_at": now,
        }
        rows.append(row)
    return pd.DataFrame(rows, columns=POSITION_TABLE_COLUMNS), errors


def import_external_positions_frame(
    df: pd.DataFrame,
    *,
    store: DuckDBStore,
    source_file: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate, match, and import external position snapshots."""
    store.initialize()
    errors = _missing_columns(df, ["snapshot_date", "ts_code", "quantity", "cost_price"])
    if errors:
        return _import_result("positions", len(df), 0, 0, 0, len(df), errors, dry_run=dry_run)
    rows, row_errors = _normalize_position_rows(df)
    matched = match_position_rows(pd.DataFrame(rows), store=store).to_dict("records") if rows else []
    existing = _safe_read_table(store, "external_position_snapshots")
    existing_ids = set(existing.get("id", [])) if not existing.empty else set()
    inserted = len([row for row in matched if row["id"] not in existing_ids])
    updated = len(matched) - inserted
    if not dry_run and matched:
        store.upsert_dataframe("external_position_snapshots", pd.DataFrame(matched, columns=POSITION_TABLE_COLUMNS))
        _write_batch(store, "positions", source_file, matched, inserted, updated, row_errors)
    result = _import_result("positions", len(df), len(matched), inserted, updated, len(row_errors), row_errors, dry_run=dry_run)
    warning = _position_import_warning(pd.DataFrame(matched))
    if warning:
        result["warning"] = warning
    return result


def match_external_positions(store: DuckDBStore) -> dict[str, Any]:
    """Re-match all imported position snapshots with latest local context."""
    store.initialize()
    positions = _safe_read_table(store, "external_position_snapshots")
    if positions.empty:
        return {"status": "partial_success", "matched_rows": 0, "message": "暂无外部持仓快照。"}
    matched = match_position_rows(positions, store=store)
    store.upsert_dataframe("external_position_snapshots", matched[POSITION_TABLE_COLUMNS])
    return {"status": "success", "matched_rows": int(len(matched)), "message": "外部持仓匹配完成。"}


def match_position_rows(rows: pd.DataFrame, *, store: DuckDBStore) -> pd.DataFrame:
    """Attach stock, entry zone, and risk status fields to position rows."""
    if rows.empty:
        return pd.DataFrame(columns=POSITION_TABLE_COLUMNS)
    stock_basic = _safe_read_table(store, "stock_basic")
    entry_zones = _safe_read_table(store, "entry_zone_snapshots")
    watchlist = _safe_read_table(store, "review_decisions")
    daily_price = _safe_read_table(store, "daily_price")
    output: list[dict[str, Any]] = []
    for item in rows.to_dict("records"):
        row = {column: item.get(column) for column in POSITION_TABLE_COLUMNS}
        code = row.get("ts_code")
        stock_info = _lookup_stock(stock_basic, code)
        if stock_info and not row.get("name"):
            row["name"] = stock_info.get("name")
        if parse_number(row.get("current_price")) is None:
            current_price = _price_on_or_before(daily_price, str(code), str(row.get("snapshot_date") or ""))
            if current_price is not None:
                row["current_price"] = current_price
        row = _fill_position_amounts(row)
        zone = _match_entry_zone(entry_zones, str(code), str(row.get("snapshot_date") or ""))
        if zone:
            row.update(
                {
                    "matched_entry_zone_date": zone.get("trade_date"),
                    "stop_loss": zone.get("stop_loss"),
                    "target_price": zone.get("target_price"),
                    "entry_low": zone.get("entry_low"),
                    "entry_high": zone.get("entry_high"),
                    "reward_risk_ratio": zone.get("reward_risk_ratio"),
                }
            )
        risk_status, note = _risk_status(row, zone)
        if not stock_info:
            note = "unknown_symbol；" + note
        if _is_watch(watchlist, str(code)):
            note = "已匹配观察池；" + note
        row["risk_status"] = risk_status
        row["risk_status_cn"] = RISK_STATUS_CN[risk_status]
        row["position_status"] = "active"
        row["match_note"] = note
        output.append(row)
    result = pd.DataFrame(output)
    for column in POSITION_TABLE_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result[POSITION_TABLE_COLUMNS]


def _normalize_trade_rows(df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = datetime.now().replace(microsecond=0)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in df.iterrows():
        code, error = normalize_ts_code(row.get("ts_code"))
        if error:
            errors.append({"row": int(index) + 2, "error": error})
            continue
        side = _normalize_side(row.get("side"))
        if side not in {"buy", "sell"}:
            errors.append({"row": int(index) + 2, "error": "side must be buy/sell or 买入/卖出"})
            continue
        quantity = parse_number(row.get("quantity"))
        price = parse_number(row.get("price"))
        if quantity is None or price is None:
            errors.append({"row": int(index) + 2, "error": "quantity and price are required numbers"})
            continue
        trade_date = _normalize_trade_date(row.get("trade_date"))
        if not trade_date:
            errors.append({"row": int(index) + 2, "error": "trade_date is required"})
            continue
        amount = parse_number(row.get("amount"))
        if amount is None:
            amount = quantity * price
        platform = _text(row.get("platform")) or "同花顺模拟"
        account_name = _text(row.get("account_name")) or "默认账户"
        external_id = _text(row.get("external_id"))
        record = {
            "platform": platform,
            "account_name": account_name,
            "trade_date": trade_date,
            "ts_code": code,
            "name": _text(row.get("name")),
            "side": side,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "fee": parse_number(row.get("fee")) or 0.0,
            "note": _text(row.get("note")),
            "external_id": external_id,
            "matched_plan_id": None,
            "matched_entry_zone_date": None,
            "created_at": now,
            "updated_at": now,
        }
        if external_id:
            record["id"] = _stable_id("trade", platform, account_name, external_id)
        else:
            record["id"] = _stable_id("trade", platform, account_name, trade_date, code, side, quantity, price, record["fee"])
        rows.append(record)
    return rows, errors


def _normalize_position_rows(df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = datetime.now().replace(microsecond=0)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in df.iterrows():
        code, error = normalize_ts_code(row.get("ts_code"))
        if error:
            errors.append({"row": int(index) + 2, "error": error})
            continue
        quantity = parse_number(row.get("quantity"))
        cost_price = parse_number(row.get("cost_price"))
        if quantity is None or cost_price is None:
            errors.append({"row": int(index) + 2, "error": "quantity and cost_price are required numbers"})
            continue
        snapshot_date = _normalize_trade_date(row.get("snapshot_date"))
        if not snapshot_date:
            errors.append({"row": int(index) + 2, "error": "snapshot_date is required"})
            continue
        platform = _text(row.get("platform")) or "同花顺模拟"
        account_name = _text(row.get("account_name")) or "默认账户"
        record = {
            "platform": platform,
            "account_name": account_name,
            "snapshot_date": snapshot_date,
            "ts_code": code,
            "name": _text(row.get("name")),
            "quantity": quantity,
            "cost_price": cost_price,
            "current_price": parse_number(row.get("current_price")),
            "market_value": parse_number(row.get("market_value")),
            "pnl": parse_number(row.get("pnl")),
            "pnl_pct": parse_number(row.get("pnl_pct")),
            "note": _text(row.get("note")),
            "matched_plan_id": None,
            "matched_entry_zone_date": None,
            "stop_loss": None,
            "target_price": None,
            "entry_low": None,
            "entry_high": None,
            "reward_risk_ratio": None,
            "position_status": "active",
            "risk_status": "insufficient_data",
            "risk_status_cn": RISK_STATUS_CN["insufficient_data"],
            "match_note": "",
            "created_at": now,
            "updated_at": now,
        }
        record["id"] = _stable_id("position", platform, account_name, snapshot_date, code)
        rows.append(record)
    return rows, errors


def _risk_status(row: dict[str, Any], zone: dict[str, Any] | None) -> tuple[str, str]:
    current = parse_number(row.get("current_price"))
    cost = parse_number(row.get("cost_price"))
    stop = parse_number(row.get("stop_loss"))
    target = parse_number(row.get("target_price"))
    low = parse_number(row.get("entry_low"))
    high = parse_number(row.get("entry_high"))
    if not zone or current is None:
        return "insufficient_data", "未匹配买入区间或当前价缺失。"
    if stop is not None and current <= stop:
        return "hit_stop_loss", "当前价已低于或等于止损位。"
    if stop is not None and current > stop and (current - stop) / current <= 0.03:
        return "near_stop_loss", "当前价距离止损位 3% 以内。"
    if target is not None and current >= target:
        return "hit_target", "当前价已达到或超过目标价位。"
    if cost is not None and high is not None and cost > high and str(zone.get("chase_risk")) == "high":
        return "chased_high", "成本价高于买入区间且追高风险较高。"
    if cost is not None and low is not None and high is not None and low <= cost <= high:
        return "entered_in_zone", "成本价位于参考买入区间。"
    return "normal", "正常跟踪。"


def _match_entry_zone(entry_zones: pd.DataFrame, ts_code: str, target_date: str) -> dict[str, Any] | None:
    if entry_zones.empty or "ts_code" not in entry_zones.columns or "trade_date" not in entry_zones.columns:
        return None
    rows = entry_zones[entry_zones["ts_code"].astype(str) == ts_code].copy()
    if rows.empty:
        return None
    if target_date:
        rows = rows[rows["trade_date"].astype(str) <= target_date]
    if rows.empty:
        return None
    return rows.sort_values("trade_date").iloc[-1].to_dict()


def _lookup_stock(stock_basic: pd.DataFrame, ts_code: str | None) -> dict[str, Any] | None:
    if stock_basic.empty or "ts_code" not in stock_basic.columns or not ts_code:
        return None
    rows = stock_basic[stock_basic["ts_code"].astype(str) == str(ts_code)]
    return None if rows.empty else rows.iloc[-1].to_dict()


def _latest_price_map(daily_price: pd.DataFrame) -> dict[str, float]:
    if daily_price.empty or not {"ts_code", "trade_date", "close"}.issubset(daily_price.columns):
        return {}
    result = {}
    for code, rows in daily_price.sort_values("trade_date").groupby("ts_code"):
        result[str(code)] = float(pd.to_numeric(rows.iloc[-1]["close"], errors="coerce"))
    return result


def _latest_price_detail_map(daily_price: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if daily_price.empty or not {"ts_code", "trade_date", "close"}.issubset(daily_price.columns):
        return {}
    result: dict[str, dict[str, Any]] = {}
    frame = daily_price.copy()
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    for code, rows in frame.sort_values("trade_date").groupby("ts_code"):
        latest = rows.iloc[-1]
        close = pd.to_numeric(latest.get("close"), errors="coerce")
        result[str(code)] = {
            "trade_date": str(latest.get("trade_date") or ""),
            "close": None if pd.isna(close) else float(close),
        }
    return result


def _price_on_or_before(daily_price: pd.DataFrame, ts_code: str, snapshot_date: str) -> float | None:
    if daily_price.empty or not {"ts_code", "trade_date", "close"}.issubset(daily_price.columns):
        return None
    target_date = _normalize_trade_date(snapshot_date)
    rows = daily_price[daily_price["ts_code"].astype(str) == str(ts_code)].copy()
    if rows.empty:
        return None
    rows["trade_date"] = rows["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    if target_date:
        rows = rows[rows["trade_date"] <= target_date]
    if rows.empty:
        return None
    close = pd.to_numeric(rows.sort_values("trade_date").iloc[-1].get("close"), errors="coerce")
    return None if pd.isna(close) else float(close)


def _latest_daily_price_date(store: DuckDBStore) -> str:
    daily_price = _safe_read_table(store, "daily_price")
    if daily_price.empty or "trade_date" not in daily_price.columns:
        return ""
    values = daily_price["trade_date"].dropna().astype(str).str.replace("-", "", regex=False).str[:8]
    return str(values.max()) if not values.empty else ""


def _combined_trade_rows(existing: pd.DataFrame, rows: list[dict[str, Any]]) -> pd.DataFrame:
    existing_records = existing.to_dict("records") if not existing.empty else []
    combined = pd.DataFrame([*existing_records, *rows])
    if combined.empty:
        return pd.DataFrame(columns=TRADE_TABLE_COLUMNS)
    for column in TRADE_TABLE_COLUMNS:
        if column not in combined.columns:
            combined[column] = pd.NA
    combined = combined[TRADE_TABLE_COLUMNS].drop_duplicates(subset=["id"], keep="last")
    return combined.reset_index(drop=True)


def _delete_position_snapshots_for_keys(store: DuckDBStore, keys: list[tuple[str, str, str]]) -> None:
    if not keys:
        return
    with store.connect(read_only=False) as conn:
        for platform, account_name, ts_code in keys:
            conn.execute(
                """
                DELETE FROM external_position_snapshots
                WHERE platform = ? AND account_name = ? AND ts_code = ?
                """,
                [platform, account_name, ts_code],
            )


def _trade_rebuild_result(
    status: str,
    total_rows: int,
    imported_rows: int,
    skipped_rows: int,
    affected_symbols: list[str],
    latest_trade_date: str,
    latest_snapshot_date: str,
    errors: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "status": status,
        "import_type": "trades_rebuild_positions",
        "total_rows": int(total_rows),
        "imported_rows": int(imported_rows),
        "skipped_rows": int(skipped_rows),
        "invalid_rows": int(len(errors)),
        "error_rows": errors,
        "affected_symbols": affected_symbols,
        "latest_trade_date": latest_trade_date,
        "latest_snapshot_date": latest_snapshot_date,
        "target_tables": ["external_trades", "external_position_snapshots"],
        "target_trade_table": "external_trades",
        "target_position_table": "external_position_snapshots",
        "rebuilt_position_rows": 0,
        "current_position_count": 0,
        "warning": "",
        "dry_run": dry_run,
    }


def _trade_rebuild_warning(current_positions: pd.DataFrame) -> str:
    if current_positions.empty:
        return "交易记录已导入；当前没有未清仓模拟持仓。"
    if "current_price" in current_positions.columns and current_positions["current_price"].isna().any():
        return "部分持仓未找到本地最新行情，当前价、市值和盈亏字段暂缺。"
    return ""


def _position_import_warning(positions: pd.DataFrame) -> str:
    if positions.empty:
        return ""
    if "current_price" in positions.columns and positions["current_price"].isna().any():
        return "部分持仓未找到 snapshot_date 当日或之前的本地行情，当前价、市值和盈亏字段暂缺。"
    return ""


def _template_excel_bytes(template: pd.DataFrame, notes: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        template.to_excel(writer, index=False, sheet_name="template")
        notes.to_excel(writer, index=False, sheet_name="字段说明")
    return output.getvalue()


def _trade_field_notes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _field_note("trade_date", "交易日期", "是", "需要", "20260706", "不自动计算；支持 YYYYMMDD 或 YYYY-MM-DD。"),
            _field_note("ts_code", "股票代码", "是", "需要", "000001.SZ", "不自动计算；支持 000001 / 000001.SZ。"),
            _field_note("side", "买卖方向", "是", "需要", "买入", "支持 buy/sell/买入/卖出。"),
            _field_note("quantity", "成交数量", "是", "需要", "1000", "不自动计算。"),
            _field_note("price", "成交价格", "是", "需要", "10.50", "不自动计算。"),
            _field_note("name", "股票名称", "否", "推荐填写", "平安银行", "可空；系统会尽量从本地股票基础表补名称。"),
            _field_note("note", "备注", "否", "推荐填写", "模拟买入", "可空。"),
            _field_note("amount", "成交金额", "否", "可不填", "10500", "为空时按 quantity × price 自动计算。"),
            _field_note("fee", "手续费", "否", "可不填", "0", "为空时默认 0，并参与买入成本计算。"),
            _field_note("platform", "平台", "否", "可不填", "同花顺模拟", "为空时默认 同花顺模拟。"),
            _field_note("account_name", "账户名称", "否", "可不填", "默认账户", "为空时默认 默认账户。"),
            _field_note("external_id", "外部流水号", "否", "可不填", "THS-001", "填写后用于幂等去重；不填则按交易要素生成稳定 ID。"),
        ]
    )


def _position_field_notes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _field_note("snapshot_date", "快照日期", "是", "需要", "20260706", "不自动计算；支持 YYYYMMDD 或 YYYY-MM-DD。"),
            _field_note("ts_code", "股票代码", "是", "需要", "000001.SZ", "不自动计算；支持 000001 / 000001.SZ。"),
            _field_note("quantity", "当前持仓数量", "是", "需要", "1000", "不自动计算。"),
            _field_note("cost_price", "持仓成本价", "是", "需要", "10.50", "不自动计算。"),
            _field_note("name", "股票名称", "否", "推荐填写", "平安银行", "可空；系统会尽量从本地股票基础表补名称。"),
            _field_note("note", "备注", "否", "推荐填写", "手动校正", "可空。"),
            _field_note("platform", "平台", "否", "可不填", "同花顺模拟", "为空时默认 同花顺模拟。"),
            _field_note("account_name", "账户名称", "否", "可不填", "默认账户", "为空时默认 默认账户。"),
            _field_note("current_price", "当前价", "否", "不需要填写", "10.80", "为空时按 snapshot_date 当日或之前最近 daily_price.close 自动补。"),
            _field_note("market_value", "持仓市值", "否", "不需要填写", "10800", "系统按 quantity × current_price 自动计算。"),
            _field_note("pnl", "浮动盈亏", "否", "不需要填写", "300", "系统按 (current_price - cost_price) × quantity 自动计算。"),
            _field_note("pnl_pct", "浮动盈亏比例", "否", "不需要填写", "0.0286", "系统按 current_price / cost_price - 1 自动计算。"),
        ]
    )


def _field_note(field: str, cn: str, required: str, user_fill: str, example: str, auto_note: str) -> dict[str, str]:
    return {
        "字段": field,
        "中文说明": cn,
        "是否必填": required,
        "用户是否需要填写": user_fill,
        "示例": example,
        "自动计算说明": auto_note,
    }


def _normalize_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "买入": "buy",
        "买": "buy",
        "b": "buy",
        "buy": "buy",
        "卖出": "sell",
        "卖": "sell",
        "s": "sell",
        "sell": "sell",
    }
    return mapping.get(text, text)


def _normalize_trade_date(value: Any) -> str:
    text = _text(value).replace("-", "").replace("/", "")
    if not text:
        return ""
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y%m%d")


def _fill_position_amounts(row: dict[str, Any]) -> dict[str, Any]:
    quantity = parse_number(row.get("quantity"))
    cost = parse_number(row.get("cost_price"))
    current = parse_number(row.get("current_price"))
    if quantity is not None and current is not None:
        row["market_value"] = quantity * current
    if quantity is not None and current is not None and cost is not None:
        row["pnl"] = (current - cost) * quantity
    if current is not None and cost:
        row["pnl_pct"] = (current - cost) / cost
    return row


def _write_batch(store: DuckDBStore, import_type: str, source_file: str, rows: list[dict[str, Any]], inserted: int, updated: int, errors: list[dict[str, Any]]) -> None:
    now = datetime.now().replace(microsecond=0)
    first = rows[0] if rows else {}
    batch = pd.DataFrame(
        [
            {
                "batch_id": str(uuid.uuid4()),
                "import_type": import_type,
                "source_file": source_file,
                "platform": first.get("platform"),
                "account_name": first.get("account_name"),
                "imported_rows": len(rows),
                "inserted_rows": inserted,
                "updated_rows": updated,
                "skipped_rows": len(errors),
                "error_rows": len(errors),
                "status": "success" if not errors else "partial_success",
                "created_at": now,
            }
        ]
    )
    store.upsert_dataframe("external_import_batches", batch)


def _missing_columns(df: pd.DataFrame, required: list[str]) -> list[dict[str, Any]]:
    missing = [column for column in required if column not in df.columns]
    return [{"row": 0, "error": f"missing required columns: {', '.join(missing)}"}] if missing else []


def _import_result(import_type: str, total: int, imported: int, inserted: int, updated: int, skipped: int, errors: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    return {
        "status": "success" if not errors else ("failed" if imported == 0 else "partial_success"),
        "import_type": import_type,
        "total_rows": int(total),
        "imported_rows": int(imported),
        "inserted_rows": int(inserted),
        "updated_rows": int(updated),
        "skipped_rows": int(skipped),
        "error_rows": errors,
        "dry_run": dry_run,
    }


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _is_watch(watchlist: pd.DataFrame, ts_code: str) -> bool:
    if watchlist.empty or "ts_code" not in watchlist.columns:
        return False
    rows = watchlist[watchlist["ts_code"].astype(str) == ts_code]
    if rows.empty:
        return False
    if "decision" in rows.columns:
        rows = rows[rows["decision"] == "watch"]
    if "review_status" in rows.columns:
        rows = rows[rows["review_status"].fillna("active") == "active"]
    return not rows.empty


def _stable_id(*parts: Any) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(str(part) for part in parts)))


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def read_csv_file(path: Path | str) -> pd.DataFrame:
    """Read a UTF-8 CSV file, accepting BOM."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
