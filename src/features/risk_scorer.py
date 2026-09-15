"""Feature 6: Account Risk Evaluation (Risk Scoring) Module.

Calculates a 0-100 risk score from 5 behavioural indicators.
Basis: AML Practice Vol 2 -- Risk Assessment Framework (Inherent Risk -
Internal Controls = Residual Risk).

Definitions, after the round-2 audit:

* the account's transactions are those it sends *or* receives, so accounts that
  only appear as receiver_acc are scored instead of rejected;
* amount_anomaly compares the account's average amount with the dataset average
  in units of the *dataset's* standard deviation (dividing by the account's own
  standard deviation scored every constant-amount account 0);
* velocity_change compares the account's last active quarter with the calendar
  quarter immediately before it, with integer quarter arithmetic;
* fraud_history is the share of the account's transactions that HOFINET labels
  as fraud. It is derived from the ground-truth label, which is stated in the
  tool description: it is prior confirmed-fraud history, not a prediction.
"""

import pandas as pd
import streamlit as st

from src.data.db import query
from src.features.monitoring import NIGHT_TIME_SLOTS

_NIGHT_SQL = ", ".join(str(slot) for slot in NIGHT_TIME_SLOTS)


def _safe_int(val, default: int = 0) -> int:
    """NaN-safe int conversion (aggregates over zero rows come back NULL)."""
    if val is None or pd.isna(val):
        return default
    return int(val)


def _safe_float(val, default: float = 0.0) -> float:
    """NaN-safe float conversion."""
    if val is None or pd.isna(val):
        return default
    return float(val)


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

@st.cache_data(ttl=300, show_spinner=False)
def get_amount_baseline() -> tuple[float, float]:
    """Returns the dataset-wide mean and standard deviation of amount."""
    row = query("SELECT AVG(amount) AS avg_amt, STDDEV_POP(amount) AS std_amt FROM hofinet").iloc[0]
    return _safe_float(row["avg_amt"]), _safe_float(row["std_amt"])


def _account_stats(account_id: int) -> dict:
    """Returns the aggregates every component is derived from."""
    aid = int(account_id)
    row = query(
        f"""
        SELECT
            COUNT(*)::BIGINT AS total,
            COUNT(*) FILTER (WHERE sender_acc = $aid)::BIGINT AS sent,
            COUNT(*) FILTER (WHERE receiver_acc = $aid)::BIGINT AS received,
            COUNT(*) FILTER (WHERE time_slot IN ({_NIGHT_SQL}))::BIGINT AS night,
            COALESCE(SUM(is_fraud), 0)::BIGINT AS fraud,
            AVG(amount) AS avg_amount,
            COALESCE(SUM(amount), 0)::BIGINT AS total_amount,
            COUNT(DISTINCT CASE WHEN sender_acc = $aid THEN receiver_acc END)::BIGINT AS out_counterparties,
            COUNT(DISTINCT CASE WHEN receiver_acc = $aid THEN sender_acc END)::BIGINT AS in_counterparties,
            MIN(date) AS first_date,
            MAX(date) AS last_date
        FROM hofinet
        WHERE sender_acc = $aid OR receiver_acc = $aid
        """,
        {"aid": aid},
    ).iloc[0]
    return {
        "total": _safe_int(row["total"]),
        "sent": _safe_int(row["sent"]),
        "received": _safe_int(row["received"]),
        "night": _safe_int(row["night"]),
        "fraud": _safe_int(row["fraud"]),
        "avg_amount": _safe_float(row["avg_amount"]),
        "total_amount": _safe_int(row["total_amount"]),
        "counterparties": _safe_int(row["out_counterparties"]) + _safe_int(row["in_counterparties"]),
        "first_date": _safe_int(row["first_date"]),
        "last_date": _safe_int(row["last_date"]),
    }


def _calc_nighttime_ratio(stats: dict) -> float:
    """Share of the account's transactions in the night slots (0 to 1)."""
    return stats["night"] / stats["total"] if stats["total"] else 0.0


def _calc_amount_anomaly(stats: dict) -> float:
    """How far the account's average amount sits from the dataset average (0 to 1)."""
    global_avg, global_std = get_amount_baseline()
    if not global_std or not stats["avg_amount"]:
        return 0.0
    z = abs(stats["avg_amount"] - global_avg) / global_std
    return min(1.0, z / 5.0)


