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
    options=["홈", "대시보드", "네트워크", "탐지", "에이전트"],
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
            "font-size": "15px",
        },
        "nav-link": {
            "flex": "1",
            "font-size": "14px",
            "font-weight": "500",
            "text-align": "center",
            "margin": "2px",
            "padding": "10px 8px",
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
if selected == "홈":
    st.markdown('<p class="page-title page-title-lg">AML Assistant Platform</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스</p>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # 요약 메트릭 카드 (dashboard.get_summary() 활용)
    from src.features.dashboard import get_summary
    summary = get_summary()
    if summary.empty:
        st.error("데이터를 불러올 수 없습니다. 데이터 로딩 상태를 확인하세요.")
        st.stop()
    row = summary.iloc[0]

    total = int(row['총거래'])
    fraud = int(row['이상거래'])
    fraud_rate = fraud / total * 100 if total > 0 else 0
    banks_count = int(row['출금금융회사수']) + int(row['입금금융회사수'])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""<div class="metric-card">
            <div class="label">총 거래 건수</div>
            <div class="value">{total:,}</div>
            <div class="sub">2021 Q4 ~ 2024 Q4</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="metric-card">
            <div class="label">이상거래 건수</div>
            <div class="value">{fraud:,}</div>
            <div class="sub">전체 대비 {fraud_rate:.2f}%</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="metric-card">
            <div class="label">출금 계좌 수</div>
            <div class="value">{int(row['출금계좌수']):,}</div>
            <div class="sub">고유 계좌 기준</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="metric-card">
            <div class="label">참여 금융회사</div>
            <div class="value">{banks_count:,}</div>
            <div class="sub">출금 + 입금 기관</div>
        </div>""", unsafe_allow_html=True)

    # 기능 안내 카드 그리드
    st.markdown('<p class="section-header">기능 안내</p>', unsafe_allow_html=True)
    st.markdown("""
    <div class="feature-grid">
        <div class="feature-card">
            <span class="f-icon">📊</span>
            <div class="f-name">대시보드</div>
            <div class="f-desc">거래 통계, 이상거래 유형 분포, 시간대·금융회사별 패턴을 대시보드로 시각화</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">🔗</span>
            <div class="f-name">네트워크</div>
            <div class="f-desc">금융회사·계좌 간 거래 그래프, 커뮤니티 탐지, 순환거래·레이어링 등 AML 패턴 분석</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">🤖</span>
            <div class="f-name">탐지</div>
            <div class="f-desc">XGBoost 모델 기반 이상거래 확률 예측, 모델 학습·평가 및 특성 중요도 분석</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">💬</span>
            <div class="f-name">에이전트</div>
            <div class="f-desc">AI 에이전트와 대화로 거래 조회·분석하고 의심거래보고서(STR) 자동 작성</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

elif selected == "대시보드":
    from _pages.dashboard_page import render
    render()

elif selected == "네트워크":
    from _pages.network_page import render
    render()

elif selected == "탐지":
    from _pages.detection_page import render
    render()

elif selected == "에이전트":
    from _pages.agent_page import render
    render()
