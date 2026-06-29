"""Historical validation for Elder technical review signals."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.sample_data import get_sample_dashboard_data
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.technical.elder import _classify_elder_state, _review_action, calculate_elder_indicators


DETAIL_COLUMNS = [
    "signal_date",
    "rank",
    "ts_code",
    "name",
    "total_score",
    "total_score_group",
    "market_stage",
    "elder_score",
    "elder_score_group",
    "action_hint",
    "review_action",
    "forward_return_5d",
    "forward_return_10d",
    "forward_return_20d",
    "max_drawdown_20d",
    "max_gain_20d",
    "close",
]


def backtest_elder_review(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    output_dir: Path | str = "reports",
    report_format: str = "all",
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    use_sample: bool = True,
) -> dict[str, Any]:
    """Run a historical Elder review validation from local data only.

    Signals for a given date are calculated using price rows up to and
    including that date. Forward returns and drawdown/gain metrics are computed
    afterwards from future rows, so they are never part of signal generation.
    """
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    payload = _load_price_payload(resolved_settings, resolved_store, use_sample)
    price_df = _filter_price_window(payload["price_df"], start_date, end_date)
    details = build_elder_backtest_details(price_df)
    summary = summarize_elder_backtest(details)
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_source": payload["data_source"],
        "start_date": start_date or _min_date(price_df),
        "end_date": end_date or _max_date(price_df),
        "sample_stock_count": _nunique(price_df, "ts_code"),
        "valid_signal_count": int(len(details)),
        "candidate_signal_count": summary["candidate_signal_count"],
        "elder_score_group_summary": summary["elder_score_group_summary"],
        "action_hint_summary": summary["action_hint_summary"],
        "candidate_action_hint_summary": summary["candidate_action_hint_summary"],
        "total_score_group_summary": summary["total_score_group_summary"],
        "market_stage_summary": summary["market_stage_summary"],
        "market_stage_action_hint_summary": summary["market_stage_action_hint_summary"],
        "has_reverse_signal": summary["has_reverse_signal"],
        "skip_reasons": _skip_reasons(price_df, details),
        "details_df": details,
        "risk_note": "该回看只用于个人研究，不构成交易建议。",
    }
    files = save_elder_backtest_report(result, output_dir=output_dir, report_format=report_format)
    result["generated_files"] = files
    return result


def build_elder_backtest_details(
    price_df: pd.DataFrame,
    min_history_rows: int = 35,
    min_forward_rows: int = 20,
) -> pd.DataFrame:
    """Build per-stock per-date Elder signals and future performance details."""
    required = {"ts_code", "trade_date", "high", "low", "close"}
    if price_df.empty or not required.issubset(price_df.columns):
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    rows: list[dict[str, Any]] = []
    source = price_df.copy()
    source["trade_date"] = source["trade_date"].astype(str)
    indicators = calculate_elder_indicators(source)
    weekly_lookup = _calculate_weekly_trend_history(source)
    market_stage_lookup = _market_stage_by_date(source)
    for ts_code, group in source.groupby("ts_code", sort=False):
        history = group.sort_values("trade_date").reset_index(drop=True)
        indicator_history = indicators[indicators["ts_code"].astype(str) == str(ts_code)].sort_values("trade_date").reset_index(drop=True)
        if indicator_history.empty:
            continue
        weekly_for_symbol = weekly_lookup[weekly_lookup["ts_code"].astype(str) == str(ts_code)].sort_values("trade_date").reset_index(drop=True)
        weekly_index = -1
        for idx in range(min_history_rows - 1, len(history) - min_forward_rows):
            current = history.iloc[idx]
            signal_date = str(current["trade_date"])
            if idx >= len(indicator_history) or str(indicator_history.iloc[idx]["trade_date"]) != signal_date:
                latest_rows = indicator_history[indicator_history["trade_date"].astype(str) <= signal_date]
                if len(latest_rows) < min_history_rows:
                    continue
                latest = latest_rows.iloc[-1]
                previous = latest_rows.iloc[-2] if len(latest_rows) >= 2 else latest
            elif idx + 1 < min_history_rows:
                continue
            else:
                latest = indicator_history.iloc[idx]
                previous = indicator_history.iloc[idx - 1] if idx >= 1 else latest
            while weekly_index + 1 < len(weekly_for_symbol) and str(weekly_for_symbol.iloc[weekly_index + 1]["trade_date"]) <= signal_date:
                weekly_index += 1
            weekly_row = weekly_for_symbol.iloc[weekly_index] if weekly_index >= 0 else None
            elder_score, action_hint, elder_reason, signals = _classify_elder_state(latest, previous, weekly_row)
            metrics = calculate_forward_metrics(history, idx)
            row = {
                "signal_date": signal_date,
                "rank": current.get("rank"),
                "ts_code": ts_code,
                "name": current.get("name", ""),
                "total_score": _to_float(current.get("total_score")),
                "total_score_group": total_score_group(current.get("total_score")),
                "market_stage": market_stage_lookup.get(signal_date, "unknown"),
                "close": _to_float(current.get("close")),
                "elder_score": elder_score,
                "action_hint": action_hint,
                "elder_reason": elder_reason,
                "review_action": _review_action(action_hint),
                "weekly_trend": signals.get("weekly_trend"),
                "daily_pullback": signals.get("daily_pullback"),
                "force_signal": signals.get("force_signal"),
                "elder_ray_signal": signals.get("elder_ray_signal"),
                **metrics,
            }
            for column in [
                "ema13",
                "ema22",
                "macd",
                "macd_signal",
                "macd_histogram",
                "macd_histogram_slope",
                "force_index_2d",
                "force_index_13d",
                "bull_power",
                "bear_power",
                "close_to_ema13_pct",
                "close_to_ema22_pct",
            ]:
                row[column] = _to_float(latest.get(column))
            row["elder_score_group"] = elder_score_group(row.get("elder_score"))
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=DETAIL_COLUMNS)
    result = pd.DataFrame(rows)
    for column in DETAIL_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result


def calculate_forward_metrics(price_history: pd.DataFrame, signal_index: int) -> dict[str, float | None]:
    """Calculate forward returns, max drawdown and max gain from future closes."""
    closes = pd.to_numeric(price_history["close"], errors="coerce").reset_index(drop=True)
    if signal_index >= len(closes) or pd.isna(closes.iloc[signal_index]):
        return _empty_forward_metrics()
    current_close = float(closes.iloc[signal_index])
    if current_close == 0:
        return _empty_forward_metrics()
    future = closes.iloc[signal_index + 1 : signal_index + 21].dropna()
    metrics = {
        "forward_return_5d": _forward_return(closes, signal_index, 5),
        "forward_return_10d": _forward_return(closes, signal_index, 10),
        "forward_return_20d": _forward_return(closes, signal_index, 20),
        "max_drawdown_20d": None,
        "max_gain_20d": None,
    }
    if not future.empty:
        metrics["max_drawdown_20d"] = float(future.min() / current_close - 1)
        metrics["max_gain_20d"] = float(future.max() / current_close - 1)
    return metrics


def elder_score_group(value: Any) -> str:
    """Group elder_score into top/middle/bottom buckets."""
    score = _to_float(value)
    if score is None:
        return "unknown"
    if score >= 75:
        return "top"
    if score >= 45:
        return "middle"
    return "bottom"


def total_score_group(value: Any) -> str:
    """Group total_score for layered Elder validation."""
    score = _to_float(value)
    if score is None:
        return "unknown"
    if score >= 70:
        return "high"
    if score >= 45:
        return "middle"
    return "low"


def summarize_elder_backtest(details: pd.DataFrame) -> dict[str, Any]:
    """Summarize future performance by score group and action_hint."""
    candidate_details = _candidate_details(details)
    return {
        "candidate_signal_count": int(len(candidate_details)),
        "elder_score_group_summary": _group_summary(details, "elder_score_group"),
        "action_hint_summary": _group_summary(details, "action_hint"),
        "candidate_action_hint_summary": _group_summary(candidate_details, "action_hint"),
        "total_score_group_summary": _group_summary(details, "total_score_group"),
        "market_stage_summary": _group_summary(details, "market_stage"),
        "market_stage_action_hint_summary": _two_level_group_summary(details, "market_stage", "action_hint"),
        "has_reverse_signal": _has_reverse_signal(details),
    }


def save_elder_backtest_report(
    result: dict[str, Any],
    output_dir: Path | str = "reports",
    report_format: str = "all",
) -> dict[str, str]:
    """Save Markdown/CSV/JSON Elder backtest reports."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formats = ["markdown", "csv", "json"] if report_format == "all" else [report_format]
    paths: dict[str, str] = {}
    for fmt in formats:
        if fmt == "markdown":
            path = directory / f"elder_backtest_{timestamp}.md"
            path.write_text(render_elder_backtest_markdown(result), encoding="utf-8")
        elif fmt == "csv":
            path = directory / f"elder_backtest_{timestamp}.csv"
            result["details_df"].to_csv(path, index=False, encoding="utf-8-sig")
        elif fmt == "json":
            path = directory / f"elder_backtest_{timestamp}.json"
            payload = {**result, "details_df": result["details_df"].to_dict("records")}
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        else:
            raise ValueError("report_format must be markdown, csv, json, or all")
        paths[fmt] = str(path)
    return paths


