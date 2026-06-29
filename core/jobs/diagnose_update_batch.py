"""Batch update coverage diagnostics for configured real-data universes."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.data_sources.akshare_client import AKShareClient
from core.data_sources.base import StockDataSource
from core.data_sources.real_universe import is_full_universe_preset, resolve_full_a_share_universe
from core.data_sources.universe_presets import get_universe_preset, to_ts_code
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


CORE_TABLES = ["stock_basic", "daily_price", "daily_basic", "adj_factor"]
FULL_UNIVERSE_PENDING = "__FULL_UNIVERSE_PENDING__"


def diagnose_update_batch(
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    client: StockDataSource | None = None,
) -> dict[str, Any]:
    """Diagnose configured universe coverage in local DuckDB tables."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    configured_symbols, sample_source = _configured_symbols(resolved_settings)
    empty_tables = {table_name: pd.DataFrame() for table_name in CORE_TABLES}

    if not resolved_store.db_path.exists():
        universe_summary = {}
        if sample_source == "REAL_UNIVERSE_PRESET=full":
            universe_summary = _resolve_full_universe_for_diagnosis(
                settings=resolved_settings,
                stock_basic=pd.DataFrame(),
                client=client,
            )
            configured_symbols = list(universe_summary.get("ts_codes", []))
        return _build_result(
            settings=resolved_settings,
            store=resolved_store,
            tables=empty_tables,
            configured_symbols=configured_symbols,
            sample_source=sample_source,
            reasons=[
                "DuckDB 文件不存在，请先运行 python -m core.jobs.update_real_data。",
                *list(universe_summary.get("warnings", [])),
            ],
            universe_summary=universe_summary,
        )

    tables: dict[str, pd.DataFrame] = {}
    reasons: list[str] = []
    for table_name in CORE_TABLES:
        try:
            tables[table_name] = resolved_store.read_table(table_name)
        except DuckDBStoreError as exc:
            tables[table_name] = pd.DataFrame()
            reasons.append(f"{table_name} 读取失败：{exc}")

    universe_summary: dict[str, Any] = {}
    if sample_source == "REAL_UNIVERSE_PRESET=full":
        universe_summary = _resolve_full_universe_for_diagnosis(
            settings=resolved_settings,
            stock_basic=tables.get("stock_basic", pd.DataFrame()),
            client=client,
        )
        configured_symbols = list(universe_summary.get("ts_codes", []))
        reasons.extend(universe_summary.get("warnings", []))
    return _build_result(
        settings=resolved_settings,
        store=resolved_store,
        tables=tables,
        configured_symbols=configured_symbols,
        sample_source=sample_source,
        reasons=reasons,
        universe_summary=universe_summary,
    )


def main() -> None:
    """Print batch update diagnostics."""
    result = diagnose_update_batch()
    print("真实股票批量更新诊断摘要")
    print(f"- 当前 DATA_PROVIDER: {result['data_provider']}")
    print(f"- DuckDB 路径: {result['duckdb_path']}")
    print(f"- 当前股票样本来源: {result['sample_source']}")
    if result["sample_source"] == "REAL_UNIVERSE_PRESET=full":
        print(f"- 原始沪深 A 股数量: {result.get('raw_symbol_count', 0)}")
        print(f"- 剔除北交所数量: {result.get('excluded_bse_count', 0)}")
        print(f"- 剔除 ST / 退市数量: {result.get('excluded_abnormal_count', 0)}")
        print(f"- 基础股票池数量: {result.get('base_universe_count', 0)}")
    print(f"- 配置股票数量: {result['configured_symbol_count']}")
    print(f"- 数据库中实际有行情的股票数量: {result['priced_symbol_count']}")
    print(f"- 覆盖率: {result['coverage_rate']:.2%}")
    print(f"- 缺数据股票数量: {len(result['missing_symbols'])}")
    if result["missing_symbols"]:
        print(f"- 缺数据股票列表: {_format_symbol_list(result['missing_symbols'])}")
    print(f"- 可运行因子诊断的股票数量: {result['factor_ready_count']}")
    print(f"- 可运行选股的股票数量: {result['selection_ready_count']}")
    print(f"- 可运行回测的股票数量: {result['backtest_ready_count']}")
    print("- 每只股票覆盖:")
    coverage_rows = result["symbol_coverage"]
    for item in coverage_rows[:120]:
        print(
            f"  {item['ts_code']} {item.get('name') or ''} "
            f"daily_price={'是' if item['has_daily_price'] else '否'} "
            f"rows={item['daily_price_rows']} "
            f"min={item['min_trade_date'] or '暂无'} max={item['max_trade_date'] or '暂无'} "
            f"daily_basic={'是' if item['has_daily_basic'] else '否'} "
            f"adj_factor={'是' if item['has_adj_factor'] else '否'}"
        )
    if len(coverage_rows) > 120:
        print(f"  ... 其余 {len(coverage_rows) - 120} 只省略，完整结构化结果可在函数返回值中查看。")
    if result["reasons"]:
        print("- 具体原因:")
        for reason in result["reasons"]:
            print(f"  {reason}")
    print("- 下一步建议:")
    for step in result["next_steps"]:
        print(f"  {step}")


