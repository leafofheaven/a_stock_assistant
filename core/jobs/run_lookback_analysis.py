"""Run read-only lookback analysis for persisted local research signals."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.storage.duckdb_store import DUCKDB_LOCK_MESSAGE, DuckDBStore, DuckDBStoreError, DuckDBStoreLockedError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS_PATH = PROJECT_ROOT / "data" / "runtime" / "lookback_analysis_status.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "lookback"
DEFAULT_HORIZONS = [1, 3, 5, 10, 20]

LOOKBACK_COLUMN_LABELS = {
    "section": "项目（section）",
    "metric": "指标（metric）",
    "value": "内容（value）",
    "research_date": "研究日期（research_date）",
    "as_of_trade_date": "回看截止交易日（as_of_trade_date）",
    "sample_period": "样本区间（sample_period）",
    "horizons": "回看周期（horizons）",
    "group_dimension": "分组维度（group_dimension）",
    "group": "分组（group）",
    "horizon": "回看周期（horizon）",
    "sample_count": "样本数量（sample_count）",
    "valid_sample_count": "可用样本数量（valid_sample_count）",
    "avg_forward_return": "平均收益（avg_forward_return）",
    "median_forward_return": "中位数收益（median_forward_return）",
    "win_rate": "胜率（win_rate）",
    "up_gt_3pct_rate": "上涨超过3%比例（up_gt_3pct_rate）",
    "down_gt_3pct_rate": "下跌超过3%比例（down_gt_3pct_rate）",
    "avg_max_drawdown": "平均最大回撤（avg_max_drawdown）",
    "median_max_drawdown": "中位数最大回撤（median_max_drawdown）",
    "avg_max_runup": "平均最大上冲（avg_max_runup）",
    "hit_stop_loss_rate": "触及止损比例（hit_stop_loss_rate）",
    "hit_target_rate": "触及目标比例（hit_target_rate）",
    "insufficient_forward_data_count": "数据不足数量（insufficient_forward_data_count）",
    "trade_date": "基准交易日（trade_date）",
    "ts_code": "股票代码（ts_code）",
    "name": "股票名称（name）",
    "industry": "行业（industry）",
    "entry_close": "基准收盘价（entry_close）",
    "future_close": "未来收盘价（future_close）",
    "forward_return": "未来收益（forward_return）",
    "max_drawdown": "最大回撤（max_drawdown）",
    "max_runup": "最大上冲（max_runup）",
    "hit_stop_loss": "是否触及止损（hit_stop_loss）",
    "hit_target": "是否触及目标价（hit_target）",
    "available_forward_days": "可用未来交易日数（available_forward_days）",
    "data_quality_flag": "数据质量标记（data_quality_flag）",
    "total_score": "综合分（total_score）",
    "trend_score": "趋势分（trend_score）",
    "momentum_score": "动量分（momentum_score）",
    "liquidity_score": "流动性分（liquidity_score）",
    "fundamental_score": "基本面分（fundamental_score）",
    "volatility_score": "波动分（volatility_score）",
    "elder_score": "埃尔德分（elder_score）",
    "action_hint": "操作提示（action_hint）",
    "weekly_trend": "周线趋势（weekly_trend）",
    "daily_pullback": "日线回调（daily_pullback）",
    "force_signal": "强力指数信号（force_signal）",
    "elder_ray_signal": "埃尔德射线信号（elder_ray_signal）",
    "entry_zone_status": "买入区间状态（entry_zone_status）",
    "chase_risk": "追高风险（chase_risk）",
    "reward_risk_ratio": "盈亏比（reward_risk_ratio）",
    "risk_pct": "风险比例（risk_pct）",
    "watch_status": "观察状态（watch_status）",
    "watch_status_label": "观察状态说明（watch_status_label）",
    "watch_days": "观察天数（watch_days）",
    "selected_count_5d": "近5日入选次数（selected_count_5d）",
    "selected_count_10d": "近10日入选次数（selected_count_10d）",
    "consecutive_selected_days": "连续入选天数（consecutive_selected_days）",
    "note": "说明（note）",
}


@dataclass(frozen=True)
class LookbackInputs:
    """Local input tables used for lookback analysis."""

    strategy_result: pd.DataFrame
    daily_price: pd.DataFrame
    entry_zone_snapshots: pd.DataFrame
    watchlist_daily_snapshots: pd.DataFrame


def run_lookback_analysis(
    *,
    as_of: str = "latest",
    start_date: str = "",
    end_date: str = "",
    horizons: list[int] | None = None,
    min_forward_days: int = 1,
    source: str = "strategy_result",
    include_elder: bool = True,
    include_entry_zone: bool = True,
    include_watchlist: bool = True,
    report_format: str = "text",
    output_path: str | Path | None = None,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    limit: int = 0,
    dry_run: bool = False,
    settings: Settings | Any | None = None,
    store: DuckDBStore | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run a read-only lookback analysis and optionally export an Excel report."""
    started_at = now or datetime.now()
    resolved_horizons = normalize_horizons(horizons)
    status_file = Path(status_path)
    status = _base_status(
        started_at=started_at,
        as_of=as_of,
        start_date=start_date,
        end_date=end_date,
        horizons=resolved_horizons,
        dry_run=dry_run,
    )
    _write_status(status_file, status)
    try:
        resolved_settings = settings or get_settings()
        resolved_store = store or DuckDBStore(getattr(resolved_settings, "duckdb_path", None))
        inputs = load_lookback_inputs(resolved_store)
        samples = build_lookback_samples(
            inputs,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
            source=source,
            include_elder=include_elder,
            include_entry_zone=include_entry_zone,
            include_watchlist=include_watchlist,
            limit=limit,
        )
        details = build_forward_return_details(samples, inputs.daily_price, resolved_horizons, min_forward_days=min_forward_days)
        summaries = summarize_lookback(details)
        as_of_trade_date = _resolve_as_of_trade_date(samples, as_of, end_date)
        report_path = Path(output_path) if output_path else _default_report_path(as_of_trade_date or started_at.strftime("%Y%m%d"))
        status.update(
            _status_from_analysis(
                started_at=started_at,
                as_of_trade_date=as_of_trade_date,
                samples=samples,
                details=details,
                summaries=summaries,
                report_path=report_path,
                dry_run=dry_run,
            )
        )
        status["stage"] = "dry_run" if dry_run else "export_report"
        _write_status(status_file, status)
        if not dry_run:
            save_lookback_workbook(
                report_path,
                status=status,
                summaries=summaries,
                details=details,
            )
            status["generated_report_path"] = str(report_path)
            status["report_exists"] = report_path.exists()
            status["report_size_bytes"] = report_path.stat().st_size if report_path.exists() else 0
        status["status"] = _final_status(details)
        status["summary"] = _summary_text(status)
        status["stage"] = "done"
        status["finished_at"] = (now or datetime.now()).isoformat(timespec="seconds")
        _write_status(status_file, status)
        return status
    except DuckDBStoreLockedError:
        status.update(_failed_status(started_at, DUCKDB_LOCK_MESSAGE))
        _write_status(status_file, status)
        return status
    except DuckDBStoreError as exc:
        status.update(_failed_status(started_at, str(exc)))
        _write_status(status_file, status)
        return status
    except Exception as exc:
        status.update(_failed_status(started_at, str(exc) or "自动回看分析失败。"))
        _write_status(status_file, status)
        return status


