"""테스트 공통 설정.

DuckDB 파일 잠금 문제 해결:
- 파일 기반 DuckDB는 단일 프로세스만 write 모드로 열 수 있음
- 앱 실행 중에는 tests가 해당 파일에 접근 불가 (IOException)
- conftest에서 in-memory DuckDB에 Parquet를 로드하여 db._conn을 패치
- 모든 테스트는 이 in-memory 연결을 공유 (세션 스코프)
"""

import sys
from pathlib import Path

import duckdb
import pytest

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _build_inmemory_conn():
    """Parquet 파일을 in-memory DuckDB에 로드하여 연결을 반환한다."""
    import config

    conn = duckdb.connect(":memory:")
    conn.execute(f"SET threads TO {config.DUCKDB_THREADS}")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS hofinet AS
        SELECT * FROM read_parquet('{config.PARQUET_PATH.as_posix()}')
    """)
    return conn


@pytest.fixture(scope="session", autouse=True)
def patch_db_connection():
    """세션 전체에서 db._conn을 in-memory DuckDB로 교체한다.

    이 fixture는 autouse=True로 모든 테스트에 자동 적용된다.
    파일 기반 DuckDB 잠금 문제를 방지하고 테스트 격리를 보장한다.

    데이터(_datasets/HOFINET.parquet) 부재 시 모든 테스트를 자동 skip한다 —
    공개 repo는 raw 데이터를 포함하지 않으므로 fresh clone 환경에서도 적용된다.
    """
    import config

    if not config.PARQUET_PATH.exists():
        pytest.skip(
            f"HOFINET.parquet not found at {config.PARQUET_PATH} — "
            "skipping all DB-backed tests. Place the parquet locally to enable.",
            allow_module_level=True,
        )

    import src.data.db as db_module

    # in-memory 연결 생성
    conn = _build_inmemory_conn()

    # db 모듈의 싱글턴 연결을 교체
    original_conn = db_module._conn
    db_module._conn = conn

    yield conn

    # 테스트 종료 후 정리
    conn.close()
    db_module._conn = original_conn
