# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AML Assistant Platform (**STAR-Bench-Web**) - 에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스. 본 repo는 STAR-Bench 벤치마크의 23개 도구가 도출된 **레퍼런스 플랫폼**이다.

| 기능 | 페이지 | 비즈니스 로직 | 상태 |
|------|--------|--------------|------|
| 기능1: 기본 분석 대시보드 | `_pages/dashboard_page.py` | `src/features/dashboard.py` | 완성 |
| 기능2: 네트워크(그래프) 분석 | `_pages/network_page.py` | `src/features/network.py` | 완성 |
| 기능3: AI 모델 기반 이상거래 탐지 | `_pages/detection_page.py` | `src/features/detector.py` | 완성 |
| 기능4: AI 에이전트 대화형 분석 + STR 작성 | `_pages/agent_page.py` | `src/features/agent.py` | 완성 |
| 기능5: CTR 모니터링 (고액현금거래보고) | `_pages/ctr_page.py` | `src/features/ctr_monitor.py` | 완성 |
| 기능6: 계좌 위험도 평가 (Risk Scoring) | `_pages/risk_page.py` | `src/features/risk_scorer.py` | 완성 |
| 기능7: 거래 모니터링 규칙 탐지 | `_pages/monitoring_page.py` | `src/features/monitoring.py` | 완성 |
| 기능8: 자금 흐름 분석 (스머핑/기관간) | — | `src/features/flow_analyzer.py` | 완성 |
| 기능9: AML 참조 자료 | `_pages/aml_reference_page.py` | `src/features/aml_reference.py` | 완성 |

> **관련 저장소**: 벤치마크는 `STAR-Bench`, 논문은 `STAR-Bench-paper` (별도 repo). 이 repo는 웹 플랫폼만 포함한다.

## Commands

```bash
streamlit run app.py                                    # 앱 실행
python -m src.data.loader                               # CSV → Parquet 변환 (최초 1회)
pip install -r requirements.txt                         # 의존성 설치
pytest tests/ -v                                        # 전체 테스트
pytest tests/test_dashboard.py -v                       # 특정 파일
pytest tests/test_dashboard.py::TestGetSummary -v       # 특정 클래스
pytest tests/test_dashboard.py::TestGetSummary::test_returns_dataframe -v  # 단일 테스트
docker-compose up -d                                    # Memgraph 실행 (그래프 분석용)
python -c "from src.data.graph_etl import run_etl; print(run_etl())"  # DuckDB → Memgraph ETL
```

**데이터 준비**: 거버넌스상 HOFINET 원천 데이터는 이 repo에 포함되지 않는다(`_datasets/HOFINET.MD` 스키마만 포함). 앱을 실행하려면 `_datasets/HOFINET.parquet`(또는 `.duckdb`)를 로컬에 배치하거나, 원천 CSV를 두고 `python -m src.data.loader`로 생성해야 한다. 데이터·모델 부재 시 `tests/test_config.py`의 데이터 의존 테스트는 자동 skip된다.

**환경 변수** (`.env` 파일 또는 환경에 설정):
```
OPENAI_API_KEY=...           # 기능4 에이전트에 필요
MEMGRAPH_HOST=localhost      # 기본값, 변경 시 설정
MEMGRAPH_PORT=7687           # 기본값
```

## Architecture

### 레이어 구조

```
app.py (라우팅 + 글로벌 CSS 주입)
  → _pages/ (UI, 각 모듈은 render() 함수를 export)
    → src/features/ (비즈니스 로직)
      → src/data/db (DuckDB 쿼리)
      → src/data/graph_db (Memgraph Cypher 쿼리)
  → assets/style.css (글로벌 CSS 클래스 정의)
  → src/ui/chart_utils.py (Plotly 색상 상수 + apply_dark() 공통 모듈)
```

### Dual-Store 아키텍처

DuckDB(분석/집계)와 Memgraph(그래프 패턴 탐지)가 공존한다. Memgraph 미실행 시 DuckDB+NetworkX로 자동 폴백한다 (Graceful Degradation).

### Data Pipeline

- **DuckDB**: CSV → Parquet (PyArrow, snappy) → DuckDB 인메모리 테이블(`hofinet`). 앱 시작 시 Parquet이 없으면 `src/data/loader`가 자동 변환
- **Memgraph**: `src/data/graph_etl.run_etl()`로 DuckDB → Memgraph 일괄 ETL (최초 1회). `docker-compose up -d` 후 실행

### Memgraph 그래프 모델

