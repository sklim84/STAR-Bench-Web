"""src/features/agent.py: the 23 tools as the benchmark calls them.

Every test goes through `_execute_tool`, the entry point the benchmark runners
use, and reads the JSON string it returns. The cases cover the defects the
recorded runs showed: crashes on empty aggregates, arguments serialised as
strings, ignored parameters, and outputs that contradicted their description.
"""

import json

import pytest

from src.features.agent import TOOLS, SYSTEM_PROMPT, _execute_tool


def call(name, **arguments):
    """Runs a tool and returns its parsed result."""
    return json.loads(_execute_tool(name, arguments))


def call_raw(name, arguments):
    return json.loads(_execute_tool(name, arguments))


@pytest.fixture(scope="module")
def tool_names():
    return {tool["function"]["name"] for tool in TOOLS}


class TestSchema:
    def test_every_tool_is_dispatchable(self, tool_names):
        for name in tool_names:
            result = call_raw(name, {})
            assert "Unknown tool" not in json.dumps(result, ensure_ascii=False)

    def test_unknown_tool_is_reported(self):
        assert "Unknown tool" in call("no_such_tool")["error"]

    def test_schema_covers_23_tools(self, tool_names):
        assert len(tool_names) == 23

    def test_system_prompt_states_the_data_facts(self):
        for fact in ("20210901", "20241231", "yyyymmdd", "9000000000000002",
                     "102-161", "심야/새벽 대량 거래", "language of the user's question"):
            assert fact in SYSTEM_PROMPT

    def test_system_prompt_has_no_prescribed_flow(self):
        assert "Recommended Analysis Flow" not in SYSTEM_PROMPT
        assert "Always query" not in SYSTEM_PROMPT

    def test_system_prompt_states_the_glossary_scope_rule(self):
        assert "get_aml_glossary" in SYSTEM_PROMPT
        assert "without a tool" in SYSTEM_PROMPT


class TestArgumentHandling:
    def test_null_string_is_treated_as_absent(self):
        result = call("get_fraud_type_summary", fraud_type=3, bank_id="null")
        assert result["bank_filter"] is None
        assert result["total_count"] > 0

    def test_arguments_may_arrive_as_a_json_string(self):
        result = call_raw("get_fraud_type_summary", '{"fraud_type": 3}')
        assert result["type_code"] == 3

    def test_numeric_strings_are_accepted(self, accounts):
        result = call("get_account_profile", account_id=str(accounts["both_roles"]))
        assert result["account_id"] == accounts["both_roles"]

    def test_missing_required_argument_is_named(self):
        assert "account_id is required" in call("get_account_profile")["error"]

    def test_unreadable_argument_is_named(self):
        assert "account_id" in call("get_account_profile", account_id="abc")["error"]

    def test_invalid_date_is_rejected(self):
        error = call("detect_ctr_candidates", mode="high_value", date_from="2024-01-01")["error"]
        assert "YYYYMMDD" in error


