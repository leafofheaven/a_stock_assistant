"""Preflight checks for local full-universe data updates."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from app.config import Settings, get_settings
from core.storage.duckdb_store import DUCKDB_LOCK_MESSAGE, is_duckdb_lock_error

EASTMONEY_KLINE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid=0.000001&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116"
    "&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=1&beg=20240101&end={end_date}"
)
EASTMONEY_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
EASTMONEY_REFERER = "https://quote.eastmoney.com/"
EASTMONEY_UNAVAILABLE_MESSAGE = "东方财富 K 线接口当前不可用，请检查网络、系统代理或稍后再试。本次未启动批量更新。"
DUCKDB_LOCK_USER_MESSAGE = "DuckDB is locked by another process. Please stop other running jobs or Streamlit first."


def run_data_source_preflight(
    *,
    settings: Settings | None = None,
    skip_network: bool = False,
    timeout_seconds: int = 8,
) -> dict[str, Any]:
    """Check DuckDB lock state, local proxy settings, and Eastmoney kline availability."""
    resolved_settings = settings or get_settings()
    duckdb_result = check_duckdb_access(Path(resolved_settings.duckdb_path))
    proxy_result = detect_proxy_settings()
    eastmoney_result = (
        {"status": "skipped", "ok": True, "message": "已跳过网络连通性测试。"}
        if skip_network
        else check_eastmoney_kline(timeout_seconds=timeout_seconds)
    )
    ok = bool(duckdb_result["ok"] and eastmoney_result["ok"])
    suggestions = []
    if not duckdb_result["ok"]:
        suggestions.extend(duckdb_result.get("suggestions", []))
    if not eastmoney_result["ok"]:
        suggestions.extend(
            [
                "检查 Clash / macOS 系统代理是否影响 Python 或 curl 访问。",
                "稍后重试，或先用命令行 curl 验证 push2his.eastmoney.com K 线接口。",
            ]
        )
    if proxy_result["has_proxy"]:
        suggestions.append("检测到系统代理；如 AKShare / 东方财富失败，请检查 Clash 规则或临时关闭代理。")
    return {
        "status": "success" if ok else "failed",
        "ok": ok,
        "duckdb": duckdb_result,
        "proxy": proxy_result,
        "eastmoney_kline": eastmoney_result,
        "message": "数据源预检通过。" if ok else EASTMONEY_UNAVAILABLE_MESSAGE,
        "suggestions": suggestions,
    }


def detect_proxy_settings() -> dict[str, Any]:
    """Return Python urllib proxy settings without performing network requests."""
    proxies = urllib.request.getproxies()
    env_proxies = {
        key: value
        for key, value in os.environ.items()
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    has_proxy = bool(proxies or env_proxies)
    return {
        "has_proxy": has_proxy,
        "proxies": proxies,
        "env_proxies": env_proxies,
        "message": "检测到系统代理配置。" if has_proxy else "未检测到 Python urllib 代理配置。",
    }


def check_duckdb_access(db_path: Path) -> dict[str, Any]:
    """Check whether DuckDB can be opened read-only and whether FileProvider may hold it."""
    holders = _duckdb_holders(db_path)
    if not db_path.exists():
        return {
            "ok": True,
            "exists": False,
            "locked": False,
            "holders": holders,
            "message": "DuckDB 文件不存在，首次更新会创建。",
            "suggestions": [],
        }
    try:
        with duckdb.connect(str(db_path), read_only=True):
            pass
        fileprovider_holders = [
            item for item in holders if "fileprovi" in item.get("command", "").lower() or "fileprovider" in item.get("command", "").lower()
        ]
        suggestions = []
        if fileprovider_holders:
            suggestions.append("DuckDB may be locked by macOS FileProvider or cloud sync. Consider moving the database to a non-synced local directory.")
        return {
            "ok": True,
            "exists": True,
            "locked": False,
            "holders": holders,
            "fileprovider_holders": fileprovider_holders,
            "message": "DuckDB read_only 可访问。",
            "suggestions": suggestions,
        }
    except Exception as exc:
        locked = is_duckdb_lock_error(exc)
        message = DUCKDB_LOCK_MESSAGE if locked else str(exc)
        return {
            "ok": False,
            "exists": True,
            "locked": locked,
            "holders": holders,
            "message": message,
            "suggestions": [
                "停止其他正在运行的 core.jobs 或 Streamlit。",
                "运行 lsof data/a_stock_assistant.duckdb 查看占用进程。",
            ],
        }


def check_eastmoney_kline(*, timeout_seconds: int = 8) -> dict[str, Any]:
    """Call the concrete Eastmoney kline API through system curl and validate klines."""
    used_url = EASTMONEY_KLINE_URL.format(end_date=date.today().strftime("%Y%m%d"))
    command = [
        "curl",
        "-sSL",
        "--max-time",
        str(max(1, int(timeout_seconds))),
        "-A",
        EASTMONEY_USER_AGENT,
        "-H",
        f"Referer: {EASTMONEY_REFERER}",
        used_url,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout_seconds + 2)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _eastmoney_failure(
            used_url=used_url,
            curl_returncode=None,
            stderr=str(exc),
            message=f"{EASTMONEY_UNAVAILABLE_MESSAGE} error={type(exc).__name__}: {exc}",
        )
    if completed.returncode != 0:
        return _eastmoney_failure(
            used_url=used_url,
            curl_returncode=completed.returncode,
            stderr=completed.stderr,
            message=f"{EASTMONEY_UNAVAILABLE_MESSAGE} curl_returncode={completed.returncode}",
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return _eastmoney_failure(
            used_url=used_url,
            curl_returncode=completed.returncode,
            stderr=completed.stderr,
            message=f"{EASTMONEY_UNAVAILABLE_MESSAGE} JSON 解析失败：{exc}",
        )
    klines = ((payload.get("data") or {}).get("klines") or [])
    ok = payload.get("rc") == 0 and bool(klines)
    return {
        "status": "success" if ok else "failed",
        "ok": ok,
        "message": f"东方财富 K 线接口可用，返回 {len(klines)} 行。" if ok else EASTMONEY_UNAVAILABLE_MESSAGE,
        "kline_count": len(klines),
        "rc": payload.get("rc"),
        "used_url": used_url,
        "headers_present": {"user_agent": True, "referer": True},
    }


def _eastmoney_failure(
    *,
    used_url: str,
    curl_returncode: int | None,
    stderr: str,
    message: str,
) -> dict[str, Any]:
    """Build a detailed but concise Eastmoney preflight failure result."""
    return {
        "status": "failed",
        "ok": False,
        "message": message,
        "used_url": used_url,
        "curl_returncode": curl_returncode,
        "stderr": (stderr or "").strip()[:500],
        "headers_present": {"user_agent": True, "referer": True},
    }


def _duckdb_holders(db_path: Path) -> list[dict[str, str]]:
    if not db_path.exists():
        return []
    try:
        result = subprocess.run(["lsof", str(db_path)], text=True, capture_output=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    holders: list[dict[str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        holders.append({"command": parts[0], "pid": parts[1], "raw": line})
    return holders