def render_elder_backtest_markdown(result: dict[str, Any]) -> str:
    """Render Elder backtest summary as Markdown."""
    lines = [
        "# 埃尔德复核历史回看",
        "",
        f"- 运行时间: {result.get('generated_at')}",
        f"- 数据来源: {result.get('data_source')}",
        f"- 样本区间: {result.get('start_date') or '暂无'} 至 {result.get('end_date') or '暂无'}",
        f"- 样本股票数量: {result.get('sample_stock_count', 0)}",
        f"- 有效信号数量: {result.get('valid_signal_count', 0)}",
        f"- 当前候选/selection_review 样本信号数量: {result.get('candidate_signal_count', 0)}",
        f"- 是否存在明显反向信号: {'是' if result.get('has_reverse_signal') else '否'}",
        f"- 解释口径: elder_score 是技术状态 / 节奏复核分，不是买入优先级或收益预测。",
        "",
        "## elder_score 分组表现",
        "",
        *_summary_table_lines(result.get("elder_score_group_summary", []), "elder_score_group"),
        "",
        "## action_hint 分组表现",
        "",
        *_summary_table_lines(result.get("action_hint_summary", []), "action_hint"),
        "",
        "## 当前候选 / selection_review 样本表现",
        "",
        *_summary_table_lines(result.get("candidate_action_hint_summary", []), "action_hint"),
        "",
        "## total_score 分层后的 elder 表现",
        "",
        *_summary_table_lines(result.get("total_score_group_summary", []), "total_score_group"),
        "",
        "## 市场阶段分层表现",
        "",
        *_summary_table_lines(result.get("market_stage_summary", []), "market_stage"),
        "",
        "## 市场阶段 x action_hint",
        "",
        *_summary_table_lines(result.get("market_stage_action_hint_summary", []), "market_stage/action_hint"),
        "",
        "## action_hint 解释",
        "",
        "- 趋势确认，进入人工复核：表示技术节奏具备人工复核条件，不表示收益预测或买入优先级。",
        "- 趋势尚可，等待回调：趋势结构尚可，但节奏或位置仍需等待更合适的复核点。",
        "- 短线过热，不追：短期回撤风险偏高，但不等于中期趋势差，可作为等待回调或移动止损观察信号。",
        "- 趋势偏弱，暂缓：周线或短线结构未改善，先降低技术复核优先度。",
        "",
        "## 数据不足或跳过原因",
        "",
        *[f"- {item}" for item in result.get("skip_reasons", [])],
        "",
        "## 风险提示",
        "",
        f"- {result.get('risk_note', '该回看只用于个人研究，不构成交易建议。')}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Parse CLI args and run Elder backtest validation."""
    parser = argparse.ArgumentParser(description="Backtest Elder review signals from local data.")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--format", choices=["text", "markdown", "csv", "json", "all"], default="text")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args(argv)

    report_format = "all" if args.format == "text" else args.format
    result = backtest_elder_review(
        start_date=args.start_date,
        end_date=args.end_date,
        report_format=report_format,
        output_dir=args.output_dir,
    )
    if args.format == "markdown":
        print(render_elder_backtest_markdown(result))
        return
    print("埃尔德复核历史回看摘要")
    print(f"- 数据来源: {result['data_source']}")
    print(f"- 样本区间: {result.get('start_date') or '暂无'} 至 {result.get('end_date') or '暂无'}")
    print(f"- 样本股票数量: {result['sample_stock_count']}")
    print(f"- 有效信号数量: {result['valid_signal_count']}")
    print(f"- 当前候选/selection_review 样本信号数量: {result['candidate_signal_count']}")
    print(f"- 是否存在明显反向信号: {'是' if result['has_reverse_signal'] else '否'}")
    print("- elder_score 口径: 技术状态 / 节奏复核分，不代表买入优先级。")
    print(f"- 生成文件: {', '.join(result.get('generated_files', {}).values())}")
    print(f"- 风险提示: {result['risk_note']}")


def _load_price_payload(settings: Settings, store: DuckDBStore, use_sample: bool) -> dict[str, Any]:
    if settings.data_provider != "sample" and store.db_path.exists():
        try:
            price = store.read_table("daily_price")
            stock_basic = store.read_table("stock_basic")
        except DuckDBStoreError:
            price = pd.DataFrame()
            stock_basic = pd.DataFrame()
        if not price.empty:
            if not stock_basic.empty and "ts_code" in stock_basic.columns:
                columns = [column for column in ["ts_code", "name", "industry"] if column in stock_basic.columns]
                price = price.merge(stock_basic[columns].drop_duplicates("ts_code"), on="ts_code", how="left")
            return {"data_source": f"{settings.data_provider} 本地 DuckDB 真实数据", "price_df": price}
    if use_sample:
        data = get_sample_dashboard_data()
        price = data.get("price", pd.DataFrame()).copy()
        basic = data.get("stock_basic", pd.DataFrame())
        if not price.empty and not basic.empty:
            price = price.merge(basic[["ts_code", "name", "industry"]], on="ts_code", how="left")
        return {"data_source": "sample 数据（演示）", "price_df": price}
    return {"data_source": "无数据", "price_df": pd.DataFrame()}


def _filter_price_window(price_df: pd.DataFrame, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    if price_df.empty or "trade_date" not in price_df.columns:
        return price_df
    df = price_df.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    if start_date:
        df = df[df["trade_date"] >= str(start_date)]
    if end_date:
        df = df[df["trade_date"] <= str(end_date)]
    return df.reset_index(drop=True)


def _calculate_weekly_trend_history(price_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate historical weekly trend rows without using incomplete future weeks."""
    required = {"ts_code", "trade_date", "high", "low", "close"}
    if price_df.empty or not required.issubset(price_df.columns):
        return pd.DataFrame(columns=["ts_code", "trade_date", "weekly_trend_improving"])

    source = price_df.copy()
    if "vol" not in source.columns:
        source["vol"] = source["amount"] if "amount" in source.columns else 0.0
    rows: list[pd.DataFrame] = []
    for ts_code, group in source.groupby("ts_code", sort=False):
        df = group.sort_values("trade_date").copy()
        df["date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["date"]).set_index("date")
        if df.empty:
            continue
        for column in ["high", "low", "close", "vol"]:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        weekly = (
            df.resample("W-FRI")
            .agg({"high": "max", "low": "min", "close": "last", "vol": "sum", "trade_date": "last"})
            .dropna(subset=["close"])
            .reset_index(drop=True)
        )
        if weekly.empty:
            continue
        indicators = calculate_elder_indicators(weekly.assign(ts_code=ts_code))
        if indicators.empty:
            continue
        indicators["weekly_trend_improving"] = (
            (pd.to_numeric(indicators["close"], errors="coerce") >= pd.to_numeric(indicators["ema13"], errors="coerce"))
            & (
                (pd.to_numeric(indicators["ema13"], errors="coerce") >= pd.to_numeric(indicators["ema22"], errors="coerce"))
                | (pd.to_numeric(indicators["macd_histogram_slope"], errors="coerce") > 0)
            )
        )
        indicators["weekly_reason"] = indicators["weekly_trend_improving"].map({True: "周线趋势改善。", False: "周线趋势仍偏弱。"})
        rows.append(indicators[["ts_code", "trade_date", "weekly_trend_improving", "weekly_reason"]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["ts_code", "trade_date", "weekly_trend_improving"])


def _market_stage_by_date(price_df: pd.DataFrame) -> dict[str, str]:
    """Classify market stage from sample average trailing 20-day returns."""
    if price_df.empty or not {"ts_code", "trade_date", "close"}.issubset(price_df.columns):
        return {}
    source = price_df.copy()
    source["trade_date"] = source["trade_date"].astype(str)
    frames = []
    for _, group in source.groupby("ts_code", sort=False):
        df = group.sort_values("trade_date").copy()
        close = pd.to_numeric(df["close"], errors="coerce")
        df["trailing_return_20d"] = close / close.shift(20) - 1
        frames.append(df[["trade_date", "trailing_return_20d"]])
    if not frames:
        return {}
    avg_by_date = pd.concat(frames, ignore_index=True).groupby("trade_date")["trailing_return_20d"].mean()
    stages: dict[str, str] = {}
    for trade_date, value in avg_by_date.items():
        if pd.isna(value):
            stages[str(trade_date)] = "unknown"
        elif float(value) >= 0.02:
            stages[str(trade_date)] = "strong"
        elif float(value) <= -0.02:
            stages[str(trade_date)] = "weak"
        else:
            stages[str(trade_date)] = "range"
    return stages


def _latest_weekly_for_date(weekly: pd.DataFrame, ts_code: str, signal_date: str) -> pd.Series | None:
    if weekly.empty or "ts_code" not in weekly.columns or "trade_date" not in weekly.columns:
        return None
    rows = weekly[(weekly["ts_code"].astype(str) == ts_code) & (weekly["trade_date"].astype(str) <= signal_date)]
    if rows.empty:
        return None
    return rows.sort_values("trade_date").iloc[-1]


def _group_summary(details: pd.DataFrame, group_col: str) -> list[dict[str, Any]]:
    if details.empty or group_col not in details.columns:
        return []
    rows = []
    for group_name, group in details.groupby(group_col, dropna=False):
        row: dict[str, Any] = {"group": str(group_name), "count": int(len(group))}
        for horizon in [5, 10, 20]:
            column = f"forward_return_{horizon}d"
            values = _numeric_column(group, column)
            row[f"avg_forward_return_{horizon}d"] = _mean(values)
            row[f"hit_rate_{horizon}d"] = _hit_rate(values)
        row["avg_max_drawdown_20d"] = _mean(_numeric_column(group, "max_drawdown_20d"))
        row["avg_max_gain_20d"] = _mean(_numeric_column(group, "max_gain_20d"))
        rows.append(row)
    return sorted(rows, key=lambda item: item["group"])


def _two_level_group_summary(details: pd.DataFrame, first_col: str, second_col: str) -> list[dict[str, Any]]:
    if details.empty or first_col not in details.columns or second_col not in details.columns:
        return []
    source = details.copy()
    source[f"{first_col}/{second_col}"] = source[first_col].astype(str) + "/" + source[second_col].astype(str)
    return _group_summary(source, f"{first_col}/{second_col}")


def _candidate_details(details: pd.DataFrame) -> pd.DataFrame:
    if details.empty:
        return details
    mask = pd.Series(False, index=details.index)
    if "rank" in details.columns:
        mask = mask | pd.to_numeric(details["rank"], errors="coerce").notna()
    if "total_score" in details.columns:
        mask = mask | pd.to_numeric(details["total_score"], errors="coerce").notna()
    return details[mask].copy()


def _numeric_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def _summary_table_lines(rows: list[dict[str, Any]], label: str) -> list[str]:
    if not rows:
        return ["暂无有效样本。"]
    lines = [
        f"| {label} | count | avg_5d | hit_5d | avg_10d | hit_10d | avg_20d | hit_20d | max_dd_20d | max_gain_20d |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {group} | {count} | {avg5} | {hit5} | {avg10} | {hit10} | {avg20} | {hit20} | {dd20} | {gain20} |".format(
                group=row["group"],
                count=row["count"],
                avg5=_fmt_pct(row.get("avg_forward_return_5d")),
                hit5=_fmt_pct(row.get("hit_rate_5d")),
                avg10=_fmt_pct(row.get("avg_forward_return_10d")),
                hit10=_fmt_pct(row.get("hit_rate_10d")),
                avg20=_fmt_pct(row.get("avg_forward_return_20d")),
                hit20=_fmt_pct(row.get("hit_rate_20d")),
                dd20=_fmt_pct(row.get("avg_max_drawdown_20d")),
                gain20=_fmt_pct(row.get("avg_max_gain_20d")),
            )
        )
    return lines


def _forward_return(closes: pd.Series, signal_index: int, horizon: int) -> float | None:
    target = signal_index + horizon
    if target >= len(closes):
        return None
    current = closes.iloc[signal_index]
    future = closes.iloc[target]
    if pd.isna(current) or pd.isna(future) or float(current) == 0:
        return None
    return float(future / current - 1)


def _empty_forward_metrics() -> dict[str, None]:
    return {
        "forward_return_5d": None,
        "forward_return_10d": None,
        "forward_return_20d": None,
        "max_drawdown_20d": None,
        "max_gain_20d": None,
    }


def _has_reverse_signal(details: pd.DataFrame) -> bool:
    if details.empty or "elder_score_group" not in details.columns:
        return False
    summary = {row["group"]: row for row in _group_summary(details, "elder_score_group")}
    top = summary.get("top", {}).get("avg_forward_return_20d")
    bottom = summary.get("bottom", {}).get("avg_forward_return_20d")
    return top is not None and bottom is not None and top < bottom


def _skip_reasons(price_df: pd.DataFrame, details: pd.DataFrame) -> list[str]:
    reasons: list[str] = []
    if price_df.empty:
        reasons.append("daily_price 无可用数据。")
    if details.empty:
        reasons.append("有效信号为空，可能是历史天数不足或缺少未来 20 日价格。")
    if not reasons:
        reasons.append("部分临近样本结束日期的信号因缺少未来 20 日价格被跳过。")
    return reasons


def _nunique(df: pd.DataFrame, column: str) -> int:
    if df.empty or column not in df.columns:
        return 0
    return int(df[column].nunique())


def _min_date(df: pd.DataFrame) -> str | None:
    if df.empty or "trade_date" not in df.columns:
        return None
    values = df["trade_date"].dropna().astype(str)
    return str(values.min()) if not values.empty else None


def _max_date(df: pd.DataFrame) -> str | None:
    if df.empty or "trade_date" not in df.columns:
        return None
    values = df["trade_date"].dropna().astype(str)
    return str(values.max()) if not values.empty else None


def _mean(values: pd.Series) -> float | None:
    clean = values.dropna()
    return None if clean.empty else float(clean.mean())


def _hit_rate(values: pd.Series) -> float | None:
    clean = values.dropna()
    return None if clean.empty else float((clean > 0).mean())


def _to_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(converted) else converted


def _fmt_pct(value: Any) -> str:
    number = _to_float(value)
    return "暂无" if number is None else f"{number:.2%}"


if __name__ == "__main__":
    main()
