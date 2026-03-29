"""기능7: 거래 모니터링 규칙 탐지 페이지."""

import streamlit as st
import plotly.express as px
import pandas as pd

from src.features.monitoring import (
    detect_nighttime_bulk,
    detect_rapid_fire,
    detect_round_amounts,
    detect_institution_concentration,
    detect_pattern_change,
    run_all_rules,
    get_monitoring_summary,
)
from src.ui.chart_utils import (
    BAR_COLOR, LINE_COLOR, ACCENT_COLOR, MINT_COLOR,
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
    st.markdown('<p class="page-title">Transaction Monitoring</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">Rule-based suspicious transaction monitoring (R001~R005)</p>',
        unsafe_allow_html=True,
    )

    # --- Summary statistics ---
    with st.spinner("Loading data..."):
        summary = get_monitoring_summary()
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Total Transactions", f"{summary['총거래건수']:,}")
    with c2:
        _metric_card("Nighttime Transactions", f"{summary['심야거래건수']:,}")
    with c3:
        _metric_card("Nighttime Ratio", f"{summary['심야거래비율']:.2f}%")
    with c4:
        _metric_card("High-Frequency Days", f"{summary['고빈도거래일수']:,}", "10+ txns/day")

    # --- Tabs ---
    tabs = st.tabs(["Overview Dashboard", "R001 Nighttime Bulk", "R002 Rapid-Fire", "R003 Round Amounts", "R004 Institution Concentration", "R005 Pattern Change"])

    # ------------------------------------------------------------------
    # 탭0: 종합 대시보드
    # ------------------------------------------------------------------
    with tabs[0]:
        st.markdown('<p class="section-header">All Rules Execution Results</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            all_from = st.number_input("Start Date", value=20240101, key="mon_all_from")
        with col2:
            all_to = st.number_input("End Date", value=20241231, key="mon_all_to")

        if st.button("Run All Rules", type="primary", key="mon_run_all"):
            with st.spinner("Running all rules..."):
                results = run_all_rules(date_from=all_from, date_to=all_to)

            rule_counts = {k: v["건수"] for k, v in results.items()}
            count_df = pd.DataFrame(
                [{"Rule": k, "Detections": v} for k, v in rule_counts.items()]
            )
            fig = px.bar(
                count_df, x="Rule", y="Detections",
                color_discrete_sequence=[BAR_COLOR], text="Detections",
            )
            fig.update_layout(title="Detection Count by Rule")
            _apply_dark(fig)
            st.plotly_chart(fig, width='stretch')

            for rule_name, data in results.items():
                with st.expander(f"{rule_name} ({data['건수']} cases)"):
                    if data["상위"]:
                        st.dataframe(pd.DataFrame(data["상위"]), width='stretch')
                    else:
                        st.info("No detections found.")

    # ------------------------------------------------------------------
    # Tab1: R001 Nighttime Bulk Transactions
    # ------------------------------------------------------------------
    with tabs[1]:
        st.markdown('<p class="section-header">R001: Nighttime Bulk Transactions</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            r1_from = st.number_input("Start Date", value=20240101, key="r1_from")
        with col2:
            r1_to = st.number_input("End Date", value=20241231, key="r1_to")
        with col3:
            r1_min_amt = st.number_input("Minimum Amount", value=10_000_000, step=1_000_000, key="r1_min")

        if st.button("Run Detection", key="r1_run"):
            df = detect_nighttime_bulk(date_from=r1_from, date_to=r1_to, min_amount=r1_min_amt, limit=100)
            if df.empty:
                st.info("No detections found.")
            else:
                st.markdown(f"Detection results: **{len(df):,} cases**")
                fig = px.histogram(df, x="거래금액", nbins=30, color_discrete_sequence=[LINE_COLOR])
                fig.update_layout(title="Nighttime Bulk Transaction Amount Distribution")
                _apply_dark(fig)
                st.plotly_chart(fig, width='stretch')
                st.dataframe(df, width='stretch', height=400)

    # ------------------------------------------------------------------
    # 탭2: R002 동일일 다건거래
    # ------------------------------------------------------------------
    with tabs[2]:
        st.markdown('<p class="section-header">R002: Same-Day Rapid-Fire Transactions</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            r2_from = st.number_input("Start Date", value=20240101, key="r2_from")
        with col2:
            r2_to = st.number_input("End Date", value=20241231, key="r2_to")
        with col3:
            r2_min = st.number_input("Minimum Count", value=10, min_value=2, key="r2_min")

        if st.button("Run Detection", key="r2_run"):
            df = detect_rapid_fire(date_from=r2_from, date_to=r2_to, min_count=r2_min, limit=100)
            if df.empty:
                st.info("No detections found.")
            else:
                st.markdown(f"Detection results: **{len(df):,} cases**")
                fig = px.scatter(
                    df, x="거래건수", y="합산금액",
                    color_discrete_sequence=[ACCENT_COLOR],
                    hover_data=["출금계좌일련번호"],
                )
                fig.update_layout(title="Rapid-Fire: Count vs Total Amount")
                _apply_dark(fig)
                st.plotly_chart(fig, width='stretch')
                st.dataframe(df, width='stretch', height=400)

    # ------------------------------------------------------------------
    # 탭3: R003 정액거래 패턴
    # ------------------------------------------------------------------
    with tabs[3]:
        st.markdown('<p class="section-header">R003: Round Amount Pattern</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            r3_from = st.number_input("Start Date", value=20240101, key="r3_from")
            r3_to = st.number_input("End Date", value=20241231, key="r3_to")
        with col2:
            r3_unit = st.number_input("Round Unit (KRW)", value=1_000_000, step=100_000, key="r3_unit")
            r3_min = st.number_input("Minimum Count", value=3, min_value=2, key="r3_min")

        if st.button("Run Detection", key="r3_run"):
            df = detect_round_amounts(
                date_from=r3_from, date_to=r3_to,
                round_unit=r3_unit, min_count=r3_min, limit=100,
            )
            if df.empty:
                st.info("No detections found.")
            else:
                st.markdown(f"Detection results: **{len(df):,} cases**")
                st.dataframe(df, width='stretch', height=400)

    # ------------------------------------------------------------------
    # 탭4: R004 기관집중거래
    # ------------------------------------------------------------------
    with tabs[4]:
        st.markdown('<p class="section-header">R004: Institution Concentration</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            r4_ratio = st.slider("Minimum concentration ratio", 0.5, 1.0, 0.8, 0.05, key="r4_ratio")
        with col2:
            r4_min_tx = st.number_input("Minimum transactions", value=10, min_value=1, key="r4_min")

        if st.button("Run Detection", key="r4_run"):
            df = detect_institution_concentration(
                min_ratio=r4_ratio, min_transactions=r4_min_tx, limit=100,
            )
            if df.empty:
                st.info("No detections found.")
            else:
                st.markdown(f"Detection results: **{len(df):,} cases**")
                fig = px.bar(
                    df.head(20), x="출금계좌일련번호", y="집중비율",
                    color_discrete_sequence=[MINT_COLOR], text="집중비율",
                )
                fig.update_layout(title="Institution Concentration Ratio")
                fig.update_xaxes(type="category")
                _apply_dark(fig)
                st.plotly_chart(fig, width='stretch')
                st.dataframe(df, width='stretch', height=400)

    # ------------------------------------------------------------------
    # 탭5: R005 거래패턴 급변
    # ------------------------------------------------------------------
    with tabs[5]:
        st.markdown('<p class="section-header">R005: Transaction Pattern Change</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Baseline Period**")
            r5_b_from = st.number_input("Start Date", value=20230101, key="r5_b_from")
            r5_b_to = st.number_input("End Date", value=20230630, key="r5_b_to")
        with col2:
            st.markdown("**Comparison Period**")
            r5_c_from = st.number_input("Start Date", value=20230701, key="r5_c_from")
            r5_c_to = st.number_input("End Date", value=20231231, key="r5_c_to")

        r5_threshold = st.slider("Change multiplier threshold", 1.5, 10.0, 3.0, 0.5, key="r5_threshold")

        if st.button("Run Detection", key="r5_run"):
            df = detect_pattern_change(
                base_start=r5_b_from, base_end=r5_b_to,
                compare_start=r5_c_from, compare_end=r5_c_to,
                change_threshold=r5_threshold, limit=100,
            )
            if df.empty:
                st.info("No detections found.")
            else:
                st.markdown(f"Detection results: **{len(df):,} cases**")
                fig = px.scatter(
                    df, x="기준기간건수", y="비교기간건수",
                    size="건수변화배율", color="건수변화배율",
                    color_continuous_scale=[[0, "#1A1F2E"], [0.5, "#2A6B65"], [1, "#E15759"]],
                    hover_data=["출금계좌일련번호"],
                )
                fig.update_layout(title="Transaction Pattern Change: Baseline vs Comparison")
                _apply_dark(fig, height=420)
                st.plotly_chart(fig, width='stretch')
                st.dataframe(df, width='stretch', height=400)
