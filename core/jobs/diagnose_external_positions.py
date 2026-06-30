"""Diagnose imported external simulated positions."""

from __future__ import annotations

import argparse
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.external_positions.importer import RISK_STATUS_CN
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


def diagnose_external_positions(*, settings: Settings | None = None, store: DuckDBStore | None = None, quiet: bool = False) -> dict[str, Any]:
    """Return a summary of external position snapshots."""
    resolved_store = store or DuckDBStore((settings or get_settings()).duckdb_path)
    resolved_store.initialize()
    positions = _safe_read_table(resolved_store, "external_position_snapshots")
    latest = _latest_positions(positions)
    result = {
        "status": "success" if not latest.empty else "partial_success",
        "platform_count": _nunique(latest, "platform"),
        "account_count": _nunique(latest, "account_name"),
        "position_count": int(len(latest)),
        "total_market_value": _sum(latest, "market_value"),
        "total_pnl": _sum(latest, "pnl"),
        "risk_counts": _counts(latest, "risk_status"),
        "near_stop_loss_count": _count(latest, "near_stop_loss"),
        "hit_stop_loss_count": _count(latest, "hit_stop_loss"),
        "hit_target_count": _count(latest, "hit_target"),
        "chased_high_count": _count(latest, "chased_high"),
        "unmatched_entry_zone_count": _count(latest, "insufficient_data"),
        "unknown_symbol_count": _contains(latest, "match_note", "unknown_symbol"),
        "message": "已读取外部模拟持仓。" if not latest.empty else "暂无外部模拟持仓，请先导入模板。",
    }
    if not quiet:
        print(_console_summary(result))
    return result


def _latest_positions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "snapshot_date" not in df.columns:
        return pd.DataFrame()
    latest = df["snapshot_date"].dropna().astype(str).max()
    return df[df["snapshot_date"].astype(str) == str(latest)].copy()


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _nunique(df: pd.DataFrame, column: str) -> int:
    return 0 if df.empty or column not in df.columns else int(df[column].dropna().nunique())


def _sum(df: pd.DataFrame, column: str) -> float:
    return 0.0 if df.empty or column not in df.columns else float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    return {} if df.empty or column not in df.columns else {str(k): int(v) for k, v in df[column].fillna("unknown").value_counts().items()}


def _count(df: pd.DataFrame, status: str) -> int:
    return 0 if df.empty or "risk_status" not in df.columns else int((df["risk_status"].astype(str) == status).sum())


def _contains(df: pd.DataFrame, column: str, text: str) -> int:
    return 0 if df.empty or column not in df.columns else int(df[column].fillna("").astype(str).str.contains(text, regex=False).sum())


def _console_summary(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "外部模拟持仓诊断摘要",
            f"- 状态: {result.get('status')}",
            f"- 平台数量: {result.get('platform_count', 0)}",
            f"- 账户数量: {result.get('account_count', 0)}",
            f"- 持仓股票数量: {result.get('position_count', 0)}",
            f"- 总市值: {result.get('total_market_value', 0):.2f}",
            f"- 总盈亏: {result.get('total_pnl', 0):.2f}",
            f"- 接近止损数量: {result.get('near_stop_loss_count', 0)}",
            f"- 跌破止损数量: {result.get('hit_stop_loss_count', 0)}",
            f"- 达到目标价数量: {result.get('hit_target_count', 0)}",
            f"- 成本高于买入区间数量: {result.get('chased_high_count', 0)}",
            f"- 未匹配买入区间数量: {result.get('unmatched_entry_zone_count', 0)}",
            f"- unknown symbol 数量: {result.get('unknown_symbol_count', 0)}",
            f"- 说明: {result.get('message')}",
        ]
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Diagnose external simulated positions.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    diagnose_external_positions(quiet=args.quiet)


if __name__ == "__main__":
    main()
