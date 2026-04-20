"""Feature 2: Network (Graph) Analysis Query and Graph Construction Module."""

import logging

import networkx as nx
import pandas as pd
import streamlit as st

from src.data.db import query
from src.data import graph_db
from src.features.aml_reference import FRAUD_TYPE_MAP, FUND_TYPE_MAP

logger = logging.getLogger(__name__)


@st.cache_data(ttl=300, show_spinner=False)
def get_bank_network() -> pd.DataFrame:
    """Returns inter-institution transaction network data."""
    return query("""
        SELECT
            sender_bank as source,
            receiver_bank as target,
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            sum(amount) as total_amount
        FROM hofinet
        GROUP BY source, target
        ORDER BY total_txns DESC
    """)


@st.cache_data(ttl=300, show_spinner=False)
def get_fraud_account_network(limit: int = 500) -> pd.DataFrame:
    """Returns inter-account network data related to fraud."""
    limit = int(limit)
    df = query(f"""
        SELECT
            sender_acc as source,
            receiver_acc as target,
            count(*) as tx_count,
            sum(amount) as total_amount,
            max(fraud_type) as fraud_type
        FROM hofinet
        WHERE is_fraud = 1
        GROUP BY source, target
        ORDER BY tx_count DESC
        LIMIT {limit}
    """)
    if not df.empty:
        df["fraud_desc"] = df["fraud_type"].map(FRAUD_TYPE_MAP).fillna("Other")
    return df


def get_account_ego_network(account_id: int, hops: int = 1) -> pd.DataFrame:
    """Returns the ego network (n-hop neighbors) of a specific account."""
    account_id = int(account_id)
    if hops == 1:
        return query(
            """
            SELECT
                sender_acc as source,
                receiver_acc as target,
                count(*) as tx_count,
                sum(amount) as total_amount,
                max(is_fraud) as is_fraud
            FROM hofinet
            WHERE sender_acc = ?
               OR receiver_acc = ?
            GROUP BY source, target
            """,
            [account_id, account_id],
        )
    # 2-hop: Includes transactions of 1-hop neighbors
    return query(f"""
        WITH hop1 AS (
            SELECT DISTINCT
                CASE WHEN sender_acc = {account_id}
                     THEN receiver_acc ELSE sender_acc END as neighbor
            FROM hofinet
            WHERE sender_acc = {account_id}
               OR receiver_acc = {account_id}
        )
        SELECT
            sender_acc as source,
            receiver_acc as target,
            count(*) as tx_count,
            sum(amount) as total_amount,
            max(is_fraud) as is_fraud
        FROM hofinet
        WHERE sender_acc = {account_id}
           OR receiver_acc = {account_id}
           OR sender_acc IN (SELECT neighbor FROM hop1)
           OR receiver_acc IN (SELECT neighbor FROM hop1)
        GROUP BY source, target
    """)


@st.cache_data(ttl=300, show_spinner=False)
def get_fraud_accounts() -> pd.DataFrame:
    """Returns a list of sender accounts involved in fraud."""
    return query("""
        SELECT DISTINCT sender_acc as account_id
        FROM hofinet
        WHERE is_fraud = 1
        ORDER BY account_id
    """)


@st.cache_data(ttl=300, show_spinner=False)
def get_bank_network_stats() -> pd.DataFrame:
    """Returns summary statistics for the institution network."""
    return query("""
        SELECT
            count(DISTINCT sender_bank) as sender_banks,
            count(DISTINCT receiver_bank) as receiver_banks,
            count(DISTINCT (CAST(sender_bank AS INT) * 1000 + CAST(receiver_bank AS INT))) as connection_count
        FROM hofinet
    """)


def build_bank_graph(df: pd.DataFrame) -> nx.DiGraph:
    """Creates an inter-institution network graph from a DataFrame."""
    G = nx.DiGraph()
    for _, row in df.iterrows():
        G.add_edge(
            str(int(row["source"])),
            str(int(row["target"])),
            weight=int(row["total_txns"]),
            fraud=int(row["fraud_txns"]),
            amount=float(row["total_amount"]),
        )
    return G


def build_account_graph(df: pd.DataFrame) -> nx.DiGraph:
    """Creates an inter-account network graph from a DataFrame."""
    G = nx.DiGraph()
    for _, row in df.iterrows():
        G.add_edge(
            str(int(row["source"])),
            str(int(row["target"])),
            weight=int(row["tx_count"]),
            amount=float(row["total_amount"]),
        )
    return G


