"""AML 참조 자료 페이지: FIU 의심거래 참고유형, STR 필드 점검, AML 용어집."""

import streamlit as st

from src.features.aml_reference import (
    lookup_fiu_reference_types,
    validate_str_fields,
    get_aml_glossary,
)


def render():
    st.markdown('<p class="page-title">AML 참조 자료</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">FIU 의심거래 참고유형, STR 필드 점검, AML 용어집</p>',
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["FIU 참고유형 검색", "STR 필드 점검", "AML 용어집"])

    # ------------------------------------------------------------------
    # 탭1: FIU 참고유형 검색
    # ------------------------------------------------------------------
    with tab1:
        st.markdown(
            '<p class="section-header">FIU 업권별 의심거래 참고유형 검색</p>',
            unsafe_allow_html=True,
        )
        st.caption("07b_STR_의심거래보고_업권별지표.md 기반. 검색어 예: 분할거래, 심야, 비대면, 가상자산")

        col1, col2 = st.columns([3, 1])
        with col1:
            keyword = st.text_input("검색어", placeholder="분할거래, 심야, 비대면, 가상자산 등", key="fiu_keyword")
        with col2:
            industry = st.selectbox(
                "업권",
                options=["전체", "banking", "securities"],
                format_func=lambda x: {"전체": "전체", "banking": "은행업", "securities": "증권업"}.get(x, x),
                key="fiu_industry",
            )

        if st.button("검색", key="fiu_search"):
            with st.spinner("검색 중..."):
                ind = None if industry == "전체" else industry
                results = lookup_fiu_reference_types(keyword, ind)

            if not results:
                st.info("검색 결과가 없습니다.")

            else:
                st.success(f"총 {len(results)}건")
                for r in results:
                    with st.expander(f"[{r['industry']}] {r['category']} #{r['no']}"):
                        st.markdown(f"**{r['description']}**")

    # ------------------------------------------------------------------
    # 탭2: STR 필드 점검
    # ------------------------------------------------------------------
    with tab2:
        st.markdown(
            '<p class="section-header">STR 필수 필드 점검</p>',
            unsafe_allow_html=True,
        )
        st.caption("08_STR_보고서양식.md 기반. STR 초안의 필수 필드 누락 여부를 점검합니다.")

        sample = st.text_area(
            "STR 초안 (JSON)",
            value='{"I_보고기관": {"보고기관명": "테스트은행", "보고책임자명": "홍길동", "보고담당자명": "김담당", "보고담당자 전화번호": "02-1234-5678"}}',
            height=120,
            key="str_draft",
        )

        if st.button("점검", key="str_validate"):
            import json
            try:
                draft = json.loads(sample)
                result = validate_str_fields(draft)
                if result["valid"]:
                    st.success("✅ 모든 필수 필드가 기재되었습니다.")
                else:
                    st.warning(f"**누락 필드 ({len(result['missing_required'])}건):**")
                    for m in result["missing_required"]:
                        st.markdown(f"- {m}")
            except json.JSONDecodeError as e:
                st.error(f"JSON 형식 오류: {e}")

    # ------------------------------------------------------------------
    # 탭3: AML 용어집
    # ------------------------------------------------------------------
    with tab3:
        st.markdown(
            '<p class="section-header">AML 용어집</p>',
            unsafe_allow_html=True,
        )
        st.caption("CDD, EDD, STR, CTR, RBA, PEP, MLRO, FATF, FIU 등")

        term = st.text_input("용어 검색", placeholder="CDD, STR, RBA 등", key="glossary_term")

        if st.button("조회", key="glossary_lookup"):
            result = get_aml_glossary(term)
            if result:
                st.markdown(f"### {result['term']}")
                st.markdown(result["definition"])
                st.caption(f"출처: {result['source']}")
            else:
                st.info("해당 용어를 찾을 수 없습니다. CDD, EDD, STR, CTR, RBA, PEP, MLRO, FATF, FIU, KYE, 구조화, 레이어링 등을 시도해보세요.")
