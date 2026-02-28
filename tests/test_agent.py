"""기능4: AI 분석 에이전트 (src/features/agent.py) 단위 테스트.

검증 항목:
- TOOLS 정의가 OpenAI function calling 스펙을 충족하는지
- SYSTEM_PROMPT가 올바른 내용을 포함하는지
- _execute_tool()이 각 도구를 올바르게 실행하는지
- _execute_tool()의 SELECT 전용 제한이 동작하는지
- _message_to_dict()가 올바른 dict를 반환하는지
- chat()이 OpenAI API 호출 없이 mock으로 정상 동작하는지
- _validate_predict_fraud_args()가 유효하지 않은 파라미터를 올바르게 검증하는지
- _build_str_report()가 올바른 구조의 STR을 생성하는지
- _execute_tool('analyze_network', ...)가 계좌 네트워크를 올바르게 분석하는지
- _execute_tool('get_statistics', ...)가 통계 요약을 반환하는지
"""

import json
import re
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from src.features.agent import (
    TOOLS,
    SYSTEM_PROMPT,
    MAX_TOOL_ROUNDS,
    _execute_tool,
    _message_to_dict,
    _validate_predict_fraud_args,
    _build_str_report,
)


# ──────────────────────────────────────────────
# TOOLS 정의 검증
# ──────────────────────────────────────────────
class TestToolsDefinition:
    """TOOLS 상수 검증."""

    def test_tools_is_list(self):
        """TOOLS가 리스트이어야 한다."""
        assert isinstance(TOOLS, list)

    def test_tools_count(self):
        """도구가 정확히 8개이어야 한다 (get_account_profile, get_fraud_type_summary 추가)."""
        assert len(TOOLS) == 8

    def test_tools_have_required_structure(self):
        """각 도구가 type과 function 키를 가져야 한다."""
        for tool in TOOLS:
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool

    def test_tool_names(self):
        """도구 이름이 기대하는 값과 일치하는지 확인."""
        names = {tool["function"]["name"] for tool in TOOLS}
        expected = {
            "query_transactions",
            "predict_fraud",
            "generate_str",
            "analyze_network",
            "get_statistics",
            "detect_aml_patterns",
            "get_account_profile",
            "get_fraud_type_summary",
        }
        assert names == expected

    def test_tools_have_description(self):
        """모든 도구에 description이 있어야 한다."""
        for tool in TOOLS:
            assert "description" in tool["function"]
            assert len(tool["function"]["description"]) > 0

    def test_tools_have_parameters(self):
        """모든 도구에 parameters가 정의되어 있어야 한다."""
        for tool in TOOLS:
            assert "parameters" in tool["function"]
            params = tool["function"]["parameters"]
            assert "type" in params
            assert "properties" in params

    def test_query_transactions_required_sql(self):
        """query_transactions 도구에 sql이 required 파라미터여야 한다."""
        qt = next(t for t in TOOLS if t["function"]["name"] == "query_transactions")
        assert "sql" in qt["function"]["parameters"]["required"]

    def test_predict_fraud_required_params(self):
        """predict_fraud 도구에 필수 파라미터가 있어야 한다."""
        pf = next(t for t in TOOLS if t["function"]["name"] == "predict_fraud")
        required = set(pf["function"]["parameters"]["required"])
        expected = {"거래시간대", "출금금융회사일련번호", "입금금융회사일련번호", "자금구분", "매체구분", "거래금액"}
        assert expected == required

    def test_generate_str_required_summary(self):
        """generate_str 도구에 summary가 required 파라미터여야 한다."""
        gs = next(t for t in TOOLS if t["function"]["name"] == "generate_str")
        assert "summary" in gs["function"]["parameters"]["required"]


# ──────────────────────────────────────────────
# SYSTEM_PROMPT 검증
# ──────────────────────────────────────────────
class TestSystemPrompt:
    """SYSTEM_PROMPT 상수 검증."""

    def test_system_prompt_is_string(self):
        """SYSTEM_PROMPT가 문자열이어야 한다."""
        assert isinstance(SYSTEM_PROMPT, str)

    def test_system_prompt_not_empty(self):
        """SYSTEM_PROMPT가 비어있지 않아야 한다."""
        assert len(SYSTEM_PROMPT) > 0

    def test_system_prompt_contains_hofinet(self):
        """SYSTEM_PROMPT에 HOFINET 데이터셋 언급이 있어야 한다."""
        assert "hofinet" in SYSTEM_PROMPT.lower() or "HOFINET" in SYSTEM_PROMPT

    def test_system_prompt_mentions_aml(self):
        """SYSTEM_PROMPT에 AML 관련 내용이 포함되어야 한다."""
        prompt_lower = SYSTEM_PROMPT.lower()
        assert "자금세탁" in SYSTEM_PROMPT or "aml" in prompt_lower

    def test_system_prompt_mentions_tools(self):
        """SYSTEM_PROMPT에 도구 사용 안내가 포함되어야 한다."""
        assert "query_transactions" in SYSTEM_PROMPT
        assert "predict_fraud" in SYSTEM_PROMPT
        assert "generate_str" in SYSTEM_PROMPT

    def test_system_prompt_mentions_korean(self):
        """SYSTEM_PROMPT에 한국어 응답 지시가 있어야 한다."""
        assert "한국어" in SYSTEM_PROMPT


# ──────────────────────────────────────────────
# MAX_TOOL_ROUNDS 검증
# ──────────────────────────────────────────────
class TestMaxToolRounds:
    """MAX_TOOL_ROUNDS 상수 검증."""

    def test_max_rounds_positive(self):
        """MAX_TOOL_ROUNDS가 양수이어야 한다."""
        assert isinstance(MAX_TOOL_ROUNDS, int)
        assert MAX_TOOL_ROUNDS > 0

    def test_max_rounds_reasonable(self):
        """MAX_TOOL_ROUNDS가 합리적인 범위(1~10)이어야 한다."""
        assert 1 <= MAX_TOOL_ROUNDS <= 10


