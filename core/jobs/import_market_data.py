"""Import local CSV / Excel market data into DuckDB with field aliases."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import get_settings
from core.jobs.market_data_status import DEFAULT_STATUS_PATH, record_provider_attempt
from core.storage.duckdb_store import DuckDBStore


SUPPORTED_TABLES = {"daily_price", "daily_basic", "adj_factor"}

ALIASES = {
    "代码": "ts_code",
    "股票代码": "ts_code",
    "ts_code": "ts_code",
    "symbol": "ts_code",
    "日期": "trade_date",
    "交易日期": "trade_date",
    "trade_date": "trade_date",
    "开盘": "open",
    "open": "open",
    "最高": "high",
    "high": "high",
    "最低": "low",
    "low": "low",
    "收盘": "close",
    "最新价": "close",
    "close": "close",
    "昨收": "pre_close",
    "pre_close": "pre_close",
    "成交量": "vol",
    "volume": "vol",
    "vol": "vol",
    "成交额": "amount",
    "amount": "amount",
    "换手率": "turnover_rate",
    "turnover_rate": "turnover_rate",
    "量比": "volume_ratio",
    "volume_ratio": "volume_ratio",
    "市盈率": "pe",
    "pe": "pe",
    "市净率": "pb",
    "pb": "pb",
    "市销率": "ps",
    "ps": "ps",
    "总市值": "total_mv",
    "total_mv": "total_mv",
    "流通市值": "circ_mv",
    "circ_mv": "circ_mv",
    "复权因子": "adj_factor",
    "adj_factor": "adj_factor",
}

TABLE_COLUMNS = {
    "daily_price": ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"],
    "daily_basic": ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_mv", "circ_mv"],
    "adj_factor": ["ts_code", "trade_date", "adj_factor"],
}


def import_market_data(
    *,
    file: str | Path,
    table: str,
    dry_run: bool = False,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Import a local market-data file and refresh data-quality status."""
    if table not in SUPPORTED_TABLES:
        raise ValueError(f"Unsupported table: {table}")
    source = Path(file)
    raw = _read_file(source)
    normalized = normalize_import_frame(raw, table)
    if dry_run:
        return {"status": "success", "table": table, "preview_rows": len(normalized), "written_rows": 0, "columns": list(normalized.columns)}
    store = DuckDBStore(db_path or get_settings().duckdb_path)
    store.initialize()
    written = store.upsert_dataframe(table, normalized) if not normalized.empty else 0
    record_provider_attempt(
        provider="csv_manual_import" if source.suffix.lower() == ".csv" else "excel_manual_import",
        mode=f"import_{table}",
        success=True,
        written_table_names=[table],
        written_row_count=written,
        partial_update=True,
        trade_date=str(normalized["trade_date"].max()) if not normalized.empty and "trade_date" in normalized.columns else "",
        status_path=status_path,
        db_path=store.db_path,
        extra={"manual_import_last_file": str(source), "manual_import_last_result": f"{table} written_rows={written}"},
    )
    return {"status": "success", "table": table, "written_rows": written, "source_file": str(source)}


def normalize_import_frame(raw: pd.DataFrame, table: str) -> pd.DataFrame:
    """Normalize aliases and values for one supported market-data table."""
    if raw.empty:
        return pd.DataFrame(columns=TABLE_COLUMNS[table])
    frame = raw.rename(columns={column: ALIASES.get(str(column).strip(), str(column).strip()) for column in raw.columns}).copy()
    if "ts_code" not in frame.columns or "trade_date" not in frame.columns:
        raise ValueError("导入文件必须包含股票代码和交易日期。")
    frame["ts_code"] = frame["ts_code"].map(normalize_ts_code)
    frame["trade_date"] = frame["trade_date"].map(normalize_trade_date)
    for column in TABLE_COLUMNS[table]:
        if column not in frame.columns:
            frame[column] = pd.NA
    numeric_columns = [column for column in TABLE_COLUMNS[table] if column not in {"ts_code", "trade_date"}]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if table == "daily_price":
        frame["change"] = frame["change"].where(frame["change"].notna(), frame["close"] - frame["pre_close"])
    return frame[TABLE_COLUMNS[table]].dropna(subset=["ts_code", "trade_date"]).drop_duplicates(["ts_code", "trade_date"], keep="last").reset_index(drop=True)


def normalize_ts_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "." in text:
        code, suffix = text.split(".", 1)
        if suffix in {"SH", "SZ"}:
            return f"{code.zfill(6)}.{suffix}"
    code = "".join(ch for ch in text if ch.isdigit())[:6]
    suffix = "SH" if code.startswith("6") else "SZ"
    return f"{code}.{suffix}" if len(code) == 6 else ""


def normalize_trade_date(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y%m%d")
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    return digits[:8]


def _read_file(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError("Only csv/xlsx/xls files are supported.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import local CSV/XLSX market data into DuckDB.")
    parser.add_argument("--file", required=True)
    parser.add_argument("--table", choices=sorted(SUPPORTED_TABLES), required=True)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = import_market_data(file=args.file, table=args.table, dry_run=args.dry_run)
    if args.format == "json":
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print("本地行情导入")
        print(f"- 状态: {result.get('status')}")
        print(f"- 表: {result.get('table')}")
        print(f"- 写入行数: {result.get('written_rows', 0)}")
        print(f"- 文件: {result.get('source_file', args.file)}")


if __name__ == "__main__":
    main()
