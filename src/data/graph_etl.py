"""DuckDB -> Memgraph Data Loading (ETL) Module.

Converts transaction data from the HOFINET table into a Memgraph graph model.
Nodes: Account, Company
Edges: TRANSFER, BELONGS_TO

Graph Model:
    (:Company {id})
    (:Account {id, company_id})
    (:Account)-[:BELONGS_TO]->(:Company)
    (:Account)-[:TRANSFER {
        date, time_slot, fund_type, media_type, amount, is_fraud, fraud_type
    }]->(:Account)
"""

import logging
import time

import pandas as pd

from src.data import db
from src.data import graph_db

logger = logging.getLogger(__name__)


def run_etl(batch_size: int = 10000) -> dict:
    """Executes the entire ETL process.

    Reads HOFINET data from DuckDB and loads it into the Memgraph graph.
    If data already exists (nodes > 0), it skips and returns the existing counts.
    If Memgraph is not running, it returns a dict with error information.

    Args:
        batch_size: Batch insertion unit (default 10000)

    Returns:
        dict: {
            "accounts": account node count,
            "companies": company node count,
            "transfers": transfer edge count,
            "elapsed_sec": elapsed time in seconds
        }
        When Memgraph is not running: {"error": "Memgraph not running"}
    """
    if not graph_db.is_available():
        logger.warning("Skipping ETL as Memgraph is not running")
        return {"error": "Memgraph not running"}

    # Check if data already exists
    stats = get_graph_stats()
    if stats.get("accounts", 0) > 0:
        logger.info(
            "Graph data already exists (accounts=%d, transfers=%d). Skipping ETL.",
            stats["accounts"],
            stats["transfers"],
        )
        stats["elapsed_sec"] = 0.0
        return stats

    start = time.time()
    logger.info("Starting ETL: DuckDB -> Memgraph")

    # 1. Create indexes
    _create_indexes()

    # 2. Load company nodes
    company_count = _load_companies()
    logger.info("Company nodes loaded: %d", company_count)

    # 3. Load account nodes + BELONGS_TO relationships
    account_count = _load_accounts(batch_size)
    logger.info("Account nodes loaded: %d", account_count)

    # 4. Load transfer edges
    transfer_count = _load_transfers(batch_size)
    logger.info("Transfer edges loaded: %d", transfer_count)

    elapsed = time.time() - start
    logger.info("ETL completed: %.1f seconds", elapsed)

    return {
        "accounts": account_count,
        "companies": company_count,
        "transfers": transfer_count,
        "elapsed_sec": round(elapsed, 1),
    }


def _create_indexes():
    """Creates Memgraph indexes.

    Indexes are created before node creation to improve MERGE performance.
    Existing indexes are ignored.
    """
    index_queries = [
        "CREATE INDEX ON :Account(id)",
        "CREATE INDEX ON :Company(id)",
    ]
    for q in index_queries:
        try:
            graph_db.execute(q)
        except Exception:  # noqa: BLE001
            # Ignore if index already exists
            pass
    logger.info("Indexes created")


def _load_companies() -> int:
    """Creates unique company nodes.

    Extracts unique company IDs from HOFINET sender/receiver banks in DuckDB
    and creates Company nodes in Memgraph.

    Returns:
        int: Number of company nodes created
    """
    df = db.query("""
        SELECT DISTINCT company_id FROM (
            SELECT DISTINCT sender_bank AS company_id FROM hofinet
            UNION
            SELECT DISTINCT receiver_bank AS company_id FROM hofinet
        )
        ORDER BY company_id
    """)

    if df.empty:
        return 0

    batch = [{"id": int(row["company_id"])} for _, row in df.iterrows()]
    graph_db.execute(
        "UNWIND $batch AS row MERGE (:Company {id: row.id})",
        {"batch": batch},
    )
    return len(batch)