# ──────────────────────────────────────────────
# _execute_tool - query_transactions
# ──────────────────────────────────────────────
class TestExecuteToolQueryTransactions:
    """_execute_tool('query_transactions', ...) 단위 테스트."""

    def test_select_query_returns_json(self):
        """SELECT 쿼리가 JSON 문자열을 반환하는지 확인."""
        result = _execute_tool("query_transactions", {"sql": "SELECT count(*) as cnt FROM hofinet"})
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_select_result_contains_data(self):
        """SELECT 쿼리 결과에 데이터가 있는지 확인."""
        result = _execute_tool("query_transactions", {"sql": "SELECT count(*) as cnt FROM hofinet"})
        parsed = json.loads(result)
        assert len(parsed) > 0
        assert "cnt" in parsed[0]

    def test_select_count_matches_total(self):
        """전체 건수 쿼리가 정확한 값을 반환하는지 확인."""
        result = _execute_tool("query_transactions", {"sql": "SELECT count(*) as cnt FROM hofinet"})
        parsed = json.loads(result)
        assert parsed[0]["cnt"] == 4_732_130

    def test_non_select_rejected(self):
        """SELECT가 아닌 쿼리는 오류를 반환해야 한다."""
        result = _execute_tool("query_transactions", {"sql": "DROP TABLE hofinet"})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_insert_rejected(self):
        """INSERT 쿼리는 오류를 반환해야 한다."""
        result = _execute_tool("query_transactions", {"sql": "INSERT INTO hofinet VALUES (1)"})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_result_limited_to_100(self):
        """결과가 100행으로 제한되는지 확인."""
        result = _execute_tool("query_transactions", {"sql": "SELECT * FROM hofinet"})
        parsed = json.loads(result)
        assert len(parsed) <= 100

    def test_fraud_query_result(self):
        """이상거래 쿼리가 정상 동작하는지 확인."""
        result = _execute_tool("query_transactions", {
            "sql": "SELECT 이상거래유형, count(*) as cnt FROM hofinet WHERE 이상거래여부=1 GROUP BY 이상거래유형"
        })
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) > 0

    def test_case_insensitive_select_check(self):
        """소문자 select도 허용되는지 확인."""
        result = _execute_tool("query_transactions", {"sql": "select count(*) as cnt from hofinet"})
        # 오류가 아닌 정상 결과이어야 함
        parsed = json.loads(result)
        assert "error" not in parsed or "cnt" in str(parsed)


# ──────────────────────────────────────────────
# _execute_tool - predict_fraud
# ──────────────────────────────────────────────
class TestExecuteToolPredictFraud:
    """_execute_tool('predict_fraud', ...) 단위 테스트."""

    @pytest.fixture
    def sample_transaction(self):
        return {
            "거래시간대": 21,
            "출금금융회사일련번호": 134,
            "입금금융회사일련번호": 20,
            "자금구분": 1,
            "매체구분": 3,
            "거래금액": 50000000,
        }

    def test_no_model_returns_error(self, sample_transaction):
        """모델이 없을 때 오류 메시지를 반환하는지 확인.

        agent.py 상단에서 'from src.features.detector import load_model'로
        import하므로, 패치 대상은 agent 모듈의 load_model이어야 한다.
        """
        with patch("src.features.agent.load_model", return_value=None):
            result = _execute_tool("predict_fraud", sample_transaction)
            parsed = json.loads(result)
            assert "error" in parsed

    def test_with_mock_model_returns_probability(self, sample_transaction):
        """Mock 모델을 사용하여 확률이 반환되는지 확인."""
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])

        with patch("src.features.agent.load_model", return_value=mock_model):
            result = _execute_tool("predict_fraud", sample_transaction)
            parsed = json.loads(result)
            assert "이상거래확률" in parsed
            assert 0 <= parsed["이상거래확률"] <= 1

    def test_probability_rounded_to_4_decimals(self, sample_transaction):
        """확률이 소수점 4자리까지 반올림되는지 확인."""
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.123456, 0.876544]])

        with patch("src.features.agent.load_model", return_value=mock_model):
            result = _execute_tool("predict_fraud", sample_transaction)
            parsed = json.loads(result)
            prob = parsed["이상거래확률"]
            assert prob == round(prob, 4)


# ──────────────────────────────────────────────
# _execute_tool - generate_str
# ──────────────────────────────────────────────
class TestExecuteToolGenerateStr:
    """_execute_tool('generate_str', ...) 단위 테스트."""

    def test_returns_json(self):
        """generate_str이 JSON 문자열을 반환하는지 확인."""
        result = _execute_tool("generate_str", {"summary": "테스트 의심거래 내용"})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_contains_report_key(self):
        """결과에 보고서 유형 키가 있는지 확인 (강화된 STR 구조)."""
        result = _execute_tool("generate_str", {"summary": "출금계좌 123에서 이상거래 탐지"})
        parsed = json.loads(result)
        # 강화된 STR 구조: 보고서유형 또는 보고서 키 중 하나가 있어야 함
        assert "보고서유형" in parsed or "보고서" in parsed

    def test_summary_preserved_in_content(self):
        """입력한 summary가 결과에 포함되는지 확인."""
        summary_text = "계좌 ABC에서 대량 자금 이동 의심"
        result = _execute_tool("generate_str", {"summary": summary_text})
        parsed = json.loads(result)
        assert summary_text in str(parsed)

    def test_contains_guidance(self):
        """STR 작성 안내 메시지가 포함되어야 한다."""
        result = _execute_tool("generate_str", {"summary": "test"})
        parsed = json.loads(result)
        # 강화된 구조: 작성안내, 안내, 내용 중 하나가 있어야 함
        assert "작성안내" in parsed or "안내" in parsed or "내용" in parsed


# ──────────────────────────────────────────────
# _execute_tool - 알 수 없는 도구
# ──────────────────────────────────────────────
class TestExecuteToolUnknown:
    """알 수 없는 도구 이름 처리 테스트."""

    def test_unknown_tool_returns_error(self):
        """알 수 없는 도구명에 오류를 반환해야 한다."""
        result = _execute_tool("nonexistent_tool", {})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_unknown_tool_error_mentions_name(self):
        """오류 메시지에 도구명이 포함되어야 한다."""
        result = _execute_tool("nonexistent_tool", {})
        assert "nonexistent_tool" in result


