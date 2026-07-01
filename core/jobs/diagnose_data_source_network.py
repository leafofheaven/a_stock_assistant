"""Diagnose local network paths for Eastmoney data source access."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.runtime.data_source_preflight import (
    EASTMONEY_KLINE_URL,
    EASTMONEY_REFERER,
    EASTMONEY_USER_AGENT,
    check_duckdb_access,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SENSITIVE_MARKERS = ("password", "token", "secret", "sk-", "apikey", "api_key", "key=")
EASTMONEY_HOSTS = ("push2his.eastmoney.com", "push2.eastmoney.com")
EASTMONEY_TEST_SECID = "secid=0.000001"


def diagnose_data_source_network(
    *,
    output_format: str = "text",
    output_path: str | Path | None = None,
    timeout_seconds: int = 20,
    include_curl: bool = True,
    include_python: bool = True,
    include_dns: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run read-only local network diagnostics for Eastmoney access."""
    resolved_settings = settings or get_settings()
    used_url = EASTMONEY_KLINE_URL.format(end_date="20260630")
    generated_at = datetime.now().isoformat(timespec="seconds")
    duckdb = check_duckdb_access(Path(resolved_settings.duckdb_path))
    proxies = detect_proxy_environment()
    dns = diagnose_dns(EASTMONEY_HOSTS) if include_dns else {"status": "skipped", "hosts": {}}
    request_tests = run_eastmoney_request_tests(
        used_url=used_url,
        timeout_seconds=timeout_seconds,
        include_curl=include_curl,
        include_python=include_python,
        proxies=proxies,
    )
    classification = classify_diagnosis(duckdb=duckdb, proxy=proxies, dns=dns, request_tests=request_tests)
    result = {
        "status": classification["status"],
        "summary": classification["summary"],
        "suggested_action": classification["suggested_action"],
        "generated_at": generated_at,
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "cwd": str(Path.cwd()),
            "project_root": str(PROJECT_ROOT),
            "is_project_dir": (PROJECT_ROOT / "pyproject.toml").exists(),
            "env_exists": (PROJECT_ROOT / ".env").exists(),
            "duckdb_path": str(resolved_settings.duckdb_path),
            "duckdb_file_exists": Path(resolved_settings.duckdb_path).exists(),
        },
        "duckdb": duckdb,
        "proxy": proxies,
        "dns": dns,
        "eastmoney": {
            "used_url": used_url,
            "headers_present": {"user_agent": True, "referer": True},
            "tests": request_tests,
        },
        "duckdb_status": "locked" if duckdb.get("locked") else ("ok" if duckdb.get("ok") else "failed"),
        "proxy_status": proxies.get("status"),
        "dns_status": dns.get("status"),
        "eastmoney_status": classification.get("eastmoney_status"),
        "python_request_status": _test_status(request_tests, "python_default"),
        "curl_default_status": _test_status(request_tests, "curl_default"),
        "curl_ipv4_status": _test_status(request_tests, "curl_ipv4"),
        "curl_ipv6_status": _test_status(request_tests, "curl_ipv6"),
    }
    result = _mask_value(result)
    if output_path:
        Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_diagnosis_text(result))
    return result


