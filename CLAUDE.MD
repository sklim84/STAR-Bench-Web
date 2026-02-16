# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AML Assistant Platform - 에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스
- 기능1: 대시보드 형태로 자금세탁의심거래들의 기본 분석 정보 출력
- 기능2: 대시보드 형태로 자금세탁의심거래들의 네트워크(그래프) 분석 정보 출력
- 기능3: AI 모델(부스팅 모델) 기반 자금세탁의심거래 학습 및 탐지(확률)
- 기능4: 에이전트와 대화를 통해 기능1~3을 활용하여 자금세탁의심거래를 분석하고, Suspicious Transaction Report 작성

## Commands

```bash
# 앱 실행
streamlit run app.py

# CSV → Parquet 변환 (최초 1회 또는 데이터 변경 시)
python -m src.data.loader

# 의존성 설치
pip install -r requirements.txt
```

## Architecture

**Data pipeline**: CSV → Parquet (PyArrow, snappy 압축) → DuckDB (인메모리 테이블)
- `src/data/loader.py`: CSV→Parquet 변환. PyArrow 멀티스레드 파싱, 최적 타입 캐스팅 (int64→int8/int16/int32)
- `src/data/db.py`: DuckDB 싱글턴 연결. `query(sql)` → DataFrame, `query_arrow(sql)` → Arrow Table. 앱 시작 시 Parquet이 없으면 자동 변환 후 `hofinet` 테이블 생성
- `config.py`: 모든 경로(`CSV_PATH`, `PARQUET_PATH`, `DUCKDB_PATH`)와 API 키를 중앙 관리

**Streamlit 멀티페이지 앱**: `app.py` (메인) + `pages/` (기능별 페이지)
- `pages/1_Dashboard.py` → 기능1
- `pages/2_Network.py` → 기능2
- `pages/3_Detection.py` → 기능3
- `pages/4_Agent.py` → 기능4

**비즈니스 로직**: `src/features/` (기능별 모듈, 추후 구현)

## Data

HOFINET 데이터셋 - 전자금융공동망 이상거래탐지 데이터 (4,732,130건, 2021 3Q ~ 2024 4Q).
DuckDB 테이블명은 `hofinet`. 컬럼명이 한글이므로 SQL에서 그대로 사용 가능 (`SELECT 거래금액 FROM hofinet`).
클래스 불균형 325.6:1 (정상 99.69% / 이상 0.31%). 상세 스키마는 `_datasets/HOFINET.MD` 참조.

## Coding Standards

- 지나친 예외처리 하지 않기
- 구조화된 코드 작성하기
- DB 쿼리는 `src/data/db.query()` 또는 `db.query_arrow()`를 통해 실행
- 경로는 `config.py`의 상수를 사용 (하드코딩 금지)

## DO NOT

- Never commit `.env` files
- Never expose API keys in client code
