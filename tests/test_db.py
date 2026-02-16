"""src/data/db.py 기능 테스트.

검증 항목:
- DuckDB 연결 싱글턴 패턴이 정상 동작하는지
- SQL 쿼리가 DataFrame/Arrow Table을 올바르게 반환하는지
- 테이블 hofinet이 생성되어 있는지
- 집계 쿼리(COUNT, SUM, DISTINCT)가 정상 동작하는지
- 파라미터 바인딩 쿼리가 동작하는지
"""

import pandas as pd
import pyarrow as pa

from src.data import db


class TestConnection:
    """DuckDB 연결 테스트."""

    def test_get_connection_returns_connection(self):
        """get_connection이 유효한 연결 객체를 반환하는지 확인."""
        conn = db.get_connection()
        assert conn is not None

    def test_singleton_pattern(self):
        """동일한 연결 객체가 반환되는지 확인 (싱글턴)."""
        conn1 = db.get_connection()
        conn2 = db.get_connection()
        assert conn1 is conn2

    def test_hofinet_table_exists(self):
        """hofinet 테이블이 존재하는지 확인."""
        conn = db.get_connection()
        tables = conn.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]
        assert "hofinet" in table_names


class TestQuery:
    """query() 함수 테스트."""

    def test_query_returns_dataframe(self):
        """query()가 pandas DataFrame을 반환하는지 확인."""
        result = db.query("SELECT 1 as val")
        assert isinstance(result, pd.DataFrame)

    def test_query_count(self):
        """전체 레코드 수 조회가 정상 동작하는지 확인."""
        result = db.query("SELECT count(*) as cnt FROM hofinet")
        count = result["cnt"].iloc[0]
        assert count == 4_732_130

    def test_query_fraud_count(self):
        """이상거래 건수 집계가 정상 동작하는지 확인."""
        result = db.query(
            "SELECT count(*) as cnt FROM hofinet WHERE 이상거래여부 = 1"
        )
        fraud_count = result["cnt"].iloc[0]
        assert fraud_count > 0
        assert fraud_count < 100_000  # 약 14,490건 예상

    def test_query_distinct_accounts(self):
        """DISTINCT 출금계좌 수 조회가 정상 동작하는지 확인."""
        result = db.query(
            "SELECT count(DISTINCT 출금계좌일련번호) as cnt FROM hofinet"
        )
        account_count = result["cnt"].iloc[0]
        assert account_count > 0

    def test_query_with_params(self):
        """파라미터 바인딩 쿼리가 동작하는지 확인."""
        result = db.query(
            "SELECT count(*) as cnt FROM hofinet WHERE 이상거래여부 = ?",
            [1],
        )
        assert isinstance(result, pd.DataFrame)
        assert result["cnt"].iloc[0] > 0

    def test_query_aggregation(self):
        """복합 집계 쿼리(app.py에서 사용하는 쿼리)가 동작하는지 확인."""
        result = db.query("""
            SELECT
                count(*) as total,
                sum(이상거래여부) as fraud,
                count(DISTINCT 출금계좌일련번호) as accounts,
                count(DISTINCT 출금금융회사일련번호)
                    + count(DISTINCT 입금금융회사일련번호) as banks
            FROM hofinet
        """)
        assert result["total"].iloc[0] > 0
        assert result["fraud"].iloc[0] > 0
        assert result["accounts"].iloc[0] > 0
        assert result["banks"].iloc[0] > 0

    def test_query_group_by(self):
        """GROUP BY 쿼리가 정상 동작하는지 확인."""
        result = db.query("""
            SELECT 이상거래여부, count(*) as cnt
            FROM hofinet
            GROUP BY 이상거래여부
            ORDER BY 이상거래여부
        """)
        assert len(result) == 2  # 0과 1
        assert result["이상거래여부"].tolist() == [0, 1]

    def test_query_limit(self):
        """LIMIT 쿼리가 정상 동작하는지 확인."""
        result = db.query("SELECT * FROM hofinet LIMIT 10")
        assert len(result) == 10
        assert len(result.columns) == 12


class TestQueryArrow:
    """query_arrow() 함수 테스트."""

    def test_query_arrow_returns_arrow_table(self):
        """query_arrow()가 PyArrow Table을 반환하는지 확인."""
        result = db.query_arrow("SELECT * FROM hofinet LIMIT 5")
        assert isinstance(result, pa.Table)

    def test_query_arrow_count(self):
        """Arrow 쿼리로 레코드 수 조회가 정상 동작하는지 확인."""
        result = db.query_arrow("SELECT count(*) as cnt FROM hofinet")
        count = result.column("cnt")[0].as_py()
        assert count == 4_732_130

    def test_query_arrow_with_params(self):
        """Arrow 쿼리에서 파라미터 바인딩이 동작하는지 확인."""
        result = db.query_arrow(
            "SELECT count(*) as cnt FROM hofinet WHERE 이상거래여부 = ?",
            [0],
        )
        assert isinstance(result, pa.Table)
        count = result.column("cnt")[0].as_py()
        assert count > 0


class TestFraudAnalysis:
    """이상거래 분석 쿼리 테스트."""

    def test_fraud_types_exist(self):
        """이상거래유형이 복수 종류 존재하는지 확인."""
        result = db.query("""
            SELECT DISTINCT 이상거래유형
            FROM hofinet
            WHERE 이상거래여부 = 1
            ORDER BY 이상거래유형
        """)
        assert len(result) >= 2  # 최소 2종류 이상

    def test_fraud_descriptions_exist(self):
        """이상거래설명이 채워져 있는지 확인."""
        result = db.query("""
            SELECT DISTINCT 이상거래설명
            FROM hofinet
            WHERE 이상거래여부 = 1
            ORDER BY 이상거래설명
        """)
        assert len(result) >= 2
        # 설명이 빈 문자열이 아닌지 확인
        for desc in result["이상거래설명"].tolist():
            assert desc is not None and len(desc) > 0

    def test_transaction_amount_statistics(self):
        """거래금액 통계(최소, 최대, 평균)가 합리적인지 확인."""
        result = db.query("""
            SELECT
                min(거래금액) as min_amt,
                max(거래금액) as max_amt,
                avg(거래금액) as avg_amt
            FROM hofinet
        """)
        min_amt = result["min_amt"].iloc[0]
        max_amt = result["max_amt"].iloc[0]
        avg_amt = result["avg_amt"].iloc[0]
        assert min_amt > 0
        assert max_amt > min_amt
        assert avg_amt > 0

    def test_quarterly_data_coverage(self):
        """데이터가 여러 분기에 걸쳐 있는지 확인."""
        result = db.query("""
            SELECT
                min(거래일자) as min_date,
                max(거래일자) as max_date,
                count(DISTINCT 거래일자) as distinct_dates
            FROM hofinet
        """)
        distinct_dates = result["distinct_dates"].iloc[0]
        assert distinct_dates > 100  # 최소 100일 이상

    def test_financial_institutions_count(self):
        """금융회사 수가 합리적인지 확인."""
        result = db.query("""
            SELECT
                count(DISTINCT 출금금융회사일련번호) as withdraw_banks,
                count(DISTINCT 입금금융회사일련번호) as deposit_banks
            FROM hofinet
        """)
        assert result["withdraw_banks"].iloc[0] >= 10
        assert result["deposit_banks"].iloc[0] >= 10
