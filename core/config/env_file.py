"""Safe .env file reading and updating for the local console."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SUPPORTED_ENV_KEYS = [
    "DATA_PROVIDER",
    "AKSHARE_SAMPLE_SYMBOLS",
    "REAL_UNIVERSE_PRESET",
    "AKSHARE_ADJUST",
    "REAL_DATA_START_DATE",
    "REAL_DATA_END_DATE",
    "ENABLE_REAL_BASIC_ENRICHMENT",
    "ENABLE_REAL_VALUATION_ENRICHMENT",
    "REAL_BATCH_SIZE",
    "REAL_BATCH_SLEEP_SECONDS",
    "REAL_MAX_RETRIES",
    "REAL_REQUEST_TIMEOUT_SECONDS",
    "FULL_UPDATE_BATCH_SIZE",
    "FULL_UPDATE_LOOKBACK_DAYS",
    "FULL_UPDATE_MAX_RETRIES",
    "FULL_UPDATE_SLEEP_SECONDS",
    "FULL_UPDATE_RESUME",
    "ENABLE_STOCK_BASIC_ENRICHMENT",
    "FULL_ENABLE_STOCK_BASIC_ENRICHMENT",
    "MIN_LISTING_DAYS",
    "MIN_AVG_AMOUNT_20D",
    "MIN_MEDIAN_AMOUNT_20D",
    "MIN_LATEST_AMOUNT",
    "MIN_TRADED_DAYS_20D",
    "INCLUDE_BSE",
    "DATA_DIR",
    "DUCKDB_PATH",
    "TUSHARE_TOKEN",
]

BOOL_KEYS = {
    "ENABLE_REAL_BASIC_ENRICHMENT",
    "ENABLE_REAL_VALUATION_ENRICHMENT",
    "ENABLE_STOCK_BASIC_ENRICHMENT",
    "FULL_ENABLE_STOCK_BASIC_ENRICHMENT",
    "INCLUDE_BSE",
    "FULL_UPDATE_RESUME",
}
INT_KEYS = {
    "REAL_BATCH_SIZE",
    "REAL_MAX_RETRIES",
    "REAL_REQUEST_TIMEOUT_SECONDS",
    "FULL_UPDATE_BATCH_SIZE",
    "FULL_UPDATE_LOOKBACK_DAYS",
    "FULL_UPDATE_MAX_RETRIES",
    "MIN_LISTING_DAYS",
    "MIN_AVG_AMOUNT_20D",
    "MIN_MEDIAN_AMOUNT_20D",
    "MIN_LATEST_AMOUNT",
    "MIN_TRADED_DAYS_20D",
}
FLOAT_KEYS = {"REAL_BATCH_SLEEP_SECONDS", "FULL_UPDATE_SLEEP_SECONDS"}
DATA_PROVIDERS = {"sample", "tushare", "akshare"}
PRESETS = {"mini", "small", "medium", "full"}


def read_env_file(path: Path | str = ".env") -> dict[str, str]:
    """Read key/value pairs from a .env file without exposing comments as data."""
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def update_env_file(path: Path | str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update supported .env keys while preserving unknown keys and comments."""
    env_path = Path(path)
    normalized = {key: format_env_value(key, value) for key, value in updates.items()}
    validate_env_updates(normalized)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        parsed = _parse_env_line(line)
        if parsed is None:
            output.append(line)
            continue
        key, _old_value = parsed
        if key in normalized:
            output.append(f"{key}={normalized[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key in SUPPORTED_ENV_KEYS:
        if key in normalized and key not in seen:
            output.append(f"{key}={normalized[key]}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    return {"path": str(env_path), "updated_keys": sorted(normalized)}


def validate_env_updates(values: dict[str, str]) -> None:
    """Validate known .env values before saving."""
    unknown = [key for key in values if key not in SUPPORTED_ENV_KEYS]
    if unknown:
        raise ValueError(f"Unsupported .env keys: {', '.join(unknown)}")
    provider = values.get("DATA_PROVIDER")
    if provider and provider not in DATA_PROVIDERS:
        raise ValueError("DATA_PROVIDER must be sample, tushare, or akshare.")
    preset = values.get("REAL_UNIVERSE_PRESET")
    if preset and preset not in PRESETS:
        raise ValueError("REAL_UNIVERSE_PRESET must be mini, small, medium, or full.")
    for key in INT_KEYS & values.keys():
        if values[key] and int(values[key]) < 0:
            raise ValueError(f"{key} must be a non-negative integer.")
    for key in FLOAT_KEYS & values.keys():
        if values[key] and float(values[key]) < 0:
            raise ValueError(f"{key} must be a non-negative number.")


def format_env_value(key: str, value: Any) -> str:
    """Format a Python value for .env storage."""
    if value is None:
        return ""
    if key in BOOL_KEYS:
        if isinstance(value, str):
            return "true" if value.strip().lower() in {"1", "true", "yes", "on"} else "false"
        return "true" if bool(value) else "false"
    if key == "AKSHARE_SAMPLE_SYMBOLS":
        return ",".join(clean_stock_symbols(str(value)))
    return str(value).strip()


def clean_stock_symbols(value: str) -> list[str]:
    """Normalize comma-separated A-share symbols for AKShare input."""
    return parse_stock_symbols(value)["symbols"]


def parse_stock_symbols(value: str) -> dict[str, list[str]]:
    """Parse A-share symbols and return cleaned symbols plus invalid entries."""
    seen: set[str] = set()
    symbols: list[str] = []
    invalid: list[str] = []
    normalized_input = value.replace("，", ",").replace("\n", ",").replace("\r", ",")
    for raw in normalized_input.split(","):
        symbol = raw.strip().upper()
        if not symbol:
            continue
        symbol = symbol.replace(".SZ", "").replace(".SH", "")
        if len(symbol) == 6 and symbol.isdigit():
            if symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
        else:
            invalid.append(raw.strip())
    return {"symbols": symbols, "invalid": invalid}


def masked_env_values(values: dict[str, str]) -> dict[str, str]:
    """Return .env values with TUSHARE_TOKEN redacted."""
    result = dict(values)
    token = result.get("TUSHARE_TOKEN", "")
    result["TUSHARE_TOKEN"] = mask_secret(token)
    return result


def mask_secret(value: str | None) -> str:
    """Mask secret values for display."""
    if not value:
        return "未设置"
    if len(value) <= 8:
        return "已设置"
    return f"{value[:4]}****{value[-4:]}"


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, value.strip()
