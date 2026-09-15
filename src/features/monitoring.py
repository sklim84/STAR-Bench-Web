"""Feature 7: Transaction Monitoring Rule Detection Module.

Five rules and the alerts they raise. Basis: AML Practice Vol 5 -- Rule-based
Monitoring, Suspicious Transaction Indicators.

Every rule takes the same filters: a date range and one account, so a question
about a single account is answered by the rule rather than by scanning the whole
dataset. Thresholds are set from HOFINET's own value structure, because the
generic textbook thresholds cannot fire on it:

* night hours are time slots 21, 0 and 3 (21:00-06:00). All 35 transactions
  labelled "late-night/early-morning bulk" sit in slot 21, and the smallest of
  them is 5,000,000 KRW, which is the default amount for R001. The previous
  definition (slots 0 and 3 with at least 10,000,000 KRW) matched 0 of the
  4.7M transactions, since those slots top out at 5,000,000 KRW.
* R003 flags the same amount sent repeatedly by one account. HOFINET amounts
  take 48 values, all multiples of 1,000 -- "amount is a round million" was true
  for every transaction of 1M KRW or more and said nothing. The default floor,
  2,000,000 KRW, is the smallest amount that appears on any fraud-labelled row.
* R004 flags accounts whose transactions concentrate on one receiving
  institution. Among accounts with at least 10 transactions the 99th percentile
  of that share is 0.44, so the default of 0.5 (not 0.8, which matched a single
  account) marks the tail.
"""

import json
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import config
from src.data.db import query

_CACHE_HASH_FUNCS = {
    dict: lambda d: json.dumps(d, sort_keys=True, default=str) if d else "none",
}

# 21:00-06:00. Slot n covers n:00 to n+3:00.
NIGHT_TIME_SLOTS = (21, 0, 3)
NIGHT_MIN_AMOUNT = 5_000_000
REPEATED_AMOUNT_MIN = 2_000_000
CONCENTRATION_MIN_RATIO = 0.5

_NIGHT_SQL = ", ".join(str(slot) for slot in NIGHT_TIME_SLOTS)


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


def default_pattern_change_period() -> tuple[int, int]:
    """Returns the comparison window R005 uses when no dates are given.

    The last full quarter of the dataset, derived from the reference date rather
    than from today, so the rule returns the same alerts on every run.
    """
    end = _parse_yyyymmdd(config.REFERENCE_DATE)
    quarter_first_month = (end.month - 1) // 3 * 3 + 1
    start = end.replace(month=quarter_first_month, day=1)
    return _to_yyyymmdd(start), _to_yyyymmdd(end)


