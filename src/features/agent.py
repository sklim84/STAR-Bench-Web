"""Feature 4: AI Analysis Agent Module.

Registers Features 1-3 as tools using OpenAI function calling,
analyzes suspicious transactions through conversation, and generates STR drafts.
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
from src.features.ctr_monitor import (
    get_ctr_candidates,
    detect_structuring,
)
from src.features.risk_scorer import score_account as _score_account_risk
from src.features.monitoring import (
    detect_nighttime_bulk,
    detect_rapid_fire,
    detect_round_amounts,
    detect_institution_concentration,
    detect_pattern_change,
    run_all_rules,
    detect_dormant_reactivation,
    _calculate_previous_period,
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
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_transactions",
            "description": (
                "Executes SQL queries on the HOFINET database to retrieve transaction data. "
                "The table name is 'hofinet' and columns are: date, time_slot, sender_bank, "
                "sender_acc, receiver_bank, receiver_acc, fund_type, media_type, "
                "amount, is_fraud, fraud_type, fraud_description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "SELECT SQL query to execute. Perform aggregation, filtering, "
                            "and grouping on the 'hofinet' table."
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
            "description": "Predicts the probability of fraud for a transaction using the trained XGBoost model. Returns a probability between 0 and 1.",
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
                "Generates a Suspicious Transaction Report (STR) in the official format (Sections I-VII) based on analysis results. "
                "Always query related transaction data with 'query_transactions' first and include the records in the 'transactions' parameter."
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
                        "description": "HOFINET fraud type classification",
                        "enum": ["Money Laundering", "Mule Account", "Voice Phishing", "Illegal Gambling", "Illegal Private Finance", "New Customer", "Other"],
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
                        "description": "Fraud probability predicted by predict_fraud (0.0-1.0). Used for calculating suspicion intensity (1-5).",
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
            "description": "Analyzes the transaction network of a specific account. Returns connected account count, transaction frequency, and fraud association.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "Account number to analyze (sender_acc)",
                    },
                    "hops": {
                        "type": "integer",
                        "description": "Search depth (1-5). Default is 1. Hops >= 3 requires Memgraph.",
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
            "description": "Retrieves dashboard summary statistics. Returns basic stats including total transaction count, fraud count/ratio, and distribution by fraud type.",
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
                "Retrieves the transaction profile for a specific account. "
                "Returns total transaction count/amount, fraud count/ratio, primary transaction hours, "
                "main channels used, and top 5 counterparties."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "Account number to query (sender_acc)",
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
                "Retrieves details by fraud type (Money Laundering, Voice Phishing, Mule Account, etc.). "
                "Returns count/amount statistics and top associated institutions. "
                "Code mapping: 1=Money Laundering, 2=New Counterparty, 3=Mule Account, 4=Voice Phishing, 5=Illegal Gambling, 6=Illegal Private Finance, 7=Other"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fraud_type": {
                        "type": "integer",
                        "description": "Fraud type code (1-7)",
                        "enum": [1, 2, 3, 4, 5, 6, 7],
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
                "Reports the comprehensive status of a specific financial institution. "
                "Returns transaction scale (count/amount), fraud ratio, top counterparts, "
                "distribution by fraud type, and quarterly trends."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bank_id": {
                        "type": "integer",
                        "description": "Financial institution ID to query (sender_bank)",
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
                "Predicts samples from the database using the trained XGBoost model "
                "and returns the top-K high-risk ones. Useful for mass detection and prioritization. "
                "Fails if no model is found."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_size": {
                        "type": "integer",
                        "description": "Number of samples to predict (default 1000, max 5000)",
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
                "Detects AML (Anti-Money Laundering) patterns using Memgraph Graph DB. "
                "Identifies ring transactions, layering, funnel (mule) patterns, "
                "finds shortest paths between accounts, or calculates account risk scores."
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
                "mode=high_value: Query transactions over 10M KRW. "
                "mode=structuring: Detect suspected structuring where multiple transactions on the same day sum above threshold."
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
                        "description": "Reporting threshold (default 10,000,000 KRW)",
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
                "Evaluates an account's risk score (0-100) based on 5 indicators (nighttime ratio, "
                "amount anomaly, diversity, velocity change, fraud history). "
                "Returns risk level (High/Medium/Low) and component scores."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "integer",
                        "description": "Account number to evaluate (sender_acc)",
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
                "Detects rule-based transaction monitoring alerts. "
                "R001=Nighttime Bulk, R002=Rapid Fire, R003=Round Amount Pattern, "
                "R004=Institution Concentration, R005=Pattern Change. "
                "Use rule_id='all' to run all rules."
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
                        "description": "Optional account filter",
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
                "Detects accounts reactivated after a long period of dormancy. "
                "Finds accounts with no transactions for a set period (default 180 days) followed by large transactions. "
                "Useful for identifying mule accounts or money laundering patterns."
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
                "Detects fund collection (many-to-one) or distribution (one-to-many) patterns. "
                "direction=inbound: Funds converging from many accounts to one (collection). "
                "direction=outbound: Funds dispersing from one account to many. "
                "Used for identifying mule accounts, placement stage, or smurfing."
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
                "Analyzes monthly or quarterly time-series trends. "
                "Tracks changes in transaction volume, fraud ratio, and amounts over time. "
                "Returns trends for a specified range or the entire period if omitted."
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
                "Analyzes risk by transaction channel (medium_type). "
                "Returns fraud ratios for ATM, Internet Banking, PB, Counter, etc., "
                "along with channel x hour cross-analysis results."
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
                "Profiles an account from a fund-receiving (inbound) perspective. "
                "Analyzes inflow patterns based on receiver_acc to identify who sends funds "
                "and how diverse the sources are."
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
                "Searches FIU reference types for suspicious transactions by industry. "
                "Used to check if transaction patterns match FIU reference types. "
                "Search keywords: structuring, nighttime, non-face-to-face, virtual assets, third-party name, dormancy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Search keyword (e.g., structuring, nighttime, non-face-to-face, virtual assets)",
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
                "Performs validation of mandatory fields for an STR (Suspicious Transaction Report) draft. "
                "Checks for missing mandatory items such as header, reporting institution, transactor, and transaction details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "str_draft": {
                        "type": "object",
                        "description": "STR draft dict. Can be nested by section (e.g., I_ReportingInstitution, II_Transactor, III_TransactionDetails)",
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
                "Returns definitions of AML terms. "
                "CDD, EDD, STR, CTR, RBA, PEP, MLRO, FATF, FIU, KYE, structuring, layering, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "Term to lookup (e.g., CDD, STR, CTR, RBA, PEP)",
                    },
                },
                "required": ["term"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are an Anti-Money Laundering (AML) analysis expert.
You analyze HOFINET (Electronic Financial Network) fraud detection data to detect and report suspicious money laundering transactions.

Available Tools:
1. get_statistics: Overall summary and fraud type distribution (use first)
2. query_transactions: Execute SQL on HOFINET DB for detailed analysis
3. get_account_profile: Statistics for a specific account
4. get_fraud_type_summary: Summary by fraud type (1=Money Laundering, 2=New Customer, 3=Mule Account, 4=Voice Phishing, 5=Illegal Gambling, 6=Illegal Private Finance, 7=Other)
5. compare_periods: Compare stats between two periods
6. get_institution_report: Comprehensive report for a financial institution
7. rank_risky_transactions: Batch prediction ranking
8. analyze_network: Account network analysis (N-hop)
9. detect_aml_patterns: Memgraph-based AML pattern detection (Ring, Layering, Funnel, etc.)
10. predict_fraud: XGBoost model probability prediction
11. generate_str: Generate Suspicious Transaction Report (STR)
12. detect_ctr_candidates: CTR candidates or structuring detection (mode=high_value or structuring)
13. score_account_risk: Risk evaluation (0-100) based on 5 behavioral indicators
14. detect_monitoring_alerts: Rule-based alerts (R001-R005)
15. detect_dormant_reactivation: Dormant account reactivation detection
16. detect_smurfing_network: Inbound/outbound smurfing detection
17. get_trend_analysis: Monthly/quarterly time-series trends
18. analyze_channel_risk: Risk analysis by channel (media_type)
19. get_receiving_account_profile: Receiving account profiling
20. analyze_cross_institution_flow: Fund flow between institution pairs
21. lookup_fiu_reference_types: Search FIU reference types (structuring, nighttime, non-face-to-face, etc.)
22. validate_str_fields: STR draft validation
23. get_aml_glossary: AML term definitions (CDD, EDD, STR, CTR, RBA, PEP, etc.)

Recommended Analysis Flow:
1. Statistics overview -> 2. Trend analysis -> 3. Detailed query -> 4. CTR/Structuring detection -> 5. Risk score -> 6. Monitoring alerts -> 7. Dormant reactivation -> 8. Smurfing detection -> 9. Channel risk -> 10. Receiving profile -> 11. External flow -> 12. Network analysis -> 13. AML pattern detection -> 14. Model prediction -> 15. STR generation (only with sufficient evidence)

STR Generation Notes:
- Always query data first with query_transactions.
- Include transaction records in the transactions parameter for auto-extraction.
- Pass fraud_probability from predict_fraud if performed.
- Include aml_patterns from detect_aml_patterns results.

Data Schema:
- Table: hofinet (4,732,130 records)
- Columns: date(YYYYMMDD), time_slot(0-21, 3h units), sender_bank, sender_acc, receiver_bank, receiver_acc, fund_type(0,1,3,4), media_type(1-7), amount, is_fraud(0/1), fraud_type(1-7), fraud_description
- fraud_type: 1=Money Laundering, 2=New Customer, 3=Mule Account, 4=Voice Phishing, 5=Illegal Gambling, 6=Illegal Private Finance, 7=Other
- media_type: 1=Counter, 2=ATM, 3=PB Center, 4=Internet Banking, 5=Phone, 6=Call Center, 7=Other
- fund_type: 0=N/A, 1=Deposit, 3=Withdrawal, 4=Transfer

Respond in English. Provide specific figures and evidence in your analysis."""


