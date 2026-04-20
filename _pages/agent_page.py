"""Feature 4: AI Agent Interactive Analysis & STR Generation Page."""

import json
from datetime import date

import streamlit as st

import config
from src.features.agent import chat


# ---------------------------------------------------------------------------
# Tool Name Labels
# ---------------------------------------------------------------------------

_TOOL_LABELS = {
    "query_transactions": "Query Transactions",
    "predict_fraud": "Predict Fraud Probability",
    "generate_str": "Generate STR Report",
    "analyze_network": "Network Analysis",
    "get_statistics": "Summary Statistics",
    "detect_aml_patterns": "AML Pattern Detection",
    "get_account_profile": "Account Profile",
    "get_fraud_type_summary": "Fraud Type Summary",
    "compare_periods": "Period Comparison",
    "get_institution_report": "Institution Report",
    "rank_risky_transactions": "Risk Ranking",
    "detect_ctr_candidates": "CTR/Structuring Detection",
    "score_account_risk": "Risk Scoring",
    "detect_monitoring_alerts": "Monitoring Alerts",
    "detect_dormant_reactivation": "Dormant Reactivation",
    "detect_smurfing_network": "Smurfing Detection",
    "get_trend_analysis": "Trend Analysis",
    "analyze_channel_risk": "Channel Risk Analysis",
    "get_receiving_account_profile": "Receiving Profile Analysis",
    "analyze_cross_institution_flow": "Cross-Institution Flow",
    "lookup_fiu_reference_types": "FIU Typology Lookup",
    "validate_str_fields": "STR Validation",
    "get_aml_glossary": "AML Glossary",
}

_TOOL_ICONS = {
    "query_transactions": "🔍",
    "predict_fraud": "🤖",
    "generate_str": "📄",
    "analyze_network": "🔗",
    "get_statistics": "📊",
    "detect_aml_patterns": "⚠️",
    "score_account_risk": "🛡️",
    "detect_monitoring_alerts": "🚨",
}


def _tool_label(name: str) -> str:
    icon = _TOOL_ICONS.get(name, "🔧")
    label = _TOOL_LABELS.get(name, name)
    return f"{icon} {label}"


# ---------------------------------------------------------------------------
# Tool Event Expander Rendering
# ---------------------------------------------------------------------------

def _render_tool_event(event: dict, index: int) -> None:
    """Renders a single tool call event as an expander."""
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
# Conversation Export
# ---------------------------------------------------------------------------

def _build_export_json(messages: list[dict]) -> str:
    """Returns a JSON string containing only user/assistant messages."""
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
# Main Render Function
# ---------------------------------------------------------------------------

def render() -> None:
    st.markdown('<p class="page-title">AI Analysis Agent</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Suspicious transaction analysis and automatic STR (Suspicious Transaction Report) generation</p>', unsafe_allow_html=True)

    if not config.OPENAI_API_KEY:
        st.error("OPENAI_API_KEY is not configured. Please check your `.env` file.")
        st.stop()

    # Session Initialization
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = None
    # Tool events mapped by assistant message index: {assistant_msg_index: [events]}
    if "tool_events_map" not in st.session_state:
        st.session_state.tool_events_map = {}

    # ------------------------------------------------------------------
    # Toolbar: Reset / Export + Stats
    # ------------------------------------------------------------------
    messages = st.session_state.messages
    turn_count = sum(1 for m in messages if m.get("role") == "user")

    btn_c1, btn_c2, info_c = st.columns([1, 1, 4])
    with btn_c1:
        if st.button("Reset Chat", use_container_width=True):
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
                use_container_width=True,
            )
        else:
            st.button("Export Chat", disabled=True, use_container_width=True)
    with info_c:
        if turn_count > 0:
            st.markdown(
                f'<p class="caption-text" style="padding-top:8px">Current conversation: {turn_count} turns</p>',
                unsafe_allow_html=True,
            )

    # ------------------------------------------------------------------
    # Agent Guide & Example Questions
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
    # Conversation History Display
    # ------------------------------------------------------------------
    # Display user/assistant messages in order.
    # Tool events used for a response are displayed right before the assistant message.

    assistant_index = 0  # Accrued counter for assistant messages
    for msg in st.session_state.messages:
        role = msg.get("role")

        if role == "user":
            with st.chat_message("user"):
                st.markdown(msg.get("content", ""))

        elif role == "assistant":
            with st.chat_message("assistant"):
                # Display tool events linked to this assistant response
                events = st.session_state.tool_events_map.get(assistant_index, [])
                if events:
                    for i, event in enumerate(events):
                        _render_tool_event(event, i)

                st.markdown(msg.get("content", ""))
            assistant_index += 1

        # tool/function messages are not displayed directly (replaced by expander)

    # ------------------------------------------------------------------
    # User Input Processing
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
            # Display status while analyzing (st.status)
            with st.status("Agent analyzing...", expanded=True) as status:
                st.write("Selecting tools and querying data...")
                try:
                    # chat function returns the final response and updated message history
                    response, updated, tool_events = chat(st.session_state.messages)
                    st.session_state.messages = updated

                    if tool_events:
                        st.write(f"{len(tool_events)} tool call(s) completed")
                    status.update(label="Analysis complete", state="complete", expanded=False)
                except Exception as exc:
                    status.update(label="Error occurred", state="error", expanded=True)
                    st.error(f"Agent error: {str(exc)}")
                    response = None
                    tool_events = []

            # Store tool events for the current assistant index
            if tool_events:
                current_assistant_index = sum(
                    1 for m in st.session_state.messages
                    if m.get("role") == "assistant"
                ) - 1
                if current_assistant_index >= 0:
                    st.session_state.tool_events_map[current_assistant_index] = tool_events

                # Immediately render tool event expanders
                for i, event in enumerate(tool_events):
                    _render_tool_event(event, i)

            if response:
                st.markdown(response)
