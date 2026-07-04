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


class DuckDBStoreLockedError(DuckDBStoreError):
    """Raised when the local DuckDB file is locked by another process."""


DUCKDB_LOCK_MESSAGE = "DuckDB is locked by another process. Please stop other running jobs or Streamlit first."
LOCK_ERROR_MARKERS = (
    "could not set lock",
    "conflicting lock",
    "Conflicting lock",
    "database is locked",
    "io error",
    "lock on file",
    "locked",
)


def is_duckdb_lock_error(exc: BaseException | str) -> bool:
    """Return whether an exception or message indicates a DuckDB file lock."""
    text = str(exc).lower()
    return any(marker in text for marker in LOCK_ERROR_MARKERS)


def friendly_duckdb_error(exc: BaseException) -> DuckDBStoreError:
    """Convert low-level DuckDB errors into user-facing storage errors."""
    if is_duckdb_lock_error(exc):
        return DuckDBStoreLockedError(DUCKDB_LOCK_MESSAGE)
    return DuckDBStoreError(str(exc) or "DuckDB operation failed.")


class DuckDBStore:
    """Small DuckDB wrapper for schema setup and DataFrame persistence."""

    DATE_COLUMNS: ClassVar[dict[str, str]] = {
        "trade_calendar": "cal_date",
        "daily_price": "trade_date",
        "daily_basic": "trade_date",
        "adj_factor": "trade_date",
        "update_failures": "target_end_date",
        "factor_values": "trade_date",
        "factor_scores": "trade_date",
        "strategy_result": "trade_date",
        "entry_zone_snapshots": "trade_date",
        "external_trades": "trade_date",
        "external_position_snapshots": "snapshot_date",
        "external_import_batches": "created_at",
        "backtest_result": "start_date",
        "review_decisions": "selection_date",
        "watchlist_snapshots": "snapshot_date",
        "watchlist_daily_snapshots": "trade_date",
        "watchlist_events": "event_date",
        "review_decision_history": "created_at",
        "positions": "entry_date",
    }

    KEY_COLUMNS: ClassVar[dict[str, tuple[str, ...]]] = {
        "stock_basic": ("ts_code",),
        "trade_calendar": ("exchange", "cal_date"),
        "daily_price": ("ts_code", "trade_date"),
        "daily_basic": ("ts_code", "trade_date"),
        "adj_factor": ("ts_code", "trade_date"),
        "update_failures": ("ts_code", "table_name", "target_end_date"),
        "factor_values": ("ts_code", "trade_date", "factor_name"),
        "factor_scores": ("ts_code", "trade_date"),
        "strategy_result": ("trade_date", "rank", "ts_code"),
        "entry_zone_snapshots": ("ts_code", "trade_date", "source"),
        "external_trades": ("id",),
        "external_position_snapshots": ("id",),
        "external_import_batches": ("batch_id",),
        "backtest_result": ("strategy_name", "start_date", "end_date", "created_at"),
        "review_decisions": ("ts_code", "selection_date"),
        "watchlist_snapshots": ("ts_code", "snapshot_date"),
        "watchlist_daily_snapshots": ("ts_code", "trade_date"),
        "watchlist_events": ("event_id",),
        "review_decision_history": ("history_id",),
        "positions": ("position_id",),
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
                self._apply_lightweight_migrations(connection)
        except DuckDBStoreError:
            raise
        except Exception as exc:
            logger.exception("Failed to initialize DuckDB schema at %s.", self.db_path)
            raise friendly_duckdb_error(exc) from exc

        logger.info("Initialized DuckDB schema at %s.", self.db_path)

    def _apply_lightweight_migrations(self, connection: duckdb.DuckDBPyConnection) -> None:
        """Apply additive schema changes for existing local DuckDB files."""
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('stock_basic')").fetchall()
        }
        if "exchange" not in columns:
            connection.execute("ALTER TABLE stock_basic ADD COLUMN exchange VARCHAR")
        self._add_columns_if_missing(
            connection,
            "watchlist_daily_snapshots",
            {
                "pe": "DOUBLE",
                "pb": "DOUBLE",
            },
        )
        self._add_columns_if_missing(
            connection,
            "strategy_result",
            {
                "close": "DOUBLE",
                "pe": "DOUBLE",
                "pb": "DOUBLE",
                "trend_score": "DOUBLE",
                "momentum_score": "DOUBLE",
                "liquidity_score": "DOUBLE",
                "fundamental_score": "DOUBLE",
                "volatility_score": "DOUBLE",
                "quality_score": "DOUBLE",
                "valuation_score": "DOUBLE",
                "risk_score": "DOUBLE",
                "created_at": "TIMESTAMP",
                "updated_at": "TIMESTAMP",
            },
        )
        self._add_columns_if_missing(
            connection,
            "adj_factor",
            {
                "derived_adj_factor": "BOOLEAN",
                "source_provider": "VARCHAR",
            },
        )

    def _add_columns_if_missing(
        self,
        connection: duckdb.DuckDBPyConnection,
        table_name: str,
        column_defs: dict[str, str],
    ) -> None:
        """Add missing columns to an existing table when the table exists."""
        try:
            existing = {row[1] for row in connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()}
        except Exception:
            return
        for column, data_type in column_defs.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {data_type}")

    def connect(self, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        """Open a DuckDB connection for this store."""
        try:
            return duckdb.connect(str(self.db_path), read_only=read_only)
        except Exception as exc:
            raise friendly_duckdb_error(exc) from exc

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
        except DuckDBStoreError:
            raise
        except Exception as exc:
            logger.exception("Failed to write DataFrame to %s.", table_name)
            raise friendly_duckdb_error(exc) from exc

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
        except DuckDBStoreError:
            raise
        except Exception as exc:
            logger.exception("Failed to upsert DataFrame into %s.", table_name)
            raise friendly_duckdb_error(exc) from exc

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
            with self.connect(read_only=True) as connection:
                return connection.execute(
                    f"""
                    SELECT *
                    FROM {table_name}
                    WHERE {resolved_date_column} BETWEEN ? AND ?
                    ORDER BY {resolved_date_column}
                    """,
                    [start_date, end_date],
                ).fetchdf()
        except DuckDBStoreError:
            raise
        except Exception as exc:
            logger.exception("Failed to read date range from %s.", table_name)
            raise friendly_duckdb_error(exc) from exc

    def read_table(self, table_name: str, *, limit: int | None = None, read_only: bool = True) -> pd.DataFrame:
        """Read an entire table into a DataFrame."""
        self._validate_table(table_name)
        try:
            query = f"SELECT * FROM {table_name}"
            if limit is not None and limit > 0:
                query = f"{query} LIMIT {int(limit)}"
            with self.connect(read_only=read_only) as connection:
                return connection.execute(query).fetchdf()
        except DuckDBStoreError:
            raise
        except Exception as exc:
            logger.exception("Failed to read table %s.", table_name)
            raise friendly_duckdb_error(exc) from exc

    def _validate_table(self, table_name: str) -> None:
        """Reject unknown table names before building SQL statements."""
        if table_name not in self.KEY_COLUMNS:
            raise DuckDBStoreError(f"Unsupported table: {table_name}")