def _build_result(
    settings: Settings,
    store: DuckDBStore,
    tables: dict[str, pd.DataFrame],
    configured_symbols: list[str],
    sample_source: str,
    reasons: list[str],
    universe_summary: dict[str, Any],
) -> dict[str, Any]:
    """Build a structured batch coverage diagnostic."""
    coverage = _symbol_coverage(configured_symbols, tables)
    priced = [item for item in coverage if item["has_daily_price"]]
    factor_ready = [item for item in coverage if item["daily_price_rows"] >= 20 and item["has_daily_basic"]]
    backtest_ready = [item for item in coverage if item["daily_price_rows"] >= 60 and item["has_daily_basic"]]
    missing = [item["ts_code"] for item in coverage if not item["has_daily_price"]]
    computed_reasons = list(reasons)
    if missing:
        computed_reasons.append(f"部分股票缺少 daily_price：{_format_symbol_list(missing)}。")
    return {
        "data_provider": settings.data_provider,
        "duckdb_path": str(store.db_path),
        "sample_source": sample_source,
        "configured_symbol_count": len(configured_symbols),
        "raw_symbol_count": int(universe_summary.get("raw_symbol_count", len(configured_symbols))),
        "excluded_bse_count": int(universe_summary.get("excluded_bse_count", 0)),
        "excluded_abnormal_count": int(universe_summary.get("excluded_abnormal_count", 0)),
        "base_universe_count": int(universe_summary.get("base_universe_count", len(configured_symbols))),
        "priced_symbol_count": len(priced),
        "coverage_rate": (len(priced) / len(configured_symbols)) if configured_symbols else 0.0,
        "symbol_coverage": coverage,
        "missing_symbols": missing,
        "factor_ready_count": len(factor_ready),
        "selection_ready_count": len(factor_ready),
        "backtest_ready_count": len(backtest_ready),
        "reasons": computed_reasons,
        "next_steps": _next_steps(len(priced), len(configured_symbols)),
    }


