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
    st.markdown('<p class="page-title">거래 모니터링</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">규칙 기반 의심거래 모니터링 (R001~R005)</p>',
        unsafe_allow_html=True,
    )

    # --- 종합 통계 ---
    summary = get_monitoring_summary()
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("총 거래 건수", f"{summary['총거래건수']:,}")
    with c2:
        _metric_card("심야거래 건수", f"{summary['심야거래건수']:,}")
    with c3:
        _metric_card("심야거래 비율", f"{summary['심야거래비율']:.2f}%")
    with c4:
        _metric_card("고빈도 거래일수", f"{summary['고빈도거래일수']:,}", "10건 이상/일")

    # --- 탭 ---
    tabs = st.tabs(["종합 대시보드", "R001 심야대량", "R002 다건거래", "R003 정액패턴", "R004 기관집중", "R005 패턴급변"])

    # ------------------------------------------------------------------
    # 탭0: 종합 대시보드
    # ------------------------------------------------------------------
    with tabs[0]:
        st.markdown('<p class="section-header">전체 규칙 실행 결과</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            all_from = st.number_input("시작일", value=20240101, key="mon_all_from")
        with col2:
            all_to = st.number_input("종료일", value=20241231, key="mon_all_to")

        if st.button("전체 규칙 실행", type="primary", key="mon_run_all"):
            with st.spinner("전체 규칙 실행 중..."):
                results = run_all_rules(date_from=all_from, date_to=all_to)

            rule_counts = {k: v["건수"] for k, v in results.items()}
            count_df = pd.DataFrame(
                [{"규칙": k, "탐지건수": v} for k, v in rule_counts.items()]
            )
            fig = px.bar(
                count_df, x="규칙", y="탐지건수",
                color_discrete_sequence=[BAR_COLOR], text="탐지건수",
            )
            fig.update_layout(title="규칙별 탐지 건수")
            _apply_dark(fig)
            st.plotly_chart(fig, use_container_width=True)

            for rule_name, data in results.items():
                with st.expander(f"{rule_name} ({data['건수']}건)"):
                    if data["상위"]:
                        st.dataframe(pd.DataFrame(data["상위"]), use_container_width=True)
                    else:
                        st.info("탐지된 건이 없습니다.")

    # ------------------------------------------------------------------
    # 탭1: R001 심야대량거래
    # ------------------------------------------------------------------
    with tabs[1]:
        st.markdown('<p class="section-header">R001: 심야시간대 대량 거래</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            r1_from = st.number_input("시작일", value=20240101, key="r1_from")
        with col2:
            r1_to = st.number_input("종료일", value=20241231, key="r1_to")
        with col3:
            r1_min_amt = st.number_input("최소 금액", value=10_000_000, step=1_000_000, key="r1_min")

        if st.button("탐지 실행", key="r1_run"):
            df = detect_nighttime_bulk(date_from=r1_from, date_to=r1_to, min_amount=r1_min_amt, limit=100)
            if df.empty:
                st.info("탐지된 건이 없습니다.")
            else:
                st.markdown(f"탐지 결과: **{len(df):,}건**")
                fig = px.histogram(df, x="거래금액", nbins=30, color_discrete_sequence=[LINE_COLOR])
                fig.update_layout(title="심야 대량거래 금액 분포")
                _apply_dark(fig)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # 탭2: R002 동일일 다건거래
    # ------------------------------------------------------------------
    with tabs[2]:
        st.markdown('<p class="section-header">R002: 동일일 다건 거래</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            r2_from = st.number_input("시작일", value=20240101, key="r2_from")
        with col2:
            r2_to = st.number_input("종료일", value=20241231, key="r2_to")
        with col3:
            r2_min = st.number_input("최소 건수", value=10, min_value=2, key="r2_min")

        if st.button("탐지 실행", key="r2_run"):
            df = detect_rapid_fire(date_from=r2_from, date_to=r2_to, min_count=r2_min, limit=100)
            if df.empty:
                st.info("탐지된 건이 없습니다.")
            else:
                st.markdown(f"탐지 결과: **{len(df):,}건**")
                fig = px.scatter(
                    df, x="거래건수", y="합산금액",
                    color_discrete_sequence=[ACCENT_COLOR],
                    hover_data=["출금계좌일련번호"],
                )
                fig.update_layout(title="다건거래: 건수 vs 합산금액")
                _apply_dark(fig)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # 탭3: R003 정액거래 패턴
    # ------------------------------------------------------------------
    with tabs[3]:
        st.markdown('<p class="section-header">R003: 정액 거래 패턴</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            r3_from = st.number_input("시작일", value=20240101, key="r3_from")
            r3_to = st.number_input("종료일", value=20241231, key="r3_to")
        with col2:
            r3_unit = st.number_input("정액 단위 (원)", value=1_000_000, step=100_000, key="r3_unit")
            r3_min = st.number_input("최소 건수", value=3, min_value=2, key="r3_min")

        if st.button("탐지 실행", key="r3_run"):
            df = detect_round_amounts(
                date_from=r3_from, date_to=r3_to,
                round_unit=r3_unit, min_count=r3_min, limit=100,
            )
            if df.empty:
                st.info("탐지된 건이 없습니다.")
            else:
                st.markdown(f"탐지 결과: **{len(df):,}건**")
                st.dataframe(df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # 탭4: R004 기관집중거래
    # ------------------------------------------------------------------
    with tabs[4]:
        st.markdown('<p class="section-header">R004: 특정 기관 집중 거래</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            r4_ratio = st.slider("최소 집중 비율", 0.5, 1.0, 0.8, 0.05, key="r4_ratio")
        with col2:
            r4_min_tx = st.number_input("최소 거래 건수", value=10, min_value=1, key="r4_min")

        if st.button("탐지 실행", key="r4_run"):
            df = detect_institution_concentration(
                min_ratio=r4_ratio, min_transactions=r4_min_tx, limit=100,
            )
            if df.empty:
                st.info("탐지된 건이 없습니다.")
            else:
                st.markdown(f"탐지 결과: **{len(df):,}건**")
                fig = px.bar(
                    df.head(20), x="출금계좌일련번호", y="집중비율",
                    color_discrete_sequence=[MINT_COLOR], text="집중비율",
                )
                fig.update_layout(title="기관 집중 비율")
                fig.update_xaxes(type="category")
                _apply_dark(fig)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # 탭5: R005 거래패턴 급변
    # ------------------------------------------------------------------
    with tabs[5]:
        st.markdown('<p class="section-header">R005: 거래 패턴 급변</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**기준 기간**")
            r5_b_from = st.number_input("시작일", value=20230101, key="r5_b_from")
            r5_b_to = st.number_input("종료일", value=20230630, key="r5_b_to")
        with col2:
            st.markdown("**비교 기간**")
            r5_c_from = st.number_input("시작일", value=20230701, key="r5_c_from")
            r5_c_to = st.number_input("종료일", value=20231231, key="r5_c_to")

        r5_threshold = st.slider("변화 배율 기준", 1.5, 10.0, 3.0, 0.5, key="r5_threshold")

        if st.button("탐지 실행", key="r5_run"):
            df = detect_pattern_change(
                base_start=r5_b_from, base_end=r5_b_to,
                compare_start=r5_c_from, compare_end=r5_c_to,
                change_threshold=r5_threshold, limit=100,
            )
            if df.empty:
                st.info("탐지된 건이 없습니다.")
            else:
                st.markdown(f"탐지 결과: **{len(df):,}건**")
                fig = px.scatter(
                    df, x="기준기간건수", y="비교기간건수",
                    size="건수변화배율", color="건수변화배율",
                    color_continuous_scale=[[0, "#1A1F2E"], [0.5, "#2A6B65"], [1, "#E15759"]],
                    hover_data=["출금계좌일련번호"],
                )
                fig.update_layout(title="거래 패턴 변화: 기준 vs 비교 기간")
                _apply_dark(fig, height=420)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True, height=400)
