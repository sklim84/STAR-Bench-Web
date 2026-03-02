"""기능3: XGBoost 기반 이상거래 탐지 모듈.

Training/Test/Validation 분할을 활용하여 학습하고,
이상거래 확률을 예측한다.
"""

import joblib
import streamlit as st
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    roc_curve,
)

import config
from src.data.db import query


FEATURE_COLS = ["거래시간대", "출금금융회사일련번호", "입금금융회사일련번호", "자금구분", "매체구분", "거래금액"]
TARGET_COL = "이상거래여부"
MODEL_PATH = config.MODELS_DIR / "xgb_detector.joblib"

# 이상거래유형 설명 매핑
FRAUD_TYPE_LABELS = {
    1: "계좌수집형 거래패턴의 변화",
    2: "신규 거래처 거래",
    3: "분산 거래",
    4: "다중거래처 자금 회수",
    5: "대량 입금 후 자금 이탈",
    7: "심야/새벽 대량 거래",
}


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


@st.cache_data(ttl=300, show_spinner=False)
def get_training_data():
    """학습/테스트/검증 데이터를 반환한다."""
    train = _load_split("Training")
    test = _load_split("Test")
    val = _load_split("Validation")

    X_train, y_train = train[FEATURE_COLS], train[TARGET_COL]
    X_test, y_test = test[FEATURE_COLS], test[TARGET_COL]
    X_val, y_val = val[FEATURE_COLS], val[TARGET_COL]

    return X_train, y_train, X_test, y_test, X_val, y_val


def train_model(X_train, y_train, X_val, y_val, params=None):
    """XGBoost 모델을 학습하고 저장한다.

    Args:
        X_train: 학습 피처
        y_train: 학습 레이블
        X_val: 검증 피처
        y_val: 검증 레이블
        params: 하이퍼파라미터 딕셔너리 (선택). 키: n_estimators, max_depth, learning_rate.
                지정하지 않으면 기본값 사용.

    Returns:
        학습된 XGBClassifier 모델
    """
    pos_count = int(y_train.sum())
    neg_count = len(y_train) - pos_count
    scale_pos = neg_count / max(pos_count, 1)

    # 기본 하이퍼파라미터
    hp = {
        "n_estimators": 300,
        "max_depth": 6,
        "learning_rate": 0.1,
    }
    if params:
        hp.update(params)

    model = XGBClassifier(
        n_estimators=hp["n_estimators"],
        max_depth=hp["max_depth"],
        learning_rate=hp["learning_rate"],
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
    load_model.clear()  # 새 모델 저장 시 캐시 무효화
    return model


@st.cache_resource
def load_model():
    """저장된 모델을 로드한다. 없으면 None. 앱 생명주기 동안 1회만 디스크에서 로드."""
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


def find_optimal_threshold(y_test, y_prob):
    """Precision-Recall 커브에서 F1-Score를 최대화하는 최적 임계값을 탐색한다.

    다양한 임계값(0.1~0.9, 0.05 단위)에서 precision, recall, f1을 계산하고
    F1이 최대인 임계값을 반환한다.

    Args:
        y_test: 실제 레이블 (array-like)
        y_prob: 예측 확률 (array-like, 양성 클래스)

    Returns:
        dict with keys:
            - optimal_threshold: F1 최대화 임계값
            - precision: 해당 임계값의 정밀도
            - recall: 해당 임계값의 재현율
            - f1: 해당 임계값의 F1-Score
            - thresholds_df: 모든 임계값별 성능 DataFrame
            - pr_curve: (precision_array, recall_array, thresholds_array) from sklearn
    """
    y_test_arr = np.asarray(y_test)
    y_prob_arr = np.asarray(y_prob)

    # sklearn PR 커브 (시각화용)
    pr_precision, pr_recall, pr_thresholds = precision_recall_curve(y_test_arr, y_prob_arr)

    # 수동 임계값 탐색 (0.05 ~ 0.95, 0.05 단위)
    thresholds = np.arange(0.05, 1.0, 0.05)
    records = []
    for t in thresholds:
        y_pred_t = (y_prob_arr >= t).astype(int)
        tp = int(((y_pred_t == 1) & (y_test_arr == 1)).sum())
        fp = int(((y_pred_t == 1) & (y_test_arr == 0)).sum())
        fn = int(((y_pred_t == 0) & (y_test_arr == 1)).sum())

        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-8)

        records.append({
            "임계값": round(float(t), 2),
            "Precision": round(prec, 4),
            "Recall": round(rec, 4),
            "F1-Score": round(f1, 4),
            "TP": tp,
            "FP": fp,
            "FN": fn,
        })

    thresholds_df = pd.DataFrame(records)

    # F1 최대화 임계값 찾기
    if thresholds_df.empty:
        return {
            "optimal_threshold": 0.5,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "thresholds_df": thresholds_df,
            "pr_curve": (pr_precision, pr_recall, pr_thresholds),
        }

    best_idx = thresholds_df["F1-Score"].idxmax()
    best_row = thresholds_df.loc[best_idx]

    return {
        "optimal_threshold": float(best_row["임계값"]),
        "precision": float(best_row["Precision"]),
        "recall": float(best_row["Recall"]),
        "f1": float(best_row["F1-Score"]),
        "thresholds_df": thresholds_df,
        "pr_curve": (pr_precision, pr_recall, pr_thresholds),
    }


