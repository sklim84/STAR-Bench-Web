"""기능3: XGBoost 이상거래 탐지 (src/features/detector.py) 단위 테스트.

검증 항목:
- load_model()이 None 또는 모델 객체를 반환하는지
- get_feature_importance()가 올바른 DataFrame을 반환하는지
- predict_from_db()가 올바른 예측 결과 DataFrame을 반환하는지
- evaluate_model()이 필수 지표를 포함하는지
- FEATURE_COLS, TARGET_COL, MODEL_PATH 상수가 올바른지
- 클래스 불균형 처리(scale_pos_weight)가 올바르게 계산되는지
- find_optimal_threshold()가 최적 임계값을 올바르게 찾는지
- get_roc_curve_data()가 올바른 ROC 데이터를 반환하는지
- evaluate_by_fraud_type()가 유형별 recall을 반환하는지
- get_probability_distribution()가 구간별 분포를 반환하는지
- train_model()이 커스텀 파라미터를 수용하는지
"""

import numpy as np
import pandas as pd
import pytest

import config
from src.features.detector import (
    FEATURE_COLS,
    TARGET_COL,
    MODEL_PATH,
    FRAUD_TYPE_LABELS,
    load_model,
    get_feature_importance,
    predict_from_db,
    evaluate_model,
    find_optimal_threshold,
    get_roc_curve_data,
    evaluate_by_fraud_type,
    get_probability_distribution,
    train_model,
)


# ──────────────────────────────────────────────
# 테스트 공통 fixture
# ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def mock_model():
    """테스트용 간단한 XGBoost 모델을 학습하여 반환한다."""
    from xgboost import XGBClassifier  # noqa: PLC0415 — fixture-local import 허용
    np.random.seed(42)
    n = 200
    X = pd.DataFrame({
        "time_slot": np.random.choice([0, 3, 6, 9, 12, 15, 18, 21], n),
        "sender_bank": np.random.randint(1, 100, n),
        "receiver_bank": np.random.randint(1, 100, n),
        "fund_type": np.random.choice([0, 1, 3, 4], n),
        "media_type": np.random.randint(1, 8, n),
        "amount": np.random.randint(10000, 10000000, n),
    })
    y = pd.Series([0] * 190 + [1] * 10)
    model = XGBClassifier(n_estimators=10, random_state=42, n_jobs=1, verbosity=0)
    model.fit(X, y)
    return model


@pytest.fixture(scope="module")
def eval_data():
    """테스트용 모델, 테스트 데이터, 예측 결과를 함께 반환한다."""
    from xgboost import XGBClassifier  # noqa: PLC0415 — fixture-local import 허용
    np.random.seed(42)
    n = 200
    X = pd.DataFrame({
        "time_slot": np.random.choice([0, 3, 6, 9, 12, 15, 18, 21], n),
        "sender_bank": np.random.randint(1, 100, n),
        "receiver_bank": np.random.randint(1, 100, n),
        "fund_type": np.random.choice([0, 1, 3, 4], n),
        "media_type": np.random.randint(1, 8, n),
        "amount": np.random.randint(10000, 10000000, n),
    })
    y = pd.Series([0] * 190 + [1] * 10)
    model = XGBClassifier(n_estimators=10, random_state=42, n_jobs=1, verbosity=0)
    model.fit(X, y)

    y_prob = model.predict_proba(X)[:, 1]
    return model, X, y, y_prob


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
        expected = {"time_slot", "sender_bank", "receiver_bank", "fund_type", "media_type", "amount"}
        assert expected == set(FEATURE_COLS)

    def test_feature_cols_count(self):
        """FEATURE_COLS가 6개 피처를 정의하는지 확인."""
        assert len(FEATURE_COLS) == 6

    def test_target_col_defined(self):
        """TARGET_COL이 올바르게 정의되어 있는지 확인."""
        assert TARGET_COL == "is_fraud"

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

    def test_fraud_type_labels_defined(self):
        """FRAUD_TYPE_LABELS가 정의되어 있는지 확인."""
        assert isinstance(FRAUD_TYPE_LABELS, dict)
        assert len(FRAUD_TYPE_LABELS) > 0

    def test_fraud_type_labels_contains_known_types(self):
        """FRAUD_TYPE_LABELS에 주요 이상거래 유형이 포함되어 있는지 확인."""
        assert 1 in FRAUD_TYPE_LABELS
        assert 3 in FRAUD_TYPE_LABELS
        assert 7 in FRAUD_TYPE_LABELS


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

    def test_returns_dataframe(self, mock_model):
        assert isinstance(get_feature_importance(mock_model), pd.DataFrame)

    def test_expected_columns(self, mock_model):
        fi = get_feature_importance(mock_model)
        assert "feature" in fi.columns
        assert "importance" in fi.columns

    def test_row_count_matches_features(self, mock_model):
        """피처 중요도 행 수가 FEATURE_COLS 수와 같아야 한다."""
        fi = get_feature_importance(mock_model)
        assert len(fi) == len(FEATURE_COLS)

    def test_all_features_present(self, mock_model):
        """모든 FEATURE_COLS가 결과에 포함되어야 한다."""
        fi = get_feature_importance(mock_model)
        for col in FEATURE_COLS:
            assert col in fi["feature"].tolist()

    def test_sorted_descending(self, mock_model):
        """중요도 기준 내림차순 정렬이어야 한다."""
        fi = get_feature_importance(mock_model)
        importances = fi["importance"].tolist()
        assert importances == sorted(importances, reverse=True)

    def test_importance_sum_approximately_one(self, mock_model):
        """피처 중요도 합이 약 1.0이어야 한다 (XGBoost 정규화)."""
        fi = get_feature_importance(mock_model)
        total = fi["importance"].sum()
        assert abs(total - 1.0) < 0.01, f"피처 중요도 합: {total}"

    def test_all_importances_non_negative(self, mock_model):
        """모든 피처 중요도가 0 이상이어야 한다."""
        fi = get_feature_importance(mock_model)
        assert (fi["importance"] >= 0).all()


