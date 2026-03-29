"""기능4: AI 에이전트 대화형 분석 + STR 작성 페이지."""

import json
from datetime import date

import streamlit as st

import config
from src.features.agent import chat


# ---------------------------------------------------------------------------
# 도구 이름 한글 레이블
# ---------------------------------------------------------------------------

_TOOL_LABELS = {
    "query_transactions": "Query Transactions",
    "predict_fraud": "Predict Fraud Probability",
    "generate_str": "Generate STR Report",
    "analyze_network": "Network Analysis",
    "get_statistics": "Summary Statistics",
    "detect_aml_patterns": "AML Pattern Detection",
}

_TOOL_ICONS = {
    "query_transactions": "🔍",
    "predict_fraud": "🤖",
    "generate_str": "📄",
    "analyze_network": "🔗",
    "get_statistics": "📊",
    "detect_aml_patterns": "⚠️",
}


def _tool_label(name: str) -> str:
    icon = _TOOL_ICONS.get(name, "🔧")
    label = _TOOL_LABELS.get(name, name)
    return f"{icon} {label}"


# ---------------------------------------------------------------------------
# 도구 이벤트 expander 렌더링
# ---------------------------------------------------------------------------

def _render_tool_event(event: dict, index: int) -> None:
    """단일 도구 호출 이벤트를 expander로 렌더링한다."""
    tool_name = event.get("name", "unknown")
    label = f"Tool Call {index + 1}: {_tool_label(tool_name)}"

    with st.expander(label, expanded=False):
        col_in, col_out = st.columns(2)

        with col_in:
            st.markdown(
                "<p class='tool-label'>Input Parameters</p>",
                unsafe_allow_html=True,
            )
            args = event.get("arguments", {})
            if args:
                st.json(args)
            else:
                st.markdown('<span class="caption-text">No parameters</span>', unsafe_allow_html=True)

        with col_out:
            st.markdown(
                "<p class='tool-label'>Result</p>",
                unsafe_allow_html=True,
            )
            raw = event.get("result", "{}")
            try:
                parsed = json.loads(raw)
                st.json(parsed)
            except (json.JSONDecodeError, TypeError):
                st.code(str(raw)[:500])


# ---------------------------------------------------------------------------
# 대화 내보내기
# ---------------------------------------------------------------------------

