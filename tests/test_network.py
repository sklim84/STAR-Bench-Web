"""src/features/network.py: ego networks, AML patterns, paths, risk score.

The patterns run on DuckDB and NetworkX; nothing here needs a graph server.
"""

import networkx as nx
import pandas as pd
import pytest

from src.data.db import query
from src.features import network


class TestBankAndAccountNetworks:
    def test_bank_network_columns(self):
        df = network.get_bank_network()
        assert list(df.columns) == ["source", "target", "total_txns", "fraud_txns", "total_amount"]

    def test_fraud_account_network_labels(self):
        df = network.get_fraud_account_network(limit=50)
        assert len(df) <= 50
        assert set(df["fraud_desc"]) <= set(network.FRAUD_TYPE_MAP.values()) | {"Other"}

    def test_bank_network_stats(self):
        row = network.get_bank_network_stats().iloc[0]
        assert int(row["sender_banks"]) == 50 and int(row["receiver_banks"]) == 54

    def test_fraud_accounts_are_senders_with_fraud(self):
        df = network.get_fraud_accounts()
        assert not df.empty and df["account_id"].is_monotonic_increasing


class TestEgoNetwork:
    def test_one_hop_covers_the_account_transactions(self, accounts):
        aid = accounts["most_fraud"]
        df = network.get_account_ego_network(aid, hops=1)
        expected = query(
            "SELECT count(*) AS n, sum(is_fraud) AS f FROM hofinet "
            "WHERE sender_acc = $a OR receiver_acc = $a", {"a": aid}).iloc[0]
        assert int(df["tx_count"].sum()) == int(expected["n"])
        assert int(df["fraud_tx_count"].sum()) == int(expected["f"])

    def test_fraud_tx_count_counts_transactions_not_edges(self, accounts):
        df = network.get_account_ego_network(accounts["most_fraud"], hops=1)
        assert int(df["fraud_tx_count"].sum()) >= int(df["is_fraud"].sum())

    def test_two_hops_include_one_hop(self, accounts):
        aid = accounts["most_fraud"]
        one = network.get_account_ego_network(aid, hops=1)
        two = network.get_account_ego_network(aid, hops=2)
        assert int(two["tx_count"].sum()) >= int(one["tx_count"].sum())

    def test_deep_network_runs_without_a_graph_server(self, accounts):
        df = network.get_account_ego_network_deep(accounts["receiver_only"], hops=3, edge_limit=100)
        assert isinstance(df, pd.DataFrame) and len(df) <= 100

    def test_absent_account_gives_an_empty_frame(self, accounts):
        assert network.get_account_ego_network(accounts["absent"], hops=1).empty

    def test_summary_reports_hop_growth(self, accounts):
        aid = accounts["most_fraud"]
        one = network.summarize_account_network(aid, hops=1)
        three = network.summarize_account_network(aid, hops=3)
        assert three["total_tx_count"] >= one["total_tx_count"]
        assert aid not in three["connected_account_samples"]


class TestFraudGraph:
    def test_fraud_edges_match_the_labelled_transactions(self):
        df = network.get_fraud_edges()
        assert int(df["tx_count"].sum()) == 14_490

    def test_fraud_graph_is_acyclic(self):
        graph = network.build_fraud_graph()
        assert nx.is_directed_acyclic_graph(graph)

    def test_longest_fraud_chain_is_two_transfers(self):
        graph = network.build_fraud_graph()
        assert nx.dag_longest_path_length(graph) == 2