def load_lookback_inputs(store: DuckDBStore) -> LookbackInputs:
    """Read required local tables through read-only DuckDB connections."""
    return LookbackInputs(
        strategy_result=_read_table(store, "strategy_result"),
        daily_price=_read_table(store, "daily_price"),
        entry_zone_snapshots=_read_table(store, "entry_zone_snapshots"),
        watchlist_daily_snapshots=_read_table(store, "watchlist_daily_snapshots"),
    )


def build_lookback_samples(
    inputs: LookbackInputs,
    *,
    as_of: str = "latest",
    start_date: str = "",
    end_date: str = "",
    source: str = "strategy_result",
    include_elder: bool = True,
    include_entry_zone: bool = True,
    include_watchlist: bool = True,
    limit: int = 0,
) -> pd.DataFrame:
    """Build base samples from strategy_result and optional signal snapshots."""
    if source != "strategy_result":
        raise ValueError("Task 58 currently supports source=strategy_result only.")
    strategy = _normalize_date_column(inputs.strategy_result, "trade_date")
    if strategy.empty or "trade_date" not in strategy.columns:
        return pd.DataFrame()
    strategy = strategy.copy()
    resolved_end = _resolve_end_date(strategy, as_of, end_date)
    if start_date:
        strategy = strategy[strategy["trade_date"].astype(str) >= str(start_date)]
    if resolved_end:
        strategy = strategy[strategy["trade_date"].astype(str) <= str(resolved_end)]
    if "rank" in strategy.columns:
        strategy = strategy.sort_values(["trade_date", "rank", "ts_code"], na_position="last")
    elif "total_score" in strategy.columns:
        strategy = strategy.sort_values(["trade_date", "total_score"], ascending=[True, False], na_position="last")
    if limit and limit > 0:
        strategy = strategy.head(int(limit))
    samples = strategy.reset_index(drop=True).copy()
    if include_entry_zone:
        samples = _merge_latest_snapshot(
            samples,
            inputs.entry_zone_snapshots,
            columns=[
                "ts_code",
                "trade_date",
                "entry_low",
                "entry_high",
                "entry_mid",
                "stop_loss",
                "target_price",
                "reward_risk_ratio",
                "risk_pct",
                "reward_pct",
                "chase_risk",
                "entry_zone_status",
            ],
        )
    if include_watchlist:
        samples = _merge_latest_snapshot(
            samples,
            inputs.watchlist_daily_snapshots,
            columns=[
                "ts_code",
                "trade_date",
                "watch_status",
                "watch_status_label",
                "watch_days",
                "selected_count_5d",
                "selected_count_10d",
                "consecutive_selected_days",
            ],
        )
    if not include_elder:
        for column in ["elder_score", "action_hint", "weekly_trend", "daily_pullback", "force_signal", "elder_ray_signal"]:
            if column in samples.columns:
                samples = samples.drop(columns=[column])
    return samples.reset_index(drop=True)


