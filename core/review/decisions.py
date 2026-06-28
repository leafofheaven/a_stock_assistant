"""Manual review decision persistence and watchlist helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

import pandas as pd

from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.review.watchlist_scores import enrich_watchlist_latest_fields

ALLOWED_DECISIONS = {"watch", "pass", "exclude", "needs_data", "pending"}
ALLOWED_REVIEW_STATUS = {"active", "archived"}
ALLOWED_ACTION_TYPES = {"create", "update", "archive", "reactivate"}
REQUIRED_IMPORT_COLUMNS = ["ts_code", "name", "selection_date", "decision", "reason", "notes", "reviewer"]
REVIEW_COLUMNS = [
    "decision_id",
    "ts_code",
    "name",
    "selection_date",
    "review_date",
    "decision",
    "review_status",
    "reviewer",
    "reason",
    "notes",
    "data_quality_note",
    "source_report_path",
    "created_at",
    "updated_at",
]
HISTORY_COLUMNS = [
    "history_id",
    "ts_code",
    "name",
    "selection_date",
    "old_decision",
    "new_decision",
    "old_review_status",
    "new_review_status",
    "reason",
    "notes",
    "reviewer",
    "action_type",
    "created_at",
]


def ensure_review_decisions_table(store: DuckDBStore) -> None:
    """Create review_decisions table without disturbing existing data."""
    store.initialize()


def import_review_decisions(
    df: pd.DataFrame,
    *,
    store: DuckDBStore,
    source_report_path: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate and import review decisions into DuckDB."""
    ensure_review_decisions_table(store)
    errors = _validate_frame(df)
    if errors:
        return {
            "total_rows": int(len(df)),
            "imported_rows": 0,
            "updated_rows": 0,
            "inserted_rows": 0,
            "skipped_rows": int(len(df)),
            "error_rows": errors,
            "dry_run": dry_run,
        }
    valid_rows: list[dict[str, Any]] = []
    skipped = 0
    for index, row in df.iterrows():
        row_errors = _validate_row(row)
        if row_errors:
            errors.extend({"row": int(index) + 2, "error": error} for error in row_errors)
            skipped += 1
            continue
        valid_rows.append(_normalize_row(row, source_report_path, _latest_local_trade_date(store)))

    updated_rows = 0
    inserted_rows = 0
    if not dry_run and valid_rows:
        existing = _safe_read_reviews(store)
        valid_rows = _preserve_existing_text_fields(valid_rows, existing)
        existing_keys = set(zip(existing.get("ts_code", []), existing.get("selection_date", [])))
        incoming = pd.DataFrame(valid_rows, columns=REVIEW_COLUMNS)
        incoming_keys = set(zip(incoming["ts_code"], incoming["selection_date"]))
        updated_rows = len(incoming_keys.intersection(existing_keys))
        inserted_rows = len(incoming_keys - existing_keys)
        store.upsert_dataframe("review_decisions", incoming)

    return {
        "total_rows": int(len(df)),
        "imported_rows": len(valid_rows) if not dry_run else 0,
        "updated_rows": updated_rows,
        "inserted_rows": inserted_rows,
        "skipped_rows": skipped + len(_frame_level_errors(errors)),
        "error_rows": errors,
        "dry_run": dry_run,
    }


def read_review_decisions(store: DuckDBStore) -> pd.DataFrame:
    """Read review decisions, returning an empty frame when unavailable."""
    ensure_review_decisions_table(store)
    return _safe_read_reviews(store)


def build_watchlist_dataframe(store: DuckDBStore, active_only: bool = True) -> pd.DataFrame:
    """Return active watch decisions enriched with latest local market data."""
    decisions = read_review_decisions(store)
    if decisions.empty:
        return pd.DataFrame(columns=[*REVIEW_COLUMNS, "latest_trade_date", "latest_close", "total_score"])
    df = decisions.copy()
    if active_only and "review_status" in df.columns:
        df = df[df["review_status"].fillna("active") == "active"]
    if "decision" in df.columns:
        df = df[df["decision"] == "watch"]
    history = read_review_decision_history(store)
    result = enrich_watchlist_latest_fields(df, store=store)
    return _attach_history_summary(result, history)


