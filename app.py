import streamlit as st
from streamlit_option_menu import option_menu

from src.data import db

st.set_page_config(
    page_title="AML Assistant",
    page_icon="🔍",
    layout="wide",
)

# ------------------------------------------------------------------
# 다크 테마 커스텀 CSS
# ------------------------------------------------------------------
st.markdown("""
<style>
/* ── 전역 배경 ── */
.stApp {
    background-color: #0E1117;
}

/* ── 카드 컨테이너 ── */
.dark-card {
    background-color: #1A1F2E;
    border: 1px solid #2A2F3E;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 16px;
}

/* ── 메트릭 카드 ── */
.metric-card {
    background-color: #1A1F2E;
    border: 1px solid #2A2F3E;
    border-radius: 12px;
    padding: 18px 22px;
    text-align: left;
}
.metric-card .label {
    color: #8B8FA3;
    font-size: 13px;
    font-weight: 500;
    margin-bottom: 6px;
}
.metric-card .value {
    color: #4ECDC4;
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.5px;
}
.metric-card .value.white {
    color: #E0E0E0;
}
.metric-card .sub {
    color: #6B7080;
    font-size: 12px;
    margin-top: 4px;
}

/* ── 섹션 헤더 ── */
.section-header {
    color: #FFFFFF;
    font-size: 18px;
    font-weight: 700;
    margin: 28px 0 16px 0;
    padding-bottom: 0;
}

/* ── Streamlit 기본 metric 다크 스타일 ── */
[data-testid="stMetric"] {
    background-color: #1A1F2E;
    border: 1px solid #2A2F3E;
    border-radius: 12px;
    padding: 18px 22px;
}
[data-testid="stMetricLabel"] {
    color: #8B8FA3 !important;
}
[data-testid="stMetricValue"] {
    color: #4ECDC4 !important;
    font-weight: 700 !important;
}

/* ── 탭 스타일 ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0px;
    background-color: #1A1F2E;
    border-radius: 10px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    color: #8B8FA3;
    font-weight: 500;
    padding: 10px 20px;
}
.stTabs [aria-selected="true"] {
    background-color: #2A2F3E !important;
    color: #FFFFFF !important;
}

/* ── divider ── */
.stDivider {
    border-color: #2A2F3E !important;
}
hr {
    border-color: #2A2F3E !important;
}

/* ── 테이블 ── */
.dark-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
}
.dark-table th {
    background-color: #1E2333;
    color: #8B8FA3;
    font-weight: 600;
    font-size: 13px;
    padding: 10px 16px;
    text-align: left;
    border-bottom: 1px solid #2A2F3E;
}
.dark-table td {
    color: #E0E0E0;
    font-size: 14px;
    padding: 10px 16px;
    border-bottom: 1px solid #1E2333;
}
.dark-table tr:hover td {
    background-color: #1E2333;
}
</style>
""", unsafe_allow_html=True)


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
            "background-color": "#1A1F2E",
            "border-radius": "12px",
            "border": "1px solid #2A2F3E",
            "margin-bottom": "20px",
        },
        "icon": {
            "color": "#8B8FA3",
            "font-size": "16px",
        },
        "nav-link": {
            "font-size": "15px",
            "font-weight": "500",
            "text-align": "center",
            "margin": "2px",
            "padding": "10px 24px",
            "color": "#8B8FA3",
            "border-radius": "10px",
            "--hover-color": "#252A3A",
        },
        "nav-link-selected": {
            "background-color": "#4ECDC4",
            "color": "#0E1117",
            "font-weight": "700",
            "border-radius": "10px",
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