def _symbol_coverage(configured_symbols: list[str], tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Return per-symbol local data coverage."""
    stock_basic = tables.get("stock_basic", pd.DataFrame())
    daily_price = tables.get("daily_price", pd.DataFrame())
    daily_basic = tables.get("daily_basic", pd.DataFrame())
    adj_factor = tables.get("adj_factor", pd.DataFrame())
    rows: list[dict[str, Any]] = []
    for symbol in configured_symbols:
        price_rows = _rows_for_symbol(daily_price, symbol)
        basic_rows = _rows_for_symbol(daily_basic, symbol)
        adj_rows = _rows_for_symbol(adj_factor, symbol)
        name = _stock_name(stock_basic, symbol)
        rows.append(
            {
                "ts_code": symbol,
                "name": name,
                "has_daily_price": not price_rows.empty,
                "daily_price_rows": int(len(price_rows)),
                "min_trade_date": _date_stat(price_rows, "trade_date", "min"),
                "max_trade_date": _date_stat(price_rows, "trade_date", "max"),
                "has_daily_basic": not basic_rows.empty,
                "has_adj_factor": not adj_rows.empty,
            }
        )
    return rows


def _configured_symbols(settings: Settings) -> tuple[list[str], str]:
    """Return configured ts_codes and their source label."""
    if settings.data_provider == "akshare":
        explicit = [symbol.strip() for symbol in settings.akshare_sample_symbols.split(",") if symbol.strip()]
        if explicit:
            return [to_ts_code(symbol) for symbol in explicit], "AKSHARE_SAMPLE_SYMBOLS"
        if is_full_universe_preset(settings.real_universe_preset):
            return [FULL_UNIVERSE_PENDING], "REAL_UNIVERSE_PRESET=full"
        return [to_ts_code(symbol) for symbol in get_universe_preset(settings.real_universe_preset)], "REAL_UNIVERSE_PRESET"
    explicit = [symbol.strip() for symbol in settings.real_data_sample_symbols.split(",") if symbol.strip()]
    if explicit:
        return [to_ts_code(symbol) for symbol in explicit], "REAL_DATA_SAMPLE_SYMBOLS"
    return [to_ts_code(symbol) for symbol in get_universe_preset(settings.real_universe_preset)], "REAL_UNIVERSE_PRESET"


def _resolve_full_universe_for_diagnosis(
    *,
    settings: Settings,
    stock_basic: pd.DataFrame,
    client: StockDataSource | None,
) -> dict[str, Any]:
    """Resolve full universe for diagnostics from provider first, then local fallback."""
    try:
        resolved_client = client or AKShareClient(
            adjust=getattr(settings, "akshare_adjust", "qfq"),
            request_timeout_seconds=getattr(settings, "real_request_timeout_seconds", 30),
            enable_basic_enrichment=False,
            enable_valuation_enrichment=False,
        )
        provider_stock_basic = resolved_client.get_stock_basic()
    except Exception as exc:
        local_summary = resolve_full_a_share_universe(stock_basic, include_bse=getattr(settings, "include_bse", False))
        local_result = _without_frame(local_summary)
        if local_result.get("base_universe_count", 0):
            local_result["warnings"] = [
                f"AKShare 基础股票列表获取失败：{type(exc).__name__}: {exc}；已回退使用本地 stock_basic 诊断。",
                *list(local_result.get("warnings", [])),
            ]
            return local_result
        return {
            "source": "REAL_UNIVERSE_PRESET=full",
            "label": "沪深 A 股全市场，不含北交所",
            "symbols": [],
            "ts_codes": [],
            "raw_symbol_count": 0,
            "excluded_bse_count": 0,
            "excluded_abnormal_count": 0,
            "base_universe_count": 0,
            "warnings": [f"AKShare 基础股票列表获取失败：{type(exc).__name__}: {exc}"],
        }
    provider_summary = resolve_full_a_share_universe(
        provider_stock_basic,
        include_bse=getattr(settings, "include_bse", False),
    )
    return _without_frame(provider_summary)


def _without_frame(summary: dict[str, Any]) -> dict[str, Any]:
    """Drop DataFrame values from a universe summary."""
    return {key: value for key, value in summary.items() if key != "stock_basic"}


def _rows_for_symbol(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    """Return rows matching one ts_code."""
    if df.empty or "ts_code" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["ts_code"].astype(str) == ts_code]


def _stock_name(stock_basic: pd.DataFrame, ts_code: str) -> str | None:
    """Return stock name when available."""
    if stock_basic.empty or not {"ts_code", "name"}.issubset(stock_basic.columns):
        return None
    rows = stock_basic[stock_basic["ts_code"].astype(str) == ts_code]
    if rows.empty:
        return None
    return str(rows.iloc[0]["name"])


def _date_stat(df: pd.DataFrame, column: str, method: str) -> str | None:
    """Return min or max date for a DataFrame column."""
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    if values.empty:
        return None
    return str(values.min() if method == "min" else values.max())


def _next_steps(priced_count: int, configured_count: int) -> list[str]:
    """Return suggested next commands for batch state."""
    if priced_count == 0 and configured_count:
        return ["python -m core.jobs.update_real_data"]
    return [
        "python -m core.jobs.diagnose_factors",
        "python -m core.jobs.run_daily_selection",
        "python -m core.jobs.diagnose_backtest",
    ]


def _format_symbol_list(symbols: list[str], limit: int = 50) -> str:
    """Return a concise symbol list for full-universe diagnostics."""
    if len(symbols) <= limit:
        return ", ".join(symbols)
    preview = ", ".join(symbols[:limit])
    return f"{preview}, ...（共 {len(symbols)} 只）"


if __name__ == "__main__":
    main()
