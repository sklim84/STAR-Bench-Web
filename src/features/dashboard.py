"""Feature 1: Basic Analysis Dashboard Query Module."""

import json

import pandas as pd
import streamlit as st

from src.data.db import query
from src.features.aml_reference import (
    FRAUD_TYPE_MAP, MEDIA_TYPE_MAP, FUND_TYPE_MAP,
    translate_fraud_type, translate_media_type, translate_fund_type
)

# For st.cache_data: dict is unhashable, so convert to JSON string
_CACHE_HASH_FUNCS = {
    dict: lambda d: json.dumps(d, sort_keys=True, default=str) if d else "none",
}


# ------------------------------------------------------------------
# Global Filter Helpers
# ------------------------------------------------------------------

def _build_filter_conditions(filters: dict | None) -> str:
    """Converts filter dictionary to SQL condition string (w/o WHERE)."""
    if not filters:
        return ""
    clauses = []
    if filters.get("date_from"):
        clauses.append(f"date >= {int(filters['date_from'])}")
    if filters.get("date_to"):
        clauses.append(f"date <= {int(filters['date_to'])}")
    if filters.get("banks"):
        bank_ids = ",".join(str(int(b)) for b in filters["banks"])
        clauses.append(f"sender_bank IN ({bank_ids})")
    if filters.get("fraud_types"):
        type_ids = ",".join(str(int(t)) for t in filters["fraud_types"])
        clauses.append(f"fraud_type IN ({type_ids})")
    return " AND ".join(clauses)


