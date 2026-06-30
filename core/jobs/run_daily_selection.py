"""Daily stock selection smoke entrypoint for local MVP runs."""

from __future__ import annotations

from datetime import date, datetime
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

FACTOR_SCORE_TABLE_COLUMNS = [
    "ts_code",
    "trade_date",
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "volatility_score",
    "fundamental_score",
    "total_score",
]

STRATEGY_RESULT_TABLE_COLUMNS = [
    "trade_date",
    "rank",
    "ts_code",
    "name",
    "industry",
    "close",
    "pe",
    "pb",
    "total_score",
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "fundamental_score",
    "volatility_score",
    "quality_score",
    "valuation_score",
    "risk_score",
    "select_reason",
    "risk_note",
    "created_at",
    "updated_at",
]


def run_daily_selection(
    use_sample: bool = True,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    top_n: int | None = None,
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
            top_n=top_n,
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
        "is_real_data": False,
        "stock_pool_count": int(len(stock_basic)),
        "scored_stock_count": int(len(factor_scores)),
        "factor_calculable_count": int(len(factor_scores)),
        "total_score_non_null_count": _non_null_count(factor_scores, "total_score"),
        "backtest_ready": int(len(selection)) > 0,
        "backtest_note": "sample 演示数据可用于页面 smoke test，不代表真实回测。",
        "candidate_count": int(len(selection)),
        "top_candidates": _top_candidate_records(selection),
        "latest_price_date": _latest_date(data.get("price", pd.DataFrame()), "trade_date"),
        "wrote_to_database": False,
        "fallback_to_sample": "回退 sample" in result_location,
        "data_quality_note": "sample 演示数据，仅用于流程验证。",
        "result_location": result_location,
    }


def main() -> None:
    """Print the MVP daily selection summary."""
    summary = run_daily_selection()
    print("每日选股任务摘要")
    print(f"- 当前运行日期: {summary['run_date']}")
    print(f"- 数据来源: {summary['data_source']}")
    print(f"- 是否使用真实数据: {'是' if summary.get('is_real_data') else '否'}")
    print(f"- 最新行情日期: {summary.get('latest_price_date') or '暂无'}")
    print(f"- 股票池数量: {summary['stock_pool_count']}")
    print(f"- 因子可计算股票数量: {summary.get('factor_calculable_count', summary['scored_stock_count'])}")
    print(f"- 综合评分非空股票数量: {summary.get('total_score_non_null_count', 0)}")
    print(f"- 是否支持当前数据进行回测: {'是' if summary.get('backtest_ready') else '否'}")
    print(f"- 评分股票数量: {summary['scored_stock_count']}")
    print(f"- 候选股票数量: {summary['candidate_count']}")
    print(f"- 是否写入数据库: {'是' if summary.get('wrote_to_database') else '否'}")
    print(f"- factor_scores 写入行数: {summary.get('factor_scores_written_rows', 0)}")
    print(f"- strategy_result 写入行数: {summary.get('strategy_result_written_rows', 0)}")
    print(f"- 本地可展示选股结果数量: {summary.get('local_display_selection_count', 0)}")
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
    if summary.get("data_quality_note"):
        print(f"- 数据质量提示: {summary['data_quality_note']}")
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
        "is_real_data": False,
        "stock_pool_count": 0,
        "scored_stock_count": 0,
        "factor_calculable_count": 0,
        "total_score_non_null_count": 0,
        "backtest_ready": False,
        "backtest_note": "无可用评分结果，暂不能回测。",
        "candidate_count": 0,
        "top_candidates": [],
        "latest_price_date": None,
        "wrote_to_database": False,
        "fallback_to_sample": False,
        "data_quality_note": "",
        "result_location": "未生成结果；请导入本地数据或启用演示数据。",
    }


