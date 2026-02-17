"""기능3: XGBoost 기반 이상거래 탐지 모듈.

Training/Test/Validation 분할을 활용하여 학습하고,
이상거래 확률을 예측한다.
"""

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    average_precision_score,
    confusion_matrix,
)

import config
from src.data.db import query


FEATURE_COLS = ["거래시간대", "출금금융회사일련번호", "입금금융회사일련번호", "자금구분", "매체구분", "거래금액"]
TARGET_COL = "이상거래여부"
MODEL_PATH = config.MODELS_DIR / "xgb_detector.joblib"


def _load_split(split_name):
    """원본 Training/Test/Validation 분할 데이터를 로드한다."""
    import pyarrow.csv as pcsv
    from src.data.loader import CONVERT_OPTIONS

    split_dir = config.DATASETS_DIR / "original" / split_name
    dfs = []
    for csv_file in sorted(split_dir.glob("*.csv")):
        table = pcsv.read_csv(str(csv_file), convert_options=CONVERT_OPTIONS)
        dfs.append(table.to_pandas())
    return pd.concat(dfs, ignore_index=True)


def get_training_data():
    """학습/테스트/검증 데이터를 반환한다."""
    train = _load_split("Training")
    test = _load_split("Test")
    val = _load_split("Validation")

    X_train, y_train = train[FEATURE_COLS], train[TARGET_COL]
    X_test, y_test = test[FEATURE_COLS], test[TARGET_COL]
    X_val, y_val = val[FEATURE_COLS], val[TARGET_COL]

    return X_train, y_train, X_test, y_test, X_val, y_val


def train_model(X_train, y_train, X_val, y_val):
    """XGBoost 모델을 학습하고 저장한다."""
    pos_count = int(y_train.sum())
    neg_count = len(y_train) - pos_count
    scale_pos = neg_count / max(pos_count, 1)

    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.1,
        scale_pos_weight=scale_pos,
        eval_metric="aucpr",
        early_stopping_rounds=20,
        random_state=42,
        n_jobs=-1,
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    config.MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    return model


def load_model():
    """저장된 모델을 로드한다. 없으면 None."""
    if MODEL_PATH.exists():
        return joblib.load(MODEL_PATH)
    return None


def evaluate_model(model, X_test, y_test):
    """모델 성능을 평가하고 결과를 반환한다."""
    y_prob = model.predict_proba(X_test)[:, 1]
    y_pred = model.predict(X_test)

    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_test, y_pred)
    roc_auc = roc_auc_score(y_test, y_prob)
    pr_auc = average_precision_score(y_test, y_prob)

    return {
        "report": report,
        "confusion_matrix": cm,
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "y_prob": y_prob,
        "y_pred": y_pred,
        "y_test": y_test,
    }


def get_feature_importance(model):
    """피처 중요도를 DataFrame으로 반환한다."""
    importance = model.feature_importances_
    return pd.DataFrame({
        "피처": FEATURE_COLS,
        "중요도": importance,
    }).sort_values("중요도", ascending=False)


def predict_from_db(model, limit=1000):
    """hofinet 테이블에서 샘플을 추출하여 예측 결과를 반환한다."""
    # limit은 int 형변환으로 안전하게 처리 (DuckDB는 LIMIT 파라미터 바인딩 미지원)
    limit = int(limit)
    df = query(f"""
        SELECT 거래일자, 거래시간대, 출금금융회사일련번호, 출금계좌일련번호,
               입금금융회사일련번호, 입금계좌일련번호, 자금구분, 매체구분,
               거래금액, 이상거래여부, 이상거래유형, 이상거래설명
        FROM hofinet
        ORDER BY random()
        LIMIT {limit}
    """)
    X = df[FEATURE_COLS]
    df["예측확률"] = model.predict_proba(X)[:, 1]
    df["예측결과"] = model.predict(X)
    return df.sort_values("예측확률", ascending=False)