def _filters(date_from, date_to, account_id, account_columns=("sender_acc",)) -> list[str]:
    """Builds the WHERE conditions every rule shares."""
    conditions = []
    if date_from is not None:
        conditions.append(f"date >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"date <= {int(date_to)}")
    if account_id is not None:
        match = " OR ".join(f"{col} = {int(account_id)}" for col in account_columns)
        conditions.append(f"({match})")
    return conditions


# ------------------------------------------------------------------
# R001: Late-night bulk transactions
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_nighttime_bulk(date_from: int | None = None,
                          date_to: int | None = None,
                          min_amount: int = NIGHT_MIN_AMOUNT,
                          account_id: int | None = None,
                          limit: int = 100) -> pd.DataFrame:
    """R001: Large transactions in the night slots (21, 0, 3)."""
    min_amount = int(min_amount)
    limit = int(limit)
    conditions = [f"time_slot IN ({_NIGHT_SQL})", f"amount >= {min_amount}"]
    conditions += _filters(date_from, date_to, account_id, ("sender_acc", "receiver_acc"))
    where = "WHERE " + " AND ".join(conditions)
    return query(f"""
        SELECT date, time_slot, sender_acc, receiver_acc,
               sender_bank, receiver_bank, amount,
               is_fraud, fraud_type
        FROM hofinet
        {where}
        ORDER BY amount DESC, date, time_slot, sender_acc, receiver_acc,
                 sender_bank, receiver_bank, is_fraud
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R002: Multi-transaction on same day (Rapid-fire)
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_rapid_fire(date_from: int | None = None,
                      date_to: int | None = None,
                      min_count: int = 10,
                      account_id: int | None = None,
                      limit: int = 100) -> pd.DataFrame:
    """R002: Detects accounts with min_count+ transactions on the same day."""
    min_count = int(min_count)
    limit = int(limit)
    conditions = _filters(date_from, date_to, account_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return query(f"""
        SELECT sender_acc, date,
               COUNT(*)::BIGINT AS tx_count,
               COALESCE(SUM(amount), 0)::BIGINT AS total_amount,
               COALESCE(SUM(is_fraud), 0)::BIGINT AS fraud_count
        FROM hofinet
        {where}
        GROUP BY sender_acc, date
        HAVING COUNT(*) >= {min_count}
        ORDER BY tx_count DESC, total_amount DESC, sender_acc, date
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R003: Repeated identical amounts
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_repeated_amounts(date_from: int | None = None,
                            date_to: int | None = None,
                            min_amount: int = REPEATED_AMOUNT_MIN,
                            min_count: int = 3,
                            account_id: int | None = None,
                            limit: int = 100) -> pd.DataFrame:
    """R003: Accounts that send the same amount min_count+ times."""
    min_amount = int(min_amount)
    min_count = int(min_count)
    limit = int(limit)
    conditions = [f"amount >= {min_amount}"]
    conditions += _filters(date_from, date_to, account_id)
    where = "WHERE " + " AND ".join(conditions)
    return query(f"""
        SELECT sender_acc, amount,
               COUNT(*)::BIGINT AS repeat_count,
               COALESCE(SUM(amount), 0)::BIGINT AS total_amount,
               MIN(date) AS first_date,
               MAX(date) AS last_date,
               COUNT(DISTINCT receiver_acc)::BIGINT AS receiver_count
        FROM hofinet
        {where}
        GROUP BY sender_acc, amount
        HAVING COUNT(*) >= {min_count}
        ORDER BY repeat_count DESC, amount DESC, sender_acc
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R004: Institutional concentration
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_institution_concentration(min_ratio: float = CONCENTRATION_MIN_RATIO,
                                     min_transactions: int = 10,
                                     date_from: int | None = None,
                                     date_to: int | None = None,
                                     account_id: int | None = None,
                                     limit: int = 100) -> pd.DataFrame:
    """R004: Accounts whose transactions concentrate on one receiving institution."""
    min_transactions = int(min_transactions)
    limit = int(limit)
    conditions = _filters(date_from, date_to, account_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return query(f"""
        WITH account_bank AS (
            SELECT sender_acc,
                   receiver_bank,
                   COUNT(*) AS bank_tx_count
            FROM hofinet
            {where}
            GROUP BY sender_acc, receiver_bank
        ),
        ranked AS (
            SELECT sender_acc, receiver_bank, bank_tx_count,
                   SUM(bank_tx_count) OVER (PARTITION BY sender_acc) AS total_tx_count,
                   ROW_NUMBER() OVER (
                       PARTITION BY sender_acc
                       ORDER BY bank_tx_count DESC, receiver_bank
                   ) AS rn
            FROM account_bank
        )
        SELECT
            sender_acc,
            total_tx_count::BIGINT AS total_tx_count,
            bank_tx_count::BIGINT AS max_bank_tx_count,
            ROUND(bank_tx_count * 100.0 / total_tx_count, 2) AS concentration_percent,
            receiver_bank AS concentration_bank
        FROM ranked
        WHERE rn = 1
          AND total_tx_count >= {min_transactions}
          AND bank_tx_count * 1.0 / total_tx_count >= {float(min_ratio)}
        ORDER BY concentration_percent DESC, total_tx_count DESC, sender_acc
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R005: Sudden pattern change
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_pattern_change(base_start: int, base_end: int,
                          compare_start: int, compare_end: int,
                          change_threshold: float = 3.0,
                          account_id: int | None = None,
                          limit: int = 100) -> pd.DataFrame:
    """R005: Detects accounts with a sudden surge in transaction volume compared to a base period."""
    base_start = int(base_start)
    base_end = int(base_end)
    compare_start = int(compare_start)
    compare_end = int(compare_end)
    limit = int(limit)
    account_filter = f"AND sender_acc = {int(account_id)}" if account_id is not None else ""
    return query(f"""
        WITH base AS (
            SELECT sender_acc, COUNT(*) AS base_count, SUM(amount) AS base_amount
            FROM hofinet
            WHERE date BETWEEN {base_start} AND {base_end}
            {account_filter}
            GROUP BY sender_acc
            HAVING COUNT(*) >= 5
        ),
        compare AS (
            SELECT sender_acc, COUNT(*) AS comp_count, SUM(amount) AS comp_amount
            FROM hofinet
            WHERE date BETWEEN {compare_start} AND {compare_end}
            {account_filter}
            GROUP BY sender_acc
        )
        SELECT
            b.sender_acc,
            b.base_count::BIGINT AS base_period_count,
            c.comp_count::BIGINT AS comp_period_count,
            ROUND(c.comp_count * 1.0 / b.base_count, 2) AS count_change_multiple,
            b.base_amount::BIGINT AS base_period_amount,
            c.comp_amount::BIGINT AS comp_period_amount,
            ROUND(c.comp_amount * 1.0 / NULLIF(b.base_amount, 0), 2) AS amount_change_multiple
        FROM base b
        JOIN compare c ON b.sender_acc = c.sender_acc
        WHERE c.comp_count * 1.0 / b.base_count >= {float(change_threshold)}
           OR c.comp_amount * 1.0 / NULLIF(b.base_amount, 0) >= {float(change_threshold)}
        ORDER BY count_change_multiple DESC, comp_period_count DESC, b.sender_acc
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# Full rule execution
# ------------------------------------------------------------------

RULE_NAMES = {
    "R001": "Nighttime Bulk Transactions",
    "R002": "Same-Day Rapid-Fire Transactions",
    "R003": "Repeated Identical Amounts",
    "R004": "Institution Concentration",
    "R005": "Transaction Pattern Change",
}


def run_rule(rule_id: str,
             date_from: int | None = None,
             date_to: int | None = None,
             account_id: int | None = None,
             limit: int = 100) -> pd.DataFrame:
    """Runs one rule with the shared filters and returns its alerts."""
    if rule_id == "R001":
        return detect_nighttime_bulk(date_from, date_to, account_id=account_id, limit=limit)
    if rule_id == "R002":
        return detect_rapid_fire(date_from, date_to, account_id=account_id, limit=limit)
    if rule_id == "R003":
        return detect_repeated_amounts(date_from, date_to, account_id=account_id, limit=limit)
    if rule_id == "R004":
        return detect_institution_concentration(
            date_from=date_from, date_to=date_to, account_id=account_id, limit=limit
        )
    if rule_id == "R005":
        if date_from is None or date_to is None:
            date_from, date_to = default_pattern_change_period()
        base_start, base_end = _calculate_previous_period(int(date_from), int(date_to))
        return detect_pattern_change(
            base_start=base_start, base_end=base_end,
            compare_start=int(date_from), compare_end=int(date_to),
            account_id=account_id, limit=limit,
        )
    raise ValueError(f"Unknown rule_id: {rule_id}")


@st.cache_data(ttl=300, show_spinner=False)
def run_all_rules(date_from: int | None = None,
                  date_to: int | None = None,
                  account_id: int | None = None,
                  limit: int = 10) -> dict:
    """Runs all rules and returns results summary."""
    limit = int(limit)
    results = {}
    for rule_id, rule_name in RULE_NAMES.items():
        try:
            df = run_rule(rule_id, date_from, date_to, account_id, limit=limit)
        except ValueError:
            # Invalid date input: that rule reports nothing, the others continue.
            df = pd.DataFrame()
        results[rule_id] = {
            "rule_name": rule_name,
            "count": len(df),
            "result": df.to_dict(orient="records"),
        }
    return results


# ------------------------------------------------------------------
# R006: Long-term dormant account reactivation
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_dormant_reactivation(dormant_days: int = 180,
                                 min_reactivation_amount: int = 5_000_000,
                                 account_id: int | None = None,
                                 limit: int = 100) -> pd.DataFrame:
    """R006: Detects accounts reactivated after a long dormant period.

    Activity is aggregated per day before the gap is measured: with one row per
    transaction, several transactions on the reactivation day made the reported
    gap and amount depend on the order rows came back in.
    """
    dormant_days = int(dormant_days)
    min_reactivation_amount = int(min_reactivation_amount)
    limit = int(limit)
    account_filter = f"WHERE sender_acc = {int(account_id)}" if account_id is not None else ""
    return query(f"""
        WITH daily AS (
            SELECT sender_acc, date,
                   COUNT(*) AS day_tx_count,
                   SUM(amount) AS day_amount,
                   MAX(amount) AS day_max_amount
            FROM hofinet
            {account_filter}
            GROUP BY sender_acc, date
        ),
        gaps AS (
            SELECT sender_acc,
                   LAG(date) OVER (PARTITION BY sender_acc ORDER BY date) AS last_activity_date,
                   date AS reactivation_date,
                   day_max_amount AS reactivation_amount,
                   day_tx_count AS reactivation_day_tx_count,
                   day_amount AS reactivation_day_amount
            FROM daily
        )
        SELECT sender_acc, last_activity_date, reactivation_date,
               date_diff('day',
                         strptime(CAST(last_activity_date AS VARCHAR), '%Y%m%d'),
                         strptime(CAST(reactivation_date AS VARCHAR), '%Y%m%d')) AS dormant_days,
               reactivation_amount::BIGINT AS reactivation_amount,
               reactivation_day_tx_count::BIGINT AS reactivation_day_tx_count,
               reactivation_day_amount::BIGINT AS reactivation_day_amount
        FROM gaps
        WHERE last_activity_date IS NOT NULL
          AND date_diff('day',
                        strptime(CAST(last_activity_date AS VARCHAR), '%Y%m%d'),
                        strptime(CAST(reactivation_date AS VARCHAR), '%Y%m%d')) >= {dormant_days}
          AND reactivation_amount >= {min_reactivation_amount}
        ORDER BY dormant_days DESC, reactivation_amount DESC, sender_acc, reactivation_date
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
            SUM(CASE WHEN time_slot IN ({_NIGHT_SQL}) THEN 1 ELSE 0 END) AS night_cnt
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
