# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AML Assistant Platform - 에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스

| 기능 | 페이지 | 비즈니스 로직 | 상태 |
|------|--------|--------------|------|
| 기능1: 기본 분석 대시보드 | `_pages/dashboard_page.py` | `src/features/dashboard.py` | 완성 |
| 기능2: 네트워크(그래프) 분석 | `_pages/network_page.py` | `src/features/network.py` | 완성 |
| 기능3: AI 모델 기반 이상거래 탐지 | `_pages/detection_page.py` | `src/features/detector.py` | 완성 |
| 기능4: AI 에이전트 대화형 분석 + STR 작성 | `_pages/agent_page.py` | `src/features/agent.py` | 완성 |

## Commands

```bash
streamlit run app.py                                    # 앱 실행
python -m src.data.loader                               # CSV → Parquet 변환 (최초 1회)
pip install -r requirements.txt                         # 의존성 설치
pytest tests/ -v                                        # 전체 테스트
pytest tests/test_dashboard.py -v                       # 특정 파일
pytest tests/test_dashboard.py::TestGetSummary -v       # 특정 클래스
pytest tests/test_dashboard.py::TestGetSummary::test_returns_dataframe -v  # 단일 테스트
```

## Architecture

`app.py`가 `streamlit-option-menu` 기반 상단 가로 메뉴를 렌더링하고, 선택된 메뉴에 따라 `_pages/` 모듈의 `render()` 함수를 호출한다. 각 페이지는 `src/features/` 모듈의 비즈니스 로직을 호출하고, features 모듈은 `src/data/db`를 통해 DuckDB에 쿼리한다.

```
app.py (라우팅 + 글로벌 CSS) → _pages/ (UI, render()) → src/features/ (비즈니스 로직) → src/data/db (쿼리) → DuckDB
```

**Data pipeline**: CSV → Parquet (PyArrow, snappy 압축, 타입 최적화) → DuckDB 인메모리 테이블(`hofinet`). 앱 시작 시 Parquet이 없으면 `src/data/loader`가 자동 변환하고, `src/data/db`가 테이블을 생성한다.

**Dashboard (기능1)**: `src/features/dashboard.py`에 17개 함수. 글로벌 필터(`_build_filter_conditions`, `_apply_filters`) 지원으로 모든 쿼리 함수에 `filters=None` 파라미터 적용. 자금구분 분석, 이상거래 금액 분석, 교차 히트맵(시간대x유형), 유형별 추이 포함.

**Network (기능2)**: `src/features/network.py`에 11개 함수. 금융회사/계좌 간 거래 네트워크 구축, 4대 중심성 지표(`compute_centrality_metrics`), Louvain 커뮤니티 탐지(`detect_communities`), 이상거래 흐름 매트릭스(`get_fraud_flow_matrix`), 확장 네트워크 통계(`get_extended_network_stats`). UI 4개 탭: 금융회사 네트워크, 이상거래 계좌 네트워크, 계좌 탐색, 이상거래 흐름.

**Detector (기능3)**: `src/features/detector.py`에 11개 함수. XGBoost 이상거래 탐지. 학습 피처: `["거래시간대", "출금금융회사일련번호", "입금금융회사일련번호", "자금구분", "매체구분", "거래금액"]`. 모델 저장: `_models/xgb_detector.joblib`. `train_model(params=None)`로 하이퍼파라미터 튜닝 지원. F1 기반 임계값 최적화(`find_optimal_threshold`), ROC 커브(`get_roc_curve_data`), 이상거래 유형별 탐지 성능(`evaluate_by_fraud_type`), 확률 구간 분포(`get_probability_distribution`).

**Agent (기능4)**: `src/features/agent.py`에서 OpenAI `gpt-4o-mini` + function calling. 도구 5개: `query_transactions` (SQL 실행, 최대 100행, 위험 키워드 차단), `predict_fraud` (XGBoost 예측 + 파라미터 검증), `generate_str` (구조화된 STR 보고서 생성), `analyze_network` (계좌 네트워크 분석), `get_statistics` (대시보드 요약 통계 조회). 최대 5라운드 tool calling. UI에서 도구 호출 시각화(expander) + 대화 내보내기(JSON) 지원.

