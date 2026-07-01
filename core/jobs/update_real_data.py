"""Minimal real data ingestion command for DuckDB."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import time
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.data_sources.base import DataSourceError, StockDataSource
from core.data_sources.basic_info_presets import enrich_with_basic_info_presets
from core.data_sources.provider import select_data_provider
from core.data_sources.real_universe import (
    FULL_UNIVERSE_LABEL,
    is_full_universe_preset,
    resolve_full_a_share_universe,
)
from core.data_sources.universe_presets import get_universe_preset, to_akshare_symbol
from core.runtime.progress import ProgressCallback, emit_progress, print_progress
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


TABLE_ORDER = [
    "stock_basic",
    "trade_calendar",
    "daily_price",
    "daily_basic",
    "adj_factor",
]

TABLE_COLUMNS = {
    "stock_basic": ["ts_code", "symbol", "name", "area", "industry", "market", "exchange", "list_date", "delist_date", "is_hs"],
    "trade_calendar": ["exchange", "cal_date", "is_open", "pretrade_date"],
    "daily_price": ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"],
    "daily_basic": ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"],
    "adj_factor": ["ts_code", "trade_date", "adj_factor"],
    "update_failures": [
        "ts_code",
        "provider",
        "table_name",
        "target_end_date",
        "status",
        "failed_stage",
        "error_message",
        "attempt_count",
        "first_seen_at",
        "last_seen_at",
    ],
}


def update_real_data(
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    client: StockDataSource | None = None,
    fallback_client: StockDataSource | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Fetch a small configured provider sample and upsert it into DuckDB.

    The function is intentionally small-scope: it only downloads the configured
    sample symbols and date range. Tests should inject ``client`` and ``store``;
    the default path performs real provider calls only when this command is
    invoked manually with the required local configuration.
    """
    resolved_settings = settings or get_settings()
    start_date = resolved_settings.real_data_start_date
    end_date = resolved_settings.real_data_end_date or date.today().strftime("%Y%m%d")
    selection = select_data_provider(resolved_settings, client, fallback_client)
    sample_symbols = _sample_symbols_for_provider(resolved_settings, selection.provider_name)

    if selection.provider_name == "sample":
        emit_progress(
            progress,
            step="update_real_data",
            skipped=len(sample_symbols),
            message="DATA_PROVIDER=sample，跳过真实数据更新。",
        )
        return {
            "status": "skipped",
            "message": "DATA_PROVIDER=sample，跳过真实数据更新；sample smoke test 仍可运行。",
            "data_source": "无真实数据",
            "start_date": start_date,
            "end_date": end_date,
            "sample_symbols": sample_symbols,
            "written_rows": {table_name: 0 for table_name in TABLE_ORDER},
            "before_rows": {table_name: 0 for table_name in TABLE_ORDER},
            "after_rows": {table_name: 0 for table_name in TABLE_ORDER},
            "empty_tables": TABLE_ORDER,
            "next_steps": ["python -m core.jobs.run_daily_selection"],
        }

    if selection.provider_name == "tushare" and not resolved_settings.tushare_token and client is None:
        if selection.fallback is None:
            emit_progress(
                progress,
                step="update_real_data",
                skipped=len(sample_symbols),
                message="TUSHARE_TOKEN 为空，跳过真实数据更新。",
            )
            return {
                "status": "skipped",
                "message": "TUSHARE_TOKEN 为空，跳过真实 Tushare 数据更新；sample smoke test 仍可运行。",
                "data_source": "无真实数据",
                "start_date": start_date,
                "end_date": end_date,
                "sample_symbols": sample_symbols,
                "full_universe_symbol_count": len(sample_symbols),
                "initial_update_symbols": 0,
                "incremental_update_symbols": 0,
                "written_rows": {table_name: 0 for table_name in TABLE_ORDER},
                "before_rows": {table_name: 0 for table_name in TABLE_ORDER},
                "after_rows": {table_name: 0 for table_name in TABLE_ORDER},
                "empty_tables": TABLE_ORDER,
                "next_steps": ["配置 TUSHARE_TOKEN 或 ENABLE_AKSHARE_FALLBACK=true 后重试。"],
            }
        return _run_provider_update(
            provider_name="akshare",
            client=selection.fallback,
            store=store,
            settings=resolved_settings,
            start_date=start_date,
            end_date=end_date,
            message_prefix="TUSHARE_TOKEN 为空，已尝试 AKShare fallback。",
            progress=progress,
        )

    result = _run_provider_update(
        provider_name=selection.provider_name,
        client=selection.primary,
        store=store,
        settings=resolved_settings,
        start_date=start_date,
        end_date=end_date,
        progress=progress,
    )
    if result["status"] == "failed" and selection.fallback is not None:
        return _run_provider_update(
            provider_name="akshare",
            client=selection.fallback,
            store=store,
            settings=resolved_settings,
            start_date=start_date,
            end_date=end_date,
            message_prefix=f"{result['message']} 已尝试 AKShare fallback。",
            progress=progress,
        )
    return result


