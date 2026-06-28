"""Factor diagnostics for local sample or real DuckDB data."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.jobs.run_daily_selection import _calculate_minimal_real_scores
from core.sample_data import get_sample_dashboard_data
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.strategy.selector import select_top_stocks
from core.universe.stock_pool import build_tradeable_universe


CORE_TABLES = ["stock_basic", "daily_price", "daily_basic", "adj_factor"]
FACTOR_COLUMNS = [
    "return_20d",
    "avg_amount_20d",
    "avg_turnover_20d",
    "pe_score",
    "volatility_20d",
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "fundamental_score",
    "volatility_score",
    "total_score",
]


def diagnose_factors(
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    use_sample: bool = True,
) -> dict[str, Any]:
    """Diagnose factor coverage and score quality for local data.

    The function never fetches external data. It only reads local DuckDB tables
    or clearly marked sample data. AKShare fallback limitations are surfaced as
    quality notes instead of failing the whole diagnostic when PE/PB or true
    adjustment factors are unavailable.
    """
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)

    if resolved_settings.data_provider == "sample":
        return _diagnose_sample_data(resolved_settings, resolved_store)

    if not resolved_store.db_path.exists():
        if use_sample:
            result = _diagnose_sample_data(resolved_settings, resolved_store)
            result["data_type"] = "sample 数据（真实 DuckDB 文件不存在）"
            result["reasons"] = ["真实 DuckDB 文件不存在，已使用 sample 数据诊断。"]
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
            result = _diagnose_sample_data(resolved_settings, resolved_store)
            result["data_type"] = "sample 数据（真实 DuckDB 读取失败）"
            result["reasons"] = [f"真实 DuckDB 读取失败：{exc}；已使用 sample 数据诊断。"]
            return result
        return _empty_result(
            settings=resolved_settings,
            store=resolved_store,
            data_type="无数据",
            reasons=[f"真实 DuckDB 读取失败：{exc}。"],
        )

    return _diagnose_real_tables(resolved_settings, resolved_store, tables)


def main() -> None:
    """Print factor diagnostics."""
    result = diagnose_factors()
    print("因子质量诊断摘要")
    print(f"- 当前 DATA_PROVIDER: {result['data_provider']}")
    print(f"- DuckDB 路径: {result['duckdb_path']}")
    print(f"- 当前使用的数据类型: {result['data_type']}")
    print(f"- 最新行情日期: {result['latest_price_date'] or '暂无'}")
    print(f"- 股票池数量: {result['stock_pool_count']}")
    print(f"- 可计算因子的股票数量: {result['factor_calculable_count']}")
    print(f"- total_score 非空股票数量: {result['total_score_non_null_count']}")
    print("- 因子质量:")
    for factor_name, stats in result["factor_quality"].items():
        print(
            f"  {factor_name}: non_null_rate={stats['non_null_rate']:.2f}, "
            f"nan_count={stats['nan_count']}, min={stats['min']}, max={stats['max']}, "
            f"mean={stats['mean']}, median={stats['median']}"
        )
    print("- Top 10 综合评分股票:")
    if result["top_10"]:
        for item in result["top_10"]:
            print(f"  {item['rank']}. {item['ts_code']} {item.get('name', '')} 综合分 {item['total_score']:.2f}")
    else:
        print("  暂无。")
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


def _diagnose_real_tables(
    settings: Settings,
    store: DuckDBStore,
    tables: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Build a factor diagnostic from local real-data tables."""
    stock_basic = tables["stock_basic"]
    daily_price = tables["daily_price"]
    daily_basic = tables["daily_basic"]
    adj_factor = tables["adj_factor"]
    reasons = _missing_table_reasons(tables)
    latest_trade_date = _latest_date(daily_price, "trade_date")
    data_quality_notes = _data_quality_notes(settings.data_provider, daily_basic, adj_factor)

    if reasons or latest_trade_date is None:
        return _empty_result(
            settings=settings,
            store=store,
            data_type=f"{settings.data_provider} 本地 DuckDB 真实数据",
            latest_price_date=latest_trade_date,
            reasons=reasons or ["daily_price 缺少可用 trade_date。"],
            data_quality_notes=data_quality_notes,
        )

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
        return _empty_result(
            settings=settings,
            store=store,
            data_type=f"{settings.data_provider} 本地 DuckDB 真实数据",
            latest_price_date=latest_trade_date,
            stock_pool_count=int(len(universe)),
            reasons=["股票池过滤后无可交易股票。"],
            data_quality_notes=data_quality_notes,
        )

    factor_scores = _calculate_minimal_real_scores(daily_price, daily_basic, tradeable, latest_trade_date)
    data_quality_notes.extend(_fundamental_missing_notes(daily_basic, factor_scores))
    selected = select_top_stocks(factor_scores, top_n=10)
    return _build_result(
        settings=settings,
        store=store,
        data_type=f"{settings.data_provider} 本地 DuckDB 真实数据",
        latest_price_date=latest_trade_date,
        stock_pool_count=int(len(tradeable)),
        factor_scores=factor_scores,
        selected=selected,
        reasons=[],
        data_quality_notes=data_quality_notes,
    )