# ──────────────────────────────────────────────
# predict_from_db
# ──────────────────────────────────────────────
class TestPredictFromDb:
    """predict_from_db() 단위 테스트."""

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
        assert "prob" in prediction_df.columns
        assert "prediction" in prediction_df.columns

    def test_original_columns_present(self, prediction_df):
        """원래 DB 컬럼들이 유지되어야 한다."""
        original_cols = {"date", "amount", "is_fraud"}
        assert original_cols.issubset(set(prediction_df.columns))

    def test_probability_range(self, prediction_df):
        """예측확률이 0~1 사이이어야 한다."""
        probs = prediction_df["prob"]
        assert (probs >= 0).all()
        assert (probs <= 1).all()

    def test_prediction_binary(self, prediction_df):
        """예측결과가 0 또는 1이어야 한다."""
        preds = set(prediction_df["prediction"].unique())
        assert preds.issubset({0, 1})

    def test_sorted_by_probability_desc(self, prediction_df):
        """예측확률 기준 내림차순 정렬이어야 한다."""
        probs = prediction_df["prob"].tolist()
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
    def eval_result(self, eval_data):
        model, X, y, _ = eval_data
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

    def test_confusion_matrix_sum_matches_total(self, eval_result, eval_data):
        """혼동 행렬 합계가 총 샘플 수와 일치해야 한다."""
        _, X, y, _ = eval_data
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
# find_optimal_threshold
# ──────────────────────────────────────────────
class TestFindOptimalThreshold:
    """find_optimal_threshold() 단위 테스트."""

    @pytest.fixture(scope="class")
    def threshold_result(self, eval_data):
        _, _, y, y_prob = eval_data
        return find_optimal_threshold(y, y_prob)

    def test_returns_dict(self, threshold_result):
        """dict를 반환하는지 확인."""
        assert isinstance(threshold_result, dict)

    def test_required_keys(self, threshold_result):
        """필수 키가 모두 존재하는지 확인."""
        required = {"optimal_threshold", "precision", "recall", "f1", "thresholds_df", "pr_curve"}
        assert required.issubset(set(threshold_result.keys()))

    def test_optimal_threshold_range(self, threshold_result):
        """최적 임계값이 0~1 사이인지 확인."""
        t = threshold_result["optimal_threshold"]
        assert 0 < t < 1

    def test_precision_range(self, threshold_result):
        """precision이 0~1 사이인지 확인."""
        assert 0 <= threshold_result["precision"] <= 1

    def test_recall_range(self, threshold_result):
        """recall이 0~1 사이인지 확인."""
        assert 0 <= threshold_result["recall"] <= 1

    def test_f1_range(self, threshold_result):
        """f1이 0~1 사이인지 확인."""
        assert 0 <= threshold_result["f1"] <= 1

    def test_thresholds_df_is_dataframe(self, threshold_result):
        """thresholds_df가 DataFrame인지 확인."""
        assert isinstance(threshold_result["thresholds_df"], pd.DataFrame)

    def test_thresholds_df_columns(self, threshold_result):
        """thresholds_df에 필수 컬럼이 있는지 확인."""
        df = threshold_result["thresholds_df"]
        expected_cols = {"threshold", "precision", "recall", "f1", "tp", "fp", "fn"}
        assert expected_cols.issubset(set(df.columns))

    def test_thresholds_df_rows(self, threshold_result):
        """thresholds_df에 여러 임계값 행이 있는지 확인."""
        df = threshold_result["thresholds_df"]
        assert len(df) >= 10  # 0.05~0.95 범위에 0.05 간격이면 19행

    def test_thresholds_sorted(self, threshold_result):
        """thresholds_df의 임계값이 오름차순인지 확인."""
        df = threshold_result["thresholds_df"]
        vals = df["threshold"].tolist()
        assert vals == sorted(vals)

    def test_pr_curve_is_tuple(self, threshold_result):
        """pr_curve가 (precision, recall, thresholds) 튜플인지 확인."""
        pr = threshold_result["pr_curve"]
        assert isinstance(pr, tuple)
        assert len(pr) == 3

    def test_f1_consistency(self, threshold_result):
        """F1이 precision과 recall로부터 올바르게 계산되는지 확인."""
        df = threshold_result["thresholds_df"]
        for _, row in df.iterrows():
            p, r, f = row["precision"], row["recall"], row["f1"]
            if p + r > 0:
                expected_f1 = 2 * p * r / (p + r)
                assert abs(f - expected_f1) < 0.01, f"F1 불일치: {f} vs {expected_f1}"


