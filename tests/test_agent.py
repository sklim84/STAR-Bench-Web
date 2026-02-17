"""기능4: AI 분석 에이전트 (src/features/agent.py) 단위 테스트.

검증 항목:
- TOOLS 정의가 OpenAI function calling 스펙을 충족하는지
- SYSTEM_PROMPT가 올바른 내용을 포함하는지
- _execute_tool()이 각 도구를 올바르게 실행하는지
- _execute_tool()의 SELECT 전용 제한이 동작하는지
- _message_to_dict()가 올바른 dict를 반환하는지
- chat()이 OpenAI API 호출 없이 mock으로 정상 동작하는지
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from src.features.agent import (
    TOOLS,
    SYSTEM_PROMPT,
    MAX_TOOL_ROUNDS,
    _execute_tool,
    _message_to_dict,
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
        """도구가 정확히 3개이어야 한다."""
        assert len(TOOLS) == 3

    def test_tools_have_required_structure(self):
        """각 도구가 type과 function 키를 가져야 한다."""
        for tool in TOOLS:
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool

    def test_tool_names(self):
        """도구 이름이 기대하는 값과 일치하는지 확인."""
        names = {tool["function"]["name"] for tool in TOOLS}
        expected = {"query_transactions", "predict_fraud", "generate_str"}
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

        agent.py의 _execute_tool은 'from src.features.detector import load_model'을
        로컬 임포트로 실행하므로, 패치 대상은 detector 모듈의 load_model이어야 한다.
        """
        with patch("src.features.detector.load_model", return_value=None):
            result = _execute_tool("predict_fraud", sample_transaction)
            parsed = json.loads(result)
            assert "error" in parsed

    def test_with_mock_model_returns_probability(self, sample_transaction):
        """Mock 모델을 사용하여 확률이 반환되는지 확인."""
        mock_model = MagicMock()
        import numpy as np
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])

        with patch("src.features.detector.load_model", return_value=mock_model):
            result = _execute_tool("predict_fraud", sample_transaction)
            parsed = json.loads(result)
            assert "이상거래확률" in parsed
            assert 0 <= parsed["이상거래확률"] <= 1

    def test_probability_rounded_to_4_decimals(self, sample_transaction):
        """확률이 소수점 4자리까지 반올림되는지 확인."""
        mock_model = MagicMock()
        import numpy as np
        mock_model.predict_proba.return_value = np.array([[0.123456, 0.876544]])

        with patch("src.features.detector.load_model", return_value=mock_model):
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
        """결과에 보고서 키가 있는지 확인."""
        result = _execute_tool("generate_str", {"summary": "출금계좌 123에서 이상거래 탐지"})
        parsed = json.loads(result)
        assert "보고서" in parsed

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
        assert "안내" in parsed or "내용" in parsed


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
        """chat()이 (content, messages) 튜플을 반환하는지 확인."""
        from src.features.agent import chat

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response("분석 완료")

        with patch("src.features.agent.OpenAI", return_value=mock_client):
            result = chat([{"role": "user", "content": "이상거래 현황을 알려줘"}])

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_chat_returns_assistant_content(self):
        """chat()이 어시스턴트 응답 내용을 반환하는지 확인."""
        from src.features.agent import chat

        expected_content = "2024년 이상거래는 총 14,490건입니다."
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response(expected_content)

        with patch("src.features.agent.OpenAI", return_value=mock_client):
            content, messages = chat([{"role": "user", "content": "이상거래 현황"}])

        assert content == expected_content

    def test_chat_appends_messages(self):
        """chat()이 응답 메시지를 대화 히스토리에 추가하는지 확인."""
        from src.features.agent import chat

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response("응답")

        messages = [{"role": "user", "content": "질문"}]
        with patch("src.features.agent.OpenAI", return_value=mock_client):
            content, updated_messages = chat(messages)

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
            content, messages = chat([{"role": "user", "content": "이상거래 건수 알려줘"}])

        assert final_content in content
        # tool 메시지가 히스토리에 포함되어야 함
        roles = [m["role"] for m in messages]
        assert "tool" in roles

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
