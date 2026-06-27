"""Tests for real basic/fundamental enrichment with mock data and temporary duckdb."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from core.data_sources.akshare_client import AKShareClient
from core.jobs.diagnose_data_quality import diagnose_data_quality
from core.jobs.diagnose_factors import diagnose_factors
from core.jobs.update_real_data import update_real_data
from core.reporting.selection_review_report import build_selection_review_report, candidates_to_dataframe
from core.reporting.watchlist_report import build_watchlist_report, watchlist_to_dataframe
from core.review.decisions import build_watchlist_dataframe, import_review_decisions
from core.storage.duckdb_store import DuckDBStore
from web.streamlit_app import summarize_basic_data_quality


class Task27Settings(SimpleNamespace):
    """Settings-like object for no-network tests."""

    data_provider: str = "akshare"
    tushare_token: str = ""
    enable_akshare_fallback: bool = False
    real_data_start_date: str = "20240101"
    real_data_end_date: str = "20240105"
    real_data_sample_symbols: str = ""
    akshare_sample_symbols: str = "000001,600000"
    real_universe_preset: str = "mini"
    real_batch_size: int = 2
    real_batch_sleep_seconds: float = 0.0
    real_max_retries: int = 1
    real_request_timeout_seconds: int = 30
    duckdb_path: Path = Path("unused.duckdb")
    default_top_n: int = 30
    enable_real_basic_enrichment: bool = True
    enable_real_valuation_enrichment: bool = True

    @property
    def sample_symbols(self) -> list[str]:
        """Return no Tushare symbols."""
        return []

    @property
    def akshare_symbols(self) -> list[str]:
        """Return explicit AKShare sample symbols."""
        return [symbol.strip() for symbol in self.akshare_sample_symbols.split(",") if symbol.strip()]


class MockAKShareModule:
    """Mock AKShare module; no real Tushare, AKShare, or Eastmoney access."""

    def __init__(self, fail_basic: set[str] | None = None, fail_valuation: set[str] | None = None) -> None:
        self.fail_basic = fail_basic or set()
        self.fail_valuation = fail_valuation or set()

    def stock_info_a_code_name(self) -> pd.DataFrame:
        """Return minimal stock names."""
        return pd.DataFrame({"code": ["000001", "600000"], "name": ["平安银行", "浦发银行"]})

    def stock_individual_info_em(self, symbol: str) -> pd.DataFrame:
        """Return basic information for one stock or raise a mock error."""
        if symbol in self.fail_basic:
            raise RuntimeError("mock basic failure")
        industry = "银行" if symbol == "000001" else "股份制银行"
        list_date = "19910403" if symbol == "000001" else "19991110"
        return pd.DataFrame(
            {
                "item": ["行业", "上市时间", "地区"],
                "value": [industry, list_date, "深圳" if symbol == "000001" else "上海"],
            }
        )

    def tool_trade_date_hist_sina(self) -> pd.DataFrame:
        """Return a small trade calendar."""
        return pd.DataFrame({"trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"]})

    def stock_zh_a_hist(
        self,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> pd.DataFrame:
        """Return Chinese-column daily bars with turnover_rate."""
        return pd.DataFrame(
            {
                "日期": ["2024-01-02", "2024-01-03", "2024-01-04"],
                "开盘": [10.0, 10.2, 10.4],
                "收盘": [10.1, 10.3, 10.5],
                "最高": [10.5, 10.6, 10.8],
                "最低": [9.9, 10.1, 10.2],
                "成交量": [1000, 1100, 1200],
                "成交额": [150_000_000, 160_000_000, 170_000_000],
                "涨跌幅": [1.0, 1.2, 1.4],
                "涨跌额": [0.1, 0.2, 0.2],
                "换手率": [1.1, 1.2, 1.3],
            }
        )

    def stock_a_lg_indicator(self, symbol: str) -> pd.DataFrame:
        """Return valuation rows for one stock or raise a mock error."""
        if symbol in self.fail_valuation:
            raise RuntimeError("mock valuation failure")
        pe = 6.5 if symbol == "000001" else 7.5
        pb = 0.65 if symbol == "000001" else 0.75
        return pd.DataFrame(
            {
                "date": ["20240102", "20240103", "20240104"],
                "pe": [pe, pe + 0.1, pe + 0.2],
                "pb": [pb, pb + 0.01, pb + 0.02],
                "total_mv": [1000.0, 1001.0, 1002.0],
                "circ_mv": [900.0, 901.0, 902.0],
            }
        )


def test_stock_basic_enrichment_writes_industry_and_list_date(tmp_path: Path) -> None:
    """AKShare stock_basic enrichment should write industry/list_date to temporary duckdb."""
    store = DuckDBStore(tmp_path / "temporary.duckdb")
    client = AKShareClient(akshare_module=MockAKShareModule())

    update_real_data(settings=Task27Settings(duckdb_path=store.db_path), store=store, client=client)

    stock_basic = store.read_table("stock_basic")
    row = stock_basic[stock_basic["ts_code"] == "000001.SZ"].iloc[0]
    assert row["industry"] == "银行"
    assert row["list_date"] == "19910403"


def test_daily_basic_enrichment_writes_pe_pb(tmp_path: Path) -> None:
    """AKShare valuation enrichment should write pe/pb to daily_basic."""
    store = DuckDBStore(tmp_path / "valuation.duckdb")
    client = AKShareClient(akshare_module=MockAKShareModule())

    update_real_data(settings=Task27Settings(duckdb_path=store.db_path), store=store, client=client)

    daily_basic = store.read_table("daily_basic")
    assert daily_basic["pe"].notna().any()
    assert daily_basic["pb"].notna().any()


def test_enrichment_single_symbol_failure_does_not_block_others(tmp_path: Path) -> None:
    """One enrichment failure should not prevent other symbols from being written."""
    store = DuckDBStore(tmp_path / "partial.duckdb")
    client = AKShareClient(akshare_module=MockAKShareModule(fail_basic={"600000"}, fail_valuation={"600000"}))

    result = update_real_data(settings=Task27Settings(duckdb_path=store.db_path), store=store, client=client)

    assert result["success_symbols"] == 2
    assert "stock_basic_enrichment" in {item["failed_stage"] for item in result["failure_records"]}
    daily_basic = store.read_table("daily_basic")
    assert daily_basic[daily_basic["ts_code"] == "000001.SZ"]["pe"].notna().any()
    assert daily_basic[daily_basic["ts_code"] == "600000.SH"]["pe"].isna().all()


def test_enrichment_switches_keep_simplified_logic(tmp_path: Path) -> None:
    """Disabled enrichment switches should preserve current simplified AKShare logic."""
    store = DuckDBStore(tmp_path / "disabled.duckdb")
    client = AKShareClient(
        akshare_module=MockAKShareModule(),
        enable_basic_enrichment=False,
        enable_valuation_enrichment=False,
    )
    settings = Task27Settings(
        duckdb_path=store.db_path,
        enable_real_basic_enrichment=False,
        enable_real_valuation_enrichment=False,
    )

    update_real_data(settings=settings, store=store, client=client)

    stock_basic = store.read_table("stock_basic")
    daily_basic = store.read_table("daily_basic")
    assert stock_basic["industry"].isna().all()
    assert daily_basic["pe"].isna().all()
    assert daily_basic["pb"].isna().all()


def test_diagnose_data_quality_outputs_completeness(tmp_path: Path) -> None:
    """diagnose_data_quality should report field completeness for temporary duckdb."""
    store = DuckDBStore(tmp_path / "quality.duckdb")
    update_real_data(settings=Task27Settings(duckdb_path=store.db_path), store=store, client=AKShareClient(akshare_module=MockAKShareModule()))

    result = diagnose_data_quality(settings=Task27Settings(duckdb_path=store.db_path), store=store)

    assert result["stock_basic_completeness"]["industry"] == 1.0
    assert result["daily_basic_completeness"]["pe"] == 1.0
    assert result["symbol_quality"][0]["data_quality_note"] == "基础信息和估值字段可用"


def test_diagnose_factors_explains_missing_fundamental_score(tmp_path: Path) -> None:
    """diagnose_factors should explain fundamental_score gaps when pe/pb are missing."""
    store = DuckDBStore(tmp_path / "factors.duckdb")
    store.initialize()
    trade_dates = [f"202401{index + 1:02d}" for index in range(65)]
    stock_basic = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "symbol": "000001",
                "name": "平安银行",
                "area": "深圳",
                "industry": "银行",
                "market": "深交所",
                "list_date": "19910403",
                "delist_date": None,
                "is_hs": None,
            }
        ]
    )
    daily_price = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * len(trade_dates),
            "trade_date": trade_dates,
            "open": [10.0] * len(trade_dates),
            "high": [10.5] * len(trade_dates),
            "low": [9.5] * len(trade_dates),
            "close": [10.0 + index * 0.01 for index in range(len(trade_dates))],
            "pre_close": [None] * len(trade_dates),
            "change": [0.1] * len(trade_dates),
            "pct_chg": [1.0] * len(trade_dates),
            "vol": [1000] * len(trade_dates),
            "amount": [150_000_000] * len(trade_dates),
        }
    )
    daily_basic = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * len(trade_dates),
            "trade_date": trade_dates,
            "turnover_rate": [1.0] * len(trade_dates),
            "volume_ratio": [None] * len(trade_dates),
            "pe": [None] * len(trade_dates),
            "pb": [None] * len(trade_dates),
            "ps": [None] * len(trade_dates),
            "total_mv": [None] * len(trade_dates),
            "circ_mv": [None] * len(trade_dates),
        }
    )
    store.upsert_dataframe("stock_basic", stock_basic)
    store.upsert_dataframe("daily_price", daily_price)
    store.upsert_dataframe("daily_basic", daily_basic)
    store.upsert_dataframe("adj_factor", pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240101"], "adj_factor": [1.0]}))

    result = diagnose_factors(settings=Task27Settings(duckdb_path=store.db_path), store=store, use_sample=False)

    assert any("pe/pb" in note or "fundamental_score" in note for note in result["data_quality_notes"])


def test_reports_include_industry_pe_pb_or_missing_notes() -> None:
    """selection_review and watchlist reports should include industry, pe, pb, or missing prompts."""
    selection = pd.DataFrame(
        {
            "trade_date": ["20240104"],
            "rank": [1],
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
            "industry": ["银行"],
            "list_date": ["19910403"],
            "total_score": [88.0],
            "trend_score": [80.0],
            "momentum_score": [80.0],
            "liquidity_score": [80.0],
            "volatility_score": [80.0],
            "fundamental_score": [80.0],
        }
    )
    daily_basic = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240104"], "turnover_rate": [1.0], "pe": [6.8], "pb": [0.68]})
    report = build_selection_review_report(
        metadata={"generated_at": "2026-06-27", "data_provider": "akshare", "duckdb_path": "temporary duckdb"},
        selection_summary={"is_real_data": True, "fallback_to_sample": False, "latest_price_date": "20240104", "stock_pool_count": 1, "scored_stock_count": 1, "candidate_count": 1},
        selection_df=selection,
        factor_df=selection,
        price_df=pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240104"], "close": [10.5]}),
        daily_basic_df=daily_basic,
        top_n=1,
    )
    df = candidates_to_dataframe(report["candidates"])
    assert df.loc[0, "industry"] == "银行"
    assert df.loc[0, "pe"] == 6.8
    assert df.loc[0, "pb"] == 0.68


def test_watchlist_report_contains_basic_and_valuation_fields(tmp_path: Path) -> None:
    """watchlist export should contain industry/pe/pb and data_quality_note."""
    store = DuckDBStore(tmp_path / "watchlist.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "平安银行",
                    "area": "深圳",
                    "industry": "银行",
                    "market": "深交所",
                    "list_date": "19910403",
                    "delist_date": None,
                    "is_hs": None,
                }
            ]
        ),
    )
    store.upsert_dataframe("daily_price", pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240104"], "open": [10.0], "high": [10.5], "low": [9.5], "close": [10.2], "pre_close": [None], "change": [0.1], "pct_chg": [1.0], "vol": [1000], "amount": [150_000_000]}))
    store.upsert_dataframe("daily_basic", pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240104"], "turnover_rate": [1.0], "volume_ratio": [None], "pe": [6.8], "pb": [0.68], "ps": [None], "total_mv": [1000.0], "circ_mv": [900.0]}))
    store.upsert_dataframe("factor_scores", pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240104"], "trend_score": [80.0], "momentum_score": [80.0], "liquidity_score": [80.0], "volatility_score": [80.0], "fundamental_score": [80.0], "total_score": [88.0]}))
    import_review_decisions(
        pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "name": ["平安银行"],
                "selection_date": ["20240104"],
                "decision": ["watch"],
                "reason": ["观察理由"],
                "notes": ["复核要点"],
                "reviewer": ["me"],
            }
        ),
        store=store,
    )

    watchlist_df = build_watchlist_dataframe(store)
    report = build_watchlist_report(metadata={"generated_at": "2026-06-27", "data_provider": "akshare"}, watchlist_df=watchlist_df)
    exported = watchlist_to_dataframe(report["watchlist"])

    assert exported.loc[0, "industry"] == "银行"
    assert exported.loc[0, "pe"] == 6.8
    assert exported.loc[0, "pb"] == 0.68
    assert exported.loc[0, "data_quality_note"] in ("", None) or "缺失" not in str(exported.loc[0, "data_quality_note"])


def test_streamlit_helper_summarizes_sample_and_real_data_status() -> None:
    """streamlit helper should expose field quality for sample smoke test and real data."""
    quality = summarize_basic_data_quality(
        pd.DataFrame({"name": ["平安银行"], "industry": ["银行"], "market": ["深交所"], "list_date": ["19910403"]}),
        pd.DataFrame({"turnover_rate": [1.0], "pe": [6.8], "pb": [0.68], "total_mv": [1000.0], "circ_mv": [900.0]}),
    )

    assert quality["stock_basic"]["industry"]["non_null_rate"] == 1.0
    assert quality["daily_basic"]["pe"]["non_null_rate"] == 1.0
