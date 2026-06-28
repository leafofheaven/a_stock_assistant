"""Watchlist tracking snapshot helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

import pandas as pd

from app.config import Settings
from core.review.decisions import build_watchlist_dataframe
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError

SNAPSHOT_COLUMNS = [
    "snapshot_id",
    "ts_code",
    "name",
    "snapshot_date",
    "selection_date",
    "review_date",
    "decision",
    "industry",
    "market",
    "list_date",
    "latest_trade_date",
    "latest_close",
    "pe",
    "pb",
    "total_score",
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "volatility_score",
    "fundamental_score",
    "return_20d",
    "avg_amount_20d",
    "avg_turnover_20d",
    "volatility_20d",
    "score_missing_reason",
    "data_quality_note",
    "created_at",
]


def create_watchlist_snapshots(
    *,
    settings: Settings,
    store: DuckDBStore,
    snapshot_date: str | None = None,
) -> dict[str, Any]:
    """Create or update watchlist snapshots from local DuckDB data only."""
    store.initialize()
    _ensure_snapshot_columns(store)
    watchlist = build_watchlist_dataframe(store, active_only=True)
    resolved_snapshot_date = snapshot_date or _latest_trade_date(store)
    if watchlist.empty:
        return {
            "status": "skipped",
            "data_provider": settings.data_provider,
            "duckdb_path": str(store.db_path),
            "active_watch_count": 0,
            "snapshot_count": 0,
            "missing_price_count": 0,
            "missing_score_count": 0,
            "snapshot_date": resolved_snapshot_date,
            "message": "暂无 active watch 股票，未生成 snapshot。",
            "next_steps": ["python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv"],
        }

    rows = [
        _snapshot_row(item, resolved_snapshot_date)
        for item in watchlist.to_dict("records")
    ]
    snapshot_df = pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)
    written = store.upsert_dataframe("watchlist_snapshots", snapshot_df)
    missing_price = int(snapshot_df["latest_close"].isna().sum()) if not snapshot_df.empty else 0
    missing_score = int(snapshot_df["total_score"].isna().sum()) if not snapshot_df.empty else 0
    return {
        "status": "success",
        "data_provider": settings.data_provider,
        "duckdb_path": str(store.db_path),
        "active_watch_count": int(len(watchlist)),
        "snapshot_count": int(len(snapshot_df)),
        "written_rows": int(written),
        "missing_price_count": missing_price,
        "missing_score_count": missing_score,
        "snapshot_date": resolved_snapshot_date,
        "snapshots": snapshot_df,
        "next_steps": ["python -m core.jobs.export_watchlist_tracking_report", "streamlit run web/streamlit_app.py"],
    }


def read_watchlist_snapshots(store: DuckDBStore) -> pd.DataFrame:
    """Read watchlist snapshots, returning an empty frame when unavailable."""
    store.initialize()
    try:
        return store.read_table("watchlist_snapshots")
    except DuckDBStoreError:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)


def latest_tracking_snapshot(store: DuckDBStore) -> pd.DataFrame:
    """Return rows for the latest snapshot date."""
    snapshots = read_watchlist_snapshots(store)
    if snapshots.empty or "snapshot_date" not in snapshots.columns:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    latest = str(snapshots["snapshot_date"].dropna().astype(str).max())
    return snapshots[snapshots["snapshot_date"].astype(str) == latest].reset_index(drop=True)


def _latest_trade_date(store: DuckDBStore) -> str:
    daily_price = _safe_read_table(store, "daily_price")
    if not daily_price.empty and "trade_date" in daily_price.columns:
        values = daily_price["trade_date"].dropna().astype(str)
        if not values.empty:
            return str(values.max())
    return datetime.now().strftime("%Y%m%d")


def _snapshot_row(
    item: dict[str, Any],
    snapshot_date: str,
) -> dict[str, Any]:
    ts_code = str(item.get("ts_code", ""))
    latest_close = _optional_float(item.get("latest_close"))
    total_score = _optional_float(item.get("total_score"))
    note = _quality_note(item.get("data_quality_note"), latest_close, total_score)
    return {
        "snapshot_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ts_code}:{snapshot_date}")),
        "ts_code": ts_code,
        "name": item.get("name"),
        "snapshot_date": snapshot_date,
        "selection_date": item.get("selection_date"),
        "review_date": item.get("review_date"),
        "decision": item.get("decision"),
        "industry": item.get("industry"),
        "market": item.get("market"),
        "list_date": item.get("list_date"),
        "latest_trade_date": item.get("latest_trade_date"),
        "latest_close": latest_close,
        "pe": _optional_float(item.get("pe")),
        "pb": _optional_float(item.get("pb")),
        "total_score": total_score,
        "trend_score": _optional_float(item.get("trend_score")),
        "momentum_score": _optional_float(item.get("momentum_score")),
        "liquidity_score": _optional_float(item.get("liquidity_score")),
        "volatility_score": _optional_float(item.get("volatility_score")),
        "fundamental_score": _optional_float(item.get("fundamental_score")),
        "return_20d": _optional_float(item.get("return_20d")),
        "avg_amount_20d": _optional_float(item.get("avg_amount_20d")),
        "avg_turnover_20d": _optional_float(item.get("avg_turnover_20d")),
        "volatility_20d": _optional_float(item.get("volatility_20d")),
        "score_missing_reason": item.get("score_missing_reason"),
        "data_quality_note": note,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _latest_row(df: pd.DataFrame, ts_code: str, date_col: str, cutoff_date: str) -> dict[str, Any]:
    if df.empty or "ts_code" not in df.columns or date_col not in df.columns:
        return {}
    rows = df[(df["ts_code"].astype(str) == ts_code) & (df[date_col].astype(str) <= cutoff_date)].copy()
    if rows.empty:
        return {}
    return rows.sort_values(date_col).iloc[-1].to_dict()


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _quality_note(existing: Any, latest_close: float | None, total_score: float | None) -> str:
    notes = [str(existing).strip()] if existing and not pd.isna(existing) else []
    if latest_close is None:
        notes.append("缺少当前行情")
    if total_score is None:
        notes.append("当前无可用综合评分")
    return "；".join(dict.fromkeys(note for note in notes if note))


def _ensure_snapshot_columns(store: DuckDBStore) -> None:
    """Add Task 29 snapshot columns to older local DuckDB files."""
    column_defs = {
        "industry": "VARCHAR",
        "market": "VARCHAR",
        "list_date": "VARCHAR",
        "pe": "DOUBLE",
        "pb": "DOUBLE",
        "score_missing_reason": "VARCHAR",
    }
    try:
        with store.connect() as connection:
            for column, data_type in column_defs.items():
                connection.execute(f"ALTER TABLE watchlist_snapshots ADD COLUMN IF NOT EXISTS {column} {data_type}")
    except Exception:
        return


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
