"""Real data diagnostics for the local DuckDB store."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


CORE_TABLES = ["stock_basic", "trade_calendar", "daily_price", "daily_basic", "adj_factor"]
REQUIRED_FIELDS = {
    "stock_basic": ["ts_code", "name", "industry", "list_date"],
    "trade_calendar": ["exchange", "cal_date", "is_open"],
    "daily_price": ["ts_code", "trade_date", "close", "amount"],
    "daily_basic": ["ts_code", "trade_date", "turnover_rate", "pe", "pb"],
    "adj_factor": ["ts_code", "trade_date", "adj_factor"],
}


def diagnose_real_data(
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Inspect local DuckDB data readiness for the real-data workflow."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    sample_symbols = _sample_symbols(resolved_settings)
    empty_tables = {table_name: pd.DataFrame() for table_name in CORE_TABLES}

    if not resolved_store.db_path.exists():
        return _build_result(
            settings=resolved_settings,
            store=resolved_store,
            tables=empty_tables,
            sample_symbols=sample_symbols,
            reasons=["DuckDB 文件不存在，请先运行 python -m core.jobs.update_real_data。"],
        )

    tables: dict[str, pd.DataFrame] = {}
    reasons: list[str] = []
    for table_name in CORE_TABLES:
        try:
            tables[table_name] = resolved_store.read_table(table_name)
        except DuckDBStoreError as exc:
            tables[table_name] = pd.DataFrame()
            reasons.append(f"{table_name} 读取失败：{exc}")

    return _build_result(
        settings=resolved_settings,
        store=resolved_store,
        tables=tables,
        sample_symbols=sample_symbols,
        reasons=reasons,
    )


def main() -> None:
    """Print real data diagnostics."""
    result = diagnose_real_data()
    print("真实数据诊断摘要")
    print(f"- 当前 DATA_PROVIDER: {result['data_provider']}")
    print(f"- DuckDB 路径: {result['duckdb_path']}")
    for table_name, row_count in result["table_rows"].items():
        print(f"- {table_name} 行数: {row_count}")
    print(f"- 最新行情日期: {result['latest_price_date'] or '暂无'}")
    print("- 样本股票覆盖:")
    for symbol, has_data in result["sample_symbol_coverage"].items():
        print(f"  {symbol}: {'有数据' if has_data else '缺数据'}")
    print("- 缺失字段检查:")
    for table_name, missing in result["missing_fields"].items():
        print(f"  {table_name}: {', '.join(missing) if missing else '通过'}")
    print(f"- 是否足够运行 run_daily_selection: {'是' if result['is_ready_for_selection'] else '否'}")
    if result["reasons"]:
        print("- 不足原因:")
        for reason in result["reasons"]:
            print(f"  {reason}")
    print("- 下一步建议:")
    for step in result["next_steps"]:
        print(f"  {step}")


def _build_result(
    settings: Settings,
    store: DuckDBStore,
    tables: dict[str, pd.DataFrame],
    sample_symbols: list[str],
    reasons: list[str],
) -> dict[str, Any]:
    """Build a structured diagnostic result."""
    table_rows = {table_name: int(len(tables.get(table_name, pd.DataFrame()))) for table_name in CORE_TABLES}
    missing_fields = {
        table_name: [
            column
            for column in REQUIRED_FIELDS[table_name]
            if column not in tables.get(table_name, pd.DataFrame()).columns
        ]
        for table_name in CORE_TABLES
    }
    daily_price = tables.get("daily_price", pd.DataFrame())
    latest_price_date = _latest_date(daily_price, "trade_date")
    coverage = _sample_symbol_coverage(daily_price, sample_symbols)
    computed_reasons = list(reasons)
    for table_name in CORE_TABLES:
        if table_rows[table_name] == 0:
            computed_reasons.append(f"{table_name} 无数据。")
        if missing_fields[table_name]:
            computed_reasons.append(f"{table_name} 缺失字段：{', '.join(missing_fields[table_name])}。")
    missing_symbols = [symbol for symbol, has_data in coverage.items() if not has_data]
    if missing_symbols:
        computed_reasons.append(f"样本股票缺少行情数据：{', '.join(missing_symbols)}。")

    is_ready = not computed_reasons
    return {
        "data_provider": settings.data_provider,
        "duckdb_path": str(store.db_path),
        "table_rows": table_rows,
        "latest_price_date": latest_price_date,
        "sample_symbol_coverage": coverage,
        "missing_fields": missing_fields,
        "is_ready_for_selection": is_ready,
        "reasons": computed_reasons,
        "next_steps": _next_steps(is_ready),
    }


def _sample_symbols(settings: Settings) -> list[str]:
    """Return provider-specific sample symbols normalized to ts_code."""
    if settings.data_provider == "akshare":
        return [_to_ts_code(symbol) for symbol in settings.akshare_symbols]
    return [_to_ts_code(symbol) for symbol in settings.sample_symbols]


def _sample_symbol_coverage(daily_price: pd.DataFrame, sample_symbols: list[str]) -> dict[str, bool]:
    """Return whether each sample symbol exists in daily_price."""
    if daily_price.empty or "ts_code" not in daily_price.columns:
        return {symbol: False for symbol in sample_symbols}
    available = set(daily_price["ts_code"].dropna().astype(str))
    return {symbol: symbol in available for symbol in sample_symbols}


def _latest_date(df: pd.DataFrame, column: str) -> str | None:
    """Return latest date string from a DataFrame."""
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    return None if values.empty else str(values.max())


def _next_steps(is_ready: bool) -> list[str]:
    """Return suggested next commands for the current diagnostic state."""
    if is_ready:
        return ["python -m core.jobs.run_daily_selection", "streamlit run web/streamlit_app.py"]
    return ["python -m core.jobs.update_real_data", "python -m core.jobs.diagnose_real_data"]


def _to_ts_code(symbol: str) -> str:
    """Normalize six-digit symbols or project ts_code values to ts_code."""
    clean = str(symbol).strip()
    if "." in clean:
        return clean
    suffix = "SH" if clean.startswith("6") else "SZ"
    return f"{clean}.{suffix}"


if __name__ == "__main__":
    main()
