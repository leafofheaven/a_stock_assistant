"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.data_sources.real_universe import is_full_universe_preset
from core.data_sources.universe_presets import get_universe_preset, to_akshare_symbol


class Settings(BaseSettings):
    """Runtime settings for the stock assistant application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tushare_token: str = Field(default="", validation_alias="TUSHARE_TOKEN")
    data_dir: Path = Field(default=Path("./data"), validation_alias="DATA_DIR")
    duckdb_path: Path = Field(
        default=Path("./data/a_stock_assistant.duckdb"),
        validation_alias="DUCKDB_PATH",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    default_top_n: int = Field(default=30, validation_alias="DEFAULT_TOP_N")
    default_backtest_top_n: int = Field(
        default=20,
        validation_alias="DEFAULT_BACKTEST_TOP_N",
    )
    data_provider: str = Field(default="tushare", validation_alias="DATA_PROVIDER")
    enable_akshare_fallback: bool = Field(
        default=False,
        validation_alias="ENABLE_AKSHARE_FALLBACK",
    )
    real_data_start_date: str = Field(default="20240101", validation_alias="REAL_DATA_START_DATE")
    real_data_end_date: str = Field(default="", validation_alias="REAL_DATA_END_DATE")
    real_data_sample_symbols: str = Field(
        default="000001.SZ,600000.SH,000002.SZ",
        validation_alias="REAL_DATA_SAMPLE_SYMBOLS",
    )
    akshare_sample_symbols: str = Field(
        default="000001,600000,000002",
        validation_alias="AKSHARE_SAMPLE_SYMBOLS",
    )
    akshare_adjust: str = Field(default="qfq", validation_alias="AKSHARE_ADJUST")
    real_universe_preset: str = Field(default="mini", validation_alias="REAL_UNIVERSE_PRESET")
    real_batch_size: int = Field(default=10, validation_alias="REAL_BATCH_SIZE")
    real_batch_sleep_seconds: float = Field(default=0.0, validation_alias="REAL_BATCH_SLEEP_SECONDS")
    real_max_retries: int = Field(default=1, validation_alias="REAL_MAX_RETRIES")
    real_request_timeout_seconds: int = Field(default=30, validation_alias="REAL_REQUEST_TIMEOUT_SECONDS")
    full_update_batch_size: int = Field(default=50, validation_alias="FULL_UPDATE_BATCH_SIZE")
    full_update_lookback_days: int = Field(default=250, validation_alias="FULL_UPDATE_LOOKBACK_DAYS")
    full_update_max_retries: int = Field(default=2, validation_alias="FULL_UPDATE_MAX_RETRIES")
    full_update_sleep_seconds: float = Field(default=0.2, validation_alias="FULL_UPDATE_SLEEP_SECONDS")
    full_update_resume: bool = Field(default=True, validation_alias="FULL_UPDATE_RESUME")
    full_update_max_symbols: int = Field(default=0, validation_alias="FULL_UPDATE_MAX_SYMBOLS")
    full_update_max_batches: int = Field(default=0, validation_alias="FULL_UPDATE_MAX_BATCHES")
    enable_stock_basic_enrichment: bool = Field(default=False, validation_alias="ENABLE_STOCK_BASIC_ENRICHMENT")
    full_enable_stock_basic_enrichment: bool = Field(default=False, validation_alias="FULL_ENABLE_STOCK_BASIC_ENRICHMENT")
    enable_valuation_enrichment: bool = Field(default=False, validation_alias="ENABLE_VALUATION_ENRICHMENT")
    full_enable_valuation_enrichment: bool = Field(default=False, validation_alias="FULL_ENABLE_VALUATION_ENRICHMENT")
    enable_real_basic_enrichment: bool = Field(
        default=True,
        validation_alias="ENABLE_REAL_BASIC_ENRICHMENT",
    )
    enable_real_valuation_enrichment: bool = Field(
        default=True,
        validation_alias="ENABLE_REAL_VALUATION_ENRICHMENT",
    )
    min_listing_days: int = Field(default=120, validation_alias="MIN_LISTING_DAYS")
    min_avg_amount_20d: float = Field(default=100_000_000, validation_alias="MIN_AVG_AMOUNT_20D")
    min_median_amount_20d: float = Field(default=50_000_000, validation_alias="MIN_MEDIAN_AMOUNT_20D")
    min_latest_amount: float = Field(default=30_000_000, validation_alias="MIN_LATEST_AMOUNT")
    min_traded_days_20d: int = Field(default=18, validation_alias="MIN_TRADED_DAYS_20D")
    include_bse: bool = Field(default=False, validation_alias="INCLUDE_BSE")

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """Normalize log level values to uppercase names."""
        return value.upper()

    @field_validator("data_provider")
    @classmethod
    def normalize_data_provider(cls, value: str) -> str:
        """Normalize data provider names to lowercase."""
        return value.lower()

    @property
    def sample_symbols(self) -> list[str]:
        """Return configured sample symbols as a clean list."""
        return [
            symbol.strip()
            for symbol in self.real_data_sample_symbols.split(",")
            if symbol.strip()
        ]

    @property
    def akshare_symbols(self) -> list[str]:
        """Return configured AKShare symbols or preset symbols as six-digit codes."""
        explicit = [
            symbol.strip()
            for symbol in self.akshare_sample_symbols.split(",")
            if symbol.strip()
        ]
        if explicit:
            return explicit
        if is_full_universe_preset(self.real_universe_preset):
            return []
        return [to_akshare_symbol(symbol) for symbol in get_universe_preset(self.real_universe_preset)]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings loaded from environment and .env."""
    return Settings()
