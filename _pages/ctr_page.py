"""Feature 5: CTR Monitoring Page."""

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
    """Renders an HTML metric-card."""
    value_class = "value white" if white else "value"
    st.markdown(f"""<div class="metric-card">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
        <div class="sub">{sub}</div>
    </div>""", unsafe_allow_html=True)


def render():
    st.markdown('<p class="page-title">CTR Monitoring</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">Currency Transaction Report (CTR) candidate lookup and structuring detection</p>',
        unsafe_allow_html=True,
    )

    # --- Summary Statistics ---
    with st.spinner("Loading data..."):
        summary = get_ctr_summary()
    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("High-Value Transactions", f"{summary['high_value_count']:,}", "Over 10M KRW")
    with c2:
        _metric_card("High-Value Total Amount", f"{summary['high_value_total']:,.0f} KRW", "Cumulative amount")
    with c3:
        _metric_card("Structuring Suspects", f"{summary['structuring_suspect_count']:,}", "Account-day basis")

    # --- Tabs Configuration (lazy loading) ---
    tab_names = ["CTR High-Value Transactions", "Structuring Suspects", "Account Pattern Analysis"]
    selected_tab = st.radio(
        "Analysis Type",
        tab_names,
        horizontal=True,
        key="ctr_tab",
        label_visibility="collapsed",
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # ------------------------------------------------------------------
    # Tab 1: High-Value
    # ------------------------------------------------------------------
    if selected_tab == tab_names[0]:
        st.markdown('<p class="section-header">High-Value Transactions (Over 10M KRW)</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            date_from = st.number_input("Start Date (YYYYMMDD)", value=20240101, key="ctr_hv_from")
        with col2:
            date_to = st.number_input("End Date (YYYYMMDD)", value=20241231, key="ctr_hv_to")
        with col3:
            limit = st.slider("Number of results", 10, 200, 50, key="ctr_hv_limit")

        with st.spinner("Loading high-value transactions..."):
            df = get_ctr_candidates(date_from=date_from, date_to=date_to, limit=limit)
        if df.empty:
            st.info("No high-value transactions found for the selected criteria.")
        else:
            st.markdown(f'<p class="section-header">Results: {len(df):,} transactions</p>', unsafe_allow_html=True)

            fig = px.histogram(df, x="amount", nbins=30, color_discrete_sequence=[BAR_COLOR])
            fig.update_layout(title="High-Value Transaction Amount Distribution")
            _apply_dark(fig)
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # Tab 2: Structuring
    # ------------------------------------------------------------------
    elif selected_tab == tab_names[1]:
        st.markdown('<p class="section-header">Structuring Suspect Detection</p>', unsafe_allow_html=True)
        st.markdown(
            '<p style="color:#8B8FA3;font-size:13px;">'
            'Detects cases where the same account makes multiple sub-threshold transactions on the same day that sum above the reporting threshold</p>',
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            s_date_from = st.number_input("Start Date", value=20240101, key="ctr_st_from")
            s_date_to = st.number_input("End Date", value=20241231, key="ctr_st_to")
        with col2:
            threshold = st.number_input(
                "Reporting Threshold (KRW)", value=10_000_000, step=1_000_000, key="ctr_threshold"
            )
            s_limit = st.slider("Number of results", 10, 200, 50, key="ctr_st_limit")

        with st.spinner("Analyzing structuring patterns..."):
            struct_df = detect_structuring(
                date_from=s_date_from, date_to=s_date_to,
                threshold=threshold, limit=s_limit,
            )
        if struct_df.empty:
            st.info("No structuring suspects found.")
        else:
            st.markdown(
                f'<p class="section-header">Detection Results: {len(struct_df):,} cases (account-day basis)</p>',
                unsafe_allow_html=True,
            )

            fig = px.scatter(
                struct_df, x="tx_count", y="total_amount",
                size="total_amount", color_discrete_sequence=[ACCENT_COLOR],
                hover_data=["sender_acc", "date"],
            )
            fig.update_layout(title="Structuring Suspects: Count vs Total Amount")
            _apply_dark(fig)
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(struct_df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # Tab 3: Account Analysis
    # ------------------------------------------------------------------
    elif selected_tab == tab_names[2]:
        st.markdown('<p class="section-header">Account Structuring Pattern Analysis</p>', unsafe_allow_html=True)
        account_id = st.number_input("Account ID (Sender Account)", value=0, key="ctr_account")

        if account_id > 0 and st.button("Run Analysis", key="ctr_analyze"):
            with st.spinner("Analyzing..."):
                result = assess_account_structuring(account_id)

            if result.get("total_tx_count", 0) == 0:
                st.warning("No transaction history found for this account.")
            else:
                c1, c2, c3 = st.columns(3)
                with c1:
                    _metric_card("Total Transactions", f"{result['total_tx_count']:,}")
                with c2:
                    _metric_card("Total Amount", f"{result['total_amount']:,} KRW")
                with c3:
                    _metric_card("Structuring Suspect Days", f"{result['structuring_suspect_days']:,}")

                if result["structuring_details"]:
                    detail_df = pd.DataFrame(result["structuring_details"])
                    st.dataframe(detail_df, use_container_width=True)
                else:
                    st.success("No structuring patterns detected for this account.")
