"""src/features/flow_analyzer.py: smurfing networks and institution flows."""

import pytest

from src.features import flow_analyzer


class TestSmurfingNetwork:
    def test_inbound_columns(self):
        df = flow_analyzer.detect_smurfing_network(direction="inbound",
                                                   min_counterparts=20, limit=10)
        assert list(df.columns) == ["target_account", "counterparty_count", "total_tx_count",
                                    "total_amount", "fraud_count", "avg_amount"]
        assert (df["counterparty_count"] >= 20).all()

    def test_outbound_columns(self):
        df = flow_analyzer.detect_smurfing_network(direction="outbound",
                                                   min_counterparts=20, limit=10)
        assert df.columns[0] == "source_account"
        assert (df["counterparty_count"] >= 20).all()

    def test_account_filter(self):
        sample = flow_analyzer.detect_smurfing_network(direction="inbound",
                                                       min_counterparts=20, limit=1)
        aid = int(sample["target_account"].iloc[0])
        df = flow_analyzer.detect_smurfing_network(direction="inbound", account_id=aid,
                                                   min_counterparts=20, limit=10)
        assert list(df["target_account"]) == [aid]

    def test_date_filter_narrows_the_result(self):
        wide = flow_analyzer.detect_smurfing_network(direction="inbound",
                                                     min_counterparts=20, limit=50)
        narrow = flow_analyzer.detect_smurfing_network(direction="inbound", min_counterparts=20,
                                                       date_from=20240101, date_to=20240131,
                                                       limit=50)
        assert len(narrow) <= len(wide)

    def test_result_is_reproducible(self):
        first = flow_analyzer.detect_smurfing_network(direction="inbound",
                                                      min_counterparts=20, limit=20)
        second = flow_analyzer.detect_smurfing_network(direction="inbound",
                                                       min_counterparts=20, limit=20)
        assert first.equals(second)


class TestCrossInstitutionFlow:
    def test_columns_and_filter(self):
        df = flow_analyzer.analyze_cross_institution_flow(min_transactions=100, limit=10)
        assert "fraud_ratio_percent" in df.columns
        assert (df["tx_count"] >= 100).all()

    def test_fraud_ratio_is_a_percentage(self):
        df = flow_analyzer.analyze_cross_institution_flow(min_transactions=100, limit=20)
        assert ((df["fraud_ratio_percent"] >= 0) & (df["fraud_ratio_percent"] <= 100)).all()
        computed = df["fraud_count"] / df["tx_count"] * 100
        assert (abs(df["fraud_ratio_percent"] - computed) < 0.01).all()

    def test_result_is_reproducible(self):
        first = flow_analyzer.analyze_cross_institution_flow(limit=20)
        second = flow_analyzer.analyze_cross_institution_flow(limit=20)
        assert first.equals(second)
