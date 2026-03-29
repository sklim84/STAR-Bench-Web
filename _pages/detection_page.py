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
    find_optimal_threshold,
    get_roc_curve_data,
    evaluate_by_fraud_type,
    get_probability_distribution,
    FRAUD_TYPE_LABELS,
)
from src.ui.chart_utils import (
    BAR_COLOR, LINE_COLOR, ACCENT_COLOR, MINT_COLOR,
    apply_dark as _apply_dark,
)


def _metric_card(label, value, sub="", white=False):
    """HTML 메트릭 카드를 렌더링한다."""
    value_class = "value white" if white else "value"
    st.markdown(f"""<div class="metric-card">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
        <div class="sub">{sub}</div>
    </div>""", unsafe_allow_html=True)


def render():
    st.markdown('<p class="page-title">Fraud Detection</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">XGBoost model-based suspicious transaction training, evaluation, and probability prediction</p>', unsafe_allow_html=True)

    # --- 모델 상태 확인 ---
    model = load_model()

    if model is None:
        st.info("No trained model found. Please train a model in the 'Model Training & Evaluation' tab first.")

    # --- 탭 구성 ---
    tab1, tab2 = st.tabs(["Model Training & Evaluation", "Fraud Detection"])

    # ------------------------------------------------------------------
    # 탭1: 학습 및 평가
    # ------------------------------------------------------------------
    with tab1:
        # --- 하이퍼파라미터 튜닝 UI ---
        with st.expander("Hyperparameter Settings", expanded=False):
            hp_col1, hp_col2, hp_col3 = st.columns(3)
            with hp_col1:
                hp_n_estimators = st.number_input(
                    "n_estimators (Number of Trees)",
                    min_value=50, max_value=1000, value=300, step=50,
                    help="Number of boosting rounds. Higher values increase model complexity.",
                    key="hp_n_estimators",
                )
            with hp_col2:
                hp_max_depth = st.number_input(
                    "max_depth (Tree Depth)",
                    min_value=2, max_value=15, value=6, step=1,
                    help="Maximum depth of individual trees. Important for preventing overfitting.",
                    key="hp_max_depth",
                )
            with hp_col3:
                hp_learning_rate = st.select_slider(
                    "learning_rate (Learning Rate)",
                    options=[0.01, 0.03, 0.05, 0.1, 0.15, 0.2, 0.3],
                    value=0.1,
                    help="Contribution of each tree. Lower is more stable but slower.",
                    key="hp_learning_rate",
                )

        if st.button("Start Model Training", type="primary"):
            with st.spinner("Loading data..."):
                X_train, y_train, X_test, y_test, X_val, y_val = get_training_data()

            # 데이터셋 정보 표시
            st.markdown('<p class="section-header">Dataset Split Summary</p>', unsafe_allow_html=True)

            data_html = """<table class="dark-table">
                <thead><tr><th>Dataset</th><th>Count</th><th>Fraud</th><th>Ratio</th></tr></thead>
                <tbody>"""
            for ds_name, ds_x, ds_y in [("Training", X_train, y_train),
                                         ("Test", X_test, y_test),
                                         ("Validation", X_val, y_val)]:
                data_html += f"""<tr>
                    <td>{ds_name}</td>
                    <td>{len(ds_x):,}</td>
                    <td>{int(ds_y.sum()):,}</td>
                    <td>{ds_y.mean()*100:.2f}%</td>
                </tr>"""
            data_html += "</tbody></table>"
            st.markdown(data_html, unsafe_allow_html=True)

            # 하이퍼파라미터 표시
            params = {
                "n_estimators": hp_n_estimators,
                "max_depth": hp_max_depth,
                "learning_rate": hp_learning_rate,
            }

            hp_html = """<table class="dark-table" style="margin-top:12px;">
                <thead><tr><th>Parameter</th><th>Value</th></tr></thead>
                <tbody>"""
            hp_html += f"<tr><td>n_estimators</td><td>{hp_n_estimators}</td></tr>"
            hp_html += f"<tr><td>max_depth</td><td>{hp_max_depth}</td></tr>"
            hp_html += f"<tr><td>learning_rate</td><td>{hp_learning_rate}</td></tr>"
            pos_count = int(y_train.sum())
            neg_count = len(y_train) - pos_count
            scale_pos = neg_count / max(pos_count, 1)
            hp_html += f"<tr><td>scale_pos_weight</td><td>{scale_pos:.1f}</td></tr>"
            hp_html += "</tbody></table>"
            st.markdown(hp_html, unsafe_allow_html=True)

            with st.spinner("Training XGBoost model..."):
                model = train_model(X_train, y_train, X_val, y_val, params=params)

            st.success("Model training complete!")

            with st.spinner("Evaluating on test data..."):
                result = evaluate_model(model, X_test, y_test)

            # 평가 결과를 세션에 저장 (탭 전환 시에도 유지)
            st.session_state["detection_result"] = result
            st.session_state["detection_model"] = model

            _render_evaluation(model, result)

        # 이전 결과가 세션에 있으면 표시
        elif "detection_result" in st.session_state and "detection_model" in st.session_state:
            _render_evaluation(
                st.session_state["detection_model"],
                st.session_state["detection_result"],
            )

    # ------------------------------------------------------------------
    # 탭2: 탐지 실행
    # ------------------------------------------------------------------
    with tab2:
        if model is None:
            st.info("Please train a model in the 'Model Training & Evaluation' tab first.")
        else:
            with st.expander("Detection Settings", expanded=True):
                st.markdown(
                    '<p class="caption-text">Analyze transaction data with the trained model to predict fraud probability.</p>',
                    unsafe_allow_html=True,
                )
                sample_size = st.slider("Number of transactions to analyze", 100, 5000, 1000, 100)

            if st.button("Run Detection", type="primary"):
                with st.spinner("Predicting..."):
                    result_df = predict_from_db(model, limit=sample_size)

                st.session_state["detection_result_df"] = result_df
                _render_detection_results(model, result_df)

            elif "detection_result_df" in st.session_state:
                _render_detection_results(model, st.session_state["detection_result_df"])


