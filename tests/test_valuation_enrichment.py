"""Tests for Task 28 valuation PE/PB enrichment with mock data and temporary duckdb only."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

import core.jobs.export_selection_review as export_module
from core.data_sources.akshare_client import AKShareClient
from core.data_sources.valuation_enrichment import parse_akshare_snapshot, parse_eastmoney_quote
from core.jobs.diagnose_data_quality import diagnose_data_quality
from core.jobs.diagnose_factors import diagnose_factors
from core.jobs.export_watchlist import export_watchlist
from core.jobs.update_real_data import update_real_data
from core.review.decisions import import_review_decisions
from core.storage.duckdb_store import DuckDBStore


class Task28Settings(SimpleNamespace):
    """Settings-like object for valuation enrichment tests."""

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
        return []

    @property
    def akshare_symbols(self) -> list[str]:
        return [symbol.strip() for symbol in self.akshare_sample_symbols.split(",") if symbol.strip()]


class SnapshotAKShareModule:
    """Mock AKShare module with spot valuation snapshot."""

    def __init__(self, include_valuation: bool = True, partial: bool = False) -> None:
        self.include_valuation = include_valuation
        self.partial = partial

    def stock_info_a_code_name(self) -> pd.DataFrame:
        return pd.DataFrame({"code": ["000001", "600000"], "name": ["平安银行", "浦发银行"]})

    def stock_individual_info_em(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame({"item": ["行业", "上市时间"], "value": ["银行", "19910403" if symbol == "000001" else "19991110"]})

    def tool_trade_date_hist_sina(self) -> pd.DataFrame:
        return pd.DataFrame({"trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"]})

    def stock_zh_a_hist(self, symbol: str, period: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "日期": ["2024-01-02", "2024-01-03", "2024-01-04"],
                "开盘": [10.0, 10.1, 10.2],
                "收盘": [10.1, 10.2, 10.3],
                "最高": [10.3, 10.4, 10.5],
                "最低": [9.9, 10.0, 10.1],
                "成交量": [1000, 1100, 1200],
                "成交额": [150_000_000, 160_000_000, 170_000_000],
                "涨跌幅": [1.0, 1.1, 1.2],
                "涨跌额": [0.1, 0.1, 0.1],
                "换手率": [1.1, 1.2, 1.3],
            }
        )

    def __getattribute__(self, name: str) -> Any:
        if name == "stock_a_lg_indicator":
            raise AttributeError(name)
        return super().__getattribute__(name)

    def stock_zh_a_spot_em(self) -> pd.DataFrame:
        if not self.include_valuation:
            return pd.DataFrame()
        rows = [
            {"代码": "000001", "市盈率-动态": 6.8, "市净率": 0.68, "总市值": 1000.0, "流通市值": 900.0, "量比": 1.2},
            {"代码": "600000", "市盈率-动态": None if self.partial else 7.8, "市净率": None if self.partial else 0.78, "总市值": 1100.0, "流通市值": 990.0, "量比": 1.1},
        ]
        return pd.DataFrame(rows)


class NoValuationAKShareModule(SnapshotAKShareModule):
    """Mock AKShare module without valuation snapshot functions."""

    def __getattribute__(self, name: str) -> Any:
        if name in {"stock_a_lg_indicator", "stock_zh_a_spot_em", "stock_zh_a_spot"}:
            raise AttributeError(name)
        return super().__getattribute__(name)


def empty_curl(*args: Any, **kwargs: Any) -> SimpleNamespace:
    """Return an empty Eastmoney response without network."""
    return SimpleNamespace(returncode=0, stdout=json.dumps({"data": {"diff": []}}), stderr="")


def eastmoney_curl(*args: Any, **kwargs: Any) -> SimpleNamespace:
    """Return a mock Eastmoney quote response without network."""
    payload = {
        "data": {
            "diff": [
                {"f12": "000001", "f9": 6.9, "f23": 0.69, "f20": 1001.0, "f21": 901.0, "f10": 1.3},
                {"f12": "600000", "f9": 7.9, "f23": 0.79, "f20": 1101.0, "f21": 991.0, "f10": 1.2},
            ]
        }
    }
    return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")


def test_parse_akshare_snapshot_maps_pe_pb_market_cap() -> None:
    """AKShare Chinese valuation columns should map to internal fields."""
    parsed = parse_akshare_snapshot(
        pd.DataFrame({"代码": ["000001"], "市盈率-动态": [6.8], "市净率": [0.68], "总市值": [1000.0], "流通市值": [900.0]})
    )

    assert parsed.loc[0, "ts_code"] == "000001.SZ"
    assert parsed.loc[0, "pe"] == 6.8
    assert parsed.loc[0, "pb"] == 0.68
    assert parsed.loc[0, "total_mv"] == 1000.0
    assert parsed.loc[0, "circ_mv"] == 900.0


def test_parse_eastmoney_quote_maps_pe_pb() -> None:
    """Eastmoney quote rows should map PE/PB and market caps."""
    parsed = parse_eastmoney_quote([{"f12": "600000", "f9": 7.9, "f23": 0.79, "f20": 1101.0, "f21": 991.0}])

    assert parsed.loc[0, "ts_code"] == "600000.SH"
    assert parsed.loc[0, "pe"] == 7.9
    assert parsed.loc[0, "pb"] == 0.79


def test_valuation_snapshot_writes_latest_daily_basic_only(tmp_path: Path) -> None:
    """Valuation snapshot should fill only each stock's latest trade_date row."""
    store = DuckDBStore(tmp_path / "valuation.duckdb")
    client = AKShareClient(akshare_module=SnapshotAKShareModule(), curl_runner=empty_curl)

    update_real_data(settings=Task28Settings(duckdb_path=store.db_path), store=store, client=client)
    daily_basic = store.read_table("daily_basic")
    latest = daily_basic[daily_basic["trade_date"] == "20240104"].copy()
    older = daily_basic[daily_basic["trade_date"] < "20240104"].copy()

    assert latest["pe"].notna().all()
    assert latest["pb"].notna().all()
    assert older["pe"].isna().all()
    assert older["pb"].isna().all()


