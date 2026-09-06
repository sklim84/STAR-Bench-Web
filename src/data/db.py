"""DuckDB-based Analysis Query Interface.

DuckDB operates in-process without a server and supports 
multi-threaded parallel queries natively. It reads Parquet files
directly for fast analytic processing.
"""

import time

import duckdb
import pandas as pd

import config
from src.data.loader import csv_to_parquet


_conn = None

# A DuckDB file opened read-write takes an exclusive lock, so a second process
# fails with "IO Error: Could not set lock on file". Every query issued through
# this module is a read (agent tool SQL rejects DROP/DELETE/INSERT/UPDATE/
# ALTER/CREATE/TRUNCATE outright), so the table is materialised once and every
# connection after that is read-only. Read-only connections do not take the
# exclusive lock, which is what lets several evaluation runs share one database.
_BUILD_ATTEMPTS = 30
_BUILD_WAIT_SEC = 2.0


def get_connection():
    """Returns the DuckDB connection (singleton, read-only)."""
    global _conn
    if _conn is None:
        _ensure_database()
        _conn = duckdb.connect(str(config.DUCKDB_PATH), read_only=True)
        _conn.execute(f"SET threads TO {config.DUCKDB_THREADS}")
    return _conn


def _database_ready() -> bool:
    """True if the database exists and already holds the hofinet table."""
    if not config.DUCKDB_PATH.exists():
        return False
    try:
        probe = duckdb.connect(str(config.DUCKDB_PATH), read_only=True)
    except duckdb.Error:
        return False
    try:
        probe.execute("SELECT 1 FROM hofinet LIMIT 1")
        return True
    except duckdb.Error:
        return False
    finally:
        probe.close()


def _ensure_database() -> None:
    """Materialises the HOFINET table once, in write mode.

    Concurrent starts are expected: whichever process gets the write lock builds
    the table, the others wait for it to finish and then see a ready database.
    """
    for _ in range(_BUILD_ATTEMPTS):
        if _database_ready():
            return
        if not config.PARQUET_PATH.exists():
            csv_to_parquet()
        try:
            builder = duckdb.connect(str(config.DUCKDB_PATH))
        except duckdb.Error:
            # Another process holds the write lock; wait for it to finish.
            time.sleep(_BUILD_WAIT_SEC)
            continue
        try:
            builder.execute(f"""
                CREATE TABLE IF NOT EXISTS hofinet AS
                SELECT * FROM read_parquet('{config.PARQUET_PATH.as_posix()}')
            """)
        finally:
            builder.close()
        return

    raise RuntimeError(
        f"Timed out waiting for {config.DUCKDB_PATH} to be built "
        f"({_BUILD_ATTEMPTS * _BUILD_WAIT_SEC:.0f}s). Another process may hold "
        f"the write lock; remove the file to force a rebuild."
    )


def query(sql: str, params=None) -> pd.DataFrame:
    """Executes an SQL query and returns a pandas DataFrame."""
    conn = get_connection()
    if params:
        return conn.execute(sql, params).fetchdf()
    return conn.execute(sql).fetchdf()


def query_arrow(sql: str, params=None):
    """Executes an SQL query and returns a PyArrow Table."""
    conn = get_connection()
    if params:
        return conn.execute(sql, params).fetch_arrow_table()
    return conn.execute(sql).fetch_arrow_table()


def close():
    """Closes the DuckDB connection."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
