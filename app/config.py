"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """Normalize log level values to uppercase names."""
        return value.upper()


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings loaded from environment and .env."""
    return Settings()
