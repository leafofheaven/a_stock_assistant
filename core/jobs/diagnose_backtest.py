"""Backtest diagnostics for local sample or real DuckDB data."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.backtest.engine import run_backtest
from core.jobs.run_daily_selection import _calculate_minimal_real_scores
from core.sample_data import get_sample_dashboard_data
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.strategy.portfolio import build_equal_weight_portfolio
from core.strategy.selector import select_top_stocks
from core.universe.stock_pool import build_tradeable_universe


CORE_TABLES = ["stock_basic", "daily_price", "daily_basic", "adj_factor"]
METRIC_KEYS = ["annual_return", "max_drawdown", "sharpe_ratio", "win_rate", "turnover"]


def diagnose_backtest(
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    use_sample: bool = True,
) -> dict[str, Any]:
    """Run a minimal local backtest diagnostic without fetching external data."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)

    if resolved_settings.data_provider == "sample":
        return _diagnose_sample_backtest(resolved_settings, resolved_store)

    if not resolved_store.db_path.exists():
        if use_sample:
            result = _diagnose_sample_backtest(resolved_settings, resolved_store)
            result["data_type"] = "sample 数据（真实 DuckDB 文件不存在）"
            result["reasons"] = ["真实 DuckDB 文件不存在，已使用 sample 数据回测诊断。"]
            return result
        return _empty_result(
            settings=resolved_settings,
            store=resolved_store,
            data_type="无数据",
            reasons=["真实 DuckDB 文件不存在，请先运行 python -m core.jobs.update_real_data。"],
        )

    try:
        tables = {table_name: resolved_store.read_table(table_name) for table_name in CORE_TABLES}
    except DuckDBStoreError as exc:
        if use_sample:
            result = _diagnose_sample_backtest(resolved_settings, resolved_store)
            result["data_type"] = "sample 数据（真实 DuckDB 读取失败）"
            result["reasons"] = [f"真实 DuckDB 读取失败：{exc}；已使用 sample 数据回测诊断。"]
            return result
        return _empty_result(
            settings=resolved_settings,
            store=resolved_store,
            data_type="无数据",
            reasons=[f"真实 DuckDB 读取失败：{exc}。"],
        )

    return _diagnose_real_backtest(resolved_settings, resolved_store, tables)


def main() -> None:
    """Print backtest diagnostics."""
    result = diagnose_backtest()
    print("回测诊断摘要")
    print(f"- 当前 DATA_PROVIDER: {result['data_provider']}")
    print(f"- DuckDB 路径: {result['duckdb_path']}")
    print(f"- 当前数据类型: {result['data_type']}")
    print(f"- 回测起止日期: {result['start_date'] or '暂无'} 至 {result['end_date'] or '暂无'}")
    print(f"- 股票数量: {result['stock_count']}")
    print(f"- 可用行情行数: {result['price_row_count']}")
    print(f"- 可用评分股票数量: {result['score_stock_count']}")
    print(f"- 是否成功构建组合: {'是' if result['portfolio_built'] else '否'}")
    print("- 回测指标:")
    for key, value in result["metrics"].items():
        print(f"  {key}: {value}")
    print(f"- equity_curve 行数: {result['equity_curve_rows']}")
    print(f"- trade_records 行数: {result['trade_records_rows']}")
    print(f"- position_records 行数: {result['position_records_rows']}")
    print(f"- 是否发现异常值: {'是' if result['has_anomaly'] else '否'}")
    if result["reasons"]:
        print("- 具体原因:")
        for reason in result["reasons"]:
            print(f"  {reason}")
    if result["data_quality_notes"]:
        print("- 数据质量提示:")
        for note in result["data_quality_notes"]:
            print(f"  {note}")
    print("- 下一步建议:")
    for step in result["next_steps"]:
        print(f"  {step}")


