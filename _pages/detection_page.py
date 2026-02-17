import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd

from src.features.detector import (
    get_training_data,
    train_model,
    load_model,
    evaluate_model,
    get_feature_importance,
    predict_from_db,
)


def render():
    st.title("이상거래 탐지")

    # --- 모델 상태 확인 ---
    model = load_model()

    if model is None:
        st.warning("학습된 모델이 없습니다. 아래 버튼을 눌러 모델을 학습하세요.")

    # --- 탭 구성 ---
    tab1, tab2 = st.tabs(["모델 학습 및 평가", "이상거래 탐지"])

    # --- 탭1: 학습 및 평가 ---
    with tab1:
        if st.button("모델 학습 시작", type="primary"):
            with st.spinner("데이터 로딩 중..."):
                X_train, y_train, X_test, y_test, X_val, y_val = get_training_data()

            st.markdown(f"""
            | 데이터셋 | 건수 | 이상거래 | 비율 |
            |----------|------|---------|------|
            | Training | {len(X_train):,} | {int(y_train.sum()):,} | {y_train.mean()*100:.2f}% |
            | Test | {len(X_test):,} | {int(y_test.sum()):,} | {y_test.mean()*100:.2f}% |
            | Validation | {len(X_val):,} | {int(y_val.sum()):,} | {y_val.mean()*100:.2f}% |
            """)

            with st.spinner("XGBoost 모델 학습 중..."):
                model = train_model(X_train, y_train, X_val, y_val)

            st.success("모델 학습 완료!")

            with st.spinner("테스트 데이터 평가 중..."):
                result = evaluate_model(model, X_test, y_test)

            # 평가 결과 표시
            col1, col2, col3 = st.columns(3)
            col1.metric("ROC-AUC", f"{result['roc_auc']:.4f}")
            col2.metric("PR-AUC (AUPRC)", f"{result['pr_auc']:.4f}")
            report = result["report"]
            col3.metric("F1-Score (이상)", f"{report.get('1', report.get('1.0', {})).get('f1-score', 0):.4f}")

            st.divider()

            # 피처 중요도 + 혼동 행렬
            col_left, col_right = st.columns(2)

            with col_left:
                st.subheader("피처 중요도")
                fi = get_feature_importance(model)
                fig_fi = px.bar(
                    fi, x="중요도", y="피처", orientation="h",
                    color="중요도", color_continuous_scale="Blues",
                )
                fig_fi.update_layout(
                    height=300, margin=dict(t=20, b=20), yaxis=dict(autorange="reversed"),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#C0C4D0"),
                )
                fig_fi.update_xaxes(gridcolor="#1E2333", zerolinecolor="#1E2333", tickfont=dict(color="#8B8FA3"))
                fig_fi.update_yaxes(gridcolor="#1E2333", zerolinecolor="#1E2333", tickfont=dict(color="#8B8FA3"))
                st.plotly_chart(fig_fi, use_container_width=True)

            with col_right:
                st.subheader("혼동 행렬")
                cm = result["confusion_matrix"]
                fig_cm = px.imshow(
                    cm, text_auto=True,
                    labels=dict(x="예측", y="실제", color="건수"),
                    x=["정상", "이상"], y=["정상", "이상"],
                    color_continuous_scale="Blues",
                )
                fig_cm.update_layout(
                    height=300, margin=dict(t=20, b=20),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#C0C4D0"),
                )
                st.plotly_chart(fig_cm, use_container_width=True)

            # 분류 리포트
            with st.expander("상세 분류 리포트"):
                report_df = pd.DataFrame(report).T
                st.dataframe(report_df, use_container_width=True)

            # 확률 분포
            st.subheader("예측 확률 분포")
            y_prob = result["y_prob"]
            y_test_arr = result["y_test"]

            fig_dist = make_subplots(rows=1, cols=1)
            fig_dist.add_trace(go.Histogram(
                x=y_prob[y_test_arr == 0], name="정상", opacity=0.7, marker_color="#4E79A7", nbinsx=50,
            ))
            fig_dist.add_trace(go.Histogram(
                x=y_prob[y_test_arr == 1], name="이상", opacity=0.7, marker_color="#E15759", nbinsx=50,
            ))
            fig_dist.update_layout(
                barmode="overlay", height=350,
                xaxis_title="예측 확률", yaxis_title="빈도",
                legend=dict(orientation="h", y=1.1, font=dict(color="#8B8FA3"), bgcolor="rgba(0,0,0,0)"),
                margin=dict(t=30, b=30),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#C0C4D0"),
            )
            fig_dist.update_xaxes(gridcolor="#1E2333", zerolinecolor="#1E2333", tickfont=dict(color="#8B8FA3"))
            fig_dist.update_yaxes(gridcolor="#1E2333", zerolinecolor="#1E2333", tickfont=dict(color="#8B8FA3"))
            st.plotly_chart(fig_dist, use_container_width=True)

    # --- 탭2: 탐지 실행 ---
    with tab2:
        if model is None:
            st.info("먼저 '모델 학습 및 평가' 탭에서 모델을 학습하세요.")
        else:
            st.markdown("학습된 모델로 거래 데이터를 분석하여 이상거래 확률을 예측합니다.")

            sample_size = st.slider("분석할 거래 수", 100, 5000, 1000, 100)

            if st.button("탐지 실행", type="primary"):
                with st.spinner("예측 중..."):
                    result_df = predict_from_db(model, limit=sample_size)

                detected = result_df[result_df["예측결과"] == 1]
                col1, col2, col3 = st.columns(3)
                col1.metric("분석 거래 수", f"{len(result_df):,}")
                col2.metric("탐지된 이상거래", f"{len(detected):,}")
                col3.metric("탐지율", f"{len(detected)/len(result_df)*100:.2f}%")

                st.subheader("이상거래 의심 거래 (확률 높은 순)")
                display_cols = ["거래일자", "출금계좌일련번호", "입금계좌일련번호", "거래금액",
                               "이상거래여부", "예측확률", "예측결과"]
                st.dataframe(
                    result_df[display_cols].head(50).style.format({"예측확률": "{:.4f}"}),
                    use_container_width=True, hide_index=True,
                )

                # 실제 vs 예측 비교
                with st.expander("실제 레이블 vs 예측 비교"):
                    cross = pd.crosstab(
                        result_df["이상거래여부"].map({0: "실제_정상", 1: "실제_이상"}),
                        result_df["예측결과"].map({0: "예측_정상", 1: "예측_이상"}),
                    )
                    st.dataframe(cross, use_container_width=True)
