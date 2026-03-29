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
    """HTML metric-card를 렌더링한다."""
    value_class = "value white" if white else "value"
    st.markdown(f"""<div class="metric-card">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
        <div class="sub">{sub}</div>
    </div>""", unsafe_allow_html=True)


def _plot_network(G, title, node_color_attr=None, edge_color_attr=None,
                  center_node=None, community_map=None):
    """NetworkX 그래프를 Plotly로 시각화한다.

    Parameters
    ----------
    community_map : dict, optional
        노드 -> 커뮤니티 인덱스 매핑. 지정 시 커뮤니티별 색상으로 노드를 표시한다.
    """
    if len(G.nodes()) == 0:
        st.warning("No network data to display.")
        return

    pos = nx.spring_layout(G, k=2 / np.sqrt(max(len(G.nodes()), 1)), seed=42, iterations=50)

    # 엣지
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

    # 노드
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

        # 색상 결정: community_map > center_node > fraud > default
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
    st.plotly_chart(fig, width='stretch')


def _render_dark_table(df, max_rows=20):
    """DataFrame을 dark-table HTML로 렌더링한다."""
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
# 탭1: 금융회사 네트워크
# ------------------------------------------------------------------

def _render_tab_bank_network():
    """금융회사 네트워크 탭을 렌더링한다."""
    with st.spinner("Loading data..."):
        stats = get_bank_network_stats()
        if stats.empty:
            st.warning("Unable to retrieve institution network statistics.")
            return
        row = stats.iloc[0]

        bank_df = get_bank_network()
        bank_G = build_bank_graph(bank_df)

        # 확장 네트워크 통계
        ext_stats = get_extended_network_stats(bank_G)

    # 메트릭 카드 (HTML .metric-card)
    st.markdown('<p class="section-header">Network Summary</p>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("Sender Institutions", f"{int(row['출금금융회사수'])}", "Sending institutions")
    with c2:
        _metric_card("Receiver Institutions", f"{int(row['입금금융회사수'])}", "Receiving institutions")
    with c3:
        _metric_card("Inter-Institution Links", f"{int(row['연결수']):,}", "Unique transaction paths")
    c4, c5, c6 = st.columns(3)
    with c4:
        _metric_card("Network Density", f"{ext_stats['밀도']:.4f}", "0 (sparse) ~ 1 (fully connected)")
    with c5:
        _metric_card("Avg Clustering", f"{ext_stats['평균클러스터링계수']:.4f}", "Clustering coefficient")
    with c6:
        _metric_card("Hub Institution", f"{ext_stats['허브노드']}", f"Connections: {ext_stats['허브연결수']}")

    # 이상거래 필터 체크박스
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

    # 중심성 지표 분석
    st.markdown('<p class="section-header">Centrality Analysis (Top 10)</p>', unsafe_allow_html=True)

    with st.spinner("Computing centrality metrics..."):
        centrality_df = compute_centrality_metrics(bank_G)

    if len(centrality_df) > 0:
        top10 = centrality_df.head(10)

        # 중심성 지표 테이블 (dark-table)
        display_cols = top10[["노드", "degree", "betweenness", "closeness", "eigenvector"]].copy()
        display_cols.columns = ["Institution", "Degree", "Betweenness", "Closeness", "Eigenvector"]
        _render_dark_table(display_cols, max_rows=10)

        # 중심성 지표 Bar 차트
        st.markdown("", unsafe_allow_html=True)  # spacer

        col_left, col_right = st.columns(2)

        with col_left:
            fig_degree = go.Figure(go.Bar(
                x=top10["노드"],
                y=top10["degree"],
                marker_color=MINT_COLOR,
                text=top10["degree"],
                textposition="outside",
                textfont=dict(color="#E0E0E0", size=11),
            ))
            fig_degree.update_layout(
                title=dict(text="Degree (Connections)", font=dict(color="#C0C4D0", size=14)),
            )
            _apply_dark(fig_degree, height=350)
            fig_degree.update_xaxes(title_text="Institution", title_font=dict(color="#8B8FA3", size=11))
            fig_degree.update_yaxes(title_text="Degree", title_font=dict(color="#8B8FA3", size=11))
            st.plotly_chart(fig_degree, width='stretch')

        with col_right:
            fig_between = go.Figure(go.Bar(
                x=top10["노드"],
                y=top10["betweenness"],
                marker_color=ACCENT_COLOR,
                text=[f"{v:.4f}" for v in top10["betweenness"]],
                textposition="outside",
                textfont=dict(color="#E0E0E0", size=11),
            ))
            fig_between.update_layout(
                title=dict(text="Betweenness Centrality", font=dict(color="#C0C4D0", size=14)),
            )
            _apply_dark(fig_between, height=350)
            fig_between.update_xaxes(title_text="Institution", title_font=dict(color="#8B8FA3", size=11))
            fig_between.update_yaxes(title_text="Betweenness", title_font=dict(color="#8B8FA3", size=11))
            st.plotly_chart(fig_between, width='stretch')

    else:
        st.info("No nodes available for centrality computation.")

    # 금융회사 네트워크 상세 통계 테이블
    with st.expander("Institution Network Detailed Statistics"):
        degree_df = bank_df.groupby("source").agg(
            출금건수=("총거래", "sum"), 이상거래=("이상거래", "sum")
        ).reset_index().sort_values("이상거래", ascending=False).head(15)
        degree_df.columns = ["Institution", "Outflow Count", "Fraud Count"]
        _render_dark_table(degree_df, max_rows=15)


# ------------------------------------------------------------------
# 탭2: 이상거래 계좌 네트워크
# ------------------------------------------------------------------

def _render_tab_fraud_account_network():
    """이상거래 계좌 네트워크 탭을 렌더링한다."""
    limit = st.slider("Number of fraud links to display", 100, 1000, 300, 50, key="fraud_limit")
    with st.spinner("Loading fraud network..."):
        fraud_df = get_fraud_account_network(limit=limit)

    if len(fraud_df) == 0:
        st.info("No fraud network data available.")
        return

    fraud_G = build_account_graph(fraud_df)

    # 메트릭 카드 (HTML .metric-card)
    st.markdown('<p class="section-header">Fraud Account Network Summary</p>', unsafe_allow_html=True)
    avg_degree = sum(dict(fraud_G.degree()).values()) / max(len(fraud_G.nodes()), 1)

    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("Fraud Accounts", f"{len(fraud_G.nodes()):,}", "Unique fraud-related accounts")
    with c2:
        _metric_card("Fraud Links", f"{len(fraud_G.edges()):,}", "Transaction edges")
    with c3:
        _metric_card("Avg Connections", f"{avg_degree:.1f}", "Per account average")

    # 커뮤니티 탐지
    st.markdown('<p class="section-header">Community Detection</p>', unsafe_allow_html=True)

    show_communities = st.checkbox("Color by community", value=True, key="show_community")

    community_map = None
    community_df = pd.DataFrame()

    if show_communities:
        with st.spinner("Detecting communities..."):
            community_df = detect_communities(fraud_G)

        if len(community_df) > 0:
            community_map = dict(zip(community_df["노드"], community_df["커뮤니티"]))
            n_communities = community_df["커뮤니티"].nunique()

            st.markdown(
                f'<p class="caption-text">탐지된 커뮤니티 수: '
                f'<span style="color:#4ECDC4; font-weight:700;">{n_communities}</span></p>',
                unsafe_allow_html=True,
            )

    _plot_network(
        fraud_G,
        f"Fraud Account Network (top {limit} links)",
        community_map=community_map,
    )

    # 커뮤니티별 통계 테이블
    if show_communities and len(community_df) > 0:
        st.markdown('<p class="section-header">Community Statistics</p>', unsafe_allow_html=True)

        # 커뮤니티별 노드 수와 이상거래 비율 계산
        # fraud_df에서 이상거래유형 매핑을 활용
        fraud_nodes = set()
        for _, row in fraud_df.iterrows():
            fraud_nodes.add(str(int(row["source"])))
            fraud_nodes.add(str(int(row["target"])))

        comm_stats_rows = []
        for comm_id in sorted(community_df["커뮤니티"].unique()):
            comm_nodes = community_df[community_df["커뮤니티"] == comm_id]["노드"].tolist()
            n_nodes = len(comm_nodes)

            # 커뮤니티 내부 엣지 수
            internal_edges = 0
            total_amount = 0
            for u, v, d in fraud_G.edges(data=True):
                if community_map.get(u) == comm_id and community_map.get(v) == comm_id:
                    internal_edges += 1
                    total_amount += d.get("amount", 0)

            comm_stats_rows.append({
                "커뮤니티": comm_id,
                "노드 수": n_nodes,
                "내부 연결 수": internal_edges,
                "내부 거래금액": int(total_amount),
            })

        comm_stats_df = pd.DataFrame(comm_stats_rows)
        if len(comm_stats_df) > 0:
            _render_dark_table(comm_stats_df, max_rows=20)

    # 이상거래 유형별 연결 상세
    with st.expander("Fraud Type Connections"):
        display_df = fraud_df[["source", "target", "거래횟수", "총금액", "이상거래유형", "이상거래설명"]].head(50)
        _render_dark_table(display_df, max_rows=50)


# ------------------------------------------------------------------
# 탭3: 계좌 탐색 (hop 확장 지원)
# ------------------------------------------------------------------

def _render_tab_account_explorer():
    """특정 계좌 탐색 탭을 렌더링한다."""
    st.markdown("Explore the transaction network of a specific account.")

    with st.spinner("Loading account list..."):
        fraud_accounts = get_fraud_accounts()
        account_list = fraud_accounts["계좌"].tolist()

    selected = st.selectbox(
        "Select fraud-related account",
        options=account_list[:100],
        format_func=lambda x: f"{x}",
        key="account_select",
    )

    hops = st.slider("Exploration range (hops)", 1, 5, 2, key="hop_select")

    # hops > 2 인 경우 Memgraph 필요 안내
    if hops > 2:
        memgraph_ok = graph_db.is_available()
        if not memgraph_ok:
            st.info(
                "3+ hop exploration requires Memgraph. "
                "Without Memgraph, DuckDB fallback supports up to 2 hops."
            )

    if selected:
        with st.spinner(f"Exploring {hops}-hop network for account {selected}..."):
            if hops > 2:
                ego_df = get_account_ego_network_deep(selected, hops=hops)
            else:
                ego_df = get_account_ego_network(selected, hops=hops)

        if len(ego_df) == 0:
            st.warning("No transaction data for this account.")
            return

        ego_G = build_account_graph(ego_df)

        c1, c2 = st.columns(2)
        with c1:
            _metric_card("Connected Accounts", f"{len(ego_G.nodes()) - 1}", f"Within {hops}-hop range")
        with c2:
            _metric_card("Transaction Links", f"{len(ego_G.edges())}", "Unique transaction paths")

        _plot_network(ego_G, f"계좌 {selected}의 {hops}-hop 네트워크", center_node=str(selected))

        with st.expander("Transaction Details"):
            _render_dark_table(ego_df, max_rows=50)


# ------------------------------------------------------------------
# 탭4: 이상거래 흐름
# ------------------------------------------------------------------

def _render_tab_fraud_flow():
    """금융회사 간 이상거래 흐름 매트릭스 탭을 렌더링한다."""
    st.markdown('<p class="section-header">Inter-Institution Fraud Flow</p>', unsafe_allow_html=True)

    with st.spinner("Loading fraud flow data..."):
        flow_df = get_fraud_flow_matrix()

    if len(flow_df) == 0:
        st.info("No fraud flow data available.")
        return

    # 요약 메트릭 카드
    total_fraud_count = int(flow_df["이상거래건수"].sum())
    total_fraud_amount = float(flow_df["이상거래금액"].sum())
    n_routes = len(flow_df)
    top_route = flow_df.iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("총 이상거래 건수", f"{total_fraud_count:,}", "금융회사 간 이상거래 합계")
    with c2:
        _metric_card("총 이상거래 금액", _format_amount(total_fraud_amount), "이상거래 금액 합산")
    with c3:
        _metric_card("이상거래 경로 수", f"{n_routes:,}", "출금 → 입금 고유 경로")
    with c4:
        _metric_card(
            "최다 이상거래 경로",
            f"{int(top_route['source'])} → {int(top_route['target'])}",
            f"{int(top_route['이상거래건수']):,}건",
        )

    # 라디오 버튼: 건수 vs 금액
    metric_choice = st.radio(
        "히트맵 표시 기준",
        ["이상거래건수", "이상거래금액"],
        horizontal=True,
        key="flow_metric",
    )

    # Pivot table for heatmap
    pivot = flow_df.pivot_table(
        index="source", columns="target",
        values=metric_choice, fill_value=0, aggfunc="sum",
    )

    # 라벨 생성
    x_labels = [f"금융회사 {int(c)}" for c in pivot.columns]
    y_labels = [f"금융회사 {int(r)}" for r in pivot.index]

    # 히트맵 값에 대한 텍스트 포맷
    if metric_choice == "이상거래금액":
        text_template = "%{z:,.0f}"
        hover_template = "출금: %{y}<br>입금: %{x}<br>금액: %{z:,.0f}원<extra></extra>"
    else:
        text_template = "%{z:,}"
        hover_template = "출금: %{y}<br>입금: %{x}<br>건수: %{z:,}<extra></extra>"

    fig_heatmap = go.Figure(go.Heatmap(
        z=pivot.values,
        x=x_labels,
        y=y_labels,
        colorscale=[[0, "#F5F7FA"], [0.5, "#6EE7B7"], [1, "#059669"]],
        hovertemplate=hover_template,
        texttemplate=text_template,
        textfont=dict(color="#E0E0E0", size=10),
    ))
    _apply_dark(fig_heatmap, height=500)
    fig_heatmap.update_layout(
        xaxis_title="입금 금융회사 (수신)",
        yaxis_title="출금 금융회사 (발신)",
        xaxis=dict(title_font=dict(color="#8B8FA3", size=11), side="bottom"),
        yaxis=dict(title_font=dict(color="#8B8FA3", size=11), autorange="reversed"),
    )
    st.plotly_chart(fig_heatmap, width='stretch')

    # 상위 이상거래 경로 테이블
    st.markdown('<p class="section-header">상위 이상거래 경로 (상위 20)</p>', unsafe_allow_html=True)
    top_routes = flow_df.head(20).copy()
    top_routes.columns = ["출금 금융회사", "입금 금융회사", "이상거래 건수", "이상거래 금액"]
    _render_dark_table(top_routes, max_rows=20)


def _format_amount(amount):
    """금액을 읽기 쉬운 한국어 형식으로 포맷한다."""
    amount = float(amount)
    if amount >= 1_0000_0000:
        return f"{amount / 1_0000_0000:,.1f}억"
    elif amount >= 1_0000:
        return f"{amount / 1_0000:,.0f}만"
    else:
        return f"{amount:,.0f}"


# ------------------------------------------------------------------
# 탭5: AML 패턴 탐지
# ------------------------------------------------------------------

def _render_memgraph_status():
    """Memgraph 연결 상태 배너를 표시한다."""
    available = graph_db.is_available()
    if available:
        st.markdown(
            f'<div class="memgraph-badge connected">'
            f'<span style="color:#4ECDC4; font-weight:700;">Memgraph 연결됨</span>'
            f'<span style="color:#9EA3B8; margin-left:12px; font-size:12px;">'
            f'bolt://{config.MEMGRAPH_HOST}:{config.MEMGRAPH_PORT}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="memgraph-badge disconnected">'
            '<span style="color:#E15759; font-weight:700;">Memgraph 미실행</span>'
            '<span style="color:#9EA3B8; margin-left:12px; font-size:12px;">'
            'AML 패턴 탐지에는 Docker로 Memgraph를 실행하세요.</span>'
            '</div>',
            unsafe_allow_html=True,
        )
    return available


def _plot_ring_graph(ring_accounts, amounts=None):
    """순환거래 경로를 원형 그래프로 시각화한다."""
    if not ring_accounts or len(ring_accounts) < 3:
        return

    # 마지막 노드가 첫 노드와 같으면 (순환) 표시용으로 제거
    display_nodes = ring_accounts
    if display_nodes[0] == display_nodes[-1]:
        display_nodes = display_nodes[:-1]

    n = len(display_nodes)
    # 원형 배치
    angles = [2 * np.pi * i / n for i in range(n)]
    node_x = [np.cos(a) for a in angles]
    node_y = [np.sin(a) for a in angles]

    # 엣지 (순환이므로 i -> i+1, 마지막 -> 첫번째)
    edge_x, edge_y = [], []
    for i in range(n):
        j = (i + 1) % n
        edge_x += [node_x[i], node_x[j], None]
        edge_y += [node_y[i], node_y[j], None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=2, color=LINE_COLOR),
        hoverinfo="none",
    )

    # 엣지 라벨 (금액 표시)
    edge_annotations = []
    if amounts and len(amounts) >= n:
        for i in range(n):
            j = (i + 1) % n
            mid_x = (node_x[i] + node_x[j]) / 2
            mid_y = (node_y[i] + node_y[j]) / 2
            edge_annotations.append(
                dict(
                    x=mid_x, y=mid_y,
                    text=f"{int(amounts[i]):,}",
                    showarrow=False,
                    font=dict(size=10, color=ACCENT_COLOR),
                )
            )

    # 노드 라벨
    node_labels = [str(a) for a in display_nodes]
    node_hover = [f"계좌: {a}" for a in display_nodes]

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=30, color=LINE_COLOR, line=dict(width=2, color="#FFFFFF")),
        text=node_labels,
        textposition="top center",
        textfont=dict(size=10, color="#E0E0E0"),
        hovertext=node_hover,
        hoverinfo="text",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title=dict(text=f"순환거래 경로 ({n}개 계좌)", font=dict(color="#C0C4D0", size=14)),
        showlegend=False, height=450,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, scaleanchor="x"),
        margin=dict(t=40, b=20, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#C0C4D0"),
        annotations=edge_annotations,
    )
    st.plotly_chart(fig, width='stretch')


