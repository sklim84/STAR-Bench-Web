# Tests

`tests/`는 `src/` 모듈의 단위 테스트를 담습니다.

## 커버 범위(요약)

- 데이터 계층: `test_loader.py`, `test_db.py`, `test_graph_etl.py`, `test_graph_db.py`
- 에이전트/분석 기능: `test_agent.py`, `test_agent_str.py`, `test_agent_tools_extended.py`
- 피처 모듈: `test_dashboard.py`, `test_detector.py`, `test_network.py`, `test_monitoring.py`, `test_flow_analyzer.py`, `test_ctr_monitor.py`, `test_risk_scorer.py`, `test_aml_reference.py`
- 공통/설정: `test_config.py`, `test_modules.py`, `conftest.py`
- UI 유틸: `test_chart_utils.py`

## 실행 방법

```bash
# tests 디렉토리 전체
pytest -q tests

# 특정 파일
pytest -q tests/test_agent_tools_extended.py

# 특정 테스트
pytest -q tests/test_db.py::TestConnectionLifecycle::test_close_handles_none_and_resets_connection
```

## 참고

- `tests/__pycache__/`는 파이썬 실행 중 자동 생성되는 캐시이며 소스가 아닙니다.
- 테스트는 in-memory DuckDB 픽스처(`tests/conftest.py`)를 사용합니다.