def build_forward_return_details(
    samples: pd.DataFrame,
    daily_price: pd.DataFrame,
    horizons: list[int] | None = None,
    *,
    min_forward_days: int = 1,
) -> pd.DataFrame:
    """Calculate forward return details using per-stock future trading days."""
    resolved_horizons = normalize_horizons(horizons)
    if samples.empty or daily_price.empty:
        return pd.DataFrame(columns=_detail_columns())
    price = _normalize_date_column(daily_price, "trade_date").copy()
    required = {"ts_code", "trade_date", "close"}
    if not required.issubset(price.columns):
        return pd.DataFrame(columns=_detail_columns())
    for column in ["close", "high", "low"]:
        if column in price.columns:
            price[column] = pd.to_numeric(price[column], errors="coerce")
    grouped = {str(ts_code): frame.sort_values("trade_date").reset_index(drop=True) for ts_code, frame in price.groupby("ts_code")}
    rows: list[dict[str, Any]] = []
    for _, sample in samples.iterrows():
        ts_code = str(sample.get("ts_code") or "")
        trade_date = str(sample.get("trade_date") or "")
        symbol_price = grouped.get(ts_code, pd.DataFrame())
        row_base = _sample_base(sample)
        if symbol_price.empty or trade_date not in set(symbol_price["trade_date"].astype(str)):
            for horizon in resolved_horizons:
                rows.append({**row_base, **_empty_detail(horizon, "missing_entry_price")})
            continue
        position = symbol_price.index[symbol_price["trade_date"].astype(str) == trade_date].tolist()[0]
        entry_close = _to_float(symbol_price.iloc[position].get("close"))
        if entry_close is None or entry_close <= 0:
            for horizon in resolved_horizons:
                rows.append({**row_base, **_empty_detail(horizon, "missing_entry_price")})
            continue
        future = symbol_price.iloc[position + 1 :].copy()
        for horizon in resolved_horizons:
            available = int(len(future))
            if available < max(int(horizon), int(min_forward_days)):
                rows.append(
                    {
                        **row_base,
                        "horizon": horizon,
                        "entry_close": entry_close,
                        "future_close": None,
                        "forward_return": None,
                        "max_drawdown": None,
                        "max_runup": None,
                        "hit_stop_loss": None,
                        "hit_target": None,
                        "available_forward_days": available,
                        "data_quality_flag": "insufficient_forward_data",
                    }
                )
                continue
            window = future.head(int(horizon))
            future_close = _to_float(window.iloc[-1].get("close"))
            lows = pd.to_numeric(window.get("low", window["close"]), errors="coerce")
            highs = pd.to_numeric(window.get("high", window["close"]), errors="coerce")
            stop_loss = _to_float(sample.get("stop_loss"))
            target_price = _to_float(sample.get("target_price"))
            rows.append(
                {
                    **row_base,
                    "horizon": horizon,
                    "entry_close": entry_close,
                    "future_close": future_close,
                    "forward_return": None if future_close is None else future_close / entry_close - 1,
                    "max_drawdown": None if lows.dropna().empty else float((lows.min() / entry_close) - 1),
                    "max_runup": None if highs.dropna().empty else float((highs.max() / entry_close) - 1),
                    "hit_stop_loss": None if stop_loss is None else bool((lows <= stop_loss).any()),
                    "hit_target": None if target_price is None else bool((highs >= target_price).any()),
                    "available_forward_days": available,
                    "data_quality_flag": "ok",
                }
            )
    return pd.DataFrame(rows, columns=_detail_columns())


