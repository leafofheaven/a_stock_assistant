"""Small demo datasets for MVP smoke tests and first-run dashboard rendering.

The data in this module is synthetic demonstration data. It is only intended to
show the local workflow and UI shape when no real market database is available;
it must not be treated as investment advice or as real market data.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


DEMO_TRADE_DATE = "20240131"
DEMO_DATA_SOURCE = "sample 数据（演示）"


def get_sample_stock_basic() -> pd.DataFrame:
    """Return a small synthetic stock basic table for demo use."""
    return pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "name": "演示银行A",
                "industry": "银行",
                "list_date": "20100101",
                "data_note": "演示数据",
            },
            {
                "ts_code": "600000.SH",
                "name": "演示银行B",
                "industry": "银行",
                "list_date": "20000101",
                "data_note": "演示数据",
            },
            {
                "ts_code": "000002.SZ",
                "name": "演示地产A",
                "industry": "房地产",
                "list_date": "20050101",
                "data_note": "演示数据",
            },
        ]
    )


def get_sample_daily_price() -> pd.DataFrame:
    """Return synthetic daily price rows covering the dashboard line charts."""
    rows: list[dict[str, Any]] = []
    stock_specs = {
        "000001.SZ": (10.0, 0.045, 120_000_000),
        "600000.SH": (8.0, 0.025, 95_000_000),
        "000002.SZ": (12.0, -0.015, 80_000_000),
    }
    trade_dates = pd.bdate_range("2023-11-01", periods=65).strftime("%Y%m%d")
    for ts_code, (base_close, step, base_amount) in stock_specs.items():
        previous_close = base_close
        for index, trade_date in enumerate(trade_dates):
            close = round(base_close + index * step, 3)
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": round(previous_close * 0.998, 3),
                    "high": round(max(previous_close, close) * 1.01, 3),
                    "low": round(min(previous_close, close) * 0.99, 3),
                    "close": close,
                    "pre_close": round(previous_close, 3),
                    "pct_chg": round((close / previous_close - 1) * 100, 4)
                    if previous_close
                    else 0.0,
                    "amount": base_amount + index * 800_000,
                    "is_suspended": False,
                    "is_limit_up": False,
                    "is_limit_down": False,
                    "data_note": "演示数据",
                }
            )
            previous_close = close
    return pd.DataFrame(rows)


def get_sample_daily_basic() -> pd.DataFrame:
    """Return synthetic daily basic indicators for demo use."""
    return pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": DEMO_TRADE_DATE,
                "turnover_rate": 1.8,
                "pe": 8.5,
                "pb": 0.82,
                "total_mv": 220_000_000_000,
                "circ_mv": 180_000_000_000,
                "data_note": "演示数据",
            },
            {
                "ts_code": "600000.SH",
                "trade_date": DEMO_TRADE_DATE,
                "turnover_rate": 1.2,
                "pe": 7.9,
                "pb": 0.76,
                "total_mv": 190_000_000_000,
                "circ_mv": 160_000_000_000,
                "data_note": "演示数据",
            },
            {
                "ts_code": "000002.SZ",
                "trade_date": DEMO_TRADE_DATE,
                "turnover_rate": 0.9,
                "pe": 11.2,
                "pb": 0.95,
                "total_mv": 120_000_000_000,
                "circ_mv": 90_000_000_000,
                "data_note": "演示数据",
            },
        ]
    )


def get_sample_factor_scores() -> pd.DataFrame:
    """Return synthetic factor scores with the columns expected by strategy/UI."""
    stock_basic = get_sample_stock_basic()
    scores = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": DEMO_TRADE_DATE,
                "trend_score": 82.0,
                "momentum_score": 78.0,
                "liquidity_score": 90.0,
                "fundamental_score": 84.0,
                "volatility_score": 88.0,
                "total_score": 86.5,
            },
            {
                "ts_code": "600000.SH",
                "trade_date": DEMO_TRADE_DATE,
                "trend_score": 75.0,
                "momentum_score": 70.0,
                "liquidity_score": 86.0,
                "fundamental_score": 82.0,
                "volatility_score": 79.0,
                "total_score": 80.2,
            },
            {
                "ts_code": "000002.SZ",
                "trade_date": DEMO_TRADE_DATE,
                "trend_score": 61.0,
                "momentum_score": 58.0,
                "liquidity_score": 68.0,
                "fundamental_score": 60.0,
                "volatility_score": 72.0,
                "total_score": 66.4,
            },
        ]
    )
    result = scores.merge(stock_basic[["ts_code", "name", "industry", "list_date"]], on="ts_code", how="left")
    result["data_note"] = "演示数据"
    return result


def get_sample_strategy_result() -> pd.DataFrame:
    """Return synthetic selected stocks produced from sample factor scores."""
    selected = get_sample_factor_scores().sort_values(
        ["trade_date", "total_score", "ts_code"],
        ascending=[True, False, True],
    )
    selected = selected.reset_index(drop=True)
    selected["rank"] = selected.groupby("trade_date").cumcount() + 1
    selected["select_reason"] = selected["total_score"].map(lambda score: f"演示综合分 {score:.2f}；用于流程展示")
    selected["risk_note"] = "演示数据仅用于研究流程验证，不构成投资建议"
    selected["weight"] = 1.0 / selected.groupby("trade_date")["ts_code"].transform("count")
    return selected[
        [
            "trade_date",
            "rank",
            "ts_code",
            "name",
            "industry",
            "trend_score",
            "momentum_score",
            "liquidity_score",
            "fundamental_score",
            "volatility_score",
            "total_score",
            "select_reason",
            "risk_note",
            "weight",
        ]
    ]


def get_sample_backtest_result() -> dict[str, Any]:
    """Return a small synthetic backtest result structure for dashboard smoke use."""
    equity_curve = pd.DataFrame(
        {
            "trade_date": ["20240105", "20240112", "20240119", "20240126"],
            "equity": [1_000_000.0, 1_012_500.0, 1_008_000.0, 1_021_000.0],
            "data_note": ["演示数据"] * 4,
        }
    )
    trade_records = pd.DataFrame(
        [
            {
                "trade_date": "20240105",
                "ts_code": "000001.SZ",
                "side": "buy",
                "trade_value": 333_333.33,
                "data_note": "演示数据",
            }
        ]
    )
    position_records = get_sample_strategy_result()[["trade_date", "ts_code", "weight"]].copy()
    position_records["data_note"] = "演示数据"
    return {
        "annual_return": 0.12,
        "max_drawdown": -0.035,
        "sharpe_ratio": 1.05,
        "win_rate": 0.55,
        "turnover": 1.8,
        "yearly_returns": {"2024": 0.021},
        "equity_curve": equity_curve,
        "trade_records": trade_records,
        "position_records": position_records,
        "data_note": "演示数据",
    }


def get_sample_dashboard_data() -> dict[str, Any]:
    """Return the complete synthetic dataset consumed by the Streamlit dashboard."""
    stock_basic = get_sample_stock_basic()
    price = get_sample_daily_price()
    daily_basic = get_sample_daily_basic()
    factor_scores = get_sample_factor_scores()
    strategy_result = get_sample_strategy_result()
    return {
        "data_source": DEMO_DATA_SOURCE,
        "selection": strategy_result,
        "stock_basic": stock_basic,
        "price": price,
        "daily_basic": daily_basic,
        "factor_scores": factor_scores,
        "backtest": get_sample_backtest_result(),
        "tables": {
            "stock_basic": stock_basic,
            "daily_price": price,
            "daily_basic": daily_basic,
            "factor_scores": factor_scores,
            "strategy_result": strategy_result,
            "backtest_result": pd.DataFrame([{"strategy_name": "demo", "data_note": "演示数据"}]),
        },
    }