def _load_accounts(batch_size: int) -> int:
    """Creates unique account nodes and BELONGS_TO relationships.

    Extracts account-company mappings from DuckDB and creates
    Account nodes and BELONGS_TO edges in Memgraph.

    Args:
        batch_size: Batch insertion unit

    Returns:
        int: Number of account nodes created
    """
    df = db.query("""
        SELECT DISTINCT account_id, company_id FROM (
            SELECT DISTINCT
                sender_acc AS account_id,
                sender_bank AS company_id
            FROM hofinet
            UNION
            SELECT DISTINCT
                receiver_acc AS account_id,
                receiver_bank AS company_id
            FROM hofinet
        )
        ORDER BY account_id
    """)

    if df.empty:
        return 0

    total = len(df)
    loaded = 0

    for i in range(0, total, batch_size):
        chunk = df.iloc[i : i + batch_size]
        batch = [
            {"id": int(row["account_id"]), "company_id": int(row["company_id"])}
            for _, row in chunk.iterrows()
        ]
        graph_db.execute(
            """
            UNWIND $batch AS row
            MERGE (a:Account {id: row.id})
            ON CREATE SET a.company_id = row.company_id
            WITH a, row
            MATCH (c:Company {id: row.company_id})
            MERGE (a)-[:BELONGS_TO]->(c)
            """,
            {"batch": batch},
        )
        loaded += len(batch)
        if (i // batch_size + 1) % 10 == 0 or loaded >= total:
            logger.info("Account node loading progress: %d / %d", loaded, total)

    return total


def _load_transfers(batch_size: int) -> int:
    """Creates transfer edges in batches.

    Reads transaction data from DuckDB in batches and
    inserts them as TRANSFER relationships in Memgraph.

    Args:
        batch_size: Batch insertion unit

    Returns:
        int: Number of transfer edges created
    """
    # Get total count
    count_df = db.query("SELECT count(*) AS cnt FROM hofinet")
    total = int(count_df["cnt"].iloc[0])

    if total == 0:
        return 0

    loaded = 0
    num_batches = (total + batch_size - 1) // batch_size

    for batch_idx in range(num_batches):
        offset = batch_idx * batch_size
        df = db.query(f"""
            SELECT
                sender_acc AS source,
                receiver_acc AS target,
                date,
                time_slot,
                fund_type,
                media_type,
                amount,
                is_fraud,
                fraud_type
            FROM hofinet
            LIMIT {batch_size} OFFSET {offset}
        """)

        if df.empty:
            break

        batch = _df_to_transfer_batch(df)
        graph_db.execute(
            """
            UNWIND $batch AS row
            MATCH (a:Account {id: row.source})
            MATCH (b:Account {id: row.target})
            CREATE (a)-[:TRANSFER {
                date: row.date,
                time_slot: row.time_slot,
                fund_type: row.fund_type,
                media_type: row.media_type,
                amount: row.amount,
                is_fraud: row.is_fraud,
                fraud_type: row.fraud_type
            }]->(b)
            """,
            {"batch": batch},
        )
        loaded += len(batch)
        if (batch_idx + 1) % 50 == 0 or (batch_idx + 1) == num_batches:
            logger.info(
                "Transfer edge loading progress: %d / %d (Batch %d/%d)",
                loaded,
                total,
                batch_idx + 1,
                num_batches,
            )

    return loaded


def _df_to_transfer_batch(df: pd.DataFrame) -> list:
    """Converts DataFrame to a list of dicts for TRANSFER edge batching.

    Handles NaN values appropriately and converts int64 values to Python int.

    Args:
        df: Transaction data DataFrame

    Returns:
        list[dict]: List of dicts for Cypher UNWIND
    """
    records = []
    for _, row in df.iterrows():
        records.append({
            "source": int(row["source"]),
            "target": int(row["target"]),
            "date": int(row["date"]),
            "time_slot": int(row["time_slot"]),
            "fund_type": int(row["fund_type"]),
            "media_type": int(row["media_type"]),
            "amount": int(row["amount"]),
            "is_fraud": int(row["is_fraud"]),
            "fraud_type": int(row["fraud_type"]) if pd.notna(row["fraud_type"]) else 0,
        })
    return records


def clear_graph():
    """Deletes the entire graph (for dev/test).

    Deletes all nodes and edges.
    Does nothing if Memgraph is not running.
    """
    if not graph_db.is_available():
        logger.warning("Skipping graph deletion as Memgraph is not running")
        return

    graph_db.execute("MATCH (n) DETACH DELETE n")
    logger.info("Entire graph deleted")


def get_graph_stats() -> dict:
    """Returns node/edge counts of the current graph.

    Returns:
        dict: {
            "accounts": Account node count,
            "companies": Company node count,
            "transfers": TRANSFER edge count,
            "belongs_to": BELONGS_TO edge count
        }
        Returns a dict with all values as 0 if Memgraph is not running.
    """
    empty_stats = {
        "accounts": 0,
        "companies": 0,
        "transfers": 0,
        "belongs_to": 0,
    }

    if not graph_db.is_available():
        return empty_stats

    records = graph_db.execute("""
        MATCH (a:Account) WITH count(a) AS accounts
        MATCH (c:Company) WITH accounts, count(c) AS companies
        OPTIONAL MATCH ()-[t:TRANSFER]->() WITH accounts, companies, count(t) AS transfers
        OPTIONAL MATCH ()-[b:BELONGS_TO]->() WITH accounts, companies, transfers, count(b) AS belongs_to
        RETURN accounts, companies, transfers, belongs_to
    """)

    if not records:
        return empty_stats

    rec = records[0]
    return {
        "accounts": rec.get("accounts", 0),
        "companies": rec.get("companies", 0),
        "transfers": rec.get("transfers", 0),
        "belongs_to": rec.get("belongs_to", 0),
    }
