"""기능6: 계좌 위험도 평가 (Risk Scoring) 모듈.

5개 행위 지표 기반 0~100점 위험도 산출.
근거: 실무2편 — 위험평가 프레임워크 (고유위험 - 내부통제 = 잔여위험).
"""

import math

import pandas as pd
import streamlit as st

from src.data.db import query


def _safe_int(val, default=0):
    """NaN-safe int 변환."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return int(val)


# ------------------------------------------------------------------
# 가중치 설정
# ------------------------------------------------------------------

_WEIGHTS = {
    "nighttime_ratio": 0.15,
    "amount_anomaly": 0.25,
    "counterparty_diversity": 0.15,
    "velocity_change": 0.25,
    "fraud_history": 0.20,
}


# ------------------------------------------------------------------
# 개별 컴포넌트 계산
# ------------------------------------------------------------------

def _calc_nighttime_ratio(account_id: int) -> float:
    """심야거래(시간대 0, 3) 비율을 0~1로 반환한다."""
    aid = int(account_id)
    df = query(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN 거래시간대 IN (0, 3) THEN 1 ELSE 0 END) AS night
        FROM hofinet
        WHERE 출금계좌일련번호 = {aid}
    """)
    if df.empty:
        return 0.0
    row = df.iloc[0]
    total = _safe_int(row["total"])
    night = _safe_int(row["night"])
    return night / total if total > 0 else 0.0


def _calc_amount_anomaly(account_id: int) -> float:
    """z-score 기반 금액 이상도를 0~1로 반환한다 (클수록 이상)."""
    aid = int(account_id)
    df = query(f"""
        SELECT AVG(거래금액) AS avg_amt, STDDEV_POP(거래금액) AS std_amt
        FROM hofinet
        WHERE 출금계좌일련번호 = {aid}
    """)
    if df.empty:
        return 0.0
    row = df.iloc[0]
    avg_amt = float(row["avg_amt"] or 0)
    std_amt = float(row["std_amt"] or 0)

    if std_amt == 0 or avg_amt == 0:
        return 0.0

    # 전체 평균과 비교한 z-score
    global_df = query("SELECT AVG(거래금액) AS g_avg FROM hofinet")
    g_avg = float(global_df.iloc[0]["g_avg"] or 0) if not global_df.empty else 0

    if std_amt == 0:
        return 0.0
    z = abs(avg_amt - g_avg) / std_amt
    # sigmoid-like normalization to 0~1
    return min(1.0, z / 5.0)


def _calc_counterparty_diversity(account_id: int) -> float:
    """거래 상대 다양성 점수를 0~1로 반환한다 (다양할수록 높음)."""
    aid = int(account_id)
    df = query(f"""
        SELECT
            COUNT(DISTINCT 입금계좌일련번호) AS unique_accounts,
            COUNT(DISTINCT 입금금융회사일련번호) AS unique_banks,
            COUNT(*) AS total
        FROM hofinet
        WHERE 출금계좌일련번호 = {aid}
    """)
    if df.empty:
        return 0.0
    row = df.iloc[0]
    total = _safe_int(row["total"])
    unique_accounts = _safe_int(row["unique_accounts"])
    if total == 0:
        return 0.0
    # 고유 상대방 비율 (높으면 다양 = 위험 신호)
    ratio = unique_accounts / total
    return min(1.0, ratio)


def _calc_velocity_change(account_id: int) -> float:
    """최근 분기 vs 이전 분기 거래량 변화율을 0~1로 반환한다."""
    aid = int(account_id)
    df = query(f"""
        SELECT
            CAST(거래일자 / 10000 AS INT) AS 연도,
            CASE
                WHEN (거래일자 / 100 % 100) <= 3 THEN 1
                WHEN (거래일자 / 100 % 100) <= 6 THEN 2
                WHEN (거래일자 / 100 % 100) <= 9 THEN 3
                ELSE 4
            END AS 분기,
            COUNT(*) AS 건수
        FROM hofinet
        WHERE 출금계좌일련번호 = {aid}
        GROUP BY 연도, 분기
        ORDER BY 연도 DESC, 분기 DESC
        LIMIT 2
    """)
    if df.empty or len(df) < 2:
        return 0.0
    recent = _safe_int(df.iloc[0]["건수"])
    previous = _safe_int(df.iloc[1]["건수"])
    if previous == 0:
        return 1.0 if recent > 0 else 0.0
    change_rate = abs(recent - previous) / previous
    return min(1.0, change_rate)


