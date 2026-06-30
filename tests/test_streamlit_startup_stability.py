"""Tests for Streamlit startup diagnostics and safe launch helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb

from core.jobs.diagnose_streamlit_startup import diagnose_streamlit_startup
from scripts.start_streamlit_safe import build_open_command, build_streamlit_command, main as start_streamlit_main


def _settings(path: Path) -> SimpleNamespace:
    return SimpleNamespace(duckdb_path=path)


def test_diagnose_streamlit_startup_handles_missing_database(tmp_path: Path) -> None:
    """Missing DuckDB should produce a clear non-mutating diagnostic."""
    result = diagnose_streamlit_startup(settings=_settings(tmp_path / "missing.duckdb"), port=59999)

    assert result["duckdb_exists"] is False
    assert result["duckdb_read_only_ok"] is False
    assert "不存在" in result["duckdb_error"]


def test_diagnose_streamlit_startup_reads_existing_database(tmp_path: Path) -> None:
    """Existing DuckDB should be opened read-only and table presence should be reported."""
    db_path = tmp_path / "ok.duckdb"
    with duckdb.connect(str(db_path)) as connection:
        connection.execute("CREATE TABLE stock_basic(ts_code VARCHAR)")

    result = diagnose_streamlit_startup(settings=_settings(db_path), port=59999)

    assert result["duckdb_exists"] is True
    assert result["duckdb_read_only_ok"] is True
    assert result["core_tables"]["stock_basic"] is True


def test_diagnose_streamlit_startup_reports_locked_database(tmp_path: Path, monkeypatch) -> None:
    """A simulated DuckDB lock should be reported with the friendly lock message."""
    db_path = tmp_path / "locked.duckdb"
    db_path.write_bytes(b"not-empty")

    def raise_lock(*args, **kwargs):
        raise RuntimeError("IO Error: Could not set lock on file; Conflicting lock is held")

    monkeypatch.setattr("core.jobs.diagnose_streamlit_startup.duckdb.connect", raise_lock)

    result = diagnose_streamlit_startup(settings=_settings(db_path), port=59999)

    assert result["duckdb_locked"] is True
    assert "DuckDB is locked by another process" in result["duckdb_error"]
    assert any("lsof" in item for item in result["suggestions"])


def test_start_streamlit_safe_builds_expected_command() -> None:
    """Safe starter should launch Streamlit headless and disable file watcher."""
    command = build_streamlit_command(8501)

    assert command[:3][-2:] == ["-m", "streamlit"]
    assert "web/streamlit_app.py" in command
    assert "--server.headless" in command
    assert "true" in command
    assert "--server.fileWatcherType" in command
    assert "none" in command
    assert build_open_command(8501) == ["open", "http://localhost:8501"]


def test_start_streamlit_safe_dry_run_does_not_launch(monkeypatch, tmp_path: Path) -> None:
    """Dry-run should print diagnostics and not spawn Streamlit."""
    monkeypatch.setattr(
        "scripts.start_streamlit_safe.diagnose_streamlit_startup",
        lambda port: {
            "branch": "test",
            "duckdb_path": str(tmp_path / "x.duckdb"),
            "duckdb_exists": False,
            "duckdb_read_only_ok": False,
            "duckdb_locked": False,
            "port_in_use": False,
            "core_tables": {},
            "suggestions": ["mock"],
        },
    )

    assert start_streamlit_main(["--dry-run", "--port", "59999"]) == 0


def test_start_streamlit_safe_existing_port_opens_once_without_second_process(monkeypatch, tmp_path: Path) -> None:
    """Existing Streamlit service should not spawn a second process and should open one URL."""
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "scripts.start_streamlit_safe.diagnose_streamlit_startup",
        lambda port: {
            "branch": "test",
            "duckdb_path": str(tmp_path / "x.duckdb"),
            "duckdb_exists": True,
            "duckdb_read_only_ok": True,
            "duckdb_locked": False,
            "port_in_use": True,
            "core_tables": {},
            "suggestions": ["mock"],
        },
    )
    monkeypatch.setattr("scripts.start_streamlit_safe.subprocess.run", lambda command, check=False: calls.append(command))
    monkeypatch.setattr(
        "scripts.start_streamlit_safe.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not start second Streamlit")),
    )

    assert start_streamlit_main(["--port", "59999"]) == 0
    assert calls == [["open", "http://localhost:59999"]]