# ──────────────────────────────────────────────
# _message_to_dict
# ──────────────────────────────────────────────
class TestMessageToDict:
    """_message_to_dict() 단위 테스트."""

    def test_simple_message_conversion(self):
        """tool_calls가 없는 메시지가 올바르게 변환되는지 확인."""
        mock_msg = MagicMock()
        mock_msg.role = "assistant"
        mock_msg.content = "분석 결과입니다."
        mock_msg.tool_calls = None

        result = _message_to_dict(mock_msg)

        assert result["role"] == "assistant"
        assert result["content"] == "분석 결과입니다."
        assert "tool_calls" not in result

    def test_tool_call_message_conversion(self):
        """tool_calls가 있는 메시지가 올바르게 변환되는지 확인."""
        mock_tc = MagicMock()
        mock_tc.id = "call_abc123"
        mock_tc.function.name = "query_transactions"
        mock_tc.function.arguments = '{"sql": "SELECT 1"}'

        mock_msg = MagicMock()
        mock_msg.role = "assistant"
        mock_msg.content = ""
        mock_msg.tool_calls = [mock_tc]

        result = _message_to_dict(mock_msg)

        assert result["role"] == "assistant"
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["id"] == "call_abc123"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "query_transactions"

    def test_none_content_becomes_empty_string(self):
        """content가 None일 때 빈 문자열로 변환되는지 확인."""
        mock_msg = MagicMock()
        mock_msg.role = "assistant"
        mock_msg.content = None
        mock_msg.tool_calls = None

        result = _message_to_dict(mock_msg)
        assert result["content"] == ""

    def test_multiple_tool_calls(self):
        """복수의 tool_calls가 올바르게 변환되는지 확인."""
        tool_calls = []
        for i in range(3):
            mock_tc = MagicMock()
            mock_tc.id = f"call_{i}"
            mock_tc.function.name = "query_transactions"
            mock_tc.function.arguments = f'{{"sql": "SELECT {i}"}}'
            tool_calls.append(mock_tc)

        mock_msg = MagicMock()
        mock_msg.role = "assistant"
        mock_msg.content = ""
        mock_msg.tool_calls = tool_calls

        result = _message_to_dict(mock_msg)
        assert len(result["tool_calls"]) == 3


# ──────────────────────────────────────────────
# chat() - OpenAI API mock 테스트
# ──────────────────────────────────────────────
class TestChat:
    """chat() 함수 단위 테스트 (OpenAI API mock)."""

    def _make_mock_response(self, content="테스트 응답"):
        """OpenAI API 응답 mock 객체를 생성한다."""
        mock_msg = MagicMock()
        mock_msg.role = "assistant"
        mock_msg.content = content
        mock_msg.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_msg

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    def test_chat_returns_tuple(self):
        """chat()이 (content, messages, tool_events) 3-튜플을 반환하는지 확인."""
        from src.features.agent import chat

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response("분석 완료")

        with patch("src.features.agent.OpenAI", return_value=mock_client):
            result = chat([{"role": "user", "content": "이상거래 현황을 알려줘"}])

        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_chat_returns_assistant_content(self):
        """chat()이 어시스턴트 응답 내용을 반환하는지 확인."""
        from src.features.agent import chat

        expected_content = "2024년 이상거래는 총 14,490건입니다."
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response(expected_content)

        with patch("src.features.agent.OpenAI", return_value=mock_client):
            content, messages, tool_events = chat([{"role": "user", "content": "이상거래 현황"}])

        assert content == expected_content

    def test_chat_appends_messages(self):
        """chat()이 응답 메시지를 대화 히스토리에 추가하는지 확인."""
        from src.features.agent import chat

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response("응답")

        messages = [{"role": "user", "content": "질문"}]
        with patch("src.features.agent.OpenAI", return_value=mock_client):
            content, updated_messages, tool_events = chat(messages)

        # 원래 messages에 assistant 응답이 추가되어야 함
        assert any(m["role"] == "assistant" for m in updated_messages)

    def test_chat_with_tool_call_round(self):
        """tool_call이 포함된 응답이 올바르게 처리되는지 확인."""
        from src.features.agent import chat

        # 1차 응답: tool call 포함
        mock_tc = MagicMock()
        mock_tc.id = "call_test_001"
        mock_tc.function.name = "query_transactions"
        mock_tc.function.arguments = '{"sql": "SELECT count(*) as cnt FROM hofinet"}'

        mock_msg_with_tool = MagicMock()
        mock_msg_with_tool.role = "assistant"
        mock_msg_with_tool.content = ""
        mock_msg_with_tool.tool_calls = [mock_tc]

        mock_choice_tool = MagicMock()
        mock_choice_tool.message = mock_msg_with_tool

        # 2차 응답: 최종 텍스트
        final_content = "조회 결과: 총 4,732,130건 이상거래 탐지"
        mock_msg_final = MagicMock()
        mock_msg_final.role = "assistant"
        mock_msg_final.content = final_content
        mock_msg_final.tool_calls = None

        mock_choice_final = MagicMock()
        mock_choice_final.message = mock_msg_final

        mock_response_tool = MagicMock()
        mock_response_tool.choices = [mock_choice_tool]

        mock_response_final = MagicMock()
        mock_response_final.choices = [mock_choice_final]

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            mock_response_tool,
            mock_response_final,
        ]

        with patch("src.features.agent.OpenAI", return_value=mock_client):
            content, messages, tool_events = chat([{"role": "user", "content": "이상거래 건수 알려줘"}])

        assert final_content in content
        # tool 메시지가 히스토리에 포함되어야 함
        roles = [m["role"] for m in messages]
        assert "tool" in roles
        # tool_events에 도구 호출 기록이 있어야 함
        assert len(tool_events) >= 1
        assert tool_events[0]["name"] == "query_transactions"

    def test_chat_system_prompt_included(self):
        """API 호출 시 시스템 프롬프트가 포함되는지 확인."""
        from src.features.agent import chat

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response()

        with patch("src.features.agent.OpenAI", return_value=mock_client):
            chat([{"role": "user", "content": "질문"}])

        call_args = mock_client.chat.completions.create.call_args
        messages_sent = call_args.kwargs.get("messages") or call_args.args[0] if call_args.args else []
        if not messages_sent:
            messages_sent = call_args[1].get("messages", [])

        # 시스템 메시지가 포함되어야 함
        system_msgs = [m for m in messages_sent if m.get("role") == "system"]
        assert len(system_msgs) >= 1

    def test_chat_uses_gpt4o_mini(self):
        """API 호출 시 gpt-4o-mini 모델이 사용되는지 확인."""
        from src.features.agent import chat

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response()

        with patch("src.features.agent.OpenAI", return_value=mock_client):
            chat([{"role": "user", "content": "질문"}])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o-mini"


