"""Unified free-provider market data update command."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.data_sources.akshare_client import AKShareClient
from core.data_sources.akshare_spot_snapshot import AKShareSpotSnapshotClient
from core.data_sources.baostock_client import BaoStockClient, BaoStockUnavailable
from core.jobs.market_data_progress import DEFAULT_PROGRESS_PATH, MarketDataProgressWriter
from core.jobs.market_data_status import DEFAULT_STATUS_PATH, read_market_status, record_provider_attempt
from core.storage.duckdb_store import DuckDBStore


PROVIDERS = ["akshare_kline", "akshare_spot_snapshot", "baostock", "manual_import", "csv", "tushare_optional", "auto"]
GOALS = ["latest", "history", "diagnosis", "manual_import"]
PROVIDER_DISPLAY_NAMES = {
    "akshare_kline": "历史行情接口",
    "akshare_spot_snapshot": "实时行情快照",
    "baostock": "历史行情兜底",
    "manual_import": "本地导入",
    "csv": "本地导入",
    "tushare_optional": "Tushare 可选项",
    "auto": "后台自动判断",
    "enhanced_backfill": "增强数据补齐",
}


def update_market_data(
    *,
    goal: str = "",
    mode: str = "daily_incremental",
    provider: str = "auto",
    start_date: str = "",
    end_date: str = "",
    symbols: list[str] | None = None,
    update_limit: int = 0,
    dry_run: bool = False,
    force_snapshot: bool = False,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    progress_path: str | Path = DEFAULT_PROGRESS_PATH,
    settings: Settings | None = None,
    akshare_client: AKShareClient | None = None,
    spot_client: AKShareSpotSnapshotClient | None = None,
    baostock_client: BaoStockClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Update market data through free fallback providers."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    resolved_goal = _resolve_goal(goal, mode)
    if resolved_goal not in GOALS:
        raise ValueError(f"Unsupported goal: {resolved_goal}")
    resolved_settings = settings or get_settings()
    current_dt = now or datetime.now()
    end = _normalize_date(end_date) or _default_end_date(resolved_settings, status_path=status_path, now=current_dt)
    start = _normalize_date(start_date) or _start_from_end(end, int(getattr(resolved_settings, "full_update_lookback_days", 250) or 250))
    resolved_symbols = _resolve_symbols(symbols, settings=resolved_settings)
    if dry_run:
        return {
            "status": "success",
            "goal": resolved_goal,
            "mode": mode,
            "provider": provider,
            "planned_symbols": len(resolved_symbols),
            "start_date": start,
            "end_date": end,
            "message": "dry-run：未联网、未写 DuckDB。",
        }
    if resolved_goal == "diagnosis":
        return _diagnosis_result(provider=provider, mode=mode, goal=resolved_goal)
    progress = MarketDataProgressWriter(progress_path)
    progress.start(goal=resolved_goal, provider=provider, total_symbol_count=len(resolved_symbols))
    store = DuckDBStore(resolved_settings.duckdb_path)
    store.initialize()
    attempts: list[dict[str, Any]] = []
    provider_order = _provider_order(provider, resolved_settings, resolved_goal)
    try:
        for index, candidate in enumerate(provider_order):
            result = _run_provider(
                candidate,
                goal=resolved_goal,
                mode=mode,
                start_date=start,
                end_date=end,
                symbols=resolved_symbols,
                store=store,
                force_snapshot=force_snapshot,
                status_path=status_path,
                db_path=store.db_path,
                settings=resolved_settings,
                akshare_client=akshare_client,
                spot_client=spot_client,
                baostock_client=baostock_client,
                now=current_dt,
                progress=progress,
                update_limit=update_limit,
                )
            attempts.append(result)
            if provider != "auto":
                enhanced = _run_enhanced_backfill(
                    goal=resolved_goal,
                    mode=mode,
                    end_date=end,
                    symbols=resolved_symbols,
                    store=store,
                    update_limit=update_limit,
                    status_path=status_path,
                    db_path=store.db_path,
                    baostock_client=baostock_client,
                    progress=progress,
                )
                if enhanced:
                    attempts.append(enhanced)
                final = _finalize_result(
                    status=result.get("status", "failed"),
                    goal=resolved_goal,
                    mode=mode,
                    provider=provider,
                    attempts=attempts,
                    end_date=end,
                    status_path=status_path,
                    db_path=store.db_path,
                    message=result.get("message") or result.get("error_message") or "",
                )
                progress.finish(status=str(final.get("status") or "failed"), suggested_action=str(final.get("suggested_action") or ""))
                return final
            if result.get("status") in {"success", "partial_success"} and int(result.get("written_row_count", 0) or 0) > 0:
                enhanced = _run_enhanced_backfill(
                    goal=resolved_goal,
                    mode=mode,
                    end_date=end,
                    symbols=resolved_symbols,
                    store=store,
                    update_limit=update_limit,
                    status_path=status_path,
                    db_path=store.db_path,
                    baostock_client=baostock_client,
                    progress=progress,
                )
                if enhanced:
                    attempts.append(enhanced)
                attempts.extend(_unexecuted_attempts(provider_order[index + 1 :], goal=resolved_goal))
                if not any(item.get("provider") == "manual_import" for item in attempts):
                    attempts.append(_manual_import_result(goal=resolved_goal, mode=mode))
                final = _finalize_result(
                    status="partial" if result.get("partial_update") else "success",
                    goal=resolved_goal,
                    mode=mode,
                    provider=provider,
                    attempts=attempts,
                    end_date=end,
                    status_path=status_path,
                    db_path=store.db_path,
                    message=f"系统已自动尝试可用免费数据源，本次使用：{result.get('display_name') or _display_name(str(result.get('provider')))}。",
                )
                progress.finish(status=str(final.get("status") or "partial"), suggested_action=str(final.get("suggested_action") or ""))
                return final
        enhanced = _run_enhanced_backfill(
            goal=resolved_goal,
            mode=mode,
            end_date=end,
            symbols=resolved_symbols,
            store=store,
            update_limit=update_limit,
            status_path=status_path,
            db_path=store.db_path,
            baostock_client=baostock_client,
            progress=progress,
        )
        if enhanced:
            attempts.append(enhanced)
            if int(enhanced.get("written_row_count", 0) or 0) > 0:
                final = _finalize_result(
                    status="partial",
                    goal=resolved_goal,
                    mode=mode,
                    provider=provider,
                    attempts=attempts,
                    end_date=end,
                    status_path=status_path,
                    db_path=store.db_path,
                    message="价格行情未新增，但已补齐部分增强数据。",
                )
                progress.finish(status=str(final.get("status") or "partial"), suggested_action=str(final.get("suggested_action") or ""))
                return final
        manual = _manual_import_attempt(goal=resolved_goal, mode=mode, status_path=status_path, db_path=store.db_path, end_date=end)
        attempts.append(manual)
        final = _finalize_result(
            status="failed",
            goal=resolved_goal,
            mode=mode,
            provider=provider,
            attempts=attempts,
            end_date=end,
            status_path=status_path,
            db_path=store.db_path,
            message="自动数据源暂不可用，请使用【导入本地行情文件】或稍后重试。",
        )
        progress.finish(status="failed", suggested_action=str(final.get("suggested_action") or ""))
        return final
    except KeyboardInterrupt:
        progress.finish(status="interrupted", suggested_action="本次更新被中断，可重新运行。")
        raise
    except Exception:
        progress.finish(status="failed")
        raise


def _run_provider(
    provider: str,
    *,
    goal: str,
    mode: str,
    start_date: str,
    end_date: str,
    symbols: list[str],
    store: DuckDBStore,
    force_snapshot: bool,
    status_path: str | Path,
    settings: Settings,
    db_path: str | Path | None = None,
    akshare_client: AKShareClient | None,
    spot_client: AKShareSpotSnapshotClient | None,
    baostock_client: BaoStockClient | None,
    now: datetime,
    progress: MarketDataProgressWriter,
    update_limit: int = 0,
) -> dict[str, Any]:
    try:
        plan = _provider_symbol_plan(provider, goal=goal, end_date=end_date, symbols=symbols, store=store, update_limit=update_limit)
        provider_symbols = list(plan.get("symbols") or [])
        progress.start_provider(
            provider,
            _display_name(provider),
            total_symbol_count=len(provider_symbols),
            pending_symbol_count=int(plan.get("pending_symbol_count", len(provider_symbols)) or 0),
            already_latest_symbol_count=int(plan.get("already_latest_symbol_count", 0) or 0),
        )
        if provider == "baostock" and goal == "latest" and not provider_symbols:
            message = "最新交易日 daily_price 已无待更新股票。"
            _record(provider, goal, mode, "skipped", 0, [], True, end_date, status_path, db_path=db_path, success=True, error_message=message, extra=plan)
            progress.finish_provider(provider, _display_name(provider), status="skipped", processed_symbol_count=0, total_symbol_count=0)
            return _provider_result(provider, goal, "skipped", 0, [], True, message=message, extra=plan)
        if provider == "akshare_kline":
            client = akshare_client or AKShareClient(
                adjust=settings.akshare_adjust,
                request_timeout_seconds=settings.data_source_request_timeout_seconds,
                symbol_timeout_seconds=settings.symbol_update_timeout_seconds,
                enable_basic_enrichment=False,
                enable_valuation_enrichment=False,
            )
            fetch_symbols = provider_symbols
            if goal == "latest" and len(provider_symbols) > 2:
                probe_symbols = provider_symbols[:2]
                try:
                    with _suppress_akshare_traceback_logs():
                        probe = client.get_daily_price(start_date, end_date, probe_symbols)
                except Exception as exc:
                    error_type, message, technical = _sanitize_kline_failure(exc)
                    _record(
                        provider,
                        goal,
                        mode,
                        "failed",
                        0,
                        [],
                        False,
                        end_date,
                        status_path,
                        db_path=db_path,
                        error_type=error_type,
                        error_message=message,
                        technical_details=technical,
                    )
                    progress.finish_provider(provider, _display_name(provider), status="failed", processed_symbol_count=len(probe_symbols), total_symbol_count=len(provider_symbols))
                    return _provider_result(
                        provider,
                        goal,
                        "failed",
                        0,
                        [],
                        False,
                        error_type=error_type,
                        error_message=message,
                        technical_details=technical,
                    )
                if not isinstance(probe, pd.DataFrame) or probe.empty:
                    message = "东方财富 K 线接口不可用，已尝试下一个免费数据源。"
                    _record(
                        provider,
                        goal,
                        mode,
                        "failed",
                        0,
                        [],
                        False,
                        end_date,
                        status_path,
                        db_path=db_path,
                        error_type="network_or_provider_unavailable",
                        error_message=message,
                        technical_details={"reason": "empty_probe_result", "probe_symbol_count": len(probe_symbols)},
                    )
                    progress.finish_provider(provider, _display_name(provider), status="failed", processed_symbol_count=len(probe_symbols), total_symbol_count=len(provider_symbols))
                    return _provider_result(
                        provider,
                        goal,
                        "failed",
                        0,
                        [],
                        False,
                        error_type="network_or_provider_unavailable",
                        error_message=message,
                        technical_details={"reason": "empty_probe_result", "probe_symbol_count": len(probe_symbols)},
                    )
                fetch_symbols = symbols
            try:
                with _suppress_akshare_traceback_logs():
                    price = client.get_daily_price(start_date, end_date, fetch_symbols)
            except Exception as exc:
                error_type, message, technical = _sanitize_kline_failure(exc)
                _record(
                    provider,
                    goal,
                    mode,
                    "failed",
                    0,
                    [],
                    False,
                    end_date,
                    status_path,
                    db_path=db_path,
                    error_type=error_type,
                    error_message=message,
                        technical_details=technical,
                    )
                progress.finish_provider(provider, _display_name(provider), status="failed", processed_symbol_count=0, total_symbol_count=len(provider_symbols))
                return _provider_result(
                    provider,
                    goal,
                    "failed",
                    0,
                    [],
                    False,
                    error_type=error_type,
                    error_message=message,
                    technical_details=technical,
                )
            written = _write_price_and_partial_basic(store, price, write_basic=False)
            status = "success" if written else "failed"
            _record(provider, goal, mode, status, written, ["daily_price"], False, end_date, status_path, db_path=db_path, error_message="" if written else "历史行情接口未写入有效数据。")
            progress.finish_provider(provider, _display_name(provider), status=status, written_rows=written, processed_symbol_count=len(provider_symbols), total_symbol_count=len(provider_symbols))
            return _provider_result(provider, goal, status, written, ["daily_price"], False, error_message="" if written else "历史行情接口未写入有效数据。")
        if provider == "akshare_spot_snapshot":
            client = spot_client or AKShareSpotSnapshotClient()
            completed_before_today = _target_is_completed_before_today(end_date, now)
            snapshot_force = force_snapshot or completed_before_today
            payload = client.fetch_latest(trade_date=end_date, symbols=provider_symbols, force=snapshot_force, now=now)
            if payload.get("status") == "skipped":
                message = str(payload.get("message") or "skipped")
                _record(provider, goal, mode, "skipped", 0, [], True, end_date, status_path, db_path=db_path, success=False, error_message=message)
                progress.finish_provider(provider, _display_name(provider), status="skipped", processed_symbol_count=0, total_symbol_count=len(provider_symbols))
                return _provider_result(provider, goal, "skipped", 0, [], True, error_message=message, message=message)
            price = payload.get("daily_price", pd.DataFrame())
            basic = payload.get("daily_basic", pd.DataFrame())
            written_price = _write_price_and_partial_basic(store, price, write_basic=False)
            written_basic = store.upsert_dataframe("daily_basic", basic) if isinstance(basic, pd.DataFrame) and not basic.empty else 0
            written_adj = forward_fill_adj_factor(store, end_date=end_date, symbols=provider_symbols)
            written = written_price + written_basic + written_adj
            status = "success" if written_price else "failed"
            _record(provider, goal, mode, status, written, ["daily_price", "daily_basic", "adj_factor"], True, end_date, status_path, db_path=db_path, error_message="" if written_price else "实时行情快照未写入有效日行情。")
            message = "当前为非交易日，允许使用快照补最近一个已完成交易日。" if completed_before_today and not force_snapshot else ""
            progress.finish_provider(provider, _display_name(provider), status=status, written_rows=written, processed_symbol_count=len(provider_symbols), total_symbol_count=len(provider_symbols))
            return _provider_result(provider, goal, status, written, ["daily_price", "daily_basic", "adj_factor"], True, error_message="" if written_price else "实时行情快照未写入有效日行情。", message=message, extra={"written_price_rows": written_price})
        if provider == "baostock":
            client = baostock_client or BaoStockClient()
            payload = client.get_daily_price(
                start_date=start_date,
                end_date=end_date,
                symbols=provider_symbols,
                limit=0,
                progress_callback=lambda **payload: progress.update_symbol(provider, _display_name(provider), **payload),
            )
            price = payload.get("daily_price", pd.DataFrame())
            basic = payload.get("daily_basic", pd.DataFrame())
            written = _write_price_and_partial_basic(store, price, write_basic=False)
            written_basic = store.upsert_dataframe("daily_basic", basic) if isinstance(basic, pd.DataFrame) and not basic.empty else 0
            adj_factor = _identity_adj_factor_for_adjusted_price(price)
            written_adj = store.upsert_dataframe("adj_factor", adj_factor) if not adj_factor.empty else 0
            total_written = written + written_basic + written_adj
            status = "success" if written else "failed"
            failure_summary = payload.get("failure_summary", {}) if isinstance(payload, dict) else {}
            failure_examples = payload.get("failure_examples", {}) if isinstance(payload, dict) else {}
            extra = {**plan, "failure_summary": failure_summary, "failure_examples": failure_examples, "next_retry_symbol_count": sum(int(v or 0) for v in failure_summary.values())}
            extra.update(
                {
                    "adj_factor_source": "baostock_adjusted_price_identity",
                    "adj_factor_semantics": "daily_price_is_qfq; adj_factor_is_identity_to_avoid_double_adjustment",
                    "adjusted_price_source": "baostock_adjustflag_2_qfq",
                    "price_adjustment_status": "qfq_price_with_identity_adj_factor",
                }
            )
            _record(provider, goal, mode, status, total_written, ["daily_price", "daily_basic", "adj_factor"], True, end_date, status_path, db_path=db_path, error_message="" if written else "历史行情兜底未写入有效数据。", extra=extra)
            progress.finish_provider(
                provider,
                _display_name(provider),
                status=status,
                written_rows=total_written,
                processed_symbol_count=len(provider_symbols),
                total_symbol_count=len(provider_symbols),
                failure_summary=failure_summary,
                failure_examples=failure_examples,
            )
            return _provider_result(provider, goal, status, total_written, ["daily_price", "daily_basic", "adj_factor"], True, error_message="" if written else "历史行情兜底未写入有效数据。", extra=extra)
        if provider == "tushare_optional":
            if not settings.tushare_token:
                message = "Tushare token 未配置；Tushare 仅作为可选项，已跳过。"
                _record(provider, goal, mode, "skipped", 0, [], True, end_date, status_path, db_path=db_path, success=False, error_message=message)
                progress.finish_provider(provider, _display_name(provider), status="skipped", processed_symbol_count=0, total_symbol_count=len(provider_symbols))
                return _provider_result(provider, goal, "skipped", 0, [], True, error_message=message, message=message)
        if provider in {"csv", "manual_import"}:
            message = "CSV / Excel 需要用户通过 import_market_data 手动导入。"
            _record("manual_import", goal, mode, "available", 0, [], True, end_date, status_path, db_path=db_path, success=False, error_message=message)
            progress.finish_provider("manual_import", _display_name("manual_import"), status="available", processed_symbol_count=0, total_symbol_count=len(provider_symbols))
            return _provider_result("manual_import", goal, "available", 0, [], True, error_message=message, message=message)
    except BaoStockUnavailable as exc:
        message = "历史行情兜底当前不可用，已记录并继续。"
        technical = {"raw_exception_type": type(exc).__name__, "raw_exception": str(exc)}
        _record(provider, goal, mode, "unavailable", 0, [], True, end_date, status_path, db_path=db_path, success=False, error_type="provider_unavailable", error_message=message, technical_details=technical)
        progress.finish_provider(provider, _display_name(provider), status="unavailable", processed_symbol_count=0, total_symbol_count=0)
        return _provider_result(provider, goal, "unavailable", 0, [], True, error_type="provider_unavailable", error_message=message, technical_details=technical)
    except Exception as exc:
        if provider == "akshare_spot_snapshot" and _target_is_completed_before_today(end_date, now):
            message = "当前为非交易日，已允许使用快照补最近一个已完成交易日；但接口请求失败。"
        else:
            message = "数据源请求失败，已记录并继续尝试其他免费数据源。"
        technical = {"raw_exception_type": type(exc).__name__, "raw_exception": str(exc)}
        _record(provider, goal, mode, "failed", 0, [], True, end_date, status_path, db_path=db_path, success=False, error_type=type(exc).__name__, error_message=message, technical_details=technical)
        progress.finish_provider(provider, _display_name(provider), status="failed", processed_symbol_count=0, total_symbol_count=0)
        return _provider_result(provider, goal, "failed", 0, [], True, error_type=type(exc).__name__, error_message=message, technical_details=technical)
    return _provider_result(provider, goal, "skipped", 0, [], True, error_message="该数据源未执行。")


def _run_enhanced_backfill(
    *,
    goal: str,
    mode: str,
    end_date: str,
    symbols: list[str],
    store: DuckDBStore,
    update_limit: int,
    status_path: str | Path,
    db_path: str | Path,
    baostock_client: BaoStockClient | None,
    progress: MarketDataProgressWriter,
) -> dict[str, Any] | None:
    if goal != "latest":
        return None
    plan = _enhanced_symbol_plan(end_date=end_date, symbols=symbols, store=store, update_limit=update_limit)
    planned_symbols = list(plan.get("symbols") or [])
    if not planned_symbols:
        return None
    progress.start_provider(
        "enhanced_backfill",
        _display_name("enhanced_backfill"),
        total_symbol_count=len(planned_symbols),
        pending_symbol_count=int(plan.get("enhanced_pending_symbol_count", len(planned_symbols)) or 0),
    )
    failure_summary: dict[str, int] = {}
    failure_examples: dict[str, list[str]] = {}
    daily_basic_written = 0
    try:
        client = baostock_client or BaoStockClient()
        payload = client.get_daily_price(
            start_date=end_date,
            end_date=end_date,
            symbols=planned_symbols,
            limit=0,
            progress_callback=lambda **payload: progress.update_symbol("enhanced_backfill", _display_name("enhanced_backfill"), **payload),
        )
        basic = payload.get("daily_basic", pd.DataFrame()) if isinstance(payload, dict) else pd.DataFrame()
        if isinstance(basic, pd.DataFrame) and not basic.empty:
            daily_basic_written = store.upsert_dataframe("daily_basic", basic)
        failure_summary = payload.get("failure_summary", {}) if isinstance(payload, dict) else {}
        failure_examples = payload.get("failure_examples", {}) if isinstance(payload, dict) else {}
    except BaoStockUnavailable as exc:
        failure_summary = {"provider_error": len(planned_symbols)}
        failure_examples = {"provider_error": planned_symbols[:20]}
        technical = {"raw_exception_type": type(exc).__name__, "raw_exception": str(exc)}
        _record(
            "enhanced_backfill",
            goal,
            mode,
            "unavailable",
            0,
            [],
            True,
            end_date,
            status_path,
            db_path=db_path,
            success=False,
            error_type="provider_unavailable",
            error_message="增强数据补齐源不可用。",
            technical_details=technical,
            extra={**plan, "failure_summary": failure_summary, "failure_examples": failure_examples},
        )
        progress.finish_provider("enhanced_backfill", _display_name("enhanced_backfill"), status="unavailable", processed_symbol_count=0, total_symbol_count=len(planned_symbols), failure_summary=failure_summary, failure_examples=failure_examples)
        return _provider_result("enhanced_backfill", goal, "unavailable", 0, [], True, error_type="provider_unavailable", error_message="增强数据补齐源不可用。", technical_details=technical, extra={**plan, "failure_summary": failure_summary, "failure_examples": failure_examples})
    adj_factor = _identity_adj_factor_from_existing_price(store, end_date=end_date, symbols=planned_symbols)
    adj_factor_written = store.upsert_dataframe("adj_factor", adj_factor) if not adj_factor.empty else 0
    total_written = daily_basic_written + adj_factor_written
    status = "success" if total_written else "failed"
    extra = {
        **plan,
        "enhanced_processed_symbol_count": len(planned_symbols),
        "daily_basic_written_row_count": int(daily_basic_written or 0),
        "adj_factor_written_row_count": int(adj_factor_written or 0),
        "adj_factor_source": "baostock_adjusted_price_identity" if adj_factor_written else "",
        "adj_factor_semantics": "daily_price_is_qfq; adj_factor_is_identity_to_avoid_double_adjustment" if adj_factor_written else "",
        "adj_factor_user_note": "当前使用前复权行情价，adj_factor 为恒等兼容值，用于避免重复复权；这不是真实复权因子。" if adj_factor_written else "",
        "failure_summary": failure_summary,
        "failure_examples": failure_examples,
    }
    _record(
        "enhanced_backfill",
        goal,
        mode,
        status,
        total_written,
        ["daily_basic", "adj_factor"],
        True,
        end_date,
        status_path,
        db_path=db_path,
        error_message="" if total_written else "增强数据补齐未写入有效数据。",
        extra=extra,
    )
    progress.finish_provider(
        "enhanced_backfill",
        _display_name("enhanced_backfill"),
        status=status,
        written_rows=total_written,
        processed_symbol_count=len(planned_symbols),
        total_symbol_count=len(planned_symbols),
        failure_summary=failure_summary,
        failure_examples=failure_examples,
    )
    return _provider_result("enhanced_backfill", goal, status, total_written, ["daily_basic", "adj_factor"], True, error_message="" if total_written else "增强数据补齐未写入有效数据。", extra=extra)


def forward_fill_adj_factor(store: DuckDBStore, *, end_date: str, symbols: list[str]) -> int:
    """Forward-fill latest known adj_factor to end_date with explicit marker."""
    if not symbols:
        return 0
    symbol_frame = pd.DataFrame({"ts_code": symbols})
    with store.connect(read_only=True) as connection:
        connection.register("symbol_filter", symbol_frame)
        existing = connection.execute(
            """
            SELECT ts_code, adj_factor
            FROM (
              SELECT ts_code, adj_factor, trade_date,
                     ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
              FROM adj_factor
              WHERE ts_code IN (SELECT ts_code FROM symbol_filter)
                AND replace(CAST(trade_date AS VARCHAR), '-', '') <= ?
            )
            WHERE rn = 1
            """,
            [end_date],
        ).fetchdf()
        connection.unregister("symbol_filter")
    if existing.empty:
        return 0
    existing["trade_date"] = end_date
    existing["derived_adj_factor"] = True
    existing["source_provider"] = "forward_fill"
    return store.upsert_dataframe("adj_factor", existing[["ts_code", "trade_date", "adj_factor", "derived_adj_factor", "source_provider"]])


def _write_price_and_partial_basic(store: DuckDBStore, price: pd.DataFrame, *, write_basic: bool) -> int:
    if not isinstance(price, pd.DataFrame) or price.empty:
        return 0
    columns = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]
    for column in columns:
        if column not in price.columns:
            price[column] = pd.NA
    return store.upsert_dataframe("daily_price", price[columns])


def _identity_adj_factor_for_adjusted_price(price: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(price, pd.DataFrame) or price.empty or not {"ts_code", "trade_date"}.issubset(price.columns):
        return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor", "derived_adj_factor", "source_provider"])
    result = price[["ts_code", "trade_date"]].dropna().drop_duplicates().copy()
    result["adj_factor"] = 1.0
    result["derived_adj_factor"] = True
    result["source_provider"] = "baostock_adjusted_price_identity"
    return result[["ts_code", "trade_date", "adj_factor", "derived_adj_factor", "source_provider"]]


def _identity_adj_factor_from_existing_price(store: DuckDBStore, *, end_date: str, symbols: list[str]) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor", "derived_adj_factor", "source_provider"])
    symbol_frame = pd.DataFrame({"ts_code": [_to_ts_code(symbol) for symbol in symbols]})
    try:
        with store.connect(read_only=True) as connection:
            connection.register("adj_symbol_filter", symbol_frame)
            frame = connection.execute(
                """
                SELECT DISTINCT p.ts_code, ? AS trade_date
                FROM daily_price AS p
                JOIN adj_symbol_filter AS s ON s.ts_code = p.ts_code
                WHERE replace(CAST(p.trade_date AS VARCHAR), '-', '') = ?
                """,
                [end_date, end_date],
            ).fetchdf()
            connection.unregister("adj_symbol_filter")
    except Exception:
        return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor", "derived_adj_factor", "source_provider"])
    if frame.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor", "derived_adj_factor", "source_provider"])
    frame["adj_factor"] = 1.0
    frame["derived_adj_factor"] = True
    frame["source_provider"] = "baostock_adjusted_price_identity"
    return frame[["ts_code", "trade_date", "adj_factor", "derived_adj_factor", "source_provider"]]


def _record(
    provider: str,
    goal: str,
    mode: str,
    attempt_status: str,
    written: int,
    tables: list[str],
    partial: bool,
    trade_date: str,
    status_path: str | Path,
    *,
    db_path: str | Path | None = None,
    success: bool | None = None,
    error_type: str = "",
    error_message: str = "",
    technical_details: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    record_provider_attempt(
        provider=provider,
        display_name=_display_name(provider),
        goal=goal,
        mode=mode,
        attempt_status=attempt_status,
        success=written > 0 if success is None else success,
        written_table_names=tables,
        written_row_count=written,
        partial_update=partial,
        error_type=error_type,
        error_message=error_message,
        technical_details=technical_details,
        trade_date=trade_date,
        status_path=status_path,
        db_path=db_path,
        extra=extra,
    )


def _provider_result(
    provider: str,
    goal: str,
    status: str,
    written: int,
    tables: list[str],
    partial: bool,
    *,
    error_type: str = "",
    error_message: str = "",
    message: str = "",
    technical_details: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    result = {
        "provider": provider,
        "display_name": _display_name(provider),
        "goal": goal,
        "status": status,
        "started_at": now,
        "finished_at": now,
        "success": status == "success",
        "written_table_names": tables,
        "written_row_count": int(written or 0),
        "partial_update": bool(partial),
        "error_type": error_type,
        "error_message": error_message,
        "message": message or error_message,
        "technical_details": technical_details or {},
    }
    if extra:
        result.update(extra)
    return result


def _manual_import_attempt(*, goal: str, mode: str, status_path: str | Path, db_path: str | Path, end_date: str) -> dict[str, Any]:
    result = _manual_import_result(goal=goal, mode=mode)
    message = str(result.get("message") or "")
    _record(
        "manual_import",
        goal,
        mode,
        "available",
        0,
        [],
        True,
        end_date,
        status_path,
        db_path=db_path,
        success=False,
        error_message=message,
    )
    return result


def _manual_import_result(*, goal: str, mode: str) -> dict[str, Any]:
    message = "所有自动数据源均未写入有效数据，可使用本地 CSV / Excel 导入行情文件。"
    result = _provider_result("manual_import", goal, "available", 0, [], True, error_message=message, message=message)
    result["mode"] = mode
    return result


def _unexecuted_attempts(providers: list[str], *, goal: str) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for provider in providers:
        attempts.append(
            _provider_result(
                provider,
                goal,
                "skipped",
                0,
                [],
                True,
                message="已有可用数据源写入，本次未继续执行该数据源。",
            )
        )
    return attempts


def _finalize_result(
    *,
    status: str,
    goal: str,
    mode: str,
    provider: str,
    attempts: list[dict[str, Any]],
    end_date: str,
    status_path: str | Path,
    db_path: str | Path,
    message: str,
) -> dict[str, Any]:
    finished_at = datetime.now().isoformat(timespec="seconds")
    latest_success = next((item for item in attempts if item.get("status") == "success" and int(item.get("written_row_count", 0) or 0) > 0), None)
    written_tables = sorted({table for item in attempts for table in item.get("written_table_names", [])})
    written_rows = sum(int(item.get("written_row_count", 0) or 0) for item in attempts)
    partial = any(bool(item.get("partial_update")) for item in attempts if item.get("status") == "success") or status == "partial"
    quality = read_market_status(status_path)
    if quality.get("data_quality_snapshot_source") != "readonly_duckdb_sql":
        quality = {
            **quality,
            "data_quality_snapshot_source": quality.get("data_quality_snapshot_source") or "unavailable",
            "data_quality_status": quality.get("data_quality_status") or "unknown",
            "formal_result_usable": False,
            "formal_result_warning_reason": quality.get("formal_result_warning_reason") or "数据质量快照未能刷新，当前结果不可作为正式全市场研究结果。",
        }
    core_price_usable = bool(float(quality.get("latest_daily_price_coverage_rate", 0.0) or 0.0) >= 0.8)
    enhanced_complete = bool(
        float(quality.get("latest_daily_basic_coverage_rate", 0.0) or 0.0) >= 0.8
        and float(quality.get("latest_adj_factor_coverage_rate", 0.0) or 0.0) >= 0.8
    )
    result = {
        **quality,
        "status": status,
        "summary": message,
        "goal": goal,
        "mode": mode,
        "provider": provider,
        "started_at": attempts[0].get("started_at", "") if attempts else finished_at,
        "finished_at": finished_at,
        "latest_success_provider": latest_success.get("provider", "") if latest_success else "",
        "latest_success_trade_date": end_date if latest_success else "",
        "latest_update_completeness": "partial" if partial else "complete" if latest_success else "failed",
        "written_table_names": written_tables,
        "written_row_count": written_rows,
        "provider_attempts": attempts,
        "message": message,
        "user_summary": message,
        "suggested_action": _suggested_action(status, quality, latest_success),
        "core_price_data_usable": core_price_usable,
        "core_price_data_status": "可用" if core_price_usable else "不足",
        "enhanced_data_status": "完整" if enhanced_complete else "不完整",
        "enhanced_data_missing_reason": "" if enhanced_complete else "daily_basic 或 adj_factor 最新交易日覆盖不足。",
    }
    if partial:
        result["formal_result_usable"] = False
        result["formal_result_warning_reason"] = result.get("formal_result_warning_reason") or "本次仅完成部分更新，当前结果不可作为正式全市场研究结果。"
    path = Path(status_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def _suggested_action(status: str, quality: dict[str, Any], latest_success: dict[str, Any] | None) -> str:
    if status == "failed":
        return "自动数据源暂不可用，请使用【导入本地行情文件】或稍后重试。"
    if not latest_success:
        return "暂无成功写入记录，请运行数据源诊断或导入本地行情文件。"
    if not quality.get("formal_result_usable"):
        return "本次更新后数据质量仍不足，请查看覆盖率并按需补历史行情缺口。"
    return "数据质量满足正式研究口径，可继续本地重算和每日研究。"


def _diagnosis_result(*, provider: str, mode: str, goal: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "goal": goal,
        "mode": mode,
        "provider": provider,
        "provider_attempts": [],
        "written_row_count": 0,
        "user_summary": "诊断为只读操作，不写 DuckDB，不记录成功 provider。",
        "suggested_action": "请运行数据源诊断命令查看网络和接口状态。",
    }


def _provider_order(provider: str, settings: Settings, goal: str) -> list[str]:
    if provider != "auto":
        return [provider]
    if goal == "history":
        order = ["baostock", "akshare_kline"]
    else:
        order = ["akshare_kline", "akshare_spot_snapshot", "baostock"]
    if settings.tushare_token:
        order.append("tushare_optional")
    return order


def _provider_symbol_plan(
    provider: str,
    *,
    goal: str,
    end_date: str,
    symbols: list[str],
    store: DuckDBStore,
    update_limit: int,
) -> dict[str, Any]:
    if provider == "baostock" and goal == "latest":
        return _latest_baostock_symbol_plan(end_date=end_date, symbols=symbols, store=store, update_limit=update_limit)
    planned = list(symbols[:update_limit] if update_limit else symbols)
    return {
        "symbols": planned,
        "pending_symbol_count": len(planned),
        "already_latest_symbol_count": max(len(symbols) - len(planned), 0) if update_limit else 0,
        "history_missing_symbol_count": 0,
        "history_incomplete_symbol_count": 0,
    }


def _latest_baostock_symbol_plan(*, end_date: str, symbols: list[str], store: DuckDBStore, update_limit: int) -> dict[str, Any]:
    universe = [_to_ts_code(symbol) for symbol in symbols]
    if not universe:
        return {
            "symbols": [],
            "pending_symbol_count": 0,
            "already_latest_symbol_count": 0,
            "history_missing_symbol_count": 0,
            "history_incomplete_symbol_count": 0,
        }
    symbol_frame = pd.DataFrame({"ts_code": universe, "position": range(len(universe))})
    try:
        with store.connect(read_only=True) as connection:
            connection.register("symbol_plan", symbol_frame)
            latest = connection.execute(
                """
                SELECT DISTINCT ts_code
                FROM daily_price
                WHERE replace(CAST(trade_date AS VARCHAR), '-', '') = ?
                  AND ts_code IN (SELECT ts_code FROM symbol_plan)
                """,
                [end_date],
            ).fetchdf()
            history = connection.execute(
                """
                SELECT s.ts_code, s.position, COUNT(p.trade_date) AS row_count
                FROM symbol_plan AS s
                LEFT JOIN daily_price AS p ON p.ts_code = s.ts_code
                GROUP BY s.ts_code, s.position
                ORDER BY s.position
                """
            ).fetchdf()
            connection.unregister("symbol_plan")
    except Exception:
        planned = universe[:update_limit] if update_limit else universe
        return {
            "symbols": planned,
            "pending_symbol_count": len(universe),
            "already_latest_symbol_count": 0,
            "history_missing_symbol_count": 0,
            "history_incomplete_symbol_count": 0,
        }
    latest_symbols = set(latest["ts_code"].astype(str).tolist()) if not latest.empty else set()
    missing_latest: list[str] = []
    history_missing: list[str] = []
    history_incomplete: list[str] = []
    for row in history.to_dict("records"):
        symbol = str(row.get("ts_code") or "")
        row_count = int(row.get("row_count") or 0)
        if symbol not in latest_symbols:
            missing_latest.append(symbol)
        if row_count <= 0:
            history_missing.append(symbol)
        elif row_count < 252:
            history_incomplete.append(symbol)
    ordered: list[str] = []
    for bucket in [missing_latest, history_missing, history_incomplete]:
        for symbol in bucket:
            if symbol not in ordered and symbol not in latest_symbols:
                ordered.append(symbol)
    planned = ordered[:update_limit] if update_limit else ordered
    return {
        "symbols": planned,
        "pending_symbol_count": len(ordered),
        "already_latest_symbol_count": len(latest_symbols),
        "history_missing_symbol_count": len(history_missing),
        "history_incomplete_symbol_count": len(history_incomplete),
    }


def _enhanced_symbol_plan(*, end_date: str, symbols: list[str], store: DuckDBStore, update_limit: int) -> dict[str, Any]:
    universe = [_to_ts_code(symbol) for symbol in symbols]
    if not universe:
        return {
            "symbols": [],
            "enhanced_pending_symbol_count": 0,
            "missing_daily_basic_symbol_count": 0,
            "missing_adj_factor_symbol_count": 0,
        }
    symbol_frame = pd.DataFrame({"ts_code": universe, "position": range(len(universe))})
    try:
        with store.connect(read_only=True) as connection:
            connection.register("enhanced_symbol_plan", symbol_frame)
            frame = connection.execute(
                """
                WITH price AS (
                  SELECT DISTINCT ts_code
                  FROM daily_price
                  WHERE replace(CAST(trade_date AS VARCHAR), '-', '') = ?
                    AND ts_code IN (SELECT ts_code FROM enhanced_symbol_plan)
                ),
                basic AS (
                  SELECT DISTINCT ts_code
                  FROM daily_basic
                  WHERE replace(CAST(trade_date AS VARCHAR), '-', '') = ?
                ),
                adj AS (
                  SELECT DISTINCT ts_code
                  FROM adj_factor
                  WHERE replace(CAST(trade_date AS VARCHAR), '-', '') = ?
                )
                SELECT p.ts_code,
                       s.position,
                       CASE WHEN b.ts_code IS NULL THEN 1 ELSE 0 END AS missing_basic,
                       CASE WHEN a.ts_code IS NULL THEN 1 ELSE 0 END AS missing_adj
                FROM price AS p
                JOIN enhanced_symbol_plan AS s ON s.ts_code = p.ts_code
                LEFT JOIN basic AS b ON b.ts_code = p.ts_code
                LEFT JOIN adj AS a ON a.ts_code = p.ts_code
                WHERE b.ts_code IS NULL OR a.ts_code IS NULL
                ORDER BY missing_basic DESC, missing_adj DESC, s.position
                """,
                [end_date, end_date, end_date],
            ).fetchdf()
            connection.unregister("enhanced_symbol_plan")
    except Exception:
        return {
            "symbols": [],
            "enhanced_pending_symbol_count": 0,
            "missing_daily_basic_symbol_count": 0,
            "missing_adj_factor_symbol_count": 0,
        }
    if frame.empty:
        return {
            "symbols": [],
            "enhanced_pending_symbol_count": 0,
            "missing_daily_basic_symbol_count": 0,
            "missing_adj_factor_symbol_count": 0,
        }
    symbols_to_process = frame["ts_code"].astype(str).tolist()
    planned = symbols_to_process[:update_limit] if update_limit else symbols_to_process
    return {
        "symbols": planned,
        "enhanced_pending_symbol_count": len(symbols_to_process),
        "missing_daily_basic_symbol_count": int(pd.to_numeric(frame["missing_basic"], errors="coerce").fillna(0).sum()),
        "missing_adj_factor_symbol_count": int(pd.to_numeric(frame["missing_adj"], errors="coerce").fillna(0).sum()),
    }


@contextmanager
def _suppress_akshare_traceback_logs():
    """Keep provider tracebacks out of normal CLI output; details go to JSON."""
    logger = logging.getLogger("core.data_sources.akshare_client")
    previous_disabled = logger.disabled
    previous_level = logger.level
    logger.disabled = True
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.disabled = previous_disabled
        logger.setLevel(previous_level)


def _sanitize_kline_failure(exc: Exception) -> tuple[str, str, dict[str, Any]]:
    raw = str(exc)
    raw_lower = raw.lower()
    exception_name = type(exc).__name__
    systemic_markers = [
        "proxyerror",
        "remotedisconnected",
        "empty reply",
        "returncode=52",
        "curl returncode 52",
        "push2his.eastmoney.com",
        "stock_zh_a_hist",
        "akshare call failed",
    ]
    technical = {"raw_exception_type": exception_name, "raw_exception": raw}
    if any(marker in raw_lower for marker in systemic_markers) or exception_name in {"ProxyError", "RemoteDisconnected"}:
        return "network_or_provider_unavailable", "东方财富 K 线接口不可用，已尝试下一个免费数据源。", technical
    return exception_name, "历史行情接口请求失败，已尝试下一个免费数据源。", technical


def _format_attempt_line(index: int, attempt: dict[str, Any]) -> str:
    status = str(attempt.get("status") or ("success" if attempt.get("success") else "failed"))
    status_label = {
        "success": "成功",
        "partial": "部分成功",
        "failed": "失败",
        "skipped": "跳过",
        "unavailable": "不可用",
        "available": "可用",
    }.get(status, status)
    message = _safe_attempt_message(attempt)
    suffix = f"，{message}" if message else ""
    return f"  {index}. {attempt.get('display_name') or attempt.get('provider')}: {status_label}{suffix}"


def _safe_attempt_message(attempt: dict[str, Any]) -> str:
    provider = str(attempt.get("provider") or "")
    status = str(attempt.get("status") or "")
    message = str(attempt.get("message") or attempt.get("error_message") or "")
    if provider == "akshare_kline" and status == "failed":
        return "东方财富 K 线接口不可用"
    if provider == "akshare_spot_snapshot" and status == "skipped":
        return "未到收盘安全写入时间"
    if provider == "baostock" and status == "unavailable":
        return "兜底源不可用"
    if provider == "manual_import":
        return "可在网络源不可用时使用"
    forbidden = ["traceback", "proxyerror", "curl", "stderr", "stdout", "push2his", "empty reply", "remotedisconnected"]
    if any(term in message.lower() for term in forbidden):
        return "技术错误已记录到高级诊断"
    return message


def _resolve_goal(goal: str, mode: str) -> str:
    clean = str(goal or "").strip().lower()
    if clean:
        return clean
    return "history" if mode == "full_backfill" else "latest"


def _display_name(provider: str) -> str:
    return PROVIDER_DISPLAY_NAMES.get(provider, provider)


def _resolve_symbols(symbols: list[str] | None, *, settings: Settings) -> list[str]:
    if symbols:
        result = [_to_ts_code(symbol) for symbol in symbols]
    else:
        store = DuckDBStore(settings.duckdb_path)
        try:
            with store.connect(read_only=True) as connection:
                rows = connection.execute("SELECT ts_code FROM stock_basic ORDER BY ts_code").fetchall()
            result = [str(row[0]) for row in rows]
        except Exception:
            result = [_to_ts_code(symbol) for symbol in settings.akshare_symbols]
    return result


def _default_end_date(settings: Settings, *, status_path: str | Path, now: datetime) -> str:
    status = read_market_status(status_path)
    for key in ["latest_completed_trade_date", "research_trade_date"]:
        value = _normalize_date(str(status.get(key) or ""))
        if value:
            return value
    return settings.real_data_end_date or now.strftime("%Y%m%d")


def _target_is_completed_before_today(target_date: str, now: datetime) -> bool:
    target = _normalize_date(target_date)
    today = now.strftime("%Y%m%d")
    return bool(target and target < today)


def _start_from_end(end_date: str, days: int) -> str:
    try:
        end = datetime.strptime(end_date, "%Y%m%d")
    except ValueError:
        return end_date
    return (end - timedelta(days=max(days, 1) * 2)).strftime("%Y%m%d")


def _normalize_date(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:8]


def _to_ts_code(symbol: str) -> str:
    text = str(symbol).strip().upper()
    if "." in text:
        code, suffix = text.split(".", 1)
        return f"{code.zfill(6)}.{suffix}"
    code = text.zfill(6)
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Update market data through free fallback providers.")
    parser.add_argument("--goal", choices=GOALS, default="")
    parser.add_argument("--mode", choices=["daily_incremental", "full_backfill"], default="daily_incremental")
    parser.add_argument("--provider", choices=PROVIDERS, default="auto")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--update-limit", type=int, default=0)
    parser.add_argument("--force-snapshot", action="store_true")
    parser.add_argument("--progress-path", default=str(DEFAULT_PROGRESS_PATH))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    result = update_market_data(
        goal=args.goal,
        mode=args.mode,
        provider=args.provider,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=symbols or None,
        update_limit=args.update_limit,
        force_snapshot=args.force_snapshot,
        dry_run=args.dry_run,
        progress_path=args.progress_path,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print("免费数据源更新")
        print(f"- 状态: {result.get('status')}")
        print(f"- 目标: {result.get('goal')}")
        print("- 自动尝试:")
        for index, attempt in enumerate(result.get("provider_attempts") or [], start=1):
            print(_format_attempt_line(index, attempt))
        print(f"- 后台选择: {result.get('latest_success_provider') or '暂无成功数据源'}")
        print(f"- 写入行数: {result.get('written_row_count', 0)}")
        if result.get("enhanced_pending_symbol_count") is not None:
            print("- 增强数据补齐:")
            print(f"  - 待补 daily_basic: {result.get('missing_daily_basic_symbol_count', 0)}")
            print(f"  - 待补 adj_factor: {result.get('missing_adj_factor_symbol_count', 0)}")
            print(f"  - 本次处理: {result.get('enhanced_processed_symbol_count', 0)}")
            print(f"  - daily_basic 写入: {result.get('daily_basic_written_row_count', 0)}")
            print(f"  - adj_factor 写入: {result.get('adj_factor_written_row_count', 0)}")
            print(f"  - adj_factor 来源: {'前复权价恒等兼容值' if result.get('adj_factor_source') == 'baostock_adjusted_price_identity' else result.get('adj_factor_source', '暂无')}")
        if result.get("failure_summary"):
            print("- 失败原因摘要:")
            for key, value in dict(result.get("failure_summary") or {}).items():
                print(f"  - {key}: {value}")
        print(f"- 说明: {result.get('user_summary') or result.get('message', '')}")
        print(f"- 下一步: {result.get('suggested_action', '')}")
    raise SystemExit(0 if result.get("status") in {"success", "partial", "partial_success", "skipped"} else 1)


if __name__ == "__main__":
    main()
