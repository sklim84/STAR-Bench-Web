"""Feature 4: AI Analysis Agent Module.

Registers Features 1-3 as tools using OpenAI function calling,
analyzes suspicious transactions through conversation, and generates STR drafts.
"""

import json
import logging
import math
import re
from collections import Counter
from datetime import datetime, timedelta

import duckdb
import pandas as pd
from openai import OpenAI

import config

logger = logging.getLogger(__name__)
from src.data.db import query
from src.features.dashboard import get_summary, get_fraud_type_distribution
from src.features.detector import load_model
from src.features.network import (
    summarize_account_network,
    detect_ring_transactions,
    detect_layering_patterns,
    detect_funnel_accounts,
    find_shortest_path,
    compute_risk_score,
)
from src.features.ctr_monitor import (
    get_ctr_candidates,
    detect_structuring,
)
from src.features.risk_scorer import score_account as _score_account_risk
from src.features.monitoring import (
    RULE_NAMES,
    run_rule,
    run_all_rules,
    detect_dormant_reactivation,
    default_pattern_change_period,
)
from src.features.dashboard import (
    get_trend_analysis as _get_trend_analysis,
    analyze_channel_risk as _analyze_channel_risk,
    get_receiving_account_profile as _get_receiving_account_profile,
)
from src.features.flow_analyzer import (
    detect_smurfing_network as _detect_smurfing_network,
    analyze_cross_institution_flow as _analyze_cross_institution_flow,
)
from src.features.aml_reference import (
    lookup_fiu_reference_types,
    validate_str_fields,
    get_aml_glossary,
    glossary_terms,
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_transactions",
            "description": (
                "Executes a read-only SQL query on the HOFINET database. "
                "The table name is 'hofinet' and columns are: date (INTEGER yyyymmdd), time_slot, "
                "sender_bank, sender_acc, receiver_bank, receiver_acc, fund_type, media_type, "
                "amount, is_fraud, fraud_type, fraud_description. "
                "Returns total_count, returned_count and up to the first 100 rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "SELECT SQL query to execute (a leading WITH clause is allowed). "
                            "Perform aggregation, filtering, and grouping on the 'hofinet' table. "
                            "date is an integer, so compare it with integers: date BETWEEN 20240101 AND 20241231."
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
            "description": (
                "Scores one transaction with the platform's XGBoost model. "
                "Returns fraud_risk_score, an uncalibrated score between 0 and 1 (higher is riskier; "
                "it is not a probability of fraud) and a risk level (High >= 0.7, Medium >= 0.3)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "time_slot": {
                        "type": "integer",
                        "description": "3-hour interval (one of 0, 3, 6, 9, 12, 15, 18, 21)",
                    },
                    "sender_bank": {"type": "integer"},
                    "receiver_bank": {"type": "integer"},
                    "fund_type": {
                        "type": "integer",
                        "description": "One of 0, 1, 3, 4",
                    },
                    "media_type": {
                        "type": "integer",
                        "description": "One of 1-7",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Amount in KRW (positive integer)",
                    },
                },
                "required": [
                    "time_slot",
                    "sender_bank",
                    "receiver_bank",
                    "fund_type",
                    "media_type",
                    "amount",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_str",
            "description": (
                "Generates a Suspicious Transaction Report (STR) draft in the official format "
                "(Sections I-VII) from the analysis results passed in. Transaction records given "
                "in 'transactions' fill in the accounts, amounts, dates and channel of the report; "
                "without them those fields are taken from the summary text where possible."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of analysis results and grounds for suspicion (describe patterns, metrics, etc. concretely)",
                    },
                    "fraud_type": {
                        "type": "string",
                        "description": (
                            "STR 양식 §VI 의심거래 분류 (FIU 공식). "
                            "§VI-4 거래유형 16종(코드 15-30) + §VI-5 기타 자유기술(코드 31) = 17종. "
                            "HOFINET 이상거래유형 매핑: 1→§VI-4 code 15, 3→18, 4→25, 5→20; "
                            "2(신규 수신처)/7(심야/새벽 대량)은 §VI-4 직접 대응 없어 §VI-5 code 31(기타)로 매핑."
                        ),
                        "enum": [
                            "갑작스러운 거래패턴의 변화",   # §VI-4 code 15 (= HOFINET 1)
                            "원격지거래",                       # §VI-4 code 16
                            "교환거래",                         # §VI-4 code 17
                            "분할거래",                         # §VI-4 code 18 (= HOFINET 3)
                            "현금에 집착하는 거래",            # §VI-4 code 19
                            "거액 입금 후 당일/익일 인출",     # §VI-4 code 20 (= HOFINET 5)
                            "무기명증서 관련거래",              # §VI-4 code 21
                            "계좌개설 없이 거액 환전/송금",    # §VI-4 code 22
                            "의심스러운 담보대출/보험약관대출", # §VI-4 code 23
                            "주금 납입/잔액증명서 발급",       # §VI-4 code 24
                            "다중거래의 동시요청",              # §VI-4 code 25 (= HOFINET 4)
                            "빈번한 입출금",                    # §VI-4 code 26
                            "의심스러운 대여금고/보호예수",    # §VI-4 code 27
                            "법인/타인자산 담보 거래",         # §VI-4 code 28
                            "무관업종 보험청약",                # §VI-4 code 29
                            "테러자금으로 의심",                # §VI-4 code 30
                            "기타(자유기술)",                   # §VI-5 code 31 (= HOFINET 2, 7)
                        ],
                    },
                    "transactions": {
                        "type": "array",
                        "description": "List of related transaction records from query_transactions results. Used for automatic extraction of accounts, amounts, dates, and channels.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "integer"},
                                "time_slot": {"type": "integer"},
                                "sender_bank": {"type": "integer"},
                                "sender_acc": {"type": "integer"},
                                "receiver_bank": {"type": "integer"},
                                "receiver_acc": {"type": "integer"},
                                "fund_type": {"type": "integer"},
                                "media_type": {"type": "integer"},
                                "amount": {"type": "integer"},
                                "fraud_type": {"type": "integer"},
                            },
                        },
                    },
                    "fraud_probability": {
                        "type": "number",
                        "description": "Risk score from predict_fraud (fraud_risk_score, 0.0-1.0). Used for calculating suspicion intensity (1-5).",
                    },
                    "aml_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of AML patterns detected (e.g., ['Ring', 'Layering'])",
                    },
                    "tools_used": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tools used for analysis (e.g., ['query_transactions', 'predict_fraud'])",
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
            "description": (
                "Analyzes the transaction network around one account. Returns the number of "
                "connected accounts, transaction and fraud counts, fraud ratio (percent) and total "
                "amount over every transaction in that neighbourhood."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "Account number to analyze (sender_acc)",
                    },
                    "hops": {
                        "type": "integer",
                        "description": (
                            "Search depth 1-5 (default 1). 1 covers the account's own transactions; "
                            "each further hop adds the transactions of the accounts reached so far."
                        ),
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
            "description": (
                "Retrieves dataset-wide summary statistics: total transaction count, fraud count "
                "and fraud ratio (percent), distinct sender and receiver account counts, distinct "
                "sender and receiver bank counts, total amount, and the transaction count of every "
                "fraud type. Covers the whole dataset and takes no filters."
            ),
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
                "Retrieves the transaction profile of one account, counting the transactions it "
                "sends and the transactions it receives. Returns total/outbound/inbound counts, "
                "total amount, fraud count and ratio (percent), the busiest time slots and channels, "
                "and the top 5 counterparties with their direction."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "Account number to query (sender_acc or receiver_acc)",
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
                "Retrieves details by HOFINET fraud type (Sudden Pattern Change, New Counterparty, Split Transaction, etc.). "
                "Returns count/amount statistics and top associated institutions. "
                "Code mapping: 1=Sudden Change in Transaction Pattern, 2=Transaction with New Counterparty, 3=Split Transaction, 4=Concurrent Multiple Transactions, 5=Same-Day Withdrawal after Large Deposit, 7=Late-Night/Early-Morning Bulk Transactions (note: code 6 unused)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fraud_type": {
                        "type": "integer",
                        "description": "Fraud type code (1-5, 7; code 6 unused)",
                        "enum": [1, 2, 3, 4, 5, 7],
                    },
                    "bank_id": {
                        "type": "integer",
                        "description": "Optional filter by sender bank ID.",
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
                "Compares transaction and fraud statistics between two periods and returns the growth rate (delta). "
                "Calculates transaction count, fraud count, average amount, and rate of change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period1_start": {
                        "type": "integer",
                        "description": "Period 1 start date (YYYYMMDD integer)",
                    },
                    "period1_end": {
                        "type": "integer",
                        "description": "Period 1 end date (YYYYMMDD integer)",
                    },
                    "period2_start": {
                        "type": "integer",
                        "description": "Period 2 start date (YYYYMMDD integer)",
                    },
                    "period2_end": {
                        "type": "integer",
                        "description": "Period 2 end date (YYYYMMDD integer)",
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
                "Reports the status of one financial institution on both sides of the network: "
                "outbound (as sender_bank) and inbound (as receiver_bank) transaction counts, "
                "amounts and fraud ratios (percent), the top counterpart banks in each direction, "
                "the distribution by fraud type, and a quarterly trend."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bank_id": {
                        "type": "integer",
                        "description": "Financial institution ID to query (sender_bank codes are 102-161, receiver_bank codes 101-160)",
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
                "Scores a fixed sample of database transactions with the XGBoost model and returns "
                "the top-K by risk score. Useful for mass screening and prioritisation. The score "
                "is the same uncalibrated fraud_risk_score predict_fraud returns; the ground-truth "
                "label is not part of the result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_size": {
                        "type": "integer",
                        "description": "Number of transactions to score (default 1000, max 5000)",
                        "default": 1000,
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of high-risk transactions to return (default 20, max 100)",
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
                "Detects AML patterns in the transfer graph. "
                "ring: cycles of min_len-max_len fraud-labelled transfers that return to their "
                "starting account. layering: chains of at least min_layers consecutive "
                "fraud-labelled transfers. funnel: accounts that receive from at least min_inflow "
                "distinct accounts and forward to 1-max_outflow accounts (mule/collection accounts). "
                "shortest_path: the shortest chain of transfers between two accounts, in either "
                "direction. risk_score: a graph risk score (0-1) for one account from its own and "
                "its counterparties' fraud share, cycle participation and inflow/outflow imbalance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern_type": {
                        "type": "string",
                        "description": "Pattern type to detect",
                        "enum": ["ring", "layering", "funnel", "shortest_path", "risk_score"],
                    },
                    "account_id": {
                        "type": "integer",
                        "description": "Target account ID (required for risk_score)",
                    },
                    "account_a": {
                        "type": "integer",
                        "description": "Start account (required for shortest_path)",
                    },
                    "account_b": {
                        "type": "integer",
                        "description": "End account (required for shortest_path)",
                    },
                    "min_len": {
                        "type": "integer",
                        "description": "Minimum ring length (default 3)",
                        "default": 3,
                    },
                    "max_len": {
                        "type": "integer",
                        "description": "Maximum ring length (default 6)",
                        "default": 6,
                    },
                    "min_layers": {
                        "type": "integer",
                        "description": "Minimum layering steps (default 3)",
                        "default": 3,
                    },
                    "min_inflow": {
                        "type": "integer",
                        "description": "Minimum funnel inflow count (default 10)",
                        "default": 10,
                    },
                    "max_outflow": {
                        "type": "integer",
                        "description": "Maximum funnel outflow count (default 3)",
                        "default": 3,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 20)",
                        "default": 20,
                    },
                },
                "required": ["pattern_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_ctr_candidates",
            "description": (
                "Inquires on CTR (Currency Transaction Report) related items or detects structuring patterns. "
                "mode=high_value: single transactions at or above the threshold (default 10,000,000 KRW). "
                "mode=structuring: accounts whose transactions on one day stay below the threshold "
                "individually but sum to it or above."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "description": "Query mode: high_value or structuring",
                        "enum": ["high_value", "structuring"],
                    },
                    "date_from": {
                        "type": "integer",
                        "description": "Start date (YYYYMMDD integer)",
                    },
                    "date_to": {
                        "type": "integer",
                        "description": "End date (YYYYMMDD integer)",
                    },
                    "threshold": {
                        "type": "integer",
                        "description": "Reporting threshold in KRW, applied in both modes (default 10,000,000)",
                        "default": 10000000,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_account_risk",
            "description": (
                "Evaluates an account's behavioural risk score (0-100) from 5 indicators: share of "
                "night-time transactions (slots 21, 0, 3), how far its average amount sits from the "
                "dataset average, counterparty diversity, change in volume between its last two "
                "quarters, and fraud history (the share of its transactions that HOFINET labels as "
                "fraud). Returns the risk level (High >= 70, Medium >= 40, Low), the component "
                "scores and their weights. Transactions in both directions count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "Account number to evaluate (sender_acc or receiver_acc)",
                    },
                },
                "required": ["account_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_monitoring_alerts",
            "description": (
                "Runs the rule-based transaction monitoring rules and returns their alerts. "
                "R001 Nighttime Bulk: transactions of 5,000,000 KRW or more in the night slots "
                "(21, 0, 3). R002 Rapid Fire: accounts with 10 or more transactions on one day. "
                "R003 Repeated Identical Amounts: accounts that send the same amount "
                "(2,000,000 KRW or more) at least 3 times. R004 Institution Concentration: "
                "accounts sending at least half of their transactions to one receiving institution. "
                "R005 Pattern Change: accounts whose volume in the given period is at least 3 times "
                "their volume in the preceding period of equal length; without dates it compares the "
                "last quarter of the data with the one before. rule_id='all' runs all five. "
                "date_from, date_to and account_id apply to every rule."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_id": {
                        "type": "string",
                        "description": "Rule ID to execute",
                        "enum": ["all", "R001", "R002", "R003", "R004", "R005"],
                    },
                    "date_from": {
                        "type": "integer",
                        "description": "Start date (YYYYMMDD integer)",
                    },
                    "date_to": {
                        "type": "integer",
                        "description": "End date (YYYYMMDD integer)",
                    },
                    "account_id": {
                        "type": "integer",
                        "description": "Optional account filter (the account the rule describes: sender_acc, or either side for R001)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["rule_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_dormant_reactivation",
            "description": (
                "Detects accounts reactivated after a long period of dormancy: no transactions for "
                "dormant_days (default 180) followed by a transaction of at least "
                "min_reactivation_amount. Returns the last activity date, the reactivation date, "
                "the length of the gap and the amounts on the reactivation day."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dormant_days": {
                        "type": "integer",
                        "description": "Dormancy criteria in days (default 180)",
                        "default": 180,
                    },
                    "min_reactivation_amount": {
                        "type": "integer",
                        "description": "Minimum transaction amount for reactivation (default 5,000,000 KRW)",
                        "default": 5000000,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
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
            "name": "detect_smurfing_network",
            "description": (
                "Counts distinct counterparties per account and returns the accounts above the "
                "threshold. direction=inbound: accounts that receive from at least "
                "min_counterparts distinct sending accounts (collection). direction=outbound: "
                "accounts that send to at least min_counterparts distinct receiving accounts "
                "(dispersion). Only the counterparty count in that one direction is considered; "
                "for accounts that collect from many and then forward to a few, use "
                "detect_aml_patterns with pattern_type='funnel'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "Optional account filter. Scans all if omitted.",
                    },
                    "direction": {
                        "type": "string",
                        "description": "Analysis direction: inbound or outbound",
                        "enum": ["inbound", "outbound"],
                    },
                    "min_counterparts": {
                        "type": "integer",
                        "description": "Minimum counterparty count (default 5)",
                        "default": 5,
                    },
                    "date_from": {
                        "type": "integer",
                        "description": "Start date (YYYYMMDD integer)",
                    },
                    "date_to": {
                        "type": "integer",
                        "description": "End date (YYYYMMDD integer)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trend_analysis",
            "description": (
                "Analyzes monthly or quarterly time-series trends: transaction count, fraud count, "
                "fraud ratio (percent), total and average amount per period. Periods are labelled "
                "'2024-07' (monthly) and '2024Q3' (quarterly). Covers the whole dataset "
                "(14 quarters, 2021-09 to 2024-12) unless a date range is given."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "unit": {
                        "type": "string",
                        "description": "Aggregation unit: monthly or quarterly",
                        "enum": ["monthly", "quarterly"],
                        "default": "monthly",
                    },
                    "date_from": {
                        "type": "integer",
                        "description": "Start date (YYYYMMDD integer)",
                    },
                    "date_to": {
                        "type": "integer",
                        "description": "End date (YYYYMMDD integer)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_channel_risk",
            "description": (
                "Analyzes risk by transaction channel (media_type): 1 PC Banking, 2 Internet "
                "Banking, 3 Phone, 4 Mobile Phone, 5 Per-transaction Transfer, 6 Other, "
                "7 Bulk Transfer. Returns per-channel transaction and fraud counts, fraud ratio "
                "(percent) and amounts, plus a channel x time-slot cross-analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "integer",
                        "description": "Start date (YYYYMMDD integer)",
                    },
                    "date_to": {
                        "type": "integer",
                        "description": "End date (YYYYMMDD integer)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_receiving_account_profile",
            "description": (
                "Profiles an account from a fund-receiving (inbound) perspective, based on "
                "receiver_acc. Returns the inbound transaction count and amount, fraud count and "
                "ratio (percent), the number of distinct sending accounts and banks, and the top 5 "
                "senders and sending banks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "Account number to query (receiver_acc)",
                    },
                },
                "required": ["account_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_cross_institution_flow",
            "description": (
                "Analyzes fund flow between institution pairs (withdrawal institution → receiving institution). "
                "Identifies transaction concentration, fraud ratios, and transaction scale between institutions. "
                "Used to detect patterns where fraud is concentrated between specific institutions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "integer",
                        "description": "Start date (YYYYMMDD integer)",
                    },
                    "date_to": {
                        "type": "integer",
                        "description": "End date (YYYYMMDD integer)",
                    },
                    "min_transactions": {
                        "type": "integer",
                        "description": "Minimum transaction count (default 10)",
                        "default": 10,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
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
            "name": "lookup_fiu_reference_types",
            "description": (
                "Searches the FIU suspicious-transaction reference catalog (an excerpt: 31 entries "
                "for banking and securities). The catalog is in English and the keyword is matched "
                "as a case-insensitive substring of an entry's industry, category and description, "
                "so keywords must be English: e.g. structuring, cash, non-face-to-face, "
                "virtual asset, dormancy, gambling, balance certificate. An empty keyword returns "
                "the whole catalog."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "English search keyword (e.g., structuring, cash, non-face-to-face, virtual asset)",
                    },
                    "industry": {
                        "type": "string",
                        "description": "Industry filter: banking, securities, or omit for all",
                        "enum": ["banking", "securities"],
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_str_fields",
            "description": (
                "Checks an STR draft for the fields the report form requires and reports what is "
                "missing. Required: Header.ReportingDate; "
                "I_ReportingInstitution.WithdrawalInstitutionCode; "
                "II_Transactor.WithdrawalAccountNumber and .ReceivingAccountNumber; "
                "III_TransactionDetails.TransactionPeriod, .TransactionCount, .TransactionChannel "
                "and .TotalAmount_KRW; VI_TransactionType.PrimarySuspicionType; "
                "VII_Narrative.SuspicionJudgmentReason. The output of generate_str validates as is. "
                "Personal details the form asks for but HOFINET does not contain (names, identity "
                "documents, phone numbers) are optional and reported under missing_optional."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "str_draft": {
                        "type": "object",
                        "description": (
                            "STR draft object, nested by section "
                            "(Header, I_ReportingInstitution, II_Transactor, III_TransactionDetails, "
                            "VI_TransactionType, VII_Narrative), as generate_str returns it. "
                            "Field names are matched ignoring case and underscores."
                        ),
                    },
                },
                "required": ["str_draft"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aml_glossary",
            "description": (
                "Returns the definition of an AML term. The glossary holds 13 English entries and "
                "matches the term exactly, ignoring case: CDD, EDD, SDD, STR, CTR, RBA, PEP, MLRO, "
                "FATF, FIU, KYE, Structuring, Layering. There are no Korean entries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "English term to look up (CDD, EDD, SDD, STR, CTR, RBA, PEP, MLRO, FATF, FIU, KYE, Structuring, Layering)",
                    },
                },
                "required": ["term"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are an Anti-Money Laundering (AML) analyst.
You work with HOFINET (Electronic Financial Network) transaction data to examine and report suspicious transactions.

Tool definitions are provided via the API tools field; refer to each tool's name, description, and parameter schema there.

Data:
- Table hofinet, 4,732,130 transactions, one row per transfer.
- Columns: date, time_slot, sender_bank, sender_acc, receiver_bank, receiver_acc, fund_type, media_type, amount, is_fraud, fraud_type, fraud_description.
- date is an INTEGER in yyyymmdd form and runs from 20210901 to 20241231 (14 quarters). Compare it with integers, for example date BETWEEN 20240101 AND 20241231; string dates such as '2024-01-01' and LIKE patterns do not work on it.
- time_slot is the first hour of a 3-hour slot: 0, 3, 6, 9, 12, 15, 18, 21.
- sender_acc and receiver_acc are 16-digit account numbers, from 9000000000000002 to 9000000004455021. 30,526 accounts appear as sender, 422,698 as receiver, 414 as both.
- sender_bank codes run 102-161 (50 institutions), receiver_bank codes 101-160 (54 institutions).
- amount is in KRW and takes 48 distinct values between 1 and 500,000,000.
- is_fraud is 1 for the 14,490 transactions labelled as suspicious and 0 for the rest.
- fraud_type is NULL for normal transactions; fraud_description is an empty string for them and otherwise holds the Korean label exactly as listed here:
  1 = Sudden change in transaction pattern ('갑작스러운 거래패턴의 변화', 1,955 rows)
  2 = Transaction with a new counterparty ('신규 수신처 거래', 9,255)
  3 = Split transaction ('분할 거래', 2,073)
  4 = Concurrent multiple transactions ('다중거래의 동시 요청', 929)
  5 = Same-day withdrawal after a large deposit ('거액 입금 후 당일 인출', 243)
  7 = Late-night/early-morning bulk transactions ('심야/새벽 대량 거래', 35)
  Code 6 is not used.
- media_type: 1=PC Banking, 2=Internet Banking, 3=Phone, 4=Mobile Phone, 5=Per-transaction Transfer, 6=Other, 7=Bulk Transfer.
- fund_type: 0=General, 1=Salary, 3=Other, 4=Inter-bank Auto Transfer.

Answer in the language of the user's question. Give the figures the tools return and say what they support."""


# ---------------------------------------------------------------------------
# Argument handling
#
# Models serialise tool arguments in different ways: the whole object as a JSON
# string, nested arrays as strings, numbers as strings, and the literal "null"
# where a value is absent. The helpers below read those forms, so a tool fails
# only when the value itself is wrong, and report what is wrong instead of
# surfacing an int('null') or NaN traceback.
# ---------------------------------------------------------------------------

_VALID_TIME_SLOTS = {0, 3, 6, 9, 12, 15, 18, 21}
_VALID_FUND_TYPES = {0, 1, 3, 4}
_VALID_MEDIA_TYPES = set(range(1, 8))

_NULL_STRINGS = {"", "null", "none", "nan", "n/a", "undefined"}


class ToolArgumentError(ValueError):
    """An argument is missing, or cannot be read as the type the schema declares."""


def _is_null(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and value.strip().lower() in _NULL_STRINGS


def _load_json(value):
    """Parses a JSON-encoded string, or returns the value unchanged."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{\"":
        return value
    try:
        return json.loads(text)
    except ValueError:
        return value


def _normalize_arguments(arguments) -> dict:
    """Returns the arguments as a dict with null-like entries removed."""
    arguments = _load_json(arguments)
    if arguments is None:
        return {}
    if not isinstance(arguments, dict):
        raise ToolArgumentError("Arguments must be a JSON object.")
    return {k: v for k, v in arguments.items() if not _is_null(v)}


def _as_int(value, name: str) -> int:
    """Reads an integer argument, accepting numeric strings such as '12'."""
    if isinstance(value, bool):
        raise ToolArgumentError(f"{name} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or value != int(value):
            raise ToolArgumentError(f"{name}({value}) must be an integer.")
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("_", "")
        try:
            return int(text)
        except ValueError:
            try:
                number = float(text)
            except ValueError:
                number = None
            if number is not None and not math.isnan(number) and number == int(number):
                return int(number)
    raise ToolArgumentError(f"{name}({value!r}) must be an integer.")


def _as_float(value, name: str) -> float:
    """Reads a number argument, accepting numeric strings such as '0.91'."""
    if isinstance(value, bool):
        raise ToolArgumentError(f"{name} must be a number.")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            pass
    raise ToolArgumentError(f"{name}({value!r}) must be a number.")


def _req_int(arguments: dict, name: str) -> int:
    if name not in arguments:
        raise ToolArgumentError(f"{name} is required.")
    return _as_int(arguments[name], name)


def _opt_int(arguments: dict, name: str, default=None):
    if name not in arguments:
        return default
    return _as_int(arguments[name], name)


def _opt_date(arguments: dict, name: str, default=None):
    """Reads a YYYYMMDD date argument and checks that it is a real date."""
    if name not in arguments:
        return default
    try:
        value = _as_int(arguments[name], name)
        datetime.strptime(str(value), "%Y%m%d")
    except (ToolArgumentError, ValueError):
        raise ToolArgumentError(
            f"{name}({arguments[name]!r}) must be a date as a YYYYMMDD integer, e.g. 20240131."
        ) from None
    return value


def _limit(arguments: dict, default: int = 20, maximum: int = 100) -> int:
    limit = _opt_int(arguments, "limit", default)
    if limit is None or limit <= 0:
        return default
    return min(limit, maximum)


def _int_value(value, default: int = 0) -> int:
    """NaN-safe int for query results: SUM over zero rows comes back NULL/NaN."""
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return int(value)


def _float_value(value, default: float = 0.0, digits: int = 4) -> float:
    """NaN-safe float for query results."""
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return round(float(value), digits)


def _percent(part, whole, digits: int = 4) -> float:
    """Returns part/whole as a percentage. Every ratio a tool returns is a percentage."""
    part = _float_value(part, 0.0, 10)
    whole = _float_value(whole, 0.0, 10)
    if not whole:
        return 0.0
    return round(part / whole * 100, digits)


def _records(df) -> list[dict]:
    """Converts a DataFrame to JSON-safe records (NaN becomes null)."""
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _date_conditions(date_from, date_to, column: str = "date") -> list[str]:
    conditions = []
    if date_from is not None:
        conditions.append(f"{column} >= {int(date_from)}")
    if date_to is not None:
        conditions.append(f"{column} <= {int(date_to)}")
    return conditions


def _validate_predict_fraud_args(arguments: dict) -> tuple[dict, list[str]]:
    """Reads and validates the six predict_fraud features.

    Returns (feature values in FEATURE_COLS order, error messages). Numeric
    strings are accepted; keys that are not features are ignored, so the model's
    key order or an extra key cannot change the result.
    """
    from src.features.detector import FEATURE_COLS

    values: dict = {}
    errors: list[str] = []
    for name in FEATURE_COLS:
        if name not in arguments:
            errors.append(f"{name} is required.")
            continue
        try:
            values[name] = _as_int(arguments[name], name)
        except ToolArgumentError as exc:
            errors.append(str(exc))
    if errors:
        return values, errors

    if values["time_slot"] not in _VALID_TIME_SLOTS:
        errors.append(f"time_slot({values['time_slot']}) must be one of {sorted(_VALID_TIME_SLOTS)}.")
    if values["fund_type"] not in _VALID_FUND_TYPES:
        errors.append(f"fund_type({values['fund_type']}) must be one of {sorted(_VALID_FUND_TYPES)}.")
    if values["media_type"] not in _VALID_MEDIA_TYPES:
        errors.append(f"media_type({values['media_type']}) must be between 1 and 7.")
    if values["amount"] <= 0:
        errors.append(f"amount({values['amount']}) must be a positive integer.")
    return values, errors


# ---------------------------------------------------------------------------
# STR Structural Helpers - Code Mapping Tables
# ---------------------------------------------------------------------------

# Unified mappings sourced from src/features/aml_reference.py
# (HOFINET.MD §4.1, §6.2, §6.3 ground truth). Aliased to preserve the
# private-style names used throughout this module.
from src.features.aml_reference import (
    FRAUD_TYPE_MAP as _FRAUD_TYPE_MAP,
    MEDIA_TYPE_MAP as _MEDIA_TYPE_MAP,
    FUND_TYPE_MAP as _FUND_TYPE_MAP,
)

# STR Section VI suspicion classification (FIU form; HOFINET.MD §4.2).
# The generate_str fraud_type enum is §VI-4 (codes 15-30) plus §VI-5 code 31.
_VI_CATEGORY_CODES = {
    "갑작스러운 거래패턴의 변화": 15,
    "원격지거래": 16,
    "교환거래": 17,
    "분할거래": 18,
    "현금에 집착하는 거래": 19,
    "거액 입금 후 당일/익일 인출": 20,
    "무기명증서 관련거래": 21,
    "계좌개설 없이 거액 환전/송금": 22,
    "의심스러운 담보대출/보험약관대출": 23,
    "주금 납입/잔액증명서 발급": 24,
    "다중거래의 동시요청": 25,
    "빈번한 입출금": 26,
    "의심스러운 대여금고/보호예수": 27,
    "법인/타인자산 담보 거래": 28,
    "무관업종 보험청약": 29,
    "테러자금으로 의심": 30,
    "기타(자유기술)": 31,
}

# HOFINET fraud_type -> §VI category (HOFINET.MD §4.2). Codes 2 and 7 have no
# §VI-4 counterpart and map to the form's catch-all item.
_HOFINET_TO_VI_CATEGORY = {
    1: "갑작스러운 거래패턴의 변화",
    2: "기타(자유기술)",
    3: "분할거래",
    4: "다중거래의 동시요청",
    5: "거액 입금 후 당일/익일 인출",
    7: "기타(자유기술)",
}

# Names models use for a HOFINET fraud type: the raw fraud_description values,
# the English labels the tools return, and the §VI category names.
_FRAUD_TYPE_ALIASES = {
    "갑작스러운 거래패턴의 변화": 1,
    "sudden change in transaction pattern": 1,
    "신규 수신처 거래": 2,
    "신규거래처": 2,
    "transaction with new counterparty": 2,
    "분할 거래": 3,
    "분할거래": 3,
    "split transaction": 3,
    "다중거래의 동시 요청": 4,
    "다중거래의 동시요청": 4,
    "concurrent multiple transactions": 4,
    "거액 입금 후 당일 인출": 5,
    "거액 입금 후 당일/익일 인출": 5,
    "same-day withdrawal after large deposit": 5,
    "심야/새벽 대량 거래": 7,
    "late-night/early-morning bulk transactions": 7,
}

# Mapping fraud type codes to STR Section VI suspicion items (HOFINET official)
_FRAUD_TYPE_TO_VI_SECTION = {
    1: ["Sudden change in transaction pattern", "Behavioral anomaly"],
    2: ["Suspicious request from customer with no prior transactions"],
    3: ["Structured transactions", "Splitting amount across multiple transfers"],
    4: ["Simultaneous requests for multiple transactions", "Concurrent transaction bursts"],
    5: ["Withdrawal on same day after large deposit", "Rapid fund extraction"],
    7: ["Late-night/early-morning bulk transactions", "Off-hours mass transfers"],
}

_RECOMMENDED_ACTION_MAP = {
    1: ["Strengthen transaction monitoring", "Investigate related accounts", "Consider reporting to FIU"],
    2: ["Strengthen CDD on new counterparty", "Monitor additional transactions"],
    3: ["Aggregate related transactions", "Review structuring intent", "Verify actual owner name"],
    4: ["Consider immediate account freeze", "Victim verification and protection", "Referral to law enforcement"],
    5: ["Trace fund origin", "Verify business rationale", "Consider account freeze"],
    7: ["Continuous off-hours monitoring", "Pattern-based escalation", "Review by internal committee"],
    # Fallback used by _build_str_report when the fraud type cannot be resolved.
    None: ["Strengthen transaction monitoring", "Manager review", "Consider FIU reporting based on judgment"],
}

# AML pattern name (Korean or English, as models write it) -> Section VI check item
_AML_PATTERN_ITEMS = (
    (("ring", "cycle", "순환", "환거래"), "Structured transactions"),
    (("layering", "레이어링", "다단계"), "Sudden change in transaction pattern"),
    (("funnel", "mule", "대포통장", "집금"), "Use of someone else's name/account"),
    (("structuring", "smurfing", "분할", "스머핑"), "Splitting amount across multiple transfers"),
)

_TOOL_DESCRIPTION_MAP = {
    "query_transactions":    "Directly query HOFINET DB transaction data",
    "predict_fraud":         "XGBoost model risk score for one transaction",
    "analyze_network":       "Account transaction network analysis",
    "get_statistics":        "Query overall statistics dashboard",
    "get_account_profile":   "Query account transaction statistics profile",
    "get_fraud_type_summary": "Query status by fraud type",
    "detect_aml_patterns":   "Graph-based AML pattern detection",
    "compare_periods":        "Comparative analysis of transaction stats by period",
    "get_institution_report": "Comprehensive report for financial institution",
    "rank_risky_transactions": "XGBoost model batch risk ranking",
    "generate_str":          "Generate STR report",
    "detect_ctr_candidates": "Detect CTR high-value/structured transactions",
    "score_account_risk":    "Evaluate account risk (5 behavioral indicators)",
    "detect_monitoring_alerts": "Rule-based transaction monitoring alerts",
    "detect_dormant_reactivation": "Dormant account reactivation detection",
    "detect_smurfing_network": "Money collection/distribution pattern detection",
    "get_trend_analysis":    "Time-series trend analysis",
    "analyze_channel_risk":  "Risk analysis by channel",
    "get_receiving_account_profile": "Receiving account profiling",
    "analyze_cross_institution_flow": "Inter-institution fund flow analysis",
    "lookup_fiu_reference_types": "FIU suspicious-transaction reference catalog lookup",
    "validate_str_fields":   "STR draft field validation",
    "get_aml_glossary":      "AML term definition lookup",
}

_TX_INT_FIELDS = (
    "date", "time_slot", "sender_bank", "sender_acc", "receiver_bank",
    "receiver_acc", "fund_type", "media_type", "amount", "fraud_type",
)

# Account numbers written into a free-text summary, in either language.
_SENDER_ACCOUNT_RE = re.compile(
    r"(?:sender_acc|sender account|withdrawal account|출금\s*계좌(?:번호)?)\D{0,12}(\d{4,})",
    re.IGNORECASE,
)
_RECEIVER_ACCOUNT_RE = re.compile(
    r"(?:receiver_acc|receiver account|receiving account|beneficiary account|"
    r"입금\s*계좌(?:번호)?|수취\s*계좌(?:번호)?)\D{0,12}(\d{4,})",
    re.IGNORECASE,
)
_ANY_ACCOUNT_RE = re.compile(r"(?:account|계좌)\D{0,12}(\d{4,})", re.IGNORECASE)


def _string_list(value) -> list[str]:
    """Reads a list-of-strings argument, accepting a JSON string or 'a, b'."""
    value = _load_json(value)
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if not _is_null(item)]
    return []


def _coerce_transactions(value) -> list[dict]:
    """Reads the transactions argument, which models often send as a JSON string."""
    value = _load_json(value)
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    rows = []
    for item in value:
        item = _load_json(item)
        if not isinstance(item, dict):
            continue
        row = {}
        for key, raw in item.items():
            if _is_null(raw):
                continue
            if key in _TX_INT_FIELDS:
                try:
                    row[key] = _as_int(raw, key)
                except ToolArgumentError:
                    continue
            else:
                row[key] = raw
        rows.append(row)
    return rows


def _resolve_fraud_type(name: str | None) -> tuple[int | None, str | None]:
    """Maps a fraud_type argument to (HOFINET code, §VI category name).

    Accepts the §VI category names of the schema enum, the Korean
    fraud_description values stored in HOFINET, and the English labels the
    tools return.
    """
    if not name:
        return None, None
    text = str(name).strip()
    if text in _VI_CATEGORY_CODES:
        code = _FRAUD_TYPE_ALIASES.get(text.lower())
        return code, text
    code = _FRAUD_TYPE_ALIASES.get(text.lower())
    if code is None:
        return None, None
    return code, _HOFINET_TO_VI_CATEGORY.get(code)


def _build_str_report(
    summary: str,
    fraud_type: str,
    tools_used: list[str],
    transactions: list[dict],
    fraud_probability: float | None,
    aml_patterns: list[str],
) -> dict:
    """Generates a structured report dictionary matching official STR sections (I~VII).

    The reporting date is the HOFINET reference date, not today's date, so the
    same call always produces the same report.
    """
    reference_date = datetime.strptime(str(config.REFERENCE_DATE), "%Y%m%d").strftime("%Y-%m-%d")

    # ── Extract fields from transaction data ──────────────────────────────────────────
    tx = transactions or []

    tx_dates = sorted({str(t["date"]) for t in tx if t.get("date")})
    sender_accounts = sorted({str(t["sender_acc"]) for t in tx if t.get("sender_acc")})
    receiver_accounts = sorted({str(t["receiver_acc"]) for t in tx if t.get("receiver_acc")})
    sender_banks = sorted({str(t["sender_bank"]) for t in tx if t.get("sender_bank")})
    receiver_banks = sorted({str(t["receiver_bank"]) for t in tx if t.get("receiver_bank")})

    media_counts = Counter(t["media_type"] for t in tx if t.get("media_type") is not None)
    channel = _MEDIA_TYPE_MAP.get(
        media_counts.most_common(1)[0][0] if media_counts else None, "Unknown"
    )

    fund_counts = Counter(t["fund_type"] for t in tx if t.get("fund_type") is not None)
    tx_type = _FUND_TYPE_MAP.get(
        fund_counts.most_common(1)[0][0] if fund_counts else None, "Unknown"
    )

    total_amount = sum(t.get("amount", 0) or 0 for t in tx)
    max_single_amount = max((t.get("amount", 0) or 0 for t in tx), default=0)

    fraud_type_counts = Counter(t["fraud_type"] for t in tx if t.get("fraud_type"))
    primary_fraud_code = fraud_type_counts.most_common(1)[0][0] if fraud_type_counts else None
    argument_code, argument_category = _resolve_fraud_type(fraud_type)
    if primary_fraud_code is None:
        primary_fraud_code = argument_code
    vi_category = (
        argument_category
        or _HOFINET_TO_VI_CATEGORY.get(primary_fraud_code)
        or "기타(자유기술)"
    )
    primary_fraud_name = _FRAUD_TYPE_MAP.get(primary_fraud_code) if primary_fraud_code else None

    # Summary fallback (when transactions are not provided)
    if not tx:
        sender_accounts = sorted(set(_SENDER_ACCOUNT_RE.findall(summary)))
        receiver_accounts = sorted(set(_RECEIVER_ACCOUNT_RE.findall(summary)))
        if not sender_accounts and not receiver_accounts:
            found = sorted(set(_ANY_ACCOUNT_RE.findall(summary)))
            sender_accounts = receiver_accounts = found

    # ── VI. Transaction Type Check Items ──────────────────────────────────────────
    vi_items = list(_FRAUD_TYPE_TO_VI_SECTION.get(primary_fraud_code, []))
    for pattern in (aml_patterns or []):
        lowered = str(pattern).lower()
        for aliases, item in _AML_PATTERN_ITEMS:
            if any(alias in lowered for alias in aliases) and item not in vi_items:
                vi_items.append(item)
    if not vi_items:
        vi_items = ["Other features and types - Refer to Section VII narrative"]

    # ── VII. Suspicion Intensity (1~5) ──────────────────────────────────────────────
    if fraud_probability is not None:
        suspicion_intensity = min(5, max(1, round(fraud_probability * 4) + 1))
        suspicion_intensity_desc = (
            f"Based on the model risk score of {fraud_probability:.1%} "
            "(uncalibrated; not a probability of fraud)"
        )
    else:
        suspicion_intensity = 3
        suspicion_intensity_desc = "Model risk score not provided - manual judgment required"

    txn_period = (
        f"{tx_dates[0]} ~ {tx_dates[-1]}" if len(tx_dates) > 1
        else (tx_dates[0] if tx_dates else "Unknown")
    )
    related_account_count = len(set(sender_accounts) | set(receiver_accounts))

    overall_opinion = (
        f"[{reference_date}] {primary_fraud_name or vi_category} suspicious transaction detected. "
        f"Period: {txn_period}, related accounts: {related_account_count}, "
        f"total amount: {total_amount:,} KRW ({len(tx)} txns)."
    )
    if aml_patterns:
        overall_opinion += f" Detected AML patterns: {', '.join(aml_patterns)}."
    overall_opinion += " Manager review and decision on FIU reporting required."

    analysis_grounds = [_TOOL_DESCRIPTION_MAP.get(t, t) for t in (tools_used or [])]
    recommended_actions = _RECOMMENDED_ACTION_MAP.get(
        primary_fraud_code, _RECOMMENDED_ACTION_MAP[None]
    )

    return {
        "ReportType": "Suspicious Transaction Report (STR)",
        "Header": {
            "ReportingDate": reference_date,
            "ReportTypeClassification": "New Report",
        },
        "I_ReportingInstitution": {
            "WithdrawalInstitutionCode": sender_banks or ["Unknown"],
            "Remarks": "Based on institution serial number. Institution name requires verification by manager.",
        },
        "II_Transactor": {
            "WithdrawalAccountNumber": sender_accounts[:5] or ["Unknown"],
            "ReceivingAccountNumber": receiver_accounts[:5] or ["Unknown"],
            "Remarks": "Real name, address, and contact info not included in HOFINET - manual verification required.",
        },
        "III_TransactionDetails": {
            "TransactionPeriod": txn_period,
            "TransactionCount": len(tx),
            "TransactionChannel": channel,
            "TransactionType": tx_type,
            "TotalAmount_KRW": total_amount,
            "MaxSingleAmount_KRW": max_single_amount,
            "RelatedAccountPresence": "Yes" if related_account_count > 0 else "No",
        },
        "IV_RelatedAccounts": {
            "SenderAccountList": sender_accounts[:10],
            "ReceiverAccountList": receiver_accounts[:10],
            "WithdrawalInstitutionCode": sender_banks,
            "ReceivingInstitutionCode": receiver_banks,
        },
        "VI_TransactionType": {
            "PrimarySuspicionType": vi_category,
            "SectionVICode": _VI_CATEGORY_CODES.get(vi_category),
            "HOFINETFraudType": primary_fraud_code,
            "HOFINETFraudTypeName": primary_fraud_name,
            "ApplicableItems": vi_items,
            "DetectedAMLPatterns": aml_patterns or [],
        },
        "VII_Narrative": {
            "SuspiciousTransactorRelated": (
                f"Confirming suspicious transactions related to withdrawal accounts {', '.join(sender_accounts[:3])} "
                f"and receiving accounts {', '.join(receiver_accounts[:3])}."
                if sender_accounts or receiver_accounts else "Transactor info not confirmed - manual verification required"
            ),
            "TransactionOccurrenceDate": txn_period,
            "TransactionMethodAnomalies": f"Primary channel: {channel} / Transaction type: {tx_type}",
            "SuspicionJudgmentReason": summary,
            "OverallOpinion": overall_opinion,
            "SuspicionIntensity_1to5": suspicion_intensity,
            "SuspicionIntensityDescription": suspicion_intensity_desc,
        },
        "RecommendedActions": recommended_actions,
        "AnalysisGrounds": analysis_grounds or ["No analysis tools specified"],
        "GenerationGuide": (
            "This report is a draft automatically generated by the AI Analysis Agent. "
            "Please supplement items not included in HOFINET (such as real name, address, contact info) and submit after review."
        ),
    }


# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------

def _execute_tool(name: str, arguments: dict) -> str:
    """Executes a tool and returns the result as a JSON string.

    All exceptions are handled internally to return a JSON error message,
    so the caller can use it without separate try/except.
    """
    try:
        arguments = _normalize_arguments(arguments)
    except ToolArgumentError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

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
        elif name == "detect_ctr_candidates":
            return _tool_detect_ctr_candidates(arguments)
        elif name == "score_account_risk":
            return _tool_score_account_risk(arguments)
        elif name == "detect_monitoring_alerts":
            return _tool_detect_monitoring_alerts(arguments)
        elif name == "detect_dormant_reactivation":
            return _tool_detect_dormant_reactivation(arguments)
        elif name == "detect_smurfing_network":
            return _tool_detect_smurfing_network(arguments)
        elif name == "get_trend_analysis":
            return _tool_get_trend_analysis(arguments)
        elif name == "analyze_channel_risk":
            return _tool_analyze_channel_risk(arguments)
        elif name == "get_receiving_account_profile":
            return _tool_get_receiving_account_profile(arguments)
        elif name == "analyze_cross_institution_flow":
            return _tool_analyze_cross_institution_flow(arguments)
        elif name == "lookup_fiu_reference_types":
            return _tool_lookup_fiu_reference_types(arguments)
        elif name == "validate_str_fields":
            return _tool_validate_str_fields(arguments)
        elif name == "get_aml_glossary":
            return _tool_get_aml_glossary(arguments)
        else:
            return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)

    except ToolArgumentError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    except Exception as exc:
        logger.error(f"Error executing tool {name}: {str(exc)}")
        return json.dumps(
            {"error": f"An unexpected error occurred during tool execution: {str(exc)}"},
            ensure_ascii=False,
        )


# Read-only SQL guard. The statement is parsed by DuckDB instead of matched
# against the raw text, so CTEs, parenthesised selects, comments and column
# aliases such as last_update_date are accepted, while anything that is not a
# single SELECT is refused. File-reading table functions are blocked here as
# well; the shared connection also runs with external access disabled.
_FILE_FUNCTION_RE = re.compile(
    r"\b(read_[a-z_]+|scan_[a-z_]+|[a-z_]*_scan|glob|sniff_csv|parquet_[a-z_]+)\s*\(",
    re.IGNORECASE,
)
_QUERY_ROW_LIMIT = 100


def _tool_query_transactions(arguments: dict) -> str:
    sql = arguments.get("sql")
    sql = sql.strip() if isinstance(sql, str) else ""

    if not sql:
        return json.dumps({"error": "SQL query is empty."}, ensure_ascii=False)

    try:
        statements = duckdb.extract_statements(sql)
    except Exception as exc:
        return json.dumps({"error": f"SQL syntax error: {str(exc)[:200]}"}, ensure_ascii=False)

    if len(statements) != 1:
        return json.dumps(
            {"error": "Exactly one SELECT statement can be executed per call."},
            ensure_ascii=False,
        )
    if statements[0].type != duckdb.StatementType.SELECT:
        return json.dumps(
            {"error": "Only SELECT queries are allowed."},
            ensure_ascii=False,
        )
    if _FILE_FUNCTION_RE.search(sql):
        return json.dumps(
            {"error": "Reading files is not allowed; query the 'hofinet' table."},
            ensure_ascii=False,
        )

    try:
        df = query(sql)
    except Exception as exc:
        # Convert DuckDB errors to user-friendly messages
        err_msg = str(exc)
        if "Catalog Error" in err_msg or "does not exist" in err_msg:
            return json.dumps(
                {"error": "Table or column not found. Please ensure column names are in English (date, amount, etc.)."},
                ensure_ascii=False,
            )
        if "Parser Error" in err_msg or "SyntaxError" in err_msg:
            return json.dumps(
                {"error": f"SQL syntax error: {err_msg[:200]}"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"error": f"Query execution error: {err_msg[:300]}"},
            ensure_ascii=False,
        )

    total = 0 if df is None else len(df)
    result = _records(df.head(_QUERY_ROW_LIMIT)) if total else []
    payload = {"total_count": total, "returned_count": len(result), "result": result}
    if total == 0:
        payload["notice"] = "No data found."
    elif total > _QUERY_ROW_LIMIT:
        payload["notice"] = f"Returning the first {_QUERY_ROW_LIMIT} of {total} rows."
    return json.dumps(payload, ensure_ascii=False)


def _tool_predict_fraud(arguments: dict) -> str:
    from src.features.detector import FEATURE_COLS

    values, errors = _validate_predict_fraud_args(arguments)
    if errors:
        return json.dumps(
            {"error": "Input parameter error", "details": errors},
            ensure_ascii=False,
        )

    model = load_model()
    if model is None:
        return json.dumps(
            {"error": "No trained model found. Please train the model on the Detection page first."},
            ensure_ascii=False,
        )

    try:
        # Feature order is fixed by FEATURE_COLS: the order the model sent its
        # arguments in, and any extra key, must not change the score.
        features = pd.DataFrame([[values[col] for col in FEATURE_COLS]], columns=FEATURE_COLS)
        score = float(model.predict_proba(features)[:, 1][0])
    except Exception as exc:
        return json.dumps(
            {"error": f"Model prediction error: {str(exc)}"},
            ensure_ascii=False,
        )

    level = "High" if score >= 0.7 else ("Medium" if score >= 0.3 else "Low")
    return json.dumps(
        {
            "fraud_risk_score": round(score, 4),
            "risk_level": level,
            "score_type": "uncalibrated XGBoost score in [0, 1]; not a probability of fraud",
            "input_values": {col: values[col] for col in FEATURE_COLS},
        },
        ensure_ascii=False,
    )


def _tool_generate_str(arguments: dict) -> str:
    summary = arguments.get("summary")
    if isinstance(summary, (int, float)):
        summary = str(summary)
    summary = summary.strip() if isinstance(summary, str) else ""
    if not summary:
        return json.dumps({"error": "Summary content for STR generation is empty."}, ensure_ascii=False)

    risk_score = None
    if "fraud_probability" in arguments:
        risk_score = _as_float(arguments["fraud_probability"], "fraud_probability")
        if 1 < risk_score <= 100:
            risk_score = risk_score / 100
        if not 0 <= risk_score <= 1:
            return json.dumps(
                {"error": f"fraud_probability({arguments['fraud_probability']!r}) must be between 0 and 1."},
                ensure_ascii=False,
            )

    report = _build_str_report(
        summary=summary,
        fraud_type=arguments.get("fraud_type"),
        tools_used=_string_list(arguments.get("tools_used")),
        transactions=_coerce_transactions(arguments.get("transactions")),
        fraud_probability=risk_score,
        aml_patterns=_string_list(arguments.get("aml_patterns")),
    )
    return json.dumps(report, ensure_ascii=False)


def _tool_analyze_network(arguments: dict) -> str:
    aid = _req_int(arguments, "account_id")
    hops = max(1, min(_opt_int(arguments, "hops", 1) or 1, 5))

    try:
        summary = summarize_account_network(aid, hops=hops)
    except Exception as exc:
        return json.dumps(
            {"error": f"Network retrieval error: {str(exc)}"},
            ensure_ascii=False,
        )

    if summary["total_tx_count"] == 0:
        return json.dumps(
            {
                "account_id": aid,
                "search_hop_range": hops,
                "notice": "No transaction history for this account.",
                "connected_account_count": 0,
                "total_tx_count": 0,
                "fraud_tx_count": 0,
                "fraud_ratio_percent": 0.0,
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "account_id": aid,
            "search_hop_range": hops,
            "connected_account_count": summary["connected_account_count"],
            "total_tx_count": summary["total_tx_count"],
            "fraud_tx_count": summary["fraud_tx_count"],
            "fraud_ratio_percent": _percent(summary["fraud_tx_count"], summary["total_tx_count"], 2),
            "total_amount": summary["total_amount"],
            "connected_account_samples": summary["connected_account_samples"],
        },
        ensure_ascii=False,
    )


def _tool_detect_aml_patterns(arguments: dict) -> str:
    pattern_type = arguments.get("pattern_type", "")
    limit = _limit(arguments)
    account_id = _opt_int(arguments, "account_id")

    if pattern_type == "ring":
        min_len = _opt_int(arguments, "min_len", 3)
        max_len = _opt_int(arguments, "max_len", 6)
        try:
            df = detect_ring_transactions(
                min_len=min_len, max_len=max_len, limit=limit, account_id=account_id,
            )
        except Exception as exc:
            return json.dumps({"error": f"Ring transaction detection error: {str(exc)}"}, ensure_ascii=False)

        records = _records(df)
        payload = {"pattern": "Ring", "count": len(records), "result": records}
        if not records:
            payload["notice"] = (
                f"No ring pattern of {min_len}-{max_len} fraud transfers found. "
                "HOFINET's transfer graph is acyclic, so rings do not occur in this dataset."
            )
        return json.dumps(payload, ensure_ascii=False)

    elif pattern_type == "layering":
        min_layers = _opt_int(arguments, "min_layers", 3)
        try:
            df = detect_layering_patterns(
                min_layers=min_layers, limit=limit, account_id=account_id,
            )
        except Exception as exc:
            return json.dumps({"error": f"Layering pattern detection error: {str(exc)}"}, ensure_ascii=False)

        records = _records(df)
        payload = {"pattern": "Multi-stage Layering", "count": len(records), "result": records}
        if not records:
            payload["notice"] = (
                f"No chain of {min_layers} or more consecutive fraud transfers found. "
                "The longest such chain in HOFINET is 2 transfers."
            )
        return json.dumps(payload, ensure_ascii=False)

    elif pattern_type == "funnel":
        min_inflow = _opt_int(arguments, "min_inflow", 10)
        max_outflow = _opt_int(arguments, "max_outflow", 3)
        try:
            df = detect_funnel_accounts(
                min_inflow=min_inflow, max_outflow=max_outflow,
                limit=limit, account_id=account_id,
            )
        except Exception as exc:
            return json.dumps({"error": f"Funnel pattern detection error: {str(exc)}"}, ensure_ascii=False)

        records = _records(df)
        payload = {
            "pattern": "Funnel (collect and forward)",
            "criteria": {"min_inflow": min_inflow, "max_outflow": max_outflow},
            "count": len(records),
            "result": records,
        }
        if not records:
            payload["notice"] = (
                f"No account receives from {min_inflow} or more accounts and forwards to "
                f"1-{max_outflow} accounts. Only 414 HOFINET accounts both receive and send."
            )
        return json.dumps(payload, ensure_ascii=False)

    elif pattern_type == "shortest_path":
        if "account_a" not in arguments or "account_b" not in arguments:
            return json.dumps(
                {"error": "shortest_path requires account_a and account_b."},
                ensure_ascii=False,
            )
        account_a = _req_int(arguments, "account_a")
        account_b = _req_int(arguments, "account_b")
        try:
            result = find_shortest_path(account_a, account_b)
        except Exception as exc:
            return json.dumps({"error": f"Shortest path search error: {str(exc)}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    elif pattern_type == "risk_score":
        if account_id is None:
            return json.dumps(
                {"error": "risk_score requires account_id."},
                ensure_ascii=False,
            )
        try:
            result = compute_risk_score(account_id)
        except Exception as exc:
            return json.dumps({"error": f"Risk score calculation error: {str(exc)}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    else:
        return json.dumps(
            {"error": f"Unknown pattern type: {pattern_type}. Valid values: ring, layering, funnel, shortest_path, risk_score"},
            ensure_ascii=False,
        )


def _tool_get_statistics() -> str:
    try:
        summary_df = get_summary()
        fraud_type_df = get_fraud_type_distribution()
    except Exception as exc:
        return json.dumps(
            {"error": f"Statistics retrieval error: {str(exc)}"},
            ensure_ascii=False,
        )

    if summary_df is None or summary_df.empty:
        return json.dumps({"error": "Unable to retrieve summary statistics."}, ensure_ascii=False)

    row = summary_df.iloc[0]
    summary_dict = {
        "total_tx_count": int(row.get("total_txns", 0)),
        "fraud_tx_count": int(row.get("fraud_txns", 0)),
        "fraud_ratio_percent": float(row.get("fraud_ratio", 0.0)),
        "sender_account_count": int(row.get("sender_accounts", 0)),
        "receiver_account_count": int(row.get("receiver_accounts", 0)),
        "sender_bank_count": int(row.get("sender_banks", 0)),
        "receiver_bank_count": int(row.get("receiver_banks", 0)),
        "total_amount": int(row.get("total_amount", 0)),
    }

    if fraud_type_df is not None and not fraud_type_df.empty:
        fraud_types = fraud_type_df.to_dict(orient="records")
    else:
        fraud_types = []

    return json.dumps(
        {"summary_statistics": summary_dict, "fraud_type_distribution": fraud_types},
        ensure_ascii=False,
    )


def _tool_get_account_profile(arguments: dict) -> str:
    aid = _req_int(arguments, "account_id")

    try:
        agg_df = query(
            "SELECT COUNT(*)::BIGINT AS total_count, "
            "COUNT(*) FILTER (WHERE sender_acc = $aid)::BIGINT AS outbound_count, "
            "COUNT(*) FILTER (WHERE receiver_acc = $aid)::BIGINT AS inbound_count, "
            "COALESCE(SUM(amount), 0)::BIGINT AS total_amount, "
            "COALESCE(SUM(is_fraud), 0)::BIGINT AS fraud_count "
            "FROM hofinet WHERE sender_acc = $aid OR receiver_acc = $aid",
            {"aid": aid},
        )
        row = agg_df.iloc[0]
        total_count = _int_value(row["total_count"])

        if total_count == 0:
            return json.dumps(
                {"account_id": aid, "total_count": 0,
                 "notice": "No transaction history for this account."},
                ensure_ascii=False,
            )

        # Transactions in either direction, so a receive-only account is profiled too.
        hour_df = query(
            "SELECT time_slot, COUNT(*) AS cnt FROM hofinet "
            "WHERE sender_acc = $aid OR receiver_acc = $aid "
            "GROUP BY time_slot ORDER BY cnt DESC, time_slot LIMIT 3",
            {"aid": aid},
        )
        top_hours = [int(v) for v in hour_df["time_slot"].tolist()]

        media_df = query(
            "SELECT media_type, COUNT(*) AS cnt FROM hofinet "
            "WHERE sender_acc = $aid OR receiver_acc = $aid "
            "GROUP BY media_type ORDER BY cnt DESC, media_type LIMIT 3",
            {"aid": aid},
        )
        top_media = [_MEDIA_TYPE_MAP.get(int(c), f"Code {c}") for c in media_df["media_type"].tolist()]

        cp_df = query(
            "SELECT receiver_acc AS counterpart_id, 'outbound' AS direction, "
            "       COUNT(*)::BIGINT AS tx_count, COALESCE(SUM(amount), 0)::BIGINT AS total_amount "
            "FROM hofinet WHERE sender_acc = $aid GROUP BY receiver_acc "
            "UNION ALL "
            "SELECT sender_acc, 'inbound', "
            "       COUNT(*)::BIGINT, COALESCE(SUM(amount), 0)::BIGINT "
            "FROM hofinet WHERE receiver_acc = $aid GROUP BY sender_acc "
            "ORDER BY tx_count DESC, counterpart_id, direction LIMIT 5",
            {"aid": aid},
        )
        top_counterparts = [
            {
                "account_id": int(r["counterpart_id"]),
                "direction": r["direction"],
                "count": _int_value(r["tx_count"]),
                "amount": _int_value(r["total_amount"]),
            }
            for _, r in cp_df.iterrows()
        ]

    except ToolArgumentError:
        raise
    except Exception as exc:
        return json.dumps(
            {"error": f"Account profile retrieval error: {str(exc)}"},
            ensure_ascii=False,
        )

    fraud_count = _int_value(row["fraud_count"])
    return json.dumps(
        {
            "account_id": aid,
            "total_count": total_count,
            "outbound_count": _int_value(row["outbound_count"]),
            "inbound_count": _int_value(row["inbound_count"]),
            "total_amount": _int_value(row["total_amount"]),
            "fraud_count": fraud_count,
            "fraud_ratio_percent": _percent(fraud_count, total_count),
            "top_hours": top_hours,
            "top_media": top_media,
            "top_counterparts": top_counterparts,
        },
        ensure_ascii=False,
    )


def _no_fraud_rows_notice(bank_id) -> str:
    if bank_id is None:
        return "No fraud transactions recorded for this type."
    return f"No fraud transactions recorded for this type with sender bank {bank_id}."


def _tool_get_fraud_type_summary(arguments: dict) -> str:
    ftype = _req_int(arguments, "fraud_type")

    if ftype not in _FRAUD_TYPE_MAP:
        return json.dumps(
            {"error": f"fraud_type({ftype}) must be one of {sorted(_FRAUD_TYPE_MAP)} "
                      "(code 6 is not used in HOFINET)."},
            ensure_ascii=False,
        )

    bid = _opt_int(arguments, "bank_id")

    try:
        # Basic aggregation
        if bid is not None:
            agg_df = query(
                "SELECT COUNT(*) AS total_count, SUM(amount) AS total_amount, "
                "AVG(amount) AS avg_amount "
                "FROM hofinet "
                "WHERE is_fraud = 1 AND fraud_type = $ftype "
                "AND sender_bank = $bid",
                {"ftype": ftype, "bid": bid},
            )
        else:
            agg_df = query(
                "SELECT COUNT(*) AS total_count, SUM(amount) AS total_amount, "
                "AVG(amount) AS avg_amount "
                "FROM hofinet WHERE is_fraud = 1 AND fraud_type = $ftype",
                {"ftype": ftype},
            )

        if agg_df is None or agg_df.empty:
            return json.dumps(
                {
                    "type_code": ftype,
                    "type_name": _FRAUD_TYPE_MAP.get(ftype, "Other"),
                    "bank_filter": bid,
                    "total_count": 0,
                    "notice": _no_fraud_rows_notice(bid),
                },
                ensure_ascii=False,
            )

        row = agg_df.iloc[0]
        total_count = _int_value(row["total_count"])
        total_amount = _int_value(row["total_amount"])
        avg_amount = _float_value(row["avg_amount"], digits=2)

        if total_count == 0:
            return json.dumps(
                {
                    "type_code": ftype,
                    "type_name": _FRAUD_TYPE_MAP.get(ftype, "Other"),
                    "bank_filter": bid,
                    "total_count": 0,
                    "notice": _no_fraud_rows_notice(bid),
                },
                ensure_ascii=False,
            )

        # Top financial institutions
        if bid is not None:
            bank_df = query(
                "SELECT sender_bank AS bank_id, COUNT(*)::BIGINT AS cnt "
                "FROM hofinet WHERE is_fraud = 1 AND fraud_type = $ftype "
                "AND sender_bank = $bid "
                "GROUP BY sender_bank ORDER BY cnt DESC, bank_id LIMIT 5",
                {"ftype": ftype, "bid": bid},
            )
        else:
            bank_df = query(
                "SELECT sender_bank AS bank_id, COUNT(*)::BIGINT AS cnt "
                "FROM hofinet WHERE is_fraud = 1 AND fraud_type = $ftype "
                "GROUP BY sender_bank ORDER BY cnt DESC, bank_id LIMIT 5",
                {"ftype": ftype},
            )

        top_banks = []
        if bank_df is not None and not bank_df.empty:
            for _, brow in bank_df.iterrows():
                top_banks.append({
                    "bank_id": int(brow["bank_id"]),
                    "count": _int_value(brow["cnt"]),
                })

        # Sample dates (latest 5)
        if bid is not None:
            date_df = query(
                "SELECT DISTINCT date FROM hofinet "
                "WHERE is_fraud = 1 AND fraud_type = $ftype "
                "AND sender_bank = $bid "
                "ORDER BY date DESC LIMIT 5",
                {"ftype": ftype, "bid": bid},
            )
        else:
            date_df = query(
                "SELECT DISTINCT date FROM hofinet "
                "WHERE is_fraud = 1 AND fraud_type = $ftype "
                "ORDER BY date DESC LIMIT 5",
                {"ftype": ftype},
            )

        sample_dates = [int(v) for v in date_df["date"].tolist()] if date_df is not None else []

    except Exception as exc:
        return json.dumps(
            {"error": f"Fraud type lookup error: {str(exc)}"},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "type_code": ftype,
            "type_name": _FRAUD_TYPE_MAP.get(ftype, "Other"),
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
    missing = [
        name for name in ("period1_start", "period1_end", "period2_start", "period2_end")
        if name not in arguments
    ]
    if missing:
        return json.dumps(
            {"error": f"Missing required dates: {', '.join(missing)} (YYYYMMDD integers)."},
            ensure_ascii=False,
        )
    p1s = _opt_date(arguments, "period1_start")
    p1e = _opt_date(arguments, "period1_end")
    p2s = _opt_date(arguments, "period2_start")
    p2e = _opt_date(arguments, "period2_end")

    if p1s > p1e or p2s > p2e:
        return json.dumps({"error": "Start date cannot be later than end date."}, ensure_ascii=False)

    try:
        df1 = query(
            f"""
            SELECT COUNT(*)::BIGINT AS total_count,
                   COALESCE(SUM(is_fraud), 0)::BIGINT AS fraud_count,
                   COALESCE(SUM(amount), 0)::BIGINT AS total_amount,
                   AVG(amount) AS avg_amount
            FROM hofinet
            WHERE date BETWEEN {p1s} AND {p1e}
            """
        )
        df2 = query(
            f"""
            SELECT COUNT(*)::BIGINT AS total_count,
                   COALESCE(SUM(is_fraud), 0)::BIGINT AS fraud_count,
                   COALESCE(SUM(amount), 0)::BIGINT AS total_amount,
                   AVG(amount) AS avg_amount
            FROM hofinet
            WHERE date BETWEEN {p2s} AND {p2e}
            """
        )
    except Exception as exc:
        return json.dumps({"error": f"Period comparison lookup error: {str(exc)}"}, ensure_ascii=False)

    def _row(df):
        if df is None or df.empty:
            return {"total_count": 0, "fraud_count": 0, "total_amount": 0, "avg_amount": 0.0}
        r = df.iloc[0]
        return {
            "total_count": _int_value(r["total_count"]),
            "fraud_count": _int_value(r["fraud_count"]),
            "total_amount": _int_value(r["total_amount"]),
            "avg_amount": _float_value(r["avg_amount"], digits=2),
        }

    r1 = _row(df1)
    r2 = _row(df2)

    def _delta(v1, v2):
        if v1 == 0:
            return None
        return round((v2 - v1) / v1 * 100, 2)

    fraud_ratio1 = _percent(r1["fraud_count"], r1["total_count"])
    fraud_ratio2 = _percent(r2["fraud_count"], r2["total_count"])

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
    bid = _req_int(arguments, "bank_id")

    try:
        agg_df = query(
            "SELECT "
            "  COUNT(*) FILTER (WHERE sender_bank = $bid)::BIGINT AS out_count, "
            "  COALESCE(SUM(is_fraud) FILTER (WHERE sender_bank = $bid), 0)::BIGINT AS out_fraud, "
            "  COALESCE(SUM(amount) FILTER (WHERE sender_bank = $bid), 0)::BIGINT AS out_amount, "
            "  AVG(amount) FILTER (WHERE sender_bank = $bid) AS out_avg, "
            "  COUNT(*) FILTER (WHERE receiver_bank = $bid)::BIGINT AS in_count, "
            "  COALESCE(SUM(is_fraud) FILTER (WHERE receiver_bank = $bid), 0)::BIGINT AS in_fraud, "
            "  COALESCE(SUM(amount) FILTER (WHERE receiver_bank = $bid), 0)::BIGINT AS in_amount, "
            "  AVG(amount) FILTER (WHERE receiver_bank = $bid) AS in_avg "
            "FROM hofinet WHERE sender_bank = $bid OR receiver_bank = $bid",
            {"bid": bid},
        )
        row = agg_df.iloc[0]
        out_count = _int_value(row["out_count"])
        in_count = _int_value(row["in_count"])

        if out_count == 0 and in_count == 0:
            return json.dumps(
                {"bank_id": bid, "total_count": 0,
                 "notice": "No transaction history for this institution."},
                ensure_ascii=False,
            )

        out_fraud = _int_value(row["out_fraud"])
        in_fraud = _int_value(row["in_fraud"])

        # Counterpart institutions, both directions.
        cp_df = query(
            "SELECT receiver_bank AS bank_id, COUNT(*)::BIGINT AS tx_count, "
            "       COALESCE(SUM(amount), 0)::BIGINT AS total_amount "
            "FROM hofinet WHERE sender_bank = $bid "
            "GROUP BY receiver_bank ORDER BY tx_count DESC, bank_id LIMIT 5",
            {"bid": bid},
        )
        source_df = query(
            "SELECT sender_bank AS bank_id, COUNT(*)::BIGINT AS tx_count, "
            "       COALESCE(SUM(amount), 0)::BIGINT AS total_amount "
            "FROM hofinet WHERE receiver_bank = $bid "
            "GROUP BY sender_bank ORDER BY tx_count DESC, bank_id LIMIT 5",
            {"bid": bid},
        )

        # Fraud type distribution over transactions on either side of the bank.
        type_df = query(
            "SELECT fraud_type, COUNT(*)::BIGINT AS cnt "
            "FROM hofinet "
            "WHERE (sender_bank = $bid OR receiver_bank = $bid) AND is_fraud = 1 "
            "GROUP BY fraud_type ORDER BY cnt DESC, fraud_type",
            {"bid": bid},
        )

        # Quarterly trend (integer quarter arithmetic; see R1-N1).
        trend_df = query(
            "SELECT CAST(date / 10000 AS INT) AS year, "
            "       (date // 100 % 100 - 1) // 3 + 1 AS quarter, "
            "       COUNT(*) FILTER (WHERE sender_bank = $bid)::BIGINT AS outbound_count, "
            "       COALESCE(SUM(is_fraud) FILTER (WHERE sender_bank = $bid), 0)::BIGINT AS outbound_fraud_count, "
            "       COUNT(*) FILTER (WHERE receiver_bank = $bid)::BIGINT AS inbound_count, "
            "       COALESCE(SUM(is_fraud) FILTER (WHERE receiver_bank = $bid), 0)::BIGINT AS inbound_fraud_count "
            "FROM hofinet WHERE sender_bank = $bid OR receiver_bank = $bid "
            "GROUP BY year, quarter ORDER BY year, quarter",
            {"bid": bid},
        )

    except ToolArgumentError:
        raise
    except Exception as exc:
        return json.dumps(
            {"error": f"Institution report lookup error: {str(exc)}"},
            ensure_ascii=False,
        )

    def _counterparts(df):
        return [
            {
                "bank_id": int(r["bank_id"]),
                "count": _int_value(r["tx_count"]),
                "amount": _int_value(r["total_amount"]),
            }
            for _, r in df.iterrows()
        ]

    fraud_type_dist = [
        {
            "type_code": _int_value(r["fraud_type"]),
            "type_name": _FRAUD_TYPE_MAP.get(_int_value(r["fraud_type"]), "Other"),
            "count": _int_value(r["cnt"]),
        }
        for _, r in type_df.iterrows()
    ]

    quarterly_trend = [
        {
            "quarter": f"{_int_value(r['year'])}Q{_int_value(r['quarter'])}",
            "outbound_count": _int_value(r["outbound_count"]),
            "outbound_fraud_count": _int_value(r["outbound_fraud_count"]),
            "inbound_count": _int_value(r["inbound_count"]),
            "inbound_fraud_count": _int_value(r["inbound_fraud_count"]),
        }
        for _, r in trend_df.iterrows()
    ]

    return json.dumps(
        {
            "bank_id": bid,
            "total_count": out_count + in_count,
            "outbound": {
                "total_count": out_count,
                "fraud_count": out_fraud,
                "fraud_ratio_percent": _percent(out_fraud, out_count),
                "total_amount": _int_value(row["out_amount"]),
                "avg_amount": _float_value(row["out_avg"], digits=2),
            },
            "inbound": {
                "total_count": in_count,
                "fraud_count": in_fraud,
                "fraud_ratio_percent": _percent(in_fraud, in_count),
                "total_amount": _int_value(row["in_amount"]),
                "avg_amount": _float_value(row["in_avg"], digits=2),
            },
            "top_counterpart_banks": _counterparts(cp_df),
            "top_source_banks": _counterparts(source_df),
            "fraud_type_distribution": fraud_type_dist,
            "quarterly_trend": quarterly_trend,
        },
        ensure_ascii=False,
    )


_RANK_SAMPLE_MAX = 5000


def _tool_rank_risky_transactions(arguments: dict) -> str:
    requested_sample = _opt_int(arguments, "sample_size", 1000) or 1000
    sample_size = min(max(requested_sample, 1), _RANK_SAMPLE_MAX)
    top_k = min(max(_opt_int(arguments, "top_k", 20) or 20, 1), 100)

    model = load_model()
    if model is None:
        return json.dumps(
            {"error": "No trained model found. Please train the model on the Detection page first."},
            ensure_ascii=False,
        )

    try:
        from src.features.detector import predict_from_db
        df = predict_from_db(model, limit=sample_size)
    except Exception as exc:
        return json.dumps(
            {"error": f"Batch prediction error: {str(exc)}"},
            ensure_ascii=False,
        )

    if df is None or df.empty:
        return json.dumps({"notice": "No transaction data to score.", "results": []}, ensure_ascii=False)

    # The ground-truth label is not returned: the agent must judge the ranking
    # from the score, not from the answer key.
    records = []
    for _, row in df.head(top_k).iterrows():
        records.append({
            "date": int(row["date"]),
            "time_slot": int(row["time_slot"]),
            "sender_bank": int(row["sender_bank"]),
            "sender_acc": int(row["sender_acc"]),
            "receiver_bank": int(row["receiver_bank"]),
            "receiver_acc": int(row["receiver_acc"]),
            "fund_type": int(row["fund_type"]),
            "media_type": int(row["media_type"]),
            "amount": int(row["amount"]),
            "fraud_risk_score": round(float(row["prob"]), 4),
        })

    payload = {
        "sample_size": sample_size,
        "top_k": top_k,
        "total_returned": len(records),
        "score_type": "uncalibrated XGBoost score in [0, 1]; not a probability of fraud",
        "results": records,
    }
    if requested_sample > _RANK_SAMPLE_MAX:
        payload["notice"] = (
            f"sample_size {requested_sample} exceeds the maximum {_RANK_SAMPLE_MAX}; "
            f"scored {sample_size} transactions."
        )
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 12: detect_ctr_candidates
# ---------------------------------------------------------------------------


def _tool_detect_ctr_candidates(arguments: dict) -> str:
    mode = arguments.get("mode", "")
    date_from = _opt_date(arguments, "date_from")
    date_to = _opt_date(arguments, "date_to")
    threshold = _opt_int(arguments, "threshold", 10_000_000)
    limit = _limit(arguments)

    if mode not in ("high_value", "structuring"):
        return json.dumps(
            {"error": "mode must be 'high_value' or 'structuring'."},
            ensure_ascii=False,
        )

    try:
        if mode == "high_value":
            df = get_ctr_candidates(
                date_from=date_from, date_to=date_to,
                threshold=threshold, limit=limit,
            )
            notice = "No transactions at or above the threshold."
        else:
            df = detect_structuring(
                date_from=date_from, date_to=date_to,
                threshold=threshold, limit=limit,
            )
            notice = "No suspected structured transactions found."
    except Exception as exc:
        return json.dumps(
            {"error": f"CTR detection error: {str(exc)}"},
            ensure_ascii=False,
        )

    records = _records(df)
    payload = {"mode": mode, "threshold": threshold, "count": len(records), "result": records}
    if not records:
        payload["notice"] = notice
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 13: score_account_risk
# ---------------------------------------------------------------------------


def _tool_score_account_risk(arguments: dict) -> str:
    aid = _req_int(arguments, "account_id")

    try:
        result = _score_account_risk(aid)
    except Exception as exc:
        return json.dumps(
            {"error": f"Risk assessment error: {str(exc)}"},
            ensure_ascii=False,
        )

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 14: detect_monitoring_alerts
# ---------------------------------------------------------------------------


def _tool_detect_monitoring_alerts(arguments: dict) -> str:
    rule_id = arguments.get("rule_id", "")
    date_from = _opt_date(arguments, "date_from")
    date_to = _opt_date(arguments, "date_to")
    account_id = _opt_int(arguments, "account_id")
    limit = _limit(arguments)

    valid_rules = ["all", *sorted(RULE_NAMES)]
    if rule_id not in valid_rules:
        return json.dumps(
            {"error": f"rule_id must be one of {valid_rules}."},
            ensure_ascii=False,
        )
    if date_from is not None and date_to is not None and date_from > date_to:
        return json.dumps(
            {"error": "date_from must not be later than date_to."},
            ensure_ascii=False,
        )

    filters = {"date_from": date_from, "date_to": date_to, "account_id": account_id}
    notice = None
    if rule_id in ("all", "R005") and (date_from is None or date_to is None):
        window = default_pattern_change_period()
        notice = (
            f"R005 compares the last quarter of the data ({window[0]}-{window[1]}) with the "
            "preceding quarter, because no date range was given."
        )

    try:
        if rule_id == "all":
            result = run_all_rules(date_from, date_to, account_id, limit=limit)
            payload = {"rule_id": "all", "filters": filters, "result": result}
            if notice:
                payload["notice"] = notice
            return json.dumps(payload, ensure_ascii=False)

        df = run_rule(rule_id, date_from, date_to, account_id, limit=limit)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {"error": f"Monitoring rule execution error: {str(exc)}"},
            ensure_ascii=False,
        )

    payload = {
        "rule_id": rule_id,
        "rule_name": RULE_NAMES[rule_id],
        "filters": filters,
        "count": len(df),
        "result": _records(df),
    }
    if df.empty:
        payload["notice"] = "No alerts detected."
    elif notice:
        payload["notice"] = notice
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 15: detect_dormant_reactivation
# ---------------------------------------------------------------------------


def _tool_detect_dormant_reactivation(arguments: dict) -> str:
    dormant_days = _opt_int(arguments, "dormant_days", 180)
    min_amount = _opt_int(arguments, "min_reactivation_amount", 5_000_000)
    limit = _limit(arguments)

    try:
        df = detect_dormant_reactivation(
            dormant_days=dormant_days,
            min_reactivation_amount=min_amount,
            limit=limit,
        )
    except Exception as exc:
        return json.dumps(
            {"error": f"Dormant account reactivation detection error: {str(exc)}"},
            ensure_ascii=False,
        )

    records = _records(df)
    payload = {
        "criteria": {"dormant_days": dormant_days, "min_reactivation_amount": min_amount},
        "count": len(records),
        "result": records,
    }
    if not records:
        payload["notice"] = "No dormant reactivation accounts matching criteria."
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 16: detect_smurfing_network
# ---------------------------------------------------------------------------


def _tool_detect_smurfing_network(arguments: dict) -> str:
    direction = arguments.get("direction", "")
    if direction not in ("inbound", "outbound"):
        return json.dumps(
            {"error": "direction must be 'inbound' or 'outbound'."},
            ensure_ascii=False,
        )

    account_id = _opt_int(arguments, "account_id")
    min_counterparts = _opt_int(arguments, "min_counterparts", 5)
    date_from = _opt_date(arguments, "date_from")
    date_to = _opt_date(arguments, "date_to")
    limit = _limit(arguments)

    try:
        df = _detect_smurfing_network(
            account_id=account_id,
            direction=direction,
            min_counterparts=min_counterparts,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    except Exception as exc:
        return json.dumps(
            {"error": f"Fund collection/distribution pattern detection error: {str(exc)}"},
            ensure_ascii=False,
        )

    records = _records(df)
    payload = {
        "direction": direction,
        "min_counterparts": min_counterparts,
        "count": len(records),
        "result": records,
    }
    if not records:
        label = "Fund collection" if direction == "inbound" else "Fund distribution"
        payload["notice"] = f"{label} pattern not detected with these criteria."
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 17: get_trend_analysis
# ---------------------------------------------------------------------------


def _tool_get_trend_analysis(arguments: dict) -> str:
    unit = arguments.get("unit", "monthly")
    if unit not in ("monthly", "quarterly"):
        return json.dumps(
            {"error": f"unit('{unit}') must be 'monthly' or 'quarterly'."},
            ensure_ascii=False,
        )

    date_from = _opt_date(arguments, "date_from")
    date_to = _opt_date(arguments, "date_to")

    try:
        df = _get_trend_analysis(
            unit=unit, date_from=date_from, date_to=date_to,
        )
    except Exception as exc:
        return json.dumps(
            {"error": f"Trend analysis error: {str(exc)}"},
            ensure_ascii=False,
        )

    records = _records(df)
    payload = {"unit": unit, "period_count": len(records), "result": records}
    if not records:
        payload["notice"] = "No data found for this period."
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 18: analyze_channel_risk
# ---------------------------------------------------------------------------


def _tool_analyze_channel_risk(arguments: dict) -> str:
    date_from = _opt_date(arguments, "date_from")
    date_to = _opt_date(arguments, "date_to")

    try:
        result = _analyze_channel_risk(date_from=date_from, date_to=date_to)
    except Exception as exc:
        return json.dumps(
            {"error": f"Channel risk analysis error: {str(exc)}"},
            ensure_ascii=False,
        )

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 19: get_receiving_account_profile
# ---------------------------------------------------------------------------


def _tool_get_receiving_account_profile(arguments: dict) -> str:
    aid = _req_int(arguments, "account_id")

    try:
        result = _get_receiving_account_profile(aid)
    except Exception as exc:
        return json.dumps(
            {"error": f"Receiving account profile lookup error: {str(exc)}"},
            ensure_ascii=False,
        )

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 20: analyze_cross_institution_flow
# ---------------------------------------------------------------------------


def _tool_analyze_cross_institution_flow(arguments: dict) -> str:
    date_from = _opt_date(arguments, "date_from")
    date_to = _opt_date(arguments, "date_to")
    min_transactions = _opt_int(arguments, "min_transactions", 10)
    limit = _limit(arguments)

    try:
        df = _analyze_cross_institution_flow(
            date_from=date_from, date_to=date_to,
            min_transactions=min_transactions, limit=limit,
        )
    except Exception as exc:
        return json.dumps(
            {"error": f"Inter-institution fund flow analysis error: {str(exc)}"},
            ensure_ascii=False,
        )

    records = _records(df)
    payload = {"min_transactions": min_transactions, "count": len(records), "result": records}
    if not records:
        payload["notice"] = "No significant inter-institution flows found matching criteria."
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 21: lookup_fiu_reference_types
# ---------------------------------------------------------------------------


def _tool_lookup_fiu_reference_types(arguments: dict) -> str:
    keyword = arguments.get("keyword") or ""
    industry = arguments.get("industry")
    if industry is not None and industry not in ("banking", "securities"):
        return json.dumps(
            {"error": "industry must be 'banking' or 'securities', or be omitted."},
            ensure_ascii=False,
        )

    results = lookup_fiu_reference_types(keyword, industry)
    payload = {"keyword": keyword, "industry": industry, "count": len(results), "result": results}
    if not results:
        payload["notice"] = (
            "No catalog entry contains this keyword. The catalog is in English; "
            "try a term such as structuring, cash, non-face-to-face, virtual asset or dormancy, "
            "or call the tool without a keyword to list every entry."
        )
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 22: validate_str_fields
# ---------------------------------------------------------------------------


def _tool_validate_str_fields(arguments: dict) -> str:
    str_draft = arguments.get("str_draft")
    if str_draft is None:
        return json.dumps({"error": "str_draft is required."}, ensure_ascii=False)

    result = validate_str_fields(str_draft)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 23: get_aml_glossary
# ---------------------------------------------------------------------------


def _tool_get_aml_glossary(arguments: dict) -> str:
    term = arguments.get("term") or ""
    result = get_aml_glossary(term)
    if result is None:
        return json.dumps(
            {
                "error": f"Term '{term}' not found.",
                "available_terms": glossary_terms(),
            },
            ensure_ascii=False,
        )
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# OpenAI Message Serialization
# ---------------------------------------------------------------------------

def _message_to_dict(msg):
    """Converts ChatCompletionMessage to OpenAI API compatible dict."""
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
# Execute Conversation - Return tool call info together
# ---------------------------------------------------------------------------

MAX_TOOL_ROUNDS = 5


def _build_chat_client() -> tuple["OpenAI", str, dict]:
    """Builds the chat client and selects model.

    Returns (client, model, extra_headers).

    Routing precedence:
      1. OPENROUTER_API_KEY set  → OpenRouter (OpenAI-compatible) with
         OPENROUTER_BASE_URL + OPENROUTER_MODEL.
      2. Otherwise               → direct OpenAI with OPENAI_API_KEY + gpt-4o-mini.

    OpenRouter accepts optional HTTP-Referer / X-Title headers for app
    attribution; we pass them through `extra_headers` when present.
    """
    if config.OPENROUTER_API_KEY:
        client = OpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
        )
        extra_headers: dict = {}
        if config.OPENROUTER_HTTP_REFERER:
            extra_headers["HTTP-Referer"] = config.OPENROUTER_HTTP_REFERER
        if config.OPENROUTER_X_TITLE:
            extra_headers["X-Title"] = config.OPENROUTER_X_TITLE
        return client, config.OPENROUTER_MODEL, extra_headers

    return OpenAI(api_key=config.OPENAI_API_KEY), "gpt-4o-mini", {}


def chat(messages: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """Performs conversation with the LLM and returns response.

    Routes through OpenRouter when OPENROUTER_API_KEY is set, otherwise falls
    back to direct OpenAI (see `_build_chat_client`).

    Args:
        messages: Conversation history (list of dicts, including user/assistant/tool)

    Returns:
        (assistant_content, updated_messages, tool_events)
        - tool_events: each tool call info [{name, arguments, result}, ...]
    """
    client, model, extra_headers = _build_chat_client()

    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    tool_events: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        request_kwargs: dict = dict(
            model=model,
            messages=full_messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=4096,
        )
        if extra_headers:
            request_kwargs["extra_headers"] = extra_headers
        response = client.chat.completions.create(**request_kwargs)

        msg = response.choices[0].message

        if not msg.tool_calls:
            break

        # If there are tool calls, execute and call again
        assistant_dict = _message_to_dict(msg)
        messages.append(assistant_dict)
        full_messages.append(assistant_dict)

        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            result = _execute_tool(tool_name, tool_args)

            # Record tool event (for UI visualization)
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