def _run_provider_update(
    provider_name: str,
    client: StockDataSource | None,
    store: DuckDBStore | None,
    settings: Settings,
    start_date: str,
    end_date: str,
    message_prefix: str = "",
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Fetch and upsert one provider's configured sample data."""
    if client is None:
        return {
            "status": "skipped",
            "message": "未选择真实数据源；sample smoke test 仍可运行。",
            "data_source": "无真实数据",
            "start_date": start_date,
            "end_date": end_date,
            "sample_symbols": [],
            "written_rows": {table_name: 0 for table_name in TABLE_ORDER},
            "before_rows": {table_name: 0 for table_name in TABLE_ORDER},
            "after_rows": {table_name: 0 for table_name in TABLE_ORDER},
            "empty_tables": TABLE_ORDER,
            "next_steps": ["python -m core.jobs.run_daily_selection"],
        }

    sample_symbols = _sample_symbols_for_provider(settings, provider_name)
    effective_start_date = _effective_update_start_date(settings, provider_name, start_date, end_date)
    resolved_store = store or DuckDBStore(settings.duckdb_path)
    _configure_optional_enrichment(client, settings, provider_name)
    emit_progress(
        progress,
        step="update_real_data",
        current=provider_name,
        message=_initial_update_message(settings, provider_name, sample_symbols, effective_start_date, end_date),
    )

    try:
        resolved_store.initialize()
        before_rows = _table_row_counts(resolved_store)
        emit_progress(progress, step="stock_basic", current="stock_basic", message="读取股票基础信息。")
        full_universe_summary: dict[str, Any] = {}
        if _use_full_universe(settings, provider_name):
            stock_basic, full_universe_summary = _resolve_full_stock_basic_for_update(
                settings,
                client,
                resolved_store,
            )
            sample_symbols = list(full_universe_summary["symbols"])
            emit_progress(
                progress,
                step="stock_basic",
                current="full",
                success=len(sample_symbols),
                message=f"已获取 {FULL_UNIVERSE_LABEL} 基础列表 {len(sample_symbols)} 只。",
            )
        else:
            raw_stock_basic = client.get_stock_basic()
            stock_basic = _filter_stock_basic(raw_stock_basic, sample_symbols)
        if provider_name == "akshare":
            stock_basic = _merge_existing_stock_basic(stock_basic, resolved_store)
        if (
            provider_name == "akshare"
            and _should_run_stock_basic_enrichment(settings, provider_name)
            and hasattr(client, "enrich_stock_basic")
        ):
            try:
                stock_basic = client.enrich_stock_basic(stock_basic, sample_symbols)  # type: ignore[attr-defined]
            except Exception as exc:
                _record_client_enrichment(
                    client,
                    ["ALL"],
                    "stock_basic_enrichment",
                    f"{type(exc).__name__}: {exc}",
                )
        if (
            provider_name == "akshare"
            and getattr(settings, "enable_real_basic_enrichment", True)
            and not _use_full_universe(settings, provider_name)
        ):
            stock_basic = _apply_local_basic_info_presets(client, stock_basic)
        emit_progress(progress, step="trade_calendar", current="trade_calendar", message="读取交易日历。")
        update_plan = _build_symbol_update_plan(
            resolved_store,
            sample_symbols,
            effective_start_date,
            end_date,
            resume=_full_update_resume(settings, provider_name),
            max_symbols=_effective_max_symbols(settings, _use_full_universe(settings, provider_name)),
            batch_size=_effective_batch_size(settings, _use_full_universe(settings, provider_name)),
            max_batches=_effective_max_batches(settings, _use_full_universe(settings, provider_name)),
            mode=_effective_update_mode(settings, _use_full_universe(settings, provider_name)),
            skip_empty_unavailable=_effective_skip_empty_unavailable(settings, _use_full_universe(settings, provider_name)),
        )
        symbols_to_fetch = update_plan["symbols_to_fetch"]
        skipped_symbols = update_plan["skipped_symbols"]
        full_universe_count = len(sample_symbols)
        missing_count = len(update_plan.get("missing_symbols", []))
        priced_count = max(full_universe_count - missing_count, 0)
        pending_queue_count = int(update_plan.get("total_pending_symbols", len(symbols_to_fetch)))
        emit_progress(
            progress,
            step="update_plan",
            current="resume" if update_plan.get("resume") else "full",
            success=len(update_plan.get("incremental_update_symbols", [])),
            failed=0,
            skipped=len(skipped_symbols),
            message=(
                f"full 基础股票池数量 {full_universe_count} 只，已有行情 {priced_count} 只，"
                f"缺数据 {missing_count} 只，本次未处理 {len(skipped_symbols)} 只，"
                f"增量更新 {len(update_plan.get('incremental_update_symbols', []))} 只，"
                f"首次补数据 {len(update_plan.get('initial_update_symbols', []))} 只，"
                f"待处理队列 {pending_queue_count} 只，"
                f"本次计划处理 {len(symbols_to_fetch)} 只，每批大小 {_effective_batch_size(settings, _use_full_universe(settings, provider_name))}。"
            ),
        )
        frames = {
            "stock_basic": stock_basic,
            "trade_calendar": _filter_date_range(
                client.get_trade_calendar(),
                "cal_date",
                effective_start_date,
                end_date,
            ),
            "daily_price": _fetch_symbol_table_in_batches(
                client.get_daily_price,
                client,
                effective_start_date,
                end_date,
                symbols_to_fetch,
                settings,
                table_name="daily_price",
                full_mode=_use_full_universe(settings, provider_name),
                symbol_start_dates=update_plan.get("symbol_start_dates", {}),
                progress=progress,
            ),
            "daily_basic": _fetch_symbol_table_in_batches(
                client.get_daily_basic,
                client,
                effective_start_date,
                end_date,
                symbols_to_fetch,
                settings,
                table_name="daily_basic",
                full_mode=_use_full_universe(settings, provider_name),
                symbol_start_dates=update_plan.get("symbol_start_dates", {}),
                progress=progress,
            ),
            "adj_factor": _fetch_symbol_table_in_batches(
                client.get_adj_factor,
                client,
                effective_start_date,
                end_date,
                symbols_to_fetch,
                settings,
                table_name="adj_factor",
                full_mode=_use_full_universe(settings, provider_name),
                symbol_start_dates=update_plan.get("symbol_start_dates", {}),
                progress=progress,
            ),
        }
        normalized_frames = {
            table_name: _ensure_table_columns(table_name, frame)
            for table_name, frame in frames.items()
        }
        if (
            provider_name == "akshare"
            and _should_run_valuation_enrichment(settings, provider_name)
            and hasattr(client, "enrich_daily_basic_valuation")
        ):
            emit_progress(progress, step="valuation_enrichment", current="daily_basic", message="尝试补全估值字段。")
            normalized_frames["daily_basic"] = _apply_valuation_enrichment(
                client,
                normalized_frames["daily_basic"],
                normalized_frames["stock_basic"],
                resolved_store,
            )
        empty_tables = [
            table_name
            for table_name, frame in normalized_frames.items()
            if frame.empty
        ]
        batch_summary = _batch_summary(
            provider_name,
            sample_symbols,
            normalized_frames,
            client,
            skipped_symbols=skipped_symbols,
            planned_symbols=symbols_to_fetch,
        )
        batch_summary.update(_update_runtime_summary(settings, _use_full_universe(settings, provider_name)))
        enrichment_summary = _enrichment_summary(sample_symbols, normalized_frames, client, settings, provider_name)
        if provider_name == "akshare" and normalized_frames["daily_price"].empty and symbols_to_fetch:
            return {
                "status": "failed",
                "message": "真实数据更新失败：AKShare 所有样本股票日线行情均为空或失败。",
                "data_source": provider_name,
                "start_date": effective_start_date,
                "requested_start_date": start_date,
                "end_date": end_date,
                "sample_symbols": sample_symbols,
                "written_rows": {table_name: 0 for table_name in TABLE_ORDER},
                "before_rows": before_rows,
                "after_rows": before_rows,
                "empty_tables": empty_tables,
                **batch_summary,
                "update_plan": update_plan,
                **enrichment_summary,
                "next_steps": ["检查 AKShare 网络、版本或样本股票配置后重试。"],
            }
        written_rows = {}
        for table_name, frame in normalized_frames.items():
            emit_progress(
                progress,
                step="write_table",
                current=table_name,
                message=f"写入 {table_name}，待写入行数 {len(frame)}。",
            )
            written_rows[table_name] = resolved_store.upsert_dataframe(table_name, frame)
        after_rows = _table_row_counts(resolved_store)
    except (DataSourceError, DuckDBStoreError) as exc:
        return {
            "status": "failed",
            "message": f"真实数据更新失败：{exc}",
            "data_source": provider_name,
            "start_date": start_date,
            "end_date": end_date,
            "sample_symbols": sample_symbols,
            "written_rows": {table_name: 0 for table_name in TABLE_ORDER},
            "before_rows": {table_name: 0 for table_name in TABLE_ORDER},
            "after_rows": {table_name: 0 for table_name in TABLE_ORDER},
            "empty_tables": TABLE_ORDER,
            "next_steps": ["检查数据源配置后重试。"],
        }

    batch_summary = _batch_summary(
        provider_name,
        sample_symbols,
        normalized_frames,
        client,
        skipped_symbols=skipped_symbols,
        planned_symbols=symbols_to_fetch,
    )
    batch_summary.update(_update_runtime_summary(settings, _use_full_universe(settings, provider_name)))
    enrichment_summary = _enrichment_summary(sample_symbols, normalized_frames, client, settings, provider_name)
    failure_rows = _failure_records_to_rows(
        batch_summary.get("failure_records", []),
        provider_name,
        end_date,
        existing=_safe_read_table(resolved_store, "update_failures"),
    )
    if not failure_rows.empty:
        resolved_store.upsert_dataframe("update_failures", failure_rows)
    status = _status_from_batch_summary(batch_summary)
    emit_progress(
        progress,
        step="update_real_data",
        current=provider_name,
        success=batch_summary.get("success_symbols", 0),
        failed=batch_summary.get("failed_symbols", 0),
        skipped=batch_summary.get("skipped_symbols", 0),
        message=f"真实数据更新完成，状态 {status}。",
    )
    return {
        "status": status,
        "message": f"{message_prefix} 真实 {provider_name} 数据更新完成。".strip(),
        "data_source": provider_name,
        "universe_preset": getattr(settings, "real_universe_preset", "mini"),
        "universe_label": FULL_UNIVERSE_LABEL if _use_full_universe(settings, provider_name) else getattr(settings, "real_universe_preset", "mini"),
        "full_universe_summary": _jsonable_universe_summary(full_universe_summary),
        "start_date": effective_start_date,
        "requested_start_date": start_date,
        "end_date": end_date,
        "sample_symbols": sample_symbols,
        "update_plan": update_plan,
        "full_universe_symbol_count": len(sample_symbols),
        "full_universe_count": len(sample_symbols),
        "priced_symbol_count": max(len(sample_symbols) - len(update_plan.get("missing_symbols", [])), 0),
        "missing_symbol_count": len(update_plan.get("missing_symbols", [])),
        "pending_queue_count": int(update_plan.get("total_pending_symbols", len(symbols_to_fetch))),
        "planned_count": len(symbols_to_fetch),
        "initial_update_symbols": len(update_plan.get("initial_update_symbols", [])),
        "incremental_update_symbols": len(update_plan.get("incremental_update_symbols", [])),
        "written_rows": written_rows,
        "before_rows": before_rows,
        "after_rows": after_rows,
        "empty_tables": empty_tables,
        **batch_summary,
        **enrichment_summary,
        "next_steps": [
            "python -m core.jobs.diagnose_real_data",
            "python -m core.jobs.diagnose_update_batch",
            "python -m core.jobs.run_daily_selection",
        ],
    }


def main() -> None:
    """Run the minimal real data update and print a concise summary."""
    result = update_real_data(progress=print_progress)
    print("真实数据更新摘要")
    print(f"- 状态: {result['status']}")
    print(f"- 说明: {result['message']}")
    print(f"- 数据来源: {result['data_source']}")
    print(f"- 日期范围: {result['start_date']} 至 {result['end_date']}")
    if result.get("is_full_update"):
        print(f"- 股票池: {result.get('universe_label', FULL_UNIVERSE_LABEL)}")
    else:
        print(f"- 样本股票: {', '.join(result['sample_symbols']) or '未配置'}")
    if "total_symbols" in result:
        print(f"- 主行情更新: {result['status']}")
        print(
            f"- 主行情统计: 总股票数 {result['total_symbols']}，成功 {result['success_symbols']}，"
            f"失败 {result['failed_symbols']}，跳过 {result.get('skipped_symbols', 0)}，"
            f"本次计划 {result.get('planned_symbols', 0)}，暂未处理 {result.get('deferred_symbols', 0)}，"
            f"完成率 {result.get('completion_rate', result['success_rate']):.2%}"
        )
        if result.get("is_full_update"):
            print(
                f"- full 更新设置: batch_size={result.get('effective_batch_size')}，"
                f"lookback_days={result.get('full_update_lookback_days')}，"
                f"max_retries={result.get('effective_max_retries')}，resume={result.get('full_update_resume')}，"
                f"max_symbols={result.get('full_update_max_symbols')}，max_batches={result.get('full_update_max_batches')}"
            )
            print(
                f"- full 更新队列: full 基础股票池 {result.get('full_universe_count', result.get('full_universe_symbol_count', result.get('total_symbols', 0)))}，"
                f"已有行情 {result.get('priced_symbol_count', 0)}，"
                f"缺数据 {result.get('missing_symbol_count', 0)}，"
                f"待处理队列 {result.get('pending_queue_count', 0)}，"
                f"本次未处理 {result.get('skipped_symbols', 0)}，"
                f"增量更新 {result.get('incremental_update_symbols', 0)}，"
                f"首次补数据 {result.get('initial_update_symbols', 0)}，"
                f"本次计划 {result.get('planned_count', result.get('planned_symbols', 0))}，"
                f"失败 {result.get('failed_symbols', 0)}"
            )
    enrichment = result.get("enrichment_summary", {})
    if enrichment:
        print(
            f"- 基础信息补全: {enrichment.get('basic_status')}，"
            f"成功 {enrichment.get('basic_success_symbols', 0)}，失败 {enrichment.get('basic_failed_symbols', 0)}"
        )
        if enrichment.get("basic_preset_success_symbols", 0):
            print(f"- 本地基础信息 preset fallback 成功: {enrichment.get('basic_preset_success_symbols', 0)}")
        print(
            f"- 估值字段补全: {enrichment.get('valuation_status')}，"
            f"成功 {enrichment.get('valuation_success_symbols', 0)}，失败 {enrichment.get('valuation_failed_symbols', 0)}"
        )
        if enrichment.get("warnings"):
            print("- 补全提示:")
            for item in _group_enrichment_warnings(enrichment["warnings"]):
                print(
                    f"  {item['symbols']} stage={item['failed_stage']} "
                    f"count={item['count']} message={item['error_message']}"
                )
            print("- 补全失败不影响主行情更新。")
    print("- 写入行数:")
    for table_name, row_count in result["written_rows"].items():
        before = result.get("before_rows", {}).get(table_name, 0)
        after = result.get("after_rows", {}).get(table_name, 0)
        print(f"  {table_name}: {row_count}（更新前 {before}，更新后 {after}）")
    if result.get("empty_tables"):
        print(f"- 空数据表: {', '.join(result['empty_tables'])}")
    if result.get("empty_data_symbols"):
        examples = list(result["empty_data_symbols"])[:10]
        print(f"- 空数据股票: {len(result['empty_data_symbols'])} 只，样例: {', '.join(examples)}")
    if result.get("failure_records"):
        examples = [str(item.get("symbol", "")) for item in result["failure_records"] if item.get("symbol")][:10]
        print(f"- 失败/不可用股票: {len(result['failure_records'])} 条，样例: {', '.join(examples)}")
    print("- 下一步建议:")
    for step in result.get("next_steps", []):
        print(f"  {step}")


def _filter_stock_basic(df: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """Keep configured sample symbols from stock_basic when present."""
    if df.empty or not symbols:
        return df
    result = df.copy()
    if "ts_code" not in result.columns and "symbol" in result.columns:
        result["ts_code"] = result["symbol"].map(_to_ts_code)
    if "ts_code" not in result.columns:
        return result
    ts_codes = {_to_ts_code(symbol) for symbol in symbols}
    return result[result["ts_code"].isin(ts_codes)].reset_index(drop=True)


def _resolve_full_stock_basic_for_update(
    settings: Settings,
    client: StockDataSource,
    store: DuckDBStore,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Resolve full-universe stock_basic without shrinking to local cached samples."""
    include_bse = getattr(settings, "include_bse", False)
    cached = _safe_read_table(store, "stock_basic")

    try:
        if hasattr(client, "get_full_a_share_basic_excluding_bse"):
            raw_stock_basic = client.get_full_a_share_basic_excluding_bse()  # type: ignore[attr-defined]
        else:
            raise DataSourceError("client does not provide full HS A-share basic list")
        provider_summary = resolve_full_a_share_universe(raw_stock_basic, include_bse=include_bse)
        provider_summary["stock_basic"] = _merge_full_stock_basic_fields(
            provider_summary["stock_basic"],
            cached,
        )
        provider_summary["source"] = "full HS A-share basic list"
        return provider_summary["stock_basic"], provider_summary
    except Exception as exc:
        fallback_summary = resolve_full_a_share_universe(cached, include_bse=include_bse)
        warning = (
            f"full 基础股票列表获取失败：{type(exc).__name__}: {exc}。"
            "本地缓存不可用，无法继续 full 更新。"
        )
        if fallback_summary.get("base_universe_count", 0):
            warning = (
                f"full 基础股票列表获取失败：{type(exc).__name__}: {exc}。"
                "已回退使用本地 stock_basic 缓存。"
            )
        fallback_summary["warnings"] = [warning, *list(fallback_summary.get("warnings", []))]
        return fallback_summary["stock_basic"], fallback_summary


def _merge_full_stock_basic_fields(provider_stock_basic: pd.DataFrame, cached_stock_basic: pd.DataFrame) -> pd.DataFrame:
    """Fill missing full-universe stock_basic fields from local cache without changing membership."""
    if provider_stock_basic.empty or cached_stock_basic.empty or "ts_code" not in cached_stock_basic.columns:
        return provider_stock_basic
    result = provider_stock_basic.copy()
    cached = cached_stock_basic.drop_duplicates("ts_code", keep="last").copy()
    enrich_columns = [
        column
        for column in ["name", "area", "industry", "market", "exchange", "list_date", "delist_date", "is_hs"]
        if column in cached.columns
    ]
    if not enrich_columns:
        return result
    merged = result.merge(cached[["ts_code", *enrich_columns]], on="ts_code", how="left", suffixes=("", "_cached"))
    for column in enrich_columns:
        cached_column = f"{column}_cached"
        if cached_column in merged.columns:
            if column not in merged.columns:
                merged[column] = pd.NA
            merged[column] = merged[column].where(merged[column].map(_has_value), merged[cached_column])
            merged = merged.drop(columns=[cached_column])
    return merged


def _has_value(value: Any) -> bool:
    """Return whether a stock_basic field should be considered present."""
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip() != ""


def _use_full_universe(settings: Settings, provider_name: str) -> bool:
    """Return whether provider update should discover the full HS A-share universe."""
    if provider_name != "akshare":
        return False
    # AKSHARE_SAMPLE_SYMBOLS stays higher priority than REAL_UNIVERSE_PRESET=full.
    if [symbol.strip() for symbol in getattr(settings, "akshare_sample_symbols", "").split(",") if symbol.strip()]:
        return False
    return is_full_universe_preset(getattr(settings, "real_universe_preset", "mini"))


def _initial_update_message(
    settings: Settings,
    provider_name: str,
    sample_symbols: list[str],
    start_date: str,
    end_date: str,
) -> str:
    """Return a progress message before provider stock_basic is resolved."""
    if _use_full_universe(settings, provider_name):
        return f"开始解析 {FULL_UNIVERSE_LABEL} 基础股票池，日期 {start_date}-{end_date}。"
    return f"开始更新 {len(sample_symbols)} 只样本股票，日期 {start_date}-{end_date}。"


def _should_run_stock_basic_enrichment(settings: Settings, provider_name: str) -> bool:
    """Return whether optional per-symbol stock_basic enrichment may run."""
    if provider_name != "akshare":
        return False
    if not getattr(settings, "enable_real_basic_enrichment", True):
        return False
    if _use_full_universe(settings, provider_name):
        return bool(getattr(settings, "full_enable_stock_basic_enrichment", False))
    specific = getattr(settings, "enable_stock_basic_enrichment", None)
    if specific is None:
        return True
    return bool(specific)


def _should_run_valuation_enrichment(settings: Settings, provider_name: str) -> bool:
    """Return whether optional valuation enrichment may run network fallbacks."""
    if provider_name != "akshare":
        return False
    if not getattr(settings, "enable_real_valuation_enrichment", True):
        return False
    if _use_full_universe(settings, provider_name):
        return bool(getattr(settings, "full_enable_valuation_enrichment", False))
    specific = getattr(settings, "enable_valuation_enrichment", None)
    if specific is None:
        return True
    return bool(specific)


def _configure_optional_enrichment(client: StockDataSource, settings: Settings, provider_name: str) -> None:
    """Synchronize injected clients with job-level optional enrichment flags."""
    if provider_name != "akshare":
        return
    if hasattr(client, "enable_valuation_enrichment"):
        setattr(client, "enable_valuation_enrichment", _should_run_valuation_enrichment(settings, provider_name))
    if hasattr(client, "enable_basic_enrichment"):
        setattr(client, "enable_basic_enrichment", _should_run_stock_basic_enrichment(settings, provider_name))


def _full_update_resume(settings: Settings, provider_name: str) -> bool:
    """Return whether full-universe updates should skip symbols already current."""
    return _use_full_universe(settings, provider_name) and bool(getattr(settings, "full_update_resume", True))


def _effective_update_start_date(settings: Settings, provider_name: str, start_date: str, end_date: str) -> str:
    """Return a bounded start date for full universe updates."""
    if not _use_full_universe(settings, provider_name):
        return start_date
    lookback_days = max(1, int(getattr(settings, "full_update_lookback_days", 250) or 250))
    try:
        end = datetime.strptime(end_date, "%Y%m%d").date()
        bounded = (end - timedelta(days=lookback_days)).strftime("%Y%m%d")
    except ValueError:
        return start_date
    return max(str(start_date), bounded)


def _build_symbol_update_plan(
    store: DuckDBStore,
    symbols: list[str],
    default_start_date: str,
    target_end_date: str,
    *,
    resume: bool,
    max_symbols: int = 0,
    batch_size: int = 50,
    max_batches: int = 0,
    mode: str = "missing_first",
    skip_empty_unavailable: bool = True,
) -> dict[str, Any]:
    """Return per-symbol update plan across price, daily_basic, and adj_factor."""
    requested = [_to_ts_code(symbol) for symbol in symbols]
    default_start_date = str(default_start_date)
    target_end_date = str(target_end_date)
    if not resume or not requested:
        planned_symbols = _limit_symbols(list(symbols), max_symbols=max_symbols, batch_size=batch_size, max_batches=max_batches)
        return {
            "target_end_date": target_end_date,
            "default_start_date": default_start_date,
            "resume": resume,
            "symbols_to_fetch": planned_symbols,
            "total_pending_symbols": len(symbols),
            "skipped_symbols": [],
            "incremental_update_symbols": [_to_ts_code(symbol) for symbol in planned_symbols],
            "initial_update_symbols": [],
            "stale_symbols": [],
            "missing_symbols": [],
            "symbol_start_dates": {_to_ts_code(symbol): default_start_date for symbol in planned_symbols},
        }
    latest_by_table = {
        "daily_price": _latest_dates_by_symbol(_safe_read_table(store, "daily_price")),
        "daily_basic": _latest_dates_by_symbol(_safe_read_table(store, "daily_basic")),
        "adj_factor": _latest_dates_by_symbol(_safe_read_table(store, "adj_factor")),
    }
    deferred_empty_symbols = _empty_data_symbols_for_target(store, target_end_date) if skip_empty_unavailable else set()
    skipped: list[str] = []
    stale: list[str] = []
    missing: list[str] = []
    incremental: list[str] = []
    initial: list[str] = []
    initial_original: list[str] = []
    deferred_initial_original: list[str] = []
    incremental_original: list[str] = []
    start_dates: dict[str, str] = {}
    for original_symbol, ts_code in zip(symbols, requested, strict=False):
        latest_dates = {table: latest.get(ts_code) for table, latest in latest_by_table.items()}
        if all(value is not None and str(value) >= target_end_date for value in latest_dates.values()):
            skipped.append(ts_code)
            continue
        if latest_dates["daily_price"] is None:
            missing.append(ts_code)
            initial.append(ts_code)
            if skip_empty_unavailable and ts_code in deferred_empty_symbols:
                deferred_initial_original.append(original_symbol)
            else:
                initial_original.append(original_symbol)
            start_dates[ts_code] = default_start_date
            continue
        stale.append(ts_code)
        incremental.append(ts_code)
        incremental_original.append(original_symbol)
        if any(value is None for value in latest_dates.values()):
            start_dates[ts_code] = default_start_date
        else:
            earliest_latest = min(str(value) for value in latest_dates.values() if value is not None)
            start_dates[ts_code] = min(_next_yyyymmdd(earliest_latest), target_end_date)
    if mode == "stale_first":
        pending = [*incremental_original, *initial_original]
    elif mode == "auto":
        pending = [*initial_original, *incremental_original]
    else:
        pending = [*initial_original, *incremental_original]
    if not skip_empty_unavailable:
        pending.extend(deferred_initial_original)
    planned_symbols = _limit_symbols(
        pending,
        max_symbols=max_symbols,
        batch_size=batch_size,
        max_batches=max_batches,
    )
    planned_ts_codes = {_to_ts_code(symbol) for symbol in planned_symbols}
    return {
        "target_end_date": target_end_date,
        "default_start_date": default_start_date,
        "resume": resume,
        "symbols_to_fetch": planned_symbols,
        "total_pending_symbols": len(pending),
        "skipped_symbols": skipped,
        "incremental_update_symbols": [symbol for symbol in incremental if symbol in planned_ts_codes],
        "initial_update_symbols": [symbol for symbol in initial if symbol in planned_ts_codes],
        "stale_symbols": stale,
        "missing_symbols": missing,
        "deferred_empty_symbols": sorted(deferred_empty_symbols.intersection(set(missing))),
        "update_mode": mode,
        "skip_empty_unavailable": skip_empty_unavailable,
        "symbol_start_dates": {symbol: start for symbol, start in start_dates.items() if symbol in planned_ts_codes},
    }


def _limit_symbols(symbols: list[str], *, max_symbols: int, batch_size: int, max_batches: int) -> list[str]:
    """Limit planned symbols for safe real-world smoke tests."""
    limit = len(symbols)
    if max_batches > 0:
        limit = min(limit, max(1, batch_size) * max_batches)
    if max_symbols > 0:
        limit = min(limit, max_symbols)
    return symbols[:limit]


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    """Read a local table, returning an empty frame when unavailable."""
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _latest_dates_by_symbol(df: pd.DataFrame) -> dict[str, str]:
    """Return max trade_date by ts_code for a market data table."""
    if df.empty or not {"ts_code", "trade_date"}.issubset(df.columns):
        return {}
    return (
        df.assign(ts_code=df["ts_code"].astype(str), trade_date=df["trade_date"].astype(str))
        .groupby("ts_code")["trade_date"]
        .max()
        .to_dict()
    )


def _empty_data_symbols_for_target(store: DuckDBStore, target_end_date: str) -> set[str]:
    """Return symbols already marked empty for the target end date."""
    failures = _safe_read_table(store, "update_failures")
    if failures.empty or "ts_code" not in failures.columns:
        return set()
    required = {"table_name", "target_end_date", "status"}
    if not required.issubset(failures.columns):
        return set()
    rows = failures[
        (failures["table_name"].astype(str) == "daily_price")
        & (failures["target_end_date"].astype(str) == str(target_end_date))
        & (failures["status"].astype(str).isin(["empty_data", "temporarily_unavailable"]))
    ]
    return set(rows["ts_code"].dropna().astype(str))


def _next_yyyymmdd(value: str) -> str:
    """Return the calendar day after a YYYYMMDD value."""
    try:
        return (datetime.strptime(str(value), "%Y%m%d").date() + timedelta(days=1)).strftime("%Y%m%d")
    except ValueError:
        return str(value)


def _jsonable_universe_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return full-universe summary without DataFrames."""
    return {key: value for key, value in summary.items() if key != "stock_basic"}


def _group_enrichment_warnings(warnings: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Group repeated optional enrichment warnings for concise CLI output."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for item in warnings:
        key = (str(item.get("failed_stage", "unknown")), str(item.get("error_message", "")))
        grouped.setdefault(key, []).append(str(item.get("symbol", "")))
    rows: list[dict[str, Any]] = []
    for (stage, message), symbols in grouped.items():
        unique_symbols = list(dict.fromkeys(symbol for symbol in symbols if symbol))
        preview = ",".join(unique_symbols[:5])
        if len(unique_symbols) > 5:
            preview = f"{preview},..."
        rows.append(
            {
                "failed_stage": stage,
                "error_message": message,
                "symbols": preview or "ALL",
                "count": len(unique_symbols),
            }
        )
    return rows


def _merge_existing_stock_basic(stock_basic: pd.DataFrame, store: DuckDBStore) -> pd.DataFrame:
    """Include existing stock_basic rows so preset fallback can repair prior samples."""
    try:
        existing = store.read_table("stock_basic")
    except DuckDBStoreError:
        existing = pd.DataFrame()
    frames = [frame for frame in [existing, stock_basic] if not frame.empty]
    if not frames:
        return stock_basic
    combined = pd.concat(frames, ignore_index=True)
    if "ts_code" not in combined.columns:
        return combined
    return combined.drop_duplicates("ts_code", keep="last").reset_index(drop=True)


def _apply_local_basic_info_presets(client: StockDataSource, stock_basic: pd.DataFrame) -> pd.DataFrame:
    """Fill missing stock_basic fields from local presets and record fallback events."""
    before = stock_basic.copy()
    enriched, missing_records = enrich_with_basic_info_presets(stock_basic)
    records = getattr(client, "enrichment_records", None)
    if isinstance(records, list):
        for symbol in _preset_filled_symbols(before, enriched):
            records.append(
                {
                    "symbol": symbol,
                    "provider": "local_preset",
                    "failed_stage": "stock_basic_preset_fallback_success",
                    "error_message": "local basic info preset filled missing fields",
                }
            )
        records.extend(missing_records)
    return enriched


def _apply_valuation_enrichment(
    client: StockDataSource,
    daily_basic: pd.DataFrame,
    stock_basic: pd.DataFrame,
    store: DuckDBStore,
) -> pd.DataFrame:
    """Fill valuation fields for current and existing local daily_basic rows."""
    combined = _merge_existing_daily_basic(daily_basic, store)
    symbols = _valuation_target_symbols(combined, stock_basic)
    if not symbols:
        return combined
    try:
        return client.enrich_daily_basic_valuation(combined, symbols)  # type: ignore[attr-defined]
    except Exception as exc:
        _record_client_enrichment(
            client,
            ["ALL"],
            "daily_basic_valuation_enrichment",
            f"{type(exc).__name__}: {exc}",
        )
        return combined


def _merge_existing_daily_basic(daily_basic: pd.DataFrame, store: DuckDBStore) -> pd.DataFrame:
    """Include existing daily_basic so valuation snapshots can repair prior samples."""
    try:
        existing = store.read_table("daily_basic")
    except DuckDBStoreError:
        existing = pd.DataFrame()
    frames = [frame for frame in [existing, daily_basic] if not frame.empty]
    if not frames:
        return daily_basic
    combined = pd.concat(frames, ignore_index=True)
    if {"ts_code", "trade_date"}.issubset(combined.columns):
        rows = []
        for _, group in combined.groupby(["ts_code", "trade_date"], sort=False):
            row = group.iloc[-1].copy()
            for column in group.columns:
                if _is_missing(row.get(column)):
                    values = group[column].dropna()
                    values = values[values.astype(str).str.strip() != ""]
                    if not values.empty:
                        row[column] = values.iloc[-1]
            rows.append(row)
        combined = pd.DataFrame(rows)
    return combined.reset_index(drop=True)


def _valuation_target_symbols(daily_basic: pd.DataFrame, stock_basic: pd.DataFrame) -> list[str]:
    """Return target symbols from local tables for valuation snapshot repair."""
    values: list[str] = []
    if not stock_basic.empty and "ts_code" in stock_basic.columns:
        values.extend(stock_basic["ts_code"].dropna().astype(str).tolist())
    if not daily_basic.empty and "ts_code" in daily_basic.columns:
        values.extend(daily_basic["ts_code"].dropna().astype(str).tolist())
    return list(dict.fromkeys(_to_ts_code(symbol) for symbol in values if str(symbol).strip()))


def _preset_filled_symbols(before: pd.DataFrame, after: pd.DataFrame) -> list[str]:
    """Return symbols whose key basic fields were filled by preset fallback."""
    if before.empty or after.empty or "ts_code" not in before.columns or "ts_code" not in after.columns:
        return []
    key_fields = ["industry", "market", "list_date"]
    before_indexed = before.set_index("ts_code")
    after_indexed = after.set_index("ts_code")
    symbols: list[str] = []
    for symbol in after_indexed.index.astype(str):
        if symbol not in before_indexed.index:
            continue
        for field in key_fields:
            before_value = before_indexed.at[symbol, field] if field in before_indexed.columns else pd.NA
            after_value = after_indexed.at[symbol, field] if field in after_indexed.columns else pd.NA
            if _is_missing(before_value) and not _is_missing(after_value):
                symbols.append(symbol)
                break
    return symbols


def _filter_date_range(df: pd.DataFrame, column: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Filter a DataFrame by inclusive YYYYMMDD date strings."""
    if df.empty or column not in df.columns:
        return df
    values = df[column].astype(str)
    return df[(values >= start_date) & (values <= end_date)].reset_index(drop=True)


def _ensure_table_columns(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Ensure provider frames have project table columns before DuckDB upsert."""
    columns = TABLE_COLUMNS[table_name]
    if df.empty:
        return pd.DataFrame(columns=columns)
    result = df.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    return result[columns]


def _table_row_counts(store: DuckDBStore) -> dict[str, int]:
    """Read current table row counts, returning zero for unavailable tables."""
    counts: dict[str, int] = {}
    for table_name in TABLE_ORDER:
        try:
            counts[table_name] = int(len(store.read_table(table_name)))
        except DuckDBStoreError:
            counts[table_name] = 0
    return counts


def _fetch_symbol_table_in_batches(
    fetcher: Any,
    client: StockDataSource,
    start_date: str,
    end_date: str,
    symbols: list[str],
    settings: Settings,
    table_name: str,
    full_mode: bool = False,
    symbol_start_dates: dict[str, str] | None = None,
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    """Fetch a symbol table in configured batches with simple retries."""
    if not symbols:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    batch_size = _effective_batch_size(settings, full_mode)
    max_retries = _effective_max_retries(settings, full_mode)
    sleep_seconds = _effective_sleep_seconds(settings, full_mode)
    batches = _date_grouped_batches(symbols, batch_size, start_date, symbol_start_dates or {})
    success_symbols: set[str] = set()
    failed_symbols: set[str] = set()
    total_symbols = sum(len(batch_symbols) for _, batch_symbols in batches)
    processed_symbols = 0
    for batch_index, (batch_start_date, batch) in enumerate(batches):
        current = ",".join(_to_ts_code(symbol) for symbol in batch)
        emit_progress(
            progress,
            step=table_name,
            current=current,
            success=len(success_symbols),
            failed=len(failed_symbols),
            skipped=max(total_symbols - processed_symbols - len(batch), 0),
            message=(
                f"开始处理第 {batch_index + 1}/{len(batches)} 批，"
                f"日期 {batch_start_date}-{end_date}，剩余约 {total_symbols - processed_symbols} 只。"
            ),
        )
        frame = pd.DataFrame()
        for attempt in range(max_retries):
            try:
                frame = fetcher(batch_start_date, end_date, batch)
                break
            except DataSourceError as exc:
                _record_client_failure(client, batch, f"{table_name}:{fetcher.__name__}", str(exc))
                if attempt + 1 >= max_retries:
                    frame = pd.DataFrame()
            except Exception as exc:
                _record_client_failure(
                    client,
                    batch,
                    f"{table_name}:{fetcher.__name__}",
                    f"{type(exc).__name__}: {exc}",
                )
                if attempt + 1 >= max_retries:
                    frame = pd.DataFrame()
        if not frame.empty:
            frames.append(frame)
            if "ts_code" in frame.columns:
                success_symbols.update(frame["ts_code"].dropna().astype(str).unique())
        else:
            failed_symbols.update(_to_ts_code(symbol) for symbol in batch)
        processed_symbols += len(batch)
        emit_progress(
            progress,
            step=table_name,
            current=current,
            success=len(success_symbols),
            failed=len(failed_symbols),
            skipped=max(total_symbols - processed_symbols, 0),
            message=f"完成第 {batch_index + 1}/{len(batches)} 批，返回行数 {len(frame)}。",
        )
        if sleep_seconds and batch_index < len(batches) - 1:
            time.sleep(sleep_seconds)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _effective_batch_size(settings: Settings, full_mode: bool) -> int:
    """Return batch size for sample or full universe updates."""
    key = "full_update_batch_size" if full_mode else "real_batch_size"
    default = 50 if full_mode else 10
    return max(1, int(getattr(settings, key, default) or default))


def _effective_max_retries(settings: Settings, full_mode: bool) -> int:
    """Return retry count for sample or full universe updates."""
    key = "full_update_max_retries" if full_mode else "real_max_retries"
    default = 2 if full_mode else 1
    return max(1, int(getattr(settings, key, default) or default))


def _effective_sleep_seconds(settings: Settings, full_mode: bool) -> float:
    """Return throttling sleep seconds for sample or full universe updates."""
    key = "full_update_sleep_seconds" if full_mode else "real_batch_sleep_seconds"
    default = 0.2 if full_mode else 0.0
    return max(0.0, float(getattr(settings, key, default) or 0.0))


def _effective_max_symbols(settings: Settings, full_mode: bool) -> int:
    """Return optional maximum symbols for one full update run; 0 means unlimited."""
    if not full_mode:
        return 0
    return max(0, int(getattr(settings, "full_update_max_symbols", 0) or 0))


def _effective_max_batches(settings: Settings, full_mode: bool) -> int:
    """Return optional maximum batches for one full update run; 0 means unlimited."""
    if not full_mode:
        return 0
    return max(0, int(getattr(settings, "full_update_max_batches", 0) or 0))


def _effective_update_mode(settings: Settings, full_mode: bool) -> str:
    """Return full update queue mode."""
    if not full_mode:
        return "missing_first"
    value = str(getattr(settings, "full_update_mode", "missing_first") or "missing_first")
    return value if value in {"missing_first", "stale_first", "auto"} else "missing_first"


def _effective_skip_empty_unavailable(settings: Settings, full_mode: bool) -> bool:
    """Return whether known empty/unavailable symbols should be excluded from this run."""
    if not full_mode:
        return False
    return bool(getattr(settings, "full_update_skip_empty_unavailable", True))


def _update_runtime_summary(settings: Settings, full_mode: bool) -> dict[str, Any]:
    """Return update runtime settings for command summaries."""
    return {
        "is_full_update": bool(full_mode),
        "effective_batch_size": _effective_batch_size(settings, full_mode),
        "effective_max_retries": _effective_max_retries(settings, full_mode),
        "effective_sleep_seconds": _effective_sleep_seconds(settings, full_mode),
        "full_update_lookback_days": int(getattr(settings, "full_update_lookback_days", 250) or 250) if full_mode else None,
        "full_update_resume": bool(getattr(settings, "full_update_resume", True)) if full_mode else None,
        "full_update_max_symbols": _effective_max_symbols(settings, full_mode) if full_mode else None,
        "full_update_max_batches": _effective_max_batches(settings, full_mode) if full_mode else None,
        "full_update_mode": _effective_update_mode(settings, full_mode) if full_mode else None,
        "full_update_skip_empty_unavailable": _effective_skip_empty_unavailable(settings, full_mode) if full_mode else None,
    }


def _chunks(symbols: list[str], size: int) -> list[list[str]]:
    """Split symbols into fixed-size chunks."""
    return [symbols[index : index + size] for index in range(0, len(symbols), size)]


def _date_grouped_batches(
    symbols: list[str],
    size: int,
    default_start_date: str,
    symbol_start_dates: dict[str, str],
) -> list[tuple[str, list[str]]]:
    """Split symbols into batches grouped by their incremental start date."""
    grouped: dict[str, list[str]] = {}
    for symbol in symbols:
        start = str(symbol_start_dates.get(_to_ts_code(symbol), default_start_date))
        grouped.setdefault(start, []).append(symbol)
    batches: list[tuple[str, list[str]]] = []
    for start in sorted(grouped):
        for chunk in _chunks(grouped[start], size):
            batches.append((start, chunk))
    return batches


def _record_client_failure(client: StockDataSource, symbols: list[str], stage: str, message: str) -> None:
    """Record fetch-level failures on clients that expose failure_records."""
    records = getattr(client, "failure_records", None)
    if not isinstance(records, list):
        return
    for symbol in symbols:
        records.append(
            {
                "symbol": _to_ts_code(symbol),
                "provider": "unknown",
                "failed_stage": stage,
                "error_message": message,
            }
        )


def _record_client_enrichment(client: StockDataSource, symbols: list[str], stage: str, message: str) -> None:
    """Record optional enrichment warnings on clients that expose enrichment_records."""
    records = getattr(client, "enrichment_records", None)
    if not isinstance(records, list):
        return
    for symbol in symbols:
        records.append(
            {
                "symbol": _to_ts_code(symbol) if symbol != "ALL" else "ALL",
                "provider": "akshare",
                "failed_stage": stage,
                "error_message": message,
            }
        )


def _batch_summary(
    provider_name: str,
    sample_symbols: list[str],
    frames: dict[str, pd.DataFrame],
    client: StockDataSource,
    skipped_symbols: list[str] | None = None,
    planned_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Return batch update success and failure summary."""
    requested_ts_codes = [_to_ts_code(symbol) for symbol in sample_symbols]
    skipped_set = {_to_ts_code(symbol) for symbol in (skipped_symbols or [])}
    planned_set = {_to_ts_code(symbol) for symbol in (planned_symbols if planned_symbols is not None else sample_symbols)}
    daily_price = frames.get("daily_price", pd.DataFrame())
    if daily_price.empty or "ts_code" not in daily_price.columns:
        successful = set()
    else:
        successful = set(daily_price["ts_code"].dropna().astype(str).unique())
    completed = successful.union(skipped_set)
    deferred_symbols = [
        symbol
        for symbol in requested_ts_codes
        if symbol not in skipped_set and symbol not in planned_set
    ]
    empty_symbols = [symbol for symbol in requested_ts_codes if symbol in planned_set and symbol not in completed]
    failure_records = [
        item
        for item in _dedupe_failure_records(getattr(client, "failure_records", []))
        if not _is_enrichment_stage(item.get("failed_stage", ""))
    ]
    recorded_symbols = {item["symbol"] for item in failure_records}
    for symbol in empty_symbols:
        if symbol not in recorded_symbols:
            failure_records.append(
                {
                    "symbol": symbol,
                    "provider": provider_name,
                    "failed_stage": "daily_price",
                    "error_message": "no daily_price rows returned",
                }
            )
    success_count = len(successful.intersection(requested_ts_codes))
    skipped_count = len(skipped_set.intersection(requested_ts_codes))
    total = len(requested_ts_codes)
    failed_count = len(empty_symbols)
    return {
        "total_symbols": total,
        "planned_symbols": len(planned_set),
        "success_symbols": success_count,
        "skipped_symbols": skipped_count,
        "deferred_symbols": len(deferred_symbols),
        "failed_symbols": failed_count,
        "success_rate": (success_count / total) if total else 0.0,
        "completion_rate": ((success_count + skipped_count) / total) if total else 0.0,
        "empty_data_symbols": empty_symbols,
        "deferred_data_symbols": deferred_symbols,
        "failure_records": failure_records,
        "is_full_update": len(requested_ts_codes) >= 100 and provider_name == "akshare",
        "effective_batch_size": None,
        "effective_max_retries": None,
        "full_update_lookback_days": None,
        "full_update_resume": None,
    }


def _failure_records_to_rows(
    failure_records: list[dict[str, Any]],
    provider_name: str,
    target_end_date: str,
    existing: pd.DataFrame,
) -> pd.DataFrame:
    """Convert in-memory failures to persistent update_failures rows."""
    if not failure_records:
        return pd.DataFrame(columns=TABLE_COLUMNS["update_failures"])
    now = pd.Timestamp.now(tz="UTC").to_pydatetime().replace(tzinfo=None)
    existing_counts: dict[tuple[str, str, str], int] = {}
    existing_first_seen: dict[tuple[str, str, str], Any] = {}
    if not existing.empty and {"ts_code", "table_name", "target_end_date"}.issubset(existing.columns):
        for row in existing.to_dict("records"):
            key = (str(row.get("ts_code")), str(row.get("table_name")), str(row.get("target_end_date")))
            existing_counts[key] = int(row.get("attempt_count") or 0)
            existing_first_seen[key] = row.get("first_seen_at")
    rows: list[dict[str, Any]] = []
    for item in failure_records:
        ts_code = _to_ts_code(str(item.get("symbol", "")))
        stage = str(item.get("failed_stage", "daily_price"))
        table_name = stage.split(":", 1)[0] if ":" in stage else stage
        if table_name not in {"daily_price", "daily_basic", "adj_factor"}:
            table_name = "daily_price"
        message = str(item.get("error_message", ""))
        status = "empty_data" if "no daily_price rows returned" in message else "temporarily_unavailable"
        key = (ts_code, table_name, str(target_end_date))
        rows.append(
            {
                "ts_code": ts_code,
                "provider": str(item.get("provider") or provider_name),
                "table_name": table_name,
                "target_end_date": str(target_end_date),
                "status": status,
                "failed_stage": stage,
                "error_message": message,
                "attempt_count": existing_counts.get(key, 0) + 1,
                "first_seen_at": existing_first_seen.get(key) or now,
                "last_seen_at": now,
            }
        )
    return pd.DataFrame(rows, columns=TABLE_COLUMNS["update_failures"])


def _enrichment_summary(
    sample_symbols: list[str],
    frames: dict[str, pd.DataFrame],
    client: StockDataSource,
    settings: Settings,
    provider_name: str,
) -> dict[str, Any]:
    """Return optional enrichment status without affecting main update status."""
    events = _dedupe_failure_records(getattr(client, "enrichment_records", []))
    warnings = [item for item in events if not item.get("failed_stage", "").endswith("_success")]
    requested_ts_codes = [_to_ts_code(symbol) for symbol in sample_symbols]
    stock_basic = frames.get("stock_basic", pd.DataFrame())
    daily_basic = frames.get("daily_basic", pd.DataFrame())
    basic_success = _symbols_with_any_value(stock_basic, ["industry", "list_date"])
    valuation_success = _symbols_with_any_value(daily_basic, ["pe", "pb", "total_mv", "circ_mv"])
    basic_missing_symbols = set(requested_ts_codes) - basic_success
    basic_warning_symbols = _warning_symbols(warnings, "stock_basic_preset_fallback_missing").union(basic_missing_symbols)
    valuation_warning_symbols = _warning_symbols(warnings, "daily_basic")
    if not getattr(settings, "enable_real_basic_enrichment", True):
        basic_status = "skipped"
    else:
        basic_status = _enrichment_status(
            len(basic_success.intersection(requested_ts_codes)),
            len(basic_warning_symbols.intersection(requested_ts_codes)),
            len(requested_ts_codes),
        )
    if not _should_run_valuation_enrichment(settings, provider_name):
        valuation_status = "skipped"
    elif not valuation_success and any(item["failed_stage"] == "daily_basic_valuation_enrichment_unavailable" for item in warnings):
        valuation_status = "skipped"
    else:
        valuation_status = _enrichment_status(
            len(valuation_success.intersection(requested_ts_codes)),
            len(valuation_warning_symbols.intersection(requested_ts_codes)),
            len(requested_ts_codes),
        )
    return {
        "enrichment_summary": {
            "basic_status": basic_status,
            "basic_success_symbols": len(basic_success.intersection(requested_ts_codes)),
            "basic_failed_symbols": len(basic_warning_symbols.intersection(requested_ts_codes)),
            "basic_preset_success_symbols": len(_warning_symbols(events, "stock_basic_preset_fallback_success").intersection(requested_ts_codes)),
            "valuation_status": valuation_status,
            "valuation_success_symbols": len(valuation_success.intersection(requested_ts_codes)),
            "valuation_failed_symbols": len(valuation_warning_symbols.intersection(requested_ts_codes)),
            "warnings": warnings,
            "events": events,
        },
        "enrichment_warnings": warnings,
        "enrichment_events": events,
    }


def _symbols_with_any_value(df: pd.DataFrame, columns: list[str]) -> set[str]:
    """Return symbols that have at least one non-empty value in any requested column."""
    if df.empty or "ts_code" not in df.columns:
        return set()
    available = [column for column in columns if column in df.columns]
    if not available:
        return set()
    values = df[available].apply(lambda column: column.map(lambda value: not _is_missing(value)))
    mask = values.any(axis=1)
    return set(df.loc[mask, "ts_code"].dropna().astype(str).unique())


def _warning_symbols(warnings: list[dict[str, str]], prefix: str) -> set[str]:
    """Return warning symbols whose stage starts with a prefix."""
    return {
        item["symbol"]
        for item in warnings
        if item.get("symbol") != "ALL" and item.get("failed_stage", "").startswith(prefix)
    }


def _enrichment_status(success_count: int, failed_count: int, total_count: int) -> str:
    """Return optional enrichment status."""
    if total_count == 0:
        return "skipped"
    if success_count == 0 and failed_count == 0:
        return "skipped"
    if success_count == 0 and failed_count > 0:
        return "failed"
    if failed_count > 0:
        return "partial_success"
    return "success"


def _is_enrichment_stage(stage: str) -> bool:
    """Return whether a failure stage belongs to optional enrichment."""
    return "enrichment" in str(stage)


def _status_from_batch_summary(summary: dict[str, Any]) -> str:
    """Return update status from symbol-level coverage."""
    completed = summary.get("success_symbols", 0) + summary.get("skipped_symbols", 0)
    if summary["total_symbols"] and completed == 0:
        return "failed"
    if summary["failed_symbols"] > 0:
        return "partial_success"
    return "success"


def _dedupe_failure_records(records: Any) -> list[dict[str, str]]:
    """Return normalized unique failure records."""
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    if not isinstance(records, list):
        return result
    for item in records:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", ""))
        normalized = {
            "symbol": "ALL" if symbol == "ALL" else _to_ts_code(symbol),
            "provider": str(item.get("provider", "unknown")),
            "failed_stage": str(item.get("failed_stage", "unknown")),
            "error_message": str(item.get("error_message", "")),
        }
        key = (normalized["symbol"], normalized["failed_stage"])
        if key not in seen:
            result.append(normalized)
            seen.add(key)
    return result


def _is_missing(value: Any) -> bool:
    """Return whether a scalar should be treated as missing."""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


def _sample_symbols_for_provider(settings: Settings, provider_name: str) -> list[str]:
    """Return provider-specific sample symbols."""
    if provider_name == "akshare":
        if _use_full_universe(settings, provider_name):
            return []
        return list(settings.akshare_symbols)
    if not list(settings.sample_symbols):
        return [_to_ts_code(symbol) for symbol in get_universe_preset(getattr(settings, "real_universe_preset", "mini"))]
    return list(settings.sample_symbols)


def _to_ts_code(symbol: str) -> str:
    """Normalize either raw symbols or project ts_code values to ts_code."""
    clean = str(symbol).strip()
    if "." in clean:
        return clean
    suffix = "SH" if clean.startswith("6") else "SZ"
    return f"{clean}.{suffix}"


if __name__ == "__main__":
    main()
