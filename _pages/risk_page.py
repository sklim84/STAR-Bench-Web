"""기능6: 계좌 위험도 평가 페이지."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from src.features.risk_scorer import score_account, rank_risky_accounts
from src.ui.chart_utils import (
    BAR_COLOR, ACCENT_COLOR, MINT_COLOR,
    apply_dark as _apply_dark,
)


def _metric_card(label, value, sub="", white=False):
    value_class = "value white" if white else "value"
    st.markdown(f"""<div class="metric-card">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
        <div class="sub">{sub}</div>
    </div>""", unsafe_allow_html=True)


def render():
    st.markdown('<p class="page-title">계좌 위험도 평가</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">5개 행위 지표 기반 계좌 위험도 산출 (0~100점)</p>',
        unsafe_allow_html=True,
    )

    tab1, tab2 = st.tabs(["개별 계좌 위험도", "고위험 계좌 랭킹"])

    # ------------------------------------------------------------------
    # 탭1: 개별 계좌 위험도
    # ------------------------------------------------------------------
    with tab1:
        st.markdown('<p class="section-header">개별 계좌 위험도 평가</p>', unsafe_allow_html=True)
        account_id = st.number_input(
            "계좌 번호 (출금계좌일련번호)", value=0, key="risk_account"
        )

        if account_id > 0 and st.button("위험도 평가", key="risk_evaluate"):
            with st.spinner("평가 중..."):
                result = score_account(account_id)

            if "error" in result:
                st.warning(result["error"])
            else:
                # 종합 점수 표시
                score = result["종합점수"]
                level = result["위험등급"]
                color = (
                    "#E15759" if level == "높음" else
                    "#F28E2B" if level == "중간" else
                    "#4ECDC4"
                )

                c1, c2, c3 = st.columns(3)
                with c1:
                    _metric_card("종합 위험 점수", f"{score}", f"/ 100점")
                with c2:
                    st.markdown(f"""<div class="metric-card">
                        <div class="label">위험 등급</div>
                        <div class="value" style="color:{color}">{level}</div>
                        <div class="sub">높음(≥70) / 중간(≥40) / 낮음</div>
                    </div>""", unsafe_allow_html=True)
                with c3:
                    _metric_card("계좌 번호", f"{result['account_id']}")

                # 컴포넌트별 레이더 차트
                st.markdown('<p class="section-header">위험 요소 분석</p>', unsafe_allow_html=True)
                components = result["컴포넌트"]
                weights = result["가중치"]

                categories = list(components.keys())
                values = [components[k] for k in categories]

                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(
                    r=values + [values[0]],
                    theta=categories + [categories[0]],
                    fill="toself",
                    fillcolor="rgba(78, 205, 196, 0.2)",
                    line=dict(color=MINT_COLOR, width=2),
                    name="위험 점수",
                ))
                fig.update_layout(
                    polar=dict(
                        bgcolor="rgba(0,0,0,0)",
                        radialaxis=dict(
                            visible=True, range=[0, 1],
                            gridcolor="#1E2333",
                            tickfont=dict(color="#8B8FA3"),
                        ),
                        angularaxis=dict(
                            tickfont=dict(color="#C0C4D0", size=12),
                            gridcolor="#1E2333",
                        ),
                    ),
                )
                _apply_dark(fig, height=400)
                st.plotly_chart(fig, use_container_width=True)

                # 가중치별 기여도 바 차트
                contrib_data = {
                    "지표": categories,
                    "점수": values,
                    "가중치": [weights[k] for k in categories],
                    "기여도": [round(v * weights[k] * 100, 1)
                              for k, v in zip(categories, values)],
                }
                contrib_df = pd.DataFrame(contrib_data)

                fig2 = px.bar(
                    contrib_df, x="지표", y="기여도",
                    color_discrete_sequence=[BAR_COLOR],
                    text="기여도",
                )
                fig2.update_layout(title="위험 요소별 기여도 (가중 점수)")
                _apply_dark(fig2)
                st.plotly_chart(fig2, use_container_width=True)

    # ------------------------------------------------------------------
    # 탭2: 고위험 계좌 랭킹
    # ------------------------------------------------------------------
    with tab2:
        st.markdown('<p class="section-header">고위험 계좌 TOP-K</p>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            top_k = st.slider("상위 K개", 5, 100, 20, key="risk_top_k")
        with col2:
            min_tx = st.number_input(
                "최소 거래 건수", value=10, min_value=1, key="risk_min_tx"
            )

        if st.button("랭킹 조회", key="risk_rank"):
            with st.spinner("조회 중..."):
                df = rank_risky_accounts(top_k=top_k, min_transactions=min_tx)

            if df.empty:
                st.info("조건에 맞는 계좌가 없습니다.")
            else:
                st.markdown(
                    f'<p class="section-header">결과: {len(df):,}개 계좌</p>',
                    unsafe_allow_html=True,
                )

                fig = px.bar(
                    df.head(20), x="account_id", y="위험점수_간이",
                    color="이상거래비율",
                    color_continuous_scale=[[0, "#1A1F2E"], [0.5, "#2A6B65"], [1, "#4ECDC4"]],
                    text="위험점수_간이",
                )
                fig.update_layout(title="고위험 계좌 랭킹")
                fig.update_xaxes(type="category")
                _apply_dark(fig, height=420)
                st.plotly_chart(fig, use_container_width=True)

                st.dataframe(df, use_container_width=True, height=400)
