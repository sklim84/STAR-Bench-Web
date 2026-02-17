import streamlit as st
import plotly.graph_objects as go
import networkx as nx
import numpy as np
import pandas as pd

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
)

# ------------------------------------------------------------------
# 다크 테마 상수
# ------------------------------------------------------------------
BAR_COLOR = "#4E79A7"
LINE_COLOR = "#E15759"
ACCENT_COLOR = "#F28E2B"
MINT_COLOR = "#4ECDC4"

# 커뮤니티 색상 팔레트 (최대 12개 커뮤니티 구분)
COMMUNITY_COLORS = [
    "#4ECDC4", "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC", "#D37295",
]


def _apply_dark(fig, height=380):
    """Plotly figure에 다크 테마를 적용한다."""
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#C0C4D0", size=12),
        legend=dict(
            orientation="h", y=1.12,
            font=dict(color="#8B8FA3", size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(t=30, b=30, l=10, r=10),
    )
    fig.update_xaxes(gridcolor="#1E2333", zerolinecolor="#1E2333",
                     tickfont=dict(color="#8B8FA3"))
    fig.update_yaxes(gridcolor="#1E2333", zerolinecolor="#1E2333",
                     tickfont=dict(color="#8B8FA3"))
    return fig


def _metric_card(label, value, sub=""):
    """HTML metric-card를 렌더링한다."""
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    st.markdown(f"""<div class="metric-card">
        <div class="label">{label}</div>
        <div class="value">{value}</div>
        {sub_html}
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
        st.warning("표시할 네트워크 데이터가 없습니다.")
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

        hover_parts = [f"노드: {node}", f"연결: {degree}", f"입금: {in_w:,}", f"출금: {out_w:,}"]
        if fraud_in + fraud_out > 0:
            hover_parts += [f"이상(수신): {fraud_in:,}", f"이상(발신): {fraud_out:,}"]
        if community_map and node in community_map:
            hover_parts.append(f"커뮤니티: {community_map[node]}")
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
    st.plotly_chart(fig, use_container_width=True)


def _render_dark_table(df, max_rows=20):
    """DataFrame을 dark-table HTML로 렌더링한다."""
    if len(df) == 0:
        st.info("표시할 데이터가 없습니다.")
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
    stats = get_bank_network_stats()
    if stats.empty:
        st.warning("금융회사 네트워크 통계를 조회할 수 없습니다.")
        return
    row = stats.iloc[0]

    bank_df = get_bank_network()
    bank_G = build_bank_graph(bank_df)

    # 확장 네트워크 통계
    ext_stats = get_extended_network_stats(bank_G)

    # 메트릭 카드 (HTML .metric-card)
    st.markdown('<p class="section-header">네트워크 요약</p>', unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _metric_card("출금 금융회사", f"{int(row['출금금융회사수'])}개")
    with c2:
        _metric_card("입금 금융회사", f"{int(row['입금금융회사수'])}개")
    with c3:
        _metric_card("금융회사 간 연결", f"{int(row['연결수']):,}개")
    with c4:
        _metric_card("네트워크 밀도", f"{ext_stats['밀도']:.4f}")
    with c5:
        _metric_card("평균 클러스터링", f"{ext_stats['평균클러스터링계수']:.4f}")
    with c6:
        _metric_card("허브 금융회사", f"{ext_stats['허브노드']}", sub=f"연결 수: {ext_stats['허브연결수']}")

    # 이상거래 필터 체크박스
    fraud_filter = st.checkbox("이상거래 포함 연결만 표시", value=True, key="bank_fraud")
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
        f"금융회사 간 거래 네트워크 ({len(bank_G_show.nodes())}개 노드, {len(bank_G_show.edges())}개 연결)",
    )

    # 중심성 지표 분석
    st.markdown('<p class="section-header">중심성 지표 분석 (상위 10)</p>', unsafe_allow_html=True)

    with st.spinner("중심성 지표 계산 중..."):
        centrality_df = compute_centrality_metrics(bank_G)

    if len(centrality_df) > 0:
        top10 = centrality_df.head(10)

        # 중심성 지표 테이블 (dark-table)
        display_cols = top10[["노드", "degree", "betweenness", "closeness", "eigenvector"]].copy()
        display_cols.columns = ["금융회사", "연결 수", "매개 중심성", "근접 중심성", "고유벡터 중심성"]
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
                title=dict(text="연결 수 (Degree)", font=dict(color="#C0C4D0", size=14)),
            )
            _apply_dark(fig_degree, height=350)
            fig_degree.update_xaxes(title_text="금융회사", title_font=dict(color="#8B8FA3", size=11))
            fig_degree.update_yaxes(title_text="연결 수", title_font=dict(color="#8B8FA3", size=11))
            st.plotly_chart(fig_degree, use_container_width=True)

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
                title=dict(text="매개 중심성 (Betweenness)", font=dict(color="#C0C4D0", size=14)),
            )
            _apply_dark(fig_between, height=350)
            fig_between.update_xaxes(title_text="금융회사", title_font=dict(color="#8B8FA3", size=11))
            fig_between.update_yaxes(title_text="매개 중심성", title_font=dict(color="#8B8FA3", size=11))
            st.plotly_chart(fig_between, use_container_width=True)

    else:
        st.info("중심성 지표를 계산할 노드가 없습니다.")

    # 금융회사 네트워크 상세 통계 테이블
    with st.expander("금융회사 네트워크 상세 통계"):
        degree_df = bank_df.groupby("source").agg(
            출금건수=("총거래", "sum"), 이상거래=("이상거래", "sum")
        ).reset_index().sort_values("이상거래", ascending=False).head(15)
        degree_df.columns = ["금융회사", "출금 건수", "이상거래 건수"]
        _render_dark_table(degree_df, max_rows=15)


# ------------------------------------------------------------------
# 탭2: 이상거래 계좌 네트워크
# ------------------------------------------------------------------

def _render_tab_fraud_account_network():
    """이상거래 계좌 네트워크 탭을 렌더링한다."""
    limit = st.slider("표시할 이상거래 연결 수", 100, 1000, 300, 50, key="fraud_limit")
    fraud_df = get_fraud_account_network(limit=limit)

    if len(fraud_df) == 0:
        st.info("이상거래 네트워크 데이터가 없습니다.")
        return

    fraud_G = build_account_graph(fraud_df)

    # 메트릭 카드 (HTML .metric-card)
    st.markdown('<p class="section-header">이상거래 계좌 네트워크 요약</p>', unsafe_allow_html=True)
    avg_degree = sum(dict(fraud_G.degree()).values()) / max(len(fraud_G.nodes()), 1)

    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("이상거래 계좌 수", f"{len(fraud_G.nodes()):,}")
    with c2:
        _metric_card("이상거래 연결 수", f"{len(fraud_G.edges()):,}")
    with c3:
        _metric_card("평균 연결 수", f"{avg_degree:.1f}")

    # 커뮤니티 탐지
    st.markdown('<p class="section-header">커뮤니티 탐지</p>', unsafe_allow_html=True)

    show_communities = st.checkbox("커뮤니티별 색상 구분 표시", value=True, key="show_community")

    community_map = None
    community_df = pd.DataFrame()

    if show_communities:
        with st.spinner("커뮤니티 탐지 중..."):
            community_df = detect_communities(fraud_G)

        if len(community_df) > 0:
            community_map = dict(zip(community_df["노드"], community_df["커뮤니티"]))
            n_communities = community_df["커뮤니티"].nunique()

            st.markdown(
                f'<p style="color:#8B8FA3; font-size:13px;">탐지된 커뮤니티 수: '
                f'<span style="color:#4ECDC4; font-weight:700;">{n_communities}</span></p>',
                unsafe_allow_html=True,
            )

    _plot_network(
        fraud_G,
        f"이상거래 계좌 네트워크 (상위 {limit}개 연결)",
        community_map=community_map,
    )

    # 커뮤니티별 통계 테이블
    if show_communities and len(community_df) > 0:
        st.markdown('<p class="section-header">커뮤니티별 통계</p>', unsafe_allow_html=True)

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
    with st.expander("이상거래 유형별 연결"):
        display_df = fraud_df[["source", "target", "거래횟수", "총금액", "이상거래유형", "이상거래설명"]].head(50)
        _render_dark_table(display_df, max_rows=50)


# ------------------------------------------------------------------
# 탭3: 계좌 탐색
# ------------------------------------------------------------------

def _render_tab_account_explorer():
    """특정 계좌 탐색 탭을 렌더링한다."""
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

        if len(ego_df) == 0:
            st.warning("해당 계좌의 거래 데이터가 없습니다.")
            return

        ego_G = build_account_graph(ego_df)

        c1, c2 = st.columns(2)
        with c1:
            _metric_card("연결된 계좌 수", f"{len(ego_G.nodes()) - 1}")
        with c2:
            _metric_card("거래 연결 수", f"{len(ego_G.edges())}")

        _plot_network(ego_G, f"계좌 {selected}의 {hops}-hop 네트워크", center_node=str(selected))

        with st.expander("거래 상세"):
            _render_dark_table(ego_df, max_rows=50)


# ------------------------------------------------------------------
# 탭4: 이상거래 흐름
# ------------------------------------------------------------------

def _render_tab_fraud_flow():
    """금융회사 간 이상거래 흐름 매트릭스 탭을 렌더링한다."""
    st.markdown('<p class="section-header">금융회사 간 이상거래 흐름</p>', unsafe_allow_html=True)

    with st.spinner("이상거래 흐름 데이터 조회 중..."):
        flow_df = get_fraud_flow_matrix()

    if len(flow_df) == 0:
        st.info("이상거래 흐름 데이터가 없습니다.")
        return

    # 요약 메트릭 카드
    total_fraud_count = int(flow_df["이상거래건수"].sum())
    total_fraud_amount = float(flow_df["이상거래금액"].sum())
    n_routes = len(flow_df)
    top_route = flow_df.iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("총 이상거래 건수", f"{total_fraud_count:,}")
    with c2:
        _metric_card("총 이상거래 금액", _format_amount(total_fraud_amount))
    with c3:
        _metric_card("이상거래 경로 수", f"{n_routes:,}")
    with c4:
        _metric_card(
            "최다 이상거래 경로",
            f"{int(top_route['source'])} -> {int(top_route['target'])}",
            sub=f"{int(top_route['이상거래건수']):,}건",
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
        colorscale=[[0, "#1A1F2E"], [0.5, "#2A6B65"], [1, "#4ECDC4"]],
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
    st.plotly_chart(fig_heatmap, use_container_width=True)

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
# 메인 렌더 함수
# ------------------------------------------------------------------

def render():
    st.markdown(
        '<p style="color:#FFFFFF; font-size:24px; font-weight:800; margin-bottom:4px;">'
        '네트워크 분석 대시보드</p>',
        unsafe_allow_html=True,
    )

    # 4개 탭 구성
    tab1, tab2, tab3, tab4 = st.tabs([
        "금융회사 네트워크",
        "이상거래 계좌 네트워크",
        "계좌 탐색",
        "이상거래 흐름",
    ])

    with tab1:
        _render_tab_bank_network()

    with tab2:
        _render_tab_fraud_account_network()

    with tab3:
        _render_tab_account_explorer()

    with tab4:
        _render_tab_fraud_flow()
