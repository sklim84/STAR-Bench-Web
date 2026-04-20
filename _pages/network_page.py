import streamlit as st
import plotly.graph_objects as go
import networkx as nx
import numpy as np
import pandas as pd

import config

from src.features.network import (
    get_bank_network,
    get_fraud_account_network,
    get_account_ego_network,
    get_fraud_accounts,
    get_bank_network_stats,
    build_bank_graph,
    build_account_graph,
    compute_centrality_metrics,
    detect_communities,
    get_fraud_flow_matrix,
    get_extended_network_stats,
    detect_ring_transactions,
    detect_layering_patterns,
    detect_funnel_accounts,
    get_account_ego_network_deep,
    find_shortest_path,
    get_temporal_network,
    compute_risk_score,
)
from src.data import graph_db

from src.ui.chart_utils import (
    BAR_COLOR, LINE_COLOR, ACCENT_COLOR, MINT_COLOR,
    COMMUNITY_COLORS, apply_dark as _apply_dark,
)


def _metric_card(label, value, sub="", white=False):
    """Renders an HTML metric-card."""
    value_class = "value white" if white else "value"
    st.markdown(f"""<div class="metric-card">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
        <div class="sub">{sub}</div>
    </div>""", unsafe_allow_html=True)


def _plot_network(G, title, node_color_attr=None, edge_color_attr=None,
                  center_node=None, community_map=None):
    """Visualizes a NetworkX graph using Plotly.

    Parameters
    ----------
    community_map : dict, optional
        Node -> community index mapping. If specified, nodes are colored by community.
    """
    if len(G.nodes()) == 0:
        st.warning("No network data to display.")
        return

    pos = nx.spring_layout(G, k=2 / np.sqrt(max(len(G.nodes()), 1)), seed=42, iterations=50)

    # Edges
    edge_x, edge_y = [], []
    for u, v, data in G.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=0.8, color="#555555"),
        hoverinfo="none",
    )

    # Nodes
    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    node_text = []
    node_sizes = []
    node_colors = []

    for node in G.nodes():
        degree = G.degree(node)
        in_w = sum(d.get("weight", 1) for _, _, d in G.in_edges(node, data=True)) if G.is_directed() else 0
        out_w = sum(d.get("weight", 1) for _, _, d in G.out_edges(node, data=True)) if G.is_directed() else 0
        fraud_in = sum(d.get("fraud", 0) for _, _, d in G.in_edges(node, data=True)) if G.is_directed() else 0
        fraud_out = sum(d.get("fraud", 0) for _, _, d in G.out_edges(node, data=True)) if G.is_directed() else 0

        hover_parts = [f"Node: {node}", f"Connections: {degree}", f"Inflow: {in_w:,}", f"Outflow: {out_w:,}"]
        if fraud_in + fraud_out > 0:
            hover_parts += [f"Fraud (in): {fraud_in:,}", f"Fraud (out): {fraud_out:,}"]
        if community_map and node in community_map:
            hover_parts.append(f"Community: {community_map[node]}")
        node_text.append("<br>".join(hover_parts))

        node_sizes.append(max(8, min(40, 5 + degree * 1.5)))

        if community_map and node in community_map:
            c_idx = community_map[node] % len(COMMUNITY_COLORS)
            node_colors.append(COMMUNITY_COLORS[c_idx])
        elif center_node and node == center_node:
            node_colors.append(LINE_COLOR)
        elif fraud_in + fraud_out > 0:
            node_colors.append(ACCENT_COLOR)
        else:
            node_colors.append(BAR_COLOR)

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=node_sizes, color=node_colors, line=dict(width=1, color="#FFFFFF")),
        text=[n if len(str(n)) <= 5 else "" for n in G.nodes()],
        textposition="top center", textfont=dict(size=9, color="#C0C4D0"),
        hovertext=node_text, hoverinfo="text",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title=dict(text=title, font=dict(color="#C0C4D0")),
        showlegend=False, height=600,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(t=40, b=20, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#C0C4D0"),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_dark_table(df, max_rows=20):
    """Renders a DataFrame as a dark-table HTML table."""
    if len(df) == 0:
        st.info("No data to display.")
        return

    display_df = df.head(max_rows)
    header = "".join(f"<th>{col}</th>" for col in display_df.columns)
    rows = ""
    for _, row in display_df.iterrows():
        cells = ""
        for col in display_df.columns:
            val = row[col]
            if isinstance(val, float):
                cells += f"<td>{val:.4f}</td>"
            elif isinstance(val, (int, np.integer)):
                cells += f"<td>{val:,}</td>"
            else:
                cells += f"<td>{val}</td>"
        rows += f"<tr>{cells}</tr>"

    st.markdown(f"""
    <table class="dark-table">
        <thead><tr>{header}</tr></thead>
        <tbody>{rows}</tbody>
    </table>
    """, unsafe_allow_html=True)


# ------------------------------------------------------------------
# Tab 1: Institution Network
# ------------------------------------------------------------------

def _render_tab_bank_network():
    """Renders the institution network tab."""
    with st.spinner("Loading data..."):
        stats = get_bank_network_stats()
        if stats.empty:
            st.warning("Unable to retrieve institution network statistics.")
            return
        row = stats.iloc[0]

        bank_df = get_bank_network()
        bank_G = build_bank_graph(bank_df)
        ext_stats = get_extended_network_stats(bank_G)

    st.markdown('<p class="section-header">Network Summary</p>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("Sender Institutions", f"{int(row['sender_banks'])}", "Sending institutions")
    with c2:
        _metric_card("Receiver Institutions", f"{int(row['receiver_banks'])}", "Receiving institutions")
    with c3:
        _metric_card("Inter-Institution Links", f"{int(row['connection_count']):,}", "Unique transaction paths")
    c4, c5, c6 = st.columns(3)
    with c4:
        _metric_card("Network Density", f"{ext_stats['density']:.4f}", "0 (sparse) ~ 1 (fully connected)")
    with c5:
        _metric_card("Avg Clustering", f"{ext_stats['avg_clustering']:.4f}", "Clustering coefficient")
    with c6:
        _metric_card("Hub Institution", f"{ext_stats['hub_node']}", f"Connections: {ext_stats['hub_degree']}")

    fraud_filter = st.checkbox("Show fraud-related links only", value=True, key="bank_fraud")
    if fraud_filter:
        filtered = [(u, v) for u, v, d in bank_G.edges(data=True) if d.get("fraud", 0) > 0]
        if filtered:
            bank_G_show = bank_G.edge_subgraph(filtered).copy()
        else:
            bank_G_show = nx.DiGraph()
    else:
        bank_G_show = bank_G

    _plot_network(
        bank_G_show,
        f"Inter-Institution Transaction Network ({len(bank_G_show.nodes())} nodes, {len(bank_G_show.edges())} links)",
    )

    st.markdown('<p class="section-header">Centrality Analysis (Top 10)</p>', unsafe_allow_html=True)

    with st.spinner("Computing centrality metrics..."):
        centrality_df = compute_centrality_metrics(bank_G)

    if len(centrality_df) > 0:
        top10 = centrality_df.head(10)
        display_cols = top10[["Node", "degree", "betweenness", "closeness", "eigenvector"]].copy()
        display_cols.columns = ["Institution", "Degree", "Betweenness", "Closeness", "Eigenvector"]
        _render_dark_table(display_cols, max_rows=10)

        st.markdown("", unsafe_allow_html=True)
        col_left, col_right = st.columns(2)

        with col_left:
            fig_degree = go.Figure(go.Bar(
                x=top10["Node"],
                y=top10["degree"],
                marker_color=MINT_COLOR,
                text=top10["degree"],
                textposition="outside",
                textfont=dict(color="#E0E0E0", size=11),
            ))
            fig_degree.update_layout(title=dict(text="Degree (Connections)", font=dict(color="#C0C4D0", size=14)))
            _apply_dark(fig_degree, height=350)
            fig_degree.update_xaxes(title_text="Institution", title_font=dict(color="#8B8FA3", size=11))
            fig_degree.update_yaxes(title_text="Degree", title_font=dict(color="#8B8FA3", size=11))
            st.plotly_chart(fig_degree, use_container_width=True)

        with col_right:
            fig_between = go.Figure(go.Bar(
                x=top10["Node"],
                y=top10["betweenness"],
                marker_color=ACCENT_COLOR,
                text=[f"{v:.4f}" for v in top10["betweenness"]],
                textposition="outside",
                textfont=dict(color="#E0E0E0", size=11),
            ))
            fig_between.update_layout(title=dict(text="Betweenness Centrality", font=dict(color="#C0C4D0", size=14)))
            _apply_dark(fig_between, height=350)
            fig_between.update_xaxes(title_text="Institution", title_font=dict(color="#8B8FA3", size=11))
            fig_between.update_yaxes(title_text="Betweenness", title_font=dict(color="#8B8FA3", size=11))
            st.plotly_chart(fig_between, use_container_width=True)
    else:
        st.info("No nodes available for centrality computation.")

    with st.expander("Institution Network Detailed Statistics"):
        degree_df = bank_df.groupby("source").agg(
            out_count=("total_txns", "sum"), fraud_count=("fraud_txns", "sum")
        ).reset_index().sort_values("fraud_count", ascending=False).head(15)
        degree_df.columns = ["Institution", "Outflow Count", "Fraud Count"]
        _render_dark_table(degree_df, max_rows=15)


# ------------------------------------------------------------------
# Tab 2: Fraud Account Network
# ------------------------------------------------------------------

def _render_tab_fraud_account_network():
    """Renders the fraud account network tab."""
    limit = st.slider("Number of fraud links to display", 100, 1000, 300, 50, key="fraud_limit")
    with st.spinner("Loading fraud network..."):
        fraud_df = get_fraud_account_network(limit=limit)

    if len(fraud_df) == 0:
        st.info("No fraud network data available.")
        return

    fraud_G = build_account_graph(fraud_df)

    st.markdown('<p class="section-header">Fraud Account Network Summary</p>', unsafe_allow_html=True)
    avg_degree = sum(dict(fraud_G.degree()).values()) / max(len(fraud_G.nodes()), 1)

    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("Fraud Accounts", f"{len(fraud_G.nodes()):,}", "Unique fraud-related accounts")
    with c2:
        _metric_card("Fraud Links", f"{len(fraud_G.edges()):,}", "Transaction edges")
    with c3:
        _metric_card("Avg Connections", f"{avg_degree:.1f}", "Per account average")

    st.markdown('<p class="section-header">Community Detection</p>', unsafe_allow_html=True)
    show_communities = st.checkbox("Color by community", value=True, key="show_community")

    community_map = None
    if show_communities:
        with st.spinner("Detecting communities..."):
            community_df = detect_communities(fraud_G)
        if len(community_df) > 0:
            community_map = dict(zip(community_df["Node"], community_df["Community"]))
            n_communities = community_df["Community"].nunique()
            st.markdown(f'<p class="caption-text">Communities detected: <span style="color:#4ECDC4; font-weight:700;">{n_communities}</span></p>', unsafe_allow_html=True)

    _plot_network(fraud_G, f"Fraud Account Network (top {limit} links)", community_map=community_map)

    if show_communities and not community_df.empty:
        st.markdown('<p class="section-header">Community Statistics</p>', unsafe_allow_html=True)
        comm_stats_rows = []
        for comm_id in sorted(community_df["Community"].unique()):
            comm_nodes = community_df[community_df["Community"] == comm_id]["Node"].tolist()
            internal_edges = 0
            total_amount = 0
            for u, v, d in fraud_G.edges(data=True):
                if community_map.get(u) == comm_id and community_map.get(v) == comm_id:
                    internal_edges += 1
                    total_amount += d.get("amount", 0)
            comm_stats_rows.append({
                "Community": comm_id,
                "Nodes": len(comm_nodes),
                "Internal Links": internal_edges,
                "Internal Amount": int(total_amount),
            })
        _render_dark_table(pd.DataFrame(comm_stats_rows), max_rows=20)

    with st.expander("Fraud Type Connections"):
        display_df = fraud_df[["source", "target", "tx_count", "total_amount", "fraud_type", "fraud_desc"]].head(50)
        _render_dark_table(display_df, max_rows=50)


# ------------------------------------------------------------------
# Tab 3: Account Explorer
# ------------------------------------------------------------------

def _render_tab_account_explorer():
    """Renders the account explorer tab."""
    st.markdown("Explore the transaction network of a specific account.")
    with st.spinner("Loading account list..."):
        fraud_accounts = get_fraud_accounts()
        account_list = fraud_accounts["account_id"].tolist()

    selected = st.selectbox("Select fraud-related account", options=account_list[:100], key="account_select")
    hops = st.slider("Exploration range (hops)", 1, 5, 2, key="hop_select")

    if hops > 2 and not graph_db.is_available():
        st.info("3+ hop exploration requires Memgraph. Falling back to DuckDB (up to 2 hops).")

    if selected:
        with st.spinner(f"Exploring {hops}-hop network for account {selected}..."):
            ego_df = get_account_ego_network_deep(selected, hops=hops) if hops > 2 else get_account_ego_network(selected, hops=hops)
        if ego_df.empty:
            st.warning("No transaction data for this account.")
            return
        ego_G = build_account_graph(ego_df)
        c1, c2 = st.columns(2)
        with c1:
            _metric_card("Connected Accounts", f"{len(ego_G.nodes()) - 1}", f"Within {hops}-hop range")
        with c2:
            _metric_card("Transaction Links", f"{len(ego_G.edges())}", "Unique transaction paths")
        _plot_network(ego_G, f"Account {selected} {hops}-hop Network", center_node=str(selected))
        with st.expander("Transaction Details"):
            _render_dark_table(ego_df, max_rows=50)


# ------------------------------------------------------------------
# Tab 4: Fraud Flow
# ------------------------------------------------------------------

def _render_tab_fraud_flow():
    """Renders the inter-institution fraud flow tab."""
    st.markdown('<p class="section-header">Inter-Institution Fraud Flow</p>', unsafe_allow_html=True)
    with st.spinner("Loading fraud flow data..."):
        flow_df = get_fraud_flow_matrix()
    if flow_df.empty:
        st.info("No fraud flow data available.")
        return

    total_fraud_count = int(flow_df["fraud_count"].sum())
    total_fraud_amount = float(flow_df["fraud_amount"].sum())
    top_route = flow_df.iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    with c1: _metric_card("Total Fraud Count", f"{total_fraud_count:,}", "Inter-institution total")
    with c2: _metric_card("Total Fraud Amount", _format_amount(total_fraud_amount), "Fraud amount sum")
    with c3: _metric_card("Fraud Routes", f"{len(flow_df):,}", "Unique paths")
    with c4: _metric_card("Top Fraud Route", f"{int(top_route['source'])} → {int(top_route['target'])}", f"{int(top_route['fraud_count']):,} cases")

    metric_choice = st.radio("Display metric", ["fraud_count", "fraud_amount"], format_func=lambda x: "Count" if x=="fraud_count" else "Amount", horizontal=True)
    pivot = flow_df.pivot_table(index="source", columns="target", values=metric_choice, fill_value=0, aggfunc="sum")

    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=[f"Inst {int(c)}" for c in pivot.columns], y=[f"Inst {int(r)}" for r in pivot.index],
        colorscale=[[0, "#F5F7FA"], [0.5, "#6EE7B7"], [1, "#059669"]],
        hovertemplate="Sender: %{y}<br>Receiver: %{x}<br>Value: %{z:,.0f}<extra></extra>",
        texttemplate="%{z:,.0f}" if metric_choice=="fraud_amount" else "%{z:,}",
    ))
    _apply_dark(fig, height=500)
    fig.update_layout(xaxis_title="Receiver", yaxis_title="Sender", yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown('<p class="section-header">Top Fraud Routes</p>', unsafe_allow_html=True)
    _render_dark_table(flow_df.head(20), max_rows=20)


def _format_amount(amount):
    amount = float(amount)
    if amount >= 1e9: return f"{amount/1e9:,.1f}B"
    if amount >= 1e6: return f"{amount/1e6:,.1f}M"
    if amount >= 1e3: return f"{amount/1e3:,.0f}K"
    return f"{amount:,.0f}"


# ------------------------------------------------------------------
# Tab 5: AML Pattern Detection (Memgraph)
# ------------------------------------------------------------------

def _render_memgraph_status():
    available = graph_db.is_available()
    if available:
        st.markdown(f'<div class="memgraph-badge connected"><span style="color:#4ECDC4; font-weight:700;">Memgraph Connected</span><span style="color:#9EA3B8; margin-left:12px; font-size:12px;">bolt://{config.MEMGRAPH_HOST}:{config.MEMGRAPH_PORT}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="memgraph-badge disconnected"><span style="color:#E15759; font-weight:700;">Memgraph Not Running</span><span style="color:#9EA3B8; margin-left:12px; font-size:12px;">AML pattern detection requires Memgraph via Docker.</span></div>', unsafe_allow_html=True)
    return available


def _render_tab_aml_patterns():
    """Renders the AML pattern detection tab."""
    available = _render_memgraph_status()
    if not available:
        st.warning("Features in this tab are disabled because Memgraph is disconnected.")
        # return # Showing limited data or empty UI is fine too

    subtabs = st.tabs(["Ring Detection", "Layering Pattern", "Funnel Account", "Shortest Path"])

    with subtabs[0]:
        st.markdown('<p class="section-header">Ring Transaction Detection</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1: min_len = st.number_input("Min length", 3, 6, 3)
        with col2: max_len = st.number_input("Max length", 3, 10, 6)
        with col3: limit = st.number_input("Limit", 10, 500, 100)
        if st.button("Run Ring Detection"):
            df = detect_ring_transactions(min_len, max_len, limit=limit)
            if df.empty: st.info("No ring patterns found.")
            else:
                _metric_card("Detections", f"{len(df)}", "Circular paths")
                _render_dark_table(df)

    with subtabs[1]:
        st.markdown('<p class="section-header">Layering Pattern Detection</p>', unsafe_allow_html=True)
        min_layers = st.number_input("Min Layers", 2, 10, 3)
        if st.button("Run Layering Detection"):
            df = detect_layering_patterns(min_layers)
            if df.empty: st.info("No layering patterns found.")
            else:
                _metric_card("Detections", f"{len(df)}", "Path patterns")
                _render_dark_table(df)

    with subtabs[2]:
        st.markdown('<p class="section-header">Funnel Account Detection</p>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1: min_in = st.number_input("Min Inflow", 5, 50, 10)
        with col2: max_out = st.number_input("Max Outflow", 1, 10, 3)
        if st.button("Run Funnel Detection"):
            df = detect_funnel_accounts(min_in, max_out)
            if df.empty: st.info("No funnel accounts found.")
            else:
                _metric_card("Detections", f"{len(df)}", "High suspicion nodes")
                _render_dark_table(df)

    with subtabs[3]:
        st.markdown('<p class="section-header">Shortest Transaction Path</p>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: start_acc = st.text_input("Start Account ID")
        with c2: end_acc = st.text_input("End Account ID")
        if st.button("Find Path"):
            if start_acc and end_acc:
                res = find_shortest_path(start_acc, end_acc)
                if "error" in res: st.error(res["error"])
                elif not res["path"]: st.info("No path exists between these accounts.")
                else:
                    st.success(f"Path found: {len(res['path'])-1} hops")
                    st.write(res["path"])
            else: st.warning("Please enter both account IDs.")


def render():
    """Main render function for the Network analysis page."""
    st.markdown('<p class="page-title">Network Analysis</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Graph-based suspicious relationship and fund flow analysis</p>', unsafe_allow_html=True)

    tabs = st.tabs(["Institution Network", "Fraud Account Network", "Account Explorer", "Fraud Flow", "AML Patterns"])

    with tabs[0]: _render_tab_bank_network()
    with tabs[1]: _render_tab_fraud_account_network()
    with tabs[2]: _render_tab_account_explorer()
    with tabs[3]: _render_tab_fraud_flow()
    with tabs[4]: _render_tab_aml_patterns()
