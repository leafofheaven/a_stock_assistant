"""Tests for v0.1 release notes and daily-use handbook."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v0_1_docs_exist() -> None:
    """v0.1 release documents should exist."""
    assert (ROOT / "docs/v0_1_release_notes.md").exists()
    assert (ROOT / "docs/v0_1_handbook.md").exists()


def test_readme_contains_core_v0_1_entrypoints() -> None:
    """README should stay concise while linking to v0.1 usage paths."""
    readme = _read("README.md")
    for phrase in [
        "v0.1",
        "run_daily_workflow",
        "doctor_daily_run",
        "docs/v0_1_handbook.md",
        "docs/v0_1_release_notes.md",
        "reports/",
    ]:
        assert phrase in readme


def test_handbook_contains_recommended_daily_commands() -> None:
    """Handbook should provide copyable daily workflow commands."""
    handbook = _read("docs/v0_1_handbook.md")
    for command in [
        "cd /Users/wanghao/Documents/股票",
        "source .venv/bin/activate",
        "python -m core.jobs.doctor_daily_run --pre-run",
        "python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all",
        "python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all",
        "python -m core.jobs.export_review_template --top-n 10",
        "python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv",
        "python -m core.jobs.refresh_watchlist_scores",
        "python -m core.jobs.backup_local_data --label before_change",
        "python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --dry-run",
        "python -m core.jobs.clean_generated_reports --force",
    ]:
        assert command in handbook


def test_release_notes_include_current_limits() -> None:
    """Release notes should document v0.1 limits and optional tag steps."""
    notes = _read("docs/v0_1_release_notes.md")
    for phrase in [
        "v0.1 本地日常使用版",
        "不自动交易",
        "不接券商",
        "PE/PB 当前优先补最新交易日",
        "AKShare / 东方财富接口可能",
        "adj_factor",
        "git tag v0.1",
    ]:
        assert phrase in notes


def test_commands_reference_contains_core_commands() -> None:
    """Command reference should include all v0.1 daily-use commands."""
    commands = _read("docs/commands_reference.md")
    for command in [
        "python -m core.jobs.doctor_daily_run",
        "python -m core.jobs.run_daily_workflow",
        "python -m core.jobs.update_real_data",
        "python -m core.jobs.diagnose_data_quality",
        "python -m core.jobs.diagnose_factors",
        "python -m core.jobs.run_daily_selection",
        "python -m core.jobs.export_selection_review",
        "python -m core.jobs.export_review_template",
        "python -m core.jobs.import_review_decisions",
        "python -m core.jobs.refresh_watchlist_scores",
        "python -m core.jobs.diagnose_watchlist",
        "python -m core.jobs.export_watchlist",
        "python -m core.jobs.track_watchlist",
        "python -m core.jobs.export_watchlist_tracking_report",
        "python -m core.jobs.backup_local_data",
        "python -m core.jobs.list_backups",
        "python -m core.jobs.restore_local_data",
        "python -m core.jobs.clean_generated_reports",
        "streamlit run web/streamlit_app.py",
    ]:
        assert command in commands


def test_docs_warn_not_to_commit_local_generated_files() -> None:
    """Docs should tell users not to commit local generated files."""
    combined = "\n".join(
        [
            _read("README.md"),
            _read("docs/v0_1_handbook.md"),
            _read("docs/v0_1_release_notes.md"),
        ]
    )
    for phrase in ["不提交 data/", "不提交 backups/", "不提交 .env", "reports/.gitkeep"]:
        assert phrase in combined
