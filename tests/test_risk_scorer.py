"""src/features/risk_scorer.py: the five behavioural components."""

import pytest

from src.features import risk_scorer


class TestScoreAccount:
    def test_score_and_components(self, accounts):
        result = risk_scorer.score_account(accounts["most_fraud"])
        assert 0 <= result["total_score"] <= 100
        assert result["risk_level"] in ("High", "Medium", "Low")
        assert set(result["components"]) == set(risk_scorer._WEIGHTS)
        assert all(0.0 <= value <= 1.0 for value in result["components"].values())

    def test_receiver_only_account_is_scored(self, accounts):
        result = risk_scorer.score_account(accounts["receiver_only"])
        assert result["role"] == "receiver"
        assert result["received_count"] > 0 and result["sent_count"] == 0

    def test_sender_only_account_is_scored(self, accounts):
        result = risk_scorer.score_account(accounts["sender_only"])
        assert result["role"] == "sender"

    def test_absent_account_gets_a_notice(self, accounts):
        result = risk_scorer.score_account(accounts["absent"])
        assert result["total_count"] == 0 and "notice" in result

    def test_weights_sum_to_one(self):
        assert sum(risk_scorer._WEIGHTS.values()) == pytest.approx(1.0)

    def test_score_matches_the_weighted_components(self, accounts):
        result = risk_scorer.score_account(accounts["most_fraud"])
        expected = sum(result["components"][k] * result["weights"][k]
                       for k in result["weights"]) * 100
        assert result["total_score"] == pytest.approx(expected, abs=0.1)


class TestComponents:
    def test_amount_anomaly_uses_the_global_standard_deviation(self, accounts):
        mean, std = risk_scorer.get_amount_baseline()
        assert std > 0 and mean > 0
        stats = risk_scorer._account_stats(accounts["most_fraud"])
        assert risk_scorer._calc_amount_anomaly(stats) == pytest.approx(
            min(1.0, abs(stats["avg_amount"] - mean) / std / 5.0), abs=1e-6)

    def test_constant_amount_account_can_still_score(self, accounts):
        """Dividing by the account's own std scored constant-amount accounts 0."""
        from src.data.db import query

        row = query("""
            SELECT sender_acc FROM hofinet
            GROUP BY sender_acc
            HAVING count(DISTINCT amount) = 1 AND count(*) >= 5
            ORDER BY sender_acc LIMIT 1
        """)
        if row.empty:
            pytest.skip("no constant-amount account in the dataset")
        stats = risk_scorer._account_stats(int(row["sender_acc"].iloc[0]))
        assert risk_scorer._calc_amount_anomaly(stats) > 0

    def test_nighttime_component_uses_the_night_slots(self, accounts):
        stats = risk_scorer._account_stats(accounts["most_fraud"])
        assert 0.0 <= risk_scorer._calc_nighttime_ratio(stats) <= 1.0

    def test_velocity_compares_consecutive_quarters(self, accounts):
        assert 0.0 <= risk_scorer._calc_velocity_change(accounts["most_fraud"]) <= 1.0

    def test_fraud_history_is_the_label_share(self, accounts):
        stats = risk_scorer._account_stats(accounts["most_fraud"])
        assert risk_scorer._calc_fraud_history(stats) == pytest.approx(
            stats["fraud"] / stats["total"])


class TestRankRiskyAccounts:
    def test_columns_and_limit(self):
        df = risk_scorer.rank_risky_accounts(top_k=10, min_transactions=10)
        assert len(df) == 10
        assert {"account_id", "fraud_ratio_percent", "nighttime_ratio_percent",
                "risk_score_simple"} <= set(df.columns)

    def test_min_transactions_filter(self):
        df = risk_scorer.rank_risky_accounts(top_k=10, min_transactions=100)
        assert (df["total_tx_count"] >= 100).all()

    def test_ordering_is_deterministic(self):
        first = risk_scorer.rank_risky_accounts(top_k=20)
        second = risk_scorer.rank_risky_accounts(top_k=20)
        assert first.equals(second)
