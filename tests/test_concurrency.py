"""Tool calls from several threads must behave like serial calls.

The benchmark runners execute tools inside a ThreadPoolExecutor (BENCH_CONCURRENCY),
and with one shared DuckDB connection a call could receive another call's rows
or fail outright.
"""

from concurrent.futures import ThreadPoolExecutor

from src.features.agent import _execute_tool


CALLS = [
    ("get_statistics", {}),
    ("query_transactions", {"sql": "SELECT count(*) AS c FROM hofinet WHERE fraud_type = 7"}),
    ("query_transactions", {"sql": "SELECT count(*) AS c FROM hofinet WHERE sender_bank = 102"}),
    ("get_fraud_type_summary", {"fraud_type": 3}),
    ("get_institution_report", {"bank_id": 102}),
    ("get_trend_analysis", {"unit": "quarterly"}),
    ("detect_monitoring_alerts", {"rule_id": "R001", "limit": 5}),
    ("detect_ctr_candidates", {"mode": "high_value", "limit": 5}),
    ("analyze_cross_institution_flow", {"limit": 5}),
    ("lookup_fiu_reference_types", {"keyword": "cash"}),
]


def _run(call):
    name, arguments = call
    return _execute_tool(name, dict(arguments))


def test_concurrent_calls_match_serial_calls():
    serial = [_run(call) for call in CALLS]
    work = CALLS * 6

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_run, work))

    expected = dict(zip([str(call) for call in CALLS], serial))
    mismatches = [
        str(call) for call, result in zip(work, results)
        if result != expected[str(call)]
    ]
    assert mismatches == []


def test_account_calls_are_thread_safe(accounts):
    calls = [
        ("get_account_profile", {"account_id": accounts["most_fraud"]}),
        ("get_receiving_account_profile", {"account_id": accounts["receiver_only"]}),
        ("score_account_risk", {"account_id": accounts["both_roles"]}),
        ("analyze_network", {"account_id": accounts["most_fraud"]}),
    ]
    serial = {str(call): _run(call) for call in calls}
    work = calls * 5

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_run, work))

    assert all(result == serial[str(call)] for call, result in zip(work, results))
