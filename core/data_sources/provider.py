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
                request_timeout_seconds=_request_timeout_seconds(resolved_settings),
                symbol_timeout_seconds=getattr(resolved_settings, "symbol_update_timeout_seconds", 45),
                enable_basic_enrichment=getattr(resolved_settings, "enable_stock_basic_enrichment", False),
                enable_valuation_enrichment=_akshare_valuation_enrichment_enabled(resolved_settings),
            ),
            message="使用 AKShare 数据源。",
        )

    fallback = None
    fallback_name = None
    if getattr(resolved_settings, "enable_akshare_fallback", False):
        fallback = fallback_client or AKShareClient(
            adjust=resolved_settings.akshare_adjust,
            request_timeout_seconds=_request_timeout_seconds(resolved_settings),
            symbol_timeout_seconds=getattr(resolved_settings, "symbol_update_timeout_seconds", 45),
            enable_basic_enrichment=getattr(resolved_settings, "enable_stock_basic_enrichment", False),
            enable_valuation_enrichment=_akshare_valuation_enrichment_enabled(resolved_settings),
        )
        fallback_name = "akshare"

    return DataProviderSelection(
        provider_name="tushare",
        primary=primary_client or TushareClient(token=resolved_settings.tushare_token),
        fallback_name=fallback_name,
        fallback=fallback,
        message="使用 Tushare 主数据源。",
    )


def _akshare_valuation_enrichment_enabled(settings: Settings) -> bool:
    """Return whether AKShare may run optional valuation network enrichment."""
    if not getattr(settings, "enable_real_valuation_enrichment", True):
        return False
    sample_symbols = [
        symbol.strip()
        for symbol in getattr(settings, "akshare_sample_symbols", "").split(",")
        if symbol.strip()
    ]
    full_mode = not sample_symbols and str(getattr(settings, "real_universe_preset", "")).lower() == "full"
    if full_mode:
        return bool(getattr(settings, "full_enable_valuation_enrichment", False))
    return bool(getattr(settings, "enable_valuation_enrichment", False))


def _request_timeout_seconds(settings: Settings) -> int:
    """Return the preferred per-request timeout, keeping older config compatible."""
    explicit = int(getattr(settings, "data_source_request_timeout_seconds", 0) or 0)
    if explicit > 0:
        return explicit
    return int(getattr(settings, "real_request_timeout_seconds", 30) or 30)
