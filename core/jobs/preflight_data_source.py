"""Preflight local data source connectivity before full batch updates."""

from __future__ import annotations

import argparse
from typing import Any

from core.runtime.data_source_preflight import run_data_source_preflight


def preflight_data_source(*, skip_network: bool = False, timeout_seconds: int = 8, quiet: bool = False) -> dict[str, Any]:
    """Run datasource preflight checks without writing local data."""
    result = run_data_source_preflight(skip_network=skip_network, timeout_seconds=timeout_seconds)
    if not quiet:
        print(_summary(result))
    return result


def _summary(result: dict[str, Any]) -> str:
    proxy = result.get("proxy", {})
    duckdb = result.get("duckdb", {})
    eastmoney = result.get("eastmoney_kline", {})
    lines = [
        "数据源预检摘要",
        f"- 状态: {result.get('status')}",
        f"- DuckDB: {duckdb.get('message')}",
        f"- 代理状态: {proxy.get('message')}",
        f"- 东方财富 K 线接口: {eastmoney.get('message')}",
    ]
    if proxy.get("has_proxy"):
        lines.append(f"- urllib proxies: {proxy.get('proxies')}")
    if duckdb.get("holders"):
        lines.append(f"- DuckDB 占用进程: {duckdb.get('holders')}")
    suggestions = result.get("suggestions") or []
    if suggestions:
        lines.append("- 建议:")
        lines.extend(f"  {item}" for item in suggestions)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Preflight data source connectivity.")
    parser.add_argument("--skip-network", action="store_true", help="Skip Eastmoney network probe.")
    parser.add_argument("--timeout-seconds", type=int, default=8)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    result = preflight_data_source(skip_network=args.skip_network, timeout_seconds=args.timeout_seconds, quiet=args.quiet)
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
