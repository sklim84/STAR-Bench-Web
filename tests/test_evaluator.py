"""evaluator.py 단위 테스트."""

import json
import pytest

from _paper.scripts.evaluator import (
    evaluate_case,
    aggregate_results,
    normalize_parse_fail_result,
    classify_exception_error_type,
    normalize_exception_result,
    _evaluate_order,
    _lcs_length,
    _values_equal,
    _get_expected_arg_keys,
)


# ---------------------------------------------------------------------------
# 픽스처 헬퍼
# ---------------------------------------------------------------------------


def _make_event(name: str, arguments: dict, result: dict | None = None) -> dict:
    return {
        "name": name,
        "arguments": arguments,
        "result": json.dumps(result or {"ok": True}, ensure_ascii=False),
    }


def _sql_event(sql: str, error: str | None = None) -> dict:
    result = {"error": error} if error else {"결과": [], "total": 0}
    return _make_event("query_transactions", {"sql": sql}, result)


# ---------------------------------------------------------------------------
# TestEvaluateCase
# ---------------------------------------------------------------------------


class TestEvaluateCase:

    def test_primary_tool_hit_true(self):
        case = {
            "id": "t1",
            "expected": {"primary_tool": "get_statistics",
                         "tools_must_include": ["get_statistics"]},
        }
        events = [_make_event("get_statistics", {})]
        result = evaluate_case(case, events)
        assert result["primary_tool_hit"] is True
        assert result["tool_recall"] == 1.0

    def test_primary_tool_hit_false(self):
        case = {
            "id": "t2",
            "expected": {"primary_tool": "get_statistics",
                         "tools_must_include": ["get_statistics"]},
        }
        events = [_make_event("query_transactions", {"sql": "SELECT 1"})]
        result = evaluate_case(case, events)
        assert result["primary_tool_hit"] is False
        assert result["tool_recall"] == 0.0

    def test_tool_recall_partial(self):
        case = {
            "id": "t3",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions", "analyze_network"],
            },
        }
        events = [_make_event("query_transactions", {"sql": "SELECT 1"})]
        result = evaluate_case(case, events)
        assert result["tool_recall"] == 0.5

    def test_tool_precision(self):
        """기대 도구 외 불필요 도구 호출 시 precision 감소."""
        case = {
            "id": "t4",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions"],
            },
        }
        events = [
            _make_event("query_transactions", {"sql": "SELECT 1"}),
            _make_event("get_statistics", {}),
        ]
        result = evaluate_case(case, events)
        assert result["tool_precision"] == 0.5

    def test_no_tool_calls(self):
        case = {
            "id": "t5",
            "expected": {"primary_tool": "get_statistics",
                         "tools_must_include": ["get_statistics"]},
        }
        result = evaluate_case(case, [])
        assert result["primary_tool_hit"] is False
        assert result["tool_recall"] == 0.0
        assert result["score"] < 0.5

    def test_no_expected_tools(self):
        """expected가 비어 있으면 항상 최대 점수."""
        case = {"id": "t6", "expected": {}}
        result = evaluate_case(case, [])
        # primary_tool_hit: True (primary_tool 없음)
        # tool_recall: 1.0, tool_precision: 1.0, param_accuracy: 1.0, order_score: 1.0
        assert result["score"] == 1.0

    # --- error_type 분류 테스트 ---

    def test_error_type_correct(self):
        """score == 1.0 이면 error_type == 'correct'."""
        case = {
            "id": "e1",
            "expected": {"primary_tool": "get_statistics",
                         "tools_must_include": ["get_statistics"]},
        }
        events = [_make_event("get_statistics", {})]
        result = evaluate_case(case, events)
        assert result["score"] == 1.0
        assert result["error_type"] == "correct"

    def test_error_type_wrong_func(self):
        """주 도구를 호출하지 않으면 error_type == 'wrong_func'."""
        case = {
            "id": "e2",
            "expected": {"primary_tool": "get_statistics",
                         "tools_must_include": ["get_statistics"]},
        }
        events = [_make_event("query_transactions", {"sql": "SELECT 1"})]
        result = evaluate_case(case, events)
        assert result["error_type"] == "wrong_func"

    def test_error_type_wrong_value(self):
        """도구는 호출했지만 파라미터 값이 틀리면 error_type == 'wrong_value'."""
        case = {
            "id": "e3",
            "expected": {
                "primary_tool": "analyze_network",
                "tools_must_include": ["analyze_network"],
                "param_checks": {"analyze_network": {"account_id": 1234567890}},
            },
        }
        events = [_make_event("analyze_network", {"account_id": 9999})]
        result = evaluate_case(case, events)
        assert result["error_type"] == "wrong_value"

    def test_error_type_missing_param(self):
        """primary_tool은 호출됐지만 tools_must_include 일부 누락 → 'missing_param'."""
        case = {
            "id": "e4",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions", "analyze_network"],
            },
        }
        events = [_make_event("query_transactions", {"sql": "SELECT 1"})]
        result = evaluate_case(case, events)
        assert result["error_type"] == "missing_param"

    # --- Irrelevance Detection 테스트 ---

    def test_irrelevance_no_tool_correct(self):
        """Irrelevance 케이스에서 도구를 호출하지 않으면 만점."""
        case = {"id": "irr1", "expected": {"primary_tool": "", "tools_must_include": []}}
        result = evaluate_case(case, [])
        assert result["tool_precision"] == 1.0
        assert result["score"] == 1.0
        assert result["error_type"] == "correct"

    def test_irrelevance_tool_called_penalized(self):
        """Irrelevance 케이스에서 도구를 호출하면 tool_precision == 0.0."""
        case = {"id": "irr2", "expected": {"primary_tool": "", "tools_must_include": []}}
        events = [_make_event("get_statistics", {})]
        result = evaluate_case(case, events)
        assert result["tool_precision"] == 0.0
        assert result["score"] == pytest.approx(0.9, abs=1e-4)
        assert result["error_type"] == "hallucinated_call"


