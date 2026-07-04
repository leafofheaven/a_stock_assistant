"""Streamlit dashboard for A-share selection research results."""

from __future__ import annotations

import sys
import json
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.sample_data import get_sample_dashboard_data
from core.explain.selection_logic import (
    explain_candidates,
    explanations_to_dataframe,
    get_selection_logic_summary,
)
from core.jobs.diagnose_local_state import diagnose_local_state
from core.diagnostics.data_quality_snapshot import build_data_quality_snapshot
from core.reporting.selection_review_report import (
    REVIEW_CHECKLIST,
    load_latest_selection_review_report,
)
from core.reporting.review_template_report import latest_review_template_path, template_metadata
from core.reporting.watchlist_report import load_latest_watchlist_report
from core.reporting.watchlist_tracking_report import load_latest_watchlist_tracking_report
from core.reporting.workflow_report import load_latest_workflow_report
from core.reporting.daily_workflow_report import load_latest_daily_workflow_report
from core.config.env_file import masked_env_values, parse_stock_symbols, read_env_file, update_env_file
from core.runtime.command_runner import ALLOWED_COMMANDS, open_project_path, run_command_streaming
from core.jobs.run_scheduled_daily_update import DEFAULT_STATUS_PATH, read_scheduled_status
from core.runtime.progress import parse_progress_line
from core.technical.elder import build_elder_review
from core.external_positions.importer import position_template_frame, trade_template_frame

ALLOWED_COMMANDS.setdefault("run_full_batch_update", [sys.executable, "-m", "core.jobs.run_full_batch_update"])
ALLOWED_COMMANDS.setdefault("preflight_data_source", [sys.executable, "-m", "core.jobs.preflight_data_source"])
ALLOWED_COMMANDS.setdefault("diagnose_data_source_network", [sys.executable, "-m", "core.jobs.diagnose_data_source_network"])
ALLOWED_COMMANDS.setdefault("refresh_data_quality_status", [sys.executable, "-m", "core.jobs.refresh_data_quality_status"])
ALLOWED_COMMANDS.setdefault("run_scheduled_daily_update", [sys.executable, "-m", "core.jobs.run_scheduled_daily_update"])
ALLOWED_COMMANDS.setdefault("install_scheduled_daily_update", [sys.executable, "-m", "core.jobs.install_scheduled_daily_update"])
ALLOWED_COMMANDS.setdefault("uninstall_scheduled_daily_update", [sys.executable, "-m", "core.jobs.uninstall_scheduled_daily_update"])
ALLOWED_COMMANDS.setdefault("run_lookback_analysis", [sys.executable, "-m", "core.jobs.run_lookback_analysis"])

CORE_LOGIC_GUIDE_PATH = PROJECT_ROOT / "docs" / "user_guides" / "core_logic_guide.md"
CORE_LOGIC_GUIDE_DOWNLOAD_NAME = "A股选股辅助系统_核心逻辑说明.md"
LOOKBACK_STATUS_PATH = PROJECT_ROOT / "data" / "runtime" / "lookback_analysis_status.json"

SELECTION_COLUMNS = [
    "rank",
    "ts_code",
    "name",
    "industry",
    "list_date",
    "pe",
    "pb",
    "total_score",
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "fundamental_score",
    "volatility_score",
    "select_reason",
    "risk_note",
]

DISPLAY_COLUMN_LABELS = {
    "display_order": "序号",
    "watch_today_rank": "观察池当日排名",
    "previous_rank": "上一日排名",
    "ts_code": "股票代码",
    "name": "股票名称",
    "industry": "行业",
    "list_date": "上市日期",
    "pe": "PE",
    "pb": "PB",
    "total_score": "综合分",
    "trend_score": "趋势分",
    "momentum_score": "动量分",
    "liquidity_score": "流动性分",
    "fundamental_score": "基本面分",
    "volatility_score": "波动分",
    "elder_score": "埃尔德分",
    "action_hint": "操作提示",
    "elder_reason": "复核原因",
    "source": "来源",
    "review_date": "复核日期",
    "latest_trade_date": "最新行情日期",
    "trade_date": "交易日期",
    "current_close": "当前价",
    "close": "收盘价",
    "entry_low": "区间下沿",
    "entry_high": "区间上沿",
    "entry_mid": "区间中值",
    "stop_loss": "止损位",
    "target_price": "目标价位",
    "reward_risk_ratio": "盈亏比",
    "chase_risk_cn": "追高风险",
    "entry_zone_status_cn": "区间状态",
    "select_reason": "候选原因",
    "risk_note": "风险提示",
}

FACTOR_SCORE_COLUMNS = [
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "fundamental_score",
    "volatility_score",
    "total_score",
]


def filter_selection_data(
    selection_df: pd.DataFrame,
    industry: str | None = None,
    sort_descending: bool = True,
) -> pd.DataFrame:
    """Filter candidate stocks by industry and sort by total_score."""
    if selection_df.empty:
        return pd.DataFrame(columns=SELECTION_COLUMNS)

    df = _ensure_columns(selection_df.copy(), SELECTION_COLUMNS)
    if industry and industry != "全部" and "industry" in df.columns:
        df = df[df["industry"] == industry]

    if "total_score" in df.columns:
        df["total_score"] = pd.to_numeric(df["total_score"], errors="coerce")
        df = df.sort_values("total_score", ascending=not sort_descending, na_position="last")
    return df[SELECTION_COLUMNS].reset_index(drop=True)


def prepare_display_table(
    df: pd.DataFrame,
    *,
    columns: list[str] | None = None,
    add_display_order: bool = True,
    rename_for_display: bool = True,
    show_rank_fields: bool = False,
) -> pd.DataFrame:
    """Return a user-facing table with continuous display_order and clear rank names."""
    if df.empty:
        result = df.copy()
    else:
        result = df.copy().reset_index(drop=True)
    if "rank" in result.columns and "candidate_rank" not in result.columns:
        result = result.rename(columns={"rank": "candidate_rank"})
    if "today_rank" in result.columns and "watch_today_rank" not in result.columns:
        result = result.rename(columns={"today_rank": "watch_today_rank"})
    if columns is not None:
        available = [column for column in columns if column in result.columns]
        result = result[available].copy()
    if not show_rank_fields:
        result = result.drop(columns=[column for column in ["candidate_rank"] if column in result.columns])
    if add_display_order:
        if "display_order" in result.columns:
            result = result.drop(columns=["display_order"])
        result.insert(0, "display_order", range(1, len(result) + 1))
    if rename_for_display:
        result = result.rename(columns={key: value for key, value in DISPLAY_COLUMN_LABELS.items() if key in result.columns})
    return result.reset_index(drop=True)


def display_dataframe(
    st: Any,
    df: pd.DataFrame,
    *,
    columns: list[str] | None = None,
    show_rank_fields: bool = False,
) -> None:
    """Render a dataframe without exposing pandas' raw index."""
    display_df = prepare_display_table(df, columns=columns, show_rank_fields=show_rank_fields)
    try:
        st.dataframe(display_df, width="stretch", hide_index=True)
    except TypeError:
        st.dataframe(display_df, width="stretch")


def enrich_selection_with_watchlist_status(selection_df: pd.DataFrame, tables: dict[str, Any]) -> pd.DataFrame:
    """Attach watchlist status fields to displayed selection rows without resorting."""
    if selection_df.empty or "ts_code" not in selection_df.columns:
        return selection_df
    snapshot = tables.get("_watchlist_snapshot", pd.DataFrame())
    result = selection_df.copy()
    if not isinstance(snapshot, pd.DataFrame) or snapshot.empty or "ts_code" not in snapshot.columns:
        result["is_in_watchlist"] = False
        result["watchlist_status"] = ""
        result["suggest_add_to_watchlist"] = True
        return result
    latest = snapshot.copy()
    date_col = "trade_date" if "trade_date" in latest.columns else "snapshot_date"
    if date_col in latest.columns:
        latest_date = latest[date_col].dropna().astype(str).max()
        latest = latest[latest[date_col].astype(str) == str(latest_date)]
    fields = [
        "ts_code",
        "watch_status",
        "watch_status_label",
        "selected_count_5d",
        "selected_count_10d",
        "consecutive_selected_days",
        "rank_change",
    ]
    available = [column for column in fields if column in latest.columns]
    merged = result.merge(latest[available].drop_duplicates("ts_code"), on="ts_code", how="left")
    merged["is_in_watchlist"] = merged["watch_status"].notna() if "watch_status" in merged.columns else False
    if "watch_status_label" in merged.columns:
        merged["watchlist_status"] = merged["watch_status_label"].fillna("")
    else:
        merged["watchlist_status"] = merged.get("watch_status", "")
    merged["suggest_add_to_watchlist"] = ~merged["is_in_watchlist"]
    return merged.reset_index(drop=True)


def enrich_with_entry_zone_fields(df: pd.DataFrame, tables: dict[str, Any]) -> pd.DataFrame:
    """Attach latest entry zone fields by ts_code without changing row order."""
    if df.empty or "ts_code" not in df.columns:
        return df.copy()
    entry_zones = _latest_entry_zone_snapshot(tables.get("entry_zone_snapshots", pd.DataFrame()))
    if entry_zones.empty or "ts_code" not in entry_zones.columns:
        return df.copy()
    fields = [
        "ts_code",
        "entry_low",
        "entry_high",
        "stop_loss",
        "target_price",
        "reward_risk_ratio",
        "chase_risk_cn",
        "entry_zone_status_cn",
        "price_action_note",
    ]
    available = [column for column in fields if column in entry_zones.columns]
    return df.merge(entry_zones[available].drop_duplicates("ts_code"), on="ts_code", how="left")


def _latest_entry_zone_snapshot(entry_zones: pd.DataFrame) -> pd.DataFrame:
    """Return latest entry zone snapshot rows."""
    if entry_zones.empty or "trade_date" not in entry_zones.columns:
        return pd.DataFrame()
    latest = _latest_date(entry_zones, "trade_date")
    return entry_zones[entry_zones["trade_date"].astype(str) == str(latest)].copy()


def summarize_watchlist_snapshot(snapshot_df: pd.DataFrame) -> dict[str, int]:
    """Summarize latest watchlist daily snapshot by status for Streamlit cards."""
    if snapshot_df.empty:
        return {"total": 0}
    df = snapshot_df.copy()
    date_col = "trade_date" if "trade_date" in df.columns else "snapshot_date"
    if date_col in df.columns:
        latest_date = df[date_col].dropna().astype(str).max()
        df = df[df[date_col].astype(str) == str(latest_date)]
    counts = df.get("watch_status", pd.Series(dtype=str)).fillna("active_watch").astype(str).value_counts().to_dict()
    return {"total": int(len(df)), **{key: int(value) for key, value in counts.items()}}


def dataframe_to_csv(df: pd.DataFrame) -> str:
    """Convert a DataFrame to UTF-8 CSV text without the index."""
    buffer = StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue()


def get_industry_options(df: pd.DataFrame) -> list[str]:
    """Return industry filter options with an all-industries entry."""
    if df.empty or "industry" not in df.columns:
        return ["全部"]
    industries = sorted(str(value) for value in df["industry"].dropna().unique())
    return ["全部", *industries]


def filter_factor_ranking(
    factor_df: pd.DataFrame,
    trade_date: str | None = None,
    industry: str | None = None,
    factor_col: str = "total_score",
) -> pd.DataFrame:
    """Filter and rank factor data for one date and optional industry."""
    if factor_df.empty:
        return pd.DataFrame()
    df = factor_df.copy()
    if trade_date and "trade_date" in df.columns:
        df = df[df["trade_date"].astype(str) == str(trade_date)]
    if industry and industry != "全部" and "industry" in df.columns:
        df = df[df["industry"] == industry]
    if factor_col in df.columns:
        df[factor_col] = pd.to_numeric(df[factor_col], errors="coerce")
        df = df.sort_values(factor_col, ascending=False, na_position="last")
    return df.reset_index(drop=True)


def calculate_recent_returns(price_df: pd.DataFrame, ts_code: str) -> dict[str, float | None]:
    """Calculate recent 20-day and 60-day returns for one stock from local data."""
    if price_df.empty or not {"ts_code", "trade_date", "close"}.issubset(price_df.columns):
        return {"return_20d": None, "return_60d": None}
    df = price_df[price_df["ts_code"] == ts_code].copy()
    if df.empty:
        return {"return_20d": None, "return_60d": None}
    df = df.sort_values("trade_date")
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    return {
        "return_20d": _trailing_return(close, 20),
        "return_60d": _trailing_return(close, 60),
    }