def _plot_path_graph(path, amounts=None, dates=None):
    """최단경로를 선형 그래프로 시각화한다."""
    if not path or len(path) < 2:
        return

    n = len(path)
    # 선형 배치 (좌->우)
    node_x = list(range(n))
    node_y = [0] * n

    # 엣지
    edge_x, edge_y = [], []
    for i in range(n - 1):
        edge_x += [node_x[i], node_x[i + 1], None]
        edge_y += [0, 0, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=3, color=MINT_COLOR),
        hoverinfo="none",
    )

    # 엣지 중간에 금액/날짜 표시
    edge_annotations = []
    for i in range(n - 1):
        mid_x = (node_x[i] + node_x[i + 1]) / 2
        parts = []
        if amounts and i < len(amounts):
            parts.append(f"{int(amounts[i]):,}원")
        if dates and i < len(dates):
            parts.append(f"({dates[i]})")
        if parts:
            edge_annotations.append(
                dict(
                    x=mid_x, y=0.15,
                    text="<br>".join(parts),
                    showarrow=False,
                    font=dict(size=10, color=ACCENT_COLOR),
                )
            )

    # 노드
    node_labels = [str(a) for a in path]
    node_colors_list = [BAR_COLOR] * n
    node_colors_list[0] = MINT_COLOR  # 출발
    node_colors_list[-1] = LINE_COLOR  # 도착

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=35, color=node_colors_list, line=dict(width=2, color="#FFFFFF")),
        text=node_labels,
        textposition="bottom center",
        textfont=dict(size=10, color="#E0E0E0"),
        hovertext=[f"계좌: {a}" for a in path],
        hoverinfo="text",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title=dict(text=f"최단경로 ({n - 1} hop)", font=dict(color="#C0C4D0", size=14)),
        showlegend=False, height=300,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.5, 0.5]),
        margin=dict(t=40, b=40, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#C0C4D0"),
        annotations=edge_annotations,
    )
    st.plotly_chart(fig, width='stretch')


