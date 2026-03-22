"""기능1: 기본 분석 대시보드 쿼리 모듈."""

import json

import pandas as pd
import streamlit as st

from src.data.db import query

# st.cache_data용: dict는 unhashable이므로 JSON 문자열로 변환
_CACHE_HASH_FUNCS = {
    dict: lambda d: json.dumps(d, sort_keys=True, default=str) if d else "none",
}


# ------------------------------------------------------------------
# 글로벌 필터 헬퍼
# ------------------------------------------------------------------

def _build_filter_conditions(filters: dict | None) -> str:
    """필터 딕셔너리를 SQL 조건 문자열로 변환한다 (WHERE 키워드 없이)."""
    if not filters:
        return ""
    clauses = []
    if filters.get("date_from"):
        clauses.append(f"거래일자 >= {int(filters['date_from'])}")
    if filters.get("date_to"):
        clauses.append(f"거래일자 <= {int(filters['date_to'])}")
    if filters.get("banks"):
        bank_ids = ",".join(str(int(b)) for b in filters["banks"])
        clauses.append(f"출금금융회사일련번호 IN ({bank_ids})")
    if filters.get("fraud_types"):
        type_ids = ",".join(str(int(t)) for t in filters["fraud_types"])
        clauses.append(f"이상거래유형 IN ({type_ids})")
    return " AND ".join(clauses)


def _apply_filters(base_where: str, filters: dict | None) -> str:
    """기존 WHERE 절과 필터 조건을 결합한다.

    Args:
        base_where: 기존 WHERE 절 (예: "WHERE 이상거래여부 = 1" 또는 "")
        filters: 필터 딕셔너리

    Returns:
        결합된 WHERE 절 문자열
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
    """전체 요약 지표를 반환한다."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율,
            count(DISTINCT 출금계좌일련번호) as 출금계좌수,
            count(DISTINCT 입금계좌일련번호) as 입금계좌수,
            count(DISTINCT 출금금융회사일련번호) as 출금금융회사수,
            count(DISTINCT 입금금융회사일련번호) as 입금금융회사수,
            sum(거래금액) as 총거래금액
        FROM hofinet
        {where}
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_quarterly_trend(filters: dict | None = None) -> pd.DataFrame:
    """분기별 거래 건수 및 이상거래 추이를 반환한다."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            CAST(거래일자 / 10000 AS INT) as 연도,
            CASE
                WHEN (거래일자 / 100 % 100) <= 3 THEN 1
                WHEN (거래일자 / 100 % 100) <= 6 THEN 2
                WHEN (거래일자 / 100 % 100) <= 9 THEN 3
                ELSE 4
            END as 분기,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        {where}
        GROUP BY 연도, 분기
        ORDER BY 연도, 분기
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_hourly_distribution(filters: dict | None = None) -> pd.DataFrame:
    """시간대별 거래 분포를 반환한다."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            거래시간대,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        {where}
        GROUP BY 거래시간대
        ORDER BY 거래시간대
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_amount_distribution(filters: dict | None = None) -> pd.DataFrame:
    """거래금액 구간별 분포를 반환한다."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            CASE
                WHEN 거래금액 <= 10000 THEN '1만 이하'
                WHEN 거래금액 <= 100000 THEN '1만~10만'
                WHEN 거래금액 <= 1000000 THEN '10만~100만'
                WHEN 거래금액 <= 10000000 THEN '100만~1000만'
                WHEN 거래금액 <= 100000000 THEN '1000만~1억'
                ELSE '1억 초과'
            END as 금액구간,
            CASE
                WHEN 거래금액 <= 10000 THEN 1
                WHEN 거래금액 <= 100000 THEN 2
                WHEN 거래금액 <= 1000000 THEN 3
                WHEN 거래금액 <= 10000000 THEN 4
                WHEN 거래금액 <= 100000000 THEN 5
                ELSE 6
            END as 순서,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        {where}
        GROUP BY 금액구간, 순서
        ORDER BY 순서
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fraud_type_distribution(filters: dict | None = None) -> pd.DataFrame:
    """이상거래유형별 분포를 반환한다."""
    where = _apply_filters("WHERE 이상거래여부 = 1", filters)
    return query(f"""
        SELECT
            이상거래유형,
            이상거래설명,
            count(*) as 건수
        FROM hofinet
        {where}
        GROUP BY 이상거래유형, 이상거래설명
        ORDER BY 이상거래유형
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_monthly_trend(filters: dict | None = None) -> pd.DataFrame:
    """월별 거래 건수 및 이상거래 추이를 반환한다."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            CAST(거래일자 / 100 AS INT) as 연월,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        {where}
        GROUP BY 연월
        ORDER BY 연월
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_medium_distribution(filters: dict | None = None) -> pd.DataFrame:
    """매체구분별 거래 분포를 반환한다."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            매체구분,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        {where}
        GROUP BY 매체구분
        ORDER BY 매체구분
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_top_banks(filters: dict | None = None) -> pd.DataFrame:
    """금융회사별 이상거래 건수 상위를 반환한다."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            출금금융회사일련번호 as 금융회사,
            '출금' as 구분,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        {where}
        GROUP BY 출금금융회사일련번호
        HAVING sum(이상거래여부) > 0
        UNION ALL
        SELECT
            입금금융회사일련번호 as 금융회사,
            '입금' as 구분,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        {where}
        GROUP BY 입금금융회사일련번호
        HAVING sum(이상거래여부) > 0
        ORDER BY 이상거래 DESC
    """)