def summarize_update_status(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Summarize latest dates and row counts for dashboard status display."""
    daily_price = tables.get("daily_price", pd.DataFrame())
    factor_scores = tables.get("factor_scores", pd.DataFrame())
    strategy_result = tables.get("strategy_result", pd.DataFrame())
    data_source = str(tables.get("_data_source", ""))
    factor_missing = summarize_factor_missing(factor_scores)
    basic_quality = summarize_basic_data_quality(
        tables.get("stock_basic", pd.DataFrame()),
        tables.get("daily_basic", pd.DataFrame()),
    )
    configured_count = int(tables.get("_configured_symbol_count", 0) or 0)
    priced_count = int(tables.get("_priced_symbol_count", 0) or 0)
    coverage_rate = float(tables.get("_coverage_rate", 0.0) or 0.0)
    missing_count = int(tables.get("_missing_symbol_count", 0) or 0)
    stale_count = int(tables.get("_stale_symbol_count", 0) or 0)
    update_failed_count = int(tables.get("_update_failed_count", 0) or 0)
    empty_data_count = int(tables.get("_empty_data_count", 0) or 0)
    network_failed_count = int(tables.get("_network_failed_count", 0) or 0)
    selection_ready_count = int(tables.get("_selection_ready_count", 0) or 0)
    backtest_ready_count = int(tables.get("_backtest_ready_count", 0) or 0)
    duckdb_path = str(tables.get("_duckdb_path", ""))
    batch_status = str(tables.get("_batch_status", ""))
    bse_filter_note = str(tables.get("_bse_filter_note", ""))
    latest_workflow_report = tables.get("_latest_workflow_report")
    latest_daily_workflow_report = tables.get("_latest_daily_workflow_report")
    latest_selection_review_report = tables.get("_latest_selection_review_report")
    latest_review_template = tables.get("_latest_review_template")
    latest_watchlist_report = tables.get("_latest_watchlist_report")
    latest_watchlist_tracking_report = tables.get("_latest_watchlist_tracking_report")
    local_state = tables.get("_local_state")
    return {
        "latest_price_date": tables.get("_latest_price_date") or _latest_date(daily_price, "trade_date"),
        "latest_factor_date": _latest_date(factor_scores, "trade_date"),
        "latest_selection_date": _latest_date(strategy_result, "trade_date"),
        "is_sample_data": "sample" in data_source or "演示" in data_source,
        "is_real_data": "本地 DuckDB 真实数据" in data_source,
        "field_missing": {
            column: stats["nan_count"]
            for column, stats in factor_missing.items()
            if stats["nan_count"] > 0
        },
        "factor_missing": factor_missing,
        "basic_quality": basic_quality,
        "configured_symbol_count": configured_count,
        "priced_symbol_count": priced_count,
        "coverage_rate": coverage_rate,
        "missing_symbol_count": missing_count,
        "stale_symbol_count": stale_count,
        "update_failed_count": update_failed_count,
        "empty_data_count": empty_data_count,
        "network_failed_count": network_failed_count,
        "selection_ready_count": selection_ready_count,
        "backtest_ready_count": backtest_ready_count,
        "latest_trade_date": tables.get("_latest_trade_date") or tables.get("_latest_price_date") or _latest_date(daily_price, "trade_date"),
        "latest_price_symbol_count": int(tables.get("_latest_price_symbol_count", 0) or 0),
        "missing_latest_price_symbol_count": int(tables.get("_missing_latest_price_symbol_count", 0) or 0),
        "latest_price_coverage_rate": float(tables.get("_latest_price_coverage_rate", 0.0) or 0.0),
        "history_complete_symbol_count": int(tables.get("_history_complete_symbol_count", 0) or 0),
        "history_incomplete_symbol_count": int(tables.get("_history_incomplete_symbol_count", 0) or 0),
        "history_missing_symbol_count": int(tables.get("_history_missing_symbol_count", 0) or 0),
        "available_days_20d_count": int(tables.get("_available_days_20d_count", 0) or 0),
        "available_days_60d_count": int(tables.get("_available_days_60d_count", 0) or 0),
        "available_days_120d_count": int(tables.get("_available_days_120d_count", 0) or 0),
        "available_days_252d_count": int(tables.get("_available_days_252d_count", 0) or 0),
        "factor_ready_symbol_count": int(tables.get("_factor_ready_symbol_count", selection_ready_count) or 0),
        "elder_ready_symbol_count": int(tables.get("_elder_ready_symbol_count", 0) or 0),
        "entry_zone_ready_symbol_count": int(tables.get("_entry_zone_ready_symbol_count", 0) or 0),
        "lookback_ready_symbol_count": int(tables.get("_lookback_ready_symbol_count", 0) or 0),
        "latest_updated_but_history_incomplete_count": int(tables.get("_latest_updated_but_history_incomplete_count", 0) or 0),
        "latest_updated_but_history_incomplete_examples": list(tables.get("_latest_updated_but_history_incomplete_examples", []) or []),
        "history_complete_but_latest_missing_count": int(tables.get("_history_complete_but_latest_missing_count", 0) or 0),
        "history_complete_but_latest_missing_examples": list(tables.get("_history_complete_but_latest_missing_examples", []) or []),
        "completely_missing_price_count": int(tables.get("_completely_missing_price_count", missing_count) or 0),
        "completely_missing_price_examples": list(tables.get("_completely_missing_price_examples", []) or []),
        "duckdb_path": duckdb_path,
        "bse_filter_note": bse_filter_note,
        "batch_status": batch_status,
        "table_rows": {name: len(df) for name, df in tables.items() if isinstance(df, pd.DataFrame)},
        "last_job_status": _workflow_status_message(latest_workflow_report),
        "latest_workflow_report": latest_workflow_report,
        "latest_daily_workflow_report": latest_daily_workflow_report,
        "latest_selection_review_report": latest_selection_review_report,
        "latest_review_template": latest_review_template,
        "latest_watchlist_report": latest_watchlist_report,
        "latest_watchlist_tracking_report": latest_watchlist_tracking_report,
        "local_state": local_state,
    }


def summarize_factor_missing(factor_df: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    """Summarize factor non-null rates and missing counts for dashboard display."""
    if factor_df.empty:
        return {}
    result: dict[str, dict[str, float | int]] = {}
    row_count = len(factor_df)
    for column in [column for column in FACTOR_SCORE_COLUMNS if column in factor_df.columns]:
        values = pd.to_numeric(factor_df[column], errors="coerce")
        non_null = int(values.notna().sum())
        result[column] = {
            "non_null_rate": float(non_null / row_count) if row_count else 0.0,
            "nan_count": int(row_count - non_null),
        }
    return result


def summarize_basic_data_quality(
    stock_basic: pd.DataFrame,
    daily_basic: pd.DataFrame,
) -> dict[str, dict[str, float | int]]:
    """Summarize basic-info and valuation field completeness for dashboard display."""
    return {
        "stock_basic": _field_quality(stock_basic, ["name", "industry", "market", "list_date"]),
        "daily_basic": _field_quality(daily_basic, ["turnover_rate", "pe", "pb", "total_mv", "circ_mv"]),
    }


def _field_quality(df: pd.DataFrame, fields: list[str]) -> dict[str, dict[str, float | int]]:
    """Return non-null rate and missing count for dashboard fields."""
    result: dict[str, dict[str, float | int]] = {}
    row_count = len(df)
    for field in fields:
        if df.empty or field not in df.columns:
            result[field] = {"non_null_rate": 0.0, "missing_count": row_count}
            continue
        non_null = int(df[field].apply(lambda value: not _is_missing(value)).sum())
        result[field] = {
            "non_null_rate": float(non_null / row_count) if row_count else 0.0,
            "missing_count": int(row_count - non_null),
        }
    return result


def describe_dashboard_data_source(data: dict[str, Any]) -> dict[str, str]:
    """Return user-facing dashboard data source status."""
    data_source = str(data.get("data_source") or "sample 数据（演示）")
    tables = data.get("tables", {})
    latest_price_date = summarize_update_status(tables).get("latest_price_date") if isinstance(tables, dict) else None
    if "sample" in data_source or "演示" in data_source:
        message = "当前展示 sample 演示数据，仅用于流程验证。"
    elif latest_price_date:
        message = f"当前展示真实数据，最新交易日期：{latest_price_date}。"
    else:
        message = "真实数据不足，当前页面仅展示可用数据或友好空状态。"
    return {"data_source": data_source, "message": message}


def sample_dashboard_data() -> dict[str, Any]:
    """Return local demo data so the first dashboard render is useful."""
    return get_sample_dashboard_data()


def load_dashboard_data() -> dict[str, Any]:
    """Load local real dashboard data when available, otherwise return sample data."""
    from app.config import get_settings
    from core.storage.duckdb_store import DUCKDB_LOCK_MESSAGE, DuckDBStore, DuckDBStoreError, DuckDBStoreLockedError

    settings = get_settings()
    database_status = _database_status(str(settings.duckdb_path), exists=Path(settings.duckdb_path).exists())
    if settings.data_provider == "sample":
        data = sample_dashboard_data()
        data.setdefault("tables", {})["_database_status"] = {**database_status, "status": "sample", "message": "当前使用 sample 数据。"}
        data.setdefault("tables", {})["_latest_workflow_report"] = load_latest_workflow_report()
        data.setdefault("tables", {})["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
        data.setdefault("tables", {})["_latest_selection_review_report"] = load_latest_selection_review_report()
        data.setdefault("tables", {})["_latest_review_template"] = template_metadata(latest_review_template_path())
        data.setdefault("tables", {})["_latest_watchlist_report"] = load_latest_watchlist_report()
        data.setdefault("tables", {})["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
        data.setdefault("tables", {})["_local_state"] = _safe_local_state()
        data.setdefault("watchlist", pd.DataFrame())
        data.setdefault("watchlist_snapshot", pd.DataFrame())
        data.setdefault("positions", pd.DataFrame())
        return data

    store = DuckDBStore(settings.duckdb_path)
    if not store.db_path.exists():
        data = sample_dashboard_data()
        data["data_source"] = "sample 数据（演示，真实 DuckDB 文件不存在）"
        data.setdefault("tables", {})["_database_status"] = {**database_status, "status": "missing", "message": "DuckDB 文件不存在。"}
        data.setdefault("tables", {})["_latest_workflow_report"] = load_latest_workflow_report()
        data.setdefault("tables", {})["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
        data.setdefault("tables", {})["_latest_selection_review_report"] = load_latest_selection_review_report()
        data.setdefault("tables", {})["_latest_review_template"] = template_metadata(latest_review_template_path())
        data.setdefault("tables", {})["_latest_watchlist_report"] = load_latest_watchlist_report()
        data.setdefault("tables", {})["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
        data.setdefault("tables", {})["_local_state"] = _safe_local_state()
        data.setdefault("watchlist", pd.DataFrame())
        data.setdefault("watchlist_snapshot", pd.DataFrame())
        data.setdefault("positions", pd.DataFrame())
        return data

    try:
        tables = _safe_load_dashboard_tables(store)
    except DuckDBStoreLockedError:
        data = sample_dashboard_data()
        data["data_source"] = "sample 数据（演示，DuckDB 被锁定）"
        data.setdefault("tables", {})["_database_status"] = {**database_status, "status": "locked", "message": DUCKDB_LOCK_MESSAGE}
        data.setdefault("tables", {})["_latest_workflow_report"] = load_latest_workflow_report()
        data.setdefault("tables", {})["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
        data.setdefault("tables", {})["_latest_selection_review_report"] = load_latest_selection_review_report()
        data.setdefault("tables", {})["_latest_review_template"] = template_metadata(latest_review_template_path())
        data.setdefault("tables", {})["_latest_watchlist_report"] = load_latest_watchlist_report()
        data.setdefault("tables", {})["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
        data.setdefault("tables", {})["_local_state"] = _safe_local_state()
        data.setdefault("watchlist", pd.DataFrame())
        data.setdefault("watchlist_snapshot", pd.DataFrame())
        data.setdefault("positions", pd.DataFrame())
        return data
    except DuckDBStoreError as exc:
        data = sample_dashboard_data()
        data["data_source"] = "sample 数据（演示，真实数据读取失败）"
        data.setdefault("tables", {})["_database_status"] = {**database_status, "status": "error", "message": str(exc)}
        data.setdefault("tables", {})["_latest_workflow_report"] = load_latest_workflow_report()
        data.setdefault("tables", {})["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
        data.setdefault("tables", {})["_latest_selection_review_report"] = load_latest_selection_review_report()
        data.setdefault("tables", {})["_latest_review_template"] = template_metadata(latest_review_template_path())
        data.setdefault("tables", {})["_latest_watchlist_report"] = load_latest_watchlist_report()
        data.setdefault("tables", {})["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
        data.setdefault("tables", {})["_local_state"] = _safe_local_state()
        data.setdefault("watchlist", pd.DataFrame())
        data.setdefault("watchlist_snapshot", pd.DataFrame())
        data.setdefault("positions", pd.DataFrame())
        return data

    if tables["strategy_result"].empty:
        tables["_data_source"] = f"{settings.data_provider} 本地 DuckDB 真实数据"
        tables["_database_status"] = {**database_status, "status": "ok", "message": "DuckDB 可访问，但尚未生成本地选股结果。"}
        tables["_latest_workflow_report"] = load_latest_workflow_report()
        tables["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
        tables["_latest_selection_review_report"] = load_latest_selection_review_report()
        tables["_latest_review_template"] = template_metadata(latest_review_template_path())
        tables["_latest_watchlist_report"] = load_latest_watchlist_report()
        tables["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
        tables["_local_state"] = _safe_local_state()
        _apply_lightweight_database_metrics(tables, _lightweight_database_metrics(settings, store, tables))
        watchlist = _load_watchlist_for_dashboard(store)
        watchlist_snapshot = _load_tracking_snapshot_for_dashboard(store)
        positions = _load_positions_for_dashboard(store)
        tables["_watchlist_snapshot"] = watchlist_snapshot
        dashboard_price = _safe_read_dashboard_price_history(store, tables, watchlist=watchlist, positions=positions)
        tables["_dashboard_price_history"] = dashboard_price
        return {
            "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据（尚未生成本地选股结果）",
            "selection": pd.DataFrame(columns=SELECTION_COLUMNS),
            "stock_basic": tables["stock_basic"],
            "price": dashboard_price,
            "daily_basic": tables["daily_basic"],
            "factor_scores": tables["factor_scores"],
            "backtest": {},
            "watchlist": watchlist,
            "watchlist_snapshot": watchlist_snapshot,
            "positions": positions,
            "tables": tables,
        }

    tables["_latest_workflow_report"] = load_latest_workflow_report()
    tables["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
    tables["_latest_selection_review_report"] = load_latest_selection_review_report()
    tables["_latest_review_template"] = template_metadata(latest_review_template_path())
    tables["_latest_watchlist_report"] = load_latest_watchlist_report()
    tables["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
    tables["_local_state"] = _safe_local_state()
    _apply_lightweight_database_metrics(tables, _lightweight_database_metrics(settings, store, tables))
    watchlist = _load_watchlist_for_dashboard(store)
    watchlist_snapshot = _load_tracking_snapshot_for_dashboard(store)
    positions = _load_positions_for_dashboard(store)
    tables["_watchlist_snapshot"] = watchlist_snapshot
    dashboard_price = _safe_read_dashboard_price_history(store, tables, watchlist=watchlist, positions=positions)
    tables["_dashboard_price_history"] = dashboard_price
    return {
        "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据",
        "selection": tables["strategy_result"],
        "stock_basic": tables["stock_basic"],
        "price": dashboard_price,
        "daily_basic": tables["daily_basic"],
        "factor_scores": tables["factor_scores"],
        "backtest": {},
        "watchlist": watchlist,
        "watchlist_snapshot": watchlist_snapshot,
        "positions": positions,
        "tables": tables,
    }


def _safe_load_dashboard_tables(store: Any) -> dict[str, pd.DataFrame]:
    """Read lightweight dashboard tables with read-only short connections."""
    tables: dict[str, pd.DataFrame] = {
        "stock_basic": _safe_read_store_table(store, "stock_basic", limit=10000),
        "daily_price": _safe_read_store_table(store, "daily_price", limit=30000),
        "daily_basic": _safe_read_store_table(store, "daily_basic", limit=30000),
        "factor_scores": _safe_read_store_table(store, "factor_scores", limit=10000),
        "strategy_result": _safe_read_store_table(store, "strategy_result", limit=5000),
        "backtest_result": _safe_read_store_table(store, "backtest_result", limit=1000),
        "review_decisions": _safe_read_store_table(store, "review_decisions", limit=5000),
        "review_decision_history": _safe_read_store_table(store, "review_decision_history", limit=10000),
        "positions": _safe_read_store_table(store, "positions", limit=5000),
        "entry_zone_snapshots": _safe_read_store_table(store, "entry_zone_snapshots", limit=10000),
        "external_position_snapshots": _safe_read_store_table(store, "external_position_snapshots", limit=10000),
        "external_trades": _safe_read_store_table(store, "external_trades", limit=10000),
    }
    return tables


def _safe_read_dashboard_price_history(
    store: Any,
    tables: dict[str, pd.DataFrame],
    *,
    watchlist: pd.DataFrame | None = None,
    positions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Read full local price history only for dashboard focus stocks.

    The dashboard intentionally loads large tables with limits so the page can
    start quickly. Elder review needs complete history for the current
    candidates/watchlist; otherwise a limited full-universe sample can make
    valid candidates look like they have "日线数据不足".
    """
    codes = _dashboard_focus_codes(tables, watchlist=watchlist, positions=positions)
    focused = _safe_read_price_history_for_codes(store, codes)
    if not focused.empty:
        return focused
    return tables.get("daily_price", pd.DataFrame())


def _dashboard_focus_codes(
    tables: dict[str, pd.DataFrame],
    *,
    watchlist: pd.DataFrame | None = None,
    positions: pd.DataFrame | None = None,
) -> list[str]:
    """Return symbols whose complete price history is useful for page render."""
    frames = [
        tables.get("strategy_result", pd.DataFrame()),
        tables.get("factor_scores", pd.DataFrame()),
        tables.get("review_decisions", pd.DataFrame()),
        tables.get("entry_zone_snapshots", pd.DataFrame()),
        watchlist if isinstance(watchlist, pd.DataFrame) else pd.DataFrame(),
        positions if isinstance(positions, pd.DataFrame) else pd.DataFrame(),
    ]
    codes: list[str] = []
    seen: set[str] = set()
    for frame in frames:
        if frame.empty or "ts_code" not in frame.columns:
            continue
        for value in frame["ts_code"].dropna().astype(str).tolist():
            code = value.strip()
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


def _safe_read_price_history_for_codes(store: Any, codes: list[str]) -> pd.DataFrame:
    """Read complete daily_price rows for specific symbols using read-only DuckDB."""
    from core.storage.duckdb_store import DuckDBStoreLockedError

    symbols = [code for code in dict.fromkeys(codes) if code]
    if not symbols:
        return pd.DataFrame()
    placeholders = ", ".join(["?"] * len(symbols))
    query = f"""
        SELECT *
        FROM daily_price
        WHERE ts_code IN ({placeholders})
        ORDER BY ts_code, trade_date
    """
    try:
        with store.connect(read_only=True) as connection:
            return connection.execute(query, symbols).fetchdf()
    except DuckDBStoreLockedError:
        raise
    except Exception:
        return pd.DataFrame()


def _lightweight_database_metrics(settings: Any, store: Any, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Return lightweight local universe and coverage metrics without external calls."""
    metrics: dict[str, Any] = {
        "configured_symbol_count": 0,
        "priced_symbol_count": 0,
        "coverage_rate": 0.0,
        "missing_symbol_count": 0,
        "latest_price_date": None,
        "sample_source": "",
        "batch_status": "",
    }
    stock_basic = tables.get("stock_basic", pd.DataFrame())
    daily_price = tables.get("daily_price", pd.DataFrame())
    try:
        with store.connect(read_only=True) as connection:
            price_row = connection.execute("SELECT COUNT(DISTINCT ts_code), MAX(trade_date) FROM daily_price").fetchone()
            metrics["priced_symbol_count"] = int(price_row[0] or 0)
            metrics["latest_price_date"] = str(price_row[1]) if price_row and price_row[1] is not None else None
    except Exception:
        if isinstance(daily_price, pd.DataFrame) and not daily_price.empty:
            metrics["priced_symbol_count"] = int(daily_price["ts_code"].dropna().astype(str).nunique()) if "ts_code" in daily_price.columns else 0
            metrics["latest_price_date"] = _latest_date(daily_price, "trade_date")

    explicit = str(getattr(settings, "akshare_sample_symbols", "") or "").strip()
    preset = str(getattr(settings, "real_universe_preset", "") or "mini").strip().lower()
    if explicit:
        symbols = [item.strip() for item in explicit.split(",") if item.strip()]
        metrics["configured_symbol_count"] = len(symbols)
        metrics["sample_source"] = "AKSHARE_SAMPLE_SYMBOLS"
    elif preset == "full":
        try:
            from core.data_sources.real_universe import resolve_full_a_share_universe

            universe = resolve_full_a_share_universe(stock_basic, include_bse=getattr(settings, "include_bse", False))
            configured = int(universe.get("base_universe_count", 0) or 0)
            metrics.update(
                {
                    "configured_symbol_count": configured,
                    "raw_symbol_count": int(universe.get("raw_symbol_count", configured) or 0),
                    "base_universe_count": configured,
                    "excluded_bse_count": int(universe.get("excluded_bse_count", 0) or 0),
                    "excluded_abnormal_count": int(universe.get("excluded_abnormal_count", 0) or 0),
                    "bse_filter_note": universe.get("bse_filter_note", ""),
                    "sample_source": "REAL_UNIVERSE_PRESET=full",
                }
            )
        except Exception:
            metrics["configured_symbol_count"] = int(stock_basic["ts_code"].dropna().astype(str).nunique()) if isinstance(stock_basic, pd.DataFrame) and "ts_code" in stock_basic.columns else 0
            metrics["sample_source"] = "REAL_UNIVERSE_PRESET=full"
    else:
        try:
            from core.data_sources.universe_presets import get_universe_preset

            metrics["configured_symbol_count"] = len(get_universe_preset(preset))
        except Exception:
            metrics["configured_symbol_count"] = 0
        metrics["sample_source"] = "REAL_UNIVERSE_PRESET"

    configured_count = int(metrics.get("configured_symbol_count", 0) or 0)
    priced_count = int(metrics.get("priced_symbol_count", 0) or 0)
    metrics["coverage_rate"] = float(priced_count / configured_count) if configured_count else 0.0
    metrics["missing_symbol_count"] = max(configured_count - priced_count, 0)
    metrics["latest_trade_date"] = metrics.get("latest_price_date")
    metrics["latest_price_symbol_count"] = priced_count
    metrics["missing_latest_price_symbol_count"] = max(configured_count - priced_count, 0)
    metrics["latest_price_coverage_rate"] = metrics["coverage_rate"]
    metrics["history_missing_symbol_count"] = metrics["missing_symbol_count"]
    metrics["completely_missing_price_count"] = metrics["missing_symbol_count"]
    if preset == "full" and configured_count and priced_count < configured_count:
        metrics["batch_status"] = "全市场数据未完成"
    elif configured_count:
        metrics["batch_status"] = "当前股票池已有行情覆盖"
    return metrics


def _apply_lightweight_database_metrics(tables: dict[str, Any], metrics: dict[str, Any]) -> None:
    """Attach lightweight local coverage metrics to dashboard metadata."""
    for key, value in metrics.items():
        tables[f"_{key}"] = value


def _database_status(path: str, *, exists: bool) -> dict[str, Any]:
    """Build a database status payload for the page header."""
    return {
        "duckdb_path": path,
        "exists": exists,
        "status": "ok" if exists else "missing",
        "message": "DuckDB 可访问。" if exists else "DuckDB 文件不存在。",
    }


def _computed_real_dashboard_data(settings: Any, store: Any, tables: dict[str, pd.DataFrame]) -> dict[str, Any] | None:
    """Return computed real factor/selection data when result tables are not persisted yet."""
    from core.jobs.diagnose_backtest import diagnose_backtest
    from core.jobs.diagnose_factors import diagnose_factors
    from core.jobs.diagnose_update_batch import diagnose_update_batch

    diagnostic = diagnose_factors(settings=settings, store=store, use_sample=False)
    backtest_diagnostic = diagnose_backtest(settings=settings, store=store, use_sample=False)
    batch_diagnostic = diagnose_update_batch(settings=settings, store=store)
    factor_scores = diagnostic.get("factor_scores_df", pd.DataFrame())
    selected = diagnostic.get("selected_df", pd.DataFrame())
    if factor_scores.empty or selected.empty:
        return None
    real_tables = dict(tables)
    real_tables["factor_scores"] = factor_scores
    real_tables["strategy_result"] = selected
    focused_price = _safe_read_price_history_for_codes(
        store,
        _dashboard_focus_codes({**tables, "strategy_result": selected, "factor_scores": factor_scores}),
    )
    if not focused_price.empty:
        real_tables["_dashboard_price_history"] = focused_price
    real_tables["_data_source"] = f"{settings.data_provider} 本地 DuckDB 真实数据"
    real_tables["_configured_symbol_count"] = batch_diagnostic.get("configured_symbol_count", 0)
    real_tables["_priced_symbol_count"] = batch_diagnostic.get("priced_symbol_count", 0)
    real_tables["_coverage_rate"] = batch_diagnostic.get("coverage_rate", 0.0)
    real_tables["_missing_symbol_count"] = len(batch_diagnostic.get("missing_symbols", []))
    real_tables["_stale_symbol_count"] = batch_diagnostic.get("stale_symbol_count", 0)
    real_tables["_update_failed_count"] = batch_diagnostic.get("update_failed_count", 0)
    real_tables["_empty_data_count"] = batch_diagnostic.get("empty_data_count", 0)
    real_tables["_network_failed_count"] = batch_diagnostic.get("network_failed_count", 0)
    real_tables["_selection_ready_count"] = batch_diagnostic.get("selection_ready_count", 0)
    real_tables["_backtest_ready_count"] = batch_diagnostic.get("backtest_ready_count", 0)
    real_tables["_duckdb_path"] = batch_diagnostic.get("duckdb_path", str(getattr(store, "db_path", "")))
    real_tables["_batch_status"] = _full_batch_status_text(batch_diagnostic)
    real_tables["_bse_filter_note"] = batch_diagnostic.get("bse_filter_note", "")
    _apply_batch_diagnostic_to_tables(real_tables, batch_diagnostic)
    real_tables["_latest_workflow_report"] = load_latest_workflow_report()
    real_tables["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
    real_tables["_latest_selection_review_report"] = load_latest_selection_review_report()
    real_tables["_latest_review_template"] = template_metadata(latest_review_template_path())
    real_tables["_latest_watchlist_report"] = load_latest_watchlist_report()
    real_tables["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
    real_tables["_local_state"] = _safe_local_state()
    real_tables["review_decisions"] = _safe_read_store_table(store, "review_decisions")
    real_tables["review_decision_history"] = _safe_read_store_table(store, "review_decision_history")
    real_tables["positions"] = _safe_read_store_table(store, "positions")
    watchlist_snapshot = _load_tracking_snapshot_for_dashboard(store)
    positions = _load_positions_for_dashboard(store)
    real_tables["_watchlist_snapshot"] = watchlist_snapshot
    backtest_result = dict(backtest_diagnostic.get("backtest_result", {}))
    backtest_result["data_quality_notes"] = backtest_diagnostic.get("data_quality_notes", [])
    return {
        "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据",
        "selection": selected,
        "stock_basic": tables["stock_basic"],
        "price": real_tables.get("_dashboard_price_history", tables["daily_price"]),
        "daily_basic": tables["daily_basic"],
        "factor_scores": factor_scores,
        "factor_quality": diagnostic.get("factor_quality", {}),
        "data_quality_notes": diagnostic.get("data_quality_notes", []),
        "backtest": backtest_result,
        "watchlist": _load_watchlist_for_dashboard(store),
        "watchlist_snapshot": watchlist_snapshot,
        "positions": positions,
        "backtest_diagnostic": backtest_diagnostic,
        "batch_diagnostic": batch_diagnostic,
        "tables": real_tables,
    }


def _safe_batch_diagnostic(settings: Any, store: Any) -> dict[str, Any]:
    """Return batch diagnostic metadata for dashboard status, never raising in UI."""
    try:
        from core.jobs.diagnose_update_batch import diagnose_update_batch

        return diagnose_update_batch(settings=settings, store=store)
    except Exception:
        return {}


def _apply_batch_diagnostic_to_tables(tables: dict[str, Any], diagnostic: dict[str, Any]) -> None:
    """Attach batch diagnostic counters to dashboard table metadata."""
    if not diagnostic:
        return
    tables["_configured_symbol_count"] = diagnostic.get("configured_symbol_count", 0)
    tables["_priced_symbol_count"] = diagnostic.get("priced_symbol_count", 0)
    tables["_coverage_rate"] = diagnostic.get("coverage_rate", 0.0)
    tables["_missing_symbol_count"] = len(diagnostic.get("missing_symbols", []))
    tables["_stale_symbol_count"] = diagnostic.get("stale_symbol_count", 0)
    tables["_update_failed_count"] = diagnostic.get("update_failed_count", 0)
    tables["_empty_data_count"] = diagnostic.get("empty_data_count", 0)
    tables["_network_failed_count"] = diagnostic.get("network_failed_count", 0)
    tables["_selection_ready_count"] = diagnostic.get("selection_ready_count", 0)
    tables["_backtest_ready_count"] = diagnostic.get("backtest_ready_count", 0)
    tables["_duckdb_path"] = diagnostic.get("duckdb_path", "")
    tables["_batch_status"] = _full_batch_status_text(diagnostic)
    tables["_bse_filter_note"] = diagnostic.get("bse_filter_note", "")
    for key in [
        "latest_trade_date",
        "latest_price_symbol_count",
        "missing_latest_price_symbol_count",
        "latest_price_coverage_rate",
        "history_complete_symbol_count",
        "history_incomplete_symbol_count",
        "history_missing_symbol_count",
        "available_days_20d_count",
        "available_days_60d_count",
        "available_days_120d_count",
        "available_days_252d_count",
        "factor_ready_symbol_count",
        "elder_ready_symbol_count",
        "entry_zone_ready_symbol_count",
        "lookback_ready_symbol_count",
        "latest_updated_but_history_incomplete_count",
        "latest_updated_but_history_incomplete_examples",
        "history_complete_but_latest_missing_count",
        "history_complete_but_latest_missing_examples",
        "completely_missing_price_count",
        "completely_missing_price_examples",
    ]:
        if key in diagnostic:
            tables[f"_{key}"] = diagnostic[key]


def _full_batch_status_text(diagnostic: dict[str, Any]) -> str:
    """Return a concise full-universe coverage status."""
    configured = int(diagnostic.get("configured_symbol_count", 0) or 0)
    priced = int(diagnostic.get("priced_symbol_count", 0) or 0)
    missing = len(diagnostic.get("missing_symbols", []))
    stale = int(diagnostic.get("stale_symbol_count", 0) or 0)
    if configured and (priced < configured or missing or stale):
        return "全市场数据未完成"
    if configured:
        return "全市场数据已覆盖当前配置"
    return ""


def render_dashboard(data: dict[str, Any] | None = None) -> None:
    """Render the Streamlit dashboard from preloaded or sample local data."""
    import streamlit as st

    dashboard_data = data or load_dashboard_data()
    st.set_page_config(page_title="A 股选股辅助", layout="wide")
    st.title("A 股选股辅助")
    st.caption("仅用于研究与辅助决策，不构成投资建议。")
    data_source_status = describe_dashboard_data_source(dashboard_data)
    st.info(f"数据来源：{data_source_status['data_source']}。{data_source_status['message']}")
    _render_database_status(st, dashboard_data.get("tables", {}).get("_database_status", {}))
    st.caption("日常一键命令：python -m core.jobs.run_daily_workflow --backup-before-run --format all")

    tabs = st.tabs(["今日选股", "个股详情", "因子排名", "选股逻辑", "埃尔德复核", "观察池跟踪", "买入区间分析", "外部模拟持仓导入", "持仓池", "策略回测", "数据更新状态", "本地控制台"])
    with tabs[0]:
        _render_section(st, "今日选股", _render_selection_tab, st, dashboard_data.get("selection", pd.DataFrame()), dashboard_data.get("tables", {}))
    with tabs[1]:
        _render_section(st, "个股详情", _render_stock_detail_tab, st, dashboard_data.get("stock_basic", pd.DataFrame()), dashboard_data.get("price", pd.DataFrame()), dashboard_data.get("factor_scores", pd.DataFrame()))
    with tabs[2]:
        _render_section(st, "因子排名", _render_factor_ranking_tab, st, dashboard_data.get("factor_scores", pd.DataFrame()), dashboard_data.get("daily_basic", pd.DataFrame()))
    with tabs[3]:
        _render_section(st, "选股逻辑", _render_selection_logic_tab, st, dashboard_data.get("selection", pd.DataFrame()))
    with tabs[4]:
        _render_section(st, "埃尔德复核", _render_elder_review_tab, st, dashboard_data.get("selection", pd.DataFrame()), dashboard_data.get("price", pd.DataFrame()))
    with tabs[5]:
        _render_section(st, "观察池跟踪", _render_watchlist_tab, st, dashboard_data.get("watchlist", pd.DataFrame()), dashboard_data.get("watchlist_snapshot", pd.DataFrame()), dashboard_data.get("tables", {}))
    with tabs[6]:
        _render_section(st, "买入区间分析", _render_entry_zone_tab, st, dashboard_data.get("tables", {}))
    with tabs[7]:
        _render_section(st, "外部模拟持仓导入", _render_external_positions_tab, st, dashboard_data.get("tables", {}))
    with tabs[8]:
        _render_section(st, "持仓池", _render_positions_tab, st, dashboard_data.get("positions", pd.DataFrame()))
    with tabs[9]:
        _render_section(st, "策略回测", _render_backtest_tab, st, dashboard_data.get("backtest", {}))
    with tabs[10]:
        _render_section(st, "数据更新状态", _render_status_tab, st, dashboard_data.get("tables", {}))
    with tabs[11]:
        _render_section(st, "本地控制台", _render_local_console_tab, st, dashboard_data.get("tables", {}))


def _render_section(st: Any, title: str, func: Any, *args: Any, **kwargs: Any) -> None:
    """Render one Streamlit section without letting it blank the whole app."""
    try:
        func(*args, **kwargs)
    except Exception as exc:
        st.error(f"{title} 加载失败：{exc}")
        st.info("页面其他区域仍可使用。若涉及 DuckDB 锁，请停止其他 core.jobs 或旧 Streamlit 后重试。")


def _render_database_status(st: Any, status: dict[str, Any]) -> None:
    """Render database accessibility status at the top of the dashboard."""
    if not status:
        return
    message = status.get("message") or ""
    path = status.get("duckdb_path") or "未知"
    state = status.get("status") or "unknown"
    if state == "locked":
        st.error(f"数据库状态：DuckDB 被锁定。{message}")
        st.warning("DuckDB may be locked by macOS FileProvider or cloud sync. Consider moving the database to a non-synced local directory.")
        st.code(f"lsof {path}")
    elif state in {"missing", "error"}:
        st.warning(f"数据库状态：{message} 路径：{path}")
    else:
        st.caption(f"数据库状态：{message} 路径：{path}")


def main() -> None:
    """Run the Streamlit dashboard."""
    render_dashboard()


def _render_selection_tab(st: Any, selection_df: pd.DataFrame, tables: dict[str, Any] | None = None) -> None:
    st.subheader("今日选股")
    if isinstance(tables, dict):
        status = summarize_update_status(tables)
        if status.get("configured_symbol_count", 0) and status.get("priced_symbol_count", 0) < status.get("configured_symbol_count", 0):
            st.info(
                "当前 full 股票池基础数量为 "
                f"{status.get('configured_symbol_count', 0)}，"
                f"可运行选股股票数量为 {status.get('priced_symbol_count', 0)}，"
                "结果仅基于已有行情股票。"
            )
    if selection_df.empty:
        st.info("暂无选股结果。请先运行每日选股任务或导入本地结果。")
        return
    industry = st.selectbox("行业", get_industry_options(selection_df))
    sort_descending = st.checkbox("按综合分从高到低排序", value=True)
    filtered = enrich_with_entry_zone_fields(enrich_selection_with_watchlist_status(filter_selection_data(selection_df, industry, sort_descending), tables or {}), tables or {})
    st.info("序号为当前页面当前排序后的显示顺序；勾选按综合分排序时，显示顺序按 total_score 调整，不改变系统内部选股结果。")
    display_dataframe(st, filtered)
    st.write("候选股票详情")
    for order, item in enumerate(filtered.head(10).to_dict("records"), start=1):
        title = f"{order}. {item.get('ts_code')} {item.get('name')}"
        with st.expander(title):
            st.write(
                {
                    "trend_score": item.get("trend_score"),
                    "momentum_score": item.get("momentum_score"),
                    "liquidity_score": item.get("liquidity_score"),
                    "fundamental_score": item.get("fundamental_score"),
                    "volatility_score": item.get("volatility_score"),
                    "total_score": item.get("total_score"),
                    "industry": item.get("industry"),
                    "list_date": item.get("list_date"),
                    "pe": item.get("pe"),
                    "pb": item.get("pb"),
                    "select_reason": item.get("select_reason"),
                    "risk_note": item.get("risk_note"),
                    "entry_zone": f"{item.get('entry_low') or ''}-{item.get('entry_high') or ''}",
                    "stop_loss": item.get("stop_loss"),
                    "target_price": item.get("target_price"),
                    "reward_risk_ratio": item.get("reward_risk_ratio"),
                    "chase_risk": item.get("chase_risk_cn"),
                    "entry_zone_status": item.get("entry_zone_status_cn"),
                    "data_quality_note": item.get("risk_note") or "需结合数据来源与字段完整性人工复核。",
                }
            )
            st.write("人工复核要点")
            for checklist_item in REVIEW_CHECKLIST:
                st.write(f"- {checklist_item}")
    st.download_button("导出 CSV", dataframe_to_csv(filtered), file_name="selection.csv", mime="text/csv")


def _render_review_tab(st: Any, selection_df: pd.DataFrame, tables: dict[str, Any]) -> None:
    st.subheader("候选复核")
    report = tables.get("_latest_selection_review_report")
    template = tables.get("_latest_review_template")
    if report:
        st.write("最近 selection_review 报告")
        st.write(report)
    else:
        st.info("暂无 selection_review 报告，可运行 python -m core.jobs.export_selection_review。")
    if template:
        st.write("最近人工复核模板")
        st.write(template)
    else:
        st.info("暂无人工复核模板，可运行 python -m core.jobs.export_review_template。")
    if selection_df.empty:
        st.info("暂无候选股票。")
        if tables and "本地 DuckDB 真实数据" in str(tables.get("_data_source", "")):
            latest_daily_report = tables.get("_latest_daily_workflow_report")
            if isinstance(latest_daily_report, dict) and latest_daily_report.get("top_candidates"):
                st.warning("报告中存在候选结果，但尚未写入 DuckDB，请重新运行日常工作流或执行修复命令。")
            else:
                st.warning("行情数据存在，但尚未生成本地因子和选股结果，请运行 python -m core.jobs.run_daily_workflow --skip-update。")
        return
    st.write("候选股票")
    display_dataframe(st, filter_selection_data(selection_df).head(20))
    st.write("人工复核模板导出后，可填写 decision、reason、notes、reviewer，再用 import_review_decisions 回填本地 DuckDB。")


def _render_watchlist_tab(st: Any, watchlist_df: pd.DataFrame, snapshot_df: pd.DataFrame | None = None, tables: dict[str, Any] | None = None) -> None:
    st.subheader("观察池跟踪")
    snapshot = snapshot_df if isinstance(snapshot_df, pd.DataFrame) else pd.DataFrame()
    if watchlist_df.empty and snapshot.empty:
        st.info("暂无 active watch 股票。人工复核导入 watch 决策后会显示在这里。")
        return
    st.caption("刷新观察池：python -m core.jobs.refresh_watchlist_from_selection；每日跟踪：python -m core.jobs.track_watchlist")
    if not snapshot.empty:
        counts = summarize_watchlist_snapshot(snapshot)
        cols = st.columns(7)
        metrics = [
            ("总观察", counts.get("total", 0)),
            ("今日新入选", counts.get("new_candidate", 0)),
            ("重点观察", counts.get("strong_watch", 0)),
            ("等待回调", counts.get("wait_pullback", 0)),
            ("短线过热", counts.get("overheated", 0)),
            ("走势转弱", counts.get("weakening", 0)),
            ("建议复核", counts.get("invalidated", 0)),
        ]
        for col, (label, value) in zip(cols, metrics):
            col.metric(label, value)
        st.write("观察池每日跟踪")
        snapshot = enrich_with_entry_zone_fields(snapshot, tables or {})
        snapshot_columns = [
            "ts_code",
            "name",
            "trade_date",
            "current_close",
            "today_rank",
            "rank_change",
            "total_score",
            "total_score_change",
            "selected_count_5d",
            "selected_count_10d",
            "consecutive_selected_days",
            "action_hint",
            "entry_low",
            "entry_high",
            "stop_loss",
            "target_price",
            "reward_risk_ratio",
            "chase_risk_cn",
            "entry_zone_status_cn",
            "watch_status_label",
            "daily_note",
        ]
        display_dataframe(st, snapshot, columns=snapshot_columns)
        return

    st.caption("暂无每日跟踪快照，先运行 python -m core.jobs.track_watchlist。")
    watchlist_df = enrich_with_entry_zone_fields(watchlist_df, tables or {})
    display_columns = [
        "ts_code",
        "name",
        "decision",
        "reason",
        "notes",
        "latest_trade_date",
        "latest_close",
        "industry",
        "market",
        "list_date",
        "pe",
        "pb",
        "fundamental_score",
        "total_score",
        "score_missing_reason",
        "data_quality_note",
        "entry_low",
        "entry_high",
        "stop_loss",
        "target_price",
        "reward_risk_ratio",
        "chase_risk_cn",
        "entry_zone_status_cn",
    ]
    display_dataframe(st, watchlist_df, columns=display_columns)


def _render_entry_zone_tab(st: Any, tables: dict[str, Any]) -> None:
    st.subheader("买入区间分析")
    st.caption("仅供个人研究使用，不自动交易。")
    entry_zones = _latest_entry_zone_snapshot(tables.get("entry_zone_snapshots", pd.DataFrame()))
    if entry_zones.empty:
        st.info("暂无买入区间快照。请运行 python -m core.jobs.calculate_entry_zones。")
        return
    counts = entry_zones["entry_zone_status"].fillna("unknown").value_counts().to_dict() if "entry_zone_status" in entry_zones.columns else {}
    cols = st.columns(6)
    metrics = [
        ("股票数量", len(entry_zones)),
        ("位于区间", counts.get("in_zone", 0)),
        ("接近区间", counts.get("near_zone", 0)),
        ("等待回调", counts.get("above_zone", 0)),
        ("趋势偏弱", counts.get("weak_no_entry", 0)),
        ("数据不足", counts.get("insufficient_data", 0)),
    ]
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)
    display_columns = [
        "ts_code",
        "name",
        "trade_date",
        "source",
        "close",
        "entry_low",
        "entry_high",
        "stop_loss",
        "target_price",
        "reward_risk_ratio",
        "chase_risk_cn",
        "entry_zone_status_cn",
        "price_action_note",
    ]
    display_dataframe(st, entry_zones, columns=display_columns)
    st.caption("生成报告：python -m core.jobs.export_entry_zone_report --format all")


def parse_external_position_text(text: str) -> pd.DataFrame:
    """Parse pasted CSV or TSV text for preview only."""
    if not text.strip():
        return pd.DataFrame()
    separator = "\t" if "\t" in text.splitlines()[0] else ","
    return pd.read_csv(StringIO(text), sep=separator, dtype=str, keep_default_na=False)


def latest_external_positions(tables: dict[str, Any]) -> pd.DataFrame:
    """Return latest imported external position snapshots."""
    positions = tables.get("external_position_snapshots", pd.DataFrame())
    if not isinstance(positions, pd.DataFrame) or positions.empty or "snapshot_date" not in positions.columns:
        return pd.DataFrame()
    latest = positions["snapshot_date"].dropna().astype(str).max()
    return positions[positions["snapshot_date"].astype(str) == str(latest)].copy()


def _render_external_positions_tab(st: Any, tables: dict[str, Any]) -> None:
    st.subheader("外部模拟持仓导入")
    st.caption("仅供个人研究使用，不自动交易。不会读取同花顺、雪球 cookie 或登录态。")
    trade_csv = dataframe_to_csv(trade_template_frame())
    position_csv = dataframe_to_csv(position_template_frame())
    cols = st.columns(2)
    cols[0].download_button("下载交易记录模板", trade_csv, file_name="external_trades_template.csv", mime="text/csv")
    cols[1].download_button("下载持仓快照模板", position_csv, file_name="external_position_snapshots_template.csv", mime="text/csv")
    st.write("命令行导入")
    st.code(
        "python -m core.jobs.import_external_trades --file path/to/external_trades.csv\n"
        "python -m core.jobs.import_external_positions --file path/to/external_position_snapshots.csv\n"
        "python -m core.jobs.match_external_positions\n"
        "python -m core.jobs.export_external_position_report --format all"
    )
    uploaded = st.file_uploader("上传 CSV 预览（页面仅预览，正式导入请用命令）", type=["csv"])
    if uploaded is not None:
        preview = pd.read_csv(uploaded, dtype=str, keep_default_na=False)
        st.write("上传预览")
        display_dataframe(st, preview.head(20))
    pasted = st.text_area("粘贴 CSV 或制表符分隔内容预览", height=120)
    if pasted.strip():
        try:
            parsed = parse_external_position_text(pasted)
            st.write("粘贴内容预览")
            display_dataframe(st, parsed.head(20))
        except Exception as exc:
            st.warning(f"解析失败：{exc}")
    positions = latest_external_positions(tables)
    if positions.empty:
        st.info("暂无外部模拟持仓快照。")
        return
    st.write("最新外部模拟持仓匹配结果")
    display_columns = [
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
        "entry_low",
        "entry_high",
        "stop_loss",
        "target_price",
        "reward_risk_ratio",
        "risk_status_cn",
        "match_note",
    ]
    display_dataframe(st, positions, columns=display_columns)


def _render_stock_detail_tab(
    st: Any,
    stock_basic: pd.DataFrame,
    price_df: pd.DataFrame,
    factor_df: pd.DataFrame,
) -> None:
    st.subheader("个股详情")
    ts_code = st.text_input("股票代码", value="")
    if not ts_code:
        st.info("请输入股票代码查看详情。")
        return
    basic = stock_basic[stock_basic["ts_code"] == ts_code] if "ts_code" in stock_basic.columns else pd.DataFrame()
    if basic.empty:
        st.info("暂无该股票基础信息。")
    else:
        display_dataframe(st, basic)
    price = price_df[price_df["ts_code"] == ts_code].sort_values("trade_date") if "ts_code" in price_df.columns else pd.DataFrame()
    if price.empty:
        st.info("暂无该股票行情数据。")
        return
    returns = calculate_recent_returns(price_df, ts_code)
    col1, col2 = st.columns(2)
    col1.metric("近 20 日涨跌幅", _format_percent(returns["return_20d"]))
    col2.metric("近 60 日涨跌幅", _format_percent(returns["return_60d"]))
    st.line_chart(price.set_index("trade_date")[["close"]])
    for column in ["amount", "turnover_rate"]:
        if column in price.columns:
            st.line_chart(price.set_index("trade_date")[[column]])
    factors = factor_df[factor_df["ts_code"] == ts_code] if "ts_code" in factor_df.columns else pd.DataFrame()
    if not factors.empty:
        display_dataframe(st, factors, columns=[column for column in FACTOR_SCORE_COLUMNS if column in factors.columns])
        latest_factor = factors.sort_values("trade_date").iloc[-1].to_dict() if "trade_date" in factors.columns else factors.iloc[-1].to_dict()
        latest_factor.setdefault("ts_code", ts_code)
        if not basic.empty:
            latest_factor.setdefault("name", basic.iloc[-1].get("name"))
            latest_factor.setdefault("industry", basic.iloc[-1].get("industry"))
        elder = build_elder_review(pd.DataFrame([latest_factor]), price_df)
        if not elder.empty:
            st.write("最近一次埃尔德复核")
            elder_columns = [
                "elder_score",
                "review_action",
                "action_hint",
                "elder_reason",
                "weekly_trend",
                "daily_pullback",
                "force_signal",
                "elder_ray_signal",
            ]
            display_dataframe(st, elder, columns=[column for column in elder_columns if column in elder.columns])


def _render_factor_ranking_tab(st: Any, factor_df: pd.DataFrame, daily_basic: pd.DataFrame | None = None) -> None:
    st.subheader("因子排名")
    if factor_df.empty:
        st.info("暂无因子评分数据。")
        return
    basic_quality = summarize_basic_data_quality(
        pd.DataFrame(),
        daily_basic if isinstance(daily_basic, pd.DataFrame) else pd.DataFrame(),
    )
    valuation_quality = basic_quality.get("daily_basic", {})
    if valuation_quality:
        st.write("估值字段完整率")
        display_dataframe(
            st,
            pd.DataFrame(
                [
                    {"field": field, "non_null_rate": stats["non_null_rate"], "missing_count": stats["missing_count"]}
                    for field, stats in valuation_quality.items()
                ]
            ),
        )
    missing = summarize_factor_missing(factor_df)
    if missing:
        st.write("因子非空率")
        display_dataframe(
            st,
            pd.DataFrame(
                [
                    {
                        "factor": factor,
                        "non_null_rate": stats["non_null_rate"],
                        "nan_count": stats["nan_count"],
                    }
                    for factor, stats in missing.items()
                ]
            ),
        )
    dates = sorted(factor_df["trade_date"].astype(str).unique()) if "trade_date" in factor_df.columns else []
    trade_date = st.selectbox("交易日期", dates) if dates else None
    industry = st.selectbox("行业筛选", get_industry_options(factor_df), key="factor_industry")
    factor_col = st.selectbox("因子", [column for column in FACTOR_SCORE_COLUMNS if column in factor_df.columns])
    ranking = filter_factor_ranking(factor_df, trade_date, industry, factor_col)
    display_dataframe(st, ranking)


def _render_selection_logic_tab(st: Any, selection_df: pd.DataFrame) -> None:
    st.subheader("选股逻辑")
    _render_core_logic_guide_download(st)
    summary = get_selection_logic_summary()
    st.write("综合评分公式")
    st.code(summary.formula_summary)
    st.write("因子说明")
    display_dataframe(
        st,
        pd.DataFrame(
            [
                {
                    "因子": item.display_name,
                    "字段": item.factor_name,
                    "权重": item.weight,
                    "说明": item.meaning,
                    "主要输入": item.input_fields,
                }
                for item in summary.factor_definitions
            ]
        ),
    )
    st.write("流程说明")
    for step in summary.workflow_steps:
        st.write(f"- {step}")
    st.write("主要贡献因子 / 排名原因")
    explanations = explain_candidates(selection_df, top_n=10)
    if explanations:
        display_dataframe(st, explanations_to_dataframe(explanations))
        for item in explanations[:5]:
            with st.expander(f"{item.rank or '-'} {item.ts_code} {item.name or ''}"):
                st.write(
                    {
                        "total_score": item.total_score,
                        "factor_contributions": item.factor_contributions,
                        "top_reasons": item.top_reasons,
                        "weak_points": item.weak_points,
                        "data_quality_note": item.data_quality_note,
                        "logic_version": item.logic_version,
                    }
                )
    else:
        st.info("暂无候选股票解释。请先运行每日选股或导出候选复核报告。")
    st.write("当前限制")
    for item in summary.limitations:
        st.write(f"- {item}")
    st.caption("个人研究工具，结果需自行复核。")


def _render_core_logic_guide_download(st: Any) -> None:
    """Render a static download entry for the user-facing core logic guide."""
    st.write("核心说明文件")
    if not CORE_LOGIC_GUIDE_PATH.exists():
        st.warning("核心逻辑说明文件不存在，请先运行项目检查或联系开发者。")
        return
    st.download_button(
        "下载核心逻辑说明",
        data=CORE_LOGIC_GUIDE_PATH.read_bytes(),
        file_name=CORE_LOGIC_GUIDE_DOWNLOAD_NAME,
        mime="text/markdown",
        width="stretch",
    )


def _render_elder_review_tab(st: Any, selection_df: pd.DataFrame, price_df: pd.DataFrame) -> None:
    st.subheader("埃尔德复核")
    st.caption("二次技术状态 / 节奏复核层，不覆盖 total_score，不改变今日选股原始排序，也不代表买入优先级。")
    review_df = build_elder_review(selection_df, price_df)
    if review_df.empty:
        st.info("暂无埃尔德复核结果。请先运行每日选股并确保本地 daily_price 有足够行情。")
        return
    display_df = format_elder_review_display(review_df, source="今日候选")
    st.info("埃尔德复核为二次技术状态判断，不改变 total_score 和系统内部选股结果。序号为当前页面显示顺序；来源用于区分今日候选、观察池或持仓池。")
    display_columns = [
        "display_order",
        "source",
        "ts_code",
        "name",
        "industry",
        "total_score",
        "elder_score",
        "review_action",
        "action_hint",
        "elder_reason",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
        "ema13",
        "ema22",
        "macd_histogram",
        "macd_histogram_slope",
        "force_index_2d",
        "force_index_13d",
        "bull_power",
        "bear_power",
        "close_to_ema13_pct",
        "close_to_ema22_pct",
    ]
    display_dataframe(st, display_df, columns=display_columns)
    st.write("状态分布")
    display_dataframe(st, review_df["action_hint"].value_counts(dropna=False).rename_axis("action_hint").reset_index(name="count"))
    st.info("操作建议只用于人工复核流程，不改变今日选股 total_score 排序；“短线过热，不追”表示短期回撤风险偏高，不等于中期趋势一定转弱。批量导出可运行 python -m core.jobs.export_elder_review。")
    st.caption("命令行：python -m core.jobs.run_elder_review 或 python -m core.jobs.export_elder_review --format markdown")


def format_elder_review_display(review_df: pd.DataFrame, *, source: str = "今日候选") -> pd.DataFrame:
    """Return an Elder review display table with unambiguous ordering fields."""
    if review_df.empty:
        return review_df.copy()
    result = review_df.copy().reset_index(drop=True)
    result["source"] = source
    if "rank" in result.columns:
        result["candidate_rank"] = result["rank"]
    elif "candidate_rank" not in result.columns:
        result["candidate_rank"] = pd.NA
    sort_columns: list[str] = []
    ascending: list[bool] = []
    if "source" in result.columns:
        result["_source_order"] = result["source"].map({"今日候选": 0, "观察池": 1, "持仓池": 2}).fillna(9)
        sort_columns.append("_source_order")
        ascending.append(True)
    if "candidate_rank" in result.columns:
        result["_candidate_rank_sort"] = pd.to_numeric(result["candidate_rank"], errors="coerce")
        sort_columns.append("_candidate_rank_sort")
        ascending.append(True)
    elif "total_score" in result.columns:
        sort_columns.append("total_score")
        ascending.append(False)
    if sort_columns:
        result = result.sort_values(sort_columns, ascending=ascending, na_position="last")
    result = result.reset_index(drop=True)
    result["display_order"] = range(1, len(result) + 1)
    return result.drop(columns=[column for column in ["_source_order", "_candidate_rank_sort"] if column in result.columns])


def _render_positions_tab(st: Any, positions_df: pd.DataFrame) -> None:
    st.subheader("持仓池")
    st.caption("用于手工记录已实际持有的股票；仅做本地持仓记录和基础展示，不自动交易。")
    st.write("手工录入字段")
    st.text_input("股票代码", value="", key="position_ts_code")
    st.text_input("股票名称", value="", key="position_name")
    st.text_input("买入日期", value="", key="position_entry_date")
    st.number_input("买入价", min_value=0.0, value=0.0, step=0.01, key="position_entry_price")
    st.number_input("数量（可选）", min_value=0.0, value=0.0, step=100.0, key="position_quantity")
    st.selectbox("来源", ["manual", "selection", "watchlist", "elder_review"], key="position_source")
    st.text_area("买入理由 / 复核记录", value="", key="position_entry_reason")
    st.text_area("计划（可选）", value="", key="position_plan")
    st.info("页面第一版只展示录入入口和本地持仓池。批量导入请使用 docs/templates/positions_import_template.csv 与 python -m core.jobs.import_positions --file <csv>。")
    if positions_df.empty:
        st.info("暂无持仓记录。可通过导入模板或命令行创建本地持仓记录。")
        return
    display_columns = [
        "ts_code",
        "name",
        "entry_date",
        "entry_price",
        "latest_close",
        "pnl_pct",
        "holding_days",
        "max_gain_pct",
        "max_drawdown_pct",
        "latest_elder_score",
        "technical_state",
        "position_hint",
        "position_reason",
        "source",
        "entry_reason",
        "status",
        "data_quality_note",
    ]
    display_dataframe(st, positions_df, columns=display_columns)
    st.caption("导出：python -m core.jobs.export_positions 或 python -m core.jobs.export_positions --format markdown")


def _render_backtest_tab(st: Any, backtest: dict[str, Any]) -> None:
    st.subheader("策略回测")
    _render_lookback_analysis_section(st)
    st.divider()
    st.write("传统回测诊断")
    if not backtest:
        st.caption("传统回测诊断暂未生成；上方自动回看分析可用于查看历史样本表现。")
        return
    if backtest.get("data_quality_notes"):
        for note in backtest["data_quality_notes"]:
            st.info(note)
    st.write({"调仓频率": "W", "持仓数量": 20, "初始资金": 1_000_000})
    cols = st.columns(5)
    for col, key in zip(cols, ["annual_return", "max_drawdown", "sharpe_ratio", "win_rate", "turnover"]):
        col.metric(key, backtest.get(key, 0))
    equity_curve = backtest.get("equity_curve", pd.DataFrame())
    if not equity_curve.empty and {"trade_date", "equity"}.issubset(equity_curve.columns):
        st.line_chart(equity_curve.set_index("trade_date")[["equity"]])
    st.write("年度收益")
    st.json(backtest.get("yearly_returns", {}))
    st.write("交易记录")
    display_dataframe(st, backtest.get("trade_records", pd.DataFrame()))
    st.write("持仓记录")
    display_dataframe(st, backtest.get("position_records", pd.DataFrame()))


def _render_status_tab(st: Any, tables: dict[str, pd.DataFrame]) -> None:
    st.subheader("数据更新状态")
    st.info("本页用于补充 / 更新 full 股票池行情数据；当前主视图只展示统一数据质量快照和更新入口。页面启动不会自动联网、写库或生成 Excel。")
    legacy_status = summarize_update_status(tables)
    scheduled = read_scheduled_status(DEFAULT_STATUS_PATH)
    snapshot = _status_page_quality_snapshot(tables, scheduled, legacy_status)
    status = {**legacy_status, **snapshot}

    _render_status_quality_main(st, scheduled, status)
    _render_status_buttons(st)
    _render_full_batch_update_section(st, status)
    _render_status_advanced_sections(st, tables, scheduled, legacy_status)


def _status_page_quality_snapshot(tables: dict[str, pd.DataFrame], scheduled: dict[str, Any], legacy_status: dict[str, Any]) -> dict[str, Any]:
    """Return the authoritative quality snapshot for the status page."""
    if scheduled.get("data_quality_snapshot_source") and scheduled.get("latest_daily_price_symbol_count") is not None:
        return dict(scheduled)
    db_path = str(tables.get("_duckdb_path") or legacy_status.get("duckdb_path") or "")
    target_date = str(
        scheduled.get("latest_completed_trade_date")
        or scheduled.get("research_trade_date")
        or legacy_status.get("latest_trade_date")
        or legacy_status.get("latest_price_date")
        or ""
    )
    if db_path and target_date:
        try:
            return build_data_quality_snapshot(
                db_path=db_path,
                research_trade_date=target_date,
                latest_completed_trade_date=target_date,
            )
        except Exception:
            pass
    return {
        "data_quality_status": "unknown",
        "formal_result_usable": False,
        "formal_result_warning_reason": "当前缺少数据质量快照，请运行刷新数据状态或检查 DuckDB。",
        "configured_symbol_count": int(legacy_status.get("configured_symbol_count", 0) or 0),
        "research_trade_date": target_date,
        "latest_completed_trade_date": target_date,
    }


def _render_status_quality_main(st: Any, scheduled: dict[str, Any], status: dict[str, Any]) -> None:
    """Render only the default data-quality dashboard sections."""
    quality_status = status.get("data_quality_status") or "unknown"
    if quality_status in {"poor", "failed", "unknown"}:
        st.error("流程完成不等于数据完整；当前结果不可作为正式全市场研究结果。")
    elif quality_status == "warning":
        st.warning("数据基本可用但仍有缺口，请结合覆盖率人工复核。")
    else:
        st.success("最新交易日数据覆盖满足正式研究使用口径。")
    st.write("顶部结论卡片")
    display_dataframe(st, pd.DataFrame([_status_conclusion_row(scheduled, status)]))
    st.write("最新交易日覆盖")
    display_dataframe(st, _status_latest_coverage_frame(status))
    st.write("历史数据完整度")
    display_dataframe(st, _status_history_frame(status))
    st.info("任意历史行情覆盖不等于最新交易日覆盖；历史完整按 252 日窗口统计。")
    st.write("模块可用性")
    display_dataframe(st, _status_module_frame(status))
    st.write("本次运行结果")
    display_dataframe(st, pd.DataFrame([_status_run_result_row(scheduled)]))


def _status_conclusion_row(scheduled: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    return {
        "流程状态": scheduled.get("status") or "暂无",
        "当前阶段": scheduled.get("stage") or "暂无",
        "研究交易日": status.get("latest_completed_trade_date") or status.get("research_trade_date") or scheduled.get("research_trade_date") or "暂无",
        "数据质量": status.get("data_quality_status") or "unknown",
        "正式全市场研究结果可用": "是" if status.get("formal_result_usable") is True else "否",
        "主要提示": status.get("formal_result_warning_reason") or scheduled.get("failure_reason") or "暂无",
    }


def _status_latest_coverage_frame(status: dict[str, Any]) -> pd.DataFrame:
    total = int(status.get("configured_symbol_count", 0) or 0)
    rows = []
    for label, count_key, missing_key, rate_key in [
        ("daily_price", "latest_daily_price_symbol_count", "missing_latest_daily_price_symbol_count", "latest_daily_price_coverage_rate"),
        ("daily_basic", "latest_daily_basic_symbol_count", "missing_latest_daily_basic_symbol_count", "latest_daily_basic_coverage_rate"),
        ("adj_factor", "latest_adj_factor_symbol_count", "missing_latest_adj_factor_symbol_count", "latest_adj_factor_coverage_rate"),
        ("全部必需表", "latest_all_required_tables_symbol_count", "missing_latest_all_required_tables_symbol_count", "latest_all_required_tables_coverage_rate"),
    ]:
        count = int(status.get(count_key, 0) or 0)
        rate = float(status.get(rate_key, 0.0) or 0.0)
        rows.append({"表名": label, "已覆盖": f"{count} / {total}", "缺失": int(status.get(missing_key, max(total - count, 0)) or 0), "覆盖率": f"{rate:.2%}"})
    return pd.DataFrame(rows)


def _status_history_frame(status: dict[str, Any]) -> pd.DataFrame:
    total = int(status.get("configured_symbol_count", 0) or 0)
    any_count = int(status.get("any_daily_price_symbol_count", 0) or 0)
    any_rate = float(status.get("any_daily_price_coverage_rate", 0.0) or 0.0)
    return pd.DataFrame(
        [
            {"指标": "任意历史行情覆盖", "数量": f"{any_count} / {total}", "说明": f"{any_rate:.2%}，数据库任意日期出现过行情"},
            {"指标": "完全缺行情", "数量": int(status.get("history_missing_symbol_count", 0) or 0), "说明": "配置股票池中从未有 daily_price 的股票"},
            {"指标": "历史完整", "数量": int(status.get("history_complete_symbol_count", 0) or 0), "说明": "本地行情行数达到 252 日口径"},
            {"指标": "历史不足", "数量": int(status.get("history_incomplete_symbol_count", 0) or 0), "说明": "有行情但不足 252 日"},
            {"指标": "20 日可用", "数量": int(status.get("available_days_20d_count", 0) or 0), "说明": "可支撑短期观察"},
            {"指标": "60 日可用", "数量": int(status.get("available_days_60d_count", 0) or 0), "说明": "可支撑买入区间 / 埃尔德基础判断"},
            {"指标": "120 日可用", "数量": int(status.get("available_days_120d_count", 0) or 0), "说明": "可支撑较长周期观察"},
            {"指标": "252 日可用", "数量": int(status.get("available_days_252d_count", 0) or 0), "说明": "可支撑一年窗口观察"},
        ]
    )


def _status_module_frame(status: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"模块": "综合分", "可用股票数量": int(status.get("factor_ready_symbol_count", 0) or 0), "说明": "最新交易日 factor_scores 可用"},
            {"模块": "埃尔德复核", "可用股票数量": int(status.get("elder_ready_symbol_count", 0) or 0), "说明": "最新观察池 / 复核快照可用"},
            {"模块": "买入区间", "可用股票数量": int(status.get("entry_zone_ready_symbol_count", 0) or 0), "说明": "买入区间快照可用"},
            {"模块": "自动回看", "可用股票数量": int(status.get("lookback_ready_symbol_count", 0) or 0), "说明": "候选且历史样本足够"},
        ]
    )


def _status_run_result_row(scheduled: dict[str, Any]) -> dict[str, Any]:
    return {
        "update_mode": scheduled.get("update_mode") or "暂无",
        "started_at": scheduled.get("started_at") or "暂无",
        "finished_at": scheduled.get("finished_at") or "暂无",
        "processed_symbol_count": scheduled.get("processed_symbol_count", 0),
        "total_symbol_count": scheduled.get("total_symbol_count", 0),
        "update_failed_symbol_count": scheduled.get("update_failed_symbol_count", 0),
        "empty_data_symbol_count": scheduled.get("empty_data_symbol_count", 0),
        "network_timeout_count": scheduled.get("network_timeout_count", 0),
        "workbook_path": scheduled.get("workbook_path") or "暂无",
    }


def _render_status_buttons(st: Any) -> None:
    st.write("按钮区")
    st.markdown("**1. 只读状态 / 诊断**")
    st.caption("不联网；不写 DuckDB；不生成 Excel；不改变今日研究结果。")
    col1, col2, col3 = st.columns(3)
    if col1.button("刷新页面数据质量", key="refresh_data_quality_status_button"):
        _run_streaming_console_action(st, "刷新页面数据质量", "refresh_data_quality_status", ["--format", "text"], success_message="数据质量状态刷新完成。请刷新页面查看最新结果。")
    if col2.button("运行数据质量诊断", key="run_real_data_diagnostic"):
        _run_streaming_console_action(st, "运行数据质量诊断", "diagnose_real_data", [], success_message="数据质量诊断完成。")
    if col3.button("运行批量更新诊断", key="run_update_batch_diagnostic"):
        _run_streaming_console_action(st, "运行批量更新诊断", "diagnose_update_batch", [], success_message="批量更新诊断完成。")
    st.markdown("**2. daily_incremental：补跑每日自动更新**")
    st.caption("会联网；会写 DuckDB；会生成每日研究 Excel；会更新今日研究结果。")
    if st.button("手动补跑 18:00 自动更新", key="scheduled_daily_update_manual_catchup"):
        _run_streaming_console_action(st, "手动补跑 18:00 自动更新", "run_scheduled_daily_update", ["--force", "--format", "text"], success_message="自动更新补跑命令执行完成。请刷新页面查看最新状态。")


def _render_status_advanced_sections(st: Any, tables: dict[str, pd.DataFrame], scheduled: dict[str, Any], status: dict[str, Any]) -> None:
    with st.expander("高级：原始自动更新状态 JSON", expanded=False):
        if scheduled:
            st.json(scheduled)
        else:
            st.info("暂无自动更新状态 JSON。")
    with st.expander("高级：旧版诊断信息", expanded=False):
        st.write({"是否 sample 数据": status.get("is_sample_data"), "是否真实数据": status.get("is_real_data"), "字段缺失": status.get("field_missing", {})})
        display_dataframe(st, pd.DataFrame(status.get("table_rows", {}).items(), columns=["table", "rows"]))
    with st.expander("高级：最近报告文件", expanded=False):
        for label, key in [
            ("workflow", "latest_workflow_report"),
            ("daily_workflow", "latest_daily_workflow_report"),
            ("selection_review", "latest_selection_review_report"),
            ("watchlist", "latest_watchlist_report"),
            ("watchlist_tracking", "latest_watchlist_tracking_report"),
        ]:
            st.write({label: status.get(key) or "暂无"})
    with st.expander("高级：观察池明细", expanded=False):
        watchlist_df = _watchlist_from_tables(tables)
        if watchlist_df.empty:
            st.info("暂无观察池明细。")
        else:
            display_dataframe(st, watchlist_df)
    with st.expander("高级：本地数据库和备份", expanded=False):
        local_state = status.get("local_state")
        st.write(local_state if isinstance(local_state, dict) and local_state else "暂无本地状态 / 备份信息。")


def _render_scheduled_update_section(st: Any) -> None:
    """Render scheduled daily update status and download controls."""
    st.subheader("自动更新状态")
    scheduled = read_scheduled_status(DEFAULT_STATUS_PATH)
    if not scheduled:
        st.info("尚无自动更新记录。")
    else:
        st.write(
            {
                "最近一次状态": scheduled.get("status"),
                "计划时间": scheduled.get("scheduled_time"),
                "实际开始时间": scheduled.get("started_at"),
                "完成时间": scheduled.get("finished_at") or "暂无",
                "是否补跑": scheduled.get("catch_up"),
                "交易日期": scheduled.get("trade_date"),
                "数据源诊断状态": scheduled.get("diagnosis_status") or "暂无",
                "今日候选数量": scheduled.get("candidate_count", 0),
                "埃尔德复核数量": scheduled.get("elder_review_count", 0),
                "买入区间数量": scheduled.get("entry_zone_count", 0),
                "观察池数量": scheduled.get("watchlist_count", 0),
                "Excel 文件路径": scheduled.get("workbook_path") or "暂无",
                "邮件通知状态": (scheduled.get("notification") or {}).get("email_status", "disabled"),
                "失败原因": scheduled.get("failure_reason") or "暂无",
                "建议操作": scheduled.get("suggested_action") or "暂无",
            }
        )
        workbook_path = Path(str(scheduled.get("workbook_path") or ""))
        if scheduled.get("workbook_path") and workbook_path.exists():
            with workbook_path.open("rb") as handle:
                st.download_button(
                    "下载最新自动更新 Excel",
                    data=handle.read(),
                    file_name=workbook_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_scheduled_daily_workbook",
                    width="stretch",
                )
        elif scheduled.get("workbook_path"):
            st.warning("最新自动更新 Excel 文件不存在，可能已被清理，请重新运行自动更新。")
    st.caption("页面启动不会自动执行自动更新；手动补跑会先做数据源预检，失败时不会启动重型更新。")
    if st.button("手动补跑一次自动更新", key="legacy_scheduled_daily_update_manual_catchup"):
        _run_streaming_console_action(
            st,
            "手动补跑一次自动更新",
            "run_scheduled_daily_update",
            ["--force", "--format", "text"],
            success_message="自动更新补跑命令执行完成。请刷新页面查看最新状态。",
        )


def _render_lookback_analysis_section(st: Any) -> None:
    """Render automatic lookback analysis status and controls."""
    st.subheader("自动回看分析")
    st.write("自动回看状态摘要")
    status = _read_lookback_status()
    if not status:
        st.info("尚无自动回看记录。可以点击运行自动回看分析生成结果。")
    else:
        st.write(
            {
                "最近一次状态": status.get("status"),
                "回看截止交易日": status.get("as_of_trade_date") or "暂无",
                "样本区间": f"{status.get('start_date') or '暂无'} - {status.get('end_date') or '暂无'}",
                "回看周期": ",".join(str(item) for item in status.get("horizons", [])) if isinstance(status.get("horizons"), list) else status.get("horizons"),
                "候选样本数量": status.get("candidate_sample_count", 0),
                "有效样本数量": status.get("valid_sample_count", 0),
                "数据不足数量": status.get("insufficient_forward_data_count", 0),
                "主要发现": status.get("key_findings") or "暂无",
                "数据质量提示": status.get("data_quality_summary") or "暂无",
                "报告路径": status.get("generated_report_path") or "暂无",
            }
        )
        report_path = Path(str(status.get("generated_report_path") or ""))
        if status.get("generated_report_path") and report_path.exists():
            with report_path.open("rb") as handle:
                st.download_button(
                    "下载最新回看报告",
                    data=handle.read(),
                    file_name=report_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_latest_lookback_report",
                    width="stretch",
                )
        elif status.get("generated_report_path"):
            st.warning("最新回看报告文件不存在，可能已被清理。")
    st.caption("回看分析只验证历史样本表现，不改变 total_score、因子权重或今日候选排序。")
    col1, col2 = st.columns(2)
    if col1.button("运行自动回看分析", key="run_lookback_analysis_button"):
        _run_streaming_console_action(
            st,
            "运行自动回看分析",
            "run_lookback_analysis",
            ["--as-of", "latest", "--horizons", "1,3,5,10,20", "--format", "text"],
            success_message="自动回看分析完成。请刷新页面查看最新状态。",
        )
    if col2.button("刷新回看状态", key="refresh_lookback_status_button"):
        st.info("已读取本地状态文件；如未变化，请点击页面右上角刷新。")


def _read_lookback_status() -> dict[str, Any] | None:
    """Read latest lookback analysis status JSON for display."""
    if not LOOKBACK_STATUS_PATH.exists():
        return None
    try:
        payload = json.loads(LOOKBACK_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "failed", "summary": "自动回看状态文件不可读。"}
    return payload if isinstance(payload, dict) else None


def _render_full_batch_update_section(st: Any, status: dict[str, Any]) -> None:
    """Render page controls for bounded full-universe batch updates."""
    st.subheader("全市场批量补数据")
    st.caption("会联网；补数据按钮会写 DuckDB；不生成 Excel；不会直接重算今日研究结果，需后续本地重算或每日自动更新。")
    display_dataframe(st, pd.DataFrame([_full_batch_summary_row(status)]))
    with st.expander("高级：全市场批量补数据原始诊断", expanded=False):
        st.write(
            {
                "数据源": "akshare",
                "数据库路径": status.get("duckdb_path") or "暂无",
                "full 股票池数量": status.get("configured_symbol_count", 0),
                "最新数据覆盖股票数量": status.get("latest_daily_price_symbol_count", 0),
                "最新数据覆盖率": f"{float(status.get('latest_daily_price_coverage_rate', 0.0) or 0.0):.2%}",
                "已有任意行情股票数量": status.get("any_daily_price_symbol_count", 0),
                "任意行情覆盖率": f"{float(status.get('any_daily_price_coverage_rate', 0.0) or 0.0):.2%}",
                "完全缺行情股票数量": status.get("history_missing_symbol_count", 0),
                "历史不足但已有最新行情数量": status.get("latest_updated_but_history_incomplete_count", 0),
                "更新失败数量": status.get("update_failed_count", 0),
                "空数据 / 暂不可用股票数量": status.get("empty_data_count", 0),
                "网络失败股票数量": status.get("network_failed_count", 0),
            }
        )
    st.info("全市场更新可能耗时较长；建议先用 50 或 200 只小批量确认网络稳定。")
    mode_label = st.selectbox(
        "更新模式",
        ["优先补缺数据股票", "优先更新已有股票到最新日期", "自动模式"],
        index=0,
    )
    count_choice = st.selectbox("本次计划处理数量", ["50", "200", "500", "1000", "自定义"], index=2)
    if count_choice == "自定义":
        max_symbols = int(st.number_input("自定义本次计划处理数量", min_value=1, max_value=2000, value=500, step=50))
    else:
        max_symbols = int(count_choice)
    if max_symbols > 1000:
        st.warning("本次计划处理数量超过 1000，运行可能较久，也更容易受个别接口卡住影响。")
    batch_size = int(st.selectbox("每批大小", [20, 50, 100], index=1))
    lookback_days = int(st.selectbox("回看天数", [120, 250, 500], index=1))
    max_retries = int(st.selectbox("最大重试次数", [0, 1, 2], index=1))
    skip_empty = st.checkbox("跳过已知空数据 / 暂不可用股票", value=True)
    preflight = st.checkbox("更新前做数据源连通性预检", value=True)
    if not preflight:
        st.warning("不建议关闭预检。东方财富 K 线接口不可用时，批量更新会浪费时间。")
    args = build_full_batch_update_args(
        mode_label=mode_label,
        max_symbols=max_symbols,
        batch_size=batch_size,
        lookback_days=lookback_days,
        max_retries=max_retries,
        skip_empty_unavailable=skip_empty,
        preflight=preflight,
    )
    with st.expander("高级：本次补数据命令参数", expanded=False):
        st.write(
            {
                "FULL_UPDATE_MAX_SYMBOLS": max_symbols,
                "FULL_UPDATE_BATCH_SIZE": batch_size,
                "FULL_UPDATE_LOOKBACK_DAYS": lookback_days,
                "FULL_UPDATE_MAX_RETRIES": max_retries,
                "说明": "本次未处理数量表示 full 股票池中本次未纳入计划的股票，不代表永久跳过。",
            }
        )
    if st.button("运行数据源预检", key="full_update_preflight"):
        _run_streaming_console_action(st, "运行数据源预检", "preflight_data_source", [], success_message="预检完成。")
    col1, col2, col3 = st.columns(3)
    if col1.button("小批量补数据 50 只", key="full_batch_update_50"):
        small_args = build_full_batch_update_args(
            mode_label=mode_label,
            max_symbols=50,
            batch_size=batch_size,
            lookback_days=lookback_days,
            max_retries=max_retries,
            skip_empty_unavailable=skip_empty,
            preflight=preflight,
        )
        st.info("点击后会先做 DuckDB 锁、代理和东方财富 K 线接口预检；预检失败不会启动批量更新。")
        _run_streaming_console_action(st, "小批量补数据 50 只", "run_full_batch_update", small_args, success_message="小批量补数据完成。请刷新页面查看覆盖率变化。")
    if col2.button("小批量补数据 200 只", key="full_batch_update_200"):
        small_args = build_full_batch_update_args(
            mode_label=mode_label,
            max_symbols=200,
            batch_size=batch_size,
            lookback_days=lookback_days,
            max_retries=max_retries,
            skip_empty_unavailable=skip_empty,
            preflight=preflight,
        )
        st.info("点击后会先做 DuckDB 锁、代理和东方财富 K 线接口预检；预检失败不会启动批量更新。")
        _run_streaming_console_action(st, "小批量补数据 200 只", "run_full_batch_update", small_args, success_message="小批量补数据完成。请刷新页面查看覆盖率变化。")
    if col3.button("按当前参数开始补数据", key="full_batch_update_start"):
        st.info("点击后会先做 DuckDB 锁、代理和东方财富 K 线接口预检；预检失败不会启动批量更新。")
        _run_streaming_console_action(st, "按当前参数开始补数据", "run_full_batch_update", args, success_message="批量补数据命令执行完成。请刷新页面查看覆盖率变化。")


def _full_batch_summary_row(status: dict[str, Any]) -> dict[str, Any]:
    total = int(status.get("configured_symbol_count", 0) or 0)
    any_count = int(status.get("any_daily_price_symbol_count", 0) or 0)
    latest_count = int(status.get("latest_daily_price_symbol_count", 0) or 0)
    return {
        "数据源": "akshare",
        "full 股票池数量": total,
        "任意历史行情覆盖": f"{any_count} / {total} ({float(status.get('any_daily_price_coverage_rate', 0.0) or 0.0):.2%})",
        "最新交易日覆盖": f"{latest_count} / {total} ({float(status.get('latest_daily_price_coverage_rate', 0.0) or 0.0):.2%})",
        "完全缺行情": int(status.get("history_missing_symbol_count", 0) or 0),
        "建议": "建议先小批量 50 或 200 只确认网络稳定。",
    }


def build_full_batch_update_args(
    *,
    mode_label: str,
    max_symbols: int,
    batch_size: int,
    lookback_days: int,
    max_retries: int,
    skip_empty_unavailable: bool,
    preflight: bool,
) -> list[str]:
    """Map page controls to run_full_batch_update CLI args."""
    mode_map = {
        "优先补缺数据股票": "missing_first",
        "优先更新已有股票到最新日期": "stale_first",
        "自动模式": "auto",
    }
    args = [
        "--mode",
        mode_map.get(mode_label, "missing_first"),
        "--max-symbols",
        str(max(1, int(max_symbols))),
        "--batch-size",
        str(max(1, int(batch_size))),
        "--lookback-days",
        str(max(1, int(lookback_days))),
        "--max-retries",
        str(max(0, int(max_retries))),
    ]
    if not skip_empty_unavailable:
        args.append("--no-skip-empty-unavailable")
    if not preflight:
        args.append("--no-preflight")
    return args


def summarize_full_batch_update_result(before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Calculate user-facing before/after metrics for one full update run."""
    before_priced = int(before.get("priced_symbol_count", 0) or 0)
    after_priced = int(after.get("priced_symbol_count", before_priced) or 0)
    before_missing = int(before.get("missing_symbol_count", 0) or 0)
    after_missing = int(after.get("missing_symbol_count", before_missing) or 0)
    before_ready = int(before.get("selection_ready_count", 0) or 0)
    after_ready = int(after.get("selection_ready_count", before_ready) or 0)
    before_coverage = float(before.get("coverage_rate", 0.0) or 0.0)
    after_coverage = float(after.get("coverage_rate", before_coverage) or 0.0)
    written = result.get("written_rows", {}) if isinstance(result, dict) else {}
    return {
        "本次计划处理数量": int(result.get("planned_count", result.get("planned_symbols", 0)) or 0),
        "本次成功股票数量": int(result.get("success_symbols", 0) or 0),
        "本次失败股票数量": int(result.get("failed_symbols", 0) or 0),
        "本次空数据股票数量": len(result.get("empty_data_symbols", []) or []),
        "本次新增覆盖股票数量": max(after_priced - before_priced, 0),
        "本次只更新已有股票数量": max(int(result.get("success_symbols", 0) or 0) - max(after_priced - before_priced, 0), 0),
        "本次未处理股票数量": int(result.get("deferred_symbols", 0) or 0),
        "daily_price 新增行数": int(written.get("daily_price", 0) or 0),
        "daily_basic 新增行数": int(written.get("daily_basic", 0) or 0),
        "adj_factor 新增数量": int(written.get("adj_factor", 0) or 0),
        "覆盖率变化": f"{before_coverage:.2%} -> {after_coverage:.2%}",
        "已有行情股票数量变化": f"{before_priced} -> {after_priced}",
        "缺数据股票数量变化": f"{before_missing} -> {after_missing}",
        "可运行选股股票数量变化": f"{before_ready} -> {after_ready}",
    }


def _render_local_console_tab(st: Any, tables: dict[str, pd.DataFrame]) -> None:
    """Render local settings and command console."""
    st.subheader("参数设置 / 本地控制台")
    st.caption("仅供个人研究使用，不自动交易。页面只执行预设白名单命令。")
    st.info("本地控制台用于查看参数、保存参数、本地重算和导出报告。如需补充行情数据，请到“数据更新状态”页面执行；本页的本地重算只基于现有数据库，不补行情。")
    env_path = PROJECT_ROOT / ".env"
    env_values = read_env_file(env_path)
    display_values = masked_env_values(env_values)
    status = summarize_update_status(tables)
    effective = effective_pool_config(env_values, status)
    date_status = build_date_status(env_values, status)

    st.write("当前生效配置")
    st.write(
        {
            "当前股票池模式": effective["mode_label"],
            "当前实际生效股票数量": effective["symbol_count"],
            "当前实际生效股票代码": effective["symbols_text"],
            "AKSHARE_SAMPLE_SYMBOLS 当前值": effective["akshare_sample_symbols"] or "空",
            "REAL_UNIVERSE_PRESET 当前值": effective["real_universe_preset"],
            "当前提示": effective["message"],
        }
    )
    if effective["preset_inactive"]:
        st.warning("你现在选择的是“自定义股票池”，所以系统只会更新上面输入的股票代码。预设股票池 small / medium / full 暂时不会生效。")
    else:
        st.info("当前使用 REAL_UNIVERSE_PRESET 股票池。")

    st.write("参数日期 vs 数据库日期")
    st.write(
        {
            "参数开始日期": date_status["start_date"] or "未设置",
            "参数结束日期": date_status["end_date"] or "留空",
            "数据库最新行情日期": date_status["latest_price_date"] or "暂无",
            "数据库最新因子日期": date_status["latest_factor_date"] or "暂无",
            "数据库最新选股日期": date_status["latest_selection_date"] or "暂无",
            "full 覆盖率": f"{status.get('coverage_rate', 0.0):.2%}",
            "full 缺行情股票": status.get("missing_symbol_count", 0),
            "full 最新行情不足股票": status.get("stale_symbol_count", 0),
        }
    )
    if date_status["warning"]:
        st.warning(date_status["message"])
    else:
        st.info(date_status["message"])

    st.write("当前运行状态")
    st.write(
        {
            "当前 DATA_PROVIDER": env_values.get("DATA_PROVIDER", "未设置"),
            "DuckDB 路径": env_values.get("DUCKDB_PATH", "./data/a_stock_assistant.duckdb"),
            "最新交易日 PE/PB 完整率": _latest_pe_pb_text(tables),
            "全市场数据状态": status.get("batch_status") or "暂无",
            "当前已有行情股票数量": status.get("priced_symbol_count", 0),
            "最近日报路径": (status.get("latest_daily_workflow_report") or {}).get("path") if isinstance(status.get("latest_daily_workflow_report"), dict) else "暂无",
            "最近观察池报告路径": (status.get("latest_watchlist_report") or {}).get("path") if isinstance(status.get("latest_watchlist_report"), dict) else "暂无",
            "TUSHARE_TOKEN": display_values.get("TUSHARE_TOKEN", "未设置"),
        }
    )

    st.write("简化设置区")
    with st.form("local_console_settings"):
        default_pool_mode = "自定义股票池" if effective["mode"] == "custom" else "使用预设股票池"
        pool_mode = st.radio("股票池模式", ["自定义股票池", "使用预设股票池"], index=_option_index(["自定义股票池", "使用预设股票池"], default_pool_mode), horizontal=True)
        symbols = st.text_input("自定义股票代码", value=env_values.get("AKSHARE_SAMPLE_SYMBOLS", "000001,600000,000002"))
        preset = st.selectbox(
            "预设股票池",
            ["mini", "small", "medium", "full"],
            index=_option_index(["mini", "small", "medium", "full"], env_values.get("REAL_UNIVERSE_PRESET", "mini")),
        )
        if pool_mode == "自定义股票池":
            st.caption("支持 000001,600000,002475，也支持中文逗号、换行和 000001.SZ / 600000.SH。保存后预设股票池暂时不会生效。")
        else:
            st.caption("保存时会清空 AKSHARE_SAMPLE_SYMBOLS。mini / small / medium 是样本池；full 是沪深 A 股全市场，不含北交所。")
        start_date = st.text_input("参数开始日期", value=env_values.get("REAL_DATA_START_DATE", "20240101"))
        end_date = st.text_input("参数结束日期", value=env_values.get("REAL_DATA_END_DATE", ""))
        st.caption("结束日期留空表示尽量拉取到最新可得日期。")
        with st.expander("高级参数", expanded=False):
            provider = st.selectbox(
                "DATA_PROVIDER",
                ["sample", "tushare", "akshare"],
                index=_option_index(["sample", "tushare", "akshare"], env_values.get("DATA_PROVIDER", "akshare")),
            )
            akshare_adjust = st.selectbox(
                "AKSHARE_ADJUST",
                ["qfq", "hfq", ""],
                index=_option_index(["qfq", "hfq", ""], env_values.get("AKSHARE_ADJUST", "qfq")),
            )
            basic_enrichment = st.checkbox("ENABLE_REAL_BASIC_ENRICHMENT", value=_bool_value(env_values.get("ENABLE_REAL_BASIC_ENRICHMENT", "true")))
            stock_basic_enrichment = st.checkbox("ENABLE_STOCK_BASIC_ENRICHMENT", value=_bool_value(env_values.get("ENABLE_STOCK_BASIC_ENRICHMENT", "false")))
            full_stock_basic_enrichment = st.checkbox("FULL_ENABLE_STOCK_BASIC_ENRICHMENT", value=_bool_value(env_values.get("FULL_ENABLE_STOCK_BASIC_ENRICHMENT", "false")))
            valuation_enrichment = st.checkbox("ENABLE_REAL_VALUATION_ENRICHMENT", value=_bool_value(env_values.get("ENABLE_REAL_VALUATION_ENRICHMENT", "true")))
            valuation_network_enrichment = st.checkbox("ENABLE_VALUATION_ENRICHMENT", value=_bool_value(env_values.get("ENABLE_VALUATION_ENRICHMENT", "false")))
            full_valuation_network_enrichment = st.checkbox("FULL_ENABLE_VALUATION_ENRICHMENT", value=_bool_value(env_values.get("FULL_ENABLE_VALUATION_ENRICHMENT", "false")))
            batch_size = st.number_input("REAL_BATCH_SIZE", min_value=1, value=int(env_values.get("REAL_BATCH_SIZE", "10") or 10), step=1)
            batch_sleep = st.number_input("REAL_BATCH_SLEEP_SECONDS", min_value=0.0, value=float(env_values.get("REAL_BATCH_SLEEP_SECONDS", "0") or 0.0), step=0.1)
            max_retries = st.number_input("REAL_MAX_RETRIES", min_value=0, value=int(env_values.get("REAL_MAX_RETRIES", "1") or 1), step=1)
            timeout_seconds = st.number_input("REAL_REQUEST_TIMEOUT_SECONDS", min_value=1, value=int(env_values.get("REAL_REQUEST_TIMEOUT_SECONDS", "30") or 30), step=1)
            full_update_batch_size = st.number_input("FULL_UPDATE_BATCH_SIZE", min_value=1, value=int(env_values.get("FULL_UPDATE_BATCH_SIZE", "50") or 50), step=10)
            full_update_lookback_days = st.number_input("FULL_UPDATE_LOOKBACK_DAYS", min_value=1, value=int(env_values.get("FULL_UPDATE_LOOKBACK_DAYS", "250") or 250), step=10)
            full_update_max_retries = st.number_input("FULL_UPDATE_MAX_RETRIES", min_value=1, value=int(env_values.get("FULL_UPDATE_MAX_RETRIES", "2") or 2), step=1)
            full_update_sleep_seconds = st.number_input("FULL_UPDATE_SLEEP_SECONDS", min_value=0.0, value=float(env_values.get("FULL_UPDATE_SLEEP_SECONDS", "0.2") or 0.2), step=0.1)
            full_update_resume = st.checkbox("FULL_UPDATE_RESUME", value=_bool_value(env_values.get("FULL_UPDATE_RESUME", "true")))
            full_update_max_symbols = st.number_input("FULL_UPDATE_MAX_SYMBOLS", min_value=0, value=int(env_values.get("FULL_UPDATE_MAX_SYMBOLS", "0") or 0), step=20)
            full_update_max_batches = st.number_input("FULL_UPDATE_MAX_BATCHES", min_value=0, value=int(env_values.get("FULL_UPDATE_MAX_BATCHES", "0") or 0), step=1)
            min_listing_days = st.number_input("MIN_LISTING_DAYS", min_value=0, value=int(env_values.get("MIN_LISTING_DAYS", "120") or 120), step=10)
            min_avg_amount_20d = st.number_input("MIN_AVG_AMOUNT_20D", min_value=0, value=int(env_values.get("MIN_AVG_AMOUNT_20D", "100000000") or 100000000), step=10_000_000)
            min_median_amount_20d = st.number_input("MIN_MEDIAN_AMOUNT_20D", min_value=0, value=int(env_values.get("MIN_MEDIAN_AMOUNT_20D", "50000000") or 50000000), step=5_000_000)
            min_latest_amount = st.number_input("MIN_LATEST_AMOUNT", min_value=0, value=int(env_values.get("MIN_LATEST_AMOUNT", "30000000") or 30000000), step=5_000_000)
            min_traded_days_20d = st.number_input("MIN_TRADED_DAYS_20D", min_value=0, max_value=20, value=int(env_values.get("MIN_TRADED_DAYS_20D", "18") or 18), step=1)
            include_bse = st.checkbox("INCLUDE_BSE", value=_bool_value(env_values.get("INCLUDE_BSE", "false")))
            data_dir = st.text_input("DATA_DIR", value=env_values.get("DATA_DIR", "./data"))
            duckdb_path = st.text_input("DUCKDB_PATH", value=env_values.get("DUCKDB_PATH", "./data/a_stock_assistant.duckdb"))
            st.write({"TUSHARE_TOKEN 状态": display_values.get("TUSHARE_TOKEN", "未设置")})
        save_only = st.form_submit_button("保存参数")
        save_recalculate = st.form_submit_button("保存并本地重算")

    updates, validation = build_settings_updates(
        pool_mode=pool_mode,
        symbols_text=symbols,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        provider=provider,
        akshare_adjust=akshare_adjust,
        basic_enrichment=basic_enrichment,
        stock_basic_enrichment=stock_basic_enrichment,
        full_stock_basic_enrichment=full_stock_basic_enrichment,
        valuation_enrichment=valuation_enrichment,
        valuation_network_enrichment=valuation_network_enrichment,
        full_valuation_network_enrichment=full_valuation_network_enrichment,
        batch_size=batch_size,
        batch_sleep=batch_sleep,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
        full_update_batch_size=full_update_batch_size,
        full_update_lookback_days=full_update_lookback_days,
        full_update_max_retries=full_update_max_retries,
        full_update_sleep_seconds=full_update_sleep_seconds,
        full_update_resume=full_update_resume,
        full_update_max_symbols=full_update_max_symbols,
        full_update_max_batches=full_update_max_batches,
        min_listing_days=min_listing_days,
        min_avg_amount_20d=min_avg_amount_20d,
        min_median_amount_20d=min_median_amount_20d,
        min_latest_amount=min_latest_amount,
        min_traded_days_20d=min_traded_days_20d,
        include_bse=include_bse,
        data_dir=data_dir,
        duckdb_path=duckdb_path,
    )
    if validation["invalid"]:
        st.warning(f"以下股票代码不是 6 位数字，未保存：{', '.join(validation['invalid'])}")
    if save_only or save_recalculate:
        if validation["invalid"]:
            st.error("请先修正股票代码，再保存参数。")
        else:
            saved = _save_console_settings(st, env_path, updates)
            if saved and save_only:
                st.info("参数已保存，但数据库尚未更新。full 批量补数据请到“数据更新状态”页执行；本页可用于本地重算或日常工作流。请点击页面右上角刷新，或按 R 重新加载页面。")
            elif saved and save_recalculate:
                st.info("该操作不会联网更新行情，只会用本地已有数据重新生成报告。")
                _run_console_action(st, "保存并本地重算", "run_daily_workflow", ["--doctor-before-run", "--skip-update", "--format", "all"])

    st.write("一键操作区")
    st.caption("一键本地重算不会联网补行情；如需补行情，请到“数据更新状态”页面。")
    _command_button(st, "一键本地重算（不联网）", "run_daily_workflow", ["--doctor-before-run", "--skip-update", "--format", "all"])
    _export_workbook_button(st)
    _command_button(st, "运行体检", "doctor_daily_run")
    _open_button(st, "打开报告文件夹", PROJECT_ROOT / "reports")
    _command_button(st, "清理旧报告", "clean_generated_reports", ["--force"])

    with st.expander("高级操作", expanded=False):
        output_format = st.selectbox("输出格式", ["all", "markdown", "json", "csv"], index=0)
        _command_button(st, "只用本地已有数据，不联网更新行情", "run_daily_workflow", ["--doctor-before-run", "--skip-update", "--format", output_format])
        _command_button(st, "生成候选", "run_daily_selection")
        _command_button(st, "刷新观察池", "refresh_watchlist_scores")
        _command_button(st, "查看观察池", "diagnose_watchlist")
        _open_button(st, "打开项目文件夹", PROJECT_ROOT)


def build_settings_updates(
    *,
    pool_mode: str,
    symbols_text: str,
    preset: str,
    start_date: str,
    end_date: str,
    provider: str,
    akshare_adjust: str,
    basic_enrichment: bool,
    valuation_enrichment: bool,
    batch_size: int,
    batch_sleep: float,
    max_retries: int,
    timeout_seconds: int,
    full_update_batch_size: int = 50,
    full_update_lookback_days: int = 250,
    full_update_max_retries: int = 2,
    full_update_sleep_seconds: float = 0.2,
    full_update_resume: bool = True,
    full_update_max_symbols: int = 0,
    full_update_max_batches: int = 0,
    min_listing_days: int = 120,
    min_avg_amount_20d: int = 100_000_000,
    min_median_amount_20d: int = 50_000_000,
    min_latest_amount: int = 30_000_000,
    min_traded_days_20d: int = 18,
    include_bse: bool = False,
    data_dir: str = "./data",
    duckdb_path: str = "./data/a_stock_assistant.duckdb",
    stock_basic_enrichment: bool = False,
    full_stock_basic_enrichment: bool = False,
    valuation_network_enrichment: bool = False,
    full_valuation_network_enrichment: bool = False,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Build .env updates for the simplified settings form."""
    parsed = parse_stock_symbols(symbols_text)
    use_preset = pool_mode == "使用预设股票池"
    updates = {
        "DATA_PROVIDER": provider,
        "AKSHARE_SAMPLE_SYMBOLS": "" if use_preset else ",".join(parsed["symbols"]),
        "REAL_UNIVERSE_PRESET": preset,
        "AKSHARE_ADJUST": akshare_adjust,
        "REAL_DATA_START_DATE": start_date,
        "REAL_DATA_END_DATE": end_date,
        "ENABLE_REAL_BASIC_ENRICHMENT": basic_enrichment,
        "ENABLE_STOCK_BASIC_ENRICHMENT": stock_basic_enrichment,
        "FULL_ENABLE_STOCK_BASIC_ENRICHMENT": full_stock_basic_enrichment,
        "ENABLE_REAL_VALUATION_ENRICHMENT": valuation_enrichment,
        "ENABLE_VALUATION_ENRICHMENT": valuation_network_enrichment,
        "FULL_ENABLE_VALUATION_ENRICHMENT": full_valuation_network_enrichment,
        "REAL_BATCH_SIZE": batch_size,
        "REAL_BATCH_SLEEP_SECONDS": batch_sleep,
        "REAL_MAX_RETRIES": max_retries,
        "REAL_REQUEST_TIMEOUT_SECONDS": timeout_seconds,
        "FULL_UPDATE_BATCH_SIZE": full_update_batch_size,
        "FULL_UPDATE_LOOKBACK_DAYS": full_update_lookback_days,
        "FULL_UPDATE_MAX_RETRIES": full_update_max_retries,
        "FULL_UPDATE_SLEEP_SECONDS": full_update_sleep_seconds,
        "FULL_UPDATE_RESUME": full_update_resume,
        "FULL_UPDATE_MAX_SYMBOLS": full_update_max_symbols,
        "FULL_UPDATE_MAX_BATCHES": full_update_max_batches,
        "MIN_LISTING_DAYS": min_listing_days,
        "MIN_AVG_AMOUNT_20D": min_avg_amount_20d,
        "MIN_MEDIAN_AMOUNT_20D": min_median_amount_20d,
        "MIN_LATEST_AMOUNT": min_latest_amount,
        "MIN_TRADED_DAYS_20D": min_traded_days_20d,
        "INCLUDE_BSE": include_bse,
        "DATA_DIR": data_dir,
        "DUCKDB_PATH": duckdb_path,
    }
    return updates, {"invalid": [] if use_preset else parsed["invalid"]}


def effective_pool_config(values: dict[str, str], status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Describe the currently effective stock-pool configuration."""
    resolved_status = status or {}
    symbols = parse_stock_symbols(values.get("AKSHARE_SAMPLE_SYMBOLS", ""))
    preset = values.get("REAL_UNIVERSE_PRESET", "mini")
    if symbols["symbols"]:
        return {
            "mode": "custom",
            "mode_label": "自定义股票池",
            "symbol_count": len(symbols["symbols"]),
            "symbols": symbols["symbols"],
            "symbols_text": ",".join(symbols["symbols"]),
            "akshare_sample_symbols": values.get("AKSHARE_SAMPLE_SYMBOLS", ""),
            "REAL_UNIVERSE_PRESET": preset,
            "real_universe_preset": preset,
            "preset_inactive": True,
            "message": "AKSHARE_SAMPLE_SYMBOLS 不为空，当前优先使用自定义股票池，REAL_UNIVERSE_PRESET 当前不生效。",
        }
    configured_count = int(resolved_status.get("configured_symbol_count", 0) or 0)
    if configured_count <= 0 and preset != "full":
        configured_count = _configured_symbol_count(values)
    return {
        "mode": "preset",
        "mode_label": "REAL_UNIVERSE_PRESET=full（沪深 A 股全市场，不含北交所）" if preset == "full" else "REAL_UNIVERSE_PRESET",
        "symbol_count": configured_count,
        "symbols": [],
        "symbols_text": (
            f"使用 full 沪深 A 股全市场股票池，不含北交所；当前解析 {configured_count} 只"
            if preset == "full"
            else f"使用预设：{preset}，当前解析 {configured_count} 只"
        ),
        "akshare_sample_symbols": "",
        "real_universe_preset": preset,
        "preset_inactive": False,
        "message": "AKSHARE_SAMPLE_SYMBOLS 为空，当前使用 full 沪深 A 股全市场股票池，不含北交所。" if preset == "full" else "AKSHARE_SAMPLE_SYMBOLS 为空，当前使用 REAL_UNIVERSE_PRESET 股票池。",
    }


def build_date_status(env_values: dict[str, str], status: dict[str, Any]) -> dict[str, Any]:
    """Compare parameter dates with actual database dates."""
    end_date = env_values.get("REAL_DATA_END_DATE", "")
    latest_price_date = status.get("latest_price_date")
    message = "结束日期留空表示尽量拉取到最新可得日期。"
    warning = False
    full_mode = (
        env_values.get("DATA_PROVIDER", "").lower() == "akshare"
        and not str(env_values.get("AKSHARE_SAMPLE_SYMBOLS", "")).strip()
        and env_values.get("REAL_UNIVERSE_PRESET") == "full"
    )
    configured_count = int(status.get("configured_symbol_count", 0) or 0)
    priced_count = int(status.get("priced_symbol_count", 0) or 0)
    missing_count = int(status.get("missing_symbol_count", 0) or 0)
    stale_count = int(status.get("stale_symbol_count", 0) or 0)
    if full_mode and configured_count and (priced_count < configured_count or missing_count or stale_count):
        warning = True
        message = (
            f"全市场数据未完成：基础股票池 {configured_count} 只，已有行情 {priced_count} 只，"
            f"缺行情 {missing_count} 只，最新不足 {stale_count} 只。请到“数据更新状态”页使用“全市场批量补数据”。"
        )
    elif full_mode and configured_count:
        message = "full 股票池覆盖率已达到当前配置。"
    if end_date and latest_price_date and str(latest_price_date) < str(end_date):
        warning = True
        message = f"参数结束日期为 {end_date}，但数据库最新行情日期仍为 {latest_price_date}。请到“数据更新状态”页运行数据源预检和批量补数据。"
    elif end_date and not warning:
        message = "数据库最新行情日期已达到或晚于参数结束日期。"
    return {
        "start_date": env_values.get("REAL_DATA_START_DATE", ""),
        "end_date": end_date,
        "latest_price_date": latest_price_date,
        "latest_factor_date": status.get("latest_factor_date"),
        "latest_selection_date": status.get("latest_selection_date"),
        "warning": warning,
        "message": message,
    }


def _save_console_settings(st: Any, env_path: Path, updates: dict[str, Any]) -> bool:
    try:
        result = update_env_file(env_path, updates)
        st.success(f"参数已保存：{', '.join(result['updated_keys'])}。")
        return True
    except Exception as exc:
        st.error(f"保存失败：{exc}")
        return False


def _run_console_action(st: Any, label: str, command_key: str, args: list[str]) -> None:
    _run_streaming_console_action(st, label, command_key, args, success_message="执行完成。请点击页面右上角刷新，或按 R 重新加载页面。")


def _command_button(st: Any, label: str, command_key: str, args: list[str] | None = None) -> None:
    """Render a whitelisted command button."""
    if not st.button(label, key=f"cmd_{label}"):
        return
    _run_streaming_console_action(st, label, command_key, args or [], success_message="命令执行成功。")


def _export_workbook_button(st: Any) -> None:
    """Render the daily research workbook export button with file feedback."""
    label = "导出今日研究工作簿 Excel"
    if not st.button(label, key="cmd_export_daily_research_workbook"):
        return
    logs: list[str] = []
    status_box = st.empty()
    log_box = st.empty()
    status = {
        "当前运行步骤": "准备开始",
        "当前处理任务": label,
        "已成功数量": 0,
        "已失败数量": 0,
        "最终报告路径": "暂无",
    }

    def on_line(line: str) -> None:
        logs.append(line)
        output_path = _extract_workbook_output_path("\n".join(logs))
        if output_path:
            status["最终报告路径"] = str(output_path)
        status_box.write(status)
        log_box.code("\n".join(logs[-120:]) or "等待输出...")

    status_box.write(status)
    log_box.code("等待输出...")
    with st.spinner("正在生成 Excel 工作簿..."):
        try:
            result = run_command_streaming("export_daily_research_workbook", [], on_line=on_line)
        except Exception as exc:
            status["已失败数量"] = 1
            status_box.write(status)
            st.error(f"导出失败：{exc}")
            return
    output_path = _extract_workbook_output_path(result.stdout)
    if result.status != "success":
        status["已失败数量"] = 1
        status_box.write(status)
        st.error(f"导出失败：returncode={result.returncode}")
        st.code(result.stdout or "无输出")
        return
    if output_path is None or not output_path.exists():
        status["已失败数量"] = 1
        status_box.write(status)
        st.error("导出失败：未找到导出的 Excel 文件路径。")
        st.code(result.stdout or "无输出")
        return
    status.update({"当前运行步骤": "已完成", "已成功数量": 1, "已失败数量": 0, "最终报告路径": str(output_path)})
    status_box.write(status)
    file_size_kb = output_path.stat().st_size / 1024
    st.success("导出成功")
    st.write(
        {
            "文件名": output_path.name,
            "保存位置": str(output_path.resolve()),
            "文件大小": f"{file_size_kb:.1f} KB",
        }
    )
    st.download_button(
        "下载 Excel 工作簿",
        data=output_path.read_bytes(),
        file_name=output_path.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    _open_button(st, "打开 reports 文件夹", PROJECT_ROOT / "reports")


def _extract_workbook_output_path(output: str) -> Path | None:
    """Extract exported workbook path from CLI stdout."""
    for line in reversed(output.splitlines()):
        if line.startswith("输出文件:"):
            raw = line.split(":", 1)[1].strip()
            if raw:
                return Path(raw)
    return None


def _run_streaming_console_action(
    st: Any,
    label: str,
    command_key: str,
    args: list[str],
    *,
    success_message: str,
) -> None:
    """Run a local command and stream progress/log lines into Streamlit."""
    status_box = st.empty()
    log_box = st.empty()
    progress_bar = st.progress(0)
    logs: list[str] = []
    latest_progress: dict[str, Any] = {
        "当前运行步骤": "准备开始",
        "当前处理股票或子任务": label,
        "已成功数量": 0,
        "已失败数量": 0,
        "本次未处理数量": 0,
        "最终报告路径": "暂无",
    }

    def on_line(line: str) -> None:
        logs.append(line)
        state = parse_progress_line(line)
        if state is not None:
            latest_progress.update(
                {
                    "当前运行步骤": state.step or "暂无",
                    "当前处理股票或子任务": state.current or "暂无",
                    "已成功数量": state.success,
                    "已失败数量": state.failed,
                    "本次未处理数量": state.skipped,
                }
            )
            if "报告 " in state.message:
                latest_progress["最终报告路径"] = state.message.split("报告 ", 1)[-1].strip("。")
            progress_bar.progress(min(0.95, max(0.05, len(logs) / 80)))
        status_box.write(latest_progress)
        log_box.code("\n".join(logs[-300:]) or "等待输出...")

    status_box.write(latest_progress)
    log_box.code("等待输出...")
    with st.spinner(f"正在执行：{label}"):
        try:
            result = run_command_streaming(command_key, args, on_line=on_line)
        except Exception as exc:
            st.error(f"执行失败：{exc}")
            st.info("请先运行 doctor 体检，或查看 docs/troubleshooting.md。")
            return
    if result.status == "success":
        progress_bar.progress(1.0)
        st.success(success_message)
    else:
        if command_key in {"preflight_data_source", "run_full_batch_update"}:
            st.error("数据源预检未通过，未启动批量更新。")
            st.warning("原因：东方财富 K 线接口检测失败，或 DuckDB / 代理预检未通过。请查看日志中的 used_url、curl_returncode 和 stderr。")
        else:
            st.error(f"命令执行失败：{result.status}，returncode={result.returncode}")
        st.info("可查看 stderr，并按提示重跑对应命令。")
    with st.expander("实时日志 / stdout"):
        st.code(result.stdout or "无输出")


def _open_button(st: Any, label: str, path: Path) -> None:
    """Render a button that opens a project-local folder."""
    if not st.button(label, key=f"open_{label}"):
        return
    try:
        result = open_project_path(path)
    except Exception as exc:
        st.error(f"打开失败：{exc}")
        return
    if result.status == "success":
        st.success(f"已打开：{path}")
    else:
        st.error(result.stderr or "打开失败。")


def _latest_pe_pb_text(tables: dict[str, pd.DataFrame]) -> str:
    daily_basic = tables.get("daily_basic", pd.DataFrame())
    if not isinstance(daily_basic, pd.DataFrame) or daily_basic.empty or "trade_date" not in daily_basic.columns:
        return "暂无"
    latest = str(daily_basic["trade_date"].dropna().astype(str).max())
    latest_rows = daily_basic[daily_basic["trade_date"].astype(str) == latest]
    pe = _present_rate(latest_rows, "pe")
    pb = _present_rate(latest_rows, "pb")
    return f"{latest}: PE {pe:.2%} / PB {pb:.2%}"


def _present_rate(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    return float(df[column].apply(lambda value: not _is_missing(value)).sum() / len(df))


def _configured_symbol_count(values: dict[str, str]) -> int:
    symbols = values.get("AKSHARE_SAMPLE_SYMBOLS", "")
    if symbols.strip():
        return len([item for item in symbols.split(",") if item.strip()])
    preset = values.get("REAL_UNIVERSE_PRESET", "mini")
    if preset == "full":
        return 0
    try:
        from core.data_sources.universe_presets import get_universe_preset

        return len(get_universe_preset(preset))
    except Exception:
        return 0


def _bool_value(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _option_index(options: list[str], value: str) -> int:
    try:
        return options.index(str(value))
    except ValueError:
        return 0


def _load_watchlist_for_dashboard(store: Any) -> pd.DataFrame:
    """Load active watchlist from local DuckDB for dashboard display."""
    from core.review.decisions import build_watchlist_dataframe

    try:
        return build_watchlist_dataframe(store, active_only=True)
    except Exception:
        return pd.DataFrame()


def _load_positions_for_dashboard(store: Any) -> pd.DataFrame:
    """Load local positions enriched with latest close for dashboard display."""
    from core.positions.position_pool import build_positions_dataframe

    try:
        return build_positions_dataframe(store, active_only=False)
    except Exception:
        return pd.DataFrame()


def _safe_read_store_table(store: Any, table_name: str, limit: int | None = None) -> pd.DataFrame:
    """Read optional local DuckDB tables for the dashboard."""
    from core.storage.duckdb_store import DuckDBStoreLockedError

    try:
        return store.read_table(table_name, limit=limit)
    except DuckDBStoreLockedError:
        raise
    except Exception:
        return pd.DataFrame()


def _safe_local_state() -> dict[str, Any]:
    """Return local state diagnostics for display without mutating files."""
    try:
        return diagnose_local_state()
    except Exception:
        return {}


def _watchlist_from_tables(tables: dict[str, Any]) -> pd.DataFrame:
    """Return active watchlist rows enriched with local history metadata."""
    reviews = tables.get("review_decisions", pd.DataFrame())
    if not isinstance(reviews, pd.DataFrame) or reviews.empty:
        return pd.DataFrame()
    watchlist = reviews[
        (reviews["decision"].astype(str) == "watch")
        & (reviews["review_status"].fillna("active").astype(str) == "active")
    ].copy()
    history = tables.get("review_decision_history", pd.DataFrame())
    if not isinstance(history, pd.DataFrame) or history.empty:
        watchlist["latest_action_at"] = pd.NA
        watchlist["history_count"] = 0
        return _attach_basic_fields_for_dashboard(watchlist, tables)
    rows = []
    grouped = {str(code): df.sort_values("created_at") for code, df in history.groupby("ts_code")}
    for item in watchlist.to_dict("records"):
        current = grouped.get(str(item.get("ts_code")), pd.DataFrame())
        latest = current.iloc[-1].to_dict() if not current.empty else {}
        rows.append(
            {
                **item,
                "latest_action_at": latest.get("created_at"),
                "latest_action_type": latest.get("action_type"),
                "history_count": int(len(current)),
            }
        )
    return _attach_basic_fields_for_dashboard(pd.DataFrame(rows), tables)


def _attach_basic_fields_for_dashboard(watchlist: pd.DataFrame, tables: dict[str, Any]) -> pd.DataFrame:
    """Attach stock_basic and latest daily_basic fields for status display."""
    if watchlist.empty or "ts_code" not in watchlist.columns:
        return watchlist
    result = watchlist.copy()
    stock_basic = tables.get("stock_basic", pd.DataFrame())
    if isinstance(stock_basic, pd.DataFrame) and not stock_basic.empty and "ts_code" in stock_basic.columns:
        basic_cols = [column for column in ["ts_code", "industry", "list_date"] if column in stock_basic.columns]
        result = result.merge(stock_basic[basic_cols].drop_duplicates("ts_code"), on="ts_code", how="left")
    daily_basic = tables.get("daily_basic", pd.DataFrame())
    if isinstance(daily_basic, pd.DataFrame) and not daily_basic.empty and {"ts_code", "trade_date"}.issubset(daily_basic.columns):
        latest = daily_basic.sort_values("trade_date").groupby("ts_code").tail(1)
        basic_cols = [column for column in ["ts_code", "pe", "pb"] if column in latest.columns]
        result = result.merge(latest[basic_cols], on="ts_code", how="left")
    return result


def _load_tracking_snapshot_for_dashboard(store: Any) -> pd.DataFrame:
    """Load latest watchlist snapshot rows from local DuckDB for dashboard display."""
    from core.review.tracking import latest_tracking_snapshot

    try:
        return latest_tracking_snapshot(store)
    except Exception:
        return pd.DataFrame()


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Ensure a DataFrame contains all requested columns."""
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    return df


def _latest_date(df: pd.DataFrame, column: str) -> str | None:
    """Return the latest date string from a DataFrame column."""
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    if values.empty:
        return None
    return str(values.max())


def _trailing_return(close: pd.Series, window: int) -> float | None:
    """Return trailing return over a window when enough observations exist."""
    if len(close) <= window:
        return None
    previous = close.iloc[-window - 1]
    if previous == 0:
        return None
    return float(close.iloc[-1] / previous - 1)


def _format_percent(value: float | None) -> str:
    """Format optional decimal return as a percentage string."""
    if value is None or pd.isna(value):
        return "暂无"
    return f"{value:.2%}"


def _format_optional_rate(value: Any) -> str:
    """Format optional rate values for status display."""
    if value is None or pd.isna(value):
        return "暂无"
    return f"{float(value):.2%}"


def _is_missing(value: Any) -> bool:
    """Return whether a dashboard value should be treated as missing."""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


def _workflow_status_message(report: Any) -> str:
    """Return a concise status message from the latest workflow report."""
    if not isinstance(report, dict):
        return "暂无 workflow 报告；可运行 python -m core.jobs.run_real_workflow 生成。"
    status = report.get("overall_status") or "未知"
    path = report.get("path") or "未知路径"
    return f"最近 workflow 报告状态：{status}；报告路径：{path}"


if __name__ == "__main__":
    main()
