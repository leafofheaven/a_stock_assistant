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
        "task41": check_task41,
        "task42": check_task42,
        "task43": check_task43,
        "task44": check_task44,
        "task45": check_task45,
        "task46": check_task46,
        "task47": check_task47,
        "task48": check_task48,
        "task49": check_task49,
        "task50": check_task50,
        "task51": check_task51,
        "task52": check_task52,
        "task53": check_task53,
        "task54": check_task54,
        "task55": check_task55,
        "task56": check_task56,
        "task57a": check_task57a,
        "task57b": check_task57b,
        "task57h": check_task57h,
        "task57i": check_task57i,
        "task58": check_task58,
        "task59": check_task59,
        "task59b": check_task59b,
        "task59c": check_task59c,
        "task60": check_task60,
        "task61": check_task61,
        "task62": check_task62,
        "task64": check_task64,
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


def check_task41(root: Path) -> list[str]:
    """Check Task 41 Elder review workflow integration."""
    failures = check_paths(
        root,
        [
            "core/jobs/export_elder_review.py",
            "core/jobs/run_elder_review.py",
            "core/technical/elder.py",
            "core/reporting/selection_review_report.py",
            "docs/elder_review_workflow.md",
            "tests/test_elder_review_workflow.py",
            "web/streamlit_app.py",
        ],
    )
    elder_source = read_source(root / "core/technical/elder.py")
    for phrase in ["review_action", "weekly_trend", "daily_pullback", "force_signal", "elder_ray_signal"]:
        if phrase not in elder_source:
            failures.append(f"core/technical/elder.py is missing {phrase}.")
    export_source = read_source(root / "core/jobs/export_elder_review.py")
    for phrase in [
        "export_elder_review",
        "add_confirmed_elder_to_watchlist",
        "--add-confirmed-to-watchlist",
        "skipped_existing",
        "elder_score",
        "action_hint",
    ]:
        if phrase not in export_source:
            failures.append(f"core/jobs/export_elder_review.py is missing {phrase}.")
    report_source = read_source(root / "core/reporting/selection_review_report.py")
    for phrase in ["elder_score", "action_hint", "elder_reason", "weekly_trend", "daily_pullback", "force_signal", "elder_ray_signal"]:
        if phrase not in report_source:
            failures.append(f"selection_review_report.py is missing {phrase}.")
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["埃尔德复核", "review_action", "最近一次埃尔德复核", "export_elder_review"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing {phrase}.")
    docs = read_source(root / "docs/elder_review_workflow.md") + read_source(root / "README.md")
    for phrase in ["加入观察池", "等待回调", "暂缓", "忽略", "不改变", "不自动交易"]:
        if phrase not in docs:
            failures.append(f"Task 41 docs are missing {phrase}.")
    tests_source = read_source(root / "tests/test_elder_review_workflow.py")
    for phrase in ["selection_review", "total_score", "skipped_existing", "export_elder_review", "数据不足"]:
        if phrase.lower() not in tests_source.lower():
            failures.append(f"tests/test_elder_review_workflow.py should cover {phrase}.")
    return failures


def check_task42(root: Path) -> list[str]:
    """Check Task 42 Elder review historical validation."""
    failures = check_paths(
        root,
        [
            "core/jobs/backtest_elder_review.py",
            "core/jobs/run_elder_review.py",
            "core/jobs/export_elder_review.py",
            "core/technical/elder.py",
            "docs/elder_review_backtest.md",
            "tests/test_elder_review_backtest.py",
        ],
    )
    job_source = read_source(root / "core/jobs/backtest_elder_review.py")
    for phrase in [
        "backtest_elder_review",
        "build_elder_backtest_details",
        "calculate_forward_metrics",
        "forward_return_5d",
        "forward_return_10d",
        "forward_return_20d",
        "max_drawdown_20d",
        "max_gain_20d",
        "elder_score_group",
        "action_hint",
        "不构成交易建议",
    ]:
        if phrase not in job_source:
            failures.append(f"core/jobs/backtest_elder_review.py is missing {phrase}.")

    docs = read_source(root / "docs/elder_review_backtest.md") + read_source(root / "README.md") + read_source(root / "docs/commands_reference.md")
    for phrase in [
        "python -m core.jobs.backtest_elder_review",
        "forward_return_5d",
        "max_drawdown_20d",
        "elder_score",
        "action_hint",
        "未来函数",
    ]:
        if phrase not in docs:
            failures.append(f"Task 42 docs are missing {phrase}.")

    tests_source = read_source(root / "tests/test_elder_review_backtest.py")
    for phrase in ["forward_return", "max_drawdown", "max_gain", "elder_score_group", "action_hint", "future", "markdown", "csv"]:
        if phrase.lower() not in tests_source.lower():
            failures.append(f"tests/test_elder_review_backtest.py should cover {phrase}.")
    return failures


def check_task43(root: Path) -> list[str]:
    """Check Task 43 Elder threshold and explanation optimization."""
    failures = check_paths(
        root,
        [
            "core/technical/elder.py",
            "core/jobs/backtest_elder_review.py",
            "docs/elder_review.md",
            "docs/elder_review_backtest.md",
            "tests/test_elder_threshold_explanation.py",
            "web/streamlit_app.py",
        ],
    )
    elder_source = read_source(root / "core/technical/elder.py")
    for phrase in ["技术节奏", "不代表收益预测", "短期回撤风险", "移动止损观察信号", "追高风险"]:
        if phrase not in elder_source:
            failures.append(f"core/technical/elder.py is missing Task 43 wording: {phrase}.")

    backtest_source = read_source(root / "core/jobs/backtest_elder_review.py")
    for phrase in [
        "candidate_action_hint_summary",
        "total_score_group_summary",
        "market_stage_summary",
        "market_stage_action_hint_summary",
        "total_score_group",
        "_market_stage_by_date",
        "技术状态 / 节奏复核分",
    ]:
        if phrase not in backtest_source:
            failures.append(f"core/jobs/backtest_elder_review.py is missing Task 43 layered backtest phrase: {phrase}.")

    docs = read_source(root / "docs/elder_review.md") + read_source(root / "docs/elder_review_backtest.md")
    for phrase in ["技术状态 / 节奏复核分", "不是买入优先级", "短期回撤风险", "total_score 分层", "市场阶段分层"]:
        if phrase not in docs:
            failures.append(f"Task 43 docs are missing {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["节奏复核层", "不代表买入优先级", "短期回撤风险"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 43 wording: {phrase}.")

    tests_source = read_source(root / "tests/test_elder_threshold_explanation.py")
    for phrase in ["total_score", "market_stage", "短线过热", "技术状态", "action_hint", "排序"]:
        if phrase.lower() not in tests_source.lower():
            failures.append(f"tests/test_elder_threshold_explanation.py should cover {phrase}.")
    return failures


def check_task44(root: Path) -> list[str]:
    """Check Task 44 position pool foundation."""
    failures = check_paths(
        root,
        [
            "core/positions/position_pool.py",
            "core/jobs/import_positions.py",
            "core/jobs/export_positions.py",
            "core/reporting/positions_report.py",
            "docs/position_pool.md",
            "docs/templates/positions_import_template.csv",
            "tests/test_position_pool.py",
            "web/streamlit_app.py",
        ],
    )
    schema_source = read_source(root / "core/storage/schema.sql")
    for phrase in ["CREATE TABLE IF NOT EXISTS positions", "entry_price", "entry_total_score", "entry_elder_score", "initial_stop", "status"]:
        if phrase not in schema_source:
            failures.append(f"schema.sql is missing positions field: {phrase}.")

    source = read_source(root / "core/positions/position_pool.py")
    for phrase in [
        "create_position",
        "import_positions",
        "update_position_status",
        "build_positions_dataframe",
        "active position",
        "pnl_pct",
        "holding_days",
        "active",
        "reduced",
        "exited",
    ]:
        if phrase not in source:
            failures.append(f"core/positions/position_pool.py is missing {phrase}.")

    jobs_source = read_source(root / "core/jobs/import_positions.py") + read_source(root / "core/jobs/export_positions.py")
    for phrase in ["import_positions", "export_positions", "--file", "--format", "markdown"]:
        if phrase not in jobs_source:
            failures.append(f"Task 44 jobs are missing {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["持仓池", "entry_price", "latest_close", "pnl_pct", "holding_days"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 44 phrase: {phrase}.")

    docs = read_source(root / "docs/position_pool.md") + read_source(root / "README.md") + read_source(root / "docs/commands_reference.md")
    for phrase in ["python -m core.jobs.import_positions", "python -m core.jobs.export_positions", "active / reduced / exited", "不自动交易"]:
        if phrase not in docs:
            failures.append(f"Task 44 docs are missing {phrase}.")

    tests_source = read_source(root / "tests/test_position_pool.py")
    for phrase in ["create_position", "active position", "update_position_status", "latest_close", "pnl_pct", "export_positions", "total_score"]:
        if phrase.lower() not in tests_source.lower():
            failures.append(f"tests/test_position_pool.py should cover {phrase}.")
    return failures


def check_task45(root: Path) -> list[str]:
    """Check Task 45 position daily tracking."""
    failures = check_paths(
        root,
        [
            "core/positions/position_pool.py",
            "core/jobs/track_positions.py",
            "core/jobs/export_positions.py",
            "core/reporting/positions_report.py",
            "docs/position_tracking.md",
            "tests/test_position_tracking.py",
            "web/streamlit_app.py",
        ],
    )
    source = read_source(root / "core/positions/position_pool.py")
    for phrase in [
        "track_active_positions",
        "enrich_positions_with_tracking",
        "max_gain_pct",
        "max_drawdown_pct",
        "close_to_entry_pct",
        "latest_elder_score",
        "technical_state",
        "position_hint",
        "position_reason",
        "波动加大，需人工复核",
        "数据不足",
    ]:
        if phrase not in source:
            failures.append(f"core/positions/position_pool.py is missing Task 45 phrase: {phrase}.")

    job_source = read_source(root / "core/jobs/track_positions.py")
    for phrase in ["track_positions", "--format", "markdown", "all"]:
        if phrase not in job_source:
            failures.append(f"core/jobs/track_positions.py is missing {phrase}.")

    report_source = read_source(root / "core/reporting/positions_report.py")
    for phrase in ["max_gain_pct", "max_drawdown_pct", "latest_elder_score", "position_hint"]:
        if phrase not in report_source:
            failures.append(f"positions_report.py is missing tracking field {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["max_gain_pct", "max_drawdown_pct", "latest_elder_score", "technical_state", "position_hint", "position_reason"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 45 display field: {phrase}.")

    docs = read_source(root / "docs/position_tracking.md") + read_source(root / "README.md") + read_source(root / "docs/commands_reference.md")
    for phrase in ["python -m core.jobs.track_positions", "持仓正常", "持有观察", "波动加大，需人工复核", "不自动交易"]:
        if phrase not in docs:
            failures.append(f"Task 45 docs are missing {phrase}.")

    tests_source = read_source(root / "tests/test_position_tracking.py")
    for phrase in ["pnl_pct", "holding_days", "max_gain_pct", "max_drawdown_pct", "track_positions", "export_positions", "total_score"]:
        if phrase.lower() not in tests_source.lower():
            failures.append(f"tests/test_position_tracking.py should cover {phrase}.")
    return failures


def check_task46(root: Path) -> list[str]:
    """Check Task 46 full HS A-share universe and tradeability filters."""
    failures = check_paths(
        root,
        [
            "core/data_sources/real_universe.py",
            "core/universe/stock_pool.py",
            "core/jobs/update_real_data.py",
            "core/config/env_file.py",
            "docs/real_universe.md",
            "tests/test_real_universe_full.py",
            "web/streamlit_app.py",
        ],
    )
    config_source = read_source(root / "app/config.py") + read_source(root / ".env.example") + read_source(root / "core/config/env_file.py")
    for phrase in [
        "REAL_UNIVERSE_PRESET",
        "MIN_LISTING_DAYS",
        "MIN_AVG_AMOUNT_20D",
        "MIN_MEDIAN_AMOUNT_20D",
        "MIN_LATEST_AMOUNT",
        "MIN_TRADED_DAYS_20D",
        "INCLUDE_BSE",
    ]:
        if phrase not in config_source:
            failures.append(f"configuration is missing {phrase}.")

    universe_source = read_source(root / "core/data_sources/real_universe.py")
    for phrase in ["full", "沪深 A 股全市场，不含北交所", "build_full_a_share_universe", "contains_bse", "bse_filter_note", "BSE", "ST", "退市"]:
        if phrase not in universe_source:
            failures.append(f"core/data_sources/real_universe.py is missing {phrase}.")

    pool_source = read_source(root / "core/universe/stock_pool.py")
    for phrase in [
        "median_amount_20d",
        "latest_amount",
        "traded_days_20d",
        "min_avg_amount_20d",
        "min_median_amount_20d",
        "min_latest_amount",
        "min_traded_days_20d",
        "BSE stock",
    ]:
        if phrase not in pool_source:
            failures.append(f"core/universe/stock_pool.py is missing {phrase}.")

    update_source = read_source(root / "core/jobs/update_real_data.py")
    for phrase in ["resolve_full_a_share_universe", "AKSHARE_SAMPLE_SYMBOLS", "sample_symbols", "emit_progress"]:
        if phrase not in update_source:
            failures.append(f"core/jobs/update_real_data.py is missing {phrase}.")

    diagnose_source = read_source(root / "core/jobs/diagnose_update_batch.py")
    if 'return [], "REAL_UNIVERSE_PRESET=full"' in diagnose_source:
        failures.append("diagnose_update_batch.py must not silently return [] for full mode.")
    for phrase in ["resolve_full_a_share_universe", "raw_symbol_count", "excluded_bse_count", "bse_filter_note", "base_universe_count", "AKShare 基础股票列表获取失败"]:
        if phrase not in diagnose_source:
            failures.append(f"core/jobs/diagnose_update_batch.py is missing full diagnostic phrase: {phrase}.")

    docs = read_source(root / "docs/real_universe.md") + read_source(root / "README.md") + read_source(root / "docs/commands_reference.md")
    for phrase in ["mini / small / medium", "full", "沪深 A 股全市场，不含北交所", "近 20 日平均成交额", "复牌后"]:
        if phrase not in docs:
            failures.append(f"Task 46 docs are missing {phrase}.")

    tests_source = read_source(root / "tests/test_real_universe_full.py").lower()
    for phrase in ["full", "akshare_sample_symbols", "contains_bse", "数据源未包含北交所", "bse", "st", "退市", "avg amount", "median amount", "latest amount", "traded days", "total_score", "validate_env_updates", "diagnose_update_batch"]:
        if phrase.lower() not in tests_source:
            failures.append(f"tests/test_real_universe_full.py should cover {phrase}.")
    return failures


def check_task47(root: Path) -> list[str]:
    """Check Task 47 full-universe update stability support."""
    failures = check_paths(
        root,
        [
            "core/jobs/update_real_data.py",
            "core/jobs/diagnose_update_batch.py",
            "tests/test_full_update_stability.py",
            "docs/real_universe.md",
        ],
    )
    config_source = read_source(root / "app/config.py") + read_source(root / ".env.example") + read_source(root / "core/config/env_file.py")
    for phrase in [
        "FULL_UPDATE_BATCH_SIZE",
        "FULL_UPDATE_LOOKBACK_DAYS",
        "FULL_UPDATE_MAX_RETRIES",
        "FULL_UPDATE_SLEEP_SECONDS",
        "FULL_UPDATE_RESUME",
        "FULL_UPDATE_MAX_SYMBOLS",
        "FULL_UPDATE_MAX_BATCHES",
        "ENABLE_STOCK_BASIC_ENRICHMENT",
        "FULL_ENABLE_STOCK_BASIC_ENRICHMENT",
        "ENABLE_VALUATION_ENRICHMENT",
        "FULL_ENABLE_VALUATION_ENRICHMENT",
    ]:
        if phrase not in config_source:
            failures.append(f"Task 47 configuration is missing {phrase}.")

    update_source = read_source(root / "core/jobs/update_real_data.py")
    for phrase in [
        "_build_symbol_update_plan",
        "_resolve_full_stock_basic_for_update",
        "_effective_update_start_date",
        "daily_basic",
        "adj_factor",
        "initial_update_symbols",
        "incremental_update_symbols",
        "symbol_start_dates",
        "_should_run_stock_basic_enrichment",
        "_should_run_valuation_enrichment",
        "full_enable_stock_basic_enrichment",
        "full_enable_valuation_enrichment",
        "_effective_max_symbols",
        "_effective_max_batches",
        "_limit_symbols",
        "full_universe_count",
        "pending_queue_count",
        "planned_count",
        "update_failures",
        "empty_data",
        "temporarily_unavailable",
        "_effective_batch_size",
        "_effective_max_retries",
        "_effective_sleep_seconds",
        "skipped_symbols",
        "completion_rate",
        "FULL_UNIVERSE_LABEL",
    ]:
        if phrase not in update_source:
            failures.append(f"core/jobs/update_real_data.py is missing Task 47 phrase: {phrase}.")
    if "raw_stock_basic = client.get_stock_basic()" in update_source.split("if _use_full_universe", 1)[0]:
        failures.append("full mode should not call generic client.get_stock_basic before resolving the full universe.")

    akshare_source = read_source(root / "core/data_sources/akshare_client.py")
    for phrase in ["get_full_a_share_basic_excluding_bse", "_fetch_eastmoney_hs_basic_list", "push2.eastmoney.com/api/qt/clist/get", "--max-time"]:
        if phrase not in akshare_source:
            failures.append(f"akshare_client.py is missing full basic list phrase: {phrase}.")

    diagnose_source = read_source(root / "core/jobs/diagnose_update_batch.py")
    for phrase in ["stale_symbols", "stale_symbol_count", "update_failed_count", "empty_data_symbols", "update_failures", "最新行情不足", "max_daily_basic_date", "max_adj_factor_date", "get_full_a_share_basic_excluding_bse", "bse_filter_note"]:
        if phrase not in diagnose_source:
            failures.append(f"core/jobs/diagnose_update_batch.py is missing Task 47 phrase: {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["全市场数据未完成", "coverage_rate", "missing_symbol_count", "stale_symbol_count", "bse_filter_note", "结果仅基于已有行情股票"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 47 display phrase: {phrase}.")

    tests_source = read_source(root / "tests/test_full_update_stability.py").lower()
    schema_source = read_source(root / "core/storage/schema.sql") + read_source(root / "core/storage/duckdb_store.py")
    for phrase in ["update_failures", "target_end_date", "attempt_count"]:
        if phrase not in schema_source:
            failures.append(f"storage schema should support persistent update failures: {phrase}.")

    for phrase in ["batch", "resume", "retry", "progress", "skipped", "total_score", "diagnose_update_batch", "global_max", "initial_update_symbols", "build_date_status", "stock_individual_info_em", "blockingbasicenrichmentclient", "stock_zh_a_spot_em", "blockingvaluationenrichmentclient", "stock_info_a_code_name", "brokenfullbasiclistclient", "stock_basic cache", "does_not_shrink", "full_universe_count", "pending_queue_count", "planned_count", "emptyfirstsymbolclient", "empty_data", "deprioritizes", "limitedsymbolssettings", "hardfailpriceclient", "missing daily_price"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_full_update_stability.py should cover {phrase}.")

    docs = (
        read_source(root / "docs/real_universe.md")
        + read_source(root / "docs/commands_reference.md")
        + read_source(root / "README.md")
    )
    for phrase in ["FULL_UPDATE_BATCH_SIZE", "FULL_UPDATE_RESUME", "FULL_UPDATE_MAX_SYMBOLS", "FULL_UPDATE_MAX_BATCHES", "ENABLE_STOCK_BASIC_ENRICHMENT", "FULL_ENABLE_STOCK_BASIC_ENRICHMENT", "ENABLE_VALUATION_ENRICHMENT", "FULL_ENABLE_VALUATION_ENRICHMENT", "PE/PB", "断点续跑", "失败重试", "全市场更新可能耗时较长"]:
        if phrase not in docs:
            failures.append(f"Task 47 docs are missing {phrase}.")
    return failures


def check_task48(root: Path) -> list[str]:
    """Check Task 48 watchlist candidate tracking support."""
    failures = check_paths(
        root,
        [
            "core/jobs/refresh_watchlist_from_selection.py",
            "core/jobs/track_watchlist.py",
            "core/jobs/diagnose_watchlist.py",
            "core/jobs/export_watchlist_tracking.py",
            "core/review/tracking.py",
            "core/reporting/watchlist_tracking_report.py",
            "tests/test_watchlist_candidate_tracking.py",
            "docs/watchlist_candidate_tracking.md",
        ],
    )
    schema_source = read_source(root / "core/storage/schema.sql") + read_source(root / "core/storage/duckdb_store.py")
    for phrase in ["watchlist_daily_snapshots", "watchlist_events", "selected_count_5d", "consecutive_selected_days", "watch_status"]:
        if phrase not in schema_source:
            failures.append(f"Task 48 storage support is missing {phrase}.")

    tracking_source = read_source(root / "core/review/tracking.py")
    for phrase in [
        "WATCH_STATUS_LABELS",
        "new_candidate",
        "active_watch",
        "strong_watch",
        "wait_pullback",
        "near_buy_zone",
        "overheated",
        "weakening",
        "invalidated",
        "bought",
        "removed",
        "refresh_watchlist_from_selection",
        "read_watchlist_daily_snapshots",
        "read_watchlist_events",
        "rank_change",
        "total_score_change",
        "selected_count_10d",
        "watchlist_events",
    ]:
        if phrase not in tracking_source:
            failures.append(f"core/review/tracking.py is missing Task 48 phrase: {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["观察池跟踪", "enrich_selection_with_watchlist_status", "summarize_watchlist_snapshot", "suggest_add_to_watchlist", "selected_count_5d"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 48 phrase: {phrase}.")

    tests_source = read_source(root / "tests/test_watchlist_candidate_tracking.py").lower()
    for phrase in ["temporary duckdb", "mock", "not duplicate", "top-n", "selected_count_5d", "consecutive", "rank", "events", "export_watchlist_tracking", "streamlit"]:
        if phrase not in tests_source:
            failures.append(f"tests/test_watchlist_candidate_tracking.py should cover {phrase}.")

    docs = read_source(root / "docs/watchlist_candidate_tracking.md") + read_source(root / "README.md") + read_source(root / "docs/commands_reference.md")
    for phrase in [
        "refresh_watchlist_from_selection",
        "track_watchlist",
        "export_watchlist_tracking",
        "new_candidate",
        "strong_watch",
        "wait_pullback",
        "观察池",
        "仅供个人研究使用，不自动交易",
    ]:
        if phrase not in docs:
            failures.append(f"Task 48 docs are missing {phrase}.")
    return failures


def check_task49(root: Path) -> list[str]:
    """Check Streamlit and DuckDB startup stability guardrails."""
    failures = check_paths(
        root,
        [
            "core/jobs/diagnose_streamlit_startup.py",
            "scripts/start_streamlit_safe.py",
            "scripts/verify_task.py",
            "tests/test_streamlit_startup_stability.py",
            "tests/test_duckdb_store.py",
            "tests/test_streamlit_app.py",
            "tests/test_entry_zones.py",
            "core/entry_zones/calculator.py",
            "core/jobs/calculate_entry_zones.py",
            "core/jobs/diagnose_entry_zones.py",
            "core/jobs/export_entry_zone_report.py",
            "docs/entry_zones.md",
        ],
    )
    store_source = read_source(root / "core/storage/duckdb_store.py")
    for phrase in [
        "DuckDBStoreLockedError",
        "DUCKDB_LOCK_MESSAGE",
        "is_duckdb_lock_error",
        "friendly_duckdb_error",
        "read_only=True",
        "Conflicting lock",
    ]:
        if phrase not in store_source:
            failures.append(f"duckdb_store.py is missing Task 49 stability phrase: {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in [
        "_render_database_status",
        "_render_section",
        "_safe_load_dashboard_tables",
        "_lightweight_database_metrics",
        "_apply_lightweight_database_metrics",
        "_database_status",
        "configured_symbol_count",
        "priced_symbol_count",
        "coverage_rate",
        "尚未生成本地选股结果",
        "报告中存在候选结果，但尚未写入 DuckDB",
        "DuckDB 被锁定",
        "lsof",
        "fileprovider",
    ]:
        if phrase.lower() not in streamlit_source.lower():
            failures.append(f"web/streamlit_app.py is missing Task 49 stability phrase: {phrase}.")
    forbidden_startup_calls = ["update_real_data(", "refresh_watchlist_from_selection(", "track_watchlist(", "run_daily_workflow("]
    load_section = streamlit_source.split("def load_dashboard_data", 1)[-1].split("def _computed_real_dashboard_data", 1)[0]
    for phrase in forbidden_startup_calls:
        if phrase in load_section:
            failures.append(f"load_dashboard_data should not auto-run heavy task: {phrase}")

    diagnose_source = read_source(root / "core/jobs/diagnose_streamlit_startup.py")
    for phrase in ["lsof", "read_only=True", "stock_basic", "daily_price", "8501", "FileProvider", "DuckDB is locked"]:
        if phrase not in diagnose_source:
            failures.append(f"diagnose_streamlit_startup.py is missing {phrase}.")

    starter_source = read_source(root / "scripts/start_streamlit_safe.py")
    for phrase in ["--server.fileWatcherType", "none", "--kill-stale", "--dry-run", "diagnose_streamlit_startup"]:
        if phrase not in starter_source:
            failures.append(f"start_streamlit_safe.py is missing {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["pytest", "check_project.py", "diagnose_streamlit_startup", "task49"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py is missing {phrase}.")

    selection_source = read_source(root / "core/jobs/run_daily_selection.py")
    for phrase in ["strategy_result_written_rows", "factor_scores_written_rows", "local_display_selection_count", "_replace_strategy_result_for_date", "upsert_dataframe(\"factor_scores\""]:
        if phrase not in selection_source:
            failures.append(f"run_daily_selection.py is missing Task 49A persistence phrase: {phrase}.")

    workflow_source = read_source(root / "core/jobs/run_daily_workflow.py")
    if "local_display_selection_count" not in workflow_source:
        failures.append("run_daily_workflow.py should check local_display_selection_count for real selection success.")

    tests_source = (
        read_source(root / "tests/test_streamlit_startup_stability.py")
        + read_source(root / "tests/test_duckdb_store.py")
        + read_source(root / "tests/test_streamlit_app.py")
        + read_source(root / "tests/test_real_data_e2e_validation.py")
        + read_source(root / "tests/test_daily_workflow_summary_report.py")
        + read_source(root / "tests/test_entry_zones.py")
    ).lower()
    for phrase in ["locked", "read_only", "dry-run", "friendly", "render_section", "database_locked", "real_universe_preset", "configured_symbol_count", "strategy_result", "local_display_selection_count", "factor_scores_written_rows"]:
        if phrase not in tests_source:
            failures.append(f"Task 49 tests should cover {phrase}.")

    entry_source = read_source(root / "core/entry_zones/calculator.py")
    for phrase in ["ema13", "ema22", "ema60", "support_20d", "support_60d", "resistance_20d", "resistance_60d", "atr_14", "entry_low", "entry_high", "stop_loss", "target_price", "reward_risk_ratio", "chase_risk", "entry_zone_status"]:
        if phrase not in entry_source:
            failures.append(f"entry zone calculator is missing {phrase}.")

    schema_source = read_source(root / "core/storage/schema.sql")
    if "entry_zone_snapshots" not in schema_source:
        failures.append("schema.sql is missing entry_zone_snapshots.")

    streamlit_source_lower = streamlit_source.lower()
    for phrase in ["买入区间分析", "entry_zone_snapshots", "enrich_with_entry_zone_fields"]:
        if phrase.lower() not in streamlit_source_lower:
            failures.append(f"web/streamlit_app.py is missing entry zone UI phrase: {phrase}.")

    command_source = read_source(root / "core/runtime/command_runner.py")
    for phrase in ["calculate_entry_zones", "diagnose_entry_zones", "export_entry_zone_report"]:
        if phrase not in command_source:
            failures.append(f"command_runner.py is missing {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["calculate_entry_zones", "diagnose_entry_zones", "export_entry_zone_report", "run_daily_workflow", "--skip-update"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task49 is missing {phrase}.")

    docs = read_source(root / "README.md") + read_source(root / "docs/commands_reference.md") + read_source(root / "docs/entry_zones.md")
    for phrase in ["买入区间", "支撑阻力", "止损位", "不自动交易"]:
        if phrase not in docs:
            failures.append(f"Task 49 docs are missing {phrase}.")
    return failures


def check_task50(root: Path) -> list[str]:
    """Check external simulated position import and matching workflow."""
    failures = check_paths(
        root,
        [
            "core/external_positions/importer.py",
            "core/jobs/generate_external_position_template.py",
            "core/jobs/import_external_trades.py",
            "core/jobs/import_external_positions.py",
            "core/jobs/match_external_positions.py",
            "core/jobs/diagnose_external_positions.py",
            "core/jobs/export_external_position_report.py",
            "tests/test_external_positions.py",
            "docs/external_positions.md",
        ],
    )

    schema_source = read_source(root / "core/storage/schema.sql")
    for phrase in ["external_trades", "external_position_snapshots", "external_import_batches"]:
        if phrase not in schema_source:
            failures.append(f"schema.sql is missing {phrase}.")

    importer_source = read_source(root / "core/external_positions/importer.py")
    for phrase in [
        "normalize_ts_code",
        "unsupported_bse",
        "parse_number",
        "import_external_trades_frame",
        "import_external_positions_frame",
        "match_external_positions",
        "hit_stop_loss",
        "near_stop_loss",
        "hit_target",
        "chased_high",
        "entered_in_zone",
        "insufficient_data",
        "unknown_symbol",
    ]:
        if phrase not in importer_source:
            failures.append(f"external position importer is missing {phrase}.")

    command_source = read_source(root / "core/runtime/command_runner.py")
    for phrase in [
        "generate_external_position_template",
        "import_external_trades",
        "import_external_positions",
        "match_external_positions",
        "diagnose_external_positions",
        "export_external_position_report",
    ]:
        if phrase not in command_source:
            failures.append(f"command_runner.py is missing {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["外部模拟持仓导入", "external_position_snapshots", "parse_external_position_text", "latest_external_positions"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 50 phrase: {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in [
        "task50",
        "generate_external_position_template",
        "/tmp/a_stock_assistant_task50_templates",
        "diagnose_external_positions",
        "export_external_position_report",
        "run_daily_workflow",
        "clean_generated_reports",
    ]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task50 is missing {phrase}.")

    tests_source = read_source(root / "tests/test_external_positions.py")
    for phrase in [
        "normalize_ts_code",
        "unsupported_bse",
        "parse_number",
        "import_external_trades_frame",
        "import_external_positions_frame",
        "match_external_positions",
        "hit_stop_loss",
        "near_stop_loss",
        "hit_target",
        "chased_high",
        "entered_in_zone",
        "unknown_symbol",
        "external_positions_to_dataframe",
        "parse_external_position_text",
    ]:
        if phrase not in tests_source:
            failures.append(f"Task 50 tests should cover {phrase}.")

    docs = read_source(root / "README.md") + read_source(root / "docs/commands_reference.md") + read_source(root / "docs/external_positions.md")
    for phrase in ["外部模拟持仓", "导入模板", "买入区间", "止损", "cookie", "不自动交易"]:
        if phrase not in docs:
            failures.append(f"Task 50 docs are missing {phrase}.")
    return failures


def check_task51(root: Path) -> list[str]:
    """Check full-universe batch update UI and datasource preflight support."""
    failures = check_paths(
        root,
        [
            "core/runtime/data_source_preflight.py",
            "core/jobs/preflight_data_source.py",
            "core/jobs/run_full_batch_update.py",
            "tests/test_full_batch_update_ui_precheck.py",
            "web/streamlit_app.py",
        ],
    )
    preflight_source = read_source(root / "core/runtime/data_source_preflight.py")
    for phrase in [
        "urllib.request.getproxies",
        "push2his.eastmoney.com",
        "secid=0.000001",
        "rc",
        "klines",
        "DuckDB is locked by another process",
        "FileProvider",
        "curl",
        "--max-time",
    ]:
        if phrase not in preflight_source:
            failures.append(f"data_source_preflight.py is missing {phrase}.")

    update_source = read_source(root / "core/jobs/update_real_data.py")
    for phrase in ["full_update_mode", "full_update_skip_empty_unavailable", "missing_first", "stale_first", "本次未处理"]:
        if phrase not in update_source:
            failures.append(f"update_real_data.py is missing Task 51 phrase: {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in [
        "全市场批量补数据",
        "build_full_batch_update_args",
        "summarize_full_batch_update_result",
        "run_full_batch_update",
        "preflight_data_source",
        "本次未处理数量",
        "本次未纳入计划",
        "东方财富 K 线接口",
    ]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 51 phrase: {phrase}.")

    command_source = read_source(root / "core/runtime/command_runner.py")
    for phrase in ["run_full_batch_update", "preflight_data_source"]:
        if phrase not in command_source:
            failures.append(f"command_runner.py is missing {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["task51", "preflight_data_source", "--skip-network", "run_full_batch_update", "--dry-run", "clean_generated_reports"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task51 is missing {phrase}.")

    tests_source = read_source(root / "tests/test_full_batch_update_ui_precheck.py")
    for phrase in [
        "getproxies",
        "check_eastmoney_kline",
        "precheck_failure",
        "duckdb_lock",
        "build_full_batch_update_args",
        "summarize_full_batch_update_result",
        "本次未处理",
        "run_full_batch_update",
    ]:
        if phrase not in tests_source:
            failures.append(f"Task 51 tests should cover {phrase}.")
    return failures


def check_task52(root: Path) -> list[str]:
    """Check Elder review date handling and Streamlit full-history loading."""
    failures = check_paths(
        root,
        [
            "core/technical/elder.py",
            "core/jobs/run_elder_review.py",
            "web/streamlit_app.py",
            "tests/test_elder_review_date_handling.py",
        ],
    )
    elder_source = read_source(root / "core/technical/elder.py")
    for phrase in [
        "review_date",
        "price_latest_trade_date",
        "price_row_count",
        "price_date_note",
        "使用该股票最新可用日期",
        "周线样本不足",
        "candidate_date",
        "cutoff_date",
    ]:
        if phrase not in elder_source:
            failures.append(f"core/technical/elder.py is missing Task 52 phrase: {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in [
        "_safe_read_dashboard_price_history",
        "_safe_read_price_history_for_codes",
        "_dashboard_focus_codes",
        "format_elder_review_display",
        "display_order",
        "candidate_rank",
        "rank 为今日选股原始排名",
        "complete history",
        "日线数据不足",
    ]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 52 dashboard phrase: {phrase}.")

    starter_source = read_source(root / "scripts/start_streamlit_safe.py")
    for phrase in [
        "--server.headless",
        "true",
        "build_open_command",
        "_open_browser_once",
        "_wait_for_port",
        "未启动新的 Streamlit，只打开已有页面一次",
    ]:
        if phrase not in starter_source:
            failures.append(f"start_streamlit_safe.py is missing Task 52 launcher phrase: {phrase}.")

    mac_launcher_source = read_source(root / "scripts/mac/A股选股助手.command")
    if "python scripts/start_streamlit_safe.py --port 8501" not in mac_launcher_source:
        failures.append("Mac launcher should delegate to start_streamlit_safe.py.")
    if 'open "$APP_URL"' in mac_launcher_source or "streamlit run web/streamlit_app.py" in mac_launcher_source:
        failures.append("Mac launcher should not both open URL and run Streamlit directly.")

    export_source = read_source(root / "core/jobs/export_selection_review.py")
    for phrase in ["review_date", "price_date_note", "merge(review[available], on=[\"ts_code\"]"]:
        if phrase not in export_source:
            failures.append(f"export_selection_review.py is missing Task 52 Elder merge phrase: {phrase}.")

    tests_source = (
        read_source(root / "tests/test_elder_review_date_handling.py")
        + read_source(root / "tests/test_streamlit_startup_stability.py")
        + read_source(root / "tests/test_mac_local_console_docs.py")
        + read_source(root / "tests/test_streamlit_app.py")
    )
    for phrase in [
        "global latest",
        "日线数据不足",
        "周线样本不足",
        "_safe_read_dashboard_price_history",
        "track_watchlist",
        "total_score",
        "headless",
        "display_order",
        "candidate_rank",
    ]:
        if phrase not in tests_source:
            failures.append(f"Task 52 tests should cover {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["task52", "check_task.py", "clean_generated_reports"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task52 is missing {phrase}.")
    return failures


def check_task53(root: Path) -> list[str]:
    """Check daily research workbook export support."""
    failures = check_paths(
        root,
        [
            "core/jobs/export_daily_research_workbook.py",
            "tests/test_daily_research_workbook.py",
            "scripts/verify_task.py",
            "web/streamlit_app.py",
        ],
    )
    export_source = read_source(root / "core/jobs/export_daily_research_workbook.py")
    for phrase in [
        "SHEET_NAMES",
        "00_摘要",
        "01_今日候选",
        "02_埃尔德复核",
        "03_买入区间",
        "04_观察池",
        "05_观察池跟踪",
        "06_外部模拟持仓",
        "07_风险提示",
        "08_数据质量",
        "09_参数配置",
        "10_说明",
        "read_only=True",
        "display_order",
        "candidate_rank",
        "SENSITIVE_KEYWORDS",
        "openpyxl",
        "export_daily_research_workbook",
    ]:
        if phrase not in export_source:
            failures.append(f"export_daily_research_workbook.py is missing {phrase}.")
    for forbidden in [
        "from core.jobs.update_real_data",
        "from core.jobs.run_daily_workflow",
        "from core.jobs.run_daily_selection",
        "update_real_data(",
        "run_daily_workflow(",
        "run_daily_selection(",
    ]:
        if forbidden in export_source:
            failures.append(f"Workbook export should not call heavy command: {forbidden}.")

    command_source = read_source(root / "core/runtime/command_runner.py")
    if "export_daily_research_workbook" not in command_source:
        failures.append("command_runner.py is missing export_daily_research_workbook.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["导出今日研究工作簿 Excel", "export_daily_research_workbook"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 53 phrase: {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["task53", "export_daily_research_workbook", "/tmp/a_stock_assistant_task53/daily_research.xlsx"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task53 is missing {phrase}.")
    if "reports/daily_research" in verify_source:
        failures.append("verify_task.py task53 should not write daily research workbook into reports/.")

    tests_source = read_source(root / "tests/test_daily_research_workbook.py")
    for phrase in [
        "SHEET_NAMES",
        "display_order",
        "candidate_rank",
        "SECRET",
        "read_only",
        "/tmp/a_stock_assistant_task53",
    ]:
        if phrase not in tests_source:
            failures.append(f"Task 53 tests should cover {phrase}.")

    docs = read_source(root / "README.md") + read_source(root / "docs/commands_reference.md")
    for phrase in ["每日研究工作簿", "export_daily_research_workbook", "Excel"]:
        if phrase not in docs:
            failures.append(f"Task 53 docs are missing {phrase}.")

    setup_source = read_source(root / "setup.py") + read_source(root / "build_backend.py")
    if "openpyxl" not in setup_source:
        failures.append("Packaging metadata should include openpyxl for xlsx export.")
    return failures


def check_task54(root: Path) -> list[str]:
    """Check Streamlit UI clarity and workbook export feedback."""
    failures = check_paths(
        root,
        [
            "web/streamlit_app.py",
            "tests/test_streamlit_app.py",
            "scripts/verify_task.py",
        ],
    )
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in [
        "prepare_display_table",
        "display_dataframe",
        "hide_index=True",
        "display_order",
        "candidate_rank",
        "watch_today_rank",
        "DISPLAY_COLUMN_LABELS",
        "序号为当前页面当前排序后的显示顺序",
        "本页用于补充 / 更新 full 股票池行情数据",
        "_export_workbook_button",
        "_extract_workbook_output_path",
        "下载 Excel 工作簿",
        "导出成功",
        "文件大小",
    ]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 54 phrase: {phrase}.")
    for forbidden in [
        "保存并更新数据",
        '"更新真实数据"',
        '"一键运行"',
        "原始选股排名",
        "candidate_rank 为",
        "系统原始选股排名",
        "对应股票的原始选股排名",
    ]:
        if forbidden in streamlit_source:
            failures.append(f"web/streamlit_app.py should remove ambiguous update entrypoint: {forbidden}.")
    command_source = read_source(root / "core/runtime/command_runner.py")
    for phrase in ["run_full_batch_update", "preflight_data_source"]:
        if phrase not in command_source:
            failures.append(f"command_runner.py is missing allowed command: {phrase}.")
    preflight_source = read_source(root / "core/runtime/data_source_preflight.py")
    for phrase in [
        "push2his.eastmoney.com/api/qt/stock/kline/get",
        "secid=0.000001",
        "User-Agent",
        "Referer",
        "headers_present",
        "curl_returncode",
        "used_url",
        "klines",
    ]:
        if phrase not in preflight_source and phrase != "User-Agent":
            failures.append(f"data_source_preflight.py is missing Task 54 preflight phrase: {phrase}.")
        if phrase == "User-Agent" and "EASTMONEY_USER_AGENT" not in preflight_source:
            failures.append("data_source_preflight.py is missing Eastmoney User-Agent header.")
    web_sources = "\n".join(read_source(path) for path in (root / "web").rglob("*.py"))
    if "use_container_width" in web_sources:
        failures.append("web/ should not use deprecated Streamlit use_container_width.")

    tests_source = read_source(root / "tests/test_streamlit_app.py")
    for phrase in [
        "test_streamlit_tables_hide_raw_index",
        "test_display_order_continuous_after_sort",
        "test_rank_columns_are_renamed_for_display",
        "test_elder_review_has_source_and_display_order",
        "test_update_entrypoints_are_consolidated",
        "test_export_workbook_page_feedback",
        "test_export_does_not_run_workflow_or_update",
        "test_eastmoney_precheck_curl_52_reports_diagnostics",
    ]:
        all_tests = tests_source + read_source(root / "tests/test_full_batch_update_ui_precheck.py")
        if phrase not in all_tests:
            failures.append(f"tests/test_streamlit_app.py is missing Task 54 test: {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["task54", "pytest", "check_project.py", "check_task.py"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task54 is missing {phrase}.")
    for forbidden in ["export_daily_research_workbook\", \"--output", "run_daily_workflow", "update_real_data"]:
        task54_block = verify_source.split('"task54":', 1)[-1].split("]", 1)[0] if '"task54":' in verify_source else ""
        if forbidden in task54_block:
            failures.append(f"verify_task.py task54 should not create reports or run update/workflow: {forbidden}.")
    return failures


def check_task55(root: Path) -> list[str]:
    """Check the core logic guide and Streamlit download entry."""
    failures = check_paths(
        root,
        [
            "docs/user_guides/core_logic_guide.md",
            "web/streamlit_app.py",
            "tests/test_core_logic_guide.py",
            "scripts/verify_task.py",
        ],
    )

    guide = read_source(root / "docs/user_guides/core_logic_guide.md")
    for phrase in [
        "A 股选股辅助系统：核心计算逻辑与公式说明",
        "中文名称（英文名）",
        "综合分（total_score）",
        "趋势分（trend_score）",
        "动量分（momentum_score）",
        "流动性分（liquidity_score）",
        "基本面分（fundamental_score）",
        "波动分（volatility_score）",
        "仅供个人研究使用",
        "不自动交易",
        "埃尔德分（elder_score）",
        "操作提示（action_hint）",
        "复核原因（elder_reason）",
        "周线趋势（weekly_trend）",
        "日线回调（daily_pullback）",
        "不覆盖综合分（total_score）",
        "不代表买入优先级",
        "Excel 默认应避免导出排名字段（rank）",
        "序号只代表当前 Sheet 显示顺序",
        "外部模拟持仓",
        "数据质量",
        "total_score =",
        "0.30 * 趋势分（trend_score）",
        "20日收益率（return_20d）= 当前收盘价 / 20 个交易日前收盘价 - 1",
        "20日平均成交额（avg_amount_20d）= 最近 20 个交易日成交额均值",
        "市盈率倒数指标（pe_score）= 1 / 市盈率（pe）",
        "20日波动率（volatility_20d）",
        "score = (value - min_value) / (max_value - min_value) * 100",
        "## 8. 埃尔德复核计算公式",
        "周线趋势改善：+35",
        "## 9. 买入区间计算公式",
        "盈亏比（reward_risk_ratio）= 收益距离（reward） / 风险距离（risk）",
        "## 10. 普通用户如何使用这些公式",
        "不使用排名字段（rank）或序号作为买入优先级",
    ]:
        if phrase not in guide:
            failures.append(f"core_logic_guide.md is missing phrase: {phrase}.")
    for forbidden in [
        "来自趋势相关指标。",
        "来自动量信息",
        "来自成交额、换手率等流动性信息。",
        "来自 ROE、PE、PB、营收增长等基础面或估值字段。",
        "来自波动率、回撤等风险相关指标。",
    ]:
        if forbidden in guide:
            failures.append(f"core_logic_guide.md still contains generic wording: {forbidden}.")
    for forbidden in ["源码位置索引", "core/jobs/", "core/factors/", "::"]:
        if forbidden in guide:
            failures.append(f"core_logic_guide.md should not include source index/path detail: {forbidden}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in [
        "CORE_LOGIC_GUIDE_PATH",
        "docs",
        "user_guides",
        "core_logic_guide.md",
        "核心说明文件",
        "下载核心逻辑说明",
        "A股选股辅助系统_核心逻辑说明.md",
        "st.download_button",
    ]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing core guide download phrase: {phrase}.")
    if "export_logic_docs" in streamlit_source or "write_text" in streamlit_source:
        failures.append("Streamlit download entry should read the committed guide without generating artifacts.")

    tests_source = read_source(root / "tests/test_core_logic_guide.py")
    for phrase in [
        "test_core_logic_guide_exists",
        "test_core_logic_guide_mentions_stock_selection_concepts",
        "test_core_logic_guide_mentions_elder_review_concepts",
        "test_core_logic_guide_mentions_excel_and_no_rank_policy",
        "test_streamlit_has_core_logic_doc_download",
        "test_no_algorithm_changes",
        "test_core_logic_guide_has_formula_details",
        "test_core_logic_guide_omits_source_location_index",
        "test_core_logic_guide_has_elder_rule_table",
        "test_core_logic_guide_has_entry_zone_calculation",
        "test_core_logic_guide_not_generic",
        "test_core_logic_guide_has_user_formula_usage_section",
        "test_core_logic_guide_defines_chinese_first_field_naming",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_core_logic_guide.py is missing test: {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["task55", "pytest", "check_project.py", "check_task.py"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task55 is missing {phrase}.")
    task55_block = verify_source.split('"task55":', 1)[-1].split("]", 1)[0] if '"task55":' in verify_source else ""
    for forbidden in ["run_daily_workflow", "update_real_data", "export_daily_research_workbook", "reports", "data/a_stock_assistant.duckdb"]:
        if forbidden in task55_block:
            failures.append(f"verify_task.py task55 should not create runtime artifacts: {forbidden}.")
    return failures


def check_task56(root: Path) -> list[str]:
    """Check daily research workbook field clarity and no-rank export policy."""
    failures = check_paths(
        root,
        [
            "core/jobs/export_daily_research_workbook.py",
            "tests/test_daily_research_workbook.py",
            "scripts/verify_task.py",
        ],
    )
    export_source = read_source(root / "core/jobs/export_daily_research_workbook.py")
    for phrase in [
        "COLUMN_LABELS",
        "RANK_COLUMNS",
        "综合分（total_score）",
        "趋势分（trend_score）",
        "动量分（momentum_score）",
        "流动性分（liquidity_score）",
        "基本面分（fundamental_score）",
        "波动分（volatility_score）",
        "埃尔德分（elder_score）",
        "操作提示（action_hint）",
        "买入区间下限（entry_low）",
        "止损价（stop_loss）",
        "盈亏比（reward_risk_ratio）",
        "_drop_rank_columns",
        "_prepare_for_excel",
        "基本面分（fundamental_score）缺失记录数",
        "默认不导出 rank / 排名字段",
        "序号只代表当前 Sheet 当前显示顺序，不代表买入优先级",
        "中文名称（英文名）",
        "SENSITIVE_VALUE_MARKERS",
    ]:
        if phrase not in export_source:
            failures.append(f"export_daily_research_workbook.py is missing Task 56 phrase: {phrase}.")
    for forbidden in [
        "candidate_rank 保留今日选股原始排名",
        "字段缺失：{'fundamental_score'",
        "字段缺失：fundamental_score",
    ]:
        if forbidden in export_source:
            failures.append(f"export_daily_research_workbook.py still contains misleading Task 56 wording: {forbidden}.")

    tests_source = read_source(root / "tests/test_daily_research_workbook.py")
    for phrase in [
        "test_workbook_has_no_rank_columns_by_default",
        "test_workbook_uses_chinese_name_with_english_field_labels",
        "test_candidate_sheet_fields",
        "test_elder_review_sheet_fields",
        "test_watchlist_sheet_hides_rank_fields",
        "test_watchlist_tracking_sheet_hides_rank_fields",
        "test_data_quality_missing_values_wording",
        "test_explanation_sheet_defines_no_rank_policy",
        "test_workbook_filters_sensitive_settings",
        "test_no_algorithm_changes",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_daily_research_workbook.py is missing Task 56 coverage: {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["task56", "export_daily_research_workbook", "/tmp/a_stock_assistant_task56/daily_research.xlsx"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task56 is missing {phrase}.")
    if "reports/daily_research" in verify_source:
        failures.append("verify_task.py task56 should not write workbook output into reports/.")

    docs_source = read_source(root / "docs/commands_reference.md")
    for phrase in ["默认不导出 rank", "中文名称（英文名）", "序号只代表当前 Sheet 当前显示顺序"]:
        if phrase not in docs_source:
            failures.append(f"docs/commands_reference.md is missing Task 56 wording: {phrase}.")
    return failures


def check_task57a(root: Path) -> list[str]:
    """Check data source network diagnosis and preflight enhancement."""
    failures = check_paths(
        root,
        [
            "core/jobs/diagnose_data_source_network.py",
            "core/runtime/data_source_preflight.py",
            "core/jobs/preflight_data_source.py",
            "tests/test_data_source_network_diagnosis.py",
            "scripts/verify_task.py",
            "web/streamlit_app.py",
        ],
    )
    diag_source = read_source(root / "core/jobs/diagnose_data_source_network.py")
    for phrase in [
        "数据源网络诊断",
        "push2his.eastmoney.com",
        "secid=0.000001",
        "EASTMONEY_USER_AGENT",
        "EASTMONEY_REFERER",
        "diagnose_dns",
        "curl_ipv4",
        "curl_ipv6",
        "curl_noproxy",
        "python_default",
        "classify_diagnosis",
        "suggested_action",
        "urllib.request.getproxies",
        "scutil",
        "DuckDB",
        "手机热点",
        "json",
    ]:
        if phrase not in diag_source:
            failures.append(f"diagnose_data_source_network.py is missing Task 57A phrase: {phrase}.")
    for forbidden in ["update_real_data", "run_daily_workflow", "export_daily_research_workbook"]:
        if forbidden in diag_source:
            failures.append(f"diagnose_data_source_network.py should not run heavy task: {forbidden}.")

    preflight_source = read_source(root / "core/runtime/data_source_preflight.py") + read_source(root / "core/jobs/preflight_data_source.py")
    for phrase in ["dns_status", "ipv4_status", "ipv6_status", "suggested_action", "check_eastmoney_dns"]:
        if phrase not in preflight_source:
            failures.append(f"preflight code is missing Task 57A field: {phrase}.")

    command_source = read_source(root / "core/runtime/command_runner.py")
    if "diagnose_data_source_network" not in command_source:
        failures.append("command_runner.py is missing diagnose_data_source_network.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["运行数据源网络诊断", "diagnose_data_source_network", "数据源网络诊断"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 57A phrase: {phrase}.")

    tests_source = read_source(root / "tests/test_data_source_network_diagnosis.py")
    for phrase in [
        "test_diagnose_data_source_network_outputs_text",
        "test_diagnose_data_source_network_outputs_json",
        "test_diagnosis_masks_sensitive_proxy_values",
        "test_diagnosis_classifies_ipv4_success_ipv6_failure",
        "test_diagnosis_classifies_all_network_failures",
        "test_preflight_includes_network_diagnosis_summary_on_failure",
        "test_streamlit_has_network_diagnosis_button",
        "test_no_algorithm_changes",
    ]:
        if phrase not in tests_source:
            failures.append(f"Task 57A tests are missing {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["task57a", "diagnose_data_source_network", "--format", "json"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task57a is missing {phrase}.")

    docs_source = read_source(root / "docs/commands_reference.md")
    for phrase in ["diagnose_data_source_network", "数据源网络诊断", "Wi-Fi", "手机热点"]:
        if phrase not in docs_source:
            failures.append(f"docs/commands_reference.md is missing Task 57A wording: {phrase}.")
    return failures


def check_task57b(root: Path) -> list[str]:
    """Check scheduled 18:00 update workflow, status, launchd, and notification framework."""
    failures = check_paths(
        root,
        [
            "core/jobs/run_scheduled_daily_update.py",
            "core/jobs/refresh_data_quality_status.py",
            "core/jobs/update_market_data.py",
            "core/jobs/market_data_progress.py",
            "core/jobs/import_market_data.py",
            "core/jobs/market_data_status.py",
            "core/diagnostics/data_quality_snapshot.py",
            "core/data_sources/akshare_spot_snapshot.py",
            "core/data_sources/baostock_client.py",
            "core/jobs/install_scheduled_daily_update.py",
            "core/jobs/uninstall_scheduled_daily_update.py",
            "core/notifications/macos.py",
            "core/notifications/email.py",
            "tests/test_scheduled_daily_update.py",
            "tests/test_task57c_data_quality_snapshot.py",
            "tests/test_task57d_free_data_fallbacks.py",
            "scripts/verify_task.py",
            "web/streamlit_app.py",
        ],
    )
    scheduled_source = read_source(root / "core/jobs/run_scheduled_daily_update.py")
    for phrase in [
        "scheduled_time",
        "18:00",
        "catch_up",
        "force",
        "dry_run",
        "scheduled_daily_update_status.json",
        "scheduled_daily_update.lock",
        "run_data_source_preflight",
        "backup_local_data",
        "run_daily_workflow",
        "run_elder_review",
        "calculate_entry_zones",
        "track_watchlist",
        "export_daily_research_workbook",
        "send_macos_notification",
        "send_email_notification",
        "DuckDB is locked by another process",
        "update_limit",
        "allow_intraday",
        "intraday_warning",
        "formal_run",
        "formal_run_note",
        "formal_success_date",
        "update_mode",
        "daily_incremental",
        "full_backfill",
        "recent_days",
        "max_update_symbols",
        "update_failed_symbol_count",
        "update_continued_after_partial_failure",
        "preflight_allows_run",
        "curl_fallback_available",
        "preflight_warning_reason",
        "_is_formal_success_for_date",
        "latest_completed_trade_date",
        "research_trade_date",
        "stage_timeout_seconds",
        "last_heartbeat_at",
        "processed_symbol_count",
        "total_symbol_count",
        "StageCommand",
        "subprocess.Popen",
        "select.select",
        "--max-symbols",
        "FULL_BATCH_UPDATE_TIMEOUT_SECONDS",
    ]:
        if phrase not in scheduled_source:
            failures.append(f"run_scheduled_daily_update.py is missing Task 57B phrase: {phrase}.")

    launchd_source = read_source(root / "core/jobs/install_scheduled_daily_update.py")
    for phrase in ["LaunchAgent", "StartCalendarInterval", "Hour", "Minute", "run_scheduled_daily_update", "--catch-up", "--update-mode", "daily_incremental", "launchctl", "dry_run"]:
        if phrase not in launchd_source:
            failures.append(f"install_scheduled_daily_update.py is missing {phrase}.")
    uninstall_source = read_source(root / "core/jobs/uninstall_scheduled_daily_update.py")
    for phrase in ["bootout", "dry_run", "LaunchAgent"]:
        if phrase not in uninstall_source:
            failures.append(f"uninstall_scheduled_daily_update.py is missing {phrase}.")

    command_source = read_source(root / "core/runtime/command_runner.py")
    for phrase in ["run_scheduled_daily_update", "install_scheduled_daily_update", "uninstall_scheduled_daily_update", "refresh_data_quality_status", "update_market_data", "import_market_data"]:
        if phrase not in command_source:
            failures.append(f"command_runner.py is missing {phrase}.")

    update_market_source = read_source(root / "core/jobs/update_market_data.py")
    for phrase in [
        "akshare_kline",
        "akshare_spot_snapshot",
        "baostock",
        "manual_import",
        "csv",
        "tushare_optional",
        "auto",
        "GOALS",
        "latest",
        "history",
        "diagnosis",
        "forward_fill_adj_factor",
        "record_provider_attempt",
        "provider_attempts",
        "MarketDataProgressWriter",
        "DEFAULT_PROGRESS_PATH",
        "network_or_provider_unavailable",
        "core_price_data_usable",
        "enhanced_data_status",
    ]:
        if phrase not in update_market_source:
            failures.append(f"update_market_data.py is missing Task 57D phrase: {phrase}.")
    import_market_source = read_source(root / "core/jobs/import_market_data.py")
    for phrase in ["import_market_data", "CSV", "Excel", "normalize_ts_code", "normalize_trade_date", "upsert_dataframe"]:
        if phrase not in import_market_source:
            failures.append(f"import_market_data.py is missing Task 57D phrase: {phrase}.")
    spot_source = read_source(root / "core/data_sources/akshare_spot_snapshot.py")
    for phrase in ["AKShareSpotSnapshotClient", "MARKET_CLOSE_WRITE_TIME", "source_granularity", "eod_snapshot", "turnover_rate"]:
        if phrase not in spot_source:
            failures.append(f"akshare_spot_snapshot.py is missing Task 57D phrase: {phrase}.")
    baostock_source = read_source(root / "core/data_sources/baostock_client.py")
    for phrase in ["BaoStockClient", "query_history_k_data_plus", "daily_price", "daily_basic", "adjustflag", "progress_callback", "failure_summary", "failure_examples", "max_retries", "peTTM", "pbMRQ"]:
        if phrase not in baostock_source:
            failures.append(f"baostock_client.py is missing Task 57D phrase: {phrase}.")
    market_progress_source = read_source(root / "core/jobs/market_data_progress.py")
    for phrase in ["MarketDataProgressWriter", "market_data_update_progress.json", "read_market_data_progress", ".tmp", "replace", "failure_summary", "failure_examples"]:
        if phrase not in market_progress_source:
            failures.append(f"market_data_progress.py is missing Task 57E phrase: {phrase}.")

    snapshot_source = read_source(root / "core/diagnostics/data_quality_snapshot.py")
    for phrase in [
        "build_data_quality_snapshot",
        "normalize_trade_date",
        "replace(CAST(trade_date AS VARCHAR), '-', '')",
        "any_daily_price_symbol_count",
        "history_missing_symbol_count",
        "formal_result_usable",
        "readonly_duckdb_sql",
        "adj_factor_source",
        "adj_factor_semantics",
        "baostock_adjusted_price_identity",
        "daily_basic 缺估值或换手率关键字段",
        "technical_research_usable",
        "formal_full_market_result_usable",
        "adj_factor_required",
        "qfq_price_available",
    ]:
        if phrase not in snapshot_source:
            failures.append(f"data_quality_snapshot.py is missing Task 57C phrase: {phrase}.")

    refresh_source = read_source(root / "core/jobs/refresh_data_quality_status.py")
    for phrase in [
        "refresh_data_quality_status",
        "read_only SQL counts",
        "trade_date 分布 top 10",
        "any_daily_price_symbol_count",
        "history_missing_symbol_count",
    ]:
        if phrase not in refresh_source:
            failures.append(f"refresh_data_quality_status.py is missing Task 57C phrase: {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["自动更新状态", "下载最新自动更新 Excel", "手动补跑一次自动更新", "read_scheduled_status", "数据更新操作", "一键更新最新交易日数据", "补历史行情缺口", "运行数据源诊断", "上传 CSV / Excel 导入行情", "后台自动判断"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 57B phrase: {phrase}.")

    tests_source = (
        read_source(root / "tests/test_scheduled_daily_update.py")
        + read_source(root / "tests/test_task57c_data_quality_snapshot.py")
        + read_source(root / "tests/test_task57d_free_data_fallbacks.py")
        + read_source(root / "tests/test_streamlit_app.py")
    )
    for phrase in [
        "test_scheduled_update_skips_before_scheduled_time",
        "test_scheduled_update_skips_if_already_success_today",
        "test_scheduled_update_runs_after_scheduled_time_when_not_success",
        "test_scheduled_update_force_runs_even_if_already_success",
        "test_scheduled_update_preflight_failure_stops_before_heavy_update",
        "test_scheduled_update_writes_status_json",
        "test_scheduled_update_exports_workbook_on_success",
        "test_scheduled_update_lock_prevents_concurrent_runs",
        "test_macos_notification_builds_safe_message",
        "test_email_notification_disabled_by_default",
        "test_install_scheduled_daily_update_generates_launchd_plist",
        "test_streamlit_shows_scheduled_update_status_and_download",
        "test_force_update_limit_is_passed_to_update_stage",
        "test_text_mode_prints_start_immediately",
        "test_text_mode_prints_each_stage_with_flush",
        "test_stage_status_written_before_heavy_work",
        "test_stage_timeout_exits_and_releases_lock",
        "test_heartbeat_updates_during_long_stage",
        "test_force_update_limit_50_finishes_in_test",
        "test_force_before_scheduled_time_uses_previous_completed_trade_date_by_default",
        "test_allow_intraday_uses_current_trade_date_with_warning",
        "test_scheduled_after_1800_uses_current_trade_date",
        "test_intraday_daily_incremental_does_not_set_formal_success_date",
        "test_intraday_force_does_not_block_1800_formal_run",
        "test_allow_intraday_sets_formal_run_false",
        "test_before_scheduled_time_uses_previous_completed_trade_date_unless_allow_intraday",
        "test_formal_success_only_after_scheduled_time",
        "test_acceptance_run_does_not_block_formal_scheduled_run",
        "test_intraday_run_does_not_block_formal_scheduled_run",
        "test_update_limit_run_does_not_set_formal_success",
        "test_formal_success_blocks_duplicate_formal_run",
        "test_skipped_status_from_acceptance_state_does_not_clear_previous_formal_fields",
        "test_scheduled_update_defaults_to_daily_incremental",
        "test_daily_incremental_partial_symbol_failures_continue_workflow",
        "test_preflight_warning_allows_daily_incremental_when_curl_succeeds",
        "test_preflight_fails_when_python_and_curl_all_fail",
        "test_preflight_records_curl_fallback_available",
        "test_preflight_warning_message_in_text_output",
        "test_no_algorithm_changes",
        "test_data_quality_snapshot_counts_latest_trade_date",
        "test_data_quality_snapshot_counts_daily_basic_latest_trade_date",
        "test_data_quality_snapshot_counts_adj_factor_latest_trade_date",
        "test_data_quality_snapshot_counts_any_history_separately",
        "test_history_missing_uses_any_history_count",
        "test_history_complete_is_separate_from_any_history",
        "test_refresh_data_quality_status_writes_status_json",
        "test_refresh_data_quality_status_is_read_only",
        "test_refresh_data_quality_status_prints_sql_counts",
        "test_streamlit_status_page_prefers_data_quality_snapshot",
        "test_streamlit_status_page_does_not_use_tables_summary_for_latest_coverage",
        "test_streamlit_status_page_does_not_use_full_batch_for_latest_coverage",
        "test_missing_quality_fields_fallbacks_to_readonly_snapshot",
        "test_buttons_grouped_by_side_effects",
        "test_raw_json_sections_collapsed_by_default",
        "test_status_page_no_lookback_button",
        "test_no_duplicate_streamlit_keys",
        "test_provider_auto_prefers_free_fallbacks_before_tushare",
        "test_tushare_is_optional_and_disabled_without_token",
        "test_akshare_spot_snapshot_mapping_daily_price",
        "test_akshare_spot_snapshot_not_used_before_market_close_without_force",
        "test_spot_snapshot_skips_on_trade_day_before_close_without_force",
        "test_spot_snapshot_allowed_on_non_trade_day_before_close",
        "test_spot_snapshot_uses_latest_completed_trade_date_on_non_trade_day",
        "test_akshare_spot_snapshot_marks_partial_daily_basic",
        "test_adj_factor_forward_fill_marks_derived",
        "test_baostock_daily_price_mapping",
        "test_baostock_partial_provider_status",
        "test_manual_import_daily_price_csv",
        "test_manual_import_xlsx",
        "test_manual_import_trade_date_normalization",
        "test_manual_import_symbol_normalization",
        "test_manual_import_upsert_deduplicates",
        "test_update_market_data_refreshes_data_quality_snapshot",
        "test_provider_failure_recorded_in_status_json",
        "test_partial_success_does_not_mark_formal_usable",
        "test_update_latest_auto_attempts_fallback_after_kline_failure",
        "test_update_latest_kline_fail_fast_before_full_symbol_loop",
        "test_update_latest_kline_fail_fast_on_exception",
        "test_update_latest_auto_records_unavailable_provider",
        "test_update_latest_all_failed_records_manual_import_available",
        "test_update_latest_all_failed_no_success_provider",
        "test_update_market_data_text_output_hides_tracebacks",
        "test_update_market_data_json_contains_all_provider_attempts",
        "test_update_latest_partial_success_does_not_mark_formal_usable",
        "test_update_history_auto_prefers_history_provider",
        "test_diagnosis_does_not_write_success_provider",
        "test_diagnosis_does_not_write_duckdb_or_success_provider",
        "test_status_json_contains_provider_attempts_after_one_click_update",
        "test_refresh_data_quality_snapshot_after_update",
        "test_market_data_progress_file_created_when_update_starts",
        "test_market_data_progress_updates_provider_and_symbol_counts",
        "test_market_data_progress_finishes_on_success_or_partial",
        "test_market_data_progress_finishes_on_failure",
        "test_market_data_progress_atomic_write",
        "test_latest_update_targets_missing_latest_symbols_first",
        "test_latest_update_limit_applies_to_pending_symbols",
        "test_latest_update_skips_already_latest_symbols",
        "test_baostock_failure_summary_classifies_errors",
        "test_baostock_retry_only_for_transient_errors",
        "test_baostock_records_failure_examples",
        "test_progress_json_contains_failure_summary",
        "test_baostock_daily_basic_mapping",
        "test_daily_basic_written_for_latest_trade_date",
        "test_adj_factor_identity_written_for_adjusted_baostock_price",
        "test_adj_factor_identity_has_explicit_source_semantics",
        "test_no_double_adjustment_when_price_already_adjusted",
        "test_data_quality_snapshot_counts_compatible_adj_factor",
        "test_data_quality_snapshot_explains_compatible_adj_factor",
        "test_formal_result_not_usable_if_daily_basic_key_fields_missing",
        "test_enhanced_backfill_targets_existing_price_missing_basic_or_adj",
        "test_update_limit_applies_to_enhanced_backfill_pool",
        "test_enhanced_backfill_writes_daily_basic_without_new_price",
        "test_enhanced_backfill_writes_latest_identity_adj_factor",
        "test_refresh_data_quality_reports_identity_adj_factor_source",
        "test_latest_all_required_tables_increases_after_enhanced_backfill",
        "test_price_data_enables_technical_research_without_daily_basic",
        "test_missing_daily_basic_marks_enhanced_data_incomplete_only",
        "test_qfq_price_does_not_require_adj_factor_for_technical_research",
        "test_formal_full_market_result_still_false_when_enhanced_data_missing",
        "test_streamlit_free_provider_fallback_section",
        "test_streamlit_update_page_has_only_user_level_actions",
        "test_provider_buttons_hidden_in_advanced_expander",
        "test_update_latest_uses_provider_auto",
        "test_streamlit_one_click_update_calls_goal_latest_provider_auto",
        "test_streamlit_history_backfill_calls_goal_history_provider_auto",
        "test_streamlit_no_col4_name_error",
        "test_streamlit_primary_view_hides_technical_fields",
        "test_streamlit_primary_attempt_message_sanitizes_technical_fields",
        "test_streamlit_advanced_contains_technical_details",
        "test_streamlit_progress_table_reads_progress_json",
        "test_streamlit_running_progress_autorefresh",
        "test_streamlit_progress_primary_view_hides_technical_fields",
        "test_streamlit_displays_failure_summary_without_raw_traceback",
        "test_streamlit_displays_adj_factor_semantics",
        "test_streamlit_displays_layered_data_quality_status",
        "test_streamlit_hides_raw_technical_details",
        "test_auto_provider_attempts_are_recorded_but_not_user_selected",
        "test_data_quality_snapshot_metrics_preserved",
        "test_technical_terms_not_in_primary_buttons",
        "test_no_data_runtime_files_committed",
    ]:
        if phrase not in tests_source:
            failures.append(f"Task 57B tests are missing {phrase}.")

    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["task57b", "run_scheduled_daily_update", "--dry-run", "/tmp/a_stock_assistant_task57b", "install_scheduled_daily_update"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task57b is missing {phrase}.")
    docs_source = read_source(root / "docs/commands_reference.md")
    for phrase in ["run_scheduled_daily_update", "install_scheduled_daily_update", "18:00", "自动更新状态", "--update-limit 50", "--allow-intraday", "--update-mode daily_incremental", "full_backfill", "research_trade_date", "last_heartbeat_at", "DATA_SOURCE_REQUEST_TIMEOUT_SECONDS", "SYMBOL_UPDATE_TIMEOUT_SECONDS"]:
        if phrase not in docs_source:
            failures.append(f"docs/commands_reference.md is missing Task 57B wording: {phrase}.")
    diagnose_source = read_source(root / "core/jobs/diagnose_update_batch.py")
    for phrase in ["latest_price_symbol_count", "history_complete_symbol_count", "elder_ready_symbol_count", "latest_updated_but_history_incomplete_count"]:
        if phrase not in diagnose_source:
            failures.append(f"diagnose_update_batch.py is missing latest/history coverage field: {phrase}.")
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["顶部结论卡片", "当前研究展示日期覆盖", "历史数据完整度", "模块可用性", "本次运行结果", "按钮区", "全市场批量补数据"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing data update status section: {phrase}.")
    env_source = read_source(root / ".env.example")
    for phrase in ["DATA_SOURCE_REQUEST_TIMEOUT_SECONDS", "SYMBOL_UPDATE_TIMEOUT_SECONDS", "FULL_BATCH_UPDATE_TIMEOUT_SECONDS"]:
        if phrase not in env_source:
            failures.append(f".env.example is missing Task 57B timeout config: {phrase}.")
    gitignore_source = read_source(root / ".gitignore")
    for phrase in ["data/", "reports/*.xlsx", "*.log"]:
        if phrase not in gitignore_source:
            failures.append(f".gitignore should ignore Task 57B runtime artifact: {phrase}.")
    preflight_source = read_source(root / "core/runtime/data_source_preflight.py")
    for phrase in ["curl_fallback_available", "preflight_warning_reason", "preflight_allows_run", "curl_ipv4", "curl_ipv6"]:
        if phrase not in preflight_source:
            failures.append(f"data_source_preflight.py is missing fallback preflight phrase: {phrase}.")
    return failures


def check_task58(root: Path) -> list[str]:
    """Check Task 58 automatic lookback analysis module."""
    failures: list[str] = []
    failures.extend(
        check_paths(
            root,
            [
                "core/jobs/run_lookback_analysis.py",
                "tests/test_lookback_analysis.py",
            ],
        )
    )
    lookback_source = read_source(root / "core/jobs/run_lookback_analysis.py")
    for phrase in [
        "run_lookback_analysis",
        "build_forward_return_details",
        "group_summary",
        "save_lookback_workbook",
        "forward_return",
        "max_drawdown",
        "max_runup",
        "hit_stop_loss",
        "hit_target",
        "lookback_analysis_status.json",
        "read_only=True",
        "仅供个人研究使用，不自动交易",
    ]:
        if phrase not in lookback_source:
            failures.append(f"run_lookback_analysis.py is missing Task 58 phrase: {phrase}.")
    workbook_source = read_source(root / "core/jobs/export_daily_research_workbook.py")
    for phrase in ["11_自动回看摘要", "lookback_analysis_status.json", "尚无自动回看记录", "lookback_report_path"]:
        if phrase not in workbook_source:
            failures.append(f"export_daily_research_workbook.py is missing Task 58 lookback summary phrase: {phrase}.")
    command_source = read_source(root / "core/runtime/command_runner.py")
    if "run_lookback_analysis" not in command_source:
        failures.append("command_runner.py is missing run_lookback_analysis allowlist entry.")
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["自动回看分析", "自动回看状态摘要", "运行自动回看分析", "刷新回看状态", "下载最新回看报告", "run_lookback_analysis"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 58 phrase: {phrase}.")
    backtest_marker = "def _render_backtest_tab"
    status_marker = "def _render_status_tab"
    if backtest_marker in streamlit_source and status_marker in streamlit_source:
        backtest_source = streamlit_source[streamlit_source.index(backtest_marker) : streamlit_source.index(status_marker, streamlit_source.index(backtest_marker))]
        if "_render_lookback_analysis_section(st)" not in backtest_source:
            failures.append("Strategy Backtest tab does not render the automatic lookback analysis section.")
        if "暂无回测结果。请先运行回测诊断；真实数据不足时不会生成结果。" in backtest_source:
            failures.append("Strategy Backtest tab still uses the old missing-backtest main prompt.")
    else:
        failures.append("web/streamlit_app.py is missing Strategy Backtest tab render markers.")
    scheduled_source = read_source(root / "core/jobs/run_scheduled_daily_update.py")
    for phrase in ["run_lookback_after_daily_update", "lookback_analysis"]:
        if phrase not in scheduled_source:
            failures.append(f"run_scheduled_daily_update.py is missing Task 58 optional integration phrase: {phrase}.")
    config_source = read_source(root / "app/config.py") + read_source(root / ".env.example")
    if "RUN_LOOKBACK_AFTER_DAILY_UPDATE" not in config_source:
        failures.append("Config is missing RUN_LOOKBACK_AFTER_DAILY_UPDATE.")
    tests_source = read_source(root / "tests/test_lookback_analysis.py") + read_source(root / "tests/test_daily_research_workbook.py")
    for phrase in [
        "test_forward_return_uses_future_trading_days",
        "test_forward_return_does_not_use_future_data_for_selection",
        "test_insufficient_forward_data_is_excluded_from_horizon_stats",
        "test_max_drawdown_and_max_runup_calculation",
        "test_hit_stop_loss_and_target",
        "test_total_score_grouping",
        "test_factor_score_grouping",
        "test_elder_action_hint_grouping",
        "test_entry_zone_status_grouping",
        "test_watch_status_grouping",
        "test_lookback_workbook_has_expected_sheets",
        "test_lookback_status_json_written",
        "test_lookback_dry_run_does_not_write_report",
        "test_lookback_streamlit_entry_exists",
        "test_lookback_command_allowlist",
        "test_daily_research_workbook_includes_lookback_summary_when_status_exists",
        "test_daily_research_workbook_handles_missing_lookback_status",
        "test_daily_research_workbook_does_not_embed_full_lookback_detail",
        "test_lookback_report_path_is_recorded_in_daily_workbook_summary",
    ]:
        if phrase not in tests_source:
            failures.append(f"Task 58 tests are missing {phrase}.")
    verify_source = read_source(root / "scripts/verify_task.py")
    for phrase in ["task58", "run_lookback_analysis", "--dry-run", "--format", "json"]:
        if phrase not in verify_source:
            failures.append(f"verify_task.py task58 is missing {phrase}.")
    docs_source = read_source(root / "docs/commands_reference.md")
    for phrase in ["run_lookback_analysis", "自动回看分析", "RUN_LOOKBACK_AFTER_DAILY_UPDATE"]:
        if phrase not in docs_source:
            failures.append(f"docs/commands_reference.md is missing Task 58 wording: {phrase}.")
    return failures


def check_task57h(root: Path) -> list[str]:
    """Check Task 57H batched update timeout and recovery support."""
    failures: list[str] = []
    required_paths = [
        "core/jobs/update_market_data.py",
        "core/jobs/market_data_progress.py",
        "core/jobs/doctor_daily_run.py",
        "web/streamlit_app.py",
        "tests/test_task57h_batched_update_timeout.py",
    ]
    failures.extend(check_paths(root, required_paths))
    update_source = read_source(root / "core/jobs/update_market_data.py")
    for phrase in [
        "--batch-size",
        "--batch-timeout-seconds",
        "--symbol-timeout-seconds",
        "--continue-missing-latest",
        "run_batched_update_parent",
        "_continue_missing_latest_symbol_plan",
        "subprocess.Popen",
        "os.killpg",
        "stale_detected",
    ]:
        if phrase not in update_source:
            failures.append(f"core/jobs/update_market_data.py is missing Task 57H phrase: {phrase}.")
    progress_source = read_source(root / "core/jobs/market_data_progress.py")
    for phrase in ["batch_id", "batch_timeout_seconds", "symbol_timeout_seconds", "stale_detected", "timeout"]:
        if phrase not in progress_source:
            failures.append(f"core/jobs/market_data_progress.py is missing Task 57H progress field: {phrase}.")
    doctor_source = read_source(root / "core/jobs/doctor_daily_run.py")
    for phrase in ["latest_coverage_counts", "daily_price 覆盖数", "daily_basic 覆盖数", "缺口数量"]:
        if phrase not in doctor_source:
            failures.append(f"core/jobs/doctor_daily_run.py is missing Task 57H coverage phrase: {phrase}.")
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["--batch-size", "--batch-timeout-seconds", "--continue-missing-latest", "stale_detected"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 57H minimal UI phrase: {phrase}.")
    tests_source = read_source(root / "tests/test_task57h_batched_update_timeout.py")
    for phrase in [
        "test_continue_missing_latest_selects_missing_price_or_basic_only",
        "test_parent_timeout_writes_interrupted_progress",
        "test_progress_finish_clears_running_provider",
        "test_doctor_daily_run_reports_latest_coverage_counts",
        "test_streamlit_latest_update_uses_batched_continue_missing",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_task57h_batched_update_timeout.py is missing {phrase}.")
    return failures


def check_task57i(root: Path) -> list[str]:
    """Check Task 57I missing-latest skip/retry queue support."""
    failures: list[str] = []
    required_paths = [
        "core/jobs/update_market_data.py",
        "core/jobs/missing_latest_retry_queue.py",
        "core/jobs/market_data_progress.py",
        "core/jobs/doctor_daily_run.py",
        "tests/test_task57i_gap_update_skip_retry_queue.py",
    ]
    failures.extend(check_paths(root, required_paths))
    update_source = read_source(root / "core/jobs/update_market_data.py")
    for phrase in [
        "--respect-skip-queue",
        "--retry-skip-queue",
        "--max-no-data-retries",
        "--max-timeout-retries",
        "--skip-queue-path",
        "--reset-skip-queue",
        "--skip-cooldown-minutes",
        "record_failure_records",
        "mark_resolved_symbols",
        "KeyboardInterrupt",
    ]:
        if phrase not in update_source:
            failures.append(f"core/jobs/update_market_data.py is missing Task 57I phrase: {phrase}.")
    queue_source = read_source(root / "core/jobs/missing_latest_retry_queue.py")
    for phrase in [
        "missing_latest_retry_queue.json",
        "resolve_missing_latest_queue_path",
        "skip_queue",
        "retry_queue",
        "retry_count",
        "next_retry_after",
        "excluded_symbols_for_main_scan",
        "retry_symbols",
    ]:
        if phrase not in queue_source:
            failures.append(f"core/jobs/missing_latest_retry_queue.py is missing Task 57I phrase: {phrase}.")
    progress_source = read_source(root / "core/jobs/market_data_progress.py")
    for phrase in ["skip_queue_count", "retry_queue_count", "cooldown_symbol_count", "retry_round", "interrupted_by_user", "timeout_symbol"]:
        if phrase not in progress_source:
            failures.append(f"core/jobs/market_data_progress.py is missing Task 57I progress field: {phrase}.")
    doctor_source = read_source(root / "core/jobs/doctor_daily_run.py")
    for phrase in ["本轮 no_data 冷却队列", "待 retry 队列", "duckdb_fileprovider_risk", "FileProvider"]:
        if phrase not in doctor_source:
            failures.append(f"core/jobs/doctor_daily_run.py is missing Task 57I doctor phrase: {phrase}.")
    tests_source = read_source(root / "tests/test_task57i_gap_update_skip_retry_queue.py")
    for phrase in [
        "test_no_data_stock_enters_skip_queue",
        "test_continue_missing_latest_skips_skip_queue_and_moves_forward",
        "test_retry_skip_queue_has_limited_attempts",
        "test_timeout_batch_does_not_mark_whole_batch_no_data",
        "test_keyboard_interrupt_cleans_child_and_progress",
        "test_resolve_queue_path_follows_data_dir",
        "test_update_market_data_default_queue_path_follows_data_dir",
        "test_doctor_daily_run_uses_data_dir_queue_counts_and_fileprovider_warning",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_task57i_gap_update_skip_retry_queue.py is missing {phrase}.")
    return failures


def check_task59(root: Path) -> list[str]:
    """Check Task 59 watchlist lifecycle and Elder review scope support."""
    failures: list[str] = []
    required_paths = [
        "core/review/tracking.py",
        "core/review/decisions.py",
        "core/jobs/run_elder_review.py",
        "core/jobs/export_daily_research_workbook.py",
        "tests/test_watchlist_lifecycle_task59.py",
    ]
    failures.extend(check_paths(root, required_paths))
    tracking_source = read_source(root / "core/review/tracking.py")
    for phrase in [
        "CURRENT_WATCH_STATUSES",
        "DEFAULT_DAILY_NEW_LIMIT",
        "DEFAULT_ACTIVE_LIMIT",
        "_apply_active_watch_limit",
        "_sync_review_statuses_from_snapshots",
        "expired",
    ]:
        if phrase not in tracking_source:
            failures.append(f"core/review/tracking.py is missing Task 59 phrase: {phrase}.")
    decisions_source = read_source(root / "core/review/decisions.py")
    for phrase in ["CURRENT_WATCH_REVIEW_STATUSES", "entry_zone", "triggered", "manual_removed"]:
        if phrase not in decisions_source:
            failures.append(f"core/review/decisions.py is missing Task 59 status support: {phrase}.")
    elder_source = read_source(root / "core/jobs/run_elder_review.py")
    for phrase in ["_append_current_watchlist_targets", "review_scope", "当前观察池"]:
        if phrase not in elder_source:
            failures.append(f"core/jobs/run_elder_review.py is missing Task 59 Elder scope phrase: {phrase}.")
    workbook_source = read_source(root / "core/jobs/export_daily_research_workbook.py")
    for phrase in ["_current_watchlist_scope", "ELDER_DISPLAY_COLUMNS", "Elder 复核已作为今日候选和当前观察池的附加判断字段展示"]:
        if phrase not in workbook_source:
            failures.append(f"core/jobs/export_daily_research_workbook.py is missing Task 59 workbook phrase: {phrase}.")
    tests_source = read_source(root / "tests/test_watchlist_lifecycle_task59.py")
    for phrase in [
        "test_watchlist_does_not_append_duplicate_active_rows",
        "test_watchlist_daily_new_limit",
        "test_watchlist_active_size_limit",
        "test_watchlist_expires_stale_symbols",
        "test_watchlist_keeps_entry_zone_priority",
        "test_elder_review_includes_active_watchlist",
        "test_elder_review_no_blank_score_without_reason",
        "test_daily_research_excel_watchlist_current_scope",
        "test_daily_research_excel_elder_review_scope",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_watchlist_lifecycle_task59.py is missing {phrase}.")
    return failures


def check_task59b(root: Path) -> list[str]:
    """Check Task 59B Elder fields are embedded in candidate/watchlist views."""
    failures: list[str] = []
    required_paths = [
        "core/jobs/export_daily_research_workbook.py",
        "web/streamlit_app.py",
        "tests/test_task59b_simplify_elder_review_fields.py",
    ]
    failures.extend(check_paths(root, required_paths))

    workbook_path = root / "core/jobs/export_daily_research_workbook.py"
    workbook_source = read_source(workbook_path)
    for phrase in [
        "_embedded_elder_row_count",
        "_current_watchlist_scope",
        "elder_score",
        "action_hint",
        "elder_reason",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
        "head(30)",
    ]:
        if phrase not in workbook_source:
            failures.append(f"core/jobs/export_daily_research_workbook.py is missing Task 59B phrase: {phrase}.")

    try:
        tree = ast.parse(workbook_source)
        sheet_names: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "SHEET_NAMES":
                        if isinstance(node.value, ast.List):
                            sheet_names = [item.value for item in node.value.elts if isinstance(item, ast.Constant)]
        forbidden_sheets = {
            "02_埃尔德复核",
            "05_观察池跟踪",
            "07_风险提示",
            "08_数据质量",
            "09_参数配置",
            "10_说明",
        }
        for sheet_name in forbidden_sheets & set(sheet_names):
            failures.append(f"SHEET_NAMES should not include Task 59B removed sheet: {sheet_name}.")
    except SyntaxError as exc:
        failures.append(f"core/jobs/export_daily_research_workbook.py has syntax error: {exc}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    tabs_index = streamlit_source.find("st.tabs([")
    tabs_end = streamlit_source.find("])", tabs_index)
    tabs_source = streamlit_source[tabs_index:tabs_end] if tabs_index >= 0 and tabs_end >= 0 else ""
    if "埃尔德复核" in tabs_source:
        failures.append("web/streamlit_app.py should not include a standalone Elder review tab.")
    for phrase in [
        "Elder 复核已作为今日候选和当前观察池的附加判断字段展示",
        "elder_score",
        "action_hint",
        "elder_reason",
    ]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 59B phrase: {phrase}.")

    tests_source = read_source(root / "tests/test_task59b_simplify_elder_review_fields.py")
    for phrase in [
        "test_daily_research_removed_standalone_elder_and_diagnostic_sheets",
        "test_candidate_sheet_contains_elder_fields_and_scores",
        "test_current_watchlist_sheet_contains_elder_fields_and_scores",
        "test_missing_elder_fields_do_not_break_daily_research",
        "test_empty_watchlist_does_not_break_daily_research",
        "test_current_watchlist_sheet_limits_to_30_rows",
        "test_streamlit_no_standalone_elder_review_tab",
        "test_candidate_order_and_total_score_unchanged",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_task59b_simplify_elder_review_fields.py is missing {phrase}.")
    return failures


def check_task59c(root: Path) -> list[str]:
    """Check Task 59C report buy-zone and lookback status alignment."""
    failures: list[str] = []
    required_paths = [
        "core/jobs/export_daily_research_workbook.py",
        "web/streamlit_app.py",
        "tests/test_task59c_report_buyzone_lookback_repair.py",
    ]
    failures.extend(check_paths(root, required_paths))

    workbook_source = read_source(root / "core/jobs/export_daily_research_workbook.py")
    for phrase in [
        "build_daily_research_view_from_frames",
        "_ensure_entry_zones_for_trade_date",
        "calculate_entry_zones",
        "_build_entry_zone_sheet",
        "_visible_research_codes",
        "drop_duplicates(\"ts_code\"",
        "selection",
        "watchlist",
        "_build_lookback_status_sheet",
        "build_lookback_status_display",
        "需要刷新当日回看",
        "Elder 字段补充",
    ]:
        if phrase not in workbook_source:
            failures.append(f"core/jobs/export_daily_research_workbook.py is missing Task 59C phrase: {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in [
        "build_daily_research_view_from_frames",
        "_daily_research_selection",
        "_daily_research_watchlist",
        "_daily_research_entry_zones",
        "planned_update_trade_date",
        "current_research_trade_date",
        "latest_local_trade_date",
        "resolve_streamlit_research_dates",
        "build_lookback_status_display",
        "Task 60 TODO",
    ]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 59C phrase: {phrase}.")

    tests_source = read_source(root / "tests/test_task59c_report_buyzone_lookback_repair.py")
    for phrase in [
        "test_export_autocalculates_same_day_entry_zones_when_missing",
        "test_entry_zone_sheet_uses_visible_candidate_and_watchlist_scope",
        "test_entry_zone_duplicate_prefers_selection_source",
        "test_stale_lookback_creates_refresh_status_sheet",
        "test_same_day_valid_lookback_keeps_summary_sheet",
        "test_status_page_uses_latest_local_research_date_when_planned_date_has_zero_coverage",
        "test_streamlit_daily_research_frames_match_excel_scope",
        "test_streamlit_lookback_status_uses_shared_display_function",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_task59c_report_buyzone_lookback_repair.py is missing {phrase}.")
    return failures


def check_task60(root: Path) -> list[str]:
    """Check Task 60 trading-calendar update-target repairs."""
    failures: list[str] = []
    required_paths = [
        "core/calendar/trading_calendar.py",
        "app/config.py",
        "web/streamlit_app.py",
        "core/jobs/run_scheduled_daily_update.py",
        "tests/test_data_update_status.py",
    ]
    failures.extend(check_paths(root, required_paths))
    calendar_source = read_source(root / "core/calendar/trading_calendar.py")
    for phrase in [
        "resolve_update_target_trade_date",
        "Asia/Shanghai",
        "trade_calendar",
        "local_price_fallback",
        "尚未过安全更新时间",
    ]:
        if phrase not in calendar_source:
            failures.append(f"core/calendar/trading_calendar.py is missing Task 60 phrase: {phrase}.")
    config_source = read_source(root / "app/config.py")
    if "DAILY_UPDATE_CUTOFF_TIME" not in config_source:
        failures.append("app/config.py is missing DAILY_UPDATE_CUTOFF_TIME.")
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in ["resolve_update_target_trade_date", "planned_update_reason", "planned_update_calendar_source"]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 60 phrase: {phrase}.")
    scheduled_source = read_source(root / "core/jobs/run_scheduled_daily_update.py")
    if "resolve_update_target_trade_date" not in scheduled_source:
        failures.append("run_scheduled_daily_update should use resolve_update_target_trade_date.")
    tests_source = read_source(root / "tests/test_data_update_status.py")
    for phrase in [
        "test_trade_day_before_cutoff_uses_previous_trade_date",
        "test_trade_day_after_cutoff_uses_today",
        "test_non_trade_day_uses_recent_completed_trade_date",
        "test_missing_calendar_falls_back_to_latest_daily_price",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_data_update_status.py is missing {phrase}.")
    return failures


def check_task61(root: Path) -> list[str]:
    """Check Task 61 tradeable-universe filter repairs."""
    failures: list[str] = []
    required_paths = [
        "core/universe/stock_pool.py",
        "app/config.py",
        "core/jobs/run_daily_selection.py",
        "core/jobs/diagnose_factors.py",
        "core/jobs/diagnose_backtest.py",
        "core/explain/selection_logic.py",
        "tests/test_stock_pool.py",
        "tests/test_real_data_e2e_validation.py",
        "tests/test_streamlit_app.py",
    ]
    failures.extend(check_paths(root, required_paths))

    stock_pool_source = read_source(root / "core/universe/stock_pool.py")
    for phrase in [
        "allow_missing_list_date_with_price_history: bool = True",
        "min_price_history_days",
        "price_history_days < min_price_history_days",
        'required_columns = ["turnover_rate"]',
    ]:
        if phrase not in stock_pool_source:
            failures.append(f"core/universe/stock_pool.py is missing Task 61 phrase: {phrase}.")
    if 'required_columns = ["turnover_rate", "pe", "pb", "total_mv", "circ_mv"]' in stock_pool_source:
        failures.append("total_mv/circ_mv must not be severe financial required_columns.")

    config_source = read_source(root / "app/config.py")
    for phrase in [
        "ALLOW_MISSING_LIST_DATE_WITH_PRICE_HISTORY",
        "MIN_PRICE_HISTORY_DAYS",
        "ALLOW_MISSING_VALUATION",
    ]:
        if phrase not in config_source:
            failures.append(f"app/config.py is missing Task 61 setting: {phrase}.")

    for rel_path in ["core/jobs/run_daily_selection.py", "core/jobs/diagnose_factors.py", "core/jobs/diagnose_backtest.py"]:
        source = read_source(root / rel_path)
        for phrase in ["allow_missing_list_date_with_price_history", "min_price_history_days", "allow_missing_valuation"]:
            if phrase not in source:
                failures.append(f"{rel_path} is missing unified Task 61 setting usage: {phrase}.")

    streamlit_source = read_source(root / "web/streamlit_app.py")
    if "通过股票池过滤并生成 factor_scores 的股票数量" not in streamlit_source:
        failures.append("web/streamlit_app.py should explain factor_ready_symbol_count as filtered factor_scores count.")
    for phrase in [
        "当前选中交易日估值字段完整率",
        "当前基本面评分核心字段",
        "可选诊断字段",
        "_derive_watchlist_status_counts",
    ]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 61 page phrase: {phrase}.")

    logic_source = read_source(root / "core/explain/selection_logic.py")
    for phrase in [
        "最小真实评分路径主要来自市盈率倒数指标",
        "daily_basic.pb 作为估值参考",
        "不作为硬性股票池过滤门槛",
    ]:
        if phrase not in logic_source:
            failures.append(f"core/explain/selection_logic.py is missing Task 61 explanation phrase: {phrase}.")

    tests_source = read_source(root / "tests/test_stock_pool.py")
    for phrase in [
        "test_missing_list_date_with_enough_price_history_is_not_recent_listing",
        "test_missing_list_date_with_short_price_history_is_recent_listing",
        "test_missing_total_mv_and_circ_mv_do_not_trigger_severe_financial_missing",
        "test_missing_turnover_rate_still_triggers_severe_financial_missing",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_stock_pool.py is missing {phrase}.")
    e2e_source = read_source(root / "tests/test_real_data_e2e_validation.py")
    if 'summary["factor_scores_written_rows"] == summary["stock_pool_count"]' not in e2e_source:
        failures.append("tests/test_real_data_e2e_validation.py should assert factor_scores rows equal stock_pool_count.")
    streamlit_tests = read_source(root / "tests/test_streamlit_app.py")
    for phrase in [
        "test_daily_basic_quality_uses_current_factor_trade_date",
        "test_watchlist_summary_derives_cards_from_display_fields",
    ]:
        if phrase not in streamlit_tests:
            failures.append(f"tests/test_streamlit_app.py is missing Task 61 page test: {phrase}.")
    return failures


def check_task62(root: Path) -> list[str]:
    """Check Task 62 daily research display-scope repairs."""
    failures: list[str] = []
    required_paths = [
        "core/jobs/export_daily_research_workbook.py",
        "web/streamlit_app.py",
        "tests/test_task59c_report_buyzone_lookback_repair.py",
    ]
    failures.extend(check_paths(root, required_paths))
    workbook_source = read_source(root / "core/jobs/export_daily_research_workbook.py")
    for phrase in [
        "SELECTION_DISPLAY_TOP_N = 10",
        "WATCHLIST_DISPLAY_TOP_N = 30",
        "entry_missing_sheet",
        "12_买入区间缺失说明",
        "_entry_zone_source_scope",
        "后端候选池数量",
        "日报展示候选数量",
    ]:
        if phrase not in workbook_source:
            failures.append(f"core/jobs/export_daily_research_workbook.py is missing Task 62 phrase: {phrase}.")
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in [
        "_daily_research_entry_zone_missing",
        "今日候选 Top10 + 当前观察池 Top30",
        "买入区间缺失说明",
    ]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 62 phrase: {phrase}.")
    tests_source = read_source(root / "tests/test_task59c_report_buyzone_lookback_repair.py")
    for phrase in [
        "test_entry_zone_missing_sheet_lists_visible_scope_gaps",
        "len(candidates) == 10",
        "12_买入区间缺失说明",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_task59c_report_buyzone_lookback_repair.py is missing Task 62 test phrase: {phrase}.")
    return failures


def check_task64(root: Path) -> list[str]:
    """Check Task 64 simulated trading advice layer."""
    failures: list[str] = []
    required_paths = [
        "core/advice/simulated_trading_advice.py",
        "core/jobs/export_daily_research_workbook.py",
        "web/streamlit_app.py",
        "tests/test_simulated_trading_advice.py",
    ]
    failures.extend(check_paths(root, required_paths))
    advice_source = read_source(root / "core/advice/simulated_trading_advice.py")
    for phrase in [
        "build_simulated_trading_advice",
        "summarize_simulated_trading_advice",
        "source_tags",
        "simulated_position",
        "可模拟买入",
        "等待回调",
        "继续持有",
        "可模拟加仓",
        "减仓",
        "卖出",
    ]:
        if phrase not in advice_source:
            failures.append(f"core/advice/simulated_trading_advice.py is missing Task 64 phrase: {phrase}.")
    workbook_source = read_source(root / "core/jobs/export_daily_research_workbook.py")
    for phrase in [
        "13_模拟交易建议",
        "build_simulated_trading_advice",
        "simulated_advice_sheet",
        "模拟交易建议数量",
        "模拟持仓跟踪数量",
        "06_外部模拟持仓",
    ]:
        if phrase not in workbook_source:
            failures.append(f"core/jobs/export_daily_research_workbook.py is missing Task 64 phrase: {phrase}.")
    streamlit_source = read_source(root / "web/streamlit_app.py")
    for phrase in [
        "模拟交易建议",
        "_daily_research_simulated_advice",
        "以下仅用于模拟交易和复盘，不构成真实投资建议，不自动交易。",
        "position_action",
        "holding_status",
    ]:
        if phrase not in streamlit_source:
            failures.append(f"web/streamlit_app.py is missing Task 64 phrase: {phrase}.")
    tests_source = read_source(root / "tests/test_simulated_trading_advice.py")
    for phrase in [
        "test_advice_scope_deduplicates_sources_and_prioritizes_holdings",
        "test_unheld_advice_actions_cover_buy_wait_pause_and_remove",
        "test_holding_advice_generates_position_actions",
    ]:
        if phrase not in tests_source:
            failures.append(f"tests/test_simulated_trading_advice.py is missing Task 64 test: {phrase}.")
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
            "task41",
            "task42",
            "task43",
            "task44",
            "task45",
            "task46",
            "task47",
            "task48",
            "task49",
            "task50",
            "task51",
            "task52",
            "task53",
            "task54",
            "task55",
            "task56",
            "task57a",
            "task57b",
            "task57h",
            "task57i",
            "task58",
            "task59",
            "task59b",
            "task59c",
            "task60",
            "task61",
            "task62",
            "task64",
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
