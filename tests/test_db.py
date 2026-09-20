"""src/data/db.py: connection guards, per-call cursors, rebuild.

The guards matter because the May benchmark runs queried a DuckDB file built
from the pre-translation Korean-column data without noticing.
"""

import threading

import duckdb
import pandas as pd
import pyarrow as pa
import pytest

import config
from src.data import db


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Points the module at a throwaway database file."""
    original = db._conn
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_verified_conn", None)
    monkeypatch.setattr(config, "DUCKDB_PATH", tmp_path / "test.duckdb")
    yield tmp_path / "test.duckdb"
    if db._conn is not None:
        db._conn.close()
    db._conn = original
    db._verified_conn = None


class TestConnection:
    def test_returns_singleton(self):
        assert db.get_connection() is db.get_connection()

    def test_table_matches_released_schema(self):
        assert db.table_columns(db.get_connection()) == db.EXPECTED_COLUMNS

    def test_build_info_records_parquet_hash(self):
        info = db.build_info(db.get_connection())
        if info is None:
            pytest.skip("connection was installed from outside (no build metadata)")
        assert info["parquet_sha256"] == db.parquet_sha256()
        assert info["row_count"] == int(db.query("SELECT count(*) AS c FROM hofinet")["c"].iloc[0])

    def test_connection_info_reports_paths(self):
        info = db.connection_info()
        assert info["duckdb_path"].endswith(".duckdb")
        assert info["parquet_path"] == str(config.PARQUET_PATH)


class TestQuery:
    def test_returns_dataframe(self):
        assert isinstance(db.query("SELECT 1 AS val"), pd.DataFrame)

    def test_row_count(self):
        assert db.query("SELECT count(*) AS cnt FROM hofinet")["cnt"].iloc[0] == 4_732_130

    def test_english_columns(self):
        row = db.query("SELECT * FROM hofinet LIMIT 1")
        assert list(row.columns) == list(db.EXPECTED_COLUMNS)

    def test_parameter_binding(self):
        result = db.query("SELECT count(*) AS cnt FROM hofinet WHERE is_fraud = ?", [1])
        assert result["cnt"].iloc[0] == 14_490

    def test_named_parameter_binding(self):
        result = db.query(
            "SELECT count(*) AS cnt FROM hofinet WHERE fraud_type = $t", {"t": 7}
        )
        assert result["cnt"].iloc[0] == 35

    def test_query_arrow_returns_table(self):
        assert isinstance(db.query_arrow("SELECT * FROM hofinet LIMIT 5"), pa.Table)

    def test_external_file_access_is_disabled(self):
        if db.connection_info()["origin"] != "file":
            pytest.skip("external connection installed by the caller")
        with pytest.raises(duckdb.Error):
            db.query("SELECT * FROM read_csv_auto('/etc/hostname')")


class TestCursorIsolation:
    """Concurrent queries must not read each other's results."""

    def test_threads_get_their_own_results(self):
        queries = [
            ("SELECT count(*) AS c FROM hofinet WHERE fraud_type = 7", 35),
            ("SELECT count(*) AS c FROM hofinet WHERE is_fraud = 1", 14_490),
            ("SELECT count(*) AS c FROM hofinet WHERE time_slot = 3", 116),
        ]
        errors = []

        def run(sql, expected):
            for _ in range(20):
                try:
                    value = int(db.query(sql)["c"].iloc[0])
                except Exception as exc:  # noqa: BLE001 - reported below
                    errors.append(f"{sql}: {exc}")
                    return
                if value != expected:
                    errors.append(f"{sql}: {value} != {expected}")
                    return

        threads = [threading.Thread(target=run, args=q) for q in queries for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestDatabaseGuards:
    def test_refuses_korean_column_database(self, isolated_db):
        conn = duckdb.connect(str(isolated_db))
        conn.execute("CREATE TABLE hofinet AS SELECT 20210901 AS 거래일자, 1 AS 거래금액")
        conn.close()
        with pytest.raises(db.DatabaseMismatch):
            db.get_connection()

    def test_refuses_database_without_build_metadata(self, isolated_db):
        conn = duckdb.connect(str(isolated_db))
        conn.execute(
            f"CREATE TABLE hofinet AS SELECT * FROM read_parquet('{config.PARQUET_PATH.as_posix()}') LIMIT 10"
        )
        conn.close()
        with pytest.raises(db.DatabaseMismatch):
            db.get_connection()

    def test_refuses_database_built_from_another_parquet(self, isolated_db, monkeypatch):
        db.rebuild_database()
        probe = duckdb.connect(str(isolated_db))
        try:
            assert db.build_info(probe)["parquet_sha256"] == db.parquet_sha256()
        finally:
            probe.close()
        monkeypatch.setattr(db, "parquet_sha256", lambda: "0" * 64)
        with pytest.raises(db.DatabaseMismatch):
            db.get_connection()

    def test_rebuild_creates_a_verified_database(self, isolated_db):
        db.rebuild_database()
        assert db.query("SELECT count(*) AS c FROM hofinet")["c"].iloc[0] == 4_732_130
        assert db.connection_info()["build_info"]["parquet_sha256"] == db.parquet_sha256()

    def test_use_connection_checks_the_schema(self):
        stale = duckdb.connect(":memory:")
        stale.execute("CREATE TABLE hofinet AS SELECT 1 AS 거래일자")
        try:
            with pytest.raises(db.DatabaseMismatch):
                db.use_connection(stale)
        finally:
            stale.close()

    def test_file_sha256_is_stable(self):
        assert db.file_sha256(config.PARQUET_PATH) == db.parquet_sha256()
        assert len(db.parquet_sha256()) == 64


class TestConnectionLifecycle:
    def test_close_is_safe_when_already_closed(self, isolated_db):
        db.close()
        assert db._conn is None
        db.close()
