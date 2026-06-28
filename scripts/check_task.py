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
        "task21": check_task21,
        "task22": check_task22,
        "task23": check_task23,
        "task24": check_task24,
        "task25": check_task25,
        "task26": check_task26,
        "task27": check_task27,
        "task28": check_task28,
        "task29": check_task29,
        "task30": check_task30,
        "task31": check_task31,
        "task32": check_task32,
        "task33": check_task33,
        "task34": check_task34,
        "task35": check_task35,
        "task36": check_task36,
        "task37": check_task37,
        "task38": check_task38,
        "task39": check_task39,
        "task40": check_task40,
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


def check_task21(root: Path) -> list[str]:
    """Check Task 21 selection review export support."""
    failures = check_paths(
        root,
        [
            "core/jobs/export_selection_review.py",
            "core/reporting/selection_review_report.py",
            "tests/test_selection_review_export.py",
            "core/jobs/run_real_workflow.py",
            "core/reporting/workflow_report.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "候选股票人工复核清单与结果导出",
        "python -m core.jobs.export_selection_review",
        "python -m core.jobs.export_selection_review --top-n 10",
        "python -m core.jobs.export_selection_review --format all",
        "--export-selection-review",
        "reports/",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    export_source = read_source(root / "core/jobs/export_selection_review.py")
    for phrase in ["--top-n", "--output-dir", "--format", "--use-existing", "--quiet", "save_selection_review_report"]:
        if phrase not in export_source:
            failures.append(f"core/jobs/export_selection_review.py is missing {phrase}.")

    report_source = read_source(root / "core/reporting/selection_review_report.py")
    for phrase in ["render_markdown_report", "save_selection_review_report", "load_latest_selection_review_report", "人工复核要点", "不构成投资建议"]:
        if phrase not in report_source:
            failures.append(f"core/reporting/selection_review_report.py is missing {phrase}.")

    workflow_source = read_source(root / "core/jobs/run_real_workflow.py")
    for phrase in ["--export-selection-review", "export_selection_review", "export_selection_review_report"]:
        if phrase not in workflow_source:
            failures.append(f"run_real_workflow must support selection review export: missing {phrase}.")

    if "run_real_workflow" not in workflow_source:
        failures.append("Task 20 workflow command must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_selection_review_export.py").lower()
    for phrase in ["mock", "temporary duckdb", "markdown", "json", "csv", "pe/pb", "export_selection_review", "streamlit"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_selection_review_export.py should cover {phrase}.")
    return failures


def check_task22(root: Path) -> list[str]:
    """Check Task 22 review decision and watchlist support."""
    failures = check_paths(
        root,
        [
            "core/jobs/export_review_template.py",
            "core/jobs/import_review_decisions.py",
            "core/jobs/diagnose_watchlist.py",
            "core/jobs/export_watchlist.py",
            "core/reporting/watchlist_report.py",
            "core/reporting/review_template_report.py",
            "core/review/decisions.py",
            "tests/test_review_decision_watchlist.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "人工复核结果回填与观察池管理",
        "review_decisions",
        "python -m core.jobs.export_review_template",
        "python -m core.jobs.import_review_decisions",
        "python -m core.jobs.diagnose_watchlist",
        "python -m core.jobs.export_watchlist",
        "--export-review-template",
        "--export-watchlist",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    schema_source = read_source(root / "core/storage/schema.sql")
    if "CREATE TABLE IF NOT EXISTS review_decisions" not in schema_source:
        failures.append("schema.sql must create review_decisions.")

    decisions_source = read_source(root / "core/review/decisions.py")
    for phrase in ["ALLOWED_DECISIONS", "watch", "needs_data", "import_review_decisions", "build_watchlist_dataframe"]:
        if phrase not in decisions_source:
            failures.append(f"core/review/decisions.py is missing {phrase}.")

    workflow_source = read_source(root / "core/jobs/run_real_workflow.py")
    for phrase in ["--export-review-template", "--export-watchlist", "summarize_review_decisions"]:
        if phrase not in workflow_source:
            failures.append(f"run_real_workflow must include Task 22 integration: missing {phrase}.")

    if "export_selection_review" not in read_source(root / "core/jobs/export_selection_review.py"):
        failures.append("Task 21 export_selection_review must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_review_decision_watchlist.py").lower()
    for phrase in ["temporary duckdb", "mock", "dry_run", "diagnose_watchlist", "export_watchlist", "streamlit"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_review_decision_watchlist.py should cover {phrase}.")
    return failures


def check_task23(root: Path) -> list[str]:
    """Check Task 23 watchlist tracking report support."""
    failures = check_paths(
        root,
        [
            "core/jobs/track_watchlist.py",
            "core/jobs/export_watchlist_tracking_report.py",
            "core/reporting/watchlist_tracking_report.py",
            "core/review/tracking.py",
            "tests/test_watchlist_tracking_report.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "观察池跟踪与变化报告",
        "watchlist_snapshots",
        "python -m core.jobs.track_watchlist",
        "python -m core.jobs.export_watchlist_tracking_report",
        "--track-watchlist",
        "--export-watchlist-tracking",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    schema_source = read_source(root / "core/storage/schema.sql")
    if "CREATE TABLE IF NOT EXISTS watchlist_snapshots" not in schema_source:
        failures.append("schema.sql must create watchlist_snapshots.")

    tracking_source = read_source(root / "core/review/tracking.py")
    for phrase in ["create_watchlist_snapshots", "latest_tracking_snapshot", "watchlist_snapshots"]:
        if phrase not in tracking_source:
            failures.append(f"core/review/tracking.py is missing {phrase}.")

    report_source = read_source(root / "core/reporting/watchlist_tracking_report.py")
    for phrase in ["build_watchlist_tracking_report", "save_watchlist_tracking_report", "close_change_pct", "total_score_change"]:
        if phrase not in report_source:
            failures.append(f"core/reporting/watchlist_tracking_report.py is missing {phrase}.")
    forbidden = ["买入建议", "卖出建议", "强烈推荐", "目标价", "保证收益", "自动交易建议"]
    for phrase in forbidden:
        if phrase in report_source:
            failures.append(f"watchlist_tracking_report should not contain forbidden phrase: {phrase}.")

    workflow_source = read_source(root / "core/jobs/run_real_workflow.py")
    for phrase in ["--track-watchlist", "--export-watchlist-tracking", "track_watchlist", "export_watchlist_tracking"]:
        if phrase not in workflow_source:
            failures.append(f"run_real_workflow must include Task 23 integration: missing {phrase}.")

    if "export_watchlist" not in read_source(root / "core/jobs/export_watchlist.py"):
        failures.append("Task 22 export_watchlist must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_watchlist_tracking_report.py").lower()
    for phrase in ["temporary duckdb", "mock", "track_watchlist", "export_watchlist_tracking", "streamlit", "run_real_workflow"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_watchlist_tracking_report.py should cover {phrase}.")
    return failures


def check_task24(root: Path) -> list[str]:
    """Check Task 24 watchlist decision action support."""
    failures = check_paths(
        root,
        [
            "core/jobs/update_review_decision.py",
            "core/jobs/diagnose_review_history.py",
            "tests/test_watchlist_decision_actions.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "观察池状态调整与复核记录管理",
        "python -m core.jobs.update_review_decision",
        "python -m core.jobs.diagnose_review_history",
        "--diagnose-review-history",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    schema_source = read_source(root / "core/storage/schema.sql")
    if "CREATE TABLE IF NOT EXISTS review_decision_history" not in schema_source:
        failures.append("schema.sql must create review_decision_history.")

    decisions_source = read_source(root / "core/review/decisions.py")
    for phrase in ["update_review_decision", "read_review_decision_history", "summarize_review_history", "review_decision_history"]:
        if phrase not in decisions_source:
            failures.append(f"core/review/decisions.py is missing {phrase}.")

    workflow_source = read_source(root / "core/jobs/run_real_workflow.py")
    for phrase in ["--diagnose-review-history", "diagnose_review_history"]:
        if phrase not in workflow_source:
            failures.append(f"run_real_workflow must include Task 24 integration: missing {phrase}.")

    watchlist_report_source = read_source(root / "core/reporting/watchlist_report.py")
    for phrase in ["history_count", "latest_action_type", "latest_action_at", "review_status"]:
        if phrase not in watchlist_report_source:
            failures.append(f"watchlist_report must include history metadata: missing {phrase}.")

    if "track_watchlist" not in read_source(root / "core/jobs/track_watchlist.py"):
        failures.append("Task 23 track_watchlist must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_watchlist_decision_actions.py").lower()
    for phrase in ["temporary duckdb", "mock", "update_review_decision", "diagnose_review_history", "dry_run", "run_real_workflow"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_watchlist_decision_actions.py should cover {phrase}.")
    return failures


def check_task25(root: Path) -> list[str]:
    """Check Task 25 local backup and restore support."""
    failures = check_paths(
        root,
        [
            "core/jobs/backup_local_data.py",
            "core/jobs/list_backups.py",
            "core/jobs/restore_local_data.py",
            "core/jobs/diagnose_local_state.py",
            "core/jobs/clean_generated_reports.py",
            "tests/test_local_backup_restore.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "本地数据备份与恢复",
        "python -m core.jobs.backup_local_data",
        "python -m core.jobs.restore_local_data",
        "python -m core.jobs.diagnose_local_state",
        "python -m core.jobs.clean_generated_reports",
        "--backup-before-run",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    gitignore = read_source(root / ".gitignore")
    for phrase in [".env", "data/*.duckdb", "reports/*.md", "reports/*.json", "reports/*.csv", "backups/", "**/__pycache__/", ".pytest_cache/"]:
        if phrase not in gitignore:
            failures.append(f".gitignore is missing {phrase}.")

    workflow_source = read_source(root / "core/jobs/run_real_workflow.py")
    for phrase in ["--backup-before-run", "backup_local_data"]:
        if phrase not in workflow_source:
            failures.append(f"run_real_workflow must include Task 25 integration: missing {phrase}.")

    if "update_review_decision" not in read_source(root / "core/jobs/update_review_decision.py"):
        failures.append("Task 24 update_review_decision must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_local_backup_restore.py").lower()
    for phrase in ["temporary duckdb", "mock", "backup_local_data", "restore_local_data", "dry_run", "clean_generated_reports", "run_real_workflow"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_local_backup_restore.py should cover {phrase}.")
    return failures


def check_task26(root: Path) -> list[str]:
    """Check Task 26 project documentation and usage guide."""
    failures = check_paths(
        root,
        [
            "docs/usage_guide.md",
            "docs/commands_reference.md",
            "docs/daily_workflow.md",
            "docs/troubleshooting.md",
            "docs/data_and_backup.md",
            "tests/test_docs_and_usage_guide.py",
            "README.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in [
        "个人本地 A 股选股辅助工具",
        "docs/usage_guide.md",
        "docs/commands_reference.md",
        "docs/daily_workflow.md",
        "python -m core.jobs.run_real_workflow",
        "streamlit run web/streamlit_app.py",
    ]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    commands = read_source(root / "docs/commands_reference.md")
    for phrase in [
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
    ]:
        if phrase not in commands:
            failures.append(f"docs/commands_reference.md is missing {phrase}.")

    troubleshooting = read_source(root / "docs/troubleshooting.md")
    for phrase in ["AKShare 请求失败", "Clash Verge", "run_daily_selection 回退 sample", "restore_local_data 没有 --force 不会恢复"]:
        if phrase not in troubleshooting:
            failures.append(f"docs/troubleshooting.md is missing {phrase}.")

    if "backup_local_data" not in read_source(root / "core/jobs/backup_local_data.py"):
        failures.append("Task 25 backup_local_data must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task27(root: Path) -> list[str]:
    """Check Task 27 real basic and fundamental data enrichment."""
    failures = check_paths(
        root,
        [
            "core/jobs/diagnose_data_quality.py",
            "core/data_sources/basic_info_presets.py",
            "tests/test_real_basic_fundamental_data.py",
            "README.md",
            "docs/usage_guide.md",
            "docs/commands_reference.md",
            "docs/troubleshooting.md",
        ],
    )
    config_source = read_source(root / "app/config.py")
    env_example = read_source(root / ".env.example")
    for phrase in ["ENABLE_REAL_BASIC_ENRICHMENT", "ENABLE_REAL_VALUATION_ENRICHMENT"]:
        if phrase not in config_source:
            failures.append(f"app/config.py is missing {phrase}.")
        if phrase not in env_example:
            failures.append(f".env.example is missing {phrase}.")

    akshare_source = read_source(root / "core/data_sources/akshare_client.py")
    for phrase in ["enrich_stock_basic", "stock_individual_info_em", "stock_a_lg_indicator", "push2his.eastmoney.com"]:
        if phrase not in akshare_source:
            failures.append(f"AKShare enrichment/fallback is missing {phrase}.")
    preset_source = read_source(root / "core/data_sources/basic_info_presets.py")
    for phrase in ["BASIC_INFO_PRESETS", "000001", "600000", "688981", "enrich_with_basic_info_presets"]:
        if phrase not in preset_source:
            failures.append(f"basic_info_presets.py is missing {phrase}.")

    diagnose_source = read_source(root / "core/jobs/diagnose_data_quality.py")
    for phrase in ["stock_basic_completeness", "daily_basic_completeness", "fundamental_score", "pe", "pb"]:
        if phrase not in diagnose_source:
            failures.append(f"diagnose_data_quality.py is missing {phrase}.")

    readme = read_source(root / "README.md")
    for phrase in ["diagnose_data_quality", "ENABLE_REAL_BASIC_ENRICHMENT", "ENABLE_REAL_VALUATION_ENRICHMENT"]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")
    commands = read_source(root / "docs/commands_reference.md")
    if "python -m core.jobs.diagnose_data_quality" not in commands:
        failures.append("docs/commands_reference.md is missing diagnose_data_quality command.")

    if "docs/usage_guide.md" not in readme:
        failures.append("Task 26 documentation links must remain in README.md.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")

    tests_source = read_source(root / "tests/test_real_basic_fundamental_data.py").lower()
    for phrase in ["temporary duckdb", "mock", "industry", "list_date", "pe", "pb", "diagnose_data_quality", "streamlit"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_real_basic_fundamental_data.py should cover {phrase}.")
    return failures


def check_task28(root: Path) -> list[str]:
    """Check Task 28 PE/PB valuation enrichment."""
    failures = check_paths(
        root,
        [
            "core/data_sources/valuation_enrichment.py",
            "tests/test_valuation_enrichment.py",
            "core/data_sources/basic_info_presets.py",
            "core/jobs/diagnose_data_quality.py",
            "README.md",
            "docs/usage_guide.md",
            "docs/commands_reference.md",
            "docs/troubleshooting.md",
        ],
    )
    valuation_source = read_source(root / "core/data_sources/valuation_enrichment.py")
    for phrase in ["ValuationEnricher", "parse_akshare_snapshot", "parse_eastmoney_quote", "merge_latest_valuation", "push2.eastmoney.com"]:
        if phrase not in valuation_source:
            failures.append(f"valuation_enrichment.py is missing {phrase}.")

    update_source = read_source(root / "core/jobs/update_real_data.py")
    for phrase in ["enrich_daily_basic_valuation", "valuation_status", "valuation_success_symbols"]:
        if phrase not in update_source:
            failures.append(f"update_real_data.py is missing {phrase}.")

    diagnose_source = read_source(root / "core/jobs/diagnose_data_quality.py")
    for phrase in ["valuation_summary", "pe_non_null_rate", "pb_non_null_rate", "valuation_updated_count"]:
        if phrase not in diagnose_source:
            failures.append(f"diagnose_data_quality.py is missing {phrase}.")

    tests_source = read_source(root / "tests/test_valuation_enrichment.py").lower()
    for phrase in ["mock", "temporary duckdb", "eastmoney", "pe", "pb", "fundamental_score", "export_selection_review", "watchlist"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_valuation_enrichment.py should cover {phrase}.")

    readme = read_source(root / "README.md")
    docs = "\n".join(
        read_source(root / path)
        for path in ["docs/usage_guide.md", "docs/commands_reference.md", "docs/troubleshooting.md"]
    )
    for phrase in ["ENABLE_REAL_VALUATION_ENRICHMENT", "PE/PB", "diagnose_data_quality"]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")
        if phrase not in docs:
            failures.append(f"docs are missing {phrase}.")

    if "enrich_with_basic_info_presets" not in read_source(root / "core/data_sources/basic_info_presets.py"):
        failures.append("Task 27 basic info preset fallback must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task29(root: Path) -> list[str]:
    """Check Task 29 watchlist latest score refresh."""
    failures = check_paths(
        root,
        [
            "core/jobs/refresh_watchlist_scores.py",
            "core/review/watchlist_scores.py",
            "tests/test_watchlist_score_refresh.py",
            "README.md",
            "docs/commands_reference.md",
            "docs/daily_workflow.md",
        ],
    )
    refresh_source = read_source(root / "core/jobs/refresh_watchlist_scores.py")
    for phrase in ["refresh_watchlist_scores", "--dry-run", "--export-report", "score_missing_reason"]:
        if phrase not in refresh_source:
            failures.append(f"refresh_watchlist_scores.py is missing {phrase}.")

    score_source = read_source(root / "core/review/watchlist_scores.py")
    for phrase in ["factor_scores", "strategy_result", "_calculate_minimal_real_scores", "score_missing_reason"]:
        if phrase not in score_source:
            failures.append(f"watchlist_scores.py is missing {phrase}.")

    tracking_source = read_source(root / "core/reporting/watchlist_tracking_report.py")
    for phrase in ["score_change", "pe_change", "pb_change"]:
        if phrase not in tracking_source:
            failures.append(f"watchlist_tracking_report.py is missing {phrase}.")

    tests_source = read_source(root / "tests/test_watchlist_score_refresh.py").lower()
    for phrase in ["temporary duckdb", "dry_run", "total_score", "pe", "pb", "score_change"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_watchlist_score_refresh.py should cover {phrase}.")

    readme = read_source(root / "README.md")
    commands = read_source(root / "docs/commands_reference.md")
    workflow = read_source(root / "docs/daily_workflow.md")
    for path_name, source in {
        "README.md": readme,
        "docs/commands_reference.md": commands,
        "docs/daily_workflow.md": workflow,
    }.items():
        if "refresh_watchlist_scores" not in source:
            failures.append(f"{path_name} is missing refresh_watchlist_scores.")

    valuation_source = read_source(root / "core/data_sources/valuation_enrichment.py")
    if "ValuationEnricher" not in valuation_source:
        failures.append("Task 28 valuation enrichment must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task30(root: Path) -> list[str]:
    """Check Task 30 daily workflow summary report."""
    failures = check_paths(
        root,
        [
            "core/jobs/run_daily_workflow.py",
            "core/reporting/daily_workflow_report.py",
            "tests/test_daily_workflow_summary_report.py",
            "README.md",
            "docs/usage_guide.md",
            "docs/commands_reference.md",
            "docs/daily_workflow.md",
            "docs/troubleshooting.md",
        ],
    )
    workflow_source = read_source(root / "core/jobs/run_daily_workflow.py")
    for phrase in ["run_daily_workflow", "--skip-update", "--backup-before-run", "--no-watchlist-tracking", "refresh_watchlist_scores"]:
        if phrase not in workflow_source:
            failures.append(f"run_daily_workflow.py is missing {phrase}.")

    report_source = read_source(root / "core/reporting/daily_workflow_report.py")
    for phrase in ["daily_workflow", "Top 候选股票", "watchlist_summary", "pe_non_null_rate", "pb_non_null_rate"]:
        if phrase not in report_source:
            failures.append(f"daily_workflow_report.py is missing {phrase}.")

    tests_source = read_source(root / "tests/test_daily_workflow_summary_report.py").lower()
    for phrase in ["temporary duckdb", "mock", "skip_update", "backup_before_run", "partial_success", "top_candidates", "watchlist"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_daily_workflow_summary_report.py should cover {phrase}.")

    for path in ["README.md", "docs/usage_guide.md", "docs/commands_reference.md", "docs/daily_workflow.md", "docs/troubleshooting.md"]:
        source = read_source(root / path)
        if "run_daily_workflow" not in source:
            failures.append(f"{path} is missing run_daily_workflow.")

    if "refresh_watchlist_scores" not in read_source(root / "core/jobs/refresh_watchlist_scores.py"):
        failures.append("Task 29 watchlist score refresh must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task31(root: Path) -> list[str]:
    """Check Task 31 latest-date report quality scope."""
    failures = check_paths(
        root,
        [
            "tests/test_report_quality_latest_date.py",
            "core/reporting/daily_workflow_report.py",
            "core/jobs/diagnose_data_quality.py",
            "README.md",
            "docs/usage_guide.md",
            "docs/commands_reference.md",
            "docs/daily_workflow.md",
            "docs/troubleshooting.md",
        ],
    )
    diagnose_source = read_source(root / "core/jobs/diagnose_data_quality.py")
    for phrase in ["latest_date_pe_non_null_rate", "latest_date_pb_non_null_rate", "latest_date_stock_count"]:
        if phrase not in diagnose_source:
            failures.append(f"diagnose_data_quality.py is missing {phrase}.")

    report_source = read_source(root / "core/reporting/daily_workflow_report.py")
    for phrase in ["data_quality_scope", "latest_date_pe_non_null_rate", "candidate_pe_missing_count", "watchlist_pe_missing_count"]:
        if phrase not in report_source:
            failures.append(f"daily_workflow_report.py is missing {phrase}.")

    tests_source = read_source(root / "tests/test_report_quality_latest_date.py").lower()
    for phrase in ["historical", "latest_date", "selection_review", "watchlist", "diagnose_factors"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_report_quality_latest_date.py should cover {phrase}.")

    docs = "\n".join(
        read_source(root / path)
        for path in ["README.md", "docs/usage_guide.md", "docs/commands_reference.md", "docs/daily_workflow.md", "docs/troubleshooting.md"]
    )
    for phrase in ["最新交易日", "全历史", "PE/PB", "diagnose_data_quality", "run_daily_workflow"]:
        if phrase not in docs:
            failures.append(f"docs are missing {phrase}.")

    if "run_daily_workflow" not in read_source(root / "core/jobs/run_daily_workflow.py"):
        failures.append("Task 30 run_daily_workflow must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task32(root: Path) -> list[str]:
    """Check Task 32 daily stability and recovery support."""
    failures = check_paths(
        root,
        [
            "core/jobs/doctor_daily_run.py",
            "tests/test_daily_run_doctor.py",
            "README.md",
            "docs/usage_guide.md",
            "docs/commands_reference.md",
            "docs/daily_workflow.md",
            "docs/troubleshooting.md",
            "docs/data_and_backup.md",
        ],
    )
    doctor_source = read_source(root / "core/jobs/doctor_daily_run.py")
    for phrase in ["doctor_daily_run", "--fix-safe", "--pre-run", "--post-run", "reports/.gitkeep", "DUCKDB_PATH"]:
        if phrase not in doctor_source:
            failures.append(f"doctor_daily_run.py is missing {phrase}.")

    workflow_source = read_source(root / "core/jobs/run_daily_workflow.py")
    for phrase in ["--doctor-before-run", "--doctor-after-run", "--stop-on-doctor-failure", "doctor_daily_run"]:
        if phrase not in workflow_source:
            failures.append(f"run_daily_workflow.py is missing {phrase}.")

    report_source = read_source(root / "core/reporting/daily_workflow_report.py")
    for phrase in ["doctor_summary", "日常运行体检", "doctor_before_run"]:
        if phrase not in report_source:
            failures.append(f"daily_workflow_report.py is missing {phrase}.")

    tests_source = read_source(root / "tests/test_daily_run_doctor.py").lower()
    for phrase in ["temporary", "duckdb", "gitkeep", "fix_safe", "doctor_before_run", "pe/pb"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_daily_run_doctor.py should cover {phrase}.")

    docs = "\n".join(
        read_source(root / path)
        for path in ["README.md", "docs/usage_guide.md", "docs/commands_reference.md", "docs/daily_workflow.md", "docs/troubleshooting.md", "docs/data_and_backup.md"]
    )
    for phrase in ["doctor_daily_run", "--pre-run", "--post-run", "--fix-safe", "reports/.gitkeep", "doctor-before-run"]:
        if phrase not in docs:
            failures.append(f"docs are missing {phrase}.")

    if "latest_date_pe_non_null_rate" not in read_source(root / "core/jobs/diagnose_data_quality.py"):
        failures.append("Task 31 latest-date quality scope must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task33(root: Path) -> list[str]:
    """Check Task 33 v0.1 release docs and handbook."""
    failures = check_paths(
        root,
        [
            "docs/v0_1_release_notes.md",
            "docs/v0_1_handbook.md",
            "tests/test_v0_1_release_docs.py",
            "README.md",
            "docs/usage_guide.md",
            "docs/commands_reference.md",
            "docs/daily_workflow.md",
            "docs/troubleshooting.md",
            "docs/data_and_backup.md",
        ],
    )
    readme = read_source(root / "README.md")
    for phrase in ["v0.1", "run_daily_workflow", "doctor_daily_run", "docs/v0_1_handbook.md"]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    release_notes = read_source(root / "docs/v0_1_release_notes.md")
    for phrase in ["v0.1 本地日常使用版", "当前核心能力", "当前限制", "推荐日常命令", "git tag v0.1"]:
        if phrase not in release_notes:
            failures.append(f"v0_1_release_notes.md is missing {phrase}.")

    handbook = read_source(root / "docs/v0_1_handbook.md")
    for phrase in ["第一次使用", "每天推荐流程", "人工复核", "观察池刷新", "Git 注意事项", "reports/.gitkeep"]:
        if phrase not in handbook:
            failures.append(f"v0_1_handbook.md is missing {phrase}.")

    commands = read_source(root / "docs/commands_reference.md")
    for phrase in [
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
        if phrase not in commands:
            failures.append(f"docs/commands_reference.md is missing {phrase}.")

    daily_workflow = read_source(root / "docs/daily_workflow.md")
    if "推荐日常一键命令" not in daily_workflow:
        failures.append("docs/daily_workflow.md must contain 推荐日常一键命令.")
    troubleshooting = read_source(root / "docs/troubleshooting.md")
    if "reports/.gitkeep" not in troubleshooting:
        failures.append("docs/troubleshooting.md must mention reports/.gitkeep.")
    if "doctor_daily_run" not in read_source(root / "core/jobs/doctor_daily_run.py"):
        failures.append("Task 32 doctor_daily_run must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task34(root: Path) -> list[str]:
    """Check Task 34 Mac local console and settings support."""
    failures = check_paths(
        root,
        [
            "core/config/env_file.py",
            "core/runtime/command_runner.py",
            "web/streamlit_app.py",
            "scripts/mac/A股选股助手.command",
            "scripts/mac/README.md",
            "tests/test_env_file_config.py",
            "tests/test_command_runner.py",
            "tests/test_mac_local_console_docs.py",
            "README.md",
            "docs/v0_1_handbook.md",
            "docs/troubleshooting.md",
        ],
    )
    env_source = read_source(root / "core/config/env_file.py")
    for phrase in ["read_env_file", "update_env_file", "masked_env_values", "clean_stock_symbols", "TUSHARE_TOKEN"]:
        if phrase not in env_source:
            failures.append(f"env_file.py is missing {phrase}.")

    command_source = read_source(root / "core/runtime/command_runner.py")
    for phrase in ["ALLOWED_COMMANDS", "subprocess.run", "open_project_path", "shell", "doctor_daily_run"]:
        if phrase not in command_source:
            failures.append(f"command_runner.py is missing {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    if "参数设置" not in streamlit_source and "本地控制台" not in streamlit_source:
        failures.append("web/streamlit_app.py must include 参数设置 or 本地控制台.")

    readme = read_source(root / "README.md")
    for phrase in ["Chrome", "localhost:8501", "参数设置", "A股选股助手.command"]:
        if phrase not in readme:
            failures.append(f"README.md is missing {phrase}.")

    handbook = read_source(root / "docs/v0_1_handbook.md")
    if "参数设置" not in handbook:
        failures.append("docs/v0_1_handbook.md must mention 参数设置.")
    troubleshooting = read_source(root / "docs/troubleshooting.md")
    if "Mac 启动器" not in troubleshooting:
        failures.append("docs/troubleshooting.md must mention Mac 启动器.")

    if not (root / "docs/v0_1_release_notes.md").exists() or not (root / "docs/v0_1_handbook.md").exists():
        failures.append("Task 33 v0.1 docs must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task35(root: Path) -> list[str]:
    """Check Task 35 simplified settings workflow."""
    failures = check_paths(
        root,
        [
            "web/streamlit_app.py",
            "tests/test_simplified_settings_workflow.py",
            "core/config/env_file.py",
            "core/runtime/command_runner.py",
            "scripts/mac/A股选股助手.command",
            "docs/v0_1_handbook.md",
        ],
    )
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["保存并更新数据", "保存并本地重算", "当前生效配置", "参数结束日期", "数据库最新行情日期"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing {phrase}.")
    docs = read_source(root / "docs/v0_1_handbook.md") + read_source(root / "docs/usage_guide.md")
    if "保存并更新数据" not in docs:
        failures.append("docs must explain 保存并更新数据.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task36(root: Path) -> list[str]:
    """Check Task 36 selection logic explainer."""
    failures = check_paths(
        root,
        [
            "core/explain/selection_logic.py",
            "core/jobs/explain_selection_logic.py",
            "docs/selection_logic.md",
            "tests/test_selection_logic_explainer.py",
            "tests/test_explain_selection_logic_job.py",
        ],
    )
    explain_source = read_source(root / "core/explain/selection_logic.py")
    for name in [
        "get_selection_logic_summary",
        "get_factor_definitions",
        "explain_candidate",
        "factor_contributions",
        "formula_summary",
    ]:
        if name not in explain_source:
            failures.append(f"core/explain/selection_logic.py is missing {name}.")
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["选股逻辑", "综合评分公式", "因子说明", "主要贡献因子", "排名原因"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing {phrase}.")
    docs = (
        read_source(root / "README.md")
        + read_source(root / "docs/selection_logic.md")
        + read_source(root / "docs/commands_reference.md")
    )
    for phrase in ["选股逻辑", "total_score", "explain_selection_logic"]:
        if phrase not in docs:
            failures.append(f"docs are missing {phrase}.")
    if "保存并更新数据" not in streamlit_source:
        failures.append("Task 35 simplified settings workflow must remain available.")
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task37(root: Path) -> list[str]:
    """Check Task 37 live progress reporting for local commands."""
    failures = check_paths(
        root,
        [
            "core/runtime/progress.py",
            "core/runtime/command_runner.py",
            "core/jobs/update_real_data.py",
            "core/jobs/run_daily_workflow.py",
            "web/streamlit_app.py",
            "tests/test_progress_reporting.py",
        ],
    )
    progress_source = read_source(root / "core/runtime/progress.py")
    for phrase in ["[progress]", "ProgressState", "format_progress_line", "parse_progress_line"]:
        if phrase not in progress_source:
            failures.append(f"progress.py is missing {phrase}.")
    runner_source = read_source(root / "core/runtime/command_runner.py")
    for phrase in ["run_command_streaming", "subprocess.Popen", "on_line", "STDOUT"]:
        if phrase not in runner_source:
            failures.append(f"command_runner.py is missing streaming support: {phrase}.")
    update_source = read_source(root / "core/jobs/update_real_data.py")
    workflow_source = read_source(root / "core/jobs/run_daily_workflow.py")
    for path, source in {
        "core/jobs/update_real_data.py": update_source,
        "core/jobs/run_daily_workflow.py": workflow_source,
    }.items():
        for phrase in ["emit_progress", "print_progress"]:
            if phrase not in source:
                failures.append(f"{path} is missing {phrase}.")
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["run_command_streaming", "实时日志", "当前运行步骤", "已成功数量", "最终报告路径", "一键运行"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing {phrase}.")
    tests_source = read_source(root / "tests/test_progress_reporting.py")
    for phrase in ["mock", "run_command_streaming", "returncode", "ProgressState"]:
        if phrase.lower() not in tests_source.lower():
            failures.append(f"tests/test_progress_reporting.py should cover {phrase}.")
    if "保存并更新数据" not in streamlit_source:
        failures.append("Task 35 simplified settings workflow must remain available.")
    return failures


def check_task38(root: Path) -> list[str]:
    """Check Task 38 AKShare basic enrichment compatibility."""
    failures = check_paths(
        root,
        [
            "core/data_sources/akshare_client.py",
            "core/jobs/update_real_data.py",
            "tests/test_real_basic_fundamental_data.py",
        ],
    )
    akshare_source = read_source(root / "core/data_sources/akshare_client.py")
    for phrase in [
        "_parse_individual_info",
        "normalize_basic_enrichment_frame",
        "_infer_basic_enrichment_columns",
        "source_columns",
        "_log_enrichment_warning_once",
        "AKShare 基础增强字段缺失",
        "_sanitize_basic_enrichment_error",
        "stock_individual_info_em",
    ]:
        if phrase not in akshare_source:
            failures.append(f"akshare_client.py is missing {phrase}.")
    update_source = read_source(root / "core/jobs/update_real_data.py")
    if "_group_enrichment_warnings" not in update_source:
        failures.append("update_real_data.py must group repeated enrichment warnings.")
    tests_source = read_source(root / "tests/test_real_basic_fundamental_data.py")
    for phrase in [
        "three-column",
        "two-column",
        "empty",
        "single_symbol_failure",
        "update_real_data",
    ]:
        if phrase.lower() not in tests_source.lower():
            failures.append(f"tests/test_real_basic_fundamental_data.py should cover {phrase}.")
    if "total_score =" in read_source(root / "core/factors/scoring.py"):
        pass
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task39(root: Path) -> list[str]:
    """Check Task 39 documentation handoff and task check coverage."""
    required_paths = [
        "README.md",
        "docs/task_35_39_handoff.md",
        "docs/v0_1_handbook.md",
        "docs/v0_1_release_notes.md",
        "docs/commands_reference.md",
        "docs/selection_logic.md",
        "scripts/check_task.py",
    ]
    failures = check_paths(root, required_paths)

    handoff = read_source(root / "docs/task_35_39_handoff.md")
    for phrase in [
        "Task 35",
        "Task 36",
        "Task 37",
        "Task 38",
        "Task 39",
        "保存参数",
        "保存并本地重算",
        "保存并更新数据",
        "选股逻辑",
        "[progress]",
        "AKShare 基础增强字段缺失",
        "不修改选股公式",
        "不修改因子权重",
        "不改变候选排序",
    ]:
        if phrase not in handoff:
            failures.append(f"docs/task_35_39_handoff.md is missing {phrase}.")

    combined_docs = "\n".join(
        read_source(root / path)
        for path in [
            "README.md",
            "docs/v0_1_handbook.md",
            "docs/v0_1_release_notes.md",
            "docs/commands_reference.md",
            "docs/task_35_39_handoff.md",
        ]
    )
    for phrase in [
        "task_35_39_handoff.md",
        "python scripts/check_task.py task39",
        "Chrome",
        "参数设置",
        "实时进度",
        "AKShare",
    ]:
        if phrase not in combined_docs:
            failures.append(f"Task 39 docs are missing {phrase}.")

    check_source = read_source(root / "scripts/check_task.py")
    for phrase in ['"task39": check_task39', "def check_task39", '"task39"']:
        if phrase not in check_source:
            failures.append(f"scripts/check_task.py is missing {phrase}.")

    if "total_score =" in read_source(root / "core/factors/scoring.py"):
        pass
    if "get_sample_dashboard_data" not in read_source(root / "core/sample_data.py"):
        failures.append("sample smoke test support must remain available.")
    return failures


def check_task40(root: Path) -> list[str]:
    """Check Task 40 Elder technical review layer."""
    failures = check_paths(
        root,
        [
            "core/technical/elder.py",
            "core/jobs/run_elder_review.py",
            "docs/elder_review.md",
            "tests/test_elder_review.py",
            "web/streamlit_app.py",
        ],
    )
    elder_source = read_source(root / "core/technical/elder.py")
    for phrase in [
        "calculate_elder_indicators",
        "calculate_weekly_elder_trend",
        "build_elder_review",
        "ema13",
        "ema22",
        "macd_histogram",
        "force_index_2d",
        "force_index_13d",
        "bull_power",
        "bear_power",
        "close_to_ema13_pct",
        "close_to_ema22_pct",
        "elder_score",
        "action_hint",
    ]:
        if phrase not in elder_source:
            failures.append(f"core/technical/elder.py is missing {phrase}.")

    job_source = read_source(root / "core/jobs/run_elder_review.py")
    for phrase in ["run_elder_review", "--format", "markdown", "不覆盖 total_score"]:
        if phrase not in job_source:
            failures.append(f"core/jobs/run_elder_review.py is missing {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["埃尔德复核", "build_elder_review", "elder_score", "action_hint"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing {phrase}.")

    docs = read_source(root / "docs/elder_review.md") + read_source(root / "README.md")
    for phrase in ["EMA13", "MACD", "Force Index", "Elder Ray", "不修改", "不覆盖"]:
        if phrase not in docs:
            failures.append(f"Task 40 docs are missing {phrase}.")

    tests_source = read_source(root / "tests/test_elder_review.py")
    for phrase in ["EMA", "MACD", "Force", "Elder Ray", "数据不足", "total_score"]:
        if phrase.lower() not in tests_source.lower():
            failures.append(f"tests/test_elder_review.py should cover {phrase}.")

    if "DEFAULT_WEIGHTS" not in read_source(root / "core/factors/scoring.py"):
        failures.append("Existing scoring weights must remain available.")
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
            "task21",
            "task22",
            "task23",
            "task24",
            "task25",
            "task26",
            "task27",
            "task28",
            "task29",
            "task30",
            "task31",
            "task32",
            "task33",
            "task34",
            "task35",
            "task36",
            "task37",
            "task38",
            "task39",
            "task40",
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