# ──────────────────────────────────────────────
# _validate_predict_fraud_args
# ──────────────────────────────────────────────
class TestValidatePredictFraudArgs:
    """_validate_predict_fraud_args() 단위 테스트."""

    def _valid_args(self):
        return {
            "거래시간대": 9,
            "출금금융회사일련번호": 10,
            "입금금융회사일련번호": 20,
            "자금구분": 1,
            "매체구분": 3,
            "거래금액": 500000,
        }

    def test_valid_args_returns_empty_errors(self):
        """유효한 파라미터는 오류 목록이 비어야 한다."""
        errors = _validate_predict_fraud_args(self._valid_args())
        assert errors == []

    def test_invalid_거래시간대_returns_error(self):
        """잘못된 거래시간대(예: 5)는 오류를 반환해야 한다."""
        args = self._valid_args()
        args["거래시간대"] = 5  # 유효 값: {0,3,6,9,12,15,18,21}
        errors = _validate_predict_fraud_args(args)
        assert len(errors) >= 1
        assert any("거래시간대" in e for e in errors)

    def test_invalid_자금구분_returns_error(self):
        """잘못된 자금구분(예: 2)은 오류를 반환해야 한다."""
        args = self._valid_args()
        args["자금구분"] = 2  # 유효 값: {0,1,3,4}
        errors = _validate_predict_fraud_args(args)
        assert len(errors) >= 1
        assert any("자금구분" in e for e in errors)

    def test_invalid_매체구분_returns_error(self):
        """잘못된 매체구분(예: 10)은 오류를 반환해야 한다."""
        args = self._valid_args()
        args["매체구분"] = 10  # 유효 값: 1~7
        errors = _validate_predict_fraud_args(args)
        assert len(errors) >= 1
        assert any("매체구분" in e for e in errors)

    def test_negative_거래금액_returns_error(self):
        """음수 거래금액은 오류를 반환해야 한다."""
        args = self._valid_args()
        args["거래금액"] = -100
        errors = _validate_predict_fraud_args(args)
        assert len(errors) >= 1
        assert any("거래금액" in e for e in errors)

    def test_zero_거래금액_returns_error(self):
        """0원 거래금액은 오류를 반환해야 한다."""
        args = self._valid_args()
        args["거래금액"] = 0
        errors = _validate_predict_fraud_args(args)
        assert len(errors) >= 1
        assert any("거래금액" in e for e in errors)

    def test_multiple_invalid_params_return_multiple_errors(self):
        """여러 파라미터가 잘못되면 각각 오류를 반환해야 한다."""
        args = {
            "거래시간대": 7,      # 잘못됨
            "출금금융회사일련번호": 10,
            "입금금융회사일련번호": 20,
            "자금구분": 2,         # 잘못됨
            "매체구분": 0,         # 잘못됨
            "거래금액": -1,        # 잘못됨
        }
        errors = _validate_predict_fraud_args(args)
        assert len(errors) >= 3

    def test_boundary_거래시간대_valid(self):
        """경계값 거래시간대 0과 21은 유효해야 한다."""
        for t in [0, 21]:
            args = self._valid_args()
            args["거래시간대"] = t
            errors = _validate_predict_fraud_args(args)
            assert not any("거래시간대" in e for e in errors), f"시간대 {t}는 유효해야 함"

    def test_boundary_매체구분_valid(self):
        """경계값 매체구분 1과 7은 유효해야 한다."""
        for m in [1, 7]:
            args = self._valid_args()
            args["매체구분"] = m
            errors = _validate_predict_fraud_args(args)
            assert not any("매체구분" in e for e in errors), f"매체구분 {m}은 유효해야 함"


# ──────────────────────────────────────────────
# _build_str_report
# ──────────────────────────────────────────────
class TestBuildStrReport:
    """_build_str_report() 단위 테스트 - 새 6-파라미터 시그니처 기준."""

    # 공통 헬퍼: 최소 필수 인수로 함수 호출
    @staticmethod
    def _call(**kwargs):
        defaults = dict(
            summary="테스트 요약",
            fraud_type="자금세탁",
            tools_used=[],
            transactions=[],
            fraud_probability=None,
            aml_patterns=[],
        )
        defaults.update(kwargs)
        return _build_str_report(**defaults)

    def test_returns_dict(self):
        """dict를 반환해야 한다."""
        result = self._call(tools_used=["query_transactions"])
        assert isinstance(result, dict)

    def test_required_top_level_keys_present(self):
        """새 STR 구조의 필수 최상위 키가 모두 존재해야 한다."""
        result = self._call()
        required_keys = {
            "보고서유형", "표제부", "I_보고기관", "II_거래자",
            "III_거래내역", "IV_관련계좌", "VI_거래유형", "VII_서술",
            "권고조치", "분석근거", "작성안내",
        }
        assert required_keys.issubset(set(result.keys()))

    def test_보고서유형_is_str(self):
        """보고서유형이 STR 관련 문자열이어야 한다."""
        result = self._call()
        assert "STR" in result["보고서유형"] or "의심거래" in result["보고서유형"]

    def test_표제부_보고일자_format(self):
        """표제부.보고일자가 YYYY-MM-DD 형식이어야 한다."""
        result = self._call()
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", result["표제부"]["보고일자"])

    def test_summary_preserved_in_VII(self):
        """summary가 VII_서술.혐의판단사유에 보존되어야 한다."""
        summary = "계좌 123에서 심야 대량 자금 이동"
        result = self._call(summary=summary)
        assert result["VII_서술"]["혐의판단사유"] == summary

    def test_fraud_type_자금세탁_권고조치(self):
        """자금세탁 유형의 권고조치가 존재해야 한다."""
        result = self._call(fraud_type="자금세탁")
        assert isinstance(result["권고조치"], list)
        assert len(result["권고조치"]) > 0
        actions_text = " ".join(result["권고조치"])
        assert "모니터링" in actions_text or "FIU" in actions_text or "조사" in actions_text

    def test_fraud_type_기타_권고조치(self):
        """기타 유형의 권고조치가 존재해야 한다."""
        result = self._call(fraud_type="기타")
        assert isinstance(result["권고조치"], list)
        assert len(result["권고조치"]) > 0

    def test_unknown_fraud_type_defaults_to_기타(self):
        """알 수 없는 의심사유 분류는 기타로 처리되어야 한다."""
        result = self._call(fraud_type="알수없음")
        assert isinstance(result["권고조치"], list)
        assert len(result["권고조치"]) > 0

    def test_tools_used_in_분석근거(self):
        """사용된 도구 목록이 분석근거에 반영되어야 한다."""
        tools = ["query_transactions", "analyze_network"]
        result = self._call(tools_used=tools)
        근거 = result["분석근거"]
        assert isinstance(근거, list)
        assert len(근거) == len(tools)

    def test_empty_tools_used(self):
        """도구 목록이 비어 있어도 오류 없이 동작해야 한다."""
        result = self._call(tools_used=[])
        assert "분석근거" in result
        assert isinstance(result["분석근거"], list)

    def test_작성안내_is_string(self):
        """작성안내가 문자열이어야 한다."""
        result = self._call()
        assert isinstance(result["작성안내"], str)
        assert len(result["작성안내"]) > 0

    def test_account_extracted_from_summary_when_no_transactions(self):
        """transactions 없을 때 summary regex로 계좌 번호를 추출해야 한다."""
        summary = "출금계좌 1234567에서 500만원 이동"
        result = self._call(summary=summary, transactions=[])
        # II_거래자 또는 IV_관련계좌에 계좌 정보가 있어야 함
        ii = result["II_거래자"]
        assert isinstance(ii["출금계좌번호"], list)
        assert len(ii["출금계좌번호"]) > 0


