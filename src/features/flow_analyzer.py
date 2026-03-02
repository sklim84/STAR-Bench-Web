"""자금 흐름 분석 모듈.

자금 수집/분산 패턴(Smurfing Network) 탐지 및
기관 간 자금 흐름(Cross-Institution Flow) 분석.
"""

import pandas as pd
import streamlit as st

from src.data.db import query


# ------------------------------------------------------------------
# 자금 수집/분산 패턴 탐지 (Smurfing Network)
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def detect_smurfing_network(account_id: int | None = None,
                            direction: str = "inbound",
                            min_counterparts: int = 5,
                            date_from: int | None = None,
                            date_to: int | None = None,
                            limit: int = 50) -> pd.DataFrame:
    """자금 수집(inbound) 또는 분산(outbound) 패턴을 탐지한다.

    Args:
        account_id: 특정 계좌 한정 (None이면 전체 스캔)
        direction: 'inbound'(다수→1 수집) 또는 'outbound'(1→다수 분산)
        min_counterparts: 최소 거래 상대 계좌 수
        date_from: 시작일 (YYYYMMDD)
        date_to: 종료일 (YYYYMMDD)
        limit: 최대 결과 수

    Returns:
        DataFrame with 계좌, 거래상대수, 총거래건수, 총거래금액, 이상거래건수
    """
    min_counterparts = int(min_counterparts)
    limit = int(limit)
    conditions = []
    if date_from is not None:
        conditions.append(f"거래일자 >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"거래일자 <= {int(date_to)}")

    if direction == "inbound":
        # 다수 출금계좌 → 1 입금계좌 (자금 수집 / funnel)
        target_col = "입금계좌일련번호"
        counter_col = "출금계좌일련번호"
        label = "수집대상계좌"
    else:
        # 1 출금계좌 → 다수 입금계좌 (자금 분산 / dispersion)
        target_col = "출금계좌일련번호"
        counter_col = "입금계좌일련번호"
        label = "분산원천계좌"

    if account_id is not None:
        conditions.append(f"{target_col} = {int(account_id)}")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    return query(f"""
        SELECT
            {target_col} AS {label},
            COUNT(DISTINCT {counter_col}) AS 거래상대수,
            COUNT(*) AS 총거래건수,
            SUM(거래금액) AS 총거래금액,
            SUM(이상거래여부) AS 이상거래건수,
            ROUND(AVG(거래금액), 0) AS 평균거래금액
        FROM hofinet
        {where}
        GROUP BY {target_col}
        HAVING COUNT(DISTINCT {counter_col}) >= {min_counterparts}
        ORDER BY 거래상대수 DESC, 총거래금액 DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# 기관 간 자금 흐름 분석 (Cross-Institution Flow)
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def analyze_cross_institution_flow(date_from: int | None = None,
                                   date_to: int | None = None,
                                   min_transactions: int = 10,
                                   limit: int = 50) -> pd.DataFrame:
    """기관 쌍(출금기관→입금기관) 간 자금 흐름을 분석한다.

    Args:
        date_from: 시작일 (YYYYMMDD)
        date_to: 종료일 (YYYYMMDD)
        min_transactions: 최소 거래 건수
        limit: 최대 결과 수

    Returns:
        DataFrame with 기관쌍별 거래건수, 이상거래건수, 이상거래비율, 총거래금액
    """
    min_transactions = int(min_transactions)
    limit = int(limit)
    conditions = []
    if date_from is not None:
        conditions.append(f"거래일자 >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"거래일자 <= {int(date_to)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    return query(f"""
        SELECT
            출금금융회사일련번호 AS 출금기관,
            입금금융회사일련번호 AS 입금기관,
            COUNT(*) AS 거래건수,
            SUM(이상거래여부) AS 이상거래건수,
            ROUND(SUM(이상거래여부) * 100.0 / COUNT(*), 4) AS 이상거래비율,
            SUM(거래금액) AS 총거래금액,
            ROUND(AVG(거래금액), 0) AS 평균거래금액,
            COUNT(DISTINCT 출금계좌일련번호) AS 출금계좌수,
            COUNT(DISTINCT 입금계좌일련번호) AS 입금계좌수
        FROM hofinet
        {where}
        GROUP BY 출금금융회사일련번호, 입금금융회사일련번호
        HAVING COUNT(*) >= {min_transactions}
        ORDER BY 이상거래비율 DESC, 거래건수 DESC
        LIMIT {limit}
    """)
