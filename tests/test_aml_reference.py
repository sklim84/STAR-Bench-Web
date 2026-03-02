"""AML 참조 기능 테스트."""

import pytest

from src.features.aml_reference import (
    lookup_fiu_reference_types,
    validate_str_fields,
    get_aml_glossary,
)


class TestLookupFiuReferenceTypes:
    """lookup_fiu_reference_types 테스트."""

    def test_returns_list(self):
        result = lookup_fiu_reference_types("분할거래")
        assert isinstance(result, list)

    def test_keyword_match(self):
        result = lookup_fiu_reference_types("분할")
        assert len(result) >= 1
        assert any("분할" in r.get("description", "") for r in result)

    def test_industry_filter_banking(self):
        result = lookup_fiu_reference_types("비대면", "banking")
        assert all(r["industry"] == "은행업" for r in result)

    def test_empty_keyword_returns_empty(self):
        result = lookup_fiu_reference_types("")
        assert result == []


class TestValidateStrFields:
    """validate_str_fields 테스트."""

    def test_returns_dict(self):
        result = validate_str_fields({})
        assert isinstance(result, dict)
        assert "valid" in result
        assert "missing_required" in result

    def test_incomplete_draft_has_missing(self):
        result = validate_str_fields({})
        assert result["valid"] is False
        assert len(result["missing_required"]) > 0

    def test_complete_draft_valid(self):
        draft = {
            "표제부": {"문서번호": "2024-001", "보고일자": "20240301"},
            "I_보고기관": {
                "보고기관명": "테스트",
                "보고책임자명": "홍길동",
                "보고담당자명": "김담당",
                "보고담당자 전화번호": "02-1234-5678",
            },
            "II_거래자_공통": {
                "거래자(사업자)명": "테스트",
                "거래자(사업자) 실명번호구분": "1",
                "거래자(사업자) 실명번호": "123456",
                "거래자(사업자) 국적": "1",
            },
            "III_거래내역": {
                "거래발생일시": "202403011200",
                "거래채널": "1",
                "거래수단": "1",
                "거래종류": "1",
                "거래상품": "1",
                "통화종류": "1",
                "관련계좌 존재 여부": "1",
                "송금/수취계좌 존재 여부": "1",
                "거래대리인 존재여부": "2",
            },
        }
        result = validate_str_fields(draft)
        assert result["valid"] is True
        assert len(result["missing_required"]) == 0


class TestGetAmlGlossary:
    """get_aml_glossary 테스트."""

    def test_cdd_returns_definition(self):
        result = get_aml_glossary("CDD")
        assert result is not None
        assert "CDD" in result["term"]
        assert "고객확인" in result["definition"]

    def test_str_returns_definition(self):
        result = get_aml_glossary("STR")
        assert result is not None
        assert "의심거래" in result["definition"]

    def test_unknown_returns_none(self):
        result = get_aml_glossary("UNKNOWN_XYZ")
        assert result is None