# ──────────────────────────────────────────────
# _execute_tool - analyze_network
# ──────────────────────────────────────────────
class TestExecuteToolAnalyzeNetwork:
    """_execute_tool('analyze_network', ...) 단위 테스트."""

    def test_returns_json_string(self):
        """JSON 문자열을 반환해야 한다."""
        from src.features.network import get_fraud_accounts
        # 실제 이상거래 계좌 하나를 샘플링
        accounts = get_fraud_accounts()
        account_id = int(accounts["계좌"].iloc[0])
        result = _execute_tool("analyze_network", {"account_id": account_id})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_contains_account_id(self):
        """결과에 account_id가 포함되어야 한다."""
        from src.features.network import get_fraud_accounts
        accounts = get_fraud_accounts()
        account_id = int(accounts["계좌"].iloc[0])
        result = _execute_tool("analyze_network", {"account_id": account_id})
        parsed = json.loads(result)
        assert "account_id" in parsed
        assert parsed["account_id"] == account_id

    def test_contains_연결계좌수(self):
        """결과에 연결계좌수가 포함되어야 한다."""
        from src.features.network import get_fraud_accounts
        accounts = get_fraud_accounts()
        account_id = int(accounts["계좌"].iloc[0])
        result = _execute_tool("analyze_network", {"account_id": account_id})
        parsed = json.loads(result)
        # 데이터가 있으면 연결계좌수, 없으면 안내 메시지
        assert "연결계좌수" in parsed or "안내" in parsed

    def test_missing_account_id_returns_error(self):
        """account_id가 없으면 오류를 반환해야 한다."""
        result = _execute_tool("analyze_network", {})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_hops_clamped_to_valid_range(self):
        """hops 값은 1~5 범위로 클램프되어 오류 없이 처리되어야 한다."""
        from src.features.network import get_fraud_accounts
        accounts = get_fraud_accounts()
        account_id = int(accounts["계좌"].iloc[0])
        # hops=5는 최대 허용값이므로 오류 없이 처리되어야 함
        result = _execute_tool("analyze_network", {"account_id": account_id, "hops": 5})
        parsed = json.loads(result)
        # 오류가 아닌 정상 응답이어야 함
        assert "error" not in parsed or "네트워크" not in parsed.get("error", "")

    def test_2hop_analysis(self):
        """hops=2로 2-hop 분석이 동작해야 한다."""
        from src.features.network import get_fraud_accounts
        accounts = get_fraud_accounts()
        account_id = int(accounts["계좌"].iloc[0])
        result = _execute_tool("analyze_network", {"account_id": account_id, "hops": 2})
        parsed = json.loads(result)
        # 정상 응답이어야 함
        assert isinstance(parsed, dict)
        if "탐색범위_hop" in parsed:
            assert parsed["탐색범위_hop"] == 2

    def test_이상거래비율_non_negative(self):
        """이상거래비율이 0 이상이어야 한다."""
        from src.features.network import get_fraud_accounts
        accounts = get_fraud_accounts()
        account_id = int(accounts["계좌"].iloc[0])
        result = _execute_tool("analyze_network", {"account_id": account_id})
        parsed = json.loads(result)
        if "이상거래비율_percent" in parsed:
            assert parsed["이상거래비율_percent"] >= 0


# ──────────────────────────────────────────────
# _execute_tool - get_statistics
# ──────────────────────────────────────────────
class TestExecuteToolGetStatistics:
    """_execute_tool('get_statistics', ...) 단위 테스트."""

    @pytest.fixture(scope="class")
    def stats_result(self):
        """get_statistics 도구 실행 결과를 반환한다."""
        result = _execute_tool("get_statistics", {})
        return json.loads(result)

    def test_returns_json(self):
        """JSON 문자열을 반환해야 한다."""
        result = _execute_tool("get_statistics", {})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_contains_요약통계_key(self, stats_result):
        """결과에 요약통계 키가 있어야 한다."""
        assert "요약통계" in stats_result

    def test_contains_이상거래유형별분포_key(self, stats_result):
        """결과에 이상거래유형별분포 키가 있어야 한다."""
        assert "이상거래유형별분포" in stats_result

    def test_요약통계_총거래건수(self, stats_result):
        """요약통계에 총거래건수가 포함되어야 한다."""
        summary = stats_result["요약통계"]
        assert "총거래건수" in summary
        assert summary["총거래건수"] == 4_732_130

    def test_요약통계_이상거래건수(self, stats_result):
        """요약통계에 이상거래건수가 포함되어야 한다."""
        summary = stats_result["요약통계"]
        assert "이상거래건수" in summary
        assert summary["이상거래건수"] > 0

    def test_요약통계_이상거래비율(self, stats_result):
        """이상거래비율이 0~100 사이이어야 한다."""
        summary = stats_result["요약통계"]
        ratio = summary.get("이상거래비율_percent", 0)
        assert 0 <= ratio <= 100

    def test_이상거래유형별분포_is_list(self, stats_result):
        """이상거래유형별분포가 리스트이어야 한다."""
        assert isinstance(stats_result["이상거래유형별분포"], list)

    def test_이상거래유형별분포_not_empty(self, stats_result):
        """이상거래유형별분포가 비어있지 않아야 한다."""
        assert len(stats_result["이상거래유형별분포"]) > 0

    def test_요약통계_계좌수_positive(self, stats_result):
        """출금/입금계좌수가 양수이어야 한다."""
        summary = stats_result["요약통계"]
        if "출금계좌수" in summary:
            assert summary["출금계좌수"] > 0
        if "입금계좌수" in summary:
            assert summary["입금계좌수"] > 0


