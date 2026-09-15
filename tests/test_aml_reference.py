"""src/features/aml_reference.py: FIU catalog, STR fields, glossary, code maps."""

import json

import pytest

from src.features import aml_reference as ref


class TestCodeMaps:
    def test_fraud_type_map_matches_hofinet(self):
        assert sorted(ref.FRAUD_TYPE_MAP) == [1, 2, 3, 4, 5, 7]

    def test_media_type_map(self):
        assert ref.MEDIA_TYPE_MAP[2] == "Internet Banking"
        assert ref.MEDIA_TYPE_MAP[7] == "Bulk Transfer"
        assert sorted(ref.MEDIA_TYPE_MAP) == [1, 2, 3, 4, 5, 6, 7]

    def test_fund_type_map(self):
        assert sorted(ref.FUND_TYPE_MAP) == [0, 1, 3, 4]

    def test_translators_fall_back(self):
        assert ref.translate_fraud_type(6) == "Other"
        assert ref.translate_media_type(None) == "Other"
        assert ref.translate_fund_type("x") == "N/A"


class TestFiuCatalog:
    def test_catalog_size(self):
        assert len(ref.lookup_fiu_reference_types("")) == 31

    def test_keyword_match_is_case_insensitive(self):
        assert ref.lookup_fiu_reference_types("STRUCTURING") == \
               ref.lookup_fiu_reference_types("structuring")

    def test_industry_filter(self):
        results = ref.lookup_fiu_reference_types("", industry="securities")
        assert results and {item["industry"] for item in results} == {"Securities"}

    def test_korean_keyword_has_no_match(self):
        assert ref.lookup_fiu_reference_types("심야") == []

    def test_entries_carry_the_documented_fields(self):
        item = ref.lookup_fiu_reference_types("cash")[0]
        assert set(item) == {"industry", "category", "no", "description"}


class TestGlossary:
    def test_terms(self):
        assert ref.glossary_terms()[:3] == ["CDD", "EDD", "SDD"]
        assert len(ref.glossary_terms()) == 13

    def test_lookup_is_case_insensitive(self):
        assert ref.get_aml_glossary("cdd")["term"] == "CDD"

    def test_unknown_term(self):
        assert ref.get_aml_glossary("구조화") is None
        assert ref.get_aml_glossary("") is None


class TestStrValidation:
    def _draft(self):
        return {
            section: {field: "value" for field in fields}
            for section, fields in ref.STR_REQUIRED_FIELDS.items()
        }

    def test_complete_draft_is_valid(self):
        assert ref.validate_str_fields(self._draft())["valid"]

    def test_missing_field_is_named(self):
        draft = self._draft()
        del draft["III_TransactionDetails"]["TransactionPeriod"]
        result = ref.validate_str_fields(draft)
        assert not result["valid"]
        assert result["missing_required"] == ["III_TransactionDetails.TransactionPeriod"]

    def test_placeholder_counts_as_missing(self):
        draft = self._draft()
        draft["II_Transactor"]["WithdrawalAccountNumber"] = ["Unknown"]
        assert not ref.validate_str_fields(draft)["valid"]

    def test_personal_details_are_optional(self):
        result = ref.validate_str_fields(self._draft())
        assert "II_Transactor.Name" in result["missing_optional"]

    def test_json_string_draft(self):
        assert ref.validate_str_fields(json.dumps(self._draft()))["valid"]

    def test_free_text_draft(self):
        result = ref.validate_str_fields("not a draft")
        assert not result["valid"] and "error" in result

    def test_flat_draft_is_accepted(self):
        flat = {field: "value" for fields in ref.STR_REQUIRED_FIELDS.values() for field in fields}
        assert ref.validate_str_fields(flat)["valid"]
