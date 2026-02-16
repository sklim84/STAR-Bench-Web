# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AML Assistant Platform - 에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스

| 기능 | 페이지 | 상태 |
|------|--------|------|
| 기능1: 기본 분석 대시보드 | `_pages/dashboard_page.py` | 완성 |
| 기능2: 네트워크(그래프) 분석 | `_pages/network_page.py` | 개발 중 |
| 기능3: AI 모델 기반 이상거래 탐지 | `_pages/detection_page.py` | 개발 중 |
| 기능4: AI 에이전트 대화형 분석 + STR 작성 | `_pages/agent_page.py` | 완성 |

## Commands

```bash
streamlit run app.py                                    # 앱 실행
python -m src.data.loader                               # CSV → Parquet 변환 (최초 1회)
pip install -r requirements.txt                         # 의존성 설치
pytest tests/ -v                                        # 전체 테스트
pytest tests/test_dashboard.py::TestGetSummary -v       # 특정 클래스
pytest tests/test_dashboard.py::TestGetSummary::test_returns_dataframe -v  # 단일 테스트
```

## Architecture

`app.py`가 `streamlit-option-menu` 기반 상단 가로 메뉴를 렌더링하고, 선택된 메뉴에 따라 `_pages/` 모듈의 `render()` 함수를 호출한다. 각 페이지는 `src/features/` 모듈의 비즈니스 로직을 호출하고, features 모듈은 `src/data/db`를 통해 DuckDB에 쿼리한다.

```
app.py (라우팅) → _pages/ (UI, render()) → src/features/ (비즈니스 로직) → src/data/db (쿼리) → DuckDB
```

**Data pipeline**: CSV → Parquet (PyArrow, snappy 압축, 타입 최적화) → DuckDB 인메모리 테이블(`hofinet`). 앱 시작 시 Parquet이 없으면 `src/data/loader`가 자동 변환하고, `src/data/db`가 테이블을 생성한다.

**Agent (기능4)**: `src/features/agent.py`에서 OpenAI `gpt-4o-mini` + function calling으로 구현. 도구 3개 등록: `query_transactions` (SQL 실행), `predict_fraud` (XGBoost 예측), `generate_str` (STR 작성). 최대 5라운드 tool calling 반복.

**새 기능 추가 패턴**: `src/features/`에 비즈니스 로직 모듈 생성 → `_pages/`에 `render()` 함수가 있는 페이지 모듈 생성 → `app.py`의 메뉴와 라우팅에 추가

## Data

HOFINET 데이터셋 - 전자금융공동망 이상거래탐지 데이터 (4,732,130건, 2021 3Q ~ 2024 4Q).
DuckDB 테이블명 `hofinet`. **컬럼명이 한글**이므로 SQL에서 그대로 사용: `SELECT 거래금액 FROM hofinet`.
클래스 불균형 325.6:1 (정상 99.69% / 이상 0.31%). 상세 스키마는 `_datasets/HOFINET.MD` 참조.

**컬럼**: 거래일자(int32), 거래시간대(int8), 출금금융회사일련번호(int16), 출금계좌일련번호(int64), 입금금융회사일련번호(int16), 입금계좌일련번호(int64), 자금구분(int8), 매체구분(int8), 거래금액(int64), 이상거래여부(int8, 0/1), 이상거래유형(int8), 이상거래설명(utf8)

## Coding Standards

- DB 쿼리는 반드시 `src/data/db.query()` 또는 `db.query_arrow()`를 통해 실행
- 경로는 `config.py`의 상수를 사용 (하드코딩 금지)
- 시각화는 Plotly 사용, 색상 팔레트: `#4E79A7`, `#E15759`, `#F28E2B`
- 지나친 예외처리 하지 않기
- 페이지 모듈은 `_pages/`에 위치하며, 반드시 `render()` 함수를 export