def _apply_filters(base_where: str, filters: dict | None) -> str:
    """Combines existing WHERE clause with filter conditions.

    Args:
        base_where: Existing WHERE clause (e.g., "WHERE is_fraud = 1" or "")
        filters: Filter dictionary

    Returns:
        Combined WHERE clause string
    """
    extra = _build_filter_conditions(filters)
    if base_where and extra:
        return f"{base_where} AND {extra}"
    elif base_where:
        return base_where
    elif extra:
        return f"WHERE {extra}"
    return ""


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_summary(filters: dict | None = None) -> pd.DataFrame:
    """Returns overall summary metrics."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            round(sum(is_fraud) * 100.0 / count(*), 4) as fraud_ratio,
            count(DISTINCT sender_acc) as sender_accounts,
            count(DISTINCT receiver_acc) as receiver_accounts,
            count(DISTINCT sender_bank) as sender_banks,
            count(DISTINCT receiver_bank) as receiver_banks,
            sum(amount) as total_amount
        FROM hofinet
        {where}
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_quarterly_trend(filters: dict | None = None) -> pd.DataFrame:
    """Returns quarterly transaction count and fraud trend."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            CAST(date / 10000 AS INT) as year,
            CASE
                WHEN (date / 100 % 100) <= 3 THEN 1
                WHEN (date / 100 % 100) <= 6 THEN 2
                WHEN (date / 100 % 100) <= 9 THEN 3
                ELSE 4
            END as quarter,
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            round(sum(is_fraud) * 100.0 / count(*), 4) as fraud_ratio
        FROM hofinet
        {where}
        GROUP BY year, quarter
        ORDER BY year, quarter
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_hourly_distribution(filters: dict | None = None) -> pd.DataFrame:
    """Returns hourly transaction distribution."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            time_slot as hour_range,
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            round(sum(is_fraud) * 100.0 / count(*), 4) as fraud_ratio
        FROM hofinet
        {where}
        GROUP BY hour_range
        ORDER BY hour_range
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_amount_distribution(filters: dict | None = None) -> pd.DataFrame:
    """Returns transaction distribution by amount range."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            CASE
                WHEN amount <= 10000 THEN 'Under 10K'
                WHEN amount <= 100000 THEN '10K-100K'
                WHEN amount <= 1000000 THEN '100K-1M'
                WHEN amount <= 10000000 THEN '1M-10M'
                WHEN amount <= 100000000 THEN '10M-100M'
                ELSE 'Over 100M'
            END as amount_range,
            CASE
                WHEN amount <= 10000 THEN 1
                WHEN amount <= 100000 THEN 2
                WHEN amount <= 1000000 THEN 3
                WHEN amount <= 10000000 THEN 4
                WHEN amount <= 100000000 THEN 5
                ELSE 6
            END as sort_order,
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            round(sum(is_fraud) * 100.0 / count(*), 4) as fraud_ratio
        FROM hofinet
        {where}
        GROUP BY amount_range, sort_order
        ORDER BY sort_order
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fraud_type_distribution(filters: dict | None = None) -> pd.DataFrame:
    """Returns distribution by fraud type."""
    where = _apply_filters("WHERE is_fraud = 1", filters)
    df = query(f"""
        SELECT
            fraud_type,
            count(*) as count
        FROM hofinet
        {where}
        GROUP BY fraud_type
        ORDER BY fraud_type
    """)
    if not df.empty:
        df["fraud_desc"] = df["fraud_type"].map(FRAUD_TYPE_MAP).fillna("Other")
    return df


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_monthly_trend(filters: dict | None = None) -> pd.DataFrame:
    """Returns monthly transaction count and fraud trend."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            CAST(date / 100 AS INT) as year_month,
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            round(sum(is_fraud) * 100.0 / count(*), 4) as fraud_ratio
        FROM hofinet
        {where}
        GROUP BY year_month
        ORDER BY year_month
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_medium_distribution(filters: dict | None = None) -> pd.DataFrame:
    """Returns transaction distribution by medium/channel."""
    where = _apply_filters("", filters)
    df = query(f"""
        SELECT
            media_type as channel_code,
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            round(sum(is_fraud) * 100.0 / count(*), 4) as fraud_ratio
        FROM hofinet
        {where}
        GROUP BY channel_code
        ORDER BY channel_code
    """)
    if not df.empty:
        df["channel"] = df["channel_code"].map(MEDIA_TYPE_MAP).fillna("Other")
    return df


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_top_banks(filters: dict | None = None) -> pd.DataFrame:
    """Returns top financial institutions by fraud count."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            sender_bank as bank_id,
            'Sender' as type,
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            round(sum(is_fraud) * 100.0 / count(*), 4) as fraud_ratio
        FROM hofinet
        {where}
        GROUP BY sender_bank
        HAVING sum(is_fraud) > 0
        UNION ALL
        SELECT
            receiver_bank as bank_id,
            'Receiver' as type,
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            round(sum(is_fraud) * 100.0 / count(*), 4) as fraud_ratio
        FROM hofinet
        {where}
        GROUP BY receiver_bank
        HAVING sum(is_fraud) > 0
        ORDER BY fraud_txns DESC
    """)


# ------------------------------------------------------------------
# Analysis by Fund Type
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fund_type_distribution(filters: dict | None = None) -> pd.DataFrame:
    """Returns transaction distribution by fund type."""
    where = _apply_filters("", filters)
    df = query(f"""
        SELECT
            fund_type as fund_type_code,
            count(*) as total_txns,
            sum(is_fraud) as fraud_txns,
            round(sum(is_fraud) * 100.0 / count(*), 4) as fraud_ratio,
            sum(amount) as total_amount
        FROM hofinet
        {where}
        GROUP BY fund_type_code
        ORDER BY fund_type_code
    """)
    if not df.empty:
        df["fund_type"] = df["fund_type_code"].map(FUND_TYPE_MAP).fillna("Other")
    return df


# ------------------------------------------------------------------
# Fraud Amount Analysis
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fraud_amount_summary(filters: dict | None = None) -> pd.DataFrame:
    """Returns amount statistics by fraud status."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            is_fraud,
            count(*) as count,
            sum(amount) as total_amount,
            round(avg(amount), 0) as avg_amount,
            median(amount) as median_amount,
            min(amount) as min_amount,
            max(amount) as max_amount
        FROM hofinet
        {where}
        GROUP BY is_fraud
        ORDER BY is_fraud
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fraud_amount_by_type(filters: dict | None = None) -> pd.DataFrame:
    """Returns volume statistics by fraud type."""
    where = _apply_filters("WHERE is_fraud = 1", filters)
    df = query(f"""
        SELECT
            fraud_type,
            count(*) as count,
            sum(amount) as total_amount,
            round(avg(amount), 0) as avg_amount,
            median(amount) as median_amount
        FROM hofinet
        {where}
        GROUP BY fraud_type
        ORDER BY total_amount DESC
    """)
    if not df.empty:
        df["fraud_desc"] = df["fraud_type"].map(FRAUD_TYPE_MAP).fillna("Other")
    return df


