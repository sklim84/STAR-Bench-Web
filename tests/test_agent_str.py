"""generate_str and validate_str_fields.

Recorded runs showed that a third of the recorded generate_str executions crashed on
transactions serialised as a JSON string, that Korean enum values fell through
to the "Other" branch, and that no draft a model could build ever validated.
"""

import json

import pytest

import config
from src.features.agent import _execute_tool


TRANSACTION = {
    "date": 20241015, "time_slot": 21, "sender_bank": 134, "sender_acc": 9000000004390593,
    "receiver_bank": 117, "receiver_acc": 9000000004371903, "fund_type": 0,
    "media_type": 2, "amount": 5000000, "fraud_type": 3,
}


def generate(**arguments):
    return json.loads(_execute_tool("generate_str", arguments))


def validate(draft):
    return json.loads(_execute_tool("validate_str_fields", {"str_draft": draft}))


class TestGenerateStr:
    def test_requires_a_summary(self):
        assert "error" in generate(fraud_type="분할거래")

    def test_builds_the_seven_sections(self):
        report = generate(summary="반복 이체 의심", transactions=[TRANSACTION])
        for section in ("Header", "I_ReportingInstitution", "II_Transactor",
                        "III_TransactionDetails", "IV_RelatedAccounts",
                        "VI_TransactionType", "VII_Narrative"):
            assert section in report

    def test_reporting_date_is_the_reference_date(self):
        report = generate(summary="s", transactions=[TRANSACTION])
        assert report["Header"]["ReportingDate"] == "2024-12-31"
        assert str(config.REFERENCE_DATE) == "20241231"

    def test_transactions_as_a_json_string(self):
        report = generate(summary="s", transactions=json.dumps([TRANSACTION]))
        assert report["III_TransactionDetails"]["TransactionCount"] == 1
        assert report["II_Transactor"]["WithdrawalAccountNumber"] == ["9000000004390593"]

    def test_transaction_values_as_strings(self):
        row = {k: str(v) for k, v in TRANSACTION.items()}
        report = generate(summary="s", transactions=[row])
        assert report["III_TransactionDetails"]["TotalAmount_KRW"] == 5_000_000
        assert report["III_TransactionDetails"]["TransactionChannel"] == "Internet Banking"

    def test_single_transaction_object(self):
        report = generate(summary="s", transactions=TRANSACTION)
        assert report["III_TransactionDetails"]["TransactionCount"] == 1

    def test_risk_score_as_a_string(self):
        report = generate(summary="s", transactions=[TRANSACTION], fraud_probability="0.91")
        assert report["VII_Narrative"]["SuspicionIntensity_1to5"] == 5
        assert "risk score" in report["VII_Narrative"]["SuspicionIntensityDescription"]

    def test_risk_score_given_as_a_percentage(self):
        report = generate(summary="s", fraud_probability=91)
        assert report["VII_Narrative"]["SuspicionIntensity_1to5"] == 5

    def test_risk_score_out_of_range_is_refused(self):
        assert "error" in generate(summary="s", fraud_probability=700)

    def test_korean_enum_value_maps_to_a_section_vi_item(self):
        report = generate(summary="s", fraud_type="분할거래")
        assert report["VI_TransactionType"]["PrimarySuspicionType"] == "분할거래"
        assert report["VI_TransactionType"]["SectionVICode"] == 18
        assert report["VI_TransactionType"]["HOFINETFraudType"] == 3
        assert report["RecommendedActions"][0] == "Aggregate related transactions"

    def test_hofinet_description_value_is_accepted(self):
        report = generate(summary="s", fraud_type="심야/새벽 대량 거래")
        assert report["VI_TransactionType"]["HOFINETFraudType"] == 7
        assert report["VI_TransactionType"]["PrimarySuspicionType"] == "기타(자유기술)"

    def test_english_label_is_accepted(self):
        report = generate(summary="s", fraud_type="Split Transaction")
        assert report["VI_TransactionType"]["HOFINETFraudType"] == 3

    def test_korean_summary_yields_the_accounts(self):
        report = generate(summary="출금계좌 9000000004390593에서 입금계좌 9000000004371903로 이체")
        assert report["II_Transactor"]["WithdrawalAccountNumber"] == ["9000000004390593"]
        assert report["II_Transactor"]["ReceivingAccountNumber"] == ["9000000004371903"]

    def test_english_summary_yields_the_accounts(self):
        report = generate(summary="sender account 9000000004390593 sent to receiver account 9000000004371903")
        assert report["II_Transactor"]["WithdrawalAccountNumber"] == ["9000000004390593"]
        assert report["II_Transactor"]["ReceivingAccountNumber"] == ["9000000004371903"]

    def test_aml_patterns_as_a_string(self):
        report = generate(summary="s", aml_patterns="분할거래, layering")
        items = report["VI_TransactionType"]["ApplicableItems"]
        assert "Splitting amount across multiple transfers" in items
        assert "Sudden change in transaction pattern" in items

    def test_tools_used_as_a_string(self):
        report = generate(summary="s", tools_used="query_transactions, predict_fraud")
        assert "Directly query HOFINET DB transaction data" in report["AnalysisGrounds"]

    def test_amount_missing_from_a_transaction(self):
        row = dict(TRANSACTION)
        row["amount"] = None
        report = generate(summary="s", transactions=[row])
        assert report["III_TransactionDetails"]["TotalAmount_KRW"] == 0

    def test_report_is_the_same_on_every_call(self):
        first = _execute_tool("generate_str", {"summary": "s", "transactions": [TRANSACTION]})
        second = _execute_tool("generate_str", {"summary": "s", "transactions": [TRANSACTION]})
        assert first == second