def _render_sub_ring():
    """서브탭: 순환거래 탐지."""
    st.markdown('<p class="section-header">순환거래 탐지</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="caption-text">'
        'A -> B -> C -> ... -> A 형태의 순환 자금 이동 패턴을 탐지합니다.'
        '</p>',
        unsafe_allow_html=True,
    )

    with st.expander("탐지 파라미터", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            min_len = st.number_input("최소 순환 길이", min_value=3, max_value=6, value=3, key="ring_min")
        with c2:
            max_len = st.number_input("최대 순환 길이", min_value=3, max_value=10, value=6, key="ring_max")
        with c3:
            min_amount = st.number_input("최소 거래금액", min_value=0, value=0, step=100000, key="ring_amt")
        with c4:
            limit = st.number_input("최대 결과 수", min_value=10, max_value=500, value=100, key="ring_limit")

    if st.button("탐지 실행", key="ring_btn"):
        with st.spinner("순환거래 패턴 탐지 중..."):
            result_df = detect_ring_transactions(
                min_len=min_len, max_len=max_len,
                min_amount=min_amount, limit=limit,
            )

        if len(result_df) == 0:
            st.info("탐지된 순환거래 패턴이 없습니다.")
            return

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            _metric_card("탐지 건수", f"{len(result_df):,}", "순환거래 패턴 수")
        with mc2:
            _metric_card("최대 순환 크기", f"{int(result_df['ring_size'].max())}", "최다 계좌 참여 순환")
        with mc3:
            _metric_card("최대 순환 금액", _format_amount(result_df["total_amount"].max()), "단일 순환 최대 금액")

        # 첫 번째 결과 시각화
        first = result_df.iloc[0]
        ring_accounts = first["ring_accounts"]
        # ring_accounts 리스트에서 순환 시각화
        _plot_ring_graph(ring_accounts)

        # 결과 테이블
        st.markdown('<p class="section-header">탐지 결과</p>', unsafe_allow_html=True)
        display_df = result_df[["ring_size", "total_amount"]].copy()
        display_df.columns = ["순환 크기", "총 거래금액"]
        _render_dark_table(display_df, max_rows=20)

        with st.expander("전체 결과 상세"):
            _render_dark_table(result_df, max_rows=50)


def _render_sub_layering():
    """서브탭: 레이어링 패턴 탐지."""
    st.markdown('<p class="section-header">레이어링 패턴 탐지</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="caption-text">'
        '출발 계좌에서 중개 계좌를 거쳐 도착 계좌에 이르는 다단계 자금 이동 패턴을 탐지합니다.'
        '</p>',
        unsafe_allow_html=True,
    )

    with st.expander("탐지 파라미터", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            min_layers = st.number_input("최소 레이어 수", min_value=2, max_value=10, value=3, key="layer_min")
        with c2:
            limit = st.number_input("최대 결과 수", min_value=10, max_value=500, value=100, key="layer_limit")

    if st.button("탐지 실행", key="layer_btn"):
        with st.spinner("레이어링 패턴 탐지 중..."):
            result_df = detect_layering_patterns(min_layers=min_layers, limit=limit)

        if len(result_df) == 0:
            st.info("탐지된 레이어링 패턴이 없습니다.")
            return

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            _metric_card("탐지 건수", f"{len(result_df):,}", "레이어링 패턴 수")
        with mc2:
            _metric_card("최대 레이어 수", f"{int(result_df['layers'].max())}", "최다 중간 단계")
        with mc3:
            _metric_card("최대 금액", _format_amount(result_df["total_amount"].max()), "단일 경로 최대 금액")

        # 결과 테이블
        st.markdown('<p class="section-header">탐지 결과</p>', unsafe_allow_html=True)
        display_df = result_df[["source_account", "destination_account", "layers", "total_amount"]].copy()
        display_df.columns = ["출발 계좌", "도착 계좌", "레이어 수", "총 거래금액"]
        _render_dark_table(display_df, max_rows=20)

        with st.expander("전체 결과 상세"):
            _render_dark_table(result_df, max_rows=50)


def _render_sub_funnel():
    """서브탭: 대포통장(funnel) 패턴 탐지."""
    st.markdown('<p class="section-header">대포통장 패턴 탐지</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="caption-text">'
        '다수의 계좌로부터 입금을 받고 소수의 계좌로 출금하는 의심 계좌를 탐지합니다.'
        '</p>',
        unsafe_allow_html=True,
    )

    with st.expander("탐지 파라미터", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            min_inflow = st.number_input("최소 입금 계좌 수", min_value=5, max_value=50, value=10, key="funnel_in")
        with c2:
            max_outflow = st.number_input("최대 출금 계좌 수", min_value=1, max_value=10, value=3, key="funnel_out")
        with c3:
            limit = st.number_input("최대 결과 수", min_value=10, max_value=500, value=100, key="funnel_limit")

    if st.button("탐지 실행", key="funnel_btn"):
        with st.spinner("대포통장 패턴 탐지 중..."):
            result_df = detect_funnel_accounts(
                min_inflow=min_inflow, max_outflow=max_outflow, limit=limit,
            )

        if len(result_df) == 0:
            st.info("탐지된 대포통장 의심 계좌가 없습니다.")
            return

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            _metric_card("의심 계좌 수", f"{len(result_df):,}", "대포통장 의심 계좌")
        with mc2:
            _metric_card("최고 Funnel 비율", f"{result_df['funnel_ratio'].max():.2f}", "입금 계좌 수 / 출금 계좌 수")
        with mc3:
            _metric_card("최대 입금 건수", f"{int(result_df['inflow_count'].max()):,}", "단일 계좌 최다 입금")

        # 결과 테이블
        st.markdown('<p class="section-header">탐지 결과</p>', unsafe_allow_html=True)
        display_df = result_df[[
            "account_id", "inflow_count", "inflow_amount",
            "outflow_count", "outflow_amount", "funnel_ratio",
        ]].copy()
        display_df.columns = [
            "계좌 ID", "입금 건수", "입금 금액",
            "출금 건수", "출금 금액", "Funnel 비율",
        ]
        _render_dark_table(display_df, max_rows=20)


def _render_sub_shortest_path():
    """서브탭: 최단경로 탐색."""
    st.markdown('<p class="section-header">최단경로 탐색</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="caption-text">'
        '두 계좌 간 최단 거래 경로를 탐색합니다.'
        '</p>',
        unsafe_allow_html=True,
    )

    with st.expander("계좌 입력", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            account_a = st.number_input("출발 계좌 ID", min_value=0, value=0, step=1, key="path_a")
        with c2:
            account_b = st.number_input("도착 계좌 ID", min_value=0, value=0, step=1, key="path_b")

    if st.button("경로 탐색", key="path_btn"):
        if account_a == 0 or account_b == 0:
            st.warning("출발 계좌와 도착 계좌를 모두 입력하세요.")
            return
        if account_a == account_b:
            st.warning("출발 계좌와 도착 계좌가 동일합니다.")
            return

        with st.spinner(f"계좌 {account_a} -> {account_b} 최단경로 탐색 중..."):
            result = find_shortest_path(account_a, account_b)

        if "error" in result:
            st.error(result["error"])
            return

        path = result.get("path", [])
        hops = result.get("hops", 0)
        amounts = result.get("amounts", [])
        dates = result.get("dates", [])

        if not path:
            st.info("두 계좌 간 경로가 존재하지 않습니다.")
            return

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            _metric_card("경로 길이", f"{hops} hop", "출발~도착 최단 거리")
        with mc2:
            total_amt = sum(amounts) if amounts else 0
            _metric_card("총 경유 금액", _format_amount(total_amt), "경로 상 거래금액 합계")
        with mc3:
            _metric_card("경유 계좌 수", f"{max(0, len(path) - 2)}", "중간 경유 계좌")

        # 경로 시각화
        _plot_path_graph(path, amounts=amounts, dates=dates)

        # 경로 상세 테이블
        if len(path) >= 2:
            path_rows = []
            for i in range(len(path) - 1):
                row_data = {"구간": f"{path[i]} -> {path[i+1]}"}
                if amounts and i < len(amounts):
                    row_data["거래금액"] = int(amounts[i])
                if dates and i < len(dates):
                    row_data["거래일자"] = dates[i]
                path_rows.append(row_data)
            path_df = pd.DataFrame(path_rows)
            st.markdown('<p class="section-header">구간별 상세</p>', unsafe_allow_html=True)
            _render_dark_table(path_df, max_rows=20)


def _render_sub_temporal():
    """서브탭: 시간대별 네트워크."""
    st.markdown('<p class="section-header">시간대별 네트워크</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="caption-text">'
        '지정된 기간 내 거래 네트워크를 추출합니다.'
        '</p>',
        unsafe_allow_html=True,
    )

    with st.expander("조회 조건", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            start_date = st.number_input(
                "시작일 (YYYYMMDD)", min_value=20210101, max_value=20241231,
                value=20210101, step=1, key="temp_start",
            )
        with c2:
            end_date = st.number_input(
                "종료일 (YYYYMMDD)", min_value=20210101, max_value=20241231,
                value=20241231, step=1, key="temp_end",
            )
        with c3:
            fraud_only = st.checkbox("이상거래만 표시", value=True, key="temp_fraud")

    if st.button("조회", key="temp_btn"):
        if start_date > end_date:
            st.warning("시작일이 종료일보다 클 수 없습니다.")
            return

        with st.spinner("시간대별 네트워크 조회 중..."):
            result_df = get_temporal_network(start_date, end_date, fraud_only=fraud_only)

        if len(result_df) == 0:
            st.info("해당 기간의 네트워크 데이터가 없습니다.")
            return

        # 그래프 구축 및 시각화
        temp_G = build_account_graph(result_df)

        mc1, mc2, mc3, mc4 = st.columns(4)
        with mc1:
            _metric_card("노드 수", f"{len(temp_G.nodes()):,}", "기간 내 계좌 수")
        with mc2:
            _metric_card("엣지 수", f"{len(temp_G.edges()):,}", "거래 연결 수")
        with mc3:
            total_txn = int(result_df["거래횟수"].sum()) if "거래횟수" in result_df.columns else 0
            _metric_card("총 거래 건수", f"{total_txn:,}", "기간 내 거래 합계")
        with mc4:
            total_amt = float(result_df["총금액"].sum()) if "총금액" in result_df.columns else 0
            _metric_card("총 거래 금액", _format_amount(total_amt), "기간 내 금액 합계")

        # 네트워크 시각화
        fraud_label = "이상거래" if fraud_only else "전체 거래"
        _plot_network(
            temp_G,
            f"시간대별 네트워크: {start_date}~{end_date} ({fraud_label})",
        )

        with st.expander("거래 상세"):
            _render_dark_table(result_df, max_rows=50)


def _render_sub_risk_score():
    """서브탭: 위험도 분석."""
    st.markdown('<p class="section-header">위험도 분석</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="caption-text">'
        '그래프 기반 복합 위험 점수를 산출합니다. '
        '직접 이상거래 비율, 이웃 이상거래 비율, 사이클 참여, 입출금 집중도를 종합합니다.'
        '</p>',
        unsafe_allow_html=True,
    )

    # 계좌 선택: selectbox 또는 직접 입력
    input_mode = st.radio("입력 방식", ["이상거래 계좌 선택", "계좌 번호 직접 입력"], horizontal=True, key="risk_mode")

    if input_mode == "이상거래 계좌 선택":
        fraud_accounts = get_fraud_accounts()
        account_list = fraud_accounts["계좌"].tolist()
        target_account = st.selectbox(
            "분석 대상 계좌",
            options=account_list[:100],
            key="risk_select",
        )
    else:
        target_account = st.number_input("계좌 번호", min_value=0, value=0, step=1, key="risk_input")

    if st.button("분석", key="risk_btn"):
        if target_account == 0:
            st.warning("분석 대상 계좌를 선택하세요.")
            return

        with st.spinner(f"계좌 {target_account} 위험도 분석 중..."):
            result = compute_risk_score(target_account)

        if "error" in result:
            st.error(result["error"])
            return

        risk_score = result["risk_score"]
        components = result.get("components", {})

        # 위험 점수 게이지 차트
        # 색상을 위험도에 따라 변경
        if risk_score >= 0.7:
            gauge_bar_color = LINE_COLOR  # red
        elif risk_score >= 0.4:
            gauge_bar_color = ACCENT_COLOR  # orange
        else:
            gauge_bar_color = MINT_COLOR  # mint/green

        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=risk_score,
            number=dict(
                font=dict(size=48, color="#E0E0E0"),
                valueformat=".4f",
            ),
            gauge=dict(
                axis=dict(range=[0, 1], tickcolor="#8B8FA3", tickfont=dict(color="#8B8FA3")),
                bar=dict(color=gauge_bar_color),
                bgcolor="#1A1F2E",
                bordercolor="#2A2F3E",
                steps=[
                    dict(range=[0, 0.3], color="#1A2E28"),
                    dict(range=[0.3, 0.7], color="#2E2A1A"),
                    dict(range=[0.7, 1.0], color="#2E1A1A"),
                ],
                threshold=dict(
                    line=dict(color="#FFFFFF", width=2),
                    thickness=0.8,
                    value=risk_score,
                ),
            ),
            title=dict(
                text=f"계좌 {target_account} 위험 점수",
                font=dict(color="#C0C4D0", size=16),
            ),
        ))
        fig_gauge.update_layout(
            height=320,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#C0C4D0"),
            margin=dict(t=60, b=20, l=30, r=30),
        )
        st.plotly_chart(fig_gauge, width='stretch')

        # 구성 요소별 점수 Bar 차트
        if components:
            comp_names = {
                "fraud_ratio": "직접 이상거래 비율 (x0.4)",
                "neighbor_fraud_ratio": "이웃 이상거래 비율 (x0.3)",
                "cycle_score": "사이클 참여 점수 (x0.2)",
                "concentration_score": "입출금 집중도 (x0.1)",
            }
            comp_keys = ["fraud_ratio", "neighbor_fraud_ratio", "cycle_score", "concentration_score"]
            comp_labels = [comp_names[k] for k in comp_keys]
            comp_values = [components.get(k, 0) for k in comp_keys]
            comp_weights = [0.4, 0.3, 0.2, 0.1]
            comp_weighted = [v * w for v, w in zip(comp_values, comp_weights)]

            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                x=comp_labels,
                y=comp_values,
                name="원시 점수",
                marker_color=BAR_COLOR,
                text=[f"{v:.4f}" for v in comp_values],
                textposition="outside",
                textfont=dict(color="#E0E0E0", size=11),
            ))
            fig_bar.add_trace(go.Bar(
                x=comp_labels,
                y=comp_weighted,
                name="가중 기여도",
                marker_color=MINT_COLOR,
                text=[f"{v:.4f}" for v in comp_weighted],
                textposition="outside",
                textfont=dict(color="#E0E0E0", size=11),
            ))
            fig_bar.update_layout(
                barmode="group",
                title=dict(text="위험 점수 구성 요소", font=dict(color="#C0C4D0", size=14)),
            )
            _apply_dark(fig_bar, height=380)
            fig_bar.update_xaxes(title_text="", tickangle=-15)
            fig_bar.update_yaxes(title_text="점수", title_font=dict(color="#8B8FA3", size=11))
            st.plotly_chart(fig_bar, width='stretch')

            # 상세 수치 테이블
            detail_rows = []
            for k, lbl in comp_names.items():
                detail_rows.append({
                    "구성 요소": lbl,
                    "원시 점수": round(components.get(k, 0), 4),
                    "가중치": comp_weights[comp_keys.index(k)],
                    "가중 기여도": round(components.get(k, 0) * comp_weights[comp_keys.index(k)], 4),
                })
            detail_df = pd.DataFrame(detail_rows)
            with st.expander("상세 점수 테이블"):
                _render_dark_table(detail_df, max_rows=10)


def _render_tab_aml_patterns():
    """AML 패턴 탐지 탭을 렌더링한다."""
    # Memgraph 연결 상태 표시
    memgraph_available = _render_memgraph_status()

    # 6개 서브탭
    sub1, sub2, sub3, sub4, sub5, sub6 = st.tabs([
        "순환거래",
        "레이어링",
        "대포통장",
        "최단경로",
        "시간대별",
        "위험도",
    ])

    with sub1:
        _render_sub_ring()

    with sub2:
        _render_sub_layering()

    with sub3:
        _render_sub_funnel()

    with sub4:
        _render_sub_shortest_path()

    with sub5:
        _render_sub_temporal()

    with sub6:
        _render_sub_risk_score()


# ------------------------------------------------------------------
# 메인 렌더 함수
# ------------------------------------------------------------------

def render():
    st.markdown('<p class="page-title">네트워크 분석 대시보드</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">금융회사·계좌 간 거래 그래프 분석 및 AML 패턴 탐지</p>', unsafe_allow_html=True)

    # 5개 탭 구성 (선택된 탭만 쿼리 실행하여 지연 로딩)
    tab_names = [
        "금융회사 네트워크",
        "이상거래 계좌 네트워크",
        "계좌 탐색",
        "이상거래 흐름",
        "AML 패턴 탐지",
    ]
    selected_tab = st.radio(
        "분석 유형",
        tab_names,
        horizontal=True,
        key="network_tab",
        label_visibility="collapsed",
    )
    st.markdown("<br>", unsafe_allow_html=True)

    if selected_tab == tab_names[0]:
        _render_tab_bank_network()
    elif selected_tab == tab_names[1]:
        _render_tab_fraud_account_network()
    elif selected_tab == tab_names[2]:
        _render_tab_account_explorer()
    elif selected_tab == tab_names[3]:
        _render_tab_fraud_flow()
    elif selected_tab == tab_names[4]:
        _render_tab_aml_patterns()
