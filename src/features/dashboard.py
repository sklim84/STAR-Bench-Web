"""기능1: 기본 분석 대시보드 쿼리 모듈."""

import pandas as pd
from src.data.db import query


# ------------------------------------------------------------------
# 글로벌 필터 헬퍼
# ------------------------------------------------------------------

def _build_filter_conditions(filters):
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


def _apply_filters(base_where, filters):
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


def get_summary(filters=None):
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


def get_quarterly_trend(filters=None):
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


def get_hourly_distribution(filters=None):
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


def get_amount_distribution(filters=None):
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


def get_fraud_type_distribution(filters=None):
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


def get_monthly_trend(filters=None):
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


def get_medium_distribution(filters=None):
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


def get_top_banks(filters=None):
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

def get_fund_type_distribution(filters=None):
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

def get_fraud_amount_summary(filters=None):
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


def get_fraud_amount_by_type(filters=None):
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

def get_hourly_fraud_type_heatmap(filters=None):
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

def get_fraud_type_monthly_trend(filters=None):
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

def get_bank_options() -> list:
    """출금 금융회사 코드 목록을 반환한다 (필터 UI 드롭다운용)."""
    try:
        result = query(
            "SELECT DISTINCT 출금금융회사일련번호 FROM hofinet ORDER BY 출금금융회사일련번호"
        )
        return result["출금금융회사일련번호"].tolist()
    except Exception:
        return []


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


def get_date_range() -> tuple[int, int]:
    """데이터의 최소·최대 거래일자를 (min_date, max_date) 튜플로 반환한다 (필터 UI용)."""
    try:
        row = query(
            "SELECT min(거래일자) as min_date, max(거래일자) as max_date FROM hofinet"
        ).iloc[0]
        return int(row["min_date"]), int(row["max_date"])
    except Exception:
        return 20210901, 20241231
