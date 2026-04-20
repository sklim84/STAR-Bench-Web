"""Feature 6: Account Risk Assessment Page."""

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
    """Renders an HTML metric-card."""
    value_class = "value white" if white else "value"
    st.markdown(f"""<div class="metric-card">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
        <div class="sub">{sub}</div>
    </div>""", unsafe_allow_html=True)


def _render_dark_table(df):
    """Renders a DataFrame as a styled HTML table."""
    table_html = """<table class="dark-table">
        <thead><tr>"""
    for col in df.columns:
        table_html += f"<th>{col}</th>"
    table_html += "</tr></thead><tbody>"
    for _, row in df.iterrows():
        table_html += "<tr>"
        for val in row:
            if isinstance(val, (int, float)):
                if abs(val) >= 1_000_000:
                    table_html += f"<td>{val:,.0f}</td>"
                elif isinstance(val, float):
                    table_html += f"<td>{val:.2f}</td>"
                else:
                    table_html += f"<td>{val:,}</td>"
            else:
                table_html += f"<td>{val}</td>"
        table_html += "</tr>"
    table_html += "</tbody></table>"
    st.markdown(table_html, unsafe_allow_html=True)


def render():
    st.markdown('<p class="page-title">Account Risk Assessment</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">Account risk scoring (0-100) based on 5 behavioral indicators</p>',
        unsafe_allow_html=True,
    )

    tab1, tab2 = st.tabs(["Individual Account Risk", "High-Risk Account Ranking"])

    # ------------------------------------------------------------------
    # Tab 1: Individual Account Risk
    # ------------------------------------------------------------------
    with tab1:
        st.markdown('<p class="section-header">Individual Account Risk Profile</p>', unsafe_allow_html=True)
        account_id = st.number_input(
            "Enter Account ID to analyze", value=0, key="risk_account_id"
        )

        if account_id > 0:
            if st.button("Evaluate Risk", key="risk_evaluate_btn"):
                res = score_account(account_id)
                if "error" in res:
                    st.warning(res["error"])
                else:
                    score = res["total_score"]
                    level = res["risk_level"]
                    color = "#E15759" if level == "High" else "#F28E2B" if level == "Medium" else "#4ECDC4"

                    c1, c2, c3 = st.columns(3)
                    with c1:
                        _metric_card("Outcome Score", f"{score}", "/ 100")
                    with c2:
                        st.markdown(f"""<div class="metric-card">
                            <div class="label">Risk Level</div>
                            <div class="value" style="color:{color}">{level}</div>
                            <div class="sub">Classification</div>
                        </div>""", unsafe_allow_html=True)
                    with c3:
                        _metric_card("Transactions", "Found history", "Active status")

                    col_chart1, col_chart2 = st.columns(2)

                    with col_chart1:
                        # Gauge Chart
                        fig_gauge = go.Figure(go.Indicator(
                            mode="gauge+number",
                            value=score,
                            domain={'x': [0, 1], 'y': [0, 1]},
                            title={'text': f"Risk Score: {score} ({level})", 'font': {'size': 18, 'color': '#E0E0E0'}},
                            gauge={
                                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#8B8FA3"},
                                'bar': {'color': ACCENT_COLOR},
                                'bgcolor': "#1A1F2E",
                                'borderwidth': 2,
                                'bordercolor': "#2A2F3E",
                                'steps': [
                                    {'range': [0, 40], 'color': '#1A2E28'},
                                    {'range': [40, 70], 'color': '#2E2A1A'},
                                    {'range': [70, 100], 'color': '#2E1A1A'}
                                ],
                            }
                        ))
                        _apply_dark(fig_gauge, height=350)
                        st.plotly_chart(fig_gauge, use_container_width=True)

                    with col_chart2:
                        # Radar Chart
                        comp = res["components"]
                        categories = ["Nighttime", "Amount Anomaly", "Diversity", "Velocity", "Fraud Hist"]
                        # Mapping internal keys to display labels
                        int_keys = ["nighttime_ratio", "amount_anomaly", "counterparty_diversity", "velocity_change", "fraud_history"]
                        values = [comp[k] for k in int_keys]

                        fig_radar = go.Figure()
                        fig_radar.add_trace(go.Scatterpolar(
                            r=values + [values[0]],
                            theta=categories + [categories[0]],
                            fill="toself",
                            fillcolor="rgba(78, 205, 196, 0.2)",
                            line=dict(color=MINT_COLOR, width=2),
                            name="Risk Component",
                        ))
                        fig_radar.update_layout(
                            polar=dict(
                                bgcolor="rgba(0,0,0,0)",
                                radialaxis=dict(visible=True, range=[0, 1], gridcolor="#1E2333", tickfont=dict(color="#8B8FA3")),
                                angularaxis=dict(tickfont=dict(color="#C0C4D0", size=12), gridcolor="#1E2333"),
                            ),
                            margin=dict(t=40, b=40, l=40, r=40),
                        )
                        _apply_dark(fig_radar, height=350)
                        st.plotly_chart(fig_radar, use_container_width=True)

                    st.markdown('<p class="section-header">Risk Factor Contribution</p>', unsafe_allow_html=True)
                    weights = res["weights"]
                    contrib_data = []
                    for i, k in enumerate(int_keys):
                        v = comp[k]
                        w = weights[k]
                        contrib_data.append({
                            "Indicator": categories[i],
                            "Score": round(v, 4),
                            "Weight": w,
                            "Contribution": round(v * w * 100, 1)
                        })
                    
                    contrib_df = pd.DataFrame(contrib_data)
                    fig_contrib = px.bar(
                        contrib_df, x="Indicator", y="Contribution",
                        color_discrete_sequence=[BAR_COLOR],
                        text="Contribution",
                    )
                    fig_contrib.update_layout(yaxis_title="Weighted Score Contribution")
                    _apply_dark(fig_contrib, height=350)
                    st.plotly_chart(fig_contrib, use_container_width=True)

    # ------------------------------------------------------------------
    # Tab 2: High-Risk Ranking
    # ------------------------------------------------------------------
    with tab2:
        st.markdown('<p class="section-header">Top 20 High-Risk Accounts</p>', unsafe_allow_html=True)
        col_ctrl1, col_ctrl2 = st.columns(2)
        with col_ctrl1:
            top_k = st.slider("Show Top", 5, 50, 20)
        with col_ctrl2:
            min_tx = st.number_input("Min Transactions", 1, 100, 10)

        with st.spinner("Ranking accounts..."):
            rank_df = rank_risky_accounts(top_k=top_k, min_transactions=min_tx)
        
        if rank_df.empty:
            st.info("No accounts found matching the criteria.")
        else:
            avg_risk = rank_df["risk_score_simple"].mean()
            max_risk = rank_df["risk_score_simple"].max()
            high_count = len(rank_df[rank_df["risk_score_simple"] >= 15])

            c1, c2, c3 = st.columns(3)
            with c1:
                _metric_card("Avg Risk Score", f"{avg_risk:.1f}", "Top subset avg")
            with c2:
                _metric_card("Highest Score", f"{max_risk:.1f}", "Maximum detected")
            with c3:
                _metric_card("Critical Accounts", f"{high_count}", "Score >= 15")

            # Bar chart of ranking
            fig_rank = px.bar(
                rank_df, x="account_id", y="risk_score_simple",
                title="High-Risk Account Ranking",
                color="risk_score_simple",
                color_continuous_scale=[[0, "#1A2E28"], [0.5, "#2E2A1A"], [1, "#2E1A1A"]],
                labels={"account_id": "Account ID", "risk_score_simple": "Risk Score"}
            )
            fig_rank.update_xaxes(type="category")
            _apply_dark(fig_rank, height=400)
            st.plotly_chart(fig_rank, use_container_width=True)

            # Detail data table
            st.markdown('<p class="section-header">Ranking Details</p>', unsafe_allow_html=True)
            display_df = rank_df.copy()
            display_df.columns = [
                "Account ID", "Tx Count", "Total Amount", "Fraud Count",
                "Fraud %", "Night %", "Counterparties", "Risk Score"
            ]
            _render_dark_table(display_df)