class TestValidateStrFields:
    def test_generate_str_output_validates(self):
        report = generate(summary="s", fraud_type="분할거래", transactions=[TRANSACTION])
        result = validate(report)
        assert result["valid"], result["missing_required"]

    def test_generate_str_output_as_a_json_string_validates(self):
        report = generate(summary="s", fraud_type="분할거래", transactions=[TRANSACTION])
        assert validate(json.dumps(report, ensure_ascii=False))["valid"]

    def test_missing_fields_are_named(self):
        result = validate({"Header": {"ReportingDate": "2024-12-31"}})
        assert not result["valid"]
        assert "II_Transactor.WithdrawalAccountNumber" in result["missing_required"]

    def test_personal_details_are_optional(self):
        report = generate(summary="s", fraud_type="분할거래", transactions=[TRANSACTION])
        result = validate(report)
        assert "II_Transactor.Name" in result["missing_optional"]
        assert not any(field.startswith("II_Transactor.Name") for field in result["missing_required"])

    def test_documented_section_names_are_accepted(self):
        from src.features.aml_reference import STR_REQUIRED_FIELDS

        draft = {
            section: {field: "filled" for field in fields}
            for section, fields in STR_REQUIRED_FIELDS.items()
        }
        assert validate(draft)["valid"]

    def test_legacy_section_names_are_accepted(self):
        report = generate(summary="s", fraud_type="분할거래", transactions=[TRANSACTION])
        renamed = dict(report)
        renamed["I_Reporting_Institution"] = renamed.pop("I_ReportingInstitution")
        renamed["III_Transaction_Details"] = renamed.pop("III_TransactionDetails")
        assert validate(renamed)["valid"]

    def test_field_names_match_ignoring_case_and_underscores(self):
        report = generate(summary="s", fraud_type="분할거래", transactions=[TRANSACTION])
        section = report["III_TransactionDetails"]
        report["III_TransactionDetails"] = {
            "transaction_period": section["TransactionPeriod"],
            "transaction_count": section["TransactionCount"],
            "transaction_channel": section["TransactionChannel"],
            "total_amount_krw": section["TotalAmount_KRW"],
        }
        assert validate(report)["valid"]

    def test_unknown_placeholder_counts_as_missing(self):
        report = generate(summary="no accounts here")
        result = validate(report)
        assert not result["valid"]
        assert "II_Transactor.WithdrawalAccountNumber" in result["missing_required"]

    def test_free_text_draft_is_refused(self):
        result = validate("this is not a draft")
        assert not result["valid"] and "error" in result

    def test_draft_is_required(self):
        assert "error" in json.loads(_execute_tool("validate_str_fields", {}))
