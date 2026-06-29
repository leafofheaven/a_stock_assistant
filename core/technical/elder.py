"""Elder-style technical review for selected candidates.

The functions in this module only read local DataFrames and append a secondary
review layer. They do not change total_score, factor weights, or the original
candidate ordering.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


ELDER_REVIEW_COLUMNS = [
    "rank",
    "ts_code",
    "name",
    "industry",
    "trade_date",
    "total_score",
    "elder_score",
    "action_hint",
    "elder_reason",
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
    "weekly_trend_improving",
    "weekly_trend",
    "daily_pullback_ok",
    "daily_pullback",
    "short_trigger",
    "force_signal",
    "elder_ray_signal",
    "review_action",
]


def calculate_elder_indicators(price_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Elder-style daily indicators by ts_code.

    Required input columns are ``ts_code``, ``trade_date``, ``high``, ``low``
    and ``close``. ``vol`` is preferred for Force Index; ``amount`` is used as a
    fallback when sample or provider data lacks volume. Missing numeric values
    are coerced to NaN and handled by pandas rolling/EMA calculations. The
    output preserves the input rows and appends EMA, MACD, Force Index, Elder
    Ray and distance-to-EMA columns.
    """
    required = {"ts_code", "trade_date", "high", "low", "close"}
    if price_df.empty or not required.issubset(price_df.columns):
        return pd.DataFrame(columns=[*price_df.columns, *ELDER_REVIEW_COLUMNS])

    source = price_df.copy()
    if "vol" not in source.columns:
        source["vol"] = source["amount"] if "amount" in source.columns else 0.0
    frames: list[pd.DataFrame] = []
    for _, group in source.groupby("ts_code", sort=False):
        df = group.sort_values("trade_date").reset_index(drop=True)
        for column in ["high", "low", "close", "vol"]:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        close = df["close"]
        df["ema13"] = close.ewm(span=13, adjust=False, min_periods=1).mean()
        df["ema22"] = close.ewm(span=22, adjust=False, min_periods=1).mean()
        ema12 = close.ewm(span=12, adjust=False, min_periods=1).mean()
        ema26 = close.ewm(span=26, adjust=False, min_periods=1).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False, min_periods=1).mean()
        df["macd_histogram"] = df["macd"] - df["macd_signal"]
        df["macd_histogram_slope"] = df["macd_histogram"].diff()
        force_raw = close.diff() * df["vol"]
        df["force_index_2d"] = force_raw.ewm(span=2, adjust=False, min_periods=1).mean()
        df["force_index_13d"] = force_raw.ewm(span=13, adjust=False, min_periods=1).mean()
        df["bull_power"] = df["high"] - df["ema13"]
        df["bear_power"] = df["low"] - df["ema13"]
        df["close_to_ema13_pct"] = (close - df["ema13"]) / df["ema13"] * 100
        df["close_to_ema22_pct"] = (close - df["ema22"]) / df["ema22"] * 100
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def calculate_weekly_elder_trend(price_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily prices to weekly bars and judge trend improvement.

    Weekly trend is considered improving when the latest weekly close is above
    EMA13 and either EMA13 is above EMA22 or MACD histogram is improving.
    """
    required = {"ts_code", "trade_date", "high", "low", "close"}
    if price_df.empty or not required.issubset(price_df.columns):
        return pd.DataFrame(columns=["ts_code", "trade_date", "weekly_trend_improving", "weekly_reason"])

    rows: list[dict[str, Any]] = []
    source = price_df.copy()
    if "vol" not in source.columns:
        source["vol"] = source["amount"] if "amount" in source.columns else 0.0
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
        if len(weekly) < 6:
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": str(df["trade_date"].dropna().astype(str).max()),
                    "weekly_trend_improving": False,
                    "weekly_reason": "周线数据不足。",
                }
            )
            continue
        indicators = calculate_elder_indicators(weekly.assign(ts_code=ts_code))
        latest = indicators.iloc[-1]
        ema_structure = bool(latest["close"] >= latest["ema13"] and latest["ema13"] >= latest["ema22"])
        hist_improving = bool(pd.notna(latest["macd_histogram_slope"]) and latest["macd_histogram_slope"] > 0)
        trend = bool(latest["close"] >= latest["ema13"] and (ema_structure or hist_improving))
        rows.append(
            {
                "ts_code": ts_code,
                "trade_date": str(latest["trade_date"]),
                "weekly_trend_improving": trend,
                "weekly_reason": "周线趋势改善。" if trend else "周线趋势仍偏弱。",
            }
        )
    return pd.DataFrame(rows)


def build_elder_review(
    candidates_df: pd.DataFrame,
    price_df: pd.DataFrame,
    min_daily_rows: int = 35,
) -> pd.DataFrame:
    """Append Elder review fields to candidates without changing their order.

    ``elder_score`` is a secondary review score only. It does not replace or
    modify ``total_score`` and this function preserves the candidate input
    order, including the original ``rank`` column.
    """
    if candidates_df.empty:
        return pd.DataFrame(columns=ELDER_REVIEW_COLUMNS)

    candidates = candidates_df.copy().reset_index(drop=True)
    indicators = calculate_elder_indicators(price_df)
    weekly = calculate_weekly_elder_trend(price_df)
    rows: list[dict[str, Any]] = []
    for _, candidate in candidates.iterrows():
        ts_code = str(candidate.get("ts_code", ""))
        history = indicators[indicators["ts_code"].astype(str) == ts_code].sort_values("trade_date")
        if history.empty or len(history) < min_daily_rows:
            rows.append(_review_row(candidate, None, None, 0, "数据不足", "日线数据不足，暂不做技术复核。"))
            continue
        latest = history.iloc[-1]
        previous = history.iloc[-2] if len(history) >= 2 else latest
        weekly_row = _latest_weekly_row(weekly, ts_code)
        score, action_hint, reason, signals = _classify_elder_state(latest, previous, weekly_row)
        rows.append(_review_row(candidate, latest, weekly_row, score, action_hint, reason))
        rows[-1].update(signals)
    return pd.DataFrame(rows)[ELDER_REVIEW_COLUMNS]


def _classify_elder_state(
    latest: pd.Series,
    previous: pd.Series,
    weekly_row: pd.Series | None,
) -> tuple[int, str, str, dict[str, str]]:
    """Classify one candidate into an Elder-style review bucket."""
    weekly_ok = bool(weekly_row is not None and weekly_row.get("weekly_trend_improving", False))
    close_to_ema13 = _to_float(latest.get("close_to_ema13_pct"))
    close_to_ema22 = _to_float(latest.get("close_to_ema22_pct"))
    hist_slope = _to_float(latest.get("macd_histogram_slope"))
    prev_force2 = _to_float(previous.get("force_index_2d"))
    force2 = _to_float(latest.get("force_index_2d"))
    bull_power = _to_float(latest.get("bull_power"))
    bear_power = _to_float(latest.get("bear_power"))
    prev_bear_power = _to_float(previous.get("bear_power"))

    pullback_ok = abs(close_to_ema13) <= 5 or abs(close_to_ema22) <= 8
    overheat = close_to_ema13 > 10 and close_to_ema22 > 12
    force_cross_up = prev_force2 <= 0 < force2
    hist_strengthening = hist_slope > 0
    elder_ray_improving = bull_power > 0 or bear_power > prev_bear_power
    short_trigger = force_cross_up or (hist_strengthening and elder_ray_improving)
    signals = {
        "weekly_trend": "改善" if weekly_ok else "偏弱",
        "daily_pullback": "接近 EMA" if pullback_ok else "偏离 EMA",
        "force_signal": "由负转正" if force_cross_up else ("偏强" if force2 > 0 else "偏弱"),
        "elder_ray_signal": "多头增强/空头减弱" if elder_ray_improving else "压力未减弱",
    }

    score = 0
    if weekly_ok:
        score += 35
    if pullback_ok:
        score += 20
    if not overheat:
        score += 10
    if force_cross_up:
        score += 15
    if hist_strengthening:
        score += 10
    if elder_ray_improving:
        score += 10

    if not weekly_ok:
        return min(score, 45), "趋势偏弱，暂缓", "周线趋势尚未改善，先暂缓技术确认。", signals
    if overheat:
        signals["daily_pullback"] = "短线过热"
        return min(score, 70), "短线过热，不追", "周线趋势尚可，但收盘价明显高于 EMA，短线不宜追高。", signals
    if pullback_ok and short_trigger:
        return min(score, 100), "趋势确认，进入人工复核", "周线趋势改善，日线接近 EMA，短线触发信号转强。", signals
    if pullback_ok:
        return min(score, 85), "趋势尚可，等待回调", "周线趋势改善，价格仍在趋势结构内，但短线触发信号不够明确。", signals
    return min(score, 75), "趋势尚可，等待回调", "周线趋势改善，但价格离 EMA 较远，等待更合适的回调位置。", signals


def _review_row(
    candidate: pd.Series,
    latest: pd.Series | None,
    weekly_row: pd.Series | None,
    elder_score: int,
    action_hint: str,
    reason: str,
) -> dict[str, Any]:
    """Build one review output row."""
    row = {column: candidate.get(column) for column in ["rank", "ts_code", "name", "industry", "trade_date", "total_score"]}
    row.update(
        {
            "elder_score": elder_score,
            "action_hint": action_hint,
            "elder_reason": reason,
            "weekly_trend_improving": bool(weekly_row is not None and weekly_row.get("weekly_trend_improving", False)),
            "weekly_trend": "数据不足",
            "daily_pullback_ok": False,
            "daily_pullback": "数据不足",
            "short_trigger": False,
            "force_signal": "数据不足",
            "elder_ray_signal": "数据不足",
            "review_action": _review_action(action_hint),
        }
    )
    indicator_columns = [
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
    ]
    for column in indicator_columns:
        row[column] = _round_or_none(latest.get(column) if latest is not None else None)
    if latest is not None:
        row["trade_date"] = str(latest.get("trade_date") or row.get("trade_date") or "")
        close_to_ema13 = _to_float(latest.get("close_to_ema13_pct"))
        close_to_ema22 = _to_float(latest.get("close_to_ema22_pct"))
        row["daily_pullback_ok"] = bool(abs(close_to_ema13) <= 5 or abs(close_to_ema22) <= 8)
        row["short_trigger"] = "短线触发信号转强" in reason or "短线触发" in reason
    return row


def _review_action(action_hint: str) -> str:
    """Map technical status to manual review workflow action."""
    if action_hint == "趋势确认，进入人工复核":
        return "加入观察池"
    if action_hint == "趋势尚可，等待回调":
        return "等待回调"
    if action_hint == "趋势偏弱，暂缓":
        return "暂缓"
    return "忽略"


def _latest_weekly_row(weekly: pd.DataFrame, ts_code: str) -> pd.Series | None:
    if weekly.empty or "ts_code" not in weekly.columns:
        return None
    rows = weekly[weekly["ts_code"].astype(str) == ts_code]
    if rows.empty:
        return None
    return rows.sort_values("trade_date").iloc[-1]


def _to_float(value: Any) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(converted):
        return 0.0
    return converted


def _round_or_none(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(converted):
        return None
    return round(converted, 4)
