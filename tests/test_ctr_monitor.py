"""기능5: CTR 모니터링 (src/features/ctr_monitor.py) 단위 테스트."""

import pandas as pd
import pytest

from src.features.ctr_monitor import (
    get_ctr_candidates,
    detect_structuring,
    assess_account_structuring,
    get_ctr_summary,
)


class TestGetCtrCandidates:
    """get_ctr_candidates() 단위 테스트."""

    def test_returns_dataframe(self):
        result = get_ctr_candidates(limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_all_amounts_above_threshold(self):
        """모든 결과의 거래금액이 1,000만원 이상인지 확인."""
        result = get_ctr_candidates(limit=10)
        if not result.empty:
            assert (result["거래금액"] >= 10_000_000).all()

    def test_limit_works(self):
        result = get_ctr_candidates(limit=5)
        assert len(result) <= 5

    def test_date_filter(self):
        result = get_ctr_candidates(date_from=20240101, date_to=20240331, limit=10)
        assert isinstance(result, pd.DataFrame)
        if not result.empty:
            assert (result["거래일자"] >= 20240101).all()
            assert (result["거래일자"] <= 20240331).all()

    def test_expected_columns(self):
        result = get_ctr_candidates(limit=1)
        expected_cols = {"거래일자", "거래시간대", "출금계좌일련번호", "거래금액"}
        assert expected_cols.issubset(set(result.columns))


class TestDetectStructuring:
    """detect_structuring() 단위 테스트."""

    def test_returns_dataframe(self):
        result = detect_structuring(limit=10)
        assert isinstance(result, pd.DataFrame)

    def test_expected_columns(self):
        result = detect_structuring(limit=10)
        if not result.empty:
            expected = {"출금계좌일련번호", "거래일자", "거래건수", "합산금액"}
            assert expected.issubset(set(result.columns))

    def test_structuring_conditions(self):
        """분할거래 조건: 합산 >= threshold, 최대단건 < threshold, 건수 >= 2."""
        result = detect_structuring(threshold=10_000_000, limit=20)
        if not result.empty:
            assert (result["합산금액"] >= 10_000_000).all()
            assert (result["최대단건금액"] < 10_000_000).all()
            assert (result["거래건수"] >= 2).all()

    def test_custom_threshold(self):
        result = detect_structuring(threshold=50_000_000, limit=10)
        assert isinstance(result, pd.DataFrame)


class TestAssessAccountStructuring:
    """assess_account_structuring() 단위 테스트."""

    def test_returns_dict(self):
        result = assess_account_structuring(account_id=1)
        assert isinstance(result, dict)

    def test_required_keys(self):
        result = assess_account_structuring(account_id=1)
        assert "account_id" in result
        assert "총거래건수" in result
        assert "분할거래의심일수" in result


class TestGetCtrSummary:
    """get_ctr_summary() 단위 테스트."""

    def test_returns_dict(self):
        result = get_ctr_summary()
        assert isinstance(result, dict)

    def test_required_keys(self):
        result = get_ctr_summary()
        assert "고액거래건수" in result
        assert "고액거래총액" in result
        assert "분할거래의심건수" in result

    def test_non_negative_values(self):
        result = get_ctr_summary()
        assert result["고액거래건수"] >= 0
        assert result["고액거래총액"] >= 0
        assert result["분할거래의심건수"] >= 0

    def test_with_filters(self):
        result = get_ctr_summary(filters={"date_from": 20240101, "date_to": 20240630})
        assert isinstance(result, dict)
