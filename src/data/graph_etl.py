"""DuckDB -> Memgraph 데이터 적재(ETL) 모듈.

HOFINET 테이블의 거래 데이터를 Memgraph 그래프 모델로 변환한다.
노드: Account(계좌), Company(금융회사)
엣지: TRANSFER(거래), BELONGS_TO(소속)

그래프 모델:
    (:Company {id})
    (:Account {id, company_id})
    (:Account)-[:BELONGS_TO]->(:Company)
    (:Account)-[:TRANSFER {
        거래일자, 거래시간대, 자금구분, 매체구분, 거래금액, 이상거래여부, 이상거래유형
    }]->(:Account)
"""

import logging
import time

import pandas as pd

from src.data import db
from src.data import graph_db

logger = logging.getLogger(__name__)


def run_etl(batch_size: int = 10000) -> dict:
    """전체 ETL을 실행한다.

    DuckDB에서 HOFINET 데이터를 읽어 Memgraph 그래프로 적재한다.
    이미 데이터가 있으면(노드 > 0) 스킵하고 기존 카운트를 반환한다.
    Memgraph 미실행 시 에러 정보를 담은 dict를 반환한다.

    Args:
        batch_size: 배치 삽입 단위 (기본 10000)

    Returns:
        dict: {
            "accounts": 계좌 노드 수,
            "companies": 금융회사 노드 수,
            "transfers": 거래 엣지 수,
            "elapsed_sec": 소요 시간(초)
        }
        Memgraph 미실행 시: {"error": "Memgraph 미실행"}
    """
    if not graph_db.is_available():
        logger.warning("Memgraph 미실행 상태로 ETL을 건너뜁니다")
        return {"error": "Memgraph 미실행"}

    # 이미 데이터가 있는지 확인
    stats = get_graph_stats()
    if stats.get("accounts", 0) > 0:
        logger.info(
            "기존 그래프 데이터 존재 (accounts=%d, transfers=%d). ETL 스킵.",
            stats["accounts"],
            stats["transfers"],
        )
        stats["elapsed_sec"] = 0.0
        return stats

    start = time.time()
    logger.info("ETL 시작: DuckDB -> Memgraph")

    # 1. 인덱스 생성
    _create_indexes()

    # 2. 금융회사 노드 적재
    company_count = _load_companies()
    logger.info("금융회사 노드 적재 완료: %d개", company_count)

    # 3. 계좌 노드 적재 + BELONGS_TO 관계
    account_count = _load_accounts(batch_size)
    logger.info("계좌 노드 적재 완료: %d개", account_count)

    # 4. 거래 엣지 적재
    transfer_count = _load_transfers(batch_size)
    logger.info("거래 엣지 적재 완료: %d개", transfer_count)

    elapsed = time.time() - start
    logger.info("ETL 완료: %.1f초 소요", elapsed)

    return {
        "accounts": account_count,
        "companies": company_count,
        "transfers": transfer_count,
        "elapsed_sec": round(elapsed, 1),
    }


def _create_indexes():
    """Memgraph 인덱스를 생성한다.

    MERGE 성능 향상을 위해 노드 생성 전에 인덱스를 먼저 생성한다.
    이미 존재하는 인덱스는 무시된다.
    """
    index_queries = [
        "CREATE INDEX ON :Account(id)",
        "CREATE INDEX ON :Company(id)",
    ]
    for q in index_queries:
        try:
            graph_db.execute(q)
        except Exception:  # noqa: BLE001
            # 이미 존재하는 인덱스는 무시
            pass
    logger.info("인덱스 생성 완료")


def _load_companies() -> int:
    """고유 금융회사 노드를 생성한다.

    DuckDB에서 출금/입금 금융회사 ID를 합쳐 고유값을 추출한 후
    Memgraph에 Company 노드로 생성한다.

    Returns:
        int: 생성된 금융회사 노드 수
    """
    df = db.query("""
        SELECT DISTINCT company_id FROM (
            SELECT DISTINCT 출금금융회사일련번호 AS company_id FROM hofinet
            UNION
            SELECT DISTINCT 입금금융회사일련번호 AS company_id FROM hofinet
        )
        ORDER BY company_id
    """)

    if df.empty:
        return 0

    batch = [{"id": int(row["company_id"])} for _, row in df.iterrows()]
    graph_db.execute(
        "UNWIND $batch AS row MERGE (:Company {id: row.id})",
        {"batch": batch},
    )
    return len(batch)


