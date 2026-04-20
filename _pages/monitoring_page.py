"""Feature 7: Transaction Monitoring Rule Detection Page."""

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
    detect_dormant_reactivation,
)
from src.features.aml_reference import FRAUD_TYPE_MAP
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


def _render_dark_table(df):
    """Renders a dark-styled HTML table for the dataframe."""
    cols = df.columns.tolist()
    header_html = "".join([f"<th>{c}</th>" for c in cols])
    
    rows_html = ""
    for _, row in df.iterrows():
        row_html = "".join([f"<td>{row[c]}</td>" for c in cols])
        rows_html += f"<tr>{row_html}</tr>"
        
    st.markdown(f"""<table class="dark-table">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{rows_html}</tbody>
    </table>""", unsafe_allow_html=True)


def render():
    st.markdown('<p class="page-title">Transaction Monitoring</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">Rule-based suspicious transaction monitoring (R001~R006)</p>',
        unsafe_allow_html=True,
    )

    # --- Summary statistics ---
    filters = {"date_from": 20240101, "date_to": 20241231}
    with st.spinner("Loading data..."):
        summary = get_monitoring_summary(filters)
    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("Total Multi-Day Transacting Accounts", f"{summary['high_freq_tx_count']:,}", "Rapid-fire suspects")
    with c2:
        _metric_card("Late-night Transaction Count", f"{summary['night_tx_count']:,}", f"{summary['night_tx_ratio']}% of total")
    with c3:
        _metric_card("Total Filtered Transactions", f"{summary['total_tx_count']:,}", "Within selected date range")

    # --- Tabs ---
    tabs = st.tabs(["Overview Dashboard", "R001 Nighttime Bulk", "R002 Rapid-Fire", "R003 Round Amounts", "R004 Institution Concentration", "R005 Pattern Change"])

    # ------------------------------------------------------------------
    # Tab 0: Overview Dashboard
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
                all_res = run_all_rules(all_from, all_to)
                st.session_state["mon_all_results"] = all_res
        
        all_res = st.session_state.get("mon_all_results")
        if all_res:
            col_left, col_right = st.columns(2)
            
            with col_left:
                st.markdown('<p class="section-header">Rule Violations (Summary)</p>', unsafe_allow_html=True)
                rule_counts = pd.DataFrame([
                    {"Rule": k, "Violations": v["count"]} for k, v in all_res.items()
                ])
                fig_rules = px.bar(rule_counts, x="Violations", y="Rule", orientation="h",
                                   color="Violations", color_continuous_scale="Viridis")
                _apply_dark(fig_rules, height=350)
                st.plotly_chart(fig_rules, use_container_width=True)

            st.markdown('<p class="section-header">Detailed Violation Logs</p>', unsafe_allow_html=True)
            t1, t2, t3, t4, t5 = st.tabs([
                "Night Bulk (R001)", "Rapid Fire (R002)", "Round Amount (R003)",
                "Concentration (R004)", "Pattern Change (R005)"
            ])
            
            with t1:
                df1 = pd.DataFrame(all_res["R001_Nighttime_Bulk"]["top"])
                if not df1.empty:
                    df1.columns = ["Date", "Time", "Sender Acc", "Receiver Acc", "Sender Bank", "Receiver Bank", "Amount", "Is Fraud", "Fraud Type"]
                    _render_dark_table(df1)
                else: st.info("No violations found.")
            with t2:
                df2 = pd.DataFrame(all_res["R002_Rapid_Fire"]["top"])
                if not df2.empty:
                    df2.columns = ["Account ID", "Date", "Tx Count", "Total Amount", "Fraud Count"]
                    _render_dark_table(df2)
                else: st.info("No violations found.")
            with t3:
                df3 = pd.DataFrame(all_res["R003_Round_Amount"]["top"])
                if not df3.empty:
                    df3.columns = ["Account ID", "Round Tx Count", "Total Amount", "Distinct Amount Count"]
                    _render_dark_table(df3)
                else: st.info("No violations found.")
            with t4:
                df4 = pd.DataFrame(all_res["R004_Concentrated_Bank"]["top"])
                if not df4.empty:
                    df4.columns = ["Account ID", "Total Count", "Max Bank Count", "Ratio", "Bank ID"]
                    _render_dark_table(df4)
                else: st.info("No violations found.")
            with t5:
                df5 = pd.DataFrame(all_res["R005_Pattern_Change"]["top"])
                if not df5.empty:
                    df5.columns = ["Account ID", "Base Count", "Comp Count", "Count Ratio", "Base Amount", "Comp Amount", "Amount Ratio"]
                    _render_dark_table(df5)
                else: st.info("No violations found.")

    # ------------------------------------------------------------------
    # Tab 1: R001 Nighttime Bulk Transactions
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
                if not df.empty:
                    df["fraud_type"] = df["fraud_type"].map(FRAUD_TYPE_MAP).fillna("Other")
                st.markdown(f"Detection results: **{len(df):,} cases**")
                fig = px.histogram(df, x="amount", nbins=30, color_discrete_sequence=[LINE_COLOR])
                fig.update_layout(title="Nighttime Bulk Transaction Amount Distribution")
                _apply_dark(fig)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # Tab 2: R002 Rapid-Fire Transactions
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
                    df, x="tx_count", y="total_amount",
                    color_discrete_sequence=[ACCENT_COLOR],
                    hover_data=["sender_acc"],
                )
                fig.update_layout(title="Rapid-Fire: Count vs Total Amount")
                _apply_dark(fig)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # Tab 3: R003 Round Amount Pattern
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
                st.dataframe(df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # Tab 4: R004 Institution Concentration
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
                    df.head(20), x="sender_acc", y="concentration_ratio",
                    color_discrete_sequence=[MINT_COLOR], text="concentration_ratio",
                )
                fig.update_layout(title="Institution Concentration Ratio")
                fig.update_xaxes(type="category")
                _apply_dark(fig)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True, height=400)

    # ------------------------------------------------------------------
    # Tab 5: R005 Transaction Pattern Change
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
                    df, x="base_period_count", y="comp_period_count",
                    size="count_change_ratio", color="count_change_ratio",
                    color_continuous_scale=[[0, "#1A1F2E"], [0.5, "#2A6B65"], [1, "#E15759"]],
                    hover_data=["sender_acc"],
                )
                fig.update_layout(title="Transaction Pattern Change: Baseline vs Comparison")
                _apply_dark(fig, height=420)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True, height=400)
