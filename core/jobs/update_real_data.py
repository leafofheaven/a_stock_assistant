"""Minimal real data ingestion command for DuckDB."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.data_sources.base import DataSourceError, StockDataSource
from core.data_sources.provider import select_data_provider
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


TABLE_ORDER = [
    "stock_basic",
    "trade_calendar",
    "daily_price",
    "daily_basic",
    "adj_factor",
]


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
        }

    sample_symbols = _sample_symbols_for_provider(settings, provider_name)
    resolved_store = store or DuckDBStore(settings.duckdb_path)

    try:
        resolved_store.initialize()
        frames = {
            "stock_basic": _filter_stock_basic(client.get_stock_basic(), sample_symbols),
            "trade_calendar": _filter_date_range(
                client.get_trade_calendar(),
                "cal_date",
                start_date,
                end_date,
            ),
            "daily_price": client.get_daily_price(start_date, end_date, sample_symbols),
            "daily_basic": client.get_daily_basic(start_date, end_date, sample_symbols),
            "adj_factor": client.get_adj_factor(start_date, end_date, sample_symbols),
        }
        written_rows = {
            table_name: resolved_store.upsert_dataframe(table_name, frame)
            for table_name, frame in frames.items()
        }
    except (DataSourceError, DuckDBStoreError) as exc:
        return {
            "status": "failed",
            "message": f"真实数据更新失败：{exc}",
            "data_source": provider_name,
            "start_date": start_date,
            "end_date": end_date,
            "sample_symbols": sample_symbols,
            "written_rows": {table_name: 0 for table_name in TABLE_ORDER},
        }

    return {
        "status": "success",
        "message": f"{message_prefix} 真实 {provider_name} 数据更新完成。".strip(),
        "data_source": provider_name,
        "start_date": start_date,
        "end_date": end_date,
        "sample_symbols": sample_symbols,
        "written_rows": written_rows,
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
    print("- 写入行数:")
    for table_name, row_count in result["written_rows"].items():
        print(f"  {table_name}: {row_count}")


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


def _sample_symbols_for_provider(settings: Settings, provider_name: str) -> list[str]:
    """Return provider-specific sample symbols."""
    if provider_name == "akshare":
        return list(settings.akshare_symbols)
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
