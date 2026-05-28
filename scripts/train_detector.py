"""XGBoost 이상거래 탐지 모델 학습 스크립트.

`_datasets/original/{Training,Test,Validation}` 분할 CSV가 부재할 때 사용하는
대안: hofinet 테이블에서 stratified train/val/test split을 직접 만들어
`src.features.detector.train_model()`을 호출하여 `_models/xgb_detector.joblib`을
생성한다.

Usage:
    python -m scripts.train_detector                 # 70/15/15 split (default)
    python -m scripts.train_detector --val 0.1 --test 0.1
    python -m scripts.train_detector --sample 1000000  # subsampling for speed
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

import config
from src.data.db import query
from src.features.detector import (
    FEATURE_COLS,
    TARGET_COL,
    MODEL_PATH,
    train_model,
    evaluate_model,
)


def _fetch_hofinet(sample: int | None = None) -> pd.DataFrame:
    """hofinet 테이블에서 모델 학습용 컬럼만 가져온다."""
    cols = FEATURE_COLS + [TARGET_COL]
    sql = f"SELECT {', '.join(cols)} FROM hofinet"
    if sample is not None and sample > 0:
        # Stratified-ish 샘플링은 SQL만으로 어려우므로 균등 random + 추후 split에서 stratify.
        sql += f" USING SAMPLE {int(sample)} ROWS"
    return query(sql)


def _stratified_split(
    df: pd.DataFrame,
    val_ratio: float,
    test_ratio: float,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """이상거래 비율을 유지하는 stratified train/val/test split."""
    y = df[TARGET_COL]

    # 1차: train vs (val+test)
    train_df, holdout_df = train_test_split(
        df,
        test_size=val_ratio + test_ratio,
        stratify=y,
        random_state=seed,
    )
    # 2차: val vs test
    holdout_y = holdout_df[TARGET_COL]
    val_share = val_ratio / (val_ratio + test_ratio)
    val_df, test_df = train_test_split(
        holdout_df,
        test_size=1.0 - val_share,
        stratify=holdout_y,
        random_state=seed,
    )
    return train_df, val_df, test_df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--val", type=float, default=0.15, help="Validation 비율 (기본 0.15)")
    parser.add_argument("--test", type=float, default=0.15, help="Test 비율 (기본 0.15)")
    parser.add_argument("--sample", type=int, default=0, help="hofinet에서 샘플링할 행 수 (0=전체)")
    parser.add_argument("--seed", type=int, default=42, help="random seed")
    parser.add_argument(
        "--n-estimators", type=int, default=300, help="XGBoost n_estimators (기본 300)"
    )
    parser.add_argument(
        "--max-depth", type=int, default=6, help="XGBoost max_depth (기본 6)"
    )
    parser.add_argument(
        "--learning-rate", type=float, default=0.1, help="XGBoost learning_rate (기본 0.1)"
    )
    args = parser.parse_args()

    if args.val + args.test >= 1.0:
        raise SystemExit(f"val({args.val}) + test({args.test}) must be < 1.0")

    print(f"[1/4] Loading hofinet (sample={args.sample or 'ALL'})...")
    t0 = time.time()
    df = _fetch_hofinet(sample=args.sample or None)
    print(
        f"    rows={len(df):,}, fraud={int(df[TARGET_COL].sum()):,} "
        f"({df[TARGET_COL].mean() * 100:.4f}%), "
        f"loaded in {time.time() - t0:.1f}s"
    )

    print(f"[2/4] Stratified split — val={args.val}, test={args.test}, seed={args.seed}")
    train_df, val_df, test_df = _stratified_split(df, args.val, args.test, args.seed)
    for name, part in [("train", train_df), ("val", val_df), ("test", test_df)]:
        fraud = int(part[TARGET_COL].sum())
        print(
            f"    {name:5s}: rows={len(part):,}, fraud={fraud:,} "
            f"({part[TARGET_COL].mean() * 100:.4f}%)"
        )

    X_train, y_train = train_df[FEATURE_COLS], train_df[TARGET_COL]
    X_val, y_val = val_df[FEATURE_COLS], val_df[TARGET_COL]
    X_test, y_test = test_df[FEATURE_COLS], test_df[TARGET_COL]

    print(
        f"[3/4] Training XGBoost (n_estimators={args.n_estimators}, "
        f"max_depth={args.max_depth}, lr={args.learning_rate})..."
    )
    t0 = time.time()
    model = train_model(
        X_train, y_train, X_val, y_val,
        params={
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "learning_rate": args.learning_rate,
        },
    )
    print(f"    trained in {time.time() - t0:.1f}s -> saved to {MODEL_PATH}")

    print("[4/4] Evaluating on test set...")
    metrics = evaluate_model(model, X_test, y_test)
    rep = metrics["report"]
    cm = metrics["confusion_matrix"]
    print(f"    ROC-AUC : {metrics['roc_auc']:.4f}")
    print(f"    PR-AUC  : {metrics['pr_auc']:.4f}")
    print(f"    accuracy: {rep['accuracy']:.4f}")
    if "1" in rep:
        print(
            f"    fraud   : precision={rep['1']['precision']:.4f} "
            f"recall={rep['1']['recall']:.4f} f1={rep['1']['f1-score']:.4f} "
            f"support={int(rep['1']['support'])}"
        )
    print(f"    confusion_matrix (rows=true, cols=pred):\n{cm}")

    print(f"\n✅ Model saved: {MODEL_PATH} ({MODEL_PATH.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