def _load_accounts(batch_size: int) -> int:
    """고유 계좌 노드를 생성하고 BELONGS_TO 관계를 만든다.

    DuckDB에서 계좌-금융회사 매핑을 추출한 후
    Memgraph에 Account 노드와 BELONGS_TO 엣지를 생성한다.

    Args:
        batch_size: 배치 삽입 단위

    Returns:
        int: 생성된 계좌 노드 수
    """
    df = db.query("""
        SELECT DISTINCT account_id, company_id FROM (
            SELECT DISTINCT
                출금계좌일련번호 AS account_id,
                출금금융회사일련번호 AS company_id
            FROM hofinet
            UNION
            SELECT DISTINCT
                입금계좌일련번호 AS account_id,
                입금금융회사일련번호 AS company_id
            FROM hofinet
        )
        ORDER BY account_id
    """)

    if df.empty:
        return 0

    total = len(df)
    loaded = 0

    for i in range(0, total, batch_size):
        chunk = df.iloc[i : i + batch_size]
        batch = [
            {"id": int(row["account_id"]), "company_id": int(row["company_id"])}
            for _, row in chunk.iterrows()
        ]
        graph_db.execute(
            """
            UNWIND $batch AS row
            MERGE (a:Account {id: row.id})
            ON CREATE SET a.company_id = row.company_id
            WITH a, row
            MATCH (c:Company {id: row.company_id})
            MERGE (a)-[:BELONGS_TO]->(c)
            """,
            {"batch": batch},
        )
        loaded += len(batch)
        if (i // batch_size + 1) % 10 == 0 or loaded >= total:
            logger.info("계좌 노드 적재 진행률: %d / %d", loaded, total)

    return total


def _load_transfers(batch_size: int) -> int:
    """거래 엣지를 배치 단위로 생성한다.

    DuckDB에서 전체 거래 데이터를 배치 단위로 읽어
    Memgraph에 TRANSFER 관계로 삽입한다.

    Args:
        batch_size: 배치 삽입 단위

    Returns:
        int: 생성된 거래 엣지 수
    """
    # 전체 건수 조회
    count_df = db.query("SELECT count(*) AS cnt FROM hofinet")
    total = int(count_df["cnt"].iloc[0])

    if total == 0:
        return 0

    loaded = 0
    num_batches = (total + batch_size - 1) // batch_size

    for batch_idx in range(num_batches):
        offset = batch_idx * batch_size
        df = db.query(f"""
            SELECT
                출금계좌일련번호 AS source,
                입금계좌일련번호 AS target,
                거래일자,
                거래시간대,
                자금구분,
                매체구분,
                거래금액,
                이상거래여부,
                이상거래유형
            FROM hofinet
            LIMIT {batch_size} OFFSET {offset}
        """)

        if df.empty:
            break

        batch = _df_to_transfer_batch(df)
        graph_db.execute(
            """
            UNWIND $batch AS row
            MATCH (a:Account {id: row.source})
            MATCH (b:Account {id: row.target})
            CREATE (a)-[:TRANSFER {
                거래일자: row.거래일자,
                거래시간대: row.거래시간대,
                자금구분: row.자금구분,
                매체구분: row.매체구분,
                거래금액: row.거래금액,
                이상거래여부: row.이상거래여부,
                이상거래유형: row.이상거래유형
            }]->(b)
            """,
            {"batch": batch},
        )
        loaded += len(batch)
        if (batch_idx + 1) % 50 == 0 or (batch_idx + 1) == num_batches:
            logger.info(
                "거래 엣지 적재 진행률: %d / %d (배치 %d/%d)",
                loaded,
                total,
                batch_idx + 1,
                num_batches,
            )

    return loaded


def _df_to_transfer_batch(df: pd.DataFrame) -> list:
    """DataFrame을 TRANSFER 엣지 배치용 딕셔너리 리스트로 변환한다.

    NaN 값을 적절히 처리하고, int64 값을 Python int로 변환한다.

    Args:
        df: 거래 데이터 DataFrame

    Returns:
        list[dict]: Cypher UNWIND용 딕셔너리 리스트
    """
    records = []
    for _, row in df.iterrows():
        records.append({
            "source": int(row["source"]),
            "target": int(row["target"]),
            "거래일자": int(row["거래일자"]),
            "거래시간대": int(row["거래시간대"]),
            "자금구분": int(row["자금구분"]),
            "매체구분": int(row["매체구분"]),
            "거래금액": int(row["거래금액"]),
            "이상거래여부": int(row["이상거래여부"]),
            "이상거래유형": int(row["이상거래유형"]) if pd.notna(row["이상거래유형"]) else 0,
        })
    return records


def clear_graph():
    """전체 그래프를 삭제한다 (개발/테스트용).

    모든 노드와 엣지를 삭제한다.
    Memgraph 미실행 시 아무 작업도 하지 않는다.
    """
    if not graph_db.is_available():
        logger.warning("Memgraph 미실행 상태로 그래프 삭제를 건너뜁니다")
        return

    graph_db.execute("MATCH (n) DETACH DELETE n")
    logger.info("전체 그래프 삭제 완료")


def get_graph_stats() -> dict:
    """현재 그래프의 노드/엣지 카운트를 반환한다.

    Returns:
        dict: {
            "accounts": Account 노드 수,
            "companies": Company 노드 수,
            "transfers": TRANSFER 엣지 수,
            "belongs_to": BELONGS_TO 엣지 수
        }
        Memgraph 미실행 시 모든 값이 0인 dict 반환.
    """
    empty_stats = {
        "accounts": 0,
        "companies": 0,
        "transfers": 0,
        "belongs_to": 0,
    }

    if not graph_db.is_available():
        return empty_stats

    records = graph_db.execute("""
        MATCH (a:Account) WITH count(a) AS accounts
        MATCH (c:Company) WITH accounts, count(c) AS companies
        OPTIONAL MATCH ()-[t:TRANSFER]->() WITH accounts, companies, count(t) AS transfers
        OPTIONAL MATCH ()-[b:BELONGS_TO]->() WITH accounts, companies, transfers, count(b) AS belongs_to
        RETURN accounts, companies, transfers, belongs_to
    """)

    if not records:
        return empty_stats

    rec = records[0]
    return {
        "accounts": rec.get("accounts", 0),
        "companies": rec.get("companies", 0),
        "transfers": rec.get("transfers", 0),
        "belongs_to": rec.get("belongs_to", 0),
    }
