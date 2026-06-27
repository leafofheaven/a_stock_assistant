"""MVP smoke tests for demo data, daily job, README, and dashboard wiring."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

from core.jobs.run_daily_selection import run_daily_selection
from core.sample_data import (
    get_sample_backtest_result,
    get_sample_daily_basic,
    get_sample_daily_price,
    get_sample_factor_scores,
    get_sample_stock_basic,
    get_sample_strategy_result,
)
from web.streamlit_app import filter_selection_data, summarize_update_status


class SampleSettings:
    """Settings-like object that forces sample-mode smoke tests."""

    data_provider = "sample"


def test_sample_data_functions_return_dataframes() -> None:
    """Sample data should cover the MVP tables without external API calls."""
    frames = [
        get_sample_stock_basic(),
        get_sample_daily_price(),
        get_sample_daily_basic(),
        get_sample_factor_scores(),
        get_sample_strategy_result(),
    ]

    for frame in frames:
        assert isinstance(frame, pd.DataFrame)
        assert not frame.empty
        assert "演示数据" in frame.to_string()

    backtest = get_sample_backtest_result()
    assert isinstance(backtest["equity_curve"], pd.DataFrame)
    assert not backtest["equity_curve"].empty


def test_run_daily_selection_sample_mode_runs_without_token() -> None:
    """Daily selection smoke entry should run with demo data and no real token."""
    summary = run_daily_selection(use_sample=True, settings=SampleSettings())

    assert "sample" in summary["data_source"]
    assert summary["stock_pool_count"] > 0
    assert summary["scored_stock_count"] > 0
    assert summary["candidate_count"] > 0
    assert summary["top_candidates"]


def test_run_daily_selection_no_data_mode_is_clear() -> None:
    """No-data mode should return a readable empty summary instead of crashing."""
    summary = run_daily_selection(use_sample=False, settings=SampleSettings())

    assert summary["data_source"] == "无数据"
    assert summary["candidate_count"] == 0
    assert summary["top_candidates"] == []


def test_streamlit_helpers_handle_empty_data() -> None:
    """Streamlit helper functions should not crash on empty local data."""
    filtered = filter_selection_data(pd.DataFrame())
    status = summarize_update_status({})

    assert filtered.empty
    assert "total_score" in filtered.columns
    assert status["latest_price_date"] is None
    assert status["latest_factor_date"] is None
    assert status["latest_selection_date"] is None


def test_readme_contains_mvp_commands_and_paths() -> None:
    """README should document the MVP commands a local user needs."""
    root = Path.cwd()
    readme = (root / "README.md").read_text(encoding="utf-8")

    for text in [
        "pip install -e .",
        "cp .env.example .env",
        "python -m pytest",
        "python scripts/check_project.py",
        "python scripts/check_task.py task11",
        "python -m core.jobs.run_daily_selection",
        "streamlit run web/streamlit_app.py",
        "项目根目录",
        "不构成投资建议",
    ]:
        assert text in readme

    assert (root / "web/streamlit_app.py").exists()
    assert (root / "core/jobs/run_daily_selection.py").exists()
    assert (root / "core/sample_data.py").exists()


def test_streamlit_app_contains_five_tab_names() -> None:
    """Dashboard source should expose the five MVP tab names."""
    source = Path("web/streamlit_app.py").read_text(encoding="utf-8")

    for tab_name in ["今日选股", "个股详情", "因子排名", "策略回测", "数据更新状态"]:
        assert tab_name in source


def test_streamlit_app_import_adds_project_root_for_core_import(monkeypatch) -> None:
    """Streamlit script import should not fail when only web/ starts on sys.path."""
    root = Path.cwd().resolve()
    web_dir = root / "web"
    script = web_dir / "streamlit_app.py"
    module_name = "_streamlit_app_import_check"
    original_path = list(sys.path)
    monkeypatch.setattr(sys, "path", [str(web_dir), *[path for path in original_path if path != str(root)]])

    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert str(root) in sys.path
    assert hasattr(module, "sample_dashboard_data")


def test_setup_includes_web_package() -> None:
    """Editable install config should include app, core, and web packages."""
    setup_source = Path("setup.py").read_text(encoding="utf-8")

    assert '"app", "app.*"' in setup_source
    assert '"core", "core.*"' in setup_source
    assert '"web", "web.*"' in setup_source