def summarize_review_decisions(store: DuckDBStore) -> dict[str, Any]:
    """Return review decision counts for diagnostics and workflow reports."""
    decisions = read_review_decisions(store)
    counts = {decision: 0 for decision in ALLOWED_DECISIONS}
    if not decisions.empty and "decision" in decisions.columns:
        values = decisions["decision"].fillna("pending").astype(str).value_counts().to_dict()
        counts.update({key: int(values.get(key, 0)) for key in counts})
    active_watch = 0
    if not decisions.empty:
        active_watch = int(
            len(decisions[(decisions["decision"] == "watch") & (decisions["review_status"].fillna("active") == "active")])
        )
    return {
        "total_rows": int(len(decisions)),
        "active_watch_count": active_watch,
        "decision_counts": counts,
    }


def update_review_decision(
    *,
    store: DuckDBStore,
    ts_code: str,
    decision: str | None = None,
    reason: str = "",
    notes: str = "",
    reviewer: str = "",
    archive: bool = False,
    reactivate: bool = False,
    selection_date: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create or update one review decision and append a local history row."""
    ensure_review_decisions_table(store)
    code = _clean_text(ts_code).upper()
    if not code:
        return {"status": "failed", "message": "ts_code 不能为空。", "history_written": False}
    if archive and reactivate:
        return {"status": "failed", "message": "--archive 与 --reactivate 不能同时使用。", "history_written": False}
    requested_decision = _clean_text(decision)
    if requested_decision and requested_decision not in ALLOWED_DECISIONS:
        return {"status": "failed", "message": f"非法 decision: {requested_decision}", "history_written": False}

    existing = _find_existing_decision(store, code, selection_date)
    stock_info = _resolve_stock_info(store, code)
    if not existing and not stock_info:
        return {
            "status": "failed",
            "message": f"{code} 不存在于 review_decisions、stock_basic 或当前选股结果中。",
            "history_written": False,
        }

    now = datetime.now().isoformat(timespec="seconds")
    old_decision = _clean_text(existing.get("decision"))
    old_status = _clean_text(existing.get("review_status")) or None
    resolved_selection_date = (
        _clean_text(selection_date)
        or _clean_text(existing.get("selection_date"))
        or _latest_local_trade_date(store)
    )
    new_decision = requested_decision or old_decision or "pending"
    new_status = _clean_text(existing.get("review_status")) or "active"
    action_type = "create" if not existing else "update"
    if archive:
        new_status = "archived"
        action_type = "archive"
    elif reactivate:
        new_status = "active"
        action_type = "reactivate"

    row = {
        "decision_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{code}:{resolved_selection_date}")),
        "ts_code": code,
        "name": _clean_text(existing.get("name")) or _clean_text(stock_info.get("name")),
        "selection_date": resolved_selection_date,
        "review_date": now[:10],
        "decision": new_decision,
        "review_status": new_status,
        "reviewer": _clean_text(reviewer) or _clean_text(existing.get("reviewer")),
        "reason": _clean_text(reason) or _clean_text(existing.get("reason")),
        "notes": _clean_text(notes) or _clean_text(existing.get("notes")),
        "data_quality_note": _clean_text(existing.get("data_quality_note")),
        "source_report_path": _clean_text(existing.get("source_report_path")),
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    history_row = {
        "history_id": str(uuid.uuid4()),
        "ts_code": code,
        "name": row["name"],
        "selection_date": resolved_selection_date,
        "old_decision": old_decision or None,
        "new_decision": new_decision,
        "old_review_status": old_status,
        "new_review_status": new_status,
        "reason": _clean_text(reason) or row["reason"],
        "notes": _clean_text(notes) or row["notes"],
        "reviewer": _clean_text(reviewer) or row["reviewer"],
        "action_type": action_type,
        "created_at": now,
    }
    if not dry_run:
        store.upsert_dataframe("review_decisions", pd.DataFrame([row], columns=REVIEW_COLUMNS))
        store.write_dataframe("review_decision_history", pd.DataFrame([history_row], columns=HISTORY_COLUMNS))

    return {
        "status": "dry_run" if dry_run else "success",
        "ts_code": code,
        "name": row["name"],
        "selection_date": resolved_selection_date,
        "old_decision": old_decision or None,
        "new_decision": new_decision,
        "old_review_status": old_status,
        "new_review_status": new_status,
        "reason": history_row["reason"],
        "notes": history_row["notes"],
        "reviewer": history_row["reviewer"],
        "action_type": action_type,
        "history_written": not dry_run,
        "dry_run": dry_run,
        "message": "dry-run 未写入。" if dry_run else "复核状态已更新。",
    }


def read_review_decision_history(store: DuckDBStore, ts_code: str | None = None) -> pd.DataFrame:
    """Read review decision history, optionally filtered by ts_code."""
    ensure_review_decisions_table(store)
    history = _safe_read_history(store)
    if ts_code and not history.empty and "ts_code" in history.columns:
        history = history[history["ts_code"].astype(str) == _clean_text(ts_code).upper()]
    if not history.empty and "created_at" in history.columns:
        history = history.sort_values("created_at", ascending=False).reset_index(drop=True)
    return history


def summarize_review_history(store: DuckDBStore, ts_code: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Return compact review history diagnostics."""
    history = read_review_decision_history(store, ts_code=ts_code)
    limited = history.head(limit).reset_index(drop=True)
    return {
        "history_rows": int(len(history)),
        "records": limited.to_dict("records"),
    }


def load_review_csv(path: Path | str) -> pd.DataFrame:
    """Load a review decision CSV with a clear missing-file error."""
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"复核结果文件不存在: {resolved}")
    return pd.read_csv(resolved, dtype=str).fillna("")