# ---------------------------------------------------------------------------
# TestParamChecks
# ---------------------------------------------------------------------------


class TestParamChecks:

    def test_sql_contains_pass(self):
        case = {
            "id": "p1",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions"],
                "param_checks": {
                    "query_transactions": {
                        "sql_contains": ["134", "이상거래여부"],
                    }
                },
            },
        }
        events = [_sql_event("SELECT * FROM hofinet WHERE 출금금융회사일련번호=134 AND 이상거래여부=1")]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 1.0

    def test_sql_contains_partial_fail(self):
        case = {
            "id": "p2",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions"],
                "param_checks": {
                    "query_transactions": {
                        "sql_contains": ["134", "이상거래여부"],
                    }
                },
            },
        }
        # '이상거래여부' 없음
        events = [_sql_event("SELECT * FROM hofinet WHERE 출금금융회사일련번호=134")]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 0.0  # sql_contains는 단일 check 항목

    def test_sql_valid_pass(self):
        case = {
            "id": "p3",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions"],
                "param_checks": {
                    "query_transactions": {"sql_valid": True}
                },
            },
        }
        events = [_sql_event("SELECT 1")]  # 오류 없음
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 1.0

    def test_sql_valid_fail(self):
        case = {
            "id": "p4",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions"],
                "param_checks": {
                    "query_transactions": {"sql_valid": True}
                },
            },
        }
        events = [_sql_event("BAD SQL", error="파서 오류")]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 0.0

    def test_account_id_exact_match(self):
        case = {
            "id": "p5",
            "expected": {
                "primary_tool": "analyze_network",
                "tools_must_include": ["analyze_network"],
                "param_checks": {
                    "analyze_network": {"account_id": 1234567890}
                },
            },
        }
        events = [_make_event("analyze_network", {"account_id": 1234567890, "hops": 2})]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 1.0

    def test_account_id_wrong(self):
        case = {
            "id": "p6",
            "expected": {
                "primary_tool": "analyze_network",
                "tools_must_include": ["analyze_network"],
                "param_checks": {
                    "analyze_network": {"account_id": 1234567890}
                },
            },
        }
        events = [_make_event("analyze_network", {"account_id": 9999999999})]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 0.0

    def test_hops_min_pass(self):
        case = {
            "id": "p7",
            "expected": {
                "primary_tool": "analyze_network",
                "tools_must_include": ["analyze_network"],
                "param_checks": {
                    "analyze_network": {"account_id": 1234567890, "hops_min": 3}
                },
            },
        }
        events = [_make_event("analyze_network", {"account_id": 1234567890, "hops": 3})]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 1.0

    def test_hops_min_fail(self):
        case = {
            "id": "p8",
            "expected": {
                "primary_tool": "analyze_network",
                "tools_must_include": ["analyze_network"],
                "param_checks": {
                    "analyze_network": {"account_id": 1234567890, "hops_min": 3}
                },
            },
        }
        events = [_make_event("analyze_network", {"account_id": 1234567890, "hops": 2})]
        result = evaluate_case(case, events)
        # account_id=pass, hops_min=fail => 1/2
        assert result["param_accuracy"] == 0.5

    def test_pattern_type_exact(self):
        case = {
            "id": "p9",
            "expected": {
                "primary_tool": "detect_aml_patterns",
                "tools_must_include": ["detect_aml_patterns"],
                "param_checks": {
                    "detect_aml_patterns": {"pattern_type": "ring"}
                },
            },
        }
        events = [_make_event("detect_aml_patterns", {"pattern_type": "ring"})]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 1.0

    def test_missing_tool_all_param_fail(self):
        """도구가 호출되지 않으면 모든 param_check 실패."""
        case = {
            "id": "p10",
            "expected": {
                "primary_tool": "predict_fraud",
                "tools_must_include": ["predict_fraud"],
                "param_checks": {
                    "predict_fraud": {
                        "거래시간대": 9,
                        "거래금액": 5000000,
                    }
                },
            },
        }
        events = [_make_event("get_statistics", {})]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 0.0

    # --- hallucinated_param_count 테스트 ---

    def test_hallucinated_params_detected(self):
        """GT에 없는 파라미터 키를 모델이 생성하면 hallucinated_param_count에 집계된다."""
        case = {
            "id": "h1",
            "expected": {
                "primary_tool": "analyze_network",
                "tools_must_include": ["analyze_network"],
                "param_checks": {
                    "analyze_network": {"account_id": 1234567890},
                },
            },
        }
        # 기대: account_id만. 실제: account_id + unexpected_param + another_extra
        events = [_make_event("analyze_network", {
            "account_id": 1234567890,
            "unexpected_param": "foo",
            "another_extra": 42,
        })]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 1.0       # account_id는 정확
        assert result["hallucinated_param_count"] == 2  # 2개 할루시네이션

    def test_no_hallucinated_params(self):
        """파라미터가 GT와 일치하면 hallucinated_param_count == 0."""
        case = {
            "id": "h2",
            "expected": {
                "primary_tool": "analyze_network",
                "tools_must_include": ["analyze_network"],
                "param_checks": {
                    "analyze_network": {"account_id": 1234567890, "hops_min": 2},
                },
            },
        }
        # hops_min 체크 → 실제 arg 키는 "hops"
        events = [_make_event("analyze_network", {"account_id": 1234567890, "hops": 3})]
        result = evaluate_case(case, events)
        assert result["hallucinated_param_count"] == 0

    def test_hallucinated_params_sql_tool(self):
        """sql_contains/sql_valid 체크 시 'sql' 키는 할루시네이션으로 집계되지 않는다."""
        case = {
            "id": "h3",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions"],
                "param_checks": {
                    "query_transactions": {
                        "sql_contains": ["이상거래여부"],
                        "sql_valid": True,
                    },
                },
            },
        }
        events = [_sql_event("SELECT * FROM hofinet WHERE 이상거래여부=1")]
        result = evaluate_case(case, events)
        assert result["hallucinated_param_count"] == 0  # "sql"은 기대 키에 포함

    def test_result_contains_pass(self):
        """result_contains: 실행 결과 문자열에 키워드가 포함되면 통과."""
        case = {
            "id": "r1",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions"],
                "param_checks": {
                    "query_transactions": {
                        "sql_contains": ["이상거래여부"],
                        "result_contains": ["결과", "총건수"],
                    }
                },
            },
        }
        events = [_make_event(
            "query_transactions",
            {"sql": "SELECT * FROM hofinet WHERE 이상거래여부=1"},
            result={"결과": [{"a": 1}], "총건수": 5},
        )]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 1.0

    def test_result_row_count_min_pass(self):
        """result_row_count_min: 결과가 최소 행 수 이상이면 통과."""
        case = {
            "id": "r2",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions"],
                "param_checks": {
                    "query_transactions": {
                        "sql_valid": True,
                        "result_row_count_min": 1,
                    }
                },
            },
        }
        events = [_make_event(
            "query_transactions",
            {"sql": "SELECT 1"},
            result={"결과": [{"x": 1}, {"x": 2}], "총건수": 2},
        )]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 1.0

    def test_result_row_count_min_fail(self):
        """result_row_count_min: 결과가 최소 행 수 미만이면 실패."""
        case = {
            "id": "r3",
            "expected": {
                "primary_tool": "query_transactions",
                "tools_must_include": ["query_transactions"],
                "param_checks": {
                    "query_transactions": {"result_row_count_min": 5},
                },
            },
        }
        events = [_make_event(
            "query_transactions",
            {"sql": "SELECT 1"},
            result={"결과": [], "총건수": 0},
        )]
        result = evaluate_case(case, events)
        assert result["param_accuracy"] == 0.0


