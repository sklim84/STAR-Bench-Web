"""기능4: AI 분석 에이전트 모듈.

OpenAI function calling을 활용하여 기능1~3을 도구로 등록하고,
대화를 통해 자금세탁의심거래를 분석하고 STR을 작성한다.
"""

import json
import re
from collections import Counter
from datetime import date

import pandas as pd
from openai import OpenAI

import config
from src.data.db import query
from src.features.dashboard import get_summary, get_fraud_type_distribution
from src.features.detector import load_model
from src.features.network import (
    get_account_ego_network,
    get_account_ego_network_deep,
    detect_ring_transactions,
    detect_layering_patterns,
    detect_funnel_accounts,
    find_shortest_path,
    compute_risk_score,
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_transactions",
            "description": (
                "HOFINET 데이터베이스에 SQL 쿼리를 실행하여 거래 데이터를 조회한다. "
                "테이블명은 hofinet이고 컬럼은 거래일자, 거래시간대, 출금금융회사일련번호, "
                "출금계좌일련번호, 입금금융회사일련번호, 입금계좌일련번호, 자금구분, 매체구분, "
                "거래금액, 이상거래여부, 이상거래유형, 이상거래설명이다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "실행할 SELECT SQL 쿼리. hofinet 테이블에 대해 "
                            "집계, 필터링, 그룹핑 등을 수행한다."
                        ),
                    }
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_fraud",
            "description": "학습된 XGBoost 모델로 거래의 이상거래 확률을 예측한다. 거래 정보를 입력하면 0~1 사이의 확률을 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "거래시간대": {
                        "type": "integer",
                        "description": "3시간 단위 (0, 3, 6, 9, 12, 15, 18, 21 중 하나)",
                    },
                    "출금금융회사일련번호": {"type": "integer"},
                    "입금금융회사일련번호": {"type": "integer"},
                    "자금구분": {
                        "type": "integer",
                        "description": "0, 1, 3, 4 중 하나",
                    },
                    "매체구분": {
                        "type": "integer",
                        "description": "1~7 중 하나",
                    },
                    "거래금액": {
                        "type": "integer",
                        "description": "원 단위 금액 (양의 정수)",
                    },
                },
                "required": [
                    "거래시간대",
                    "출금금융회사일련번호",
                    "입금금융회사일련번호",
                    "자금구분",
                    "매체구분",
                    "거래금액",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_str",
            "description": (
                "분석 결과를 기반으로 의심거래보고서(STR) 공식 양식(I~VII섹션)에 맞게 작성한다. "
                "STR 작성 전에 반드시 query_transactions로 관련 거래 데이터를 먼저 조회하고, "
                "조회한 거래 레코드를 transactions 파라미터에 포함하여 호출할 것."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "분석 결과 요약 및 혐의 판단 사유 (의심 사유, 거래 패턴, 수치 등 구체적으로 기술)",
                    },
                    "fraud_type": {
                        "type": "string",
                        "description": "HOFINET 이상거래유형 분류",
                        "enum": ["자금세탁", "대포통장", "보이스피싱", "불법도박", "유사수신", "신규거래처", "기타"],
                    },
                    "transactions": {
                        "type": "array",
                        "description": "query_transactions 결과에서 가져온 관련 거래 레코드 목록. 계좌·금액·날짜·채널 자동 추출에 사용됨.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "거래일자": {"type": "integer"},
                                "거래시간대": {"type": "integer"},
                                "출금금융회사일련번호": {"type": "integer"},
                                "출금계좌일련번호": {"type": "integer"},
                                "입금금융회사일련번호": {"type": "integer"},
                                "입금계좌일련번호": {"type": "integer"},
                                "자금구분": {"type": "integer"},
                                "매체구분": {"type": "integer"},
                                "거래금액": {"type": "integer"},
                                "이상거래유형": {"type": "integer"},
                            },
                        },
                    },
                    "fraud_probability": {
                        "type": "number",
                        "description": "predict_fraud 도구로 예측한 이상거래 확률 (0.0~1.0). 의심 강도(1~5) 산출에 사용됨.",
                    },
                    "aml_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "detect_aml_patterns로 탐지된 AML 패턴 목록 (예: ['순환거래', '레이어링'])",
                    },
                    "tools_used": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "분석에 사용된 도구 목록 (예: ['query_transactions', 'predict_fraud', 'analyze_network'])",
                    },
                },
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_network",
            "description": "특정 계좌의 거래 네트워크를 분석한다. 계좌 번호를 입력하면 연결된 계좌 수, 거래 횟수, 이상거래 관련 여부를 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "분석할 계좌 번호 (출금계좌일련번호)",
                    },
                    "hops": {
                        "type": "integer",
                        "description": "탐색 범위 (1~5). 기본값은 1. 3 이상은 Memgraph 필요.",
                        "default": 1,
                    },
                },
                "required": ["account_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_statistics",
            "description": "대시보드 요약 통계를 조회한다. 전체 거래 건수, 이상거래 건수/비율, 이상거래 유형별 분포 등 기본 통계를 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_profile",
            "description": (
                "특정 계좌의 거래 통계 프로파일을 조회한다. "
                "총 거래 건수/금액, 이상거래 건수/비율, 주요 거래 시간대, "
                "주 사용 매체, 상위 거래 상대 계좌 5개를 반환한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "조회할 계좌 번호 (출금계좌일련번호 기준)",
                    }
                },
                "required": ["account_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fraud_type_summary",
            "description": (
                "이상거래 유형별(자금세탁/보이스피싱/대포통장 등) 현황을 조회한다. "
                "유형 이름 또는 코드(1~7)로 필터하면 건수·금액 통계와 상위 금융회사를 반환한다. "
                "코드 매핑: 1=자금세탁, 2=신규거래처, 3=대포통장, 4=보이스피싱, 5=불법도박, 6=유사수신, 7=기타"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fraud_type": {
                        "type": "integer",
                        "description": "이상거래유형 코드 (1~7)",
                        "enum": [1, 2, 3, 4, 5, 6, 7],
                    },
                    "bank_id": {
                        "type": "integer",
                        "description": "출금금융회사일련번호 필터 (선택). 지정 시 해당 금융회사의 거래만 조회.",
                    },
                },
                "required": ["fraud_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": (
                "두 기간의 거래·이상거래 통계를 비교하고 변화율(delta)을 반환한다. "
                "기간별 거래 건수, 이상거래 건수, 평균 거래금액과 증감률을 산출한다. "
                "분기 비교, 월간 비교, 특정 이벤트 전후 비교에 활용한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period1_start": {
                        "type": "integer",
                        "description": "첫 번째 기간 시작일 (YYYYMMDD 정수, 예: 20240101)",
                    },
                    "period1_end": {
                        "type": "integer",
                        "description": "첫 번째 기간 종료일 (YYYYMMDD 정수, 예: 20240331)",
                    },
                    "period2_start": {
                        "type": "integer",
                        "description": "두 번째 기간 시작일 (YYYYMMDD 정수, 예: 20240401)",
                    },
                    "period2_end": {
                        "type": "integer",
                        "description": "두 번째 기간 종료일 (YYYYMMDD 정수, 예: 20240630)",
                    },
                },
                "required": ["period1_start", "period1_end", "period2_start", "period2_end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_institution_report",
            "description": (
                "특정 금융회사의 종합 현황을 보고한다. "
                "거래 규모(건수·금액), 이상거래 비율, 상위 거래 상대 기관, "
                "주요 이상거래 유형별 분포, 최근 분기 추이를 반환한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bank_id": {
                        "type": "integer",
                        "description": "조회할 금융회사일련번호 (출금금융회사일련번호 기준)",
                    }
                },
                "required": ["bank_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_risky_transactions",
            "description": (
                "학습된 XGBoost 모델로 데이터베이스에서 샘플 거래를 일괄 예측하여 "
                "위험도 상위 K건을 반환한다. 대규모 탐지 및 우선순위 설정에 활용한다. "
                "모델이 없으면 오류를 반환한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_size": {
                        "type": "integer",
                        "description": "예측할 샘플 건수 (기본 1000, 최대 5000)",
                        "default": 1000,
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "반환할 상위 위험 거래 건수 (기본 20, 최대 100)",
                        "default": 20,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_aml_patterns",
            "description": (
                "Memgraph 그래프 DB를 활용하여 AML(자금세탁방지) 패턴을 탐지한다. "
                "순환거래(ring), 다단계 레이어링, 대포통장(funnel) 패턴을 탐지하거나, "
                "두 계좌 간 최단경로를 찾거나, 계좌의 위험도 점수를 산출한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern_type": {
                        "type": "string",
                        "description": "탐지할 패턴 유형",
                        "enum": ["ring", "layering", "funnel", "shortest_path", "risk_score"],
                    },
                    "account_id": {
                        "type": "integer",
                        "description": "분석 대상 계좌 번호 (risk_score 시 필수)",
                    },
                    "account_a": {
                        "type": "integer",
                        "description": "출발 계좌 (shortest_path 시 필수)",
                    },
                    "account_b": {
                        "type": "integer",
                        "description": "도착 계좌 (shortest_path 시 필수)",
                    },
                    "min_len": {
                        "type": "integer",
                        "description": "순환 최소 길이 (ring 시, 기본 3)",
                        "default": 3,
                    },
                    "max_len": {
                        "type": "integer",
                        "description": "순환 최대 길이 (ring 시, 기본 6)",
                        "default": 6,
                    },
                    "min_layers": {
                        "type": "integer",
                        "description": "최소 레이어 수 (layering 시, 기본 3)",
                        "default": 3,
                    },
                    "min_inflow": {
                        "type": "integer",
                        "description": "최소 입금 계좌 수 (funnel 시, 기본 10)",
                        "default": 10,
                    },
                    "max_outflow": {
                        "type": "integer",
                        "description": "최대 출금 계좌 수 (funnel 시, 기본 3)",
                        "default": 3,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "최대 결과 수 (기본 20)",
                        "default": 20,
                    },
                },
                "required": ["pattern_type"],
            },
        },
    },
]

SYSTEM_PROMPT = """당신은 자금세탁방지(AML) 전문 분석가입니다.
HOFINET(전자금융공동망) 이상거래탐지 데이터를 분석하여 자금세탁의심거래를 탐지하고 보고합니다.

사용 가능한 도구:
1. get_statistics: 전체 거래 요약 통계 및 이상거래 유형별 분포 조회 (분석 시작 시 가장 먼저 사용)
2. query_transactions: HOFINET DB에 SQL 쿼리를 실행하여 거래 통계, 패턴, 특정 계좌 거래 내역 등을 상세 조회
3. get_account_profile: 특정 계좌의 거래 통계 프로파일 조회 (건수/금액/이상거래비율/주요시간대/상위거래상대)
4. get_fraud_type_summary: 이상거래유형별 현황 조회 (건수·금액 통계, 상위 금융회사). 코드: 1=자금세탁, 2=신규거래처, 3=대포통장, 4=보이스피싱, 5=불법도박, 6=유사수신, 7=기타
5. compare_periods: 두 기간의 거래·이상거래 통계 비교 및 증감률 산출 (분기 비교, 월간 비교)
6. get_institution_report: 특정 금융회사의 종합 현황 보고 (거래규모, 이상거래비율, 상위거래상대, 유형분포)
7. rank_risky_transactions: XGBoost 모델 배치 예측으로 위험도 상위 K건 랭킹 반환
8. analyze_network: 특정 계좌의 거래 네트워크를 분석하여 연결 계좌 수, 이상거래 관련 여부 파악 (N-hop 심층 탐색 지원)
9. detect_aml_patterns: Memgraph 그래프 DB를 활용한 AML 패턴 탐지 (순환거래, 레이어링, 대포통장, 최단경로, 위험도 산출)
10. predict_fraud: XGBoost 모델로 특정 거래의 이상거래 확률을 예측
11. generate_str: 분석 결과를 의심거래보고서(STR) 양식으로 작성

권장 분석 절차:
1. get_statistics로 전체 현황 파악
2. query_transactions으로 의심 거래 상세 조회
3. analyze_network으로 계좌 네트워크 분석 (N-hop 심층 탐색 지원)
4. detect_aml_patterns으로 순환거래/레이어링/대포통장 패턴 탐지
5. predict_fraud로 이상거래 확률 예측
6. 충분한 근거가 확보된 경우에만 generate_str로 STR 작성

STR 작성 시 주의사항:
- 반드시 query_transactions로 근거 데이터를 먼저 조회한 후 STR을 작성하세요
- 조회한 거래 레코드를 transactions 파라미터에 담아 generate_str을 호출하면 계좌·금액·채널이 자동 추출됩니다
- predict_fraud 결과가 있으면 fraud_probability에 확률값을 전달하세요
- detect_aml_patterns 탐지 결과가 있으면 aml_patterns에 포함하세요

데이터 스키마:
- 테이블: hofinet (4,732,130건)
- 컬럼: 거래일자(YYYYMMDD), 거래시간대(0~21, 3시간단위), 출금금융회사일련번호, 출금계좌일련번호, 입금금융회사일련번호, 입금계좌일련번호, 자금구분(0,1,3,4), 매체구분(1~7), 거래금액, 이상거래여부(0/1), 이상거래유형(1~7), 이상거래설명

이상거래유형: 1=자금세탁, 2=신규거래처(최다 63.87%), 3=대포통장, 4=보이스피싱, 5=불법도박, 6=유사수신, 7=기타
매체구분: 1=창구, 2=자동화기기(ATM), 3=PB센터, 4=인터넷뱅킹, 5=전화/휴대전화, 6=콜센터, 7=기타
자금구분: 0=해당없음, 1=입금, 3=출금, 4=이체

한국어로 응답하세요. 분석 시 구체적인 수치와 근거를 제시하세요."""


# ---------------------------------------------------------------------------
# 파라미터 유효성 검증 헬퍼
# ---------------------------------------------------------------------------

_VALID_시간대 = {0, 3, 6, 9, 12, 15, 18, 21}
_VALID_자금구분 = {0, 1, 3, 4}
_VALID_매체구분 = set(range(1, 8))


def _validate_predict_fraud_args(arguments: dict) -> list[str]:
    """predict_fraud 파라미터 유효성을 검사하고 오류 메시지 목록을 반환한다."""
    errors = []
    시간대 = arguments.get("거래시간대")
    if 시간대 not in _VALID_시간대:
        errors.append(f"거래시간대({시간대})는 {sorted(_VALID_시간대)} 중 하나여야 합니다.")
    자금구분 = arguments.get("자금구분")
    if 자금구분 not in _VALID_자금구분:
        errors.append(f"자금구분({자금구분})은 {sorted(_VALID_자금구분)} 중 하나여야 합니다.")
    매체구분 = arguments.get("매체구분")
    if 매체구분 not in _VALID_매체구분:
        errors.append(f"매체구분({매체구분})은 1~7 중 하나여야 합니다.")
    금액 = arguments.get("거래금액")
    if not isinstance(금액, (int, float)) or 금액 <= 0:
        errors.append(f"거래금액({금액})은 양의 정수여야 합니다.")
    return errors


# ---------------------------------------------------------------------------
# STR 구조화 헬퍼 -코드 매핑 테이블
# ---------------------------------------------------------------------------

_매체구분_MAP = {
    1: "창구", 2: "자동화기기(ATM)", 3: "PB센터",
    4: "인터넷뱅킹", 5: "전화/휴대전화", 6: "콜센터", 7: "기타",
}

_자금구분_MAP = {0: "해당없음", 1: "입금", 3: "출금", 4: "이체"}

_이상거래유형_MAP = {
    1: "자금세탁", 2: "신규거래처", 3: "대포통장",
    4: "보이스피싱", 5: "불법도박", 6: "유사수신", 7: "기타",
}

# 이상거래유형 코드 → STR VI섹션 의심거래유형 체크항목 매핑
_유형_to_VI항목 = {
    1: ["분할거래", "갑작스러운 거래패턴의 변화"],
    2: ["사전거래가 없는 고객의 의심스러운 거래 요청"],
    3: ["타인의 명의 또는 계좌의 이용", "단발성 계좌의 이용"],
    4: ["거액 입금 후 당일 또는 익일 중 인출", "빈번한 입출금(입출고)"],
    5: ["빈번한 입출금(입출고)", "갑작스러운 거래패턴의 변화"],
    6: ["다중거래의 동시요청", "단발성 계좌의 이용"],
}

_권고조치_MAP = {
    "자금세탁":   ["거래 패턴 모니터링 강화", "관련 계좌 추가 조사", "금융정보분석원(FIU) 보고 검토"],
    "대포통장":   ["계좌 즉시 모니터링", "계좌주 실명 확인", "수사기관 의뢰 검토"],
    "보이스피싱": ["관련 계좌 즉시 동결 검토", "피해자 확인 및 보호 조치", "수사기관 의뢰"],
    "불법도박":   ["거래 패턴 지속 모니터링", "관계 기관 신고 검토", "계좌 거래 제한 검토"],
    "유사수신":   ["투자자 피해 확인", "관계 기관 신고", "계좌 동결 검토"],
    "신규거래처": ["고객 실사(CDD) 강화", "추가 거래 모니터링"],
    "기타":       ["추가 모니터링 실시", "거래 내역 보존", "내부 심사 위원회 검토"],
}

# AML 패턴 이름 → STR VI섹션 체크항목 매핑
_패턴_VI항목_MAP = {
    "순환거래": "분할거래",
    "레이어링": "갑작스러운 거래패턴의 변화",
    "대포통장": "타인의 명의 또는 계좌의 이용",
}

_도구설명_MAP = {
    "query_transactions":    "HOFINET DB 거래 데이터 직접 조회",
    "predict_fraud":         "XGBoost 이상거래 확률 모델 예측",
    "analyze_network":       "계좌 거래 네트워크 분석",
    "get_statistics":        "전체 통계 대시보드 조회",
    "get_account_profile":   "계좌 거래 통계 프로파일 조회",
    "get_fraud_type_summary": "이상거래유형별 현황 조회",
    "detect_aml_patterns":   "Memgraph 그래프 DB AML 패턴 탐지",
    "compare_periods":        "기간별 거래 통계 비교 분석",
    "get_institution_report": "금융회사 종합 현황 보고",
    "rank_risky_transactions": "XGBoost 모델 배치 예측 위험도 랭킹",
    "generate_str":          "STR 보고서 생성",
}


def _build_str_report(
    summary: str,
    fraud_type: str,
    tools_used: list[str],
    transactions: list[dict],
    fraud_probability: float | None,
    aml_patterns: list[str],
) -> dict:
    """공식 STR 양식(I~VII 섹션)에 맞는 구조화된 보고서 딕셔너리를 생성한다."""
    today = date.today().strftime("%Y-%m-%d")

    # ── 거래 데이터에서 필드 추출 ──────────────────────────────────────────
    tx = transactions or []

    tx_dates = sorted({str(t.get("거래일자", "")) for t in tx if t.get("거래일자")})
    출금계좌목록 = list({str(t["출금계좌일련번호"]) for t in tx if t.get("출금계좌일련번호")})
    입금계좌목록 = list({str(t["입금계좌일련번호"]) for t in tx if t.get("입금계좌일련번호")})
    출금회사목록 = list({str(t["출금금융회사일련번호"]) for t in tx if t.get("출금금융회사일련번호")})
    입금회사목록 = list({str(t["입금금융회사일련번호"]) for t in tx if t.get("입금금융회사일련번호")})

    매체카운트 = Counter(t.get("매체구분") for t in tx if t.get("매체구분"))
    거래채널 = _매체구분_MAP.get(
        매체카운트.most_common(1)[0][0] if 매체카운트 else None, "미확인"
    )

    자금카운트 = Counter(t.get("자금구분") for t in tx if t.get("자금구분") is not None)
    거래종류 = _자금구분_MAP.get(
        자금카운트.most_common(1)[0][0] if 자금카운트 else None, "미확인"
    )

    총거래금액 = sum(t.get("거래금액", 0) for t in tx)
    최대단건금액 = max((t.get("거래금액", 0) for t in tx), default=0)

    유형카운트 = Counter(t.get("이상거래유형") for t in tx if t.get("이상거래유형"))
    주요유형코드 = 유형카운트.most_common(1)[0][0] if 유형카운트 else None
    주요유형명 = _이상거래유형_MAP.get(주요유형코드, fraud_type or "기타")

    # summary regex 폴백 (transactions 없을 때)
    if not tx:
        account_candidates = re.findall(r"(?:계좌|출금계좌|입금계좌)[^\d]*(\d{5,})", summary)
        출금계좌목록 = 입금계좌목록 = list(set(account_candidates))

    # ── VI. 의심거래유형 체크항목 ──────────────────────────────────────────
    vi_항목 = list(_유형_to_VI항목.get(주요유형코드, []))
    for p in (aml_patterns or []):
        for k, v in _패턴_VI항목_MAP.items():
            if k in p and v not in vi_항목:
                vi_항목.append(v)
    if not vi_항목:
        vi_항목 = ["기타 특징 및 유형 -VII 서술부 참조"]

    # ── VII. 의심 강도 (1~5) ──────────────────────────────────────────────
    if fraud_probability is not None:
        의심강도 = min(5, max(1, round(fraud_probability * 4) + 1))
        의심강도_설명 = f"AI 모델 예측 확률 {fraud_probability:.1%} 기반"
    else:
        의심강도 = 3
        의심강도_설명 = "AI 예측 미수행 -담당자 판단 필요"

    거래기간 = (
        f"{tx_dates[0]} ~ {tx_dates[-1]}" if len(tx_dates) > 1
        else (tx_dates[0] if tx_dates else "미확인")
    )
    관련계좌수 = len(set(출금계좌목록) | set(입금계좌목록))

    종합의견 = (
        f"[{today}] {주요유형명} 의심거래 탐지. "
        f"거래기간 {거래기간}, 관련 계좌 {관련계좌수}개, "
        f"총 거래금액 {총거래금액:,}원({len(tx)}건)."
    )
    if aml_patterns:
        종합의견 += f" 탐지된 AML 패턴: {', '.join(aml_patterns)}."
    종합의견 += " 담당자 검토 후 FIU 보고 여부 결정 요망."

    분석근거 = [_도구설명_MAP.get(t, t) for t in (tools_used or [])]
    권고조치 = _권고조치_MAP.get(주요유형명, _권고조치_MAP["기타"])

    return {
        "보고서유형": "의심거래보고서(STR)",
        "표제부": {
            "보고일자": today,
            "보고서구분": "신규보고",
        },
        "I_보고기관": {
            "출금금융회사코드": 출금회사목록 or ["미확인"],
            "비고": "금융회사일련번호 기준. 기관명은 담당자 확인 필요",
        },
        "II_거래자": {
            "출금계좌번호": 출금계좌목록[:5] or ["미확인"],
            "입금계좌번호": 입금계좌목록[:5] or ["미확인"],
            "비고": "실명·주소·연락처는 HOFINET 미포함 -담당자 별도 확인 필요",
        },
        "III_거래내역": {
            "거래기간": 거래기간,
            "거래건수": len(tx),
            "거래채널": 거래채널,
            "거래종류": 거래종류,
            "총거래금액_원": 총거래금액,
            "최대단건금액_원": 최대단건금액,
            "관련계좌존재여부": "여" if 관련계좌수 > 0 else "부",
        },
        "IV_관련계좌": {
            "출금계좌목록": 출금계좌목록[:10],
            "입금계좌목록": 입금계좌목록[:10],
            "출금금융회사코드": 출금회사목록,
            "입금금융회사코드": 입금회사목록,
        },
        "VI_거래유형": {
            "주요의심유형": 주요유형명,
            "해당항목": vi_항목,
            "탐지된AML패턴": aml_patterns or [],
        },
        "VII_서술": {
            "의심거래자관련": (
                f"출금계좌 {', '.join(출금계좌목록[:3])} 등 "
                f"입금계좌 {', '.join(입금계좌목록[:3])} 관련 의심 거래 확인."
                if 출금계좌목록 or 입금계좌목록 else "거래자 정보 미확인 -담당자 확인 필요"
            ),
            "거래발생일자": 거래기간,
            "거래방법특이사항": f"주요 채널: {거래채널} / 거래 종류: {거래종류}",
            "혐의판단사유": summary,
            "종합의견": 종합의견,
            "의심강도_1to5": 의심강도,
            "의심강도설명": 의심강도_설명,
        },
        "권고조치": 권고조치,
        "분석근거": 분석근거 or ["분석 도구 미지정"],
        "작성안내": (
            "본 보고서는 AI 분석 에이전트가 자동 생성한 초안입니다. "
            "실명·주소·연락처 등 HOFINET 미포함 항목은 담당자가 보완하고 검토 후 제출하시기 바랍니다."
        ),
    }


# ---------------------------------------------------------------------------
# 도구 실행
# ---------------------------------------------------------------------------

def _execute_tool(name: str, arguments: dict) -> str:
    """도구를 실행하고 결과를 JSON 문자열로 반환한다.

    모든 예외는 내부에서 처리하여 JSON 에러 메시지를 반환하므로
    호출부에서 별도 try/except 없이 사용할 수 있다.
    """
    try:
        if name == "query_transactions":
            return _tool_query_transactions(arguments)
        elif name == "predict_fraud":
            return _tool_predict_fraud(arguments)
        elif name == "generate_str":
            return _tool_generate_str(arguments)
        elif name == "analyze_network":
            return _tool_analyze_network(arguments)
        elif name == "get_statistics":
            return _tool_get_statistics()
        elif name == "get_account_profile":
            return _tool_get_account_profile(arguments)
        elif name == "get_fraud_type_summary":
            return _tool_get_fraud_type_summary(arguments)
        elif name == "compare_periods":
            return _tool_compare_periods(arguments)
        elif name == "get_institution_report":
            return _tool_get_institution_report(arguments)
        elif name == "rank_risky_transactions":
            return _tool_rank_risky_transactions(arguments)
        elif name == "detect_aml_patterns":
            return _tool_detect_aml_patterns(arguments)
        else:
            return json.dumps({"error": f"알 수 없는 도구: {name}"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {"error": f"도구 실행 중 예기치 못한 오류가 발생했습니다: {str(exc)}"},
            ensure_ascii=False,
        )


def _tool_query_transactions(arguments: dict) -> str:
    sql = arguments.get("sql", "").strip()

    if not sql:
        return json.dumps({"error": "SQL 쿼리가 비어 있습니다."}, ensure_ascii=False)

    # SELECT만 허용 (SQL 인젝션 방지)
    if not sql.upper().startswith("SELECT"):
        return json.dumps({"error": "SELECT 쿼리만 실행 가능합니다."}, ensure_ascii=False)

    # 위험 키워드 차단
    forbidden = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE"]
    sql_upper = sql.upper()
    for kw in forbidden:
        if kw in sql_upper:
            return json.dumps(
                {"error": f"'{kw}' 키워드가 포함된 쿼리는 실행할 수 없습니다."},
                ensure_ascii=False,
            )

    try:
        df = query(sql)
    except Exception as exc:
        # DuckDB 오류를 사용자 친화적 메시지로 변환
        err_msg = str(exc)
        if "Catalog Error" in err_msg or "does not exist" in err_msg:
            return json.dumps(
                {"error": "테이블 또는 컬럼을 찾을 수 없습니다. 컬럼명이 한글인지 확인하세요."},
                ensure_ascii=False,
            )
        if "Parser Error" in err_msg or "SyntaxError" in err_msg:
            return json.dumps(
                {"error": f"SQL 문법 오류입니다: {err_msg[:200]}"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"error": f"쿼리 실행 오류: {err_msg[:300]}"},
            ensure_ascii=False,
        )

    if df is None or df.empty:
        return json.dumps({"결과": [], "안내": "조회된 데이터가 없습니다."}, ensure_ascii=False)

    # 결과가 너무 크면 상위 100건으로 제한
    total = len(df)
    if total > 100:
        df = df.head(100)
        result = json.loads(df.to_json(orient="records", force_ascii=False))
        return json.dumps(
            {"결과": result, "총건수": total, "안내": f"총 {total}건 중 상위 100건만 반환합니다."},
            ensure_ascii=False,
        )

    return df.to_json(orient="records", force_ascii=False)


def _tool_predict_fraud(arguments: dict) -> str:
    # 파라미터 유효성 검증
    errors = _validate_predict_fraud_args(arguments)
    if errors:
        return json.dumps(
            {"error": "입력 파라미터 오류", "상세": errors},
            ensure_ascii=False,
        )

    model = load_model()
    if model is None:
        return json.dumps(
            {"error": "학습된 모델이 없습니다. Detection 페이지에서 모델을 먼저 학습하세요."},
            ensure_ascii=False,
        )

    try:
        features = pd.DataFrame([arguments])
        prob = model.predict_proba(features)[:, 1][0]
        level = "높음" if prob >= 0.7 else ("중간" if prob >= 0.3 else "낮음")
        return json.dumps(
            {
                "이상거래확률": round(float(prob), 4),
                "위험도": level,
                "입력값": arguments,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {"error": f"모델 예측 오류: {str(exc)}"},
            ensure_ascii=False,
        )


def _tool_generate_str(arguments: dict) -> str:
    summary = arguments.get("summary", "").strip()
    if not summary:
        return json.dumps({"error": "STR 작성을 위한 요약 내용이 비어 있습니다."}, ensure_ascii=False)

    report = _build_str_report(
        summary=summary,
        fraud_type=arguments.get("fraud_type", "기타"),
        tools_used=arguments.get("tools_used", []),
        transactions=arguments.get("transactions", []),
        fraud_probability=arguments.get("fraud_probability"),
        aml_patterns=arguments.get("aml_patterns", []),
    )
    return json.dumps(report, ensure_ascii=False)


def _tool_analyze_network(arguments: dict) -> str:
    account_id = arguments.get("account_id")
    if account_id is None:
        return json.dumps({"error": "account_id가 필요합니다."}, ensure_ascii=False)

    hops = max(1, min(int(arguments.get("hops", 1)), 5))

    try:
        if hops > 2:
            df = get_account_ego_network_deep(account_id, hops=hops)
        else:
            df = get_account_ego_network(account_id, hops=hops)
    except Exception as exc:
        return json.dumps(
            {"error": f"네트워크 조회 오류: {str(exc)}"},
            ensure_ascii=False,
        )

    if df is None or df.empty:
        return json.dumps(
            {
                "account_id": account_id,
                "안내": "해당 계좌의 거래 내역이 없습니다.",
                "연결계좌수": 0,
                "총거래건수": 0,
                "이상거래건수": 0,
                "이상거래비율": 0.0,
            },
            ensure_ascii=False,
        )

    # ego 네트워크에서 계좌 번호 집합 수집
    all_accounts = set(df["source"].tolist()) | set(df["target"].tolist())
    all_accounts.discard(account_id)
    연결계좌수 = len(all_accounts)

    총거래건수 = int(df["거래횟수"].sum())
    이상거래건수 = int(df["이상거래여부"].sum()) if "이상거래여부" in df.columns else 0
    이상거래비율 = round(이상거래건수 / 총거래건수 * 100, 2) if 총거래건수 > 0 else 0.0
    총금액 = int(df["총금액"].sum()) if "총금액" in df.columns else 0

    # 연결된 계좌 샘플 (최대 10개)
    sample_accounts = sorted(list(all_accounts))[:10]

    return json.dumps(
        {
            "account_id": account_id,
            "탐색범위_hop": hops,
            "연결계좌수": 연결계좌수,
            "총거래건수": 총거래건수,
            "이상거래건수": 이상거래건수,
            "이상거래비율_percent": 이상거래비율,
            "총거래금액": 총금액,
            "연결계좌_샘플": sample_accounts,
        },
        ensure_ascii=False,
    )


def _tool_detect_aml_patterns(arguments: dict) -> str:
    pattern_type = arguments.get("pattern_type", "")

    if pattern_type == "ring":
        try:
            df = detect_ring_transactions(
                min_len=arguments.get("min_len", 3),
                max_len=arguments.get("max_len", 6),
                limit=arguments.get("limit", 20),
            )
        except Exception as exc:
            return json.dumps({"error": f"순환거래 탐지 오류: {str(exc)}"}, ensure_ascii=False)

        if df.empty:
            return json.dumps(
                {
                    "안내": "순환거래 패턴이 탐지되지 않았습니다. Memgraph가 실행 중인지 확인하세요.",
                    "결과": [],
                },
                ensure_ascii=False,
            )
        records = df.to_dict(orient="records")
        return json.dumps(
            {"패턴": "순환거래", "건수": len(records), "결과": records},
            ensure_ascii=False,
        )

    elif pattern_type == "layering":
        try:
            df = detect_layering_patterns(
                min_layers=arguments.get("min_layers", 3),
                limit=arguments.get("limit", 20),
            )
        except Exception as exc:
            return json.dumps({"error": f"레이어링 패턴 탐지 오류: {str(exc)}"}, ensure_ascii=False)

        if df.empty:
            return json.dumps(
                {
                    "안내": "레이어링 패턴이 탐지되지 않았습니다. Memgraph가 실행 중인지 확인하세요.",
                    "결과": [],
                },
                ensure_ascii=False,
            )
        records = df.to_dict(orient="records")
        return json.dumps(
            {"패턴": "다단계 레이어링", "건수": len(records), "결과": records},
            ensure_ascii=False,
        )

    elif pattern_type == "funnel":
        try:
            df = detect_funnel_accounts(
                min_inflow=arguments.get("min_inflow", 10),
                max_outflow=arguments.get("max_outflow", 3),
                limit=arguments.get("limit", 20),
            )
        except Exception as exc:
            return json.dumps({"error": f"대포통장 패턴 탐지 오류: {str(exc)}"}, ensure_ascii=False)

        if df.empty:
            return json.dumps(
                {
                    "안내": "대포통장 패턴이 탐지되지 않았습니다. Memgraph가 실행 중인지 확인하세요.",
                    "결과": [],
                },
                ensure_ascii=False,
            )
        records = df.to_dict(orient="records")
        return json.dumps(
            {"패턴": "대포통장(funnel)", "건수": len(records), "결과": records},
            ensure_ascii=False,
        )

    elif pattern_type == "shortest_path":
        account_a = arguments.get("account_a")
        account_b = arguments.get("account_b")
        if not account_a or not account_b:
            return json.dumps(
                {"error": "shortest_path에는 account_a와 account_b가 필요합니다."},
                ensure_ascii=False,
            )
        try:
            result = find_shortest_path(account_a, account_b)
        except Exception as exc:
            return json.dumps({"error": f"최단경로 탐색 오류: {str(exc)}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    elif pattern_type == "risk_score":
        account_id = arguments.get("account_id")
        if not account_id:
            return json.dumps(
                {"error": "risk_score에는 account_id가 필요합니다."},
                ensure_ascii=False,
            )
        try:
            result = compute_risk_score(account_id)
        except Exception as exc:
            return json.dumps({"error": f"위험도 점수 산출 오류: {str(exc)}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    else:
        return json.dumps(
            {"error": f"알 수 없는 패턴 유형: {pattern_type}. 유효한 값: ring, layering, funnel, shortest_path, risk_score"},
            ensure_ascii=False,
        )


def _tool_get_statistics() -> str:
    try:
        summary_df = get_summary()
        fraud_type_df = get_fraud_type_distribution()
    except Exception as exc:
        return json.dumps(
            {"error": f"통계 조회 오류: {str(exc)}"},
            ensure_ascii=False,
        )

    if summary_df is None or summary_df.empty:
        return json.dumps({"error": "요약 통계를 조회할 수 없습니다."}, ensure_ascii=False)

    row = summary_df.iloc[0]
    summary_dict = {
        "총거래건수": int(row.get("총거래", 0)),
        "이상거래건수": int(row.get("이상거래", 0)),
        "이상거래비율_percent": float(row.get("이상거래비율", 0.0)),
        "출금계좌수": int(row.get("출금계좌수", 0)),
        "입금계좌수": int(row.get("입금계좌수", 0)),
        "출금금융회사수": int(row.get("출금금융회사수", 0)),
        "입금금융회사수": int(row.get("입금금융회사수", 0)),
        "총거래금액": int(row.get("총거래금액", 0)),
    }

    if fraud_type_df is not None and not fraud_type_df.empty:
        fraud_types = fraud_type_df.to_dict(orient="records")
    else:
        fraud_types = []

    return json.dumps(
        {"요약통계": summary_dict, "이상거래유형별분포": fraud_types},
        ensure_ascii=False,
    )


def _tool_get_account_profile(arguments: dict) -> str:
    account_id = arguments.get("account_id")
    if account_id is None:
        return json.dumps({"error": "account_id가 필요합니다."}, ensure_ascii=False)

    try:
        aid = int(account_id)
    except (TypeError, ValueError):
        return json.dumps({"error": "account_id는 정수여야 합니다."}, ensure_ascii=False)

    try:
        # 기본 집계: 출금 방향
        out_df = query(
            "SELECT COUNT(*) AS cnt, SUM(거래금액) AS total_amount, "
            "SUM(이상거래여부) AS fraud_cnt "
            "FROM hofinet WHERE 출금계좌일련번호 = $aid",
            {"aid": aid},
        )
        # 입금 방향
        in_df = query(
            "SELECT COUNT(*) AS cnt, SUM(거래금액) AS total_amount, "
            "SUM(이상거래여부) AS fraud_cnt "
            "FROM hofinet WHERE 입금계좌일련번호 = $aid",
            {"aid": aid},
        )

        out_row = out_df.iloc[0] if out_df is not None and not out_df.empty else None
        in_row = in_df.iloc[0] if in_df is not None and not in_df.empty else None

        total_count = int((out_row["cnt"] if out_row is not None else 0) +
                          (in_row["cnt"] if in_row is not None else 0))
        total_amount = int((out_row["total_amount"] if out_row is not None else 0) or 0) + \
                       int((in_row["total_amount"] if in_row is not None else 0) or 0)
        fraud_count = int((out_row["fraud_cnt"] if out_row is not None else 0) or 0) + \
                      int((in_row["fraud_cnt"] if in_row is not None else 0) or 0)
        fraud_ratio = round(fraud_count / total_count, 4) if total_count > 0 else 0.0

        if total_count == 0:
            return json.dumps(
                {"account_id": aid, "안내": "해당 계좌의 거래 내역이 없습니다."},
                ensure_ascii=False,
            )

        # 주요 거래 시간대 (출금 기준)
        hour_df = query(
            "SELECT 거래시간대, COUNT(*) AS cnt FROM hofinet "
            "WHERE 출금계좌일련번호 = $aid "
            "GROUP BY 거래시간대 ORDER BY cnt DESC LIMIT 3",
            {"aid": aid},
        )
        top_hours = hour_df["거래시간대"].tolist() if hour_df is not None and not hour_df.empty else []

        # 주 사용 매체 (출금 기준)
        media_df = query(
            "SELECT 매체구분, COUNT(*) AS cnt FROM hofinet "
            "WHERE 출금계좌일련번호 = $aid "
            "GROUP BY 매체구분 ORDER BY cnt DESC LIMIT 3",
            {"aid": aid},
        )
        top_media_codes = media_df["매체구분"].tolist() if media_df is not None and not media_df.empty else []
        top_media = [_매체구분_MAP.get(int(c), f"코드{c}") for c in top_media_codes]

        # 상위 거래 상대 계좌 5개 (출금계좌 기준으로 입금계좌 상대)
        cp_df = query(
            "SELECT 입금계좌일련번호 AS counterpart_id, "
            "COUNT(*) AS tx_count, SUM(거래금액) AS total_amount "
            "FROM hofinet WHERE 출금계좌일련번호 = $aid "
            "GROUP BY 입금계좌일련번호 ORDER BY tx_count DESC LIMIT 5",
            {"aid": aid},
        )
        top_counterparts = []
        if cp_df is not None and not cp_df.empty:
            for _, row in cp_df.iterrows():
                top_counterparts.append({
                    "account_id": int(row["counterpart_id"]),
                    "count": int(row["tx_count"]),
                    "amount": int(row["total_amount"] or 0),
                })

    except Exception as exc:
        return json.dumps(
            {"error": f"계좌 프로파일 조회 오류: {str(exc)}"},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "account_id": aid,
            "total_count": total_count,
            "total_amount": total_amount,
            "fraud_count": fraud_count,
            "fraud_ratio": fraud_ratio,
            "top_hours": top_hours,
            "top_media": top_media,
            "top_counterparts": top_counterparts,
        },
        ensure_ascii=False,
    )


def _tool_get_fraud_type_summary(arguments: dict) -> str:
    fraud_type = arguments.get("fraud_type")
    if fraud_type is None:
        return json.dumps({"error": "fraud_type이 필요합니다."}, ensure_ascii=False)

    try:
        ftype = int(fraud_type)
    except (TypeError, ValueError):
        return json.dumps({"error": "fraud_type은 1~7 사이의 정수여야 합니다."}, ensure_ascii=False)

    if ftype not in range(1, 8):
        return json.dumps(
            {"error": f"fraud_type({ftype})은 1~7 범위여야 합니다."},
            ensure_ascii=False,
        )

    bank_id_raw = arguments.get("bank_id")
    bid = int(bank_id_raw) if bank_id_raw is not None else None

    try:
        # 기본 집계
        if bid is not None:
            agg_df = query(
                "SELECT COUNT(*) AS total_count, SUM(거래금액) AS total_amount, "
                "AVG(거래금액) AS avg_amount "
                "FROM hofinet "
                "WHERE 이상거래여부 = 1 AND 이상거래유형 = $ftype "
                "AND 출금금융회사일련번호 = $bid",
                {"ftype": ftype, "bid": bid},
            )
        else:
            agg_df = query(
                "SELECT COUNT(*) AS total_count, SUM(거래금액) AS total_amount, "
                "AVG(거래금액) AS avg_amount "
                "FROM hofinet WHERE 이상거래여부 = 1 AND 이상거래유형 = $ftype",
                {"ftype": ftype},
            )

        if agg_df is None or agg_df.empty:
            return json.dumps(
                {
                    "type_code": ftype,
                    "type_name": _이상거래유형_MAP.get(ftype, "기타"),
                    "안내": "해당 유형의 이상거래가 없습니다.",
                },
                ensure_ascii=False,
            )

        row = agg_df.iloc[0]
        total_count = int(row["total_count"] or 0)
        total_amount = int(row["total_amount"] or 0)
        avg_amount = round(float(row["avg_amount"] or 0), 2)

        if total_count == 0:
            return json.dumps(
                {
                    "type_code": ftype,
                    "type_name": _이상거래유형_MAP.get(ftype, "기타"),
                    "안내": "해당 유형의 이상거래가 없습니다.",
                },
                ensure_ascii=False,
            )

        # 상위 금융회사
        if bid is not None:
            bank_df = query(
                "SELECT 출금금융회사일련번호 AS bank_id, COUNT(*) AS cnt "
                "FROM hofinet WHERE 이상거래여부 = 1 AND 이상거래유형 = $ftype "
                "AND 출금금융회사일련번호 = $bid "
                "GROUP BY 출금금융회사일련번호 ORDER BY cnt DESC LIMIT 5",
                {"ftype": ftype, "bid": bid},
            )
        else:
            bank_df = query(
                "SELECT 출금금융회사일련번호 AS bank_id, COUNT(*) AS cnt "
                "FROM hofinet WHERE 이상거래여부 = 1 AND 이상거래유형 = $ftype "
                "GROUP BY 출금금융회사일련번호 ORDER BY cnt DESC LIMIT 5",
                {"ftype": ftype},
            )

        top_banks = []
        if bank_df is not None and not bank_df.empty:
            for _, brow in bank_df.iterrows():
                top_banks.append({
                    "bank_id": int(brow["bank_id"]),
                    "count": int(brow["cnt"]),
                })

        # 샘플 날짜 (최신 5개)
        if bid is not None:
            date_df = query(
                "SELECT DISTINCT 거래일자 FROM hofinet "
                "WHERE 이상거래여부 = 1 AND 이상거래유형 = $ftype "
                "AND 출금금융회사일련번호 = $bid "
                "ORDER BY 거래일자 DESC LIMIT 5",
                {"ftype": ftype, "bid": bid},
            )
        else:
            date_df = query(
                "SELECT DISTINCT 거래일자 FROM hofinet "
                "WHERE 이상거래여부 = 1 AND 이상거래유형 = $ftype "
                "ORDER BY 거래일자 DESC LIMIT 5",
                {"ftype": ftype},
            )

        sample_dates = date_df["거래일자"].tolist() if date_df is not None and not date_df.empty else []

    except Exception as exc:
        return json.dumps(
            {"error": f"이상거래유형 조회 오류: {str(exc)}"},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "type_code": ftype,
            "type_name": _이상거래유형_MAP.get(ftype, "기타"),
            "total_count": total_count,
            "total_amount": total_amount,
            "avg_amount": avg_amount,
            "top_banks": top_banks,
            "sample_dates": sample_dates,
            "bank_filter": bid,
        },
        ensure_ascii=False,
    )


def _tool_compare_periods(arguments: dict) -> str:
    try:
        p1s = int(arguments.get("period1_start", 0))
        p1e = int(arguments.get("period1_end", 0))
        p2s = int(arguments.get("period2_start", 0))
        p2e = int(arguments.get("period2_end", 0))
    except (TypeError, ValueError):
        return json.dumps({"error": "날짜는 YYYYMMDD 정수여야 합니다."}, ensure_ascii=False)

    if p1s > p1e or p2s > p2e:
        return json.dumps({"error": "시작일이 종료일보다 늦을 수 없습니다."}, ensure_ascii=False)

    try:
        # p1s, p1e, p2s, p2e는 상단에서 int()로 강제 변환했으므로 f-string 삽입 안전
        # (DuckDB BETWEEN 절은 파라미터 바인딩도 지원하나 정수 리터럴로 삽입)
        df1 = query(
            f"""
            SELECT COUNT(*) AS total_count,
                   SUM(이상거래여부) AS fraud_count,
                   AVG(거래금액) AS avg_amount
            FROM hofinet
            WHERE 거래일자 BETWEEN {p1s} AND {p1e}
            """
        )
        df2 = query(
            f"""
            SELECT COUNT(*) AS total_count,
                   SUM(이상거래여부) AS fraud_count,
                   AVG(거래금액) AS avg_amount
            FROM hofinet
            WHERE 거래일자 BETWEEN {p2s} AND {p2e}
            """
        )
    except Exception as exc:
        return json.dumps({"error": f"기간 비교 조회 오류: {str(exc)}"}, ensure_ascii=False)

    def _row(df):
        if df is None or df.empty:
            return {"total_count": 0, "fraud_count": 0, "avg_amount": 0.0}
        r = df.iloc[0]
        return {
            "total_count": int(r["total_count"] or 0),
            "fraud_count": int(r["fraud_count"] or 0),
            "avg_amount": round(float(r["avg_amount"] or 0.0), 2),
        }

    r1 = _row(df1)
    r2 = _row(df2)

    def _delta(v1, v2):
        if v1 == 0:
            return None
        return round((v2 - v1) / v1 * 100, 2)

    fraud_ratio1 = round(r1["fraud_count"] / r1["total_count"] * 100, 4) if r1["total_count"] > 0 else 0.0
    fraud_ratio2 = round(r2["fraud_count"] / r2["total_count"] * 100, 4) if r2["total_count"] > 0 else 0.0

    return json.dumps(
        {
            "period1": {"start": p1s, "end": p1e, **r1, "fraud_ratio_percent": fraud_ratio1},
            "period2": {"start": p2s, "end": p2e, **r2, "fraud_ratio_percent": fraud_ratio2},
            "delta": {
                "total_count_pct": _delta(r1["total_count"], r2["total_count"]),
                "fraud_count_pct": _delta(r1["fraud_count"], r2["fraud_count"]),
                "avg_amount_pct": _delta(r1["avg_amount"], r2["avg_amount"]),
                "fraud_ratio_ppt": round(fraud_ratio2 - fraud_ratio1, 4),
            },
        },
        ensure_ascii=False,
    )


def _tool_get_institution_report(arguments: dict) -> str:
    bank_id_raw = arguments.get("bank_id")
    if bank_id_raw is None:
        return json.dumps({"error": "bank_id가 필요합니다."}, ensure_ascii=False)
    try:
        bid = int(bank_id_raw)
    except (TypeError, ValueError):
        return json.dumps({"error": "bank_id는 정수여야 합니다."}, ensure_ascii=False)

    try:
        # 기본 집계 (출금 방향 기준)
        agg_df = query(
            "SELECT COUNT(*) AS total_count, "
            "SUM(이상거래여부) AS fraud_count, "
            "SUM(거래금액) AS total_amount, "
            "AVG(거래금액) AS avg_amount "
            "FROM hofinet WHERE 출금금융회사일련번호 = $bid",
            {"bid": bid},
        )

        if agg_df is None or agg_df.empty or int(agg_df.iloc[0]["total_count"] or 0) == 0:
            return json.dumps(
                {"bank_id": bid, "안내": "해당 금융회사의 거래 내역이 없습니다."},
                ensure_ascii=False,
            )

        row = agg_df.iloc[0]
        total_count = int(row["total_count"] or 0)
        fraud_count = int(row["fraud_count"] or 0)
        total_amount = int(row["total_amount"] or 0)
        avg_amount = round(float(row["avg_amount"] or 0.0), 2)
        fraud_ratio = round(fraud_count / total_count * 100, 4) if total_count > 0 else 0.0

        # 상위 거래 상대 기관 (입금 기관 기준)
        cp_df = query(
            "SELECT 입금금융회사일련번호 AS counterpart_bank_id, "
            "COUNT(*) AS tx_count, SUM(거래금액) AS total_amount "
            "FROM hofinet WHERE 출금금융회사일련번호 = $bid "
            "GROUP BY 입금금융회사일련번호 ORDER BY tx_count DESC LIMIT 5",
            {"bid": bid},
        )
        top_counterparts = []
        if cp_df is not None and not cp_df.empty:
            for _, r in cp_df.iterrows():
                top_counterparts.append({
                    "bank_id": int(r["counterpart_bank_id"]),
                    "count": int(r["tx_count"]),
                    "amount": int(r["total_amount"] or 0),
                })

        # 이상거래 유형별 분포
        type_df = query(
            "SELECT 이상거래유형, COUNT(*) AS cnt "
            "FROM hofinet "
            "WHERE 출금금융회사일련번호 = $bid AND 이상거래여부 = 1 "
            "GROUP BY 이상거래유형 ORDER BY cnt DESC",
            {"bid": bid},
        )
        fraud_type_dist = []
        if type_df is not None and not type_df.empty:
            for _, r in type_df.iterrows():
                ftype = int(r["이상거래유형"]) if r["이상거래유형"] is not None else 0
                fraud_type_dist.append({
                    "type_code": ftype,
                    "type_name": _이상거래유형_MAP.get(ftype, "기타"),
                    "count": int(r["cnt"]),
                })

    except Exception as exc:
        return json.dumps(
            {"error": f"금융회사 보고서 조회 오류: {str(exc)}"},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "bank_id": bid,
            "total_count": total_count,
            "fraud_count": fraud_count,
            "fraud_ratio_percent": fraud_ratio,
            "total_amount": total_amount,
            "avg_amount": avg_amount,
            "top_counterpart_banks": top_counterparts,
            "fraud_type_distribution": fraud_type_dist,
        },
        ensure_ascii=False,
    )


def _tool_rank_risky_transactions(arguments: dict) -> str:
    sample_size = min(int(arguments.get("sample_size", 1000)), 5000)
    top_k = min(int(arguments.get("top_k", 20)), 100)

    model = load_model()
    if model is None:
        return json.dumps(
            {"error": "학습된 모델이 없습니다. Detection 페이지에서 모델을 먼저 학습하세요."},
            ensure_ascii=False,
        )

    try:
        from src.features.detector import predict_from_db, FEATURE_COLS
        df = predict_from_db(model, limit=sample_size)
    except Exception as exc:
        return json.dumps(
            {"error": f"배치 예측 오류: {str(exc)}"},
            ensure_ascii=False,
        )

    if df is None or df.empty:
        return json.dumps({"안내": "예측할 거래 데이터가 없습니다.", "results": []}, ensure_ascii=False)

    top_df = df.head(top_k)
    records = []
    for _, row in top_df.iterrows():
        records.append({
            "출금계좌일련번호": int(row["출금계좌일련번호"]),
            "입금계좌일련번호": int(row["입금계좌일련번호"]),
            "거래일자": int(row["거래일자"]),
            "거래시간대": int(row["거래시간대"]),
            "거래금액": int(row["거래금액"]),
            "이상거래확률": round(float(row["예측확률"]), 4),
            "실제이상거래여부": int(row["이상거래여부"]) if "이상거래여부" in row else None,
        })

    return json.dumps(
        {
            "sample_size": sample_size,
            "top_k": top_k,
            "총반환건수": len(records),
            "results": records,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# OpenAI 메시지 직렬화
# ---------------------------------------------------------------------------

def _message_to_dict(msg):
    """ChatCompletionMessage를 OpenAI API 호환 dict로 변환한다."""
    d = {"role": msg.role, "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


# ---------------------------------------------------------------------------
# 대화 실행 -도구 호출 정보를 함께 반환
# ---------------------------------------------------------------------------

MAX_TOOL_ROUNDS = 5


def chat(messages: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """OpenAI API로 대화를 수행하고 응답을 반환한다.

    Args:
        messages: 대화 히스토리 (list of dicts, user/assistant/tool 포함)

    Returns:
        (assistant_content, updated_messages, tool_events)
        - tool_events: 각 도구 호출 정보 [{name, arguments, result}, ...]
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    tool_events: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=4096,
        )

        msg = response.choices[0].message

        if not msg.tool_calls:
            break

        # tool call이 있으면 실행 후 재호출
        assistant_dict = _message_to_dict(msg)
        messages.append(assistant_dict)
        full_messages.append(assistant_dict)

        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            result = _execute_tool(tool_name, tool_args)

            # 도구 이벤트 기록 (UI 시각화용)
            tool_events.append(
                {
                    "name": tool_name,
                    "arguments": tool_args,
                    "result": result,
                }
            )

            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            }
            messages.append(tool_msg)
            full_messages.append(tool_msg)

    content = msg.content or ""
    assistant_msg = {"role": "assistant", "content": content}
    messages.append(assistant_msg)
    return content, messages, tool_events
