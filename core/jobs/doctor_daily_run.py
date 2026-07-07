"""Daily run environment doctor and safe recovery helpers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

from app.config import Settings, get_settings
from core.diagnostics.data_quality_snapshot import build_data_quality_snapshot
from core.data_sources.real_universe import is_full_universe_preset
from core.jobs.diagnose_data_quality import diagnose_data_quality
from core.jobs.local_backup_utils import PROJECT_ROOT, tracked_local_data_paths
from core.jobs.missing_latest_retry_queue import DEFAULT_SKIP_QUEUE_PATH, queue_counts
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError

CORE_TABLES = [
    "stock_basic",
    "daily_price",
    "daily_basic",
    "factor_scores",
    "review_decisions",
    "watchlist_snapshots",
]
GENERATED_REPORT_SUFFIXES = {".md", ".json", ".csv"}


def doctor_daily_run(
    *,
    fix_safe: bool = False,
    pre_run: bool = False,
    post_run: bool = False,
    as_json: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Run local daily-use checks and optionally apply safe non-data fixes."""
    resolved_root = Path(root) if root is not None else PROJECT_ROOT
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    fixes = _apply_safe_fixes(resolved_root, resolved_store, fix_safe)
    checks = _build_checks(resolved_root, resolved_settings, resolved_store, pre_run=pre_run, post_run=post_run)
    status = _overall_status(checks)
    result = {
        "status": status,
        "mode": "pre_run" if pre_run else "post_run" if post_run else "default",
        "fix_safe": fix_safe,
        "root": str(resolved_root),
        "checks": checks,
        "summary": _summary(checks),
        "fixes": fixes,
        "next_steps": _next_steps(checks),
    }
    if as_json:
        result["json"] = json.dumps(result, ensure_ascii=False, indent=2)
    return result


