"""Entry zone, support/resistance, and stop reference calculations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

ENTRY_ZONE_COLUMNS = [
    "ts_code",
    "name",
    "trade_date",
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
    "volatility_pct",
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
    "source",
    "created_at",
    "updated_at",
]

STATUS_CN = {
    "in_zone": "位于买入区间",
    "near_zone": "接近买入区间",
    "above_zone": "高于买入区间，等待回调",
    "below_zone": "低于买入区间",
    "weak_no_entry": "趋势偏弱，暂不进入",
    "insufficient_data": "数据不足",
}

CHASE_RISK_CN = {"low": "低", "medium": "中", "high": "高"}


def add_technical_indicators(price_df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA, support/resistance, and ATR columns by ``ts_code``.

    The calculation uses only current and historical rows through rolling and
    exponentially weighted windows, so it does not introduce future data.
    """
    if price_df.empty:
        return pd.DataFrame(columns=[*price_df.columns, "ema13", "ema22", "ema60", "atr_14"])
    required = {"ts_code", "trade_date", "high", "low", "close"}
    missing = required - set(price_df.columns)
    if missing:
        raise ValueError(f"price_df is missing required columns: {', '.join(sorted(missing))}")

    frames: list[pd.DataFrame] = []
    for _, group in price_df.copy().groupby("ts_code", sort=False):
        df = group.sort_values("trade_date").copy()
        close = pd.to_numeric(df["close"], errors="coerce")
        high = pd.to_numeric(df["high"], errors="coerce")
        low = pd.to_numeric(df["low"], errors="coerce")
        pre_close = close.shift(1)
        true_range = pd.concat([(high - low).abs(), (high - pre_close).abs(), (low - pre_close).abs()], axis=1).max(axis=1)
        df["ema13"] = close.ewm(span=13, adjust=False).mean()
        df["ema22"] = close.ewm(span=22, adjust=False).mean()
        df["ema60"] = close.ewm(span=60, adjust=False).mean()
        df["support_20d"] = low.rolling(20, min_periods=20).min()
        df["support_60d"] = low.rolling(60, min_periods=60).min()
        df["resistance_20d"] = high.rolling(20, min_periods=20).max()
        df["resistance_60d"] = high.rolling(60, min_periods=60).max()
        df["atr_14"] = true_range.rolling(14, min_periods=14).mean()
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=price_df.columns)


def calculate_entry_zones_for_targets(
    price_df: pd.DataFrame,
    targets_df: pd.DataFrame,
    *,
    trade_date: str | None = None,
    source: str = "selection",
) -> pd.DataFrame:
    """Calculate entry zone snapshots for target stocks.

    ``targets_df`` must contain ``ts_code`` and may contain ``name`` and
    ``source``. When a target has fewer than 20 price rows, the result is marked
    ``insufficient_data`` instead of raising.
    """
    if targets_df.empty:
        return pd.DataFrame(columns=ENTRY_ZONE_COLUMNS)
    if "ts_code" not in targets_df.columns:
        raise ValueError("targets_df is missing required column: ts_code")

    now = datetime.now().replace(microsecond=0)
    enriched = add_technical_indicators(price_df)
    records: list[dict[str, Any]] = []
    for target in targets_df.drop_duplicates(subset=["ts_code"]).to_dict("records"):
        ts_code = str(target.get("ts_code", ""))
        rows = enriched[enriched["ts_code"].astype(str) == ts_code].sort_values("trade_date") if not enriched.empty else pd.DataFrame()
        if trade_date and not rows.empty:
            rows = rows[rows["trade_date"].astype(str) <= str(trade_date)]
        target_source = str(target.get("source") or source)
        if len(rows) < 20:
            records.append(_insufficient_record(target, rows, target_source, now))
            continue
        latest = rows.iloc[-1]
        records.append(_entry_zone_record(target, rows, latest, target_source, now))

    result = pd.DataFrame(records)
    for column in ENTRY_ZONE_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result[ENTRY_ZONE_COLUMNS]


