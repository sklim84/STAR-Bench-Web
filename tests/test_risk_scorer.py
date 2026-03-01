"""기능6: 계좌 위험도 평가 (src/features/risk_scorer.py) 단위 테스트."""

import pandas as pd
import pytest

from src.features.risk_scorer import (
    score_account,
    rank_risky_accounts,
    _calc_nighttime_ratio,
    _calc_amount_anomaly,
    _calc_counterparty_diversity,
    _calc_velocity_change,
    _calc_fraud_history,
)


class TestCalcNighttimeRatio:
    """_calc_nighttime_ratio() 단위 테스트."""

    def test_returns_float(self):
        result = _calc_nighttime_ratio(1)
        assert isinstance(result, float)

    def test_range_zero_to_one(self):
        result = _calc_nighttime_ratio(1)
        assert 0.0 <= result <= 1.0

    def test_nonexistent_account(self):
        """존재하지 않는 계좌는 0.0을 반환."""
        result = _calc_nighttime_ratio(999999999999)
        assert result == 0.0


class TestCalcAmountAnomaly:
    """_calc_amount_anomaly() 단위 테스트."""

    def test_returns_float(self):
        result = _calc_amount_anomaly(1)
        assert isinstance(result, float)

    def test_range_zero_to_one(self):
        result = _calc_amount_anomaly(1)
        assert 0.0 <= result <= 1.0


class TestCalcCounterpartyDiversity:
    """_calc_counterparty_diversity() 단위 테스트."""

    def test_returns_float(self):
        result = _calc_counterparty_diversity(1)
        assert isinstance(result, float)

    def test_range_zero_to_one(self):
        result = _calc_counterparty_diversity(1)
        assert 0.0 <= result <= 1.0


class TestCalcVelocityChange:
    """_calc_velocity_change() 단위 테스트."""

    def test_returns_float(self):
        result = _calc_velocity_change(1)
        assert isinstance(result, float)

    def test_range_zero_to_one(self):
        result = _calc_velocity_change(1)
        assert 0.0 <= result <= 1.0


class TestCalcFraudHistory:
    """_calc_fraud_history() 단위 테스트."""

    def test_returns_float(self):
        result = _calc_fraud_history(1)
        assert isinstance(result, float)

    def test_range_zero_to_one(self):
        result = _calc_fraud_history(1)
        assert 0.0 <= result <= 1.0


class TestScoreAccount:
    """score_account() 단위 테스트."""

    def test_returns_dict(self):
        result = score_account(1)
        assert isinstance(result, dict)

    def test_nonexistent_account_error(self):
        """존재하지 않는 계좌는 error 키를 반환."""
        result = score_account(999999999999)
        assert "error" in result

    def test_required_keys_for_valid_account(self):
        """유효 계좌에 대해 필수 키가 포함되어야 한다."""
        # 실제 데이터에서 존재하는 계좌를 찾기
        from src.data.db import query
        sample = query("SELECT DISTINCT 출금계좌일련번호 FROM hofinet LIMIT 1")
        if sample.empty:
            pytest.skip("테스트 데이터 없음")
        aid = int(sample.iloc[0]["출금계좌일련번호"])
        result = score_account(aid)
        assert "종합점수" in result
        assert "위험등급" in result
        assert "컴포넌트" in result

    def test_score_range(self):
        """종합점수가 0~100 범위인지 확인."""
        from src.data.db import query
        sample = query("SELECT DISTINCT 출금계좌일련번호 FROM hofinet LIMIT 1")
        if sample.empty:
            pytest.skip("테스트 데이터 없음")
        aid = int(sample.iloc[0]["출금계좌일련번호"])
        result = score_account(aid)
        assert 0 <= result["종합점수"] <= 100

    def test_risk_level_categories(self):
        """위험등급이 올바른 카테고리인지 확인."""
        from src.data.db import query
        sample = query("SELECT DISTINCT 출금계좌일련번호 FROM hofinet LIMIT 1")
        if sample.empty:
            pytest.skip("테스트 데이터 없음")
        aid = int(sample.iloc[0]["출금계좌일련번호"])
        result = score_account(aid)
        assert result["위험등급"] in ("높음", "중간", "낮음")


class TestRankRiskyAccounts:
    """rank_risky_accounts() 단위 테스트."""

    def test_returns_dataframe(self):
        result = rank_risky_accounts(top_k=5)
        assert isinstance(result, pd.DataFrame)

    def test_limit_works(self):
        result = rank_risky_accounts(top_k=5)
        assert len(result) <= 5

    def test_expected_columns(self):
        result = rank_risky_accounts(top_k=5)
        if not result.empty:
            expected = {"account_id", "총거래건수", "이상거래건수", "위험점수_간이"}
            assert expected.issubset(set(result.columns))

    def test_min_transactions_filter(self):
        """min_transactions 필터가 동작하는지 확인."""
        result = rank_risky_accounts(top_k=5, min_transactions=100)
        if not result.empty:
            assert (result["총거래건수"] >= 100).all()
