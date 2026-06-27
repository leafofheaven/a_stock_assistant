"""Tests for project documentation and usage guide."""

from __future__ import annotations

from pathlib import Path


DOCS = [
    Path("docs/usage_guide.md"),
    Path("docs/commands_reference.md"),
    Path("docs/daily_workflow.md"),
    Path("docs/troubleshooting.md"),
    Path("docs/data_and_backup.md"),
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_docs_files_exist() -> None:
    """Required docs files should exist."""
    for path in DOCS:
        assert path.exists(), f"Missing {path}"


def test_readme_contains_key_entrypoints() -> None:
    """README should stay concise and link to docs."""
    readme = _read(Path("README.md"))

    assert "个人本地 A 股选股辅助工具" in readme
    assert "python -m core.jobs.run_real_workflow" in readme
    assert "streamlit run web/streamlit_app.py" in readme
    assert "docs/usage_guide.md" in readme
    assert "docs/commands_reference.md" in readme
    assert "docs/daily_workflow.md" in readme
    assert "docs/troubleshooting.md" in readme
    assert "docs/data_and_backup.md" in readme


def test_commands_reference_contains_core_commands() -> None:
    """commands_reference should include all user-facing commands."""
    commands = _read(Path("docs/commands_reference.md"))
    required = [
        "python -m core.jobs.update_real_data",
        "python -m core.jobs.diagnose_real_data",
        "python -m core.jobs.diagnose_update_batch",
        "python -m core.jobs.diagnose_factors",
        "python -m core.jobs.run_daily_selection",
        "python -m core.jobs.diagnose_backtest",
        "python -m core.jobs.run_real_workflow",
        "python -m core.jobs.export_selection_review",
        "python -m core.jobs.export_review_template",
        "python -m core.jobs.import_review_decisions",
        "python -m core.jobs.diagnose_watchlist",
        "python -m core.jobs.export_watchlist",
        "python -m core.jobs.track_watchlist",
        "python -m core.jobs.export_watchlist_tracking_report",
        "python -m core.jobs.update_review_decision",
        "python -m core.jobs.diagnose_review_history",
        "python -m core.jobs.diagnose_local_state",
        "python -m core.jobs.backup_local_data",
        "python -m core.jobs.list_backups",
        "python -m core.jobs.restore_local_data",
        "python -m core.jobs.clean_generated_reports",
        "streamlit run web/streamlit_app.py",
    ]

    for command in required:
        assert command in commands


def test_troubleshooting_contains_common_problem_keywords() -> None:
    """troubleshooting should cover common local workflow issues."""
    content = _read(Path("docs/troubleshooting.md"))
    for phrase in [
        ".env 不存在",
        "DATA_PROVIDER 仍然是 tushare",
        "TUSHARE_TOKEN 为空",
        "AKShare 请求失败",
        "东方财富接口走代理失败",
        "Clash Verge",
        "daily_price 为 0",
        "run_daily_selection 回退 sample",
        "股票池过滤为空",
        "pe/pb 为空",
        "total_score=None",
        "reports/ 或 backups/ 出现在 git status",
        "误把占位符命令粘进终端",
        "GitHub 没有可合并 PR",
        "Codex 改完但没有 commit",
        "分支错乱",
        "Numbers 保存 CSV",
        "restore_local_data 没有 --force 不会恢复",
    ]:
        assert phrase in content


def test_data_and_backup_contains_backup_restore_commands() -> None:
    """data_and_backup should include backup and restore commands."""
    content = _read(Path("docs/data_and_backup.md"))
    for phrase in [
        "python -m core.jobs.diagnose_local_state",
        "python -m core.jobs.backup_local_data --label before_change",
        "python -m core.jobs.list_backups",
        "python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --dry-run",
        "python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --force",
        "python -m core.jobs.clean_generated_reports --dry-run",
        "python -m core.jobs.clean_generated_reports --force",
        "git status",
    ]:
        assert phrase in content


def test_docs_do_not_instruct_committing_local_data() -> None:
    """Docs should not ask users to commit local generated or secret paths."""
    combined = "\n".join(_read(path) for path in [Path("README.md"), *DOCS])
    forbidden = [
        "git add data",
        "git add reports",
        "git add backups",
        "git add .env",
        "提交 data/",
        "提交 reports/",
        "提交 backups/",
        "提交 .env",
    ]

    for phrase in forbidden:
        assert phrase not in combined


def test_sample_smoke_support_remains_available() -> None:
    """sample smoke test support should remain available."""
    from core.sample_data import get_sample_dashboard_data

    sample = get_sample_dashboard_data()

    assert not sample["selection"].empty
