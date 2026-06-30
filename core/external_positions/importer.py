"""Import and match external simulated trades and position snapshots."""

from __future__ import annotations

from datetime import datetime
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
    errors = _missing_columns(df, ["platform", "account_name", "trade_date", "ts_code", "side", "quantity", "price"])
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


def import_external_positions_frame(
    df: pd.DataFrame,
    *,
    store: DuckDBStore,
    source_file: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate, match, and import external position snapshots."""
    store.initialize()
    errors = _missing_columns(df, ["platform", "account_name", "snapshot_date", "ts_code", "quantity", "cost_price"])
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
    return _import_result("positions", len(df), len(matched), inserted, updated, len(row_errors), row_errors, dry_run=dry_run)


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
    latest_price = _latest_price_map(_safe_read_table(store, "daily_price"))
    output: list[dict[str, Any]] = []
    for item in rows.to_dict("records"):
        row = {column: item.get(column) for column in POSITION_TABLE_COLUMNS}
        code = row.get("ts_code")
        stock_info = _lookup_stock(stock_basic, code)
        if stock_info and not row.get("name"):
            row["name"] = stock_info.get("name")
        if row.get("current_price") is None and code in latest_price:
            row["current_price"] = latest_price[code]
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
        side = str(row.get("side") or "").strip().lower()
        if side not in {"buy", "sell"}:
            errors.append({"row": int(index) + 2, "error": "side must be buy or sell"})
            continue
        quantity = parse_number(row.get("quantity"))
        price = parse_number(row.get("price"))
        if quantity is None or price is None:
            errors.append({"row": int(index) + 2, "error": "quantity and price are required numbers"})
            continue
        amount = parse_number(row.get("amount"))
        if amount is None:
            amount = quantity * price
        record = {
            "platform": _text(row.get("platform")),
            "account_name": _text(row.get("account_name")),
            "trade_date": _text(row.get("trade_date")),
            "ts_code": code,
            "name": _text(row.get("name")),
            "side": side,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "fee": parse_number(row.get("fee")) or 0.0,
            "note": _text(row.get("note")),
            "external_id": _text(row.get("external_id")),
            "matched_plan_id": None,
            "matched_entry_zone_date": None,
            "created_at": now,
            "updated_at": now,
        }
        record["id"] = _stable_id("trade", record["platform"], record["account_name"], record["trade_date"], code, side, quantity, price)
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
        record = {
            "platform": _text(row.get("platform")),
            "account_name": _text(row.get("account_name")),
            "snapshot_date": _text(row.get("snapshot_date")),
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
        record["id"] = _stable_id("position", record["platform"], record["account_name"], record["snapshot_date"], code)
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


def _fill_position_amounts(row: dict[str, Any]) -> dict[str, Any]:
    quantity = parse_number(row.get("quantity"))
    cost = parse_number(row.get("cost_price"))
    current = parse_number(row.get("current_price"))
    if row.get("market_value") is None and quantity is not None and current is not None:
        row["market_value"] = quantity * current
    if row.get("pnl") is None and quantity is not None and current is not None and cost is not None:
        row["pnl"] = (current - cost) * quantity
    if row.get("pnl_pct") is None and current is not None and cost:
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