def test_empty_new_valuation_does_not_overwrite_existing_values(tmp_path: Path) -> None:
    """New empty valuation fields should not clear existing valid PE/PB."""
    store = DuckDBStore(tmp_path / "preserve.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "daily_basic",
        pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20240104"],
                "turnover_rate": [1.0],
                "volume_ratio": [None],
                "pe": [9.9],
                "pb": [0.99],
                "ps": [None],
                "total_mv": [999.0],
                "circ_mv": [888.0],
            }
        ),
    )
    client = AKShareClient(akshare_module=SnapshotAKShareModule(include_valuation=False), curl_runner=empty_curl)

    update_real_data(settings=Task28Settings(duckdb_path=store.db_path), store=store, client=client)
    row = store.read_table("daily_basic")
    latest = row[(row["ts_code"] == "000001.SZ") & (row["trade_date"] == "20240104")].iloc[0]

    assert latest["pe"] == 9.9
    assert latest["pb"] == 0.99


def test_partial_valuation_missing_does_not_block_other_symbols(tmp_path: Path) -> None:
    """One symbol missing valuation should not block another symbol's PE/PB."""
    store = DuckDBStore(tmp_path / "partial.duckdb")
    client = AKShareClient(akshare_module=SnapshotAKShareModule(partial=True), curl_runner=empty_curl)

    result = update_real_data(settings=Task28Settings(duckdb_path=store.db_path), store=store, client=client)
    daily_basic = store.read_table("daily_basic")
    latest = daily_basic[daily_basic["trade_date"] == "20240104"]

    assert result["status"] == "success"
    assert latest[latest["ts_code"] == "000001.SZ"]["pe"].notna().all()
    assert latest[latest["ts_code"] == "600000.SH"]["pe"].isna().all()