# ---------------------------------------------------------------------------
# Parameter Validation Helpers
# ---------------------------------------------------------------------------

_VALID_TIME_SLOTS = {0, 3, 6, 9, 12, 15, 18, 21}
_VALID_FUND_TYPES = {0, 1, 3, 4}
_VALID_MEDIA_TYPES = set(range(1, 8))


def _validate_predict_fraud_args(arguments: dict) -> list[str]:
    """Validates predict_fraud parameters."""
    errors = []
    time_slot = arguments.get("time_slot")
    if time_slot not in _VALID_TIME_SLOTS:
        errors.append(f"time_slot({time_slot}) must be one of {sorted(_VALID_TIME_SLOTS)}.")
    fund_type = arguments.get("fund_type")
    if fund_type not in _VALID_FUND_TYPES:
        errors.append(f"fund_type({fund_type}) must be one of {sorted(_VALID_FUND_TYPES)}.")
    media_type = arguments.get("media_type")
    if media_type not in _VALID_MEDIA_TYPES:
        errors.append(f"media_type({media_type}) must be between 1 and 7.")
    amount = arguments.get("amount")
    if not isinstance(amount, (int, float)) or amount <= 0:
        errors.append(f"amount({amount}) must be a positive integer.")
    return errors


# ---------------------------------------------------------------------------
# STR Structural Helpers - Code Mapping Tables
# ---------------------------------------------------------------------------

