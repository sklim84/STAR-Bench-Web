import streamlit as st
from src.features.agent import chat
import config

st.set_page_config(page_title="AI 분석 에이전트", layout="wide")
st.title("AI 분석 에이전트")

if not config.OPENAI_API_KEY:
    st.error("OPENAI_API_KEY가 설정되지 않았습니다. `.env` 파일을 확인하세요.")
    st.stop()

st.caption("자금세탁의심거래 분석 및 STR 작성을 위한 대화형 에이전트")

# 세션 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 사이드바: 대화 관리
with st.sidebar:
    st.subheader("에이전트 기능")
    st.markdown("""
    - **거래 조회**: DB에서 거래 데이터 조회/분석
    - **이상 탐지**: 모델로 이상거래 확률 예측
    - **STR 작성**: 의심거래보고서 자동 생성
    """)

    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.markdown("**예시 질문**")
    examples = [
        "2024년 이상거래 현황을 요약해줘",
        "심야 시간대 이상거래 패턴을 분석해줘",
        "출금금융회사 134에서 발생한 이상거래를 조사해줘",
        "이상거래 유형별 금액 분포를 알려줘",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{ex[:10]}"):
            st.session_state.messages.append({"role": "user", "content": ex})
            st.rerun()

# 대화 히스토리 표시
for msg in st.session_state.messages:
    if msg["role"] in ("user", "assistant"):
        with st.chat_message(msg["role"]):
            st.markdown(msg.get("content", ""))

# 사용자 입력
if prompt := st.chat_input("거래 분석 질문을 입력하세요..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("분석 중..."):
            # tool/system 메시지 제외하고 user/assistant만 전달
            chat_messages = [
                m for m in st.session_state.messages
                if m["role"] in ("user", "assistant") and m.get("content")
            ]
            response, updated = chat(chat_messages)
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
