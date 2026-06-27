"""Daily stock selection smoke entrypoint for local MVP runs."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.factors.fundamental import calculate_pe_score
from core.factors.liquidity import calculate_avg_amount_20d, calculate_avg_turnover_20d
from core.factors.scoring import calculate_total_score, normalize_factor
from core.factors.trend import calculate_return_20d
from core.factors.volatility import calculate_volatility_20d
from core.sample_data import DEMO_DATA_SOURCE, get_sample_dashboard_data
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.strategy.selector import select_top_stocks
from core.universe.stock_pool import build_tradeable_universe


def run_daily_selection(
    use_sample: bool = True,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Run the MVP daily selection command and return a summary.

    The current MVP does not fetch external data, place trades, or promise
    investment outcomes. When no real local pipeline output is available, the
    function uses clearly marked demo data so users can verify installation,
    command execution, and dashboard wiring end to end.
    """
    resolved_settings = settings or get_settings()
    if resolved_settings.data_provider in {"tushare", "akshare"}:
        real_summary = _try_real_data_summary(
            store or DuckDBStore(resolved_settings.duckdb_path),
            resolved_settings,
        )
        if real_summary["candidate_count"] > 0:
            return real_summary
        if not use_sample:
            return real_summary

        if use_sample:
            return _sample_summary(f"真实数据不足，已回退 sample 数据。{real_summary['result_location']}")

    if not use_sample:
        return _empty_summary("无数据")

    return _sample_summary("未写入数据库；当前使用演示数据完成本地 smoke test。")


def _sample_summary(result_location: str) -> dict[str, Any]:
    """Return the standard sample-data summary."""
    data = get_sample_dashboard_data()
    selection = data.get("selection", pd.DataFrame())
    factor_scores = data.get("factor_scores", pd.DataFrame())
    stock_basic = data.get("stock_basic", pd.DataFrame())
    return {
        "run_date": date.today().isoformat(),
        "data_source": DEMO_DATA_SOURCE,
        "stock_pool_count": int(len(stock_basic)),
        "scored_stock_count": int(len(factor_scores)),
        "candidate_count": int(len(selection)),
        "top_candidates": _top_candidate_records(selection),
        "latest_price_date": _latest_date(data.get("price", pd.DataFrame()), "trade_date"),
        "wrote_to_database": False,
        "fallback_to_sample": "回退 sample" in result_location,
        "result_location": result_location,
    }


def main() -> None:
    """Print the MVP daily selection summary."""
    summary = run_daily_selection()
    print("每日选股任务摘要")
    print(f"- 当前运行日期: {summary['run_date']}")
    print(f"- 数据来源: {summary['data_source']}")
    print(f"- 最新行情日期: {summary.get('latest_price_date') or '暂无'}")
    print(f"- 股票池数量: {summary['stock_pool_count']}")
    print(f"- 评分股票数量: {summary['scored_stock_count']}")
    print(f"- 候选股票数量: {summary['candidate_count']}")
    print(f"- 是否写入数据库: {'是' if summary.get('wrote_to_database') else '否'}")
    print(f"- 是否回退 sample: {'是' if summary.get('fallback_to_sample') else '否'}")
    print("- 前若干只候选股票摘要:")
    if summary["top_candidates"]:
        for item in summary["top_candidates"]:
            print(
                f"  {item['rank']}. {item['ts_code']} {item['name']} "
                f"综合分 {item['total_score']:.2f}"
            )
    else:
        print("  暂无候选股票。")
    print(f"- 结果保存位置或说明: {summary['result_location']}")
    diagnostics = summary.get("universe_diagnostics") or []
    if diagnostics:
        print("- 股票池过滤诊断:")
        for item in diagnostics:
            print(
                "  "
                f"{item.get('ts_code')} {item.get('name')} "
                f"latest_trade_date={item.get('latest_trade_date') or '暂无'} "
                f"list_date={item.get('list_date') or '暂无'} "
                f"available_price_days={item.get('available_price_days')} "
                f"avg_amount_20d={item.get('avg_amount_20d')} "
                f"pe_missing={item.get('pe_missing')} "
                f"pb_missing={item.get('pb_missing')} "
                f"exclude_reason={item.get('exclude_reason') or '无'}"
            )


