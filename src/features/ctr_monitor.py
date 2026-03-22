"""기능5: CTR 모니터링 (고액현금거래보고) 모듈.

1,000만원 이상 고액거래 조회 및 분할거래(structuring) 탐지.
근거: 특정금융정보법 — 고액현금거래보고(CTR) 의무.
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
    """NaN-safe int 변환."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return int(val)


# ------------------------------------------------------------------
# 고액거래 조회
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_ctr_candidates(date_from: int | None = None,
                       date_to: int | None = None,
                       limit: int = 100) -> pd.DataFrame:
    """거래금액 >= 1,000만원인 CTR 대상 거래를 조회한다."""
    limit = int(limit)
    conditions = ["거래금액 >= 10000000"]
    if date_from is not None:
        conditions.append(f"거래일자 >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"거래일자 <= {int(date_to)}")
    where = "WHERE " + " AND ".join(conditions)
    return query(f"""
        SELECT 거래일자, 거래시간대, 출금금융회사일련번호, 출금계좌일련번호,
               입금금융회사일련번호, 입금계좌일련번호, 자금구분, 매체구분,
               거래금액, 이상거래여부, 이상거래유형
        FROM hofinet
        {where}
        ORDER BY 거래금액 DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# 분할거래(Structuring) 탐지
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_structuring(date_from: int | None = None,
                       date_to: int | None = None,
                       threshold: int = 10_000_000,
                       limit: int = 100) -> pd.DataFrame:
    """동일 계좌·동일일 합산 >= threshold, 단건 < threshold, 2건 이상인 분할거래 의심 건을 탐지한다."""
    threshold = int(threshold)
    limit = int(limit)
    conditions = []
    if date_from is not None:
        conditions.append(f"거래일자 >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"거래일자 <= {int(date_to)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return query(f"""
        SELECT 출금계좌일련번호, 거래일자,
               COUNT(*) AS 거래건수,
               SUM(거래금액) AS 합산금액,
               MAX(거래금액) AS 최대단건금액,
               MIN(거래금액) AS 최소단건금액
        FROM hofinet
        {where}
        GROUP BY 출금계좌일련번호, 거래일자
        HAVING SUM(거래금액) >= {threshold}
           AND MAX(거래금액) < {threshold}
           AND COUNT(*) >= 2
        ORDER BY 합산금액 DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# 특정 계좌 분할거래 패턴 분석
# ------------------------------------------------------------------

def assess_account_structuring(account_id: int,
                               threshold: int = 10_000_000) -> dict:
    """특정 계좌의 분할거래 패턴을 분석한다."""
    aid = int(account_id)
    threshold = int(threshold)

    # 분할거래 의심일 조회
    df = query(f"""
        SELECT 거래일자, COUNT(*) AS 거래건수,
               SUM(거래금액) AS 합산금액,
               MAX(거래금액) AS 최대단건금액
        FROM hofinet
        WHERE 출금계좌일련번호 = {aid}
        GROUP BY 거래일자
        HAVING SUM(거래금액) >= {threshold}
           AND MAX(거래금액) < {threshold}
           AND COUNT(*) >= 2
        ORDER BY 거래일자
    """)

    # 전체 거래 통계
    total_df = query(f"""
        SELECT COUNT(*) AS 총건수, SUM(거래금액) AS 총금액
        FROM hofinet
        WHERE 출금계좌일련번호 = {aid}
    """)

    total_row = total_df.iloc[0] if not total_df.empty else {}
    총건수 = _safe_int(total_row.get("총건수", 0))
    총금액 = _safe_int(total_row.get("총금액", 0))

    return {
        "account_id": aid,
        "총거래건수": 총건수,
        "총거래금액": 총금액,
        "분할거래의심일수": len(df),
        "분할거래상세": df.to_dict(orient="records") if not df.empty else [],
    }


# ------------------------------------------------------------------
# CTR 종합 통계
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_ctr_summary(filters=None) -> dict:
    """CTR 모니터링 종합 통계를 반환한다."""
    conditions = []
    if filters:
        if filters.get("date_from"):
            conditions.append(f"거래일자 >= {int(filters['date_from'])}")
        if filters.get("date_to"):
            conditions.append(f"거래일자 <= {int(filters['date_to'])}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # 고액거래 통계
    high_conditions = ["거래금액 >= 10000000"] + conditions
    high_where = "WHERE " + " AND ".join(high_conditions)
    high_df = query(f"""
        SELECT COUNT(*) AS 고액거래건수, SUM(거래금액) AS 고액거래총액
        FROM hofinet
        {high_where}
    """)

    # 분할거래 의심 통계 — 정확한 SQL로 재작성
    if conditions:
        struct_where = "WHERE " + " AND ".join(conditions)
    else:
        struct_where = ""

    struct_df = query(f"""
        SELECT COUNT(*) AS 의심건수 FROM (
            SELECT 출금계좌일련번호, 거래일자
            FROM hofinet
            {struct_where}
            GROUP BY 출금계좌일련번호, 거래일자
            HAVING SUM(거래금액) >= 10000000
               AND MAX(거래금액) < 10000000
               AND COUNT(*) >= 2
        ) sub
    """)

    high_row = high_df.iloc[0] if not high_df.empty else {}
    struct_row = struct_df.iloc[0] if not struct_df.empty else {}

    return {
        "고액거래건수": _safe_int(high_row.get("고액거래건수", 0)),
        "고액거래총액": _safe_int(high_row.get("고액거래총액", 0)),
        "분할거래의심건수": _safe_int(struct_row.get("의심건수", 0)),
    }
