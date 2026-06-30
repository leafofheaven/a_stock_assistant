"""Parameterized full-universe batch update wrapper for Streamlit."""

from __future__ import annotations

import argparse
from typing import Any

from app.config import Settings, get_settings
from core.jobs.update_real_data import update_real_data
from core.runtime.data_source_preflight import run_data_source_preflight
from core.runtime.progress import print_progress


def run_full_batch_update(
    *,
    mode: str = "missing_first",
    max_symbols: int = 500,
    batch_size: int = 50,
    lookback_days: int = 250,
    max_retries: int = 1,
    skip_empty_unavailable: bool = True,
    preflight: bool = True,
    skip_network_preflight: bool = False,
    dry_run: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run a bounded full-universe update with page-selected runtime parameters."""
    base = settings or get_settings()
    runtime_settings = base.model_copy(
        update={
            "data_provider": "akshare",
            "akshare_sample_symbols": "",
            "real_universe_preset": "full",
            "full_update_batch_size": int(batch_size),
            "full_update_lookback_days": int(lookback_days),
            "full_update_max_retries": int(max_retries),
            "full_update_max_symbols": int(max_symbols),
            "full_update_max_batches": 0,
            "full_update_resume": True,
            "full_update_mode": mode,
            "full_update_skip_empty_unavailable": bool(skip_empty_unavailable),
            "full_enable_stock_basic_enrichment": False,
            "full_enable_valuation_enrichment": False,
        }
    )
    preflight_result: dict[str, Any] | None = None
    if preflight:
        preflight_result = run_data_source_preflight(settings=runtime_settings, skip_network=skip_network_preflight)
        if not preflight_result.get("ok"):
            return {
                "status": "failed",
                "message": preflight_result.get("message", "数据源预检失败，本次未启动批量更新。"),
                "preflight": preflight_result,
                "planned_symbols": 0,
            }
    if dry_run:
        return {
            "status": "success",
            "message": "dry-run：参数已通过校验，未启动批量更新。",
            "preflight": preflight_result,
            "settings": {
                "mode": mode,
                "max_symbols": max_symbols,
                "batch_size": batch_size,
                "lookback_days": lookback_days,
                "max_retries": max_retries,
                "skip_empty_unavailable": skip_empty_unavailable,
            },
        }
    result = update_real_data(settings=runtime_settings, progress=print_progress)
    result["preflight"] = preflight_result
    result["full_update_mode"] = mode
    result["skip_empty_unavailable"] = skip_empty_unavailable
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a bounded full-universe batch update.")
    parser.add_argument("--mode", choices=["missing_first", "stale_first", "auto"], default="missing_first")
    parser.add_argument("--max-symbols", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--lookback-days", type=int, default=250)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--skip-empty-unavailable", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--preflight", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--skip-network-preflight", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = run_full_batch_update(
        mode=args.mode,
        max_symbols=args.max_symbols,
        batch_size=args.batch_size,
        lookback_days=args.lookback_days,
        max_retries=args.max_retries,
        skip_empty_unavailable=args.skip_empty_unavailable,
        preflight=args.preflight,
        skip_network_preflight=args.skip_network_preflight,
        dry_run=args.dry_run,
    )
    print(_summary(result))
    raise SystemExit(0 if result.get("status") in {"success", "partial_success", "skipped"} else 1)


def _summary(result: dict[str, Any]) -> str:
    lines = [
        "全市场批量补数据摘要",
        f"- 状态: {result.get('status')}",
        f"- 说明: {result.get('message')}",
        f"- full 股票池数量: {result.get('full_universe_count', result.get('full_universe_symbol_count', 0))}",
        f"- 本次计划处理: {result.get('planned_count', result.get('planned_symbols', 0))}",
        f"- 成功数量: {result.get('success_symbols', 0)}",
        f"- 失败数量: {result.get('failed_symbols', 0)}",
        f"- 本次未处理数量: {result.get('deferred_symbols', 0)}",
    ]
    if result.get("preflight"):
        lines.append(f"- 预检状态: {result['preflight'].get('status')}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