def get_roc_curve_data(y_test, y_prob):
    """ROC 커브 데이터를 반환한다.

    Args:
        y_test: 실제 레이블
        y_prob: 예측 확률

    Returns:
        dict with keys: fpr, tpr, thresholds, auc
    """
    fpr, tpr, thresholds = roc_curve(np.asarray(y_test), np.asarray(y_prob))
    auc_val = roc_auc_score(np.asarray(y_test), np.asarray(y_prob))
    return {
        "fpr": fpr,
        "tpr": tpr,
        "thresholds": thresholds,
        "auc": auc_val,
    }


def evaluate_by_fraud_type(model, limit=5000):
    """이상거래 유형별 모델 탐지 성능(Recall)을 평가한다.

    DB에서 이상거래 포함 샘플을 추출하고, 유형별로 recall을 계산한다.

    Args:
        model: 학습된 XGBClassifier
        limit: 이상거래 샘플 추출 수 (기본 5000)

    Returns:
        DataFrame with columns: 이상거래유형, 유형설명, 전체건수, 탐지건수, Recall
        빈 데이터가 없도록 방어 처리.
    """
    limit = int(limit)

    # 이상거래 샘플 추출 (유형별 정보 포함)
    df_fraud = query(f"""
        SELECT 거래시간대, 출금금융회사일련번호, 입금금융회사일련번호,
               자금구분, 매체구분, 거래금액, 이상거래여부, 이상거래유형
        FROM hofinet
        WHERE 이상거래여부 = 1
        ORDER BY random()
        LIMIT {limit}
    """)

    if df_fraud.empty:
        return pd.DataFrame(columns=["이상거래유형", "유형설명", "전체건수", "탐지건수", "Recall"])

    X = df_fraud[FEATURE_COLS]
    y_pred = model.predict(X)

    df_fraud = df_fraud.copy()
    df_fraud["예측결과"] = y_pred

    # 유형별 recall 계산
    records = []
    for fraud_type in sorted(df_fraud["이상거래유형"].dropna().unique()):
        fraud_type_int = int(fraud_type)
        subset = df_fraud[df_fraud["이상거래유형"] == fraud_type]
        total = len(subset)
        detected = int(subset["예측결과"].sum())
        recall = detected / max(total, 1)

        records.append({
            "이상거래유형": fraud_type_int,
            "유형설명": FRAUD_TYPE_LABELS.get(fraud_type_int, f"유형 {fraud_type_int}"),
            "전체건수": total,
            "탐지건수": detected,
            "Recall": round(recall, 4),
        })

    return pd.DataFrame(records)


def get_probability_distribution(y_test, y_prob, bins=10):
    """예측 확률 구간별 정상/이상 건수 분포를 반환한다.

    Args:
        y_test: 실제 레이블
        y_prob: 예측 확률
        bins: 구간 수 (기본 10)

    Returns:
        DataFrame with columns: 구간, 정상, 이상
    """
    y_test_arr = np.asarray(y_test)
    y_prob_arr = np.asarray(y_prob)

    bin_edges = np.linspace(0, 1, bins + 1)
    records = []

    for i in range(len(bin_edges) - 1):
        low = bin_edges[i]
        high = bin_edges[i + 1]
        label = f"{low:.1f}~{high:.1f}"

        if i < len(bin_edges) - 2:
            mask = (y_prob_arr >= low) & (y_prob_arr < high)
        else:
            mask = (y_prob_arr >= low) & (y_prob_arr <= high)

        normal_count = int((mask & (y_test_arr == 0)).sum())
        fraud_count = int((mask & (y_test_arr == 1)).sum())

        records.append({
            "구간": label,
            "정상": normal_count,
            "이상": fraud_count,
        })

    return pd.DataFrame(records)


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