class TestQueryTransactions:
    def test_aggregate_query(self):
        result = call("query_transactions", sql="SELECT count(*) AS n FROM hofinet")
        assert result["result"][0]["n"] == 4_732_130
        assert result["total_count"] == 1

    def test_cte_is_allowed(self):
        result = call("query_transactions", sql="WITH t AS (SELECT 1 AS a) SELECT * FROM t")
        assert result["result"] == [{"a": 1}]

    def test_leading_comment_is_allowed(self):
        result = call("query_transactions", sql="-- why not\nSELECT 1 AS a")
        assert result["result"] == [{"a": 1}]

    def test_parenthesised_select_is_allowed(self):
        assert call("query_transactions", sql="(SELECT 1 AS a)")["result"] == [{"a": 1}]

    def test_alias_containing_a_keyword_is_allowed(self):
        result = call("query_transactions", sql="SELECT 1 AS last_update_date, 2 AS created_cnt")
        assert result["result"] == [{"last_update_date": 1, "created_cnt": 2}]

    def test_write_statement_is_refused(self):
        assert "SELECT" in call("query_transactions", sql="DROP TABLE hofinet")["error"]

    def test_multiple_statements_are_refused(self):
        assert "one SELECT" in call("query_transactions", sql="SELECT 1; SELECT 2")["error"]

    def test_file_access_is_refused(self):
        error = call("query_transactions", sql="SELECT * FROM read_csv_auto('/etc/hostname')")["error"]
        assert "files" in error

    def test_empty_result_has_the_same_shape(self):
        result = call("query_transactions", sql="SELECT * FROM hofinet WHERE sender_acc = 1")
        assert result["result"] == [] and result["total_count"] == 0 and "notice" in result

    def test_large_result_is_truncated_but_counted(self):
        result = call("query_transactions", sql="SELECT * FROM hofinet LIMIT 250")
        assert result["total_count"] == 250 and result["returned_count"] == 100

    def test_syntax_error_is_reported(self):
        assert "error" in call("query_transactions", sql="SELECT FROM WHERE")


class TestAccountProfiles:
    def test_sender_only_account(self, accounts):
        result = call("get_account_profile", account_id=accounts["sender_only"])
        assert result["total_count"] > 0
        assert result["inbound_count"] == 0

    def test_receiver_only_account(self, accounts):
        result = call("get_account_profile", account_id=accounts["receiver_only"])
        assert result["total_count"] > 0
        assert result["outbound_count"] == 0

    def test_absent_account_gets_a_notice(self, accounts):
        result = call("get_account_profile", account_id=accounts["absent"])
        assert result["total_count"] == 0 and "notice" in result and "error" not in result

    def test_fraud_ratio_is_a_percentage(self, accounts):
        from src.data.db import query

        aid = accounts["most_fraud"]
        result = call("get_account_profile", account_id=aid)
        expected = query(
            "SELECT count(*) AS n, sum(is_fraud) AS f FROM hofinet "
            "WHERE sender_acc = $a OR receiver_acc = $a", {"a": aid}
        ).iloc[0]
        assert result["total_count"] == int(expected["n"])
        assert result["fraud_count"] == int(expected["f"])
        assert result["fraud_ratio_percent"] == pytest.approx(
            int(expected["f"]) / int(expected["n"]) * 100, abs=1e-3
        )

    def test_receiving_profile_counts_all_senders(self, accounts):
        from src.data.db import query

        aid = accounts["receiver_only"]
        result = call("get_receiving_account_profile", account_id=aid)
        expected = int(query(
            "SELECT count(DISTINCT sender_acc) AS c FROM hofinet WHERE receiver_acc = $a",
            {"a": aid},
        )["c"].iloc[0])
        assert result["unique_senders"] == expected
        assert "fraud_ratio_percent" in result


class TestStatisticsAndSummaries:
    def test_statistics_returns_the_documented_fields(self):
        stats = call("get_statistics")["summary_statistics"]
        for key in ("total_tx_count", "fraud_tx_count", "fraud_ratio_percent",
                    "sender_account_count", "receiver_account_count",
                    "sender_bank_count", "receiver_bank_count", "total_amount"):
            assert key in stats
        assert stats["total_tx_count"] == 4_732_130

    def test_statistics_description_mentions_account_and_bank_counts(self):
        description = next(
            t["function"]["description"] for t in TOOLS
            if t["function"]["name"] == "get_statistics"
        )
        assert "account counts" in description and "bank counts" in description

    def test_fraud_type_summary(self):
        result = call("get_fraud_type_summary", fraud_type=7)
        assert result["total_count"] == 35
        assert result["type_name"] == "Late-Night/Early-Morning Bulk Transactions"

    def test_unused_fraud_type_code_is_refused(self):
        assert "6" in call("get_fraud_type_summary", fraud_type=6)["error"]

    def test_bank_filter_without_rows_gets_a_notice(self, banks):
        result = call("get_fraud_type_summary", fraud_type=3, bank_id=banks["absent"])
        assert result["total_count"] == 0 and "notice" in result and "error" not in result

    def test_compare_periods(self):
        result = call("compare_periods", period1_start=20230101, period1_end=20230630,
                      period2_start=20230701, period2_end=20231231)
        assert result["period1"]["total_count"] > 0
        assert result["delta"]["total_count_pct"] is not None

    def test_compare_periods_reports_missing_dates(self):
        error = call("compare_periods", period_a_start=20230101)["error"]
        assert "period1_start" in error

    def test_compare_periods_handles_an_empty_period(self):
        result = call("compare_periods", period1_start=20200101, period1_end=20200630,
                      period2_start=20230701, period2_end=20231231)
        assert result["period1"]["total_count"] == 0
        assert result["delta"]["total_count_pct"] is None