def _diagnose_real_backtest(
    settings: Settings,
    store: DuckDBStore,
    tables: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Build and run a minimal backtest from local real-data tables."""
    reasons = _missing_table_reasons(tables)
    stock_basic = tables["stock_basic"]
    daily_price = tables["daily_price"]
    daily_basic = tables["daily_basic"]
    adj_factor = tables["adj_factor"]
    start_date = _earliest_date(daily_price, "trade_date")
    end_date = _latest_date(daily_price, "trade_date")
    data_quality_notes = _data_quality_notes(settings.data_provider, daily_basic, adj_factor)

    if reasons or start_date is None or end_date is None:
        return _empty_result(
            settings=settings,
            store=store,
            data_type=f"{settings.data_provider} 本地 DuckDB 真实数据",
            start_date=start_date,
            end_date=end_date,
            stock_count=_unique_count(stock_basic, "ts_code"),
            price_row_count=int(len(daily_price)),
            reasons=reasons or ["daily_price 缺少可用 trade_date。"],
            data_quality_notes=data_quality_notes,
        )

    score_df, score_reasons = _build_score_history(settings, stock_basic, daily_price, daily_basic)
    if score_df.empty:
        return _empty_result(
            settings=settings,
            store=store,
            data_type=f"{settings.data_provider} 本地 DuckDB 真实数据",
            start_date=start_date,
            end_date=end_date,
            stock_count=_unique_count(stock_basic, "ts_code"),
            price_row_count=int(len(daily_price)),
            reasons=score_reasons or ["可用评分结果为空，无法运行回测。"],
            data_quality_notes=data_quality_notes,
        )

    selected = select_top_stocks(score_df, top_n=min(20, max(1, _unique_count(score_df, "ts_code"))))
    portfolio = build_equal_weight_portfolio(selected, max_positions=20)
    result = run_backtest(
        daily_price,
        score_df,
        start_date=str(score_df["trade_date"].min()),
        end_date=end_date,
        top_n=min(20, max(1, _unique_count(score_df, "ts_code"))),
    )
    return _build_result(
        settings=settings,
        store=store,
        data_type=f"{settings.data_provider} 本地 DuckDB 真实数据",
        start_date=str(score_df["trade_date"].min()),
        end_date=end_date,
        stock_count=_unique_count(stock_basic, "ts_code"),
        price_row_count=int(len(daily_price)),
        score_stock_count=_unique_count(score_df, "ts_code"),
        portfolio_built=not portfolio.empty,
        backtest_result=result,
        reasons=[],
        data_quality_notes=data_quality_notes,
    )


def _diagnose_sample_backtest(settings: Settings, store: DuckDBStore) -> dict[str, Any]:
    """Build diagnostics from packaged sample backtest data."""
    data = get_sample_dashboard_data()
    backtest = data.get("backtest", {})
    price = data.get("price", pd.DataFrame())
    selection = data.get("selection", pd.DataFrame())
    return _build_result(
        settings=settings,
        store=store,
        data_type="sample 数据（演示）",
        start_date=_earliest_date(price, "trade_date"),
        end_date=_latest_date(price, "trade_date"),
        stock_count=_unique_count(data.get("stock_basic", pd.DataFrame()), "ts_code"),
        price_row_count=int(len(price)),
        score_stock_count=_unique_count(selection, "ts_code"),
        portfolio_built=not selection.empty,
        backtest_result=backtest,
        reasons=[],
        data_quality_notes=["当前为 sample 演示数据，仅用于流程验证。"],
    )


def _build_score_history(
    settings: Settings,
    stock_basic: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """Generate historical scores from existing factors without future data."""
    if daily_price.empty or "trade_date" not in daily_price.columns:
        return pd.DataFrame(), ["daily_price 缺少可用 trade_date。"]

    dates = sorted(daily_price["trade_date"].dropna().astype(str).unique().tolist())
    if len(dates) < 20:
        return pd.DataFrame(), ["可用行情少于 20 个交易日，无法进行最小回测。"]

    is_akshare = settings.data_provider == "akshare"
    score_frames: list[pd.DataFrame] = []
    for trade_date in dates:
        universe = build_tradeable_universe(
            stock_basic,
            daily_price,
            daily_basic,
            trade_date,
            allow_missing_list_date_with_price_history=is_akshare,
            min_price_history_days=60,
            allow_missing_valuation=is_akshare,
        )
        tradeable = universe[universe["is_tradeable"].fillna(False)].copy()
        if tradeable.empty:
            continue
        scores = _calculate_minimal_real_scores(daily_price, daily_basic, tradeable, trade_date)
        if not scores.empty:
            score_frames.append(scores)

    if not score_frames:
        return pd.DataFrame(), ["股票池或因子评分在可用日期内为空。"]
    score_df = pd.concat(score_frames, ignore_index=True)
    return score_df[score_df["total_score"].notna()].reset_index(drop=True), []


def _build_result(
    settings: Settings,
    store: DuckDBStore,
    data_type: str,
    start_date: str | None,
    end_date: str | None,
    stock_count: int,
    price_row_count: int,
    score_stock_count: int,
    portfolio_built: bool,
    backtest_result: dict[str, Any],
    reasons: list[str],
    data_quality_notes: list[str],
) -> dict[str, Any]:
    """Build the structured diagnostic result."""
    metrics = {key: _optional_float(backtest_result.get(key)) for key in METRIC_KEYS}
    anomalies = _find_anomalies(metrics, backtest_result)
    return {
        "data_provider": settings.data_provider,
        "duckdb_path": str(store.db_path),
        "data_type": data_type,
        "start_date": start_date,
        "end_date": end_date,
        "stock_count": stock_count,
        "price_row_count": price_row_count,
        "score_stock_count": score_stock_count,
        "portfolio_built": portfolio_built,
        "metrics": metrics,
        "equity_curve_rows": _frame_len(backtest_result.get("equity_curve")),
        "trade_records_rows": _frame_len(backtest_result.get("trade_records")),
        "position_records_rows": _frame_len(backtest_result.get("position_records")),
        "backtest_result": backtest_result,
        "has_anomaly": bool(anomalies),
        "anomalies": anomalies,
        "reasons": reasons,
        "data_quality_notes": data_quality_notes,
        "next_steps": _next_steps(bool(reasons), _frame_len(backtest_result.get("equity_curve"))),
    }


def _empty_result(
    settings: Settings,
    store: DuckDBStore,
    data_type: str,
    reasons: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    stock_count: int = 0,
    price_row_count: int = 0,
    data_quality_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Return an empty diagnostic with concrete reasons."""
    return _build_result(
        settings=settings,
        store=store,
        data_type=data_type,
        start_date=start_date,
        end_date=end_date,
        stock_count=stock_count,
        price_row_count=price_row_count,
        score_stock_count=0,
        portfolio_built=False,
        backtest_result={},
        reasons=reasons,
        data_quality_notes=data_quality_notes or [],
    )


def _missing_table_reasons(tables: dict[str, pd.DataFrame]) -> list[str]:
    """Return reasons for empty core backtest inputs."""
    reasons: list[str] = []
    for table_name in CORE_TABLES:
        if tables.get(table_name, pd.DataFrame()).empty:
            reasons.append(f"{table_name} 无数据。")
    return reasons


def _data_quality_notes(data_provider: str, daily_basic: pd.DataFrame, adj_factor: pd.DataFrame) -> list[str]:
    """Return provider-specific data quality notes."""
    notes = ["回测结果仅为少量样本真实数据试运行，不代表正式投资策略表现。"]
    if data_provider == "akshare":
        notes.append("AKShare fallback 当前只用于少量股票真实数据试运行。")
        if _column_all_missing(daily_basic, "pe") or _column_all_missing(daily_basic, "pb"):
            notes.append("AKShare fallback 的 pe/pb 可能为空。")
        if not adj_factor.empty and "adj_factor" in adj_factor.columns:
            values = pd.to_numeric(adj_factor["adj_factor"], errors="coerce").dropna()
            if not values.empty and bool((values == 1.0).all()):
                notes.append("AKShare fallback 的 adj_factor 当前可能简化为 1.0。")
    return notes


def _find_anomalies(metrics: dict[str, float | None], backtest_result: dict[str, Any]) -> list[str]:
    """Return simple anomaly descriptions for backtest outputs."""
    anomalies: list[str] = []
    for key, value in metrics.items():
        if value is None:
            anomalies.append(f"{key} 缺失。")
    equity_curve = backtest_result.get("equity_curve", pd.DataFrame())
    if isinstance(equity_curve, pd.DataFrame) and not equity_curve.empty and "equity" in equity_curve.columns:
        equity = pd.to_numeric(equity_curve["equity"], errors="coerce")
        if (equity.dropna() <= 0).any():
            anomalies.append("equity_curve 存在非正权益。")
    return anomalies


def _next_steps(has_reasons: bool, equity_rows: int) -> list[str]:
    """Return suggested follow-up commands."""
    if has_reasons or equity_rows == 0:
        return [
            "python -m core.jobs.update_real_data",
            "python -m core.jobs.diagnose_real_data",
            "python -m core.jobs.diagnose_factors",
            "python -m core.jobs.diagnose_backtest",
        ]
    return ["streamlit run web/streamlit_app.py"]


def _latest_date(df: pd.DataFrame, column: str) -> str | None:
    """Return latest date string from a DataFrame."""
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    return None if values.empty else str(values.max())


def _earliest_date(df: pd.DataFrame, column: str) -> str | None:
    """Return earliest date string from a DataFrame."""
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    return None if values.empty else str(values.min())


def _unique_count(df: pd.DataFrame, column: str) -> int:
    """Return unique value count for one column."""
    if df.empty or column not in df.columns:
        return 0
    return int(df[column].dropna().astype(str).nunique())


def _frame_len(value: Any) -> int:
    """Return DataFrame length or zero for missing values."""
    return int(len(value)) if isinstance(value, pd.DataFrame) else 0


def _optional_float(value: Any) -> float | None:
    """Convert numeric values to float while preserving missing values."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def _column_all_missing(df: pd.DataFrame, column: str) -> bool:
    """Return whether a column is absent or entirely missing."""
    if df.empty or column not in df.columns:
        return True
    return bool(pd.to_numeric(df[column], errors="coerce").dropna().empty)


if __name__ == "__main__":
    main()
