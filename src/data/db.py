"""DuckDB-based Analysis Query Interface.

DuckDB operates in-process without a server and supports 
multi-threaded parallel queries natively. It reads Parquet files
directly for fast analytic processing.
"""

import duckdb
import pandas as pd

import config
from src.data.loader import csv_to_parquet


_conn = None


def get_connection():
    """Returns the DuckDB connection (singleton)."""
    global _conn
    if _conn is None:
        _conn = duckdb.connect(str(config.DUCKDB_PATH))
        _conn.execute(f"SET threads TO {config.DUCKDB_THREADS}")
        _init_table()
    return _conn


def _init_table():
    """Creates the HOFINET table from Parquet data."""
    # Convert CSV to Parquet if not exists
    if not config.PARQUET_PATH.exists():
        csv_to_parquet()

    _conn.execute(f"""
        CREATE TABLE IF NOT EXISTS hofinet AS
        SELECT * FROM read_parquet('{config.PARQUET_PATH.as_posix()}')
    """ )

    count = _conn.execute("SELECT count(*) FROM hofinet").fetchone()[0]
    return count


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