def _validate_frame(df: pd.DataFrame) -> list[dict[str, Any]]:
    missing = [column for column in REQUIRED_IMPORT_COLUMNS if column not in df.columns]
    if missing:
        return [{"row": None, "error": f"缺少必要字段: {', '.join(missing)}"}]
    return []


def _validate_row(row: pd.Series) -> list[str]:
    errors: list[str] = []
    if not _clean_text(row.get("ts_code")):
        errors.append("ts_code 不能为空")
    decision = _clean_text(row.get("decision")) or "pending"
    if decision not in ALLOWED_DECISIONS:
        errors.append(f"非法 decision: {decision}")
    review_status = _clean_text(row.get("review_status")) or "active"
    if review_status not in ALLOWED_REVIEW_STATUS:
        errors.append(f"非法 review_status: {review_status}")
    return errors


def _normalize_row(row: pd.Series, source_report_path: str, default_selection_date: str) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    ts_code = _clean_text(row.get("ts_code"))
    selection_date = _clean_text(row.get("selection_date")) or default_selection_date
    decision = _clean_text(row.get("decision")) or "pending"
    return {
        "decision_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ts_code}:{selection_date}")),
        "ts_code": ts_code,
        "name": _clean_text(row.get("name")),
        "selection_date": selection_date,
        "review_date": _clean_text(row.get("review_date")) or now[:10],
        "decision": decision,
        "review_status": _clean_text(row.get("review_status")) or "active",
        "reviewer": _clean_text(row.get("reviewer")),
        "reason": _clean_text(row.get("reason")),
        "notes": _clean_text(row.get("notes")),
        "data_quality_note": _clean_text(row.get("data_quality_note")),
        "source_report_path": source_report_path,
        "created_at": now,
        "updated_at": now,
    }


