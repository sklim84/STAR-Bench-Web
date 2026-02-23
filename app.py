import pathlib

import streamlit as st
from streamlit_option_menu import option_menu

from src.data import db

st.set_page_config(
    page_title="AML Assistant",
    page_icon="🔍",
    layout="wide",
)

# ------------------------------------------------------------------
# 글래스모피즘 테마 CSS (assets/style.css)
# ------------------------------------------------------------------
def _load_css() -> None:
    css = pathlib.Path("assets/style.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

_load_css()


@st.cache_resource
def init_database():
    """앱 시작 시 DuckDB를 초기화하고 데이터를 적재한다."""
    conn = db.get_connection()
    # db.py 내부에서 직접 연결을 사용하는 것은 허용된 패턴
    count = conn.execute("SELECT count(*) FROM hofinet").fetchone()[0]
    return count


init_database()

# ------------------------------------------------------------------
# 상단 가로 메뉴
# ------------------------------------------------------------------
selected = option_menu(
    menu_title=None,
    options=["Home", "Dashboard", "Network", "Detection", "Agent"],
    icons=["house-fill", "bar-chart-fill", "diagram-3-fill", "robot", "chat-dots-fill"],
    default_index=0,
    orientation="horizontal",
    styles={
        "container": {
            "padding": "4px",
            "background": "rgba(255, 255, 255, 0.04)",
            "backdrop-filter": "blur(16px)",
            "border-radius": "14px",
            "border": "1px solid rgba(255, 255, 255, 0.09)",
            "margin-bottom": "20px",
            "box-shadow": "0 4px 24px rgba(0, 0, 0, 0.35)",
        },
        "icon": {
            "color": "#9EA3B8",
            "font-size": "16px",
        },
        "nav-link": {
            "font-size": "15px",
            "font-weight": "500",
            "text-align": "center",
            "margin": "2px",
            "padding": "10px 24px",
            "color": "#9EA3B8",
            "border-radius": "10px",
            "--hover-color": "rgba(255, 255, 255, 0.06)",
        },
        "nav-link-selected": {
            "background": "rgba(78, 205, 196, 0.15)",
            "color": "#4ECDC4",
            "font-weight": "700",
            "border-radius": "10px",
            "border": "1px solid rgba(78, 205, 196, 0.3)",
        },
    },
)

# ------------------------------------------------------------------
# 선택된 메뉴에 따라 페이지 렌더링
# ------------------------------------------------------------------
if selected == "Home":
    st.markdown('<p style="color:#FFFFFF; font-size:28px; font-weight:800; margin-bottom:4px;">'
                'AML Assistant Platform</p>', unsafe_allow_html=True)
    st.markdown('<p style="color:#6B7080; font-size:15px; margin-top:0;">'
                '에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스</p>',
                unsafe_allow_html=True)

    st.markdown("---")

    # 요약 메트릭 카드 (dashboard.get_summary() 활용)
    from src.features.dashboard import get_summary
    summary = get_summary()
    if summary.empty:
        st.error("데이터를 불러올 수 없습니다. 데이터 로딩 상태를 확인하세요.")
        st.stop()
    row = summary.iloc[0]

    # Home 페이지에서는 출금+입금 금융회사 수 합산으로 표시 (기존 동작 유지)
    banks_count = int(row['출금금융회사수']) + int(row['입금금융회사수'])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""<div class="metric-card">
            <div class="label">총 거래 건수</div>
            <div class="value">{int(row['총거래']):,}</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="metric-card">
            <div class="label">이상거래 건수</div>
            <div class="value">{int(row['이상거래']):,}</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="metric-card">
            <div class="label">출금 계좌 수</div>
            <div class="value">{int(row['출금계좌수']):,}</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="metric-card">
            <div class="label">금융회사 수</div>
            <div class="value">{banks_count:,}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # 기능 안내
    st.markdown('<p class="section-header">기능 안내</p>', unsafe_allow_html=True)
    st.markdown("""
    <table class="dark-table">
        <thead>
            <tr><th>페이지</th><th>설명</th></tr>
        </thead>
        <tbody>
            <tr><td><strong>Dashboard</strong></td><td>대시보드 형태로 자금세탁의심거래들의 기본 분석 정보 출력</td></tr>
            <tr><td><strong>Network</strong></td><td>대시보드 형태로 자금세탁의심거래들의 네트워크(그래프) 분석 정보 출력</td></tr>
            <tr><td><strong>Detection</strong></td><td>AI 모델(부스팅 모델) 기반 자금세탁의심거래 학습 및 탐지(확률)</td></tr>
            <tr><td><strong>Agent</strong></td><td>에이전트와 대화를 통해 자금세탁의심거래를 분석하고 STR 작성</td></tr>
        </tbody>
    </table>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<p style="color:#6B7080; font-size:13px;">상단 메뉴에서 페이지를 선택하세요.</p>',
                unsafe_allow_html=True)

elif selected == "Dashboard":
    from _pages.dashboard_page import render
    render()

elif selected == "Network":
    from _pages.network_page import render
    render()

elif selected == "Detection":
    from _pages.detection_page import render
    render()

elif selected == "Agent":
    from _pages.agent_page import render
    render()