def _diagnose_sample_data(settings: Settings, store: DuckDBStore) -> dict[str, Any]:
    """Build diagnostics from packaged sample data."""
    data = get_sample_dashboard_data()
    factor_scores = data.get("factor_scores", pd.DataFrame())
    selected = data.get("selection", pd.DataFrame())
    return _build_result(
        settings=settings,
        store=store,
        data_type="sample 数据（演示）",
        latest_price_date=_latest_date(data.get("price", pd.DataFrame()), "trade_date"),
        stock_pool_count=int(len(data.get("stock_basic", pd.DataFrame()))),
        factor_scores=factor_scores,
        selected=selected,
        reasons=[],
        data_quality_notes=["当前为 sample 演示数据，仅用于流程验证。"],
    )


def _build_result(
    settings: Settings,
    store: DuckDBStore,
    data_type: str,
    latest_price_date: str | None,
    stock_pool_count: int,
    factor_scores: pd.DataFrame,
    selected: pd.DataFrame,
    reasons: list[str],
    data_quality_notes: list[str],
) -> dict[str, Any]:
    """Build the structured diagnostic result."""
    factor_quality = _factor_quality(factor_scores)
    total_non_null = _non_null_count(factor_scores, "total_score")
    anomalies = _find_anomalies(factor_scores)
    return {
        "data_provider": settings.data_provider,
        "duckdb_path": str(store.db_path),
        "data_type": data_type,
        "latest_price_date": latest_price_date,
        "stock_pool_count": stock_pool_count,
        "factor_calculable_count": int(len(factor_scores)),
        "factor_quality": factor_quality,
        "total_score_non_null_count": total_non_null,
        "top_10": _top_records(selected),
        "factor_scores_df": factor_scores,
        "selected_df": selected,
        "has_anomaly": bool(anomalies),
        "anomalies": anomalies,
        "reasons": reasons,
        "data_quality_notes": data_quality_notes,
        "next_steps": _next_steps(bool(reasons), total_non_null),
    }