_MEDIA_TYPE_MAP = {
    1: "Counter", 2: "ATM", 3: "PB Center",
    4: "Internet Banking", 5: "Phone/Mobile", 6: "Call Center", 7: "Other",
}

_FUND_TYPE_MAP = {0: "N/A", 1: "Deposit", 3: "Withdrawal", 4: "Transfer"}

_FRAUD_TYPE_MAP = {
    1: "Money Laundering", 2: "New Customer", 3: "Mule Account",
    4: "Voice Phishing", 5: "Illegal Gambling", 6: "Illegal Private Finance", 7: "Other",
}

# Mapping fraud type codes to STR Section VI suspicion items
_FRAUD_TYPE_TO_VI_SECTION = {
    1: ["Structured transactions", "Sudden change in transaction pattern"],
    2: ["Suspicious request from customer with no prior transactions"],
    3: ["Use of someone else's name/account", "Use of one-off accounts"],
    4: ["Withdrawal on same/next day after large deposit", "Frequent deposits/withdrawals"],
    5: ["Frequent deposits/withdrawals", "Sudden change in transaction pattern"],
    6: ["Simultaneous requests for multiple transactions", "Use of one-off accounts"],
}

_RECOMMENDED_ACTION_MAP = {
    "Money Laundering": ["Strengthen transaction monitoring", "Investigate related accounts", "Consider reporting to FIU"],
    "Mule Account":      ["Immediate account monitoring", "Verify actual owner name", "Consider referral to law enforcement"],
    "Voice Phishing":   ["Consider immediate account freeze", "Victim verification and protection", "Referral to law enforcement"],
    "Illegal Gambling": ["Continuous pattern monitoring", "Consider referral to authorities", "Consider transaction limits"],
    "Illegal Private Finance": ["Verify investor damage", "Referral to authorities", "Consider account freeze"],
    "New Customer":     ["Strengthen CDD", "Monitor additional transactions"],
    "Other":            ["Conduct additional monitoring", "Preserve transaction history", "Review by internal committee"],
}

# AML pattern name → STR Section VI check item mapping
_PATTERN_TO_VI_SECTION_MAP = {
    "Ring": "Structured transactions",
    "Layering": "Sudden change in transaction pattern",
    "Funnel": "Use of someone else's name/account",
}

_TOOL_DESCRIPTION_MAP = {
    "query_transactions":    "Directly query HOFINET DB transaction data",
    "predict_fraud":         "XGBoost fraud probability model prediction",
    "analyze_network":       "Account transaction network analysis",
    "get_statistics":        "Query overall statistics dashboard",
    "get_account_profile":   "Query account transaction statistics profile",
    "get_fraud_type_summary": "Query status by fraud type",
    "detect_aml_patterns":   "Memgraph graph DB AML pattern detection",
    "compare_periods":        "Comparative analysis of transaction stats by period",
    "get_institution_report": "Comprehensive report for financial institution",
    "rank_risky_transactions": "XGBoost model batch prediction risk ranking",
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
}