# ------------------------------------------------------------------
# Enhanced Feature: Centrality Metric Analysis
# ------------------------------------------------------------------

def compute_centrality_metrics(G: nx.DiGraph) -> pd.DataFrame:
    """Calculates major network centrality metrics and returns them as a DataFrame.

    Parameters
    ----------
    G : nx.DiGraph
        Target directed graph for analysis.

    Returns
    -------
    pd.DataFrame
        Columns: Node, degree, betweenness, closeness, eigenvector
    """
    if len(G.nodes()) == 0:
        return pd.DataFrame(columns=["Node", "degree", "betweenness", "closeness", "eigenvector"])

    degree = dict(G.degree())
    betweenness = nx.betweenness_centrality(G, weight="weight")
    closeness = nx.closeness_centrality(G)

    try:
        eigenvector = nx.eigenvector_centrality(G, max_iter=300, weight="weight")
    except nx.PowerIterationFailedConvergence:
        eigenvector = {n: 0.0 for n in G.nodes()}

    nodes = list(G.nodes())
    df = pd.DataFrame({
        "Node": nodes,
        "degree": [degree[n] for n in nodes],
        "betweenness": [round(betweenness[n], 6) for n in nodes],
        "closeness": [round(closeness[n], 6) for n in nodes],
        "eigenvector": [round(eigenvector[n], 6) for n in nodes],
    })
    return df.sort_values("degree", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------
# Enhanced Feature: Community Detection
# ------------------------------------------------------------------

def detect_communities(G: nx.DiGraph) -> pd.DataFrame:
    """Performs community detection based on greedy modularity.

    Converts DiGraph to undirected, applies greedy_modularity_communities,
    and returns a DataFrame with community labels for each node.

    Parameters
    ----------
    G : nx.DiGraph
        Target directed graph for analysis.

    Returns
    -------
    pd.DataFrame
        Columns: Node, Community
    """
    if len(G.nodes()) == 0:
        return pd.DataFrame(columns=["Node", "Community"])

    G_undirected = G.to_undirected()
    communities = nx.community.greedy_modularity_communities(G_undirected, weight="weight")

    node_community = {}
    for idx, community in enumerate(communities):
        for node in community:
            node_community[node] = idx

    df = pd.DataFrame({
        "Node": list(node_community.keys()),
        "Community": list(node_community.values()),
    })
    return df.sort_values("Community").reset_index(drop=True)


# ------------------------------------------------------------------
# Enhanced Feature: Inter-institution Fraud Flow Matrix
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_fraud_flow_matrix() -> pd.DataFrame:
    """Returns inter-institution fraud flow matrix data.

    Returns
    -------
    pd.DataFrame
        Columns: source, target, fraud_count, fraud_amount
    """
    return query("""
        SELECT
            sender_bank as source,
            receiver_bank as target,
            sum(is_fraud) as fraud_count,
            sum(amount) as fraud_amount
        FROM hofinet
        WHERE is_fraud = 1
        GROUP BY source, target
        HAVING fraud_count > 0
        ORDER BY fraud_count DESC
    """)


# ------------------------------------------------------------------
# Enhanced Feature: Extended Network Statistics
# ------------------------------------------------------------------

def get_extended_network_stats(G: nx.DiGraph) -> dict:
    """Calculates extended network statistics and returns them as a dictionary.

    Parameters
    ----------
    G : nx.DiGraph
        Target directed graph for analysis.

    Returns
    -------
    dict
        Density, average clustering coefficient, hub node, etc.
    """
    if len(G.nodes()) == 0:
        return {
            "node_count": 0,
            "edge_count": 0,
            "density": 0.0,
            "avg_clustering": 0.0,
            "hub_node": "-",
            "hub_degree": 0,
        }

    density = nx.density(G)

    G_undirected = G.to_undirected()
    avg_clustering = nx.average_clustering(G_undirected, weight="weight")

    degree_dict = dict(G.degree())
    hub_node = max(degree_dict, key=degree_dict.get)
    hub_degree = degree_dict[hub_node]

    return {
        "node_count": len(G.nodes()),
        "edge_count": len(G.edges()),
        "density": round(density, 4),
        "avg_clustering": round(avg_clustering, 4),
        "hub_node": hub_node,
        "hub_degree": hub_degree,
    }


# ==================================================================
# Memgraph Cypher-based AML Pattern Detection Functions
# ==================================================================
# Graceful degradation if Memgraph is not running: returns empty DF/dict + warning log.
# TRANSFER edge attributes: date, time_slot, fund_type, medium_type, amount,
#                           is_fraud, fraud_type
# Account node attributes: id, company_id
# ------------------------------------------------------------------


@st.cache_data(ttl=300, show_spinner=False)
def detect_ring_transactions(min_len: int = 3, max_len: int = 6, min_amount: int = 0, limit: int = 100) -> pd.DataFrame:
    """Detects circular fund transfer patterns (rings).

    Searches for A->B->C->...->A circular transaction patterns, a core money laundering pattern,
    using graph traversal. Only relations marked as fraud are explored.

    Parameters
    ----------
    min_len : int
        Minimum length of the circular path (default 3).
    max_len : int
        Maximum length of the circular path (default 6).
    min_amount : int
        Minimum total transaction amount filter within the ring (default 0).
    limit : int
        Maximum number of results to return (default 100).

    Returns
    -------
    pd.DataFrame
        Columns: ring_accounts, ring_size, total_amount, dates
        Returns empty DataFrame if Memgraph is not running.
    """
    empty = pd.DataFrame(columns=["ring_accounts", "ring_size", "total_amount", "dates"])

    if not graph_db.is_available():
        logger.warning("Unable to detect ring transactions as Memgraph is not running.")
        return empty

    min_len = int(min_len)
    max_len = int(max_len)
    min_amount = int(min_amount)
    limit = int(limit)

    cypher = f"""
        MATCH p=(a:Account)-[:TRANSFER*{min_len}..{max_len}]->(a)
        WHERE ALL(r IN relationships(p) WHERE r.is_fraud = 1)
        WITH [n IN nodes(p) | n.id] AS ring_accounts,
             [r IN relationships(p) | r.amount] AS amounts,
             [r IN relationships(p) | r.date] AS dates,
             size(relationships(p)) AS ring_size,
             reduce(s = 0, r IN relationships(p) | s + r.amount) AS total_amount
        WHERE total_amount >= {min_amount}
        RETURN ring_accounts, ring_size, total_amount, dates
        ORDER BY total_amount DESC
        LIMIT {limit}
    """

    records = graph_db.execute(cypher)
    if not records:
        return empty

    rows = []
    for rec in records:
        rows.append({
            "ring_accounts": rec.get("ring_accounts", []),
            "ring_size": rec.get("ring_size", 0),
            "total_amount": rec.get("total_amount", 0),
            "dates": rec.get("dates", []),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=300, show_spinner=False)
def detect_layering_patterns(min_layers: int = 3, limit: int = 100) -> pd.DataFrame:
    """Detects multi-stage layering patterns.

    Searches for multi-stage fund movement patterns from a source account through 
    intermediaries to a destination account (A->B->C->...->Z).
    Only relations marked as fraud are explored.

    Parameters
    ----------
    min_layers : int
        Minimum number of layers (intermediate steps) (default 3).
    limit : int
        Maximum number of results to return (default 100).

    Returns
    -------
    pd.DataFrame
        Columns: source_account, destination_account, path_accounts, layers, total_amount
        Returns empty DataFrame if Memgraph is not running.
    """
    empty = pd.DataFrame(columns=[
        "source_account", "destination_account", "path_accounts",
        "layers", "total_amount",
    ])

    if not graph_db.is_available():
        logger.warning("Unable to detect layering patterns as Memgraph is not running.")
        return empty

    min_layers = int(min_layers)
    limit = int(limit)

    cypher = f"""
        MATCH p=(src:Account)-[:TRANSFER*{min_layers}..]->(dst:Account)
        WHERE src <> dst
          AND ALL(r IN relationships(p) WHERE r.is_fraud = 1)
        WITH src, dst,
             [n IN nodes(p) | n.id] AS path_accounts,
             size(relationships(p)) AS layers,
             reduce(s = 0, r IN relationships(p) | s + r.amount) AS total_amount
        WHERE layers >= {min_layers}
        RETURN src.id AS source_account,
               dst.id AS destination_account,
               path_accounts,
               layers,
               total_amount
        ORDER BY layers DESC, total_amount DESC
        LIMIT {limit}
    """

    records = graph_db.execute(cypher)
    if not records:
        return empty

    rows = []
    for rec in records:
        rows.append({
            "source_account": rec.get("source_account"),
            "destination_account": rec.get("destination_account"),
            "path_accounts": rec.get("path_accounts", []),
            "layers": rec.get("layers", 0),
            "total_amount": rec.get("total_amount", 0),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=300, show_spinner=False)
def detect_funnel_accounts(min_inflow: int = 10, max_outflow: int = 3, limit: int = 100) -> pd.DataFrame:
    """Detects primary account (funnel) patterns.

    Searches for suspicious accounts that receive deposits from many accounts (inflow) 
    and withdraw to a few accounts (outflow). A higher funnel_ratio indicates higher suspicion.

    Parameters
    ----------
    min_inflow : int
        Minimum number of inflow accounts (default 10).
    max_outflow : int
        Maximum number of outflow accounts (default 3).
    limit : int
        Maximum number of results to return (default 100).

    Returns
    -------
    pd.DataFrame
        Columns: account_id, inflow_count, inflow_amount, outflow_count,
              outflow_amount, funnel_ratio
        Returns empty DataFrame if Memgraph is not running.
    """
    empty = pd.DataFrame(columns=[
        "account_id", "inflow_count", "inflow_amount",
        "outflow_count", "outflow_amount", "funnel_ratio",
    ])

    if not graph_db.is_available():
        logger.warning("Unable to detect funnel patterns as Memgraph is not running.")
        return empty

    min_inflow = int(min_inflow)
    max_outflow = int(max_outflow)
    limit = int(limit)

    cypher = f"""
        MATCH (s:Account)-[r1:TRANSFER]->(funnel:Account)
        WITH funnel,
             count(DISTINCT s) AS inflow_count,
             sum(r1.amount) AS inflow_amount
        WHERE inflow_count >= {min_inflow}
        OPTIONAL MATCH (funnel)-[r2:TRANSFER]->(d:Account)
        WITH funnel, inflow_count, inflow_amount,
             count(DISTINCT d) AS outflow_count,
             coalesce(sum(r2.amount), 0) AS outflow_amount
        WHERE outflow_count <= {max_outflow}
        RETURN funnel.id AS account_id,
               inflow_count,
               inflow_amount,
               outflow_count,
               outflow_amount,
               inflow_count * 1.0 / CASE WHEN outflow_count = 0
                   THEN 1 ELSE outflow_count END AS funnel_ratio
        ORDER BY funnel_ratio DESC
        LIMIT {limit}
    """

    records = graph_db.execute(cypher)
    if not records:
        return empty

    rows = []
    for rec in records:
        rows.append({
            "account_id": rec.get("account_id"),
            "inflow_count": rec.get("inflow_count", 0),
            "inflow_amount": rec.get("inflow_amount", 0),
            "outflow_count": rec.get("outflow_count", 0),
            "outflow_amount": rec.get("outflow_amount", 0),
            "funnel_ratio": round(float(rec.get("funnel_ratio", 0)), 2),
        })
    return pd.DataFrame(rows)


def get_account_ego_network_deep(account_id: int, hops: int = 3) -> pd.DataFrame:
    """Extracts a deep ego network from Memgraph.

    Extracts a subgraph consisting of neighbor accounts up to N hops centered on a 
    specified account, along with their transaction relationships. 
    Allows deeper exploration than get_account_ego_network (up to 5 hops).

    Falls back to get_account_ego_network (DuckDB-based, up to 2 hops) if Memgraph is not running.

    Parameters
    ----------
    account_id : int
        Center account ID.
    hops : int
        Exploration depth (default 3, max 5).

    Returns
    -------
    pd.DataFrame
        Columns: source, target, tx_count, total_amount, is_fraud
        Same schema as get_account_ego_network.
    """
    account_id = int(account_id)
    hops = min(int(hops), 5)

    if not graph_db.is_available():
        logger.warning(
            "Deep ego network exploration unavailable as Memgraph is not running (falling back to DuckDB, max 2 hops)."
        )
        fallback_hops = min(hops, 2)
        return get_account_ego_network(account_id, hops=fallback_hops)

    cypher = f"""
        MATCH p=(center:Account {{id: $account_id}})-[:TRANSFER*1..{hops}]-(neighbor)
        WITH collect(DISTINCT neighbor) + [center] AS all_nodes
        MATCH (center:Account {{id: $account_id}})
        WITH all_nodes, center
        UNWIND all_nodes AS n
        WITH collect(DISTINCT n) AS all_nodes
        UNWIND all_nodes AS n
        MATCH (n)-[r:TRANSFER]->(m)
        WHERE m IN all_nodes
        RETURN startNode(r).id AS source,
               endNode(r).id AS target,
               count(r) AS tx_count,
               sum(r.amount) AS total_amount,
               max(r.is_fraud) AS is_fraud
    """

    df = graph_db.execute_df(cypher, {"account_id": account_id})
    if df.empty:
        logger.info("Memgraph results empty, falling back to DuckDB.")
        fallback_hops = min(hops, 2)
        return get_account_ego_network(account_id, hops=fallback_hops)

    return df


def find_shortest_path(account_a: int, account_b: int) -> dict:
    """Finds the shortest transaction path between two accounts.

    Uses Memgraph's shortestPath algorithm to find the path with the minimum number of hops.

    Parameters
    ----------
    account_a : int
        Source account ID.
    account_b : int
        Destination account ID.

    Returns
    -------
    dict
        {"path": [AccountID, ...], "hops": int, "amounts": [...], "dates": [...]}
        If Memgraph is not running: {"error": "..."}
        If no path exists: {"path": [], "hops": 0, "amounts": [], "dates": []}
    """
    account_a = int(account_a)
    account_b = int(account_b)

    if not graph_db.is_available():
        logger.warning("Unable to find shortest path as Memgraph is not running.")
        return {"error": "Unable to find shortest path as Memgraph is not running."}

    cypher = """
        MATCH p=shortestPath(
            (a:Account {id: $account_a})-[:TRANSFER*]-(b:Account {id: $account_b})
        )
        RETURN [n IN nodes(p) | n.id] AS path,
               size(relationships(p)) AS hops,
               [r IN relationships(p) | r.amount] AS amounts,
               [r IN relationships(p) | r.date] AS dates
    """

    records = graph_db.execute(cypher, {
        "account_a": account_a,
        "account_b": account_b,
    })

    if not records:
        return {"path": [], "hops": 0, "amounts": [], "dates": []}

    rec = records[0]
    return {
        "path": rec.get("path", []),
        "hops": rec.get("hops", 0),
        "amounts": rec.get("amounts", []),
        "dates": rec.get("dates", []),
    }


def get_temporal_network(start_date: int, end_date: int, fraud_only: bool = True) -> pd.DataFrame:
    """Extracts the transaction network within a time window.

    Extracts a network composed only of transactions within a specified period from Memgraph.

    Parameters
    ----------
    start_date : int
        Start transaction date (e.g., 20210101).
    end_date : int
        End transaction date (e.g., 20241231).
    fraud_only : bool
        Whether to filter only fraud transactions (default True).

    Returns
    -------
    pd.DataFrame
        Columns: source, target, tx_count, total_amount, is_fraud
        Returns empty DataFrame if Memgraph is not running.
    """
    empty = pd.DataFrame(columns=["source", "target", "tx_count", "total_amount", "is_fraud"])

    if not graph_db.is_available():
        logger.warning("Unable to extract temporal network as Memgraph is not running.")
        return empty

    start_date = int(start_date)
    end_date = int(end_date)

    fraud_filter = "AND r.is_fraud = 1" if fraud_only else ""

    cypher = f"""
        MATCH (a:Account)-[r:TRANSFER]->(b:Account)
        WHERE r.date >= $start_date AND r.date <= $end_date
              {fraud_filter}
        RETURN a.id AS source, b.id AS target,
               count(r) AS tx_count,
               sum(r.amount) AS total_amount,
               max(r.is_fraud) AS is_fraud
        ORDER BY tx_count DESC
        LIMIT 1000
    """

    df = graph_db.execute_df(cypher, {
        "start_date": start_date,
        "end_date": end_date,
    })

    if df.empty:
        return empty

    return df


def compute_risk_score(account_id: int) -> dict:
    """Calculates a composite graph-based risk score.

    Computes an AML risk score (0.0 to 1.0) for a specific account by synthesizing 
    various graph metrics. Weight composition:
    - 0.4: Direct fraud ratio
    - 0.3: Neighbor fraud ratio
    - 0.2: Cycle participation score
    - 0.1: Inflow/outflow concentration

    Parameters
    ----------
    account_id : int
        Account ID to analyze.

    Returns
    -------
    dict
        {
            "account_id": int,
            "risk_score": float (0.0 to 1.0),
            "components": {
                "fraud_ratio": float,
                "neighbor_fraud_ratio": float,
                "cycle_score": float,
                "concentration_score": float,
            }
        }
        If Memgraph is not running: {"risk_score": 0.0, "error": "..."}
    """
    account_id = int(account_id)

    if not graph_db.is_available():
        logger.warning("Unable to calculate risk score as Memgraph is not running.")
        return {"account_id": account_id, "risk_score": 0.0, "error": "Memgraph not running"}

    # 1) Direct fraud ratio
    cypher_fraud = """
        MATCH (a:Account {id: $account_id})-[r:TRANSFER]-()
        WITH count(r) AS total_txn,
             sum(CASE WHEN r.is_fraud = 1 THEN 1 ELSE 0 END) AS fraud_txn
        RETURN total_txn, fraud_txn,
               CASE WHEN total_txn = 0 THEN 0.0
                    ELSE fraud_txn * 1.0 / total_txn END AS fraud_ratio
    """
    fraud_records = graph_db.execute(cypher_fraud, {"account_id": account_id})

    if not fraud_records:
        return {
            "account_id": account_id,
            "risk_score": 0.0,
            "components": {
                "fraud_ratio": 0.0,
                "neighbor_fraud_ratio": 0.0,
                "cycle_score": 0.0,
                "concentration_score": 0.0,
            },
        }

    fraud_ratio = float(fraud_records[0].get("fraud_ratio", 0.0))

    # 2) Neighbor fraud ratio
    cypher_neighbor = """
        MATCH (a:Account {id: $account_id})-[:TRANSFER]-(neighbor:Account)
        WITH collect(DISTINCT neighbor) AS neighbors
        UNWIND neighbors AS nb
        MATCH (nb)-[r:TRANSFER]-()
        WITH count(r) AS neighbor_total,
             sum(CASE WHEN r.is_fraud = 1 THEN 1 ELSE 0 END) AS neighbor_fraud
        RETURN CASE WHEN neighbor_total = 0 THEN 0.0
                    ELSE neighbor_fraud * 1.0 / neighbor_total END AS neighbor_fraud_ratio
    """
    neighbor_records = graph_db.execute(cypher_neighbor, {"account_id": account_id})
    neighbor_fraud_ratio = 0.0
    if neighbor_records:
        neighbor_fraud_ratio = float(
            neighbor_records[0].get("neighbor_fraud_ratio", 0.0)
        )

    # 3) Cycle participation score
    cypher_cycle = """
        MATCH p=(a:Account {id: $account_id})-[:TRANSFER*3..4]->(a)
        RETURN count(p) AS cycle_count
    """
    cycle_records = graph_db.execute(cypher_cycle, {"account_id": account_id})
    cycle_count = 0
    if cycle_records:
        cycle_count = int(cycle_records[0].get("cycle_count", 0))
    cycle_score = min(cycle_count / 5.0, 1.0) if cycle_count > 0 else 0.0

    # 4) Concentration score
    cypher_concentration = """
        MATCH (a:Account {id: $account_id})
        OPTIONAL MATCH (a)<-[r_in:TRANSFER]-()
        WITH a, count(r_in) AS in_count
        OPTIONAL MATCH (a)-[r_out:TRANSFER]->()
        WITH in_count, count(r_out) AS out_count
        RETURN in_count, out_count,
               CASE WHEN (in_count + out_count) = 0 THEN 0.0
                    ELSE abs(in_count - out_count) * 1.0 / (in_count + out_count)
               END AS concentration
    """
    conc_records = graph_db.execute(cypher_concentration, {"account_id": account_id})
    concentration_score = 0.0
    if conc_records:
        concentration_score = float(conc_records[0].get("concentration", 0.0))

    risk_score = (
        0.4 * fraud_ratio
        + 0.3 * neighbor_fraud_ratio
        + 0.2 * cycle_score
        + 0.1 * concentration_score
    )

    return {
        "account_id": account_id,
        "risk_score": round(risk_score, 4),
        "components": {
            "fraud_ratio": round(fraud_ratio, 4),
            "neighbor_fraud_ratio": round(neighbor_fraud_ratio, 4),
            "cycle_score": round(cycle_score, 4),
            "concentration_score": round(concentration_score, 4),
        },
    }
