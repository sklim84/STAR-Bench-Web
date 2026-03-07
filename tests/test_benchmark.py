"""benchmark.py 헬퍼 함수 단위 테스트."""

import json
from pathlib import Path

from _paper.scripts import benchmark as rmm


def test_rename_schema_keys_and_revert_args_keys_recursive():
    schema = {
        "type": "object",
        "properties": {
            "거래금액": {"type": "integer"},
            "transactions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"출금계좌일련번호": {"type": "integer"}},
                    "required": ["출금계좌일련번호"],
                },
            },
        },
        "required": ["거래금액"],
    }
    renamed = rmm._rename_schema_keys(schema)
    assert "transaction_amount" in renamed["properties"]
    assert renamed["required"] == ["transaction_amount"]
    nested_required = renamed["properties"]["transactions"]["items"]["required"]
    assert nested_required == ["sender_account_id"]

    reverted = rmm._revert_args_keys(
        {"transaction_amount": 1000, "transactions": [{"sender_account_id": 123}]}
    )
    assert reverted["거래금액"] == 1000
    assert reverted["transactions"][0]["출금계좌일련번호"] == 123


def test_convert_tools_to_anthropic_converts_input_schema_keys():
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "predict_fraud",
                "description": "x",
                "parameters": {
                    "type": "object",
                    "properties": {"거래금액": {"type": "integer"}},
                    "required": ["거래금액"],
                },
            },
        }
    ]
    converted = rmm._convert_tools_to_anthropic(openai_tools)
    assert converted[0]["name"] == "predict_fraud"
    assert "transaction_amount" in converted[0]["input_schema"]["properties"]


def test_parse_helpers_support_multiple_formats():
    from_json_block = rmm._parse_tool_calls_from_content(
        'text```json\n[{"name":"get_statistics","arguments":{}}]\n```'
    )
    assert from_json_block[0]["name"] == "get_statistics"

    from_inline = rmm._parse_tool_calls_from_content(
        'blah {"name":"analyze_network","arguments":{"account_id":1}} blah'
    )
    assert from_inline[0]["arguments"]["account_id"] == 1

    assert rmm._parse_tool_calls_from_content("no json here") is None

    calls = rmm._try_parse_tool_json(
        '{"function":{"name":"query_transactions","arguments":"{\\"sql\\":\\"SELECT 1\\"}"}}'
    )
    assert calls[0]["name"] == "query_transactions"
    assert calls[0]["arguments"]["sql"] == "SELECT 1"

    bad_args_calls = rmm._try_parse_tool_json(
        '{"name":"x","arguments":"{bad json}"}'
    )
    assert bad_args_calls[0]["arguments"] == {}


def test_extract_json_objects_ignores_braces_inside_strings():
    text = 'prefix {"a":"{not_obj}","b":1} mid {"name":"x","arguments":{}} suffix'
    objs = rmm._extract_json_objects(text)
    assert len(objs) == 2
    parsed = [json.loads(o) for o in objs]
    assert parsed[0]["b"] == 1
    assert parsed[1]["name"] == "x"


def test_checkpoint_roundtrip_and_parse_fail_normalization(tmp_path, monkeypatch):
    cp = tmp_path / "checkpoint.jsonl"
    normalized = {"category": "c1", "case_id": "id1", "score": 0.2, "error_type": "api_error"}

    monkeypatch.setattr(rmm, "normalize_parse_fail_result", lambda rec: normalized)
    cp.write_text(
        "\n".join(
            [
                json.dumps({"category": "c1", "case_id": "id1", "error_type": "parse_fail"}),
                "not-json",
                json.dumps({"category": "", "case_id": "id2"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    completed, cache = rmm._load_checkpoint(cp)
    assert ("c1", "id1") in completed
    assert cache[("c1", "id1")]["error_type"] == "api_error"

    rmm._append_checkpoint(cp, {"category": "c2", "case_id": "id2", "score": 1.0})
    completed2, cache2 = rmm._load_checkpoint(cp)
    assert ("c2", "id2") in completed2
    assert cache2[("c2", "id2")]["score"] == 1.0


def test_result_file_helpers_and_comparison(tmp_path):
    assert rmm._sanitize_model_name("a/b:c.d") == "a_b_c_d"
    cp = rmm._get_checkpoint_path("a/b:c.d", tmp_path)
    assert cp == Path(tmp_path) / "checkpoint_a_b_c_d.jsonl"

    data1 = {"model": "m1", "provider": "p", "overall": {"avg_score": 0.5}, "by_category": {"x": {"aggregated": {"avg_score": 0.5}}}}
    data2 = {"model": "m1", "provider": "p", "overall": {"avg_score": 0.7}, "by_category": {"x": {"aggregated": {"avg_score": 0.7}}}}
    (tmp_path / "eval_20260101.json").write_text(json.dumps(data1), encoding="utf-8")
    (tmp_path / "eval_20260102.json").write_text(json.dumps(data2), encoding="utf-8")
    (tmp_path / "eval_bad.json").write_text("{bad", encoding="utf-8")
    loaded = rmm.load_existing_results(tmp_path)
    assert loaded["m1"]["overall"]["avg_score"] == 0.7

    comparison = rmm.build_comparison(
        {
            "m1": {
                "provider": "p1",
                "total_cases": 10,
                "total_elapsed_sec": 1.2,
                "overall": {
                    "avg_score": 0.8,
                    "primary_tool_hit_rate": 0.9,
                    "avg_tool_recall": 0.8,
                    "avg_tool_precision": 0.7,
                    "avg_param_accuracy": 0.6,
                    "avg_param_key_accuracy": 0.5,
                    "total_hallucinated_params": 2,
                    "by_error_type": {"none": 8},
                    "by_difficulty": {"easy": 5},
                },
                "by_category": {"catA": {"aggregated": {"avg_score": 0.75, "primary_tool_hit_rate": 0.8, "avg_param_accuracy": 0.6, "total": 5}, "elapsed_sec": 0.5}},
            }
        }
    )
    assert comparison["model_summaries"][0]["model"] == "m1"
    assert "catA" in comparison["category_comparison"]