def detect_proxy_environment() -> dict[str, Any]:
    """Return sanitized Python, environment, and macOS proxy settings."""
    urllib_proxies = _mask_value(urllib.request.getproxies())
    env_proxies = {
        key: _mask_value(value)
        for key, value in os.environ.items()
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    scutil = _scutil_proxy()
    combined = "\n".join([json.dumps(urllib_proxies, ensure_ascii=False), json.dumps(env_proxies, ensure_ascii=False), str(scutil)])
    local_proxy_detected = "127.0.0.1" in combined or "localhost" in combined
    clash_like_detected = any(port in combined for port in ("7890", "7897", "7891", "1080"))
    return {
        "status": "proxy_detected" if (urllib_proxies or env_proxies or scutil.get("enabled")) else "no_proxy",
        "urllib_proxies": urllib_proxies,
        "env_proxies": env_proxies,
        "macos_scutil_proxy": scutil,
        "local_proxy_detected": local_proxy_detected,
        "clash_like_detected": clash_like_detected,
        "message": "检测到代理配置。" if (urllib_proxies or env_proxies or scutil.get("enabled")) else "未检测到代理配置。",
    }


def diagnose_dns(hosts: tuple[str, ...] = EASTMONEY_HOSTS) -> dict[str, Any]:
    """Resolve A/AAAA addresses using Python socket APIs."""
    host_results: dict[str, Any] = {}
    ok = True
    for host in hosts:
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            host_results[host] = {"ok": False, "a_records": [], "aaaa_records": [], "error": str(exc)}
            ok = False
            continue
        a_records = sorted({item[4][0] for item in infos if item[0] == socket.AF_INET})
        aaaa_records = sorted({item[4][0] for item in infos if item[0] == socket.AF_INET6})
        host_results[host] = {"ok": bool(a_records or aaaa_records), "a_records": a_records, "aaaa_records": aaaa_records, "error": ""}
        ok = ok and bool(a_records or aaaa_records)
    return {"status": "ok" if ok else "failed", "hosts": host_results}


def run_eastmoney_request_tests(
    *,
    used_url: str,
    timeout_seconds: int,
    include_curl: bool,
    include_python: bool,
    proxies: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run Python and curl request variants against the concrete kline URL."""
    tests: list[dict[str, Any]] = []
    if include_python:
        tests.append(_run_python_request("python_default", used_url, timeout_seconds))
    if include_curl:
        tests.extend(
            [
                _run_curl_request("curl_default", used_url, timeout_seconds, extra_args=[]),
                _run_curl_request("curl_ipv4", used_url, timeout_seconds, extra_args=["-4"]),
                _run_curl_request("curl_ipv6", used_url, timeout_seconds, extra_args=["-6"]),
                _run_curl_request("curl_noproxy", used_url, timeout_seconds, extra_args=["--noproxy", "*"]),
            ]
        )
        if proxies.get("local_proxy_detected"):
            tests.append(_run_curl_request("curl_local_proxy_7897", used_url, timeout_seconds, extra_args=["-x", "http://127.0.0.1:7897"]))
    return tests


def _run_python_request(name: str, used_url: str, timeout_seconds: int) -> dict[str, Any]:
    started = time.monotonic()
    request = urllib.request.Request(
        used_url,
        headers={"User-Agent": EASTMONEY_USER_AGENT, "Referer": EASTMONEY_REFERER},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", None)
        return _request_result(name, True, time.monotonic() - started, stdout=body, http_status=status_code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return _request_result(name, False, time.monotonic() - started, stderr=str(exc), error_type=type(exc).__name__)


def _run_curl_request(name: str, used_url: str, timeout_seconds: int, *, extra_args: list[str]) -> dict[str, Any]:
    if shutil.which("curl") is None:
        return {"name": name, "executed": False, "success": False, "status": "unavailable", "reason": "curl unavailable"}
    started = time.monotonic()
    command = [
        "curl",
        *extra_args,
        "-sS",
        "-L",
        "--max-time",
        str(max(1, int(timeout_seconds))),
        "-w",
        "\nHTTP_STATUS:%{http_code}",
        "-A",
        EASTMONEY_USER_AGENT,
        "-H",
        f"Referer: {EASTMONEY_REFERER}",
        used_url,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout_seconds + 2)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _request_result(name, False, time.monotonic() - started, returncode=None, stderr=str(exc), error_type=type(exc).__name__)
    stdout, http_status = _split_curl_status(completed.stdout)
    return _request_result(
        name,
        completed.returncode == 0,
        time.monotonic() - started,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=completed.stderr,
        http_status=http_status,
    )


def _request_result(
    name: str,
    transport_ok: bool,
    elapsed_seconds: float,
    *,
    returncode: int | None = None,
    stdout: str = "",
    stderr: str = "",
    http_status: int | None = None,
    error_type: str = "",
) -> dict[str, Any]:
    parsed = _parse_eastmoney_payload(stdout)
    success = bool(transport_ok and parsed["ok"])
    return {
        "name": name,
        "executed": True,
        "success": success,
        "status": "success" if success else "failed",
        "returncode": returncode,
        "http_status": http_status,
        "contains_rc0": parsed["contains_rc0"],
        "kline_count": parsed["kline_count"],
        "response_preview": (stdout or "")[:200],
        "stderr": (stderr or "")[:500],
        "elapsed_seconds": round(elapsed_seconds, 3),
        "failure_category": "" if success else classify_request_failure(returncode=returncode, stderr=stderr, stdout=stdout, error_type=error_type),
    }


def _parse_eastmoney_payload(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": False, "contains_rc0": '"rc":0' in stdout or '"rc": 0' in stdout, "kline_count": 0}
    klines = ((payload.get("data") or {}).get("klines") or [])
    return {"ok": payload.get("rc") == 0 and bool(klines), "contains_rc0": payload.get("rc") == 0, "kline_count": len(klines)}


def classify_request_failure(*, returncode: int | None, stderr: str, stdout: str, error_type: str = "") -> str:
    text = f"{stderr}\n{stdout}\n{error_type}".lower()
    if returncode == 52 or "empty reply" in text or "remotedisconnected" in text:
        return "empty_reply"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "could not resolve" in text or "nodename nor servname" in text or "name or service" in text:
        return "dns"
    if "ssl" in text or "certificate" in text:
        return "ssl"
    if "proxy" in text:
        return "proxy"
    return "network_or_data_source"


def classify_diagnosis(*, duckdb: dict[str, Any], proxy: dict[str, Any], dns: dict[str, Any], request_tests: list[dict[str, Any]]) -> dict[str, str]:
    """Classify diagnostic results into a user-facing summary and suggested action."""
    if duckdb.get("locked"):
        return {
            "status": "failed",
            "eastmoney_status": "unknown",
            "summary": "DuckDB 被其他进程锁定，数据更新前需要先释放数据库。",
            "suggested_action": "停止其他 core.jobs 或 Streamlit 后重试；如为 FileProvider 占用，考虑迁移数据库到非同步目录。",
        }
    if dns.get("status") == "failed":
        return {
            "status": "failed",
            "eastmoney_status": "unknown",
            "summary": "DNS 解析失败，当前网络无法解析东方财富数据源域名。",
            "suggested_action": "检查 Wi-Fi DNS、系统代理或切换手机热点后重试。",
        }
    python_success = _is_success(request_tests, "python_default")
    curl_success = _is_success(request_tests, "curl_default")
    ipv4_success = _is_success(request_tests, "curl_ipv4")
    ipv6_success = _is_success(request_tests, "curl_ipv6")
    any_success = any(item.get("success") for item in request_tests)
    if any_success:
        if ipv4_success and not _test_executed_success_or_skip(request_tests, "curl_ipv6"):
            return {
                "status": "warning",
                "eastmoney_status": "partial",
                "summary": "东方财富接口可用，但 IPv6 或默认网络路径可能异常。",
                "suggested_action": "优先使用 IPv4 网络路径，检查 Wi-Fi IPv6 或 DNS 设置；自动更新前建议再次预检。",
            }
        if curl_success and not python_success:
            return {
                "status": "warning",
                "eastmoney_status": "partial",
                "summary": "curl 可访问东方财富接口，但 Python 请求失败，可能是 Python 代理、SSL 或 requests 环境问题。",
                "suggested_action": "检查 Python 代理环境变量、证书或 Clash 规则；批量更新会使用现有 fallback 路径。",
            }
        return {
            "status": "ok",
            "eastmoney_status": "ok",
            "summary": "数据源可用，东方财富 K 线接口返回有效数据。",
            "suggested_action": "可以继续执行数据更新；全市场更新仍建议先小批量运行。",
        }
    proxy_hint = "，且检测到代理配置" if proxy.get("status") == "proxy_detected" else ""
    return {
        "status": "failed",
        "eastmoney_status": "failed",
        "summary": f"curl 和 Python 请求均未能访问东方财富 K 线接口{proxy_hint}，当前网络或数据源不可用。",
        "suggested_action": "建议切换手机热点后重试；同时检查 Clash / 系统代理、Wi-Fi DNS 和 IPv6 设置。",
    }


def format_diagnosis_text(result: dict[str, Any]) -> str:
    """Format diagnostic result as concise human-readable text."""
    tests = {item.get("name"): item for item in result.get("eastmoney", {}).get("tests", [])}
    lines = [
        "数据源网络诊断",
        f"- 整体状态: {result.get('status')}",
        f"- 主要结论: {result.get('summary')}",
        f"- DuckDB: {result.get('duckdb', {}).get('message')}",
        f"- Python 代理: {result.get('proxy', {}).get('message')}",
        f"- DNS: {result.get('dns_status')}",
        f"- 东方财富接口: {result.get('eastmoney_status')}",
        f"- used_url: {result.get('eastmoney', {}).get('used_url')}",
    ]
    for name, label in [
        ("python_default", "Python 默认请求"),
        ("curl_default", "curl 默认请求"),
        ("curl_ipv4", "curl IPv4"),
        ("curl_ipv6", "curl IPv6"),
        ("curl_noproxy", "curl 直连"),
    ]:
        item = tests.get(name, {})
        if not item:
            continue
        lines.append(
            f"- {label}: {item.get('status')}, returncode={item.get('returncode')}, "
            f"http_status={item.get('http_status')}, reason={item.get('failure_category') or 'ok'}"
        )
    lines.append("- 建议:")
    lines.append(f"  1. {result.get('suggested_action')}")
    lines.append("  2. 若 Wi-Fi 失败，请切换手机热点后再次运行诊断。")
    lines.append("  3. 自动更新任务在当前网络不稳定时可能失败。")
    return "\n".join(lines)


def _split_curl_status(stdout: str) -> tuple[str, int | None]:
    marker = "\nHTTP_STATUS:"
    if marker not in stdout:
        return stdout, None
    body, status_text = stdout.rsplit(marker, 1)
    try:
        return body, int(status_text.strip())
    except ValueError:
        return body, None


def _scutil_proxy() -> dict[str, Any]:
    if shutil.which("scutil") is None:
        return {"available": False, "enabled": False, "raw": ""}
    try:
        completed = subprocess.run(["scutil", "--proxy"], capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "enabled": False, "raw": ""}
    raw = _mask_value(completed.stdout[:2000])
    enabled = "Enable : 1" in completed.stdout
    return {"available": True, "enabled": enabled, "raw": raw}


def _test_status(tests: list[dict[str, Any]], name: str) -> str:
    for item in tests:
        if item.get("name") == name:
            return str(item.get("status"))
    return "skipped"


def _is_success(tests: list[dict[str, Any]], name: str) -> bool:
    return any(item.get("name") == name and item.get("success") for item in tests)


def _test_executed_success_or_skip(tests: list[dict[str, Any]], name: str) -> bool:
    matching = [item for item in tests if item.get("name") == name]
    if not matching:
        return True
    return bool(matching[0].get("success"))


def _mask_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _mask_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    if not isinstance(value, str):
        return value
    masked = value
    if "@" in masked and "://" in masked:
        scheme, rest = masked.split("://", 1)
        if "@" in rest:
            masked = f"{scheme}://***@{rest.split('@', 1)[1]}"
    for marker in SENSITIVE_MARKERS:
        lower = masked.lower()
        idx = lower.find(marker)
        if idx >= 0:
            masked = masked[: idx + len(marker)] + "***"
    return masked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose data source network connectivity.")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--output", default=None)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--include-curl", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-python", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-dns", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    diagnose_data_source_network(
        output_format=args.format,
        output_path=args.output,
        timeout_seconds=args.timeout,
        include_curl=args.include_curl,
        include_python=args.include_python,
        include_dns=args.include_dns,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
