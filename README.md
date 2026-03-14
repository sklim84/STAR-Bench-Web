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

논문 작성 목적의 에이전트 행위능력 벤치마크입니다. AML 도메인 특화 23개 도구에 대해 LLM의 도구 선택(tool selection) 및 파라미터 추출(parameter extraction) 능력을 평가합니다.

### 벤치마크 데이터셋 구성

벤치마크 데이터셋은 4개 시트(도구 정의, 평가 시나리오, 벤치마크 케이스, 케이스 요약)로 구성되며, 상세 내용은 [`benchmark_dataset.xlsx`](_paper/benchmarks/benchmark_dataset.xlsx)를 참조합니다.

- **총 테스트 케이스**: 1,258건 (정상 1,099건 + 무관질문 159건)
- **평가 도구**: 23개 (AML 에이전트의 function calling 도구)
- **평가 카테고리**: 24개 (도구별 22개 + multi_tool + missing_parameters)
- **난이도 분포**: Easy 663건 (52.7%) / Medium 412건 (32.7%) / Hard 173건 (13.8%)

#### 도구 정의 및 평가 시나리오

각 도구에 대해 **정답 도구(①)**, **유사 기능 도구(②)**, **인접·미끼 도구(③)** 역할을 정의하고, 도구별 평가 시나리오(시나리오 설정, 사용자 질문, 정답, 정답 설정 근거, 모델 사고 과정)를 설계하였습니다.

| 서브 도메인 | 도구 | 설명 |
|------------|------|------|
| **이상거래 통계 및 현황 조회** | get_statistics | 전체 이상거래 요약 통계 조회 |
| | get_fraud_type_summary | 이상거래 유형별 상세 현황 조회 |
| | get_account_profile | 특정 계좌의 거래 통계 프로파일 조회 |
| | compare_periods | 두 기간 이상거래 통계 비교 |
| | get_institution_report | 금융회사 종합 현황 보고 |
| | query_transactions | SQL 기반 거래 데이터 원본 조회 |
| **AML 탐지·분석 및 보고서 작성** | analyze_network | 계좌 거래 네트워크 구조 분석 |
| | detect_aml_patterns | AML 특화 패턴 탐지 |
| | rank_risky_transactions | 위험도 상위 거래 일괄 랭킹 |
| | predict_fraud | XGBoost 모델 기반 이상거래 확률 예측 |
| | generate_str | 의심거래보고서(STR) 공식 양식 작성 |
| **CTR·위험평가·모니터링** | detect_ctr_candidates | CTR 대상 고액거래 및 분할거래 탐지 |
| | score_account_risk | 계좌 행위 기반 위험도 종합 평가 |
| | detect_monitoring_alerts | 규칙 기반 거래 모니터링 알림 탐지 |
| **자금 흐름·추세·채널 분석** | detect_dormant_reactivation | 장기 휴면 계좌 재활성화 탐지 |
| | detect_smurfing_network | 스머핑(자금 수집/분산) 네트워크 탐지 |
| | get_trend_analysis | 시계열 추세 분석 |
| | analyze_channel_risk | 채널(매체) 위험도 분석 |
| | get_receiving_account_profile | 입금 계좌 프로파일 조회 |
| | analyze_cross_institution_flow | 기관간 자금 흐름 분석 |
| **AML 참조 자료** | lookup_fiu_reference_types | FIU 의심거래 참고유형 검색 |
| | validate_str_fields | STR 필드 점검 |
| | get_aml_glossary | AML 용어집 |

#### 카테고리별 케이스 분포

| 카테고리 | 합계 | 정상 | 무관질문 | Easy | Medium | Hard |
|---------|------|------|---------|------|--------|------|
| multi_tool | 100 | 92 | 8 | 16 | 55 | 29 |
| query_transactions | 66 | 58 | 12 | 29 | 23 | 10 |
| get_statistics | 60 | 55 | 8 | 30 | 17 | 10 |
| predict_fraud | 60 | 53 | 7 | 37 | 16 | 7 |
| 기타 18개 카테고리 | 947 | 816 | 134 | 540 | 290 | 114 |
| missing_parameters | 25 | 0 | 25 | 11 | 11 | 3 |
| **합계** | **1,258** | **1,099** | **169** | **663** | **412** | **173** |

**평가 메트릭**: 종합점수(0~1), 도구 선택 정확도(primary_tool_hit_rate), 파라미터 추출 정확도(param_accuracy), 에러 유형별 분포(wrong_func, wrong_params, missing_params, connection_error)

