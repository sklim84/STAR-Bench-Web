"""Feature 3: XGBoost-based Fraud Detection Module.

Trains using Training/Test/Validation splits and predicts fraud probabilities.
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
from src.features.aml_reference import FRAUD_TYPE_MAP


FEATURE_COLS = ["time_slot", "sender_bank", "receiver_bank", "fund_type", "media_type", "amount"]
TARGET_COL = "is_fraud"
MODEL_PATH = config.MODELS_DIR / "xgb_detector.joblib"

# HOFINET fraud_type code → English label (single source of truth: HOFINET.MD §4.1).
# Kept as an alias for backward compatibility with existing imports.
FRAUD_TYPE_LABELS = FRAUD_TYPE_MAP


def _load_split(split_name: str) -> pd.DataFrame:
    """Loads original Training/Test/Validation split data."""
    import pyarrow.csv as pcsv
    from src.data.loader import CONVERT_OPTIONS

    split_dir = config.DATASETS_DIR / "original" / split_name
    dfs = []
    for csv_file in sorted(split_dir.glob("*.csv")):
        table = pcsv.read_csv(str(csv_file), convert_options=CONVERT_OPTIONS)
        # Rename original Korean columns to English schema (based on actual CSV order)
        table = table.rename_columns([
            "sender_acc", "receiver_acc", "sender_bank", "receiver_bank",
            "fund_type", "amount", "time_slot", "media_type", "date",
            "fraud_type", "is_fraud", "fraud_description"
        ])
        dfs.append(table.to_pandas())
    return pd.concat(dfs, ignore_index=True)


@st.cache_data(ttl=300, show_spinner=False)
def get_training_data() -> tuple:
    """Returns training/test/validation data."""
    train = _load_split("Training")
    test = _load_split("Test")
    val = _load_split("Validation")

    X_train, y_train = train[FEATURE_COLS], train[TARGET_COL]
    X_test, y_test = test[FEATURE_COLS], test[TARGET_COL]
    X_val, y_val = val[FEATURE_COLS], val[TARGET_COL]

    return X_train, y_train, X_test, y_test, X_val, y_val


def train_model(X_train: pd.DataFrame, y_train: pd.Series, X_val: pd.DataFrame, y_val: pd.Series, params: dict | None = None):
    """Trains and saves XGBoost model."""
    pos_count = int(y_train.sum())
    neg_count = len(y_train) - pos_count
    scale_pos = neg_count / max(pos_count, 1)

    # Default hyperparameters
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
    load_model.clear()  # Invalidate cache on save
    return model


@st.cache_resource
def load_model() -> object | None:
    """Loads saved model."""
    if MODEL_PATH.exists():
        return joblib.load(MODEL_PATH)
    return None


def evaluate_model(model: object, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    """Evaluates model performance."""
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


def get_feature_importance(model: object) -> pd.DataFrame:
    """Returns feature importance as DataFrame."""
    importance = model.feature_importances_
    return pd.DataFrame({
        "feature": FEATURE_COLS,
        "importance": importance,
    }).sort_values("importance", ascending=False)


def find_optimal_threshold(y_test: pd.Series, y_prob) -> dict:
    """Searches for optimal threshold maximizing F1-Score."""
    y_test_arr = np.asarray(y_test)
    y_prob_arr = np.asarray(y_prob)

    # sklearn PR curve (for visualization)
    pr_precision, pr_recall, pr_thresholds = precision_recall_curve(y_test_arr, y_prob_arr)

    # Manual threshold search (0.05 ~ 0.95, step 0.05)
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
            "threshold": round(float(t), 2),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        })

    thresholds_df = pd.DataFrame(records)

    # Find threshold maximizing F1
    if thresholds_df.empty:
        return {
            "optimal_threshold": 0.5,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "thresholds_df": thresholds_df,
            "pr_curve": (pr_precision, pr_recall, pr_thresholds),
        }

    best_idx = thresholds_df["f1"].idxmax()
    best_row = thresholds_df.loc[best_idx]

    return {
        "optimal_threshold": float(best_row["threshold"]),
        "precision": float(best_row["precision"]),
        "recall": float(best_row["recall"]),
        "f1": float(best_row["f1"]),
        "thresholds_df": thresholds_df,
        "pr_curve": (pr_precision, pr_recall, pr_thresholds),
    }


def get_roc_curve_data(y_test: pd.Series, y_prob) -> dict:
    """Returns ROC curve data."""
    fpr, tpr, thresholds = roc_curve(np.asarray(y_test), np.asarray(y_prob))
    auc_val = roc_auc_score(np.asarray(y_test), np.asarray(y_prob))
    return {
        "fpr": fpr,
        "tpr": tpr,
        "thresholds": thresholds,
        "auc": auc_val,
    }


def evaluate_by_fraud_type(model: object, limit: int = 5000) -> pd.DataFrame:
    """Evaluates model recall by fraud type."""
    limit = int(limit)

    # Extract fraud samples (with type info)
    df_fraud = query(f"""
        SELECT time_slot, sender_bank, receiver_bank,
               fund_type, media_type, amount, is_fraud, fraud_type
        FROM hofinet
        WHERE is_fraud = 1
        ORDER BY random()
        LIMIT {limit}
    """)

    if df_fraud.empty:
        return pd.DataFrame(columns=["fraud_type", "type_desc", "total_count", "detected_count", "recall"])

    X = df_fraud[FEATURE_COLS]
    y_pred = model.predict(X)

    df_fraud = df_fraud.copy()
    df_fraud["prediction"] = y_pred

    # Calculate recall by type
    records = []
    for fraud_type in sorted(df_fraud["fraud_type"].dropna().unique()):
        fraud_type_int = int(fraud_type)
        subset = df_fraud[df_fraud["fraud_type" ] == fraud_type]
        total = len(subset)
        detected = int(subset["prediction"].sum())
        recall = detected / max(total, 1)

        records.append({
            "fraud_type": fraud_type_int,
            "type_desc": FRAUD_TYPE_LABELS.get(fraud_type_int, f"Type {fraud_type_int}"),
            "total_count": total,
            "detected_count": detected,
            "recall": round(recall, 4),
        })

    return pd.DataFrame(records)


def get_probability_distribution(y_test: pd.Series, y_prob, bins: int = 10) -> pd.DataFrame:
    """Returns distribution of normal/fraud cases by prediction probability bins."""
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
            "bin": label,
            "normal": normal_count,
            "fraud": fraud_count,
        })

    return pd.DataFrame(records)


def predict_from_db(model: object, limit: int = 1000) -> pd.DataFrame:
    """Extracts samples from hofinet table and returns prediction results."""
    limit = int(limit)
    df = query(f"""
        SELECT date, time_slot, sender_bank, sender_acc,
               receiver_bank, receiver_acc, fund_type, media_type,
               amount, is_fraud, fraud_type, fraud_description
        FROM hofinet
        ORDER BY random()
        LIMIT {limit}
    """)
    X = df[FEATURE_COLS]
    df["prob"] = model.predict_proba(X)[:, 1]
    df["prediction"] = model.predict(X)
    return df.sort_values("prob", ascending=False)
