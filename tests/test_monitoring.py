"""기능7: 거래 모니터링 규칙 탐지 (src/features/monitoring.py) 단위 테스트."""

import pandas as pd
import pytest
from unittest.mock import patch

from src.features.monitoring import (
    detect_nighttime_bulk,
    detect_rapid_fire,
    detect_round_amounts,
    detect_institution_concentration,
    detect_pattern_change,
    run_all_rules,
    get_monitoring_summary,
    detect_dormant_reactivation,
    _calculate_previous_period,
)


class TestDetectNighttimeBulk:
    """R001: detect_nighttime_bulk() 단위 테스트."""

    def test_returns_dataframe(self):
        result = detect_nighttime_bulk(limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_nighttime_only(self):
        """결과가 심야시간대(0, 3)만 포함하는지 확인."""
        result = detect_nighttime_bulk(limit=20)
        if not result.empty:
            assert result["거래시간대"].isin([0, 3]).all()

    def test_min_amount_filter(self):
        result = detect_nighttime_bulk(min_amount=50_000_000, limit=10)
        if not result.empty:
            assert (result["거래금액"] >= 50_000_000).all()

    def test_date_filter(self):
        result = detect_nighttime_bulk(
            date_from=20240101, date_to=20240630, limit=10
        )
        assert isinstance(result, pd.DataFrame)


class TestDetectRapidFire:
    """R002: detect_rapid_fire() 단위 테스트."""

    def test_returns_dataframe(self):
        result = detect_rapid_fire(limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_min_count_condition(self):
        result = detect_rapid_fire(min_count=10, limit=20)
        if not result.empty:
            assert (result["거래건수"] >= 10).all()

    def test_expected_columns(self):
        result = detect_rapid_fire(limit=5)
        if not result.empty:
            expected = {"출금계좌일련번호", "거래일자", "거래건수", "합산금액"}
            assert expected.issubset(set(result.columns))


class TestDetectRoundAmounts:
    """R003: detect_round_amounts() 단위 테스트."""

    def test_returns_dataframe(self):
        result = detect_round_amounts(limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_expected_columns(self):
        result = detect_round_amounts(limit=5)
        if not result.empty:
            expected = {"출금계좌일련번호", "정액거래건수", "합산금액"}
            assert expected.issubset(set(result.columns))


class TestDetectInstitutionConcentration:
    """R004: detect_institution_concentration() 단위 테스트."""

    def test_returns_dataframe(self):
        result = detect_institution_concentration(limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_concentration_ratio(self):
        """집중비율이 min_ratio 이상인지 확인."""
        result = detect_institution_concentration(min_ratio=0.8, limit=10)
        if not result.empty:
            assert (result["집중비율"] >= 0.8).all()


class TestDetectPatternChange:
    """R005: detect_pattern_change() 단위 테스트."""

    def test_returns_dataframe(self):
        result = detect_pattern_change(
            base_start=20230101, base_end=20230630,
            compare_start=20230701, compare_end=20231231,
            limit=10,
        )
        assert isinstance(result, pd.DataFrame)

    def test_change_threshold(self):
        result = detect_pattern_change(
            base_start=20230101, base_end=20230630,
            compare_start=20230701, compare_end=20231231,
            change_threshold=3.0, limit=10,
        )
        assert isinstance(result, pd.DataFrame)


class TestRunAllRules:
    """run_all_rules() 단위 테스트."""

    def test_returns_dict(self):
        result = run_all_rules()
        assert isinstance(result, dict)

    def test_all_rules_present(self):
        result = run_all_rules()
        assert "R001_심야대량거래" in result
        assert "R002_동일일다건거래" in result
        assert "R003_정액거래패턴" in result
        assert "R004_기관집중거래" in result
        assert "R005_거래패턴급변" in result

    def test_each_rule_has_count(self):
        result = run_all_rules()
        for key in result:
            assert "건수" in result[key]
            assert result[key]["건수"] >= 0

    def test_previous_period_calculation_uses_calendar_days(self):
        base_start, base_end = _calculate_previous_period(20240201, 20240229)
        assert base_start == 20240103
        assert base_end == 20240131

    def test_r005_previous_period_passed_to_detector(self):
        with patch("src.features.monitoring.detect_pattern_change", return_value=pd.DataFrame()) as mock_r005:
            run_all_rules(date_from=20240201, date_to=20240229)

        args = mock_r005.call_args.args
        assert args[0] == 20240103
        assert args[1] == 20240131
        assert args[2] == 20240201
        assert args[3] == 20240229


class TestGetMonitoringSummary:
    """get_monitoring_summary() 단위 테스트."""

    def test_returns_dict(self):
        result = get_monitoring_summary()
        assert isinstance(result, dict)

    def test_required_keys(self):
        result = get_monitoring_summary()
        assert "총거래건수" in result
        assert "심야거래건수" in result
        assert "심야거래비율" in result
        assert "고빈도거래일수" in result

    def test_non_negative_values(self):
        result = get_monitoring_summary()
        assert result["총거래건수"] >= 0
        assert result["심야거래건수"] >= 0
        assert result["심야거래비율"] >= 0


class TestDetectDormantReactivation:
    """R006: detect_dormant_reactivation() 단위 테스트."""

    def test_returns_dataframe(self):
        result = detect_dormant_reactivation(limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_expected_columns(self):
        result = detect_dormant_reactivation(limit=5)
        if not result.empty:
            expected = {"출금계좌일련번호", "마지막활동일", "재활성화일", "휴면일수", "재활성화금액"}
            assert expected.issubset(set(result.columns))

    def test_dormant_days_filter(self):
        result = detect_dormant_reactivation(dormant_days=365, limit=10)
        if not result.empty:
            assert (result["휴면일수"] >= 365).all()

    def test_min_amount_filter(self):
        result = detect_dormant_reactivation(
            min_reactivation_amount=10_000_000, limit=10
        )
        if not result.empty:
            assert (result["재활성화금액"] >= 10_000_000).all()

    def test_uses_precise_date_diff_sql(self):
        with patch("src.features.monitoring.query", return_value=pd.DataFrame()) as mock_query:
            detect_dormant_reactivation(limit=1)
        sql = mock_query.call_args.args[0]
        assert "date_diff(" in sql
        assert "strptime(CAST(이전거래일자 AS VARCHAR), '%Y%m%d')" in sql
        assert "strptime(CAST(거래일자 AS VARCHAR), '%Y%m%d')" in sql
