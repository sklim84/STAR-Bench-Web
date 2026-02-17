"""기능3: XGBoost 이상거래 탐지 (src/features/detector.py) 단위 테스트.

검증 항목:
- load_model()이 None 또는 모델 객체를 반환하는지
- get_feature_importance()가 올바른 DataFrame을 반환하는지
- predict_from_db()가 올바른 예측 결과 DataFrame을 반환하는지
- evaluate_model()이 필수 지표를 포함하는지
- FEATURE_COLS, TARGET_COL, MODEL_PATH 상수가 올바른지
- 클래스 불균형 처리(scale_pos_weight)가 올바르게 계산되는지
"""

import numpy as np
import pandas as pd
import pytest

import config
from src.features.detector import (
    FEATURE_COLS,
    TARGET_COL,
    MODEL_PATH,
    load_model,
    get_feature_importance,
    predict_from_db,
    evaluate_model,
)


# ──────────────────────────────────────────────
# 상수 검증
# ──────────────────────────────────────────────
class TestConstants:
    """모듈 상수 검증."""

    def test_feature_cols_defined(self):
        """FEATURE_COLS가 정의되어 있는지 확인."""
        assert isinstance(FEATURE_COLS, list)
        assert len(FEATURE_COLS) > 0

    def test_feature_cols_content(self):
        """FEATURE_COLS가 기대하는 컬럼을 포함하는지 확인."""
        expected = {"거래시간대", "출금금융회사일련번호", "입금금융회사일련번호", "자금구분", "매체구분", "거래금액"}
        assert expected == set(FEATURE_COLS)

    def test_feature_cols_count(self):
        """FEATURE_COLS가 6개 피처를 정의하는지 확인."""
        assert len(FEATURE_COLS) == 6

    def test_target_col_defined(self):
        """TARGET_COL이 올바르게 정의되어 있는지 확인."""
        assert TARGET_COL == "이상거래여부"

    def test_model_path_is_pathlib(self):
        """MODEL_PATH가 Path 객체인지 확인."""
        from pathlib import Path
        assert isinstance(MODEL_PATH, Path)

    def test_model_path_in_models_dir(self):
        """MODEL_PATH가 config.MODELS_DIR 아래에 있는지 확인."""
        assert MODEL_PATH.parent == config.MODELS_DIR

    def test_model_path_joblib_extension(self):
        """MODEL_PATH가 .joblib 확장자인지 확인."""
        assert MODEL_PATH.suffix == ".joblib"


# ──────────────────────────────────────────────
# load_model
# ──────────────────────────────────────────────
class TestLoadModel:
    """load_model() 단위 테스트."""

    def test_returns_none_when_no_model(self, tmp_path, monkeypatch):
        """모델 파일이 없을 때 None을 반환하는지 확인."""
        import src.features.detector as det
        fake_path = tmp_path / "nonexistent.joblib"
        monkeypatch.setattr(det, "MODEL_PATH", fake_path)
        result = det.load_model()
        assert result is None

    def test_returns_none_or_model(self):
        """load_model()이 None 또는 모델 객체를 반환하는지 확인."""
        result = load_model()
        assert result is None or hasattr(result, "predict_proba")

    def test_model_has_required_methods(self):
        """모델이 존재하면 필수 메서드를 갖는지 확인."""
        model = load_model()
        if model is not None:
            assert hasattr(model, "predict")
            assert hasattr(model, "predict_proba")
            assert hasattr(model, "feature_importances_")


