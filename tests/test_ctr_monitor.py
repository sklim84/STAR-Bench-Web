"""src/features/ctr_monitor.py: high-value and structuring detection."""

import pytest

from src.features import ctr_monitor


class TestCtrCandidates:
    def test_default_threshold(self):
        df = ctr_monitor.get_ctr_candidates(limit=50)
        assert not df.empty and (df["amount"] >= 10_000_000).all()

    def test_threshold_is_applied(self):
        df = ctr_monitor.get_ctr_candidates(threshold=100_000_000, limit=50)
        assert not df.empty and (df["amount"] >= 100_000_000).all()

    def test_date_filter(self):
        df = ctr_monitor.get_ctr_candidates(date_from=20240101, date_to=20240131, limit=50)
        assert ((df["date"] >= 20240101) & (df["date"] <= 20240131)).all()

    def test_columns(self):
        df = ctr_monitor.get_ctr_candidates(limit=5)
        assert list(df.columns) == [
            "date", "time_slot", "sender_bank", "sender_acc", "receiver_bank",
            "receiver_acc", "fund_type", "media_type", "amount", "is_fraud", "fraud_type",
        ]

    def test_result_is_reproducible(self):
        """48 distinct amounts means ORDER BY amount alone is full of ties."""
        assert ctr_monitor.get_ctr_candidates(limit=50).equals(
            ctr_monitor.get_ctr_candidates(limit=50))


class TestStructuring:
    def test_conditions(self):
        df = ctr_monitor.detect_structuring(limit=50)
        assert not df.empty
        assert (df["total_amount"] >= 10_000_000).all()
        assert (df["max_single_amount"] < 10_000_000).all()
        assert (df["tx_count"] >= 2).all()

    def test_threshold_is_applied(self):
        df = ctr_monitor.detect_structuring(threshold=50_000_000, limit=50)
        assert (df["total_amount"] >= 50_000_000).all()

    def test_result_is_reproducible(self):
        assert ctr_monitor.detect_structuring(limit=30).equals(
            ctr_monitor.detect_structuring(limit=30))


class TestAccountAssessment:
    def test_keys(self, accounts):
        result = ctr_monitor.assess_account_structuring(accounts["most_fraud"])
        assert set(result) == {"account_id", "total_tx_count", "total_amount",
                               "structuring_suspect_days", "structuring_details"}

    def test_absent_account(self, accounts):
        result = ctr_monitor.assess_account_structuring(accounts["absent"])
        assert result["total_tx_count"] == 0 and result["structuring_suspect_days"] == 0


class TestCtrSummary:
    def test_keys_and_values(self):
        summary = ctr_monitor.get_ctr_summary()
        assert set(summary) == {"high_value_count", "high_value_total",
                                "structuring_suspect_count"}
        assert all(value >= 0 for value in summary.values())

    def test_filters(self):
        summary = ctr_monitor.get_ctr_summary({"date_from": 20240101, "date_to": 20240131})
        assert summary["high_value_count"] >= 0
