"""AML Reference Feature: FIU suspicious transaction types, STR field validation, AML glossary.

Provides knowledge lookup capabilities to support AML specialists based on _docs.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# FIU 업권별 의심거래 참고유형 (07b_STR_의심거래보고_업권별지표.md 기반)
# ---------------------------------------------------------------------------

_FIU_REFERENCE_TYPES = [
    # Banking - Deposits
    {"industry": "Banking", "category": "Deposits-Cash", "no": 1, "description": "Frequent large cash deposits/withdrawals without a rational reason"},
    {"industry": "Banking", "category": "Deposits-Cash", "no": 6, "description": "Processing substitute transactions as cash transactions"},
    {"industry": "Banking", "category": "Deposits-Cash", "no": 10, "description": "Suspicious tax evasion transactions deposited using ATMs"},
    {"industry": "Banking", "category": "Deposits-Account", "no": 11, "description": "Frequent large deposits/withdrawals followed by closure, or reactivation with large funds after long dormancy"},
    {"industry": "Banking", "category": "Deposits-Account", "no": 12, "description": "Transactions using accounts in others' names (minors, elderly, credit-managed individuals, etc.)"},
    {"industry": "Banking", "category": "Deposits-Account", "no": 14, "description": "Opening multiple demand deposit accounts without a rational reason"},
    {"industry": "Banking", "category": "Deposits-Split", "no": 17, "description": "Transactions split among multiple people or structured below threshold to avoid reporting (structuring)"},
    {"industry": "Banking", "category": "Deposits-Disguise", "no": 18, "description": "Disguising personal transactions using others' names for cashier's checks or wire transfers to hide source of funds"},
    {"industry": "Banking", "category": "Deposits-Misc", "no": 26, "description": "Refusal/non-cooperation regarding customer information requests or inconsistency in information provided"},
    {"industry": "Banking", "category": "Deposits-Misc", "no": 28, "description": "Depositing large funds, issuing a balance certificate, and withdrawing the full amount the next day"},
    {"industry": "Banking", "category": "Deposits-Misc", "no": 30, "description": "24-hour bulk transactions via internet banking with parties unrelated to business"},
    {"industry": "Banking", "category": "Deposits-Misc", "no": 33, "description": "Prepaid card or gift certificate balance refund transactions"},
    # Banking - Non-face-to-face
    {"industry": "Banking", "category": "Non-face-to-face", "no": 1, "description": "Excessive number of transactions and bulk operations via internet banking throughout the day, including night/early morning hours"},
    {"industry": "Banking", "category": "Non-face-to-face", "no": 2, "description": "Cash withdrawals from ATMs using funds received from unknown counterparties"},
    {"industry": "Banking", "category": "Non-face-to-face", "no": 3, "description": "Transferring funds received from unknown counterparties to a third party"},
    {"industry": "Banking", "category": "Non-face-to-face", "no": 8, "description": "Large wire transfer transactions using accounts that have been unused for a long period"},
    {"industry": "Banking", "category": "Non-face-to-face", "no": 13, "description": "Frequent transfers with entities suspected of being illegal gambling sites"},
    {"industry": "Banking", "category": "Non-face-to-face", "no": 17, "description": "Fund flow transactions inconsistent with customer information"},
    # Banking - Virtual Asset
    {"industry": "Banking", "category": "Virtual Asset", "no": 3, "description": "Non-face-to-face cash withdrawals of funds received from virtual asset exchanges"},
    {"industry": "Banking", "category": "Virtual Asset", "no": 4, "description": "Sending funds to unspecified multiple parties after receiving large amounts from accounts related to virtual asset exchanges"},
    {"industry": "Banking", "category": "Virtual Asset", "no": 18, "description": "Suspicious money laundering using price differences between countries (Kimchi Premium, etc.)"},
    # Banking - Corporate
    {"industry": "Banking", "category": "Corporate Related", "no": 1, "description": "Transactions between corporate accounts and the individual account of the representative"},
    {"industry": "Banking", "category": "Corporate Related", "no": 2, "description": "Transactions between corporations with the same representative"},
    {"industry": "Banking", "category": "Corporate Related", "no": 3, "description": "Transactions using shell corporation accounts"},
    # Securities
    {"industry": "Securities", "category": "In/Out", "no": 1, "description": "Deposit/withdrawal or equivalent transactions occurring unusually compared to normal patterns"},
    {"industry": "Securities", "category": "In/Out", "no": 2, "description": "Split transactions involving multiple small amounts without a rational reason"},
    {"industry": "Securities", "category": "In/Out", "no": 4, "description": "Transactions using borrowed names or transferring to others' accounts"},
    {"industry": "Securities", "category": "In/Out", "no": 13, "description": "Deposit/withdrawal transactions solely for issuing balance certificates without real transaction intent"},
    {"industry": "Securities", "category": "Securities Trading", "no": 6, "description": "Concentrated trading of specific stocks followed by full liquidation for stock manipulation purposes"},
    {"industry": "Securities", "category": "Non-face-to-face", "no": 1, "description": "Transactions with closed or newly established corporations and multiple individuals after non-face-to-face account opening"},
    {"industry": "Securities", "category": "Non-face-to-face", "no": 2, "description": "Opening multiple accounts non-face-to-face within a short period"},
]

# ---------------------------------------------------------------------------
# AML 용어집 (_docs 기반)
# ---------------------------------------------------------------------------

_AML_GLOSSARY = {
    "CDD": {
        "definition": "Customer Due Diligence. The process by which financial institutions exercise reasonable care regarding customers, including identity verification, confirming transaction purposes, and identifying beneficial owners.",
        "source": "Financial Information Act, FATF Recommendations",
    },
    "EDD": {
        "definition": "Enhanced Due Diligence. Procedures to verification additional information for customers or products with high money laundering risk identified through risk assessment.",
        "source": "05a_CDD_Customer_Due_Diligence",
    },
    "SDD": {
        "definition": "Simplified Due Diligence. Certain customer due diligence procedures may not be applied to customers or products identified as low risk through risk assessment.",
        "source": "05a_CDD_Customer_Due_Diligence",
    },
    "STR": {
        "definition": "Suspicious Transaction Report. A system for reporting financial transactions suspected of involving illegal assets, money laundering, or terrorist financing to the FIU. Thresholds were abolished in Aug 2013.",
        "source": "07a_STR_System_and_Procedures",
    },
    "CTR": {
        "definition": "Currency Transaction Report. A system for reporting cash transactions of 10 million KRW or more by the same person on the same day to the FIU within 30 days.",
        "source": "06_CTR_Currency_Transaction_Report",
    },
    "RBA": {
        "definition": "Risk-Based Approach. A framework for identifying and assessing ML/TF risks and differentiating management levels according to the risk level.",
        "source": "04_Risk_Assessment_System, FATF Recommendation 1",
    },
    "PEP": {
        "definition": "Politically Exposed Person. Individuals who must be classified as high risk in customer risk assessment.",
        "source": "05a_CDD_Customer_Due_Diligence",
    },
    "MLRO": {
        "definition": "Money Laundering Reporting Officer. The person in charge of anti-money laundering operations at each financial institution, overseeing STR/CTR reporting and CDD.",
        "source": "03c_ML_TF_Risk_Understanding",
    },
    "FATF": {
        "definition": "Financial Action Task Force. An international organization that sets standards for anti-money laundering and combating the financing of terrorism. 40+9 recommendations.",
        "source": "01a_Global_AML_Standard_FATF",
    },
    "FIU": {
        "definition": "Financial Intelligence Unit. Collects and analyzes STR/CTR data and provides it to law enforcement. The Korean FIU is the Korea Financial Intelligence Unit.",
        "source": "07a_STR_System_and_Procedures",
    },
    "KYE": {
        "definition": "Know Your Employee. Procedures to determine the suitability and trustworthiness of employees performing AML tasks.",
        "source": "03c_ML_TF_Risk_Understanding",
    },
    "Structuring": {
        "definition": "Dividing cash transactions below the reporting threshold to avoid CTR. Subject to STR reporting.",
        "source": "06_CTR, 07a_STR",
    },
    "Layering": {
        "definition": "Creating complex transaction paths to conceal the source of funds. The second stage of money laundering.",
        "source": "03a_ML_TF_Risk_Overview",
    },
}

# ---------------------------------------------------------------------------
# STR draft fields (08_STR_보고서양식.md).
#
# Section and field names are the ones `generate_str` writes and the ones the
# tool description documents, so a draft built from either validates. Fields the
# form asks for but HOFINET cannot supply -- names, identity documents, phone
# numbers -- are optional: they are reported separately as items a person has to
# fill in, instead of making every draft invalid.
# ---------------------------------------------------------------------------

STR_REQUIRED_FIELDS = {
    "Header": ["ReportingDate"],
    "I_ReportingInstitution": ["WithdrawalInstitutionCode"],
    "II_Transactor": ["WithdrawalAccountNumber", "ReceivingAccountNumber"],
    "III_TransactionDetails": [
        "TransactionPeriod", "TransactionCount", "TransactionChannel", "TotalAmount_KRW",
    ],
    "VI_TransactionType": ["PrimarySuspicionType"],
    "VII_Narrative": ["SuspicionJudgmentReason"],
}

STR_OPTIONAL_FIELDS = {
    "I_ReportingInstitution": ["InstitutionName", "MLROName", "OfficerName", "OfficerPhone"],
    "II_Transactor": ["Name", "IdType", "IdNumber", "Nationality"],
    "III_TransactionDetails": ["TransactionType", "MaxSingleAmount_KRW"],
    "VII_Narrative": ["OverallOpinion", "SuspicionIntensity_1to5"],
}

# Section names earlier drafts used.
_STR_SECTION_ALIASES = {
    "I_Reporting_Institution": "I_ReportingInstitution",
    "II_Trader_Common": "II_Transactor",
    "II_Trader": "II_Transactor",
    "III_Transaction_Details": "III_TransactionDetails",
    "VI_Transaction_Type": "VI_TransactionType",
    "VII_Narrative_Description": "VII_Narrative",
}

# Placeholders generate_str writes when a field could not be filled in.
_STR_PLACEHOLDERS = {"unknown", "n/a", "none", "-"}


# ---------------------------------------------------------------------------
# HOFINET Transaction Data Mappings (Codes -> English Labels)
#
# Source of truth: _datasets/DATASET.md §4.1, §6.2, §6.3.
# Labels are direct English translations of the HOFINET original Korean
# definitions. Prior to 2026-05-28 these dictionaries held unrelated AML
# categories ("Money Laundering"/"ATM/CD"/...) which did not correspond to
# the HOFINET coding scheme — that regression has been corrected here.
#
# Note: HOFINET fraud_type uses codes 1, 2, 3, 4, 5, 7 (code 6 is unused).
# ---------------------------------------------------------------------------

FRAUD_TYPE_MAP = {
    1: "Sudden Change in Transaction Pattern",
    2: "Transaction with New Counterparty",
    3: "Split Transaction",
    4: "Concurrent Multiple Transactions",
    5: "Same-Day Withdrawal after Large Deposit",
    7: "Late-Night/Early-Morning Bulk Transactions",
}

MEDIA_TYPE_MAP = {
    1: "PC Banking",
    2: "Internet Banking",
    3: "Phone",
    4: "Mobile Phone",
    5: "Per-transaction Transfer",
    6: "Other",
    7: "Bulk Transfer",
}

FUND_TYPE_MAP = {
    0: "General",
    1: "Salary",
    3: "Other",
    4: "Inter-bank Auto Transfer",
}


def translate_fraud_type(code: int) -> str:
    """Translates fraud type code to English label."""
    try:
        return FRAUD_TYPE_MAP.get(int(code), "Other")
    except (ValueError, TypeError):
        return "Other"


def translate_media_type(code: int) -> str:
    """Translates media type code to English label."""
    try:
        return MEDIA_TYPE_MAP.get(int(code), "Other")
    except (ValueError, TypeError):
        return "Other"


def translate_fund_type(code: int) -> str:
    """Translates fund type code to English label."""
    try:
        return FUND_TYPE_MAP.get(int(code), "N/A")
    except (ValueError, TypeError):
        return "N/A"


def lookup_fiu_reference_types(keyword: str, industry: str | None = None) -> list[dict]:
    """Searches the FIU suspicious-transaction reference catalog.

    The catalog is an English excerpt; matching is a case-insensitive substring
    of the industry, category and description of each entry. An empty keyword
    returns every entry of the selected industry.

    Args:
        keyword: Search keyword (e.g., structuring, cash, dormant, virtual asset)
        industry: "banking" | "securities" | None (overall)

    Returns:
        List of matching reference types [{"industry", "category", "no", "description"}, ...]
    """
    keyword = (keyword or "").strip().lower()

    industry_map = {"banking": "Banking", "securities": "Securities", "bank": "Banking", "sec": "Securities"}
    filter_industry = industry_map.get(industry, industry) if industry else None

    results = []
    for item in _FIU_REFERENCE_TYPES:
        if filter_industry and item["industry"] != filter_industry:
            continue
        text = f"{item['industry']} {item['category']} {item['description']}".lower()
        if not keyword or keyword in text:
            results.append(dict(item))
    return results


def _normalize_field(name: str) -> str:
    return str(name).replace("_", "").replace(" ", "").lower()


def _is_filled(value) -> bool:
    """True when a draft field carries content rather than a placeholder."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in _STR_PLACEHOLDERS
    if isinstance(value, (list, tuple, set, dict)):
        return any(_is_filled(v) for v in value) if not isinstance(value, dict) else bool(value)
    return True