def _try_real_data_summary(store: DuckDBStore, settings: Settings, *, top_n: int | None = None) -> dict[str, Any]:
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
            min_listing_days=getattr(settings, "min_listing_days", 120),
            min_avg_amount_20d=getattr(settings, "min_avg_amount_20d", 100_000_000),
            min_median_amount_20d=getattr(settings, "min_median_amount_20d", 50_000_000),
            min_latest_amount=getattr(settings, "min_latest_amount", 30_000_000),
            min_traded_days_20d=getattr(settings, "min_traded_days_20d", 18),
            include_bse=getattr(settings, "include_bse", False),
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
        selected = select_top_stocks(factor_scores, top_n=top_n or settings.default_top_n)
    except Exception as exc:
        summary = _empty_summary("无数据")
        summary["result_location"] = f"真实数据计算失败：{exc}；可回退 sample 数据。"
        return summary

    if selected.empty:
        summary = _empty_summary("无数据")
        summary["stock_pool_count"] = int(len(tradeable))
        summary["scored_stock_count"] = int(len(factor_scores))
        summary["factor_calculable_count"] = int(len(factor_scores))
        summary["total_score_non_null_count"] = _non_null_count(factor_scores, "total_score")
        summary["backtest_ready"] = False
        summary["backtest_note"] = "真实评分未生成候选股票，暂不能回测。"
        summary["result_location"] = "真实数据已计算，但未生成候选股票；可回退 sample 数据。"
        return summary

    persistence = _persist_real_selection_results(
        store=store,
        factor_scores=factor_scores,
        selected=selected,
        daily_price=daily_price,
        daily_basic=daily_basic,
        trade_date=latest_trade_date,
    )
    total_score_non_null = _non_null_count(factor_scores, "total_score")
    persistence_error = persistence.get("persistence_error")
    result_location = f"基于本地 DuckDB 真实数据完成最小选股试运行，最新行情日期 {latest_trade_date}。"
    if persistence_error:
        result_location = f"{result_location} 本地展示结果写入失败：{persistence_error}"
    elif int(persistence.get("strategy_result_written_rows", 0) or 0) == 0:
        result_location = f"{result_location} 但本地 strategy_result 未写入候选结果。"
    return {
        "run_date": date.today().isoformat(),
        "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据",
        "is_real_data": True,
        "selection_date": latest_trade_date,
        "universe_source": _universe_source_label(settings),
        "raw_universe_count": int(len(universe)),
        "stock_pool_count": int(len(tradeable)),
        "universe_filter_counts": _universe_filter_counts(universe),
        "scored_stock_count": int(len(factor_scores)),
        "factor_calculable_count": int(len(factor_scores)),
        "total_score_non_null_count": total_score_non_null,
        "backtest_ready": total_score_non_null > 0 and int(len(selected)) > 0,
        "backtest_note": "可运行 python -m core.jobs.diagnose_backtest 进行少量样本真实数据回测诊断。",
        "candidate_count": int(len(selected)),
        "top_candidates": _top_candidate_records(selected),
        "latest_price_date": latest_trade_date,
        "wrote_to_database": bool(persistence.get("wrote_to_database")),
        "factor_scores_written_rows": int(persistence.get("factor_scores_written_rows", 0) or 0),
        "strategy_result_written_rows": int(persistence.get("strategy_result_written_rows", 0) or 0),
        "local_display_selection_count": int(persistence.get("local_display_selection_count", 0) or 0),
        "persistence_error": persistence_error,
        "fallback_to_sample": False,
        "data_quality_note": _real_data_quality_note(settings.data_provider, daily_basic),
        "result_location": result_location,
    }


def _persist_real_selection_results(
    *,
    store: DuckDBStore,
    factor_scores: pd.DataFrame,
    selected: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
    trade_date: str,
) -> dict[str, Any]:
    """Persist factor scores and latest strategy result for local dashboard display."""
    if selected.empty:
        return {
            "wrote_to_database": False,
            "factor_scores_written_rows": 0,
            "strategy_result_written_rows": 0,
            "local_display_selection_count": 0,
        }

    try:
        store.initialize()
        factor_df = _factor_scores_for_storage(factor_scores)
        strategy_df = _strategy_result_for_storage(selected, daily_price, daily_basic, trade_date)
        factor_rows = store.upsert_dataframe("factor_scores", factor_df)
        strategy_rows = _replace_strategy_result_for_date(store, strategy_df, trade_date)
    except DuckDBStoreError as exc:
        return {
            "wrote_to_database": False,
            "factor_scores_written_rows": 0,
            "strategy_result_written_rows": 0,
            "local_display_selection_count": 0,
            "persistence_error": str(exc),
        }

    return {
        "wrote_to_database": strategy_rows > 0,
        "factor_scores_written_rows": int(factor_rows),
        "strategy_result_written_rows": int(strategy_rows),
        "local_display_selection_count": int(len(strategy_df)) if strategy_rows > 0 else 0,
    }


def _replace_strategy_result_for_date(store: DuckDBStore, strategy_df: pd.DataFrame, trade_date: str) -> int:
    """Replace the full persisted strategy result for one trade date."""
    if strategy_df.empty:
        return 0
    try:
        with store.connect() as connection:
            connection.register("input_df", strategy_df)
            connection.execute("BEGIN TRANSACTION")
            connection.execute("DELETE FROM strategy_result WHERE trade_date = ?", [str(trade_date)])
            connection.execute("INSERT INTO strategy_result BY NAME SELECT * FROM input_df")
            connection.execute("COMMIT")
            connection.unregister("input_df")
    except DuckDBStoreError:
        raise
    except Exception as exc:
        raise DuckDBStoreError(str(exc) or "Failed to replace strategy_result rows.") from exc
    return int(len(strategy_df))


def _factor_scores_for_storage(factor_scores: pd.DataFrame) -> pd.DataFrame:
    """Return only factor score table columns with stable dtypes."""
    if factor_scores.empty:
        return pd.DataFrame(columns=FACTOR_SCORE_TABLE_COLUMNS)
    df = factor_scores.copy()
    for column in FACTOR_SCORE_TABLE_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[FACTOR_SCORE_TABLE_COLUMNS].dropna(subset=["ts_code", "trade_date"]).reset_index(drop=True)