def _empty_summary(data_source: str) -> dict[str, Any]:
    """Return a clear no-data summary instead of raising an opaque error."""
    return {
        "run_date": date.today().isoformat(),
        "data_source": data_source,
        "stock_pool_count": 0,
        "scored_stock_count": 0,
        "candidate_count": 0,
        "top_candidates": [],
        "latest_price_date": None,
        "wrote_to_database": False,
        "fallback_to_sample": False,
        "result_location": "未生成结果；请导入本地数据或启用演示数据。",
    }


def _try_real_data_summary(store: DuckDBStore, settings: Settings) -> dict[str, Any]:
    """Try to summarize real local DuckDB results without crashing on empty data."""
    if not store.db_path.exists():
        summary = _empty_summary("无数据")
        summary["result_location"] = "真实 DuckDB 文件不存在；可回退 sample 数据。"
        return summary

    try:
        stock_basic = store.read_table("stock_basic")
        daily_price = store.read_table("daily_price")
        daily_basic = store.read_table("daily_basic")
    except DuckDBStoreError:
        summary = _empty_summary("无数据")
        summary["result_location"] = "真实 DuckDB 数据不可用；可回退 sample 数据。"
        return summary

    if daily_price.empty or stock_basic.empty or daily_basic.empty:
        summary = _empty_summary("无数据")
        summary["result_location"] = "真实 DuckDB 基础表不足；可回退 sample 数据。"
        return summary

    latest_trade_date = str(daily_price["trade_date"].dropna().astype(str).max())
    try:
        is_akshare = settings.data_provider == "akshare"
        universe = build_tradeable_universe(
            stock_basic,
            daily_price,
            daily_basic,
            latest_trade_date,
            allow_missing_list_date_with_price_history=is_akshare,
            min_price_history_days=60,
            allow_missing_valuation=is_akshare,
        )
        tradeable = universe[universe["is_tradeable"].fillna(False)].copy()
        if tradeable.empty:
            summary = _empty_summary("无数据")
            summary["stock_pool_count"] = int(len(universe))
            summary["latest_price_date"] = latest_trade_date
            summary["selection_date"] = latest_trade_date
            summary["universe_diagnostics"] = _universe_diagnostics(
                universe=universe,
                stock_basic=stock_basic,
                daily_price=daily_price,
                daily_basic=daily_basic,
                latest_trade_date=latest_trade_date,
            )
            summary["result_location"] = "真实数据已读取，但股票池过滤后无可交易股票；可回退 sample 数据。"
            return summary
        factor_scores = _calculate_minimal_real_scores(
            daily_price=daily_price,
            daily_basic=daily_basic,
            universe=tradeable,
            trade_date=latest_trade_date,
        )
        selected = select_top_stocks(factor_scores, top_n=settings.default_top_n)
    except Exception as exc:
        summary = _empty_summary("无数据")
        summary["result_location"] = f"真实数据计算失败：{exc}；可回退 sample 数据。"
        return summary

    if selected.empty:
        summary = _empty_summary("无数据")
        summary["stock_pool_count"] = int(len(tradeable))
        summary["scored_stock_count"] = int(len(factor_scores))
        summary["result_location"] = "真实数据已计算，但未生成候选股票；可回退 sample 数据。"
        return summary

    return {
        "run_date": date.today().isoformat(),
        "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据",
        "selection_date": latest_trade_date,
        "stock_pool_count": int(len(tradeable)),
        "scored_stock_count": int(len(factor_scores)),
        "candidate_count": int(len(selected)),
        "top_candidates": _top_candidate_records(selected),
        "latest_price_date": latest_trade_date,
        "wrote_to_database": False,
        "fallback_to_sample": False,
        "result_location": f"基于本地 DuckDB 真实数据完成最小选股试运行，最新行情日期 {latest_trade_date}。",
    }