# ------------------------------------------------------------------
# FR-001: 자금구분별 이상거래 분포
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fund_type_distribution(filters: dict | None = None) -> pd.DataFrame:
    """자금구분별 거래 건수, 이상거래, 이상거래비율, 총거래금액을 반환한다."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            자금구분,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율,
            sum(거래금액) as 총거래금액
        FROM hofinet
        {where}
        GROUP BY 자금구분
        ORDER BY 자금구분
    """)


# ------------------------------------------------------------------
# FR-002: 이상거래 금액 분석
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fraud_amount_summary(filters: dict | None = None) -> pd.DataFrame:
    """이상거래여부별 금액 통계를 반환한다."""
    where = _apply_filters("", filters)
    return query(f"""
        SELECT
            이상거래여부,
            count(*) as 건수,
            sum(거래금액) as 총금액,
            round(avg(거래금액), 0) as 평균금액,
            median(거래금액) as 중앙값,
            min(거래금액) as 최소금액,
            max(거래금액) as 최대금액
        FROM hofinet
        {where}
        GROUP BY 이상거래여부
        ORDER BY 이상거래여부
    """)


@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fraud_amount_by_type(filters: dict | None = None) -> pd.DataFrame:
    """이상거래유형별 금액 통계를 반환한다."""
    where = _apply_filters("WHERE 이상거래여부 = 1", filters)
    return query(f"""
        SELECT
            이상거래유형,
            이상거래설명,
            count(*) as 건수,
            sum(거래금액) as 총금액,
            round(avg(거래금액), 0) as 평균금액,
            median(거래금액) as 중앙값
        FROM hofinet
        {where}
        GROUP BY 이상거래유형, 이상거래설명
        ORDER BY 총금액 DESC
    """)


# ------------------------------------------------------------------
# FR-005: 시간대 x 이상거래유형 교차 분석 히트맵
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_hourly_fraud_type_heatmap(filters: dict | None = None) -> pd.DataFrame:
    """시간대별 이상거래유형 건수를 반환한다 (히트맵용)."""
    where = _apply_filters("WHERE 이상거래여부 = 1", filters)
    return query(f"""
        SELECT
            거래시간대,
            이상거래유형,
            count(*) as 건수
        FROM hofinet
        {where}
        GROUP BY 거래시간대, 이상거래유형
        ORDER BY 거래시간대, 이상거래유형
    """)


# ------------------------------------------------------------------
# FR-006: 이상거래유형별 월별 추이
# ------------------------------------------------------------------

@st.cache_data(ttl=300, hash_funcs=_CACHE_HASH_FUNCS, show_spinner=False)
def get_fraud_type_monthly_trend(filters: dict | None = None) -> pd.DataFrame:
    """이상거래유형별 월별 건수 추이를 반환한다."""
    where = _apply_filters("WHERE 이상거래여부 = 1", filters)
    return query(f"""
        SELECT
            CAST(거래일자 / 100 AS INT) as 연월,
            이상거래유형,
            이상거래설명,
            count(*) as 건수
        FROM hofinet
        {where}
        GROUP BY 연월, 이상거래유형, 이상거래설명
        ORDER BY 연월, 이상거래유형
    """)


