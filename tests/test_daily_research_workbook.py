"""Tests for Task 53 daily research workbook export."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openpyxl import load_workbook
import pandas as pd

from core.jobs.export_daily_research_workbook import (
    SHEET_NAMES,
    export_daily_research_workbook,
    _resolve_output_path,
)
from core.storage.duckdb_store import DuckDBStore


def test_export_daily_research_workbook_writes_required_sheets(tmp_path: Path) -> None:
    """Workbook export should include all required sheets and key rows."""
    store = _seed_store(tmp_path)
    output = tmp_path / "daily_research.xlsx"

    result = export_daily_research_workbook(
        output_path=output,
        settings=_settings(store),
        store=store,
    )

    workbook = load_workbook(output)
    assert workbook.sheetnames == SHEET_NAMES
    assert result.strategy_rows == 2
    assert result.entry_zone_rows == 2
    assert result.watchlist_rows == 1
    assert result.external_position_rows == 1


def test_candidate_sheet_uses_display_order_and_candidate_rank(tmp_path: Path) -> None:
    """Current display order should be continuous while preserving original candidate rank."""
    store = _seed_store(tmp_path)
    output = tmp_path / "daily_research.xlsx"

    export_daily_research_workbook(output_path=output, settings=_settings(store), store=store)

    sheet = load_workbook(output)["01_今日候选"]
    headers = [cell.value for cell in sheet[1]]
    display_idx = headers.index("display_order") + 1
    rank_idx = headers.index("candidate_rank") + 1
    code_idx = headers.index("ts_code") + 1

    assert [sheet.cell(row=row, column=display_idx).value for row in (2, 3)] == [1, 2]
    assert [sheet.cell(row=row, column=rank_idx).value for row in (2, 3)] == [1, 2]
    assert [sheet.cell(row=row, column=code_idx).value for row in (2, 3)] == ["000001.SZ", "000002.SZ"]


def test_workbook_export_is_read_only_for_duckdb(tmp_path: Path) -> None:
    """Export should not write or recompute local strategy rows."""
    store = _seed_store(tmp_path)
    before = _table_counts(store)

    export_daily_research_workbook(
        output_path=tmp_path / "daily_research.xlsx",
        settings=_settings(store),
        store=store,
    )

    assert _table_counts(store) == before


def test_workbook_filters_sensitive_settings(tmp_path: Path) -> None:
    """Settings sheet must not expose token/key/password/secret values."""
    store = _seed_store(tmp_path)
    settings = SimpleNamespace(
        duckdb_path=store.db_path,
        data_provider="akshare",
        real_universe_preset="full",
        tushare_token="SECRET_TOKEN",
        api_key="SECRET_KEY",
        password="SECRET_PASSWORD",
    )
    output = tmp_path / "daily_research.xlsx"

    export_daily_research_workbook(output_path=output, settings=settings, store=store)

    values = [
        cell.value
        for row in load_workbook(output)["09_参数配置"].iter_rows()
        for cell in row
        if cell.value is not None
    ]
    joined = "\n".join(str(value) for value in values)
    assert "SECRET" not in joined
    assert "duckdb_path" in joined
    assert "real_universe_preset" in joined


def test_empty_database_still_exports_clear_workbook(tmp_path: Path) -> None:
    """Missing or empty local results should produce an Excel workbook with clear messages."""
    store = DuckDBStore(tmp_path / "empty.duckdb")
    output = tmp_path / "empty.xlsx"

    result = export_daily_research_workbook(
        output_path=output,
        settings=_settings(store),
        store=store,
    )

    sheet = load_workbook(output)["01_今日候选"]
    assert output.exists()
    assert result.strategy_rows == 1
    assert "暂无本地选股结果" in str(sheet["A2"].value)


def test_task53_verifier_uses_temp_output() -> None:
    """Task 53 verification should not write workbook output into reports/."""
    source = Path("scripts/verify_task.py").read_text(encoding="utf-8")

    assert "task53" in source
    assert "/tmp/a_stock_assistant_task53" in source
    assert "reports/daily_research" not in source


def test_default_workbook_filename_does_not_repeat_trade_date() -> None:
    """Default output should be daily_research_YYYYMMDD_HHMMSS.xlsx."""
    path = _resolve_output_path(None, "20260630")

    assert path.name.startswith("daily_research_20260630_")
    assert path.name.count("20260630") == 1
    assert path.suffix == ".xlsx"


def _seed_store(tmp_path: Path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "research.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "industry": "银行", "market": "主板", "exchange": "SZSE"},
                {"ts_code": "000002.SZ", "symbol": "000002", "name": "万科A", "industry": "地产", "market": "主板", "exchange": "SZSE"},
            ]
        ),
    )
    store.upsert_dataframe(
        "daily_price",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20260630", "open": 10, "high": 11, "low": 9, "close": 10.5, "pre_close": 10, "change": 0.5, "pct_chg": 5, "vol": 1, "amount": 1},
                {"ts_code": "000002.SZ", "trade_date": "20260630", "open": 20, "high": 21, "low": 19, "close": 20.5, "pre_close": 20, "change": 0.5, "pct_chg": 2.5, "vol": 1, "amount": 1},
            ]
        ),
    )
    store.upsert_dataframe(
        "factor_scores",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20260630", "trend_score": 90, "momentum_score": 80, "liquidity_score": 70, "volatility_score": 60, "fundamental_score": 50, "total_score": 78},
                {"ts_code": "000002.SZ", "trade_date": "20260630", "trend_score": 70, "momentum_score": 60, "liquidity_score": 50, "volatility_score": 40, "fundamental_score": 30, "total_score": 58},
            ]
        ),
    )
    store.upsert_dataframe(
        "strategy_result",
        pd.DataFrame(
            [
                {"trade_date": "20260630", "rank": 1, "ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "close": 10.5, "pe": 6.1, "pb": 0.8, "total_score": 78.0, "trend_score": 90.0, "momentum_score": 80.0, "liquidity_score": 70.0, "fundamental_score": 50.0, "volatility_score": 60.0},
                {"trade_date": "20260630", "rank": 2, "ts_code": "000002.SZ", "name": "万科A", "industry": "地产", "close": 20.5, "pe": 7.2, "pb": 0.9, "total_score": 58.0, "trend_score": 70.0, "momentum_score": 60.0, "liquidity_score": 50.0, "fundamental_score": 30.0, "volatility_score": 40.0},
            ]
        ),
    )
    store.upsert_dataframe(
        "entry_zone_snapshots",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "name": "平安银行", "trade_date": "20260630", "close": 10.5, "ema13": 10.0, "ema22": 9.8, "ema60": 9.0, "entry_low": 9.8, "entry_high": 10.2, "entry_mid": 10.0, "stop_loss": 9.2, "target_price": 11.6, "reward_risk_ratio": 2.0, "entry_zone_status": "near_zone", "entry_zone_status_cn": "接近买入区间", "chase_risk": "medium", "chase_risk_cn": "中", "source": "selection"},
                {"ts_code": "000002.SZ", "name": "万科A", "trade_date": "20260630", "close": 20.5, "ema13": 19.0, "ema22": 18.8, "ema60": 18.0, "entry_low": 18.8, "entry_high": 19.5, "entry_mid": 19.15, "stop_loss": 17.8, "target_price": 21.85, "reward_risk_ratio": 2.0, "entry_zone_status": "above_zone", "entry_zone_status_cn": "高于买入区间", "chase_risk": "high", "chase_risk_cn": "高", "source": "selection"},
            ]
        ),
    )
    store.upsert_dataframe(
        "watchlist_daily_snapshots",
        pd.DataFrame(
            [
                {
                    "snapshot_id": "watch-000001-20260630",
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "trade_date": "20260630",
                    "current_close": 10.5,
                    "today_rank": 1,
                    "total_score": 78.0,
                    "watch_status": "active_watch",
                    "watch_status_label": "正常观察",
                    "elder_score": 62.0,
                    "action_hint": "趋势尚可，等待回调",
                    "elder_reason": "节奏复核",
                }
            ]
        ),
    )
    store.upsert_dataframe(
        "external_position_snapshots",
        pd.DataFrame(
            [
                {
                    "id": "external-000001-20260630",
                    "platform": "模拟",
                    "account_name": "默认",
                    "snapshot_date": "20260630",
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "quantity": 100,
                    "cost_price": 10.0,
                    "current_price": 10.5,
                    "market_value": 1050.0,
                    "pnl": 50.0,
                    "pnl_pct": 0.05,
                    "risk_status": "normal",
                    "risk_status_cn": "正常",
                }
            ]
        ),
    )
    return store


def _settings(store: DuckDBStore) -> SimpleNamespace:
    return SimpleNamespace(
        duckdb_path=store.db_path,
        data_provider="akshare",
        real_universe_preset="full",
        akshare_sample_symbols="",
    )


def _table_counts(store: DuckDBStore) -> dict[str, int]:
    tables = [
        "strategy_result",
        "factor_scores",
        "entry_zone_snapshots",
        "watchlist_daily_snapshots",
        "external_position_snapshots",
    ]
    return {table: len(store.read_table(table)) for table in tables}
