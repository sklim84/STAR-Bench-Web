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
# 라이트 테마 CSS (assets/style.css)
# ------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def _load_css_content() -> str:
    return pathlib.Path("assets/style.css").read_text(encoding="utf-8")


def _load_css() -> None:
    css = _load_css_content()
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
    options=["Home", "Dashboard", "Network", "Detection", "CTR", "Risk", "Monitoring", "Reference", "Agent"],
    icons=["house-fill", "bar-chart-fill", "diagram-3-fill", "robot", "cash-coin", "shield-check", "bell-fill", "journal-bookmark-fill", "chat-dots-fill"],
    default_index=0,
    orientation="horizontal",
    styles={
        "container": {
            "padding": "8px 16px",
            "background": "#FFFFFF",
            "border-radius": "0",
            "border": "none",
            "border-bottom": "1px solid #E5E7EB",
            "margin-bottom": "20px",
            "box-shadow": "0 2px 8px rgba(0, 0, 0, 0.06)",
            "width": "100%",
            "max-width": "none",
        },
        "nav": {
            "flex": "1",
            "width": "100%",
        },
        "nav-item": {
            "flex": "1 1 0%",
            "min-width": "0",
        },
        "icon": {
            "color": "#6B7280",
            "font-size": "15px",
        },
        "nav-link": {
            "flex": "1",
            "width": "100%",
            "font-size": "14px",
            "font-weight": "500",
            "text-align": "center",
            "margin": "2px",
            "padding": "10px 8px",
            "color": "#6B7280",
            "border-radius": "10px",
            "--hover-color": "rgba(0, 0, 0, 0.04)",
        },
        "nav-link-selected": {
            "background": "rgba(5, 150, 105, 0.10)",
            "color": "#059669",
            "font-weight": "700",
            "border-radius": "10px",
            "border": "1px solid rgba(5, 150, 105, 0.25)",
        },
    },
)

# ------------------------------------------------------------------
# 선택된 메뉴에 따라 페이지 렌더링
# ------------------------------------------------------------------
if selected == "Home":
    st.markdown('<p class="page-title page-title-lg">AML Assistant Platform</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Web service for analyzing suspicious money laundering transactions using AI agents</p>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Summary metric cards (using dashboard.get_summary())
    from src.features.dashboard import get_summary
    with st.spinner("Loading data..."):
        summary = get_summary()
    if summary.empty:
        st.error("Unable to load data. Please check the data loading status.")
        st.stop()
    row = summary.iloc[0]

    total = int(row['총거래'])
    fraud = int(row['이상거래'])
    fraud_rate = fraud / total * 100 if total > 0 else 0
    banks_count = int(row['출금금융회사수']) + int(row['입금금융회사수'])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""<div class="metric-card">
            <div class="label">Total Transactions</div>
            <div class="value">{total:,}</div>
            <div class="sub">2021 Q4 ~ 2024 Q4</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="metric-card">
            <div class="label">Fraud Transactions</div>
            <div class="value">{fraud:,}</div>
            <div class="sub">{fraud_rate:.2f}% of total</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="metric-card">
            <div class="label">Sender Accounts</div>
            <div class="value">{int(row['출금계좌수']):,}</div>
            <div class="sub">Unique accounts</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="metric-card">
            <div class="label">Financial Institutions</div>
            <div class="value">{banks_count:,}</div>
            <div class="sub">Sender + Receiver</div>
        </div>""", unsafe_allow_html=True)

    # Feature guide card grid
    st.markdown('<p class="section-header">Features</p>', unsafe_allow_html=True)
    st.markdown("""
    <div class="feature-grid">
        <div class="feature-card">
            <span class="f-icon">📊</span>
            <div class="f-name">Dashboard</div>
            <div class="f-desc">Visualize transaction statistics, fraud type distribution, and patterns by time period and financial institution</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">🔗</span>
            <div class="f-name">Network</div>
            <div class="f-desc">Transaction graph between institutions and accounts, community detection, ring transactions, layering, and other AML pattern analysis</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">🤖</span>
            <div class="f-name">Detection</div>
            <div class="f-desc">XGBoost model-based fraud probability prediction, model training/evaluation, and feature importance analysis</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">💰</span>
            <div class="f-name">CTR</div>
            <div class="f-desc">Currency Transaction Report (CTR) candidate lookup and structuring detection</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">🛡️</span>
            <div class="f-name">Risk Assessment</div>
            <div class="f-desc">Account risk scoring (0~100) based on 5 behavioral indicators and high-risk account ranking</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">🔔</span>
            <div class="f-name">Monitoring</div>
            <div class="f-desc">Rule-based suspicious transaction detection (nighttime bulk, rapid-fire, round amounts, institution concentration, pattern change)</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">📚</span>
            <div class="f-name">Reference</div>
            <div class="f-desc">FIU suspicious transaction reference types, STR field validation, AML glossary (CDD, STR, CTR, RBA, etc.)</div>
        </div>
        <div class="feature-card">
            <span class="f-icon">💬</span>
            <div class="f-name">Agent</div>
            <div class="f-desc">Query and analyze transactions through AI agent conversation, and auto-generate Suspicious Transaction Reports (STR)</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

elif selected == "Dashboard":
    from _pages.dashboard_page import render
    render()

elif selected == "Network":
    from _pages.network_page import render
    render()

elif selected == "Detection":
    from _pages.detection_page import render
    render()

elif selected == "CTR":
    from _pages.ctr_page import render
    render()

elif selected == "Risk":
    from _pages.risk_page import render
    render()

elif selected == "Monitoring":
    from _pages.monitoring_page import render
    render()

elif selected == "Reference":
    from _pages.aml_reference_page import render
    render()

elif selected == "Agent":
    from _pages.agent_page import render
    render()
