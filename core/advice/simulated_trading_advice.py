"""Build paper-trading advice from the daily research view.

This module is intentionally an advice/display layer. It does not recalculate
selection scores, Elder review, or entry-zone formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


ADVICE_COLUMNS = [
    "display_order",
    "trade_date",
    "ts_code",
    "name",
    "source",
    "source_tags",
    "holding_status",
    "simulated_action",
    "suggested_position",
    "action_priority",
    "close",
    "entry_low",
    "entry_high",
    "entry_mid",
    "stop_loss",
    "target_price",
    "reward_risk_ratio",
    "entry_zone_status_cn",
    "chase_risk_cn",
    "action_hint",
    "elder_score",
    "elder_reason",
    "weekly_trend",
    "daily_pullback",
    "force_signal",
    "elder_ray_signal",
    "position_qty",
    "avg_cost",
    "unrealized_pnl",
    "unrealized_pnl_pct",
    "holding_days",
    "position_action",
    "position_reason",
    "add_condition",
    "reduce_condition",
    "exit_condition",
    "trigger_condition",
    "invalidation_condition",
    "advice_reason",
    "risk_note",
    "total_score",
]

SOURCE_PRIORITY = {"simulated_position": 0, "selection": 1, "watchlist": 2}
POSITION_ACTION_PRIORITY = {"卖出": 1, "减仓": 2, "可模拟加仓": 3, "继续持有": 4, "观察不操作": 5, "未建仓": 9}
SIMULATED_ACTION_PRIORITY = {"可模拟买入": 1, "等待回调": 2, "继续观察": 3, "暂缓": 4, "剔除": 5}


@dataclass(frozen=True)
class _SourceRecord:
    code: str
    source: str
    source_tags: list[str]
    row: dict[str, Any]


def build_simulated_trading_advice(
    *,
    strategy: pd.DataFrame | None,
    watchlist: pd.DataFrame | None,
    entry_zones: pd.DataFrame | None,
    entry_missing: pd.DataFrame | None,
    external_positions: pd.DataFrame | None,
    trade_date: str,
) -> pd.DataFrame:
    """Build the shared paper-trading advice table for Excel and Streamlit."""
    strategy_df = _clean_frame(strategy)
    watchlist_df = _clean_frame(watchlist)
    entry_df = _clean_frame(entry_zones)
    missing_df = _clean_frame(entry_missing)
    external_df = _clean_frame(external_positions)

    source_records = _build_source_records(strategy_df, watchlist_df, external_df)
    if not source_records:
        return pd.DataFrame(columns=ADVICE_COLUMNS)

    entry_map = _index_latest(entry_df, "ts_code")
    missing_map = _index_latest(missing_df, "ts_code")
    strategy_map = _index_latest(strategy_df, "ts_code")
    watchlist_map = _index_latest(watchlist_df, "ts_code")
    external_map = _index_latest(external_df, "ts_code")

    rows: list[dict[str, Any]] = []
    for record in source_records:
        code = record.code
        merged = _merge_rows(
            strategy_map.get(code, {}),
            watchlist_map.get(code, {}),
            entry_map.get(code, {}),
            external_map.get(code, {}),
            preferred=record.row,
        )
        source_tags = record.source_tags
        row = _base_advice_row(
            code=code,
            source=record.source,
            source_tags=source_tags,
            merged=merged,
            trade_date=trade_date,
            entry_row=entry_map.get(code, {}),
            missing_row=missing_map.get(code, {}),
        )
        if row["holding_status"] == "已建仓":
            _apply_holding_advice(row)
        else:
            _apply_unheld_advice(row)
        rows.append(row)

    result = pd.DataFrame(rows)
    result = _sort_advice(result)
    data_columns = [column for column in ADVICE_COLUMNS if column != "display_order"]
    result = _ensure_columns(result, data_columns)
    result = result[data_columns].copy()
    result.insert(0, "display_order", range(1, len(result) + 1))
    return result


def summarize_simulated_trading_advice(advice: pd.DataFrame | None) -> dict[str, int]:
    """Return counts used by workbook summaries and Streamlit metric cards."""
    frame = _clean_frame(advice)
    if frame.empty:
        return {
            "total": 0,
            "buy": 0,
            "wait_pullback": 0,
            "observe": 0,
            "pause": 0,
            "remove": 0,
            "holding": 0,
            "hold": 0,
            "add": 0,
            "reduce": 0,
            "sell": 0,
        }
    simulated = frame.get("simulated_action", pd.Series(dtype=str)).fillna("").astype(str)
    position = frame.get("position_action", pd.Series(dtype=str)).fillna("").astype(str)
    holding = frame.get("holding_status", pd.Series(dtype=str)).fillna("").astype(str)
    return {
        "total": int(len(frame)),
        "buy": int((simulated == "可模拟买入").sum()),
        "wait_pullback": int((simulated == "等待回调").sum()),
        "observe": int((simulated == "继续观察").sum()),
        "pause": int((simulated == "暂缓").sum()),
        "remove": int((simulated == "剔除").sum()),
        "holding": int((holding == "已建仓").sum()),
        "hold": int((position == "继续持有").sum()),
        "add": int((position == "可模拟加仓").sum()),
        "reduce": int((position == "减仓").sum()),
        "sell": int((position == "卖出").sum()),
    }


def _clean_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "message" in frame.columns:
        return pd.DataFrame()
    return frame.copy()


def _build_source_records(strategy: pd.DataFrame, watchlist: pd.DataFrame, external: pd.DataFrame) -> list[_SourceRecord]:
    by_code: dict[str, dict[str, Any]] = {}
    for source, frame in [("selection", strategy), ("watchlist", watchlist), ("simulated_position", external)]:
        if frame.empty or "ts_code" not in frame.columns:
            continue
        for _, row in frame.iterrows():
            code = _text(row.get("ts_code"))
            if not code:
                continue
            current = by_code.setdefault(code, {"tags": [], "rows": {}, "primary": source})
            if source not in current["tags"]:
                current["tags"].append(source)
            current["rows"][source] = row.to_dict()
            if SOURCE_PRIORITY[source] < SOURCE_PRIORITY.get(current["primary"], 99):
                current["primary"] = source
    records: list[_SourceRecord] = []
    for code, item in by_code.items():
        primary = str(item["primary"])
        ordered_tags = sorted(item["tags"], key=lambda value: SOURCE_PRIORITY.get(value, 99))
        records.append(_SourceRecord(code=code, source=primary, source_tags=ordered_tags, row=item["rows"].get(primary, {})))
    records.sort(key=lambda record: (SOURCE_PRIORITY.get(record.source, 99), record.code))
    return records


def _index_latest(frame: pd.DataFrame, key: str) -> dict[str, dict[str, Any]]:
    if frame.empty or key not in frame.columns:
        return {}
    deduped = frame.drop_duplicates(key, keep="last")
    return {_text(row.get(key)): row.to_dict() for _, row in deduped.iterrows() if _text(row.get(key))}


def _merge_rows(*rows: dict[str, Any], preferred: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for row in rows:
        for key, value in row.items():
            if key not in merged or _is_blank(merged[key]):
                merged[key] = value
    for key, value in preferred.items():
        if not _is_blank(value):
            merged[key] = value
    return merged


def _base_advice_row(
    *,
    code: str,
    source: str,
    source_tags: list[str],
    merged: dict[str, Any],
    trade_date: str,
    entry_row: dict[str, Any],
    missing_row: dict[str, Any],
) -> dict[str, Any]:
    qty = _number(_first_value(merged, ["position_qty", "shares", "quantity"]))
    has_position = source == "simulated_position" and (qty is None or qty > 0)
    close = _number(_first_value(merged, ["close", "current_close", "current_price"]))
    avg_cost = _number(_first_value(merged, ["avg_cost", "cost_price", "position_cost"]))
    pnl = _number(_first_value(merged, ["unrealized_pnl", "pnl"]))
    pnl_pct = _number(_first_value(merged, ["unrealized_pnl_pct", "pnl_pct"]))
    row = {
        "trade_date": trade_date,
        "ts_code": code,
        "name": _first_value(merged, ["name"]) or "",
        "source": source,
        "source_tags": ",".join(source_tags),
        "holding_status": "已建仓" if has_position else "未建仓",
        "simulated_action": "",
        "suggested_position": "",
        "action_priority": None,
        "close": close,
        "entry_low": _number(_first_value(entry_row or merged, ["entry_low"])),
        "entry_high": _number(_first_value(entry_row or merged, ["entry_high"])),
        "entry_mid": _number(_first_value(entry_row or merged, ["entry_mid"])),
        "stop_loss": _number(_first_value(entry_row or merged, ["stop_loss"])),
        "target_price": _number(_first_value(entry_row or merged, ["target_price"])),
        "reward_risk_ratio": _number(_first_value(entry_row or merged, ["reward_risk_ratio"])),
        "entry_zone_status": _text(_first_value(entry_row or merged, ["entry_zone_status"])),
        "entry_zone_status_cn": _text(_first_value(entry_row or merged, ["entry_zone_status_cn"])),
        "chase_risk": _text(_first_value(entry_row or merged, ["chase_risk"])),
        "chase_risk_cn": _text(_first_value(entry_row or merged, ["chase_risk_cn"])),
        "action_hint": _text(_first_value(merged, ["action_hint"])),
        "elder_score": _number(_first_value(merged, ["elder_score"])),
        "elder_reason": _text(_first_value(merged, ["elder_reason"])),
        "weekly_trend": _text(_first_value(merged, ["weekly_trend"])),
        "daily_pullback": _text(_first_value(merged, ["daily_pullback"])),
        "force_signal": _text(_first_value(merged, ["force_signal"])),
        "elder_ray_signal": _text(_first_value(merged, ["elder_ray_signal"])),
        "position_qty": qty,
        "avg_cost": avg_cost,
        "unrealized_pnl": pnl,
        "unrealized_pnl_pct": pnl_pct,
        "holding_days": _number(_first_value(merged, ["holding_days"])),
        "position_action": "",
        "position_reason": "",
        "add_condition": "",
        "reduce_condition": "",
        "exit_condition": "",
        "trigger_condition": "",
        "invalidation_condition": "",
        "advice_reason": "",
        "risk_note": _text(_first_value(entry_row or merged, ["risk_note", "note", "match_note"])),
        "total_score": _number(_first_value(merged, ["total_score"])),
        "_has_entry": bool(entry_row),
        "_entry_missing_reason": _text(_first_value(missing_row, ["missing_reason"])),
    }
    if row["close"] is None:
        row["close"] = _number(_first_value(merged, ["current_price", "current_close"]))
    return row


def _apply_unheld_advice(row: dict[str, Any]) -> None:
    row["position_action"] = "未建仓"
    row["position_reason"] = "未建仓股票仅生成模拟买入或观察建议。"
    if _missing_entry_or_prices(row):
        row["simulated_action"] = "剔除"
        row["suggested_position"] = "不建仓"
        reason = row.get("_entry_missing_reason") or "缺少买入区间数据，请重新运行 calculate_entry_zones。"
        row["advice_reason"] = reason
        row["risk_note"] = row.get("risk_note") or reason
    elif _negative_signal(row) or _weak_entry(row) or _high_chase_risk(row) or _ratio(row) < 1.8 or row.get("stop_loss") is None:
        row["simulated_action"] = "暂缓"
        row["suggested_position"] = "不建仓"
        row["advice_reason"] = "趋势、追高风险、止损或盈亏比条件未满足，暂不模拟建仓。"
    elif _wait_pullback(row):
        row["simulated_action"] = "等待回调"
        row["suggested_position"] = "观察不建仓"
        row["advice_reason"] = "趋势尚可但当前价格高于合理区间，等待回到买入区间后再评估。"
        row["trigger_condition"] = "回落至 entry_high 以下，或进入 entry_low ~ entry_high，且 Elder / action_hint 不转弱。"
    elif _in_or_near_zone(row) and not _high_chase_risk(row) and _ratio(row) >= 1.8:
        row["simulated_action"] = "可模拟买入"
        row["suggested_position"] = "标准模拟仓" if _ratio(row) >= 2.5 and _low_chase_risk(row) else "轻仓模拟"
        row["advice_reason"] = "价格位于或接近买入区间，止损和盈亏比条件满足，可用于纸面交易验证。"
        row["trigger_condition"] = "进入 entry_low ~ entry_high，且 Elder / action_hint 不转弱。"
    else:
        row["simulated_action"] = "继续观察"
        row["suggested_position"] = "观察不建仓"
        row["advice_reason"] = "有候选或观察价值，但当前缺少明确模拟买入触发。"
    row["invalidation_condition"] = row["invalidation_condition"] or "跌破 stop_loss，或 action_hint 转为趋势偏弱 / 暂缓，或追高风险升高。"
    row["action_priority"] = SIMULATED_ACTION_PRIORITY.get(row["simulated_action"], 9)


def _apply_holding_advice(row: dict[str, Any]) -> None:
    row["simulated_action"] = "继续观察"
    row["suggested_position"] = "已建仓跟踪"
    if _missing_entry_or_prices(row):
        reason = "买入区间缺失或关键风控字段缺失，无法完整定义模拟持仓风险。"
        row["risk_note"] = row.get("risk_note") or reason
        if row.get("stop_loss") is None:
            row["position_action"] = "卖出"
            row["position_reason"] = f"{reason} 当前缺少 stop_loss，优先模拟退出。"
            row["exit_condition"] = "补齐买入区间和 stop_loss 前，不继续模拟持有。"
        else:
            row["position_action"] = "观察不操作"
            row["position_reason"] = f"{reason} 暂不加仓或继续强化持有判断。"
    elif _stop_triggered(row) or _sell_signal(row):
        row["position_action"] = "卖出"
        row["position_reason"] = "已触发止损、趋势转弱或关键风险数据不足，模拟持仓应优先退出。"
        row["exit_condition"] = "跌破 stop_loss，或 Elder / action_hint 明显转弱且无法重新站回买入区间。"
    elif _reduce_signal(row):
        row["position_action"] = "减仓"
        row["position_reason"] = "短线过热、追高风险偏高或价格远离买入区间，模拟减仓控制风险。"
        row["reduce_condition"] = "若价格继续远离 entry_high 且强力指数转弱，模拟减仓 1/3；达到目标价可模拟减仓 1/3 至 1/2。"
    elif _can_add(row):
        row["position_action"] = "可模拟加仓"
        row["position_reason"] = "仍处于或接近买入区间，趋势未破坏且盈亏比满足，可小幅模拟加仓。"
        row["add_condition"] = "回踩 entry_mid 附近不破，或重新进入 entry_low ~ entry_high，且 Elder 信号不转弱。"
    elif not _negative_signal(row):
        row["position_action"] = "继续持有"
        row["position_reason"] = "当前未触发止损，趋势未明显破坏，继续模拟持有观察。"
    else:
        row["position_action"] = "观察不操作"
        row["position_reason"] = "信号混杂，暂未触发明确加仓、减仓或卖出条件。"
    row["advice_reason"] = row["position_reason"]
    row["invalidation_condition"] = row["invalidation_condition"] or "跌破 stop_loss，或 action_hint 转为趋势偏弱 / 暂缓。"
    row["action_priority"] = POSITION_ACTION_PRIORITY.get(row["position_action"], 9)


def _missing_entry_or_prices(row: dict[str, Any]) -> bool:
    if row.get("_entry_missing_reason"):
        return True
    if not row.get("_has_entry"):
        return True
    required = ["entry_low", "entry_high", "entry_mid", "stop_loss", "target_price"]
    return any(row.get(key) is None for key in required)


def _in_or_near_zone(row: dict[str, Any]) -> bool:
    status = f"{row.get('entry_zone_status', '')} {row.get('entry_zone_status_cn', '')}"
    return _contains_any(status, ["in_zone", "near_zone", "位于买入区间", "接近买入区间"])


def _wait_pullback(row: dict[str, Any]) -> bool:
    status = f"{row.get('entry_zone_status', '')} {row.get('entry_zone_status_cn', '')} {row.get('action_hint', '')}"
    return _contains_any(status, ["above_zone", "等待回调", "高于买入区间"])


def _weak_entry(row: dict[str, Any]) -> bool:
    status = f"{row.get('entry_zone_status', '')} {row.get('entry_zone_status_cn', '')}"
    return _contains_any(status, ["weak_no_entry", "insufficient_data", "趋势偏弱", "数据不足", "暂不进入"])


def _negative_signal(row: dict[str, Any]) -> bool:
    text = f"{row.get('action_hint', '')} {row.get('elder_reason', '')} {row.get('risk_note', '')}"
    return _contains_any(text, ["趋势偏弱", "暂缓", "短线过热", "追高风险", "不进入", "破位", "数据不足"])


def _sell_signal(row: dict[str, Any]) -> bool:
    text = f"{row.get('action_hint', '')} {row.get('elder_reason', '')} {row.get('entry_zone_status_cn', '')}"
    return _contains_any(text, ["趋势偏弱", "暂缓", "不进入", "破位", "数据不足", "insufficient"])


def _reduce_signal(row: dict[str, Any]) -> bool:
    return _high_chase_risk(row) or _wait_pullback(row) or _contains_any(str(row.get("action_hint", "")), ["短线过热", "等待回调"])


def _can_add(row: dict[str, Any]) -> bool:
    unrealized_pct = _number(row.get("unrealized_pnl_pct"))
    return (
        _in_or_near_zone(row)
        and _ratio(row) >= 2.0
        and not _high_chase_risk(row)
        and not _negative_signal(row)
        and (unrealized_pct is None or unrealized_pct > -0.08)
    )


def _stop_triggered(row: dict[str, Any]) -> bool:
    close = _number(row.get("close"))
    stop = _number(row.get("stop_loss"))
    return close is not None and stop is not None and close <= stop


def _high_chase_risk(row: dict[str, Any]) -> bool:
    text = f"{row.get('chase_risk', '')} {row.get('chase_risk_cn', '')}"
    return _contains_any(text.lower(), ["high", "高", "追高风险高"])


def _low_chase_risk(row: dict[str, Any]) -> bool:
    text = f"{row.get('chase_risk', '')} {row.get('chase_risk_cn', '')}"
    return _contains_any(text.lower(), ["low", "低"])


def _ratio(row: dict[str, Any]) -> float:
    value = _number(row.get("reward_risk_ratio"))
    return float(value) if value is not None else 0.0


def _sort_advice(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["_source_priority"] = result["source"].map(SOURCE_PRIORITY).fillna(9)
    result["_holding_priority"] = result["holding_status"].map({"已建仓": 0, "未建仓": 1}).fillna(2)
    result["_position_priority"] = result["position_action"].map(POSITION_ACTION_PRIORITY).fillna(9)
    result["_simulated_priority"] = result["simulated_action"].map(SIMULATED_ACTION_PRIORITY).fillna(9)
    for column in ["reward_risk_ratio", "elder_score", "total_score"]:
        result[column] = pd.to_numeric(result.get(column), errors="coerce")
    result = result.sort_values(
        [
            "_holding_priority",
            "_source_priority",
            "_position_priority",
            "_simulated_priority",
            "reward_risk_ratio",
            "elder_score",
            "total_score",
            "ts_code",
        ],
        ascending=[True, True, True, True, False, False, False, True],
        na_position="last",
    )
    return result.drop(columns=[column for column in result.columns if column.startswith("_")])


def _ensure_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    if "display_order" in result.columns:
        result = result.drop(columns=["display_order"])
    return result


def _first_value(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if not _is_blank(value):
            return value
    return None


def _text(value: Any) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip()


def _number(value: Any) -> float | None:
    if _is_blank(value):
        return None
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        return False
    return str(value).strip() == ""


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)
