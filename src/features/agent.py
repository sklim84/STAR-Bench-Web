"""기능4: AI 분석 에이전트 모듈.

OpenAI function calling을 활용하여 기능1~3을 도구로 등록하고,
대화를 통해 자금세탁의심거래를 분석하고 STR을 작성한다.
"""

import json
import re
from datetime import date

import pandas as pd
from openai import OpenAI

import config
from src.data.db import query
from src.features.dashboard import get_summary, get_fraud_type_distribution
from src.features.detector import load_model
from src.features.network import get_account_ego_network


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
            "description": "분석 결과를 기반으로 의심거래보고서(STR)를 작성한다. 분석 내용 요약을 입력하면 STR 양식에 맞춰 구조화된 보고서를 생성한다. STR 작성 전에 반드시 관련 거래 데이터를 먼저 조회할 것.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "분석 결과 요약 (의심 사유, 관련 계좌, 금액, 거래 패턴 등 구체적인 수치 포함)",
                    },
                    "fraud_type": {
                        "type": "string",
                        "description": "의심 활동 분류: '자금세탁', '사기', '기타' 중 하나",
                        "enum": ["자금세탁", "사기", "기타"],
                    },
                    "tools_used": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "분석에 사용된 도구 목록 (예: ['query_transactions', 'predict_fraud'])",
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
                        "description": "탐색 범위 (1 또는 2). 기본값은 1.",
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
]

SYSTEM_PROMPT = """당신은 자금세탁방지(AML) 전문 분석가입니다.
HOFINET(전자금융공동망) 이상거래탐지 데이터를 분석하여 자금세탁의심거래를 탐지하고 보고합니다.

사용 가능한 도구:
1. get_statistics: 전체 거래 요약 통계 및 이상거래 유형별 분포 조회 (분석 시작 시 가장 먼저 사용)
2. query_transactions: HOFINET DB에 SQL 쿼리를 실행하여 거래 통계, 패턴, 특정 계좌 거래 내역 등을 상세 조회
3. analyze_network: 특정 계좌의 거래 네트워크를 분석하여 연결 계좌 수, 이상거래 관련 여부 파악
4. predict_fraud: XGBoost 모델로 특정 거래의 이상거래 확률을 예측
5. generate_str: 분석 결과를 의심거래보고서(STR) 양식으로 작성

권장 분석 절차:
1. get_statistics로 전체 현황 파악
2. query_transactions으로 의심 거래 상세 조회
3. analyze_network으로 계좌 네트워크 분석 (특정 계좌가 있는 경우)
4. predict_fraud로 이상거래 확률 예측
5. 충분한 근거가 확보된 경우에만 generate_str로 STR 작성

STR 작성 시 주의사항:
- 반드시 근거 데이터를 먼저 조회한 후 STR을 작성하세요
- 구체적인 계좌번호, 금액, 거래 패턴 수치를 포함하세요
- 의심 사유를 명확하게 기술하세요

데이터 스키마:
- 테이블: hofinet (4,732,130건)
- 컬럼: 거래일자(YYYYMMDD), 거래시간대(0~21, 3시간단위), 출금금융회사일련번호, 출금계좌일련번호, 입금금융회사일련번호, 입금계좌일련번호, 자금구분(0,1,3,4), 매체구분(1~7), 거래금액, 이상거래여부(0/1), 이상거래유형(1~7), 이상거래설명

이상거래유형:
1=계좌수집형 거래패턴의 변화, 2=신규 거래처 거래, 3=분산 거래, 4=다중거래처 자금 회수, 5=대량 입금 후 자금 이탈, 7=심야/새벽 대량 거래

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
# STR 구조화 헬퍼
# ---------------------------------------------------------------------------

def _build_str_report(summary: str, fraud_type: str, tools_used: list[str]) -> dict:
    """STR 양식에 맞는 구조화된 보고서 딕셔너리를 생성한다."""
    today = date.today().strftime("%Y-%m-%d")

    # 의심 사유 분류에 따른 권고 조치 결정
    조치_map = {
        "자금세탁": ["거래 패턴 모니터링 강화", "관련 계좌 추가 조사", "금융정보분석원(FIU) 보고 검토"],
        "사기": ["관련 계좌 즉시 동결 검토", "피해자 확인 및 보호 조치", "수사기관 의뢰 검토"],
        "기타": ["추가 모니터링 실시", "거래 내역 보존", "내부 심사 위원회 검토"],
    }
    권고조치 = 조치_map.get(fraud_type, 조치_map["기타"])

    # summary에서 계좌 정보 추출 시도 (숫자 패턴)
    account_candidates = re.findall(r"(?:계좌|출금계좌|입금계좌)[^\d]*(\d{5,})", summary)
    관련계좌 = list(set(account_candidates)) if account_candidates else ["요약에서 계좌 정보를 추출할 수 없습니다."]

    도구설명 = {
        "query_transactions": "HOFINET DB 거래 데이터 직접 조회",
        "predict_fraud": "XGBoost 이상거래 확률 모델 예측",
        "analyze_network": "계좌 거래 네트워크 분석",
        "get_statistics": "전체 통계 대시보드 조회",
        "generate_str": "STR 보고서 생성",
    }
    분석근거 = [도구설명.get(t, t) for t in (tools_used or [])]

    return {
        "보고서유형": "의심거래보고서(STR)",
        "보고일자": today,
        "의심활동요약": summary,
        "관련계좌정보": 관련계좌,
        "의심사유분류": fraud_type or "기타",
        "권고조치": 권고조치,
        "분석근거": 분석근거 if 분석근거 else ["분석 도구 미지정"],
        "작성안내": "본 보고서는 AI 분석 에이전트가 자동 생성한 초안입니다. 담당자 검토 후 제출하시기 바랍니다.",
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

    fraud_type = arguments.get("fraud_type", "기타")
    tools_used = arguments.get("tools_used", [])

    report = _build_str_report(summary, fraud_type, tools_used)
    return json.dumps(report, ensure_ascii=False)


def _tool_analyze_network(arguments: dict) -> str:
    account_id = arguments.get("account_id")
    if account_id is None:
        return json.dumps({"error": "account_id가 필요합니다."}, ensure_ascii=False)

    hops = int(arguments.get("hops", 1))
    if hops not in (1, 2):
        hops = 1

    try:
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
# 대화 실행 — 도구 호출 정보를 함께 반환
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