```
(:Company {id: int})
(:Account {id: int, company_id: int})
(:Account)-[:BELONGS_TO]->(:Company)
(:Account)-[:TRANSFER {거래일자, 거래시간대, 자금구분, 매체구분, 거래금액, 이상거래여부, 이상거래유형}]->(:Account)
```

### 기능별 핵심 구조

- **기능1 (Dashboard)**: 글로벌 필터(`filters=None` 파라미터) 패턴. 모든 쿼리 함수가 동일 필터 인터페이스 지원
- **기능2 (Network)**: DuckDB+NetworkX 함수(중심성, 커뮤니티) + Memgraph Cypher 함수(순환거래, 레이어링, 대포통장, N-hop, 최단경로, 시간 윈도우, 위험도). UI 5개 탭 + AML 패턴 탐지 탭(6개 서브탭)
- **기능3 (Detector)**: XGBoost 모델. 학습 피처: `["거래시간대", "출금금융회사일련번호", "입금금융회사일련번호", "자금구분", "매체구분", "거래금액"]`. 모델 저장: `_models/xgb_detector.joblib`
- **기능4 (Agent)**: OpenAI `gpt-4o-mini` + function calling. 도구 23개, 최대 5라운드 tool calling. `TOOLS` 리스트가 `src/features/agent.py` 상단에 정의됨. `generate_str`은 STR 공식 양식 I~VII 섹션 구조로 출력하며 `transactions`(거래 레코드), `fraud_probability`(확률 0~1→의심강도 1~5), `aml_patterns`(탐지 패턴) 파라미터를 통해 자동 추출. 23개 도구: `get_statistics`, `query_transactions`, `get_account_profile`, `get_fraud_type_summary`, `compare_periods`, `get_institution_report`, `rank_risky_transactions`, `analyze_network`, `detect_aml_patterns`, `predict_fraud`, `generate_str`, `detect_ctr_candidates`, `score_account_risk`, `detect_monitoring_alerts`, `detect_dormant_reactivation`, `detect_smurfing_network`, `get_trend_analysis`, `analyze_channel_risk`, `get_receiving_account_profile`, `analyze_cross_institution_flow`, `lookup_fiu_reference_types`, `validate_str_fields`, `get_aml_glossary`
- **기능5 (CTR)**: 고액현금거래(1,000만원 이상) 조회 + 분할거래(structuring) 탐지. 동일계좌 동일일 합산액이 기준금액 이상이면서 단건이 기준 미만인 패턴을 탐지
- **기능6 (Risk)**: 5개 행위 지표 기반 0~100점 위험도 산출. 심야거래비율(0.15), 금액이상도(0.25), 거래상대다양성(0.15), 거래속도변화(0.25), 이상거래이력(0.20). DuckDB만으로 동작
- **기능7 (Monitoring)**: 6개 규칙 기반 모니터링. R001 심야대량거래, R002 동일일다건거래, R003 정액거래패턴, R004 기관집중거래, R005 거래패턴급변, R006 휴면계좌재활성화
- **기능8 (Flow)**: 스머핑 네트워크(자금 수집/분산 패턴) + 기관간 자금 흐름 분석. DuckDB만으로 동작

### 새 기능 추가 패턴

`src/features/`에 비즈니스 로직 모듈 생성 → `_pages/`에 `render()` 함수가 있는 페이지 모듈 생성 → `app.py`의 `option_menu` options/icons와 라우팅 if-elif에 추가

## Data

HOFINET 데이터셋 (Interbank Home/Firm Banking Network) - 전자금융공동망 이상거래탐지 합성데이터 (4,732,130건, 2021 Q3 ~ 2024 Q4, 14분기).
DuckDB 테이블명 `hofinet`. **컬럼명이 한글**이므로 SQL에서 그대로 사용: `SELECT 거래금액 FROM hofinet`.
클래스 불균형 325.6:1 (정상 99.69% / 이상 0.31%). 상세 스키마는 `_datasets/HOFINET.MD` 참조.

**이상거래유형 코드 (HOFINET 공식 매핑)**: 1=갑작스러운 거래패턴의 변화, 2=신규 수신처 거래(63.87%로 최다), 3=분할 거래, 4=다중거래의 동시 요청, 5=거액 입금 후 당일 인출, 7=심야/새벽 대량 거래 (코드 6은 미존재).

**컬럼**: 거래일자(int32), 거래시간대(int8, 0/3/6/9/12/15/18/21만 유효), 출금금융회사일련번호(int16, 50종), 출금계좌일련번호(int64), 입금금융회사일련번호(int16, 54종), 입금계좌일련번호(int64), 자금구분(int8, {0,1,3,4}), 매체구분(int8, 1~7), 거래금액(int64), 이상거래여부(int8, 0/1), 이상거래유형(int8), 이상거래설명(utf8)

