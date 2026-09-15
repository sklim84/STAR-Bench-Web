"""DuckDB-based analysis query interface.

DuckDB runs in-process and reads the released HOFINET Parquet file directly.
Every caller -- the Streamlit pages, the agent tools, the benchmark runners --
goes through :func:`get_connection`, so there is exactly one database behind the
tool layer and one place that checks it is the database the release describes.

Two guards matter for reproducibility:

* the DuckDB file records the sha256 and row count of the Parquet it was built
  from, and a file whose schema or source hash does not match the Parquet on
  disk is refused instead of silently reused (an older build with Korean column
  names, for instance);
* queries run on a per-call cursor, so concurrent worker threads cannot read
  each other's results.
"""

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone

import duckdb
import pandas as pd

import config
from src.data.loader import csv_to_parquet


TABLE_NAME = "hofinet"
BUILD_INFO_TABLE = "_hofinet_build_info"

# Column names and DuckDB types the released Parquet defines. A connection whose
# hofinet table does not match this exactly is rejected.
EXPECTED_COLUMNS = {
    "date": "INTEGER",
    "time_slot": "TINYINT",
    "sender_bank": "SMALLINT",
    "sender_acc": "BIGINT",
    "receiver_bank": "SMALLINT",
    "receiver_acc": "BIGINT",
    "fund_type": "TINYINT",
    "media_type": "TINYINT",
    "amount": "BIGINT",
    "is_fraud": "TINYINT",
    "fraud_type": "TINYINT",
    "fraud_description": "VARCHAR",
}

_conn = None
_conn_origin = "file"
_verified_conn = None
_lock = threading.RLock()

_BUILD_ATTEMPTS = 30
_BUILD_WAIT_SEC = 2.0

_sha_cache: dict[str, tuple[int, int, str]] = {}


class DatabaseMismatch(RuntimeError):
    """Raised when the DuckDB file does not match the released Parquet."""


def file_sha256(path) -> str:
    """Returns the sha256 of a file, cached per (size, mtime)."""
    path = str(path)
    stat = os.stat(path)
    cached = _sha_cache.get(path)
    if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
        return cached[2]
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _sha_cache[path] = (stat.st_size, stat.st_mtime_ns, value)
    return value


def parquet_sha256() -> str:
    """Returns the sha256 of the released HOFINET Parquet file."""
    return file_sha256(config.PARQUET_PATH)


def table_columns(conn) -> dict:
    """Returns {column name: DuckDB type} for the hofinet table of a connection."""
    rows = conn.execute(f"DESCRIBE {TABLE_NAME}").fetchall()
    return {row[0]: row[1] for row in rows}


def check_schema(conn) -> None:
    """Raises DatabaseMismatch unless the connection holds the expected table."""
    try:
        columns = table_columns(conn)
    except duckdb.Error as exc:
        raise DatabaseMismatch(f"table '{TABLE_NAME}' is missing: {exc}") from exc
    if columns != EXPECTED_COLUMNS:
        raise DatabaseMismatch(
            f"'{TABLE_NAME}' columns do not match the released schema.\n"
            f"  expected: {EXPECTED_COLUMNS}\n"
            f"  found:    {columns}"
        )


def build_info(conn) -> dict | None:
    """Returns the recorded build metadata of a connection, if any."""
    try:
        row = conn.execute(
            f"SELECT parquet_sha256, row_count, built_at, columns FROM {BUILD_INFO_TABLE}"
        ).fetchone()
    except duckdb.Error:
        return None
    if not row:
        return None
    return {
        "parquet_sha256": row[0],
        "row_count": int(row[1]),
        "built_at": row[2],
        "columns": json.loads(row[3]),
    }


def _check_file_database(conn) -> None:
    """Raises DatabaseMismatch unless the file database matches the Parquet."""
    check_schema(conn)
    info = build_info(conn)
    if info is None:
        raise DatabaseMismatch(
            f"{config.DUCKDB_PATH} carries no build metadata, so it cannot be "
            "matched against the released Parquet."
        )
    expected = parquet_sha256()
    if info["parquet_sha256"] != expected:
        raise DatabaseMismatch(
            f"{config.DUCKDB_PATH} was built from a different Parquet file "
            f"(recorded {info['parquet_sha256'][:16]}..., current {expected[:16]}...)."
        )
    rows = conn.execute(f"SELECT count(*) FROM {TABLE_NAME}").fetchone()[0]
    if int(rows) != info["row_count"]:
        raise DatabaseMismatch(
            f"{config.DUCKDB_PATH} holds {rows} rows but records {info['row_count']}."
        )


