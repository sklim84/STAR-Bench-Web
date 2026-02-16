"""기능1: 기본 분석 대시보드 (src/features/dashboard.py) 단위 테스트.

검증 항목:
- 각 쿼리 함수가 올바른 DataFrame을 반환하는지
- 반환 컬럼 이름과 수가 기대값과 일치하는지
- 데이터 값의 범위와 정합성이 올바른지
- 페이지(1_Dashboard.py)에서 사용하는 데이터 변환이 정상 동작하는지
"""

import pandas as pd
import pytest

from src.features.dashboard import (
    get_summary,
    get_monthly_trend,
    get_quarterly_trend,
    get_hourly_distribution,
    get_amount_distribution,
    get_fraud_type_distribution,
    get_medium_distribution,
    get_top_banks,
)


# ──────────────────────────────────────────────
# get_summary
# ──────────────────────────────────────────────
class TestGetSummary:
    """get_summary() 단위 테스트."""

    @pytest.fixture(scope="class")
    def summary(self):
        return get_summary()

    def test_returns_dataframe(self, summary):
        assert isinstance(summary, pd.DataFrame)

    def test_single_row(self, summary):
        """집계 결과는 정확히 1행이어야 한다."""
        assert len(summary) == 1

    def test_expected_columns(self, summary):
        expected = {"총거래", "이상거래", "이상거래비율", "출금계좌수", "입금계좌수", "총거래금액"}
        assert expected.issubset(set(summary.columns))

    def test_total_transactions(self, summary):
        """총 거래 건수가 4,732,130인지 확인."""
        assert int(summary["총거래"].iloc[0]) == 4_732_130

    def test_fraud_count_positive(self, summary):
        """이상거래 건수가 0보다 큰지 확인."""
        assert int(summary["이상거래"].iloc[0]) > 0

    def test_fraud_ratio_range(self, summary):
        """이상거래 비율이 0~100% 사이인지 확인."""
        ratio = float(summary["이상거래비율"].iloc[0])
        assert 0 < ratio < 100

    def test_fraud_ratio_consistency(self, summary):
        """이상거래비율 = 이상거래/총거래 * 100 인지 확인."""
        row = summary.iloc[0]
        expected = float(row["이상거래"]) * 100.0 / float(row["총거래"])
        actual = float(row["이상거래비율"])
        assert abs(actual - expected) < 0.01

    def test_account_counts_positive(self, summary):
        """출금/입금 계좌 수가 모두 양수인지 확인."""
        assert int(summary["출금계좌수"].iloc[0]) > 0
        assert int(summary["입금계좌수"].iloc[0]) > 0

    def test_total_amount_positive(self, summary):
        """총 거래금액이 양수인지 확인."""
        assert float(summary["총거래금액"].iloc[0]) > 0

    def test_page_metric_formatting(self, summary):
        """페이지에서 사용하는 f-string 포맷팅이 오류 없이 동작하는지 확인."""
        row = summary.iloc[0]
        assert f"{int(row['총거래']):,}" != ""
        assert f"{int(row['이상거래']):,}" != ""
        assert f"{row['이상거래비율']:.2f}%" != ""
        assert f"{int(row['출금계좌수']):,}" != ""
        assert f"{int(row['입금계좌수']):,}" != ""


