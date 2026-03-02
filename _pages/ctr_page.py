"""기능5: CTR 모니터링 페이지."""

import streamlit as st
import plotly.express as px
import pandas as pd

from src.features.ctr_monitor import (
    get_ctr_candidates,
    detect_structuring,
    assess_account_structuring,
    get_ctr_summary,
)
from src.ui.chart_utils import BAR_COLOR, ACCENT_COLOR, MINT_COLOR, apply_dark as _apply_dark


def _metric_card(label, value, sub="", white=False):
    value_class = "value white" if white else "value"
    st.markdown(f"""<div class="metric-card">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
        <div class="sub">{sub}</div>
    </div>""", unsafe_allow_html=True)


def render():
    st.markdown('<p class="page-title">CTR 모니터링</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">고액현금거래보고(CTR) 대상 조회 및 분할거래(Structuring) 탐지</p>',
        unsafe_allow_html=True,
    )

    # --- 종합 통계 ---
    with st.spinner("데이터 불러오는 중..."):
        summary = get_ctr_summary()
    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("고액거래 건수", f"{summary['고액거래건수']:,}", "1,000만원 이상")
    with c2:
        _metric_card("고액거래 총액", f"{summary['고액거래총액']:,.0f}원")
    with c3:
        _metric_card("분할거래 의심", f"{summary['분할거래의심건수']:,}", "계좌-일 기준")

    # --- 탭 (선택된 탭만 쿼리 실행하여 지연 로딩) ---
    tab_names = ["CTR 대상 고액거래", "분할거래 의심", "계좌별 분석"]
    selected_tab = st.radio(
        "분석 유형",
        tab_names,
        horizontal=True,
        key="ctr_tab",
        label_visibility="collapsed",
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # ------------------------------------------------------------------
    # 탭1: 고액거래
    # ------------------------------------------------------------------
    if selected_tab == tab_names[0]:
        st.markdown('<p class="section-header">1,000만원 이상 고액거래</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            date_from = st.number_input("시작일 (YYYYMMDD)", value=20240101, key="ctr_hv_from")
        with col2:
            date_to = st.number_input("종료일 (YYYYMMDD)", value=20241231, key="ctr_hv_to")
        with col3:
            limit = st.slider("조회 건수", 10, 200, 50, key="ctr_hv_limit")

        with st.spinner("고액거래 조회 중..."):
            df = get_ctr_candidates(date_from=date_from, date_to=date_to, limit=limit)
        if df.empty:
            st.info("조건에 맞는 고액거래가 없습니다.")
        else:
            st.markdown(f'<p class="section-header">조회 결과: {len(df):,}건</p>', unsafe_allow_html=True)

            # 금액 분포 히스토그램
            fig = px.histogram(df, x="거래금액", nbins=30, color_discrete_sequence=[BAR_COLOR])
            fig.update_layout(title="고액거래 금액 분포")
            _apply_dark(fig)
            st.plotly_chart(fig, width='stretch')

            st.dataframe(df, width='stretch', height=400)

    # ------------------------------------------------------------------
    # 탭2: 분할거래
    # ------------------------------------------------------------------
    elif selected_tab == tab_names[1]:
        st.markdown('<p class="section-header">분할거래(Structuring) 의심 탐지</p>', unsafe_allow_html=True)
        st.markdown(
            '<p style="color:#8B8FA3;font-size:13px;">'
            '동일 계좌가 동일일에 보고 기준 미만으로 여러 건 거래하여 합산이 기준 이상인 경우</p>',
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            s_date_from = st.number_input("시작일", value=20240101, key="ctr_st_from")
            s_date_to = st.number_input("종료일", value=20241231, key="ctr_st_to")
        with col2:
            threshold = st.number_input(
                "보고 기준 금액 (원)", value=10_000_000, step=1_000_000, key="ctr_threshold"
            )
            s_limit = st.slider("조회 건수", 10, 200, 50, key="ctr_st_limit")

        with st.spinner("분할거래 분석 중..."):
            struct_df = detect_structuring(
                date_from=s_date_from, date_to=s_date_to,
                threshold=threshold, limit=s_limit,
            )
        if struct_df.empty:
            st.info("분할거래 의심 건이 없습니다.")
        else:
            st.markdown(
                f'<p class="section-header">탐지 결과: {len(struct_df):,}건 (계좌-일 기준)</p>',
                unsafe_allow_html=True,
            )

            fig = px.scatter(
                struct_df, x="거래건수", y="합산금액",
                size="합산금액", color_discrete_sequence=[ACCENT_COLOR],
                hover_data=["출금계좌일련번호", "거래일자"],
            )
            fig.update_layout(title="분할거래 의심: 건수 vs 합산금액")
            _apply_dark(fig)
            st.plotly_chart(fig, width='stretch')

            st.dataframe(struct_df, width='stretch', height=400)

    # ------------------------------------------------------------------
    # 탭3: 계좌별 분석
    # ------------------------------------------------------------------
    elif selected_tab == tab_names[2]:
        st.markdown('<p class="section-header">계좌별 분할거래 패턴 분석</p>', unsafe_allow_html=True)
        account_id = st.number_input("계좌 번호 (출금계좌일련번호)", value=0, key="ctr_account")

        if account_id > 0 and st.button("분석 실행", key="ctr_analyze"):
            with st.spinner("분석 중..."):
                result = assess_account_structuring(account_id)

            if result.get("총거래건수", 0) == 0:
                st.warning("해당 계좌의 거래 내역이 없습니다.")
            else:
                c1, c2, c3 = st.columns(3)
                with c1:
                    _metric_card("총 거래 건수", f"{result['총거래건수']:,}")
                with c2:
                    _metric_card("총 거래 금액", f"{result['총거래금액']:,}원")
                with c3:
                    _metric_card("분할거래 의심일수", f"{result['분할거래의심일수']:,}")

                if result["분할거래상세"]:
                    detail_df = pd.DataFrame(result["분할거래상세"])
                    st.dataframe(detail_df, width='stretch')
                else:
                    st.success("분할거래 의심 패턴이 탐지되지 않았습니다.")
