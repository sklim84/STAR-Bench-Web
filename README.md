# AML Assistant Platform

에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스입니다.

## 주요 기능

| 기능 | 설명 |
|------|------|
| **대시보드** | 거래 통계, 이상거래 유형 분포, 시간대·금융회사별 패턴 시각화 |
| **네트워크** | 계좌 간 거래 그래프, 커뮤니티 탐지, 순환거래·레이어링 등 AML 패턴 분석 |
| **탐지** | XGBoost 모델 기반 이상거래 확률 예측, 모델 학습·평가 |
| **CTR** | 고액현금거래보고(CTR) 대상 조회 및 분할거래(Structuring) 탐지 |
| **위험평가** | 5개 행위 지표 기반 계좌 위험도 산출 (0~100점) |
| **모니터링** | 6개 규칙 기반 의심거래 탐지 (심야대량·다건·정액·기관집중·패턴급변·휴면재활성화) |
| **참조자료** | FIU 의심거래 참고유형 검색, STR 필드 점검, AML 용어집 |
| **에이전트** | AI 에이전트와 대화로 거래 조회·분석, 의심거래보고서(STR) 자동 작성 |

## 요구사항

- Python 3.10+
- HOFINET 데이터셋 (`_datasets/HOFINET.csv` 또는 `HOFINET.parquet`)

## 설치

```bash
git clone <repository-url>
cd KA-001-AML-Assistant
pip install -r requirements.txt
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

| 변수 | 설명 | 필수 |
|------|------|------|
| `MEMGRAPH_HOST` | Memgraph 호스트 (기본: localhost) | 그래프 고급 분석 시 |
| `MEMGRAPH_PORT` | Memgraph 포트 (기본: 7687) | 그래프 고급 분석 시 |

## Memgraph (선택)

네트워크 페이지의 순환거래·레이어링·대포통장 등 고급 그래프 패턴 탐지는 Memgraph 사용 시에만 동작합니다. Memgraph 미실행 시 DuckDB+NetworkX로 자동 폴백됩니다.

```bash
docker-compose up -d
python -c "from src.data.graph_etl import run_etl; print(run_etl())"  # 최초 1회 ETL
```

## 테스트

```bash
pytest tests/ -v
```

> **참고**: 앱 실행 중에는 DuckDB 파일 잠금으로 테스트가 실패할 수 있습니다. 앱을 종료한 뒤 실행하세요.

## 벤치마크

에이전트 행위능력 벤치마크 (다중 모델 비교):

```bash
# OpenAI GPT-4o-mini
python _paper/benchmarks/run_multi_model.py --models gpt-4o-mini --checkpoint --output _paper/results/

# Anthropic Claude
python _paper/benchmarks/run_multi_model.py --models claude-haiku-4-5-20251001 --output _paper/results/

# Ollama (로컬)
python _paper/benchmarks/run_multi_model.py --models qwen2.5:1.5b --checkpoint --debug-chat --log-file _paper/results/bench_qwen25_15b.log --output _paper/results/

# 기존 결과로 비교 리포트만
python _paper/benchmarks/run_multi_model.py --comparison-only --output _paper/results/
```

## 데이터셋

- **HOFINET**: 전자금융공동망 이상거래탐지 데이터 (약 473만 건, 2021 Q4 ~ 2024 Q4)
- 클래스 불균형: 정상 99.69% / 이상 0.31% (325.6:1)
- 상세 스키마: `_datasets/HOFINET.MD` 참조

## 아키텍처

- **프론트엔드**: Streamlit + 다크 테마
- **데이터**: DuckDB (분석/집계) + Memgraph (그래프 패턴, 선택)
- **에이전트**: OpenAI `gpt-4o-mini` + function calling (23개 도구)

## 프로젝트 구조

```
app.py                 # 앱 진입점
_pages/                 # UI 페이지 (render 함수)
src/features/            # 비즈니스 로직
src/data/               # DB, ETL, 그래프
_datasets/              # HOFINET 데이터
_paper/benchmarks/      # 에이전트 벤치마크
```

## 라이선스

(프로젝트 라이선스에 따라 추가)