def test_missing_akshare_valuation_interface_gracefully_skips(tmp_path: Path) -> None:
    """Missing AKShare and empty curl valuation should be a graceful skip."""
    store = DuckDBStore(tmp_path / "missing.duckdb")
    client = AKShareClient(akshare_module=NoValuationAKShareModule(), curl_runner=empty_curl)

    result = update_real_data(settings=Task28Settings(duckdb_path=store.db_path), store=store, client=client)

    assert result["status"] == "success"
    assert result["enrichment_summary"]["valuation_status"] == "skipped"
    assert any("valuation" in item["failed_stage"] for item in result["enrichment_warnings"])


def test_eastmoney_curl_fallback_writes_pe_pb(tmp_path: Path) -> None:
    """Eastmoney quote curl fallback should fill PE/PB when AKShare snapshot is unavailable."""
    store = DuckDBStore(tmp_path / "eastmoney.duckdb")
    client = AKShareClient(akshare_module=NoValuationAKShareModule(), curl_runner=eastmoney_curl)

    update_real_data(settings=Task28Settings(duckdb_path=store.db_path), store=store, client=client)
    latest = store.read_table("daily_basic")
    latest = latest[latest["trade_date"] == "20240104"]

    assert latest["pe"].notna().all()
    assert latest["pb"].notna().all()
    assert latest[latest["ts_code"] == "600000.SH"]["pb"].iloc[0] == 0.79


def test_diagnose_data_quality_rates_improve_after_valuation(tmp_path: Path) -> None:
    """diagnose_data_quality should show improved PE/PB completeness."""
    store = DuckDBStore(tmp_path / "quality.duckdb")
    client = AKShareClient(akshare_module=SnapshotAKShareModule(), curl_runner=empty_curl)

    update_real_data(settings=Task28Settings(duckdb_path=store.db_path), store=store, client=client)
    result = diagnose_data_quality(settings=Task28Settings(duckdb_path=store.db_path), store=store)

    assert result["daily_basic_completeness"]["pe"] > 0.0
    assert result["daily_basic_completeness"]["pb"] > 0.0
    assert result["valuation_updated_count"] == 2


def test_diagnose_factors_fundamental_score_recovers_with_pe(tmp_path: Path) -> None:
    """fundamental_score should be calculable when PE exists on latest rows."""
    store = DuckDBStore(tmp_path / "factors.duckdb")
    _seed_factor_ready_store(store)

    result = diagnose_factors(settings=Task28Settings(duckdb_path=store.db_path), store=store, use_sample=False)

    assert result["factor_quality"]["pe_score"]["non_null_rate"] > 0.0
    assert result["factor_quality"]["fundamental_score"]["non_null_rate"] > 0.0
    assert not any("pe/pb 均缺失" in note for note in result["data_quality_notes"])


