import streamlit as st
import plotly.graph_objects as go
import networkx as nx
import numpy as np

from src.features.network import (
    get_bank_network,
    get_fraud_account_network,
    get_account_ego_network,
    get_fraud_accounts,
    get_bank_network_stats,
    build_bank_graph,
    build_account_graph,
)


def _plot_network(G, title, node_color_attr=None, edge_color_attr=None, center_node=None):
    """NetworkX 그래프를 Plotly로 시각화한다."""
    if len(G.nodes()) == 0:
        st.warning("표시할 네트워크 데이터가 없습니다.")
        return

    pos = nx.spring_layout(G, k=2 / np.sqrt(max(len(G.nodes()), 1)), seed=42, iterations=50)

    # 엣지
    edge_x, edge_y = [], []
    edge_colors = []
    for u, v, data in G.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
        if edge_color_attr and edge_color_attr in data:
            edge_colors.append(data[edge_color_attr])

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=0.8, color="#AAAAAA"),
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

        node_text.append(f"노드: {node}<br>연결: {degree}<br>입금: {in_w:,}<br>출금: {out_w:,}<br>이상(수신): {fraud_in:,}<br>이상(발신): {fraud_out:,}")
        node_sizes.append(max(8, min(40, 5 + degree * 1.5)))

        if center_node and node == center_node:
            node_colors.append("#E15759")
        elif fraud_in + fraud_out > 0:
            node_colors.append("#F28E2B")
        else:
            node_colors.append("#4E79A7")

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=node_sizes, color=node_colors, line=dict(width=1, color="#FFFFFF")),
        text=[n if len(str(n)) <= 5 else "" for n in G.nodes()],
        textposition="top center", textfont=dict(size=9),
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


def render():
    st.title("네트워크 분석 대시보드")

    # ------------------------------------------------------------------
    # 탭 구성
    # ------------------------------------------------------------------
    tab1, tab2, tab3 = st.tabs(["금융회사 네트워크", "이상거래 계좌 네트워크", "계좌 탐색"])

    # --- 탭1: 금융회사 간 네트워크 ---
    with tab1:
        stats = get_bank_network_stats()
        row = stats.iloc[0]

        col1, col2, col3 = st.columns(3)
        col1.metric("출금 금융회사", f"{int(row['출금금융회사수'])}개")
        col2.metric("입금 금융회사", f"{int(row['입금금융회사수'])}개")
        col3.metric("금융회사 간 연결", f"{int(row['연결수']):,}개")

        bank_df = get_bank_network()
        bank_G = build_bank_graph(bank_df)

        # 이상거래가 있는 엣지만 필터
        fraud_filter = st.checkbox("이상거래 포함 연결만 표시", value=True, key="bank_fraud")
        if fraud_filter:
            filtered = [(u, v) for u, v, d in bank_G.edges(data=True) if d.get("fraud", 0) > 0]
            bank_G_show = bank_G.edge_subgraph(filtered).copy()
        else:
            bank_G_show = bank_G

        _plot_network(bank_G_show, f"금융회사 간 거래 네트워크 ({len(bank_G_show.nodes())}개 노드, {len(bank_G_show.edges())}개 연결)")

        # 주요 통계 테이블
        with st.expander("금융회사 네트워크 상세 통계"):
            degree_df = bank_df.groupby("source").agg(
                출금건수=("총거래", "sum"), 이상거래=("이상거래", "sum")
            ).reset_index().sort_values("이상거래", ascending=False).head(15)
            degree_df.columns = ["금융회사", "출금 건수", "이상거래 건수"]
            st.dataframe(degree_df, use_container_width=True, hide_index=True)

    # --- 탭2: 이상거래 계좌 네트워크 ---
    with tab2:
        limit = st.slider("표시할 이상거래 연결 수", 100, 1000, 300, 50, key="fraud_limit")
        fraud_df = get_fraud_account_network(limit=limit)

        if len(fraud_df) > 0:
            fraud_G = build_account_graph(fraud_df)

            col1, col2, col3 = st.columns(3)
            col1.metric("이상거래 계좌 수", f"{len(fraud_G.nodes()):,}")
            col2.metric("이상거래 연결 수", f"{len(fraud_G.edges()):,}")
            col3.metric("평균 연결 수", f"{sum(dict(fraud_G.degree()).values()) / max(len(fraud_G.nodes()), 1):.1f}")

            _plot_network(fraud_G, f"이상거래 계좌 네트워크 (상위 {limit}개 연결)")

            with st.expander("이상거래 유형별 연결"):
                st.dataframe(
                    fraud_df[["source", "target", "거래횟수", "총금액", "이상거래유형", "이상거래설명"]]
                    .head(50),
                    use_container_width=True, hide_index=True,
                )
        else:
            st.info("이상거래 네트워크 데이터가 없습니다.")

    # --- 탭3: 특정 계좌 탐색 ---
    with tab3:
        st.markdown("특정 계좌의 거래 네트워크를 탐색합니다.")

        fraud_accounts = get_fraud_accounts()
        account_list = fraud_accounts["계좌"].tolist()

        selected = st.selectbox(
            "이상거래 관련 계좌 선택",
            options=account_list[:100],
            format_func=lambda x: f"{x}",
            key="account_select",
        )

        hops = st.radio("탐색 범위", [1, 2], horizontal=True, key="hop_select")

        if selected:
            ego_df = get_account_ego_network(selected, hops=hops)

            if len(ego_df) > 0:
                ego_G = build_account_graph(ego_df)

                col1, col2 = st.columns(2)
                col1.metric("연결된 계좌 수", f"{len(ego_G.nodes()) - 1}")
                col2.metric("거래 연결 수", f"{len(ego_G.edges())}")

                _plot_network(ego_G, f"계좌 {selected}의 {hops}-hop 네트워크", center_node=str(selected))

                with st.expander("거래 상세"):
                    st.dataframe(ego_df, use_container_width=True, hide_index=True)
            else:
                st.warning("해당 계좌의 거래 데이터가 없습니다.")
