"""AML 참조 기능: FIU 의심거래 참고유형, STR 필드 검증, AML 용어집.

_docs 기반으로 AML 업무 담당자를 지원하는 지식 조회 기능을 제공한다.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# FIU 업권별 의심거래 참고유형 (07b_STR_의심거래보고_업권별지표.md 기반)
# ---------------------------------------------------------------------------

_FIU_REFERENCE_TYPES = [
    # 은행업 - 수신거래
    {"industry": "은행업", "category": "수신거래-현금", "no": 1, "description": "합리적인 이유 없이 거액 현금에 의한 입출금 거래가 빈번히 일어나는 거래"},
    {"industry": "은행업", "category": "수신거래-현금", "no": 6, "description": "대체거래를 현금거래로 처리하는 거래"},
    {"industry": "은행업", "category": "수신거래-현금", "no": 10, "description": "자동화기기를 이용하여 입금한 탈세의심거래"},
    {"industry": "은행업", "category": "수신거래-계좌", "no": 11, "description": "단기간에 빈번히 거액이 입출금된 후 해지 또는 장기간 거래가 없다가 거액의 자금이 입출금 되는 거래"},
    {"industry": "은행업", "category": "수신거래-계좌", "no": 12, "description": "실질적으로 타인명의 계좌를 이용하는 거래 (미성년자, 고령자, 신용관리대상자 등)"},
    {"industry": "은행업", "category": "수신거래-계좌", "no": 14, "description": "본인이 합리적 이유 없이 다수의 요구불예금 계좌를 개설하는 거래"},
    {"industry": "은행업", "category": "수신거래-분할", "no": 17, "description": "다수인이 동시에 분할하여 거래하거나, 고액현금거래보고 등을 회피하기 위해 동일인이 일정금액 미만으로 수차례 나누어 입출금하는 거래"},
    {"industry": "은행업", "category": "수신거래-위장", "no": 18, "description": "자금출처 등을 숨길 목적으로 타인명의로 자기앞수표 발행, 타행환송금 등 본인 거래를 타인명의로 위장하는 거래"},
    {"industry": "은행업", "category": "수신거래-기타", "no": 26, "description": "고객정보 제공 요구에 대한 거절/비협조 또는 제공 정보의 불일치 확인"},
    {"industry": "은행업", "category": "수신거래-기타", "no": 28, "description": "당일 거액의 자금을 입금하고 잔액증명서 발급 후 다음날 전액 인출하는 거래"},
    {"industry": "은행업", "category": "수신거래-기타", "no": 30, "description": "사업과 무관한 상대방과 인터넷 뱅킹을 이용한 24시간 대량거래"},
    {"industry": "은행업", "category": "수신거래-기타", "no": 33, "description": "선불카드 또는 상품권 잔액 환불 거래"},
    # 은행업 - 비대면
    {"industry": "은행업", "category": "비대면 거래", "no": 1, "description": "거래 발생건수가 과다하며 심야/새벽시간대를 포함하여 하루 종일 인터넷뱅킹을 이용한 대량거래"},
    {"industry": "은행업", "category": "비대면 거래", "no": 2, "description": "관계를 알 수 없는 상대방으로부터 입금을 받은 자금을 자동화기기를 이용하여 현금 출금"},
    {"industry": "은행업", "category": "비대면 거래", "no": 3, "description": "관계를 알 수 없는 상대방으로부터 입금받은 자금을 제3자에게 이체"},
    {"industry": "은행업", "category": "비대면 거래", "no": 8, "description": "장기간 미사용 계좌를 이용한 고액 이체 거래"},
    {"industry": "은행업", "category": "비대면 거래", "no": 13, "description": "불법 도박사이트로 추정되는 업체와의 빈번한 이체 거래"},
    {"industry": "은행업", "category": "비대면 거래", "no": 17, "description": "고객정보와 상이한 자금흐름 거래"},
    # 은행업 - 가상자산
    {"industry": "은행업", "category": "가상자산거래", "no": 3, "description": "가상자산거래소로부터 영수받은 자금을 비대면 현금출금"},
    {"industry": "은행업", "category": "가상자산거래", "no": 4, "description": "가상자산거래소 관련 계좌로부터 거액 영수 후 불특정 다수에게 송금하는 거래"},
    {"industry": "은행업", "category": "가상자산거래", "no": 18, "description": "국가 간 가상자산 가격 차를 이용한 자금세탁행위 의심거래 (김치프리미엄 등)"},
    # 은행업 - 법인
    {"industry": "은행업", "category": "법인 특수관계자", "no": 1, "description": "법인 계좌와 대표자 개인계좌의 거래"},
    {"industry": "은행업", "category": "법인 특수관계자", "no": 2, "description": "대표자가 동일한 법인 간의 거래"},
    {"industry": "은행업", "category": "법인 특수관계자", "no": 3, "description": "위장법인 계좌를 이용한 거래"},
    # 증권업
    {"industry": "증권업", "category": "입출금(고)", "no": 1, "description": "평상시와 다르게 발생하는 거래액의 입금, 출금 또는 이에 준하는 거래"},
    {"industry": "증권업", "category": "입출금(고)", "no": 2, "description": "합리적 이유없이 일정 금액 미만으로 여러번 나누어 거래하는 분할 거래"},
    {"industry": "증권업", "category": "입출금(고)", "no": 4, "description": "차명으로 거래하거나 타인명의계좌로 이체하는 거래"},
    {"industry": "증권업", "category": "입출금(고)", "no": 13, "description": "실질적인 거래의사 없이 잔고증명서 발급만을 위한 입출금 거래"},
    {"industry": "증권업", "category": "유가증권매매", "no": 6, "description": "주가관리 또는 주가조작 목적으로 일정 기간 특정 주식만을 집중적으로 매매하다가 보유주식을 모두 매도하는 거래"},
    {"industry": "증권업", "category": "비대면", "no": 1, "description": "비대면 계좌개설 후 폐업 또는 신설법인과 거래 및 다수 개인과 거래"},
    {"industry": "증권업", "category": "비대면", "no": 2, "description": "비대면으로 여러 개의 계좌가 단기간에 개설되는 거래"},
]

# ---------------------------------------------------------------------------
# AML 용어집 (_docs 기반)
# ---------------------------------------------------------------------------

_AML_GLOSSARY = {
    "CDD": {
        "definition": "고객확인제도(Customer Due Diligence). 금융회사가 고객의 신원확인·검증, 거래목적·실제소유자 확인 등 고객에 대한 합당한 주의를 기울이는 것. KYC와 혼용.",
        "source": "특정금융정보법, FATF 권고사항",
    },
    "EDD": {
        "definition": "강화된 고객확인(Enhanced Due Diligence). 위험평가 결과 자금세탁위험이 높은 고객·상품에 대해 신원확인 이외 추가 정보를 확인하는 절차.",
        "source": "05a_CDD_고객확인제도",
    },
    "SDD": {
        "definition": "간소화된 고객확인(Simplified Due Diligence). 위험평가 결과 위험이 낮은 고객·상품에 대해 고객확인 절차 일부를 적용하지 않을 수 있음.",
        "source": "05a_CDD_고객확인제도",
    },
    "STR": {
        "definition": "의심거래보고(Suspicious Transaction Report). 불법재산 또는 자금세탁·테러자금조달 의심이 있는 금융거래를 FIU에 보고하는 제도. 2013년 8월부터 보고기준금액 폐지.",
        "source": "07a_STR_의심거래보고_제도및절차",
    },
    "CTR": {
        "definition": "고액현금거래보고(Currency Transaction Report). 동일인·동일일 1,000만원 이상 현금거래를 30일 이내 FIU에 보고하는 제도.",
        "source": "06_CTR_고액현금거래보고",
    },
    "RBA": {
        "definition": "위험기반접근법(Risk Based Approach). ML/TF 위험을 식별·평가하여 위험도에 따라 관리 수준을 차등화하는 업무체계.",
        "source": "04_위험평가제도, FATF 권고사항 1",
    },
    "PEP": {
        "definition": "정치적 주요인물(Politically Exposed Person). 고객위험평가에서 반드시 고위험으로 분류해야 하는 대상.",
        "source": "05a_CDD_고객확인제도",
    },
    "MLRO": {
        "definition": "보고책임자(Money Laundering Reporting Officer). 각 금융회사의 자금세탁방지 업무를 총괄하는 자. STR·CTR 보고, 고객확인 총괄.",
        "source": "03c_ML_TF_위험이해_사례와대응",
    },
    "FATF": {
        "definition": "금융행동특별작업반(Financial Action Task Force). 자금세탁·테러자금조달 방지를 위한 국제기준 수립 기구. 40+9 권고사항.",
        "source": "01a_글로벌_AML_기준_FATF",
    },
    "FIU": {
        "definition": "금융정보분석원(Financial Intelligence Unit). STR·CTR 수집·분석 및 법집행기관 제공. 한국 FIU는 금융정보분석원.",
        "source": "07a_STR_의심거래보고_제도및절차",
    },
    "KYE": {
        "definition": "직원알기 제도(Know Your Employee). AML 업무 수행 직원에 대한 적격성·신뢰성 파악 절차.",
        "source": "03c_ML_TF_위험이해_사례와대응",
    },
    "구조화": {
        "definition": "분할거래(Structuring). CTR 회피 목적으로 기준금액 미만으로 분할하여 현금거래하는 행위. STR 보고 대상.",
        "source": "06_CTR_고액현금거래보고, 07a_STR",
    },
    "레이어링": {
        "definition": "다단계 레이어링(Layering). 자금의 출처를 은닉하기 위해 복잡한 거래 경로를 만드는 자금세탁 2단계.",
        "source": "03a_ML_TF_위험이해_개요와유형",
    },
}

# ---------------------------------------------------------------------------
# STR 필수 필드 (08_STR_보고서양식.md 기반, 핵심만)
# ---------------------------------------------------------------------------

_STR_REQUIRED_FIELDS = {
    "표제부": ["문서번호", "보고일자"],
    "I_보고기관": ["보고기관명", "보고책임자명", "보고담당자명", "보고담당자 전화번호"],
    "II_거래자_공통": ["거래자(사업자)명", "거래자(사업자) 실명번호구분", "거래자(사업자) 실명번호", "거래자(사업자) 국적"],
    "III_거래내역": ["거래발생일시", "거래채널", "거래수단", "거래종류", "거래상품", "통화종류", "관련계좌 존재 여부", "송금/수취계좌 존재 여부", "거래대리인 존재여부"],
}


def lookup_fiu_reference_types(keyword: str, industry: str | None = None) -> list[dict]:
    """FIU 업권별 의심거래 참고유형을 검색한다.

    Args:
        keyword: 검색어 (예: 분할거래, 심야, 비대면, 가상자산)
        industry: "banking" | "securities" | None(전체)

    Returns:
        매칭되는 참고유형 목록 [{"industry", "category", "no", "description"}, ...]
    """
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return []

    industry_map = {"banking": "은행업", "securities": "증권업", "은행": "은행업", "증권": "증권업"}
    filter_industry = industry_map.get(industry, industry) if industry else None

    results = []
    for item in _FIU_REFERENCE_TYPES:
        if filter_industry and item["industry"] != filter_industry:
            continue
        text = f"{item['industry']} {item['category']} {item['description']}".lower()
        if keyword in text:
            results.append(dict(item))
    return results


def validate_str_fields(str_draft: dict) -> dict:
    """STR 초안의 필수 필드 점검을 수행한다.

    Args:
        str_draft: STR 초안 dict. 섹션별로 중첩 가능 (예: {"I_보고기관": {"보고기관명": "..."}})

    Returns:
        {"valid": bool, "missing_required": list[str], "sections_checked": list[str]}
    """
    missing = []
    sections_checked = []

    for section, fields in _STR_REQUIRED_FIELDS.items():
        sections_checked.append(section)
        data = str_draft
        # 중첩 키 지원 (예: "I_보고기관" -> str_draft.get("I_보고기관") or str_draft)
        if isinstance(data, dict) and section in data:
            data = data[section]
        if not isinstance(data, dict):
            for f in fields:
                missing.append(f"{section}.{f}")
            continue
        for f in fields:
            val = data.get(f)
            if val is None or (isinstance(val, str) and not val.strip()):
                missing.append(f"{section}.{f}")

    return {
        "valid": len(missing) == 0,
        "missing_required": missing,
        "sections_checked": sections_checked,
    }


def get_aml_glossary(term: str) -> dict | None:
    """AML 용어의 정의를 반환한다.

    Args:
        term: 조회할 용어 (CDD, EDD, STR, CTR, RBA, PEP, MLRO 등)

    Returns:
        {"term": str, "definition": str, "source": str} 또는 None
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