# ──────────────────────────────────────────────
# get_monthly_trend
# ──────────────────────────────────────────────
class TestGetMonthlyTrend:
    """get_monthly_trend() 단위 테스트."""

    @pytest.fixture(scope="class")
    def monthly(self):
        return get_monthly_trend()

    def test_returns_dataframe(self, monthly):
        assert isinstance(monthly, pd.DataFrame)

    def test_expected_columns(self, monthly):
        expected = {"연월", "총거래", "이상거래", "이상거래비율"}
        assert expected.issubset(set(monthly.columns))

    def test_multiple_months(self, monthly):
        """최소 12개월 이상 데이터가 있는지 확인."""
        assert len(monthly) >= 12

    def test_sorted_by_month(self, monthly):
        """연월 기준 오름차순 정렬인지 확인."""
        months = monthly["연월"].tolist()
        assert months == sorted(months)

    def test_month_values_valid(self, monthly):
        """연월 값이 YYYYMM 형식(202107~202412 범위)인지 확인."""
        for ym in monthly["연월"]:
            ym_int = int(ym)
            year = ym_int // 100
            month = ym_int % 100
            assert 2021 <= year <= 2024, f"유효하지 않은 연도: {year}"
            assert 1 <= month <= 12, f"유효하지 않은 월: {month}"

    def test_total_sum_matches_overall(self, monthly):
        """월별 총거래 합이 전체 건수와 일치하는지 확인."""
        total = int(monthly["총거래"].sum())
        assert total == 4_732_130

    def test_page_string_formatting(self, monthly):
        """페이지에서 사용하는 '연월str' 변환이 정상 동작하는지 확인."""
        df = monthly.copy()
        df["연월str"] = df["연월"].astype(str).str[:4] + "-" + df["연월"].astype(str).str[4:]
        # YYYY-MM 형식 검증
        for val in df["연월str"]:
            assert len(val) == 7  # "2021-07"
            assert val[4] == "-"


# ──────────────────────────────────────────────
# get_quarterly_trend
# ──────────────────────────────────────────────
class TestGetQuarterlyTrend:
    """get_quarterly_trend() 단위 테스트."""

    @pytest.fixture(scope="class")
    def quarterly(self):
        return get_quarterly_trend()

    def test_returns_dataframe(self, quarterly):
        assert isinstance(quarterly, pd.DataFrame)

    def test_expected_columns(self, quarterly):
        expected = {"연도", "분기", "총거래", "이상거래", "이상거래비율"}
        assert expected.issubset(set(quarterly.columns))

    def test_quarter_count(self, quarterly):
        """13개 분기(2021Q4 ~ 2024Q4) 데이터가 있는지 확인."""
        assert len(quarterly) == 13

    def test_quarter_values_valid(self, quarterly):
        """분기 값이 1~4인지 확인."""
        for q in quarterly["분기"]:
            assert int(q) in {1, 2, 3, 4}

    def test_year_range(self, quarterly):
        """연도가 2021~2024 범위인지 확인."""
        years = set(int(y) for y in quarterly["연도"])
        assert years.issubset({2021, 2022, 2023, 2024})

    def test_total_sum_matches_overall(self, quarterly):
        """분기별 총거래 합이 전체 건수와 일치하는지 확인."""
        total = int(quarterly["총거래"].sum())
        assert total == 4_732_130


# ──────────────────────────────────────────────
# get_hourly_distribution
# ──────────────────────────────────────────────
class TestGetHourlyDistribution:
    """get_hourly_distribution() 단위 테스트."""

    @pytest.fixture(scope="class")
    def hourly(self):
        return get_hourly_distribution()

    def test_returns_dataframe(self, hourly):
        assert isinstance(hourly, pd.DataFrame)

    def test_expected_columns(self, hourly):
        expected = {"거래시간대", "총거래", "이상거래", "이상거래비율"}
        assert expected.issubset(set(hourly.columns))

    def test_eight_time_slots(self, hourly):
        """3시간 단위 8개 시간대가 있는지 확인."""
        assert len(hourly) == 8

    def test_time_slot_values(self, hourly):
        """시간대 값이 {0,3,6,9,12,15,18,21}인지 확인."""
        slots = set(int(h) for h in hourly["거래시간대"])
        assert slots == {0, 3, 6, 9, 12, 15, 18, 21}

    def test_sorted_by_time(self, hourly):
        """시간대 기준 오름차순 정렬인지 확인."""
        slots = hourly["거래시간대"].tolist()
        assert slots == sorted(slots)

    def test_total_sum_matches_overall(self, hourly):
        """시간대별 총거래 합이 전체 건수와 일치하는지 확인."""
        total = int(hourly["총거래"].sum())
        assert total == 4_732_130

    def test_page_label_formatting(self, hourly):
        """페이지에서 사용하는 '시간대명' 변환이 정상 동작하는지 확인."""
        df = hourly.copy()
        df["시간대명"] = df["거래시간대"].apply(lambda h: f"{h:02d}~{h+3:02d}시")
        for label in df["시간대명"]:
            assert "시" in label
            assert "~" in label