# ---------------------------------------------------------------------------
# TestOrderScore
# ---------------------------------------------------------------------------


class TestOrderScore:

    def test_perfect_order(self):
        score = _evaluate_order(
            ["get_statistics", "query_transactions", "predict_fraud"],
            ["get_statistics", "query_transactions", "predict_fraud"],
        )
        assert score == 1.0

    def test_reversed_order(self):
        score = _evaluate_order(
            ["get_statistics", "query_transactions"],
            ["query_transactions", "get_statistics"],
        )
        # LCS = 1 (e.g., "get_statistics" or "query_transactions") / 2
        assert score == 0.5

    def test_partial_order(self):
        # tool_order에 없는 도구가 중간에 끼어 있어도 LCS 기준 평가
        score = _evaluate_order(
            ["query_transactions", "analyze_network"],
            ["get_statistics", "query_transactions", "analyze_network"],
        )
        assert score == 1.0

    def test_empty_called_tools(self):
        score = _evaluate_order(["query_transactions"], [])
        assert score == 0.0

    def test_empty_order(self):
        score = _evaluate_order([], ["query_transactions"])
        assert score == 1.0


# ---------------------------------------------------------------------------
# TestLcsLength
# ---------------------------------------------------------------------------


class TestLcsLength:

    def test_identical(self):
        assert _lcs_length(["a", "b", "c"], ["a", "b", "c"]) == 3

    def test_disjoint(self):
        assert _lcs_length(["a", "b"], ["c", "d"]) == 0

    def test_subsequence(self):
        assert _lcs_length(["a", "b", "c"], ["a", "c"]) == 2


