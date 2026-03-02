"""자금 흐름 분석 (src/features/flow_analyzer.py) 단위 테스트."""

import pandas as pd
import pytest

from src.features.flow_analyzer import (
    detect_smurfing_network,
    analyze_cross_institution_flow,
)


class TestDetectSmurfingNetwork:
    """detect_smurfing_network() 단위 테스트."""

    def test_returns_dataframe_inbound(self):
        result = detect_smurfing_network(direction="inbound", limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_returns_dataframe_outbound(self):
        result = detect_smurfing_network(direction="outbound", limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_min_counterparts_filter(self):
        result = detect_smurfing_network(
            direction="inbound", min_counterparts=10, limit=10,
        )
        if not result.empty:
            assert (result["거래상대수"] >= 10).all()

    def test_expected_columns_inbound(self):
        result = detect_smurfing_network(direction="inbound", limit=5)
        if not result.empty:
            expected = {"수집대상계좌", "거래상대수", "총거래건수", "총거래금액"}
            assert expected.issubset(set(result.columns))

    def test_expected_columns_outbound(self):
        result = detect_smurfing_network(direction="outbound", limit=5)
        if not result.empty:
            expected = {"분산원천계좌", "거래상대수", "총거래건수", "총거래금액"}
            assert expected.issubset(set(result.columns))

    def test_specific_account(self):
        """특정 계좌 한정 시 오류 없이 실행."""
        result = detect_smurfing_network(
            account_id=1234567890, direction="inbound", min_counterparts=1, limit=5,
        )
        assert isinstance(result, pd.DataFrame)

    def test_date_filter(self):
        result = detect_smurfing_network(
            direction="inbound",
            date_from=20240101, date_to=20240630,
            limit=10,
        )
        assert isinstance(result, pd.DataFrame)


class TestAnalyzeCrossInstitutionFlow:
    """analyze_cross_institution_flow() 단위 테스트."""

    def test_returns_dataframe(self):
        result = analyze_cross_institution_flow(limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_expected_columns(self):
        result = analyze_cross_institution_flow(limit=5)
        if not result.empty:
            expected = {"출금기관", "입금기관", "거래건수", "이상거래건수", "이상거래비율"}
            assert expected.issubset(set(result.columns))

    def test_min_transactions_filter(self):
        result = analyze_cross_institution_flow(min_transactions=100, limit=10)
        if not result.empty:
            assert (result["거래건수"] >= 100).all()

    def test_date_filter(self):
        result = analyze_cross_institution_flow(
            date_from=20240101, date_to=20240630, limit=10,
        )
        assert isinstance(result, pd.DataFrame)

    def test_non_negative_fraud_rate(self):
        result = analyze_cross_institution_flow(limit=10)
        if not result.empty:
            assert (result["이상거래비율"] >= 0).all()