class TestAmlPatterns:
    def test_ring_returns_nothing_on_an_acyclic_graph(self):
        assert network.detect_ring_transactions(min_len=3, max_len=6).empty

    def test_layering_finds_two_step_chains(self):
        df = network.detect_layering_patterns(min_layers=2, limit=10)
        assert not df.empty
        assert (df["layers"] >= 2).all()
        assert all(len(path) == layers + 1
                   for path, layers in zip(df["path_accounts"], df["layers"]))

    def test_layering_three_layers_is_empty(self):
        assert network.detect_layering_patterns(min_layers=3).empty

    def test_layering_is_reproducible(self):
        first = network.detect_layering_patterns(min_layers=2, limit=10)
        second = network.detect_layering_patterns(min_layers=2, limit=10)
        assert first.equals(second)

    def test_funnel_requires_an_outbound_flow(self):
        df = network.detect_funnel_accounts(min_inflow=3, max_outflow=5, limit=20)
        assert not df.empty
        assert (df["outflow_count"] >= 1).all()
        assert (df["outflow_count"] <= 5).all()
        assert (df["inflow_count"] >= 3).all()

    def test_funnel_defaults_match_on_hofinet(self):
        df = network.detect_funnel_accounts()
        assert len(df) == 3
        assert (df["inflow_count"] >= 5).all() and (df["outflow_count"] <= 5).all()

    def test_no_account_forwards_to_three_or_fewer(self):
        assert network.detect_funnel_accounts(min_inflow=1, max_outflow=3).empty

    def test_funnel_account_filter(self):
        df = network.detect_funnel_accounts(min_inflow=3, max_outflow=5, limit=20)
        target = int(df["account_id"].iloc[0])
        filtered = network.detect_funnel_accounts(min_inflow=3, max_outflow=5,
                                                  account_id=target)
        assert list(filtered["account_id"]) == [target]


class TestShortestPath:
    def test_path_between_an_account_and_its_counterparty(self, accounts):
        aid = accounts["most_fraud"]
        counterpart = int(query(
            "SELECT receiver_acc AS r FROM hofinet WHERE sender_acc = $a LIMIT 1",
            {"a": aid})["r"].iloc[0])
        result = network.find_shortest_path(aid, counterpart)
        assert result["path"] == [aid, counterpart]
        assert result["hops"] == 1
        assert result["edges"][0]["tx_count"] >= 1

    def test_path_to_itself(self, accounts):
        result = network.find_shortest_path(accounts["most_fraud"], accounts["most_fraud"])
        assert result["hops"] == 0

    def test_unknown_account_has_no_path(self, accounts):
        result = network.find_shortest_path(accounts["absent"], accounts["most_fraud"])
        assert result["path"] == [] and "notice" in result

    def test_path_is_reproducible(self, accounts):
        first = network.find_shortest_path(accounts["most_fraud"], accounts["receiver_only"])
        second = network.find_shortest_path(accounts["most_fraud"], accounts["receiver_only"])
        assert first == second


class TestRiskScore:
    def test_components_and_range(self, accounts):
        result = network.compute_risk_score(accounts["most_fraud"])
        assert 0.0 <= result["risk_score"] <= 1.0
        assert result["components"]["fraud_ratio_percent"] > 0
        assert result["components"]["cycle_count"] == 0

    def test_unknown_account(self, accounts):
        result = network.compute_risk_score(accounts["absent"])
        assert result["risk_score"] == 0.0 and "notice" in result


class TestGraphHelpers:
    def test_build_bank_graph(self):
        df = network.get_bank_network().head(20)
        graph = network.build_bank_graph(df)
        assert graph.number_of_edges() == len(df)

    def test_centrality_metrics(self):
        graph = network.build_bank_graph(network.get_bank_network().head(30))
        df = network.compute_centrality_metrics(graph)
        assert {"Node", "degree", "betweenness", "closeness", "eigenvector"} <= set(df.columns)

    def test_centrality_on_an_empty_graph(self):
        assert network.compute_centrality_metrics(nx.DiGraph()).empty

    def test_communities(self):
        graph = network.build_bank_graph(network.get_bank_network().head(30))
        df = network.detect_communities(graph)
        assert set(df.columns) == {"Node", "Community"}

    def test_extended_stats(self):
        graph = network.build_bank_graph(network.get_bank_network().head(30))
        stats = network.get_extended_network_stats(graph)
        assert stats["node_count"] > 0 and stats["edge_count"] > 0

    def test_extended_stats_on_an_empty_graph(self):
        assert network.get_extended_network_stats(nx.DiGraph())["node_count"] == 0

    def test_temporal_network(self):
        df = network.get_temporal_network(20240101, 20240131, fraud_only=True)
        assert not df.empty and len(df) <= 1000

    def test_fraud_flow_matrix(self):
        df = network.get_fraud_flow_matrix()
        assert int(df["fraud_count"].sum()) == 14_490
