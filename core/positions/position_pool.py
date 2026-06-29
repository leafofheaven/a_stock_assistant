"""Local position pool for manual holding records."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

import pandas as pd

from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.technical.elder import build_elder_review

ALLOWED_POSITION_STATUS = {"active", "reduced", "exited"}
ALLOWED_POSITION_SOURCES = {"selection", "watchlist", "elder_review", "manual"}
POSITION_COLUMNS = [
    "position_id",
    "ts_code",
    "name",
    "entry_date",
    "entry_price",
    "quantity",
    "entry_reason",
    "source",
    "entry_total_score",
    "entry_elder_score",
    "initial_stop",
    "plan",
    "status",
    "created_at",
    "updated_at",
]
POSITION_IMPORT_COLUMNS = [
    "ts_code",
    "name",
    "entry_date",
    "entry_price",
    "quantity",
    "entry_reason",
    "source",
    "entry_total_score",
    "entry_elder_score",
    "initial_stop",
    "plan",
]


def ensure_positions_table(store: DuckDBStore) -> None:
    """Create the positions table without disturbing existing data."""
    store.initialize()


def create_position(
    *,
    store: DuckDBStore,
    ts_code: str,
    name: str = "",
    entry_date: str = "",
    entry_price: float | None = None,
    quantity: float | None = None,
    entry_reason: str = "",
    source: str = "manual",
    entry_total_score: float | None = None,
    entry_elder_score: float | None = None,
    initial_stop: float | None = None,
    plan: str = "",
    status: str = "active",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create one manual position record, skipping duplicate active holdings."""
    ensure_positions_table(store)
    code = _clean_text(ts_code).upper()
    if not code:
        return {"status": "failed", "message": "ts_code 不能为空。", "created": False}
    if status not in ALLOWED_POSITION_STATUS:
        return {"status": "failed", "message": f"非法 status: {status}", "created": False}
    resolved_source = _clean_text(source) or "manual"
    if resolved_source not in ALLOWED_POSITION_SOURCES:
        resolved_source = "manual"
    existing_active = find_active_position(store, code)
    if existing_active:
        return {
            "status": "exists",
            "message": f"{code} 已存在 active position。",
            "created": False,
            "position_id": existing_active.get("position_id"),
        }

    now = datetime.now().isoformat(timespec="seconds")
    resolved_entry_date = _normalize_date(entry_date) or now[:10].replace("-", "")
    resolved_name = _clean_text(name) or _resolve_stock_name(store, code)
    row = {
        "position_id": str(uuid.uuid4()),
        "ts_code": code,
        "name": resolved_name,
        "entry_date": resolved_entry_date,
        "entry_price": _to_float(entry_price),
        "quantity": _to_float(quantity),
        "entry_reason": _clean_text(entry_reason),
        "source": resolved_source,
        "entry_total_score": _to_float(entry_total_score),
        "entry_elder_score": _to_float(entry_elder_score),
        "initial_stop": _to_float(initial_stop),
        "plan": _clean_text(plan),
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    if not dry_run:
        store.upsert_dataframe("positions", pd.DataFrame([row], columns=POSITION_COLUMNS))
    return {
        "status": "dry_run" if dry_run else "success",
        "message": "dry-run 未写入。" if dry_run else "持仓记录已创建。",
        "created": not dry_run,
        "position_id": row["position_id"],
        "row": row,
        "dry_run": dry_run,
    }


def import_positions(
    df: pd.DataFrame,
    *,
    store: DuckDBStore,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import manual position records from a DataFrame."""
    ensure_positions_table(store)
    errors = _validate_import_frame(df)
    if errors:
        return {
            "total_rows": int(len(df)),
            "created_rows": 0,
            "existing_rows": 0,
            "skipped_rows": int(len(df)),
            "error_rows": errors,
            "dry_run": dry_run,
        }
    created = 0
    existing = 0
    skipped = 0
    row_errors: list[dict[str, Any]] = []
    for index, row in df.iterrows():
        if not _clean_text(row.get("ts_code")):
            row_errors.append({"row": int(index) + 2, "error": "ts_code 不能为空。"})
            skipped += 1
            continue
        result = create_position(
            store=store,
            ts_code=str(row.get("ts_code")),
            name=_clean_text(row.get("name")),
            entry_date=_clean_text(row.get("entry_date")),
            entry_price=_to_float(row.get("entry_price")),
            quantity=_to_float(row.get("quantity")),
            entry_reason=_clean_text(row.get("entry_reason")),
            source=_clean_text(row.get("source")) or "manual",
            entry_total_score=_to_float(row.get("entry_total_score")),
            entry_elder_score=_to_float(row.get("entry_elder_score")),
            initial_stop=_to_float(row.get("initial_stop")),
            plan=_clean_text(row.get("plan")),
            dry_run=dry_run,
        )
        if result["status"] in {"success", "dry_run"}:
            created += 1
        elif result["status"] == "exists":
            existing += 1
        else:
            row_errors.append({"row": int(index) + 2, "error": result["message"]})
            skipped += 1
    return {
        "total_rows": int(len(df)),
        "created_rows": created,
        "existing_rows": existing,
        "skipped_rows": skipped,
        "error_rows": row_errors,
        "dry_run": dry_run,
    }


def update_position_status(
    *,
    store: DuckDBStore,
    ts_code: str,
    status: str,
    position_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update a position status to active/reduced/exited."""
    ensure_positions_table(store)
    if status not in ALLOWED_POSITION_STATUS:
        return {"status": "failed", "message": f"非法 status: {status}", "updated": False}
    positions = read_positions(store)
    if positions.empty:
        return {"status": "not_found", "message": "暂无持仓记录。", "updated": False}
    target = positions.copy()
    if position_id:
        target = target[target["position_id"].astype(str) == str(position_id)]
    else:
        target = target[target["ts_code"].astype(str) == _clean_text(ts_code).upper()]
        if "status" in target.columns:
            active = target[target["status"].fillna("active") == "active"]
            if not active.empty:
                target = active
    if target.empty:
        return {"status": "not_found", "message": f"未找到持仓记录: {ts_code}", "updated": False}
    row = target.sort_values("created_at").iloc[-1].to_dict()
    old_status = _clean_text(row.get("status")) or "active"
    row["status"] = status
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if not dry_run:
        store.upsert_dataframe("positions", pd.DataFrame([row], columns=POSITION_COLUMNS))
    return {
        "status": "dry_run" if dry_run else "success",
        "message": "dry-run 未写入。" if dry_run else "持仓状态已更新。",
        "updated": not dry_run,
        "position_id": row["position_id"],
        "ts_code": row["ts_code"],
        "old_status": old_status,
        "new_status": status,
        "dry_run": dry_run,
    }


def read_positions(store: DuckDBStore, active_only: bool = False) -> pd.DataFrame:
    """Read local positions, returning an empty frame when the table is absent."""
    ensure_positions_table(store)
    try:
        positions = store.read_table("positions")
    except DuckDBStoreError:
        positions = pd.DataFrame(columns=POSITION_COLUMNS)
    if active_only and not positions.empty and "status" in positions.columns:
        positions = positions[positions["status"].fillna("active") == "active"]
    return positions.reset_index(drop=True)


def build_positions_dataframe(store: DuckDBStore, active_only: bool = False) -> pd.DataFrame:
    """Return positions enriched with latest close, PnL percentage and holding days."""
    positions = read_positions(store, active_only=active_only)
    if positions.empty:
        return pd.DataFrame(columns=position_tracking_columns())
    return enrich_positions_with_tracking(positions, store=store).reset_index(drop=True)


def track_active_positions(store: DuckDBStore) -> pd.DataFrame:
    """Track active positions with local price and Elder review state."""
    positions = read_positions(store, active_only=True)
    if positions.empty:
        return pd.DataFrame(columns=position_tracking_columns())
    return enrich_positions_with_tracking(positions, store=store).reset_index(drop=True)


def enrich_positions_with_tracking(positions: pd.DataFrame, *, store: DuckDBStore) -> pd.DataFrame:
    """Add daily tracking fields to a positions frame without mutating storage."""
    if positions.empty:
        return pd.DataFrame(columns=position_tracking_columns())
    try:
        price = store.read_table("daily_price")
    except DuckDBStoreError:
        price = pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for _, row in positions.iterrows():
        record = row.to_dict()
        tracked = _track_one_position(record, price)
        rows.append({**record, **tracked})
    result = pd.DataFrame(rows)
    for column in position_tracking_columns():
        if column not in result.columns:
            result[column] = pd.NA
    return result


def position_tracking_columns() -> list[str]:
    """Return the full set of position and tracking columns."""
    return [
        *POSITION_COLUMNS,
        "latest_trade_date",
        "latest_close",
        "pnl_pct",
        "holding_days",
        "max_gain_pct",
        "max_drawdown_pct",
        "close_to_entry_pct",
        "latest_elder_score",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
        "technical_state",
        "position_hint",
        "position_reason",
        "data_quality_note",
    ]


def find_active_position(store: DuckDBStore, ts_code: str) -> dict[str, Any]:
    """Return an active position for ts_code when it exists."""
    positions = read_positions(store, active_only=True)
    if positions.empty or "ts_code" not in positions.columns:
        return {}
    rows = positions[positions["ts_code"].astype(str) == _clean_text(ts_code).upper()]
    if rows.empty:
        return {}
    return rows.sort_values("created_at").iloc[-1].to_dict()


def load_positions_csv(path: Path | str) -> pd.DataFrame:
    """Load a positions CSV with clear missing-file behavior."""
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"持仓导入文件不存在: {resolved}")
    return pd.read_csv(resolved, dtype=str).fillna("")


def _validate_import_frame(df: pd.DataFrame) -> list[dict[str, Any]]:
    missing = [column for column in ["ts_code", "entry_date", "entry_price"] if column not in df.columns]
    if missing:
        return [{"row": 0, "error": f"缺少必要列: {', '.join(missing)}"}]
    return []


def _latest_price_frame(store: DuckDBStore) -> pd.DataFrame:
    try:
        price = store.read_table("daily_price")
    except DuckDBStoreError:
        return pd.DataFrame(columns=["ts_code", "latest_trade_date", "latest_close"])
    if price.empty or not {"ts_code", "trade_date", "close"}.issubset(price.columns):
        return pd.DataFrame(columns=["ts_code", "latest_trade_date", "latest_close"])
    latest = price.sort_values("trade_date").groupby("ts_code", as_index=False).tail(1)
    return latest[["ts_code", "trade_date", "close"]].rename(columns={"trade_date": "latest_trade_date", "close": "latest_close"})


def _track_one_position(position: dict[str, Any], price_df: pd.DataFrame) -> dict[str, Any]:
    code = _clean_text(position.get("ts_code")).upper()
    entry_date = _normalize_date(position.get("entry_date"))
    entry_price = _to_float(position.get("entry_price"))
    empty_result = _empty_tracking_result("数据不足", "持仓买入日期之后行情数据不足。")
    if not code or not entry_date or price_df.empty or not {"ts_code", "trade_date", "close"}.issubset(price_df.columns):
        return empty_result
    history = price_df[price_df["ts_code"].astype(str) == code].copy()
    if history.empty:
        return empty_result
    history["trade_date"] = history["trade_date"].astype(str)
    history = history.sort_values("trade_date")
    held = history[history["trade_date"] >= entry_date].copy()
    if held.empty:
        return empty_result
    close = pd.to_numeric(held["close"], errors="coerce")
    if close.dropna().empty:
        return empty_result
    latest = held.iloc[-1]
    latest_close = _to_float(latest.get("close"))
    latest_trade_date = _clean_text(latest.get("trade_date"))
    if latest_close is None or entry_price is None or entry_price == 0:
        result = _empty_tracking_result("数据不足", "最新收盘价或买入价数据不足。")
        result.update({"latest_trade_date": latest_trade_date or None, "latest_close": latest_close})
        return result
    pnl_pct = latest_close / entry_price - 1
    max_gain_pct = float(close.max() / entry_price - 1)
    max_drawdown_pct = float(close.min() / entry_price - 1)
    elder = _latest_elder_for_position(position, history)
    technical_state = _technical_state(elder)
    hint, reason = _position_hint(
        pnl_pct=pnl_pct,
        max_drawdown_pct=max_drawdown_pct,
        latest_elder_score=_to_float(elder.get("elder_score")),
        technical_state=technical_state,
    )
    return {
        "latest_trade_date": latest_trade_date,
        "latest_close": latest_close,
        "pnl_pct": pnl_pct,
        "holding_days": _calculate_holding_days(pd.Series({**position, "latest_trade_date": latest_trade_date})),
        "max_gain_pct": max_gain_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "close_to_entry_pct": pnl_pct,
        "latest_elder_score": _to_float(elder.get("elder_score")),
        "weekly_trend": elder.get("weekly_trend") or "数据不足",
        "daily_pullback": elder.get("daily_pullback") or "数据不足",
        "force_signal": elder.get("force_signal") or "数据不足",
        "elder_ray_signal": elder.get("elder_ray_signal") or "数据不足",
        "technical_state": technical_state,
        "position_hint": hint,
        "position_reason": reason,
        "data_quality_note": "数据可用于持仓每日跟踪",
    }


def _latest_elder_for_position(position: dict[str, Any], history: pd.DataFrame) -> dict[str, Any]:
    candidate = pd.DataFrame(
        [
            {
                "rank": 1,
                "ts_code": position.get("ts_code"),
                "name": position.get("name"),
                "trade_date": history["trade_date"].astype(str).max() if "trade_date" in history.columns else "",
                "total_score": position.get("entry_total_score"),
            }
        ]
    )
    review = build_elder_review(candidate, history)
    if review.empty:
        return {}
    return review.iloc[-1].to_dict()


def _technical_state(elder: dict[str, Any]) -> str:
    action_hint = _clean_text(elder.get("action_hint"))
    if not action_hint:
        return "数据不足"
    if action_hint == "趋势确认，进入人工复核":
        return "技术节奏正常"
    if action_hint == "趋势尚可，等待回调":
        return "节奏观察"
    if action_hint == "短线过热，不追":
        return "短线过热"
    if action_hint == "趋势偏弱，暂缓":
        return "技术偏弱"
    return action_hint


def _position_hint(
    *,
    pnl_pct: float | None,
    max_drawdown_pct: float | None,
    latest_elder_score: float | None,
    technical_state: str,
) -> tuple[str, str]:
    if pnl_pct is None or max_drawdown_pct is None:
        return "数据不足", "最新行情或买入价不足，暂不能生成持仓跟踪提示。"
    if max_drawdown_pct <= -0.10 or technical_state in {"技术偏弱", "短线过热"}:
        return "波动加大，需人工复核", "持仓以来回撤或技术状态波动加大，需要人工复核，不构成交易指令。"
    if pnl_pct < 0 or max_drawdown_pct <= -0.05 or (latest_elder_score is not None and latest_elder_score < 45):
        return "持有观察", "当前持仓表现或技术节奏需要继续观察，不构成交易指令。"
    return "持仓正常", "当前本地行情和技术节奏未触发异常提示。"


def _empty_tracking_result(hint: str, reason: str) -> dict[str, Any]:
    return {
        "latest_trade_date": None,
        "latest_close": None,
        "pnl_pct": None,
        "holding_days": None,
        "max_gain_pct": None,
        "max_drawdown_pct": None,
        "close_to_entry_pct": None,
        "latest_elder_score": None,
        "weekly_trend": "数据不足",
        "daily_pullback": "数据不足",
        "force_signal": "数据不足",
        "elder_ray_signal": "数据不足",
        "technical_state": "数据不足",
        "position_hint": hint,
        "position_reason": reason,
        "data_quality_note": reason,
    }


def _calculate_pnl_pct(row: pd.Series) -> float | None:
    entry = _to_float(row.get("entry_price"))
    latest = _to_float(row.get("latest_close"))
    if entry is None or latest is None or entry == 0:
        return None
    return float(latest / entry - 1)


def _calculate_holding_days(row: pd.Series) -> int | None:
    entry = _parse_date(row.get("entry_date"))
    latest = _parse_date(row.get("latest_trade_date")) or datetime.now()
    if entry is None:
        return None
    return max((latest.date() - entry.date()).days, 0)


def _position_quality_note(row: pd.Series) -> str:
    notes = []
    if _to_float(row.get("latest_close")) is None:
        notes.append("最新收盘价数据不足")
    if _to_float(row.get("entry_price")) is None:
        notes.append("买入价缺失")
    if _parse_date(row.get("entry_date")) is None:
        notes.append("买入日期格式需复核")
    return "；".join(notes) if notes else "数据可用于基础持仓展示"


def _resolve_stock_name(store: DuckDBStore, ts_code: str) -> str:
    try:
        basic = store.read_table("stock_basic")
    except DuckDBStoreError:
        return ""
    if basic.empty or not {"ts_code", "name"}.issubset(basic.columns):
        return ""
    rows = basic[basic["ts_code"].astype(str) == ts_code]
    if rows.empty:
        return ""
    return _clean_text(rows.iloc[-1].get("name"))


def _parse_date(value: Any) -> datetime | None:
    text = _normalize_date(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None


def _normalize_date(value: Any) -> str:
    text = _clean_text(value).replace("-", "").replace("/", "")
    return text if len(text) == 8 and text.isdigit() else ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def _to_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(converted) else converted
