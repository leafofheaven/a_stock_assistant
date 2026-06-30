"""Calculate entry zone snapshots from local selection and watchlist data."""

from __future__ import annotations

import argparse
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.entry_zones.calculator import ENTRY_ZONE_COLUMNS, calculate_entry_zones_for_targets
from core.review.decisions import build_watchlist_dataframe
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


def calculate_entry_zones(
    *,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """Calculate and persist entry zone snapshots for latest candidates and watchlist."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    resolved_store.initialize()
    price_df = _safe_read_table(resolved_store, "daily_price")
    strategy = _latest_strategy_result(_safe_read_table(resolved_store, "strategy_result"))
    watchlist = _watchlist_targets(resolved_store)
    if price_df.empty:
        result = _empty_result("本地 daily_price 为空，无法计算买入区间。")
        if not quiet:
            print(_console_summary(result))
        return result

    frames: list[pd.DataFrame] = []
    latest_trade_date = _latest_date(price_df, "trade_date")
    if not strategy.empty:
        frames.append(
            calculate_entry_zones_for_targets(
                price_df,
                _target_columns(strategy, "selection"),
                trade_date=latest_trade_date,
                source="selection",
            )
        )
    if not watchlist.empty:
        frames.append(
            calculate_entry_zones_for_targets(
                price_df,
                _target_columns(watchlist, "watchlist"),
                trade_date=latest_trade_date,
                source="watchlist",
            )
        )
    snapshots = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=ENTRY_ZONE_COLUMNS)
    written = 0 if snapshots.empty else resolved_store.upsert_dataframe("entry_zone_snapshots", snapshots)
    result = {
        "status": "success" if written > 0 else "partial_success",
        "message": "买入区间计算完成。" if written > 0 else "没有可计算的候选或观察池股票。",
        "trade_date": latest_trade_date,
        "selection_count": int(len(strategy)),
        "watchlist_count": int(len(watchlist)),
        "calculated_count": int(len(snapshots)),
        "written_rows": int(written),
        "summary": _status_counts(snapshots),
        "next_steps": ["python -m core.jobs.diagnose_entry_zones", "python -m core.jobs.export_entry_zone_report"],
    }
    if not quiet:
        print(_console_summary(result))
    return result


def _latest_strategy_result(strategy: pd.DataFrame) -> pd.DataFrame:
    if strategy.empty or "trade_date" not in strategy.columns:
        return pd.DataFrame()
    latest = _latest_date(strategy, "trade_date")
    result = strategy[strategy["trade_date"].astype(str) == str(latest)].copy()
    if "rank" in result.columns:
        result = result.sort_values("rank")
    return result


def _watchlist_targets(store: DuckDBStore) -> pd.DataFrame:
    try:
        return build_watchlist_dataframe(store, active_only=True)
    except Exception:
        return pd.DataFrame()


def _target_columns(df: pd.DataFrame, source: str) -> pd.DataFrame:
    result = df.copy()
    if "name" not in result.columns:
        result["name"] = pd.NA
    result["source"] = source
    return result[["ts_code", "name", "source"]].dropna(subset=["ts_code"]).drop_duplicates(subset=["ts_code"])


def _status_counts(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "entry_zone_status" not in df.columns:
        return {}
    return {str(status): int(count) for status, count in df["entry_zone_status"].fillna("unknown").value_counts().items()}


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _latest_date(df: pd.DataFrame, column: str) -> str | None:
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    return None if values.empty else str(values.max())


def _empty_result(message: str) -> dict[str, Any]:
    return {
        "status": "partial_success",
        "message": message,
        "trade_date": None,
        "selection_count": 0,
        "watchlist_count": 0,
        "calculated_count": 0,
        "written_rows": 0,
        "summary": {},
        "next_steps": ["python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all"],
    }


def _console_summary(result: dict[str, Any]) -> str:
    counts = result.get("summary", {})
    return "\n".join(
        [
            "买入区间计算摘要",
            f"- 状态: {result.get('status')}",
            f"- 交易日期: {result.get('trade_date') or '暂无'}",
            f"- 今日候选数量: {result.get('selection_count', 0)}",
            f"- 观察池数量: {result.get('watchlist_count', 0)}",
            f"- 已计算股票数量: {result.get('calculated_count', 0)}",
            f"- 写入 entry_zone_snapshots 行数: {result.get('written_rows', 0)}",
            f"- in_zone: {counts.get('in_zone', 0)}",
            f"- near_zone: {counts.get('near_zone', 0)}",
            f"- above_zone: {counts.get('above_zone', 0)}",
            f"- weak_no_entry: {counts.get('weak_no_entry', 0)}",
            f"- insufficient_data: {counts.get('insufficient_data', 0)}",
            f"- 说明: {result.get('message', '')}",
        ]
    )


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and calculate entry zones."""
    parser = argparse.ArgumentParser(description="Calculate entry zones from local DuckDB data.")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    args = parser.parse_args(argv)
    calculate_entry_zones(quiet=args.quiet)


if __name__ == "__main__":
    main()