# ---------------------------------------------------------------------------
# TestValuesEqual
# ---------------------------------------------------------------------------


class TestValuesEqual:

    def test_int_int(self):
        assert _values_equal(1234567890, 1234567890) is True

    def test_str_int(self):
        assert _values_equal("1234567890", 1234567890) is True

    def test_different_values(self):
        assert _values_equal(1, 2) is False

    def test_string_match(self):
        assert _values_equal("ring", "ring") is True


# ---------------------------------------------------------------------------
# TestAggregateResults
# ---------------------------------------------------------------------------


class TestAggregateResults:

    def test_empty(self):
        assert aggregate_results([]) == {}

    def test_basic(self):
        results = [
            {"score": 0.8, "tool_recall": 1.0, "tool_precision": 1.0,
             "param_accuracy": 0.8, "order_score": 1.0,
             "primary_tool_hit": True, "difficulty": "easy"},
            {"score": 0.6, "tool_recall": 0.5, "tool_precision": 0.5,
             "param_accuracy": 0.6, "order_score": 1.0,
             "primary_tool_hit": False, "difficulty": "medium"},
        ]
        agg = aggregate_results(results)
        assert agg["total"] == 2
        assert agg["avg_score"] == pytest.approx(0.7, abs=0.01)
        assert agg["primary_tool_hit_rate"] == 0.5
        assert "easy" in agg["by_difficulty"]
        assert "medium" in agg["by_difficulty"]

    def test_by_error_type(self):
        """by_error_type 집계가 error_type별 빈도를 정확히 반환한다."""
        results = [
            {"score": 1.0, "tool_recall": 1.0, "tool_precision": 1.0,
             "param_accuracy": 1.0, "order_score": 1.0,
             "primary_tool_hit": True, "difficulty": "easy",
             "error_type": "correct", "hallucinated_param_count": 0},
            {"score": 0.45, "tool_recall": 0.0, "tool_precision": 1.0,
             "param_accuracy": 1.0, "order_score": 1.0,
             "primary_tool_hit": False, "difficulty": "medium",
             "error_type": "wrong_func", "hallucinated_param_count": 0},
            {"score": 0.9, "tool_recall": 1.0, "tool_precision": 0.0,
             "param_accuracy": 1.0, "order_score": 1.0,
             "primary_tool_hit": True, "difficulty": "easy",
             "error_type": "hallucinated_call", "hallucinated_param_count": 3},
        ]
        agg = aggregate_results(results)
        assert agg["by_error_type"]["correct"] == 1
        assert agg["by_error_type"]["wrong_func"] == 1
        assert agg["by_error_type"]["hallucinated_call"] == 1
        assert agg["total_hallucinated_params"] == 3

    def test_by_error_type_missing_field(self):
        """error_type 필드가 없는 결과는 by_error_type 집계에서 무시된다."""
        results = [
            {"score": 0.8, "tool_recall": 1.0, "tool_precision": 1.0,
             "param_accuracy": 0.8, "order_score": 1.0,
             "primary_tool_hit": True, "difficulty": "easy"},
        ]
        agg = aggregate_results(results)
        assert agg["by_error_type"] == {}
        assert agg["total_hallucinated_params"] == 0


