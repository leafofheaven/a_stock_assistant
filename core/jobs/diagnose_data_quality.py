"""Basic information and valuation data quality diagnostics."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError


STOCK_BASIC_FIELDS = ["name", "industry", "market", "list_date"]
DAILY_BASIC_FIELDS = ["turnover_rate", "pe", "pb", "total_mv", "circ_mv"]


def diagnose_data_quality(
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Diagnose stock_basic and daily_basic field completeness from local DuckDB.

    The command only reads local data. Missing PE/PB or market-cap values are
    reported as quality notes and do not fail the workflow.
    """
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    try:
        stock_basic = resolved_store.read_table("stock_basic")
        daily_price = resolved_store.read_table("daily_price")
        daily_basic = resolved_store.read_table("daily_basic")
    except DuckDBStoreError as exc:
        return {
            "data_provider": resolved_settings.data_provider,
            "duckdb_path": str(resolved_store.db_path),
            "status": "failed",
            "message": f"读取本地 DuckDB 失败：{exc}",
            "stock_basic_rows": 0,
            "daily_basic_rows": 0,
            "stock_basic_completeness": _empty_rates(STOCK_BASIC_FIELDS),
            "daily_basic_completeness": _empty_rates(DAILY_BASIC_FIELDS),
            "latest_trade_date": None,
            "latest_date_stock_count": 0,
            "latest_date_pe_non_null_rate": 0.0,
            "latest_date_pb_non_null_rate": 0.0,
            "latest_date_total_mv_non_null_rate": 0.0,
            "latest_date_circ_mv_non_null_rate": 0.0,
            "missing_reasons": ["本地 DuckDB 读取失败，无法判断补全字段完整率。"],
            "symbol_quality": [],
            "affects_fundamental_score": True,
            "next_steps": ["python -m core.jobs.update_real_data"],
        }

    stock_rates = _completeness(stock_basic, STOCK_BASIC_FIELDS)
    basic_rates = _completeness(daily_basic, DAILY_BASIC_FIELDS)
    latest_rates = _latest_date_completeness(daily_price, daily_basic)
    symbol_quality = _symbol_quality(stock_basic, daily_price, daily_basic)
    missing_reasons = _missing_reasons(stock_rates, basic_rates, daily_basic)
    valuation_summary = _valuation_summary(daily_basic)
    affects_fundamental = (
        daily_basic.empty
        or basic_rates.get("pe", 0.0) == 0.0
        or basic_rates.get("pb", 0.0) == 0.0
    )
    return {
        "data_provider": resolved_settings.data_provider,
        "duckdb_path": str(resolved_store.db_path),
        "status": "success",
        "message": "数据质量诊断完成。",
        "stock_basic_rows": int(len(stock_basic)),
        "daily_basic_rows": int(len(daily_basic)),
        "stock_basic_completeness": stock_rates,
        "daily_basic_completeness": basic_rates,
        **latest_rates,
        "missing_reasons": missing_reasons,
        "symbol_quality": symbol_quality,
        "valuation_summary": valuation_summary,
        **valuation_summary,
        "affects_fundamental_score": affects_fundamental,
        "next_steps": _next_steps(affects_fundamental),
    }


