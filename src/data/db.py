"""DuckDB 기반 분석 쿼리 인터페이스.

DuckDB는 서버 없이 프로세스 내에서 동작하며,
멀티스레드 병렬 쿼리를 기본 지원한다.
Parquet 파일을 직접 읽어 빠른 분석 쿼리를 실행한다.
"""

import duckdb
import pandas as pd

import config
from src.data.loader import csv_to_parquet


_conn = None


def get_connection():
    """DuckDB 연결을 반환한다 (싱글턴)."""
    global _conn
    if _conn is None:
        _conn = duckdb.connect(str(config.DUCKDB_PATH))
        _conn.execute(f"SET threads TO {config.DUCKDB_THREADS}")
        _init_table()
    return _conn


def _init_table():
    """HOFINET 테이블을 Parquet 데이터로 생성한다."""
    # Parquet 파일이 없으면 CSV에서 변환
    if not config.PARQUET_PATH.exists():
        csv_to_parquet()

    _conn.execute(f"""
        CREATE TABLE IF NOT EXISTS hofinet AS
        SELECT * FROM read_parquet('{config.PARQUET_PATH.as_posix()}')
    """)

    count = _conn.execute("SELECT count(*) FROM hofinet").fetchone()[0]
    return count


def query(sql: str, params=None) -> pd.DataFrame:
    """SQL 쿼리를 실행하고 DataFrame으로 반환한다."""
    conn = get_connection()
    if params:
        return conn.execute(sql, params).fetchdf()
    return conn.execute(sql).fetchdf()


def query_arrow(sql: str, params=None):
    """SQL 쿼리를 실행하고 PyArrow Table로 반환한다."""
    conn = get_connection()
    if params:
        return conn.execute(sql, params).fetch_arrow_table()
    return conn.execute(sql).fetch_arrow_table()


def close():
    """DuckDB 연결을 닫는다."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