def _calc_counterparty_diversity(stats: dict) -> float:
    """Distinct counterparties per transaction (0 to 1)."""
    if not stats["total"]:
        return 0.0
    return min(1.0, stats["counterparties"] / stats["total"])


def _calc_velocity_change(account_id: int) -> float:
    """Change in transaction volume between two consecutive quarters (0 to 1).

    The account's last active quarter is compared with the calendar quarter
    immediately before it, which may itself be empty.
    """
    aid = int(account_id)
    df = query(
        """
        SELECT CAST(date // 10000 AS INT) * 4 + (date // 100 % 100 - 1) // 3 AS quarter_index,
               COUNT(*) AS count
        FROM hofinet
        WHERE sender_acc = $aid OR receiver_acc = $aid
        GROUP BY quarter_index
        ORDER BY quarter_index
        """,
        {"aid": aid},
    )
    if df.empty:
        return 0.0
    counts = {int(r["quarter_index"]): _safe_int(r["count"]) for _, r in df.iterrows()}
    recent_quarter = max(counts)
    recent = counts[recent_quarter]
    previous = counts.get(recent_quarter - 1, 0)
    if previous == 0:
        return 1.0 if recent > 0 else 0.0
    return min(1.0, abs(recent - previous) / previous)


def _calc_fraud_history(stats: dict) -> float:
    """Share of the account's transactions labelled as fraud in HOFINET (0 to 1)."""
    return stats["fraud"] / stats["total"] if stats["total"] else 0.0


# ------------------------------------------------------------------
# Composite Risk Scoring
# ------------------------------------------------------------------

def score_account(account_id: int) -> dict:
    """Returns 5 component risk scores + composite 0-100 score for an account."""
    aid = int(account_id)
    stats = _account_stats(aid)

    if stats["total"] == 0:
        return {"account_id": aid, "total_count": 0,
                "notice": "No transaction history for this account."}

    components = {
        "nighttime_ratio": _calc_nighttime_ratio(stats),
        "amount_anomaly": _calc_amount_anomaly(stats),
        "counterparty_diversity": _calc_counterparty_diversity(stats),
        "velocity_change": _calc_velocity_change(aid),
        "fraud_history": _calc_fraud_history(stats),
    }

    weighted_sum = sum(components[key] * weight for key, weight in _WEIGHTS.items())
    total_score = round(weighted_sum * 100, 1)
    risk_level = (
        "High" if total_score >= 70 else
        "Medium" if total_score >= 40 else
        "Low"
    )

    if stats["sent"] and stats["received"]:
        role = "sender_and_receiver"
    elif stats["sent"]:
        role = "sender"
    else:
        role = "receiver"

    return {
        "account_id": aid,
        "total_score": total_score,
        "risk_level": risk_level,
        "role": role,
        "total_count": stats["total"],
        "sent_count": stats["sent"],
        "received_count": stats["received"],
        "components": {k: round(v, 4) for k, v in components.items()},
        "weights": dict(_WEIGHTS),
        "component_note": (
            "Components are 0-1 sub-scores. fraud_history is the share of this "
            "account's transactions labelled as fraud in HOFINET."
        ),
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
            COUNT(*)::BIGINT AS total_tx_count,
            COALESCE(SUM(amount), 0)::BIGINT AS total_amount,
            COALESCE(SUM(is_fraud), 0)::BIGINT AS fraud_count,
            ROUND(SUM(is_fraud) * 100.0 / COUNT(*), 2) AS fraud_ratio_percent,
            ROUND(SUM(CASE WHEN time_slot IN ({_NIGHT_SQL}) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS nighttime_ratio_percent,
            COUNT(DISTINCT receiver_acc)::BIGINT AS counterparty_count,
            ROUND(
                (SUM(CASE WHEN time_slot IN ({_NIGHT_SQL}) THEN 1 ELSE 0 END) * 1.0 / COUNT(*)) * 15 +
                (SUM(is_fraud) * 1.0 / COUNT(*)) * 20 +
                (COUNT(DISTINCT receiver_acc) * 1.0 / COUNT(*)) * 15,
                2
            ) AS risk_score_simple
        FROM hofinet
        GROUP BY sender_acc
        HAVING COUNT(*) >= {min_transactions}
        ORDER BY risk_score_simple DESC, total_tx_count DESC, account_id
        LIMIT {top_k}
    """)
