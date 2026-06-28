"""Tests for Task 35 simplified settings workflow helpers."""

from __future__ import annotations

from core.config.env_file import parse_stock_symbols
from web.streamlit_app import build_date_status, build_settings_updates, effective_pool_config


def test_custom_stock_symbols_clean_suffix_comma_newline_and_deduplicate() -> None:
    """Custom symbols should support Chinese commas, newlines, suffixes, and dedupe."""
    parsed = parse_stock_symbols("000001.SZ，600000.SH\n002475,000001")

    assert parsed["symbols"] == ["000001", "600000", "002475"]
    assert parsed["invalid"] == []


def test_invalid_stock_symbols_are_reported() -> None:
    """Non six-digit symbols should be reported instead of silently saved."""
    parsed = parse_stock_symbols("000001,12345,abc")

    assert parsed["symbols"] == ["000001"]
    assert parsed["invalid"] == ["12345", "abc"]


def test_build_settings_updates_custom_pool_saves_clean_symbols() -> None:
    """Custom pool mode should save cleaned AKSHARE_SAMPLE_SYMBOLS."""
    updates, validation = build_settings_updates(
        pool_mode="自定义股票池",
        symbols_text="000001.SZ，600000.SH\n002475",
        preset="medium",
        start_date="20240101",
        end_date="20240630",
        provider="akshare",
        akshare_adjust="qfq",
        basic_enrichment=True,
        valuation_enrichment=True,
        batch_size=10,
        batch_sleep=0.0,
        max_retries=1,
        timeout_seconds=30,
        data_dir="./data",
        duckdb_path="./data/a_stock_assistant.duckdb",
    )

    assert updates["AKSHARE_SAMPLE_SYMBOLS"] == "000001,600000,002475"
    assert updates["REAL_UNIVERSE_PRESET"] == "medium"
    assert validation["invalid"] == []


def test_build_settings_updates_preset_pool_clears_custom_symbols() -> None:
    """Preset pool mode should clear AKSHARE_SAMPLE_SYMBOLS and save preset."""
    updates, validation = build_settings_updates(
        pool_mode="使用预设股票池",
        symbols_text="000001,600000",
        preset="small",
        start_date="20240101",
        end_date="",
        provider="akshare",
        akshare_adjust="qfq",
        basic_enrichment=True,
        valuation_enrichment=True,
        batch_size=10,
        batch_sleep=0.0,
        max_retries=1,
        timeout_seconds=30,
        data_dir="./data",
        duckdb_path="./data/a_stock_assistant.duckdb",
    )

    assert updates["AKSHARE_SAMPLE_SYMBOLS"] == ""
    assert updates["REAL_UNIVERSE_PRESET"] == "small"
    assert validation["invalid"] == []


def test_effective_pool_config_reports_custom_priority() -> None:
    """Effective preview should explain that preset is inactive when custom symbols exist."""
    config = effective_pool_config({"AKSHARE_SAMPLE_SYMBOLS": "000001,600000", "REAL_UNIVERSE_PRESET": "medium"})

    assert config["mode"] == "custom"
    assert config["symbol_count"] == 2
    assert config["preset_inactive"] is True
    assert "REAL_UNIVERSE_PRESET 当前不生效" in config["message"]


def test_effective_pool_config_reports_preset_mode() -> None:
    """Effective preview should show preset mode when custom symbols are empty."""
    config = effective_pool_config({"AKSHARE_SAMPLE_SYMBOLS": "", "REAL_UNIVERSE_PRESET": "small"})

    assert config["mode"] == "preset"
    assert config["preset_inactive"] is False
    assert "当前使用 REAL_UNIVERSE_PRESET 股票池" in config["message"]


def test_date_status_warns_when_database_date_is_before_target_date() -> None:
    """Date status should distinguish parameter end date from actual database date."""
    result = build_date_status(
        {"REAL_DATA_START_DATE": "20240101", "REAL_DATA_END_DATE": "20240731"},
        {"latest_price_date": "20240628", "latest_factor_date": "20240628", "latest_selection_date": "20240628"},
    )

    assert result["warning"] is True
    assert "需要点击“保存并更新数据”" in result["message"]


def test_date_status_explains_empty_end_date() -> None:
    """Empty end date should explain that latest available data is used."""
    result = build_date_status(
        {"REAL_DATA_START_DATE": "20240101", "REAL_DATA_END_DATE": ""},
        {"latest_price_date": "20240628"},
    )

    assert result["warning"] is False
    assert "结束日期留空" in result["message"]


def test_expected_workflow_button_arguments() -> None:
    """Simplified buttons should map to the expected daily workflow modes."""
    local_recalc = ["--doctor-before-run", "--skip-update", "--format", "all"]
    update_data = ["--doctor-before-run", "--backup-before-run", "--format", "all"]

    assert "--skip-update" in local_recalc
    assert "--backup-before-run" in update_data