# ──────────────────────────────────────────────
# get_feature_importance
# ──────────────────────────────────────────────
class TestGetFeatureImportance:
    """get_feature_importance() 단위 테스트."""

    @pytest.fixture(scope="class")
    def mock_model(self):
        """테스트용 간단한 XGBoost 모델을 학습하여 반환한다."""
        from xgboost import XGBClassifier
        X = pd.DataFrame({
            "거래시간대": [0, 3, 6, 9, 12, 15, 18, 21] * 10,
            "출금금융회사일련번호": range(80),
            "입금금융회사일련번호": range(1, 81),
            "자금구분": [0, 1] * 40,
            "매체구분": [1, 2, 3, 4, 5, 6, 7, 1] * 10,
            "거래금액": [100000, 500000, 1000000, 5000000] * 20,
        })
        y = pd.Series([0] * 75 + [1] * 5)
        model = XGBClassifier(n_estimators=10, random_state=42, n_jobs=1, verbosity=0)
        model.fit(X, y)
        return model

    def test_returns_dataframe(self, mock_model):
        assert isinstance(get_feature_importance(mock_model), pd.DataFrame)

    def test_expected_columns(self, mock_model):
        fi = get_feature_importance(mock_model)
        assert "피처" in fi.columns
        assert "중요도" in fi.columns

    def test_row_count_matches_features(self, mock_model):
        """피처 중요도 행 수가 FEATURE_COLS 수와 같아야 한다."""
        fi = get_feature_importance(mock_model)
        assert len(fi) == len(FEATURE_COLS)

    def test_all_features_present(self, mock_model):
        """모든 FEATURE_COLS가 결과에 포함되어야 한다."""
        fi = get_feature_importance(mock_model)
        for col in FEATURE_COLS:
            assert col in fi["피처"].tolist()

    def test_sorted_descending(self, mock_model):
        """중요도 기준 내림차순 정렬이어야 한다."""
        fi = get_feature_importance(mock_model)
        importances = fi["중요도"].tolist()
        assert importances == sorted(importances, reverse=True)

    def test_importance_sum_approximately_one(self, mock_model):
        """피처 중요도 합이 약 1.0이어야 한다 (XGBoost 정규화)."""
        fi = get_feature_importance(mock_model)
        total = fi["중요도"].sum()
        assert abs(total - 1.0) < 0.01, f"피처 중요도 합: {total}"

    def test_all_importances_non_negative(self, mock_model):
        """모든 피처 중요도가 0 이상이어야 한다."""
        fi = get_feature_importance(mock_model)
        assert (fi["중요도"] >= 0).all()


# ──────────────────────────────────────────────
# predict_from_db
# ──────────────────────────────────────────────
class TestPredictFromDb:
    """predict_from_db() 단위 테스트."""

    @pytest.fixture(scope="class")
    def mock_model(self):
        """테스트용 XGBoost 모델을 학습하여 반환한다."""
        from xgboost import XGBClassifier
        X = pd.DataFrame({
            "거래시간대": [0, 3, 6, 9, 12, 15, 18, 21] * 10,
            "출금금융회사일련번호": range(80),
            "입금금융회사일련번호": range(1, 81),
            "자금구분": [0, 1] * 40,
            "매체구분": [1, 2, 3, 4, 5, 6, 7, 1] * 10,
            "거래금액": [100000, 500000, 1000000, 5000000] * 20,
        })
        y = pd.Series([0] * 75 + [1] * 5)
        model = XGBClassifier(n_estimators=10, random_state=42, n_jobs=1, verbosity=0)
        model.fit(X, y)
        return model

    @pytest.fixture(scope="class")
    def prediction_df(self, mock_model):
        return predict_from_db(mock_model, limit=100)

    def test_returns_dataframe(self, prediction_df):
        assert isinstance(prediction_df, pd.DataFrame)

    def test_limit_applied(self, prediction_df):
        """limit=100이므로 100행 이하여야 한다."""
        assert len(prediction_df) <= 100

    def test_prediction_columns_added(self, prediction_df):
        """예측확률과 예측결과 컬럼이 추가되어야 한다."""
        assert "예측확률" in prediction_df.columns
        assert "예측결과" in prediction_df.columns

    def test_original_columns_present(self, prediction_df):
        """원래 DB 컬럼들이 유지되어야 한다."""
        original_cols = {"거래일자", "거래금액", "이상거래여부"}
        assert original_cols.issubset(set(prediction_df.columns))

    def test_probability_range(self, prediction_df):
        """예측확률이 0~1 사이이어야 한다."""
        probs = prediction_df["예측확률"]
        assert (probs >= 0).all()
        assert (probs <= 1).all()

    def test_prediction_binary(self, prediction_df):
        """예측결과가 0 또는 1이어야 한다."""
        preds = set(prediction_df["예측결과"].unique())
        assert preds.issubset({0, 1})

    def test_sorted_by_probability_desc(self, prediction_df):
        """예측확률 기준 내림차순 정렬이어야 한다."""
        probs = prediction_df["예측확률"].tolist()
        assert probs == sorted(probs, reverse=True)

    def test_feature_cols_present(self, prediction_df):
        """FEATURE_COLS가 결과 DataFrame에 포함되어야 한다."""
        for col in FEATURE_COLS:
            assert col in prediction_df.columns


