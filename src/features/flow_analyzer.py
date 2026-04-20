"""Fund Flow Analysis Module.

Detects fund collection/distribution patterns (Smurfing Network) and
analyzes fund flow between financial institutions (Cross-Institution Flow).
"""

import pandas as pd
import streamlit as st

from src.data.db import query


# ------------------------------------------------------------------
# Smurfing Network Detection
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_smurfing_network(account_id: int | None = None,
                            direction: str = "inbound",
                            min_counterparts: int = 5,
                            date_from: int | None = None,
                            date_to: int | None = None,
                            limit: int = 50) -> pd.DataFrame:
    """Detects fund collection (inbound) or distribution (outbound) patterns.

    Args:
        account_id: Limit to a specific account (None for all scan)
        direction: 'inbound' (many→1 collection) or 'outbound' (1→many dispersion)
        min_counterparts: Minimum number of counterparty accounts
        date_from: Start date (YYYYMMDD)
        date_to: End date (YYYYMMDD)
        limit: Max results

    Returns:
        DataFrame with account, counterparty_count, total_tx_count, total_amount, fraud_count
    """
    min_counterparts = int(min_counterparts)
    limit = int(limit)
    conditions = []
    if date_from is not None:
        conditions.append(f"date >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"date <= {int(date_to)}")

    if direction == "inbound":
        # Many sender_acc → 1 receiver_acc (Fund collection / funnel)
        target_col = "receiver_acc"
        counter_col = "sender_acc"
        label = "target_account"
    else:
        # 1 sender_acc → many receiver_acc (Fund distribution / dispersion)
        target_col = "sender_acc"
        counter_col = "receiver_acc"
        label = "source_account"

    if account_id is not None:
        conditions.append(f"{target_col} = {int(account_id)}")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    return query(f"""
        SELECT
            {target_col} AS {label},
            COUNT(DISTINCT {counter_col}) AS counterparty_count,
            COUNT(*) AS total_tx_count,
            SUM(amount) AS total_amount,
            SUM(is_fraud) AS fraud_count,
            ROUND(AVG(amount), 0) AS avg_amount
        FROM hofinet
        {where}
        GROUP BY {target_col}
        HAVING COUNT(DISTINCT {counter_col}) >= {min_counterparts}
        ORDER BY counterparty_count DESC, total_amount DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# Cross-Institution Flow Analysis
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def analyze_cross_institution_flow(date_from: int | None = None,
                                   date_to: int | None = None,
                                   min_transactions: int = 10,
                                   limit: int = 50) -> pd.DataFrame:
    """Analyzes fund flow between institution pairs (sender_bank → receiver_bank).

    Args:
        date_from: Start date (YYYYMMDD)
        date_to: End date (YYYYMMDD)
        min_transactions: Minimum transaction count
        limit: Max results

    Returns:
        DataFrame with tx_count, fraud_count, fraud_ratio, total_amount by institution pair
    """
    min_transactions = int(min_transactions)
    limit = int(limit)
    conditions = []
    if date_from is not None:
        conditions.append(f"date >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"date <= {int(date_to)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    return query(f"""
        SELECT
            sender_bank AS sender_institution,
            receiver_bank AS receiver_institution,
            COUNT(*) AS tx_count,
            SUM(is_fraud) AS fraud_count,
            ROUND(SUM(is_fraud) * 100.0 / COUNT(*), 4) AS fraud_ratio,
            SUM(amount) AS total_amount,
            ROUND(AVG(amount), 0) AS avg_amount,
            COUNT(DISTINCT sender_acc) AS sender_count,
            COUNT(DISTINCT receiver_acc) AS receiver_count
        FROM hofinet
        {where}
        GROUP BY sender_bank, receiver_bank
        HAVING COUNT(*) >= {min_transactions}
        ORDER BY fraud_ratio DESC, tx_count DESC
        LIMIT {limit}
    """)
