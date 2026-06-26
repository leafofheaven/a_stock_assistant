"""Minimal real Tushare data ingestion command for DuckDB."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.data_sources.base import DataSourceError
from core.data_sources.tushare_client import TushareClient
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
    client: TushareClient | None = None,
) -> dict[str, Any]:
    """Fetch a small configured Tushare sample and upsert it into DuckDB.

    The function is intentionally small-scope: it only downloads the configured
    sample symbols and date range. Tests should inject ``client`` and ``store``;
    the default path performs the real Tushare call only when this command is
    invoked manually and ``TUSHARE_TOKEN`` is configured.
    """
    resolved_settings = settings or get_settings()
    sample_symbols = list(resolved_settings.sample_symbols)
    start_date = resolved_settings.real_data_start_date
    end_date = resolved_settings.real_data_end_date or date.today().strftime("%Y%m%d")

    if not resolved_settings.tushare_token and client is None:
        return {
            "status": "skipped",
            "message": "TUSHARE_TOKEN 为空，跳过真实 Tushare 数据更新；sample smoke test 仍可运行。",
            "data_source": "无真实数据",
            "start_date": start_date,
            "end_date": end_date,
            "sample_symbols": sample_symbols,
            "written_rows": {table_name: 0 for table_name in TABLE_ORDER},
        }

    resolved_client = client or TushareClient(token=resolved_settings.tushare_token)
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)

    try:
        resolved_store.initialize()
        frames = {
            "stock_basic": _filter_stock_basic(resolved_client.get_stock_basic(), sample_symbols),
            "trade_calendar": _filter_date_range(
                resolved_client.get_trade_calendar(),
                "cal_date",
                start_date,
                end_date,
            ),
            "daily_price": resolved_client.get_daily_price(start_date, end_date, sample_symbols),
            "daily_basic": resolved_client.get_daily_basic(start_date, end_date, sample_symbols),
            "adj_factor": resolved_client.get_adj_factor(start_date, end_date, sample_symbols),
        }
        written_rows = {
            table_name: resolved_store.upsert_dataframe(table_name, frame)
            for table_name, frame in frames.items()
        }
    except (DataSourceError, DuckDBStoreError) as exc:
        return {
            "status": "failed",
            "message": f"真实数据更新失败：{exc}",
            "data_source": "tushare",
            "start_date": start_date,
            "end_date": end_date,
            "sample_symbols": sample_symbols,
            "written_rows": {table_name: 0 for table_name in TABLE_ORDER},
        }

    return {
        "status": "success",
        "message": "真实 Tushare 数据更新完成。",
        "data_source": "tushare",
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
    return df[df["ts_code"].isin(symbols)].reset_index(drop=True)


def _filter_date_range(df: pd.DataFrame, column: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Filter a DataFrame by inclusive YYYYMMDD date strings."""
    if df.empty or column not in df.columns:
        return df
    values = df[column].astype(str)
    return df[(values >= start_date) & (values <= end_date)].reset_index(drop=True)


if __name__ == "__main__":
    main()