# ------------------------------------------------------------------
# Hourly x Fraud Type Cross Analysis Heatmap
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_hourly_fraud_type_heatmap(filters: dict | None = None) -> pd.DataFrame:
    """Returns count by fraud type and hour (for heatmap)."""
    where = _apply_filters("WHERE is_fraud = 1", filters)
    return query(f"""
        SELECT
            time_slot as hour_range,
            fraud_type,
            count(*) as count
        FROM hofinet
        {where}
        GROUP BY hour_range, fraud_type
        ORDER BY hour_range, fraud_type
    """)


# ------------------------------------------------------------------
# Monthly Trend by Fraud Type
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fraud_type_monthly_trend(filters: dict | None = None) -> pd.DataFrame:
    """Returns monthly count trend by fraud type."""
    where = _apply_filters("WHERE is_fraud = 1", filters)
    df = query(f"""
        SELECT
            CAST(date / 100 AS INT) as year_month,
            fraud_type,
            count(*) as count
        FROM hofinet
        {where}
        GROUP BY year_month, fraud_type
        ORDER BY year_month, fraud_type
    """)
    if not df.empty:
        df["fraud_desc"] = df["fraud_type"].map(FRAUD_TYPE_MAP).fillna("Other")
    return df


# ------------------------------------------------------------------
# Filter UI Support Queries
# ------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_bank_options() -> list:
    """Returns list of sender bank codes for filter UI."""
    try:
        result = query(
            "SELECT DISTINCT sender_bank as bank_id FROM hofinet ORDER BY bank_id"
        )
        return result["bank_id"].tolist()
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def get_fraud_type_options() -> pd.DataFrame:
    """Returns list of fraud type codes and descriptions for filter UI."""
    try:
        df = query("""
            SELECT DISTINCT fraud_type
            FROM hofinet WHERE is_fraud = 1
            ORDER BY fraud_type
        """)
        if not df.empty:
            df["fraud_desc"] = df["fraud_type"].map(FRAUD_TYPE_MAP).fillna("Other")
        return df
    except Exception:
        return pd.DataFrame(columns=["fraud_type", "fraud_desc"])


