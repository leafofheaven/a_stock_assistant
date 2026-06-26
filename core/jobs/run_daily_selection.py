"""Daily stock selection smoke entrypoint for local MVP runs."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from core.sample_data import DEMO_DATA_SOURCE, get_sample_dashboard_data


def run_daily_selection(use_sample: bool = True) -> dict[str, Any]:
    """Run the MVP daily selection command and return a summary.

    The current MVP does not fetch external data, place trades, or promise
    investment outcomes. When no real local pipeline output is available, the
    function uses clearly marked demo data so users can verify installation,
    command execution, and dashboard wiring end to end.
    """
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


def _top_candidate_records(selection: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]]:
    """Return compact candidate records for command-line output."""
    if selection.empty:
        return []
    columns = ["rank", "ts_code", "name", "total_score"]
    available = [column for column in columns if column in selection.columns]
    return selection.head(limit)[available].to_dict("records")


if __name__ == "__main__":
    main()
