"""The same tool call must return the same result.

Identical calls used to differ between runs: ORDER BY ties over 48 distinct
amounts, ORDER BY random() sampling and today's date in the STR report made
repeated calls, and therefore whole benchmark runs, irreproducible (L3-016).
"""

import pytest

from src.features.agent import _execute_tool


CALLS = [
    ("get_statistics", {}),
    ("query_transactions", {"sql": "SELECT sender_bank, count(*) AS c FROM hofinet GROUP BY 1 ORDER BY c DESC LIMIT 5"}),
    ("get_fraud_type_summary", {"fraud_type": 3}),
    ("compare_periods", {"period1_start": 20230101, "period1_end": 20230630,
                         "period2_start": 20230701, "period2_end": 20231231}),
    ("get_trend_analysis", {"unit": "quarterly"}),
    ("analyze_channel_risk", {}),
    ("analyze_cross_institution_flow", {"limit": 10}),
    ("detect_ctr_candidates", {"mode": "high_value", "limit": 10}),
    ("detect_ctr_candidates", {"mode": "structuring", "limit": 10}),
    ("detect_monitoring_alerts", {"rule_id": "R001", "limit": 5}),
    ("detect_monitoring_alerts", {"rule_id": "R002", "limit": 5}),
    ("detect_monitoring_alerts", {"rule_id": "R003", "limit": 5}),
    ("detect_monitoring_alerts", {"rule_id": "R004", "limit": 5}),
    ("detect_monitoring_alerts", {"rule_id": "R005", "limit": 5}),
    ("detect_monitoring_alerts", {"rule_id": "all", "limit": 3}),
    ("detect_dormant_reactivation", {"limit": 10}),
    ("detect_smurfing_network", {"direction": "inbound", "min_counterparts": 20, "limit": 10}),
    ("detect_smurfing_network", {"direction": "outbound", "min_counterparts": 20, "limit": 10}),
    ("detect_aml_patterns", {"pattern_type": "layering", "min_layers": 2, "limit": 10}),
    ("detect_aml_patterns", {"pattern_type": "funnel", "min_inflow": 3, "max_outflow": 5, "limit": 10}),
    ("lookup_fiu_reference_types", {"keyword": "cash"}),
    ("get_aml_glossary", {"term": "STR"}),
]

ACCOUNT_CALLS = [
    ("get_account_profile", "account_id"),
    ("get_receiving_account_profile", "account_id"),
    ("score_account_risk", "account_id"),
    ("analyze_network", "account_id"),
]


@pytest.mark.parametrize("name,arguments", CALLS, ids=[f"{n}-{i}" for i, (n, _) in enumerate(CALLS)])
def test_call_is_reproducible(name, arguments):
    assert _execute_tool(name, dict(arguments)) == _execute_tool(name, dict(arguments))


@pytest.mark.parametrize("name,key", ACCOUNT_CALLS)
def test_account_call_is_reproducible(name, key, accounts):
    arguments = {key: accounts["most_fraud"]}
    assert _execute_tool(name, dict(arguments)) == _execute_tool(name, dict(arguments))


def test_model_ranking_is_reproducible(model):
    first = _execute_tool("rank_risky_transactions", {"sample_size": 500, "top_k": 10})
    second = _execute_tool("rank_risky_transactions", {"sample_size": 500, "top_k": 10})
    assert first == second


def test_shortest_path_is_reproducible(accounts):
    arguments = {"pattern_type": "shortest_path",
                 "account_a": accounts["most_fraud"], "account_b": accounts["receiver_only"]}
    assert _execute_tool("detect_aml_patterns", dict(arguments)) == _execute_tool(
        "detect_aml_patterns", dict(arguments))
