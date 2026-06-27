"""Task-specific repository checks."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def run_task_check(task_name: str, root: Path) -> list[str]:
    """Run checks for a supported task name."""
    task_checks = {
        "task1": check_task1,
        "task2": check_task2,
        "task3": check_task3,
        "task4": check_task4,
        "task5": check_task5,
        "task6": check_task6,
        "task7": check_task7,
        "task8": check_task8,
        "task9": check_task9,
        "task10": check_task10,
        "task11": check_task11,
        "task12": check_task12,
        "task13": check_task13,
        "task14": check_task14,
        "task15": check_task15,
        "task16": check_task16,
        "task17": check_task17,
        "task18": check_task18,
        "task19": check_task19,
        "task20": check_task20,
    }
    if task_name not in task_checks:
        return [f"Unsupported task: {task_name}"]
    return task_checks[task_name](root)


def check_task1(root: Path) -> list[str]:
    """Check Task 1 project skeleton files."""
    required_paths = [
        "README.md",
        "PROJECT_SPEC.md",
        "pyproject.toml",
        ".env.example",
        ".gitignore",
        "app/__init__.py",
        "app/main.py",
        "app/config.py",
        "app/api/__init__.py",
        "app/api/routes_stocks.py",
        "app/api/routes_factors.py",
        "app/api/routes_backtest.py",
        "core/__init__.py",
        "core/data_sources/base.py",
        "core/data_sources/tushare_client.py",
        "core/data_sources/akshare_client.py",
        "core/storage/duckdb_store.py",
        "core/storage/schema.sql",
        "core/universe/stock_pool.py",
        "core/factors/trend.py",
        "core/factors/momentum.py",
        "core/factors/liquidity.py",
        "core/factors/volatility.py",
        "core/factors/fundamental.py",
        "core/factors/scoring.py",
        "core/strategy/selector.py",
        "core/strategy/portfolio.py",
        "core/backtest/engine.py",
        "core/backtest/metrics.py",
        "core/backtest/rules_cn_a.py",
        "core/jobs/update_daily_data.py",
        "core/jobs/compute_factors.py",
        "core/jobs/run_daily_selection.py",
        "web/streamlit_app.py",
        "tests/test_data_sources.py",
        "tests/test_stock_pool.py",
        "tests/test_factors.py",
        "tests/test_scoring.py",
        "tests/test_selector.py",
        "tests/test_backtest.py",
        "notebooks/factor_research.ipynb",
    ]
    return check_paths(root, required_paths)


def check_task2(root: Path) -> list[str]:
    """Check Task 2 configuration module."""
    failures = check_paths(root, ["app/config.py", ".env.example", "tests/test_config.py"])
    config_source = read_source(root / "app/config.py")
    env_example = (root / ".env.example").read_text(encoding="utf-8")

    for name in [
        "TUSHARE_TOKEN",
        "DATA_DIR",
        "DUCKDB_PATH",
        "LOG_LEVEL",
        "DEFAULT_TOP_N",
        "DEFAULT_BACKTEST_TOP_N",
    ]:
        if name not in config_source:
            failures.append(f"app/config.py is missing {name}.")
        if name not in env_example:
            failures.append(f".env.example is missing {name}.")

    for name in ["Settings", "get_settings"]:
        if not ast_name_exists(root / "app/config.py", name):
            failures.append(f"app/config.py is missing {name}.")

    if "pydantic_settings" not in config_source:
        failures.append("app/config.py must use pydantic-settings.")
    return failures


def check_task3(root: Path) -> list[str]:
    """Check Task 3 data source clients."""
    failures = check_paths(
        root,
        [
            "core/data_sources/base.py",
            "core/data_sources/tushare_client.py",
            "core/data_sources/akshare_client.py",
            "tests/test_data_sources.py",
        ],
    )
    for path, names in {
        "core/data_sources/base.py": ["StockDataSource", "DataSourceError"],
        "core/data_sources/tushare_client.py": ["TushareClient"],
        "core/data_sources/akshare_client.py": ["AKShareClient"],
    }.items():
        for name in names:
            if not ast_name_exists(root / path, name):
                failures.append(f"{path} is missing {name}.")

    for path in [
        "core/data_sources/base.py",
        "core/data_sources/tushare_client.py",
        "core/data_sources/akshare_client.py",
    ]:
        source = read_source(root / path)
        for method in [
            "get_stock_basic",
            "get_trade_calendar",
            "get_daily_price",
            "get_daily_basic",
            "get_adj_factor",
        ]:
            if method not in source:
                failures.append(f"{path} is missing {method}.")
    return failures


def check_task4(root: Path) -> list[str]:
    """Check Task 4 DuckDB storage layer."""
    failures = check_paths(
        root,
        [
            "core/storage/duckdb_store.py",
            "core/storage/schema.sql",
            "tests/test_duckdb_store.py",
        ],
    )
    if not ast_name_exists(root / "core/storage/duckdb_store.py", "DuckDBStore"):
        failures.append("core/storage/duckdb_store.py is missing DuckDBStore.")

    store_source = read_source(root / "core/storage/duckdb_store.py")
    for name in ["write_dataframe", "upsert_dataframe", "read_date_range"]:
        if name not in store_source:
            failures.append(f"core/storage/duckdb_store.py is missing {name}.")

    schema_source = read_source(root / "core/storage/schema.sql").lower()
    for table_name in [
        "stock_basic",
        "trade_calendar",
        "daily_price",
        "daily_basic",
        "adj_factor",
        "factor_values",
        "factor_scores",
        "strategy_result",
        "backtest_result",
    ]:
        if f"create table if not exists {table_name}" not in schema_source:
            failures.append(f"schema.sql is missing table {table_name}.")
    return failures


def check_task5(root: Path) -> list[str]:
    """Check Task 5 stock universe implementation."""
    failures = check_paths(
        root,
        [
            "core/universe/stock_pool.py",
            "tests/test_stock_pool.py",
        ],
    )
    if not ast_name_exists(root / "core/universe/stock_pool.py", "build_tradeable_universe"):
        failures.append("core/universe/stock_pool.py is missing build_tradeable_universe.")

    source = read_source(root / "core/universe/stock_pool.py")
    for name in [
        "stock_basic",
        "daily_price",
        "daily_basic",
        "trade_date",
        "avg_amount_20d",
        "avg_turnover_20d",
        "is_tradeable",
        "exclude_reason",
    ]:
        if name not in source:
            failures.append(f"core/universe/stock_pool.py is missing {name}.")

    tests_source = read_source(root / "tests/test_stock_pool.py")
    for phrase in [
        "ST stock",
        "suspended",
        "listed less than 120 days",
        "avg amount 20d below 100 million",
        "suspended more than 3 days in 20d",
        "severe financial data missing",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_stock_pool.py does not cover: {phrase}.")
    return failures


def check_task6(root: Path) -> list[str]:
    """Check Task 6 base factor calculation modules."""
    factor_files = [
        "core/factors/trend.py",
        "core/factors/momentum.py",
        "core/factors/liquidity.py",
        "core/factors/volatility.py",
        "core/factors/fundamental.py",
        "tests/test_factors.py",
    ]
    failures = check_paths(root, factor_files)
    expected_functions = {
        "core/factors/trend.py": [
            "calculate_return_20d",
            "calculate_return_60d",
            "calculate_ma_position",
            "calculate_ma_alignment",
        ],
        "core/factors/momentum.py": [
            "calculate_relative_strength",
            "calculate_new_high_60d",
        ],
        "core/factors/liquidity.py": [
            "calculate_avg_amount_20d",
            "calculate_avg_turnover_20d",
        ],
        "core/factors/volatility.py": [
            "calculate_volatility_20d",
            "calculate_max_drawdown_60d",
        ],
        "core/factors/fundamental.py": [
            "calculate_roe",
            "calculate_pe_score",
            "calculate_pb_score",
            "calculate_revenue_growth",
        ],
    }
    for path, function_names in expected_functions.items():
        for function_name in function_names:
            if not ast_name_exists(root / path, function_name):
                failures.append(f"{path} is missing {function_name}.")

    tests_source = read_source(root / "tests/test_factors.py")
    for phrase in ["mock", "insufficient", "future", "missing"]:
        if phrase not in tests_source.lower():
            failures.append(f"tests/test_factors.py should cover {phrase} data behavior.")
    return failures


def check_task7(root: Path) -> list[str]:
    """Check Task 7 factor scoring implementation."""
    failures = check_paths(root, ["core/factors/scoring.py", "tests/test_scoring.py"])
    for function_name in ["normalize_factor", "calculate_total_score"]:
        if not ast_name_exists(root / "core/factors/scoring.py", function_name):
            failures.append(f"core/factors/scoring.py is missing {function_name}.")

    scoring_source = read_source(root / "core/factors/scoring.py")
    for phrase in ["trade_date", "higher_is_better", "DEFAULT_WEIGHTS", "total_score"]:
        if phrase not in scoring_source:
            failures.append(f"core/factors/scoring.py is missing {phrase}.")

    tests_source = read_source(root / "tests/test_scoring.py").lower()
    for phrase in ["higher_is_better", "trade_date", "nan", "custom weights", "invalid weights"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_scoring.py should cover {phrase}.")
    return failures


def check_task8(root: Path) -> list[str]:
    """Check Task 8 selection strategy implementation."""
    failures = check_paths(
        root,
        [
            "core/strategy/selector.py",
            "core/strategy/portfolio.py",
            "tests/test_selector.py",
        ],
    )
    if not ast_name_exists(root / "core/strategy/selector.py", "select_top_stocks"):
        failures.append("core/strategy/selector.py is missing select_top_stocks.")
    if not ast_name_exists(root / "core/strategy/portfolio.py", "build_equal_weight_portfolio"):
        failures.append("core/strategy/portfolio.py is missing build_equal_weight_portfolio.")

    selector_source = read_source(root / "core/strategy/selector.py")
    portfolio_source = read_source(root / "core/strategy/portfolio.py")
    for phrase in ["trade_date", "total_score", "rank", "select_reason", "risk_note"]:
        if phrase not in selector_source:
            failures.append(f"core/strategy/selector.py is missing {phrase}.")
    for phrase in ["trade_date", "max_positions", "weight"]:
        if phrase not in portfolio_source:
            failures.append(f"core/strategy/portfolio.py is missing {phrase}.")

    tests_source = read_source(root / "tests/test_selector.py").lower()
    for phrase in ["total_score", "top_n", "rank", "select_reason", "risk_note", "weight"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_selector.py should cover {phrase}.")
    return failures


def check_task9(root: Path) -> list[str]:
    """Check Task 9 backtest engine implementation."""
    failures = check_paths(
        root,
        [
            "core/backtest/engine.py",
            "core/backtest/metrics.py",
            "core/backtest/rules_cn_a.py",
            "tests/test_backtest.py",
        ],
    )
    expected_functions = {
        "core/backtest/engine.py": ["run_backtest"],
        "core/backtest/metrics.py": [
            "calculate_annual_return",
            "calculate_max_drawdown",
            "calculate_sharpe_ratio",
            "calculate_win_rate",
            "calculate_turnover",
            "calculate_yearly_returns",
        ],
        "core/backtest/rules_cn_a.py": [
            "is_suspended",
            "is_limit_up",
            "is_limit_down",
            "can_buy",
            "can_sell",
        ],
    }
    for path, function_names in expected_functions.items():
        for function_name in function_names:
            if not ast_name_exists(root / path, function_name):
                failures.append(f"{path} is missing {function_name}.")

    tests_source = read_source(root / "tests/test_backtest.py").lower()
    for phrase in ["weekly", "top_n", "equal", "slippage", "suspended", "limit_up", "limit_down"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_backtest.py should cover {phrase}.")
    return failures


def check_task10(root: Path) -> list[str]:
    """Check Task 10 Streamlit dashboard implementation."""
    failures = check_paths(root, ["web/streamlit_app.py", "tests/test_streamlit_app.py"])
    source = read_source(root / "web/streamlit_app.py")
    for function_name in [
        "render_dashboard",
        "filter_selection_data",
        "dataframe_to_csv",
        "filter_factor_ranking",
        "summarize_update_status",
    ]:
        if not ast_name_exists(root / "web/streamlit_app.py", function_name):
            failures.append(f"web/streamlit_app.py is missing {function_name}.")
    for tab_name in ["今日选股", "个股详情", "因子排名", "策略回测", "数据更新状态"]:
        if tab_name not in source:
            failures.append(f"web/streamlit_app.py is missing tab {tab_name}.")
    tests_source = read_source(root / "tests/test_streamlit_app.py").lower()
    for phrase in ["empty", "filter", "sort", "csv"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_streamlit_app.py should cover {phrase}.")
    return failures


def check_task11(root: Path) -> list[str]:
    """Check Task 11 one-click daily selection entrypoint."""
    failures = check_paths(root, ["core/jobs/run_daily_selection.py"])
    source = read_source(root / "core/jobs/run_daily_selection.py")
    for function_name in ["run_daily_selection", "main"]:
        if not ast_name_exists(root / "core/jobs/run_daily_selection.py", function_name):
            failures.append(f"core/jobs/run_daily_selection.py is missing {function_name}.")
    for phrase in ["run_date", "data_source", "stock_pool_count", "candidate_count"]:
        if phrase not in source:
            failures.append(f"core/jobs/run_daily_selection.py is missing summary field {phrase}.")
    return failures


def check_task12(root: Path) -> list[str]:
    """Check Task 12 MVP smoke-test readiness."""
    failures = check_paths(
        root,
        [
            "README.md",
            "web/streamlit_app.py",
            "core/jobs/run_daily_selection.py",
            "core/sample_data.py",
            "tests/test_smoke_mvp.py",
        ],
    )

    readme = read_source(root / "README.md")
    for phrase in [
        "pip install -e .",
        "python -m pytest",
        "python scripts/check_project.py",
        "python -m core.jobs.run_daily_selection",
        "streamlit run web/streamlit_app.py",
        "sample",
        "不构成投资建议",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    sample_source = read_source(root / "core/sample_data.py")
    for function_name in [
        "get_sample_stock_basic",
        "get_sample_daily_price",
        "get_sample_daily_basic",
        "get_sample_factor_scores",
        "get_sample_strategy_result",
        "get_sample_backtest_result",
    ]:
        if not ast_name_exists(root / "core/sample_data.py", function_name):
            failures.append(f"core/sample_data.py is missing {function_name}.")
    if "演示数据" not in sample_source:
        failures.append("core/sample_data.py must clearly label demo data.")

    tests_source = read_source(root / "tests/test_smoke_mvp.py").lower()
    for phrase in ["sample", "run_daily_selection", "streamlit", "readme"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_smoke_mvp.py should cover {phrase}.")
    return failures


def check_task13(root: Path) -> list[str]:
    """Check Task 13 minimal real Tushare ingestion."""
    failures = check_paths(
        root,
        [
            "core/jobs/update_real_data.py",
            "core/data_sources/tushare_client.py",
            "tests/test_real_data_ingestion.py",
            ".env.example",
        ],
    )
    config_source = read_source(root / "app/config.py")
    env_example = read_source(root / ".env.example")
    for name in [
        "DATA_PROVIDER",
        "ENABLE_AKSHARE_FALLBACK",
        "REAL_DATA_START_DATE",
        "REAL_DATA_END_DATE",
        "REAL_DATA_SAMPLE_SYMBOLS",
    ]:
        if name not in config_source:
            failures.append(f"app/config.py is missing {name}.")
        if name not in env_example:
            failures.append(f".env.example is missing {name}.")

    token_line = next(
        (line for line in env_example.splitlines() if line.startswith("TUSHARE_TOKEN=")),
        "",
    )
    if token_line != "TUSHARE_TOKEN=":
        failures.append(".env.example must not contain a real Tushare token.")

    update_source = read_source(root / "core/jobs/update_real_data.py")
    for phrase in ["update_real_data", "TUSHARE_TOKEN 为空", "stock_basic", "daily_price"]:
        if phrase not in update_source:
            failures.append(f"core/jobs/update_real_data.py is missing {phrase}.")

    tests_source = read_source(root / "tests/test_real_data_ingestion.py").lower()
    for phrase in ["mock", "tushare_token", "duckdb", "sample"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_real_data_ingestion.py should cover {phrase}.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task14(root: Path) -> list[str]:
    """Check Task 14 AKShare fallback support."""
    failures = check_paths(
        root,
        [
            "core/data_sources/provider.py",
            "core/data_sources/akshare_client.py",
            "tests/test_akshare_fallback.py",
            ".env.example",
        ],
    )
    config_source = read_source(root / "app/config.py")
    env_example = read_source(root / ".env.example")
    for name in [
        "DATA_PROVIDER",
        "ENABLE_AKSHARE_FALLBACK",
        "AKSHARE_SAMPLE_SYMBOLS",
        "AKSHARE_ADJUST",
    ]:
        if name not in config_source:
            failures.append(f"app/config.py is missing {name}.")
        if name not in env_example:
            failures.append(f".env.example is missing {name}.")

    token_line = next(
        (line for line in env_example.splitlines() if line.startswith("TUSHARE_TOKEN=")),
        "",
    )
    if token_line != "TUSHARE_TOKEN=":
        failures.append(".env.example must not contain a real Tushare token.")

    provider_source = read_source(root / "core/data_sources/provider.py")
    for phrase in ["sample", "tushare", "akshare", "enable_akshare_fallback"]:
        if phrase not in provider_source:
            failures.append(f"core/data_sources/provider.py is missing {phrase}.")

    tests_source = read_source(root / "tests/test_akshare_fallback.py").lower()
    for phrase in ["mock", "fallback", "akshare", "sample"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_akshare_fallback.py should cover {phrase}.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task15(root: Path) -> list[str]:
    """Check Task 15 real-data E2E validation support."""
    failures = check_paths(
        root,
        [
            "core/jobs/diagnose_real_data.py",
            "tests/test_real_data_e2e_validation.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "python -m core.jobs.update_real_data",
        "python -m core.jobs.diagnose_real_data",
        "python -m core.jobs.run_daily_selection",
        "streamlit run web/streamlit_app.py",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    diagnose_source = read_source(root / "core/jobs/diagnose_real_data.py")
    for phrase in ["diagnose_real_data", "stock_basic", "daily_price", "is_ready_for_selection"]:
        if phrase not in diagnose_source:
            failures.append(f"core/jobs/diagnose_real_data.py is missing {phrase}.")

    if not (root / "core/data_sources/provider.py").exists():
        failures.append("Task 14 provider selection must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_real_data_e2e_validation.py").lower()
    for phrase in ["temporary duckdb", "mock", "diagnose_real_data", "sample"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_real_data_e2e_validation.py should cover {phrase}.")
    return failures


def check_task16(root: Path) -> list[str]:
    """Check Task 16 real-data daily workflow support."""
    failures = check_paths(
        root,
        [
            "tests/test_real_data_daily_workflow.py",
            "core/jobs/diagnose_real_data.py",
            "core/jobs/update_real_data.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "真实数据日常使用流程",
        "python -m core.jobs.update_real_data",
        "python -m core.jobs.diagnose_real_data",
        "python -m core.jobs.run_daily_selection",
        "streamlit run web/streamlit_app.py",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    tests_source = read_source(root / "tests/test_real_data_daily_workflow.py").lower()
    for phrase in ["temporary duckdb", "mock", "duplicate", "fallback", "streamlit"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_real_data_daily_workflow.py should cover {phrase}.")

    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task17(root: Path) -> list[str]:
    """Check Task 17 real factor validation support."""
    failures = check_paths(
        root,
        [
            "core/jobs/diagnose_factors.py",
            "tests/test_real_factor_validation.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "真实因子结果校验",
        "python -m core.jobs.update_real_data",
        "python -m core.jobs.diagnose_real_data",
        "python -m core.jobs.diagnose_factors",
        "python -m core.jobs.run_daily_selection",
        "streamlit run web/streamlit_app.py",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    diagnose_source = read_source(root / "core/jobs/diagnose_factors.py")
    for phrase in [
        "diagnose_factors",
        "factor_quality",
        "total_score_non_null_count",
        "AKShare fallback",
    ]:
        if phrase not in diagnose_source:
            failures.append(f"core/jobs/diagnose_factors.py is missing {phrase}.")

    akshare_source = read_source(root / "core/data_sources/akshare_client.py")
    for phrase in ["subprocess.run", "curl", "push2his.eastmoney.com"]:
        if phrase not in akshare_source:
            failures.append(f"AKShare curl fallback must remain available: missing {phrase}.")

    if not (root / "tests/test_real_data_daily_workflow.py").exists():
        failures.append("Task 16 daily workflow tests must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_real_factor_validation.py").lower()
    for phrase in ["temporary duckdb", "mock", "diagnose_factors", "nan", "streamlit", "sample"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_real_factor_validation.py should cover {phrase}.")
    return failures


def check_task18(root: Path) -> list[str]:
    """Check Task 18 real backtest validation support."""
    failures = check_paths(
        root,
        [
            "core/jobs/diagnose_backtest.py",
            "tests/test_real_backtest_validation.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "真实回测结果校验",
        "python -m core.jobs.update_real_data",
        "python -m core.jobs.diagnose_real_data",
        "python -m core.jobs.diagnose_factors",
        "python -m core.jobs.run_daily_selection",
        "python -m core.jobs.diagnose_backtest",
        "streamlit run web/streamlit_app.py",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    diagnose_source = read_source(root / "core/jobs/diagnose_backtest.py")
    for phrase in [
        "diagnose_backtest",
        "run_backtest",
        "equity_curve_rows",
        "trade_records_rows",
        "position_records_rows",
        "AKShare fallback",
    ]:
        if phrase not in diagnose_source:
            failures.append(f"core/jobs/diagnose_backtest.py is missing {phrase}.")

    if not (root / "core/jobs/diagnose_factors.py").exists():
        failures.append("Task 17 factor diagnostics must remain available.")
    akshare_source = read_source(root / "core/data_sources/akshare_client.py")
    for phrase in ["subprocess.run", "curl", "push2his.eastmoney.com"]:
        if phrase not in akshare_source:
            failures.append(f"AKShare curl fallback must remain available: missing {phrase}.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_real_backtest_validation.py").lower()
    for phrase in ["temporary duckdb", "mock", "diagnose_backtest", "equity_curve", "sample"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_real_backtest_validation.py should cover {phrase}.")
    return failures


def check_task19(root: Path) -> list[str]:
    """Check Task 19 real universe batch update support."""
    failures = check_paths(
        root,
        [
            "core/data_sources/universe_presets.py",
            "core/jobs/diagnose_update_batch.py",
            "tests/test_real_universe_batch_update.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "真实股票样本扩容与批量更新",
        "REAL_UNIVERSE_PRESET",
        "python -m core.jobs.update_real_data",
        "python -m core.jobs.diagnose_update_batch",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    preset_source = read_source(root / "core/data_sources/universe_presets.py")
    for phrase in ["mini", "small", "medium", "get_universe_preset"]:
        if phrase not in preset_source:
            failures.append(f"core/data_sources/universe_presets.py is missing {phrase}.")

    diagnose_source = read_source(root / "core/jobs/diagnose_update_batch.py")
    for phrase in ["diagnose_update_batch", "coverage_rate", "missing_symbols", "backtest_ready_count"]:
        if phrase not in diagnose_source:
            failures.append(f"core/jobs/diagnose_update_batch.py is missing {phrase}.")

    if not (root / "core/jobs/diagnose_backtest.py").exists():
        failures.append("Task 18 backtest diagnostics must remain available.")
    akshare_source = read_source(root / "core/data_sources/akshare_client.py")
    for phrase in ["subprocess.run", "curl", "push2his.eastmoney.com"]:
        if phrase not in akshare_source:
            failures.append(f"AKShare curl fallback must remain available: missing {phrase}.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_real_universe_batch_update.py").lower()
    for phrase in ["mock", "temporary duckdb", "mini", "small", "medium", "partial_success", "sample"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_real_universe_batch_update.py should cover {phrase}.")
    return failures


def check_task20(root: Path) -> list[str]:
    """Check Task 20 real workflow reporting support."""
    failures = check_paths(
        root,
        [
            "core/jobs/run_real_workflow.py",
            "core/reporting/workflow_report.py",
            "tests/test_real_workflow_reporting.py",
            "reports/.gitkeep",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "真实运行工作流与报告导出",
        "python -m core.jobs.run_real_workflow",
        "python -m core.jobs.run_real_workflow --skip-update",
        "python -m core.jobs.run_real_workflow --no-backtest",
        "python -m core.jobs.run_real_workflow --format json",
        "reports/",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    workflow_source = read_source(root / "core/jobs/run_real_workflow.py")
    for phrase in ["--skip-update", "--no-backtest", "--report-dir", "--format", "--quiet", "save_workflow_report"]:
        if phrase not in workflow_source:
            failures.append(f"core/jobs/run_real_workflow.py is missing {phrase}.")

    report_source = read_source(root / "core/reporting/workflow_report.py")
    for phrase in ["render_markdown_report", "save_workflow_report", "load_latest_workflow_report", "不构成投资建议"]:
        if phrase not in report_source:
            failures.append(f"core/reporting/workflow_report.py is missing {phrase}.")

    if not (root / "core/jobs/diagnose_update_batch.py").exists():
        failures.append("Task 19 batch diagnostics must remain available.")
    akshare_source = read_source(root / "core/data_sources/akshare_client.py")
    for phrase in ["subprocess.run", "curl", "push2his.eastmoney.com"]:
        if phrase not in akshare_source:
            failures.append(f"AKShare curl fallback must remain available: missing {phrase}.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_real_workflow_reporting.py").lower()
    for phrase in ["mock", "temporary duckdb", "skip-update", "markdown", "json", "failed", "partial_success", "no_backtest", "streamlit"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_real_workflow_reporting.py should cover {phrase}.")
    return failures


def check_paths(root: Path, relative_paths: list[str]) -> list[str]:
    """Return failures for missing required paths."""
    return [f"Missing required path: {path}" for path in relative_paths if not (root / path).exists()]


def ast_name_exists(path: Path, name: str) -> bool:
    """Return whether a class or function exists in a Python file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    return any(
        isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
        for node in ast.walk(tree)
    )


def read_source(path: Path) -> str:
    """Read a UTF-8 source file, returning an empty string when missing."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def main(argv: list[str] | None = None) -> int:
    """Run a task-specific check from the command line."""
    parser = argparse.ArgumentParser(description="Run task-specific repository checks.")
    parser.add_argument(
        "task",
        choices=[
            "task1",
            "task2",
            "task3",
            "task4",
            "task5",
            "task6",
            "task7",
            "task8",
            "task9",
            "task10",
            "task11",
            "task12",
            "task13",
            "task14",
            "task15",
            "task16",
            "task17",
            "task18",
            "task19",
            "task20",
        ],
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root.")
    args = parser.parse_args(argv)

    failures = run_task_check(args.task, args.root.resolve())
    if failures:
        print(f"{args.task} checks failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"{args.task} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
