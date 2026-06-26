"""Daily stock selection smoke entrypoint for local MVP runs."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.sample_data import DEMO_DATA_SOURCE, get_sample_dashboard_data
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


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
    if resolved_settings.data_provider == "tushare":
        real_summary = _try_real_data_summary(store or DuckDBStore(resolved_settings.duckdb_path))
        if real_summary["candidate_count"] > 0:
            return real_summary
        if not use_sample:
            return real_summary

    if not use_sample:
        return _empty_summary("无数据")

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
        "result_location": "未写入数据库；当前使用演示数据完成本地 smoke test。",
    }


def main() -> None:
    """Print the MVP daily selection summary."""
    summary = run_daily_selection()
    print("每日选股任务摘要")
    print(f"- 当前运行日期: {summary['run_date']}")
    print(f"- 数据来源: {summary['data_source']}")
    print(f"- 股票池数量: {summary['stock_pool_count']}")
    print(f"- 评分股票数量: {summary['scored_stock_count']}")
    print(f"- 候选股票数量: {summary['candidate_count']}")
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


def _empty_summary(data_source: str) -> dict[str, Any]:
    """Return a clear no-data summary instead of raising an opaque error."""
    return {
        "run_date": date.today().isoformat(),
        "data_source": data_source,
        "stock_pool_count": 0,
        "scored_stock_count": 0,
        "candidate_count": 0,
        "top_candidates": [],
        "result_location": "未生成结果；请导入本地数据或启用演示数据。",
    }


def _try_real_data_summary(store: DuckDBStore) -> dict[str, Any]:
    """Try to summarize real local DuckDB results without crashing on empty data."""
    if not store.db_path.exists():
        summary = _empty_summary("无数据")
        summary["result_location"] = "真实 DuckDB 文件不存在；可回退 sample 数据。"
        return summary

    try:
        stock_basic = store.read_table("stock_basic")
        daily_price = store.read_table("daily_price")
        strategy_result = store.read_table("strategy_result")
        factor_scores = store.read_table("factor_scores")
    except DuckDBStoreError:
        summary = _empty_summary("无数据")
        summary["result_location"] = "真实 DuckDB 数据不可用；可回退 sample 数据。"
        return summary

    if daily_price.empty or stock_basic.empty:
        summary = _empty_summary("无数据")
        summary["result_location"] = "真实 DuckDB 数据不足；可回退 sample 数据。"
        return summary

    if strategy_result.empty or factor_scores.empty:
        return {
            "run_date": date.today().isoformat(),
            "data_source": "tushare 本地 DuckDB（未生成真实选股结果，回退 sample 数据）",
            "stock_pool_count": int(len(stock_basic)),
            "scored_stock_count": int(len(factor_scores)),
            "candidate_count": 0,
            "top_candidates": [],
            "result_location": "已检测到真实行情数据，但尚无真实因子评分或选股结果。",
        }

    return {
        "run_date": date.today().isoformat(),
        "data_source": "tushare 本地 DuckDB",
        "stock_pool_count": int(len(stock_basic)),
        "scored_stock_count": int(len(factor_scores)),
        "candidate_count": int(len(strategy_result)),
        "top_candidates": _top_candidate_records(strategy_result),
        "result_location": "读取本地 DuckDB strategy_result。",
    }


def _top_candidate_records(selection: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]]:
    """Return compact candidate records for command-line output."""
    if selection.empty:
        return []
    columns = ["rank", "ts_code", "name", "total_score"]
    available = [column for column in columns if column in selection.columns]
    return selection.head(limit)[available].to_dict("records")


if __name__ == "__main__":
    main()