def _safe_read_reviews(store: DuckDBStore) -> pd.DataFrame:
    try:
        return store.read_table("review_decisions")
    except DuckDBStoreError:
        return pd.DataFrame(columns=REVIEW_COLUMNS)


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _safe_read_history(store: DuckDBStore) -> pd.DataFrame:
    try:
        return store.read_table("review_decision_history")
    except DuckDBStoreError:
        return pd.DataFrame(columns=HISTORY_COLUMNS)


def _latest_local_trade_date(store: DuckDBStore) -> str:
    daily_price = _safe_read_table(store, "daily_price")
    if daily_price.empty or "trade_date" not in daily_price.columns:
        return datetime.now().strftime("%Y%m%d")
    values = daily_price["trade_date"].dropna().astype(str)
    return datetime.now().strftime("%Y%m%d") if values.empty else str(values.max())


def _enrich_watch(
    row: dict[str, Any],
    price: pd.DataFrame,
    scores: pd.DataFrame,
    stock_basic: pd.DataFrame,
    daily_basic: pd.DataFrame,
) -> dict[str, Any]:
    ts_code = str(row.get("ts_code", ""))
    selection_date = str(row.get("selection_date", ""))
    latest_price = _latest_row(price, ts_code, "trade_date")
    latest_score = _latest_row(scores, ts_code, "trade_date")
    latest_basic = _latest_row(daily_basic, ts_code, "trade_date")
    stock_info = _latest_row(stock_basic, ts_code, "ts_code")
    total_score = _optional_float(latest_score.get("total_score"))
    data_quality_note = _data_quality_note(
        row.get("data_quality_note"),
        total_score,
        stock_info,
        latest_basic,
    )
    return {
        **row,
        "industry": stock_info.get("industry") or latest_score.get("industry"),
        "market": stock_info.get("market"),
        "list_date": stock_info.get("list_date"),
        "pe": _optional_float(latest_basic.get("pe")),
        "pb": _optional_float(latest_basic.get("pb")),
        "latest_trade_date": latest_price.get("trade_date") or latest_score.get("trade_date") or selection_date,
        "latest_close": _optional_float(latest_price.get("close")),
        "total_score": total_score,
        "data_quality_note": data_quality_note,
    }