def _build_str_report(
    summary: str,
    fraud_type: str,
    tools_used: list[str],
    transactions: list[dict],
    fraud_probability: float | None,
    aml_patterns: list[str],
) -> dict:
    """Generates a structured report dictionary matching official STR sections (I~VII)."""
    today = date.today().strftime("%Y-%m-%d")

    # ── Extract fields from transaction data ──────────────────────────────────────────
    tx = transactions or []

    tx_dates = sorted({str(t.get("date", "")) for t in tx if t.get("date")})
    sender_accounts = list({str(t["sender_acc"]) for t in tx if t.get("sender_acc")})
    receiver_accounts = list({str(t["receiver_acc"]) for t in tx if t.get("receiver_acc")})
    sender_banks = list({str(t["sender_bank"]) for t in tx if t.get("sender_bank")})
    receiver_banks = list({str(t["receiver_bank"]) for t in tx if t.get("receiver_bank")})

    media_counts = Counter(t.get("media_type") for t in tx if t.get("media_type"))
    channel = _MEDIA_TYPE_MAP.get(
        media_counts.most_common(1)[0][0] if media_counts else None, "Unknown"
    )

    fund_counts = Counter(t.get("fund_type") for t in tx if t.get("fund_type") is not None)
    tx_type = _FUND_TYPE_MAP.get(
        fund_counts.most_common(1)[0][0] if fund_counts else None, "Unknown"
    )

    total_amount = sum(t.get("amount", 0) for t in tx)
    max_single_amount = max((t.get("amount", 0) for t in tx), default=0)

    fraud_type_counts = Counter(t.get("fraud_type") for t in tx if t.get("fraud_type"))
    primary_fraud_code = fraud_type_counts.most_common(1)[0][0] if fraud_type_counts else None
    primary_fraud_name = _FRAUD_TYPE_MAP.get(primary_fraud_code, fraud_type or "Other")

    # Summary regex fallback (when transactions are not provided)
    if not tx:
        account_candidates = re.findall(r"(?:account|sender_acc|receiver_acc)[^\d]*(\d{5,})", summary)
        sender_accounts = receiver_accounts = list(set(account_candidates))

    # ── VI. Transaction Type Check Items ──────────────────────────────────────────
    vi_items = list(_FRAUD_TYPE_TO_VI_SECTION.get(primary_fraud_code, []))
    for p in (aml_patterns or []):
        for k, v in _PATTERN_TO_VI_SECTION_MAP.items():
            if k in p and v not in vi_items:
                vi_items.append(v)
    if not vi_items:
        vi_items = ["Other features and types - Refer to Section VII narrative"]

    # ── VII. Suspicion Intensity (1~5) ──────────────────────────────────────────────
    if fraud_probability is not None:
        suspicion_intensity = min(5, max(1, round(fraud_probability * 4) + 1))
        suspicion_intensity_desc = f"Based on AI model prediction probability of {fraud_probability:.1%}"
    else:
        suspicion_intensity = 3
        suspicion_intensity_desc = "AI prediction not performed - manual judgment required"

    txn_period = (
        f"{tx_dates[0]} ~ {tx_dates[-1]}" if len(tx_dates) > 1
        else (tx_dates[0] if tx_dates else "Unknown")
    )
    related_account_count = len(set(sender_accounts) | set(receiver_accounts))

    overall_opinion = (
        f"[{today}] {primary_fraud_name} suspicious transaction detected. "
        f"Period: {txn_period}, related accounts: {related_account_count}, "
        f"total amount: {total_amount:,} KRW ({len(tx)} txns)."
    )
    if aml_patterns:
        overall_opinion += f" Detected AML patterns: {', '.join(aml_patterns)}."
    overall_opinion += " Manager review and decision on FIU reporting required."

    analysis_grounds = [_TOOL_DESCRIPTION_MAP.get(t, t) for t in (tools_used or [])]
    recommended_actions = _RECOMMENDED_ACTION_MAP.get(primary_fraud_name, _RECOMMENDED_ACTION_MAP["Other"])

    return {
        "ReportType": "Suspicious Transaction Report (STR)",
        "Header": {
            "ReportingDate": today,
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
            "PrimarySuspicionType": primary_fraud_name,
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
# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------

def _execute_tool(name: str, arguments: dict) -> str:
    """Executes a tool and returns the result as a JSON string.

    All exceptions are handled internally to return a JSON error message,
    so the caller can use it without separate try/except.
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

    except Exception as exc:
        logger.error(f"Error executing tool {name}: {str(exc)}")
        return json.dumps(
            {"error": f"An unexpected error occurred during tool execution: {str(exc)}"},
            ensure_ascii=False,
        )


def _tool_query_transactions(arguments: dict) -> str:
    sql = arguments.get("sql", "").strip()

    if not sql:
        return json.dumps({"error": "SQL query is empty."}, ensure_ascii=False)

    # Allow SELECT only (prevention of SQL injection)
    if not sql.upper().startswith("SELECT"):
        return json.dumps({"error": "Only SELECT queries are allowed."}, ensure_ascii=False)

    # Block dangerous keywords
    forbidden = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE"]
    sql_upper = sql.upper()
    for kw in forbidden:
        if kw in sql_upper:
            return json.dumps(
                {"error": f"Queries containing '{kw}' keyword cannot be executed."},
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

    if df is None or df.empty:
        return json.dumps({"result": [], "notice": "No data found."}, ensure_ascii=False)

    # Limit to top 100 if result is too large
    total = len(df)
    if total > 100:
        df = df.head(100)
        result = json.loads(df.to_json(orient="records", force_ascii=False))
        return json.dumps(
            {"result": result, "total_count": total, "notice": f"Returning top 100 of {total} total records."},
            ensure_ascii=False,
        )

    return df.to_json(orient="records", force_ascii=False)


def _tool_predict_fraud(arguments: dict) -> str:
    # Validate parameters
    errors = _validate_predict_fraud_args(arguments)
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
        # Use English internal names for feature DF if model was trained with them
        features = pd.DataFrame([arguments])
        # Mapping incoming English keys to expected feature names if they differ
        # (Assuming model features were also internationalized)
        prob = model.predict_proba(features)[:, 1][0]
        level = "High" if prob >= 0.7 else ("Medium" if prob >= 0.3 else "Low")
        return json.dumps(
            {
                "fraud_probability": round(float(prob), 4),
                "risk_level": level,
                "input_values": arguments,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {"error": f"Model prediction error: {str(exc)}"},
            ensure_ascii=False,
        )


def _tool_generate_str(arguments: dict) -> str:
    summary = arguments.get("summary", "").strip()
    if not summary:
        return json.dumps({"error": "Summary content for STR generation is empty."}, ensure_ascii=False)

    report = _build_str_report(
        summary=summary,
        fraud_type=arguments.get("fraud_type", "Other"),
        tools_used=arguments.get("tools_used", []),
        transactions=arguments.get("transactions", []),
        fraud_probability=arguments.get("fraud_probability"),
        aml_patterns=arguments.get("aml_patterns", []),
    )
    return json.dumps(report, ensure_ascii=False)


def _tool_analyze_network(arguments: dict) -> str:
    account_id = arguments.get("account_id")
    if account_id is None:
        return json.dumps({"error": "account_id is required."}, ensure_ascii=False)

    try:
        aid = int(account_id)
    except (TypeError, ValueError):
        return json.dumps({"error": "account_id must be an integer."}, ensure_ascii=False)

    hops = max(1, min(int(arguments.get("hops", 1)), 5))

    try:
        if hops > 2:
            df = get_account_ego_network_deep(aid, hops=hops)
        else:
            df = get_account_ego_network(aid, hops=hops)
    except Exception as exc:
        return json.dumps(
            {"error": f"Network retrieval error: {str(exc)}"},
            ensure_ascii=False,
        )

    if df is None or df.empty:
        return json.dumps(
            {
                "account_id": aid,
                "notice": "No transaction history for this account.",
                "connected_account_count": 0,
                "total_tx_count": 0,
                "fraud_tx_count": 0,
                "fraud_ratio": 0.0,
            },
            ensure_ascii=False,
        )

    # Extract account IDs from ego network
    def _to_int_set(values):
        out = set()
        for v in values:
            try:
                out.add(int(v))
            except (TypeError, ValueError):
                continue
        return out

    all_accounts = _to_int_set(df["source"].tolist()) | _to_int_set(df["target"].tolist())
    all_accounts.discard(aid)
    connected_count = len(all_accounts)

    total_count = int(df["tx_count"].sum()) if "tx_count" in df.columns else 0
    fraud_count = int(df["is_fraud"].sum()) if "is_fraud" in df.columns else 0
    fraud_ratio = round(fraud_count / total_count * 100, 2) if total_count > 0 else 0.0
    total_amount = int(df["total_amount"].sum()) if "total_amount" in df.columns else 0

    # Sample connected accounts (max 10)
    sample_accounts = sorted(list(all_accounts))[:10]

    return json.dumps(
        {
            "account_id": aid,
            "search_hop_range": hops,
            "connected_account_count": connected_count,
            "total_tx_count": total_count,
            "fraud_tx_count": fraud_count,
            "fraud_ratio_percent": fraud_ratio,
            "total_amount": total_amount,
            "connected_account_samples": sample_accounts,
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
            return json.dumps({"error": f"Ring transaction detection error: {str(exc)}"}, ensure_ascii=False)

        if df.empty:
            return json.dumps(
                {
                    "notice": "No ring transaction patterns detected. Please ensure Memgraph is running.",
                    "result": [],
                },
                ensure_ascii=False,
            )
        records = df.to_dict(orient="records")
        return json.dumps(
            {"pattern": "Ring", "count": len(records), "result": records},
            ensure_ascii=False,
        )

    elif pattern_type == "layering":
        try:
            df = detect_layering_patterns(
                min_layers=arguments.get("min_layers", 3),
                limit=arguments.get("limit", 20),
            )
        except Exception as exc:
            return json.dumps({"error": f"Layering pattern detection error: {str(exc)}"}, ensure_ascii=False)

        if df.empty:
            return json.dumps(
                {
                    "notice": "No layering patterns detected. Please ensure Memgraph is running.",
                    "result": [],
                },
                ensure_ascii=False,
            )
        records = df.to_dict(orient="records")
        return json.dumps(
            {"pattern": "Multi-stage Layering", "count": len(records), "result": records},
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
            return json.dumps({"error": f"Mule account pattern detection error: {str(exc)}"}, ensure_ascii=False)

        if df.empty:
            return json.dumps(
                {
                    "notice": "No mule account patterns detected. Please ensure Memgraph is running.",
                    "result": [],
                },
                ensure_ascii=False,
            )
        records = df.to_dict(orient="records")
        return json.dumps(
            {"pattern": "Mule Account (Funnel)", "count": len(records), "result": records},
            ensure_ascii=False,
        )

    elif pattern_type == "shortest_path":
        account_a = arguments.get("account_a")
        account_b = arguments.get("account_b")
        if not account_a or not account_b:
            return json.dumps(
                {"error": "shortest_path requires account_a and account_b."},
                ensure_ascii=False,
            )
        try:
            result = find_shortest_path(account_a, account_b)
        except Exception as exc:
            return json.dumps({"error": f"Shortest path search error: {str(exc)}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    elif pattern_type == "risk_score":
        account_id = arguments.get("account_id")
        if not account_id:
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
    account_id = arguments.get("account_id")
    if account_id is None:
        return json.dumps({"error": "account_id is required."}, ensure_ascii=False)

    try:
        aid = int(account_id)
    except (TypeError, ValueError):
        return json.dumps({"error": "account_id must be an integer."}, ensure_ascii=False)

    try:
        # Basic aggregation: outbound
        out_df = query(
            "SELECT COUNT(*) AS cnt, SUM(amount) AS total_amount, "
            "SUM(is_fraud) AS fraud_cnt "
            "FROM hofinet WHERE sender_acc = $aid",
            {"aid": aid},
        )
        # Inbound
        in_df = query(
            "SELECT COUNT(*) AS cnt, SUM(amount) AS total_amount, "
            "SUM(is_fraud) AS fraud_cnt "
            "FROM hofinet WHERE receiver_acc = $aid",
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
                {"account_id": aid, "notice": "No transaction history for this account."},
                ensure_ascii=False,
            )

        # Top transaction time slots (outbound)
        hour_df = query(
            "SELECT time_slot, COUNT(*) AS cnt FROM hofinet "
            "WHERE sender_acc = $aid "
            "GROUP BY time_slot ORDER BY cnt DESC LIMIT 3",
            {"aid": aid},
        )
        top_hours = hour_df["time_slot"].tolist() if hour_df is not None and not hour_df.empty else []

        # Top media types (outbound)
        media_df = query(
            "SELECT media_type, COUNT(*) AS cnt FROM hofinet "
            "WHERE sender_acc = $aid "
            "GROUP BY media_type ORDER BY cnt DESC LIMIT 3",
            {"aid": aid},
        )
        top_media_codes = media_df["media_type"].tolist() if media_df is not None and not media_df.empty else []
        top_media = [_MEDIA_TYPE_MAP.get(int(c), f"Code {c}") for c in top_media_codes]

        # Top 5 counterpart accounts (based on outbound receiver)
        cp_df = query(
            "SELECT receiver_acc AS counterpart_id, "
            "COUNT(*) AS tx_count, SUM(amount) AS total_amount "
            "FROM hofinet WHERE sender_acc = $aid "
            "GROUP BY receiver_acc ORDER BY tx_count DESC LIMIT 5",
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
            {"error": f"Account profile retrieval error: {str(exc)}"},
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
        return json.dumps({"error": "fraud_type is required."}, ensure_ascii=False)

    try:
        ftype = int(fraud_type)
    except (TypeError, ValueError):
        return json.dumps({"error": "fraud_type must be an integer between 1 and 7."}, ensure_ascii=False)

    if ftype not in range(1, 8):
        return json.dumps(
            {"error": f"fraud_type({ftype}) must be in range 1-7."},
            ensure_ascii=False,
        )

    bank_id_raw = arguments.get("bank_id")
    bid = int(bank_id_raw) if bank_id_raw is not None else None

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
                    "notice": "No fraud transactions recorded for this type.",
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
                    "type_name": _FRAUD_TYPE_MAP.get(ftype, "Other"),
                    "notice": "No fraud transactions recorded for this type.",
                },
                ensure_ascii=False,
            )

        # Top financial institutions
        if bid is not None:
            bank_df = query(
                "SELECT sender_bank AS bank_id, COUNT(*) AS cnt "
                "FROM hofinet WHERE is_fraud = 1 AND fraud_type = $ftype "
                "AND sender_bank = $bid "
                "GROUP BY sender_bank ORDER BY cnt DESC LIMIT 5",
                {"ftype": ftype, "bid": bid},
            )
        else:
            bank_df = query(
                "SELECT sender_bank AS bank_id, COUNT(*) AS cnt "
                "FROM hofinet WHERE is_fraud = 1 AND fraud_type = $ftype "
                "GROUP BY sender_bank ORDER BY cnt DESC LIMIT 5",
                {"ftype": ftype},
            )

        top_banks = []
        if bank_df is not None and not bank_df.empty:
            for _, brow in bank_df.iterrows():
                top_banks.append({
                    "bank_id": int(brow["bank_id"]),
                    "count": int(brow["cnt"]),
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

        sample_dates = date_df["date"].tolist() if date_df is not None and not date_df.empty else []

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
    try:
        p1s = int(arguments.get("period1_start", 0))
        p1e = int(arguments.get("period1_end", 0))
        p2s = int(arguments.get("period2_start", 0))
        p2e = int(arguments.get("period2_end", 0))
    except (TypeError, ValueError):
        return json.dumps({"error": "Dates must be YYYYMMDD integers."}, ensure_ascii=False)

    if p1s > p1e or p2s > p2e:
        return json.dumps({"error": "Start date cannot be later than end date."}, ensure_ascii=False)

    try:
        df1 = query(
            f"""
            SELECT COUNT(*) AS total_count,
                   SUM(is_fraud) AS fraud_count,
                   AVG(amount) AS avg_amount
            FROM hofinet
            WHERE date BETWEEN {p1s} AND {p1e}
            """
        )
        df2 = query(
            f"""
            SELECT COUNT(*) AS total_count,
                   SUM(is_fraud) AS fraud_count,
                   AVG(amount) AS avg_amount
            FROM hofinet
            WHERE date BETWEEN {p2s} AND {p2e}
            """
        )
    except Exception as exc:
        return json.dumps({"error": f"Period comparison lookup error: {str(exc)}"}, ensure_ascii=False)

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
        return json.dumps({"error": "bank_id is required."}, ensure_ascii=False)
    try:
        bid = int(bank_id_raw)
    except (TypeError, ValueError):
        return json.dumps({"error": "bank_id must be an integer."}, ensure_ascii=False)

    try:
        # Basic aggregation (inbound)
        agg_df = query(
            "SELECT COUNT(*) AS total_count, "
            "SUM(is_fraud) AS fraud_count, "
            "SUM(amount) AS total_amount, "
            "AVG(amount) AS avg_amount "
            "FROM hofinet WHERE sender_bank = $bid",
            {"bid": bid},
        )

        if agg_df is None or agg_df.empty or int(agg_df.iloc[0]["total_count"] or 0) == 0:
            return json.dumps(
                {"bank_id": bid, "notice": "No transaction history for this institution."},
                ensure_ascii=False,
            )

        row = agg_df.iloc[0]
        total_count = int(row["total_count"] or 0)
        fraud_count = int(row["fraud_count"] or 0)
        total_amount = int(row["total_amount"] or 0)
        avg_amount = round(float(row["avg_amount"] or 0.0), 2)
        fraud_ratio = round(fraud_count / total_count * 100, 4) if total_count > 0 else 0.0

        # Top counterpart institutions
        cp_df = query(
            "SELECT receiver_bank AS counterpart_bank_id, "
            "COUNT(*) AS tx_count, SUM(amount) AS total_amount "
            "FROM hofinet WHERE sender_bank = $bid "
            "GROUP BY receiver_bank ORDER BY tx_count DESC LIMIT 5",
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

        # Fraud type distribution
        type_df = query(
            "SELECT fraud_type, COUNT(*) AS cnt "
            "FROM hofinet "
            "WHERE sender_bank = $bid AND is_fraud = 1 "
            "GROUP BY fraud_type ORDER BY cnt DESC",
            {"bid": bid},
        )
        fraud_type_dist = []
        if type_df is not None and not type_df.empty:
            for _, r in type_df.iterrows():
                ftype = int(r["fraud_type"]) if r["fraud_type"] is not None else 0
                fraud_type_dist.append({
                    "type_code": ftype,
                    "type_name": _FRAUD_TYPE_MAP.get(ftype, "Other"),
                    "count": int(r["cnt"]),
                })

    except Exception as exc:
        return json.dumps(
            {"error": f"Institution report lookup error: {str(exc)}"},
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
            {"error": "No trained model found. Please train the model on the Detection page first."},
            ensure_ascii=False,
        )

    try:
        from src.features.detector import predict_from_db, FEATURE_COLS
        df = predict_from_db(model, limit=sample_size)
    except Exception as exc:
        return json.dumps(
            {"error": f"Batch prediction error: {str(exc)}"},
            ensure_ascii=False,
        )

    if df is None or df.empty:
        return json.dumps({"notice": "No transaction data to predict.", "results": []}, ensure_ascii=False)

    top_df = df.head(top_k)
    records = []
    for _, row in top_df.iterrows():
        records.append({
            "sender_acc": int(row["sender_acc"]),
            "receiver_acc": int(row["receiver_acc"]),
            "date": int(row["date"]),
            "time_slot": int(row["time_slot"]),
            "amount": int(row["amount"]),
            "fraud_probability": round(float(row["predict_prob"]), 4),
            "is_fraud_actual": int(row["is_fraud"]) if "is_fraud" in row else None,
        })

    return json.dumps(
        {
            "sample_size": sample_size,
            "top_k": top_k,
            "total_returned": len(records),
            "results": records,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Tool 12: detect_ctr_candidates
# ---------------------------------------------------------------------------


def _tool_detect_ctr_candidates(arguments: dict) -> str:
    mode = arguments.get("mode", "")
    date_from = arguments.get("date_from")
    date_to = arguments.get("date_to")
    threshold = int(arguments.get("threshold", 10_000_000))
    limit = min(int(arguments.get("limit", 20)), 100)

    if mode not in ("high_value", "structuring"):
        return json.dumps(
            {"error": "mode must be 'high_value' or 'structuring'."},
            ensure_ascii=False,
        )

    try:
        if mode == "high_value":
            df = get_ctr_candidates(
                date_from=date_from, date_to=date_to, limit=limit,
            )
            if df.empty:
                return json.dumps(
                    {"mode": "high_value", "notice": "No high-value transactions matching criteria.", "result": []},
                    ensure_ascii=False,
                )
            records = json.loads(df.to_json(orient="records", force_ascii=False))
            return json.dumps(
                {"mode": "high_value", "count": len(records), "result": records},
                ensure_ascii=False,
            )
        else:  # structuring
            df = detect_structuring(
                date_from=date_from, date_to=date_to,
                threshold=threshold, limit=limit,
            )
            if df.empty:
                return json.dumps(
                    {"mode": "structuring", "notice": "No suspected structured transactions found.", "result": []},
                    ensure_ascii=False,
                )
            records = json.loads(df.to_json(orient="records", force_ascii=False))
            return json.dumps(
                {
                    "mode": "structuring",
                    "threshold": threshold,
                    "count": len(records),
                    "result": records,
                },
                ensure_ascii=False,
            )
    except Exception as exc:
        return json.dumps(
            {"error": f"CTR detection error: {str(exc)}"},
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Tool 13: score_account_risk
# ---------------------------------------------------------------------------


def _tool_score_account_risk(arguments: dict) -> str:
    account_id = arguments.get("account_id")
    if account_id is None:
        return json.dumps({"error": "account_id is required."}, ensure_ascii=False)

    try:
        aid = int(account_id)
    except (TypeError, ValueError):
        return json.dumps({"error": "account_id must be an integer."}, ensure_ascii=False)

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
    date_from = arguments.get("date_from")
    date_to = arguments.get("date_to")
    limit = min(int(arguments.get("limit", 20)), 100)

    valid_rules = {"all", "R001", "R002", "R003", "R004", "R005"}
    if rule_id not in valid_rules:
        return json.dumps(
            {"error": f"rule_id must be one of {sorted(valid_rules)}."},
            ensure_ascii=False,
        )

    try:
        if rule_id == "all":
            result = run_all_rules(date_from=date_from, date_to=date_to)
            return json.dumps({"rule_id": "all", "result": result}, ensure_ascii=False)

        if rule_id == "R001":
            df = detect_nighttime_bulk(date_from=date_from, date_to=date_to, limit=limit)
            label = "Nighttime Bulk Transactions"
        elif rule_id == "R002":
            df = detect_rapid_fire(date_from=date_from, date_to=date_to, limit=limit)
            label = "Multiple Daily Transactions"
        elif rule_id == "R003":
            df = detect_round_amounts(date_from=date_from, date_to=date_to, limit=limit)
            label = "Round Amount Pattern"
        elif rule_id == "R004":
            df = detect_institution_concentration(limit=limit)
            label = "Institution Concentration"
        elif rule_id == "R005":
            if not date_from or not date_to:
                return json.dumps(
                    {"error": "R005 (Pattern Change) requires date_from and date_to."},
                    ensure_ascii=False,
                )
            try:
                base_start, base_end = _calculate_previous_period(int(date_from), int(date_to))
            except ValueError:
                return json.dumps(
                    {"error": "Invalid date range. Please enter YYYYMMDD integers where date_from <= date_to."},
                    ensure_ascii=False,
                )
            df = detect_pattern_change(
                base_start=base_start, base_end=base_end,
                compare_start=int(date_from), compare_end=int(date_to),
                limit=limit,
            )
            label = "Transaction Pattern Change"

        if df.empty:
            return json.dumps(
                {"rule_id": rule_id, "rule_name": label, "notice": "No alerts detected.", "result": []},
                ensure_ascii=False,
            )

        records = json.loads(df.to_json(orient="records", force_ascii=False))
        return json.dumps(
            {"rule_id": rule_id, "rule_name": label, "count": len(records), "result": records},
            ensure_ascii=False,
        )

    except Exception as exc:
        return json.dumps(
            {"error": f"Monitoring rule execution error: {str(exc)}"},
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Tool 15: detect_dormant_reactivation
# ---------------------------------------------------------------------------


def _tool_detect_dormant_reactivation(arguments: dict) -> str:
    dormant_days = int(arguments.get("dormant_days", 180))
    min_amount = int(arguments.get("min_reactivation_amount", 5_000_000))
    limit = min(int(arguments.get("limit", 20)), 100)

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

    if df.empty:
        return json.dumps(
            {"notice": "No dormant reactivation accounts matching criteria.", "result": []},
            ensure_ascii=False,
        )

    records = json.loads(df.to_json(orient="records", force_ascii=False))
    return json.dumps(
        {
            "criteria": {"dormant_days": dormant_days, "min_reactivation_amount": min_amount},
            "count": len(records),
            "result": records,
        },
        ensure_ascii=False,
    )


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

    account_id = arguments.get("account_id")
    min_counterparts = int(arguments.get("min_counterparts", 5))
    date_from = arguments.get("date_from")
    date_to = arguments.get("date_to")
    limit = min(int(arguments.get("limit", 20)), 100)

    try:
        df = _detect_smurfing_network(
            account_id=int(account_id) if account_id is not None else None,
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

    if df.empty:
        label = "Fund Collection" if direction == "inbound" else "Fund Distribution"
        return json.dumps(
            {"direction": direction, "notice": f"{label} pattern not detected.", "result": []},
            ensure_ascii=False,
        )

    records = json.loads(df.to_json(orient="records", force_ascii=False))
    return json.dumps(
        {
            "direction": direction,
            "min_counterparts": min_counterparts,
            "count": len(records),
            "result": records,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Tool 17: get_trend_analysis
# ---------------------------------------------------------------------------


def _tool_get_trend_analysis(arguments: dict) -> str:
    unit = arguments.get("unit", "monthly")
    if unit not in ("monthly", "quarterly"):
        unit = "monthly"

    date_from = arguments.get("date_from")
    date_to = arguments.get("date_to")

    try:
        df = _get_trend_analysis(
            unit=unit, date_from=date_from, date_to=date_to,
        )
    except Exception as exc:
        return json.dumps(
            {"error": f"Trend analysis error: {str(exc)}"},
            ensure_ascii=False,
        )

    if df.empty:
        return json.dumps(
            {"unit": unit, "notice": "No data found for this period.", "result": []},
            ensure_ascii=False,
        )

    records = json.loads(df.to_json(orient="records", force_ascii=False))
    return json.dumps(
        {"unit": unit, "period_count": len(records), "result": records},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Tool 18: analyze_channel_risk
# ---------------------------------------------------------------------------


def _tool_analyze_channel_risk(arguments: dict) -> str:
    date_from = arguments.get("date_from")
    date_to = arguments.get("date_to")

    try:
        result = _analyze_channel_risk(date_from=date_from, date_to=date_to)
    except Exception as exc:
        return json.dumps(
            {"error": f"Channel risk analysis error: {str(exc)}"},
            ensure_ascii=False,
        )

    # Convert media type codes to English labels
    for item in result.get("channel_stats", []):
        code = item.get("media_type")
        item["channel_name"] = _MEDIA_TYPE_MAP.get(int(code) if code is not None else 0, f"Code {code}")

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 19: get_receiving_account_profile
# ---------------------------------------------------------------------------


def _tool_get_receiving_account_profile(arguments: dict) -> str:
    account_id = arguments.get("account_id")
    if account_id is None:
        return json.dumps({"error": "account_id is required."}, ensure_ascii=False)

    try:
        aid = int(account_id)
    except (TypeError, ValueError):
        return json.dumps({"error": "account_id must be an integer."}, ensure_ascii=False)

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
    date_from = arguments.get("date_from")
    date_to = arguments.get("date_to")
    min_transactions = int(arguments.get("min_transactions", 10))
    limit = min(int(arguments.get("limit", 20)), 100)

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

    if df.empty:
        return json.dumps(
            {"notice": "No significant inter-institution flows found matching criteria.", "result": []},
            ensure_ascii=False,
        )

    records = json.loads(df.to_json(orient="records", force_ascii=False))
    return json.dumps(
        {"min_transactions": min_transactions, "count": len(records), "result": records},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Tool 21: lookup_fiu_reference_types
# ---------------------------------------------------------------------------


def _tool_lookup_fiu_reference_types(arguments: dict) -> str:
    keyword = arguments.get("keyword") or ""
    industry = arguments.get("industry")

    results = lookup_fiu_reference_types(keyword, industry)
    return json.dumps(
        {"keyword": keyword, "count": len(results), "result": results},
        ensure_ascii=False,
    )


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
            {"error": f"Term '{term}' not found.", "notice": "Try searching for CDD, EDD, STR, CTR, RBA, PEP, MLRO, FATF, FIU, structuring, layering, etc."},
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


def chat(messages: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """Performs conversation with OpenAI API and returns response.

    Args:
        messages: Conversation history (list of dicts, including user/assistant/tool)

    Returns:
        (assistant_content, updated_messages, tool_events)
        - tool_events: each tool call info [{name, arguments, result}, ...]
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