# ------------------------------------------------------------------
# Agent Tools: Time-series Trend Analysis
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_trend_analysis(unit: str = "monthly",
                       metric: str = "transactions",
                       date_from: int | None = None,
                       date_to: int | None = None) -> pd.DataFrame:
    """Returns time-series trend analysis."""
    conditions = []
    if date_from is not None:
        conditions.append(f"date >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"date <= {int(date_to)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    if unit == "quarterly":
        period_expr = (
            "CAST(date / 10000 AS INT) * 10 + "
            "CASE WHEN (date / 100 % 100) <= 3 THEN 1 "
            "WHEN (date / 100 % 100) <= 6 THEN 2 "
            "WHEN (date / 100 % 100) <= 9 THEN 3 "
            "ELSE 4 END"
        )
    else:
        period_expr = "CAST(date / 100 AS INT)"

    return query(f"""
        SELECT
            {period_expr} AS period,
            COUNT(*) AS transactions,
            SUM(is_fraud) AS fraud_count,
            ROUND(SUM(is_fraud) * 100.0 / COUNT(*), 4) AS fraud_rate,
            SUM(amount) AS total_amount,
            ROUND(AVG(amount), 0) AS avg_amount
        FROM hofinet
        {where}
        GROUP BY period
        ORDER BY period
    """)


# ------------------------------------------------------------------
# Agent Tools: Risk Analysis by Channel
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def analyze_channel_risk(date_from: int | None = None,
                          date_to: int | None = None) -> dict:
    """Returns risk analysis by channel (medium_type)."""
    conditions = []
    if date_from is not None:
        conditions.append(f"date >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"date <= {int(date_to)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    channel_df = query(f"""
        SELECT
            media_type as channel_code,
            COUNT(*) AS total_txns,
            SUM(is_fraud) AS fraud_count,
            ROUND(SUM(is_fraud) * 100.0 / COUNT(*), 4) AS fraud_rate,
            SUM(amount) AS total_amount,
            ROUND(AVG(amount), 0) AS avg_amount
        FROM hofinet
        {where}
        GROUP BY channel_code
        ORDER BY fraud_rate DESC
    """)
    if not channel_df.empty:
        channel_df["channel"] = channel_df["channel_code"].map(MEDIA_TYPE_MAP).fillna("Other")

    # Channel x Hour Cross analysis
    cross_df = query(f"""
        SELECT
            media_type as channel_code, time_slot as hour_range,
            COUNT(*) AS transactions,
            SUM(is_fraud) AS fraud_count,
            ROUND(SUM(is_fraud) * 100.0 / COUNT(*), 4) AS fraud_rate
        FROM hofinet
        {where}
        GROUP BY channel_code, hour_range
        ORDER BY channel_code, hour_range
    """)
    if not cross_df.empty:
        cross_df["channel"] = cross_df["channel_code"].map(MEDIA_TYPE_MAP).fillna("Other")

    channel_stats = channel_df.to_dict(orient="records") if not channel_df.empty else []
    cross_stats = cross_df.to_dict(orient="records") if not cross_df.empty else []

    return {
        "channel_stats": channel_stats,
        "channel_time_cross": cross_stats,
    }


# ------------------------------------------------------------------
# Agent Tools: Receiving Account Profiling
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_receiving_account_profile(account_id: int) -> dict:
    """Profiles account from the perspective of fund receiving."""
    aid = int(account_id)

    # Basic aggregation (inbound)
    agg_df = query(
        "SELECT COUNT(*) AS cnt, SUM(amount) AS total_amount, "
        "SUM(is_fraud) AS fraud_cnt "
        "FROM hofinet WHERE receiver_acc = $aid",
        {"aid": aid},
    )

    if agg_df is None or agg_df.empty or int(agg_df.iloc[0]["cnt"] or 0) == 0:
        return {"account_id": aid, "direction": "inbound", "total_txns": 0, "notice": "No transaction history as receiver."}

    row = agg_df.iloc[0]
    total_count = int(row["cnt"] or 0)
    total_amount = int(row["total_amount" ] or 0)
    fraud_count = int(row["fraud_cnt"] or 0)

    # Top sending accounts
    sender_df = query(
        "SELECT sender_acc AS sender_id, "
        "COUNT(*) AS tx_count, SUM(amount) AS total_amount "
        "FROM hofinet WHERE receiver_acc = $aid "
        "GROUP BY sender_acc ORDER BY tx_count DESC LIMIT 5",
        {"aid": aid},
    )
    top_senders = sender_df.to_dict(orient="records") if not sender_df.empty else []

    # Sender bank distribution
    bank_df = query(
        "SELECT sender_bank AS bank_id, COUNT(*) AS tx_count "
        "FROM hofinet WHERE receiver_acc = $aid "
        "GROUP BY sender_bank ORDER BY tx_count DESC LIMIT 5",
        {"aid": aid},
    )
    top_sender_banks = bank_df.to_dict(orient="records") if not bank_df.empty else []

    # Hourly distribution
    hour_df = query(
        "SELECT time_slot as hour_range, COUNT(*) AS cnt FROM hofinet "
        "WHERE receiver_acc = $aid "
        "GROUP BY hour_range ORDER BY cnt DESC LIMIT 3",
        {"aid": aid},
    )
    top_hours = hour_df["hour_range"].tolist() if not hour_df.empty else []

    return {
        "account_id": aid,
        "direction": "inbound",
        "total_txns": total_count,
        "total_amount": total_amount,
        "fraud_count": fraud_count,
        "fraud_rate": round(fraud_count / total_count, 4) if total_count > 0 else 0.0,
        "unique_senders": int(sender_df["sender_id"].nunique()) if not sender_df.empty else 0,
        "top_hours": top_hours,
        "top_senders": top_senders,
        "top_sender_banks": top_sender_banks,
    }


# ------------------------------------------------------------------
# Filter UI Support
# ------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_date_range() -> tuple[int, int]:
    """Returns min and max transaction dates for filter UI."""
    try:
        row = query(
            "SELECT min(date) as min_date, max(date) as max_date FROM hofinet"
        ).iloc[0]
        return int(row["min_date"]), int(row["max_date"])
    except Exception:
        return 20210901, 20241231