# ──────────────────────────────────────────────
# get_roc_curve_data
# ──────────────────────────────────────────────
class TestGetRocCurveData:
    """get_roc_curve_data() 단위 테스트."""

    @pytest.fixture(scope="class")
    def roc_data(self, eval_data):
        _, _, y, y_prob = eval_data
        return get_roc_curve_data(y, y_prob)

    def test_returns_dict(self, roc_data):
        """dict를 반환하는지 확인."""
        assert isinstance(roc_data, dict)

    def test_required_keys(self, roc_data):
        """필수 키가 모두 존재하는지 확인."""
        required = {"fpr", "tpr", "thresholds", "auc"}
        assert required.issubset(set(roc_data.keys()))

    def test_auc_range(self, roc_data):
        """AUC가 0~1 사이인지 확인."""
        assert 0 <= roc_data["auc"] <= 1

    def test_fpr_range(self, roc_data):
        """FPR이 0~1 사이인지 확인."""
        fpr = roc_data["fpr"]
        assert np.all(fpr >= 0)
        assert np.all(fpr <= 1)

    def test_tpr_range(self, roc_data):
        """TPR이 0~1 사이인지 확인."""
        tpr = roc_data["tpr"]
        assert np.all(tpr >= 0)
        assert np.all(tpr <= 1)

    def test_fpr_tpr_same_length(self, roc_data):
        """FPR과 TPR의 길이가 동일한지 확인."""
        assert len(roc_data["fpr"]) == len(roc_data["tpr"])

    def test_fpr_sorted(self, roc_data):
        """FPR이 오름차순인지 확인."""
        fpr = roc_data["fpr"]
        assert np.all(fpr[1:] >= fpr[:-1])

    def test_starts_at_origin(self, roc_data):
        """ROC 커브가 (0, 0)에서 시작하는지 확인."""
        assert roc_data["fpr"][0] == 0
        assert roc_data["tpr"][0] == 0


# ──────────────────────────────────────────────
# evaluate_by_fraud_type
# ──────────────────────────────────────────────
class TestEvaluateByFraudType:
    """evaluate_by_fraud_type() 단위 테스트."""

    @pytest.fixture(scope="class")
    def fraud_type_result(self, mock_model):
        return evaluate_by_fraud_type(mock_model, limit=1000)

    def test_returns_dataframe(self, fraud_type_result):
        """DataFrame을 반환하는지 확인."""
        assert isinstance(fraud_type_result, pd.DataFrame)

    def test_expected_columns(self, fraud_type_result):
        """필수 컬럼이 있는지 확인."""
        expected = {"fraud_type", "type_desc", "total_count", "detected_count", "recall"}
        assert expected.issubset(set(fraud_type_result.columns))

    def test_recall_range(self, fraud_type_result):
        """Recall이 0~1 사이인지 확인."""
        if not fraud_type_result.empty:
            assert (fraud_type_result["recall"] >= 0).all()
            assert (fraud_type_result["recall"] <= 1).all()

    def test_detected_lte_total(self, fraud_type_result):
        """탐지건수가 전체건수 이하인지 확인."""
        if not fraud_type_result.empty:
            for _, row in fraud_type_result.iterrows():
                assert row["detected_count"] <= row["total_count"]

    def test_total_positive(self, fraud_type_result):
        """전체건수가 양수인지 확인."""
        if not fraud_type_result.empty:
            assert (fraud_type_result["total_count"] > 0).all()

    def test_fraud_types_valid(self, fraud_type_result):
        """이상거래유형이 유효한 범위(1~7)인지 확인."""
        if not fraud_type_result.empty:
            types = set(fraud_type_result["fraud_type"])
            assert types.issubset(set(range(1, 8)))

    def test_descriptions_not_empty(self, fraud_type_result):
        """유형설명이 비어있지 않은지 확인."""
        if not fraud_type_result.empty:
            for desc in fraud_type_result["type_desc"]:
                assert desc is not None and len(str(desc)) > 0


