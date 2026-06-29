"""Diagnose manual review decisions and active watchlist."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from core.review.decisions import build_watchlist_dataframe, summarize_review_decisions
from core.review.tracking import WATCH_STATUS_LABELS, summarize_watchlist_tracking
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
    tracking = summarize_watchlist_tracking(resolved_store)
    return {
        "data_provider": resolved_settings.data_provider,
        "duckdb_path": str(resolved_store.db_path),
        "review_decisions_rows": summary["total_rows"],
        "active_watch_count": summary["active_watch_count"],
        "pending_count": summary["decision_counts"].get("pending", 0),
        "needs_data_count": summary["decision_counts"].get("needs_data", 0),
        "exclude_count": summary["decision_counts"].get("exclude", 0),
        "pass_count": summary["decision_counts"].get("pass", 0),
        "tracking_snapshot_count": tracking["snapshot_count"],
        "watch_status_counts": tracking["status_counts"],
        "new_candidate_count": tracking["new_candidate_count"],
        "strong_watch_count": tracking["strong_watch_count"],
        "wait_pullback_count": tracking["wait_pullback_count"],
        "overheated_count": tracking["overheated_count"],
        "weakening_count": tracking["weakening_count"],
        "invalidated_count": tracking["invalidated_count"],
        "near_buy_zone_count": tracking["near_buy_zone_count"],
        "event_count": tracking["event_count"],
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
    print(f"- 每日跟踪 snapshot 数量: {result['tracking_snapshot_count']}")
    print(f"- 观察池事件数量: {result['event_count']}")
    print("- 观察池分层数量:")
    counts = result.get("watch_status_counts") or {}
    for key, label in WATCH_STATUS_LABELS.items():
        print(f"  {label}: {counts.get(key, 0)}")
    print("- 当前观察池股票列表:")
    if result["watchlist"]:
        for item in result["watchlist"]:
            print(
                f"  {item.get('ts_code')} {item.get('name')} selection_date={item.get('selection_date')} "
                f"review_date={item.get('review_date')} decision={item.get('decision')} "
                f"review_status={item.get('review_status') or '暂无'} "
                f"reviewer={item.get('reviewer') or '暂无'} "
                f"reason={item.get('reason') or '暂无'} notes={item.get('notes') or '暂无'} "
                f"latest_action_type={item.get('latest_action_type') or '暂无'} "
                f"latest_action_at={item.get('latest_action_at') or '暂无'} "
                f"history_count={item.get('history_count', 0)} "
                f"latest_trade_date={item.get('latest_trade_date') or '暂无'} "
                f"latest_close={item.get('latest_close')} pe={item.get('pe')} pb={item.get('pb')} "
                f"fundamental_score={item.get('fundamental_score')} total_score={item.get('total_score')} "
                f"score_missing_reason={item.get('score_missing_reason') or '无'} "
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
    return ["python -m core.jobs.refresh_watchlist_scores", "python -m core.jobs.export_watchlist", "streamlit run web/streamlit_app.py"]


if __name__ == "__main__":
    main()
