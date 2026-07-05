"""Unified free-provider market data update command."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.data_sources.akshare_client import AKShareClient
from core.data_sources.akshare_spot_snapshot import AKShareSpotSnapshotClient
from core.data_sources.baostock_client import BaoStockClient, BaoStockUnavailable
from core.jobs.market_data_status import DEFAULT_STATUS_PATH, record_provider_attempt
from core.storage.duckdb_store import DuckDBStore


PROVIDERS = ["akshare_kline", "akshare_spot_snapshot", "baostock", "csv", "tushare_optional", "auto"]


def update_market_data(
    *,
    mode: str = "daily_incremental",
    provider: str = "auto",
    start_date: str = "",
    end_date: str = "",
    symbols: list[str] | None = None,
    update_limit: int = 0,
    dry_run: bool = False,
    force_snapshot: bool = False,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    settings: Settings | None = None,
    akshare_client: AKShareClient | None = None,
    spot_client: AKShareSpotSnapshotClient | None = None,
    baostock_client: BaoStockClient | None = None,
) -> dict[str, Any]:
    """Update market data through free fallback providers."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    resolved_settings = settings or get_settings()
    end = _normalize_date(end_date) or _default_end_date(resolved_settings)
    start = _normalize_date(start_date) or _start_from_end(end, int(getattr(resolved_settings, "full_update_lookback_days", 250) or 250))
    resolved_symbols = _resolve_symbols(symbols, update_limit=update_limit, settings=resolved_settings)
    if dry_run:
        return {
            "status": "success",
            "mode": mode,
            "provider": provider,
            "planned_symbols": len(resolved_symbols),
            "start_date": start,
            "end_date": end,
            "message": "dry-run：未联网、未写 DuckDB。",
        }
    store = DuckDBStore(resolved_settings.duckdb_path)
    store.initialize()
    attempts: list[dict[str, Any]] = []
    provider_order = _provider_order(provider, resolved_settings)
    for candidate in provider_order:
        result = _run_provider(
            candidate,
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
        )
        attempts.append(result)
        if provider != "auto":
            result["provider_attempts"] = attempts
            return result
        if result.get("status") in {"success", "partial_success"} and int(result.get("written_row_count", 0) or 0) > 0:
            result["provider_attempts"] = attempts
            return result
    final = {
        "status": "failed",
        "mode": mode,
        "provider": provider,
        "provider_attempts": attempts,
        "message": "免费数据源均未写入有效数据，请尝试 CSV / Excel 手动导入。",
    }
    record_provider_attempt(
        provider=provider,
        mode=mode,
        success=False,
        partial_update=True,
        error_type="all_providers_failed",
        error_message=final["message"],
        status_path=status_path,
        db_path=store.db_path,
    )
    return final


