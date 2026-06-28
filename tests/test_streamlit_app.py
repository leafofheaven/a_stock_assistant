"""Tests for Streamlit dashboard helper functions."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from web.streamlit_app import (
    calculate_recent_returns,
    dataframe_to_csv,
    describe_dashboard_data_source,
    filter_factor_ranking,
    filter_selection_data,
    get_industry_options,
    render_dashboard,
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


def test_describe_dashboard_data_source_marks_sample_and_real_data() -> None:
    """Dashboard data source helper should label sample and real data clearly."""
    sample = describe_dashboard_data_source({"data_source": "sample 数据（演示）", "tables": {}})
    real = describe_dashboard_data_source(
        {
            "data_source": "tushare 本地 DuckDB 真实数据",
            "tables": {"daily_price": pd.DataFrame({"trade_date": ["20240101", "20240103"]})},
        }
    )

    assert "演示数据" in sample["message"]
    assert "最新交易日期：20240103" in real["message"]


def test_render_dashboard_creates_title_and_tabs_for_empty_data(monkeypatch) -> None:
    """Dashboard render should show title and tabs even when no real data exists."""
    fake_streamlit = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    render_dashboard(
        {
            "selection": pd.DataFrame(),
            "stock_basic": pd.DataFrame(),
            "price": pd.DataFrame(),
            "factor_scores": pd.DataFrame(),
            "backtest": {},
            "tables": {},
        }
    )

    assert fake_streamlit.title_text == "A 股选股辅助"
    assert fake_streamlit.tab_names == ["今日选股", "个股详情", "因子排名", "选股逻辑", "策略回测", "数据更新状态", "本地控制台"]
    assert fake_streamlit.info_messages


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


class FakeTab:
    """Minimal context manager used to test Streamlit tab rendering."""

    def __enter__(self) -> "FakeTab":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeForm(FakeTab):
    """Minimal form context manager."""

    def form_submit_button(self, label: str) -> bool:
        return False


class FakeStreamlit:
    """Small fake of the Streamlit API used by render_dashboard."""

    def __init__(self) -> None:
        self.title_text = ""
        self.tab_names: list[str] = []
        self.info_messages: list[str] = []

    def set_page_config(self, **kwargs) -> None:
        return None

    def title(self, text: str) -> None:
        self.title_text = text

    def caption(self, text: str) -> None:
        return None

    def tabs(self, names: list[str]) -> list[FakeTab]:
        self.tab_names = names
        return [FakeTab() for _ in names]

    def subheader(self, text: str) -> None:
        return None

    def info(self, text: str) -> None:
        self.info_messages.append(text)

    def warning(self, text: str) -> None:
        return None

    def metric(self, label: str, value) -> None:
        return None

    def write(self, value) -> None:
        return None

    def dataframe(self, data, **kwargs) -> None:
        return None

    def json(self, value) -> None:
        return None

    def line_chart(self, data) -> None:
        return None

    def selectbox(self, label: str, options, **kwargs):
        return list(options)[0] if options else None

    def radio(self, label: str, options, **kwargs):
        return list(options)[0] if options else None

    def checkbox(self, label: str, value: bool = False, **kwargs) -> bool:
        return value

    def text_input(self, label: str, value: str = "") -> str:
        return value

    def number_input(self, label: str, **kwargs):
        return kwargs.get("value", 0)

    def form(self, key: str) -> FakeForm:
        return FakeForm()

    def form_submit_button(self, label: str) -> bool:
        return False

    def button(self, label: str, **kwargs) -> bool:
        return False

    def success(self, text: str) -> None:
        return None

    def error(self, text: str) -> None:
        return None

    def spinner(self, text: str) -> FakeTab:
        return FakeTab()

    def expander(self, text: str, **kwargs) -> FakeTab:
        return FakeTab()

    def code(self, text: str) -> None:
        return None

    def download_button(self, *args, **kwargs) -> None:
        return None

    def columns(self, count: int):
        return [SimpleNamespace(metric=lambda label, value: None) for _ in range(count)]