# ------------------------------------------------------------------
# 필터 UI 지원 쿼리 (페이지 레이어 전용)
# ------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_bank_options() -> list:
    """출금 금융회사 코드 목록을 반환한다 (필터 UI 드롭다운용)."""
    try:
        result = query(
            "SELECT DISTINCT 출금금융회사일련번호 FROM hofinet ORDER BY 출금금융회사일련번호"
        )
        return result["출금금융회사일련번호"].tolist()
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def get_fraud_type_options() -> pd.DataFrame:
    """이상거래유형 코드+설명 목록을 반환한다 (필터 UI 드롭다운용)."""
    try:
        return query("""
            SELECT DISTINCT 이상거래유형, 이상거래설명
            FROM hofinet WHERE 이상거래여부 = 1
            ORDER BY 이상거래유형
        """)
    except Exception:
        return pd.DataFrame(columns=["이상거래유형", "이상거래설명"])


# ------------------------------------------------------------------
# 에이전트 도구: 시계열 트렌드 분석
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_trend_analysis(unit: str = "monthly",
                       metric: str = "transactions",
                       date_from: int | None = None,
                       date_to: int | None = None) -> pd.DataFrame:
    """시계열 트렌드 분석을 반환한다.

    Args:
        unit: 'monthly' 또는 'quarterly'
        metric: 'transactions'(거래건수), 'fraud_rate'(이상거래비율), 'amount'(거래금액)
        date_from: 시작일 (YYYYMMDD)
        date_to: 종료일 (YYYYMMDD)

    Returns:
        기간별 지표와 전기 대비 변화율을 포함한 DataFrame
    """
    conditions = []
    if date_from is not None:
        conditions.append(f"거래일자 >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"거래일자 <= {int(date_to)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    if unit == "quarterly":
        period_expr = (
            "CAST(거래일자 / 10000 AS INT) * 10 + "
            "CASE WHEN (거래일자 / 100 % 100) <= 3 THEN 1 "
            "WHEN (거래일자 / 100 % 100) <= 6 THEN 2 "
            "WHEN (거래일자 / 100 % 100) <= 9 THEN 3 "
            "ELSE 4 END"
        )
    else:
        period_expr = "CAST(거래일자 / 100 AS INT)"

    return query(f"""
        SELECT
            {period_expr} AS 기간,
            COUNT(*) AS 거래건수,
            SUM(이상거래여부) AS 이상거래건수,
            ROUND(SUM(이상거래여부) * 100.0 / COUNT(*), 4) AS 이상거래비율,
            SUM(거래금액) AS 총거래금액,
            ROUND(AVG(거래금액), 0) AS 평균거래금액
        FROM hofinet
        {where}
        GROUP BY 기간
        ORDER BY 기간
    """)


# ------------------------------------------------------------------
# 에이전트 도구: 채널별 위험도 분석
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def analyze_channel_risk(date_from: int | None = None,
                         date_to: int | None = None) -> dict:
    """채널(매체구분)별 위험도 분석 결과를 반환한다.

    Returns:
        dict with 'channel_stats' (채널별 통계), 'channel_time_cross' (채널×시간대 교차분석)
    """
    conditions = []
    if date_from is not None:
        conditions.append(f"거래일자 >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"거래일자 <= {int(date_to)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # 채널별 기본 통계
    channel_df = query(f"""
        SELECT
            매체구분,
            COUNT(*) AS 총거래건수,
            SUM(이상거래여부) AS 이상거래건수,
            ROUND(SUM(이상거래여부) * 100.0 / COUNT(*), 4) AS 이상거래비율,
            SUM(거래금액) AS 총거래금액,
            ROUND(AVG(거래금액), 0) AS 평균거래금액
        FROM hofinet
        {where}
        GROUP BY 매체구분
        ORDER BY 이상거래비율 DESC
    """)

    # 채널 × 시간대 교차분석
    cross_df = query(f"""
        SELECT
            매체구분, 거래시간대,
            COUNT(*) AS 거래건수,
            SUM(이상거래여부) AS 이상거래건수,
            ROUND(SUM(이상거래여부) * 100.0 / COUNT(*), 4) AS 이상거래비율
        FROM hofinet
        {where}
        GROUP BY 매체구분, 거래시간대
        ORDER BY 매체구분, 거래시간대
    """)

    channel_stats = channel_df.to_dict(orient="records") if not channel_df.empty else []
    cross_stats = cross_df.to_dict(orient="records") if not cross_df.empty else []

    return {
        "channel_stats": channel_stats,
        "channel_time_cross": cross_stats,
    }


# ------------------------------------------------------------------
# 에이전트 도구: 입금계좌 프로파일링
# ------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_receiving_account_profile(account_id: int) -> dict:
    """입금(수취) 관점에서 계좌를 프로파일링한다.

    기존 get_account_profile은 출금계좌 기준이지만,
    이 함수는 입금계좌일련번호 기준으로 자금 유입 패턴을 분석한다.
    """
    aid = int(account_id)

    # 기본 집계 (입금 방향)
    agg_df = query(
        "SELECT COUNT(*) AS cnt, SUM(거래금액) AS total_amount, "
        "SUM(이상거래여부) AS fraud_cnt "
        "FROM hofinet WHERE 입금계좌일련번호 = $aid",
        {"aid": aid},
    )

    if agg_df is None or agg_df.empty or int(agg_df.iloc[0]["cnt"] or 0) == 0:
        return {"account_id": aid, "방향": "입금", "총거래건수": 0, "안내": "해당 입금계좌의 거래 내역이 없습니다."}

    row = agg_df.iloc[0]
    total_count = int(row["cnt"] or 0)
    total_amount = int(row["total_amount"] or 0)
    fraud_count = int(row["fraud_cnt"] or 0)

    # 상위 출금 계좌 (자금 유입 원천)
    sender_df = query(
        "SELECT 출금계좌일련번호 AS sender_id, "
        "COUNT(*) AS tx_count, SUM(거래금액) AS total_amount "
        "FROM hofinet WHERE 입금계좌일련번호 = $aid "
        "GROUP BY 출금계좌일련번호 ORDER BY tx_count DESC LIMIT 5",
        {"aid": aid},
    )
    top_senders = sender_df.to_dict(orient="records") if not sender_df.empty else []

    # 출금 기관별 분포
    bank_df = query(
        "SELECT 출금금융회사일련번호 AS bank_id, COUNT(*) AS tx_count "
        "FROM hofinet WHERE 입금계좌일련번호 = $aid "
        "GROUP BY 출금금융회사일련번호 ORDER BY tx_count DESC LIMIT 5",
        {"aid": aid},
    )
    top_sender_banks = bank_df.to_dict(orient="records") if not bank_df.empty else []

    # 시간대별 분포
    hour_df = query(
        "SELECT 거래시간대, COUNT(*) AS cnt FROM hofinet "
        "WHERE 입금계좌일련번호 = $aid "
        "GROUP BY 거래시간대 ORDER BY cnt DESC LIMIT 3",
        {"aid": aid},
    )
    top_hours = hour_df["거래시간대"].tolist() if not hour_df.empty else []

    return {
        "account_id": aid,
        "방향": "입금",
        "총거래건수": total_count,
        "총거래금액": total_amount,
        "이상거래건수": fraud_count,
        "이상거래비율": round(fraud_count / total_count, 4) if total_count > 0 else 0.0,
        "고유출금계좌수": int(sender_df["sender_id"].nunique()) if not sender_df.empty else 0,
        "주요시간대": top_hours,
        "상위출금계좌": top_senders,
        "상위출금기관": top_sender_banks,
    }


# ------------------------------------------------------------------
# 필터 UI 지원
# ------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_date_range() -> tuple[int, int]:
    """데이터의 최소·최대 거래일자를 (min_date, max_date) 튜플로 반환한다 (필터 UI용)."""
    try:
        row = query(
            "SELECT min(거래일자) as min_date, max(거래일자) as max_date FROM hofinet"
        ).iloc[0]
        return int(row["min_date"]), int(row["max_date"])
    except Exception:
        return 20210901, 20241231