def test_selection_review_and_watchlist_reports_include_pe_pb(tmp_path: Path, monkeypatch: Any) -> None:
    """Reports should show PE/PB and avoid false missing valuation prompts."""
    store = DuckDBStore(tmp_path / "reports.duckdb")
    _seed_report_store(store)
    factor_scores = store.read_table("factor_scores")
    monkeypatch.setattr(
        export_module,
        "run_daily_selection",
        lambda settings, store: {
            "is_real_data": True,
            "fallback_to_sample": False,
            "latest_price_date": "20240104",
            "stock_pool_count": 1,
            "scored_stock_count": 1,
            "candidate_count": 1,
        },
    )
    monkeypatch.setattr(export_module, "diagnose_factors", lambda settings, store: {"factor_scores_df": factor_scores, "data_quality_notes": []})

    review = export_module.export_selection_review(
        top_n=1,
        output_dir=tmp_path / "reports",
        report_format="all",
        quiet=True,
        settings=Task28Settings(duckdb_path=store.db_path),
        store=store,
    )
    watchlist = export_watchlist(
        output_dir=tmp_path / "reports",
        report_format="all",
        quiet=True,
        settings=Task28Settings(duckdb_path=store.db_path),
        store=store,
    )

    review_payload = json.loads(Path(review["generated_files"]["json"]).read_text(encoding="utf-8"))
    watch_payload = json.loads(Path(watchlist["generated_files"]["json"]).read_text(encoding="utf-8"))

    assert review_payload["candidates"][0]["pe"] == 6.8
    assert review_payload["candidates"][0]["pb"] == 0.68
    assert "pe/pb 缺失" not in review_payload["candidates"][0]["data_quality_note"]
    assert watch_payload["watchlist"][0]["pe"] == 6.8
    assert watch_payload["watchlist"][0]["pb"] == 0.68
    assert "pe 缺失" not in watch_payload["watchlist"][0]["data_quality_note"]


def _seed_factor_ready_store(store: DuckDBStore) -> None:
    store.initialize()
    dates = [f"202401{index + 1:02d}" for index in range(65)]
    symbols = [("000001.SZ", "平安银行"), ("600000.SH", "浦发银行")]
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            [
                {"ts_code": ts_code, "symbol": ts_code[:6], "name": name, "area": "", "industry": "银行", "market": "深交所", "list_date": "19910403", "delist_date": None, "is_hs": None}
                for ts_code, name in symbols
            ]
        ),
    )
    prices = []
    basics = []
    for day_index, trade_date in enumerate(dates):
        for symbol_index, (ts_code, _) in enumerate(symbols):
            close = 10 + day_index * 0.1 + symbol_index
            prices.append({"ts_code": ts_code, "trade_date": trade_date, "open": close, "high": close + 0.2, "low": close - 0.2, "close": close, "pre_close": close - 0.1, "change": 0.1, "pct_chg": 1.0, "vol": 1000.0, "amount": 200_000_000.0})
            basics.append({"ts_code": ts_code, "trade_date": trade_date, "turnover_rate": 1.0, "volume_ratio": None, "pe": 6.8 + symbol_index, "pb": 0.68 + symbol_index * 0.1, "ps": None, "total_mv": 1000.0, "circ_mv": 900.0})
    store.upsert_dataframe("daily_price", pd.DataFrame(prices))
    store.upsert_dataframe("daily_basic", pd.DataFrame(basics))
    store.upsert_dataframe("adj_factor", pd.DataFrame([{"ts_code": ts_code, "trade_date": dates[0], "adj_factor": 1.0} for ts_code, _ in symbols]))


def _seed_report_store(store: DuckDBStore) -> None:
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame([{"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "area": "深圳", "industry": "银行", "market": "深交所", "list_date": "19910403", "delist_date": None, "is_hs": None}]),
    )
    store.upsert_dataframe("daily_price", pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20240104", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "pre_close": 10.0, "change": 0.2, "pct_chg": 2.0, "vol": 1000.0, "amount": 150_000_000.0}]))
    store.upsert_dataframe("daily_basic", pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20240104", "turnover_rate": 1.0, "volume_ratio": 1.2, "pe": 6.8, "pb": 0.68, "ps": None, "total_mv": 1000.0, "circ_mv": 900.0}]))
    store.upsert_dataframe("factor_scores", pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20240104", "trend_score": 80.0, "momentum_score": 80.0, "liquidity_score": 80.0, "volatility_score": 80.0, "fundamental_score": 70.0, "total_score": 88.0}]))
    import_review_decisions(
        pd.DataFrame({"ts_code": ["000001.SZ"], "name": ["平安银行"], "selection_date": ["20240104"], "decision": ["watch"], "reason": ["观察理由"], "notes": [""], "reviewer": ["me"]}),
        store=store,
    )
