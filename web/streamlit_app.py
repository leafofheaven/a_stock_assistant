"""Streamlit dashboard for A-share selection research results."""

from __future__ import annotations

import sys
import json
from io import StringIO
from pathlib import Path
import tempfile
import time
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.sample_data import get_sample_dashboard_data
from core.calendar.trading_calendar import resolve_update_target_trade_date, summarize_trade_calendar_status
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
from core.jobs.market_data_progress import DEFAULT_PROGRESS_PATH, read_market_data_progress
from core.jobs.run_scheduled_daily_update import DEFAULT_STATUS_PATH, read_scheduled_status
from core.jobs.export_daily_research_workbook import build_daily_research_view_from_frames, build_lookback_status_display
from core.advice.simulated_trading_advice import summarize_simulated_trading_advice
from core.runtime.progress import parse_progress_line
from core.technical.elder import build_elder_review
from app.config import get_settings
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.external_positions.importer import (
    import_external_positions_frame,
    import_external_trades_and_rebuild_positions_frame,
    position_template_excel_bytes,
    position_template_frame,
    read_uploaded_table,
    trade_template_excel_bytes,
    trade_template_frame,
)

ALLOWED_COMMANDS.setdefault("run_full_batch_update", [sys.executable, "-m", "core.jobs.run_full_batch_update"])
ALLOWED_COMMANDS.setdefault("preflight_data_source", [sys.executable, "-m", "core.jobs.preflight_data_source"])
ALLOWED_COMMANDS.setdefault("diagnose_data_source_network", [sys.executable, "-m", "core.jobs.diagnose_data_source_network"])
ALLOWED_COMMANDS.setdefault("refresh_data_quality_status", [sys.executable, "-m", "core.jobs.refresh_data_quality_status"])
ALLOWED_COMMANDS.setdefault("update_market_data", [sys.executable, "-m", "core.jobs.update_market_data"])
ALLOWED_COMMANDS.setdefault("import_market_data", [sys.executable, "-m", "core.jobs.import_market_data"])
ALLOWED_COMMANDS.setdefault("run_scheduled_daily_update", [sys.executable, "-m", "core.jobs.run_scheduled_daily_update"])
ALLOWED_COMMANDS.setdefault("install_scheduled_daily_update", [sys.executable, "-m", "core.jobs.install_scheduled_daily_update"])
ALLOWED_COMMANDS.setdefault("uninstall_scheduled_daily_update", [sys.executable, "-m", "core.jobs.uninstall_scheduled_daily_update"])
ALLOWED_COMMANDS.setdefault("run_lookback_analysis", [sys.executable, "-m", "core.jobs.run_lookback_analysis"])
ALLOWED_COMMANDS.setdefault("update_trade_calendar", [sys.executable, "-m", "core.jobs.update_trade_calendar"])

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
    "source_tags": "来源标签",
    "holding_status": "持仓状态",
    "simulated_action": "模拟操作建议",
    "suggested_position": "建议模拟仓位",
    "action_priority": "动作优先级",
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
    "position_qty": "模拟持仓数量",
    "avg_cost": "平均成本",
    "unrealized_pnl": "浮动盈亏",
    "unrealized_pnl_pct": "浮动盈亏比例",
    "holding_days": "持仓天数",
    "position_action": "持仓处理建议",
    "position_reason": "持仓建议理由",
    "add_condition": "加仓条件",
    "reduce_condition": "减仓条件",
    "exit_condition": "退出条件",
    "trigger_condition": "触发条件",
    "invalidation_condition": "失效条件",
    "advice_reason": "建议理由",
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
    display_df = _make_arrow_safe_display_df(
        prepare_display_table(df, columns=columns, show_rank_fields=show_rank_fields)
    )
    try:
        st.dataframe(display_df, width="stretch", hide_index=True)
    except TypeError:
        st.dataframe(display_df, width="stretch")


def _make_arrow_safe_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy whose object columns are safe for Streamlit Arrow serialization."""
    display_df = df.copy()
    for column in display_df.columns:
        if display_df[column].dtype == "object":
            display_df[column] = display_df[column].map(lambda value: "" if pd.isna(value) else str(value))
    return display_df


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
    if "_daily_research_entry_zones" in tables:
        entry_zones = tables.get("_daily_research_entry_zones", pd.DataFrame())
        if not isinstance(entry_zones, pd.DataFrame):
            entry_zones = pd.DataFrame()
    else:
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
    summary = {"total": int(len(df)), **{key: int(value) for key, value in counts.items()}}
    derived = _derive_watchlist_status_counts(df)
    for key, value in derived.items():
        summary[key] = max(int(summary.get(key, 0) or 0), int(value))
    return summary


def _derive_watchlist_status_counts(df: pd.DataFrame) -> dict[str, int]:
    """Derive watchlist card counts from current user-facing status fields."""
    if df.empty:
        return {}
    text_columns = [
        "watch_status_label",
        "entry_zone_status_cn",
        "daily_note",
        "action_hint",
        "elder_reason",
        "weekly_trend",
        "force_signal",
    ]

    def contains(row: pd.Series, keywords: tuple[str, ...]) -> bool:
        text = " ".join(str(row.get(column) or "") for column in text_columns if column in row.index)
        return any(keyword in text for keyword in keywords)

    status = df.get("watch_status", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str)
    new_flags = pd.Series(False, index=df.index)
    for column in ["new_candidate_flag", "is_new_candidate"]:
        if column in df.columns:
            new_flags = new_flags | df[column].fillna(False).astype(bool)
    return {
        "new_candidate": int(((status == "new_candidate") | new_flags).sum()),
        "strong_watch": int(
            ((status == "strong_watch") | df.apply(lambda row: contains(row, ("位于买入区间", "接近买入区间", "趋势确认")), axis=1)).sum()
        ),
        "wait_pullback": int(
            ((status == "wait_pullback") | df.apply(lambda row: contains(row, ("等待回调", "高于买入区间")), axis=1)).sum()
        ),
        "overheated": int(((status == "overheated") | df.apply(lambda row: contains(row, ("短线过热", "追高风险")), axis=1)).sum()),
        "weakening": int(((status == "weakening") | df.apply(lambda row: contains(row, ("趋势偏弱", "暂缓", "暂不进入")), axis=1)).sum()),
        "invalidated": int(
            ((status == "invalidated") | df.apply(lambda row: contains(row, ("人工复核", "建议复核")), axis=1)).sum()
        ),
    }


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


VALUATION_FIELD_ROLES: dict[str, str] = {
    "turnover_rate": "核心可交易字段",
    "pe": "当前基本面评分核心字段",
    "pb": "估值参考字段",
    "total_mv": "可选诊断字段",
    "circ_mv": "可选诊断字段",
}


def summarize_daily_basic_quality_for_trade_date(daily_basic: pd.DataFrame, trade_date: str | None) -> pd.DataFrame:
    """Summarize daily_basic completeness for one research date."""
    target = _compact_date(trade_date)
    df = _filter_trade_date_frame(daily_basic, target)
    quality = _field_quality(df, list(VALUATION_FIELD_ROLES))
    return pd.DataFrame(
        [
            {
                "字段": field,
                "角色": VALUATION_FIELD_ROLES[field],
                "非空率": stats["non_null_rate"],
                "缺失数量": stats["missing_count"],
                "统计交易日": target or "",
                "样本数量": len(df),
            }
            for field, stats in quality.items()
        ]
    )


def _filter_trade_date_frame(df: pd.DataFrame, trade_date: str | None) -> pd.DataFrame:
    """Filter a DataFrame by compact trade_date, keeping empty shape on missing data."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    target = _compact_date(trade_date)
    if not target or "trade_date" not in df.columns:
        return df.copy()
    dates = df["trade_date"].map(_compact_date)
    return df.loc[dates == target].copy()


