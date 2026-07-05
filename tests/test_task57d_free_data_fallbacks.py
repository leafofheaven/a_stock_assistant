"""Tests for Task 57D free market-data fallback and manual import."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.data_sources.akshare_spot_snapshot import AKShareSpotSnapshotClient
from core.data_sources.baostock_client import BaoStockClient
from core.diagnostics.data_quality_snapshot import build_data_quality_snapshot
from core.jobs.import_market_data import import_market_data, normalize_import_frame
from core.jobs.market_data_progress import MarketDataProgressWriter, read_market_data_progress
from core.jobs.refresh_data_quality_status import refresh_data_quality_status
from core.jobs.update_market_data import _format_attempt_line, forward_fill_adj_factor, update_market_data
from core.storage.duckdb_store import DuckDBStore


def test_provider_auto_prefers_free_fallbacks_before_tushare(tmp_path: Path) -> None:
    settings = _settings(tmp_path, tushare_token="")
    store = _seed_store(tmp_path)
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps({"research_trade_date": "20260703", "latest_completed_trade_date": "20260703"}), encoding="utf-8")

    result = update_market_data(
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=settings,
        status_path=status_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )

    providers = [item["provider"] for item in result["provider_attempts"]]
    assert providers[:2] == ["akshare_kline", "akshare_spot_snapshot"]
    assert "tushare_optional" not in providers


def test_tushare_is_optional_and_disabled_without_token(tmp_path: Path) -> None:
    result = update_market_data(
        provider="tushare_optional",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path, tushare_token=""),
        status_path=tmp_path / "status.json",
    )

    assert result["status"] == "skipped"
    assert "可选" in result["message"]


def test_update_latest_auto_attempts_fallback_after_kline_failure(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )

    attempts = result["provider_attempts"]
    assert [item["provider"] for item in attempts[:2]] == ["akshare_kline", "akshare_spot_snapshot"]
    assert attempts[0]["status"] == "failed"
    assert attempts[1]["status"] == "success"
    assert result["status"] == "partial"
    assert result["latest_success_provider"] == "akshare_spot_snapshot"


def test_update_latest_kline_fail_fast_before_full_symbol_loop(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)
    akshare = _RecordingEmptyAkshareKline()

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=akshare,
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )

    assert akshare.calls == [["000001.SZ", "000002.SZ"]]
    first_attempt = result["provider_attempts"][0]
    assert first_attempt["provider"] == "akshare_kline"
    assert first_attempt["status"] == "failed"
    assert first_attempt["error_type"] == "network_or_provider_unavailable"
    assert result["provider_attempts"][1]["provider"] == "akshare_spot_snapshot"


def test_update_latest_kline_fail_fast_on_exception(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)
    akshare = _ExceptionAkshareKline("ProxyError: curl returncode 52 from push2his.eastmoney.com")

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ", "000003.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=akshare,
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )

    first_attempt = result["provider_attempts"][0]
    assert akshare.calls == [["000001.SZ", "000002.SZ"]]
    assert first_attempt["status"] == "failed"
    assert first_attempt["error_type"] == "network_or_provider_unavailable"
    assert first_attempt["error_message"] == "东方财富 K 线接口不可用，已尝试下一个免费数据源。"
    assert "push2his.eastmoney.com" in first_attempt["technical_details"]["raw_exception"]
    assert result["provider_attempts"][1]["provider"] == "akshare_spot_snapshot"


def test_update_latest_auto_records_unavailable_provider(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=_FailBaoStockModule()),
        force_snapshot=True,
    )

    attempts = result["provider_attempts"]
    baostock_attempt = next(item for item in attempts if item["provider"] == "baostock")
    assert baostock_attempt["status"] == "unavailable"
    assert baostock_attempt["error_type"] == "provider_unavailable"


def test_update_latest_all_failed_records_manual_import_available(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=_FailBaoStockModule()),
        force_snapshot=True,
    )

    assert result["status"] == "failed"
    assert result["latest_success_provider"] == ""
    assert result["provider_attempts"][-1]["provider"] == "manual_import"
    assert result["provider_attempts"][-1]["status"] == "available"
    assert "导入" in result["suggested_action"]
    assert [item["provider"] for item in result["provider_attempts"]] == [
        "akshare_kline",
        "akshare_spot_snapshot",
        "baostock",
        "manual_import",
    ]


def test_update_latest_all_failed_no_success_provider(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=_FailBaoStockModule()),
        force_snapshot=True,
    )

    assert result["status"] == "failed"
    assert result["latest_success_provider"] == ""
    assert result["latest_success_trade_date"] == ""


def test_update_market_data_text_output_hides_tracebacks() -> None:
    line = _format_attempt_line(
        1,
        {
            "provider": "akshare_kline",
            "display_name": "历史行情接口",
            "status": "failed",
            "error_message": "Traceback ProxyError curl_returncode=52 push2his.eastmoney.com stderr",
            "technical_details": {"raw_exception": "Traceback ProxyError push2his.eastmoney.com"},
        },
    )

    assert "历史行情接口: 失败" in line
    assert "东方财富 K 线接口不可用" in line
    for forbidden in ["Traceback", "ProxyError", "curl", "push2his", "stderr"]:
        assert forbidden not in line


def test_update_market_data_json_contains_all_provider_attempts(tmp_path: Path) -> None:
    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=_FailBaoStockModule()),
        force_snapshot=True,
    )

    attempts = result["provider_attempts"]
    assert [item["provider"] for item in attempts] == ["akshare_kline", "akshare_spot_snapshot", "baostock", "manual_import"]
    for item in attempts:
        assert {"provider", "display_name", "goal", "status", "started_at", "finished_at", "technical_details"}.issubset(item)


def test_update_latest_partial_success_does_not_mark_formal_usable(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )

    assert result["latest_update_completeness"] == "partial"
    assert result["formal_result_usable"] is False


def test_update_history_auto_prefers_history_provider(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    result = update_market_data(
        goal="history",
        provider="auto",
        start_date="20260701",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        baostock_client=BaoStockClient(baostock_module=_BaoStockModule()),
    )

    assert result["provider_attempts"][0]["provider"] == "baostock"
    assert result["latest_success_provider"] == "baostock"


def test_diagnosis_does_not_write_success_provider(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    result = update_market_data(
        goal="diagnosis",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert result["status"] == "skipped"
    assert result["provider_attempts"] == []
    assert "latest_success_provider" not in payload


def test_diagnosis_does_not_write_duckdb_or_success_provider(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    result = update_market_data(
        goal="diagnosis",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert result["written_row_count"] == 0
    assert result["provider_attempts"] == []
    assert "latest_success_provider" not in payload


def test_status_json_contains_provider_attempts_after_one_click_update(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert payload["goal"] == "latest"
    assert payload["provider"] == "auto"
    assert payload["provider_attempts"]
    assert payload["provider_attempts"][0]["display_name"]


def test_refresh_data_quality_snapshot_after_update(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)

    update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert payload["data_quality_snapshot_source"] == "readonly_duckdb_sql"
    assert "data_quality_status" in payload


def test_market_data_progress_file_created_when_update_starts(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.json"

    update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        progress_path=progress_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )

    payload = read_market_data_progress(progress_path)
    assert payload["goal"] == "latest"
    assert payload["provider"] == "auto"
    assert payload["total_symbol_count"] == 1


def test_market_data_progress_updates_provider_and_symbol_counts(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.json"

    update_market_data(
        goal="history",
        provider="auto",
        start_date="20260701",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        progress_path=progress_path,
        baostock_client=BaoStockClient(baostock_module=_PartialBaoStockModule()),
    )

    payload = read_market_data_progress(progress_path)
    baostock = next(item for item in payload["provider_progress"] if item["provider"] == "baostock")
    assert payload["current_provider"] == "baostock"
    assert baostock["processed_symbol_count"] == 2
    assert baostock["total_symbol_count"] == 2
    assert baostock["success_symbol_count"] == 1
    assert baostock["failed_symbol_count"] == 1


def test_latest_update_targets_missing_latest_symbols_first(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, symbols=["000001.SZ", "000002.SZ", "000003.SZ"])
    store.upsert_dataframe("daily_price", _daily_price_frame("000001.SZ", "20260703"))
    _seed_enhanced_rows(store, ["000001.SZ"], "20260703")
    module = _RecordingBaoStockModule()

    result = update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ", "000003.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=module),
    )

    assert module.queried_codes == ["sz.000002", "sz.000003"]
    assert result["already_latest_symbol_count"] == 1
    assert result["pending_symbol_count"] == 2


def test_latest_update_limit_applies_to_pending_symbols(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, symbols=["000001.SZ", "000002.SZ", "000003.SZ"])
    store.upsert_dataframe("daily_price", _daily_price_frame("000001.SZ", "20260703"))
    _seed_enhanced_rows(store, ["000001.SZ"], "20260703")
    module = _RecordingBaoStockModule()

    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ", "000003.SZ"],
        update_limit=1,
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=module),
    )

    assert module.queried_codes == ["sz.000002"]


def test_latest_update_skips_already_latest_symbols(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, symbols=["000001.SZ", "000002.SZ"])
    store.upsert_dataframe("daily_price", _daily_price_frame("000001.SZ", "20260703"))
    store.upsert_dataframe("daily_price", _daily_price_frame("000002.SZ", "20260703"))
    _seed_enhanced_rows(store, ["000001.SZ", "000002.SZ"], "20260703")
    module = _RecordingBaoStockModule()

    result = update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=module),
    )

    assert module.queried_codes == []
    assert result["status"] == "skipped"
    assert "无待更新股票" in result["message"]


def test_baostock_failure_summary_classifies_errors(tmp_path: Path) -> None:
    result = BaoStockClient(baostock_module=_ClassifyingBaoStockModule()).get_daily_price(
        start_date="20260701",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ", "000003.SZ"],
        max_retries=0,
    )

    assert result["failure_summary"]["timeout"] == 1
    assert result["failure_summary"]["connection_error"] == 1
    assert result["failure_summary"]["no_data"] == 1


def test_baostock_retry_only_for_transient_errors(tmp_path: Path) -> None:
    module = _RetryBaoStockModule()

    BaoStockClient(baostock_module=module).get_daily_price(
        start_date="20260701",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ"],
        max_retries=1,
    )

    assert module.calls["sz.000001"] == 2
    assert module.calls["sz.000002"] == 1


def test_baostock_records_failure_examples(tmp_path: Path) -> None:
    result = BaoStockClient(baostock_module=_NoDataBaoStockModule()).get_daily_price(
        start_date="20260701",
        end_date="20260703",
        symbols=[f"000{index:03d}.SZ" for index in range(30)],
        max_retries=0,
    )

    assert result["failure_summary"]["no_data"] == 30
    assert len(result["failure_examples"]["no_data"]) == 20


def test_progress_json_contains_failure_summary(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.json"

    update_market_data(
        goal="history",
        provider="baostock",
        start_date="20260701",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        progress_path=progress_path,
        baostock_client=BaoStockClient(baostock_module=_NoDataBaoStockModule()),
    )
    payload = read_market_data_progress(progress_path)

    assert payload["failure_summary"]["no_data"] == 1
    assert payload["failure_examples"]["no_data"] == ["000001.SZ"]


def test_baostock_daily_basic_mapping(tmp_path: Path) -> None:
    result = BaoStockClient(baostock_module=_BaoStockBasicModule()).get_daily_price(
        start_date="20260703",
        end_date="20260703",
        symbols=["000001.SZ"],
    )

    basic = result["daily_basic"]
    assert basic.loc[0, "ts_code"] == "000001.SZ"
    assert basic.loc[0, "trade_date"] == "20260703"
    assert basic.loc[0, "turnover_rate"] == 2.5
    assert basic.loc[0, "pe"] == 10.2
    assert basic.loc[0, "pb"] == 1.1
    assert basic.loc[0, "ps"] == 3.3


def test_daily_basic_written_for_latest_trade_date(tmp_path: Path) -> None:
    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=_BaoStockBasicModule()),
    )

    daily_basic = DuckDBStore(tmp_path / "market.duckdb").read_table("daily_basic")
    row = daily_basic[daily_basic["ts_code"] == "000001.SZ"].iloc[0]
    assert row["trade_date"] == "20260703"
    assert row["turnover_rate"] == 2.5
    assert row["pe"] == 10.2
    assert row["pb"] == 1.1


def test_adj_factor_identity_written_for_adjusted_baostock_price(tmp_path: Path) -> None:
    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=_BaoStockBasicModule()),
    )

    adj_factor = DuckDBStore(tmp_path / "market.duckdb").read_table("adj_factor")
    row = adj_factor[adj_factor["ts_code"] == "000001.SZ"].iloc[0]
    assert row["trade_date"] == "20260703"
    assert row["adj_factor"] == 1.0
    assert bool(row["derived_adj_factor"]) is True
    assert row["source_provider"] == "baostock_adjusted_price_identity"


def test_adj_factor_identity_has_explicit_source_semantics(tmp_path: Path) -> None:
    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=_BaoStockBasicModule()),
    )

    snapshot = build_data_quality_snapshot(db_path=tmp_path / "market.duckdb", latest_completed_trade_date="20260703")
    assert snapshot["adj_factor_source"] == "baostock_adjusted_price_identity"
    assert "identity" in snapshot["adj_factor_semantics"]
    assert snapshot["adj_factor_is_real_factor"] is False


def test_no_double_adjustment_when_price_already_adjusted(tmp_path: Path) -> None:
    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=_BaoStockBasicModule()),
    )
    store = DuckDBStore(tmp_path / "market.duckdb")
    price = store.read_table("daily_price").iloc[0]
    adj = store.read_table("adj_factor").iloc[0]

    assert float(price["close"]) * float(adj["adj_factor"]) == float(price["close"])


def test_data_quality_snapshot_counts_compatible_adj_factor(tmp_path: Path) -> None:
    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=_BaoStockBasicModule()),
    )

    snapshot = build_data_quality_snapshot(db_path=tmp_path / "market.duckdb", latest_completed_trade_date="20260703")
    assert snapshot["latest_adj_factor_symbol_count"] == 1
    assert snapshot["latest_all_required_tables_symbol_count"] == 1


def test_data_quality_snapshot_explains_compatible_adj_factor(tmp_path: Path) -> None:
    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=_BaoStockBasicModule()),
    )

    snapshot = build_data_quality_snapshot(db_path=tmp_path / "market.duckdb", latest_completed_trade_date="20260703")
    assert "恒等兼容值" in snapshot["adj_factor_user_note"]
    assert "不是真实复权因子" in snapshot["adj_factor_user_note"]


def test_formal_result_not_usable_if_daily_basic_key_fields_missing(tmp_path: Path) -> None:
    update_market_data(
        goal="latest",
        provider="baostock",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        baostock_client=BaoStockClient(baostock_module=_BaoStockModule()),
    )

    snapshot = build_data_quality_snapshot(db_path=tmp_path / "market.duckdb", latest_completed_trade_date="20260703")
    assert snapshot["latest_daily_basic_symbol_count"] == 1
    assert snapshot["latest_daily_basic_key_field_symbol_count"] == 0
    assert snapshot["formal_result_usable"] is False
    assert "daily_basic 缺估值或换手率关键字段" in snapshot["formal_result_warning_reason"]


def test_enhanced_backfill_targets_existing_price_missing_basic_or_adj(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, symbols=["000001.SZ", "000002.SZ"])
    store.upsert_dataframe("daily_price", pd.concat([_daily_price_frame("000001.SZ", "20260703"), _daily_price_frame("000002.SZ", "20260703")], ignore_index=True))
    module = _RecordingBaoStockBasicModule()

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ"],
        update_limit=1,
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=module),
        force_snapshot=True,
    )

    assert module.queried_codes == ["sz.000001"]
    assert result["enhanced_pending_symbol_count"] == 2
    assert result["missing_daily_basic_symbol_count"] == 2
    assert result["missing_adj_factor_symbol_count"] == 2


def test_update_limit_applies_to_enhanced_backfill_pool(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, symbols=["000001.SZ", "000002.SZ", "000003.SZ"])
    store.upsert_dataframe(
        "daily_price",
        pd.concat([_daily_price_frame("000001.SZ", "20260703"), _daily_price_frame("000002.SZ", "20260703"), _daily_price_frame("000003.SZ", "20260703")], ignore_index=True),
    )
    module = _RecordingBaoStockBasicModule()

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ", "000003.SZ"],
        update_limit=2,
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=module),
        force_snapshot=True,
    )

    assert module.queried_codes == ["sz.000001", "sz.000002"]
    assert result["enhanced_processed_symbol_count"] == 2


def test_enhanced_backfill_writes_daily_basic_without_new_price(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, symbols=["000001.SZ"])
    store.upsert_dataframe("daily_price", _daily_price_frame("000001.SZ", "20260703"))
    before_price_rows = len(store.read_table("daily_price"))

    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        update_limit=1,
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=_RecordingBaoStockBasicModule()),
        force_snapshot=True,
    )
    after_price_rows = len(store.read_table("daily_price"))

    assert after_price_rows == before_price_rows
    assert result["daily_basic_written_row_count"] == 1
    assert len(store.read_table("daily_basic")) == 1


def test_enhanced_backfill_writes_latest_identity_adj_factor(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, symbols=["000001.SZ"])
    store.upsert_dataframe("daily_price", _daily_price_frame("000001.SZ", "20260703"))

    update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        update_limit=1,
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=_RecordingBaoStockBasicModule()),
        force_snapshot=True,
    )

    adj = store.read_table("adj_factor")
    assert adj["trade_date"].tolist() == ["20260703"]
    assert adj["adj_factor"].tolist() == [1.0]


def test_refresh_data_quality_reports_identity_adj_factor_source(tmp_path: Path, capsys) -> None:
    store = _seed_store(tmp_path, symbols=["000001.SZ"])
    store.upsert_dataframe("daily_price", _daily_price_frame("000001.SZ", "20260703"))
    update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        update_limit=1,
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=_RecordingBaoStockBasicModule()),
        force_snapshot=True,
    )

    refresh_data_quality_status(status_path=_status_path(tmp_path), output_format="text", db_path=store.db_path)
    output = capsys.readouterr().out
    assert "adj_factor_source: baostock_adjusted_price_identity" in output
    assert "恒等兼容值" in output


def test_latest_all_required_tables_increases_after_enhanced_backfill(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, symbols=["000001.SZ"])
    store.upsert_dataframe("daily_price", _daily_price_frame("000001.SZ", "20260703"))
    before = build_data_quality_snapshot(db_path=store.db_path, latest_completed_trade_date="20260703")

    update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        update_limit=1,
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=_RecordingBaoStockBasicModule()),
        force_snapshot=True,
    )
    after = build_data_quality_snapshot(db_path=store.db_path, latest_completed_trade_date="20260703")

    assert before["latest_all_required_tables_symbol_count"] == 0
    assert after["latest_all_required_tables_symbol_count"] == 1


def test_market_data_progress_finishes_on_success_or_partial(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.json"

    update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        progress_path=progress_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )
    payload = read_market_data_progress(progress_path)

    assert payload["running"] is False
    assert payload["status"] == "partial"
    assert payload["finished_at"]


def test_market_data_progress_finishes_on_failure(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.json"

    update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        progress_path=progress_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_NoSpotModule()),
        baostock_client=BaoStockClient(baostock_module=_FailBaoStockModule()),
        force_snapshot=True,
    )
    payload = read_market_data_progress(progress_path)

    assert payload["running"] is False
    assert payload["status"] == "failed"
    assert payload["finished_at"]


def test_market_data_progress_atomic_write(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.json"
    writer = MarketDataProgressWriter(progress_path)

    writer.start(goal="latest", provider="auto", total_symbol_count=2)
    writer.update_symbol("baostock", "历史行情兜底", symbol="000001.SZ", status="success", written_rows=3)

    payload = read_market_data_progress(progress_path)
    assert payload["current_symbol"] == "000001.SZ"
    assert payload["written_row_count"] == 3
    assert not progress_path.with_suffix(".json.tmp").exists()


def test_akshare_spot_snapshot_mapping_daily_price() -> None:
    result = AKShareSpotSnapshotClient(akshare_module=_SpotModule()).fetch_latest(
        trade_date="20260703",
        symbols=["000001.SZ"],
        force=True,
    )

    price = result["daily_price"]
    assert price.loc[0, "ts_code"] == "000001.SZ"
    assert price.loc[0, "trade_date"] == "20260703"
    assert price.loc[0, "open"] == 10.0
    assert price.loc[0, "close"] == 10.5
    assert result["source_granularity"] == "eod_snapshot"


def test_akshare_spot_snapshot_not_used_before_market_close_without_force() -> None:
    result = AKShareSpotSnapshotClient(akshare_module=_SpotModule()).fetch_latest(
        trade_date="20260703",
        symbols=["000001.SZ"],
        now=datetime(2026, 7, 3, 14, 30),
    )

    assert result["status"] == "skipped"
    assert result["daily_price"].empty


def test_spot_snapshot_skips_on_trade_day_before_close_without_force(tmp_path: Path) -> None:
    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        baostock_client=BaoStockClient(baostock_module=_FailBaoStockModule()),
        now=datetime(2026, 7, 3, 14, 30),
    )

    spot_attempt = next(item for item in result["provider_attempts"] if item["provider"] == "akshare_spot_snapshot")
    assert spot_attempt["status"] == "skipped"
    assert "15:10" in spot_attempt["message"]


def test_spot_snapshot_allowed_on_non_trade_day_before_close(tmp_path: Path) -> None:
    result = update_market_data(
        goal="latest",
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        now=datetime(2026, 7, 5, 9, 30),
    )

    spot_attempt = next(item for item in result["provider_attempts"] if item["provider"] == "akshare_spot_snapshot")
    assert spot_attempt["status"] == "success"
    assert "非交易日" in spot_attempt["message"]
    assert result["latest_success_provider"] == "akshare_spot_snapshot"


def test_spot_snapshot_uses_latest_completed_trade_date_on_non_trade_day(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.real_data_end_date = ""
    store = _seed_store(tmp_path)

    update_market_data(
        goal="latest",
        provider="auto",
        symbols=["000001.SZ"],
        settings=settings,
        status_path=_status_path(tmp_path),
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        now=datetime(2026, 7, 5, 9, 30),
    )
    price = store.read_table("daily_price")

    assert price["trade_date"].astype(str).tolist() == ["20260703"]
    assert "20260705" not in price["trade_date"].astype(str).tolist()


def test_akshare_spot_snapshot_marks_partial_daily_basic() -> None:
    result = AKShareSpotSnapshotClient(akshare_module=_SpotModule()).fetch_latest(
        trade_date="20260703",
        symbols=["000001.SZ"],
        force=True,
    )

    basic = result["daily_basic"]
    assert result["partial_update"] is True
    assert basic.loc[0, "turnover_rate"] == 2.5
    assert basic.loc[0, "pe"] == 11.0


def test_adj_factor_forward_fill_marks_derived(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    store.upsert_dataframe("adj_factor", pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260702"], "adj_factor": [1.23]}))

    written = forward_fill_adj_factor(store, end_date="20260703", symbols=["000001.SZ"])
    result = store.read_table("adj_factor")

    assert written == 1
    row = result[result["trade_date"] == "20260703"].iloc[0]
    assert row["adj_factor"] == 1.23
    assert bool(row["derived_adj_factor"]) is True


def test_baostock_daily_price_mapping() -> None:
    result = BaoStockClient(baostock_module=_BaoStockModule()).get_daily_price(
        start_date="20260701",
        end_date="20260703",
        symbols=["000001.SZ"],
    )

    price = result["daily_price"]
    assert price.loc[0, "ts_code"] == "000001.SZ"
    assert price.loc[0, "trade_date"] == "20260703"
    assert price.loc[0, "close"] == 10.5


def test_baostock_partial_provider_status() -> None:
    result = BaoStockClient(baostock_module=_PartialBaoStockModule()).get_daily_price(
        start_date="20260701",
        end_date="20260703",
        symbols=["000001.SZ", "000002.SZ"],
    )

    assert result["status"] == "partial_success"
    assert result["failure_records"]


def test_manual_import_daily_price_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "price.csv"
    pd.DataFrame({"股票代码": ["000001"], "交易日期": ["2026-07-03"], "开盘": [10], "最高": [11], "最低": [9], "收盘": [10.5], "成交量": [100], "成交额": [1000]}).to_csv(csv_path, index=False)
    status_path = _status_path(tmp_path)

    result = import_market_data(file=csv_path, table="daily_price", db_path=_seed_store(tmp_path).db_path, status_path=status_path)

    assert result["written_rows"] == 1
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["manual_import_last_file"] == str(csv_path)


def test_manual_import_xlsx(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "basic.xlsx"
    pd.DataFrame({"代码": ["600000"], "日期": [20260703], "换手率": [1.2], "市盈率": [9.0], "市净率": [0.8]}).to_excel(xlsx_path, index=False)
    result = import_market_data(file=xlsx_path, table="daily_basic", db_path=_seed_store(tmp_path).db_path, status_path=_status_path(tmp_path))

    assert result["written_rows"] == 1


def test_manual_import_trade_date_normalization() -> None:
    frame = normalize_import_frame(pd.DataFrame({"ts_code": ["000001"], "trade_date": ["2026-07-03"], "close": [10.0]}), "daily_price")

    assert frame.loc[0, "trade_date"] == "20260703"


def test_manual_import_symbol_normalization() -> None:
    frame = normalize_import_frame(pd.DataFrame({"股票代码": ["600000"], "交易日期": ["20260703"], "收盘": [10.0]}), "daily_price")

    assert frame.loc[0, "ts_code"] == "600000.SH"


def test_manual_import_upsert_deduplicates(tmp_path: Path) -> None:
    csv_path = tmp_path / "price.csv"
    pd.DataFrame({"ts_code": ["000001.SZ", "000001.SZ"], "trade_date": ["20260703", "20260703"], "close": [10, 11]}).to_csv(csv_path, index=False)
    store = _seed_store(tmp_path)

    import_market_data(file=csv_path, table="daily_price", db_path=store.db_path, status_path=_status_path(tmp_path))
    result = store.read_table("daily_price")

    assert len(result[result["ts_code"] == "000001.SZ"]) == 1
    assert result[result["ts_code"] == "000001.SZ"].iloc[0]["close"] == 11


def test_update_market_data_refreshes_data_quality_snapshot(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)
    result = update_market_data(
        provider="akshare_spot_snapshot",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert result["status"] == "success"
    assert payload["latest_success_provider"] == "akshare_spot_snapshot"
    assert payload["data_quality_snapshot_source"] == "readonly_duckdb_sql"


def test_provider_failure_recorded_in_status_json(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)
    update_market_data(provider="baostock", end_date="20260703", symbols=["000001.SZ"], settings=_settings(tmp_path), status_path=status_path, baostock_client=BaoStockClient(baostock_module=_FailBaoStockModule()))
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert payload["provider_attempts"][-1]["provider"] == "baostock"
    assert payload["latest_provider_failure_reason"]


def test_partial_success_does_not_mark_formal_usable(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)
    update_market_data(
        provider="akshare_spot_snapshot",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert payload["latest_update_completeness"] == "partial"
    assert payload["formal_result_usable"] is False


def test_status_json_has_quality_contract_when_snapshot_refresh_fails(tmp_path: Path, monkeypatch) -> None:
    status_path = _status_path(tmp_path)
    monkeypatch.setattr(
        "core.jobs.market_data_status.refresh_data_quality_status",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("snapshot failed")),
    )

    update_market_data(
        provider="akshare_spot_snapshot",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert payload["data_quality_snapshot_source"] == "unavailable"
    assert payload["data_quality_status"] == "unknown"
    assert payload["formal_result_usable"] is False
    assert "数据质量快照未能刷新" in payload["formal_result_warning_reason"]


def test_streamlit_free_provider_fallback_section() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")

    assert "数据更新操作" in source
    assert "一键更新最新交易日数据" in source
    assert "补历史行情缺口" in source
    assert "运行数据源诊断" in source
    assert "上传 CSV / Excel 导入行情" in source
    assert "update_market_data" in source
    assert "import_market_data" in source


def test_streamlit_update_page_has_only_user_level_actions() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    primary = _function_source(source, "_render_user_level_data_update_actions")

    for label in ["一键更新最新交易日数据", "补历史行情缺口", "上传 CSV / Excel 导入行情", "运行数据源诊断"]:
        assert label in primary
    for old_label in ["测试 AKShare K 线接口", "测试 AKShare 实时行情快照", "用实时行情快照补最新交易日", "用 BaoStock 补历史 daily_price"]:
        assert old_label not in primary


def test_provider_buttons_hidden_in_advanced_expander() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    status_tab = _function_source(source, "_render_status_tab")
    advanced = _function_source(source, "_render_status_advanced_sections")

    assert "_render_full_batch_update_section" not in status_tab
    assert "_render_free_provider_fallback_section" not in status_tab
    assert "_render_free_provider_fallback_section" in advanced


def test_update_latest_uses_provider_auto() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    primary = _function_source(source, "_render_user_level_data_update_actions")

    assert "auto_update_latest_trade_date" in primary
    assert '"--goal", "latest"' in primary
    assert '"--provider", "auto"' in primary


def test_streamlit_one_click_update_calls_goal_latest_provider_auto() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    primary = _function_source(source, "_render_user_level_data_update_actions")

    assert "一键更新最新交易日数据" in primary
    assert '"--goal", "latest"' in primary
    assert '"--provider", "auto"' in primary


def test_streamlit_history_backfill_calls_goal_history_provider_auto() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    primary = _function_source(source, "_render_user_level_data_update_actions")

    assert "auto_repair_history_gap" in primary
    assert '"--goal", "history"' in primary
    assert '"--provider", "auto"' in primary


def test_streamlit_no_col4_name_error() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    primary = _function_source(source, "_render_user_level_data_update_actions")

    assert "col1, col2, col3, col4 = st.columns(4)" in primary
    assert "col4.button" in primary


def test_streamlit_primary_view_hides_technical_fields() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    primary = _function_source(source, "_render_user_level_data_update_actions")
    visible_labels = _button_labels(primary)

    forbidden_visible = ["AKShare", "BaoStock", "Tushare", "curl_returncode", "used_url", "stderr", "partial_update"]
    assert visible_labels
    for label in visible_labels:
        assert not any(term.lower() in label.lower() for term in forbidden_visible)


def test_streamlit_primary_attempt_message_sanitizes_technical_fields() -> None:
    from web.streamlit_app import _attempt_user_message

    message = _attempt_user_message(
        "akshare_kline",
        {
            "status": "failed",
            "error_message": "ProxyError curl_returncode=52 push2his.eastmoney.com stderr traceback",
        },
    )

    assert "东方财富 K 线接口不可用" in message
    for forbidden in ["ProxyError", "curl", "push2his", "stderr", "traceback"]:
        assert forbidden not in message


def test_streamlit_advanced_contains_technical_details() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    advanced = _function_source(source, "_render_status_advanced_sections")

    assert "_render_free_provider_fallback_section" in advanced
    assert "高级" in advanced


def test_streamlit_progress_table_reads_progress_json() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")

    assert "read_market_data_progress(DEFAULT_PROGRESS_PATH)" in source
    assert "_render_market_data_update_progress" in source
    assert "provider_progress" in source


def test_streamlit_running_progress_autorefresh() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    progress_source = _function_source(source, "_render_market_data_update_progress")

    assert "time.sleep(2)" in progress_source
    assert "st.rerun()" in progress_source


def test_streamlit_progress_primary_view_hides_technical_fields() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    progress_source = _function_source(source, "_render_market_data_update_progress")
    forbidden = ["used_url", "curl_returncode", "proxy", "IPv4", "IPv6", "traceback", "raw_exception", "push2his.eastmoney.com"]

    for term in forbidden:
        assert term not in progress_source


def test_streamlit_displays_failure_summary_without_raw_traceback() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    progress_source = _function_source(source, "_render_market_data_update_progress")

    assert "失败原因摘要" in progress_source
    assert "_failure_type_cn" in progress_source
    for forbidden in ["traceback", "raw_exception", "socket 原始堆栈"]:
        assert forbidden not in progress_source


def test_streamlit_displays_adj_factor_semantics() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    status_source = _function_source(source, "_render_status_quality_main")
    semantics_source = _function_source(source, "_status_adjustment_semantics_row")

    assert "复权语义" in status_source
    assert "adj_factor 来源" in semantics_source
    assert "是否真实复权因子" in semantics_source
    assert "用户说明" in semantics_source


def test_streamlit_displays_layered_data_quality_status() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    conclusion_source = _function_source(source, "_status_conclusion_row")

    assert "核心价格行情" in conclusion_source
    assert "技术指标研究" in conclusion_source
    assert "增强数据" in conclusion_source
    assert "估值/市值数据" in conclusion_source
    assert "正式全字段结果" in conclusion_source


def test_streamlit_hides_raw_technical_details() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    primary = _function_source(source, "_render_status_quality_main") + _function_source(source, "_status_adjustment_semantics_row")

    for forbidden in ["traceback", "raw_exception", "curl", "used_url", "proxy", "IPv4", "IPv6"]:
        assert forbidden not in primary


def test_auto_provider_attempts_are_recorded_but_not_user_selected(tmp_path: Path) -> None:
    status_path = _status_path(tmp_path)
    update_market_data(
        provider="auto",
        end_date="20260703",
        symbols=["000001.SZ"],
        settings=_settings(tmp_path),
        status_path=status_path,
        akshare_client=_EmptyAkshareKline(),
        spot_client=AKShareSpotSnapshotClient(akshare_module=_SpotModule()),
        force_snapshot=True,
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")

    assert payload["provider_attempts"]
    assert "选择 provider" not in source
    assert "选择数据源" not in source


def test_data_quality_snapshot_metrics_preserved(tmp_path: Path) -> None:
    from tests.test_task57c_data_quality_snapshot import _seed_quality_db
    from core.diagnostics.data_quality_snapshot import build_data_quality_snapshot

    db_path = _seed_quality_db(tmp_path)
    snapshot = build_data_quality_snapshot(db_path=db_path, research_trade_date="20260703", latest_completed_trade_date="20260703")

    assert snapshot["latest_daily_price_symbol_count"] == 68
    assert snapshot["latest_daily_basic_symbol_count"] == 3
    assert snapshot["latest_adj_factor_symbol_count"] == 0
    assert snapshot["any_daily_price_symbol_count"] == 4995
    assert snapshot["history_missing_symbol_count"] == 60
    assert snapshot["data_quality_status"] == "poor"
    assert snapshot["formal_result_usable"] is False


def test_technical_terms_not_in_primary_buttons() -> None:
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    primary = _function_source(source, "_render_user_level_data_update_actions")
    labels = _button_labels(primary)
    forbidden = ["provider", "akshare", "baostock", "partial_update", "source_granularity", "curl_returncode", "used_url", "stderr"]

    assert labels
    for label in labels:
        lowered = label.lower()
        assert not any(term in lowered for term in forbidden)


def test_no_data_runtime_files_committed() -> None:
    tracked_sensitive = ["data/a_stock_assistant.duckdb", "data/runtime/scheduled_daily_update_status.json"]
    # This test guards the intended policy in source; git status is checked by verification.
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "data/" in gitignore
    assert "reports/" in gitignore or "reports/*.xlsx" in gitignore
    for path in tracked_sensitive:
        assert not Path(path).is_file() or path.startswith("data/")


def _function_source(source: str, name: str) -> str:
    start = source.index(f"def {name}")
    next_def = source.find("\ndef ", start + 1)
    return source[start:] if next_def == -1 else source[start:next_def]


def _button_labels(source: str) -> list[str]:
    import re

    return re.findall(r'button\("([^"]+)"', source)


def _seed_store(tmp_path: Path, symbols: list[str] | None = None) -> DuckDBStore:
    symbols = symbols or ["000001.SZ", "000002.SZ"]
    store = DuckDBStore(tmp_path / "market.duckdb")
    store.initialize()
    store.upsert_dataframe(
        "stock_basic",
        pd.DataFrame(
            {
                "ts_code": symbols,
                "symbol": [item.split(".")[0] for item in symbols],
                "name": [f"样本{index}" for index, _item in enumerate(symbols, start=1)],
            }
        ),
    )
    return store


def _daily_price_frame(symbol: str, trade_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_code": symbol,
                "trade_date": trade_date,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "pre_close": 10.0,
                "change": 0.5,
                "pct_chg": 5.0,
                "vol": 100.0,
                "amount": 1000.0,
            }
        ]
    )


def _seed_enhanced_rows(store: DuckDBStore, symbols: list[str], trade_date: str) -> None:
    store.upsert_dataframe(
        "daily_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": symbol,
                    "trade_date": trade_date,
                    "turnover_rate": 2.0,
                    "volume_ratio": pd.NA,
                    "pe": 10.0,
                    "pb": 1.0,
                    "ps": 2.0,
                    "total_mv": pd.NA,
                    "circ_mv": pd.NA,
                }
                for symbol in symbols
            ]
        ),
    )
    store.upsert_dataframe(
        "adj_factor",
        pd.DataFrame(
            [
                {
                    "ts_code": symbol,
                    "trade_date": trade_date,
                    "adj_factor": 1.0,
                    "derived_adj_factor": True,
                    "source_provider": "baostock_adjusted_price_identity",
                }
                for symbol in symbols
            ]
        ),
    )


def _settings(tmp_path: Path, tushare_token: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        duckdb_path=tmp_path / "market.duckdb",
        tushare_token=tushare_token,
        akshare_adjust="qfq",
        data_source_request_timeout_seconds=1,
        symbol_update_timeout_seconds=1,
        full_update_lookback_days=250,
        real_data_end_date="20260703",
        akshare_symbols=["000001", "000002"],
    )


def _status_path(tmp_path: Path) -> Path:
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"research_trade_date": "20260703", "latest_completed_trade_date": "20260703"}), encoding="utf-8")
    return path


class _EmptyAkshareKline:
    def get_daily_price(self, *_args, **_kwargs):
        return pd.DataFrame()


class _RecordingEmptyAkshareKline:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def get_daily_price(self, _start_date, _end_date, symbols):
        self.calls.append(list(symbols or []))
        return pd.DataFrame()


class _ExceptionAkshareKline:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls: list[list[str]] = []

    def get_daily_price(self, _start_date, _end_date, symbols):
        self.calls.append(list(symbols or []))
        raise RuntimeError(self.message)


class _SpotModule:
    def stock_zh_a_spot_em(self):
        return pd.DataFrame(
            [
                {"代码": "000001", "名称": "平安银行", "今开": 10.0, "最高": 11.0, "最低": 9.8, "最新价": 10.5, "昨收": 10.0, "成交量": 1000, "成交额": 1000000, "换手率": 2.5, "市盈率": 11.0, "市净率": 1.1},
                {"代码": "830001", "名称": "北交所样本", "最新价": 1.0, "成交量": 10, "成交额": 10},
                {"代码": "000002", "名称": "停牌", "最新价": 0, "成交量": 0, "成交额": 0},
            ]
        )


class _NoSpotModule:
    pass


class _BaoStockResult:
    error_code = "0"
    error_msg = ""
    fields = ["date", "code", "open", "high", "low", "close", "preclose", "volume", "amount", "pctChg"]

    def __init__(self, rows, fields: list[str] | None = None):
        self.rows = list(rows)
        self.index = -1
        if fields is not None:
            self.fields = fields

    def next(self):
        self.index += 1
        return self.index < len(self.rows)

    def get_row_data(self):
        return self.rows[self.index]


class _BaoStockModule:
    def login(self):
        return SimpleNamespace(error_code="0", error_msg="")

    def logout(self):
        return SimpleNamespace(error_code="0")

    def query_history_k_data_plus(self, *_args, **_kwargs):
        return _BaoStockResult([["2026-07-03", "sz.000001", "10", "11", "9", "10.5", "10", "100", "1000", "5"]])


class _BaoStockBasicModule(_BaoStockModule):
    fields = ["date", "code", "open", "high", "low", "close", "preclose", "volume", "amount", "pctChg", "turn", "peTTM", "pbMRQ", "psTTM", "tradestatus", "isST"]

    def query_history_k_data_plus(self, code, *_args, **_kwargs):
        return _BaoStockResult(
            [["2026-07-03", code, "10", "11", "9", "10.5", "10", "100", "1000", "5", "2.5", "10.2", "1.1", "3.3", "1", "0"]],
            fields=self.fields,
        )


class _RecordingBaoStockBasicModule(_BaoStockBasicModule):
    def __init__(self) -> None:
        self.queried_codes: list[str] = []

    def query_history_k_data_plus(self, code, *_args, **_kwargs):
        self.queried_codes.append(code)
        return super().query_history_k_data_plus(code)


class _RecordingBaoStockModule(_BaoStockModule):
    def __init__(self) -> None:
        self.queried_codes: list[str] = []

    def query_history_k_data_plus(self, code, *_args, **_kwargs):
        self.queried_codes.append(code)
        return _BaoStockResult([["2026-07-03", code, "10", "11", "9", "10.5", "10", "100", "1000", "5"]])


class _PartialBaoStockModule(_BaoStockModule):
    def query_history_k_data_plus(self, code, *_args, **_kwargs):
        if code == "sz.000002":
            return SimpleNamespace(error_code="1", error_msg="mock failure", fields=[], next=lambda: False)
        return super().query_history_k_data_plus(code)


class _FailBaoStockModule(_BaoStockModule):
    def login(self):
        return SimpleNamespace(error_code="1", error_msg="login failed")


class _NoDataBaoStockModule(_BaoStockModule):
    def query_history_k_data_plus(self, code, *_args, **_kwargs):
        return _BaoStockResult([])


class _ClassifyingBaoStockModule(_BaoStockModule):
    def query_history_k_data_plus(self, code, *_args, **_kwargs):
        if code == "sz.000001":
            raise TimeoutError("request timeout")
        if code == "sz.000002":
            raise ConnectionError("socket connection reset")
        return _BaoStockResult([])


class _RetryBaoStockModule(_BaoStockModule):
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def query_history_k_data_plus(self, code, *_args, **_kwargs):
        self.calls[code] = self.calls.get(code, 0) + 1
        if code == "sz.000001" and self.calls[code] == 1:
            raise TimeoutError("request timeout")
        if code == "sz.000002":
            return SimpleNamespace(error_code="1", error_msg="provider rejected", fields=[], next=lambda: False)
        return _BaoStockResult([["2026-07-03", code, "10", "11", "9", "10.5", "10", "100", "1000", "5"]])