def _calculate_minimal_real_scores(
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
    universe: pd.DataFrame,
    trade_date: str,
) -> pd.DataFrame:
    """Calculate existing factors and scores for a minimal real-data validation run."""
    base = universe[["ts_code", "name", "industry", "trade_date"]].copy()
    factors = base.copy()
    for frame in [
        calculate_return_20d(daily_price),
        calculate_avg_amount_20d(daily_price),
        calculate_avg_turnover_20d(daily_basic),
        calculate_pe_score(daily_basic),
        calculate_volatility_20d(daily_price),
    ]:
        latest = _latest_factor_rows(frame, trade_date)
        factors = factors.merge(latest, on=["ts_code", "trade_date"], how="left")

    factors["trend_score"] = normalize_factor(factors, "return_20d", higher_is_better=True)
    factors["momentum_score"] = normalize_factor(factors, "return_20d", higher_is_better=True)
    factors["liquidity_score"] = normalize_factor(factors, "avg_amount_20d", higher_is_better=True)
    factors["fundamental_score"] = normalize_factor(factors, "pe_score", higher_is_better=True)
    factors["volatility_score"] = normalize_factor(factors, "volatility_20d", higher_is_better=False)
    return calculate_total_score(factors)


def _latest_factor_rows(factor_df: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    """Return factor rows matching the selected trade date."""
    if factor_df.empty or "trade_date" not in factor_df.columns:
        return pd.DataFrame(columns=["ts_code", "trade_date"])
    return factor_df[factor_df["trade_date"].astype(str) == trade_date].copy()


def _latest_date(df: pd.DataFrame, column: str) -> str | None:
    """Return the latest date string from a DataFrame."""
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    return None if values.empty else str(values.max())


def _universe_diagnostics(
    universe: pd.DataFrame,
    stock_basic: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
    latest_trade_date: str,
) -> list[dict[str, Any]]:
    """Return per-stock filtering diagnostics for real-data troubleshooting."""
    if universe.empty:
        return []

    diagnostics: list[dict[str, Any]] = []
    for row in universe.to_dict("records"):
        ts_code = str(row.get("ts_code", ""))
        price_rows = _rows_until(daily_price, "trade_date", latest_trade_date, ts_code)
        basic_rows = _rows_until(daily_basic, "trade_date", latest_trade_date, ts_code)
        source_basic = (
            stock_basic[stock_basic["ts_code"].astype(str) == ts_code]
            if "ts_code" in stock_basic.columns
            else pd.DataFrame()
        )
        list_date = row.get("list_date")
        if (list_date is None or str(list_date) in {"", "None", "<NA>", "nan"}) and not source_basic.empty:
            list_date = source_basic.iloc[0].get("list_date")
        diagnostics.append(
            {
                "ts_code": ts_code,
                "name": row.get("name"),
                "latest_trade_date": latest_trade_date,
                "list_date": None if pd.isna(list_date) else list_date,
                "available_price_days": int(len(price_rows)),
                "avg_amount_20d": row.get("avg_amount_20d"),
                "pe_missing": _column_all_missing(basic_rows, "pe"),
                "pb_missing": _column_all_missing(basic_rows, "pb"),
                "exclude_reason": row.get("exclude_reason", ""),
            }
        )
    return diagnostics


def _rows_until(df: pd.DataFrame, date_column: str, trade_date: str, ts_code: str) -> pd.DataFrame:
    """Return all rows for one stock up to the selected date."""
    if df.empty or date_column not in df.columns or "ts_code" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[(df["ts_code"].astype(str) == ts_code) & (df[date_column].astype(str) <= trade_date)]


def _column_all_missing(df: pd.DataFrame, column: str) -> bool:
    """Return whether a column is absent or entirely missing."""
    if df.empty or column not in df.columns:
        return True
    return bool(pd.to_numeric(df[column], errors="coerce").dropna().empty)


def _top_candidate_records(selection: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]]:
    """Return compact candidate records for command-line output."""
    if selection.empty:
        return []
    columns = ["rank", "ts_code", "name", "total_score"]
    available = [column for column in columns if column in selection.columns]
    return selection.head(limit)[available].to_dict("records")


if __name__ == "__main__":
    main()
