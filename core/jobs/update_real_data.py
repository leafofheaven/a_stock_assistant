"""Minimal real data ingestion command for DuckDB."""

from __future__ import annotations

from datetime import date
import time
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.data_sources.base import DataSourceError, StockDataSource
from core.data_sources.provider import select_data_provider
from core.data_sources.universe_presets import get_universe_preset, to_akshare_symbol
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


TABLE_ORDER = [
    "stock_basic",
    "trade_calendar",
    "daily_price",
    "daily_basic",
    "adj_factor",
]

TABLE_COLUMNS = {
    "stock_basic": ["ts_code", "symbol", "name", "area", "industry", "market", "list_date", "delist_date", "is_hs"],
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
        )

    result = _run_provider_update(
        provider_name=selection.provider_name,
        client=selection.primary,
        store=store,
        settings=resolved_settings,
        start_date=start_date,
        end_date=end_date,
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

    try:
        resolved_store.initialize()
        before_rows = _table_row_counts(resolved_store)
        stock_basic = _filter_stock_basic(client.get_stock_basic(), sample_symbols)
        if (
            provider_name == "akshare"
            and getattr(settings, "enable_real_basic_enrichment", True)
            and hasattr(client, "enrich_stock_basic")
        ):
            try:
                stock_basic = client.enrich_stock_basic(stock_basic, sample_symbols)  # type: ignore[attr-defined]
            except Exception:
                pass
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
            ),
            "daily_basic": _fetch_symbol_table_in_batches(
                client.get_daily_basic,
                client,
                start_date,
                end_date,
                sample_symbols,
                settings,
            ),
            "adj_factor": _fetch_symbol_table_in_batches(
                client.get_adj_factor,
                client,
                start_date,
                end_date,
                sample_symbols,
                settings,
            ),
        }
        normalized_frames = {
            table_name: _ensure_table_columns(table_name, frame)
            for table_name, frame in frames.items()
        }
        empty_tables = [
            table_name
            for table_name, frame in normalized_frames.items()
            if frame.empty
        ]
        batch_summary = _batch_summary(provider_name, sample_symbols, normalized_frames, client)
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
                "next_steps": ["检查 AKShare 网络、版本或样本股票配置后重试。"],
            }
        written_rows = {
            table_name: resolved_store.upsert_dataframe(table_name, frame)
            for table_name, frame in normalized_frames.items()
        }
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
    status = _status_from_batch_summary(batch_summary)
    return {
        "status": status,
        "message": f"{message_prefix} 真实 {provider_name} 数据更新完成。".strip(),
        "data_source": provider_name,
        "start_date": start_date,
        "end_date": end_date,
        "sample_symbols": sample_symbols,
        "written_rows": written_rows,
        "before_rows": before_rows,
        "after_rows": after_rows,
        "empty_tables": empty_tables,
        **batch_summary,
        "next_steps": [
            "python -m core.jobs.diagnose_real_data",
            "python -m core.jobs.diagnose_update_batch",
            "python -m core.jobs.run_daily_selection",
        ],
    }


def main() -> None:
    """Run the minimal real data update and print a concise summary."""
    result = update_real_data()
    print("真实数据更新摘要")
    print(f"- 状态: {result['status']}")
    print(f"- 说明: {result['message']}")
    print(f"- 数据来源: {result['data_source']}")
    print(f"- 日期范围: {result['start_date']} 至 {result['end_date']}")
    print(f"- 样本股票: {', '.join(result['sample_symbols']) or '未配置'}")
    if "total_symbols" in result:
        print(
            f"- 批量统计: 总股票数 {result['total_symbols']}，成功 {result['success_symbols']}，"
            f"失败 {result['failed_symbols']}，成功率 {result['success_rate']:.2%}"
        )
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
    if df.empty or not symbols or "ts_code" not in df.columns:
        return df
    ts_codes = {_to_ts_code(symbol) for symbol in symbols}
    return df[df["ts_code"].isin(ts_codes)].reset_index(drop=True)


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
) -> pd.DataFrame:
    """Fetch a symbol table in configured batches with simple retries."""
    if not symbols:
        return fetcher(start_date, end_date, symbols)

    frames: list[pd.DataFrame] = []
    batch_size = max(1, int(getattr(settings, "real_batch_size", 10) or 10))
    max_retries = max(1, int(getattr(settings, "real_max_retries", 1) or 1))
    sleep_seconds = max(0.0, float(getattr(settings, "real_batch_sleep_seconds", 0.0) or 0.0))
    batches = list(_chunks(symbols, batch_size))
    for batch_index, batch in enumerate(batches):
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
    failure_records = _dedupe_failure_records(getattr(client, "failure_records", []))
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
        normalized = {
            "symbol": _to_ts_code(str(item.get("symbol", ""))),
            "provider": str(item.get("provider", "unknown")),
            "failed_stage": str(item.get("failed_stage", "unknown")),
            "error_message": str(item.get("error_message", "")),
        }
        key = (normalized["symbol"], normalized["failed_stage"])
        if key not in seen:
            result.append(normalized)
            seen.add(key)
    return result


def _sample_symbols_for_provider(settings: Settings, provider_name: str) -> list[str]:
    """Return provider-specific sample symbols."""
    if provider_name == "akshare":
        return list(settings.akshare_symbols)
    if not list(settings.sample_symbols):
        return [_to_ts_code(symbol) for symbol in get_universe_preset(settings.real_universe_preset)]
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