def _entry_zone_record(target: dict[str, Any], rows: pd.DataFrame, latest: pd.Series, source: str, now: datetime) -> dict[str, Any]:
    close = _num(latest.get("close"))
    ema13 = _num(latest.get("ema13"))
    ema22 = _num(latest.get("ema22"))
    ema60 = _num(latest.get("ema60"))
    atr = _num(latest.get("atr_14")) or max(close * 0.03, 0.01) if close else None
    support_20 = _num(latest.get("support_20d"))
    support_60 = _num(latest.get("support_60d"))
    resistance_20 = _num(latest.get("resistance_20d"))
    resistance_60 = _num(latest.get("resistance_60d"))
    nearest_support = _nearest_below(close, [support_20, support_60, ema22, ema60])
    nearest_resistance = _nearest_above(close, [resistance_20, resistance_60])
    trend_weak = _trend_weak(close, ema13, ema22, ema60)
    close_to_ema13 = (close - ema13) / ema13 if close and ema13 else None
    close_to_ema22 = (close - ema22) / ema22 if close and ema22 else None
    overheat = bool(
        (close_to_ema13 is not None and close_to_ema13 > 0.10)
        or (close_to_ema22 is not None and close_to_ema22 > 0.14)
        or (nearest_resistance and close and (nearest_resistance - close) / close < 0.03)
    )
    if trend_weak:
        entry_low = nearest_support or support_20
        entry_high = ema22 or close
        status = "weak_no_entry"
        chase_risk = "medium"
    else:
        entry_low = nearest_support or ema22 or support_20
        entry_high = entry_low + 0.5 * atr if entry_low is not None and atr is not None else None
        status = _zone_status(close, entry_low, entry_high, atr, overheat)
        chase_risk = _chase_risk(close_to_ema13, close_to_ema22, status)
    entry_mid = (entry_low + entry_high) / 2 if entry_low is not None and entry_high is not None else None
    stop_loss = _stop_loss(entry_mid, nearest_support, atr)
    risk = entry_mid - stop_loss if entry_mid is not None and stop_loss is not None else None
    target_price = _target_price(entry_mid, risk, nearest_resistance)
    reward = target_price - entry_mid if target_price is not None and entry_mid is not None else None
    risk_pct = risk / entry_mid if risk and entry_mid and risk > 0 else None
    reward_pct = reward / entry_mid if reward and entry_mid and reward > 0 else None
    reward_risk_ratio = reward / risk if reward is not None and risk and risk > 0 else None
    volatility_pct = atr / close if atr and close else None
    return {
        "ts_code": target.get("ts_code"),
        "name": target.get("name"),
        "trade_date": str(latest.get("trade_date")),
        "close": close,
        "ema13": ema13,
        "ema22": ema22,
        "ema60": ema60,
        "support_20d": support_20,
        "support_60d": support_60,
        "resistance_20d": resistance_20,
        "resistance_60d": resistance_60,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "atr_14": atr,
        "volatility_pct": volatility_pct,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_mid": entry_mid,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "reward_risk_ratio": reward_risk_ratio,
        "entry_zone_status": status,
        "entry_zone_status_cn": STATUS_CN[status],
        "chase_risk": chase_risk,
        "chase_risk_cn": CHASE_RISK_CN[chase_risk],
        "price_action_note": _price_action_note(status, chase_risk),
        "entry_reason": _entry_reason(status, close, ema13, ema22, nearest_support),
        "risk_note": _risk_note(status, reward_risk_ratio),
        "source": source,
        "created_at": now,
        "updated_at": now,
    }


def _insufficient_record(target: dict[str, Any], rows: pd.DataFrame, source: str, now: datetime) -> dict[str, Any]:
    latest = rows.iloc[-1] if not rows.empty else pd.Series(dtype=object)
    return {
        "ts_code": target.get("ts_code"),
        "name": target.get("name"),
        "trade_date": str(latest.get("trade_date")) if not rows.empty else None,
        "close": _num(latest.get("close")) if not rows.empty else None,
        "entry_zone_status": "insufficient_data",
        "entry_zone_status_cn": STATUS_CN["insufficient_data"],
        "chase_risk": "medium",
        "chase_risk_cn": CHASE_RISK_CN["medium"],
        "price_action_note": "少于 20 个交易日，暂不计算买入区间。",
        "entry_reason": "历史行情不足，需补充数据后再复核。",
        "risk_note": "数据不足，无法计算可靠支撑阻力和盈亏比。",
        "source": source,
        "created_at": now,
        "updated_at": now,
    }


