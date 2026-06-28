"""Tests for .env file editing helpers used by the local console."""

from __future__ import annotations

from pathlib import Path

from core.config.env_file import (
    clean_stock_symbols,
    masked_env_values,
    read_env_file,
    update_env_file,
)


def test_read_env_file_reads_values_and_ignores_comments(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# comment\nDATA_PROVIDER=akshare\nREAL_DATA_END_DATE=\n", encoding="utf-8")

    values = read_env_file(env_path)

    assert values["DATA_PROVIDER"] == "akshare"
    assert values["REAL_DATA_END_DATE"] == ""
    assert "# comment" not in values


def test_update_env_file_preserves_unknown_keys_and_comments(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# keep\nUNKNOWN_KEY=keep\nDATA_PROVIDER=sample\n", encoding="utf-8")

    update_env_file(env_path, {"DATA_PROVIDER": "akshare", "REAL_DATA_END_DATE": ""})
    text = env_path.read_text(encoding="utf-8")

    assert "# keep" in text
    assert "UNKNOWN_KEY=keep" in text
    assert "DATA_PROVIDER=akshare" in text
    assert "REAL_DATA_END_DATE=" in text


def test_update_env_file_formats_bool_and_cleans_symbols(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    update_env_file(
        env_path,
        {
            "ENABLE_REAL_BASIC_ENRICHMENT": True,
            "ENABLE_REAL_VALUATION_ENRICHMENT": "no",
            "AKSHARE_SAMPLE_SYMBOLS": "000001, 600000.SH,000001,002475.SZ",
        },
    )
    values = read_env_file(env_path)

    assert values["ENABLE_REAL_BASIC_ENRICHMENT"] == "true"
    assert values["ENABLE_REAL_VALUATION_ENRICHMENT"] == "false"
    assert values["AKSHARE_SAMPLE_SYMBOLS"] == "000001,600000,002475"


def test_masked_env_values_hides_tushare_token() -> None:
    values = masked_env_values({"TUSHARE_TOKEN": "abcd1234efgh5678", "DATA_PROVIDER": "akshare"})

    assert values["TUSHARE_TOKEN"] == "abcd****5678"
    assert values["DATA_PROVIDER"] == "akshare"


def test_clean_stock_symbols_deduplicates_and_removes_suffix() -> None:
    assert clean_stock_symbols("000001, 600000.SH, 002475.SZ, bad, 000001") == [
        "000001",
        "600000",
        "002475",
    ]