## UI / Dark Theme

앱 전체가 다크 테마로 통일되어 있다. 테마 설정은 `.streamlit/config.toml`에 정의되고, `app.py` 상단에 커스텀 CSS가 주입된다.

**색상 팔레트**:
- 배경: `#0E1117` (메인), `#1A1F2E` (카드/컨테이너), `#2A2F3E` (테두리/구분선)
- 강조: `#4ECDC4` (민트, 메트릭 값/선택된 탭)
- 차트: `#4E79A7` (파랑 바), `#E15759` (빨강 라인), `#F28E2B` (주황 강조)
- 텍스트: `#E0E0E0` (본문), `#8B8FA3` (라벨/보조), `#6B7080` (설명)

**UI 패턴**:
- 페이지 타이틀/부제목: `<p class="page-title">`, `<p class="page-subtitle">` HTML 사용
- 메트릭 카드: `st.metric()` 대신 `_metric_card(label, value, sub="", white=False)` 헬퍼 사용. 이 함수는 `st.markdown()`을 직접 호출하며 문자열을 반환하지 않는다. `sub` 인자는 항상 렌더링(빈 문자열도)하여 카드 높이 일관성 보장
- 섹션 헤더: `st.subheader()` 대신 `<p class="section-header">` HTML 사용
- Plotly 차트: `from src.ui.chart_utils import apply_dark as _apply_dark`로 import하여 사용. 색상 상수(`BAR_COLOR`, `LINE_COLOR`, `ACCENT_COLOR`, `MINT_COLOR`)도 동일 모듈에서 import
- 테이블: `.dark-table` HTML 클래스 사용
- 히트맵 colorscale: `[[0,'#1A1F2E'],[0.5,'#2A6B65'],[1,'#4ECDC4']]`
- 공통 CSS 클래스는 `assets/style.css`에 정의. 새 클래스 추가 시 이 파일에 작성

## Coding Standards

### 레이어 규칙
- DB 쿼리는 반드시 `src/data/db.query()` 또는 `db.query_arrow()`를 통해 실행. 그래프 쿼리는 `src/data/graph_db.execute()` 또는 `graph_db.execute_df()` 사용
- **`_pages/`에서 `src/data/db`를 직접 import하지 않는다** — 반드시 `src/features/` 레이어를 경유
- `_pages/`에서 `graph_db`는 `is_available()` 상태 확인 목적으로만 import 허용
- 경로는 `config.py`의 상수를 사용 (하드코딩 금지)
- 페이지 모듈은 `_pages/`에 위치하며, 반드시 `render()` 함수를 export

### 시각화
- 시각화는 Plotly 사용, 위 색상 팔레트 준수
- Plotly 차트에 다크 테마 적용 필수 (투명 배경, `#1E2333` 그리드)

### 쿼리 안전성
- SQL 안전성: 외부 입력에 `int()` 변환 또는 파라미터 바인딩 사용
- Cypher 안전성: Memgraph는 LIMIT에 파라미터 바인딩 불가. `int()` 변환 후 f-string 삽입. 파라미터 바인딩 가능한 곳은 `$param` 형식 사용

### Memgraph Graceful Degradation 패턴
모든 Cypher 기반 함수는 아래 패턴을 따른다:
```python
def detect_something(...):
    if not graph_db.is_available():
        logger.warning("Memgraph 미실행으로 ... 불가")
        return pd.DataFrame()  # 또는 빈 dict
    # Cypher 쿼리 실행
```

### 테스트
- 테스트 네이밍: `Test<FunctionName>::test_<description>` 패턴 사용
- Memgraph 의존 함수는 `unittest.mock.patch`로 `graph_db` 모킹하여 테스트
- **DuckDB 격리**: `tests/conftest.py`의 `patch_db_connection` fixture(autouse, session scope)가 `src/data/db._conn`을 in-memory DuckDB로 교체한다. 파일 기반 DuckDB는 단일 프로세스만 write 모드로 열 수 있으므로 앱 실행 중 pytest를 돌리면 파일 잠금 충돌이 발생한다 — 앱을 종료한 뒤 테스트를 실행할 것
- `agent.py`가 `from src.features.detector import load_model`로 import하므로, 테스트에서 load_model 모킹 시 `src.features.agent.load_model`을 패치해야 함 (`src.features.detector.load_model` 패치 무효)