def _run_provider(
    provider: str,
    *,
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
) -> dict[str, Any]:
    try:
        if provider == "akshare_kline":
            client = akshare_client or AKShareClient(
                adjust=settings.akshare_adjust,
                request_timeout_seconds=settings.data_source_request_timeout_seconds,
                symbol_timeout_seconds=settings.symbol_update_timeout_seconds,
                enable_basic_enrichment=False,
                enable_valuation_enrichment=False,
            )
            price = client.get_daily_price(start_date, end_date, symbols)
            written = _write_price_and_partial_basic(store, price, write_basic=False)
            _record(provider, mode, written, ["daily_price"], False, end_date, status_path, db_path=db_path)
            return {"status": "success" if written else "failed", "provider": provider, "written_row_count": written, "partial_update": False}
        if provider == "akshare_spot_snapshot":
            client = spot_client or AKShareSpotSnapshotClient()
            payload = client.fetch_latest(trade_date=end_date, symbols=symbols, force=force_snapshot)
            if payload.get("status") == "skipped":
                _record(provider, mode, 0, [], True, end_date, status_path, db_path=db_path, success=False, error_message=str(payload.get("message") or "skipped"))
                return {"status": "skipped", "provider": provider, "written_row_count": 0, "message": payload.get("message"), "partial_update": True}
            price = payload.get("daily_price", pd.DataFrame())
            basic = payload.get("daily_basic", pd.DataFrame())
            written_price = _write_price_and_partial_basic(store, price, write_basic=False)
            written_basic = store.upsert_dataframe("daily_basic", basic) if isinstance(basic, pd.DataFrame) and not basic.empty else 0
            written_adj = forward_fill_adj_factor(store, end_date=end_date, symbols=symbols)
            written = written_price + written_basic + written_adj
            _record(provider, mode, written, ["daily_price", "daily_basic", "adj_factor"], True, end_date, status_path, db_path=db_path)
            return {"status": "success" if written_price else "failed", "provider": provider, "written_row_count": written, "partial_update": True, "written_price_rows": written_price}
        if provider == "baostock":
            client = baostock_client or BaoStockClient()
            payload = client.get_daily_price(start_date=start_date, end_date=end_date, symbols=symbols, limit=0)
            price = payload.get("daily_price", pd.DataFrame())
            written = _write_price_and_partial_basic(store, price, write_basic=False)
            _record(provider, mode, written, ["daily_price"], True, end_date, status_path, db_path=db_path)
            return {"status": "success" if written else "failed", "provider": provider, "written_row_count": written, "partial_update": True}
        if provider == "tushare_optional":
            if not settings.tushare_token:
                message = "Tushare token 未配置；Tushare 仅作为可选项，已跳过。"
                _record(provider, mode, 0, [], True, end_date, status_path, db_path=db_path, success=False, error_message=message)
                return {"status": "skipped", "provider": provider, "written_row_count": 0, "message": message, "partial_update": True}
        if provider == "csv":
            message = "CSV / Excel 需要用户通过 import_market_data 手动导入。"
            _record(provider, mode, 0, [], True, end_date, status_path, db_path=db_path, success=False, error_message=message)
            return {"status": "skipped", "provider": provider, "written_row_count": 0, "message": message, "partial_update": True}
    except BaoStockUnavailable as exc:
        _record(provider, mode, 0, [], True, end_date, status_path, db_path=db_path, success=False, error_type="provider_unavailable", error_message=str(exc))
        return {"status": "failed", "provider": provider, "written_row_count": 0, "error_message": str(exc), "partial_update": True}
    except Exception as exc:
        _record(provider, mode, 0, [], True, end_date, status_path, db_path=db_path, success=False, error_type=type(exc).__name__, error_message=str(exc))
        return {"status": "failed", "provider": provider, "written_row_count": 0, "error_message": str(exc), "partial_update": True}
    return {"status": "skipped", "provider": provider, "written_row_count": 0, "partial_update": True}


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


def _record(
    provider: str,
    mode: str,
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
) -> None:
    record_provider_attempt(
        provider=provider,
        mode=mode,
        success=written > 0 if success is None else success,
        written_table_names=tables,
        written_row_count=written,
        partial_update=partial,
        error_type=error_type,
        error_message=error_message,
        trade_date=trade_date,
        status_path=status_path,
        db_path=db_path,
    )


def _provider_order(provider: str, settings: Settings) -> list[str]:
    if provider != "auto":
        return [provider]
    order = ["akshare_kline", "akshare_spot_snapshot", "baostock", "csv"]
    if settings.tushare_token:
        order.append("tushare_optional")
    return order


def _resolve_symbols(symbols: list[str] | None, *, update_limit: int, settings: Settings) -> list[str]:
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
    return result[:update_limit] if update_limit else result


def _default_end_date(settings: Settings) -> str:
    return settings.real_data_end_date or datetime.now().strftime("%Y%m%d")


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
    parser.add_argument("--mode", choices=["daily_incremental", "full_backfill"], default="daily_incremental")
    parser.add_argument("--provider", choices=PROVIDERS, default="auto")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--update-limit", type=int, default=0)
    parser.add_argument("--force-snapshot", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    result = update_market_data(
        mode=args.mode,
        provider=args.provider,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=symbols or None,
        update_limit=args.update_limit,
        force_snapshot=args.force_snapshot,
        dry_run=args.dry_run,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print("免费数据源更新")
        print(f"- 状态: {result.get('status')}")
        print(f"- provider: {result.get('provider')}")
        print(f"- mode: {result.get('mode')}")
        print(f"- 写入行数: {result.get('written_row_count', 0)}")
        print(f"- 说明: {result.get('message', '')}")
    raise SystemExit(0 if result.get("status") in {"success", "partial_success", "skipped"} else 1)


if __name__ == "__main__":
    main()