**새 기능 추가 패턴**: `src/features/`에 비즈니스 로직 모듈 생성 → `_pages/`에 `render()` 함수가 있는 페이지 모듈 생성 → `app.py`의 `option_menu` options/icons와 라우팅 if-elif에 추가

## Data

HOFINET 데이터셋 - 전자금융공동망 이상거래탐지 데이터 (4,732,130건, 2021 Q4 ~ 2024 Q4, 13분기).
DuckDB 테이블명 `hofinet`. **컬럼명이 한글**이므로 SQL에서 그대로 사용: `SELECT 거래금액 FROM hofinet`.
클래스 불균형 325.6:1 (정상 99.69% / 이상 0.31%). 상세 스키마는 `_datasets/HOFINET.MD` 참조.

**학습 데이터**: `_datasets/original/{Training,Test,Validation}/` 디렉토리에 분할 저장.

**이상거래유형 코드**: 1=자금세탁, 2=신규 거래처(63.87%로 최다), 3=대포통장, 4=보이스피싱, 5=불법도박, 6=유사수신, 7=기타

**컬럼**: 거래일자(int32), 거래시간대(int8), 출금금융회사일련번호(int16), 출금계좌일련번호(int64), 입금금융회사일련번호(int16), 입금계좌일련번호(int64), 자금구분(int8), 매체구분(int8), 거래금액(int64), 이상거래여부(int8, 0/1), 이상거래유형(int8), 이상거래설명(utf8)

## UI / Dark Theme

앱 전체가 다크 테마로 통일되어 있다. 테마 설정은 `.streamlit/config.toml`에 정의되고, `app.py` 상단에 커스텀 CSS가 주입된다.

**색상 팔레트**:
- 배경: `#0E1117` (메인), `#1A1F2E` (카드/컨테이너), `#2A2F3E` (테두리/구분선)
- 강조: `#4ECDC4` (민트, 메트릭 값/선택된 탭)
- 차트: `#4E79A7` (파랑 바), `#E15759` (빨강 라인), `#F28E2B` (주황 강조)
- 텍스트: `#E0E0E0` (본문), `#8B8FA3` (라벨/보조), `#6B7080` (설명)

**UI 패턴**:
- 메트릭 카드: `st.metric()` 대신 HTML `.metric-card` 클래스 사용 (라벨 회색, 값 민트색)
- 섹션 헤더: `st.subheader()` 대신 `<p class="section-header">` HTML 사용
- Plotly 차트: `_apply_dark()` 헬퍼로 투명 배경 + `#1E2333` 그리드 적용 (각 페이지에 로컬 정의)
- 테이블: `.dark-table` HTML 클래스 사용
- 히트맵 colorscale: `[[0,'#1A1F2E'],[0.5,'#2A6B65'],[1,'#4ECDC4']]`

## Coding Standards

- DB 쿼리는 반드시 `src/data/db.query()` 또는 `db.query_arrow()`를 통해 실행
- **`_pages/`에서 `src/data/db`를 직접 import하지 않는다** — 반드시 `src/features/` 레이어를 경유
- 경로는 `config.py`의 상수를 사용 (하드코딩 금지)
- 시각화는 Plotly 사용, 위 색상 팔레트 준수
- Plotly 차트에 다크 테마 적용 필수 (투명 배경, `#1E2333` 그리드)
- 페이지 모듈은 `_pages/`에 위치하며, 반드시 `render()` 함수를 export
- `.env` 파일 커밋 금지, API 키를 코드에 노출하지 않기
- SQL 안전성: 외부 입력에 `int()` 변환 또는 파라미터 바인딩 사용
- 테스트 네이밍: `Test<FunctionName>::test_<description>` 패턴 사용
- 테스트 커버리지: dashboard(115), network(79), detector(76), agent(96), db(19), config(16), loader(13), modules(10) — 총 435개
