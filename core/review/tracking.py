"""Watchlist tracking snapshot helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

import pandas as pd

from app.config import Settings
from core.review.decisions import REVIEW_COLUMNS, build_watchlist_dataframe, read_review_decisions
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.strategy.selector import select_top_stocks
from core.technical.elder import build_elder_review

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

WATCH_STATUS_LABELS = {
    "new_candidate": "新入选",
    "active_watch": "正常观察",
    "strong_watch": "重点观察",
    "wait_pullback": "等待回调",
    "near_buy_zone": "接近买入区间",
    "overheated": "短线过热",
    "weakening": "走势转弱",
    "invalidated": "逻辑失效",
    "bought": "已买入",
    "removed": "已移出",
}

DAILY_SNAPSHOT_COLUMNS = [
    "snapshot_id",
    "ts_code",
    "name",
    "trade_date",
    "current_close",
    "pe",
    "pb",
    "today_rank",
    "previous_rank",
    "rank_change",
    "total_score",
    "total_score_change",
    "top_n_flag",
    "new_candidate_flag",
    "first_selected_date",
    "last_selected_date",
    "selected_count_5d",
    "selected_count_10d",
    "consecutive_selected_days",
    "best_rank",
    "watch_status",
    "watch_status_label",
    "watch_days",
    "entry_reason",
    "watch_reason",
    "daily_note",
    "elder_score",
    "action_hint",
    "elder_reason",
    "weekly_trend",
    "daily_pullback",
    "force_signal",
    "elder_ray_signal",
    "created_at",
]

EVENT_COLUMNS = [
    "event_id",
    "ts_code",
    "event_date",
    "event_type",
    "old_status",
    "new_status",
    "old_rank",
    "new_rank",
    "old_score",
    "new_score",
    "reason",
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


def refresh_watchlist_from_selection(
    *,
    settings: Settings,
    store: DuckDBStore,
    trade_date: str | None = None,
    top_n: int | None = None,
) -> dict[str, Any]:
    """Refresh watchlist membership and daily candidate tracking from local selection data.

    The function does not change total_score, factor weights, or candidate order. It
    reads the current local selection result, marks new Top-N candidates as watch
    records when needed, and writes a daily tracking snapshot for every active
    watchlist stock. Stocks that drop out of today's Top-N remain in the watchlist.
    """
    store.initialize()
    _ensure_daily_tracking_tables(store)
    resolved_top_n = int(top_n or getattr(settings, "default_top_n", 30))
    selection_history = _load_selection_history(settings=settings, store=store, top_n=resolved_top_n)
    resolved_trade_date = trade_date or _latest_selection_date(selection_history) or _latest_trade_date(store)
    current_selection = _current_selection(selection_history, resolved_trade_date, resolved_top_n)
    existing_decisions = read_review_decisions(store)
    active_codes = _active_watch_codes(existing_decisions)
    new_rows = _new_watch_decision_rows(
        current_selection=current_selection,
        existing_decisions=existing_decisions,
        active_codes=active_codes,
        selection_date=resolved_trade_date,
    )
    if new_rows:
        store.upsert_dataframe("review_decisions", pd.DataFrame(new_rows, columns=REVIEW_COLUMNS))
        existing_decisions = read_review_decisions(store)
        active_codes = _active_watch_codes(existing_decisions)

    snapshots = _build_daily_snapshots(
        store=store,
        selection_history=selection_history,
        current_selection=current_selection,
        existing_decisions=existing_decisions,
        active_codes=active_codes,
        trade_date=resolved_trade_date,
        top_n=resolved_top_n,
        new_codes={row["ts_code"] for row in new_rows},
    )
    written = 0
    if not snapshots.empty:
        written = store.upsert_dataframe("watchlist_daily_snapshots", snapshots)
    events = _build_watchlist_events(store=store, snapshots=snapshots, trade_date=resolved_trade_date)
    if not events.empty:
        store.upsert_dataframe("watchlist_events", events)
    status_counts = _status_counts(snapshots)
    return {
        "status": "success" if not snapshots.empty else "skipped",
        "data_provider": settings.data_provider,
        "duckdb_path": str(store.db_path),
        "trade_date": resolved_trade_date,
        "top_n": resolved_top_n,
        "candidate_count": int(len(current_selection)),
        "new_candidate_count": int(len(new_rows)),
        "active_watch_count": int(len(active_codes)),
        "snapshot_count": int(len(snapshots)),
        "written_rows": int(written),
        "event_count": int(len(events)),
        "status_counts": status_counts,
        "snapshots": snapshots,
        "events": events,
        "next_steps": ["python -m core.jobs.track_watchlist", "python -m core.jobs.export_watchlist_tracking"],
    }


def read_watchlist_snapshots(store: DuckDBStore) -> pd.DataFrame:
    """Read watchlist snapshots, returning an empty frame when unavailable."""
    store.initialize()
    try:
        return store.read_table("watchlist_snapshots")
    except DuckDBStoreError:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)


def read_watchlist_daily_snapshots(store: DuckDBStore) -> pd.DataFrame:
    """Read Task 48 daily watchlist snapshots."""
    store.initialize()
    try:
        return store.read_table("watchlist_daily_snapshots")
    except DuckDBStoreError:
        return pd.DataFrame(columns=DAILY_SNAPSHOT_COLUMNS)


def read_watchlist_events(store: DuckDBStore) -> pd.DataFrame:
    """Read Task 48 watchlist events."""
    store.initialize()
    try:
        return store.read_table("watchlist_events")
    except DuckDBStoreError:
        return pd.DataFrame(columns=EVENT_COLUMNS)


def latest_tracking_snapshot(store: DuckDBStore) -> pd.DataFrame:
    """Return rows for the latest snapshot date."""
    daily = read_watchlist_daily_snapshots(store)
    if not daily.empty and "trade_date" in daily.columns:
        latest_daily = str(daily["trade_date"].dropna().astype(str).max())
        result = daily[daily["trade_date"].astype(str) == latest_daily].reset_index(drop=True)
        if "snapshot_date" not in result.columns:
            result["snapshot_date"] = result["trade_date"]
        return result
    snapshots = read_watchlist_snapshots(store)
    if snapshots.empty or "snapshot_date" not in snapshots.columns:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    latest = str(snapshots["snapshot_date"].dropna().astype(str).max())
    return snapshots[snapshots["snapshot_date"].astype(str) == latest].reset_index(drop=True)


def summarize_watchlist_tracking(store: DuckDBStore) -> dict[str, Any]:
    """Return latest Task 48 watchlist status counts and event summary."""
    latest = latest_tracking_snapshot(store)
    events = read_watchlist_events(store)
    status_counts = _status_counts(latest)
    return {
        "snapshot_count": int(len(latest)),
        "status_counts": status_counts,
        "new_candidate_count": int(status_counts.get("new_candidate", 0)),
        "strong_watch_count": int(status_counts.get("strong_watch", 0)),
        "wait_pullback_count": int(status_counts.get("wait_pullback", 0)),
        "overheated_count": int(status_counts.get("overheated", 0)),
        "weakening_count": int(status_counts.get("weakening", 0)),
        "invalidated_count": int(status_counts.get("invalidated", 0)),
        "near_buy_zone_count": int(status_counts.get("near_buy_zone", 0)),
        "event_count": int(len(events)),
    }


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


def _ensure_daily_tracking_tables(store: DuckDBStore) -> None:
    store.initialize()


def _load_selection_history(*, settings: Settings, store: DuckDBStore, top_n: int) -> pd.DataFrame:
    strategy = _safe_read_table(store, "strategy_result")
    if not strategy.empty and {"ts_code", "trade_date"}.issubset(strategy.columns):
        result = strategy.copy()
        if "rank" not in result.columns and "total_score" in result.columns:
            result = result.sort_values(["trade_date", "total_score"], ascending=[True, False])
            result["rank"] = result.groupby("trade_date").cumcount() + 1
        return _normalize_selection_columns(result)

    factor_scores = _safe_read_table(store, "factor_scores")
    if not factor_scores.empty and {"ts_code", "trade_date", "total_score"}.issubset(factor_scores.columns):
        try:
            selected = select_top_stocks(factor_scores, top_n=top_n)
            return _normalize_selection_columns(selected)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def _normalize_selection_columns(selection: pd.DataFrame) -> pd.DataFrame:
    if selection.empty:
        return selection.copy()
    result = selection.copy()
    if "trade_date" not in result.columns and "selection_date" in result.columns:
        result["trade_date"] = result["selection_date"]
    if "rank" not in result.columns and "total_score" in result.columns:
        result = result.sort_values(["trade_date", "total_score"], ascending=[True, False])
        result["rank"] = result.groupby("trade_date").cumcount() + 1
    if "rank" in result.columns:
        result["rank"] = pd.to_numeric(result["rank"], errors="coerce").astype("Int64")
    return result


def _latest_selection_date(selection_history: pd.DataFrame) -> str | None:
    if selection_history.empty or "trade_date" not in selection_history.columns:
        return None
    values = selection_history["trade_date"].dropna().astype(str)
    return None if values.empty else str(values.max())


def _current_selection(selection_history: pd.DataFrame, trade_date: str, top_n: int) -> pd.DataFrame:
    if selection_history.empty or "trade_date" not in selection_history.columns:
        return pd.DataFrame()
    current = selection_history[selection_history["trade_date"].astype(str) == str(trade_date)].copy()
    if current.empty:
        return current
    if "rank" in current.columns:
        current = current.sort_values("rank")
        return current[pd.to_numeric(current["rank"], errors="coerce") <= top_n].reset_index(drop=True)
    return current.head(top_n).reset_index(drop=True)


def _active_watch_codes(decisions: pd.DataFrame) -> set[str]:
    if decisions.empty or "ts_code" not in decisions.columns:
        return set()
    df = decisions.copy()
    if "decision" in df.columns:
        df = df[df["decision"].fillna("").astype(str) == "watch"]
    if "review_status" in df.columns:
        df = df[df["review_status"].fillna("active").astype(str) == "active"]
    return set(df["ts_code"].dropna().astype(str))


def _new_watch_decision_rows(
    *,
    current_selection: pd.DataFrame,
    existing_decisions: pd.DataFrame,
    active_codes: set[str],
    selection_date: str,
) -> list[dict[str, Any]]:
    if current_selection.empty or "ts_code" not in current_selection.columns:
        return []
    existing_by_code = _latest_decision_by_code(existing_decisions)
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for item in current_selection.to_dict("records"):
        ts_code = str(item.get("ts_code", ""))
        if not ts_code or ts_code in active_codes:
            continue
        previous = existing_by_code.get(ts_code, {})
        rows.append(
            {
                "decision_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ts_code}:{selection_date}")),
                "ts_code": ts_code,
                "name": item.get("name") or previous.get("name"),
                "selection_date": selection_date,
                "review_date": now[:10],
                "decision": "watch",
                "review_status": "active",
                "reviewer": previous.get("reviewer") or "",
                "reason": "今日候选新入选，加入观察池持续跟踪。",
                "notes": previous.get("notes") or "",
                "data_quality_note": previous.get("data_quality_note") or "",
                "source_report_path": previous.get("source_report_path") or "",
                "created_at": now,
                "updated_at": now,
            }
        )
    return rows


def _latest_decision_by_code(decisions: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if decisions.empty or "ts_code" not in decisions.columns:
        return {}
    df = decisions.copy()
    sort_col = "updated_at" if "updated_at" in df.columns else ("selection_date" if "selection_date" in df.columns else "ts_code")
    df = df.sort_values(sort_col)
    return {str(row["ts_code"]): row for row in df.to_dict("records")}


def _build_daily_snapshots(
    *,
    store: DuckDBStore,
    selection_history: pd.DataFrame,
    current_selection: pd.DataFrame,
    existing_decisions: pd.DataFrame,
    active_codes: set[str],
    trade_date: str,
    top_n: int,
    new_codes: set[str],
) -> pd.DataFrame:
    if not active_codes and current_selection.empty:
        return pd.DataFrame(columns=DAILY_SNAPSHOT_COLUMNS)
    price = _safe_read_table(store, "daily_price")
    elder = _elder_review_for_current_selection(current_selection, price)
    enriched_watchlist = build_watchlist_dataframe(store, active_only=True)
    enriched_by_code = {
        str(row.get("ts_code")): row
        for row in enriched_watchlist.to_dict("records")
        if row.get("ts_code") is not None
    }
    latest_snapshots = read_watchlist_daily_snapshots(store)
    previous_snapshot_by_code = _previous_snapshot_by_code(latest_snapshots, trade_date)
    decisions_by_code = _latest_decision_by_code(existing_decisions)
    current_by_code = {str(row.get("ts_code")): row for row in current_selection.to_dict("records")}
    codes = sorted(set(active_codes).union(current_by_code.keys()))
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for ts_code in codes:
        current = current_by_code.get(ts_code, {})
        enriched = enriched_by_code.get(ts_code, {})
        decision = decisions_by_code.get(ts_code, {})
        stats = _selection_stats(selection_history, ts_code, trade_date, top_n)
        latest_price = _latest_row(price, ts_code, "trade_date", cutoff_date=trade_date)
        previous = previous_snapshot_by_code.get(ts_code, {})
        elder_row = elder.get(ts_code, {})
        row_total_score = _optional_float(current.get("total_score")) or _optional_float(enriched.get("total_score"))
        score_change = stats["total_score_change"]
        if score_change is None:
            score_change = _diff(row_total_score, previous.get("total_score"))
        status = _resolve_watch_status(
            stats=stats,
            current=current,
            previous=previous,
            elder_row=elder_row,
            is_new=ts_code in new_codes,
        )
        rows.append(
            {
                "snapshot_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"daily:{ts_code}:{trade_date}")),
                "ts_code": ts_code,
                "name": current.get("name") or enriched.get("name") or decision.get("name"),
                "trade_date": trade_date,
                "current_close": _optional_float(latest_price.get("close")) or _optional_float(enriched.get("latest_close")),
                "pe": _optional_float(enriched.get("pe")),
                "pb": _optional_float(enriched.get("pb")),
                "today_rank": stats["today_rank"],
                "previous_rank": stats["previous_rank"],
                "rank_change": stats["rank_change"],
                "total_score": row_total_score,
                "total_score_change": score_change,
                "top_n_flag": bool(stats["top_n_flag"]),
                "new_candidate_flag": bool(ts_code in new_codes),
                "first_selected_date": stats["first_selected_date"],
                "last_selected_date": stats["last_selected_date"],
                "selected_count_5d": stats["selected_count_5d"],
                "selected_count_10d": stats["selected_count_10d"],
                "consecutive_selected_days": stats["consecutive_selected_days"],
                "best_rank": stats["best_rank"],
                "watch_status": status,
                "watch_status_label": WATCH_STATUS_LABELS.get(status, status),
                "watch_days": _watch_days(stats["first_selected_date"] or decision.get("selection_date"), trade_date),
                "entry_reason": decision.get("reason") or "",
                "watch_reason": _watch_reason(status, stats, elder_row),
                "daily_note": _daily_note(status, stats, elder_row),
                "elder_score": _optional_float(elder_row.get("elder_score")),
                "action_hint": elder_row.get("action_hint"),
                "elder_reason": elder_row.get("elder_reason"),
                "weekly_trend": elder_row.get("weekly_trend"),
                "daily_pullback": elder_row.get("daily_pullback"),
                "force_signal": elder_row.get("force_signal"),
                "elder_ray_signal": elder_row.get("elder_ray_signal"),
                "created_at": now,
            }
        )
    return pd.DataFrame(rows, columns=DAILY_SNAPSHOT_COLUMNS)


def _elder_review_for_current_selection(selection: pd.DataFrame, price: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if selection.empty or price.empty:
        return {}
    try:
        review = build_elder_review(selection, price)
    except Exception:
        return {}
    if review.empty or "ts_code" not in review.columns:
        return {}
    return {str(row["ts_code"]): row for row in review.to_dict("records")}


def _selection_stats(selection_history: pd.DataFrame, ts_code: str, trade_date: str, top_n: int) -> dict[str, Any]:
    empty = {
        "today_rank": None,
        "previous_rank": None,
        "rank_change": None,
        "total_score_change": None,
        "top_n_flag": False,
        "first_selected_date": None,
        "last_selected_date": None,
        "selected_count_5d": 0,
        "selected_count_10d": 0,
        "consecutive_selected_days": 0,
        "best_rank": None,
    }
    if selection_history.empty or "ts_code" not in selection_history.columns or "trade_date" not in selection_history.columns:
        return empty
    rows = selection_history[selection_history["ts_code"].astype(str) == ts_code].copy()
    if rows.empty:
        return empty
    rows["trade_date"] = rows["trade_date"].astype(str)
    rows = rows[rows["trade_date"] <= str(trade_date)].sort_values("trade_date")
    if rows.empty:
        return empty
    rank_values = pd.to_numeric(rows.get("rank"), errors="coerce") if "rank" in rows.columns else pd.Series([pd.NA] * len(rows))
    selected_rows = rows[rank_values <= top_n].copy()
    current_rows = rows[rows["trade_date"] == str(trade_date)]
    current = current_rows.iloc[-1].to_dict() if not current_rows.empty else {}
    previous_rows = rows[rows["trade_date"] < str(trade_date)]
    previous = previous_rows.iloc[-1].to_dict() if not previous_rows.empty else {}
    selected_dates = list(dict.fromkeys(selected_rows["trade_date"].tolist())) if not selected_rows.empty else []
    recent5 = selected_dates[-5:]
    recent10 = selected_dates[-10:]
    today_rank = _optional_int(current.get("rank"))
    previous_rank = _optional_int(previous.get("rank"))
    return {
        "today_rank": today_rank,
        "previous_rank": previous_rank,
        "rank_change": _rank_change(previous_rank, today_rank),
        "total_score_change": _diff(current.get("total_score"), previous.get("total_score")),
        "top_n_flag": today_rank is not None and today_rank <= top_n,
        "first_selected_date": str(selected_rows["trade_date"].iloc[0]) if not selected_rows.empty else None,
        "last_selected_date": str(selected_rows["trade_date"].iloc[-1]) if not selected_rows.empty else None,
        "selected_count_5d": int(selected_rows[selected_rows["trade_date"].isin(recent5)].shape[0]) if not selected_rows.empty else 0,
        "selected_count_10d": int(selected_rows[selected_rows["trade_date"].isin(recent10)].shape[0]) if not selected_rows.empty else 0,
        "consecutive_selected_days": _consecutive_selected_days(selected_dates, trade_date),
        "best_rank": _optional_int(pd.to_numeric(selected_rows.get("rank"), errors="coerce").min()) if not selected_rows.empty and "rank" in selected_rows.columns else None,
    }


def _resolve_watch_status(
    *,
    stats: dict[str, Any],
    current: dict[str, Any],
    previous: dict[str, Any],
    elder_row: dict[str, Any],
    is_new: bool,
) -> str:
    action_hint = str(elder_row.get("action_hint") or "")
    if is_new:
        return "new_candidate"
    if "短线过热" in action_hint or "不追" in action_hint:
        return "overheated"
    if "等待回调" in action_hint:
        return "wait_pullback"
    if "趋势偏弱" in action_hint or "暂缓" in action_hint:
        return "weakening"
    if stats.get("top_n_flag") is False and int(stats.get("consecutive_selected_days") or 0) == 0:
        return "invalidated"
    score_change = stats.get("total_score_change")
    rank_change = stats.get("rank_change")
    if (rank_change is not None and rank_change <= -5) or (score_change is not None and score_change <= -8):
        return "weakening"
    if int(stats.get("selected_count_5d") or 0) >= 3 and (rank_change is None or rank_change >= 0):
        return "strong_watch"
    if "接近" in action_hint or "回调" in action_hint:
        return "near_buy_zone"
    return "active_watch"


def _watch_reason(status: str, stats: dict[str, Any], elder_row: dict[str, Any]) -> str:
    if status == "new_candidate":
        return "今日首次进入候选，进入观察池持续跟踪。"
    if status == "strong_watch":
        return "近 5 日多次入选且排名或分数保持稳定。"
    if status == "wait_pullback":
        return "技术复核提示等待回调，适合继续观察节奏。"
    if status == "overheated":
        return "技术复核提示短线过热，避免把复核分解读为追高优先级。"
    if status == "weakening":
        return "排名、分数或技术状态转弱，需要人工复核。"
    if status == "invalidated":
        return "当前未进入候选范围，观察逻辑需要复核。"
    if status == "near_buy_zone":
        return "技术位置接近观察区间，仍需人工判断。"
    return "正常观察，暂无明显状态变化。"


def _daily_note(status: str, stats: dict[str, Any], elder_row: dict[str, Any]) -> str:
    pieces = [WATCH_STATUS_LABELS.get(status, status)]
    if stats.get("today_rank") is not None:
        pieces.append(f"今日排名 {stats['today_rank']}")
    if stats.get("rank_change") is not None:
        pieces.append(f"排名变化 {stats['rank_change']}")
    if stats.get("total_score_change") is not None:
        pieces.append(f"分数变化 {stats['total_score_change']:.2f}")
    if elder_row.get("action_hint"):
        pieces.append(str(elder_row["action_hint"]))
    return "；".join(pieces)


def _build_watchlist_events(*, store: DuckDBStore, snapshots: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    existing = read_watchlist_daily_snapshots(store)
    previous = _previous_snapshot_by_code(existing, trade_date)
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for item in snapshots.to_dict("records"):
        ts_code = str(item.get("ts_code", ""))
        old = previous.get(ts_code, {})
        event_type = ""
        reason = ""
        if item.get("new_candidate_flag"):
            event_type = "new_candidate"
            reason = "今日新入选并加入观察池。"
        elif old and old.get("watch_status") != item.get("watch_status"):
            event_type = "status_change"
            reason = f"观察池状态从 {old.get('watch_status')} 变为 {item.get('watch_status')}。"
        else:
            rank_change = _optional_int(item.get("rank_change"))
            score_change = _optional_float(item.get("total_score_change"))
            if rank_change is not None and abs(rank_change) >= 5:
                event_type = "rank_up" if rank_change > 0 else "rank_down"
                reason = f"排名明显变化 {rank_change}。"
            elif score_change is not None and abs(score_change) >= 5:
                event_type = "score_up" if score_change > 0 else "score_down"
                reason = f"综合分明显变化 {score_change:.2f}。"
        if not event_type:
            continue
        rows.append(
            {
                "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ts_code}:{trade_date}:{event_type}:{item.get('watch_status')}")),
                "ts_code": ts_code,
                "event_date": trade_date,
                "event_type": event_type,
                "old_status": old.get("watch_status"),
                "new_status": item.get("watch_status"),
                "old_rank": _optional_int(old.get("today_rank")),
                "new_rank": _optional_int(item.get("today_rank")),
                "old_score": _optional_float(old.get("total_score")),
                "new_score": _optional_float(item.get("total_score")),
                "reason": reason,
                "created_at": now,
            }
        )
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


def _previous_snapshot_by_code(snapshots: pd.DataFrame, trade_date: str) -> dict[str, dict[str, Any]]:
    if snapshots.empty or "ts_code" not in snapshots.columns:
        return {}
    date_col = "trade_date" if "trade_date" in snapshots.columns else "snapshot_date"
    if date_col not in snapshots.columns:
        return {}
    df = snapshots[snapshots[date_col].astype(str) < str(trade_date)].copy()
    if df.empty:
        return {}
    df = df.sort_values(date_col)
    return {str(row["ts_code"]): row for row in df.groupby("ts_code", as_index=False).tail(1).to_dict("records")}


def _status_counts(df: pd.DataFrame) -> dict[str, int]:
    counts = {status: 0 for status in WATCH_STATUS_LABELS}
    if df.empty or "watch_status" not in df.columns:
        return counts
    values = df["watch_status"].fillna("active_watch").astype(str).value_counts().to_dict()
    counts.update({key: int(values.get(key, 0)) for key in counts})
    return counts


def _rank_change(previous_rank: int | None, today_rank: int | None) -> int | None:
    if previous_rank is None or today_rank is None:
        return None
    return previous_rank - today_rank


def _consecutive_selected_days(dates: list[str], trade_date: str) -> int:
    if not dates or dates[-1] != str(trade_date):
        return 0
    count = 0
    for _ in reversed(dates):
        count += 1
    return count


def _watch_days(first_date: Any, trade_date: str) -> int | None:
    start = str(first_date or "")
    if not start:
        return None
    try:
        return max((datetime.strptime(str(trade_date), "%Y%m%d") - datetime.strptime(start, "%Y%m%d")).days, 0)
    except ValueError:
        return None


def _diff(value: Any, baseline: Any) -> float | None:
    current = _optional_float(value)
    previous = _optional_float(baseline)
    if current is None or previous is None:
        return None
    return current - previous


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
