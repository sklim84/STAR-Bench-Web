"""src/features/agent.py 신규 도구 래퍼 분기 테스트."""

import json
from unittest.mock import patch

import pandas as pd

from src.features.agent import _execute_tool


def _json(result: str) -> dict:
    return json.loads(result)


def test_execute_tool_returns_guarded_error_on_unexpected_exception():
    """도구 내부 예외는 _execute_tool에서 안전한 에러 JSON으로 감싸야 한다."""
    with patch("src.features.agent._tool_get_statistics", side_effect=RuntimeError("boom")):
        parsed = _json(_execute_tool("get_statistics", {}))
    assert "error" in parsed
    assert "예기치 못한 오류" in parsed["error"]


def test_detect_ctr_candidates_invalid_mode():
    parsed = _json(_execute_tool("detect_ctr_candidates", {"mode": "invalid"}))
    assert "error" in parsed


def test_detect_ctr_candidates_high_value_empty():
    with patch("src.features.agent.get_ctr_candidates", return_value=pd.DataFrame()):
        parsed = _json(_execute_tool("detect_ctr_candidates", {"mode": "high_value"}))
    assert parsed["mode"] == "high_value"
    assert parsed["결과"] == []


def test_detect_ctr_candidates_structuring_success():
    df = pd.DataFrame([{"계좌": 1, "건수": 2}])
    with patch("src.features.agent.detect_structuring", return_value=df):
        parsed = _json(_execute_tool("detect_ctr_candidates", {"mode": "structuring", "threshold": 5000000}))
    assert parsed["mode"] == "structuring"
    assert parsed["건수"] == 1
    assert parsed["threshold"] == 5000000


def test_score_account_risk_branches():
    assert "error" in _json(_execute_tool("score_account_risk", {}))
    assert "error" in _json(_execute_tool("score_account_risk", {"account_id": "x"}))

    with patch("src.features.agent._score_account_risk", return_value={"account_id": 10, "risk_score": 80}):
        parsed = _json(_execute_tool("score_account_risk", {"account_id": "10"}))
    assert parsed["account_id"] == 10

    with patch("src.features.agent._score_account_risk", side_effect=ValueError("fail")):
        parsed = _json(_execute_tool("score_account_risk", {"account_id": 10}))
    assert "error" in parsed


def test_detect_monitoring_alerts_branches():
    assert "error" in _json(_execute_tool("detect_monitoring_alerts", {"rule_id": "BAD"}))

    with patch("src.features.agent.run_all_rules", return_value={"ok": True}):
        parsed = _json(_execute_tool("detect_monitoring_alerts", {"rule_id": "all"}))
    assert parsed["rule_id"] == "all"

    parsed = _json(_execute_tool("detect_monitoring_alerts", {"rule_id": "R005"}))
    assert "error" in parsed

    with patch("src.features.agent._calculate_previous_period", side_effect=ValueError("bad")):
        parsed = _json(
            _execute_tool(
                "detect_monitoring_alerts",
                {"rule_id": "R005", "date_from": 20240201, "date_to": 20240101},
            )
        )
    assert "error" in parsed

    with patch("src.features.agent.detect_round_amounts", return_value=pd.DataFrame()):
        parsed = _json(_execute_tool("detect_monitoring_alerts", {"rule_id": "R003"}))
    assert parsed["결과"] == []

    with patch("src.features.agent.detect_round_amounts", return_value=pd.DataFrame([{"a": 1}])):
        parsed = _json(_execute_tool("detect_monitoring_alerts", {"rule_id": "R003"}))
    assert parsed["건수"] == 1


def test_detect_dormant_reactivation_branches():
    with patch("src.features.agent.detect_dormant_reactivation", return_value=pd.DataFrame()):
        parsed = _json(_execute_tool("detect_dormant_reactivation", {}))
    assert parsed["결과"] == []

    with patch("src.features.agent.detect_dormant_reactivation", return_value=pd.DataFrame([{"acc": 1}])):
        parsed = _json(_execute_tool("detect_dormant_reactivation", {"limit": 1}))
    assert parsed["건수"] == 1

    with patch("src.features.agent.detect_dormant_reactivation", side_effect=RuntimeError("db")):
        parsed = _json(_execute_tool("detect_dormant_reactivation", {}))
    assert "error" in parsed


def test_detect_smurfing_network_branches():
    assert "error" in _json(_execute_tool("detect_smurfing_network", {"direction": "x"}))

    with patch("src.features.agent._detect_smurfing_network", return_value=pd.DataFrame()):
        parsed = _json(_execute_tool("detect_smurfing_network", {"direction": "inbound"}))
    assert parsed["결과"] == []

    with patch("src.features.agent._detect_smurfing_network", return_value=pd.DataFrame([{"x": 1}])):
        parsed = _json(_execute_tool("detect_smurfing_network", {"direction": "outbound"}))
    assert parsed["건수"] == 1


def test_trend_channel_receiving_and_cross_flow_wrappers():
    with patch("src.features.agent._get_trend_analysis", return_value=pd.DataFrame()):
        parsed = _json(_execute_tool("get_trend_analysis", {"unit": "weird"}))
    assert parsed["unit"] == "monthly"
    assert parsed["결과"] == []

    with patch("src.features.agent._get_trend_analysis", return_value=pd.DataFrame([{"m": "2024-01"}])):
        parsed = _json(_execute_tool("get_trend_analysis", {"unit": "quarterly"}))
    assert parsed["기간수"] == 1

    with patch(
        "src.features.agent._analyze_channel_risk",
        return_value={"channel_stats": [{"매체구분": 4}, {"매체구분": None}]},
    ):
        parsed = _json(_execute_tool("analyze_channel_risk", {}))
    assert all("채널명" in item for item in parsed["channel_stats"])

    assert "error" in _json(_execute_tool("get_receiving_account_profile", {}))
    assert "error" in _json(_execute_tool("get_receiving_account_profile", {"account_id": "x"}))
    with patch("src.features.agent._get_receiving_account_profile", return_value={"account_id": 11}):
        parsed = _json(_execute_tool("get_receiving_account_profile", {"account_id": "11"}))
    assert parsed["account_id"] == 11

    with patch("src.features.agent._analyze_cross_institution_flow", return_value=pd.DataFrame()):
        parsed = _json(_execute_tool("analyze_cross_institution_flow", {}))
    assert parsed["결과"] == []

    with patch("src.features.agent._analyze_cross_institution_flow", return_value=pd.DataFrame([{"f": 1}])):
        parsed = _json(_execute_tool("analyze_cross_institution_flow", {"min_transactions": 5}))
    assert parsed["건수"] == 1


def test_reference_tools_wrappers():
    with patch("src.features.agent.lookup_fiu_reference_types", return_value=[{"name": "A"}]):
        parsed = _json(_execute_tool("lookup_fiu_reference_types", {"keyword": "자금"}))
    assert parsed["건수"] == 1

    assert "error" in _json(_execute_tool("validate_str_fields", {}))
    with patch("src.features.agent.validate_str_fields", return_value={"ok": True}):
        parsed = _json(_execute_tool("validate_str_fields", {"str_draft": {"a": 1}}))
    assert parsed["ok"] is True

    with patch("src.features.agent.get_aml_glossary", return_value=None):
        parsed = _json(_execute_tool("get_aml_glossary", {"term": "UNKNOWN"}))
    assert "error" in parsed

    with patch("src.features.agent.get_aml_glossary", return_value={"term": "CDD", "definition": "x"}):
        parsed = _json(_execute_tool("get_aml_glossary", {"term": "CDD"}))
    assert parsed["term"] == "CDD"