### 실험 결과 (18개 모델, 2026-03-06)

| 모델 | 파라미터 | 종합점수 | 도구정확도 | 파라미터정확도 |
|------|---------|---------|----------|-------------|
| Qwen3-4B-Thinking (think) | 4B | 0.927 | 94.7% | 90.0% |
| Qwen3-4B-Thinking (nothink) | 4B | 0.927 | 94.7% | 90.1% |
| gpt-oss-120b (think) | 120B | 0.912 | 92.3% | 92.5% |
| gpt-oss-120b (nothink) | 120B | 0.909 | 92.1% | 92.0% |
| Mistral-Small-3.2-24B | 24B | 0.900 | 89.5% | 89.5% |
| gpt-oss-20b (nothink) | 20B | 0.892 | 89.6% | 88.4% |
| gpt-oss-20b (think) | 20B | 0.891 | 89.5% | 88.4% |
| Qwen3-4B-Instruct | 4B | 0.887 | 90.5% | 88.1% |
| Llama-3.1-8B-Instruct | 8B | 0.809 | 81.9% | 79.1% |
| Kanana-1.5-8B | 8B | 0.771 | 74.6% | 73.0% |
| Kanana-1.5-15.7B | 15.7B (3B active) | 0.717 | 66.2% | 68.5% |
| Granite-3.1-8B | 8B | 0.326 | 12.9% | 23.4% |
| EXAONE-3.5-7.8B | 7.8B | 0.325 | 12.6% | 23.4% |
| Gemma-3-12B | 12B | 0.325 | 12.6% | 23.4% |
| Gemma-3-27B | 27B | 0.325 | 12.6% | 23.4% |
| Phi-4-mini | 14B | 0.225 | 8.3% | 13.8% |
| Kanana-1.5-2.1B | 2.1B | 0.224 | 22.1% | 21.4% |
| EXAONE-3.5-32B | 32B | 0.072 | 2.1% | 6.5% |

> Granite, EXAONE, Gemma 등 하위 모델은 vLLM tool-call parser 호환 문제로 도구 호출 추출이 실패한 케이스가 대부분이며, 파서 변경 재실험 진행 중.

#### 종합 성능 비교

<img src="_paper/results/figures/fig1_overall_performance.png" width="700" alt="Overall Performance">

#### 도구 선택 vs 파라미터 추출 정확도

<img src="_paper/results/figures/fig5_tool_vs_param.png" width="600" alt="Tool vs Param">

#### 난이도별 성능 히트맵

<img src="_paper/results/figures/fig4_difficulty_heatmap.png" width="700" alt="Difficulty Heatmap">

#### 카테고리별 레이더 차트 (상위 6개 모델)

<img src="_paper/results/figures/fig2_radar_chart.png" width="700" alt="Radar Chart">

#### 에러 유형 분포

<img src="_paper/results/figures/fig3_error_distribution.png" width="700" alt="Error Distribution">

#### 카테고리 × 모델 히트맵

<img src="_paper/results/figures/fig6_category_heatmap.png" width="800" alt="Category Heatmap">

### 비교 대상 모델 (8개 계열, 20개 구성)

| 계열 | 모델 | 파라미터 | 실행 환경 |
|------|------|---------|---------|
| GPT-OSS | gpt-oss-20b, gpt-oss-120b | 20B, 120B | vLLM |
| Qwen3 | Qwen3-4B-Instruct, Qwen3-4B-Thinking | 4B | vLLM |
| Mistral | Mistral-Small-3.2-24B-Instruct | 24B | vLLM |
| Llama | Llama-3.1-8B-Instruct | 8B | vLLM |
| Kanana | kanana-1.5-2.1b, 8b, 15.7b-a3b | 2.1B~15.7B | vLLM (커스텀 파서) |
| EXAONE | EXAONE-3.5-7.8B, 32B | 7.8B, 32B | vLLM |
| Gemma | gemma-3-12b-it, 27b-it | 12B, 27B | vLLM |
| Granite | granite-3.1-8b | 8B | vLLM |

### 실행 방법

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

### 결과 디렉토리 구조

