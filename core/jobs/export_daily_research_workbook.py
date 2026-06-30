"""Export a read-only daily research workbook as an Excel file."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.config import Settings, get_settings
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError

SHEET_NAMES = [
    "00_摘要",
    "01_今日候选",
    "02_埃尔德复核",
    "03_买入区间",
    "04_观察池",
    "05_观察池跟踪",
    "06_外部模拟持仓",
    "07_风险提示",
    "08_数据质量",
    "09_参数配置",
    "10_说明",
]

SENSITIVE_KEYWORDS = ("token", "key", "password", "secret")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class WorkbookExportResult:
    """Summary returned after exporting a daily research workbook."""

    output_path: Path
    trade_date: str
    strategy_rows: int
    elder_rows: int
    entry_zone_rows: int
    watchlist_rows: int
    external_position_rows: int


def export_daily_research_workbook(
    *,
    trade_date: str | None = None,
    output_path: str | Path | None = None,
    include_external_positions: bool = True,
    include_data_quality: bool = True,
    settings: Settings | Any | None = None,
    store: DuckDBStore | None = None,
) -> WorkbookExportResult:
    """Export the latest local research state to a read-only Excel workbook.

    The export reads only existing DuckDB tables. It does not update market data,
    recompute factors, rerank candidates, or write back to DuckDB.
    """
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(getattr(resolved_settings, "duckdb_path", None))

    strategy = _read_table(resolved_store, "strategy_result")
    factor_scores = _read_table(resolved_store, "factor_scores")
    entry_zones = _read_table(resolved_store, "entry_zone_snapshots")
    watchlist = _read_table(resolved_store, "watchlist_daily_snapshots")
    external_positions = (
        _read_table(resolved_store, "external_position_snapshots")
        if include_external_positions
        else pd.DataFrame()
    )

    selected_trade_date = trade_date or _latest_trade_date(strategy, factor_scores)
    selected_trade_date = selected_trade_date or _latest_price_date(resolved_store) or ""

    strategy_sheet = _build_strategy_sheet(strategy, selected_trade_date)
    elder_sheet = _build_elder_sheet(strategy_sheet, watchlist, selected_trade_date)
    entry_sheet = _build_entry_zone_sheet(entry_zones, strategy_sheet, watchlist, selected_trade_date)
    watchlist_sheet = _latest_by_date(watchlist, "trade_date", selected_trade_date)
    watchlist_sheet = _with_display_order(_preferred_columns(watchlist_sheet, _watchlist_columns()))
    external_sheet = _latest_external_positions(external_positions)
    risk_sheet = _build_risk_sheet(entry_sheet, watchlist_sheet, external_sheet)
    quality_sheet = (
        _build_data_quality_sheet(resolved_store, selected_trade_date)
        if include_data_quality
        else _message_frame("数据质量导出已关闭。")
    )
    settings_sheet = _settings_sheet(resolved_settings)
    summary_sheet = _build_summary_sheet(
        selected_trade_date=selected_trade_date,
        output_path=output_path,
        strategy_rows=len(strategy_sheet),
        elder_rows=len(elder_sheet),
        entry_zone_rows=len(entry_sheet),
        watchlist_rows=len(watchlist_sheet),
        external_position_rows=len(external_sheet),
    )
    help_sheet = _help_sheet()

    resolved_output = _resolve_output_path(output_path, selected_trade_date)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = {
        "00_摘要": summary_sheet,
        "01_今日候选": strategy_sheet,
        "02_埃尔德复核": elder_sheet,
        "03_买入区间": entry_sheet,
        "04_观察池": _empty_if_needed(watchlist_sheet, "暂无观察池跟踪数据。"),
        "05_观察池跟踪": _empty_if_needed(watchlist_sheet, "暂无观察池跟踪数据。"),
        "06_外部模拟持仓": _empty_if_needed(external_sheet, "暂无外部模拟持仓数据。"),
        "07_风险提示": _empty_if_needed(risk_sheet, "暂无需要特别提示的风险项。"),
        "08_数据质量": quality_sheet,
        "09_参数配置": settings_sheet,
        "10_说明": help_sheet,
    }
    for sheet_name in SHEET_NAMES:
        _write_sheet(workbook, sheet_name, sheets[sheet_name])
    workbook.save(resolved_output)

    return WorkbookExportResult(
        output_path=resolved_output,
        trade_date=selected_trade_date,
        strategy_rows=len(strategy_sheet),
        elder_rows=len(elder_sheet),
        entry_zone_rows=len(entry_sheet),
        watchlist_rows=len(watchlist_sheet),
        external_position_rows=len(external_sheet),
    )


def _read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    """Read a table through a read-only DuckDB connection, returning empty on failure."""
    try:
        return store.read_table(table_name, read_only=True)
    except DuckDBStoreError:
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _read_query(store: DuckDBStore, sql: str) -> pd.DataFrame:
    """Read a query through a read-only DuckDB connection, returning empty on failure."""
    try:
        with store.connect(read_only=True) as connection:
            return connection.execute(sql).fetchdf()
    except Exception:
        return pd.DataFrame()


def _latest_trade_date(strategy: pd.DataFrame, factor_scores: pd.DataFrame) -> str:
    """Return latest persisted selection/factor date."""
    for frame in (strategy, factor_scores):
        if "trade_date" in frame.columns and not frame.empty:
            value = frame["trade_date"].dropna().astype(str).max()
            if value:
                return value
    return ""


def _latest_price_date(store: DuckDBStore) -> str:
    latest = _read_query(store, "SELECT MAX(trade_date) AS latest_trade_date FROM daily_price")
    if latest.empty:
        return ""
    value = latest.iloc[0].get("latest_trade_date")
    return "" if pd.isna(value) else str(value)


def _latest_by_date(frame: pd.DataFrame, date_column: str, preferred_date: str = "") -> pd.DataFrame:
    if frame.empty or date_column not in frame.columns:
        return pd.DataFrame()
    dates = frame[date_column].dropna().astype(str)
    if dates.empty:
        return pd.DataFrame()
    selected_date = preferred_date if preferred_date and preferred_date in set(dates) else dates.max()
    return frame[frame[date_column].astype(str) == selected_date].copy()


def _build_strategy_sheet(strategy: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    frame = _latest_by_date(strategy, "trade_date", trade_date)
    if frame.empty:
        return _message_frame("暂无本地选股结果。请先运行 python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all。")
    frame = frame.copy()
    if "rank" in frame.columns:
        frame["candidate_rank"] = pd.to_numeric(frame["rank"], errors="coerce")
        frame = frame.sort_values(["candidate_rank", "ts_code"], na_position="last")
    elif "total_score" in frame.columns:
        frame = frame.sort_values("total_score", ascending=False, na_position="last")
    columns = [
        "display_order",
        "candidate_rank",
        "trade_date",
        "ts_code",
        "name",
        "industry",
        "close",
        "pe",
        "pb",
        "total_score",
        "trend_score",
        "momentum_score",
        "liquidity_score",
        "fundamental_score",
        "volatility_score",
        "quality_score",
        "valuation_score",
        "risk_score",
        "select_reason",
        "risk_note",
    ]
    return _with_display_order(_preferred_columns(frame, columns))


def _build_elder_sheet(strategy: pd.DataFrame, watchlist: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    strategy_elder_columns = [
        "display_order",
        "source",
        "candidate_rank",
        "trade_date",
        "review_date",
        "latest_trade_date",
        "ts_code",
        "name",
        "total_score",
        "elder_score",
        "action_hint",
        "elder_reason",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
    ]
    if not strategy.empty and {"elder_score", "action_hint", "elder_reason"}.intersection(strategy.columns):
        strategy_frame = strategy.copy()
        strategy_frame["source"] = "今日候选"
        rows.append(_preferred_columns(strategy_frame, strategy_elder_columns))

    watch_frame = _latest_by_date(watchlist, "trade_date", trade_date)
    if not watch_frame.empty:
        watch_frame = watch_frame.copy()
        watch_frame["source"] = "观察池"
        if "today_rank" in watch_frame.columns:
            watch_frame["candidate_rank"] = watch_frame["today_rank"]
        rows.append(_preferred_columns(watch_frame, strategy_elder_columns))

    if not rows:
        return _message_frame("暂无复核结果。请先运行 python -m core.jobs.run_elder_review。")
    return _with_display_order(pd.concat(rows, ignore_index=True, sort=False))


def _build_entry_zone_sheet(
    entry_zones: pd.DataFrame,
    strategy: pd.DataFrame,
    watchlist: pd.DataFrame,
    trade_date: str,
) -> pd.DataFrame:
    frame = _latest_by_date(entry_zones, "trade_date", trade_date)
    if frame.empty:
        return _message_frame("暂无买入区间结果。请先运行 python -m core.jobs.calculate_entry_zones。")
    if "source" not in frame.columns:
        frame["source"] = ""
    rank_map = {}
    if not strategy.empty and {"ts_code", "candidate_rank"}.issubset(strategy.columns):
        rank_map.update(strategy.set_index("ts_code")["candidate_rank"].to_dict())
    if not watchlist.empty and {"ts_code", "today_rank"}.issubset(watchlist.columns):
        rank_map.update(watchlist.set_index("ts_code")["today_rank"].to_dict())
    frame["candidate_rank"] = frame["ts_code"].map(rank_map)
    columns = [
        "display_order",
        "source",
        "candidate_rank",
        "trade_date",
        "ts_code",
        "name",
        "close",
        "ema13",
        "ema22",
        "ema60",
        "support_20d",
        "support_60d",
        "resistance_20d",
        "resistance_60d",
        "nearest_support",
        "nearest_resistance",
        "atr_14",
        "entry_low",
        "entry_high",
        "entry_mid",
        "stop_loss",
        "target_price",
        "risk_pct",
        "reward_pct",
        "reward_risk_ratio",
        "entry_zone_status",
        "entry_zone_status_cn",
        "chase_risk",
        "chase_risk_cn",
        "price_action_note",
        "entry_reason",
        "risk_note",
    ]
    return _with_display_order(_preferred_columns(frame, columns))


def _watchlist_columns() -> list[str]:
    return [
        "display_order",
        "trade_date",
        "ts_code",
        "name",
        "current_close",
        "pe",
        "pb",
        "today_rank",
        "previous_rank",
        "rank_change",
        "total_score",
        "total_score_change",
        "selected_count_5d",
        "selected_count_10d",
        "consecutive_selected_days",
        "best_rank",
        "watch_status",
        "watch_status_label",
        "watch_days",
        "elder_score",
        "action_hint",
        "elder_reason",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
        "daily_note",
    ]


def _latest_external_positions(external_positions: pd.DataFrame) -> pd.DataFrame:
    frame = _latest_by_date(external_positions, "snapshot_date")
    columns = [
        "display_order",
        "snapshot_date",
        "platform",
        "account_name",
        "ts_code",
        "name",
        "quantity",
        "cost_price",
        "current_price",
        "market_value",
        "pnl",
        "pnl_pct",
        "stop_loss",
        "target_price",
        "entry_low",
        "entry_high",
        "reward_risk_ratio",
        "position_status",
        "risk_status",
        "risk_status_cn",
        "match_note",
        "note",
    ]
    return _with_display_order(_preferred_columns(frame, columns))


def _build_risk_sheet(
    entry_zones: pd.DataFrame,
    watchlist: pd.DataFrame,
    external_positions: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not entry_zones.empty and "message" not in entry_zones.columns:
        for _, row in entry_zones.iterrows():
            risk_items: list[str] = []
            if str(row.get("chase_risk", "")).lower() == "high":
                risk_items.append("追高风险高")
            if str(row.get("entry_zone_status", "")).lower() in {"weak_no_entry", "insufficient_data"}:
                risk_items.append(str(row.get("entry_zone_status_cn") or row.get("entry_zone_status")))
            if pd.notna(row.get("reward_risk_ratio")) and float(row.get("reward_risk_ratio")) < 2:
                risk_items.append("盈亏比低于 2")
            if risk_items:
                rows.append(
                    {
                        "source": "买入区间",
                        "ts_code": row.get("ts_code"),
                        "name": row.get("name"),
                        "risk_type": "；".join(risk_items),
                        "detail": row.get("risk_note") or row.get("price_action_note"),
                        "suggested_action": "人工复核",
                    }
                )
    if not watchlist.empty and "message" not in watchlist.columns:
        for _, row in watchlist.iterrows():
            status = str(row.get("watch_status") or "")
            if status in {"overheated", "weakening", "invalidated"}:
                rows.append(
                    {
                        "source": "观察池",
                        "ts_code": row.get("ts_code"),
                        "name": row.get("name"),
                        "risk_type": row.get("watch_status_label") or status,
                        "detail": row.get("daily_note") or row.get("elder_reason"),
                        "suggested_action": "人工复核",
                    }
                )
    if not external_positions.empty and "message" not in external_positions.columns:
        for _, row in external_positions.iterrows():
            risk_status = str(row.get("risk_status") or "")
            if risk_status and risk_status not in {"normal", "matched", "ok"}:
                rows.append(
                    {
                        "source": "外部模拟持仓",
                        "ts_code": row.get("ts_code"),
                        "name": row.get("name"),
                        "risk_type": row.get("risk_status_cn") or risk_status,
                        "detail": row.get("match_note") or row.get("note"),
                        "suggested_action": "人工复核",
                    }
                )
    return pd.DataFrame(rows)


def _build_data_quality_sheet(store: DuckDBStore, trade_date: str) -> pd.DataFrame:
    metrics = [
        _table_metric(store, "stock_basic", "ts_code"),
        _table_metric(store, "daily_price", "ts_code", "trade_date"),
        _table_metric(store, "daily_basic", "ts_code", "trade_date"),
        _table_metric(store, "factor_scores", "ts_code", "trade_date"),
        _table_metric(store, "strategy_result", "ts_code", "trade_date"),
        _table_metric(store, "entry_zone_snapshots", "ts_code", "trade_date"),
        _table_metric(store, "watchlist_daily_snapshots", "ts_code", "trade_date"),
        _table_metric(store, "external_position_snapshots", "ts_code", "snapshot_date"),
    ]
    quality = pd.DataFrame(metrics)
    if trade_date:
        quality.loc[len(quality)] = {
            "table_name": "export_scope",
            "row_count": None,
            "distinct_symbols": None,
            "latest_date": trade_date,
            "note": "工作簿默认使用该日期的本地持久化结果。",
        }
    return quality


def _table_metric(
    store: DuckDBStore,
    table_name: str,
    symbol_column: str | None = None,
    date_column: str | None = None,
) -> dict[str, Any]:
    symbol_expr = f"COUNT(DISTINCT {symbol_column}) AS distinct_symbols" if symbol_column else "NULL AS distinct_symbols"
    date_expr = f"MAX({date_column}) AS latest_date" if date_column else "NULL AS latest_date"
    frame = _read_query(
        store,
        f"SELECT COUNT(*) AS row_count, {symbol_expr}, {date_expr} FROM {table_name}",
    )
    if frame.empty:
        return {
            "table_name": table_name,
            "row_count": 0,
            "distinct_symbols": 0,
            "latest_date": "",
            "note": "表不存在或不可读。",
        }
    row = frame.iloc[0]
    return {
        "table_name": table_name,
        "row_count": _blank_if_na(row.get("row_count")),
        "distinct_symbols": _blank_if_na(row.get("distinct_symbols")),
        "latest_date": _blank_if_na(row.get("latest_date")),
        "note": "",
    }


def _settings_sheet(settings: Any) -> pd.DataFrame:
    if hasattr(settings, "model_dump"):
        values = settings.model_dump()
    else:
        values = {key: value for key, value in vars(settings).items() if not key.startswith("_")}
    rows = []
    for key, value in sorted(values.items()):
        lower = key.lower()
        if any(marker in lower for marker in SENSITIVE_KEYWORDS):
            continue
        rows.append({"config_key": key, "config_value": str(value)})
    return pd.DataFrame(rows)


def _build_summary_sheet(
    *,
    selected_trade_date: str,
    output_path: str | Path | None,
    strategy_rows: int,
    elder_rows: int,
    entry_zone_rows: int,
    watchlist_rows: int,
    external_position_rows: int,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"metric": "导出时间", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            {"metric": "研究日期", "value": selected_trade_date or "暂无"},
            {"metric": "今日候选数量", "value": strategy_rows},
            {"metric": "埃尔德复核记录数量", "value": elder_rows},
            {"metric": "买入区间记录数量", "value": entry_zone_rows},
            {"metric": "观察池记录数量", "value": watchlist_rows},
            {"metric": "外部模拟持仓记录数量", "value": external_position_rows},
            {"metric": "输出文件", "value": str(output_path or "默认 reports/daily_research_*.xlsx")},
            {"metric": "说明", "value": "仅供个人研究使用，不自动交易。"},
        ]
    )


def _help_sheet() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"section": "工作簿用途", "description": "汇总今日候选、技术复核、买入区间、观察池、外部模拟持仓和数据质量。"},
            {"section": "排序口径", "description": "display_order 为当前工作表显示序号；candidate_rank 保留今日选股原始排名。"},
            {"section": "只读原则", "description": "导出命令只读取 DuckDB，不更新行情、不重算因子、不改变 total_score。"},
            {"section": "缺失数据", "description": "某些工作表显示暂无数据时，请先运行对应本地命令生成持久化结果。"},
            {"section": "提示", "description": "个人研究工具，结果需自行复核。"},
        ]
    )


def _preferred_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=columns)
    available = [column for column in columns if column in frame.columns]
    return frame.loc[:, available].copy()


def _with_display_order(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.reset_index(drop=True).copy()
    if "display_order" in frame.columns:
        frame = frame.drop(columns=["display_order"])
    frame.insert(0, "display_order", range(1, len(frame) + 1))
    return frame


def _empty_if_needed(frame: pd.DataFrame, message: str) -> pd.DataFrame:
    if frame.empty:
        return _message_frame(message)
    return frame


def _message_frame(message: str) -> pd.DataFrame:
    return pd.DataFrame([{"message": message}])


def _resolve_output_path(output_path: str | Path | None, trade_date: str) -> Path:
    if output_path is not None:
        return Path(output_path)
    timestamp = datetime.now().strftime("%H%M%S")
    date_part = trade_date or datetime.now().strftime("%Y%m%d")
    return PROJECT_ROOT / "reports" / f"daily_research_{date_part}_{timestamp}.xlsx"


def _write_sheet(workbook: Workbook, sheet_name: str, frame: pd.DataFrame) -> None:
    worksheet = workbook.create_sheet(sheet_name)
    frame = frame.copy()
    if frame.empty:
        frame = _message_frame("暂无数据。")
    worksheet.append(list(frame.columns))
    for row in frame.itertuples(index=False):
        worksheet.append([_excel_value(value) for value in row])

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    for column_cells in worksheet.columns:
        column_letter = get_column_letter(column_cells[0].column)
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 10), 36)


def _excel_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 6)
    return value


def _blank_if_na(value: Any) -> Any:
    if pd.isna(value):
        return ""
    return value


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Export daily research workbook.")
    parser.add_argument("--trade-date", default=None, help="Trade date in YYYYMMDD; default latest local selection date.")
    parser.add_argument("--output", default=None, help="Output .xlsx path; default reports/daily_research_*.xlsx.")
    parser.add_argument("--format", default="xlsx", choices=["xlsx"], help="Output format. Only xlsx is supported.")
    parser.add_argument(
        "--include-external-positions",
        dest="include_external_positions",
        action="store_true",
        default=True,
        help="Include external simulated positions sheet. Enabled by default.",
    )
    parser.add_argument(
        "--no-include-external-positions",
        dest="include_external_positions",
        action="store_false",
        help="Skip external simulated positions sheet.",
    )
    parser.add_argument(
        "--include-data-quality",
        dest="include_data_quality",
        action="store_true",
        default=True,
        help="Include data quality sheet. Enabled by default.",
    )
    parser.add_argument(
        "--no-include-data-quality",
        dest="include_data_quality",
        action="store_false",
        help="Skip data quality sheet.",
    )
    args = parser.parse_args(argv)

    result = export_daily_research_workbook(
        trade_date=args.trade_date,
        output_path=args.output,
        include_external_positions=args.include_external_positions,
        include_data_quality=args.include_data_quality,
    )
    print("每日研究工作簿导出完成")
    print(f"研究日期: {result.trade_date or '暂无'}")
    print(f"今日候选: {result.strategy_rows}")
    print(f"埃尔德复核: {result.elder_rows}")
    print(f"买入区间: {result.entry_zone_rows}")
    print(f"观察池: {result.watchlist_rows}")
    print(f"外部模拟持仓: {result.external_position_rows}")
    print(f"输出文件: {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
