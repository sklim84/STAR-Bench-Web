import streamlit as st
from src.data import db

st.set_page_config(
    page_title="AML Assistant",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def init_database():
    """앱 시작 시 DuckDB를 초기화하고 데이터를 적재한다."""
    conn = db.get_connection()
    count = conn.execute("SELECT count(*) FROM hofinet").fetchone()[0]
    return count


with st.sidebar:
    st.title("AML Assistant")
    st.caption("자금세탁의심거래 분석 플랫폼")

total_count = init_database()

st.title("AML Assistant Platform")
st.markdown("에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스")

st.divider()

col1, col2, col3, col4 = st.columns(4)

summary = db.query("""
    SELECT
        count(*) as total,
        sum(이상거래여부) as fraud,
        count(DISTINCT 출금계좌일련번호) as accounts,
        count(DISTINCT 출금금융회사일련번호) + count(DISTINCT 입금금융회사일련번호) as banks
    FROM hofinet
""")

col1.metric("총 거래 건수", f"{summary['total'].iloc[0]:,}")
col2.metric("이상거래 건수", f"{summary['fraud'].iloc[0]:,}")
col3.metric("출금 계좌 수", f"{summary['accounts'].iloc[0]:,}")
col4.metric("금융회사 수", f"{summary['banks'].iloc[0]:,}")

st.divider()

st.markdown("""
### 기능 안내

| 페이지 | 설명 |
|--------|------|
| **Dashboard** | 대시보드 형태로 자금세탁의심거래들의 기본 분석 정보 출력 |
| **Network** | 대시보드 형태로 자금세탁의심거래들의 네트워크(그래프) 분석 정보 출력 |
| **Detection** | AI 모델(부스팅 모델) 기반 자금세탁의심거래 학습 및 탐지(확률) |
| **Agent** | 에이전트와 대화를 통해 자금세탁의심거래를 분석하고 STR 작성 |

왼쪽 사이드바에서 페이지를 선택하세요.
""")
