"""Tests for repository quality check scripts."""

from __future__ import annotations

from pathlib import Path

from scripts.check_project import run_checks
from scripts.check_task import run_task_check


def test_project_check_passes_current_repository() -> None:
    """Current repository should pass project quality checks."""
    assert run_checks(Path.cwd()) == []


def test_project_check_rejects_forbidden_tracked_files(tmp_path: Path) -> None:
    """Project checks should catch forbidden committed files."""
    (tmp_path / "PROJECT_SPEC.md").write_text("spec", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "core").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".env").write_text("TUSHARE_TOKEN=secret", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"cache")

    failures = run_checks(tmp_path)

    assert any("Do not commit .env" in failure for failure in failures)
    assert any("__pycache__" in failure for failure in failures)
    assert any(".pyc" in failure for failure in failures)


def test_project_check_rejects_real_api_imports_in_tests(tmp_path: Path) -> None:
    """Tests must not import real Tushare or AKShare packages."""
    (tmp_path / "PROJECT_SPEC.md").write_text("spec", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "core").mkdir()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_external.py").write_text("import " + "tushare as ts\n", encoding="utf-8")

    failures = run_checks(tmp_path)

    assert any("real external API" in failure for failure in failures)


def test_project_check_rejects_hardcoded_tushare_token(tmp_path: Path) -> None:
    """Project checks should catch token-like hardcoded Tushare values."""
    (tmp_path / "PROJECT_SPEC.md").write_text("spec", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "core").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "settings.py").write_text(
        'tushare_token = "' + "abcdefghijklmnopqrstuvwxyz123456" + '"\n',
        encoding="utf-8",
    )

    failures = run_checks(tmp_path)

    assert any("hardcoded Tushare token" in failure for failure in failures)


def test_task_checks_pass_for_current_repository() -> None:
    """Implemented tasks should pass their task-specific checks."""
    root = Path.cwd()

    assert run_task_check("task1", root) == []
    assert run_task_check("task2", root) == []
    assert run_task_check("task3", root) == []
    assert run_task_check("task4", root) == []
    assert run_task_check("task5", root) == []
    assert run_task_check("task6", root) == []
    assert run_task_check("task7", root) == []
    assert run_task_check("task8", root) == []
    assert run_task_check("task9", root) == []
    assert run_task_check("task10", root) == []
    assert run_task_check("task11", root) == []
    assert run_task_check("task12", root) == []
    assert run_task_check("task13", root) == []
    assert run_task_check("task14", root) == []
    assert run_task_check("task15", root) == []


def test_task_check_rejects_unsupported_task() -> None:
    """Unsupported tasks should return a clear failure."""
    assert run_task_check("task99", Path.cwd()) == ["Unsupported task: task99"]