# ──────────────────────────────────────────────
# get_amount_distribution
# ──────────────────────────────────────────────
class TestGetAmountDistribution:
    """get_amount_distribution() 단위 테스트."""

    @pytest.fixture(scope="class")
    def amount(self):
        return get_amount_distribution()

    def test_returns_dataframe(self, amount):
        assert isinstance(amount, pd.DataFrame)

    def test_expected_columns(self, amount):
        expected = {"금액구간", "순서", "총거래", "이상거래", "이상거래비율"}
        assert expected.issubset(set(amount.columns))

    def test_six_bins(self, amount):
        """6개 금액 구간이 있는지 확인."""
        assert len(amount) == 6

    def test_bin_names(self, amount):
        """기대하는 구간 이름이 모두 포함되어 있는지 확인."""
        expected_names = {"1만 이하", "1만~10만", "10만~100만", "100만~1000만", "1000만~1억", "1억 초과"}
        actual_names = set(amount["금액구간"].tolist())
        assert actual_names == expected_names

    def test_sorted_by_order(self, amount):
        """순서 컬럼 기준으로 정렬되어 있는지 확인."""
        orders = amount["순서"].tolist()
        assert orders == sorted(orders)

    def test_total_sum_matches_overall(self, amount):
        """금액구간별 총거래 합이 전체 건수와 일치하는지 확인."""
        total = int(amount["총거래"].sum())
        assert total == 4_732_130

    def test_fraud_ratio_consistency(self, amount):
        """각 구간의 이상거래비율이 이상거래/총거래*100과 일치하는지 확인."""
        for _, row in amount.iterrows():
            if int(row["총거래"]) > 0:
                expected = float(row["이상거래"]) * 100.0 / float(row["총거래"])
                actual = float(row["이상거래비율"])
                assert abs(actual - expected) < 0.01, f"구간 {row['금액구간']}: 기대 {expected}, 실제 {actual}"


# ──────────────────────────────────────────────
# get_fraud_type_distribution
# ──────────────────────────────────────────────
class TestGetFraudTypeDistribution:
    """get_fraud_type_distribution() 단위 테스트."""

    @pytest.fixture(scope="class")
    def fraud_type(self):
        return get_fraud_type_distribution()

    def test_returns_dataframe(self, fraud_type):
        assert isinstance(fraud_type, pd.DataFrame)

    def test_expected_columns(self, fraud_type):
        expected = {"이상거래유형", "이상거래설명", "건수"}
        assert expected.issubset(set(fraud_type.columns))

    def test_six_fraud_types(self, fraud_type):
        """이상거래유형이 6종류인지 확인."""
        assert len(fraud_type) == 6

    def test_all_counts_positive(self, fraud_type):
        """모든 건수가 양수인지 확인."""
        for cnt in fraud_type["건수"]:
            assert int(cnt) > 0

    def test_descriptions_not_empty(self, fraud_type):
        """이상거래설명이 비어있지 않은지 확인."""
        for desc in fraud_type["이상거래설명"]:
            assert desc is not None and len(str(desc)) > 0

    def test_total_matches_fraud_count(self, fraud_type):
        """유형별 건수 합이 전체 이상거래 건수와 일치하는지 확인."""
        summary = get_summary()
        expected_fraud = int(summary["이상거래"].iloc[0])
        actual_total = int(fraud_type["건수"].sum())
        assert actual_total == expected_fraud

    def test_page_label_formatting(self, fraud_type):
        """페이지에서 사용하는 '레이블' 변환이 정상 동작하는지 확인."""
        df = fraud_type.copy()
        df["레이블"] = df["이상거래유형"].astype(int).astype(str) + ". " + df["이상거래설명"].fillna("")
        for label in df["레이블"]:
            assert ". " in label
            assert len(label) > 3