def _zone_status(close: float | None, entry_low: float | None, entry_high: float | None, atr: float | None, overheat: bool) -> str:
    if close is None or entry_low is None or entry_high is None:
        return "insufficient_data"
    if overheat and close > entry_high:
        return "above_zone"
    if entry_low <= close <= entry_high:
        return "in_zone"
    near_buffer = max((atr or 0) * 0.5, close * 0.02)
    if abs(close - entry_high) <= near_buffer or abs(close - entry_low) <= near_buffer:
        return "near_zone"
    if close > entry_high:
        return "above_zone"
    return "below_zone"


def _trend_weak(close: float | None, ema13: float | None, ema22: float | None, ema60: float | None) -> bool:
    if close is None or ema60 is None:
        return False
    return bool(close < ema60 or (ema13 is not None and ema22 is not None and ema13 < ema22 < ema60))


def _chase_risk(close_to_ema13: float | None, close_to_ema22: float | None, status: str) -> str:
    if status == "above_zone" or (close_to_ema13 is not None and close_to_ema13 > 0.10) or (close_to_ema22 is not None and close_to_ema22 > 0.14):
        return "high"
    if status in {"near_zone", "below_zone"}:
        return "medium"
    return "low"


def _stop_loss(entry_mid: float | None, nearest_support: float | None, atr: float | None) -> float | None:
    if entry_mid is None:
        return None
    buffer = max((atr or entry_mid * 0.03), entry_mid * 0.03)
    base = nearest_support if nearest_support is not None else entry_mid
    return min(base - buffer, entry_mid * 0.92)


def _target_price(entry_mid: float | None, risk: float | None, nearest_resistance: float | None) -> float | None:
    if entry_mid is None or risk is None or risk <= 0:
        return nearest_resistance
    rr_target = entry_mid + 2 * risk
    if nearest_resistance is None or nearest_resistance <= entry_mid:
        return rr_target
    return max(nearest_resistance, rr_target)


def _nearest_below(close: float | None, values: list[float | None]) -> float | None:
    candidates = [value for value in values if value is not None and close is not None and value <= close]
    return max(candidates) if candidates else None


def _nearest_above(close: float | None, values: list[float | None]) -> float | None:
    candidates = [value for value in values if value is not None and close is not None and value >= close]
    return min(candidates) if candidates else None


def _price_action_note(status: str, chase_risk: str) -> str:
    if status == "above_zone":
        return "价格高于参考买入区间，短线追高风险偏高，等待回调复核。"
    if status == "weak_no_entry":
        return "价格结构偏弱，仅保留支撑阻力参考。"
    if status == "in_zone":
        return "价格位于参考买入区间，需结合人工复核。"
    if status == "near_zone":
        return "价格接近参考买入区间，等待确认。"
    if chase_risk == "high":
        return "短线偏高，注意回撤。"
    return "价格低于参考区间，需观察是否企稳。"


def _entry_reason(status: str, close: float | None, ema13: float | None, ema22: float | None, support: float | None) -> str:
    if status == "weak_no_entry":
        return "收盘价或均线结构偏弱，暂不强化进入条件。"
    parts = []
    if close is not None and ema22 is not None and close >= ema22:
        parts.append("收盘价位于 EMA22 上方")
    if ema13 is not None and ema22 is not None and ema13 >= ema22:
        parts.append("EMA13 不低于 EMA22")
    if support is not None:
        parts.append("参考支撑位已识别")
    return "；".join(parts) if parts else "需结合趋势和成交进一步人工复核。"


def _risk_note(status: str, reward_risk_ratio: float | None) -> str:
    notes = []
    if status == "above_zone":
        notes.append("高于区间，不追高。")
    if reward_risk_ratio is None:
        notes.append("盈亏比暂不可计算。")
    elif reward_risk_ratio < 2:
        notes.append("盈亏比低于 2，需谨慎复核。")
    else:
        notes.append("盈亏比达到 2 以上，仅作研究参考。")
    return "；".join(notes)


def _num(value: Any) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(numeric) else float(numeric)