def _attach_history_summary(watchlist: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    if watchlist.empty:
        for column in ["latest_action_type", "latest_action_at", "history_count"]:
            watchlist[column] = pd.NA
        return watchlist
    if history.empty:
        watchlist["latest_action_type"] = pd.NA
        watchlist["latest_action_at"] = pd.NA
        watchlist["history_count"] = 0
        return watchlist
    rows: list[dict[str, Any]] = []
    grouped = {str(code): df for code, df in history.sort_values("created_at").groupby("ts_code")}
    for item in watchlist.to_dict("records"):
        current = grouped.get(str(item.get("ts_code")), pd.DataFrame())
        latest = current.iloc[-1].to_dict() if not current.empty else {}
        rows.append(
            {
                **item,
                "latest_action_type": latest.get("action_type"),
                "latest_action_at": latest.get("created_at"),
                "history_count": int(len(current)),
            }
        )
    return pd.DataFrame(rows)


def _find_existing_decision(store: DuckDBStore, ts_code: str, selection_date: str | None) -> dict[str, Any]:
    decisions = read_review_decisions(store)
    if decisions.empty or "ts_code" not in decisions.columns:
        return {}
    rows = decisions[decisions["ts_code"].astype(str) == ts_code].copy()
    if selection_date:
        rows = rows[rows["selection_date"].astype(str) == str(selection_date)]
    if rows.empty:
        return {}
    return rows.sort_values("selection_date").iloc[-1].to_dict()


def _resolve_stock_info(store: DuckDBStore, ts_code: str) -> dict[str, Any]:
    for table_name in ["stock_basic", "strategy_result"]:
        df = _safe_read_table(store, table_name)
        if df.empty or "ts_code" not in df.columns:
            continue
        rows = df[df["ts_code"].astype(str) == ts_code].copy()
        if rows.empty:
            continue
        if "trade_date" in rows.columns:
            rows = rows.sort_values("trade_date")
        return rows.iloc[-1].to_dict()
    return {}


def _preserve_existing_text_fields(rows: list[dict[str, Any]], existing: pd.DataFrame) -> list[dict[str, Any]]:
    """Preserve existing reason/notes/reviewer when incoming CSV cells are blank."""
    if existing.empty:
        return rows
    indexed = {
        (str(item.get("ts_code")), str(item.get("selection_date"))): item
        for item in existing.to_dict("records")
    }
    for row in rows:
        current = indexed.get((row["ts_code"], row["selection_date"]), {})
        for column in ["reason", "notes", "reviewer"]:
            if not row.get(column) and _clean_text(current.get(column)):
                row[column] = _clean_text(current.get(column))
        if current.get("created_at"):
            row["created_at"] = current["created_at"]
    return rows


def _data_quality_note(
    value: Any,
    total_score: float | None,
    stock_info: dict[str, Any] | None = None,
    latest_basic: dict[str, Any] | None = None,
) -> str:
    note = _clean_text(value)
    notes = [note] if note else []
    if total_score is None:
        notes.append("当前无可用综合评分")
    stock_info = stock_info or {}
    latest_basic = latest_basic or {}
    pe_missing = _optional_float(latest_basic.get("pe")) is None
    pb_missing = _optional_float(latest_basic.get("pb")) is None
    notes = _filter_existing_quality_notes(notes, valuation_missing=pe_missing or pb_missing, score_missing=total_score is None)
    if not _clean_text(stock_info.get("industry")):
        notes.append("industry 缺失")
    if not _clean_text(stock_info.get("market")):
        notes.append("market 缺失")
    if not _clean_text(stock_info.get("list_date")):
        notes.append("list_date 缺失")
    if pe_missing:
        notes.append("pe 缺失")
    if pb_missing:
        notes.append("pb 缺失")
    return "；".join(dict.fromkeys(notes))


def _filter_existing_quality_notes(
    notes: list[str],
    *,
    valuation_missing: bool,
    score_missing: bool,
) -> list[str]:
    """Drop stale valuation/fundamental missing prompts that no longer apply."""
    filtered: list[str] = []
    valuation_phrases = [
        "pe 全部缺失",
        "pb 全部缺失",
        "部分股票 pe 缺失",
        "部分股票 pb 缺失",
        "pe/pb 可能为空",
        "pe/pb 缺失",
        "pe 缺失",
        "pb 缺失",
        "估值相关复核信息不完整",
    ]
    score_phrases = [
        "fundamental_score 可能为空",
        "fundamental_score 为空原因",
        "基本面分项可能偏低或为空",
        "pe_score 与 fundamental_score 可能为空",
    ]
    for note in notes:
        text = _clean_text(note)
        if not text:
            continue
        if not valuation_missing and any(phrase in text for phrase in valuation_phrases):
            continue
        if not score_missing and any(phrase in text for phrase in score_phrases):
            continue
        filtered.append(text)
    return filtered


def _clean_text(value: Any) -> str:
    """Normalize CSV text cells, treating NaN-like values as empty."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>", "null"} else text


def _latest_row(df: pd.DataFrame, ts_code: str, date_col: str) -> dict[str, Any]:
    if df.empty or "ts_code" not in df.columns or date_col not in df.columns:
        return {}
    rows = df[df["ts_code"].astype(str) == ts_code].copy()
    if rows.empty:
        return {}
    return rows.sort_values(date_col).iloc[-1].to_dict()


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _frame_level_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [error for error in errors if error.get("row") is None]