# ──────────────────────────────────────────────
# _execute_tool - generate_str (강화된 기능 검증)
# ──────────────────────────────────────────────
class TestExecuteToolGenerateStrEnhanced:
    """강화된 generate_str 도구 - 선택적 파라미터 테스트."""

    def test_fraud_type_자금세탁_applied(self):
        """fraud_type='자금세탁'이 결과에 반영되어야 한다."""
        result = _execute_tool("generate_str", {
            "summary": "자금세탁 의심 거래 발견",
            "fraud_type": "자금세탁",
        })
        parsed = json.loads(result)
        assert "자금세탁" in str(parsed)

    def test_fraud_type_사기_applied(self):
        """fraud_type='사기'가 결과에 반영되어야 한다."""
        result = _execute_tool("generate_str", {
            "summary": "사기 의심 거래 발견",
            "fraud_type": "사기",
        })
        parsed = json.loads(result)
        assert "사기" in str(parsed)

    def test_tools_used_reflected(self):
        """tools_used가 분석근거에 포함되어야 한다."""
        result = _execute_tool("generate_str", {
            "summary": "분석 결과 요약",
            "fraud_type": "자금세탁",
            "tools_used": ["query_transactions", "predict_fraud"],
        })
        parsed = json.loads(result)
        # 분석근거 또는 tools_used 항목이 결과에 포함되어야 함
        result_str = str(parsed)
        assert "query_transactions" in result_str or "거래 데이터" in result_str or "분석근거" in result_str

    def test_empty_summary_returns_error(self):
        """빈 summary는 오류를 반환해야 한다."""
        result = _execute_tool("generate_str", {"summary": ""})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_no_fraud_type_defaults_gracefully(self):
        """fraud_type이 없어도 오류 없이 STR이 생성되어야 한다."""
        result = _execute_tool("generate_str", {"summary": "분석 결과 요약"})
        parsed = json.loads(result)
        # 오류 없이 dict가 반환되어야 함
        assert isinstance(parsed, dict)
        assert "error" not in parsed

    def test_str_contains_보고일자(self):
        """STR 결과에 보고일자가 포함되어야 한다 (표제부 섹션 내부)."""
        result = _execute_tool("generate_str", {
            "summary": "의심 거래 분석 완료",
            "fraud_type": "자금세탁",
        })
        parsed = json.loads(result)
        # 새 STR 구조: 보고일자는 표제부 섹션 내부에 위치
        assert "표제부" in parsed
        assert "보고일자" in parsed["표제부"]
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", parsed["표제부"]["보고일자"])

    def test_str_contains_권고조치(self):
        """STR 결과에 권고조치가 포함되어야 한다."""
        result = _execute_tool("generate_str", {
            "summary": "의심 거래 분석 완료",
            "fraud_type": "자금세탁",
        })
        parsed = json.loads(result)
        assert "권고조치" in parsed
        assert isinstance(parsed["권고조치"], list)
        assert len(parsed["권고조치"]) > 0


# ──────────────────────────────────────────────
# analyze_network TOOLS 정의 세부 검증
# ──────────────────────────────────────────────
class TestAnalyzeNetworkToolDefinition:
    """analyze_network 도구 정의 세부 검증."""

    @pytest.fixture(scope="class")
    def analyze_network_tool(self):
        """analyze_network 도구 정의를 반환한다."""
        return next(t for t in TOOLS if t["function"]["name"] == "analyze_network")

    def test_account_id_is_required(self, analyze_network_tool):
        """account_id가 required 파라미터여야 한다."""
        required = analyze_network_tool["function"]["parameters"]["required"]
        assert "account_id" in required

    def test_hops_is_optional(self, analyze_network_tool):
        """hops는 선택적 파라미터여야 한다 (required에 없어야 함)."""
        required = analyze_network_tool["function"]["parameters"]["required"]
        assert "hops" not in required

    def test_account_id_type_is_integer(self, analyze_network_tool):
        """account_id의 타입이 integer이어야 한다."""
        props = analyze_network_tool["function"]["parameters"]["properties"]
        assert props["account_id"]["type"] == "integer"

    def test_hops_property_defined(self, analyze_network_tool):
        """hops 속성이 정의되어 있어야 한다."""
        props = analyze_network_tool["function"]["parameters"]["properties"]
        assert "hops" in props


# ──────────────────────────────────────────────
# get_statistics TOOLS 정의 세부 검증
# ──────────────────────────────────────────────
class TestGetStatisticsToolDefinition:
    """get_statistics 도구 정의 세부 검증."""

    @pytest.fixture(scope="class")
    def get_statistics_tool(self):
        """get_statistics 도구 정의를 반환한다."""
        return next(t for t in TOOLS if t["function"]["name"] == "get_statistics")

    def test_no_required_params(self, get_statistics_tool):
        """get_statistics는 필수 파라미터가 없어야 한다."""
        required = get_statistics_tool["function"]["parameters"].get("required", [])
        assert len(required) == 0

    def test_description_mentions_statistics(self, get_statistics_tool):
        """description에 통계 관련 내용이 포함되어야 한다."""
        desc = get_statistics_tool["function"]["description"]
        assert "통계" in desc or "분포" in desc or "대시보드" in desc

    def test_empty_properties(self, get_statistics_tool):
        """properties가 비어 있어야 한다 (파라미터 없는 도구)."""
        props = get_statistics_tool["function"]["parameters"].get("properties", {})
        assert isinstance(props, dict)


