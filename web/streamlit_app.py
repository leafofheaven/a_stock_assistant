"""Streamlit dashboard for A-share selection research results."""

from __future__ import annotations

import sys
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
from core.runtime.command_runner import open_project_path, run_command_streaming
from core.runtime.progress import parse_progress_line
from core.technical.elder import build_elder_review

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
    latest_workflow_report = tables.get("_latest_workflow_report")
    latest_daily_workflow_report = tables.get("_latest_daily_workflow_report")
    latest_selection_review_report = tables.get("_latest_selection_review_report")
    latest_review_template = tables.get("_latest_review_template")
    latest_watchlist_report = tables.get("_latest_watchlist_report")
    latest_watchlist_tracking_report = tables.get("_latest_watchlist_tracking_report")
    local_state = tables.get("_local_state")
    return {
        "latest_price_date": _latest_date(daily_price, "trade_date"),
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
    from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError

    settings = get_settings()
    if settings.data_provider == "sample":
        data = sample_dashboard_data()
        data.setdefault("tables", {})["_latest_workflow_report"] = load_latest_workflow_report()
        data.setdefault("tables", {})["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
        data.setdefault("tables", {})["_latest_selection_review_report"] = load_latest_selection_review_report()
        data.setdefault("tables", {})["_latest_review_template"] = template_metadata(latest_review_template_path())
        data.setdefault("tables", {})["_latest_watchlist_report"] = load_latest_watchlist_report()
        data.setdefault("tables", {})["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
        data.setdefault("tables", {})["_local_state"] = _safe_local_state()
        data.setdefault("watchlist", pd.DataFrame())
        data.setdefault("watchlist_snapshot", pd.DataFrame())
        return data

    store = DuckDBStore(settings.duckdb_path)
    if not store.db_path.exists():
        data = sample_dashboard_data()
        data["data_source"] = "sample 数据（演示，真实 DuckDB 文件不存在）"
        data.setdefault("tables", {})["_latest_workflow_report"] = load_latest_workflow_report()
        data.setdefault("tables", {})["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
        data.setdefault("tables", {})["_latest_selection_review_report"] = load_latest_selection_review_report()
        data.setdefault("tables", {})["_latest_review_template"] = template_metadata(latest_review_template_path())
        data.setdefault("tables", {})["_latest_watchlist_report"] = load_latest_watchlist_report()
        data.setdefault("tables", {})["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
        data.setdefault("tables", {})["_local_state"] = _safe_local_state()
        data.setdefault("watchlist", pd.DataFrame())
        data.setdefault("watchlist_snapshot", pd.DataFrame())
        return data

    try:
        tables = {
            "stock_basic": store.read_table("stock_basic"),
            "daily_price": store.read_table("daily_price"),
            "daily_basic": store.read_table("daily_basic"),
            "factor_scores": store.read_table("factor_scores"),
            "strategy_result": store.read_table("strategy_result"),
            "backtest_result": store.read_table("backtest_result"),
            "review_decisions": _safe_read_store_table(store, "review_decisions"),
            "review_decision_history": _safe_read_store_table(store, "review_decision_history"),
        }
    except DuckDBStoreError:
        data = sample_dashboard_data()
        data["data_source"] = "sample 数据（演示，真实数据读取失败）"
        data.setdefault("tables", {})["_latest_workflow_report"] = load_latest_workflow_report()
        data.setdefault("tables", {})["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
        data.setdefault("tables", {})["_latest_selection_review_report"] = load_latest_selection_review_report()
        data.setdefault("tables", {})["_latest_review_template"] = template_metadata(latest_review_template_path())
        data.setdefault("tables", {})["_latest_watchlist_report"] = load_latest_watchlist_report()
        data.setdefault("tables", {})["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
        data.setdefault("tables", {})["_local_state"] = _safe_local_state()
        data.setdefault("watchlist", pd.DataFrame())
        data.setdefault("watchlist_snapshot", pd.DataFrame())
        return data

    if tables["strategy_result"].empty:
        computed = _computed_real_dashboard_data(settings, store, tables)
        if computed is not None:
            return computed
        data = sample_dashboard_data()
        data["data_source"] = "sample 数据（演示，真实选股结果不足）"
        data.setdefault("tables", {})["_latest_workflow_report"] = load_latest_workflow_report()
        data.setdefault("tables", {})["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
        data.setdefault("tables", {})["_latest_selection_review_report"] = load_latest_selection_review_report()
        data.setdefault("tables", {})["_latest_review_template"] = template_metadata(latest_review_template_path())
        data.setdefault("tables", {})["_latest_watchlist_report"] = load_latest_watchlist_report()
        data.setdefault("tables", {})["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
        data.setdefault("tables", {})["_local_state"] = _safe_local_state()
        data.setdefault("watchlist", pd.DataFrame())
        data.setdefault("watchlist_snapshot", pd.DataFrame())
        return data

    tables["_latest_workflow_report"] = load_latest_workflow_report()
    tables["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
    tables["_latest_selection_review_report"] = load_latest_selection_review_report()
    tables["_latest_review_template"] = template_metadata(latest_review_template_path())
    tables["_latest_watchlist_report"] = load_latest_watchlist_report()
    tables["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
    tables["_local_state"] = _safe_local_state()
    watchlist = _load_watchlist_for_dashboard(store)
    watchlist_snapshot = _load_tracking_snapshot_for_dashboard(store)
    tables["_watchlist_snapshot"] = watchlist_snapshot
    return {
        "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据",
        "selection": tables["strategy_result"],
        "stock_basic": tables["stock_basic"],
        "price": tables["daily_price"],
        "daily_basic": tables["daily_basic"],
        "factor_scores": tables["factor_scores"],
        "backtest": {},
        "watchlist": watchlist,
        "watchlist_snapshot": watchlist_snapshot,
        "tables": tables,
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
    real_tables["_data_source"] = f"{settings.data_provider} 本地 DuckDB 真实数据"
    real_tables["_configured_symbol_count"] = batch_diagnostic.get("configured_symbol_count", 0)
    real_tables["_priced_symbol_count"] = batch_diagnostic.get("priced_symbol_count", 0)
    real_tables["_coverage_rate"] = batch_diagnostic.get("coverage_rate", 0.0)
    real_tables["_missing_symbol_count"] = len(batch_diagnostic.get("missing_symbols", []))
    real_tables["_latest_workflow_report"] = load_latest_workflow_report()
    real_tables["_latest_daily_workflow_report"] = load_latest_daily_workflow_report()
    real_tables["_latest_selection_review_report"] = load_latest_selection_review_report()
    real_tables["_latest_review_template"] = template_metadata(latest_review_template_path())
    real_tables["_latest_watchlist_report"] = load_latest_watchlist_report()
    real_tables["_latest_watchlist_tracking_report"] = load_latest_watchlist_tracking_report()
    real_tables["_local_state"] = _safe_local_state()
    real_tables["review_decisions"] = _safe_read_store_table(store, "review_decisions")
    real_tables["review_decision_history"] = _safe_read_store_table(store, "review_decision_history")
    watchlist_snapshot = _load_tracking_snapshot_for_dashboard(store)
    real_tables["_watchlist_snapshot"] = watchlist_snapshot
    backtest_result = dict(backtest_diagnostic.get("backtest_result", {}))
    backtest_result["data_quality_notes"] = backtest_diagnostic.get("data_quality_notes", [])
    return {
        "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据",
        "selection": selected,
        "stock_basic": tables["stock_basic"],
        "price": tables["daily_price"],
        "daily_basic": tables["daily_basic"],
        "factor_scores": factor_scores,
        "factor_quality": diagnostic.get("factor_quality", {}),
        "data_quality_notes": diagnostic.get("data_quality_notes", []),
        "backtest": backtest_result,
        "watchlist": _load_watchlist_for_dashboard(store),
        "watchlist_snapshot": watchlist_snapshot,
        "backtest_diagnostic": backtest_diagnostic,
        "batch_diagnostic": batch_diagnostic,
        "tables": real_tables,
    }


def render_dashboard(data: dict[str, Any] | None = None) -> None:
    """Render the Streamlit dashboard from preloaded or sample local data."""
    import streamlit as st

    dashboard_data = data or load_dashboard_data()
    st.set_page_config(page_title="A 股选股辅助", layout="wide")
    st.title("A 股选股辅助")
    st.caption("仅用于研究与辅助决策，不构成投资建议。")
    data_source_status = describe_dashboard_data_source(dashboard_data)
    st.info(f"数据来源：{data_source_status['data_source']}。{data_source_status['message']}")
    st.caption("日常一键命令：python -m core.jobs.run_daily_workflow --backup-before-run --format all")

    tabs = st.tabs(["今日选股", "个股详情", "因子排名", "选股逻辑", "埃尔德复核", "策略回测", "数据更新状态", "本地控制台"])
    with tabs[0]:
        _render_selection_tab(st, dashboard_data.get("selection", pd.DataFrame()))
    with tabs[1]:
        _render_stock_detail_tab(
            st,
            dashboard_data.get("stock_basic", pd.DataFrame()),
            dashboard_data.get("price", pd.DataFrame()),
            dashboard_data.get("factor_scores", pd.DataFrame()),
        )
    with tabs[2]:
        _render_factor_ranking_tab(
            st,
            dashboard_data.get("factor_scores", pd.DataFrame()),
            dashboard_data.get("daily_basic", pd.DataFrame()),
        )
    with tabs[3]:
        _render_selection_logic_tab(st, dashboard_data.get("selection", pd.DataFrame()))
    with tabs[4]:
        _render_elder_review_tab(
            st,
            dashboard_data.get("selection", pd.DataFrame()),
            dashboard_data.get("price", pd.DataFrame()),
        )
    with tabs[5]:
        _render_backtest_tab(st, dashboard_data.get("backtest", {}))
    with tabs[6]:
        _render_status_tab(st, dashboard_data.get("tables", {}))
    with tabs[7]:
        _render_local_console_tab(st, dashboard_data.get("tables", {}))


def main() -> None:
    """Run the Streamlit dashboard."""
    render_dashboard()


def _render_selection_tab(st: Any, selection_df: pd.DataFrame) -> None:
    st.subheader("今日选股")
    if selection_df.empty:
        st.info("暂无选股结果。请先运行每日选股任务或导入本地结果。")
        return
    industry = st.selectbox("行业", get_industry_options(selection_df))
    sort_descending = st.checkbox("按综合分从高到低排序", value=True)
    filtered = filter_selection_data(selection_df, industry, sort_descending)
    st.dataframe(filtered, use_container_width=True)
    st.write("候选股票详情")
    for item in filtered.head(10).to_dict("records"):
        title = f"{item.get('rank')}. {item.get('ts_code')} {item.get('name')}"
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
        return
    st.write("候选股票")
    st.dataframe(filter_selection_data(selection_df).head(20), use_container_width=True)
    st.write("人工复核模板导出后，可填写 decision、reason、notes、reviewer，再用 import_review_decisions 回填本地 DuckDB。")


def _render_watchlist_tab(st: Any, watchlist_df: pd.DataFrame) -> None:
    st.subheader("观察池")
    if watchlist_df.empty:
        st.info("暂无 active watch 股票。人工复核导入 watch 决策后会显示在这里。")
        return
    st.caption("刷新观察池评分：python -m core.jobs.refresh_watchlist_scores")
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
    ]
    available = [column for column in display_columns if column in watchlist_df.columns]
    st.dataframe(watchlist_df[available], use_container_width=True)


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
        st.dataframe(basic, use_container_width=True)
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
        st.dataframe(factors[[column for column in FACTOR_SCORE_COLUMNS if column in factors.columns]], use_container_width=True)
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
            st.dataframe(elder[[column for column in elder_columns if column in elder.columns]], use_container_width=True)


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
        st.dataframe(
            pd.DataFrame(
                [
                    {"field": field, "non_null_rate": stats["non_null_rate"], "missing_count": stats["missing_count"]}
                    for field, stats in valuation_quality.items()
                ]
            ),
            use_container_width=True,
        )
    missing = summarize_factor_missing(factor_df)
    if missing:
        st.write("因子非空率")
        st.dataframe(
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
            use_container_width=True,
        )
    dates = sorted(factor_df["trade_date"].astype(str).unique()) if "trade_date" in factor_df.columns else []
    trade_date = st.selectbox("交易日期", dates) if dates else None
    industry = st.selectbox("行业筛选", get_industry_options(factor_df), key="factor_industry")
    factor_col = st.selectbox("因子", [column for column in FACTOR_SCORE_COLUMNS if column in factor_df.columns])
    ranking = filter_factor_ranking(factor_df, trade_date, industry, factor_col)
    st.dataframe(ranking, use_container_width=True)


def _render_selection_logic_tab(st: Any, selection_df: pd.DataFrame) -> None:
    st.subheader("选股逻辑")
    summary = get_selection_logic_summary()
    st.write("综合评分公式")
    st.code(summary.formula_summary)
    st.write("因子说明")
    st.dataframe(
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
        use_container_width=True,
    )
    st.write("流程说明")
    for step in summary.workflow_steps:
        st.write(f"- {step}")
    st.write("主要贡献因子 / 排名原因")
    explanations = explain_candidates(selection_df, top_n=10)
    if explanations:
        st.dataframe(explanations_to_dataframe(explanations), use_container_width=True)
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


def _render_elder_review_tab(st: Any, selection_df: pd.DataFrame, price_df: pd.DataFrame) -> None:
    st.subheader("埃尔德复核")
    st.caption("二次技术状态 / 节奏复核层，不覆盖 total_score，不改变今日选股原始排序，也不代表买入优先级。")
    review_df = build_elder_review(selection_df, price_df)
    if review_df.empty:
        st.info("暂无埃尔德复核结果。请先运行每日选股并确保本地 daily_price 有足够行情。")
        return
    display_columns = [
        "rank",
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
    available = [column for column in display_columns if column in review_df.columns]
    st.dataframe(review_df[available], use_container_width=True)
    st.write("状态分布")
    st.dataframe(review_df["action_hint"].value_counts(dropna=False).rename_axis("action_hint").reset_index(name="count"), use_container_width=True)
    st.info("操作建议只用于人工复核流程，不改变今日选股 total_score 排序；“短线过热，不追”表示短期回撤风险偏高，不等于中期趋势一定转弱。批量导出可运行 python -m core.jobs.export_elder_review。")
    st.caption("命令行：python -m core.jobs.run_elder_review 或 python -m core.jobs.export_elder_review --format markdown")


def _render_backtest_tab(st: Any, backtest: dict[str, Any]) -> None:
    st.subheader("策略回测")
    if not backtest:
        st.info("暂无回测结果。请先运行回测诊断；真实数据不足时不会生成结果。")
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
    st.dataframe(backtest.get("trade_records", pd.DataFrame()), use_container_width=True)
    st.write("持仓记录")
    st.dataframe(backtest.get("position_records", pd.DataFrame()), use_container_width=True)


def _render_status_tab(st: Any, tables: dict[str, pd.DataFrame]) -> None:
    st.subheader("数据更新状态")
    status = summarize_update_status(tables)
    st.metric("最新行情日期", status["latest_price_date"] or "暂无")
    st.metric("最新因子日期", status["latest_factor_date"] or "暂无")
    st.metric("最新选股日期", status["latest_selection_date"] or "暂无")
    st.metric("配置股票数量", status["configured_symbol_count"])
    st.metric("已有行情股票数量", status["priced_symbol_count"])
    st.metric("缺数据股票数量", status["missing_symbol_count"])
    st.write({"覆盖率": f"{status['coverage_rate']:.2%}"})
    st.write({"是否 sample 数据": status["is_sample_data"], "是否真实数据": status["is_real_data"]})
    basic_quality = status.get("basic_quality", {})
    if basic_quality:
        st.write("基础信息 / 估值字段完整率")
        quality_rows = []
        for group_name, group in basic_quality.items():
            for field, stats in group.items():
                quality_rows.append(
                    {
                        "table": group_name,
                        "field": field,
                        "non_null_rate": stats["non_null_rate"],
                        "missing_count": stats["missing_count"],
                    }
                )
        st.dataframe(pd.DataFrame(quality_rows), use_container_width=True)
    local_state = status.get("local_state")
    if isinstance(local_state, dict) and local_state:
        st.write("本地状态 / 备份")
        st.write(
            {
                "DuckDB 路径": local_state.get("duckdb_path"),
                "DuckDB 文件大小": local_state.get("duckdb_size"),
                "核心表行数": local_state.get("table_counts"),
                "观察池记录数": local_state.get("review_decisions_rows"),
                "复核历史记录数": local_state.get("review_decision_history_rows"),
                "watchlist snapshots": local_state.get("watchlist_snapshots_rows"),
                "reports 文件数量": local_state.get("reports_count"),
                "backups 数量": local_state.get("backups_count"),
                "最近备份时间": local_state.get("latest_backup_time") or "暂无",
                "最近备份路径": local_state.get("latest_backup_path") or "暂无",
            }
        )
        st.caption("个人本地工具，建议定期备份。")
    if status["field_missing"]:
        st.warning(f"存在字段缺失：{status['field_missing']}")
    st.write("核心数据表状态")
    st.dataframe(pd.DataFrame(status["table_rows"].items(), columns=["table", "rows"]), use_container_width=True)
    report = status.get("latest_workflow_report")
    if report:
        st.write("最近 workflow 报告")
        st.write(
            {
                "最近运行时间": report.get("run_time") or "暂无",
                "整体状态": report.get("overall_status") or "暂无",
                "数据来源": report.get("data_provider") or "暂无",
                "最新行情日期": report.get("latest_price_date") or "暂无",
                "覆盖率": _format_optional_rate(report.get("coverage_rate")),
                "候选股票数量": report.get("candidate_count", 0),
                "是否回退 sample": bool(report.get("fallback_to_sample")),
                "报告路径": report.get("path"),
            }
        )
    daily_report = status.get("latest_daily_workflow_report")
    if daily_report:
        st.write("最近 daily_workflow 日报")
        st.write(
            {
                "最近运行时间": daily_report.get("run_time") or "暂无",
                "整体状态": daily_report.get("overall_status") or "暂无",
                "数据来源": daily_report.get("data_provider") or "暂无",
                "最新行情日期": daily_report.get("latest_price_date") or "暂无",
                "报告路径": daily_report.get("path"),
            }
        )
        top_candidates = daily_report.get("top_candidates") or []
        if top_candidates:
            st.write("最近日报 Top10 候选")
            st.dataframe(pd.DataFrame(top_candidates), use_container_width=True)
        watchlist_items = daily_report.get("watchlist") or []
        if watchlist_items:
            st.write("最近日报观察池摘要")
            st.dataframe(pd.DataFrame(watchlist_items), use_container_width=True)
    selection_review = status.get("latest_selection_review_report")
    if selection_review:
        st.write("最近 selection_review 报告")
        st.write(
            {
                "最近运行时间": selection_review.get("generated_at") or "暂无",
                "数据来源": selection_review.get("data_source") or "暂无",
                "最新行情日期": selection_review.get("latest_price_date") or "暂无",
                "候选股票数量": selection_review.get("candidate_count", 0),
                "是否回退 sample": bool(selection_review.get("fallback_to_sample")),
                "报告路径": selection_review.get("path"),
            }
        )
    review_template = status.get("latest_review_template")
    if review_template:
        st.write("最近 review_template")
        st.write(review_template)
    watchlist_report = status.get("latest_watchlist_report")
    if watchlist_report:
        st.write("最近 watchlist 报告")
        st.write(watchlist_report)
    watchlist_df = _watchlist_from_tables(tables)
    if not watchlist_df.empty:
        st.write("观察池当前状态")
        watchlist_columns = [
            "ts_code",
            "name",
            "decision",
            "review_status",
            "reason",
            "notes",
            "industry",
            "pe",
            "pb",
            "latest_action_at",
            "history_count",
        ]
        available = [column for column in watchlist_columns if column in watchlist_df.columns]
        st.dataframe(watchlist_df[available], use_container_width=True)
    history_df = tables.get("review_decision_history", pd.DataFrame())
    if isinstance(history_df, pd.DataFrame) and not history_df.empty:
        st.write("最近复核历史")
        history_display = history_df.sort_values("created_at", ascending=False).head(10)
        history_columns = [
            "created_at",
            "ts_code",
            "name",
            "action_type",
            "old_decision",
            "new_decision",
            "old_review_status",
            "new_review_status",
            "reason",
        ]
        available = [column for column in history_columns if column in history_display.columns]
        st.dataframe(history_display[available], use_container_width=True)
    tracking_report = status.get("latest_watchlist_tracking_report")
    if tracking_report:
        st.write("最近 watchlist_tracking 报告")
        st.write(tracking_report)
    snapshot_df = tables.get("_watchlist_snapshot", pd.DataFrame())
    if isinstance(snapshot_df, pd.DataFrame) and not snapshot_df.empty:
        st.write("观察池最新 snapshot")
        display_columns = [
            "ts_code",
            "name",
            "snapshot_date",
            "latest_trade_date",
            "latest_close",
            "total_score",
            "trend_score",
            "momentum_score",
            "liquidity_score",
            "volatility_score",
            "data_quality_note",
        ]
        available = [column for column in display_columns if column in snapshot_df.columns]
        st.dataframe(snapshot_df[available], use_container_width=True)
    st.info(status["last_job_status"])


def _render_local_console_tab(st: Any, tables: dict[str, pd.DataFrame]) -> None:
    """Render local settings and command console."""
    st.subheader("参数设置 / 本地控制台")
    st.caption("仅供个人研究使用，不自动交易。页面只执行预设白名单命令。")
    env_path = PROJECT_ROOT / ".env"
    env_values = read_env_file(env_path)
    display_values = masked_env_values(env_values)
    status = summarize_update_status(tables)
    effective = effective_pool_config(env_values)
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
        st.warning("你现在选择的是“自定义股票池”，所以系统只会更新上面输入的股票代码。预设股票池 small / medium 暂时不会生效。")
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
            ["mini", "small", "medium"],
            index=_option_index(["mini", "small", "medium"], env_values.get("REAL_UNIVERSE_PRESET", "mini")),
        )
        if pool_mode == "自定义股票池":
            st.caption("支持 000001,600000,002475，也支持中文逗号、换行和 000001.SZ / 600000.SH。保存后预设股票池暂时不会生效。")
        else:
            st.caption("保存时会清空 AKSHARE_SAMPLE_SYMBOLS，预设股票池将在下次更新数据时生效。")
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
            valuation_enrichment = st.checkbox("ENABLE_REAL_VALUATION_ENRICHMENT", value=_bool_value(env_values.get("ENABLE_REAL_VALUATION_ENRICHMENT", "true")))
            batch_size = st.number_input("REAL_BATCH_SIZE", min_value=1, value=int(env_values.get("REAL_BATCH_SIZE", "10") or 10), step=1)
            batch_sleep = st.number_input("REAL_BATCH_SLEEP_SECONDS", min_value=0.0, value=float(env_values.get("REAL_BATCH_SLEEP_SECONDS", "0") or 0.0), step=0.1)
            max_retries = st.number_input("REAL_MAX_RETRIES", min_value=0, value=int(env_values.get("REAL_MAX_RETRIES", "1") or 1), step=1)
            timeout_seconds = st.number_input("REAL_REQUEST_TIMEOUT_SECONDS", min_value=1, value=int(env_values.get("REAL_REQUEST_TIMEOUT_SECONDS", "30") or 30), step=1)
            data_dir = st.text_input("DATA_DIR", value=env_values.get("DATA_DIR", "./data"))
            duckdb_path = st.text_input("DUCKDB_PATH", value=env_values.get("DUCKDB_PATH", "./data/a_stock_assistant.duckdb"))
            st.write({"TUSHARE_TOKEN 状态": display_values.get("TUSHARE_TOKEN", "未设置")})
        save_only = st.form_submit_button("保存参数")
        save_recalculate = st.form_submit_button("保存并本地重算")
        save_update = st.form_submit_button("保存并更新数据")

    updates, validation = build_settings_updates(
        pool_mode=pool_mode,
        symbols_text=symbols,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        provider=provider,
        akshare_adjust=akshare_adjust,
        basic_enrichment=basic_enrichment,
        valuation_enrichment=valuation_enrichment,
        batch_size=batch_size,
        batch_sleep=batch_sleep,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
        data_dir=data_dir,
        duckdb_path=duckdb_path,
    )
    if validation["invalid"]:
        st.warning(f"以下股票代码不是 6 位数字，未保存：{', '.join(validation['invalid'])}")
    if save_only or save_recalculate or save_update:
        if validation["invalid"]:
            st.error("请先修正股票代码，再保存参数。")
        else:
            saved = _save_console_settings(st, env_path, updates)
            if saved and save_only:
                st.info("参数已保存，但数据库尚未更新。若要生效，请点击“保存并更新数据”。请点击页面右上角刷新，或按 R 重新加载页面。")
            elif saved and save_recalculate:
                st.info("该操作不会联网更新行情，只会用本地已有数据重新生成报告。")
                _run_console_action(st, "保存并本地重算", "run_daily_workflow", ["--doctor-before-run", "--skip-update", "--format", "all"])
            elif saved and save_update:
                st.info("该操作会联网更新真实行情数据，可能较慢。")
                _run_console_action(st, "保存并更新数据", "run_daily_workflow", ["--doctor-before-run", "--backup-before-run", "--format", "all"])

    st.write("一键操作区")
    _command_button(st, "一键运行", "run_daily_workflow", ["--doctor-before-run", "--backup-before-run", "--format", "all"])
    _command_button(st, "运行体检", "doctor_daily_run")
    _open_button(st, "打开报告文件夹", PROJECT_ROOT / "reports")
    _command_button(st, "清理旧报告", "clean_generated_reports", ["--force"])

    with st.expander("高级操作", expanded=False):
        output_format = st.selectbox("输出格式", ["all", "markdown", "json", "csv"], index=0)
        _command_button(st, "只用本地已有数据，不联网更新行情", "run_daily_workflow", ["--doctor-before-run", "--skip-update", "--format", output_format])
        _command_button(st, "更新真实数据", "update_real_data")
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
    data_dir: str,
    duckdb_path: str,
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
        "ENABLE_REAL_VALUATION_ENRICHMENT": valuation_enrichment,
        "REAL_BATCH_SIZE": batch_size,
        "REAL_BATCH_SLEEP_SECONDS": batch_sleep,
        "REAL_MAX_RETRIES": max_retries,
        "REAL_REQUEST_TIMEOUT_SECONDS": timeout_seconds,
        "DATA_DIR": data_dir,
        "DUCKDB_PATH": duckdb_path,
    }
    return updates, {"invalid": [] if use_preset else parsed["invalid"]}


def effective_pool_config(values: dict[str, str]) -> dict[str, Any]:
    """Describe the currently effective stock-pool configuration."""
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
    return {
        "mode": "preset",
        "mode_label": "REAL_UNIVERSE_PRESET",
        "symbol_count": 0,
        "symbols": [],
        "symbols_text": f"使用预设：{preset}",
        "akshare_sample_symbols": "",
        "real_universe_preset": preset,
        "preset_inactive": False,
        "message": "AKSHARE_SAMPLE_SYMBOLS 为空，当前使用 REAL_UNIVERSE_PRESET 股票池。",
    }


def build_date_status(env_values: dict[str, str], status: dict[str, Any]) -> dict[str, Any]:
    """Compare parameter dates with actual database dates."""
    end_date = env_values.get("REAL_DATA_END_DATE", "")
    latest_price_date = status.get("latest_price_date")
    message = "结束日期留空表示尽量拉取到最新可得日期。"
    warning = False
    if end_date and latest_price_date and str(latest_price_date) < str(end_date):
        warning = True
        message = f"参数结束日期为 {end_date}，但数据库最新行情日期仍为 {latest_price_date}。需要点击“保存并更新数据”才会拉取新数据。"
    elif end_date:
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
        "已跳过数量": 0,
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
                    "已跳过数量": state.skipped,
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


def _safe_read_store_table(store: Any, table_name: str) -> pd.DataFrame:
    """Read optional local DuckDB tables for the dashboard."""
    try:
        return store.read_table(table_name)
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
