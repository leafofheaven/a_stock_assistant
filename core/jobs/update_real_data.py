"""Minimal real data ingestion command for DuckDB."""

from __future__ import annotations

from datetime import date
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
    resolved_store = store or DuckDBStore(settings.duckdb_path)
    emit_progress(
        progress,
        step="update_real_data",
        current=provider_name,
        message=f"开始更新 {len(sample_symbols)} 只样本股票，日期 {start_date}-{end_date}。",
    )

    try:
        resolved_store.initialize()
        before_rows = _table_row_counts(resolved_store)
        emit_progress(progress, step="stock_basic", current="stock_basic", message="读取股票基础信息。")
        raw_stock_basic = client.get_stock_basic()
        full_universe_summary: dict[str, Any] = {}
        if _use_full_universe(settings, provider_name):
            full_universe_summary = resolve_full_a_share_universe(
                raw_stock_basic,
                include_bse=getattr(settings, "include_bse", False),
            )
            stock_basic = full_universe_summary["stock_basic"]
            sample_symbols = list(full_universe_summary["symbols"])
            emit_progress(
                progress,
                step="stock_basic",
                current="full",
                success=len(sample_symbols),
                message=f"已获取 {FULL_UNIVERSE_LABEL} 基础列表 {len(sample_symbols)} 只。",
            )
        else:
            stock_basic = _filter_stock_basic(raw_stock_basic, sample_symbols)
        if provider_name == "akshare":
            stock_basic = _merge_existing_stock_basic(stock_basic, resolved_store)
        if (
            provider_name == "akshare"
            and getattr(settings, "enable_real_basic_enrichment", True)
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
        if provider_name == "akshare" and getattr(settings, "enable_real_basic_enrichment", True):
            stock_basic = _apply_local_basic_info_presets(client, stock_basic)
        emit_progress(progress, step="trade_calendar", current="trade_calendar", message="读取交易日历。")
        frames = {
            "stock_basic": stock_basic,
            "trade_calendar": _filter_date_range(
                client.get_trade_calendar(),
                "cal_date",
                start_date,
                end_date,
            ),
            "daily_price": _fetch_symbol_table_in_batches(
                client.get_daily_price,
                client,
                start_date,
                end_date,
                sample_symbols,
                settings,
                table_name="daily_price",
                progress=progress,
            ),
            "daily_basic": _fetch_symbol_table_in_batches(
                client.get_daily_basic,
                client,
                start_date,
                end_date,
                sample_symbols,
                settings,
                table_name="daily_basic",
                progress=progress,
            ),
            "adj_factor": _fetch_symbol_table_in_batches(
                client.get_adj_factor,
                client,
                start_date,
                end_date,
                sample_symbols,
                settings,
                table_name="adj_factor",
                progress=progress,
            ),
        }
        normalized_frames = {
            table_name: _ensure_table_columns(table_name, frame)
            for table_name, frame in frames.items()
        }
        if (
            provider_name == "akshare"
            and getattr(settings, "enable_real_valuation_enrichment", True)
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
        batch_summary = _batch_summary(provider_name, sample_symbols, normalized_frames, client)
        enrichment_summary = _enrichment_summary(sample_symbols, normalized_frames, client, settings)
        if provider_name == "akshare" and normalized_frames["daily_price"].empty and sample_symbols:
            return {
                "status": "failed",
                "message": "真实数据更新失败：AKShare 所有样本股票日线行情均为空或失败。",
                "data_source": provider_name,
                "start_date": start_date,
                "end_date": end_date,
                "sample_symbols": sample_symbols,
                "written_rows": {table_name: 0 for table_name in TABLE_ORDER},
                "before_rows": before_rows,
                "after_rows": before_rows,
                "empty_tables": empty_tables,
                **batch_summary,
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

    batch_summary = _batch_summary(provider_name, sample_symbols, normalized_frames, client)
    enrichment_summary = _enrichment_summary(sample_symbols, normalized_frames, client, settings)
    status = _status_from_batch_summary(batch_summary)
    emit_progress(
        progress,
        step="update_real_data",
        current=provider_name,
        success=batch_summary.get("success_symbols", 0),
        failed=batch_summary.get("failed_symbols", 0),
        skipped=len(empty_tables),
        message=f"真实数据更新完成，状态 {status}。",
    )
    return {
        "status": status,
        "message": f"{message_prefix} 真实 {provider_name} 数据更新完成。".strip(),
        "data_source": provider_name,
            "universe_preset": getattr(settings, "real_universe_preset", "mini"),
            "universe_label": FULL_UNIVERSE_LABEL if _use_full_universe(settings, provider_name) else getattr(settings, "real_universe_preset", "mini"),
            "full_universe_summary": _jsonable_universe_summary(full_universe_summary),
            "start_date": start_date,
        "end_date": end_date,
        "sample_symbols": sample_symbols,
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
    print(f"- 样本股票: {', '.join(result['sample_symbols']) or '未配置'}")
    if "total_symbols" in result:
        print(f"- 主行情更新: {result['status']}")
        print(
            f"- 主行情统计: 总股票数 {result['total_symbols']}，成功 {result['success_symbols']}，"
            f"失败 {result['failed_symbols']}，成功率 {result['success_rate']:.2%}"
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
        print(f"- 空数据股票: {', '.join(result['empty_data_symbols'])}")
    if result.get("failure_records"):
        print("- 失败股票列表:")
        for item in result["failure_records"]:
            print(
                f"  {item['symbol']} provider={item['provider']} "
                f"stage={item['failed_stage']} error={item['error_message']}"
            )
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


def _use_full_universe(settings: Settings, provider_name: str) -> bool:
    """Return whether provider update should discover the full HS A-share universe."""
    if provider_name != "akshare":
        return False
    # AKSHARE_SAMPLE_SYMBOLS stays higher priority than REAL_UNIVERSE_PRESET=full.
    if [symbol.strip() for symbol in getattr(settings, "akshare_sample_symbols", "").split(",") if symbol.strip()]:
        return False
    return is_full_universe_preset(getattr(settings, "real_universe_preset", "mini"))


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
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    """Fetch a symbol table in configured batches with simple retries."""
    if not symbols:
        return fetcher(start_date, end_date, symbols)

    frames: list[pd.DataFrame] = []
    batch_size = max(1, int(getattr(settings, "real_batch_size", 10) or 10))
    max_retries = max(1, int(getattr(settings, "real_max_retries", 1) or 1))
    sleep_seconds = max(0.0, float(getattr(settings, "real_batch_sleep_seconds", 0.0) or 0.0))
    batches = list(_chunks(symbols, batch_size))
    success_symbols: set[str] = set()
    failed_symbols: set[str] = set()
    for batch_index, batch in enumerate(batches):
        current = ",".join(_to_ts_code(symbol) for symbol in batch)
        emit_progress(
            progress,
            step=table_name,
            current=current,
            success=len(success_symbols),
            failed=len(failed_symbols),
            skipped=0,
            message=f"开始处理第 {batch_index + 1}/{len(batches)} 批。",
        )
        frame = pd.DataFrame()
        for attempt in range(max_retries):
            try:
                frame = fetcher(start_date, end_date, batch)
                break
            except DataSourceError as exc:
                _record_client_failure(client, batch, fetcher.__name__, str(exc))
                if attempt + 1 >= max_retries:
                    frame = pd.DataFrame()
        if not frame.empty:
            frames.append(frame)
            if "ts_code" in frame.columns:
                success_symbols.update(frame["ts_code"].dropna().astype(str).unique())
        else:
            failed_symbols.update(_to_ts_code(symbol) for symbol in batch)
        emit_progress(
            progress,
            step=table_name,
            current=current,
            success=len(success_symbols),
            failed=len(failed_symbols),
            skipped=0,
            message=f"完成第 {batch_index + 1}/{len(batches)} 批，返回行数 {len(frame)}。",
        )
        if sleep_seconds and batch_index < len(batches) - 1:
            time.sleep(sleep_seconds)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _chunks(symbols: list[str], size: int) -> list[list[str]]:
    """Split symbols into fixed-size chunks."""
    return [symbols[index : index + size] for index in range(0, len(symbols), size)]


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
) -> dict[str, Any]:
    """Return batch update success and failure summary."""
    requested_ts_codes = [_to_ts_code(symbol) for symbol in sample_symbols]
    daily_price = frames.get("daily_price", pd.DataFrame())
    if daily_price.empty or "ts_code" not in daily_price.columns:
        successful = set()
    else:
        successful = set(daily_price["ts_code"].dropna().astype(str).unique())
    empty_symbols = [symbol for symbol in requested_ts_codes if symbol not in successful]
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
    total = len(requested_ts_codes)
    failed_count = max(total - success_count, 0)
    return {
        "total_symbols": total,
        "success_symbols": success_count,
        "failed_symbols": failed_count,
        "success_rate": (success_count / total) if total else 0.0,
        "empty_data_symbols": empty_symbols,
        "failure_records": failure_records,
    }


def _enrichment_summary(
    sample_symbols: list[str],
    frames: dict[str, pd.DataFrame],
    client: StockDataSource,
    settings: Settings,
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
    if not getattr(settings, "enable_real_valuation_enrichment", True):
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
    if summary["total_symbols"] and summary["success_symbols"] == 0:
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