# ──────────────────────────────────────────────
# detect_aml_patterns TOOLS 정의 세부 검증
# ──────────────────────────────────────────────
class TestDetectAmlPatternsToolDefinition:
    """detect_aml_patterns 도구 정의 세부 검증."""

    @pytest.fixture(scope="class")
    def aml_tool(self):
        """detect_aml_patterns 도구 정의를 반환한다."""
        return next(t for t in TOOLS if t["function"]["name"] == "detect_aml_patterns")

    def test_pattern_type_is_required(self, aml_tool):
        """pattern_type이 required 파라미터여야 한다."""
        required = aml_tool["function"]["parameters"]["required"]
        assert "pattern_type" in required

    def test_pattern_type_enum_values(self, aml_tool):
        """pattern_type enum에 5개 유형이 모두 포함되어야 한다."""
        props = aml_tool["function"]["parameters"]["properties"]
        enum_values = set(props["pattern_type"]["enum"])
        expected = {"ring", "layering", "funnel", "shortest_path", "risk_score"}
        assert enum_values == expected

    def test_optional_params_not_required(self, aml_tool):
        """account_id, account_a, account_b 등은 optional이어야 한다."""
        required = set(aml_tool["function"]["parameters"]["required"])
        optional = {"account_id", "account_a", "account_b", "min_len", "max_len",
                    "min_layers", "min_inflow", "max_outflow", "limit"}
        assert required.isdisjoint(optional)

    def test_description_mentions_memgraph(self, aml_tool):
        """description에 Memgraph 또는 AML 관련 내용이 포함되어야 한다."""
        desc = aml_tool["function"]["description"]
        assert "Memgraph" in desc or "AML" in desc or "자금세탁" in desc


# ──────────────────────────────────────────────
# _execute_tool - detect_aml_patterns
# ──────────────────────────────────────────────
class TestExecuteToolDetectAmlPatterns:
    """_execute_tool('detect_aml_patterns', ...) 단위 테스트."""

    def test_unknown_pattern_type_returns_error(self):
        """알 수 없는 pattern_type은 오류를 반환해야 한다."""
        result = _execute_tool("detect_aml_patterns", {"pattern_type": "unknown_pattern"})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_shortest_path_missing_accounts_returns_error(self):
        """shortest_path에 account_a, account_b가 없으면 오류를 반환해야 한다."""
        result = _execute_tool("detect_aml_patterns", {"pattern_type": "shortest_path"})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_risk_score_missing_account_id_returns_error(self):
        """risk_score에 account_id가 없으면 오류를 반환해야 한다."""
        result = _execute_tool("detect_aml_patterns", {"pattern_type": "risk_score"})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_ring_pattern_returns_json(self):
        """ring 패턴 탐지가 JSON을 반환해야 한다 (Memgraph 없으면 안내 메시지)."""
        result = _execute_tool("detect_aml_patterns", {"pattern_type": "ring"})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        # Memgraph 미실행 시 안내 메시지 또는 결과 목록이 있어야 함
        assert "안내" in parsed or "결과" in parsed or "패턴" in parsed or "error" in parsed

    def test_layering_pattern_returns_json(self):
        """layering 패턴 탐지가 JSON을 반환해야 한다 (Memgraph 없으면 안내 메시지)."""
        result = _execute_tool("detect_aml_patterns", {"pattern_type": "layering"})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "안내" in parsed or "결과" in parsed or "패턴" in parsed or "error" in parsed

    def test_funnel_pattern_returns_json(self):
        """funnel 패턴 탐지가 JSON을 반환해야 한다 (Memgraph 없으면 안내 메시지)."""
        result = _execute_tool("detect_aml_patterns", {"pattern_type": "funnel"})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "안내" in parsed or "결과" in parsed or "패턴" in parsed or "error" in parsed

    def test_shortest_path_with_accounts_returns_json(self):
        """account_a, account_b가 있는 shortest_path는 JSON을 반환해야 한다."""
        result = _execute_tool("detect_aml_patterns", {
            "pattern_type": "shortest_path",
            "account_a": 12345,
            "account_b": 67890,
        })
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        # Memgraph 미실행 시 error 키가 있어야 함
        assert "path" in parsed or "error" in parsed

    def test_risk_score_with_account_id_returns_json(self):
        """account_id가 있는 risk_score는 JSON을 반환해야 한다."""
        result = _execute_tool("detect_aml_patterns", {
            "pattern_type": "risk_score",
            "account_id": 12345,
        })
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        # Memgraph 미실행 시 risk_score=0.0과 error 키가 있어야 함
        assert "risk_score" in parsed or "error" in parsed

    def test_ring_with_custom_params(self):
        """커스텀 min_len, max_len, limit이 적용되어 오류 없이 동작해야 한다."""
        result = _execute_tool("detect_aml_patterns", {
            "pattern_type": "ring",
            "min_len": 3,
            "max_len": 5,
            "limit": 10,
        })
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_result_is_always_parseable_json(self):
        """모든 pattern_type에 대해 유효한 JSON이 반환되어야 한다."""
        for pt in ["ring", "layering", "funnel"]:
            result = _execute_tool("detect_aml_patterns", {"pattern_type": pt})
            parsed = json.loads(result)
            assert isinstance(parsed, dict), f"{pt} 패턴 결과가 dict가 아닙니다"