def _strategy_result_for_storage(
    selected: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
    trade_date: str,
) -> pd.DataFrame:
    """Build the persisted strategy result table from selected rows and latest market data."""
    df = selected.copy()
    if "rank" not in df.columns:
        df["rank"] = range(1, len(df) + 1)
    if "trade_date" not in df.columns:
        df["trade_date"] = trade_date

    latest_price = _latest_rows_for_storage(daily_price, trade_date, ["ts_code", "trade_date", "close"])
    if not latest_price.empty:
        latest_price = latest_price.rename(columns={"close": "close"})
        df = df.merge(latest_price[["ts_code", "trade_date", "close"]], on=["ts_code", "trade_date"], how="left")

    latest_basic = _latest_rows_for_storage(daily_basic, trade_date, ["ts_code", "trade_date", "pe", "pb"])
    if not latest_basic.empty:
        df = df.merge(latest_basic[["ts_code", "trade_date", "pe", "pb"]], on=["ts_code", "trade_date"], how="left")

    now = datetime.now().replace(microsecond=0)
    df["quality_score"] = df.get("fundamental_score", pd.Series([pd.NA] * len(df)))
    df["valuation_score"] = df.get("pe_score", pd.Series([pd.NA] * len(df)))
    df["risk_score"] = df.get("volatility_score", pd.Series([pd.NA] * len(df)))
    df["created_at"] = now
    df["updated_at"] = now
    for column in STRATEGY_RESULT_TABLE_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce").astype("Int64")
    for column in [
        "close",
        "pe",
        "pb",
        "total_score",
        "trend_score",
        "momentum_score",
        "liquidity_score",
        "fundamental_score",
        "volatility_score",
        "quality_score",
        "valuation_score",
        "risk_score",
    ]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df[STRATEGY_RESULT_TABLE_COLUMNS].dropna(subset=["trade_date", "rank", "ts_code"]).reset_index(drop=True)


def _latest_rows_for_storage(df: pd.DataFrame, trade_date: str, columns: list[str]) -> pd.DataFrame:
    """Return latest rows for storage joins using only available columns."""
    if df.empty or "ts_code" not in df.columns or "trade_date" not in df.columns:
        return pd.DataFrame(columns=columns)
    available = [column for column in columns if column in df.columns]
    rows = df[df["trade_date"].astype(str) == str(trade_date)].copy()
    if rows.empty:
        return pd.DataFrame(columns=columns)
    return rows[available].drop_duplicates(subset=["ts_code", "trade_date"], keep="last")


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


def _universe_source_label(settings: Settings) -> str:
    """Return a concise universe source label for reports."""
    if settings.data_provider == "akshare" and getattr(settings, "akshare_sample_symbols", "").strip():
        return "AKSHARE_SAMPLE_SYMBOLS"
    if getattr(settings, "real_universe_preset", "") == "full":
        return "REAL_UNIVERSE_PRESET=full（沪深 A 股全市场，不含北交所）"
    return f"REAL_UNIVERSE_PRESET={getattr(settings, 'real_universe_preset', '')}"


def _universe_filter_counts(universe: pd.DataFrame) -> dict[str, int]:
    """Return exclusion counts by broad filter reason."""
    if universe.empty or "exclude_reason" not in universe.columns:
        return {}
    reasons = universe["exclude_reason"].fillna("").astype(str)
    return {
        "st_or_abnormal": int(reasons.str.contains("ST stock|delisting stock", regex=True).sum()),
        "bse": int(reasons.str.contains("BSE stock", regex=False).sum()),
        "recent_listing": int(reasons.str.contains("listed less than", regex=False).sum()),
        "low_liquidity": int(reasons.str.contains("amount", regex=False).sum()),
        "insufficient_traded_days": int(reasons.str.contains("traded days 20d", regex=False).sum()),
        "data_missing": int(reasons.str.contains("severe financial|suspended", regex=True).sum()),
    }


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


def _real_data_quality_note(data_provider: str, daily_basic: pd.DataFrame) -> str:
    """Return concise real-data quality notes for command output."""
    if data_provider == "akshare" and (
        _column_all_missing(daily_basic, "pe") or _column_all_missing(daily_basic, "pb")
    ):
        return "AKShare fallback 的 pe/pb 可能为空，基本面分项可能偏低或为空；adj_factor 当前可能简化为 1.0。"
    return ""


def _non_null_count(df: pd.DataFrame, column: str) -> int:
    """Return non-null numeric count for one column."""
    if df.empty or column not in df.columns:
        return 0
    return int(pd.to_numeric(df[column], errors="coerce").notna().sum())


def _top_candidate_records(selection: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    """Return compact candidate records for command-line output."""
    if selection.empty:
        return []
    columns = ["rank", "ts_code", "name", "total_score"]
    available = [column for column in columns if column in selection.columns]
    return selection.head(limit)[available].to_dict("records")


if __name__ == "__main__":
    main()
