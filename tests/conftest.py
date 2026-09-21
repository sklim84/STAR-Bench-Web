"""Shared fixtures for the tool-layer test suite.

Tests query the released HOFINET Parquet through the platform's own connection
path (`src.data.db.get_connection`), so the schema and hash guards are
exercised by the suite itself rather than bypassed with a private connection.
Set HOFINET_DUCKDB_PATH to build the test database outside the app's copy.

Every database-backed test is skipped when the Parquet is absent, which is the
case in a fresh clone of the public repository.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session", autouse=True)
def database():
    """Opens the shared read-only connection once for the whole session."""
    import config

    if not config.PARQUET_PATH.exists():
        pytest.skip(
            f"transactions.parquet not found at {config.PARQUET_PATH} — "
            "place the parquet locally to enable the DB-backed tests.",
            allow_module_level=True,
        )

    from src.data import db

    conn = db.get_connection()
    yield conn


@pytest.fixture(scope="session")
def model():
    """The released detector artifact, or a skip when it is not shipped."""
    from src.features.detector import load_model

    trained = load_model()
    if trained is None:
        pytest.skip("detector model artifact not present")
    return trained


@pytest.fixture(scope="session")
def accounts():
    """Real account ids by role: sender-only, receiver-only, and both."""
    from src.data.db import query

    row = query("""
        WITH senders AS (SELECT DISTINCT sender_acc AS acc FROM hofinet),
             receivers AS (SELECT DISTINCT receiver_acc AS acc FROM hofinet)
        SELECT
            (SELECT min(acc) FROM senders WHERE acc NOT IN (SELECT acc FROM receivers)) AS sender_only,
            (SELECT min(acc) FROM receivers WHERE acc NOT IN (SELECT acc FROM senders)) AS receiver_only,
            (SELECT min(acc) FROM senders WHERE acc IN (SELECT acc FROM receivers)) AS both_roles,
            (SELECT sender_acc FROM hofinet WHERE is_fraud = 1
             GROUP BY sender_acc ORDER BY count(*) DESC, sender_acc LIMIT 1) AS most_fraud
    """).iloc[0]
    return {
        "sender_only": int(row["sender_only"]),
        "receiver_only": int(row["receiver_only"]),
        "both_roles": int(row["both_roles"]),
        "most_fraud": int(row["most_fraud"]),
        "absent": 1234567890,
    }


@pytest.fixture(scope="session")
def banks():
    """A bank that only sends, one that only receives, and one that does both."""
    from src.data.db import query

    row = query("""
        WITH s AS (SELECT DISTINCT sender_bank AS b FROM hofinet),
             r AS (SELECT DISTINCT receiver_bank AS b FROM hofinet)
        SELECT (SELECT min(b) FROM s WHERE b NOT IN (SELECT b FROM r)) AS sender_only,
               (SELECT min(b) FROM r WHERE b NOT IN (SELECT b FROM s)) AS receiver_only,
               (SELECT min(b) FROM s WHERE b IN (SELECT b FROM r)) AS both_roles
    """).iloc[0]
    return {
        "sender_only": int(row["sender_only"]),
        "receiver_only": int(row["receiver_only"]),
        "both_roles": int(row["both_roles"]),
        "absent": 500,
    }
