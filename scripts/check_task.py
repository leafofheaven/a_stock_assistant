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
        choices=["task1", "task2", "task3", "task4", "task5", "task6", "task7"],
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