def main() -> None:
    """Print a concise data-quality diagnostic report."""
    result = diagnose_data_quality()
    print("基础信息与估值字段质量诊断")
    print(f"- 当前 DATA_PROVIDER: {result['data_provider']}")
    print(f"- DuckDB 路径: {result['duckdb_path']}")
    print(f"- 状态: {result['status']}")
    print(f"- stock_basic 行数: {result['stock_basic_rows']}")
    print("- stock_basic 字段完整率:")
    for field, rate in result["stock_basic_completeness"].items():
        print(f"  {field}: {rate:.2%}")
    print(f"- daily_basic 行数: {result['daily_basic_rows']}")
    print("- daily_basic 字段完整率:")
    for field, rate in result["daily_basic_completeness"].items():
        print(f"  {field}: {rate:.2%}")
    valuation = result.get("valuation_summary", {})
    if valuation:
        print("- 估值字段摘要:")
        print(f"  valuation_source: {valuation.get('valuation_source')}")
        print(f"  valuation_as_of: {valuation.get('valuation_as_of') or '暂无'}")
        print(f"  valuation_updated_count: {valuation.get('valuation_updated_count', 0)}")
        print(f"  valuation_missing_count: {valuation.get('valuation_missing_count', 0)}")
        print(f"  pe_non_null_rate: {valuation.get('pe_non_null_rate', 0.0):.2%}")
        print(f"  pb_non_null_rate: {valuation.get('pb_non_null_rate', 0.0):.2%}")
    print("- 最新交易日估值字段完整率:")
    print(f"  latest_trade_date: {result.get('latest_trade_date') or '暂无'}")
    print(f"  latest_date_stock_count: {result.get('latest_date_stock_count', 0)}")
    print(f"  latest_date_pe_non_null_rate: {result.get('latest_date_pe_non_null_rate', 0.0):.2%}")
    print(f"  latest_date_pb_non_null_rate: {result.get('latest_date_pb_non_null_rate', 0.0):.2%}")
    print(f"  latest_date_total_mv_non_null_rate: {result.get('latest_date_total_mv_non_null_rate', 0.0):.2%}")
    print(f"  latest_date_circ_mv_non_null_rate: {result.get('latest_date_circ_mv_non_null_rate', 0.0):.2%}")
    if result.get("missing_reasons"):
        print("- 缺失原因:")
        for reason in result["missing_reasons"]:
            print(f"  {reason}")
    print("- 每只股票数据质量:")
    if result["symbol_quality"]:
        for item in result["symbol_quality"]:
            print(
                f"  {item['ts_code']} {item.get('name') or ''} industry={item.get('industry') or '缺失'} "
                f"list_date={item.get('list_date') or '缺失'} latest_trade_date={item.get('latest_trade_date') or '暂无'} "
                f"pe={item['pe_has_value']} pb={item['pb_has_value']} note={item['data_quality_note']}"
            )
    else:
        print("  暂无。")
    print(f"- 是否影响 fundamental_score: {'是' if result['affects_fundamental_score'] else '否'}")
    print("- 下一步建议:")
    for step in result["next_steps"]:
        print(f"  {step}")


def _completeness(df: pd.DataFrame, fields: list[str]) -> dict[str, float]:
    """Return non-empty rate for each field."""
    if df.empty:
        return _empty_rates(fields)
    rates: dict[str, float] = {}
    row_count = len(df)
    for field in fields:
        if field not in df.columns:
            rates[field] = 0.0
            continue
        non_empty = df[field].apply(lambda value: not _is_missing(value)).sum()
        rates[field] = float(non_empty / row_count) if row_count else 0.0
    return rates