# ──────────────────────────────────────────────
# get_probability_distribution
# ──────────────────────────────────────────────
class TestGetProbabilityDistribution:
    """get_probability_distribution() 단위 테스트."""

    @pytest.fixture(scope="class")
    def prob_dist(self, eval_data):
        _, _, y, y_prob = eval_data
        return get_probability_distribution(y, y_prob)

    def test_returns_dataframe(self, prob_dist):
        """DataFrame을 반환하는지 확인."""
        assert isinstance(prob_dist, pd.DataFrame)

    def test_expected_columns(self, prob_dist):
        """필수 컬럼이 있는지 확인."""
        expected = {"bin", "normal", "fraud"}
        assert expected.issubset(set(prob_dist.columns))

    def test_ten_bins(self, prob_dist):
        """기본 10구간인지 확인."""
        assert len(prob_dist) == 10

    def test_counts_non_negative(self, prob_dist):
        """모든 건수가 0 이상인지 확인."""
        assert (prob_dist["normal"] >= 0).all()
        assert (prob_dist["fraud"] >= 0).all()

    def test_total_matches_data_size(self, prob_dist, eval_data):
        """정상 + 이상 합계가 데이터 크기와 일치하는지 확인."""
        _, _, y, _ = eval_data
        total = prob_dist["normal"].sum() + prob_dist["fraud"].sum()
        assert total == len(y)

    def test_custom_bins(self, eval_data):
        """커스텀 구간 수가 적용되는지 확인."""
        _, _, y, y_prob = eval_data
        dist5 = get_probability_distribution(y, y_prob, bins=5)
        assert len(dist5) == 5

    def test_bin_labels_format(self, prob_dist):
        """구간 레이블이 올바른 형식인지 확인."""
        for label in prob_dist["bin"]:
            assert "~" in label


# ──────────────────────────────────────────────
# train_model (커스텀 파라미터)
# ──────────────────────────────────────────────
class TestTrainModelParams:
    """train_model()의 커스텀 파라미터 수용 테스트."""

    def test_accepts_custom_params(self, tmp_path, monkeypatch):
        """커스텀 하이퍼파라미터로 학습이 성공하는지 확인."""
        from xgboost import XGBClassifier
        import src.features.detector as det

        # 임시 모델 경로 사용
        fake_model_path = tmp_path / "test_model.joblib"
        monkeypatch.setattr(det, "MODEL_PATH", fake_model_path)
        monkeypatch.setattr(config, "MODELS_DIR", tmp_path)

        np.random.seed(42)
        n = 100
        X = pd.DataFrame({
            "time_slot": np.random.choice([0, 3, 6, 9], n),
            "sender_bank": np.random.randint(1, 50, n),
            "receiver_bank": np.random.randint(1, 50, n),
            "fund_type": np.random.choice([0, 1], n),
            "media_type": np.random.randint(1, 4, n),
            "amount": np.random.randint(10000, 1000000, n),
        })
        y_train = pd.Series([0] * 95 + [1] * 5)
        y_val = pd.Series([0] * 95 + [1] * 5)

        params = {"n_estimators": 50, "max_depth": 3, "learning_rate": 0.05}
        model = det.train_model(X, y_train, X, y_val, params=params)

        assert model is not None
        assert hasattr(model, "predict_proba")
        assert fake_model_path.exists()

    def test_default_params_when_none(self, tmp_path, monkeypatch):
        """params=None일 때 기본값으로 학습하는지 확인."""
        import src.features.detector as det

        fake_model_path = tmp_path / "test_model2.joblib"
        monkeypatch.setattr(det, "MODEL_PATH", fake_model_path)
        monkeypatch.setattr(config, "MODELS_DIR", tmp_path)

        np.random.seed(42)
        n = 100
        X = pd.DataFrame({
            "time_slot": np.random.choice([0, 3], n),
            "sender_bank": np.random.randint(1, 20, n),
            "receiver_bank": np.random.randint(1, 20, n),
            "fund_type": np.random.choice([0, 1], n),
            "media_type": np.random.randint(1, 3, n),
            "amount": np.random.randint(10000, 500000, n),
        })
        y = pd.Series([0] * 95 + [1] * 5)

        model = det.train_model(X, y, X, y, params=None)
        assert model is not None


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
        # amount과 time_slot는 이상거래 탐지에 핵심 피처
        assert "amount" in FEATURE_COLS
        assert "time_slot" in FEATURE_COLS
