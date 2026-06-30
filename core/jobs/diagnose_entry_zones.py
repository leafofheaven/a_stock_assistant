"""Diagnose persisted entry zone snapshots."""

from __future__ import annotations

import argparse
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


def diagnose_entry_zones(
    *,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """Return a concise diagnostic summary for latest entry zone snapshots."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    snapshots = _safe_read_table(resolved_store, "entry_zone_snapshots")
    latest = _latest_snapshots(snapshots)
    result = {
        "status": "success" if not latest.empty else "partial_success",
        "trade_date": _latest_date(snapshots, "trade_date"),
        "calculated_count": int(len(latest)),
        "status_counts": _counts(latest, "entry_zone_status"),
        "high_chase_risk_count": _count_equals(latest, "chase_risk", "high"),
        "reward_risk_gte_2_count": _count_reward_risk(latest),
        "message": "已读取最新买入区间快照。" if not latest.empty else "暂无 entry_zone_snapshots，请先运行 calculate_entry_zones。",
    }
    if not quiet:
        print(_console_summary(result))
    return result


def _latest_snapshots(snapshots: pd.DataFrame) -> pd.DataFrame:
    if snapshots.empty or "trade_date" not in snapshots.columns:
        return pd.DataFrame()
    latest = _latest_date(snapshots, "trade_date")
    return snapshots[snapshots["trade_date"].astype(str) == str(latest)].copy()


def _counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if df.empty or column not in df.columns:
        return {}
    return {str(key): int(value) for key, value in df[column].fillna("unknown").value_counts().items()}


def _count_equals(df: pd.DataFrame, column: str, value: str) -> int:
    if df.empty or column not in df.columns:
        return 0
    return int((df[column].astype(str) == value).sum())


def _count_reward_risk(df: pd.DataFrame) -> int:
    if df.empty or "reward_risk_ratio" not in df.columns:
        return 0
    return int((pd.to_numeric(df["reward_risk_ratio"], errors="coerce") >= 2).sum())


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


def _console_summary(result: dict[str, Any]) -> str:
    counts = result.get("status_counts", {})
    return "\n".join(
        [
            "买入区间诊断摘要",
            f"- 状态: {result.get('status')}",
            f"- 交易日期: {result.get('trade_date') or '暂无'}",
            f"- 已计算股票数量: {result.get('calculated_count', 0)}",
            f"- in_zone 数量: {counts.get('in_zone', 0)}",
            f"- near_zone 数量: {counts.get('near_zone', 0)}",
            f"- above_zone 数量: {counts.get('above_zone', 0)}",
            f"- weak_no_entry 数量: {counts.get('weak_no_entry', 0)}",
            f"- insufficient_data 数量: {counts.get('insufficient_data', 0)}",
            f"- 高追高风险数量: {result.get('high_chase_risk_count', 0)}",
            f"- 盈亏比 >= 2 数量: {result.get('reward_risk_gte_2_count', 0)}",
            f"- 说明: {result.get('message', '')}",
        ]
    )


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and print diagnostics."""
    parser = argparse.ArgumentParser(description="Diagnose latest entry zone snapshots.")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    args = parser.parse_args(argv)
    diagnose_entry_zones(quiet=args.quiet)


if __name__ == "__main__":
    main()

