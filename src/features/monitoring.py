"""Feature 7: Transaction Monitoring Rule Detection Module.

Execution of 5 defined rules and alert generation.
Basis: AML Practice Vol 5 — Rule-based Monitoring, Suspicious Transaction Indicators.
"""

import json
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from src.data.db import query

_CACHE_HASH_FUNCS = {
    dict: lambda d: json.dumps(d, sort_keys=True, default=str) if d else "none",
}


def _safe_int(val, default: int = 0) -> int:
    """NaN-safe int conversion."""
    import math
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return int(val)


def _parse_yyyymmdd(date_int: int) -> datetime:
    """Converts YYYYMMDD integer to datetime."""
    return datetime.strptime(str(int(date_int)), "%Y%m%d")


def _to_yyyymmdd(dt: datetime) -> int:
    """Converts datetime to YYYYMMDD integer."""
    return int(dt.strftime("%Y%m%d"))


def _calculate_previous_period(date_from: int, date_to: int) -> tuple[int, int]:
    """Returns the period of the same length immediately preceding the current one."""
    start_dt = _parse_yyyymmdd(date_from)
    end_dt = _parse_yyyymmdd(date_to)
    if start_dt > end_dt:
        raise ValueError("date_from must be <= date_to")

    span_days = (end_dt - start_dt).days
    prev_end = start_dt - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span_days)
    return _to_yyyymmdd(prev_start), _to_yyyymmdd(prev_end)


