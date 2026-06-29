"""Export candidate stock review reports for manual validation."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.jobs.diagnose_factors import diagnose_factors
from core.jobs.run_daily_selection import run_daily_selection
from core.reporting.selection_review_report import (
    build_console_summary,
    build_selection_review_report,
    save_selection_review_report,
)
from core.sample_data import get_sample_dashboard_data
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.strategy.selector import select_top_stocks
from core.technical.elder import build_elder_review


def export_selection_review(
    *,
    top_n: int = 20,
    output_dir: Path | str = "reports",
    report_format: str = "all",
    use_existing: bool = False,
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Export current candidate stocks as manual review reports.

    The export only uses local DuckDB or sample data. It does not fetch external
    APIs, change strategy rules, provide target prices, or create trading
    actions.
    """
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    payload = _load_selection_payload(resolved_settings, resolved_store, top_n, use_existing)
    metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_provider": resolved_settings.data_provider,
        "duckdb_path": str(resolved_store.db_path),
        "use_existing": use_existing,
    }
    report = build_selection_review_report(
        metadata=metadata,
        selection_summary=payload["selection_summary"],
        selection_df=payload["selection_df"],
        factor_df=payload["factor_df"],
        price_df=payload["price_df"],
        daily_basic_df=payload["daily_basic_df"],
        data_quality_notes=payload["data_quality_notes"],
        top_n=top_n,
    )
    files = save_selection_review_report(report, output_dir=output_dir, report_format=report_format)
    if not quiet:
        print(build_console_summary(report, files))
    return {"status": "success", "report": report, "generated_files": files}


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and export a selection review report."""
    parser = argparse.ArgumentParser(description="Export candidate stock review reports.")
    parser.add_argument("--top-n", type=int, default=20, help="Number of candidates to export.")
    parser.add_argument("--output-dir", default="reports", help="Report output directory.")
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "csv", "all"],
        default="all",
        help="Report format.",
    )
    parser.add_argument("--use-existing", action="store_true", help="Prefer existing DB selection tables.")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    args = parser.parse_args(argv)

    export_selection_review(
        top_n=args.top_n,
        output_dir=args.output_dir,
        report_format=args.format,
        use_existing=args.use_existing,
        quiet=args.quiet,
    )


def _load_selection_payload(
    settings: Settings,
    store: DuckDBStore,
    top_n: int,
    use_existing: bool,
) -> dict[str, Any]:
    """Load existing or computed local selection data for review export."""
    summary = run_daily_selection(settings=settings, store=store)
    if use_existing:
        existing = _load_existing_tables(store, top_n)
        if existing is not None:
            existing["selection_summary"] = summary
            return existing

    diagnostic = diagnose_factors(settings=settings, store=store)
    factor_df = diagnostic.get("factor_scores_df", pd.DataFrame())
    if not factor_df.empty:
        selection_df = select_top_stocks(factor_df, top_n=top_n)
        price_df = _safe_read_table(store, "daily_price")
        daily_basic_df = _safe_read_table(store, "daily_basic")
        stock_basic_df = _safe_read_table(store, "stock_basic")
        if summary.get("fallback_to_sample") or not summary.get("is_real_data"):
            sample = get_sample_dashboard_data()
            price_df = sample["price"]
            daily_basic_df = sample["daily_basic"]
            stock_basic_df = sample.get("stock_basic", pd.DataFrame())
        return {
            "selection_summary": summary,
            "selection_df": _attach_elder_fields(
                _attach_stock_basic_fields(selection_df, stock_basic_df),
                price_df,
            ),
            "factor_df": factor_df,
            "price_df": price_df,
            "daily_basic_df": daily_basic_df,
            "data_quality_notes": diagnostic.get("data_quality_notes", []),
        }

    sample = get_sample_dashboard_data()
    return {
        "selection_summary": summary,
        "selection_df": _attach_elder_fields(sample["selection"].head(top_n).copy(), sample["price"]),
        "factor_df": sample["factor_scores"],
        "price_df": sample["price"],
        "daily_basic_df": sample["daily_basic"],
        "data_quality_notes": ["当前为 sample 演示数据，仅用于流程验证。"],
    }


def _load_existing_tables(store: DuckDBStore, top_n: int) -> dict[str, Any] | None:
    """Load persisted strategy/factor tables when available."""
    selection = _safe_read_table(store, "strategy_result")
    factor_scores = _safe_read_table(store, "factor_scores")
    if selection.empty:
        return None
    if "rank" in selection.columns:
        selection = selection.sort_values(["trade_date", "rank"]).head(top_n)
    else:
        selection = selection.head(top_n)
    stock_basic = _safe_read_table(store, "stock_basic")
    return {
        "selection_df": _attach_elder_fields(_attach_stock_basic_fields(selection, stock_basic), _safe_read_table(store, "daily_price")),
        "factor_df": factor_scores,
        "price_df": _safe_read_table(store, "daily_price"),
        "daily_basic_df": _safe_read_table(store, "daily_basic"),
        "data_quality_notes": [],
    }


def _safe_read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    """Read a table and return an empty frame when it is unavailable."""
    try:
        return store.read_table(table_name)
    except DuckDBStoreError:
        return pd.DataFrame()


def _attach_stock_basic_fields(selection_df: pd.DataFrame, stock_basic_df: pd.DataFrame) -> pd.DataFrame:
    """Fill descriptive fields from stock_basic without changing strategy output."""
    if selection_df.empty or stock_basic_df.empty or "ts_code" not in selection_df.columns or "ts_code" not in stock_basic_df.columns:
        return selection_df.copy()
    fields = ["industry", "market", "list_date"]
    basic_columns = ["ts_code", *[column for column in fields if column in stock_basic_df.columns]]
    if len(basic_columns) == 1:
        return selection_df.copy()

    result = selection_df.copy()
    basic = stock_basic_df[basic_columns].drop_duplicates(subset=["ts_code"], keep="last").copy()
    merged = result.merge(basic, on="ts_code", how="left", suffixes=("", "_stock_basic"))
    for field in fields:
        stock_field = f"{field}_stock_basic"
        if field not in merged.columns:
            merged[field] = pd.NA
        if stock_field in merged.columns:
            merged[field] = merged[field].where(~merged[field].map(_is_missing), merged[stock_field])
            merged = merged.drop(columns=[stock_field])
    return merged


def _attach_elder_fields(selection_df: pd.DataFrame, price_df: pd.DataFrame) -> pd.DataFrame:
    """Attach Elder review fields without changing candidate ordering."""
    if selection_df.empty:
        return selection_df.copy()
    review = build_elder_review(selection_df, price_df)
    if review.empty:
        return selection_df.copy()
    elder_columns = [
        "ts_code",
        "trade_date",
        "elder_score",
        "action_hint",
        "elder_reason",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
        "review_action",
    ]
    available = [column for column in elder_columns if column in review.columns]
    result = selection_df.copy()
    result["_original_order"] = range(len(result))
    join_keys = ["ts_code", "trade_date"] if "trade_date" in result.columns and "trade_date" in review.columns else ["ts_code"]
    merged = result.merge(review[available], on=join_keys, how="left", suffixes=("", "_elder"))
    merged = merged.sort_values("_original_order").drop(columns=["_original_order"]).reset_index(drop=True)
    return merged


def _is_missing(value: Any) -> bool:
    """Return True for missing or empty report cells."""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"", "nan", "none", "<na>", "null"}


if __name__ == "__main__":
    main()
