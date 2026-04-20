"""Feature 5: CTR Monitoring (Currency Transaction Report) Module.

Inquiries on high-value transactions over 10 million KRW and detection of structuring transactions.
Basis: Act on Reporting and Use of Certain Financial Transaction Information — CTR obligations.
"""

import json
import math

import pandas as pd
import streamlit as st

from src.data.db import query

_CACHE_HASH_FUNCS = {
    dict: lambda d: json.dumps(d, sort_keys=True, default=str) if d else "none",
}


def _safe_int(val, default: int = 0) -> int:
    """NaN-safe int conversion."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return int(val)


# ------------------------------------------------------------------
# High-Value Transactions
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_ctr_candidates(date_from: int | None = None,
                       date_to: int | None = None,
                       limit: int = 100) -> pd.DataFrame:
    """Retrieves CTR-related transactions where amount >= 10,000,000 KRW."""
    limit = int(limit)
    conditions = ["amount >= 10000000"]
    if date_from is not None:
        conditions.append(f"date >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"date <= {int(date_to)}")
    where = "WHERE " + " AND ".join(conditions)
    return query(f"""
        SELECT date, time_slot, sender_bank, sender_acc,
               receiver_bank, receiver_acc, fund_type, media_type,
               amount, is_fraud, fraud_type
        FROM hofinet
        {where}
        ORDER BY amount DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# Structuring Detection
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_structuring(date_from: int | None = None,
                       date_to: int | None = None,
                       threshold: int = 10_000_000,
                       limit: int = 100) -> pd.DataFrame:
    """Detects suspected structuring: daily total >= threshold, single tx < threshold, count >= 2."""
    threshold = int(threshold)
    limit = int(limit)
    conditions = []
    if date_from is not None:
        conditions.append(f"date >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"date <= {int(date_to)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return query(f"""
        SELECT sender_acc, date,
               COUNT(*) AS tx_count,
               SUM(amount) AS total_amount,
               MAX(amount) AS max_single_amount,
               MIN(amount) AS min_single_amount
        FROM hofinet
        {where}
        GROUP BY sender_acc, date
        HAVING SUM(amount) >= {threshold}
           AND MAX(amount) < {threshold}
           AND COUNT(*) >= 2
        ORDER BY total_amount DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# Account Structuring Pattern Analysis
# ------------------------------------------------------------------

def assess_account_structuring(account_id: int,
                                threshold: int = 10_000_000) -> dict:
    """Analyzes structuring patterns for a specific account."""
    aid = int(account_id)
    threshold = int(threshold)

    # Query structuring suspect days
    df = query(f"""
        SELECT date, COUNT(*) AS tx_count,
               SUM(amount) AS total_amount,
               MAX(amount) AS max_single_amount
        FROM hofinet
        WHERE sender_acc = {aid}
        GROUP BY date
        HAVING SUM(amount) >= {threshold}
           AND MAX(amount) < {threshold}
           AND COUNT(*) >= 2
        ORDER BY date
    """)

    # Overall transaction stats
    total_df = query(f"""
        SELECT COUNT(*) AS total_count, SUM(amount) AS total_amount
        FROM hofinet
        WHERE sender_acc = {aid}
    """)

    total_row = total_df.iloc[0] if not total_df.empty else {}
    count_val = _safe_int(total_row.get("total_count", 0))
    amount_val = _safe_int(total_row.get("total_amount", 0))

    return {
        "account_id": aid,
        "total_tx_count": count_val,
        "total_amount": amount_val,
        "structuring_suspect_days": len(df),
        "structuring_details": df.to_dict(orient="records") if not df.empty else [],
    }


# ------------------------------------------------------------------
# CTR Summary Statistics
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_ctr_summary(filters=None) -> dict:
    """Returns overall CTR monitoring statistics."""
    conditions = []
    if filters:
        if filters.get("date_from"):
            conditions.append(f"date >= {int(filters['date_from'])}")
        if filters.get("date_to"):
            conditions.append(f"date <= {int(filters['date_to'])}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # High-value transaction stats
    high_conditions = ["amount >= 10000000"] + conditions
    high_where = "WHERE " + " AND ".join(high_conditions)
    high_df = query(f"""
        SELECT COUNT(*) AS high_value_count, SUM(amount) AS high_value_total
        FROM hofinet
        {high_where}
    """)

    # Structuring suspect stats
    if conditions:
        struct_where = "WHERE " + " AND ".join(conditions)
    else:
        struct_where = ""

    struct_df = query(f"""
        SELECT COUNT(*) AS suspect_count FROM (
            SELECT sender_acc, date
            FROM hofinet
            {struct_where}
            GROUP BY sender_acc, date
            HAVING SUM(amount) >= 10000000
               AND MAX(amount) < 10000000
               AND COUNT(*) >= 2
        ) sub
    """)

    high_row = high_df.iloc[0] if not high_df.empty else {}
    struct_row = struct_df.iloc[0] if not struct_df.empty else {}

    return {
        "high_value_count": _safe_int(high_row.get("high_value_count", 0)),
        "high_value_total": _safe_int(high_row.get("high_value_total", 0)),
        "structuring_suspect_count": _safe_int(struct_row.get("suspect_count", 0)),
    }