class TestInstitutionReport:
    def test_reports_both_directions(self, banks):
        result = call("get_institution_report", bank_id=banks["both_roles"])
        assert result["outbound"]["total_count"] > 0
        assert "fraud_ratio_percent" in result["inbound"]

    def test_receive_only_bank_is_reported(self, banks):
        result = call("get_institution_report", bank_id=banks["receiver_only"])
        assert result["inbound"]["total_count"] > 0
        assert result["outbound"]["total_count"] == 0

    def test_quarterly_trend_is_returned(self, banks):
        result = call("get_institution_report", bank_id=banks["both_roles"])
        assert result["quarterly_trend"]
        assert result["quarterly_trend"][0]["quarter"].endswith(("Q1", "Q2", "Q3", "Q4"))

    def test_absent_bank_gets_a_notice(self, banks):
        result = call("get_institution_report", bank_id=banks["absent"])
        assert "notice" in result and "error" not in result


class TestModelTools:
    def test_predict_fraud(self, model):
        result = call("predict_fraud", time_slot=9, sender_bank=134, receiver_bank=119,
                      fund_type=0, media_type=2, amount=5_000_000)
        assert 0.0 <= result["fraud_risk_score"] <= 1.0
        assert result["risk_level"] in ("High", "Medium", "Low")
        assert "not a probability" in result["score_type"]

    def test_predict_fraud_ignores_key_order_and_extra_keys(self, model):
        ordered = call("predict_fraud", time_slot=9, sender_bank=134, receiver_bank=119,
                       fund_type=0, media_type=2, amount=5_000_000)
        shuffled = call("predict_fraud", amount=5_000_000, fund_type=0, media_type=2,
                        receiver_bank=119, sender_bank=134, time_slot=9, date=20240101)
        assert ordered["fraud_risk_score"] == shuffled["fraud_risk_score"]

    def test_predict_fraud_accepts_numeric_strings(self, model):
        result = call("predict_fraud", time_slot="9", sender_bank="134", receiver_bank="119",
                      fund_type="0", media_type="2", amount="5000000")
        assert "fraud_risk_score" in result

    def test_predict_fraud_reports_missing_features(self, model):
        result = call("predict_fraud", time_slot=9, sender_bank=134)
        assert result["error"] == "Input parameter error"
        assert any("amount" in detail for detail in result["details"])

    def test_predict_fraud_rejects_impossible_values(self, model):
        result = call("predict_fraud", time_slot=7, sender_bank=134, receiver_bank=119,
                      fund_type=0, media_type=2, amount=5_000_000)
        assert any("time_slot" in detail for detail in result["details"])

    def test_rank_risky_transactions_returns_scores_without_labels(self, model):
        result = call("rank_risky_transactions", sample_size=500, top_k=5)
        assert len(result["results"]) == 5
        for row in result["results"]:
            assert "fraud_risk_score" in row
            assert "is_fraud_actual" not in row and "is_fraud" not in row

    def test_rank_risky_transactions_is_ordered_by_score(self, model):
        scores = [r["fraud_risk_score"] for r in call(
            "rank_risky_transactions", sample_size=500, top_k=10)["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_rank_risky_transactions_reports_the_sample_cap(self, model):
        result = call("rank_risky_transactions", sample_size=12000, top_k=2)
        assert result["sample_size"] == 5000 and "notice" in result


class TestNetworkTools:
    def test_analyze_network_counts_fraud_transactions(self, accounts):
        from src.data.db import query

        aid = accounts["most_fraud"]
        result = call("analyze_network", account_id=aid)
        expected = query(
            "SELECT count(*) AS n, sum(is_fraud) AS f FROM hofinet "
            "WHERE sender_acc = $a OR receiver_acc = $a", {"a": aid}
        ).iloc[0]
        assert result["total_tx_count"] == int(expected["n"])
        assert result["fraud_tx_count"] == int(expected["f"])

    def test_more_hops_cover_more_accounts(self, accounts):
        aid = accounts["most_fraud"]
        one = call("analyze_network", account_id=aid, hops=1)
        three = call("analyze_network", account_id=aid, hops=3)
        assert three["search_hop_range"] == 3
        assert three["total_tx_count"] >= one["total_tx_count"]
        assert three["connected_account_count"] >= one["connected_account_count"]

    def test_absent_account_gets_a_notice(self, accounts):
        result = call("analyze_network", account_id=accounts["absent"])
        assert result["total_tx_count"] == 0 and "notice" in result

    def test_ring_reports_that_hofinet_has_no_cycles(self):
        result = call("detect_aml_patterns", pattern_type="ring")
        assert result["count"] == 0
        assert "acyclic" in result["notice"]

    def test_layering_finds_two_step_chains(self):
        result = call("detect_aml_patterns", pattern_type="layering", min_layers=2, limit=5)
        assert result["count"] > 0
        assert all(row["layers"] >= 2 for row in result["result"])

    def test_layering_at_three_layers_is_empty(self):
        result = call("detect_aml_patterns", pattern_type="layering", min_layers=3)
        assert result["count"] == 0 and "notice" in result

    def test_funnel_requires_outbound_flow(self):
        result = call("detect_aml_patterns", pattern_type="funnel",
                      min_inflow=3, max_outflow=5, limit=5)
        assert result["count"] > 0
        assert all(1 <= row["outflow_count"] <= 5 for row in result["result"])
        assert all(row["inflow_count"] >= 3 for row in result["result"])

    def test_funnel_defaults_match_on_hofinet(self):
        result = call("detect_aml_patterns", pattern_type="funnel")
        assert result["criteria"] == {"min_inflow": 5, "max_outflow": 5}
        assert result["count"] > 0

    def test_funnel_below_the_smallest_outflow_explains_the_empty_result(self):
        result = call("detect_aml_patterns", pattern_type="funnel", max_outflow=3)
        assert result["count"] == 0 and "414" in result["notice"]

    def test_shortest_path_between_connected_accounts(self, accounts):
        result = call("detect_aml_patterns", pattern_type="shortest_path",
                      account_a=accounts["most_fraud"], account_b=accounts["receiver_only"])
        assert result["hops"] == len(result["path"]) - 1 or result["path"] == []
        if result["path"]:
            assert result["path"][0] == accounts["most_fraud"]
            assert len(result["edges"]) >= result["hops"]

    def test_shortest_path_requires_two_accounts(self):
        assert "account_a" in call("detect_aml_patterns", pattern_type="shortest_path")["error"]

    def test_risk_score_components(self, accounts):
        result = call("detect_aml_patterns", pattern_type="risk_score",
                      account_id=accounts["most_fraud"])
        assert 0.0 <= result["risk_score"] <= 1.0
        assert set(result["components"]) == {
            "fraud_ratio_percent", "neighbor_fraud_ratio_percent",
            "cycle_count", "in_out_imbalance_percent",
        }

    def test_unknown_pattern_is_refused(self):
        assert "Unknown pattern" in call("detect_aml_patterns", pattern_type="spiral")["error"]

    def test_no_tool_reports_memgraph(self):
        for pattern in ("ring", "layering", "funnel"):
            assert "Memgraph" not in json.dumps(call("detect_aml_patterns", pattern_type=pattern))


class TestMonitoringTools:
    def test_nighttime_rule_fires_on_the_data(self):
        result = call("detect_monitoring_alerts", rule_id="R001", limit=5)
        assert result["count"] > 0
        assert all(row["time_slot"] in (21, 0, 3) for row in result["result"])
        assert all(row["amount"] >= 5_000_000 for row in result["result"])

    def test_repeated_amount_rule(self):
        result = call("detect_monitoring_alerts", rule_id="R003", limit=5)
        assert result["count"] > 0
        assert all(row["repeat_count"] >= 3 for row in result["result"])
        assert all(row["amount"] >= 2_000_000 for row in result["result"])

    def test_concentration_rule_returns_more_than_one_account(self):
        result = call("detect_monitoring_alerts", rule_id="R004", limit=20)
        assert result["count"] > 1
        assert all(row["concentration_percent"] >= 50 for row in result["result"])

    def test_pattern_change_without_dates_uses_the_last_quarter(self):
        result = call("detect_monitoring_alerts", rule_id="R005", limit=5)
        assert result["count"] > 0
        assert "20241001" in result["notice"]

    def test_account_filter_is_honoured(self, accounts):
        aid = accounts["most_fraud"]
        result = call("detect_monitoring_alerts", rule_id="R002", account_id=aid, limit=10)
        assert all(row["sender_acc"] == aid for row in result["result"])

    def test_date_filter_is_honoured(self):
        result = call("detect_monitoring_alerts", rule_id="R001",
                      date_from=20240101, date_to=20241231, limit=20)
        assert all(20240101 <= row["date"] <= 20241231 for row in result["result"])

    def test_dates_also_apply_to_the_concentration_rule(self):
        wide = call("detect_monitoring_alerts", rule_id="R004", limit=20)
        narrow = call("detect_monitoring_alerts", rule_id="R004",
                      date_from=20240101, date_to=20240131, limit=20)
        assert narrow["result"] != wide["result"]

    def test_all_rules_honour_the_limit(self):
        result = call("detect_monitoring_alerts", rule_id="all", limit=2)
        assert set(result["result"]) == {"R001", "R002", "R003", "R004", "R005"}
        assert all(len(rule["result"]) <= 2 for rule in result["result"].values())

    def test_unknown_rule_is_refused(self):
        assert "rule_id" in call("detect_monitoring_alerts", rule_id="R009")["error"]

    def test_reversed_dates_are_refused(self):
        error = call("detect_monitoring_alerts", rule_id="R001",
                     date_from=20241231, date_to=20240101)["error"]
        assert "date_from" in error

    def test_dormant_reactivation(self):
        result = call("detect_dormant_reactivation", limit=5)
        assert result["count"] > 0
        assert all(row["dormant_days"] >= 180 for row in result["result"])
        assert all(row["reactivation_amount"] >= 5_000_000 for row in result["result"])


class TestAnalysisTools:
    def test_ctr_high_value_applies_the_threshold(self):
        result = call("detect_ctr_candidates", mode="high_value",
                      threshold=100_000_000, limit=10)
        assert result["count"] > 0
        assert all(row["amount"] >= 100_000_000 for row in result["result"])

    def test_ctr_structuring(self):
        result = call("detect_ctr_candidates", mode="structuring", limit=5)
        assert all(row["total_amount"] >= result["threshold"] for row in result["result"])
        assert all(row["max_single_amount"] < result["threshold"] for row in result["result"])

    def test_ctr_mode_is_validated(self):
        assert "mode" in call("detect_ctr_candidates", mode="everything")["error"]

    def test_trend_analysis_has_fourteen_quarters(self):
        result = call("get_trend_analysis", unit="quarterly")
        assert result["period_count"] == 14
        assert result["result"][0]["period"] == "2021Q3"
        assert "fraud_ratio_percent" in result["result"][0]

    def test_trend_analysis_monthly_labels(self):
        result = call("get_trend_analysis", unit="monthly")
        assert result["result"][0]["period"] == "2021-09"

    def test_trend_analysis_rejects_an_unknown_unit(self):
        assert "unit" in call("get_trend_analysis", unit="weekly")["error"]

    def test_channel_risk_uses_hofinet_channels(self):
        result = call("analyze_channel_risk")
        names = {row["channel_name"] for row in result["channel_stats"]}
        assert names == {"PC Banking", "Internet Banking", "Phone", "Mobile Phone",
                         "Per-transaction Transfer", "Other", "Bulk Transfer"}
        assert all("fraud_ratio_percent" in row for row in result["channel_stats"])

    def test_channel_risk_description_lists_real_channels(self):
        description = next(
            t["function"]["description"] for t in TOOLS
            if t["function"]["name"] == "analyze_channel_risk"
        )
        assert "media_type" in description
        assert "ATM" not in description and "medium_type" not in description

    def test_cross_institution_flow(self):
        result = call("analyze_cross_institution_flow", min_transactions=100, limit=5)
        assert result["count"] > 0
        assert all(row["tx_count"] >= 100 for row in result["result"])
        assert all("fraud_ratio_percent" in row for row in result["result"])

    def test_smurfing_inbound(self):
        result = call("detect_smurfing_network", direction="inbound",
                      min_counterparts=50, limit=5)
        assert result["count"] > 0
        assert all(row["counterparty_count"] >= 50 for row in result["result"])

    def test_smurfing_direction_is_validated(self):
        assert "direction" in call("detect_smurfing_network", direction="sideways")["error"]

    def test_score_account_risk(self, accounts):
        result = call("score_account_risk", account_id=accounts["most_fraud"])
        assert 0 <= result["total_score"] <= 100
        assert set(result["components"]) == {
            "nighttime_ratio", "amount_anomaly", "counterparty_diversity",
            "velocity_change", "fraud_history",
        }

    def test_score_account_risk_works_for_receivers(self, accounts):
        result = call("score_account_risk", account_id=accounts["receiver_only"])
        assert result["role"] == "receiver"
        assert result["total_count"] > 0

    def test_score_account_risk_absent_account(self, accounts):
        result = call("score_account_risk", account_id=accounts["absent"])
        assert "notice" in result and "error" not in result


class TestReferenceTools:
    def test_catalog_keywords_from_the_description_return_rows(self):
        description = next(
            t["function"]["description"] for t in TOOLS
            if t["function"]["name"] == "lookup_fiu_reference_types"
        )
        examples = ["structuring", "cash", "non-face-to-face", "virtual asset",
                    "dormancy", "gambling", "balance certificate"]
        for keyword in examples:
            assert keyword in description
            assert call("lookup_fiu_reference_types", keyword=keyword)["count"] > 0

    def test_empty_keyword_lists_the_catalog(self):
        assert call("lookup_fiu_reference_types", keyword="")["count"] == 31

    def test_industry_filter(self):
        result = call("lookup_fiu_reference_types", keyword="", industry="securities")
        assert {row["industry"] for row in result["result"]} == {"Securities"}

    def test_unknown_industry_is_refused(self):
        assert "industry" in call("lookup_fiu_reference_types",
                                  keyword="cash", industry="insurance")["error"]

    def test_keyword_without_a_match_gets_a_notice(self):
        result = call("lookup_fiu_reference_types", keyword="심야")
        assert result["count"] == 0 and "English" in result["notice"]

    def test_glossary_terms_are_english(self):
        result = call("get_aml_glossary", term="structuring")
        assert result["term"] == "Structuring"
        missing = call("get_aml_glossary", term="구조화")
        assert "available_terms" in missing and "Structuring" in missing["available_terms"]