def _daily_basic_for_quality(daily_basic: pd.DataFrame | None, trade_date: str | None, tables: dict[str, Any] | None = None) -> pd.DataFrame:
    """Return daily_basic rows for the selected date, reading DuckDB if the light frame lacks them."""
    frame = daily_basic if isinstance(daily_basic, pd.DataFrame) else pd.DataFrame()
    filtered = _filter_trade_date_frame(frame, trade_date)
    if not filtered.empty or not trade_date:
        return filtered
    db_path = str((tables or {}).get("_duckdb_path") or "")
    if not db_path:
        return filtered
    try:
        from core.storage.duckdb_store import DuckDBStore

        store = DuckDBStore(db_path)
        with store.connect(read_only=True) as connection:
            return connection.execute(
                """
                SELECT trade_date, ts_code, turnover_rate, pe, pb, total_mv, circ_mv
                FROM daily_basic
                WHERE replace(CAST(trade_date AS VARCHAR), '-', '') = ?
                """,
                [_compact_date(trade_date)],
            ).fetchdf()
    except Exception:
        return filtered


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

    tables["_duckdb_path"] = str(store.db_path)
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
        research_view = _build_dashboard_daily_research_view(tables, dashboard_price)
        _apply_daily_research_view_to_tables(tables, research_view)
        return {
            "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据（尚未生成本地选股结果）",
            "selection": pd.DataFrame(columns=SELECTION_COLUMNS),
            "stock_basic": tables["stock_basic"],
            "price": dashboard_price,
            "daily_basic": tables["daily_basic"],
            "factor_scores": tables["factor_scores"],
            "backtest": {},
            "watchlist": watchlist,
            "watchlist_snapshot": research_view.watchlist_sheet if research_view is not None else watchlist_snapshot,
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
    research_view = _build_dashboard_daily_research_view(tables, dashboard_price)
    _apply_daily_research_view_to_tables(tables, research_view)
    return {
        "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据",
        "selection": research_view.strategy_sheet if research_view is not None else tables["strategy_result"],
        "stock_basic": tables["stock_basic"],
        "price": dashboard_price,
        "daily_basic": tables["daily_basic"],
        "factor_scores": tables["factor_scores"],
        "backtest": {},
        "watchlist": watchlist,
        "watchlist_snapshot": research_view.watchlist_sheet if research_view is not None else watchlist_snapshot,
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


def _build_dashboard_daily_research_view(tables: dict[str, pd.DataFrame], price_df: pd.DataFrame):
    """Build Streamlit-visible research tables using the workbook display scope."""
    dates = resolve_streamlit_research_dates(tables, read_scheduled_status(DEFAULT_STATUS_PATH), summarize_update_status(tables))
    trade_date = str(dates.get("current_research_trade_date") or "")
    try:
        return build_daily_research_view_from_frames(
            strategy=tables.get("strategy_result", pd.DataFrame()),
            entry_zones=tables.get("entry_zone_snapshots", pd.DataFrame()),
            watchlist=tables.get("_watchlist_snapshot", pd.DataFrame()),
            external_positions=tables.get("external_position_snapshots", pd.DataFrame()),
            daily_price=price_df,
            trade_date=trade_date,
            lookback_status=_read_lookback_status(),
        )
    except Exception:
        return None


def _apply_daily_research_view_to_tables(tables: dict[str, Any], view: Any | None) -> None:
    if view is None:
        return
    tables["_daily_research_trade_date"] = view.trade_date
    tables["_daily_research_selection"] = view.strategy_sheet
    tables["_daily_research_watchlist"] = view.watchlist_sheet
    tables["_daily_research_entry_zones"] = view.entry_sheet
    tables["_daily_research_entry_zone_missing"] = view.entry_missing_sheet
    tables["_daily_research_simulated_advice"] = view.simulated_advice_sheet


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

    tabs = st.tabs(["今日选股", "个股详情", "因子排名", "选股逻辑", "观察池跟踪", "买入区间分析", "模拟交易建议", "外部模拟持仓导入", "持仓池", "策略回测", "数据更新状态", "本地控制台"])
    with tabs[0]:
        _render_section(st, "今日选股", _render_selection_tab, st, dashboard_data.get("selection", pd.DataFrame()), dashboard_data.get("tables", {}))
    with tabs[1]:
        _render_section(st, "个股详情", _render_stock_detail_tab, st, dashboard_data.get("stock_basic", pd.DataFrame()), dashboard_data.get("price", pd.DataFrame()), dashboard_data.get("factor_scores", pd.DataFrame()))
    with tabs[2]:
        _render_section(
            st,
            "因子排名",
            _render_factor_ranking_tab,
            st,
            dashboard_data.get("factor_scores", pd.DataFrame()),
            dashboard_data.get("daily_basic", pd.DataFrame()),
            dashboard_data.get("tables", {}),
        )
    with tabs[3]:
        _render_section(st, "选股逻辑", _render_selection_logic_tab, st, dashboard_data.get("selection", pd.DataFrame()))
    with tabs[4]:
        _render_section(st, "观察池跟踪", _render_watchlist_tab, st, dashboard_data.get("watchlist", pd.DataFrame()), dashboard_data.get("watchlist_snapshot", pd.DataFrame()), dashboard_data.get("tables", {}))
    with tabs[5]:
        _render_section(st, "买入区间分析", _render_entry_zone_tab, st, dashboard_data.get("tables", {}))
    with tabs[6]:
        _render_section(st, "模拟交易建议", _render_simulated_trading_advice_tab, st, dashboard_data.get("tables", {}))
    with tabs[7]:
        _render_section(st, "外部模拟持仓导入", _render_external_positions_tab, st, dashboard_data.get("tables", {}))
    with tabs[8]:
        _render_section(st, "持仓池", _render_positions_tab, st, dashboard_data.get("positions", pd.DataFrame()))
    with tabs[9]:
        _render_section(st, "策略回测", _render_backtest_tab, st, dashboard_data.get("backtest", {}), dashboard_data.get("tables", {}))
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
                    "elder_score": item.get("elder_score"),
                    "action_hint": item.get("action_hint"),
                    "elder_reason": item.get("elder_reason"),
                    "weekly_trend": item.get("weekly_trend"),
                    "daily_pullback": item.get("daily_pullback"),
                    "force_signal": item.get("force_signal"),
                    "elder_ray_signal": item.get("elder_ray_signal"),
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
    st.subheader("当前观察池")
    snapshot = snapshot_df if isinstance(snapshot_df, pd.DataFrame) else pd.DataFrame()
    if watchlist_df.empty and snapshot.empty:
        st.info("暂无 active watch 股票。人工复核导入 watch 决策后会显示在这里。")
        return
    st.caption("刷新观察池：python -m core.jobs.refresh_watchlist_from_selection；每日跟踪：python -m core.jobs.track_watchlist")
    if not snapshot.empty:
        snapshot = _current_watchlist_for_elder_tab(snapshot).head(30)
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
        st.write("当前观察池")
        snapshot = enrich_with_entry_zone_fields(snapshot, tables or {})
        snapshot_columns = [
            "ts_code",
            "name",
            "trade_date",
            "current_close",
            "total_score",
            "total_score_change",
            "selected_count_5d",
            "selected_count_10d",
            "consecutive_selected_days",
            "elder_score",
            "action_hint",
            "elder_reason",
            "weekly_trend",
            "daily_pullback",
            "force_signal",
            "elder_ray_signal",
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
        "elder_score",
        "action_hint",
        "elder_reason",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
    ]
    display_dataframe(st, watchlist_df.head(30), columns=display_columns)


def _render_entry_zone_tab(st: Any, tables: dict[str, Any]) -> None:
    st.subheader("买入区间分析")
    st.caption("仅供个人研究使用，不自动交易。")
    if "_daily_research_entry_zones" in tables:
        entry_zones = tables.get("_daily_research_entry_zones", pd.DataFrame())
        if not isinstance(entry_zones, pd.DataFrame):
            entry_zones = pd.DataFrame()
    else:
        entry_zones = _latest_entry_zone_snapshot(tables.get("entry_zone_snapshots", pd.DataFrame()))
    if entry_zones.empty:
        st.info("暂无买入区间快照。请运行 python -m core.jobs.calculate_entry_zones。")
        return
    missing_zones = tables.get("_daily_research_entry_zone_missing", pd.DataFrame())
    if not isinstance(missing_zones, pd.DataFrame):
        missing_zones = pd.DataFrame()
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
    source_total = len(entry_zones) + len(missing_zones)
    if source_total:
        st.caption(f"展示范围：今日候选 Top10 + 当前观察池 Top30 去重后 {source_total} 只；已生成买入区间 {len(entry_zones)} 只，缺失 {len(missing_zones)} 只。")
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
    if not missing_zones.empty:
        st.write("买入区间缺失说明")
        display_dataframe(st, missing_zones, columns=["ts_code", "name", "source", "missing_reason"])
    st.caption("生成报告：python -m core.jobs.export_entry_zone_report --format all")


def _render_simulated_trading_advice_tab(st: Any, tables: dict[str, Any]) -> None:
    """Render paper-trading advice from the shared daily research view."""
    st.subheader("模拟交易建议")
    st.warning("以下仅用于模拟交易和复盘，不构成真实投资建议，不自动交易。")
    advice = tables.get("_daily_research_simulated_advice", pd.DataFrame())
    if not isinstance(advice, pd.DataFrame) or advice.empty:
        st.info("暂无模拟交易建议。请先生成今日候选、观察池和买入区间数据。")
        return
    counts = summarize_simulated_trading_advice(advice)
    metrics = [
        ("可模拟买入", counts.get("buy", 0)),
        ("等待回调", counts.get("wait_pullback", 0)),
        ("继续观察", counts.get("observe", 0)),
        ("暂缓", counts.get("pause", 0)),
        ("剔除", counts.get("remove", 0)),
        ("已建仓跟踪", counts.get("holding", 0)),
        ("继续持有", counts.get("hold", 0)),
        ("可模拟加仓", counts.get("add", 0)),
        ("减仓", counts.get("reduce", 0)),
        ("卖出", counts.get("sell", 0)),
    ]
    for column, (label, value) in zip(st.columns(len(metrics)), metrics):
        column.metric(label, value)
    display_columns = [
        "ts_code",
        "name",
        "source",
        "source_tags",
        "holding_status",
        "simulated_action",
        "suggested_position",
        "position_action",
        "close",
        "entry_low",
        "entry_high",
        "stop_loss",
        "target_price",
        "reward_risk_ratio",
        "action_hint",
        "elder_score",
        "trigger_condition",
        "invalidation_condition",
        "position_reason",
        "add_condition",
        "reduce_condition",
        "exit_condition",
        "advice_reason",
        "risk_note",
    ]
    display_dataframe(st, advice, columns=display_columns)


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
    st.caption("仅供个人研究和模拟复盘使用，不自动交易，不构成真实投资建议。")
    st.write("模拟交易记录导入")
    st.info("日常只需要维护这张交易流水表，系统会自动计算当前持仓和加权成本。")
    st.download_button(
        "下载模拟交易记录模板.xlsx",
        trade_template_excel_bytes(),
        file_name="模拟交易记录模板.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    uploaded_trades = st.file_uploader("上传模拟交易记录 Excel", type=["xlsx", "csv"], key="external_trade_upload")
    if uploaded_trades is not None:
        try:
            trade_preview = read_uploaded_table(uploaded_trades, getattr(uploaded_trades, "name", ""))
            st.write("上传预览（前 20 行）")
            display_dataframe(st, trade_preview.head(20))
            validation_errors = _validate_uploaded_columns(trade_preview, ["trade_date", "ts_code", "side", "quantity", "price"])
            if validation_errors:
                st.warning("字段校验未通过：" + "；".join(validation_errors))
            elif st.button("导入模拟交易记录", key="import_external_trades_button"):
                _run_external_trade_import(st, trade_preview, getattr(uploaded_trades, "name", ""))
        except Exception as exc:
            st.error(f"读取上传文件失败：{exc}")

    with st.expander("高级：手动校正当前持仓", expanded=False):
        st.caption("仅在需要手动修正当前持仓快照时使用。日常建议维护交易记录，由系统自动重建持仓。")
        st.download_button(
            "下载持仓快照模板.xlsx",
            position_template_excel_bytes(),
            file_name="模拟持仓快照模板.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        uploaded_positions = st.file_uploader("上传持仓快照 Excel", type=["xlsx", "csv"], key="external_position_upload")
        if uploaded_positions is not None:
            try:
                position_preview = read_uploaded_table(uploaded_positions, getattr(uploaded_positions, "name", ""))
                st.write("持仓快照预览（前 20 行）")
                display_dataframe(st, position_preview.head(20))
                validation_errors = _validate_uploaded_columns(position_preview, ["snapshot_date", "ts_code", "quantity", "cost_price"])
                if validation_errors:
                    st.warning("字段校验未通过：" + "；".join(validation_errors))
                elif st.button("导入持仓快照", key="import_external_positions_button"):
                    _run_external_position_import(st, position_preview, getattr(uploaded_positions, "name", ""))
            except Exception as exc:
                st.error(f"读取持仓快照失败：{exc}")

    with st.expander("高级：CSV / 命令行导入", expanded=False):
        trade_csv = dataframe_to_csv(trade_template_frame())
        position_csv = dataframe_to_csv(position_template_frame())
        cols = st.columns(2)
        cols[0].download_button("下载交易记录 CSV 模板", trade_csv, file_name="external_trades_template.csv", mime="text/csv")
        cols[1].download_button("下载持仓快照 CSV 模板", position_csv, file_name="external_position_snapshots_template.csv", mime="text/csv")
        st.code(
            "python -m core.jobs.import_external_trades --file path/to/external_trades.csv\n"
            "python -m core.jobs.import_external_positions --file path/to/external_position_snapshots.csv\n"
            "python -m core.jobs.match_external_positions\n"
            "python -m core.jobs.export_external_position_report --format all"
        )
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


def _validate_uploaded_columns(df: pd.DataFrame, required: list[str]) -> list[str]:
    missing = [column for column in required if column not in df.columns]
    return [f"缺少必填字段：{', '.join(missing)}"] if missing else []


def _run_external_trade_import(st: Any, frame: pd.DataFrame, source_file: str) -> None:
    try:
        result = import_external_trades_and_rebuild_positions_frame(
            frame,
            store=DuckDBStore(get_settings().duckdb_path),
            source_file=source_file,
        )
    except DuckDBStoreError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"导入失败：{exc}")
        return
    _render_external_import_result(st, result)


def _run_external_position_import(st: Any, frame: pd.DataFrame, source_file: str) -> None:
    try:
        result = import_external_positions_frame(
            frame,
            store=DuckDBStore(get_settings().duckdb_path),
            source_file=source_file,
        )
    except DuckDBStoreError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"导入失败：{exc}")
        return
    _render_external_import_result(st, result)


def _render_external_import_result(st: Any, result: dict[str, Any]) -> None:
    if result.get("status") == "success":
        st.success("导入完成，已自动重建模拟持仓。")
    elif result.get("status") == "partial_success":
        st.warning("导入部分完成，请检查错误行。")
    else:
        st.error("导入失败，请检查字段和交易流水。")
    summary = pd.DataFrame(
        [
            {"指标": "导入状态", "值": result.get("status", "")},
            {"指标": "导入交易行数", "值": result.get("imported_rows", 0)},
            {"指标": "无效/跳过行数", "值": result.get("invalid_rows", result.get("skipped_rows", 0))},
            {"指标": "影响股票数量", "值": len(result.get("affected_symbols", []))},
            {"指标": "最新交易日期", "值": result.get("latest_trade_date", "")},
            {"指标": "最新持仓快照日期", "值": result.get("latest_snapshot_date", "")},
            {"指标": "重建持仓行数", "值": result.get("rebuilt_position_rows", "")},
            {"指标": "当前持仓数量", "值": result.get("current_position_count", "")},
        ]
    )
    display_dataframe(st, summary)
    if result.get("warning"):
        st.warning(str(result["warning"]))
    if result.get("error_rows"):
        st.write("错误行")
        display_dataframe(st, pd.DataFrame(result["error_rows"]).head(20))


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


def _render_factor_ranking_tab(
    st: Any,
    factor_df: pd.DataFrame,
    daily_basic: pd.DataFrame | None = None,
    tables: dict[str, Any] | None = None,
) -> None:
    st.subheader("因子排名")
    if factor_df.empty:
        st.info("暂无因子评分数据。")
        return
    dates = sorted(factor_df["trade_date"].dropna().astype(str).unique(), reverse=True) if "trade_date" in factor_df.columns else []
    trade_date = st.selectbox("交易日期", dates) if dates else None
    quality_frame = summarize_daily_basic_quality_for_trade_date(
        _daily_basic_for_quality(daily_basic, trade_date, tables),
        trade_date,
    )
    if not quality_frame.empty:
        st.write("当前选中交易日估值字段完整率")
        display_dataframe(st, quality_frame)
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


def _render_elder_review_tab(st: Any, selection_df: pd.DataFrame, price_df: pd.DataFrame, watchlist_snapshot: pd.DataFrame | None = None) -> None:
    st.subheader("埃尔德复核")
    st.info("Elder 复核已作为今日候选和当前观察池的附加判断字段展示。")
    st.caption("二次技术状态 / 节奏复核层，不覆盖 total_score，不改变今日选股原始排序，也不代表买入优先级。")


def format_elder_review_display(review_df: pd.DataFrame, *, source: str = "今日候选") -> pd.DataFrame:
    """Return an Elder review display table with unambiguous ordering fields."""
    if review_df.empty:
        return review_df.copy()
    result = review_df.copy().reset_index(drop=True)
    result["source"] = source
    if "review_scope" not in result.columns:
        result["review_scope"] = source
    if "review_status" not in result.columns:
        result["review_status"] = result.get("elder_score", pd.Series(index=result.index)).notna().map({True: "已复核", False: "未复核"})
    if "review_reason" not in result.columns:
        result["review_reason"] = result.get("elder_reason", "")
    missing_reason = result["review_reason"].isna() | (result["review_reason"].astype(str).str.strip() == "")
    missing_score = pd.to_numeric(result.get("elder_score"), errors="coerce").isna() if "elder_score" in result.columns else pd.Series([True] * len(result), index=result.index)
    result.loc[missing_reason & missing_score, "review_reason"] = "暂无埃尔德复核分；该行未找到可用复核结果或数据样本不足。"
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


def _with_review_scope_for_display(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    result = frame.copy()
    if not result.empty:
        result["review_scope"] = scope
    return result


def _current_watchlist_for_elder_tab(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty or "watch_status" not in snapshot.columns:
        return pd.DataFrame()
    if "trade_date" in snapshot.columns:
        dates = snapshot["trade_date"].dropna().astype(str)
        if not dates.empty:
            snapshot = snapshot[snapshot["trade_date"].astype(str) == dates.max()].copy()
    current_statuses = {"active", "entry_zone", "triggered", "active_watch", "strong_watch", "wait_pullback", "near_buy_zone"}
    result = snapshot[snapshot["watch_status"].fillna("active").astype(str).isin(current_statuses)].copy()
    if "ts_code" in result.columns:
        result = result.drop_duplicates("ts_code", keep="last")
    if "trade_date" not in result.columns and "latest_trade_date" in result.columns:
        result["trade_date"] = result["latest_trade_date"]
    return result.reset_index(drop=True).head(30)


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


def _render_backtest_tab(st: Any, backtest: dict[str, Any], tables: dict[str, pd.DataFrame] | None = None) -> None:
    st.subheader("策略回测")
    _render_lookback_analysis_section(st, tables or {})
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

    _safe_render_status_block(st, "数据质量看板", _render_status_quality_main, st, scheduled, status)
    _safe_render_status_block(st, "交易日历状态", _render_trade_calendar_status, st, tables, status)
    _safe_render_status_block(st, "数据更新操作", _render_user_level_data_update_actions, st, scheduled, status)
    _safe_render_status_block(st, "高级信息", _render_status_advanced_sections, st, tables, scheduled, legacy_status)


def _safe_render_status_block(st: Any, label: str, func: Any, *args: Any) -> None:
    """Render one status-page block without taking down the whole page."""
    try:
        func(*args)
    except Exception as exc:
        st.error(f"{label} 加载失败：{exc}")


def _render_trade_calendar_status(st: Any, tables: dict[str, pd.DataFrame], status: dict[str, Any]) -> None:
    """Render local A-share trading-calendar status separately from coverage."""
    st.write("交易日历状态")
    calendar_status = _streamlit_trade_calendar_status(tables, status)
    display_dataframe(st, pd.DataFrame([_trade_calendar_status_row(calendar_status)]))
    if not calendar_status.get("calendar_exists") or not calendar_status.get("covers_today") or not calendar_status.get("covers_next_30_days"):
        st.warning("交易日历缺失或覆盖不足。请运行 python -m core.jobs.update_trade_calendar 同步交易日历。")


def _streamlit_trade_calendar_status(tables: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    db_path = str(tables.get("_duckdb_path") or "")
    if not db_path:
        return {
            "calendar_exists": False,
            "calendar_source": status.get("planned_update_calendar_source") or "暂无",
            "coverage_start": "",
            "coverage_end": "",
            "covers_today": False,
            "covers_next_30_days": False,
            "recent_open_trade_date": "",
            "next_open_trade_date": "",
            "target_trade_date": status.get("planned_update_target_date") or "",
            "reason": status.get("planned_update_reason") or "",
        }
    try:
        from app.config import get_settings
        from core.storage.duckdb_store import DuckDBStore

        settings = get_settings()
        return summarize_trade_calendar_status(
            DuckDBStore(db_path),
            cutoff_time=getattr(settings, "daily_update_cutoff_time", "18:00") or "18:00",
        )
    except Exception:
        return {
            "calendar_exists": False,
            "calendar_source": status.get("planned_update_calendar_source") or "暂无",
            "coverage_start": "",
            "coverage_end": "",
            "covers_today": False,
            "covers_next_30_days": False,
            "recent_open_trade_date": "",
            "next_open_trade_date": "",
            "target_trade_date": status.get("planned_update_target_date") or "",
            "reason": "交易日历状态读取失败。",
        }


def _trade_calendar_status_row(calendar_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "交易日历来源": calendar_status.get("calendar_source") or "暂无",
        "trade_calendar 是否存在": "是" if calendar_status.get("calendar_exists") else "否",
        "覆盖起始日期": calendar_status.get("coverage_start") or "暂无",
        "覆盖结束日期": calendar_status.get("coverage_end") or "暂无",
        "覆盖今天": "是" if calendar_status.get("covers_today") else "否",
        "覆盖未来 30 天": "是" if calendar_status.get("covers_next_30_days") else "否",
        "最近一个交易日": calendar_status.get("recent_open_trade_date") or "暂无",
        "下一个交易日": calendar_status.get("next_open_trade_date") or "暂无",
        "计划更新目标日期": calendar_status.get("target_trade_date") or "暂无",
        "判断说明": calendar_status.get("reason") or "暂无",
    }


def _status_page_quality_snapshot(tables: dict[str, pd.DataFrame], scheduled: dict[str, Any], legacy_status: dict[str, Any]) -> dict[str, Any]:
    """Return the authoritative quality snapshot for the status page."""
    dates = resolve_streamlit_research_dates(tables, scheduled, legacy_status)
    planned_date = dates["planned_update_target_date"]
    current_research_date = dates["current_research_trade_date"]
    latest_local_date = dates["latest_local_trade_date"]
    if scheduled.get("latest_daily_price_symbol_count") is not None:
        scheduled_date = _compact_date(scheduled.get("latest_completed_trade_date") or scheduled.get("research_trade_date") or "")
        if not (current_research_date and scheduled_date > current_research_date):
            result = dict(scheduled)
            result.setdefault("planned_update_target_date", planned_date or scheduled_date)
            result.setdefault("planned_update_trade_date", planned_date or scheduled_date)
            result.setdefault("current_research_trade_date", current_research_date or scheduled_date)
            result.setdefault("latest_local_trade_date", latest_local_date or current_research_date or scheduled_date)
            result.setdefault("planned_update_reason", dates.get("planned_update_reason") or "")
            result.setdefault("planned_update_calendar_source", dates.get("planned_update_calendar_source") or "")
            if dates["date_status_note"]:
                result.setdefault("formal_result_warning_reason", dates["date_status_note"])
            return result
    db_path = str(tables.get("_duckdb_path") or legacy_status.get("duckdb_path") or "")
    target_date = current_research_date or planned_date
    if db_path and target_date:
        try:
            result = build_data_quality_snapshot(
                db_path=db_path,
                research_trade_date=target_date,
                latest_completed_trade_date=target_date,
            )
            result["planned_update_target_date"] = planned_date or target_date
            result["planned_update_trade_date"] = planned_date or target_date
            result["current_research_trade_date"] = target_date
            result["latest_local_trade_date"] = latest_local_date or current_research_date or target_date
            result["planned_update_reason"] = dates.get("planned_update_reason") or ""
            result["planned_update_calendar_source"] = dates.get("planned_update_calendar_source") or ""
            if dates["date_status_note"]:
                result["formal_result_warning_reason"] = dates["date_status_note"]
            return result
        except Exception:
            pass
    if target_date:
        fallback = _status_snapshot_from_loaded_tables(tables, target_date, scheduled, legacy_status, dates)
        if fallback:
            return fallback
    return {
        "data_quality_status": "unknown",
        "formal_result_usable": False,
        "formal_result_warning_reason": "当前缺少数据质量快照，请运行刷新数据状态或检查 DuckDB。",
        "configured_symbol_count": int(legacy_status.get("configured_symbol_count", 0) or 0),
        "research_trade_date": target_date,
        "latest_completed_trade_date": target_date,
        "planned_update_target_date": planned_date or target_date,
        "planned_update_trade_date": planned_date or target_date,
        "current_research_trade_date": target_date,
        "latest_local_trade_date": latest_local_date or current_research_date or target_date,
        "planned_update_reason": dates.get("planned_update_reason") or "",
        "planned_update_calendar_source": dates.get("planned_update_calendar_source") or "",
        "formal_result_warning_reason": dates["date_status_note"] or "当前缺少数据质量快照，请运行刷新数据状态或检查 DuckDB。",
    }


def _status_snapshot_from_loaded_tables(
    tables: dict[str, Any],
    trade_date: str,
    scheduled: dict[str, Any],
    legacy_status: dict[str, Any],
    dates: dict[str, Any],
) -> dict[str, Any]:
    """Build a current-date coverage snapshot from already loaded dashboard tables."""
    total = int(scheduled.get("configured_symbol_count") or legacy_status.get("configured_symbol_count") or tables.get("_configured_symbol_count", 0) or 0)
    if not total:
        return {}
    snapshot: dict[str, Any] = {
        "data_quality_snapshot_source": "streamlit_loaded_tables",
        "configured_symbol_count": total,
        "research_trade_date": trade_date,
        "latest_completed_trade_date": trade_date,
        "planned_update_target_date": dates.get("planned_update_target_date") or trade_date,
        "planned_update_trade_date": dates.get("planned_update_trade_date") or dates.get("planned_update_target_date") or trade_date,
        "current_research_trade_date": trade_date,
        "latest_local_trade_date": dates.get("latest_local_trade_date") or trade_date,
        "planned_update_reason": dates.get("planned_update_reason") or "",
        "planned_update_calendar_source": dates.get("planned_update_calendar_source") or "",
        "formal_result_usable": False,
        "formal_result_warning_reason": dates.get("date_status_note") or "当前使用页面已加载表估算覆盖率，请运行刷新数据状态获取完整快照。",
    }
    table_specs = [
        ("daily_price", "latest_daily_price_symbol_count", "missing_latest_daily_price_symbol_count", "latest_daily_price_coverage_rate"),
        ("daily_basic", "latest_daily_basic_symbol_count", "missing_latest_daily_basic_symbol_count", "latest_daily_basic_coverage_rate"),
        ("adj_factor", "latest_adj_factor_symbol_count", "missing_latest_adj_factor_symbol_count", "latest_adj_factor_coverage_rate"),
    ]
    counts = {}
    for table_name, count_key, missing_key, rate_key in table_specs:
        count = _count_distinct_symbols_at_trade_date(tables.get(table_name, pd.DataFrame()), trade_date)
        counts[count_key] = count
        snapshot[count_key] = count
        snapshot[missing_key] = max(total - count, 0)
        snapshot[rate_key] = float(count / total) if total else 0.0
    all_required = min(counts.values()) if counts else 0
    snapshot["latest_all_required_tables_symbol_count"] = all_required
    snapshot["missing_latest_all_required_tables_symbol_count"] = max(total - all_required, 0)
    snapshot["latest_all_required_tables_coverage_rate"] = float(all_required / total) if total else 0.0
    snapshot["data_quality_status"] = "ok" if snapshot["latest_daily_price_coverage_rate"] >= 0.8 else "poor"
    return snapshot


def _count_distinct_symbols_at_trade_date(frame: Any, trade_date: str) -> int:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "ts_code" not in frame.columns or "trade_date" not in frame.columns:
        return 0
    target = _compact_date(trade_date)
    dates = frame["trade_date"].map(_compact_date)
    return int(frame.loc[dates == target, "ts_code"].dropna().astype(str).nunique())


def resolve_streamlit_research_dates(
    tables: dict[str, Any] | None = None,
    scheduled: dict[str, Any] | None = None,
    legacy_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the dates Streamlit should use for research views and update status.

    The planned update target uses the same A-share trading-calendar helper as
    scheduled updates; the research display date remains the latest local
    selection/price date.
    """
    tables = tables or {}
    scheduled = scheduled or {}
    legacy_status = legacy_status or {}
    latest_local_trade_date = _first_compact_date(
        legacy_status.get("latest_trade_date"),
        legacy_status.get("latest_price_date"),
        tables.get("_latest_trade_date"),
        tables.get("_latest_price_date"),
        _latest_date(tables.get("daily_price", pd.DataFrame()), "trade_date") if isinstance(tables.get("daily_price"), pd.DataFrame) else "",
    )
    current_research_trade_date = _first_compact_date(
        tables.get("_daily_research_trade_date"),
        legacy_status.get("latest_selection_date"),
        _latest_date(tables.get("strategy_result", pd.DataFrame()), "trade_date") if isinstance(tables.get("strategy_result"), pd.DataFrame) else "",
        latest_local_trade_date,
    )
    update_target = _resolve_update_target_for_streamlit(tables)
    planned_update_target_date = _first_compact_date(
        update_target.get("target_trade_date"),
        scheduled.get("latest_completed_trade_date"),
        scheduled.get("research_trade_date"),
        scheduled.get("planned_update_target_date"),
        scheduled.get("planned_update_trade_date"),
    )
    note = str(update_target.get("reason") or "")
    if planned_update_target_date and current_research_trade_date and planned_update_target_date > current_research_trade_date:
        suffix = f"计划目标日期 {planned_update_target_date} 尚未完成更新，当前研究仍使用 {current_research_trade_date}。"
        note = f"{note} {suffix}".strip()
    return {
        "latest_local_trade_date": latest_local_trade_date,
        "current_research_trade_date": current_research_trade_date,
        "planned_update_target_date": planned_update_target_date,
        "planned_update_trade_date": planned_update_target_date,
        "planned_target_is_current": bool(planned_update_target_date and planned_update_target_date == current_research_trade_date),
        "planned_update_reason": str(update_target.get("reason") or ""),
        "planned_update_calendar_source": str(update_target.get("calendar_source") or ""),
        "date_status_note": note,
    }


def _resolve_update_target_for_streamlit(tables: dict[str, Any]) -> dict[str, Any]:
    db_path = str(tables.get("_duckdb_path") or "")
    if not db_path:
        return {}
    try:
        from app.config import get_settings
        from core.storage.duckdb_store import DuckDBStore

        settings = get_settings()
        decision = resolve_update_target_trade_date(
            DuckDBStore(db_path),
            cutoff_time=getattr(settings, "daily_update_cutoff_time", "18:00") or "18:00",
        )
        return decision.to_dict()
    except Exception:
        return {}


def _first_compact_date(*values: Any) -> str:
    for value in values:
        compact = _compact_date(value)
        if compact:
            return compact
    return ""


def _compact_date(value: Any) -> str:
    text = str(value or "").strip()
    return text.replace("-", "")[:8] if text else ""


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
    st.write("当前研究展示日期覆盖")
    display_dataframe(st, _status_latest_coverage_frame(status))
    st.write("复权语义")
    display_dataframe(st, pd.DataFrame([_status_adjustment_semantics_row(status)]))
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
        "最新本地可用交易日": status.get("latest_local_trade_date") or "暂无",
        "计划更新目标日期": status.get("planned_update_target_date") or status.get("planned_update_trade_date") or "暂无",
        "计划目标判断来源": status.get("planned_update_calendar_source") or "暂无",
        "当前研究展示日期": status.get("current_research_trade_date") or status.get("latest_completed_trade_date") or status.get("research_trade_date") or "暂无",
        "数据质量": status.get("data_quality_status") or "unknown",
        "核心价格行情": "可用" if status.get("core_price_data_usable") is True else "不足",
        "技术指标研究": "可用" if status.get("technical_research_usable") is True else "不足",
        "增强数据": "可用" if status.get("enhanced_data_usable") is True else "不完整",
        "估值/市值数据": "可用" if status.get("valuation_data_usable") is True else "不完整",
        "正式全字段结果": "可用" if status.get("formal_full_market_result_usable") is True else "不可用",
        "核心行情状态": status.get("core_price_data_status") or _core_price_status(status),
        "增强数据状态": status.get("enhanced_data_status") or _enhanced_data_status(status),
        "主要提示": status.get("formal_result_warning_reason") or status.get("planned_update_reason") or scheduled.get("failure_reason") or "暂无",
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


def _status_adjustment_semantics_row(status: dict[str, Any]) -> dict[str, Any]:
    source = status.get("adj_factor_source") or "暂无"
    note = status.get("adj_factor_user_note") or "暂无明确复权语义。"
    return {
        "adj_factor 来源": source,
        "是否需要额外复权因子": "是" if status.get("adj_factor_required") is True else "否",
        "是否真实复权因子": "是" if status.get("adj_factor_is_real_factor") is True else "否",
        "价格复权状态": status.get("price_adjustment_status") or "暂无",
        "用户说明": status.get("price_adjustment_user_note") or note,
    }


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
            {"模块": "综合分", "可用股票数量": int(status.get("factor_ready_symbol_count", 0) or 0), "说明": "通过股票池过滤并生成 factor_scores 的股票数量，不等同于行情覆盖数量"},
            {"模块": "埃尔德复核", "可用股票数量": int(status.get("elder_ready_symbol_count", 0) or 0), "说明": "最新观察池 / 复核快照可用"},
            {"模块": "买入区间", "可用股票数量": int(status.get("entry_zone_ready_symbol_count", 0) or 0), "说明": "买入区间快照可用"},
            {"模块": "自动回看", "可用股票数量": int(status.get("lookback_ready_symbol_count", 0) or 0), "说明": "候选且历史样本足够"},
        ]
    )


def _status_run_result_row(scheduled: dict[str, Any]) -> dict[str, Any]:
    return {
        "更新类型": scheduled.get("update_mode") or "暂无",
        "开始时间": scheduled.get("started_at") or "暂无",
        "结束时间": scheduled.get("finished_at") or "暂无",
        "已处理数量": scheduled.get("processed_symbol_count", 0),
        "计划处理数量": scheduled.get("total_symbol_count", 0),
        "失败数量": scheduled.get("update_failed_symbol_count", 0),
        "空数据数量": scheduled.get("empty_data_symbol_count", 0),
        "网络超时数量": scheduled.get("network_timeout_count", 0),
        "每日研究工作簿": scheduled.get("workbook_path") or "暂无",
    }


def _render_status_buttons(st: Any) -> None:
    st.write("按钮区")
    st.markdown("**1. 只读状态 / 诊断**")
    st.caption("不联网；不写 DuckDB；不生成 Excel；不改变今日研究结果。")
    col1, col2, col3, col4 = st.columns(4)
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


def _render_user_level_data_update_actions(st: Any, scheduled: dict[str, Any], status: dict[str, Any]) -> None:
    """Render only user-level actions; provider choice stays automatic."""
    st.write("数据更新操作")
    st.info("系统会在后台自动判断可用免费数据源；你不需要选择具体接口。")
    display_dataframe(st, pd.DataFrame([_automatic_source_summary_row(scheduled, status)]))
    _render_market_data_update_progress(st, read_market_data_progress(DEFAULT_PROGRESS_PATH))
    st.write("最近一次自动尝试摘要")
    display_dataframe(st, _automatic_attempt_summary_frame(scheduled))
    st.write("下一步建议")
    st.info(scheduled.get("suggested_action") or _next_data_update_suggestion(status))
    col1, col2, col3, col4 = st.columns(4)
    latest_update_args = ["--goal", "latest", "--provider", "auto", "--batch-size", "100", "--batch-timeout-seconds", "600", "--symbol-timeout-seconds", "60", "--continue-missing-latest", "--format", "text"]
    if col1.button("一键更新最新交易日数据", key="auto_update_latest_trade_date"):
        _run_streaming_console_action(
            st,
            "一键更新最新交易日数据",
            "update_market_data",
            latest_update_args,
            success_message="最新交易日数据更新完成。请刷新页面查看数据质量。",
        )
    if col2.button("补历史行情缺口", key="auto_repair_history_gap"):
        _run_streaming_console_action(
            st,
            "补历史行情缺口",
            "update_market_data",
            ["--goal", "history", "--provider", "auto", "--batch-size", "100", "--batch-timeout-seconds", "600", "--symbol-timeout-seconds", "60", "--format", "text"],
            success_message="历史行情缺口补齐命令执行完成。请刷新页面查看数据质量。",
        )
    if col3.button("运行数据源诊断", key="run_user_level_data_source_diagnosis"):
        _run_streaming_console_action(
            st,
            "运行数据源诊断",
            "diagnose_data_source_network",
            ["--format", "text"],
            success_message="数据源诊断完成。",
        )
    if col4.button("上传 CSV / Excel 导入行情", key="show_market_data_upload"):
        st.session_state["show_market_data_upload"] = True
    if st.session_state.get("show_market_data_upload"):
        st.caption("本地文件；会写 DuckDB；不联网；不生成 Excel；导入后刷新数据质量。")
        table_name = st.selectbox("导入目标", ["daily_price", "daily_basic", "adj_factor"], format_func=_market_table_label, index=0)
        uploaded = st.file_uploader("选择本地行情文件", type=["csv", "xlsx", "xls"], key="market_data_manual_upload")
        if uploaded is not None and st.button("确认导入本地行情文件", key="import_uploaded_market_data"):
            suffix = Path(uploaded.name).suffix or ".csv"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(uploaded.getvalue())
                temp_path = handle.name
            _run_streaming_console_action(
                st,
                "导入本地行情文件",
                "import_market_data",
                ["--file", temp_path, "--table", table_name, "--format", "text"],
                success_message="本地行情文件导入完成。请刷新页面查看数据质量。",
            )


def _automatic_source_summary_row(scheduled: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    latest_success = _friendly_provider_name(str(scheduled.get("latest_success_provider") or ""))
    failure = scheduled.get("latest_provider_failure_reason") or ""
    if latest_success != "暂无":
        result = f"本次使用：{latest_success}。"
    elif failure:
        result = "所有自动数据源均失败，请尝试导入本地行情文件。"
    else:
        result = "尚无自动数据源更新记录。"
    usable = status.get("formal_result_usable") is True
    return {
        "当前数据质量": status.get("data_quality_status") or "unknown",
        "正式全市场研究结果可用": "是" if usable else "否",
        "最新交易日覆盖率": f"{float(status.get('latest_daily_price_coverage_rate', 0.0) or 0.0):.2%}",
        "历史行情覆盖率": f"{float(status.get('any_daily_price_coverage_rate', 0.0) or 0.0):.2%}",
        "后台自动选择结果": result,
        "提示": "本次仅完成部分更新，尚不能作为正式全市场研究结果。" if not usable else "数据覆盖满足正式研究口径。",
    }


def _render_market_data_update_progress(st: Any, progress: dict[str, Any]) -> None:
    st.write("数据更新实时进度")
    if not progress:
        st.caption("暂无正在运行的数据更新任务。")
        return
    total = int(progress.get("total_symbol_count", 0) or 0)
    processed = int(progress.get("processed_symbol_count", 0) or 0)
    ratio = min(1.0, processed / total) if total > 0 else 0.0
    st.progress(ratio)
    elapsed = _elapsed_seconds(progress.get("started_at"), progress.get("finished_at") or progress.get("last_heartbeat_at"))
    display_dataframe(
        st,
        pd.DataFrame(
            [
                {
                    "运行状态": "运行中" if progress.get("running") else _attempt_status_cn(str(progress.get("status") or "")),
                    "当前数据源": progress.get("current_provider_display_name") or "暂无",
                    "当前股票": progress.get("current_symbol") or "暂无",
                    "已处理数量": processed,
                    "总数量": total,
                    "成功数量": int(progress.get("success_symbol_count", 0) or 0),
                    "失败数量": int(progress.get("failed_symbol_count", 0) or 0),
                    "跳过数量": int(progress.get("skipped_symbol_count", 0) or 0),
                    "写入行数": int(progress.get("written_row_count", 0) or 0),
                    "已耗时": f"{elapsed} 秒" if elapsed is not None else "暂无",
                    "最近更新时间": progress.get("last_heartbeat_at") or "暂无",
                    "批次编号": progress.get("batch_id") or "暂无",
                    "批次大小": int(progress.get("batch_size", 0) or 0),
                    "批次超时": int(progress.get("batch_timeout_seconds", 0) or 0),
                    "单股超时": int(progress.get("symbol_timeout_seconds", 0) or 0),
                }
            ]
        ),
    )
    if progress.get("stale_detected") or progress.get("timeout") or str(progress.get("status") or "") == "interrupted":
        st.warning(progress.get("suggested_action") or "本批更新已中断，可稍后继续补缺口。")
    provider_rows = []
    for item in progress.get("provider_progress") or []:
        provider_rows.append(
            {
                "数据来源": item.get("display_name") or "暂无",
                "状态": _attempt_status_cn(str(item.get("status") or "")),
                "已处理数量": int(item.get("processed_symbol_count", 0) or 0),
                "总数量": int(item.get("total_symbol_count", 0) or 0),
                "成功数量": int(item.get("success_symbol_count", 0) or 0),
                "失败数量": int(item.get("failed_symbol_count", 0) or 0),
                "跳过数量": int(item.get("skipped_symbol_count", 0) or 0),
                "写入行数": int(item.get("written_row_count", 0) or 0),
            }
        )
    display_dataframe(st, pd.DataFrame(provider_rows) if provider_rows else pd.DataFrame(columns=["数据来源", "状态", "已处理数量", "总数量", "成功数量", "失败数量", "跳过数量", "写入行数"]))
    failure_summary = progress.get("failure_summary") or {}
    if isinstance(failure_summary, dict) and failure_summary:
        st.write("失败原因摘要")
        display_dataframe(
            st,
            pd.DataFrame(
                [
                    {"失败类型": _failure_type_cn(str(key)), "数量": int(value or 0)}
                    for key, value in failure_summary.items()
                ]
            ),
        )
        examples = progress.get("failure_examples") or {}
        example_rows = []
        if isinstance(examples, dict):
            for key, values in examples.items():
                example_rows.append({"失败类型": _failure_type_cn(str(key)), "样例": "、".join([str(item) for item in list(values or [])[:20]])})
        if example_rows:
            display_dataframe(st, pd.DataFrame(example_rows))
    if progress.get("running"):
        st.caption("更新运行中，页面每 2 秒刷新一次。")
        time.sleep(2)
        st.rerun()


def _elapsed_seconds(started_at: Any, ended_at: Any) -> int | None:
    try:
        start = pd.to_datetime(started_at)
        end = pd.to_datetime(ended_at)
    except Exception:
        return None
    if pd.isna(start) or pd.isna(end):
        return None
    return max(0, int((end - start).total_seconds()))


def _failure_type_cn(value: str) -> str:
    return {
        "no_data": "接口无数据",
        "unsupported_symbol": "代码不支持",
        "timeout": "请求超时",
        "connection_error": "网络连接错误",
        "provider_error": "数据源返回错误",
        "unknown_error": "未知错误",
    }.get(value, value)


def _automatic_attempt_summary_frame(status: dict[str, Any]) -> pd.DataFrame:
    attempts = list(status.get("provider_attempts") or [])
    by_provider = {str(item.get("provider")): item for item in attempts}
    rows = []
    for provider, label in [
        ("akshare_kline", "历史行情接口"),
        ("akshare_spot_snapshot", "实时行情快照"),
        ("baostock", "历史行情兜底"),
        ("manual_import", "本地导入"),
    ]:
        item = by_provider.get(provider) or {}
        rows.append(
            {
                "数据来源": label,
                "结果": _attempt_status_cn(str(item.get("status") or ("available" if provider == "manual_import" else "not_tried"))),
                "写入行数": int(item.get("written_row_count", 0) or 0),
                "说明": _attempt_user_message(provider, item),
            }
        )
    return pd.DataFrame(rows)


def _attempt_status_cn(status: str) -> str:
    return {
        "success": "成功",
        "partial": "部分成功",
        "failed": "失败",
        "skipped": "跳过",
        "unavailable": "不可用",
        "available": "可用",
        "not_tried": "未尝试",
    }.get(status, status or "未尝试")


def _attempt_user_message(provider: str, item: dict[str, Any]) -> str:
    if provider == "manual_import" and not item:
        return "网络数据源不可用时，可上传本地 CSV / Excel。"
    status = str(item.get("status") or "")
    if provider == "akshare_kline" and status == "failed":
        return "东方财富 K 线接口不可用，系统已继续尝试兜底数据源。"
    if provider == "akshare_spot_snapshot" and status == "skipped":
        return "未到收盘安全写入时间，或本次已有其他数据源完成。"
    if provider == "akshare_spot_snapshot" and status in {"failed", "unavailable"}:
        message = str(item.get("message") or item.get("error_message") or "")
        if "非交易日" in message:
            return message
        return "收盘行情快照暂不可用。"
    if provider == "baostock" and status == "unavailable":
        return "历史行情兜底源当前不可用。"
    if provider == "manual_import":
        return "网络数据源不可用时，可上传本地 CSV / Excel。"
    if status == "success":
        return "已写入本地数据库。"
    if status == "failed":
        return "数据源请求失败，技术细节见高级诊断。"
    message = str(item.get("message") or item.get("error_message") or "")
    forbidden = ["used_url", "curl", "stderr", "stdout", "http_status", "ipv4", "ipv6", "proxy", "clash", "push2his", "empty_reply", "proxyerror", "traceback"]
    if any(term in message.lower() for term in forbidden):
        return "技术细节见高级诊断。"
    return message or "暂无"


def _next_data_update_suggestion(status: dict[str, Any]) -> str:
    if not status.get("provider_attempts"):
        return "最新交易日行情仍不足，建议先点击【一键更新最新交易日数据】。"
    if not status.get("formal_result_usable"):
        return "自动数据源暂不可用或覆盖不足，可使用【导入本地行情文件】或稍后重试。"
    if int(status.get("history_missing_symbol_count", 0) or 0) > 0:
        return "历史行情存在缺口，可使用【补历史行情缺口】分批修复。"
    return "当前数据质量满足正式研究口径。"


def _friendly_provider_name(provider: str) -> str:
    return {
        "akshare_kline": "历史行情接口",
        "akshare_spot_snapshot": "实时行情快照兜底",
        "baostock": "历史行情免费兜底",
        "csv_manual_import": "本地 CSV 导入",
        "excel_manual_import": "本地 Excel 导入",
        "auto": "后台自动判断",
    }.get(provider, "暂无")


def _core_price_status(status: dict[str, Any]) -> str:
    rate = float(status.get("latest_daily_price_coverage_rate", 0.0) or 0.0)
    return "可用" if rate >= 0.8 else "不足"


def _enhanced_data_status(status: dict[str, Any]) -> str:
    basic = float(status.get("latest_daily_basic_coverage_rate", 0.0) or 0.0)
    adj = float(status.get("latest_adj_factor_coverage_rate", 0.0) or 0.0)
    return "完整" if basic >= 0.8 and adj >= 0.8 else "不完整"


def _market_table_label(table_name: str) -> str:
    return {
        "daily_price": "日行情",
        "daily_basic": "估值 / 基础行情",
        "adj_factor": "复权因子",
    }.get(table_name, table_name)


def _render_status_advanced_sections(st: Any, tables: dict[str, pd.DataFrame], scheduled: dict[str, Any], status: dict[str, Any]) -> None:
    with st.expander("高级：自动数据源技术诊断", expanded=False):
        _render_free_provider_fallback_section(st, scheduled, status)
    with st.expander("高级：只读诊断和自动更新补跑", expanded=False):
        _render_status_buttons(st)
    with st.expander("高级：全市场批量补数据参数", expanded=False):
        _render_full_batch_update_section(st, status)
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


def _render_free_provider_fallback_section(st: Any, scheduled: dict[str, Any], status: dict[str, Any]) -> None:
    """Render free-provider fallback controls for Task 57D."""
    st.subheader("自动数据源技术诊断")
    st.caption("以下是技术诊断信息，默认折叠。普通使用只需点击主页面的一键更新或补历史缺口。")
    attempts = list(scheduled.get("provider_attempts") or [])
    latest_attempt = attempts[-1] if attempts else {}
    st.write(
        {
            "自动兜底顺序": "AKShare K 线 -> AKShare 实时行情快照 -> BaoStock daily_price -> CSV / Excel 手动导入提示",
            "Tushare": "可选，不推荐作为默认方案；未配置 token 不报错",
            "最近成功 provider": scheduled.get("latest_success_provider") or "暂无",
            "最近失败 provider": latest_attempt.get("provider") if latest_attempt and not latest_attempt.get("success") else "暂无",
            "最近失败原因": scheduled.get("latest_provider_failure_reason") or "暂无",
            "最新数据质量": status.get("data_quality_status") or "unknown",
        }
    )
    if attempts:
        st.json({"provider_attempts": attempts[-10:]})
    else:
        st.info("暂无 provider_attempts。")


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


def _render_lookback_analysis_section(st: Any, tables: dict[str, Any] | None = None) -> None:
    """Render automatic lookback analysis status and controls."""
    st.subheader("自动回看分析")
    st.write("自动回看状态摘要")
    tables = tables or {}
    legacy_status = summarize_update_status(tables) if tables else {}
    dates = resolve_streamlit_research_dates(tables, read_scheduled_status(DEFAULT_STATUS_PATH), legacy_status)
    current_research_date = dates.get("current_research_trade_date") or ""
    if current_research_date:
        st.caption(f"当前研究日期：{current_research_date}")
    if dates.get("date_status_note"):
        st.info(str(dates["date_status_note"]))
    status = _read_lookback_status()
    if not status:
        st.info("尚无自动回看记录。可以点击运行自动回看分析生成结果。")
    else:
        display = build_lookback_status_display(status, current_research_date)
        if display["is_current"]:
            st.success("当前研究日期已有有效自动回看摘要。")
        else:
            st.warning("需要刷新当日回看。最近回看仅作为历史参考，不代表当前研究日期。")
        st.write(display["summary"])
        report_path = Path(str(status.get("generated_report_path") or ""))
        if display["is_current"] and status.get("generated_report_path") and report_path.exists():
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
            if display["is_current"]:
                st.warning("最近回看报告文件不存在，可能已清理。")
            elif not report_path.exists():
                st.warning("最近历史回看报告文件不存在，可能已清理。")
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
