"""Manual review decision persistence and watchlist helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

import pandas as pd

from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError

ALLOWED_DECISIONS = {"watch", "pass", "exclude", "needs_data", "pending"}
ALLOWED_REVIEW_STATUS = {"active", "archived"}
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
    price = _safe_read_table(store, "daily_price")
    scores = _safe_read_table(store, "factor_scores")
    strategy = _safe_read_table(store, "strategy_result")
    score_source = scores if not scores.empty else strategy
    enriched = [_enrich_watch(row, price, score_source) for row in df.to_dict("records")]
    return pd.DataFrame(enriched)


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
    if not str(row.get("ts_code", "")).strip():
        errors.append("ts_code 不能为空")
    decision = str(row.get("decision", "") or "pending").strip()
    if decision not in ALLOWED_DECISIONS:
        errors.append(f"非法 decision: {decision}")
    review_status = str(row.get("review_status", "") or "active").strip()
    if review_status not in ALLOWED_REVIEW_STATUS:
        errors.append(f"非法 review_status: {review_status}")
    return errors


def _normalize_row(row: pd.Series, source_report_path: str, default_selection_date: str) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    ts_code = str(row.get("ts_code", "")).strip()
    selection_date = str(row.get("selection_date", "")).strip() or default_selection_date
    decision = str(row.get("decision", "") or "pending").strip()
    return {
        "decision_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ts_code}:{selection_date}")),
        "ts_code": ts_code,
        "name": str(row.get("name", "")).strip(),
        "selection_date": selection_date,
        "review_date": str(row.get("review_date", "") or now[:10]).strip(),
        "decision": decision,
        "review_status": str(row.get("review_status", "") or "active").strip(),
        "reviewer": str(row.get("reviewer", "")).strip(),
        "reason": str(row.get("reason", "")).strip(),
        "notes": str(row.get("notes", "")).strip(),
        "data_quality_note": str(row.get("data_quality_note", "")).strip(),
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


def _latest_local_trade_date(store: DuckDBStore) -> str:
    daily_price = _safe_read_table(store, "daily_price")
    if daily_price.empty or "trade_date" not in daily_price.columns:
        return datetime.now().strftime("%Y%m%d")
    values = daily_price["trade_date"].dropna().astype(str)
    return datetime.now().strftime("%Y%m%d") if values.empty else str(values.max())


def _enrich_watch(row: dict[str, Any], price: pd.DataFrame, scores: pd.DataFrame) -> dict[str, Any]:
    ts_code = str(row.get("ts_code", ""))
    selection_date = str(row.get("selection_date", ""))
    latest_price = _latest_row(price, ts_code, "trade_date")
    latest_score = _latest_row(scores, ts_code, "trade_date")
    return {
        **row,
        "latest_trade_date": latest_price.get("trade_date") or latest_score.get("trade_date") or selection_date,
        "latest_close": _optional_float(latest_price.get("close")),
        "total_score": _optional_float(latest_score.get("total_score")),
    }


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
