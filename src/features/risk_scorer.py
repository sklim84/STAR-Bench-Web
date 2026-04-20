"""Feature 6: Account Risk Evaluation (Risk Scoring) Module.

Calculates 0-100 risk score based on 5 behavioral indicators.
Basis: AML Practice Vol 2 — Risk Assessment Framework (Inherent Risk - Internal Controls = Residual Risk).
"""

import math

import pandas as pd
import streamlit as st

from src.data.db import query


def _safe_int(val, default: int = 0) -> int:
    """NaN-safe int conversion."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return int(val)


# ------------------------------------------------------------------
# Weight Settings
# ------------------------------------------------------------------

_WEIGHTS = {
    "nighttime_ratio": 0.15,
    "amount_anomaly": 0.25,
    "counterparty_diversity": 0.15,
    "velocity_change": 0.25,
    "fraud_history": 0.20,
}


# ------------------------------------------------------------------
# Component Calculations
# ------------------------------------------------------------------

def _calc_nighttime_ratio(account_id: int) -> float:
    """Returns the ratio of nighttime transactions (time_slot 0, 3) between 0 and 1."""
    aid = int(account_id)
    df = query(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN time_slot IN (0, 3) THEN 1 ELSE 0 END) AS night
        FROM hofinet
        WHERE sender_acc = {aid}
    """)
    if df.empty:
        return 0.0
    row = df.iloc[0]
    total = _safe_int(row["total"])
    night = _safe_int(row["night"])
    return night / total if total > 0 else 0.0


def _calc_amount_anomaly(account_id: int) -> float:
    """Returns the amount anomaly based on z-score between 0 and 1."""
    aid = int(account_id)
    df = query(f"""
        SELECT AVG(amount) AS avg_amt, STDDEV_POP(amount) AS std_amt
        FROM hofinet
        WHERE sender_acc = {aid}
    """)
    if df.empty:
        return 0.0
    row = df.iloc[0]
    avg_amt = float(row["avg_amt"] or 0)
    std_amt = float(row["std_amt"] or 0)

    if std_amt == 0 or avg_amt == 0:
        return 0.0

    global_df = query("SELECT AVG(amount) AS g_avg FROM hofinet")
    g_avg = float(global_df.iloc[0]["g_avg"] or 0) if not global_df.empty else 0

    z = abs(avg_amt - g_avg) / std_amt
    # Sigmoid-like normalization to 0~1
    return min(1.0, z / 5.0)


def _calc_counterparty_diversity(account_id: int) -> float:
    """Returns counterparty diversity score between 0 and 1."""
    aid = int(account_id)
    df = query(f"""
        SELECT
            COUNT(DISTINCT receiver_acc) AS unique_accounts,
            COUNT(DISTINCT receiver_bank) AS unique_banks,
            COUNT(*) AS total
        FROM hofinet
        WHERE sender_acc = {aid}
    """)
    if df.empty:
        return 0.0
    row = df.iloc[0]
    total = _safe_int(row["total"])
    unique_accounts = _safe_int(row["unique_accounts"])
    if total == 0:
        return 0.0
    # High ratio of unique counterparties is a risk signal
    ratio = unique_accounts / total
    return min(1.0, ratio)


def _calc_velocity_change(account_id: int) -> float:
    """Returns the rate of change in transaction volume between 0 and 1."""
    aid = int(account_id)
    df = query(f"""
        SELECT
            CAST(date / 10000 AS INT) AS year,
            CASE
                WHEN (date / 100 % 100) <= 3 THEN 1
                WHEN (date / 100 % 100) <= 6 THEN 2
                WHEN (date / 100 % 100) <= 9 THEN 3
                ELSE 4
            END AS quarter,
            COUNT(*) AS count
        FROM hofinet
        WHERE sender_acc = {aid}
        GROUP BY year, quarter
        ORDER BY year DESC, quarter DESC
        LIMIT 2
    """)
    if df.empty or len(df) < 2:
        return 0.0
    recent = _safe_int(df.iloc[0]["count"])
    previous = _safe_int(df.iloc[1]["count"])
    if previous == 0:
        return 1.0 if recent > 0 else 0.0
    change_rate = abs(recent - previous) / previous
    return min(1.0, change_rate)


