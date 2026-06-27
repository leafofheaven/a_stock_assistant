"""Diagnose manual review decisions and active watchlist."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from core.review.decisions import build_watchlist_dataframe, summarize_review_decisions
from core.storage.duckdb_store import DuckDBStore


def diagnose_watchlist(
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Return current watchlist diagnostics from local DuckDB."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    summary = summarize_review_decisions(resolved_store)
    watchlist = build_watchlist_dataframe(resolved_store, active_only=True)
    return {
        "data_provider": resolved_settings.data_provider,
        "duckdb_path": str(resolved_store.db_path),
        "review_decisions_rows": summary["total_rows"],
        "active_watch_count": summary["active_watch_count"],
        "pending_count": summary["decision_counts"].get("pending", 0),
        "needs_data_count": summary["decision_counts"].get("needs_data", 0),
        "exclude_count": summary["decision_counts"].get("exclude", 0),
        "pass_count": summary["decision_counts"].get("pass", 0),
        "watchlist": watchlist.to_dict("records"),
        "next_steps": _next_steps(summary["active_watch_count"]),
    }


def main() -> None:
    """Print watchlist diagnostics."""
    result = diagnose_watchlist()
    print("观察池诊断摘要")
    print(f"- 当前 DATA_PROVIDER: {result['data_provider']}")
    print(f"- DuckDB 路径: {result['duckdb_path']}")
    print(f"- review_decisions 行数: {result['review_decisions_rows']}")
    print(f"- active watch 数量: {result['active_watch_count']}")
    print(f"- pending 数量: {result['pending_count']}")
    print(f"- needs_data 数量: {result['needs_data_count']}")
    print(f"- exclude 数量: {result['exclude_count']}")
    print(f"- pass 数量: {result['pass_count']}")
    print("- 当前观察池股票列表:")
    if result["watchlist"]:
        for item in result["watchlist"]:
            print(
                f"  {item.get('ts_code')} {item.get('name')} selection_date={item.get('selection_date')} "
                f"review_date={item.get('review_date')} decision={item.get('decision')} "
                f"reason={item.get('reason') or '暂无'} notes={item.get('notes') or '暂无'} "
                f"latest_trade_date={item.get('latest_trade_date') or '暂无'} "
                f"latest_close={item.get('latest_close')} total_score={item.get('total_score')} "
                f"data_quality_note={item.get('data_quality_note') or '暂无'}"
            )
    else:
        print("  暂无 active watch 股票。")
    print("- 下一步建议:")
    for step in result["next_steps"]:
        print(f"  {step}")


def _next_steps(active_watch_count: int) -> list[str]:
    if active_watch_count == 0:
        return ["python -m core.jobs.export_review_template", "python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv"]
    return ["python -m core.jobs.export_watchlist", "streamlit run web/streamlit_app.py"]


if __name__ == "__main__":
    main()