def _database_ready() -> bool:
    """True if the database file exists and matches the released Parquet.

    Raises DatabaseMismatch for a database that exists but is stale, so the
    caller stops instead of running the benchmark on the wrong data.
    """
    if not config.DUCKDB_PATH.exists():
        return False
    try:
        probe = duckdb.connect(str(config.DUCKDB_PATH), read_only=True)
    except duckdb.Error:
        return False
    try:
        _check_file_database(probe)
    except DatabaseMismatch as exc:
        raise DatabaseMismatch(
            f"{exc}\nRebuild it with "
            f"`python -m src.data.db rebuild` (or delete the file) and rerun."
        ) from None
    finally:
        probe.close()
    return True


def _write_table(builder) -> None:
    builder.execute(f"""
        CREATE OR REPLACE TABLE {TABLE_NAME} AS
        SELECT * FROM read_parquet('{config.PARQUET_PATH.as_posix()}')
    """)
    rows = builder.execute(f"SELECT count(*) FROM {TABLE_NAME}").fetchone()[0]
    columns = table_columns(builder)
    builder.execute(f"DROP TABLE IF EXISTS {BUILD_INFO_TABLE}")
    builder.execute(f"""
        CREATE TABLE {BUILD_INFO_TABLE} (
            parquet_sha256 VARCHAR, row_count BIGINT, built_at VARCHAR, columns VARCHAR
        )
    """)
    builder.execute(
        f"INSERT INTO {BUILD_INFO_TABLE} VALUES (?, ?, ?, ?)",
        [
            parquet_sha256(),
            int(rows),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(columns),
        ],
    )


def rebuild_database() -> str:
    """Rebuilds the DuckDB file from the Parquet and returns its path.

    The table is written to a temporary file and moved into place, so readers
    that already hold the old file keep working.
    """
    if not config.PARQUET_PATH.exists():
        csv_to_parquet()
    target = config.DUCKDB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".build")
    for leftover in (tmp, tmp.with_suffix(tmp.suffix + ".wal")):
        if leftover.exists():
            leftover.unlink()
    builder = duckdb.connect(str(tmp))
    try:
        _write_table(builder)
    finally:
        builder.close()
    os.replace(tmp, target)
    return str(target)


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
            _write_table(builder)
        finally:
            builder.close()
        return

    raise RuntimeError(
        f"Timed out waiting for {config.DUCKDB_PATH} to be built "
        f"({_BUILD_ATTEMPTS * _BUILD_WAIT_SEC:.0f}s). Another process may hold "
        f"the write lock; remove the file to force a rebuild."
    )


def get_connection():
    """Returns the DuckDB connection (singleton, read-only, schema-checked)."""
    global _conn, _conn_origin
    with _lock:
        if _conn is None:
            _ensure_database()
            _conn = duckdb.connect(
                str(config.DUCKDB_PATH),
                read_only=True,
                config={"threads": config.DUCKDB_THREADS, "enable_external_access": False},
            )
            _conn_origin = "file"
        return _verified(_conn)


def use_connection(conn, origin: str = "external"):
    """Installs an already-built connection (in-memory fixtures, runners).

    The connection is checked against the released schema before it is used, so
    a table built from stale data fails here rather than deep inside a tool.
    """
    global _conn, _conn_origin
    with _lock:
        check_schema(conn)
        _conn = conn
        _conn_origin = origin
        return _verified(conn)


def _verified(conn):
    """Checks a connection's schema once per connection object."""
    global _verified_conn
    if conn is not _verified_conn:
        check_schema(conn)
        _verified_conn = conn
    return conn


def connection_info() -> dict:
    """Returns what the tool layer is currently querying."""
    with _lock:
        origin = _conn_origin if _conn is not None else None
        info = None
        if _conn is not None:
            try:
                info = build_info(_conn)
            except duckdb.Error:
                info = None
    return {
        "origin": origin,
        "duckdb_path": str(config.DUCKDB_PATH),
        "parquet_path": str(config.PARQUET_PATH),
        "build_info": info,
    }


def query(sql: str, params=None) -> pd.DataFrame:
    """Executes an SQL query and returns a pandas DataFrame.

    Each call runs on its own cursor: DuckDB connections are not thread-safe,
    and worker threads sharing one connection used to receive each other's
    results.
    """
    with _cursor() as cur:
        if params:
            return cur.execute(sql, params).fetchdf()
        return cur.execute(sql).fetchdf()


def query_arrow(sql: str, params=None):
    """Executes an SQL query and returns a PyArrow Table."""
    with _cursor() as cur:
        if params:
            return cur.execute(sql, params).fetch_arrow_table()
        return cur.execute(sql).fetch_arrow_table()


class _cursor:
    """Per-call DuckDB cursor on the shared connection."""

    def __enter__(self):
        conn = get_connection()
        with _lock:
            self._cur = conn.cursor()
        return self._cur

    def __exit__(self, exc_type, exc, tb):
        self._cur.close()
        return False


def close():
    """Closes the DuckDB connection."""
    global _conn, _verified_conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        _verified_conn = None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        print(f"rebuilt {rebuild_database()}")
    else:
        print(json.dumps(connection_info() if _conn else {"duckdb_path": str(config.DUCKDB_PATH)}, indent=2))
