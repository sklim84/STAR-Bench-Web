# AML 참조 기능 작업 요약

> **NOTE (2026-05-28)**: 본 문서는 repo 분리(STAR-Bench / STAR-Bench-paper / STAR-Bench-Web) 이전 작업 기록입니다. 본문의 `_paper/benchmarks/...` 경로는 현재 별도 repo `../star-bench/benchmarks/...`에 해당합니다.

## 1. 기능 정의 (_docs 기반)

| 기능 | 설명 | 근거 문서 |
|------|------|-----------|
| lookup_fiu_reference_types | FIU 업권별 의심거래 참고유형 검색 | 07b_STR_의심거래보고_업권별지표 |
| validate_str_fields | STR 필수 필드 점검 | 08_STR_보고서양식 |
| get_aml_glossary | AML 용어 정의 조회 | 05a, 06, 07a, 04 등 |

---

## 2. 웹 서비스 추가

- **참조자료** 메뉴 추가 (상단 네비게이션)
- **_pages/aml_reference_page.py** 신규 생성
  - 탭1: FIU 참고유형 검색 (07b 기반)
  - 탭2: STR 필드 점검 (08 기반)
  - 탭3: AML 용어집 (CDD, STR, CTR, RBA 등)
- 홈 화면 기능 안내에 참조자료 카드 추가

---

## 3. 에이전트용 도구 추가

- **src/features/aml_reference.py** 신규 생성
  - `lookup_fiu_reference_types(keyword, industry?)`
  - `validate_str_fields(str_draft)`
  - `get_aml_glossary(term)`
- **src/features/agent.py** 수정
  - 도구 20개 → 23개
  - 위 3개 도구 등록 및 `_execute_tool` 분기 추가

---

## 4. 벤치마크 구축

| 카테고리 | 케이스 수 | 파일 |
|----------|----------|------|
| lookup_fiu_reference_types | 8건 | cases_lookup_fiu_reference_types.json |
| validate_str_fields | 3건 | cases_validate_str_fields.json |
| get_aml_glossary | 8건 | cases_get_aml_glossary.json |

**총 19건** 추가 → 전체 벤치마크 **1,258건** (24개 카테고리)

- bench_agent_behavior.py: 3개 카테고리 및 테스트/bench 함수 추가
- run_benchmark.py: 3개 벤치마크 등록
- create_benchmark_dataset.py: 3개 카테고리 추가

---

## 5. 변경·추가된 파일

| 구분 | 경로 |
|------|------|
| 신규 | src/features/aml_reference.py |
| 신규 | _pages/aml_reference_page.py |
| 신규 | tests/test_aml_reference.py |
| 신규 | _paper/benchmarks/dataset/cases_lookup_fiu_reference_types.json |
| 신규 | _paper/benchmarks/dataset/cases_validate_str_fields.json |
| 신규 | _paper/benchmarks/dataset/cases_get_aml_glossary.json |
| 수정 | app.py (참조자료 메뉴, 홈 카드) |
| 수정 | src/features/agent.py (도구 3개 등록) |
| 수정 | _paper/benchmarks/bench_agent_behavior.py |
| 수정 | _paper/benchmarks/run_benchmark.py |
| 수정 | _paper/benchmarks/create_benchmark_dataset.py |

---

## 6. 실행 방법

```bash
# 앱 실행
streamlit run app.py

# aml_reference 단위 테스트
pytest tests/test_aml_reference.py -v

# 새 벤치마크 포함 전체 실행 (OPENAI_API_KEY 필요)
python _paper/benchmarks/run_benchmark.py --include-behavior --output _paper/results/benchmark_report.json
```