def main(argv: list[str] | None = None) -> None:
    """Parse command line arguments and print a daily doctor report."""
    parser = argparse.ArgumentParser(description="Check local daily workflow stability and recovery hints.")
    parser.add_argument("--fix-safe", action="store_true", help="Create missing safe local folders/files.")
    parser.add_argument("--pre-run", action="store_true", help="Run before daily workflow.")
    parser.add_argument("--post-run", action="store_true", help="Run after daily workflow.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args(argv)
    result = doctor_daily_run(
        fix_safe=args.fix_safe,
        pre_run=args.pre_run,
        post_run=args.post_run,
        as_json=args.json,
    )
    if args.json:
        print(result["json"])
    else:
        print(render_console(result))


def render_console(result: dict[str, Any]) -> str:
    """Render a readable console summary."""
    lines = [
        "日常运行体检",
        f"- 整体状态: {result['status']}",
        f"- 模式: {result['mode']}",
        f"- 安全修复: {'已启用' if result['fix_safe'] else '未启用'}",
        "- 检查项:",
    ]
    for item in result["checks"]:
        lines.append(f"  [{item['status']}] {item['name']}: {item['message']}")
        if item.get("status") != "OK" and item.get("recommendation"):
            lines.append(f"    建议: {item['recommendation']}")
    if result.get("fixes"):
        lines.append("- 修复摘要:")
        for fix in result["fixes"]:
            lines.append(f"  {fix}")
    lines.append("- 下一步建议:")
    for step in result["next_steps"]:
        lines.append(f"  {step}")
    return "\n".join(lines)


def _build_checks(
    root: Path,
    settings: Settings,
    store: DuckDBStore,
    *,
    pre_run: bool,
    post_run: bool,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    branch = _git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    status_short = _git(root, ["status", "--short"])
    tracked = tracked_local_data_paths() if root.resolve() == PROJECT_ROOT.resolve() else _tracked_local_data_paths(root)
    reports_dir = root / "reports"
    backups_dir = root / "backups"
    data_dir = _resolve(root, settings.data_dir)
    db_path = _resolve(root, store.db_path)

    checks.append(_check("git_branch", "OK" if branch == "main" or branch.startswith("task-") or branch.startswith("fix-") else "WARNING", branch or "无法读取当前分支。", "确认当前在 main 或任务分支上运行。"))
    checks.append(_check("git_status", "OK" if not status_short else "WARNING", "工作区干净。" if not status_short else "工作区存在未提交改动。", "提交或确认这些改动不影响日常运行。"))
    checks.append(_check(".env", "OK" if (root / ".env").exists() else "WARNING", ".env 已存在。" if (root / ".env").exists() else ".env 不存在。", "cp .env.example .env 后按需填写配置。"))
    checks.append(_check("data_provider", "OK" if settings.data_provider in {"sample", "tushare", "akshare"} else "FAILED", f"DATA_PROVIDER={settings.data_provider}", "设置 DATA_PROVIDER=sample/tushare/akshare。"))
    has_real_universe = bool(settings.akshare_symbols or settings.sample_symbols or is_full_universe_preset(settings.real_universe_preset))
    checks.append(_check("real_symbols", "OK" if has_real_universe else "WARNING", f"AKSHARE_SAMPLE_SYMBOLS={settings.akshare_sample_symbols or '空'}; REAL_UNIVERSE_PRESET={settings.real_universe_preset}", "确认样本股票或预设样本已配置。"))
    checks.append(_check("enrichment_flags", "OK", f"ENABLE_REAL_BASIC_ENRICHMENT={settings.enable_real_basic_enrichment}; ENABLE_REAL_VALUATION_ENRICHMENT={settings.enable_real_valuation_enrichment}", "无需处理。"))
    checks.append(_check("data_dir", "OK" if data_dir.exists() else "WARNING", f"DATA_DIR={data_dir}; {'存在' if data_dir.exists() else '不存在'}", "python -m core.jobs.doctor_daily_run --fix-safe"))
    checks.append(_check("duckdb_path", "OK" if db_path.exists() else "FAILED", f"DUCKDB_PATH={db_path}; {'存在' if db_path.exists() else '不存在'}", "python -m core.jobs.update_real_data 或 python -m core.jobs.restore_local_data"))
    checks.append(_fileprovider_path_check(db_path))
    checks.extend(_table_checks(store, db_path))
    checks.extend(_quality_checks(settings, store, db_path))
    checks.append(_check("reports_gitkeep", "OK" if (reports_dir / ".gitkeep").exists() else "WARNING", "reports/.gitkeep 已存在。" if (reports_dir / ".gitkeep").exists() else "reports/.gitkeep 缺失。", "python -m core.jobs.doctor_daily_run --fix-safe"))
    checks.append(_check("report_count", "OK", f"reports 生成文件数量: {_generated_report_count(reports_dir)}", "python -m core.jobs.clean_generated_reports --force"))
    latest_backup = _latest_path(backups_dir, "a_stock_backup_*")
    backup_status = "OK" if latest_backup else "WARNING"
    checks.append(_check("backups", backup_status, f"backups 数量: {_backup_count(backups_dir)}; 最近备份: {latest_backup or '暂无'}", "python -m core.jobs.backup_local_data --label before_change"))
    checks.append(_check("latest_daily_workflow_report", "OK" if _latest_path(reports_dir, "daily_workflow_*.json") else ("WARNING" if post_run else "OK"), f"最近日报: {_latest_path(reports_dir, 'daily_workflow_*.json') or '暂无'}", "python -m core.jobs.run_daily_workflow --skip-update --format all"))
    checks.append(_check("latest_selection_review_report", "OK" if _latest_path(reports_dir, "selection_review_*.json") else "WARNING", f"最近候选复核报告: {_latest_path(reports_dir, 'selection_review_*.json') or '暂无'}", "python -m core.jobs.export_selection_review --top-n 10 --format all"))
    checks.append(_check("latest_watchlist_report", "OK" if _latest_path(reports_dir, "watchlist_[0-9]*.json") else "WARNING", f"最近观察池报告: {_latest_path(reports_dir, 'watchlist_[0-9]*.json') or '暂无'}", "python -m core.jobs.export_watchlist --format all"))
    checks.append(_check("tracked_local_paths", "FAILED" if _bad_tracked_paths(tracked) else "OK", f"被 Git 跟踪的本地生成路径: {', '.join(tracked) if tracked else '无'}", "从 Git 中移除 reports/data/backups/.env 生成文件，仅保留 reports/.gitkeep。"))
    return checks


def _table_checks(store: DuckDBStore, db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return [_check(f"table_{table}", "FAILED", f"{table}: DuckDB 不存在，无法检查表。", "python -m core.jobs.update_real_data") for table in CORE_TABLES]
    checks: list[dict[str, Any]] = []
    existing = _existing_tables(store)
    for table in CORE_TABLES:
        checks.append(_check(f"table_{table}", "OK" if table in existing else "FAILED", f"{table}: {'存在' if table in existing else '缺失'}", "python -m core.jobs.update_real_data"))
    return checks


def _quality_checks(settings: Settings, store: DuckDBStore, db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return [
            _check("latest_trade_date", "FAILED", "DuckDB 不存在，无法读取最新行情日期。", "python -m core.jobs.update_real_data"),
            _check("latest_pe_pb", "FAILED", "DuckDB 不存在，无法读取最新交易日 PE/PB 完整率。", "python -m core.jobs.update_real_data"),
            _check("sample_fallback_risk", "WARNING", "本地真实数据不可用，run_daily_selection 可能回退 sample。", "先运行 update_real_data 或 restore_local_data。"),
        ]
    result = diagnose_data_quality(settings=settings, store=store)
    snapshot = _safe_quality_snapshot(store)
    latest_date = result.get("latest_trade_date")
    pe_rate = float(result.get("latest_date_pe_non_null_rate") or 0.0)
    pb_rate = float(result.get("latest_date_pb_non_null_rate") or 0.0)
    enough = bool(latest_date and int(result.get("latest_date_stock_count") or 0) > 0)
    checks = [
        _check("latest_trade_date", "OK" if latest_date else "WARNING", f"最新行情日期: {latest_date or '暂无'}", "python -m core.jobs.update_real_data"),
        _check("latest_pe_pb", "OK" if pe_rate > 0 and pb_rate > 0 else "WARNING", f"最新交易日 PE/PB 完整率: {pe_rate:.2%} / {pb_rate:.2%}", "python -m core.jobs.diagnose_data_quality"),
        _check("sample_fallback_risk", "OK" if enough and settings.data_provider != "sample" else "WARNING", "真实数据链路具备本地数据。" if enough else "真实数据不足，run_daily_selection 可能回退 sample。", "python -m core.jobs.update_real_data"),
    ]
    if snapshot:
        configured = int(snapshot.get("configured_symbol_count", 0) or 0)
        price_count = int(snapshot.get("latest_daily_price_symbol_count", 0) or 0)
        basic_count = int(snapshot.get("latest_daily_basic_symbol_count", 0) or 0)
        missing_price = int(snapshot.get("missing_latest_daily_price_symbol_count", 0) or 0)
        queue = queue_counts(DEFAULT_SKIP_QUEUE_PATH, trade_date=str(snapshot.get("latest_completed_trade_date") or latest_date or ""))
        examples = ", ".join(str(item) for item in list(snapshot.get("missing_latest_daily_price_examples") or [])[:8])
        checks.append(
            _check(
                "latest_coverage_counts",
                "OK" if configured and price_count >= configured else "WARNING",
                (
                    f"最新交易日: {snapshot.get('latest_completed_trade_date') or latest_date or '暂无'}; "
                    f"股票池总数: {configured}; "
                    f"daily_price 覆盖数: {price_count} / {configured}; "
                    f"daily_basic 覆盖数: {basic_count} / {configured}; "
                    f"缺口数量: {missing_price}; "
                    f"本轮 no_data 冷却队列: {queue.get('skip_queue_count', 0)}; "
                    f"待 retry 队列: {queue.get('retry_queue_count', 0)}; "
                    f"缺口示例: {examples or '暂无'}"
                ),
                "python -m core.jobs.update_market_data --goal latest --provider baostock --batch-size 100 --continue-missing-latest --format text",
            )
        )
    return checks


def _safe_quality_snapshot(store: DuckDBStore) -> dict[str, Any]:
    try:
        return build_data_quality_snapshot(db_path=store.db_path)
    except Exception:
        return {}


def _fileprovider_path_check(db_path: Path) -> dict[str, Any]:
    text = str(db_path.expanduser())
    risky_markers = ["/Documents/", "/Desktop/", "Mobile Documents", "iCloud"]
    risky = any(marker in text for marker in risky_markers)
    return _check(
        "duckdb_fileprovider_risk",
        "WARNING" if risky else "OK",
        "DuckDB 位于可能被 macOS FileProvider / 云同步扫描的目录。" if risky else "DuckDB 路径未发现明显 FileProvider 风险。",
        "建议迁移到 ~/.local/share/a_stock_assistant/data/a_stock_assistant.duckdb；不要在未确认前自动移动数据库。",
    )


def _apply_safe_fixes(root: Path, store: DuckDBStore, enabled: bool) -> list[str]:
    if not enabled:
        return []
    fixes: list[str] = []
    for directory in [root / "reports", root / "backups", root / "data"]:
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            fixes.append(f"已创建 {directory}")
    gitkeep = root / "reports" / ".gitkeep"
    if not gitkeep.exists():
        if "reports/.gitkeep" in _tracked_local_data_paths(root):
            _git(root, ["restore", "reports/.gitkeep"])
        if not gitkeep.exists():
            gitkeep.parent.mkdir(parents=True, exist_ok=True)
            gitkeep.write_text("", encoding="utf-8")
        fixes.append("已恢复 reports/.gitkeep")
    if Path(store.db_path).exists():
        fixes.append("DuckDB 已保留，未删除或覆盖。")
    return fixes


def _existing_tables(store: DuckDBStore) -> set[str]:
    try:
        with store.connect() as connection:
            rows = connection.execute("SHOW TABLES").fetchall()
    except Exception:
        return set()
    return {str(row[0]) for row in rows}


def _check(name: str, status: str, message: str, recommendation: str = "") -> dict[str, str]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "recommendation": recommendation,
    }


def _overall_status(checks: list[dict[str, Any]]) -> str:
    if any(item["status"] == "FAILED" for item in checks):
        return "failed"
    if any(item["status"] == "WARNING" for item in checks):
        return "warning"
    return "success"


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "ok": sum(1 for item in checks if item["status"] == "OK"),
        "warning": sum(1 for item in checks if item["status"] == "WARNING"),
        "failed": sum(1 for item in checks if item["status"] == "FAILED"),
    }


def _next_steps(checks: list[dict[str, Any]]) -> list[str]:
    failed = [item["recommendation"] for item in checks if item["status"] == "FAILED" and item.get("recommendation")]
    warning = [item["recommendation"] for item in checks if item["status"] == "WARNING" and item.get("recommendation")]
    steps = list(dict.fromkeys([*failed, *warning]))
    return steps[:8] if steps else ["python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all"]


def _resolve(root: Path, path: Path | str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _generated_report_count(report_dir: Path) -> int:
    if not report_dir.exists():
        return 0
    return sum(1 for path in report_dir.iterdir() if path.is_file() and path.suffix in GENERATED_REPORT_SUFFIXES)


def _backup_count(backups_dir: Path) -> int:
    if not backups_dir.exists():
        return 0
    return sum(1 for path in backups_dir.glob("a_stock_backup_*") if path.is_dir())


def _latest_path(directory: Path, pattern: str) -> str:
    if not directory.exists():
        return ""
    matches = [path for path in directory.glob(pattern) if path.exists()]
    if not matches:
        return ""
    return str(max(matches, key=lambda path: path.stat().st_mtime))


def _bad_tracked_paths(paths: list[str]) -> list[str]:
    return [path for path in paths if path != "reports/.gitkeep"]


def _tracked_local_data_paths(root: Path) -> list[str]:
    output = _git(root, ["ls-files", "data", "reports", "backups", ".env"])
    return [line for line in output.splitlines() if line.strip()]


def _git(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


if __name__ == "__main__":
    main()