def _calc_fraud_history(account_id: int) -> float:
    """이상거래이력 비율을 0~1로 반환한다."""
    aid = int(account_id)
    df = query(f"""
        SELECT COUNT(*) AS total,
               SUM(이상거래여부) AS fraud
        FROM hofinet
        WHERE 출금계좌일련번호 = {aid}
    """)
    if df.empty:
        return 0.0
    row = df.iloc[0]
    total = _safe_int(row["total"])
    fraud = _safe_int(row["fraud"])
    return fraud / total if total > 0 else 0.0


# ------------------------------------------------------------------
# 종합 위험도 산출
# ------------------------------------------------------------------

def score_account(account_id: int) -> dict:
    """계좌의 5개 컴포넌트 위험 점수 + 종합 0~100점을 반환한다."""
    aid = int(account_id)

    # 계좌 존재 여부 확인
    check = query("SELECT COUNT(*) AS cnt FROM hofinet WHERE 출금계좌일련번호 = ?", [aid])
    if check.empty or _safe_int(check.iloc[0]["cnt"]) == 0:
        return {"account_id": aid, "error": "해당 계좌의 거래 내역이 없습니다."}

    components = {
        "심야거래비율": _calc_nighttime_ratio(aid),
        "금액이상도": _calc_amount_anomaly(aid),
        "거래상대다양성": _calc_counterparty_diversity(aid),
        "거래속도변화": _calc_velocity_change(aid),
        "이상거래이력": _calc_fraud_history(aid),
    }

    weighted_sum = (
        components["심야거래비율"] * _WEIGHTS["nighttime_ratio"]
        + components["금액이상도"] * _WEIGHTS["amount_anomaly"]
        + components["거래상대다양성"] * _WEIGHTS["counterparty_diversity"]
        + components["거래속도변화"] * _WEIGHTS["velocity_change"]
        + components["이상거래이력"] * _WEIGHTS["fraud_history"]
    )
    total_score = round(weighted_sum * 100, 1)
    risk_level = (
        "높음" if total_score >= 70 else
        "중간" if total_score >= 40 else
        "낮음"
    )

    return {
        "account_id": aid,
        "종합점수": total_score,
        "위험등급": risk_level,
        "컴포넌트": {k: round(v, 4) for k, v in components.items()},
        "가중치": {
            "심야거래비율": _WEIGHTS["nighttime_ratio"],
            "금액이상도": _WEIGHTS["amount_anomaly"],
            "거래상대다양성": _WEIGHTS["counterparty_diversity"],
            "거래속도변화": _WEIGHTS["velocity_change"],
            "이상거래이력": _WEIGHTS["fraud_history"],
        },
    }


# ------------------------------------------------------------------
# 고위험 계좌 랭킹 (일괄 SQL)
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def rank_risky_accounts(top_k: int = 20,
                        min_transactions: int = 10) -> pd.DataFrame:
    """고위험 계좌 TOP-K를 일괄 SQL로 반환한다."""
    top_k = int(top_k)
    min_transactions = int(min_transactions)
    return query(f"""
        SELECT
            출금계좌일련번호 AS account_id,
            COUNT(*) AS 총거래건수,
            SUM(거래금액) AS 총거래금액,
            SUM(이상거래여부) AS 이상거래건수,
            ROUND(SUM(이상거래여부) * 100.0 / COUNT(*), 2) AS 이상거래비율,
            ROUND(SUM(CASE WHEN 거래시간대 IN (0, 3) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS 심야거래비율,
            COUNT(DISTINCT 입금계좌일련번호) AS 거래상대수,
            ROUND(
                (SUM(CASE WHEN 거래시간대 IN (0, 3) THEN 1 ELSE 0 END) * 1.0 / COUNT(*)) * 15 +
                (SUM(이상거래여부) * 1.0 / COUNT(*)) * 20 +
                (COUNT(DISTINCT 입금계좌일련번호) * 1.0 / COUNT(*)) * 15,
                2
            ) AS 위험점수_간이
        FROM hofinet
        GROUP BY 출금계좌일련번호
        HAVING COUNT(*) >= {min_transactions}
        ORDER BY 위험점수_간이 DESC
        LIMIT {top_k}
    """)
