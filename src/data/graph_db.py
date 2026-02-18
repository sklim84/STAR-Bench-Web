"""Memgraph 그래프 데이터베이스 인터페이스.

Bolt 프로토콜(neo4j 드라이버)을 사용하여 Memgraph에 접속하며,
Cypher 쿼리를 실행한다. Memgraph 미실행 시 graceful하게 처리한다.
"""

import logging

import pandas as pd

import config

logger = logging.getLogger(__name__)

# neo4j 드라이버 import 실패 시에도 모듈 임포트는 성공해야 함
try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import (
        AuthError,
        ServiceUnavailable,
    )

    _NEO4J_AVAILABLE = True
except ImportError:
    _NEO4J_AVAILABLE = False
    logger.warning("neo4j 드라이버가 설치되지 않았습니다: pip install neo4j")

_driver = None


def get_driver():
    """Memgraph Bolt 드라이버를 반환한다 (싱글턴).

    Memgraph 미실행 또는 neo4j 미설치 시 None을 반환한다.
    예외를 발생시키지 않으므로 앱이 죽지 않는다.

    Returns:
        neo4j.Driver 또는 None
    """
    global _driver
    if _driver is not None:
        return _driver

    if not _NEO4J_AVAILABLE:
        logger.warning("neo4j 드라이버 미설치로 Memgraph 접속 불가")
        return None

    try:
        auth = None
        if config.MEMGRAPH_USER:
            auth = (config.MEMGRAPH_USER, config.MEMGRAPH_PASSWORD)

        _driver = GraphDatabase.driver(
            config.MEMGRAPH_URI,
            auth=auth,
        )
        # 실제 접속 테스트
        _driver.verify_connectivity()
        logger.info("Memgraph 접속 성공: %s", config.MEMGRAPH_URI)
        return _driver
    except (ServiceUnavailable, AuthError, OSError) as exc:
        logger.warning("Memgraph 접속 실패: %s", exc)
        _driver = None
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memgraph 접속 중 예기치 않은 오류: %s", exc)
        _driver = None
        return None


def is_available() -> bool:
    """Memgraph 접속 가능 여부를 확인한다.

    get_driver()가 None이면 False를 반환한다.
    간단한 RETURN 1 쿼리로 실제 접속을 테스트한다.

    Returns:
        bool: Memgraph 접속 가능하면 True
    """
    driver = get_driver()
    if driver is None:
        return False

    try:
        with driver.session() as session:
            result = session.run("RETURN 1 AS ping")
            record = result.single()
            return record is not None and record["ping"] == 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memgraph 접속 확인 실패: %s", exc)
        return False


def execute(cypher: str, params: dict = None) -> list:
    """Cypher 쿼리를 실행하고 레코드 목록을 반환한다.

    각 레코드는 dict 형태로 반환된다.
    연결 불가 시 빈 리스트를 반환한다.

    Args:
        cypher: 실행할 Cypher 쿼리 문자열
        params: 쿼리 파라미터 딕셔너리

    Returns:
        list[dict]: 쿼리 결과 레코드 목록. 연결 불가 시 빈 리스트.
    """
    driver = get_driver()
    if driver is None:
        return []

    try:
        with driver.session() as session:
            result = session.run(cypher, parameters=params or {})
            return [record.data() for record in result]
    except Exception as exc:  # noqa: BLE001
        logger.error("Cypher 쿼리 실행 실패: %s\n쿼리: %s", exc, cypher[:200])
        return []


def execute_df(cypher: str, params: dict = None) -> pd.DataFrame:
    """Cypher 쿼리를 실행하고 DataFrame으로 반환한다.

    연결 불가 시 빈 DataFrame을 반환한다.

    Args:
        cypher: 실행할 Cypher 쿼리 문자열
        params: 쿼리 파라미터 딕셔너리

    Returns:
        pd.DataFrame: 쿼리 결과. 연결 불가 시 빈 DataFrame.
    """
    records = execute(cypher, params)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def close():
    """Memgraph 드라이버를 종료한다."""
    global _driver
    if _driver is not None:
        try:
            _driver.close()
            logger.info("Memgraph 드라이버 종료 완료")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memgraph 드라이버 종료 중 오류: %s", exc)
        finally:
            _driver = None