# ──────────────────────────────────────────────
# get_medium_distribution
# ──────────────────────────────────────────────
class TestGetMediumDistribution:
    """get_medium_distribution() 단위 테스트."""

    @pytest.fixture(scope="class")
    def medium(self):
        return get_medium_distribution()

    def test_returns_dataframe(self, medium):
        assert isinstance(medium, pd.DataFrame)

    def test_expected_columns(self, medium):
        expected = {"매체구분", "총거래", "이상거래", "이상거래비율"}
        assert expected.issubset(set(medium.columns))

    def test_seven_medium_types(self, medium):
        """매체구분이 7종류인지 확인."""
        assert len(medium) == 7

    def test_sorted_by_medium(self, medium):
        """매체구분 기준 오름차순 정렬인지 확인."""
        codes = medium["매체구분"].tolist()
        assert codes == sorted(codes)

    def test_total_sum_matches_overall(self, medium):
        """매체구분별 총거래 합이 전체 건수와 일치하는지 확인."""
        total = int(medium["총거래"].sum())
        assert total == 4_732_130

    def test_page_label_formatting(self, medium):
        """페이지에서 사용하는 '매체명' 변환이 정상 동작하는지 확인."""
        df = medium.copy()
        df["매체명"] = "매체 " + df["매체구분"].astype(str)
        for label in df["매체명"]:
            assert label.startswith("매체 ")


# ──────────────────────────────────────────────
# get_top_banks
# ──────────────────────────────────────────────
class TestGetTopBanks:
    """get_top_banks() 단위 테스트."""

    @pytest.fixture(scope="class")
    def banks(self):
        return get_top_banks()

    def test_returns_dataframe(self, banks):
        assert isinstance(banks, pd.DataFrame)

    def test_expected_columns(self, banks):
        expected = {"금융회사", "구분", "총거래", "이상거래", "이상거래비율"}
        assert expected.issubset(set(banks.columns))

    def test_has_both_types(self, banks):
        """출금과 입금 양쪽 데이터가 모두 있는지 확인."""
        types = set(banks["구분"].tolist())
        assert "출금" in types
        assert "입금" in types

    def test_all_have_fraud(self, banks):
        """모든 행의 이상거래 건수가 1 이상인지 확인 (HAVING 조건)."""
        for fraud in banks["이상거래"]:
            assert int(fraud) > 0

    def test_fraud_ratio_valid(self, banks):
        """이상거래비율이 0~100% 사이인지 확인."""
        for ratio in banks["이상거래비율"]:
            assert 0 < float(ratio) <= 100

    def test_page_filter_withdraw(self, banks):
        """페이지에서 사용하는 출금 필터링 및 상위 20개 추출이 동작하는지 확인."""
        banks_out = banks[banks["구분"] == "출금"].sort_values("이상거래", ascending=False).head(20)
        assert len(banks_out) > 0
        assert len(banks_out) <= 20
        # 내림차순 정렬 확인
        fraud_vals = banks_out["이상거래"].tolist()
        assert fraud_vals == sorted(fraud_vals, reverse=True)

    def test_page_filter_deposit(self, banks):
        """페이지에서 사용하는 입금 필터링 및 상위 20개 추출이 동작하는지 확인."""
        banks_in = banks[banks["구분"] == "입금"].sort_values("이상거래", ascending=False).head(20)
        assert len(banks_in) > 0
        assert len(banks_in) <= 20

    def test_page_string_conversion(self, banks):
        """페이지에서 사용하는 '금융회사명' 문자열 변환이 동작하는지 확인."""
        banks_out = banks[banks["구분"] == "출금"].head(5).copy()
        banks_out["금융회사명"] = banks_out["금융회사"].astype(str)
        for name in banks_out["금융회사명"]:
            assert isinstance(name, str)
            assert len(name) > 0
