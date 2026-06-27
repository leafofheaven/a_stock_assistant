"""Data provider selection helpers."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from core.data_sources.akshare_client import AKShareClient
from core.data_sources.base import DataSourceError, StockDataSource
from core.data_sources.tushare_client import TushareClient


SUPPORTED_PROVIDERS = {"sample", "tushare", "akshare"}


@dataclass(frozen=True)
class DataProviderSelection:
    """Selected primary data source and optional fallback."""

    provider_name: str
    primary: StockDataSource | None
    fallback_name: str | None = None
    fallback: StockDataSource | None = None
    message: str = ""


def select_data_provider(
    settings: Settings | None = None,
    primary_client: StockDataSource | None = None,
    fallback_client: StockDataSource | None = None,
) -> DataProviderSelection:
    """Select a data source client from settings.

    ``sample`` returns no real client. ``tushare`` remains the default primary
    provider, and AKShare is only selected directly or used as fallback when
    ``ENABLE_AKSHARE_FALLBACK`` is true.
    """
    resolved_settings = settings or get_settings()
    provider_name = resolved_settings.data_provider
    if provider_name not in SUPPORTED_PROVIDERS:
        raise DataSourceError(f"Unsupported DATA_PROVIDER: {provider_name}")

    if provider_name == "sample":
        return DataProviderSelection(
            provider_name="sample",
            primary=None,
            message="DATA_PROVIDER=sample，跳过真实数据源。",
        )

    if provider_name == "akshare":
        return DataProviderSelection(
            provider_name="akshare",
            primary=primary_client
            or AKShareClient(
                adjust=resolved_settings.akshare_adjust,
                request_timeout_seconds=getattr(resolved_settings, "real_request_timeout_seconds", 30),
            ),
            message="使用 AKShare 数据源。",
        )

    fallback = None
    fallback_name = None
    if getattr(resolved_settings, "enable_akshare_fallback", False):
        fallback = fallback_client or AKShareClient(
            adjust=resolved_settings.akshare_adjust,
            request_timeout_seconds=getattr(resolved_settings, "real_request_timeout_seconds", 30),
        )
        fallback_name = "akshare"

    return DataProviderSelection(
        provider_name="tushare",
        primary=primary_client or TushareClient(token=resolved_settings.tushare_token),
        fallback_name=fallback_name,
        fallback=fallback,
        message="使用 Tushare 主数据源。",
    )