def validate_str_fields(str_draft) -> dict:
    """Checks an STR draft for the fields the report form requires.

    Accepts the section layout `generate_str` produces (and the earlier
    `I_Reporting_Institution` style names), a draft serialised as a JSON string,
    and a flat draft with no sections. Field names are matched ignoring case and
    underscores.

    Returns:
        {"valid", "missing_required", "missing_optional", "sections_checked"}
    """
    if isinstance(str_draft, str):
        try:
            str_draft = json.loads(str_draft)
        except ValueError:
            return {
                "valid": False,
                "error": "str_draft must be a JSON object, not free text.",
                "missing_required": [],
                "missing_optional": [],
                "sections_checked": [],
            }
    if not isinstance(str_draft, dict):
        return {
            "valid": False,
            "error": "str_draft must be a JSON object.",
            "missing_required": [],
            "missing_optional": [],
            "sections_checked": [],
        }

    sections = {}
    flat = {}
    for key, value in str_draft.items():
        canonical = _STR_SECTION_ALIASES.get(key, key)
        if isinstance(value, dict):
            sections[canonical] = {_normalize_field(k): v for k, v in value.items()}
        else:
            flat[_normalize_field(key)] = value

    def _lookup(section: str, field: str):
        data = sections.get(section, {})
        key = _normalize_field(field)
        if key in data:
            return data[key]
        return flat.get(key)

    missing_required = [
        f"{section}.{field}"
        for section, fields in STR_REQUIRED_FIELDS.items()
        for field in fields
        if not _is_filled(_lookup(section, field))
    ]
    missing_optional = [
        f"{section}.{field}"
        for section, fields in STR_OPTIONAL_FIELDS.items()
        for field in fields
        if not _is_filled(_lookup(section, field))
    ]

    return {
        "valid": len(missing_required) == 0,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "sections_checked": list(STR_REQUIRED_FIELDS),
    }


def glossary_terms() -> list[str]:
    """Returns every term the glossary defines, in catalog order."""
    return list(_AML_GLOSSARY)


def get_aml_glossary(term: str) -> dict | None:
    """Returns the definition of an AML term.

    The glossary holds 13 English entries and matches the term exactly, ignoring
    case. There are no Korean aliases.

    Args:
        term: Term to lookup (CDD, EDD, STR, CTR, RBA, PEP, MLRO, etc.)

    Returns:
        {"term": str, "definition": str, "source": str} or None
    """
    term_upper = (term or "").strip().upper()
    term_raw = (term or "").strip()
    for key, val in _AML_GLOSSARY.items():
        if key.upper() == term_upper or key == term_raw:
            return {
                "term": key,
                "definition": val["definition"],
                "source": val["source"],
            }
    return None