```
_paper/results/
├── eval/              # 모델별 평가 결과 JSON (eval_<model>_<timestamp>.json)
├── checkpoint/        # 케이스별 체크포인트 JSONL (재실행 시 완료건 스킵)
├── logs/
│   ├── bench/         # 벤치마크 실행 로그
│   └── vllm/          # vLLM 서버 로그
├── figures/           # 시각화 PNG (visualize_results.py로 생성)
│   ├── fig1_overall_performance.png   # 모델별 종합 성능 비교
│   ├── fig2_radar_chart.png           # 카테고리별 레이더 차트
│   ├── fig3_error_distribution.png    # 에러 유형 분포
│   ├── fig4_difficulty_heatmap.png    # 난이도별 성능 히트맵
│   ├── fig5_tool_vs_param.png         # 도구정확도 vs 파라미터정확도
│   └── fig6_category_heatmap.png      # 카테고리 × 모델 히트맵
├── visualize_results.py               # 시각화 생성 스크립트
└── comparison_*.xlsx                  # 다중 모델 비교 리포트
```

지원 프로바이더: OpenAI, Anthropic, vLLM (로컬 모델)

## TODO

### 영문 Ablation 실험 (한/영 프롬프트 비교)

동일 1,258건 벤치마크 케이스를 영어로 번역하여, 질문 언어(한국어↔영어)에 따른 tool-calling 정확도 차이를 분석하는 단일변수 실험.

- **번역 완료**: GPT-4o-mini로 24개 케이스 파일 전체 영문 번역 (`_paper/benchmarks_en/`)
- **`benchmark.py` 수정 완료**: `--cases-dir` 옵션 추가로 한/영 데이터셋 전환 가능
- **결과 저장 경로**: `_paper/results_en/` (한국어: `_paper/results/`)

#### 완료 모델 (10/44)

| GPU | 모델 | 상태 |
|-----|------|------|
| GPU0 | xLAM-1B, EXAONE-1.2B, Qwen2.5-1.5B, xLAM-3B, Ministral-3B, Kanana-2.1B | 완료 |
| GPU0 | Qwen3-4B, xLAM-8B | 완료 |
| GPU1 | Ministral-14B, Kanana-15.7B | 완료 |

#### 미완료 모델 (34/44)

**GPU0 대상 (소형/중형 모델)**:
- [ ] Qwen3-8B, Kanana-8B, OLMo-3-7B, Command-R-7B, Granite-3.2-8B
- [ ] Llama-3.1-8B, Hermes-3-8B, DeepSeek-R1-Qwen3-8B, Ministral-8B, Mistral-Nemo-12B
- [ ] Qwen3-4B-Thinking (think/nothink)
- [ ] Qwen3.5-0.8B, Qwen3.5-2B, Qwen3.5-4B, Qwen3.5-9B (각 think/nothink)

**GPU1 대상 (중형/대형 모델)**:
- [ ] Mistral-Small-24B, xLAM-32B, EXAONE-32B, GLM-4.7-Flash, Qwen3-Coder-30B
- [ ] gpt-oss-20b (think/nothink)
- [ ] Qwen3-30B-A3B-Thinking (think/nothink)
- [ ] Qwen3.5-27B (think/nothink)
- [ ] Qwen3-30B-A3B-Instruct

**TP=2 대상 (70B 모델, GPU 2장 필요)**:
- [ ] Llama-3.3-70B, xLAM-70B

**상용 API 모델**:
- [ ] gpt-4o-mini, gpt-5-mini (OpenAI)
- [ ] claude-haiku-4-5, claude-sonnet-4-5 (Anthropic)

#### 실행 방법

```bash
# GPU0 소형/중형 모델
CUDA_VISIBLE_DEVICES=0 bash /tmp/bench_en_gpu0_retry.sh

# GPU1 중형/대형 모델
CUDA_VISIBLE_DEVICES=1 bash /tmp/bench_en_gpu1_retry.sh

# TP=2 70B 모델 (GPU0/1 완료 후)
bash /tmp/bench_en_tp2_retry.sh

# 상용 API 모델
python -m _paper.scripts.benchmark --models gpt-4o-mini --output _paper/results_en/ --cases-dir _paper/benchmarks_en/
python -m _paper.scripts.benchmark --models claude-haiku-4-5-20251001 --output _paper/results_en/ --cases-dir _paper/benchmarks_en/
```

#### 완료 후 작업
- [ ] 한/영 결과 비교 분석 (Korean vs English accuracy delta)
- [ ] 비교 시각화 생성 (fig 추가)
- [ ] 한국어 벤치마크 시각화 재생성 (44개 모델 반영)

### 기타

- [ ] `benchmark.py` 코드 정리: VLLM_BASE_URL 상수 추출, 미사용 openpyxl import lazy화
- [ ] `evaluator.py` 리팩토링: _safe_json_load(), _check_keywords() 헬퍼 추출, 108줄 거대함수 분리