def _empty_result(
    settings: Settings,
    store: DuckDBStore,
    data_type: str,
    reasons: list[str],
    latest_price_date: str | None = None,
    stock_pool_count: int = 0,
    data_quality_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Return an empty diagnostic with concrete reasons."""
    return _build_result(
        settings=settings,
        store=store,
        data_type=data_type,
        latest_price_date=latest_price_date,
        stock_pool_count=stock_pool_count,
        factor_scores=pd.DataFrame(columns=FACTOR_COLUMNS),
        selected=pd.DataFrame(),
        reasons=reasons,
        data_quality_notes=data_quality_notes or [],
    )


def _factor_quality(factor_scores: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Calculate coverage and descriptive stats for factor columns."""
    quality: dict[str, dict[str, Any]] = {}
    row_count = len(factor_scores)
    for column in FACTOR_COLUMNS:
        if column not in factor_scores.columns:
            values = pd.Series(dtype="float64")
        else:
            values = pd.to_numeric(factor_scores[column], errors="coerce")
        non_null = int(values.notna().sum())
        quality[column] = {
            "non_null_rate": float(non_null / row_count) if row_count else 0.0,
            "nan_count": int(row_count - non_null),
            "min": _optional_float(values.min()),
            "max": _optional_float(values.max()),
            "mean": _optional_float(values.mean()),
            "median": _optional_float(values.median()),
        }
    return quality


def _find_anomalies(factor_scores: pd.DataFrame) -> list[str]:
    """Return simple anomaly descriptions for score columns."""
    anomalies: list[str] = []
    for column in [name for name in FACTOR_COLUMNS if name.endswith("_score") or name == "total_score"]:
        if column not in factor_scores.columns:
            continue
        values = pd.to_numeric(factor_scores[column], errors="coerce")
        if ((values.dropna() < 0) | (values.dropna() > 100)).any():
            anomalies.append(f"{column} 存在 0-100 以外的值。")
    return anomalies


def _data_quality_notes(data_provider: str, daily_basic: pd.DataFrame, adj_factor: pd.DataFrame) -> list[str]:
    """Return provider-specific data quality notes."""
    notes: list[str] = []
    if daily_basic.empty:
        notes.append("daily_basic 缺失，fundamental_score 可能为空。")
    else:
        latest_basic = _latest_trade_date_rows(daily_basic)
        if "pe" not in latest_basic.columns:
            notes.append("daily_basic 缺少 pe 字段，pe_score 与 fundamental_score 可能为空。")
        elif _column_all_missing(latest_basic, "pe"):
            notes.append("pe 全部缺失，pe_score 与 fundamental_score 可能为空。")
        elif _column_has_missing(latest_basic, "pe"):
            notes.append("最新交易日部分股票 pe 缺失，缺失股票的 pe_score 与 fundamental_score 可能为空。")
        if "pb" not in latest_basic.columns:
            notes.append("daily_basic 缺少 pb 字段，估值相关复核信息不完整。")
        elif _column_all_missing(latest_basic, "pb"):
            notes.append("pb 全部缺失，估值相关复核信息不完整。")
        elif _column_has_missing(latest_basic, "pb"):
            notes.append("最新交易日部分股票 pb 缺失，缺失股票的估值相关复核信息不完整。")
        if (
            not _column_has_missing(latest_basic, "pe")
            and not _column_has_missing(latest_basic, "pb")
            and (_column_has_missing(daily_basic, "pe") or _column_has_missing(daily_basic, "pb"))
        ):
            notes.append("PE/PB 当前仅补全最新交易日，历史区间估值字段可能为空。")
    if data_provider == "akshare":
        notes.append("AKShare fallback 当前只用于少量股票真实数据试运行。")
        if _column_all_missing(daily_basic, "pe") or _column_all_missing(daily_basic, "pb"):
            notes.append("AKShare fallback 的 pe/pb 可能为空，基本面分项可能偏低或为空。")
        if not adj_factor.empty and "adj_factor" in adj_factor.columns:
            values = pd.to_numeric(adj_factor["adj_factor"], errors="coerce").dropna()
            if not values.empty and bool((values == 1.0).all()):
                notes.append("AKShare fallback 的 adj_factor 当前简化为 1.0。")
    return notes


def _latest_trade_date_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows for the latest trade_date in a DataFrame."""
    if df.empty or "trade_date" not in df.columns:
        return df.copy()
    values = df["trade_date"].dropna().astype(str)
    if values.empty:
        return df.copy()
    latest = str(values.max())
    return df[df["trade_date"].astype(str) == latest].copy()


def _fundamental_missing_notes(daily_basic: pd.DataFrame, factor_scores: pd.DataFrame) -> list[str]:
    """Explain empty fundamental_score when valuation inputs are incomplete."""
    if factor_scores.empty or "fundamental_score" not in factor_scores.columns:
        return []
    values = pd.to_numeric(factor_scores["fundamental_score"], errors="coerce")
    if values.notna().any():
        return []
    reasons: list[str] = []
    if daily_basic.empty:
        reasons.append("fundamental_score 为空原因：daily_basic 无数据。")
    elif _column_all_missing(daily_basic, "pe") and _column_all_missing(daily_basic, "pb"):
        reasons.append("fundamental_score 为空原因：pe/pb 均缺失。")
    elif _column_all_missing(daily_basic, "pe"):
        reasons.append("fundamental_score 为空原因：pe 缺失。")
    elif _column_all_missing(daily_basic, "pb"):
        reasons.append("fundamental_score 为空原因：pb 缺失。")
    return reasons


def _column_has_missing(df: pd.DataFrame, column: str) -> bool:
    """Return whether some but not all values in a column are missing."""
    if df.empty or column not in df.columns:
        return False
    values = pd.to_numeric(df[column], errors="coerce")
    return bool(values.isna().any() and values.notna().any())


def _missing_table_reasons(tables: dict[str, pd.DataFrame]) -> list[str]:
    """Return reasons for empty or missing core factor inputs."""
    reasons: list[str] = []
    for table_name in CORE_TABLES:
        frame = tables.get(table_name, pd.DataFrame())
        if frame.empty:
            reasons.append(f"{table_name} 无数据。")
    return reasons


def _top_records(selected: pd.DataFrame) -> list[dict[str, Any]]:
    """Return top candidate records for diagnostics."""
    if selected.empty:
        return []
    columns = ["rank", "ts_code", "name", "industry", "total_score", "risk_note"]
    available = [column for column in columns if column in selected.columns]
    return selected.head(10)[available].to_dict("records")


def _non_null_count(df: pd.DataFrame, column: str) -> int:
    """Return non-null numeric count for a column."""
    if df.empty or column not in df.columns:
        return 0
    return int(pd.to_numeric(df[column], errors="coerce").notna().sum())


def _column_all_missing(df: pd.DataFrame, column: str) -> bool:
    """Return whether a column is absent or entirely missing."""
    if df.empty or column not in df.columns:
        return True
    return bool(pd.to_numeric(df[column], errors="coerce").dropna().empty)


def _latest_date(df: pd.DataFrame, column: str) -> str | None:
    """Return latest date string from a DataFrame."""
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    return None if values.empty else str(values.max())


def _optional_float(value: Any) -> float | None:
    """Convert pandas/numpy scalars to plain floats while preserving NaN as None."""
    if pd.isna(value):
        return None
    return float(value)


def _next_steps(has_reasons: bool, total_non_null: int) -> list[str]:
    """Return suggested follow-up commands."""
    if has_reasons or total_non_null == 0:
        return [
            "python -m core.jobs.update_real_data",
            "python -m core.jobs.diagnose_real_data",
            "python -m core.jobs.diagnose_factors",
        ]
    return ["python -m core.jobs.run_daily_selection", "streamlit run web/streamlit_app.py"]


if __name__ == "__main__":
    main()
