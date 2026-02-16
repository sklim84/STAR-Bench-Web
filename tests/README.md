# Tests

KA-001-AML-Assistant 프로젝트의 단위 테스트 디렉토리입니다.

## 테스트 파일 구조

| 파일 | 대상 모듈 | 설명 |
|------|----------|------|
| `test_modules.py` | 프로젝트 구조 / 의존성 | 모듈 임포트, 패키지 설치, 디렉토리 구조 검증 |
| `test_config.py` | `config.py` | 경로 상수, 데이터 파일, DuckDB 설정, API 키 검증 |
| `test_loader.py` | `src/data/loader.py` | Parquet 스키마, 데이터 무결성 검증 |
| `test_db.py` | `src/data/db.py` | DuckDB 연결, query/query_arrow 함수 검증 |
| `test_dashboard.py` | `src/features/dashboard.py` | 8개 대시보드 쿼리 함수 검증 |

## 테스트 실행

```bash
# 전체 테스트
pytest tests/ -v

# 개별 파일
pytest tests/test_config.py -v

# 특정 클래스
pytest tests/test_dashboard.py::TestGetSummary -v

# 특정 케이스
pytest tests/test_config.py::TestPathConstants::test_base_dir_is_project_root -v
```

## 테스트 작성 규칙

- **클래스명**: `Test<FunctionName>` (예: `TestGetSummary`)
- **메서드명**: `test_<검증내용>` (예: `test_returns_dataframe`)
- **구조**: Arrange-Act-Assert (AAA) 패턴
- **Fixture**: 반복 호출이 비싼 함수는 `@pytest.fixture(scope="class")`로 캐싱
- **공통 Fixture**: `conftest.py`에 정의

## 테스트 환경

- **Framework**: pytest
- **Python**: 3.13+
- **필수 패키지**: `requirements.txt` 참조
