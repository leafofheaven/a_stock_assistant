"""Tests for Task 57A data source network diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.factors.scoring import DEFAULT_WEIGHTS
from core.jobs import diagnose_data_source_network as diag
from core.runtime.command_runner import ALLOWED_COMMANDS
from core.runtime.data_source_preflight import run_data_source_preflight


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(duckdb_path=tmp_path / "diagnose.duckdb")


def _patch_ok_basics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diag, "check_duckdb_access", lambda path: {"ok": True, "locked": False, "message": "DuckDB read_only 可访问。"})
    monkeypatch.setattr(
        diag,
        "detect_proxy_environment",
        lambda: {"status": "no_proxy", "message": "未检测到代理配置。", "local_proxy_detected": False},
    )
    monkeypatch.setattr(diag, "diagnose_dns", lambda hosts=diag.EASTMONEY_HOSTS: {"status": "ok", "hosts": {}})


def test_diagnose_data_source_network_outputs_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Text output should include the key diagnostic sections."""
    _patch_ok_basics(monkeypatch)
    monkeypatch.setattr(
        diag,
        "run_eastmoney_request_tests",
        lambda **kwargs: [
            {"name": "python_default", "success": True, "status": "success", "returncode": None, "http_status": 200, "failure_category": ""},
            {"name": "curl_default", "success": True, "status": "success", "returncode": 0, "http_status": 200, "failure_category": ""},
        ],
    )

    result = diag.diagnose_data_source_network(output_format="text", settings=_settings(tmp_path), include_curl=True, include_python=True)

    output = capsys.readouterr().out
    assert result["status"] == "ok"
    assert "数据源网络诊断" in output
    assert "DuckDB" in output
    assert "代理" in output
    assert "DNS" in output
    assert "东方财富接口" in output


def test_diagnose_data_source_network_outputs_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """JSON output should be parseable and include Task 57B-ready fields."""
    _patch_ok_basics(monkeypatch)
    monkeypatch.setattr(diag, "run_eastmoney_request_tests", lambda **kwargs: [])

    diag.diagnose_data_source_network(output_format="json", settings=_settings(tmp_path), include_curl=False, include_python=False)

    payload = json.loads(capsys.readouterr().out)
    assert {"status", "summary", "suggested_action", "generated_at"}.issubset(payload)
    assert "duckdb_status" in payload
    assert "proxy_status" in payload
    assert "dns_status" in payload


def test_diagnosis_masks_sensitive_proxy_values() -> None:
    """Proxy values should be sanitized before display or JSON output."""
    masked = diag._mask_value(
        {
            "https": "http://user:secret-password@127.0.0.1:7897",
            "token": "sk-proj-123456",
        }
    )
    joined = json.dumps(masked, ensure_ascii=False)
    assert "secret-password" not in joined
    assert "sk-proj-123456" not in joined
    assert "127.0.0.1:7897" in joined


def test_diagnosis_classifies_ipv4_success_ipv6_failure() -> None:
    """IPv4 success with IPv6 failure should produce an IPv6/default-path warning."""
    result = diag.classify_diagnosis(
        duckdb={"ok": True, "locked": False},
        proxy={"status": "no_proxy"},
        dns={"status": "ok"},
        request_tests=[
            {"name": "curl_ipv4", "success": True},
            {"name": "curl_ipv6", "success": False},
        ],
    )
    assert result["status"] == "warning"
    assert "IPv6" in result["summary"]


def test_diagnosis_classifies_all_network_failures() -> None:
    """All request failures should point to current network or data-source availability."""
    result = diag.classify_diagnosis(
        duckdb={"ok": True, "locked": False},
        proxy={"status": "proxy_detected"},
        dns={"status": "ok"},
        request_tests=[
            {"name": "python_default", "success": False},
            {"name": "curl_default", "success": False},
            {"name": "curl_ipv4", "success": False},
            {"name": "curl_ipv6", "success": False},
        ],
    )
    assert result["status"] == "failed"
    assert "当前网络或数据源不可用" in result["summary"]
    assert "手机热点" in result["suggested_action"]