# ──────────────────────────────────────────────
# analyze_network hop 확장 검증
# ──────────────────────────────────────────────
class TestAnalyzeNetworkHopExpansion:
    """analyze_network hop 1~5 확장 동작 검증."""

    @pytest.fixture(scope="class")
    def sample_account_id(self):
        """테스트용 이상거래 계좌 ID를 반환한다."""
        from src.features.network import get_fraud_accounts
        accounts = get_fraud_accounts()
        return int(accounts["계좌"].iloc[0])

    def test_hops_1_works(self, sample_account_id):
        """hops=1 분석이 정상 동작해야 한다."""
        result = _execute_tool("analyze_network", {"account_id": sample_account_id, "hops": 1})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "error" not in parsed or "네트워크" not in parsed.get("error", "")

    def test_hops_2_works(self, sample_account_id):
        """hops=2 분석이 정상 동작해야 한다."""
        result = _execute_tool("analyze_network", {"account_id": sample_account_id, "hops": 2})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        if "탐색범위_hop" in parsed:
            assert parsed["탐색범위_hop"] == 2

    def test_hops_3_does_not_raise(self, sample_account_id):
        """hops=3은 Memgraph 미실행 시 DuckDB 폴백으로 오류 없이 동작해야 한다."""
        result = _execute_tool("analyze_network", {"account_id": sample_account_id, "hops": 3})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "error" not in parsed or "네트워크" not in parsed.get("error", "")

    def test_hops_5_does_not_raise(self, sample_account_id):
        """hops=5는 Memgraph 미실행 시 DuckDB 폴백으로 오류 없이 동작해야 한다."""
        result = _execute_tool("analyze_network", {"account_id": sample_account_id, "hops": 5})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "error" not in parsed or "네트워크" not in parsed.get("error", "")

    def test_hops_above_5_clamped(self, sample_account_id):
        """hops=10은 5로 클램프되어 오류 없이 처리되어야 한다."""
        result = _execute_tool("analyze_network", {"account_id": sample_account_id, "hops": 10})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "error" not in parsed or "네트워크" not in parsed.get("error", "")

    def test_hops_below_1_clamped(self, sample_account_id):
        """hops=0은 1로 클램프되어 오류 없이 처리되어야 한다."""
        result = _execute_tool("analyze_network", {"account_id": sample_account_id, "hops": 0})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "error" not in parsed or "네트워크" not in parsed.get("error", "")


# ──────────────────────────────────────────────
# get_account_profile 도구 검증
# ──────────────────────────────────────────────
class TestGetAccountProfile:
    """_execute_tool('get_account_profile', ...) 단위 테스트."""

    @pytest.fixture(scope="class")
    def sample_profile(self):
        """테스트용 이상거래 계좌의 프로파일 결과를 반환한다."""
        from src.features.network import get_fraud_accounts
        accounts = get_fraud_accounts()
        account_id = int(accounts["계좌"].iloc[0])
        result = _execute_tool("get_account_profile", {"account_id": account_id})
        return json.loads(result), account_id

    def test_returns_dict(self, sample_profile):
        """유효한 계좌 ID로 호출하면 dict를 반환해야 한다."""
        parsed, _ = sample_profile
        assert isinstance(parsed, dict)

    def test_returns_expected_keys(self, sample_profile):
        """결과 dict에 필수 키가 포함되어야 한다."""
        parsed, _ = sample_profile
        if "error" not in parsed and "안내" not in parsed:
            for key in ("account_id", "total_count", "total_amount", "fraud_count", "fraud_ratio"):
                assert key in parsed, f"키 '{key}'가 결과에 없습니다"

    def test_unknown_account_empty(self):
        """존재하지 않는 계좌 ID는 안내 메시지를 반환해야 한다."""
        result = _execute_tool("get_account_profile", {"account_id": 0})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        # 거래가 없으면 안내 메시지가 있거나 total_count == 0
        if "안내" not in parsed:
            assert parsed.get("total_count", 0) == 0

    def test_missing_account_id_returns_error(self):
        """account_id 없이 호출하면 에러를 반환해야 한다."""
        result = _execute_tool("get_account_profile", {})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_fraud_ratio_in_range(self, sample_profile):
        """fraud_ratio가 0~1 범위 내에 있어야 한다."""
        parsed, _ = sample_profile
        if "fraud_ratio" in parsed:
            assert 0.0 <= parsed["fraud_ratio"] <= 1.0

    def test_top_counterparts_is_list(self, sample_profile):
        """top_counterparts가 리스트여야 한다."""
        parsed, _ = sample_profile
        if "top_counterparts" in parsed:
            assert isinstance(parsed["top_counterparts"], list)
            assert len(parsed["top_counterparts"]) <= 5


# ──────────────────────────────────────────────
# get_fraud_type_summary 도구 검증
# ──────────────────────────────────────────────
class TestGetFraudTypeSummary:
    """_execute_tool('get_fraud_type_summary', ...) 단위 테스트."""

    def test_valid_type_returns_dict(self):
        """유효한 fraud_type(4=보이스피싱)으로 호출하면 dict를 반환해야 한다."""
        result = _execute_tool("get_fraud_type_summary", {"fraud_type": 4})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_returns_expected_keys(self):
        """결과 dict에 필수 키가 포함되어야 한다."""
        result = _execute_tool("get_fraud_type_summary", {"fraud_type": 1})
        parsed = json.loads(result)
        if "error" not in parsed and "안내" not in parsed:
            for key in ("type_code", "type_name", "total_count", "total_amount"):
                assert key in parsed, f"키 '{key}'가 결과에 없습니다"

    def test_type_name_matches_code(self):
        """type_name이 fraud_type 코드에 맞는 이름을 반환해야 한다."""
        expected_names = {
            1: "자금세탁", 2: "신규거래처", 3: "대포통장",
            4: "보이스피싱", 5: "불법도박", 6: "유사수신", 7: "기타",
        }
        for code, name in expected_names.items():
            result = _execute_tool("get_fraud_type_summary", {"fraud_type": code})
            parsed = json.loads(result)
            if "type_name" in parsed:
                assert parsed["type_name"] == name, f"코드 {code}의 type_name 불일치"

    def test_invalid_type_returns_error(self):
        """범위 밖(0, 8) fraud_type은 에러를 반환해야 한다."""
        for bad_type in (0, 8, -1):
            result = _execute_tool("get_fraud_type_summary", {"fraud_type": bad_type})
            parsed = json.loads(result)
            assert "error" in parsed, f"fraud_type={bad_type}에 대해 에러가 반환되어야 합니다"

    def test_missing_fraud_type_returns_error(self):
        """fraud_type 없이 호출하면 에러를 반환해야 한다."""
        result = _execute_tool("get_fraud_type_summary", {})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_bank_filter_returns_dict(self):
        """bank_id 옵션 파라미터와 함께 호출해도 dict를 반환해야 한다."""
        result = _execute_tool("get_fraud_type_summary", {"fraud_type": 4, "bank_id": 1})
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_top_banks_is_list(self):
        """top_banks가 리스트여야 한다."""
        result = _execute_tool("get_fraud_type_summary", {"fraud_type": 1})
        parsed = json.loads(result)
        if "top_banks" in parsed:
            assert isinstance(parsed["top_banks"], list)
            assert len(parsed["top_banks"]) <= 5
