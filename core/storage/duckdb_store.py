"""DuckDB storage layer for local market data."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

import duckdb
import pandas as pd

from app.config import get_settings

logger = logging.getLogger(__name__)


class DuckDBStoreError(RuntimeError):
    """Raised when DuckDB storage operations fail."""


class DuckDBStore:
    """Small DuckDB wrapper for schema setup and DataFrame persistence."""

    DATE_COLUMNS: ClassVar[dict[str, str]] = {
        "trade_calendar": "cal_date",
        "daily_price": "trade_date",
        "daily_basic": "trade_date",
        "adj_factor": "trade_date",
        "factor_values": "trade_date",
        "factor_scores": "trade_date",
        "strategy_result": "trade_date",
        "backtest_result": "start_date",
    }

    KEY_COLUMNS: ClassVar[dict[str, tuple[str, ...]]] = {
        "stock_basic": ("ts_code",),
        "trade_calendar": ("exchange", "cal_date"),
        "daily_price": ("ts_code", "trade_date"),
        "daily_basic": ("ts_code", "trade_date"),
        "adj_factor": ("ts_code", "trade_date"),
        "factor_values": ("ts_code", "trade_date", "factor_name"),
        "factor_scores": ("ts_code", "trade_date"),
        "strategy_result": ("trade_date", "rank", "ts_code"),
        "backtest_result": ("strategy_name", "start_date", "end_date", "created_at"),
    }

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Create a store using an explicit path or the configured DUCKDB_PATH."""
        self.db_path = Path(db_path) if db_path is not None else get_settings().duckdb_path
        self.schema_path = Path(__file__).with_name("schema.sql")

    def initialize(self) -> None:
        """Create all configured DuckDB tables if they do not already exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        schema_sql = self.schema_path.read_text(encoding="utf-8")
        try:
            with self.connect() as connection:
                connection.execute(schema_sql)
        except Exception as exc:
            logger.exception("Failed to initialize DuckDB schema at %s.", self.db_path)
            raise DuckDBStoreError("Failed to initialize DuckDB schema.") from exc

        logger.info("Initialized DuckDB schema at %s.", self.db_path)

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Open a DuckDB connection for this store."""
        return duckdb.connect(str(self.db_path))

    def write_dataframe(self, table_name: str, df: pd.DataFrame) -> int:
        """Append a DataFrame to a table and return the number of inserted rows."""
        self._validate_table(table_name)
        if df.empty:
            logger.info("Skipped writing empty DataFrame to %s.", table_name)
            return 0

        try:
            with self.connect() as connection:
                connection.register("input_df", df)
                connection.execute(f"INSERT INTO {table_name} BY NAME SELECT * FROM input_df")
                connection.unregister("input_df")
        except Exception as exc:
            logger.exception("Failed to write DataFrame to %s.", table_name)
            raise DuckDBStoreError(f"Failed to write DataFrame to {table_name}.") from exc

        logger.info("Wrote %s rows to %s.", len(df), table_name)
        return len(df)

    def upsert_dataframe(self, table_name: str, df: pd.DataFrame) -> int:
        """Incrementally replace rows by table key columns and insert new data."""
        self._validate_table(table_name)
        if df.empty:
            logger.info("Skipped upserting empty DataFrame to %s.", table_name)
            return 0

        key_columns = self.KEY_COLUMNS[table_name]
        missing_keys = [column for column in key_columns if column not in df.columns]
        if missing_keys:
            raise DuckDBStoreError(
                f"DataFrame for {table_name} is missing key columns: {', '.join(missing_keys)}"
            )

        join_condition = " AND ".join(f"target.{column} = source.{column}" for column in key_columns)

        try:
            with self.connect() as connection:
                connection.register("input_df", df)
                connection.execute(
                    f"""
                    DELETE FROM {table_name} AS target
                    USING input_df AS source
                    WHERE {join_condition}
                    """
                )
                connection.execute(f"INSERT INTO {table_name} BY NAME SELECT * FROM input_df")
                connection.unregister("input_df")
        except Exception as exc:
            logger.exception("Failed to upsert DataFrame into %s.", table_name)
            raise DuckDBStoreError(f"Failed to upsert DataFrame into {table_name}.") from exc

        logger.info("Upserted %s rows into %s.", len(df), table_name)
        return len(df)

    def read_date_range(
        self,
        table_name: str,
        start_date: str,
        end_date: str,
        date_column: str | None = None,
    ) -> pd.DataFrame:
        """Read rows from a table where the date column is within a closed range."""
        self._validate_table(table_name)
        resolved_date_column = date_column or self.DATE_COLUMNS.get(table_name)
        if resolved_date_column is None:
            raise DuckDBStoreError(f"Table {table_name} does not have a configured date column.")

        try:
            with self.connect() as connection:
                return connection.execute(
                    f"""
                    SELECT *
                    FROM {table_name}
                    WHERE {resolved_date_column} BETWEEN ? AND ?
                    ORDER BY {resolved_date_column}
                    """,
                    [start_date, end_date],
                ).fetchdf()
        except Exception as exc:
            logger.exception("Failed to read date range from %s.", table_name)
            raise DuckDBStoreError(f"Failed to read date range from {table_name}.") from exc

    def read_table(self, table_name: str) -> pd.DataFrame:
        """Read an entire table into a DataFrame."""
        self._validate_table(table_name)
        try:
            with self.connect() as connection:
                return connection.execute(f"SELECT * FROM {table_name}").fetchdf()
        except Exception as exc:
            logger.exception("Failed to read table %s.", table_name)
            raise DuckDBStoreError(f"Failed to read table {table_name}.") from exc

    def _validate_table(self, table_name: str) -> None:
        """Reject unknown table names before building SQL statements."""
        if table_name not in self.KEY_COLUMNS:
            raise DuckDBStoreError(f"Unsupported table: {table_name}")
