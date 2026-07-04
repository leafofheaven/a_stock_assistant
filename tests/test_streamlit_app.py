"""Tests for Streamlit dashboard helper functions."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from web.streamlit_app import (
    calculate_recent_returns,
    dataframe_to_csv,
    describe_dashboard_data_source,
    display_dataframe,
    effective_pool_config,
    filter_factor_ranking,
    filter_selection_data,
    format_elder_review_display,
    get_industry_options,
    load_dashboard_data,
    latest_external_positions,
    parse_external_position_text,
    prepare_display_table,
    render_dashboard,
    _extract_workbook_output_path,
    _merge_scheduled_quality_fallback,
    _render_section,
    _render_status_tab,
    _lightweight_database_metrics,
    _status_data_quality_snapshot,
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


def test_format_elder_review_display_uses_continuous_display_order_and_source() -> None:
    """Candidate rank may repeat across sources, but display_order must be clear."""
    review = pd.DataFrame(
        {
            "rank": [1, 2, 1],
            "ts_code": ["000001.SZ", "000002.SZ", "600000.SH"],
            "name": ["平安银行", "万科A", "浦发银行"],
            "total_score": [90.0, 80.0, 70.0],
            "elder_score": [50, 60, 55],
        }
    )
    candidate = format_elder_review_display(review.iloc[:2], source="今日候选")
    watch = format_elder_review_display(review.iloc[2:], source="观察池")
    combined = pd.concat([candidate, watch], ignore_index=True)
    combined["display_order"] = range(1, len(combined) + 1)

    assert combined["display_order"].tolist() == [1, 2, 3]
    assert combined["candidate_rank"].tolist() == [1, 2, 1]
    assert combined["source"].tolist() == ["今日候选", "今日候选", "观察池"]
    assert combined["total_score"].tolist() == [90.0, 80.0, 70.0]


def test_dataframe_to_csv_contains_headers_and_values() -> None:
    """CSV conversion should include headers and rows."""
    csv_text = dataframe_to_csv(pd.DataFrame({"ts_code": ["000001.SZ"], "total_score": [90]}))

    assert "ts_code,total_score" in csv_text
    assert "000001.SZ,90" in csv_text


def test_streamlit_tables_hide_raw_index() -> None:
    """Display helper should hide pandas raw index through hide_index=True."""
    fake = FakeStreamlit()
    df = pd.DataFrame({"rank": [2, 1], "ts_code": ["000002.SZ", "000001.SZ"]}, index=[9, 10])

    display_dataframe(fake, df)

    rendered = fake.dataframes[0]
    assert rendered["序号"].tolist() == [1, 2]
    assert 9 not in rendered.index.tolist()
    assert fake.hide_index_values == [True]
    assert fake.width_values == ["stretch"]


def test_display_order_continuous_after_sort() -> None:
    """Sorting by total_score should keep display_order continuous."""
    sorted_df = filter_selection_data(_selection_df(), sort_descending=True)
    display = prepare_display_table(sorted_df)

    assert display["序号"].tolist() == list(range(1, len(display) + 1))
    assert "原始选股排名" not in display.columns
    assert "rank" not in display.columns


def test_rank_columns_are_renamed_for_display() -> None:
    """Ambiguous candidate rank fields should be hidden from default user-facing tables."""
    display = prepare_display_table(pd.DataFrame({"rank": [1], "today_rank": [2], "previous_rank": [3]}))

    assert "rank" not in display.columns
    assert "原始选股排名" not in display.columns
    assert "观察池当日排名" in display.columns
    assert "上一日排名" in display.columns


def test_elder_review_has_source_and_display_order() -> None:
    """Elder review display should include source and continuous order."""
    review = pd.DataFrame({"rank": [2, 1], "ts_code": ["000002.SZ", "000001.SZ"], "total_score": [80, 90]})

    result = format_elder_review_display(review, source="今日候选")
    display = prepare_display_table(result)

    assert result["display_order"].tolist() == [1, 2]
    assert result["candidate_rank"].tolist() == [1, 2]
    assert result["source"].tolist() == ["今日候选", "今日候选"]
    assert "原始选股排名" not in display.columns


def test_update_entrypoints_are_consolidated() -> None:
    """Local console should not keep a second ambiguous data update entrypoint."""
    from core.runtime.command_runner import ALLOWED_COMMANDS

    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")

    assert "保存并更新数据" not in source
    assert "更新真实数据" not in source
    assert "全市场批量补数据" in source
    assert "本页用于补充 / 更新 full 股票池行情数据" in source
    assert "run_full_batch_update" in source
    assert "preflight_data_source" in source
    assert "run_full_batch_update" in ALLOWED_COMMANDS
    assert "preflight_data_source" in ALLOWED_COMMANDS


def test_export_workbook_page_feedback_helpers() -> None:
    """Workbook export UI should extract a concrete output path for feedback/download."""
    output = "每日研究工作簿导出完成\n输出文件: /tmp/a_stock_assistant_task53/daily_research.xlsx\n"

    path = _extract_workbook_output_path(output)

    assert path == Path("/tmp/a_stock_assistant_task53/daily_research.xlsx")


def test_export_does_not_run_workflow_or_update() -> None:
    """Workbook export UI should call the export command, not update/workflow commands."""
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    export_section = source.split("def _export_workbook_button", 1)[1].split("def _extract_workbook_output_path", 1)[0]

    assert "export_daily_research_workbook" in export_section
    assert "update_real_data" not in export_section
    assert "run_daily_workflow" not in export_section


def test_no_algorithm_changes_for_task54() -> None:
    """Task 54 should stay in the UI layer and leave scoring modules untouched."""
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")

    assert "calculate_total_score(" not in source
    assert "DEFAULT_WEIGHTS" not in source
    assert "normalize_factor(" not in source


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
        "买入区间分析",
        "外部模拟持仓导入",
        "持仓池",
        "策略回测",
        "数据更新状态",
        "本地控制台",
    ]
    assert fake_streamlit.info_messages


def test_data_update_status_page_shows_data_quality_section() -> None:
    """Data update status page should expose formal-result data quality fields."""
    source = (Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py").read_text(encoding="utf-8")
    for phrase in [
        "数据质量等级",
        "正式全市场研究结果可用",
        "流程完成不等于数据完整",
        "最新交易日行情覆盖严重不足",
        "latest_daily_price_coverage_rate",
        "latest_daily_basic_coverage_rate",
        "latest_adj_factor_coverage_rate",
        "任意历史行情覆盖",
        "顶部结论卡片",
        "高级：原始自动更新状态 JSON",
    ]:
        assert phrase in source


def test_data_update_status_page_has_diagnosis_buttons() -> None:
    """Diagnostics should be user-triggered buttons, not automatic page-start jobs."""
    source = (Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py").read_text(encoding="utf-8")
    assert "运行数据质量诊断" in source
    assert "运行批量更新诊断" in source
    assert '"diagnose_real_data"' in source
    assert '"diagnose_update_batch"' in source
    assert "ALLOWED_COMMANDS.setdefault(\"diagnose_real_data\"" in source
    assert "ALLOWED_COMMANDS.setdefault(\"diagnose_update_batch\"" in source


def test_data_update_status_page_marks_poor_coverage() -> None:
    """Old scheduled status should be enriched from read-only update diagnostics."""
    merged = _merge_scheduled_quality_fallback(
        {"status": "warning", "stage": "done", "research_trade_date": "20260703"},
        {
            "configured_symbol_count": 5055,
            "latest_trade_date": "20260703",
            "latest_daily_price_symbol_count": 68,
            "missing_latest_daily_price_symbol_count": 4987,
            "latest_daily_price_coverage_rate": 0.0135,
            "latest_daily_basic_symbol_count": 3,
            "latest_daily_basic_coverage_rate": 0.0006,
            "latest_adj_factor_symbol_count": 0,
            "latest_adj_factor_coverage_rate": 0.0,
        },
    )
    assert merged["data_quality_status"] == "poor"
    assert merged["formal_result_usable"] is False
    assert merged["latest_completed_trade_date"] == "20260703"
    assert "仅供流程检查" in merged["formal_result_warning_reason"]


def test_missing_data_quality_fields_do_not_default_to_ok() -> None:
    """Missing quality fields should not be treated as ok."""
    merged = _merge_scheduled_quality_fallback(
        {"status": "warning", "stage": "done", "research_trade_date": "20260703"},
        {},
    )

    assert merged["data_quality_status"] == "unknown"
    assert merged["formal_result_usable"] is False


def test_missing_formal_result_usable_does_not_default_to_true() -> None:
    """Missing usability should not become true implicitly."""
    merged = _merge_scheduled_quality_fallback(
        {"status": "warning", "stage": "done", "research_trade_date": "20260703", "latest_daily_price_coverage_rate": 0.0},
        {},
    )

    assert merged["formal_result_usable"] is False


def test_data_update_page_uses_current_snapshot_for_poor_quality() -> None:
    """Current read-only snapshot should override stale scheduled ok quality."""
    merged = _merge_scheduled_quality_fallback(
        {
            "status": "warning",
            "stage": "done",
            "research_trade_date": "20260703",
            "data_quality_status": "ok",
            "formal_result_usable": True,
        },
        {
            "configured_symbol_count": 5055,
            "latest_completed_trade_date": "20260703",
            "latest_daily_price_symbol_count": 68,
            "missing_latest_daily_price_symbol_count": 4987,
            "latest_daily_price_coverage_rate": 0.0135,
            "data_quality_status": "poor",
            "formal_result_usable": False,
            "formal_result_warning_reason": "最新交易日数据覆盖严重不足",
        },
    )

    assert merged["data_quality_status"] == "poor"
    assert merged["formal_result_usable"] is False
    assert merged["latest_daily_price_symbol_count"] == 68


def test_data_update_page_raw_json_is_collapsed_by_default() -> None:
    """Raw scheduled JSON should be hidden behind an expander."""
    source = (Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py").read_text(encoding="utf-8")
    assert "高级：原始自动更新状态 JSON" in source
    assert "expanded=False" in source
    assert "顶部结论卡片" in source


def test_status_tab_does_not_render_lookback_analysis_section() -> None:
    """Data update tab should not render the automatic lookback action section."""
    body = inspect.getsource(_render_status_tab)

    assert "_render_lookback_analysis_section" not in body


def test_status_tab_has_no_run_lookback_analysis_button() -> None:
    """The run_lookback_analysis button must only live outside the status tab."""
    body = inspect.getsource(_render_status_tab)

    assert "run_lookback_analysis_button" not in body


def test_status_tab_default_view_uses_scheduled_update_section_only() -> None:
    """The default status tab should start with scheduled quality and batch update sections."""
    body = inspect.getsource(_render_status_tab)

    assert "_render_scheduled_update_section(st, status)" in body
    assert "_render_full_batch_update_section(st, status)" in body
    assert 'st.metric("最新行情日期"' not in body
    assert 'st.write("最新数据覆盖")' not in body


def test_old_status_sections_are_collapsed_by_default() -> None:
    """Legacy diagnostics should be available only in collapsed advanced sections."""
    body = inspect.getsource(_render_status_tab)

    assert 'st.expander("高级：旧版诊断信息", expanded=False)' in body
    assert 'st.expander("高级：最近报告文件", expanded=False)' in body
    assert 'st.expander("高级：观察池明细", expanded=False)' in body
    assert 'st.expander("高级：本地数据库和备份", expanded=False)' in body


def test_no_duplicate_streamlit_keys_for_lookback_button() -> None:
    """Only the strategy/backtest lookback section should define the lookback button key."""
    source = (Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py").read_text(encoding="utf-8")

    assert source.count('key="run_lookback_analysis_button"') == 1


def test_latest_coverage_counts_actual_trade_date(tmp_path: Path) -> None:
    """Status-page snapshot should query DuckDB and count only the requested trade date."""
    store = DuckDBStore(tmp_path / "coverage.duckdb")
    store.initialize()
    symbols = [f"{index:06d}.SZ" for index in range(1, 5056)]
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            {
                "ts_code": symbols,
                "symbol": [code[:6] for code in symbols],
                "name": [f"股票{index}" for index in range(1, 5056)],
                "market": ["主板"] * 5055,
                "exchange": ["SZSE"] * 5055,
            }
        ),
    )
    priced_symbols = symbols[:4995]
    latest_symbols = set(symbols[:68])
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {
                    "ts_code": symbol,
                    "trade_date": "20260703" if symbol in latest_symbols else "20260630",
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "pre_close": 1.0,
                    "change": 0.0,
                    "pct_chg": 0.0,
                    "vol": 1.0,
                    "amount": 1.0,
                }
                for symbol in priced_symbols
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_basic",
        pd.DataFrame(
            {
                "ts_code": symbols[:3],
                "trade_date": ["20260703"] * 3,
                "turnover_rate": [1.0] * 3,
                "pe": [10.0] * 3,
                "pb": [1.0] * 3,
            }
        ),
    )

    snapshot = _status_data_quality_snapshot({"_duckdb_path": str(store.db_path)}, "20260703")

    assert snapshot["configured_symbol_count"] == 5055
    assert snapshot["latest_daily_price_symbol_count"] == 68
    assert snapshot["latest_daily_basic_symbol_count"] == 3
    assert snapshot["latest_adj_factor_symbol_count"] == 0
    assert snapshot["latest_all_required_tables_symbol_count"] == 0
    assert snapshot["any_daily_price_symbol_count"] == 4995
    assert snapshot["latest_daily_price_coverage_rate"] == 68 / 5055
    assert snapshot["any_daily_price_coverage_rate"] == 4995 / 5055
    assert snapshot["data_quality_status"] == "poor"
    assert snapshot["formal_result_usable"] is False


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


def test_external_position_helpers_parse_and_select_latest_snapshot() -> None:
    """External simulated position helpers should parse text and select latest snapshots."""
    parsed = parse_external_position_text("ts_code\tquantity\n000725\t100\n")
    snapshots = pd.DataFrame(
        {
            "snapshot_date": ["20260629", "20260630"],
            "ts_code": ["000001.SZ", "000725.SZ"],
            "quantity": [1000, 2000],
        }
    )

    latest = latest_external_positions({"external_position_snapshots": snapshots})

    assert parsed["ts_code"].tolist() == ["000725"]
    assert latest["ts_code"].tolist() == ["000725.SZ"]


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
        self.dataframes: list[pd.DataFrame] = []
        self.hide_index_values: list[object] = []
        self.width_values: list[object] = []

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
        self.dataframes.append(data)
        self.hide_index_values.append(kwargs.get("hide_index"))
        self.width_values.append(kwargs.get("width"))

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

    def file_uploader(self, label: str, **kwargs):
        return None

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
        return [self for _ in range(count)]