def test_preflight_includes_network_diagnosis_summary_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Preflight failure should include DNS, curl, stderr, and suggested action fields."""
    monkeypatch.setattr("core.runtime.data_source_preflight.check_duckdb_access", lambda path: {"ok": True, "message": "ok"})
    monkeypatch.setattr("core.runtime.data_source_preflight.detect_proxy_settings", lambda: {"has_proxy": False, "message": "no proxy"})
    monkeypatch.setattr(
        "core.runtime.data_source_preflight.check_eastmoney_dns",
        lambda: {"status": "ok", "ipv4_status": "available", "ipv6_status": "missing"},
    )
    monkeypatch.setattr(
        "core.runtime.data_source_preflight.check_eastmoney_kline",
        lambda **kwargs: {
            "ok": False,
            "status": "failed",
            "message": "东方财富 K 线接口当前不可用",
            "curl_returncode": 52,
            "stderr": "Empty reply from server",
        },
    )

    result = run_data_source_preflight(settings=_settings(tmp_path), skip_network=False)

    assert result["status"] == "failed"
    assert result["dns_status"] == "ok"
    assert result["ipv4_status"] == "available"
    assert result["ipv6_status"] == "missing"
    assert result["eastmoney_kline"]["curl_returncode"] == 52
    assert "suggested_action" in result


def test_preflight_warning_when_curl_fallback_is_available(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Preflight should allow runs when Eastmoney is reachable through curl fallback."""
    monkeypatch.setattr("core.runtime.data_source_preflight.check_duckdb_access", lambda path: {"ok": True, "message": "ok"})
    monkeypatch.setattr("core.runtime.data_source_preflight.detect_proxy_settings", lambda: {"has_proxy": True, "message": "proxy"})
    monkeypatch.setattr(
        "core.runtime.data_source_preflight.check_eastmoney_dns",
        lambda: {"status": "ok", "ipv4_status": "available", "ipv6_status": "available"},
    )
    monkeypatch.setattr(
        "core.runtime.data_source_preflight.check_eastmoney_kline",
        lambda **kwargs: {
            "ok": True,
            "status": "warning",
            "warning_reason": "Python 请求失败但 curl fallback 可用",
            "curl_fallback_available": True,
            "message": "partial",
        },
    )

    result = run_data_source_preflight(settings=_settings(tmp_path), skip_network=False)

    assert result["status"] == "warning"
    assert result["ok"] is True
    assert result["preflight_allows_run"] is True
    assert result["curl_fallback_available"] is True
    assert "curl fallback" in result["preflight_warning_reason"]


def test_streamlit_has_network_diagnosis_button() -> None:
    """Streamlit should expose a safe network diagnosis command without auto-running updates."""
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")
    assert "运行数据源网络诊断" in source
    assert "diagnose_data_source_network" in ALLOWED_COMMANDS
    assert "core.jobs.diagnose_data_source_network" in " ".join(ALLOWED_COMMANDS["diagnose_data_source_network"])
    assert "run_command_streaming" in source


def test_no_algorithm_changes() -> None:
    """Task 57A should not alter scoring, selection, Elder, or entry-zone logic."""
    assert DEFAULT_WEIGHTS == {
        "trend_score": 0.30,
        "momentum_score": 0.20,
        "liquidity_score": 0.20,
        "fundamental_score": 0.15,
        "volatility_score": 0.15,
    }
    root = Path(__file__).resolve().parents[1]
    selection_source = (root / "core" / "strategy" / "selector.py").read_text(encoding="utf-8")
    elder_source = (root / "core" / "technical" / "elder.py").read_text(encoding="utf-8")
    entry_zone_source = (root / "core" / "entry_zones" / "calculator.py").read_text(encoding="utf-8")
    assert 'sort_values(["trade_date", "total_score", "ts_code"], ascending=[True, False, True])' in selection_source
    assert "does not replace or\n    modify ``total_score``" in elder_source
    assert "calculate_entry_zones_for_targets" in entry_zone_source
