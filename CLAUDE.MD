# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AML Assistant Platform - 에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스

| 기능 | 페이지 | 상태 |
|------|--------|------|
| 기능1: 기본 분석 대시보드 | `pages/1_Dashboard.py` | 완성 |
| 기능2: 네트워크(그래프) 분석 | `pages/2_Network.py` | 개발 중 |
| 기능3: AI 모델 기반 이상거래 탐지 | `pages/3_Detection.py` | 개발 중 |
| 기능4: AI 에이전트 대화형 분석 + STR 작성 | `pages/4_Agent.py` | 개발 중 |

## Commands

```bash
# 앱 실행
streamlit run app.py

# CSV → Parquet 변환 (최초 1회 또는 데이터 변경 시)
python -m src.data.loader

# 의존성 설치
pip install -r requirements.txt

# 테스트 실행
pytest tests/ -v
pytest tests/test_dashboard.py::TestGetSummary -v   # 특정 클래스
```

## Architecture

```
app.py (메인)
├── pages/                      # Streamlit 멀티페이지
│   ├── 1_Dashboard.py          # 기능1 (완성, Plotly 시각화)
│   ├── 2_Network.py            # 기능2 (스켈레톤)
│   ├── 3_Detection.py          # 기능3 (스켈레톤)
│   └── 4_Agent.py              # 기능4 (스켈레톤)
├── src/
│   ├── data/
│   │   ├── loader.py           # CSV→Parquet 변환 (PyArrow 멀티스레드, 타입 최적화)
│   │   └── db.py               # DuckDB 싱글턴 연결, query()/query_arrow()
│   └── features/
│       └── dashboard.py        # 대시보드 쿼리 함수 8개
├── config.py                   # 경로·API 키 중앙 관리
├── _datasets/                  # 데이터 저장소
│   ├── HOFINET.csv             # 원본 (313MB)
│   ├── HOFINET.parquet         # 변환 (78MB, Snappy)
│   ├── hofinet.duckdb          # DB (67MB)
│   └── HOFINET.MD              # 스키마 문서
├── _models/                    # 학습된 모델 저장소 (향후)
├── _docs/                      # 문서 저장소 (향후)
└── tests/                      # pytest (127개 케이스, 100% 통과)
```

**Data pipeline**: CSV → Parquet (PyArrow, snappy 압축) → DuckDB (인메모리 테이블)
- `src/data/loader.py`: CSV→Parquet 변환. PyArrow 멀티스레드 파싱, 최적 타입 캐스팅 (int64→int8/int16/int32)
- `src/data/db.py`: DuckDB 싱글턴 연결. `query(sql)` → DataFrame, `query_arrow(sql)` → Arrow Table. 앱 시작 시 Parquet이 없으면 자동 변환 후 `hofinet` 테이블 생성
- `config.py`: 모든 경로(`CSV_PATH`, `PARQUET_PATH`, `DUCKDB_PATH`)와 API 키를 중앙 관리
- `src/features/dashboard.py`: 8개 분석 쿼리 함수 (get_summary, get_quarterly_trend, get_hourly_distribution, get_amount_distribution, get_fraud_type_distribution, get_monthly_trend, get_medium_distribution, get_top_banks)

## Data

HOFINET 데이터셋 - 전자금융공동망 이상거래탐지 데이터 (4,732,130건, 2021 3Q ~ 2024 4Q).
DuckDB 테이블명은 `hofinet`. 컬럼명이 한글이므로 SQL에서 그대로 사용 가능 (`SELECT 거래금액 FROM hofinet`).
클래스 불균형 325.6:1 (정상 99.69% / 이상 0.31%). 상세 스키마는 `_datasets/HOFINET.MD` 참조.

**주요 컬럼**: 거래일자(int32), 거래시간대(int8), 출금금융회사일련번호(int16), 출금계좌일련번호(int64), 입금금융회사일련번호(int16), 입금계좌일련번호(int64), 자금구분(int8), 매체구분(int8), 거래금액(int64), 이상거래여부(int8, 0/1), 이상거래유형(int8), 이상거래설명(utf8)

## Tech Stack

- **Web**: Streamlit (멀티페이지), Plotly (시각화)
- **Data**: DuckDB (인메모리 DB), PyArrow/Parquet, Pandas
- **ML**: scikit-learn, XGBoost (기능3용)
- **Graph**: NetworkX (기능2용)
- **AI API**: OpenAI, Anthropic (기능4용)
- **Config**: python-dotenv (.env → config.py)

## Tests

pytest 기반, 127개 테스트 케이스 전부 통과.

| 테스트 파일 | 대상 모듈 | 테스트 수 |
|---|---|---|
| test_modules.py | 프로젝트 구조/의존성 | 20 |
| test_config.py | config.py | 16 |
| test_loader.py | src/data/loader.py | 13 |
| test_db.py | src/data/db.py | 19 |
| test_dashboard.py | src/features/dashboard.py | 59 |

## Coding Standards

- 지나친 예외처리 하지 않기
- 구조화된 코드 작성하기
- DB 쿼리는 `src/data/db.query()` 또는 `db.query_arrow()`를 통해 실행
- 경로는 `config.py`의 상수를 사용 (하드코딩 금지)
- 새 기능 추가 시 `src/features/`에 비즈니스 로직 모듈 생성, `pages/`에서 import하여 사용
- 시각화는 Plotly 사용, 색상 팔레트: `#4E79A7`, `#E15759`, `#F28E2B`

## DO NOT

- Never commit `.env` files
- Never expose API keys in client code
- Never hardcode file paths (use `config.py` constants)
