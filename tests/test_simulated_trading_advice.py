"""Tests for Task 64 simulated trading advice."""

from __future__ import annotations

import pandas as pd

from core.advice.simulated_trading_advice import build_simulated_trading_advice, summarize_simulated_trading_advice


def test_advice_scope_deduplicates_sources_and_prioritizes_holdings() -> None:
    """Advice scope should include selection, watchlist, and external holdings once."""
    advice = build_simulated_trading_advice(
        strategy=_selection(["000001.SZ", "000002.SZ"]),
        watchlist=_watchlist(["000001.SZ", "000003.SZ"]),
        entry_zones=_entry_zones(["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]),
        entry_missing=pd.DataFrame(),
        external_positions=_external(["000001.SZ", "000004.SZ"]),
        trade_date="20260706",
    )

    assert advice["ts_code"].tolist() == ["000001.SZ", "000004.SZ", "000002.SZ", "000003.SZ"]
    first = advice[advice["ts_code"] == "000001.SZ"].iloc[0]
    assert first["source"] == "simulated_position"
    assert first["source_tags"] == "simulated_position,selection,watchlist"
    assert advice[advice["ts_code"] == "000004.SZ"].iloc[0]["holding_status"] == "已建仓"


def test_unheld_advice_actions_cover_buy_wait_pause_and_remove() -> None:
    """Unheld stocks should produce clear simulated actions."""
    strategy = _selection(["BUY.SZ", "WAIT.SZ", "PAUSE.SZ", "MISS.SZ"])
    entries = _entry_zones(["BUY.SZ", "WAIT.SZ", "PAUSE.SZ"])
    entries.loc[entries["ts_code"] == "WAIT.SZ", ["entry_zone_status", "entry_zone_status_cn", "chase_risk", "chase_risk_cn"]] = [
        "above_zone",
        "高于买入区间",
        "medium",
        "中",
    ]
    entries.loc[entries["ts_code"] == "PAUSE.SZ", ["reward_risk_ratio", "chase_risk", "chase_risk_cn"]] = [1.2, "high", "高"]
    missing = pd.DataFrame([{"ts_code": "MISS.SZ", "name": "缺失", "source": "selection", "missing_reason": "未生成买入区间快照"}])

    advice = build_simulated_trading_advice(
        strategy=strategy,
        watchlist=pd.DataFrame(),
        entry_zones=entries,
        entry_missing=missing,
        external_positions=pd.DataFrame(),
        trade_date="20260706",
    ).set_index("ts_code")

    assert advice.loc["BUY.SZ", "simulated_action"] == "可模拟买入"
    assert advice.loc["WAIT.SZ", "simulated_action"] == "等待回调"
    assert advice.loc["PAUSE.SZ", "simulated_action"] == "暂缓"
    assert advice.loc["MISS.SZ", "simulated_action"] == "剔除"
    assert set(advice["position_action"]) == {"未建仓"}


def test_unheld_high_chase_risk_pauses_even_when_near_zone() -> None:
    """High chase risk should force unheld stocks into pause, not continue-observe."""
    strategy = _selection(["HIGH.SZ"])
    entries = _entry_zones(["HIGH.SZ"])
    entries.loc[0, "reward_risk_ratio"] = 2.4
    entries.loc[0, "stop_loss"] = 8.8
    entries.loc[0, "entry_zone_status"] = "near_zone"
    entries.loc[0, "entry_zone_status_cn"] = "接近买入区间"
    entries.loc[0, "chase_risk"] = "high"
    entries.loc[0, "chase_risk_cn"] = "高"

    advice = build_simulated_trading_advice(
        strategy=strategy,
        watchlist=pd.DataFrame(),
        entry_zones=entries,
        entry_missing=pd.DataFrame(),
        external_positions=pd.DataFrame(),
        trade_date="20260706",
    )

    row = advice.iloc[0]
    assert row["simulated_action"] == "暂缓"
    assert row["suggested_position"] == "不建仓"


def test_holding_advice_generates_position_actions() -> None:
    """Held stocks must always receive a position_action."""
    entries = _entry_zones(["SELL.SZ", "ADD.SZ", "REDUCE.SZ", "HOLD.SZ"])
    entries.loc[entries["ts_code"] == "SELL.SZ", ["close", "stop_loss"]] = [8.0, 9.0]
    entries.loc[entries["ts_code"] == "REDUCE.SZ", ["entry_zone_status", "entry_zone_status_cn", "chase_risk", "chase_risk_cn"]] = [
        "above_zone",
        "高于买入区间",
        "high",
        "高",
    ]
    external = _external(["SELL.SZ", "ADD.SZ", "REDUCE.SZ", "HOLD.SZ"])

    advice = build_simulated_trading_advice(
        strategy=pd.DataFrame(),
        watchlist=_watchlist(["ADD.SZ", "REDUCE.SZ", "HOLD.SZ"]),
        entry_zones=entries,
        entry_missing=pd.DataFrame(),
        external_positions=external,
        trade_date="20260706",
    ).set_index("ts_code")

    assert advice.loc["SELL.SZ", "position_action"] == "卖出"
    assert advice.loc["ADD.SZ", "position_action"] in {"可模拟加仓", "继续持有"}
    assert advice.loc["REDUCE.SZ", "position_action"] == "减仓"
    assert advice.loc["HOLD.SZ", "position_action"] in {"可模拟加仓", "继续持有"}
    assert all(advice["position_action"].astype(str).str.len() > 0)


def test_holding_missing_entry_zone_gets_explicit_risk_action() -> None:
    """A held stock without entry-zone risk fields should not silently continue holding."""
    advice = build_simulated_trading_advice(
        strategy=pd.DataFrame(),
        watchlist=pd.DataFrame(),
        entry_zones=pd.DataFrame(),
        entry_missing=pd.DataFrame(),
        external_positions=_external(["HELD.SZ"]),
        trade_date="20260706",
    )

    row = advice.iloc[0]
    assert row["ts_code"] == "HELD.SZ"
    assert row["holding_status"] == "已建仓"
    assert row["position_action"] not in {"", "继续持有"}
    assert "买入区间缺失" in row["position_reason"] or "关键风控字段缺失" in row["position_reason"]
    assert "买入区间缺失" in row["advice_reason"] or "关键风控字段缺失" in row["advice_reason"]


def test_every_advice_row_has_reason_and_holding_position_reason() -> None:
    """Advice rows should not leave explanation fields blank."""
    advice = build_simulated_trading_advice(
        strategy=_selection(["BUY.SZ", "WAIT.SZ"]),
        watchlist=_watchlist(["WATCH.SZ"]),
        entry_zones=_entry_zones(["BUY.SZ", "WAIT.SZ", "WATCH.SZ"]),
        entry_missing=pd.DataFrame(),
        external_positions=_external(["HELD.SZ"]),
        trade_date="20260706",
    )

    assert advice["advice_reason"].fillna("").astype(str).str.strip().ne("").all()
    holdings = advice[advice["holding_status"] == "已建仓"]
    assert not holdings.empty
    assert holdings["position_reason"].fillna("").astype(str).str.strip().ne("").all()


def test_advice_summary_counts_actions() -> None:
    """Summary counts should support workbook and page metric cards."""
    advice = pd.DataFrame(
        {
            "holding_status": ["未建仓", "未建仓", "已建仓"],
            "simulated_action": ["可模拟买入", "等待回调", "继续观察"],
            "position_action": ["未建仓", "未建仓", "卖出"],
        }
    )

    counts = summarize_simulated_trading_advice(advice)

    assert counts["total"] == 3
    assert counts["buy"] == 1
    assert counts["wait_pullback"] == 1
    assert counts["holding"] == 1
    assert counts["sell"] == 1


def _selection(codes: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "20260706",
                "ts_code": code,
                "name": code,
                "total_score": 80 - index,
                "close": 10 + index,
                "action_hint": "趋势确认",
                "elder_score": 70,
            }
            for index, code in enumerate(codes)
        ]
    )


def _watchlist(codes: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "20260706",
                "ts_code": code,
                "name": code,
                "current_close": 10 + index,
                "action_hint": "趋势确认",
                "elder_score": 65,
            }
            for index, code in enumerate(codes)
        ]
    )


def _entry_zones(codes: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "20260706",
                "ts_code": code,
                "name": code,
                "close": 10 + index,
                "entry_low": 9.5 + index,
                "entry_high": 10.5 + index,
                "entry_mid": 10.0 + index,
                "stop_loss": 8.8 + index,
                "target_price": 12.4 + index,
                "reward_risk_ratio": 2.2,
                "entry_zone_status": "near_zone",
                "entry_zone_status_cn": "接近买入区间",
                "chase_risk": "low",
                "chase_risk_cn": "低",
            }
            for index, code in enumerate(codes)
        ]
    )


def _external(codes: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "snapshot_date": "20260706",
                "ts_code": code,
                "name": code,
                "quantity": 100,
                "cost_price": 9.8 + index,
                "current_price": 10.0 + index,
                "pnl": 20.0,
                "pnl_pct": 0.02,
            }
            for index, code in enumerate(codes)
        ]
    )
