"""AML 참조 자료 페이지: FIU 의심거래 참고유형, STR 필드 점검, AML 용어집."""

import streamlit as st

from src.features.aml_reference import (
    lookup_fiu_reference_types,
    validate_str_fields,
    get_aml_glossary,
)


def render():
    st.markdown('<p class="page-title">AML Reference</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">FIU suspicious transaction reference types, STR field validation, AML glossary</p>',
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["FIU Reference Types", "STR Field Validation", "AML Glossary"])

    # ------------------------------------------------------------------
    # 탭1: FIU 참고유형 검색
    # ------------------------------------------------------------------
    with tab1:
        st.markdown(
            '<p class="section-header">FIU Suspicious Transaction Reference Types by Industry</p>',
            unsafe_allow_html=True,
        )
        st.caption("Based on STR suspicious transaction indicators by industry. Example keywords: structuring, nighttime, non-face-to-face, virtual asset")

        col1, col2 = st.columns([3, 1])
        with col1:
            keyword = st.text_input("Search keyword", placeholder="structuring, nighttime, non-face-to-face, etc.", key="fiu_keyword")
        with col2:
            industry = st.selectbox(
                "Industry",
                options=["All", "banking", "securities"],
                format_func=lambda x: {"All": "All", "banking": "Banking", "securities": "Securities"}.get(x, x),
                key="fiu_industry",
            )

        if st.button("Search", key="fiu_search"):
            with st.spinner("Searching..."):
                ind = None if industry == "All" else industry
                results = lookup_fiu_reference_types(keyword, ind)

            if not results:
                st.info("No results found.")

            else:
                st.success(f"Total {len(results)} results")
                for r in results:
                    with st.expander(f"[{r['industry']}] {r['category']} #{r['no']}"):
                        st.markdown(f"**{r['description']}**")

    # ------------------------------------------------------------------
    # 탭2: STR 필드 점검
    # ------------------------------------------------------------------
    with tab2:
        st.markdown(
            '<p class="section-header">STR Required Field Validation</p>',
            unsafe_allow_html=True,
        )
        st.caption("Based on STR report template. Checks for missing required fields in STR drafts.")

        sample = st.text_area(
            "STR Draft (JSON)",
            value='{"I_보고기관": {"보고기관명": "테스트은행", "보고책임자명": "홍길동", "보고담당자명": "김담당", "보고담당자 전화번호": "02-1234-5678"}}',
            height=120,
            key="str_draft",
        )

        if st.button("Validate", key="str_validate"):
            import json
            try:
                draft = json.loads(sample)
                result = validate_str_fields(draft)
                if result["valid"]:
                    st.success("All required fields are present.")
                else:
                    st.warning(f"**Missing fields ({len(result['missing_required'])}):**")
                    for m in result["missing_required"]:
                        st.markdown(f"- {m}")
            except json.JSONDecodeError as e:
                st.error(f"JSON format error: {e}")

    # ------------------------------------------------------------------
    # 탭3: AML 용어집
    # ------------------------------------------------------------------
    with tab3:
        st.markdown(
            '<p class="section-header">AML Glossary</p>',
            unsafe_allow_html=True,
        )
        st.caption("CDD, EDD, STR, CTR, RBA, PEP, MLRO, FATF, FIU, etc.")

        term = st.text_input("Search term", placeholder="CDD, STR, RBA, etc.", key="glossary_term")

        if st.button("Lookup", key="glossary_lookup"):
            result = get_aml_glossary(term)
            if result:
                st.markdown(f"### {result['term']}")
                st.markdown(result["definition"])
                st.caption(f"Source: {result['source']}")
            else:
                st.info("Term not found. Try CDD, EDD, STR, CTR, RBA, PEP, MLRO, FATF, FIU, KYE, structuring, layering, etc.")