# ------------------------------------------------------------------
# 탭1: 평가 결과 렌더링
# ------------------------------------------------------------------
def _render_evaluation(model, result):
    """모델 평가 결과 전체를 렌더링한다."""
    y_prob = result["y_prob"]
    y_test = result["y_test"]
    report = result["report"]

    # --- 주요 성능 지표 (메트릭 카드) ---
    st.markdown('<p class="section-header">Model Performance Metrics</p>', unsafe_allow_html=True)

    f1_class1 = report.get("1", report.get("1.0", {})).get("f1-score", 0)
    prec_class1 = report.get("1", report.get("1.0", {})).get("precision", 0)
    rec_class1 = report.get("1", report.get("1.0", {})).get("recall", 0)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        _metric_card("ROC-AUC", f"{result['roc_auc']:.4f}", "Closer to 1 is better")
    with c2:
        _metric_card("PR-AUC", f"{result['pr_auc']:.4f}", "Key metric for imbalanced data")
    with c3:
        _metric_card("F1-Score", f"{f1_class1:.4f}", "Harmonic mean of Precision & Recall")
    with c4:
        _metric_card("Precision", f"{prec_class1:.4f}", "Ratio of true fraud among detected")
    with c5:
        _metric_card("Recall", f"{rec_class1:.4f}", "Ratio of detected among actual fraud")

    # --- 피처 중요도 + 혼동 행렬 ---
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown('<p class="section-header">Feature Importance</p>', unsafe_allow_html=True)
        fi = get_feature_importance(model)
        fig_fi = px.bar(
            fi, x="중요도", y="피처", orientation="h",
            color_discrete_sequence=[MINT_COLOR],
        )
        _apply_dark(fig_fi, height=340)
        fig_fi.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_fi, width='stretch')

    with col_right:
        st.markdown('<p class="section-header">Confusion Matrix</p>', unsafe_allow_html=True)
        cm = result["confusion_matrix"]
        fig_cm = px.imshow(
            cm, text_auto=True,
            labels=dict(x="Predicted", y="Actual", color="Count"),
            x=["Normal", "Fraud"], y=["Normal", "Fraud"],
            color_continuous_scale=[[0, "#1A1F2E"], [0.5, "#2A6B65"], [1, "#4ECDC4"]],
        )
        _apply_dark(fig_cm, height=340)
        st.plotly_chart(fig_cm, width='stretch')

    # --- ROC 커브 + PR 커브 ---
    col_roc, col_pr = st.columns(2)

    with col_roc:
        st.markdown('<p class="section-header">ROC Curve</p>', unsafe_allow_html=True)
        roc_data = get_roc_curve_data(y_test, y_prob)
        fig_roc = go.Figure()
        fig_roc.add_trace(go.Scatter(
            x=roc_data["fpr"], y=roc_data["tpr"],
            mode="lines",
            name=f"ROC (AUC={roc_data['auc']:.4f})",
            line=dict(color=MINT_COLOR, width=2),
        ))
        fig_roc.add_trace(go.Scatter(
            x=[0, 1], y=[0, 1],
            mode="lines",
            name="Random Baseline",
            line=dict(color="#AAAAAA", width=1, dash="dash"),
        ))
        _apply_dark(fig_roc, height=340)
        fig_roc.update_xaxes(title_text="False Positive Rate",
                             title_font=dict(color="#8B8FA3", size=11))
        fig_roc.update_yaxes(title_text="True Positive Rate",
                             title_font=dict(color="#8B8FA3", size=11))
        st.plotly_chart(fig_roc, width='stretch')

    with col_pr:
        st.markdown('<p class="section-header">Precision-Recall Curve</p>', unsafe_allow_html=True)
        threshold_result = find_optimal_threshold(y_test, y_prob)
        pr_prec, pr_rec, _ = threshold_result["pr_curve"]

        fig_pr = go.Figure()
        fig_pr.add_trace(go.Scatter(
            x=pr_rec, y=pr_prec,
            mode="lines",
            name=f"PR (AUPRC={result['pr_auc']:.4f})",
            line=dict(color=MINT_COLOR, width=2),
        ))
        opt_t = threshold_result["optimal_threshold"]
        opt_p = threshold_result["precision"]
        opt_r = threshold_result["recall"]
        fig_pr.add_trace(go.Scatter(
            x=[opt_r], y=[opt_p],
            mode="markers+text",
            name=f"Optimal (t={opt_t:.2f})",
            marker=dict(color=LINE_COLOR, size=12, symbol="star"),
            text=[f"t={opt_t:.2f}"],
            textposition="top right",
            textfont=dict(color=LINE_COLOR, size=11),
        ))
        _apply_dark(fig_pr, height=340)
        fig_pr.update_xaxes(title_text="Recall",
                            title_font=dict(color="#8B8FA3", size=11))
        fig_pr.update_yaxes(title_text="Precision",
                            title_font=dict(color="#8B8FA3", size=11))
        st.plotly_chart(fig_pr, width='stretch')

    # --- 임계값 최적화 결과 ---
    st.markdown('<p class="section-header">Threshold Optimization</p>', unsafe_allow_html=True)

    opt_c1, opt_c2, opt_c3, opt_c4 = st.columns(4)
    with opt_c1:
        _metric_card("Optimal Threshold", f"{threshold_result['optimal_threshold']:.2f}",
                     "Maximizes F1-Score")
    with opt_c2:
        _metric_card("Precision", f"{threshold_result['precision']:.4f}",
                     f"At threshold {threshold_result['optimal_threshold']:.2f}")
    with opt_c3:
        _metric_card("Recall", f"{threshold_result['recall']:.4f}",
                     f"At threshold {threshold_result['optimal_threshold']:.2f}")
    with opt_c4:
        _metric_card("F1-Score", f"{threshold_result['f1']:.4f}",
                     f"At threshold {threshold_result['optimal_threshold']:.2f}")

    # 임계값별 성능 차트
    th_df = threshold_result["thresholds_df"]
    if not th_df.empty:
        fig_th = go.Figure()
        fig_th.add_trace(go.Scatter(
            x=th_df["임계값"], y=th_df["Precision"],
            mode="lines+markers", name="Precision",
            line=dict(color=BAR_COLOR, width=2),
            marker=dict(size=5),
        ))
        fig_th.add_trace(go.Scatter(
            x=th_df["임계값"], y=th_df["Recall"],
            mode="lines+markers", name="Recall",
            line=dict(color=LINE_COLOR, width=2),
            marker=dict(size=5),
        ))
        fig_th.add_trace(go.Scatter(
            x=th_df["임계값"], y=th_df["F1-Score"],
            mode="lines+markers", name="F1-Score",
            line=dict(color=MINT_COLOR, width=2),
            marker=dict(size=5),
        ))
        # 최적 임계값 수직선
        fig_th.add_vline(
            x=threshold_result["optimal_threshold"],
            line_dash="dash", line_color=ACCENT_COLOR,
            annotation_text=f"Optimal t={threshold_result['optimal_threshold']:.2f}",
            annotation_font_color=ACCENT_COLOR,
        )
        _apply_dark(fig_th, height=350)
        fig_th.update_xaxes(title_text="Threshold", title_font=dict(color="#8B8FA3", size=11))
        fig_th.update_yaxes(title_text="Score", title_font=dict(color="#8B8FA3", size=11))
        st.plotly_chart(fig_th, width='stretch')

        # 임계값별 성능 테이블
        with st.expander("Detailed Performance by Threshold"):
            table_html = """<table class="dark-table">
                <thead><tr><th>Threshold</th><th>Precision</th><th>Recall</th>
                <th>F1-Score</th><th>TP</th><th>FP</th><th>FN</th></tr></thead>
                <tbody>"""
            for _, row in th_df.iterrows():
                highlight = ' class="row-highlight"' if row["임계값"] == threshold_result["optimal_threshold"] else ""
                table_html += f"""<tr{highlight}>
                    <td>{row['임계값']:.2f}</td>
                    <td>{row['Precision']:.4f}</td>
                    <td>{row['Recall']:.4f}</td>
                    <td>{row['F1-Score']:.4f}</td>
                    <td>{int(row['TP']):,}</td>
                    <td>{int(row['FP']):,}</td>
                    <td>{int(row['FN']):,}</td>
                </tr>"""
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)

    # --- 예측 확률 분포 (히스토그램) ---
    st.markdown('<p class="section-header">Prediction Probability Distribution</p>', unsafe_allow_html=True)

    y_test_arr = np.asarray(y_test)
    fig_dist = go.Figure()
    fig_dist.add_trace(go.Histogram(
        x=y_prob[y_test_arr == 0], name="Normal", opacity=0.7,
        marker_color=BAR_COLOR, nbinsx=50,
    ))
    fig_dist.add_trace(go.Histogram(
        x=y_prob[y_test_arr == 1], name="Fraud", opacity=0.7,
        marker_color=LINE_COLOR, nbinsx=50,
    ))
    fig_dist.update_layout(barmode="overlay")
    _apply_dark(fig_dist, height=350)
    fig_dist.update_xaxes(title_text="Predicted Probability", title_font=dict(color="#8B8FA3", size=11))
    fig_dist.update_yaxes(title_text="Frequency", title_font=dict(color="#8B8FA3", size=11))
    st.plotly_chart(fig_dist, width='stretch')

    # --- 확률 구간별 정상/이상 분포 (stacked bar) ---
    st.markdown('<p class="section-header">Normal/Fraud Distribution by Probability Range</p>', unsafe_allow_html=True)

    prob_dist = get_probability_distribution(y_test, y_prob)
    if not prob_dist.empty:
        fig_prob = go.Figure()
        fig_prob.add_trace(go.Bar(
            x=prob_dist["구간"], y=prob_dist["정상"],
            name="Normal", marker_color=BAR_COLOR,
        ))
        fig_prob.add_trace(go.Bar(
            x=prob_dist["구간"], y=prob_dist["이상"],
            name="Fraud", marker_color=LINE_COLOR,
        ))
        fig_prob.update_layout(barmode="stack")
        _apply_dark(fig_prob, height=350)
        fig_prob.update_xaxes(title_text="Predicted Probability Range", title_font=dict(color="#8B8FA3", size=11))
        fig_prob.update_yaxes(title_text="Count", title_font=dict(color="#8B8FA3", size=11))
        st.plotly_chart(fig_prob, width='stretch')

    # --- 분류 리포트 ---
    with st.expander("Detailed Classification Report"):
        report = result["report"]
        report_df = pd.DataFrame(report).T
        report_html = """<table class="dark-table">
            <thead><tr><th>Class</th><th>Precision</th><th>Recall</th>
            <th>F1-Score</th><th>Support</th></tr></thead>
            <tbody>"""
        for idx, row in report_df.iterrows():
            report_html += f"""<tr>
                <td>{idx}</td>
                <td>{row.get('precision', '-'):.4f}</td>
                <td>{row.get('recall', '-'):.4f}</td>
                <td>{row.get('f1-score', '-'):.4f}</td>
                <td>{int(row.get('support', 0)):,}</td>
            </tr>"""
        report_html += "</tbody></table>"
        st.markdown(report_html, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 탭2: 탐지 결과 렌더링
# ------------------------------------------------------------------
def _render_detection_results(model, result_df):
    """탐지 실행 결과를 렌더링한다."""
    detected = result_df[result_df["예측결과"] == 1]

    # --- 메트릭 카드 ---
    st.markdown('<p class="section-header">Detection Result Summary</p>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("Analyzed Transactions", f"{len(result_df):,}", "Sample size")
    with c2:
        _metric_card("Detected Fraud", f"{len(detected):,}", "Predicted fraud count")
    with c3:
        rate = len(detected) / max(len(result_df), 1) * 100
        _metric_card("Detection Rate", f"{rate:.2f}%", "Ratio to total")

    # --- 이상거래 의심 거래 테이블 ---
    st.markdown('<p class="section-header">Suspected Fraud Transactions (Highest Probability First)</p>', unsafe_allow_html=True)

    display_cols = ["거래일자", "출금계좌일련번호", "입금계좌일련번호", "거래금액",
                    "이상거래여부", "이상거래유형", "예측확률", "예측결과"]
    display_df = result_df[display_cols].head(50)

    # HTML 테이블로 변환
    table_html = """<table class="dark-table">
        <thead><tr>"""
    for col in display_cols:
        table_html += f"<th>{col}</th>"
    table_html += "</tr></thead><tbody>"

    for _, row in display_df.iterrows():
        # 예측확률에 따라 행 스타일링
        prob = float(row["예측확률"])
        if prob >= 0.8:
            style = ' class="row-risk-high"'
        elif prob >= 0.5:
            style = ' class="row-risk-medium"'
        else:
            style = ""

        table_html += f"<tr{style}>"
        for col in display_cols:
            val = row[col]
            if col == "예측확률":
                table_html += f"<td>{float(val):.4f}</td>"
            elif col == "거래금액":
                table_html += f"<td>{int(val):,}</td>"
            elif col in ("출금계좌일련번호", "입금계좌일련번호"):
                table_html += f"<td>{int(val)}</td>"
            else:
                table_html += f"<td>{val}</td>"
        table_html += "</tr>"

    table_html += "</tbody></table>"
    st.markdown(table_html, unsafe_allow_html=True)

    # --- 실제 vs 예측 비교 ---
    st.markdown('<p class="section-header">Actual vs Predicted Comparison</p>', unsafe_allow_html=True)

    cross = pd.crosstab(
        result_df["이상거래여부"].map({0: "Actual_Normal", 1: "Actual_Fraud"}),
        result_df["예측결과"].map({0: "Pred_Normal", 1: "Pred_Fraud"}),
    )

    # Confusion matrix heatmap
    fig_cross = px.imshow(
        cross.values, text_auto=True,
        labels=dict(x="Predicted", y="Actual", color="Count"),
        x=cross.columns.tolist(), y=cross.index.tolist(),
        color_continuous_scale=[[0, "#1A1F2E"], [0.5, "#2A6B65"], [1, "#4ECDC4"]],
    )
    _apply_dark(fig_cross, height=300)
    st.plotly_chart(fig_cross, width='stretch')

    # --- 이상거래 유형별 탐지 성능 ---
    st.markdown('<p class="section-header">Detection Performance by Fraud Type</p>', unsafe_allow_html=True)

    with st.spinner("Analyzing detection performance by type..."):
        fraud_type_perf = evaluate_by_fraud_type(model, limit=5000)

    if not fraud_type_perf.empty:
        # Metric cards: recall by type
        cols = st.columns(len(fraud_type_perf))
        for i, (_, row) in enumerate(fraud_type_perf.iterrows()):
            with cols[i]:
                _metric_card(
                    f"Type {int(row['이상거래유형'])}",
                    f"{row['Recall']*100:.1f}%",
                    row["유형설명"],
                )

        # Bar chart
        fraud_type_perf["레이블"] = (
            fraud_type_perf["이상거래유형"].astype(str) + ". "
            + fraud_type_perf["유형설명"]
        )
        fig_ft = go.Figure()
        fig_ft.add_trace(go.Bar(
            x=fraud_type_perf["레이블"],
            y=fraud_type_perf["Recall"],
            marker_color=MINT_COLOR,
            text=fraud_type_perf["Recall"].apply(lambda x: f"{x*100:.1f}%"),
            textposition="outside",
            textfont=dict(color="#E0E0E0", size=11),
        ))
        _apply_dark(fig_ft, height=380)
        fig_ft.update_xaxes(title_text="Fraud Type",
                            title_font=dict(color="#8B8FA3", size=11))
        fig_ft.update_yaxes(title_text="Recall (Detection Rate)",
                            title_font=dict(color="#8B8FA3", size=11),
                            range=[0, 1.1])
        st.plotly_chart(fig_ft, width='stretch')

        # Detail table
        with st.expander("Detection Details by Type"):
            ft_table = """<table class="dark-table">
                <thead><tr><th>Type</th><th>Description</th><th>Total</th>
                <th>Detected</th><th>Recall</th></tr></thead>
                <tbody>"""
            for _, row in fraud_type_perf.iterrows():
                ft_table += f"""<tr>
                    <td>{int(row['이상거래유형'])}</td>
                    <td>{row['유형설명']}</td>
                    <td>{int(row['전체건수']):,}</td>
                    <td>{int(row['탐지건수']):,}</td>
                    <td>{row['Recall']*100:.2f}%</td>
                </tr>"""
            ft_table += "</tbody></table>"
            st.markdown(ft_table, unsafe_allow_html=True)
    else:
        st.info("No fraud data available for type-specific analysis.")

    # --- 확률 구간별 분포 (탐지 결과 기반) ---
    st.markdown('<p class="section-header">Normal/Fraud Distribution by Probability Range</p>', unsafe_allow_html=True)

    prob_dist = get_probability_distribution(
        result_df["이상거래여부"], result_df["예측확률"]
    )
    if not prob_dist.empty:
        fig_prob2 = go.Figure()
        fig_prob2.add_trace(go.Bar(
            x=prob_dist["구간"], y=prob_dist["정상"],
            name="Normal", marker_color=BAR_COLOR,
        ))
        fig_prob2.add_trace(go.Bar(
            x=prob_dist["구간"], y=prob_dist["이상"],
            name="Fraud", marker_color=LINE_COLOR,
        ))
        fig_prob2.update_layout(barmode="stack")
        _apply_dark(fig_prob2, height=350)
        fig_prob2.update_xaxes(title_text="Predicted Probability Range",
                               title_font=dict(color="#8B8FA3", size=11))
        fig_prob2.update_yaxes(title_text="Count",
                               title_font=dict(color="#8B8FA3", size=11))
        st.plotly_chart(fig_prob2, width='stretch')