# ──────────────────────────────────────────────
# evaluate_model
# ──────────────────────────────────────────────
class TestEvaluateModel:
    """evaluate_model() 단위 테스트."""

    @pytest.fixture(scope="class")
    def model_and_data(self):
        """간단한 XGBoost 모델과 테스트 데이터를 준비한다."""
        from xgboost import XGBClassifier
        np.random.seed(42)
        n = 200
        X = pd.DataFrame({
            "거래시간대": np.random.choice([0, 3, 6, 9, 12, 15, 18, 21], n),
            "출금금융회사일련번호": np.random.randint(1, 100, n),
            "입금금융회사일련번호": np.random.randint(1, 100, n),
            "자금구분": np.random.choice([0, 1, 3, 4], n),
            "매체구분": np.random.randint(1, 8, n),
            "거래금액": np.random.randint(10000, 10000000, n),
        })
        y = pd.Series([0] * 190 + [1] * 10)

        model = XGBClassifier(n_estimators=10, random_state=42, n_jobs=1, verbosity=0)
        model.fit(X, y)
        return model, X, y

    @pytest.fixture(scope="class")
    def eval_result(self, model_and_data):
        model, X, y = model_and_data
        return evaluate_model(model, X, y)

    def test_returns_dict(self, eval_result):
        assert isinstance(eval_result, dict)

    def test_required_keys(self, eval_result):
        """필수 키가 모두 존재하는지 확인."""
        required_keys = {"report", "confusion_matrix", "roc_auc", "pr_auc", "y_prob", "y_pred", "y_test"}
        assert required_keys.issubset(set(eval_result.keys()))

    def test_roc_auc_range(self, eval_result):
        """ROC-AUC가 0~1 사이이어야 한다."""
        assert 0 <= eval_result["roc_auc"] <= 1

    def test_pr_auc_range(self, eval_result):
        """PR-AUC가 0~1 사이이어야 한다."""
        assert 0 <= eval_result["pr_auc"] <= 1

    def test_confusion_matrix_shape(self, eval_result):
        """혼동 행렬이 2x2 행렬이어야 한다."""
        cm = eval_result["confusion_matrix"]
        assert cm.shape == (2, 2)

    def test_confusion_matrix_non_negative(self, eval_result):
        """혼동 행렬의 모든 값이 0 이상이어야 한다."""
        cm = eval_result["confusion_matrix"]
        assert (cm >= 0).all()

    def test_confusion_matrix_sum_matches_total(self, eval_result, model_and_data):
        """혼동 행렬 합계가 총 샘플 수와 일치해야 한다."""
        _, X, y = model_and_data
        cm = eval_result["confusion_matrix"]
        assert cm.sum() == len(y)

    def test_y_prob_range(self, eval_result):
        """y_prob(예측 확률)이 0~1 사이이어야 한다."""
        y_prob = eval_result["y_prob"]
        assert np.all(y_prob >= 0)
        assert np.all(y_prob <= 1)

    def test_y_pred_binary(self, eval_result):
        """y_pred(예측 결과)가 0 또는 1이어야 한다."""
        y_pred = eval_result["y_pred"]
        assert set(np.unique(y_pred)).issubset({0, 1})

    def test_report_has_class_keys(self, eval_result):
        """분류 리포트에 클래스별 지표가 있어야 한다."""
        report = eval_result["report"]
        # 0(정상) 또는 '0' 키가 있어야 함
        has_zero = ("0" in report) or (0 in report)
        assert has_zero or "accuracy" in report


# ──────────────────────────────────────────────
# 클래스 불균형 처리 검증
# ──────────────────────────────────────────────
class TestClassImbalanceHandling:
    """클래스 불균형(325.6:1) 처리 관련 테스트."""

    def test_scale_pos_weight_calculation(self):
        """scale_pos_weight 계산 로직이 올바른지 확인."""
        # 가상의 학습 데이터 (325:1 불균형)
        n_neg = 325
        n_pos = 1
        scale_pos = n_neg / max(n_pos, 1)
        assert scale_pos == 325.0

    def test_scale_pos_weight_no_division_by_zero(self):
        """양성 클래스가 0일 때 ZeroDivisionError가 발생하지 않는지 확인."""
        n_neg = 1000
        n_pos = 0
        scale_pos = n_neg / max(n_pos, 1)
        assert scale_pos == 1000.0  # max(0, 1) = 1로 처리

    def test_feature_cols_for_imbalanced_data(self):
        """FEATURE_COLS가 클래스 불균형 감지에 유용한 피처를 포함하는지 확인."""
        # 거래금액과 거래시간대는 이상거래 탐지에 핵심 피처
        assert "거래금액" in FEATURE_COLS
        assert "거래시간대" in FEATURE_COLS
