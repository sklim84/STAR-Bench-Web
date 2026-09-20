"""src/features/monitoring.py: the five rules, recalibrated to HOFINET ()."""

import pytest

from src.data.db import query
from src.features import monitoring


class TestRuleR001:
    def test_fires_on_the_data(self):
        df = monitoring.detect_nighttime_bulk(limit=20)
        assert not df.empty
        assert set(df["time_slot"]) <= set(monitoring.NIGHT_TIME_SLOTS)
        assert (df["amount"] >= monitoring.NIGHT_MIN_AMOUNT).all()

    def test_night_slots_cover_the_labelled_night_type(self):
        rows = int(query(
            f"SELECT count(*) AS c FROM hofinet WHERE fraud_type = 7 AND "
            f"time_slot IN ({', '.join(str(s) for s in monitoring.NIGHT_TIME_SLOTS)})"
        )["c"].iloc[0])
        assert rows == 35

    def test_date_filter(self):
        df = monitoring.detect_nighttime_bulk(date_from=20240101, date_to=20241231, limit=20)
        assert ((df["date"] >= 20240101) & (df["date"] <= 20241231)).all()

    def test_account_filter_matches_either_side(self):
        sample = monitoring.detect_nighttime_bulk(limit=1)
        aid = int(sample["sender_acc"].iloc[0])
        df = monitoring.detect_nighttime_bulk(account_id=aid, limit=20)
        assert ((df["sender_acc"] == aid) | (df["receiver_acc"] == aid)).all()


class TestRuleR002:
    def test_minimum_count(self):
        df = monitoring.detect_rapid_fire(min_count=10, limit=20)
        assert not df.empty and (df["tx_count"] >= 10).all()

    def test_account_filter(self):
        aid = int(monitoring.detect_rapid_fire(limit=1)["sender_acc"].iloc[0])
        df = monitoring.detect_rapid_fire(account_id=aid, limit=20)
        assert (df["sender_acc"] == aid).all()


class TestRuleR003:
    def test_repeated_identical_amounts(self):
        df = monitoring.detect_repeated_amounts(limit=20)
        assert not df.empty
        assert (df["repeat_count"] >= 3).all()
        assert (df["amount"] >= monitoring.REPEATED_AMOUNT_MIN).all()

    def test_repeat_count_matches_the_data(self):
        row = monitoring.detect_repeated_amounts(limit=1).iloc[0]
        actual = int(query(
            "SELECT count(*) AS c FROM hofinet WHERE sender_acc = $a AND amount = $m",
            {"a": int(row["sender_acc"]), "m": int(row["amount"])})["c"].iloc[0])
        assert int(row["repeat_count"]) == actual

    def test_rule_is_selective(self):
        """The old 'amount % 1,000,000 = 0' rule was true for every row >= 1M."""
        flagged = len(monitoring.detect_repeated_amounts(limit=100_000))
        senders = int(query("SELECT count(DISTINCT sender_acc) AS c FROM hofinet")["c"].iloc[0])
        assert 0 < flagged < senders


class TestRuleR004:
    def test_returns_more_than_one_account(self):
        df = monitoring.detect_institution_concentration(limit=50)
        assert len(df) > 1
        assert (df["concentration_percent"] >= 50).all()

    def test_dates_change_the_result(self):
        wide = monitoring.detect_institution_concentration(limit=50)
        narrow = monitoring.detect_institution_concentration(
            date_from=20240101, date_to=20240131, limit=50)
        assert not wide.equals(narrow)

    def test_account_filter(self):
        aid = int(monitoring.detect_institution_concentration(limit=1)["sender_acc"].iloc[0])
        df = monitoring.detect_institution_concentration(account_id=aid, limit=10)
        assert list(df["sender_acc"]) == [aid]

    def test_one_row_per_account(self):
        df = monitoring.detect_institution_concentration(limit=50)
        assert df["sender_acc"].is_unique


class TestRuleR005:
    def test_default_window_is_the_last_quarter(self):
        assert monitoring.default_pattern_change_period() == (20241001, 20241231)

    def test_previous_period_has_the_same_length(self):
        assert monitoring._calculate_previous_period(20240401, 20240630) == (20240101, 20240331)

    def test_reversed_dates_are_refused(self):
        with pytest.raises(ValueError):
            monitoring._calculate_previous_period(20240630, 20240401)

    def test_detects_surges(self):
        df = monitoring.detect_pattern_change(20240701, 20240930, 20241001, 20241231, limit=20)
        assert not df.empty
        assert ((df["count_change_multiple"] >= 3) | (df["amount_change_multiple"] >= 3)).all()


class TestRuleRunner:
    def test_run_rule_dispatches_every_rule(self):
        for rule_id in monitoring.RULE_NAMES:
            df = monitoring.run_rule(rule_id, limit=3)
            assert len(df) <= 3

    def test_unknown_rule(self):
        with pytest.raises(ValueError):
            monitoring.run_rule("R009")

    def test_run_all_rules_honours_the_limit(self):
        result = monitoring.run_all_rules(limit=2)
        assert set(result) == set(monitoring.RULE_NAMES)
        assert all(len(entry["result"]) <= 2 for entry in result.values())

    def test_run_all_rules_reports_counts(self):
        result = monitoring.run_all_rules(limit=5)
        assert all(entry["count"] == len(entry["result"]) for entry in result.values())


class TestDormantReactivation:
    def test_criteria(self):
        df = monitoring.detect_dormant_reactivation(limit=20)
        assert not df.empty
        assert (df["dormant_days"] >= 180).all()
        assert (df["reactivation_amount"] >= 5_000_000).all()

    def test_daily_aggregation_is_reported(self):
        df = monitoring.detect_dormant_reactivation(limit=5)
        assert (df["reactivation_day_amount"] >= df["reactivation_amount"]).all()

    def test_account_filter(self):
        aid = int(monitoring.detect_dormant_reactivation(limit=1)["sender_acc"].iloc[0])
        df = monitoring.detect_dormant_reactivation(account_id=aid, limit=10)
        assert (df["sender_acc"] == aid).all()


class TestMonitoringSummary:
    def test_summary_keys(self):
        summary = monitoring.get_monitoring_summary()
        assert set(summary) == {"total_tx_count", "night_tx_count",
                                "night_tx_ratio", "high_freq_tx_count"}
        assert summary["total_tx_count"] == 4_732_130

    def test_summary_honours_filters(self):
        summary = monitoring.get_monitoring_summary({"date_from": 20240101, "date_to": 20240131})
        assert 0 < summary["total_tx_count"] < 4_732_130