# ------------------------------------------------------------------
# R001: Late-night bulk transactions
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_nighttime_bulk(date_from: int | None = None,
                          date_to: int | None = None,
                          min_amount: int = 10_000_000,
                          limit: int = 100) -> pd.DataFrame:
    """R001: Detects bulk transactions during late-night hours (0, 3)."""
    min_amount = int(min_amount)
    limit = int(limit)
    conditions = ["time_slot IN (0, 3)", f"amount >= {min_amount}"]
    if date_from is not None:
        conditions.append(f"date >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"date <= {int(date_to)}")
    where = "WHERE " + " AND ".join(conditions)
    return query(f"""
        SELECT date, time_slot, sender_acc, receiver_acc,
               sender_bank, receiver_bank, amount,
               is_fraud, fraud_type
        FROM hofinet
        {where}
        ORDER BY amount DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R002: Multi-transaction on same day (Rapid-fire)
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_rapid_fire(date_from: int | None = None,
                      date_to: int | None = None,
                      min_count: int = 10,
                      limit: int = 100) -> pd.DataFrame:
    """R002: Detects accounts with min_count+ transactions on the same day."""
    min_count = int(min_count)
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
               SUM(is_fraud) AS fraud_count
        FROM hofinet
        {where}
        GROUP BY sender_acc, date
        HAVING COUNT(*) >= {min_count}
        ORDER BY tx_count DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R003: Round amount patterns
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_round_amounts(date_from: int | None = None,
                         date_to: int | None = None,
                         round_unit: int = 1_000_000,
                         min_count: int = 3,
                         limit: int = 100) -> pd.DataFrame:
    """R003: Detects accounts with min_count+ round-unit transactions."""
    round_unit = int(round_unit)
    min_count = int(min_count)
    limit = int(limit)
    conditions = [f"amount % {round_unit} = 0", f"amount >= {round_unit}"]
    if date_from is not None:
        conditions.append(f"date >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"date <= {int(date_to)}")
    where = "WHERE " + " AND ".join(conditions)
    return query(f"""
        SELECT sender_acc, COUNT(*) AS round_tx_count,
               SUM(amount) AS total_amount,
               COUNT(DISTINCT amount) AS distinct_amount_count
        FROM hofinet
        {where}
        GROUP BY sender_acc
        HAVING COUNT(*) >= {min_count}
        ORDER BY round_tx_count DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R004: Institutional concentration
# ------------------------------------------------------------------

def detect_institution_concentration(min_ratio: float = 0.8,
                                     min_transactions: int = 10,
                                     limit: int = 100) -> pd.DataFrame:
    """R004: Detects accounts concentrated in transactions with a specific receiver institution."""
    min_transactions = int(min_transactions)
    limit = int(limit)
    return query(f"""
        WITH account_bank AS (
            SELECT sender_acc,
                   receiver_bank,
                   COUNT(*) AS bank_tx_count
            FROM hofinet
            GROUP BY sender_acc, receiver_bank
        ),
        account_total AS (
            SELECT sender_acc,
                   SUM(bank_tx_count) AS total_tx_count,
                   MAX(bank_tx_count) AS max_bank_tx_count
            FROM account_bank
            GROUP BY sender_acc
            HAVING SUM(bank_tx_count) >= {min_transactions}
        )
        SELECT
            t.sender_acc,
            t.total_tx_count,
            t.max_bank_tx_count,
            ROUND(t.max_bank_tx_count * 1.0 / t.total_tx_count, 4) AS concentration_ratio,
            b.receiver_bank AS concentration_bank
        FROM account_total t
        JOIN account_bank b
          ON t.sender_acc = b.sender_acc
         AND t.max_bank_tx_count = b.bank_tx_count
        WHERE t.max_bank_tx_count * 1.0 / t.total_tx_count >= {float(min_ratio)}
        ORDER BY concentration_ratio DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R005: Sudden pattern change
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_pattern_change(base_start: int, base_end: int,
                          compare_start: int, compare_end: int,
                          change_threshold: float = 3.0,
                          limit: int = 100) -> pd.DataFrame:
    """R005: Detects accounts with a sudden surge in transaction volume compared to a base period."""
    base_start = int(base_start)
    base_end = int(base_end)
    compare_start = int(compare_start)
    compare_end = int(compare_end)
    limit = int(limit)
    return query(f"""
        WITH base AS (
            SELECT sender_acc, COUNT(*) AS base_count, SUM(amount) AS base_amount
            FROM hofinet
            WHERE date BETWEEN {base_start} AND {base_end}
            GROUP BY sender_acc
            HAVING COUNT(*) >= 5
        ),
        compare AS (
            SELECT sender_acc, COUNT(*) AS comp_count, SUM(amount) AS comp_amount
            FROM hofinet
            WHERE date BETWEEN {compare_start} AND {compare_end}
            GROUP BY sender_acc
        )
        SELECT
            b.sender_acc,
            b.base_count AS base_period_count,
            c.comp_count AS comp_period_count,
            ROUND(c.comp_count * 1.0 / b.base_count, 2) AS count_change_ratio,
            b.base_amount AS base_period_amount,
            c.comp_amount AS comp_period_amount,
            ROUND(c.comp_amount * 1.0 / b.base_amount, 2) AS amount_change_ratio
        FROM base b
        JOIN compare c ON b.sender_acc = c.sender_acc
        WHERE c.comp_count * 1.0 / b.base_count >= {float(change_threshold)}
           OR c.comp_amount * 1.0 / NULLIF(b.base_amount, 0) >= {float(change_threshold)}
        ORDER BY count_change_ratio DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# Full rule execution
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def run_all_rules(date_from: int | None = None,
                  date_to: int | None = None) -> dict:
    """Runs all rules and returns results summary."""
    r001 = detect_nighttime_bulk(date_from, date_to, limit=50)
    r002 = detect_rapid_fire(date_from, date_to, limit=50)
    r003 = detect_round_amounts(date_from, date_to, limit=50)
    r004 = detect_institution_concentration(limit=50)
    r005_result = pd.DataFrame()
    if date_from and date_to:
        try:
            base_start, base_end = _calculate_previous_period(int(date_from), int(date_to))
            r005_result = detect_pattern_change(
                base_start, base_end, int(date_from), int(date_to), limit=50
            )
        except ValueError:
            # For invalid date inputs, R005 returns an empty DF while others continue.
            r005_result = pd.DataFrame()

    return {
        "R001_Nighttime_Bulk": {"count": len(r001), "top": r001.head(10).to_dict(orient="records")},
        "R002_Rapid_Fire": {"count": len(r002), "top": r002.head(10).to_dict(orient="records")},
        "R003_Round_Amount": {"count": len(r003), "top": r003.head(10).to_dict(orient="records")},
        "R004_Concentrated_Bank": {"count": len(r004), "top": r004.head(10).to_dict(orient="records")},
        "R005_Pattern_Change": {"count": len(r005_result), "top": r005_result.head(10).to_dict(orient="records")},
    }


# ------------------------------------------------------------------
# R006: Long-term dormant account reactivation
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_dormant_reactivation(dormant_days: int = 180,
                                 min_reactivation_amount: int = 5_000_000,
                                 limit: int = 100) -> pd.DataFrame:
    """R006: Detects accounts reactivated after a long dormant period."""
    dormant_days = int(dormant_days)
    min_reactivation_amount = int(min_reactivation_amount)
    limit = int(limit)
    return query(f"""
        WITH account_dates AS (
            SELECT sender_acc,
                   date,
                   amount,
                   LAG(date) OVER (
                       PARTITION BY sender_acc
                       ORDER BY date
                   ) AS prev_date
            FROM hofinet
        ),
        gaps AS (
            SELECT sender_acc,
                   prev_date AS last_activity_date,
                   date AS reactivation_date,
                   amount AS reactivation_amount,
                   date_diff(
                       'day',
                       strptime(CAST(prev_date AS VARCHAR), '%Y%m%d'),
                       strptime(CAST(date AS VARCHAR), '%Y%m%d')
                   ) AS dormant_days
            FROM account_dates
            WHERE prev_date IS NOT NULL
        )
        SELECT sender_acc, last_activity_date, reactivation_date,
               dormant_days, reactivation_amount
        FROM gaps
        WHERE dormant_days >= {dormant_days}
          AND reactivation_amount >= {min_reactivation_amount}
        ORDER BY dormant_days DESC, reactivation_amount DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# Monitoring stats
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_monitoring_summary(filters=None) -> dict:
    """Returns monitoring summary statistics."""
    conditions = []
    if filters:
        if filters.get("date_from"):
            conditions.append(f"date >= {int(filters['date_from'])}")
        if filters.get("date_to"):
            conditions.append(f"date <= {int(filters['date_to'])}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Late-night ratio
    night_df = query(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN time_slot IN (0, 3) THEN 1 ELSE 0 END) AS night_cnt
        FROM hofinet
        {where}
    """)

    # High-frequency count
    rapid_df = query(f"""
        SELECT COUNT(*) AS cnt FROM (
            SELECT sender_acc, date
            FROM hofinet
            {where}
            GROUP BY sender_acc, date
            HAVING COUNT(*) >= 10
        ) sub
    """)

    night_row = night_df.iloc[0] if not night_df.empty else {}
    rapid_row = rapid_df.iloc[0] if not rapid_df.empty else {}

    total = _safe_int(night_row.get("total", 0))
    night = _safe_int(night_row.get("night_cnt", 0))

    return {
        "total_tx_count": total,
        "night_tx_count": night,
        "night_tx_ratio": round(night / total * 100, 2) if total > 0 else 0.0,
        "high_freq_tx_count": _safe_int(rapid_row.get("cnt", 0)),
    }
