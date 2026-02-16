"""기능1: 기본 분석 대시보드 쿼리 모듈."""

from src.data.db import query


def get_summary():
    """전체 요약 지표를 반환한다."""
    return query("""
        SELECT
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율,
            count(DISTINCT 출금계좌일련번호) as 출금계좌수,
            count(DISTINCT 입금계좌일련번호) as 입금계좌수,
            sum(거래금액) as 총거래금액
        FROM hofinet
    """)


def get_quarterly_trend():
    """분기별 거래 건수 및 이상거래 추이를 반환한다."""
    return query("""
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
        GROUP BY 연도, 분기
        ORDER BY 연도, 분기
    """)


def get_hourly_distribution():
    """시간대별 거래 분포를 반환한다."""
    return query("""
        SELECT
            거래시간대,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        GROUP BY 거래시간대
        ORDER BY 거래시간대
    """)


def get_amount_distribution():
    """거래금액 구간별 분포를 반환한다."""
    return query("""
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
        GROUP BY 금액구간, 순서
        ORDER BY 순서
    """)


def get_fraud_type_distribution():
    """이상거래유형별 분포를 반환한다."""
    return query("""
        SELECT
            이상거래유형,
            이상거래설명,
            count(*) as 건수
        FROM hofinet
        WHERE 이상거래여부 = 1
        GROUP BY 이상거래유형, 이상거래설명
        ORDER BY 이상거래유형
    """)


def get_monthly_trend():
    """월별 거래 건수 및 이상거래 추이를 반환한다."""
    return query("""
        SELECT
            CAST(거래일자 / 100 AS INT) as 연월,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        GROUP BY 연월
        ORDER BY 연월
    """)


def get_medium_distribution():
    """매체구분별 거래 분포를 반환한다."""
    return query("""
        SELECT
            매체구분,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
        GROUP BY 매체구분
        ORDER BY 매체구분
    """)


def get_top_banks():
    """금융회사별 이상거래 건수 상위를 반환한다."""
    return query("""
        SELECT
            출금금융회사일련번호 as 금융회사,
            '출금' as 구분,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            round(sum(이상거래여부) * 100.0 / count(*), 4) as 이상거래비율
        FROM hofinet
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
        GROUP BY 입금금융회사일련번호
        HAVING sum(이상거래여부) > 0
        ORDER BY 이상거래 DESC
    """)