def _build_export_json(messages: list[dict]) -> str:
    """user/assistant 메시지만 포함하는 JSON 문자열을 반환한다."""
    exportable = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in messages
        if m.get("role") in ("user", "assistant")
    ]
    payload = {
        "exported_at": date.today().isoformat(),
        "total_turns": len(exportable),
        "conversation": exportable,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 메인 render 함수
# ---------------------------------------------------------------------------

def render() -> None:
    st.markdown('<p class="page-title">AI Analysis Agent</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Suspicious transaction analysis and automatic STR (Suspicious Transaction Report) generation</p>', unsafe_allow_html=True)

    if not config.OPENAI_API_KEY:
        st.error("OPENAI_API_KEY is not configured. Please check your `.env` file.")
        st.stop()

    # 세션 초기화
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = None
    # 도구 이벤트는 메시지 인덱스를 키로 저장: {assistant_msg_index: [events]}
    if "tool_events_map" not in st.session_state:
        st.session_state.tool_events_map = {}

    # ------------------------------------------------------------------
    # 툴바: 대화 초기화 / 내보내기 + 대화 상태 (항상 표시)
    # ------------------------------------------------------------------
    messages = st.session_state.messages
    turn_count = sum(1 for m in messages if m.get("role") == "user")

    btn_c1, btn_c2, info_c = st.columns([1, 1, 4])
    with btn_c1:
        if st.button("Reset Chat", width='stretch'):
            st.session_state.messages = []
            st.session_state.pending_prompt = None
            st.session_state.tool_events_map = {}
            st.rerun()
    with btn_c2:
        if messages:
            export_data = _build_export_json(messages)
            filename = f"aml_analysis_{date.today().strftime('%Y%m%d')}.json"
            st.download_button(
                label="Export Chat",
                data=export_data,
                file_name=filename,
                mime="application/json",
                width='stretch',
            )
        else:
            st.button("Export Chat", disabled=True, width='stretch')
    with info_c:
        if turn_count > 0:
            st.markdown(
                f'<p class="caption-text" style="padding-top:8px">Current conversation: {turn_count} turns</p>',
                unsafe_allow_html=True,
            )

    # ------------------------------------------------------------------
    # 기능 안내 및 예시 질문
    # ------------------------------------------------------------------
    with st.expander("Agent Features & Example Questions"):
        col_info, col_examples = st.columns(2)

        with col_info:
            st.markdown('<p class="section-header">Agent Features</p>', unsafe_allow_html=True)
            st.markdown("""
- 📊 **Statistics**: Overall fraud transaction dashboard
- 🔍 **Query**: Search and analyze transaction data from DB
- 🔗 **Network Analysis**: Analyze transaction connections for specific accounts
- 🤖 **Fraud Detection**: Predict fraud probability using ML model
- ⚠️ **AML Pattern Detection**: Detect ring transactions, layering, and other ML patterns
- 📄 **STR Generation**: Auto-generate Suspicious Transaction Reports

**Recommended Analysis Flow**
1. Overall statistics → 2. Detailed query → 3. Network analysis → 4. Model prediction → 5. STR generation
""")

        with col_examples:
            st.markdown('<p class="section-header">Example Questions</p>', unsafe_allow_html=True)
            examples = [
                "Summarize overall fraud transaction statistics",
                "Summarize fraud status for 2024",
                "Analyze nighttime fraud transaction patterns",
                "Investigate fraud transactions from sender institution 134",
                "Show amount distribution by fraud type",
                "Analyze the network for account 123456789",
            ]
            for ex in examples:
                if st.button(ex, key=f"ex_{ex[:12]}"):
                    st.session_state.pending_prompt = ex
                    st.rerun()

    # ------------------------------------------------------------------
    # 대화 히스토리 표시
    # ------------------------------------------------------------------
    # user/assistant 메시지 순서대로 표시하되,
    # assistant 직전에 해당 응답에서 사용된 도구 이벤트를 함께 표시한다.

    assistant_index = 0  # assistant 메시지 누적 카운터
    for msg in st.session_state.messages:
        role = msg.get("role")

        if role == "user":
            with st.chat_message("user"):
                st.markdown(msg.get("content", ""))

        elif role == "assistant":
            with st.chat_message("assistant"):
                # 이 assistant 응답에 연결된 도구 이벤트 표시
                events = st.session_state.tool_events_map.get(assistant_index, [])
                if events:
                    for i, event in enumerate(events):
                        _render_tool_event(event, i)

                st.markdown(msg.get("content", ""))
            assistant_index += 1

        # tool/function 메시지는 화면에 직접 표시하지 않음 (expander로 대체)

    # ------------------------------------------------------------------
    # 사용자 입력 처리
    # ------------------------------------------------------------------
    prompt = st.chat_input("Enter your transaction analysis question...")

    if st.session_state.pending_prompt:
        prompt = st.session_state.pending_prompt
        st.session_state.pending_prompt = None

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            # 도구 호출 중 상태 표시 (st.status)
            with st.status("Agent analyzing...", expanded=True) as status:
                st.write("Selecting tools and querying data...")
                try:
                    # session_state.messages에는 이미 user 메시지가 포함되어 있음
                    response, updated, tool_events = chat(st.session_state.messages)
                    # messages를 갱신 (chat 함수가 반환한 updated가 최신 상태)
                    st.session_state.messages = updated

                    if tool_events:
                        st.write(f"{len(tool_events)} tool call(s) completed")
                    status.update(label="Analysis complete", state="complete", expanded=False)
                except Exception as exc:
                    status.update(label="Error occurred", state="error", expanded=True)
                    st.error(f"Agent error: {str(exc)}")
                    response = None
                    tool_events = []

            # 도구 이벤트를 현재 assistant 인덱스에 저장
            if tool_events:
                current_assistant_index = sum(
                    1 for m in st.session_state.messages
                    if m.get("role") == "assistant"
                ) - 1
                if current_assistant_index >= 0:
                    st.session_state.tool_events_map[current_assistant_index] = tool_events

                # 도구 이벤트 expander 즉시 표시
                for i, event in enumerate(tool_events):
                    _render_tool_event(event, i)

            if response:
                st.markdown(response)
