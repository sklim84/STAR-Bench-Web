# AML Assistant Platform

에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스입니다.

## 주요 기능

| 기능 | 페이지 | 설명 |
|------|--------|------|
| **대시보드** | `dashboard_page.py` | 거래 통계, 이상거래 유형 분포, 시간대/금융회사별 패턴 시각화 |
| **네트워크 분석** | `network_page.py` | 계좌 간 거래 그래프, 커뮤니티 탐지, 순환거래/레이어링 등 AML 패턴 분석 |
| **이상거래 탐지** | `detection_page.py` | XGBoost 모델 기반 이상거래 확률 예측, 모델 학습/평가 |
| **에이전트** | `agent_page.py` | AI 에이전트와 대화로 거래 조회/분석, 의심거래보고서(STR) 자동 작성 |
| **CTR 모니터링** | `ctr_page.py` | 고액현금거래보고(CTR) 대상 조회 및 분할거래(Structuring) 탐지 |
| **위험도 평가** | `risk_page.py` | 5개 행위 지표 기반 계좌 위험도 산출 (0~100점) |
| **거래 모니터링** | `monitoring_page.py` | 6개 규칙 기반 의심거래 탐지 (심야대량/다건/정액/기관집중/패턴급변/휴면재활성화) |
| **자금 흐름 분석** | — | 스머핑 네트워크(자금 수집/분산 패턴) + 기관간 자금 흐름 분석 |
| **AML 참조자료** | `aml_reference_page.py` | FIU 의심거래 참고유형 검색, STR 필드 점검, AML 용어집 |

## 기술 스택

| 영역 | 기술 |
|------|------|
| 프론트엔드 | Streamlit + 다크 테마 (Plotly 시각화) |
| 분석 DB | DuckDB (인메모리, Parquet 기반) |
| 그래프 DB | Memgraph (선택, Docker) — 미실행 시 DuckDB+NetworkX 폴백 |
| AI 에이전트 | OpenAI `gpt-4o-mini` + function calling (23개 도구) |
| ML 모델 | XGBoost (이상거래 탐지) |

## 요구사항

- Python 3.10+
- HOFINET 데이터셋 (`_datasets/HOFINET.csv` 또는 `HOFINET.parquet`)
- OpenAI API 키 (에이전트 기능 사용 시)

## 설치

```bash
git clone <repository-url>
cd KA-001-AML-Assistant
pip install -r requirements.txt
cp .env.example .env  # API 키 설정
```

## 데이터 준비

1. **HOFINET.csv**를 `_datasets/` 디렉터리에 배치합니다.
2. 최초 실행 시 앱이 자동으로 Parquet으로 변환합니다. 수동 변환 시:
   ```bash
   python -m src.data.loader
   ```

## 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501`로 접속합니다.

## 환경 변수

`.env` 파일에 설정합니다 (`.env.example` 참조):

| 변수 | 설명 | 필수 |
|------|------|------|
| `OPENAI_API_KEY` | OpenAI API 키 | 에이전트(기능4) 사용 시 |
| `ANTHROPIC_API_KEY` | Anthropic API 키 | 벤치마크 실행 시 |
| `MEMGRAPH_HOST` | Memgraph 호스트 (기본: `localhost`) | 그래프 고급 분석 시 |
| `MEMGRAPH_PORT` | Memgraph 포트 (기본: `7687`) | 그래프 고급 분석 시 |

## Memgraph (선택)

네트워크 페이지의 순환거래/레이어링/대포통장 등 고급 그래프 패턴 탐지는 Memgraph 사용 시에만 동작합니다. Memgraph 미실행 시 DuckDB+NetworkX로 자동 폴백됩니다.

```bash
docker-compose up -d
python -c "from src.data.graph_etl import run_etl; print(run_etl())"  # 최초 1회 ETL
```

## 테스트

```bash
pytest tests/ -v                                        # 전체 테스트
pytest tests/test_dashboard.py -v                       # 특정 모듈
pytest tests/test_dashboard.py::TestGetSummary -v       # 특정 클래스
```

> **참고**: 앱 실행 중에는 DuckDB 파일 잠금으로 테스트가 실패할 수 있습니다. 앱을 종료한 뒤 실행하세요.

## 아키텍처

### Dual-Store 아키텍처

DuckDB(분석/집계)와 Memgraph(그래프 패턴 탐지)가 공존합니다. Memgraph 미실행 시 DuckDB+NetworkX로 자동 폴백합니다 (Graceful Degradation).

### 레이어 구조

```
app.py                          # 라우팅 + 글로벌 CSS 주입
├── _pages/                     # UI 페이지 (각 모듈은 render() 함수 export)
│   ├── dashboard_page.py
│   ├── network_page.py
│   ├── detection_page.py
│   ├── agent_page.py
│   ├── ctr_page.py
│   ├── risk_page.py
│   ├── monitoring_page.py
│   └── aml_reference_page.py
├── src/
│   ├── features/               # 비즈니스 로직
│   │   ├── dashboard.py
│   │   ├── network.py
│   │   ├── detector.py
│   │   ├── agent.py            # 23개 도구 + OpenAI function calling
│   │   ├── ctr_monitor.py
│   │   ├── risk_scorer.py
│   │   ├── monitoring.py
│   │   ├── flow_analyzer.py
│   │   └── aml_reference.py
│   ├── data/                   # 데이터 레이어
│   │   ├── db.py               # DuckDB 쿼리 인터페이스
│   │   ├── graph_db.py         # Memgraph Cypher 쿼리
│   │   ├── graph_etl.py        # DuckDB → Memgraph ETL
│   │   └── loader.py           # CSV → Parquet 변환
│   └── ui/
│       └── chart_utils.py      # Plotly 색상 상수 + apply_dark()
├── assets/style.css            # 글로벌 CSS
├── config.py                   # 경로/환경 변수 상수
├── _models/
│   └── xgb_detector.joblib     # 학습된 XGBoost 모델
├── _datasets/                  # HOFINET 데이터
├── _docs/                      # AML 실무 참조 문서 (FATF, CDD, STR 등)
└── tests/                      # pytest 단위 테스트 (18개 모듈)
```

## 데이터셋

- **HOFINET**: 전자금융공동망 이상거래탐지 데이터 (약 473만 건, 2021 Q4 ~ 2024 Q4, 13분기)
- 클래스 불균형: 정상 99.69% / 이상 0.31% (325.6:1)
- 이상거래유형: 자금세탁, 신규거래처, 대포통장, 보이스피싱, 불법도박, 유사수신, 기타
- 상세 스키마: `_datasets/HOFINET.MD` 참조

## 벤치마크 (`_paper/`)

논문 작성 목적의 에이전트 행위능력 벤치마크입니다. 23개 도구, 24개 카테고리, 총 1,258건의 테스트 케이스를 사용하여 다중 모델을 비교합니다.

```bash
# 단일 모델 벤치마크
python _paper/benchmarks/run_multi_model.py \
    --models gpt-4o-mini --checkpoint --output _paper/results/

# 기존 결과로 비교 리포트만
python _paper/benchmarks/run_multi_model.py \
    --comparison-only --output _paper/results/

# vLLM 기반 로컬 모델 자동화 (GPU 서버)
bash _paper/benchmarks/scripts/run_all_models.sh
```

지원 프로바이더: OpenAI, Anthropic, Ollama, vLLM (로컬 모델)
