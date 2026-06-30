"""Tests for Streamlit dashboard helper functions."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from web.streamlit_app import (
    calculate_recent_returns,
    dataframe_to_csv,
    describe_dashboard_data_source,
    effective_pool_config,
    filter_factor_ranking,
    filter_selection_data,
    get_industry_options,
    load_dashboard_data,
    render_dashboard,
    _render_section,
    _lightweight_database_metrics,
    summarize_update_status,
)
from core.storage.duckdb_store import DuckDBStore


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


def test_effective_pool_config_full_uses_status_count() -> None:
    """Empty AKSHARE_SAMPLE_SYMBOLS with full preset should use resolved full universe count."""
    result = effective_pool_config(
        {"AKSHARE_SAMPLE_SYMBOLS": "", "REAL_UNIVERSE_PRESET": "full"},
        {"configured_symbol_count": 5048},
    )

    assert result["symbol_count"] == 5048
    assert "full 沪深 A 股全市场" in result["symbols_text"]


def test_lightweight_database_metrics_uses_real_daily_price_max_and_full_coverage(tmp_path) -> None:
    """Streamlit status should derive latest date and coverage from real local DuckDB tables."""
    store = DuckDBStore(tmp_path / "dashboard.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "market": "主板", "exchange": "SZSE"},
                {"ts_code": "600000.SH", "symbol": "600000", "name": "浦发银行", "market": "主板", "exchange": "SSE"},
                {"ts_code": "430001.BJ", "symbol": "430001", "name": "北交示例", "market": "北交所", "exchange": "BSE"},
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20240130", "open": 1, "high": 1, "low": 1, "close": 1, "pre_close": 1, "change": 0, "pct_chg": 0, "vol": 1, "amount": 1},
                {"ts_code": "600000.SH", "trade_date": "20240129", "open": 1, "high": 1, "low": 1, "close": 1, "pre_close": 1, "change": 0, "pct_chg": 0, "vol": 1, "amount": 1},
            ]
        ),
    )
    settings = SimpleNamespace(akshare_sample_symbols="", real_universe_preset="full", include_bse=False)
    tables = {"stock_basic": store.read_table("stock_basic"), "daily_price": store.read_table("daily_price")}

    metrics = _lightweight_database_metrics(settings, store, tables)

    assert metrics["configured_symbol_count"] == 2
    assert metrics["priced_symbol_count"] == 2
    assert metrics["latest_price_date"] == "20240130"
    assert metrics["coverage_rate"] == 1.0


def test_summarize_update_status_prefers_real_latest_price_override() -> None:
    """Database latest price date should not come from sample or stale report data."""
    status = summarize_update_status(
        {
            "daily_price": pd.DataFrame({"trade_date": ["20240101"]}),
            "_latest_price_date": "20240130",
            "_configured_symbol_count": 5048,
            "_priced_symbol_count": 197,
            "_coverage_rate": 197 / 5048,
        }
    )

    assert status["latest_price_date"] == "20240130"
    assert status["configured_symbol_count"] == 5048
    assert status["priced_symbol_count"] == 197


def test_load_dashboard_data_does_not_show_sample_when_strategy_result_empty(tmp_path, monkeypatch) -> None:
    """Real DuckDB with prices but empty strategy_result should render an empty real state, not demo stocks."""
    db_path = tmp_path / "real-empty-selection.duckdb"
    store = DuckDBStore(db_path)
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame([{"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "market": "主板", "exchange": "SZSE"}]),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20240130",
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "pre_close": 1,
                    "change": 0,
                    "pct_chg": 0,
                    "vol": 1,
                    "amount": 1,
                }
            ]
        ),
    )
    settings = SimpleNamespace(
        data_provider="akshare",
        duckdb_path=db_path,
        akshare_sample_symbols="",
        real_universe_preset="full",
        include_bse=False,
    )
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("core.storage.duckdb_store.get_settings", lambda: settings)

    data = load_dashboard_data()

    assert "sample" not in data["data_source"].lower()
    assert data["selection"].empty
    assert data["tables"]["_latest_price_date"] == "20240130"


def test_load_dashboard_data_reads_latest_strategy_result_from_duckdb(tmp_path, monkeypatch) -> None:
    """Streamlit should display persisted local strategy_result rows instead of sample data."""
    db_path = tmp_path / "real-selection.duckdb"
    store = DuckDBStore(db_path)
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame([{"ts_code": "603986.SH", "symbol": "603986", "name": "兆易创新", "industry": "半导体", "market": "主板", "exchange": "SSE"}]),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {
                    "ts_code": "603986.SH",
                    "trade_date": "20260626",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "pre_close": 100.0,
                    "change": 0.5,
                    "pct_chg": 0.5,
                    "vol": 1_000_000,
                    "amount": 200_000_000,
                }
            ]
        ),
    )
    store.upsert_dataframe(
        "strategy_result",
        pd.DataFrame(
            [
                {
                    "trade_date": "20260626",
                    "rank": 1,
                    "ts_code": "603986.SH",
                    "name": "兆易创新",
                    "industry": "半导体",
                    "close": 100.5,
                    "pe": 32.0,
                    "pb": 5.1,
                    "total_score": 68.37,
                    "trend_score": 70.0,
                    "momentum_score": 65.0,
                    "liquidity_score": 80.0,
                    "fundamental_score": 55.0,
                    "volatility_score": 60.0,
                    "quality_score": 55.0,
                    "valuation_score": 58.0,
                    "risk_score": 60.0,
                    "select_reason": "综合分 68.37",
                    "risk_note": "需人工复核",
                }
            ]
        ),
    )
    settings = SimpleNamespace(
        data_provider="akshare",
        duckdb_path=db_path,
        akshare_sample_symbols="",
        real_universe_preset="full",
        include_bse=False,
    )
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("core.storage.duckdb_store.get_settings", lambda: settings)

    data = load_dashboard_data()

    assert "sample" not in data["data_source"].lower()
    assert data["selection"]["ts_code"].tolist() == ["603986.SH"]
    assert data["selection"]["total_score"].tolist() == [68.37]
    assert summarize_update_status(data["tables"])["latest_selection_date"] == "20260626"


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
    assert fake_streamlit.tab_names == [
        "今日选股",
        "个股详情",
        "因子排名",
        "选股逻辑",
        "埃尔德复核",
        "观察池跟踪",
        "持仓池",
        "策略回测",
        "数据更新状态",
        "本地控制台",
    ]
    assert fake_streamlit.info_messages


def test_render_dashboard_shows_database_locked_status(monkeypatch) -> None:
    """Dashboard should render a locked database warning instead of crashing."""
    fake_streamlit = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    render_dashboard(
        {
            "selection": pd.DataFrame(),
            "stock_basic": pd.DataFrame(),
            "price": pd.DataFrame(),
            "factor_scores": pd.DataFrame(),
            "backtest": {},
            "tables": {
                "_database_status": {
                    "status": "locked",
                    "message": "DuckDB is locked by another process. Please stop other running jobs or Streamlit first.",
                    "duckdb_path": "data/a_stock_assistant.duckdb",
                }
            },
        }
    )

    assert fake_streamlit.error_messages
    assert "DuckDB 被锁定" in fake_streamlit.error_messages[0]


def test_render_section_catches_block_errors() -> None:
    """A failing page section should not raise through the top-level dashboard."""
    fake_streamlit = FakeStreamlit()

    def fail_section() -> None:
        raise RuntimeError("mock block failure")

    _render_section(fake_streamlit, "测试区块", fail_section)

    assert any("测试区块 加载失败" in message for message in fake_streamlit.error_messages)


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
        self.error_messages: list[str] = []
        self.warning_messages: list[str] = []

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
        self.warning_messages.append(text)

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

    def text_input(self, label: str, value: str = "", **kwargs) -> str:
        return value

    def number_input(self, label: str, **kwargs):
        return kwargs.get("value", 0)

    def text_area(self, label: str, value: str = "", **kwargs) -> str:
        return value

    def form(self, key: str) -> FakeForm:
        return FakeForm()

    def form_submit_button(self, label: str) -> bool:
        return False

    def button(self, label: str, **kwargs) -> bool:
        return False

    def success(self, text: str) -> None:
        return None

    def error(self, text: str) -> None:
        self.error_messages.append(text)

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
