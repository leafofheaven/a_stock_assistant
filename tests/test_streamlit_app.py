"""Tests for Streamlit dashboard helper functions."""

from __future__ import annotations

import pandas as pd

from web.streamlit_app import (
    calculate_recent_returns,
    dataframe_to_csv,
    filter_factor_ranking,
    filter_selection_data,
    get_industry_options,
    summarize_update_status,
)


def test_filter_selection_data_filters_and_sorts() -> None:
    """Selection helper should filter industry and sort by score."""
    df = _selection_df()

    result = filter_selection_data(df, industry="银行", sort_descending=True)

    assert result["industry"].tolist() == ["银行", "银行"]
    assert result["ts_code"].tolist() == ["000002.SZ", "000001.SZ"]


def test_filter_selection_data_handles_empty_input() -> None:
    """Selection helper should return an empty table with expected columns."""
    result = filter_selection_data(pd.DataFrame())

    assert result.empty
    assert "total_score" in result.columns


def test_dataframe_to_csv_contains_headers_and_values() -> None:
    """CSV conversion should include headers and rows."""
    csv_text = dataframe_to_csv(pd.DataFrame({"ts_code": ["000001.SZ"], "total_score": [90]}))

    assert "ts_code,total_score" in csv_text
    assert "000001.SZ,90" in csv_text


def test_get_industry_options_handles_missing_data() -> None:
    """Industry options should be stable for empty and populated data."""
    assert get_industry_options(pd.DataFrame()) == ["全部"]
    assert get_industry_options(_selection_df()) == ["全部", "钢铁", "银行"]


def test_filter_factor_ranking_filters_date_industry_and_sorts() -> None:
    """Factor ranking helper should filter date and industry and sort factor descending."""
    result = filter_factor_ranking(_selection_df(), trade_date="20240101", industry="银行", factor_col="total_score")

    assert result["ts_code"].tolist() == ["000002.SZ", "000001.SZ"]


def test_calculate_recent_returns_handles_missing_and_short_data() -> None:
    """Recent return helper should not crash when data is short or missing."""
    short = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240101"], "close": [10.0]})

    assert calculate_recent_returns(pd.DataFrame(), "000001.SZ") == {"return_20d": None, "return_60d": None}
    assert calculate_recent_returns(short, "000001.SZ") == {"return_20d": None, "return_60d": None}


def test_calculate_recent_returns_computes_20d_and_60d() -> None:
    """Recent return helper should calculate 20-day and 60-day changes."""
    price = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 65,
            "trade_date": [f"202401{index + 1:02d}" for index in range(65)],
            "close": [100 + index for index in range(65)],
        }
    )

    returns = calculate_recent_returns(price, "000001.SZ")

    assert returns["return_20d"] == 164 / 144 - 1
    assert returns["return_60d"] == 164 / 104 - 1


def test_summarize_update_status_returns_dates_and_row_counts() -> None:
    """Status helper should summarize latest dates and table row counts."""
    tables = {
        "daily_price": pd.DataFrame({"trade_date": ["20240101", "20240102"]}),
        "factor_scores": pd.DataFrame({"trade_date": ["20240101"]}),
        "strategy_result": pd.DataFrame({"trade_date": ["20240103"]}),
    }

    status = summarize_update_status(tables)

    assert status["latest_price_date"] == "20240102"
    assert status["latest_factor_date"] == "20240101"
    assert status["latest_selection_date"] == "20240103"
    assert status["table_rows"]["daily_price"] == 2


def _selection_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": ["20240101", "20240101", "20240101"],
            "rank": [1, 2, 3],
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "name": ["平安银行", "招商银行", "宝钢股份"],
            "industry": ["银行", "银行", "钢铁"],
            "total_score": [80, 90, 70],
            "trend_score": [80, 90, 70],
            "momentum_score": [80, 90, 70],
            "liquidity_score": [80, 90, 70],
            "fundamental_score": [80, 90, 70],
            "volatility_score": [80, 90, 70],
            "select_reason": ["综合分靠前", "综合分靠前", "综合分靠前"],
            "risk_note": ["复核风险", "复核风险", "复核风险"],
        }
    )