def summarize_lookback(details: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build all requested group summary tables."""
    return {
        "candidate_overall": group_summary(details.assign(candidate_group="全部候选"), "candidate_group"),
        "total_score_groups": group_summary(_with_score_bucket(details, "total_score", "total_score_group"), "total_score_group"),
        "factor_score_groups": _factor_group_summary(details),
        "elder_review_groups": _multi_group_summary(details, ["elder_score_group", "action_hint", "weekly_trend", "daily_pullback", "force_signal", "elder_ray_signal"]),
        "entry_zone_groups": _multi_group_summary(details, ["entry_zone_status", "chase_risk", "reward_risk_ratio_group", "risk_pct_group"]),
        "watchlist_groups": _multi_group_summary(details, ["watch_status", "watch_status_label", "watch_days_group", "selected_count_5d_group", "selected_count_10d_group", "consecutive_selected_days_group"]),
        "data_quality": data_quality_summary(details),
    }


def group_summary(details: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Summarize forward returns by group and horizon."""
    columns = _summary_columns()
    if details.empty or group_column not in details.columns:
        return pd.DataFrame(columns=columns)
    frame = details.copy()
    frame[group_column] = frame[group_column].fillna("缺失").astype(str)
    rows: list[dict[str, Any]] = []
    for (group, horizon), part in frame.groupby([group_column, "horizon"], dropna=False):
        valid = part[part["data_quality_flag"] == "ok"].copy()
        returns = pd.to_numeric(valid.get("forward_return"), errors="coerce")
        drawdowns = pd.to_numeric(valid.get("max_drawdown"), errors="coerce")
        runups = pd.to_numeric(valid.get("max_runup"), errors="coerce")
        rows.append(
            {
                "group_dimension": group_column,
                "group": group,
                "horizon": int(horizon),
                "sample_count": int(len(part)),
                "valid_sample_count": int(len(valid)),
                "avg_forward_return": _mean(returns),
                "median_forward_return": _median(returns),
                "win_rate": _rate(returns > 0),
                "up_gt_3pct_rate": _rate(returns > 0.03),
                "down_gt_3pct_rate": _rate(returns < -0.03),
                "avg_max_drawdown": _mean(drawdowns),
                "median_max_drawdown": _median(drawdowns),
                "avg_max_runup": _mean(runups),
                "hit_stop_loss_rate": _bool_rate(valid.get("hit_stop_loss")),
                "hit_target_rate": _bool_rate(valid.get("hit_target")),
                "insufficient_forward_data_count": int((part["data_quality_flag"] == "insufficient_forward_data").sum()),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(["horizon", "group_dimension", "group"]).reset_index(drop=True)


def save_lookback_workbook(
    output_path: str | Path,
    *,
    status: dict[str, Any],
    summaries: dict[str, pd.DataFrame],
    details: pd.DataFrame,
) -> Path:
    """Save the full independent lookback report workbook."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheets = {
        "00_摘要": _status_summary_frame(status),
        "01_候选整体回看": summaries.get("candidate_overall", pd.DataFrame()),
        "02_综合分分组": summaries.get("total_score_groups", pd.DataFrame()),
        "03_分项因子分组": summaries.get("factor_score_groups", pd.DataFrame()),
        "04_埃尔德复核回看": summaries.get("elder_review_groups", pd.DataFrame()),
        "05_买入区间回看": summaries.get("entry_zone_groups", pd.DataFrame()),
        "06_观察池状态回看": summaries.get("watchlist_groups", pd.DataFrame()),
        "07_未来收益明细": details,
        "08_数据质量": summaries.get("data_quality", pd.DataFrame()),
        "09_说明": _help_frame(),
    }
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            prepared = _prepare_for_excel(frame)
            prepared.to_excel(writer, sheet_name=sheet_name, index=False)
    return path


def normalize_horizons(horizons: list[int] | None) -> list[int]:
    """Return sorted positive unique horizons."""
    raw = horizons if horizons is not None else DEFAULT_HORIZONS
    values = sorted({int(value) for value in raw if int(value) > 0})
    return values or DEFAULT_HORIZONS


def render_text(status: dict[str, Any]) -> str:
    """Render user-facing text output."""
    lines = [
        "自动回看分析",
        f"- 整体状态: {status.get('status')}",
        f"- 回看截止交易日: {status.get('as_of_trade_date') or '暂无'}",
        f"- 样本区间: {status.get('start_date') or '暂无'} - {status.get('end_date') or '暂无'}",
        f"- 回看周期: {','.join(str(item) for item in status.get('horizons', []))}",
        f"- 候选样本数量: {status.get('candidate_sample_count', 0)}",
        f"- 有效样本数量: {status.get('valid_sample_count', 0)}",
        f"- 数据不足样本数量: {status.get('insufficient_forward_data_count', 0)}",
        "- 综合分分组: 已完成",
        "- 埃尔德复核回看: 已完成",
        "- 买入区间回看: 已完成",
        "- 观察池状态回看: 已完成",
        f"- 报告文件: {status.get('generated_report_path') or 'dry-run 未生成报告'}",
        "- 说明: 本报告仅用于验证历史样本表现，不构成投资建议，不自动交易。",
    ]
    if status.get("failure_reason"):
        lines.append(f"- 失败原因: {status.get('failure_reason')}")
    return "\n".join(lines)


def _read_table(store: DuckDBStore, table_name: str) -> pd.DataFrame:
    try:
        return store.read_table(table_name, read_only=True)
    except DuckDBStoreError:
        raise
    except Exception:
        return pd.DataFrame()


def _merge_latest_snapshot(samples: pd.DataFrame, snapshot: pd.DataFrame, *, columns: list[str]) -> pd.DataFrame:
    if samples.empty or snapshot.empty:
        return samples
    available = [column for column in columns if column in snapshot.columns]
    if not {"ts_code", "trade_date"}.issubset(available):
        return samples
    right = snapshot.loc[:, available].copy()
    right = _normalize_date_column(right, "trade_date")
    right = right.drop_duplicates(["ts_code", "trade_date"], keep="last")
    duplicate_payload = [column for column in right.columns if column not in {"ts_code", "trade_date"} and column in samples.columns]
    if duplicate_payload:
        right = right.drop(columns=duplicate_payload)
    return samples.merge(right, on=["ts_code", "trade_date"], how="left")


def _normalize_date_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame
    result = frame.copy()
    result[column] = result[column].astype(str).str.replace("-", "", regex=False)
    return result


def _resolve_end_date(strategy: pd.DataFrame, as_of: str, end_date: str) -> str:
    if end_date:
        return str(end_date)
    if as_of and as_of != "latest":
        return str(as_of)
    if strategy.empty or "trade_date" not in strategy.columns:
        return ""
    return str(strategy["trade_date"].dropna().astype(str).max())


def _resolve_as_of_trade_date(samples: pd.DataFrame, as_of: str, end_date: str) -> str:
    if end_date:
        return str(end_date)
    if as_of and as_of != "latest":
        return str(as_of)
    if samples.empty or "trade_date" not in samples.columns:
        return ""
    return str(samples["trade_date"].dropna().astype(str).max())


def _sample_base(sample: pd.Series) -> dict[str, Any]:
    keys = [
        "trade_date",
        "ts_code",
        "name",
        "industry",
        "total_score",
        "trend_score",
        "momentum_score",
        "liquidity_score",
        "fundamental_score",
        "volatility_score",
        "elder_score",
        "action_hint",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
        "entry_zone_status",
        "chase_risk",
        "reward_risk_ratio",
        "risk_pct",
        "stop_loss",
        "target_price",
        "watch_status",
        "watch_status_label",
        "watch_days",
        "selected_count_5d",
        "selected_count_10d",
        "consecutive_selected_days",
    ]
    base = {key: sample.get(key) for key in keys}
    base["total_score_group"] = score_bucket(sample.get("total_score"))
    base["elder_score_group"] = score_bucket(sample.get("elder_score"))
    base["reward_risk_ratio_group"] = ratio_bucket(sample.get("reward_risk_ratio"))
    base["risk_pct_group"] = risk_pct_bucket(sample.get("risk_pct"))
    base["watch_days_group"] = count_bucket(sample.get("watch_days"))
    base["selected_count_5d_group"] = count_bucket(sample.get("selected_count_5d"))
    base["selected_count_10d_group"] = count_bucket(sample.get("selected_count_10d"))
    base["consecutive_selected_days_group"] = count_bucket(sample.get("consecutive_selected_days"))
    return base


def _empty_detail(horizon: int, flag: str) -> dict[str, Any]:
    return {
        "horizon": horizon,
        "entry_close": None,
        "future_close": None,
        "forward_return": None,
        "max_drawdown": None,
        "max_runup": None,
        "hit_stop_loss": None,
        "hit_target": None,
        "available_forward_days": 0,
        "data_quality_flag": flag,
    }


def score_bucket(value: Any) -> str:
    score = _to_float(value)
    if score is None:
        return "缺失"
    if score >= 80:
        return ">=80"
    if score >= 70:
        return "70-80"
    if score >= 60:
        return "60-70"
    if score >= 50:
        return "50-60"
    return "<50"


def ratio_bucket(value: Any) -> str:
    ratio = _to_float(value)
    if ratio is None:
        return "缺失"
    if ratio >= 3:
        return ">=3"
    if ratio >= 2:
        return "2-3"
    if ratio >= 1:
        return "1-2"
    return "<1"


def risk_pct_bucket(value: Any) -> str:
    risk = _to_float(value)
    if risk is None:
        return "缺失"
    risk_abs = abs(risk)
    if risk_abs <= 0.03:
        return "<=3%"
    if risk_abs <= 0.08:
        return "3%-8%"
    return ">8%"


def count_bucket(value: Any) -> str:
    count = _to_float(value)
    if count is None:
        return "缺失"
    if count <= 0:
        return "0"
    if count == 1:
        return "1"
    if count <= 3:
        return "2-3"
    return ">=4"


def _with_score_bucket(details: pd.DataFrame, source_column: str, target_column: str) -> pd.DataFrame:
    frame = details.copy()
    frame[target_column] = frame[source_column].map(score_bucket) if source_column in frame.columns else "缺失"
    return frame


def _factor_group_summary(details: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in ["trend_score", "momentum_score", "liquidity_score", "fundamental_score", "volatility_score"]:
        frame = _with_score_bucket(details, column, f"{column}_group")
        summary = group_summary(frame, f"{column}_group")
        if not summary.empty:
            summary["group_dimension"] = column
            rows.append(summary)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame(columns=_summary_columns())


def _multi_group_summary(details: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    rows = []
    prepared = details.copy()
    if "elder_score_group" not in prepared.columns:
        prepared["elder_score_group"] = prepared["elder_score"].map(score_bucket) if "elder_score" in prepared.columns else "缺失"
    for column in columns:
        if column not in prepared.columns:
            continue
        summary = group_summary(prepared, column)
        if not summary.empty:
            rows.append(summary)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame(columns=_summary_columns())


def data_quality_summary(details: pd.DataFrame) -> pd.DataFrame:
    if details.empty:
        return pd.DataFrame([{"metric": "样本状态", "value": "暂无可回看样本。"}])
    counts = details["data_quality_flag"].fillna("unknown").value_counts().to_dict()
    return pd.DataFrame([{"metric": key, "value": int(value)} for key, value in counts.items()])


def _summary_columns() -> list[str]:
    return [
        "group_dimension",
        "group",
        "horizon",
        "sample_count",
        "valid_sample_count",
        "avg_forward_return",
        "median_forward_return",
        "win_rate",
        "up_gt_3pct_rate",
        "down_gt_3pct_rate",
        "avg_max_drawdown",
        "median_max_drawdown",
        "avg_max_runup",
        "hit_stop_loss_rate",
        "hit_target_rate",
        "insufficient_forward_data_count",
    ]


def _detail_columns() -> list[str]:
    return [
        "trade_date",
        "ts_code",
        "name",
        "industry",
        "total_score",
        "trend_score",
        "momentum_score",
        "liquidity_score",
        "fundamental_score",
        "volatility_score",
        "elder_score",
        "action_hint",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
        "entry_zone_status",
        "chase_risk",
        "reward_risk_ratio",
        "risk_pct",
        "watch_status",
        "watch_status_label",
        "watch_days",
        "selected_count_5d",
        "selected_count_10d",
        "consecutive_selected_days",
        "horizon",
        "entry_close",
        "future_close",
        "forward_return",
        "max_drawdown",
        "max_runup",
        "hit_stop_loss",
        "hit_target",
        "available_forward_days",
        "data_quality_flag",
        "total_score_group",
        "elder_score_group",
        "reward_risk_ratio_group",
        "risk_pct_group",
        "watch_days_group",
        "selected_count_5d_group",
        "selected_count_10d_group",
        "consecutive_selected_days_group",
    ]


def _mean(values: pd.Series) -> float | None:
    values = values.dropna()
    return None if values.empty else float(values.mean())


def _median(values: pd.Series) -> float | None:
    values = values.dropna()
    return None if values.empty else float(values.median())


def _rate(mask: pd.Series) -> float | None:
    if mask.empty:
        return None
    return float(mask.fillna(False).mean())


def _bool_rate(values: Any) -> float | None:
    if values is None:
        return None
    series = pd.Series(values).dropna()
    if series.empty:
        return None
    return float(series.astype(bool).mean())


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _default_report_path(as_of_trade_date: str) -> Path:
    return DEFAULT_REPORT_DIR / f"lookback_analysis_{as_of_trade_date}.xlsx"


def _base_status(
    *,
    started_at: datetime,
    as_of: str,
    start_date: str,
    end_date: str,
    horizons: list[int],
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "status": "running",
        "summary": "自动回看分析运行中。",
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": "",
        "research_date": started_at.strftime("%Y%m%d"),
        "as_of": as_of,
        "as_of_trade_date": "",
        "start_date": start_date,
        "end_date": end_date,
        "horizons": horizons,
        "dry_run": dry_run,
        "candidate_sample_count": 0,
        "valid_sample_count": 0,
        "insufficient_forward_data_count": 0,
        "generated_report_path": "",
        "report_exists": False,
        "report_size_bytes": 0,
        "best_performing_group_summary": "",
        "weakest_group_summary": "",
        "total_score_group_summary": "",
        "elder_review_summary": "",
        "entry_zone_summary": "",
        "watchlist_summary": "",
        "key_findings": "",
        "data_quality_summary": "",
        "stage": "start",
        "logs": [],
        "failure_reason": "",
    }


def _status_from_analysis(
    *,
    started_at: datetime,
    as_of_trade_date: str,
    samples: pd.DataFrame,
    details: pd.DataFrame,
    summaries: dict[str, pd.DataFrame],
    report_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    valid = details[details["data_quality_flag"] == "ok"] if not details.empty else pd.DataFrame()
    insufficient = int((details["data_quality_flag"] == "insufficient_forward_data").sum()) if not details.empty else 0
    start_date = "" if samples.empty else str(samples["trade_date"].dropna().astype(str).min())
    end_date = as_of_trade_date or ("" if samples.empty else str(samples["trade_date"].dropna().astype(str).max()))
    total_score_summary = _compact_summary(summaries.get("total_score_groups", pd.DataFrame()), "综合分分组")
    elder_summary = _compact_summary(summaries.get("elder_review_groups", pd.DataFrame()), "埃尔德复核")
    entry_summary = _compact_summary(summaries.get("entry_zone_groups", pd.DataFrame()), "买入区间")
    watch_summary = _compact_summary(summaries.get("watchlist_groups", pd.DataFrame()), "观察池")
    best, weakest = _best_and_weakest(summaries.get("candidate_overall", pd.DataFrame()))
    data_quality = f"有效样本 {len(valid)}，数据不足 {insufficient}。"
    return {
        "research_date": started_at.strftime("%Y%m%d"),
        "as_of_trade_date": as_of_trade_date,
        "start_date": start_date,
        "end_date": end_date,
        "candidate_sample_count": int(len(samples)),
        "valid_sample_count": int(len(valid)),
        "insufficient_forward_data_count": insufficient,
        "generated_report_path": "" if dry_run else str(report_path),
        "report_exists": False,
        "report_size_bytes": 0,
        "best_performing_group_summary": best,
        "weakest_group_summary": weakest,
        "total_score_group_summary": total_score_summary,
        "elder_review_summary": elder_summary,
        "entry_zone_summary": entry_summary,
        "watchlist_summary": watch_summary,
        "key_findings": "回看结果仅验证历史样本表现，不自动调整因子权重或候选排序。",
        "data_quality_summary": data_quality,
    }


def _final_status(details: pd.DataFrame) -> str:
    if details.empty:
        return "skipped"
    valid_count = int((details["data_quality_flag"] == "ok").sum())
    return "success" if valid_count > 0 else "warning"


def _summary_text(status: dict[str, Any]) -> str:
    if status.get("status") == "skipped":
        return "暂无可回看样本。"
    return "自动回看分析完成。" if status.get("status") == "success" else "自动回看分析完成，但可用样本不足。"


def _failed_status(started_at: datetime, reason: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "summary": "自动回看分析失败。",
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "stage": "failed",
        "failure_reason": reason,
        "logs": [reason],
        "research_date": started_at.strftime("%Y%m%d"),
    }


def _compact_summary(frame: pd.DataFrame, label: str) -> str:
    if frame.empty:
        return f"{label}: 暂无可统计样本。"
    horizon = frame["horizon"].max() if "horizon" in frame.columns and not frame.empty else ""
    subset = frame[frame["horizon"] == horizon] if horizon != "" else frame
    subset = subset.dropna(subset=["avg_forward_return"]) if "avg_forward_return" in subset.columns else subset
    if subset.empty:
        return f"{label}: 暂无可统计样本。"
    best = subset.sort_values("avg_forward_return", ascending=False, na_position="last").head(1).iloc[0]
    return f"{label}: {horizon}日表现较高分组为 {best.get('group')}，平均收益 {best.get('avg_forward_return')}。"


def _best_and_weakest(frame: pd.DataFrame) -> tuple[str, str]:
    if frame.empty:
        return "暂无", "暂无"
    valid = frame.dropna(subset=["avg_forward_return"])
    if valid.empty:
        return "暂无", "暂无"
    best = valid.sort_values("avg_forward_return", ascending=False).iloc[0]
    weakest = valid.sort_values("avg_forward_return", ascending=True).iloc[0]
    return (
        f"{best.get('group')} / {best.get('horizon')}日平均收益 {best.get('avg_forward_return')}",
        f"{weakest.get('group')} / {weakest.get('horizon')}日平均收益 {weakest.get('avg_forward_return')}",
    )


def _status_summary_frame(status: dict[str, Any]) -> pd.DataFrame:
    rows = [
        ("整体状态", status.get("status")),
        ("回看截止交易日", status.get("as_of_trade_date")),
        ("样本区间", f"{status.get('start_date') or '暂无'} - {status.get('end_date') or '暂无'}"),
        ("回看周期", ",".join(str(item) for item in status.get("horizons", []))),
        ("候选样本数量", status.get("candidate_sample_count", 0)),
        ("有效样本数量", status.get("valid_sample_count", 0)),
        ("数据不足数量", status.get("insufficient_forward_data_count", 0)),
        ("主要发现", status.get("key_findings")),
        ("数据质量提示", status.get("data_quality_summary")),
        ("完整回看报告路径", status.get("generated_report_path")),
        ("说明", "仅供个人研究使用，不自动交易。"),
    ]
    return pd.DataFrame([{"metric": key, "value": value} for key, value in rows])


def _help_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"section": "使用边界", "note": "本报告只做历史样本验证，不模拟交易、不做仓位管理、不自动调整算法。"},
            {"section": "收益口径", "note": "未来收益使用每只股票后续有效交易日，不使用自然日。"},
            {"section": "数据不足", "note": "若某周期后续交易日不足，该样本不纳入该周期收益统计，但会纳入数据质量统计。"},
            {"section": "风险提示", "note": "历史回看不代表未来表现，仅供个人研究使用，不自动交易。"},
        ]
    )


def _prepare_for_excel(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        frame = pd.DataFrame([{"note": "暂无数据。"}])
    result = frame.copy()
    result = result.rename(columns={column: LOOKBACK_COLUMN_LABELS.get(column, column) for column in result.columns})
    return result.where(pd.notna(result), None)


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return None if pd.isna(value) else value
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _parse_horizons(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run read-only automatic lookback analysis.")
    parser.add_argument("--as-of", default="latest")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--horizons", default="1,3,5,10,20")
    parser.add_argument("--min-forward-days", type=int, default=1)
    parser.add_argument("--source", default="strategy_result", choices=["strategy_result"])
    parser.add_argument("--include-elder", action="store_true", default=True)
    parser.add_argument("--include-entry-zone", action="store_true", default=True)
    parser.add_argument("--include-watchlist", action="store_true", default=True)
    parser.add_argument("--format", default="text", choices=["text", "json"])
    parser.add_argument("--output", default=None)
    parser.add_argument("--status-path", default=str(DEFAULT_STATUS_PATH))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = run_lookback_analysis(
        as_of=args.as_of,
        start_date=args.start_date,
        end_date=args.end_date,
        horizons=_parse_horizons(args.horizons),
        min_forward_days=args.min_forward_days,
        source=args.source,
        include_elder=args.include_elder,
        include_entry_zone=args.include_entry_zone,
        include_watchlist=args.include_watchlist,
        report_format=args.format,
        output_path=args.output,
        status_path=args.status_path,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    if args.format == "json":
        print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2, default=str, allow_nan=False))
    else:
        print(render_text(result))
    return 0 if result.get("status") in {"success", "warning", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
