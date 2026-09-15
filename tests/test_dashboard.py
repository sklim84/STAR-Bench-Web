"""src/features/dashboard.py: summary, distributions, trends, profiles."""

import pandas as pd
import pytest

from src.data.db import query
from src.features import dashboard


class TestSummary:
    def test_summary_row(self):
        row = dashboard.get_summary().iloc[0]
        assert int(row["total_txns"]) == 4_732_130
        assert int(row["fraud_txns"]) == 14_490
        assert int(row["sender_accounts"]) == 30_526
        assert int(row["receiver_accounts"]) == 422_698
        assert int(row["sender_banks"]) == 50
        assert int(row["receiver_banks"]) == 54

    def test_summary_honours_filters(self):
        filtered = dashboard.get_summary({"date_from": 20240101, "date_to": 20241231}).iloc[0]
        assert 0 < int(filtered["total_txns"]) < 4_732_130

    def test_fraud_type_distribution_uses_hofinet_labels(self):
        df = dashboard.get_fraud_type_distribution()
        assert sorted(int(v) for v in df["fraud_type"]) == [1, 2, 3, 4, 5, 7]
        assert "Late-Night/Early-Morning Bulk Transactions" in set(df["fraud_desc"])

    def test_hourly_distribution_covers_the_eight_slots(self):
        df = dashboard.get_hourly_distribution()
        assert sorted(int(v) for v in df["hour_range"]) == [0, 3, 6, 9, 12, 15, 18, 21]

    def test_amount_distribution_is_ordered(self):
        df = dashboard.get_amount_distribution()
        assert list(df["sort_order"]) == sorted(df["sort_order"])

    def test_medium_distribution_labels(self):
        df = dashboard.get_medium_distribution()
        assert set(df["channel"]) == {
            "PC Banking", "Internet Banking", "Phone", "Mobile Phone",
            "Per-transaction Transfer", "Other", "Bulk Transfer",
        }

    def test_monthly_trend_spans_the_dataset(self):
        df = dashboard.get_monthly_trend()
        assert int(df["year_month"].min()) == 202109
        assert int(df["year_month"].max()) == 202412


class TestQuarters:
    """DuckDB's `/` is float division, which used to mis-bucket 24% of rows."""

    def test_quarterly_trend_has_fourteen_quarters(self):
        df = dashboard.get_quarterly_trend()
        assert len(df) == 14

    def test_first_quarter_matches_the_documented_counts(self):
        df = dashboard.get_quarterly_trend()
        first = df.iloc[0]
        assert (int(first["year"]), int(first["quarter"])) == (2021, 3)
        assert int(first["total_txns"]) == 98_530

    def test_quarter_boundaries_are_integer_arithmetic(self):
        df = dashboard.get_quarterly_trend()
        by_quarter = {(int(r["year"]), int(r["quarter"])): int(r["total_txns"])
                      for _, r in df.iterrows()}
        expected = int(query(
            "SELECT count(*) AS c FROM hofinet WHERE date BETWEEN 20210901 AND 20210930"
        )["c"].iloc[0])
        assert by_quarter[(2021, 3)] == expected


class TestTrendAnalysis:
    def test_quarterly_labels(self):
        df = dashboard.get_trend_analysis(unit="quarterly")
        assert len(df) == 14
        assert df["period"].iloc[0] == "2021Q3"
        assert df["period"].iloc[-1] == "2024Q4"

    def test_monthly_labels(self):
        df = dashboard.get_trend_analysis(unit="monthly")
        assert df["period"].iloc[0] == "2021-09"

    def test_columns(self):
        df = dashboard.get_trend_analysis(unit="quarterly")
        assert list(df.columns) == ["period", "transactions", "fraud_count",
                                    "fraud_ratio_percent", "total_amount", "avg_amount"]

    def test_date_range_narrows_the_result(self):
        df = dashboard.get_trend_analysis(unit="monthly", date_from=20240101, date_to=20240331)
        assert list(df["period"]) == ["2024-01", "2024-02", "2024-03"]


class TestChannelRisk:
    def test_channel_stats_use_media_type(self):
        result = dashboard.analyze_channel_risk()
        stats = result["channel_stats"]
        assert len(stats) == 7
        assert {row["media_type"] for row in stats} == set(range(1, 8))
        assert all("fraud_ratio_percent" in row for row in stats)
        assert all(row["channel_name"] != "Other" or row["media_type"] == 6 for row in stats)

    def test_cross_analysis_has_channel_and_slot(self):
        cross = dashboard.analyze_channel_risk()["channel_time_cross"]
        assert {row["hour_range"] for row in cross} <= {0, 3, 6, 9, 12, 15, 18, 21}
        assert all("channel_name" in row for row in cross)


class TestReceivingProfile:
    def test_unique_senders_counted_in_sql(self, accounts):
        aid = accounts["receiver_only"]
        profile = dashboard.get_receiving_account_profile(aid)
        expected = int(query(
            "SELECT count(DISTINCT sender_acc) AS c FROM hofinet WHERE receiver_acc = $a",
            {"a": aid})["c"].iloc[0])
        assert profile["unique_senders"] == expected
        assert len(profile["top_senders"]) <= 5

    def test_fraud_ratio_is_a_percentage(self, accounts):
        profile = dashboard.get_receiving_account_profile(accounts["receiver_only"])
        assert 0 <= profile["fraud_ratio_percent"] <= 100

    def test_account_without_inbound_transactions(self, accounts):
        profile = dashboard.get_receiving_account_profile(accounts["sender_only"])
        assert profile["total_txns"] == 0 and "notice" in profile


class TestFilterHelpers:
    def test_bank_options(self):
        banks = dashboard.get_bank_options()
        assert len(banks) == 50 and min(banks) == 102

    def test_fraud_type_options(self):
        df = dashboard.get_fraud_type_options()
        assert sorted(int(v) for v in df["fraud_type"]) == [1, 2, 3, 4, 5, 7]

    def test_date_range(self):
        assert dashboard.get_date_range() == (20210901, 20241231)

    def test_filter_conditions_are_composed(self):
        where = dashboard._apply_filters("WHERE is_fraud = 1", {"date_from": 20240101})
        assert where == "WHERE is_fraud = 1 AND date >= 20240101"

    def test_empty_filters_leave_the_clause_alone(self):
        assert dashboard._apply_filters("", None) == ""


class TestAmountAndTypeBreakdowns:
    def test_fraud_amount_summary(self):
        df = dashboard.get_fraud_amount_summary()
        assert sorted(int(v) for v in df["is_fraud"]) == [0, 1]

    def test_fraud_amount_by_type(self):
        df = dashboard.get_fraud_amount_by_type()
        assert set(df["fraud_desc"]) <= set(dashboard.FRAUD_TYPE_MAP.values())

    def test_hourly_fraud_type_heatmap(self):
        df = dashboard.get_hourly_fraud_type_heatmap()
        assert isinstance(df, pd.DataFrame) and not df.empty

    def test_fraud_type_monthly_trend(self):
        df = dashboard.get_fraud_type_monthly_trend()
        assert not df.empty and "fraud_desc" in df.columns

    def test_top_banks(self):
        df = dashboard.get_top_banks()
        assert set(df["type"]) == {"Sender", "Receiver"}

    def test_fund_type_distribution(self):
        df = dashboard.get_fund_type_distribution()
        assert sorted(int(v) for v in df["fund_type_code"]) == [0, 1, 3, 4]