def _calc_fraud_history(account_id: int) -> float:
    """Returns the fraud transaction history ratio between 0 and 1."""
    aid = int(account_id)
    df = query(f"""
        SELECT COUNT(*) AS total,
               SUM(is_fraud) AS fraud
        FROM hofinet
        WHERE sender_acc = {aid}
    """)
    if df.empty:
        return 0.0
    row = df.iloc[0]
    total = _safe_int(row["total"])
    fraud = _safe_int(row["fraud"])
    return fraud / total if total > 0 else 0.0


# ------------------------------------------------------------------
# Composite Risk Scoring
# ------------------------------------------------------------------

def score_account(account_id: int) -> dict:
    """Returns 5 component risk scores + composite 0-100 score for an account."""
    aid = int(account_id)

    # Check existence
    check = query("SELECT COUNT(*) AS cnt FROM hofinet WHERE sender_acc = ?", [aid])
    if check.empty or _safe_int(check.iloc[0]["cnt"]) == 0:
        return {"account_id": aid, "error": "No transaction history for this account."}

    components = {
        "nighttime_ratio": _calc_nighttime_ratio(aid),
        "amount_anomaly": _calc_amount_anomaly(aid),
        "counterparty_diversity": _calc_counterparty_diversity(aid),
        "velocity_change": _calc_velocity_change(aid),
        "fraud_history": _calc_fraud_history(aid),
    }

    weighted_sum = (
        components["nighttime_ratio"] * _WEIGHTS["nighttime_ratio"]
        + components["amount_anomaly"] * _WEIGHTS["amount_anomaly"]
        + components["counterparty_diversity"] * _WEIGHTS["counterparty_diversity"]
        + components["velocity_change"] * _WEIGHTS["velocity_change"]
        + components["fraud_history"] * _WEIGHTS["fraud_history"]
    )
    total_score = round(weighted_sum * 100, 1)
    risk_level = (
        "High" if total_score >= 70 else
        "Medium" if total_score >= 40 else
        "Low"
    )

    return {
        "account_id": aid,
        "total_score": total_score,
        "risk_level": risk_level,
        "components": {k: round(v, 4) for k, v in components.items()},
        "weights": {
            "nighttime_ratio": _WEIGHTS["nighttime_ratio"],
            "amount_anomaly": _WEIGHTS["amount_anomaly"],
            "counterparty_diversity": _WEIGHTS["counterparty_diversity"],
            "velocity_change": _WEIGHTS["velocity_change"],
            "fraud_history": _WEIGHTS["fraud_history"],
        },
    }


# ------------------------------------------------------------------
# High-risk Account Ranking
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def rank_risky_accounts(top_k: int = 20,
                        min_transactions: int = 10) -> pd.DataFrame:
    """Returns TOP-K high-risk accounts via bulk SQL."""
    top_k = int(top_k)
    min_transactions = int(min_transactions)
    return query(f"""
        SELECT
            sender_acc AS account_id,
            COUNT(*) AS total_tx_count,
            SUM(amount) AS total_amount,
            SUM(is_fraud) AS fraud_count,
            ROUND(SUM(is_fraud) * 100.0 / COUNT(*), 2) AS fraud_ratio,
            ROUND(SUM(CASE WHEN time_slot IN (0, 3) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS nighttime_ratio,
            COUNT(DISTINCT receiver_acc) AS counterparty_count,
            ROUND(
                (SUM(CASE WHEN time_slot IN (0, 3) THEN 1 ELSE 0 END) * 1.0 / COUNT(*)) * 15 +
                (SUM(is_fraud) * 1.0 / COUNT(*)) * 20 +
                (COUNT(DISTINCT receiver_acc) * 1.0 / COUNT(*)) * 15,
                2
            ) AS risk_score_simple
        FROM hofinet
        GROUP BY sender_acc
        HAVING COUNT(*) >= {min_transactions}
        ORDER BY risk_score_simple DESC
        LIMIT {top_k}
    """)