class TestNormalizeParseFailResult:

    def test_forces_zero_metrics(self):
        result = {
            "id": "x1",
            "difficulty": "easy",
            "primary_tool_hit": True,
            "tool_recall": 1.0,
            "tool_precision": 1.0,
            "param_accuracy": 1.0,
            "param_key_accuracy": 1.0,
            "order_score": 1.0,
            "score": 1.0,
            "error_type": "correct",
            "called_tools": ["get_statistics"],
        }
        fixed = normalize_parse_fail_result(result)

        assert fixed["primary_tool_hit"] is False
        assert fixed["tool_recall"] == 0.0
        assert fixed["tool_precision"] == 0.0
        assert fixed["param_accuracy"] == 0.0
        assert fixed["param_key_accuracy"] == 0.0
        assert fixed["order_score"] == 0.0
        assert fixed["score"] == 0.0
        assert fixed["error_type"] == "parse_fail"
        assert fixed["called_tools"] == []
        assert fixed["id"] == "x1"


class TestClassifyExceptionErrorType:

    def test_parse_fail_keywords(self):
        exc = ValueError("Couldn't extract tool call from JSON response")
        assert classify_exception_error_type(exc) == "parse_fail"

    def test_timeout_keywords(self):
        exc = TimeoutError("request timed out")
        assert classify_exception_error_type(exc) == "timeout_error"

    def test_connection_keywords(self):
        exc = ConnectionError("Connection refused")
        assert classify_exception_error_type(exc) == "connection_error"

    def test_api_keywords(self):
        exc = RuntimeError("HTTP 429 rate limit")
        assert classify_exception_error_type(exc) == "api_error"

    def test_other(self):
        exc = RuntimeError("unexpected failure")
        assert classify_exception_error_type(exc) == "other"


class TestNormalizeExceptionResult:

    def test_non_parse_exception_forces_zero_score(self):
        result = {
            "id": "x2",
            "score": 1.0,
            "primary_tool_hit": True,
            "tool_recall": 1.0,
            "tool_precision": 1.0,
            "param_accuracy": 1.0,
            "param_key_accuracy": 1.0,
            "order_score": 1.0,
            "error_type": "correct",
            "called_tools": ["get_statistics"],
        }
        fixed = normalize_exception_result(result, TimeoutError("timed out"))
        assert fixed["score"] == 0.0
        assert fixed["error_type"] == "timeout_error"
        assert fixed["called_tools"] == []

    def test_parse_exception_maps_to_parse_fail(self):
        result = {
            "id": "x3",
            "score": 0.8,
            "primary_tool_hit": True,
            "tool_recall": 1.0,
            "tool_precision": 1.0,
            "param_accuracy": 1.0,
            "param_key_accuracy": 1.0,
            "order_score": 1.0,
            "error_type": "correct",
            "called_tools": ["query_transactions"],
        }
        fixed = normalize_exception_result(result, ValueError("parser error"))
        assert fixed["score"] == 0.0
        assert fixed["error_type"] == "parse_fail"


# ---------------------------------------------------------------------------
# TestGetExpectedArgKeys
# ---------------------------------------------------------------------------


class TestGetExpectedArgKeys:

    def test_sql_checks_map_to_sql(self):
        checks = {"sql_contains": ["키워드"], "sql_valid": True}
        keys = _get_expected_arg_keys(checks)
        assert "sql" in keys
        assert "sql_contains" not in keys
        assert "sql_valid" not in keys

    def test_hops_checks_map_to_hops(self):
        checks = {"hops_min": 2, "hops_max": 5}
        keys = _get_expected_arg_keys(checks)
        assert "hops" in keys
        assert "hops_min" not in keys
        assert "hops_max" not in keys

    def test_direct_param_keys(self):
        checks = {"account_id": 1234567890, "pattern_type": "ring"}
        keys = _get_expected_arg_keys(checks)
        assert "account_id" in keys
        assert "pattern_type" in keys

    def test_mixed_checks(self):
        checks = {"sql_contains": ["134"], "account_id": 99, "hops_min": 1}
        keys = _get_expected_arg_keys(checks)
        assert keys == {"sql", "hops", "account_id"}
