"""Tests for application configuration."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings


def test_settings_defaults() -> None:
    """Settings should provide safe local defaults."""
    settings = Settings(_env_file=None)

    assert settings.tushare_token == ""
    assert settings.data_dir == Path("./data")
    assert settings.duckdb_path == Path("./data/a_stock_assistant.duckdb")
    assert settings.log_level == "INFO"
    assert settings.default_top_n == 30
    assert settings.default_backtest_top_n == 20
    assert settings.data_provider == "tushare"
    assert settings.enable_akshare_fallback is False
    assert settings.real_data_start_date == "20240101"
    assert settings.real_data_end_date == ""
    assert settings.sample_symbols == ["000001.SZ", "600000.SH", "000002.SZ"]
    assert settings.akshare_symbols == ["000001", "600000", "000002"]
    assert settings.akshare_adjust == "qfq"


def test_settings_loads_from_env_file(tmp_path: Path) -> None:
    """Settings should load supported values from a .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TUSHARE_TOKEN=test-token",
                "DATA_DIR=/tmp/a-stock-data",
                "DUCKDB_PATH=/tmp/a-stock-data/test.duckdb",
                "LOG_LEVEL=debug",
                "DEFAULT_TOP_N=12",
                "DEFAULT_BACKTEST_TOP_N=8",
                "DATA_PROVIDER=tushare",
                "ENABLE_AKSHARE_FALLBACK=true",
                "REAL_DATA_START_DATE=20240201",
                "REAL_DATA_END_DATE=20240229",
                "REAL_DATA_SAMPLE_SYMBOLS=000001.SZ, 600000.SH",
                "AKSHARE_SAMPLE_SYMBOLS=000001, 600000",
                "AKSHARE_ADJUST=hfq",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.tushare_token == "test-token"
    assert settings.data_dir == Path("/tmp/a-stock-data")
    assert settings.duckdb_path == Path("/tmp/a-stock-data/test.duckdb")
    assert settings.log_level == "DEBUG"
    assert settings.default_top_n == 12
    assert settings.default_backtest_top_n == 8
    assert settings.data_provider == "tushare"
    assert settings.enable_akshare_fallback is True
    assert settings.real_data_start_date == "20240201"
    assert settings.real_data_end_date == "20240229"
    assert settings.sample_symbols == ["000001.SZ", "600000.SH"]
    assert settings.akshare_symbols == ["000001", "600000"]
    assert settings.akshare_adjust == "hfq"


def test_environment_overrides_env_file(tmp_path: Path, monkeypatch) -> None:
    """Environment variables should take precedence over .env values."""
    env_file = tmp_path / ".env"
    env_file.write_text("DEFAULT_TOP_N=10\nLOG_LEVEL=warning\n", encoding="utf-8")
    monkeypatch.setenv("DEFAULT_TOP_N", "25")
    monkeypatch.setenv("LOG_LEVEL", "error")

    settings = Settings(_env_file=env_file)

    assert settings.default_top_n == 25
    assert settings.log_level == "ERROR"


def test_get_settings_returns_cached_settings(monkeypatch) -> None:
    """get_settings should cache the settings object for application reuse."""
    get_settings.cache_clear()
    monkeypatch.setenv("DEFAULT_BACKTEST_TOP_N", "15")

    first = get_settings()
    second = get_settings()

    assert first is second
    assert first.default_backtest_top_n == 15
    get_settings.cache_clear()