def _symbol_quality(
    stock_basic: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Return one quality row per stock in stock_basic."""
    if stock_basic.empty or "ts_code" not in stock_basic.columns:
        return []
    rows: list[dict[str, Any]] = []
    for item in stock_basic.to_dict("records"):
        ts_code = str(item.get("ts_code", ""))
        price_rows = _rows_for(daily_price, ts_code)
        basic_rows = _rows_for(daily_basic, ts_code)
        latest_price_date = _latest_date(price_rows, "trade_date")
        latest_basic = _latest_row(basic_rows, "trade_date")
        pe_has_value = not _is_missing(latest_basic.get("pe"))
        pb_has_value = not _is_missing(latest_basic.get("pb"))
        rows.append(
            {
                "ts_code": ts_code,
                "name": item.get("name"),
                "industry": item.get("industry"),
                "list_date": item.get("list_date"),
                "latest_trade_date": latest_price_date,
                "pe_has_value": pe_has_value,
                "pb_has_value": pb_has_value,
                "data_quality_note": _quality_note(item, latest_basic, latest_price_date),
            }
        )
    return rows


def _quality_note(stock_row: dict[str, Any], basic_row: dict[str, Any], latest_price_date: str | None) -> str:
    """Build a concise data quality note."""
    missing: list[str] = []
    for field, label in [("industry", "industry"), ("list_date", "list_date")]:
        if _is_missing(stock_row.get(field)):
            missing.append(f"{label} 缺失")
    for field, label in [("pe", "pe"), ("pb", "pb")]:
        if _is_missing(basic_row.get(field)):
            missing.append(f"{label} 缺失")
    if not latest_price_date:
        missing.append("无行情日期")
    return "；".join(missing) if missing else "基础信息和估值字段可用"


def _missing_reasons(
    stock_rates: dict[str, float],
    daily_basic_rates: dict[str, float],
    daily_basic: pd.DataFrame,
) -> list[str]:
    """Return clear reasons for important missing fields."""
    reasons: list[str] = []
    if stock_rates.get("industry", 0.0) == 0.0:
        reasons.append("industry 完整率为 0，基础信息补全未成功或 AKShare 返回字段不可解析。")
    if stock_rates.get("list_date", 0.0) == 0.0:
        reasons.append("list_date 完整率为 0，基础信息补全未成功或 AKShare 返回字段不可解析。")
    if daily_basic.empty:
        reasons.append("daily_basic 无数据，估值字段无法诊断。")
    else:
        if daily_basic_rates.get("pe", 0.0) == 0.0:
            reasons.append("pe 完整率为 0，估值补全接口当前不可用或未成功。")
        if daily_basic_rates.get("pb", 0.0) == 0.0:
            reasons.append("pb 完整率为 0，估值补全接口当前不可用或未成功。")
    return reasons


def _valuation_summary(daily_basic: pd.DataFrame) -> dict[str, Any]:
    """Return compact valuation coverage metadata."""
    if daily_basic.empty:
        return {
            "valuation_source": "none",
            "valuation_as_of": None,
            "valuation_updated_count": 0,
            "valuation_missing_count": 0,
            "pe_non_null_rate": 0.0,
            "pb_non_null_rate": 0.0,
        }
    latest = _latest_date(daily_basic, "trade_date")
    latest_rows = daily_basic[daily_basic["trade_date"].astype(str) == latest].copy() if latest else daily_basic.copy()
    pe_present = _present_mask(latest_rows, "pe")
    pb_present = _present_mask(latest_rows, "pb")
    updated = int((pe_present | pb_present).sum()) if not latest_rows.empty else 0
    total = int(len(latest_rows))
    return {
        "valuation_source": "local_daily_basic" if updated else "unavailable",
        "valuation_as_of": latest,
        "valuation_updated_count": updated,
        "valuation_missing_count": max(total - updated, 0),
        "pe_non_null_rate": float(_present_mask(daily_basic, "pe").sum() / len(daily_basic)) if len(daily_basic) else 0.0,
        "pb_non_null_rate": float(_present_mask(daily_basic, "pb").sum() / len(daily_basic)) if len(daily_basic) else 0.0,
    }


def _latest_date_completeness(daily_price: pd.DataFrame, daily_basic: pd.DataFrame) -> dict[str, Any]:
    """Return valuation completeness for the current latest local trade date."""
    latest_trade_date = _latest_date(daily_price, "trade_date") or _latest_date(daily_basic, "trade_date")
    if not latest_trade_date or daily_basic.empty or "trade_date" not in daily_basic.columns:
        return {
            "latest_trade_date": latest_trade_date,
            "latest_date_stock_count": 0,
            "latest_date_pe_non_null_rate": 0.0,
            "latest_date_pb_non_null_rate": 0.0,
            "latest_date_total_mv_non_null_rate": 0.0,
            "latest_date_circ_mv_non_null_rate": 0.0,
        }
    latest_rows = daily_basic[daily_basic["trade_date"].astype(str) == str(latest_trade_date)].copy()
    return {
        "latest_trade_date": latest_trade_date,
        "latest_date_stock_count": int(latest_rows["ts_code"].nunique()) if "ts_code" in latest_rows.columns else int(len(latest_rows)),
        "latest_date_pe_non_null_rate": _field_present_rate(latest_rows, "pe"),
        "latest_date_pb_non_null_rate": _field_present_rate(latest_rows, "pb"),
        "latest_date_total_mv_non_null_rate": _field_present_rate(latest_rows, "total_mv"),
        "latest_date_circ_mv_non_null_rate": _field_present_rate(latest_rows, "circ_mv"),
    }


def _field_present_rate(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    return float(_present_mask(df, column).sum() / len(df)) if len(df) else 0.0


def _present_mask(df: pd.DataFrame, column: str) -> pd.Series:
    if df.empty or column not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    return df[column].map(lambda value: not _is_missing(value))


def _rows_for(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    if df.empty or "ts_code" not in df.columns:
        return pd.DataFrame()
    return df[df["ts_code"].astype(str) == ts_code].copy()


def _latest_row(df: pd.DataFrame, date_col: str) -> dict[str, Any]:
    if df.empty or date_col not in df.columns:
        return {}
    return df.sort_values(date_col).iloc[-1].to_dict()


def _latest_date(df: pd.DataFrame, date_col: str) -> str | None:
    if df.empty or date_col not in df.columns:
        return None
    values = df[date_col].dropna().astype(str)
    return None if values.empty else str(values.max())


def _empty_rates(fields: list[str]) -> dict[str, float]:
    return {field: 0.0 for field in fields}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


def _next_steps(affects_fundamental: bool) -> list[str]:
    if affects_fundamental:
        return [
            "确认 ENABLE_REAL_BASIC_ENRICHMENT=true 与 ENABLE_REAL_VALUATION_ENRICHMENT=true。",
            "python -m core.jobs.update_real_data",
            "python -m core.jobs.diagnose_factors",
        ]
    return ["python -m core.jobs.diagnose_factors", "python -m core.jobs.run_daily_selection"]


if __name__ == "__main__":
    main()
