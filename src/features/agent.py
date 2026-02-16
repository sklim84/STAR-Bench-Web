"""기능4: AI 분석 에이전트 모듈.

OpenAI function calling을 활용하여 기능1~3을 도구로 등록하고,
대화를 통해 자금세탁의심거래를 분석하고 STR을 작성한다.
"""

import json
from openai import OpenAI

import config
from src.data.db import query


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_transactions",
            "description": "HOFINET 데이터베이스에 SQL 쿼리를 실행하여 거래 데이터를 조회한다. 테이블명은 hofinet이고 컬럼은 거래일자, 거래시간대, 출금금융회사일련번호, 출금계좌일련번호, 입금금융회사일련번호, 입금계좌일련번호, 자금구분, 매체구분, 거래금액, 이상거래여부, 이상거래유형, 이상거래설명이다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "실행할 SELECT SQL 쿼리. hofinet 테이블에 대해 집계, 필터링, 그룹핑 등을 수행한다."
                    }
                },
                "required": ["sql"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "predict_fraud",
            "description": "학습된 XGBoost 모델로 거래의 이상거래 확률을 예측한다. 거래 정보를 입력하면 0~1 사이의 확률을 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "거래시간대": {"type": "integer", "description": "3시간 단위 (0,3,6,9,12,15,18,21)"},
                    "출금금융회사일련번호": {"type": "integer"},
                    "입금금융회사일련번호": {"type": "integer"},
                    "자금구분": {"type": "integer", "description": "0,1,3,4 중 하나"},
                    "매체구분": {"type": "integer", "description": "1~7 중 하나"},
                    "거래금액": {"type": "integer", "description": "원 단위 금액"}
                },
                "required": ["거래시간대", "출금금융회사일련번호", "입금금융회사일련번호", "자금구분", "매체구분", "거래금액"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_str",
            "description": "분석 결과를 기반으로 의심거래보고서(STR)를 작성한다. 분석 내용 요약을 입력하면 STR 양식에 맞춰 보고서를 생성한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "분석 결과 요약 (의심 사유, 관련 계좌, 금액 등)"
                    }
                },
                "required": ["summary"]
            }
        }
    }
]

SYSTEM_PROMPT = """당신은 자금세탁방지(AML) 전문 분석가입니다.
HOFINET(전자금융공동망) 이상거래탐지 데이터를 분석하여 자금세탁의심거래를 탐지하고 보고합니다.

사용 가능한 도구:
1. query_transactions: HOFINET DB에 SQL 쿼리를 실행하여 거래 통계, 패턴, 특정 계좌 거래 내역 등을 조회
2. predict_fraud: XGBoost 모델로 특정 거래의 이상거래 확률을 예측
3. generate_str: 분석 결과를 의심거래보고서(STR) 양식으로 작성

데이터 스키마:
- 테이블: hofinet (4,732,130건)
- 컬럼: 거래일자(YYYYMMDD), 거래시간대(0~21, 3시간단위), 출금금융회사일련번호, 출금계좌일련번호, 입금금융회사일련번호, 입금계좌일련번호, 자금구분(0,1,3,4), 매체구분(1~7), 거래금액, 이상거래여부(0/1), 이상거래유형(1~7), 이상거래설명

이상거래유형:
1=계좌수집형 거래패턴의 변화, 2=신규 거래처 거래, 3=분산 거래, 4=다중거래처 자금 회수, 5=대량 입금 후 자금 이탈, 7=심야/새벽 대량 거래

한국어로 응답하세요. 분석 시 구체적인 수치와 근거를 제시하세요."""


def _execute_tool(name, arguments):
    """도구를 실행하고 결과를 반환한다."""
    if name == "query_transactions":
        sql = arguments["sql"]
        # SELECT만 허용
        if not sql.strip().upper().startswith("SELECT"):
            return json.dumps({"error": "SELECT 쿼리만 실행 가능합니다."}, ensure_ascii=False)
        df = query(sql)
        # 결과가 너무 크면 제한
        if len(df) > 100:
            df = df.head(100)
        return df.to_json(orient="records", force_ascii=False)

    elif name == "predict_fraud":
        from src.features.detector import load_model
        import pandas as pd
        model = load_model()
        if model is None:
            return json.dumps({"error": "학습된 모델이 없습니다. Detection 페이지에서 모델을 먼저 학습하세요."}, ensure_ascii=False)

        features = pd.DataFrame([arguments])
        prob = model.predict_proba(features)[:, 1][0]
        return json.dumps({"이상거래확률": round(float(prob), 4)}, ensure_ascii=False)

    elif name == "generate_str":
        return json.dumps({
            "보고서": "의심거래보고서(STR)",
            "내용": arguments["summary"],
            "안내": "이 내용을 기반으로 STR을 작성합니다."
        }, ensure_ascii=False)

    return json.dumps({"error": f"알 수 없는 도구: {name}"}, ensure_ascii=False)


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


MAX_TOOL_ROUNDS = 5


def chat(messages):
    """OpenAI API로 대화를 수행하고 응답을 반환한다.

    Args:
        messages: 대화 히스토리 (list of dicts, user/assistant/tool 포함)

    Returns:
        (assistant_content, updated_messages)
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        msg = response.choices[0].message

        if not msg.tool_calls:
            break

        # tool call이 있으면 실행 후 재호출
        assistant_dict = _message_to_dict(msg)
        messages.append(assistant_dict)
        full_messages.append(assistant_dict)

        for tool_call in msg.tool_calls:
            result = _execute_tool(
                tool_call.function.name,
                json.loads(tool_call.function.arguments),
            )
            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            }
            messages.append(tool_msg)
            full_messages.append(tool_msg)
    else:
        # MAX_TOOL_ROUNDS 초과 시 마지막 메시지 반환
        pass

    content = msg.content or ""
    assistant_msg = {"role": "assistant", "content": content}
    messages.append(assistant_msg)
    return content, messages
