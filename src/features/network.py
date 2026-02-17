"""기능2: 네트워크(그래프) 분석 쿼리 및 그래프 생성 모듈."""

import networkx as nx
from src.data.db import query


def get_bank_network():
    """금융회사 간 거래 네트워크 데이터를 반환한다."""
    return query("""
        SELECT
            출금금융회사일련번호 as source,
            입금금융회사일련번호 as target,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            sum(거래금액) as 총금액
        FROM hofinet
        GROUP BY source, target
        ORDER BY 총거래 DESC
    """)


def get_fraud_account_network(limit=500):
    """이상거래 관련 계좌 간 네트워크 데이터를 반환한다."""
    # limit은 외부 입력이므로 int 형변환으로 안전하게 처리 (DuckDB는 LIMIT 파라미터 바인딩 미지원)
    limit = int(limit)
    return query(f"""
        SELECT
            출금계좌일련번호 as source,
            입금계좌일련번호 as target,
            count(*) as 거래횟수,
            sum(거래금액) as 총금액,
            max(이상거래유형) as 이상거래유형,
            max(이상거래설명) as 이상거래설명
        FROM hofinet
        WHERE 이상거래여부 = 1
        GROUP BY source, target
        ORDER BY 거래횟수 DESC
        LIMIT {limit}
    """)


def get_account_ego_network(account_id, hops=1):
    """특정 계좌의 ego 네트워크(n-hop 이웃)를 반환한다."""
    # account_id는 int64 계좌 번호이므로 int 형변환으로 SQL 인젝션 방지
    account_id = int(account_id)
    if hops == 1:
        return query(
            """
            SELECT
                출금계좌일련번호 as source,
                입금계좌일련번호 as target,
                count(*) as 거래횟수,
                sum(거래금액) as 총금액,
                max(이상거래여부) as 이상거래여부
            FROM hofinet
            WHERE 출금계좌일련번호 = ?
               OR 입금계좌일련번호 = ?
            GROUP BY source, target
            """,
            [account_id, account_id],
        )
    # 2-hop: 1-hop 이웃의 거래까지 포함
    # DuckDB CTE에서는 파라미터가 여러 번 참조되므로 int 변수를 f-string으로 안전하게 삽입
    return query(f"""
        WITH hop1 AS (
            SELECT DISTINCT
                CASE WHEN 출금계좌일련번호 = {account_id}
                     THEN 입금계좌일련번호 ELSE 출금계좌일련번호 END as neighbor
            FROM hofinet
            WHERE 출금계좌일련번호 = {account_id}
               OR 입금계좌일련번호 = {account_id}
        )
        SELECT
            출금계좌일련번호 as source,
            입금계좌일련번호 as target,
            count(*) as 거래횟수,
            sum(거래금액) as 총금액,
            max(이상거래여부) as 이상거래여부
        FROM hofinet
        WHERE 출금계좌일련번호 = {account_id}
           OR 입금계좌일련번호 = {account_id}
           OR 출금계좌일련번호 IN (SELECT neighbor FROM hop1)
           OR 입금계좌일련번호 IN (SELECT neighbor FROM hop1)
        GROUP BY source, target
    """)


def get_fraud_accounts():
    """이상거래에 관련된 출금 계좌 목록을 반환한다."""
    return query("""
        SELECT DISTINCT 출금계좌일련번호 as 계좌
        FROM hofinet
        WHERE 이상거래여부 = 1
        ORDER BY 계좌
    """)


def get_bank_network_stats():
    """금융회사 네트워크 요약 통계를 반환한다."""
    return query("""
        SELECT
            count(DISTINCT 출금금융회사일련번호) as 출금금융회사수,
            count(DISTINCT 입금금융회사일련번호) as 입금금융회사수,
            count(DISTINCT (CAST(출금금융회사일련번호 AS INT) * 1000 + CAST(입금금융회사일련번호 AS INT))) as 연결수
        FROM hofinet
    """)


def build_bank_graph(df):
    """DataFrame으로부터 금융회사 간 네트워크 그래프를 생성한다."""
    G = nx.DiGraph()
    for _, row in df.iterrows():
        G.add_edge(
            str(int(row["source"])),
            str(int(row["target"])),
            weight=int(row["총거래"]),
            fraud=int(row["이상거래"]),
            amount=float(row["총금액"]),
        )
    return G


def build_account_graph(df):
    """DataFrame으로부터 계좌 간 네트워크 그래프를 생성한다."""
    G = nx.DiGraph()
    for _, row in df.iterrows():
        G.add_edge(
            str(int(row["source"])),
            str(int(row["target"])),
            weight=int(row["거래횟수"]),
            amount=float(row["총금액"]),
        )
    return G
