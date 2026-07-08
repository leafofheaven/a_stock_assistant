"""Update the local A-share trading calendar."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd

from app.config import Settings, get_settings
from core.data_sources.akshare_client import AKShareClient
from core.data_sources.base import DataSourceError, StockDataSource
from core.data_sources.tushare_client import TushareClient
from core.storage.duckdb_store import DuckDBStore


@dataclass(frozen=True)
class TradeCalendarUpdateResult:
    """Result of a trade-calendar update attempt."""

    status: str
    exchange: str
    source: str
    start_date: str
    end_date: str
    written_rows: int
    open_day_count: int
    coverage_start: str
    coverage_end: str
    warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ProviderFactory = Callable[[Settings], StockDataSource]


def update_trade_calendar(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    exchange: str = "SSE",
    settings: Settings | Any | None = None,
    store: DuckDBStore | None = None,
    provider_factory: ProviderFactory | None = None,
) -> TradeCalendarUpdateResult:
    """Fetch and upsert local ``trade_calendar`` rows.

    The job is non-destructive: provider failures do not clear existing rows.
    """
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(getattr(resolved_settings, "duckdb_path", None))
    resolved_store.initialize()
    start = _normalize_date(start_date) or _default_start_date()
    end = _normalize_date(end_date) or _default_end_date()
    source = "custom" if provider_factory else _preferred_calendar_source(resolved_settings)
    try:
        client = provider_factory(resolved_settings) if provider_factory else _build_provider(source, resolved_settings)
        raw = client.get_trade_calendar()
        calendar = normalize_trade_calendar(raw, start_date=start, end_date=end, exchange=exchange, source=source)
        if calendar.empty:
            return TradeCalendarUpdateResult(
                status="warning",
                exchange=exchange,
                source=source,
                start_date=start,
                end_date=end,
                written_rows=0,
                open_day_count=0,
                coverage_start="",
                coverage_end="",
                warning="交易日历数据源返回空数据，已保留本地已有 trade_calendar。",
            )
        written = resolved_store.upsert_dataframe("trade_calendar", calendar[["exchange", "cal_date", "is_open", "pretrade_date"]])
        return TradeCalendarUpdateResult(
            status="success",
            exchange=exchange,
            source=source,
            start_date=start,
            end_date=end,
            written_rows=written,
            open_day_count=int(pd.to_numeric(calendar["is_open"], errors="coerce").fillna(0).astype(int).sum()),
            coverage_start=str(calendar["cal_date"].min()),
            coverage_end=str(calendar["cal_date"].max()),
        )
    except Exception as exc:
        return TradeCalendarUpdateResult(
            status="warning",
            exchange=exchange,
            source=source,
            start_date=start,
            end_date=end,
            written_rows=0,
            open_day_count=0,
            coverage_start="",
            coverage_end="",
            warning=f"交易日历刷新失败，已保留本地已有 trade_calendar：{type(exc).__name__}: {exc}",
        )


def normalize_trade_calendar(
    frame: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    exchange: str = "SSE",
    source: str = "",
) -> pd.DataFrame:
    """Normalize provider calendar rows and fill closed days for the range."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=["exchange", "cal_date", "is_open", "pretrade_date"])
    raw = frame.copy()
    if "cal_date" not in raw.columns:
        for candidate in ["trade_date", "date", "日期"]:
            if candidate in raw.columns:
                raw = raw.rename(columns={candidate: "cal_date"})
                break
    if "cal_date" not in raw.columns:
        raise DataSourceError("trade calendar data is missing cal_date.")
    raw["cal_date"] = raw["cal_date"].map(_normalize_date)
    raw = raw[(raw["cal_date"] >= start_date) & (raw["cal_date"] <= end_date)].copy()
    if raw.empty:
        return pd.DataFrame(columns=["exchange", "cal_date", "is_open", "pretrade_date"])
    if "is_open" not in raw.columns:
        raw["is_open"] = 1
    raw["is_open"] = pd.to_numeric(raw["is_open"], errors="coerce").fillna(0).astype(int)
    raw_open = set(raw.loc[raw["is_open"] == 1, "cal_date"].dropna().astype(str))
    provided_closed = set(raw.loc[raw["is_open"] == 0, "cal_date"].dropna().astype(str))
    rows: list[dict[str, Any]] = []
    previous_open = ""
    for cal_date in _date_range(start_date, end_date):
        is_open = 1 if cal_date in raw_open else 0
        if cal_date in provided_closed:
            is_open = 0
        rows.append(
            {
                "exchange": exchange,
                "cal_date": cal_date,
                "is_open": is_open,
                "pretrade_date": previous_open if is_open else previous_open,
            }
        )
        if is_open:
            previous_open = cal_date
    result = pd.DataFrame(rows)
    result["source"] = source
    result["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return result


def _build_provider(source: str, settings: Settings | Any) -> StockDataSource:
    if source == "tushare":
        return TushareClient(token=getattr(settings, "tushare_token", ""))
    return AKShareClient()


def _preferred_calendar_source(settings: Settings | Any) -> str:
    provider = str(getattr(settings, "data_provider", "") or "").lower()
    if provider == "tushare" and getattr(settings, "tushare_token", ""):
        return "tushare"
    return "akshare"


def _default_start_date(today: date | None = None) -> str:
    current = today or date.today()
    return f"{current.year - 2}0101"


def _default_end_date(today: date | None = None) -> str:
    current = today or date.today()
    return f"{current.year + 1}1231"


def _date_range(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    days = (end - start).days
    return [(start + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days + 1)]


def _normalize_date(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    return text.replace("-", "")[:8] if text else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update local A-share trade calendar.")
    parser.add_argument("--start-date", default=None, help="Start date in YYYYMMDD; default current year - 2 years.")
    parser.add_argument("--end-date", default=None, help="End date in YYYYMMDD; default current year + 1 year.")
    parser.add_argument("--exchange", default="SSE", help="Exchange code, default SSE.")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    result = update_trade_calendar(start_date=args.start_date, end_date=args.end_date, exchange=args.exchange)
    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        if result.status == "success":
            print("交易日历更新完成")
        else:
            print("交易日历更新未完成")
        print(f"- exchange: {result.exchange}")
        print(f"- source: {result.source}")
        print(f"- 覆盖区间: {result.coverage_start or result.start_date} - {result.coverage_end or result.end_date}")
        print(f"- 写入行数: {result.written_rows}")
        print(f"- 交易日数量: {result.open_day_count}")
        if result.warning:
            print(f"- warning: {result.warning}")
    return 0 if result.status in {"success", "warning"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

