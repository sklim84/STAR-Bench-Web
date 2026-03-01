"""기능7: 거래 모니터링 규칙 탐지 모듈.

5개 명명 규칙 실행 및 알림 생성.
근거: 실무5편 — 규칙 기반 모니터링, 의심거래 지표.
"""

import pandas as pd
from src.data.db import query


# ------------------------------------------------------------------
# R001: 심야 대량 거래
# ------------------------------------------------------------------

def detect_nighttime_bulk(date_from: int | None = None,
                          date_to: int | None = None,
                          min_amount: int = 10_000_000,
                          limit: int = 100) -> pd.DataFrame:
    """R001: 심야시간대(0, 3) 대량 거래를 탐지한다."""
    min_amount = int(min_amount)
    limit = int(limit)
    conditions = ["거래시간대 IN (0, 3)", f"거래금액 >= {min_amount}"]
    if date_from is not None:
        conditions.append(f"거래일자 >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"거래일자 <= {int(date_to)}")
    where = "WHERE " + " AND ".join(conditions)
    return query(f"""
        SELECT 거래일자, 거래시간대, 출금계좌일련번호, 입금계좌일련번호,
               출금금융회사일련번호, 입금금융회사일련번호, 거래금액,
               이상거래여부, 이상거래유형
        FROM hofinet
        {where}
        ORDER BY 거래금액 DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R002: 동일일 다건 거래 (Rapid-fire)
# ------------------------------------------------------------------

def detect_rapid_fire(date_from: int | None = None,
                      date_to: int | None = None,
                      min_count: int = 10,
                      limit: int = 100) -> pd.DataFrame:
    """R002: 동일 계좌가 동일일에 min_count건 이상 거래한 경우를 탐지한다."""
    min_count = int(min_count)
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
               SUM(이상거래여부) AS 이상거래건수
        FROM hofinet
        {where}
        GROUP BY 출금계좌일련번호, 거래일자
        HAVING COUNT(*) >= {min_count}
        ORDER BY 거래건수 DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R003: 정액 거래 패턴 (Round amount)
# ------------------------------------------------------------------

def detect_round_amounts(date_from: int | None = None,
                         date_to: int | None = None,
                         round_unit: int = 1_000_000,
                         min_count: int = 3,
                         limit: int = 100) -> pd.DataFrame:
    """R003: 정액(round_unit 단위) 거래를 min_count건 이상 수행한 계좌를 탐지한다."""
    round_unit = int(round_unit)
    min_count = int(min_count)
    limit = int(limit)
    conditions = [f"거래금액 % {round_unit} = 0", f"거래금액 >= {round_unit}"]
    if date_from is not None:
        conditions.append(f"거래일자 >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"거래일자 <= {int(date_to)}")
    where = "WHERE " + " AND ".join(conditions)
    return query(f"""
        SELECT 출금계좌일련번호, COUNT(*) AS 정액거래건수,
               SUM(거래금액) AS 합산금액,
               COUNT(DISTINCT 거래금액) AS 금액종류수
        FROM hofinet
        {where}
        GROUP BY 출금계좌일련번호
        HAVING COUNT(*) >= {min_count}
        ORDER BY 정액거래건수 DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R004: 특정 기관 집중 거래
# ------------------------------------------------------------------

def detect_institution_concentration(min_ratio: float = 0.8,
                                     min_transactions: int = 10,
                                     limit: int = 100) -> pd.DataFrame:
    """R004: 특정 입금기관에 거래가 집중된 계좌를 탐지한다."""
    min_transactions = int(min_transactions)
    limit = int(limit)
    return query(f"""
        WITH account_bank AS (
            SELECT 출금계좌일련번호,
                   입금금융회사일련번호,
                   COUNT(*) AS bank_cnt
            FROM hofinet
            GROUP BY 출금계좌일련번호, 입금금융회사일련번호
        ),
        account_total AS (
            SELECT 출금계좌일련번호,
                   SUM(bank_cnt) AS total_cnt,
                   MAX(bank_cnt) AS max_bank_cnt
            FROM account_bank
            GROUP BY 출금계좌일련번호
            HAVING SUM(bank_cnt) >= {min_transactions}
        )
        SELECT
            t.출금계좌일련번호,
            t.total_cnt AS 총거래건수,
            t.max_bank_cnt AS 최다기관거래건수,
            ROUND(t.max_bank_cnt * 1.0 / t.total_cnt, 4) AS 집중비율,
            b.입금금융회사일련번호 AS 집중기관
        FROM account_total t
        JOIN account_bank b
          ON t.출금계좌일련번호 = b.출금계좌일련번호
         AND t.max_bank_cnt = b.bank_cnt
        WHERE t.max_bank_cnt * 1.0 / t.total_cnt >= {float(min_ratio)}
        ORDER BY 집중비율 DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# R005: 거래 패턴 급변
# ------------------------------------------------------------------

def detect_pattern_change(base_start: int, base_end: int,
                          compare_start: int, compare_end: int,
                          change_threshold: float = 3.0,
                          limit: int = 100) -> pd.DataFrame:
    """R005: 기준 기간 대비 비교 기간에 거래량이 급변한 계좌를 탐지한다."""
    base_start = int(base_start)
    base_end = int(base_end)
    compare_start = int(compare_start)
    compare_end = int(compare_end)
    limit = int(limit)
    return query(f"""
        WITH base AS (
            SELECT 출금계좌일련번호, COUNT(*) AS base_cnt, SUM(거래금액) AS base_amt
            FROM hofinet
            WHERE 거래일자 BETWEEN {base_start} AND {base_end}
            GROUP BY 출금계좌일련번호
            HAVING COUNT(*) >= 5
        ),
        compare AS (
            SELECT 출금계좌일련번호, COUNT(*) AS comp_cnt, SUM(거래금액) AS comp_amt
            FROM hofinet
            WHERE 거래일자 BETWEEN {compare_start} AND {compare_end}
            GROUP BY 출금계좌일련번호
        )
        SELECT
            b.출금계좌일련번호,
            b.base_cnt AS 기준기간건수,
            c.comp_cnt AS 비교기간건수,
            ROUND(c.comp_cnt * 1.0 / b.base_cnt, 2) AS 건수변화배율,
            b.base_amt AS 기준기간금액,
            c.comp_amt AS 비교기간금액,
            ROUND(c.comp_amt * 1.0 / b.base_amt, 2) AS 금액변화배율
        FROM base b
        JOIN compare c ON b.출금계좌일련번호 = c.출금계좌일련번호
        WHERE c.comp_cnt * 1.0 / b.base_cnt >= {float(change_threshold)}
           OR c.comp_amt * 1.0 / NULLIF(b.base_amt, 0) >= {float(change_threshold)}
        ORDER BY 건수변화배율 DESC
        LIMIT {limit}
    """)


# ------------------------------------------------------------------
# 전체 규칙 실행
# ------------------------------------------------------------------

def run_all_rules(date_from: int | None = None,
                  date_to: int | None = None) -> dict:
    """전체 규칙을 실행하고 종합 결과를 반환한다."""
    r001 = detect_nighttime_bulk(date_from, date_to, limit=50)
    r002 = detect_rapid_fire(date_from, date_to, limit=50)
    r003 = detect_round_amounts(date_from, date_to, limit=50)
    r004 = detect_institution_concentration(limit=50)
    r005_result = pd.DataFrame()
    if date_from and date_to:
        # 기준 기간 = 직전 동일 길이 기간
        span = int(date_to) - int(date_from)
        base_end = int(date_from) - 1
        base_start = base_end - span
        r005_result = detect_pattern_change(
            base_start, base_end, int(date_from), int(date_to), limit=50
        )

    return {
        "R001_심야대량거래": {"건수": len(r001), "상위": r001.head(10).to_dict(orient="records")},
        "R002_동일일다건거래": {"건수": len(r002), "상위": r002.head(10).to_dict(orient="records")},
        "R003_정액거래패턴": {"건수": len(r003), "상위": r003.head(10).to_dict(orient="records")},
        "R004_기관집중거래": {"건수": len(r004), "상위": r004.head(10).to_dict(orient="records")},
        "R005_거래패턴급변": {"건수": len(r005_result), "상위": r005_result.head(10).to_dict(orient="records")},
    }


# ------------------------------------------------------------------
# 모니터링 통계
# ------------------------------------------------------------------

def get_monitoring_summary(filters=None) -> dict:
    """모니터링 종합 통계를 반환한다."""
    conditions = []
    if filters:
        if filters.get("date_from"):
            conditions.append(f"거래일자 >= {int(filters['date_from'])}")
        if filters.get("date_to"):
            conditions.append(f"거래일자 <= {int(filters['date_to'])}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # 심야 거래 비율
    night_df = query(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN 거래시간대 IN (0, 3) THEN 1 ELSE 0 END) AS night_cnt
        FROM hofinet
        {where}
    """)

    # 고빈도 계좌 수
    rapid_df = query(f"""
        SELECT COUNT(*) AS cnt FROM (
            SELECT 출금계좌일련번호, 거래일자
            FROM hofinet
            {where}
            GROUP BY 출금계좌일련번호, 거래일자
            HAVING COUNT(*) >= 10
        ) sub
    """)

    night_row = night_df.iloc[0] if not night_df.empty else {}
    rapid_row = rapid_df.iloc[0] if not rapid_df.empty else {}

    total = int(night_row.get("total", 0) or 0)
    night = int(night_row.get("night_cnt", 0) or 0)

    return {
        "총거래건수": total,
        "심야거래건수": night,
        "심야거래비율": round(night / total * 100, 2) if total > 0 else 0.0,
        "고빈도거래일수": int(rapid_row.get("cnt", 0) or 0),
    }
