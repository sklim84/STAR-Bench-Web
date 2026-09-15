# Audit fixes — platform tool layer (WS-A)

Work stream A of the 2026-09-15 STAR-Bench audit: the platform defects of
register step 3, the environment guards of step 2 (platform part), the prompt
decisions D08/D13, the tool decisions D06/D12/D18, and the test suite (C1-005).

Branch `audit-fixes`, three commits:

| Commit | Scope |
|---|---|
| `ff6f2d0` | database guards, per-call cursors, provenance, pinned dependencies |
| `df8c0cb` | the 23 tools, the monitoring rules, the graph patterns, the descriptions and the system prompt |
| `109d64f` | the test suite, the determinism/threading gates and the gold-call harness |
| (this file) | `AUDIT_FIXES.md`, `CHANGES.md`, `_datasets/HOFINET.MD`, `README.md` |

`CHANGES.md` lists what the other work streams have to mirror. The tool schema
itself did not change: names, parameters, types, enums, defaults and `required`
lists are identical to `main`.

## Register ids

| id | Commit | What changed | How verified |
|---|---|---|---|
| L3-002, R1C-002, R1C-011 (NaN / 'null') | `df8c0cb` | Arguments are normalised once in `_execute_tool`: a JSON-string argument object is parsed, `null`/`None`/`""` are treated as absent, numeric strings are read as numbers, and a missing or unreadable value is reported by name. Aggregates use `COALESCE(...)` and a NaN-safe reader, so `get_account_profile`, `get_fraud_type_summary` and `compare_periods` answer with a documented notice instead of "cannot convert float NaN to integer". | `tests/test_agent_tools.py::TestArgumentHandling`, `TestAccountProfiles`, `TestStatisticsAndSummaries`; gold-call run: 0 NaN errors left |
| L3-003, R1C-001 (thread safety) | `ff6f2d0` | `db.query` / `db.query_arrow` run each call on its own DuckDB cursor, and the connection singleton is created under a lock. | `tests/test_db.py::TestCursorIsolation` (12 threads x 20 queries), `tests/test_concurrency.py` (tool calls through a thread pool match serial calls) |
| L3-005 + D06 (graph patterns) | `df8c0cb` | `detect_aml_patterns` (ring, layering, funnel, shortest_path, risk_score) and `analyze_network` at any hop depth run on DuckDB and NetworkX; `src/features/network.py` no longer imports `graph_db`. Funnel requires 1..max_outflow outbound counterparties. Empty results state the HOFINET fact instead of "ensure Memgraph is running". | `tests/test_network.py::TestAmlPatterns`, `TestShortestPath`, `TestRiskScore`; `tests/test_agent_tools.py::TestNetworkTools::test_no_tool_reports_memgraph`; acyclicity measured (fraud graph longest path 2, full graph 4) and documented in `_datasets/HOFINET.MD` §7 |
| L3-006 (FIU catalog) | `df8c0cb` | The description says the catalog is an English excerpt matched as a substring, and its example keywords are ones that return entries; an empty keyword lists the catalog; an unmatched keyword returns a notice. No Korean aliases were added (D10). | `tests/test_agent_tools.py::TestReferenceTools::test_catalog_keywords_from_the_description_return_rows` executes every example keyword |
| L3-008, R1C-015 (predict_fraud) | `df8c0cb` | Features are selected by `FEATURE_COLS` in a fixed order, so argument order and extra keys cannot change the score; numeric strings are coerced before validation; missing features are listed. | `tests/test_agent_tools.py::TestModelTools` |
| L3-009, R1C-016 (generate_str) | `df8c0cb` | `transactions` is accepted as a JSON string, a single object or a list; numbers as strings are coerced; `aml_patterns`/`tools_used` accept a string; the §VI enum, the Korean `fraud_description` values and the English labels all map to a fraud type; the account regex is bilingual; the reporting date is `config.REFERENCE_DATE`. | `tests/test_agent_str.py::TestGenerateStr` |
| L3-010, R1C-012 (validate_str_fields) | `df8c0cb` | Sections and required fields are named in the description and are the ones `generate_str` emits; older section names and snake_case fields are accepted; a JSON-string draft is parsed; personal details HOFINET cannot supply are optional and reported as `missing_optional`. | `tests/test_agent_str.py::TestValidateStrFields::test_generate_str_output_validates` and the documented-names case |
| L3-012 + D18, R1-N3 (monitoring rules) | `df8c0cb` | `date_from`, `date_to` and `account_id` apply to every rule. R001 = night slots 21/0/3 with amount >= 5,000,000 (all 35 type-7 rows are in slot 21, the smallest is 5M; the old rule matched 0 of 4.7M rows). R003 = same sender, same amount >= 2,000,000, at least 3 times (the old "round million" rule was true for every row >= 1M). R004 = one receiving institution over 50% of an account's transactions with >= 10 transactions (99th percentile of that share is 0.44; the old 0.8 matched a single account). R005 falls back to the last quarter of the data. `rule_id='all'` honours `limit`. | `tests/test_monitoring.py`, `tests/test_agent_tools.py::TestMonitoringTools`; thresholds measured on the parquet and recorded in `_datasets/HOFINET.MD` §8 |
| L3-014, R1-N6, R1C-018, R1C-024 (metrics) | `df8c0cb` | `fraud_tx_count` sums `is_fraud` per edge; `unique_senders` is a SQL `COUNT(DISTINCT)`; `get_institution_report` returns the promised quarterly trend and the receiving side; `detect_ctr_candidates` applies `threshold` in both modes; `rank_risky_transactions` reports the sample cap; ratios are percentages under `_percent` keys and sums are integers. | `tests/test_agent_tools.py` (network, institution, CTR, model), `tests/test_dashboard.py::TestReceivingProfile`, `tests/test_flow_analyzer.py` |
| L3-015 (channel names) | `df8c0cb` | `analyze_channel_risk` describes the 7 HOFINET `media_type` channels and returns `media_type` / `channel_name`; the ATM/PB/Counter list and `medium_type` are gone. | `tests/test_agent_tools.py::TestAnalysisTools::test_channel_risk_*` |
| L3-016, R1C-017 (determinism) | `df8c0cb` | Every `ORDER BY` on the tool path carries tie-breakers, sampling is a hash of the transaction's own values instead of `ORDER BY random()`, the dormant rule aggregates per day before measuring the gap, and the STR reporting date is fixed. | `tests/test_determinism.py`: every tool called twice returns identical bytes |
| L3-017, K7, C1-002 + D12 (model tools) | `df8c0cb` | `rank_risky_transactions` reads `prob` (it always failed on `predict_prob`), drops `is_fraud_actual`, samples and sorts deterministically; both model tools return `fraud_risk_score` with `score_type` "uncalibrated ... not a probability of fraud"; the amount dominance and in-sample training are documented in `src/features/detector.py` and `_datasets/HOFINET.MD` §9; the model sha256 is exposed by `src/provenance.py`. | `tests/test_agent_tools.py::TestModelTools`, `tests/test_determinism.py::test_model_ranking_is_reproducible` |
| L3-021, R1C-019 (SQL guard) | `df8c0cb` | The statement is parsed with `duckdb.extract_statements`: exactly one SELECT is required, so CTEs, comments, parenthesised selects and aliases such as `last_update_date` pass; file-reading table functions are refused and the shared connection runs with `enable_external_access=false`; one result shape (`total_count`, `returned_count`, `result`). | `tests/test_agent_tools.py::TestQueryTransactions`, `tests/test_db.py::TestQuery::test_external_file_access_is_disabled` |
| R1-N1, R1C-006 (quarters) | `df8c0cb` | Integer division (`date // 100 % 100`) in `dashboard.get_quarterly_trend`, `dashboard.get_trend_analysis`, `risk_scorer` and the institution trend; the stale "13 quarters" assertion is replaced. | `tests/test_dashboard.py::TestQuarters` (14 quarters, 2021Q3 = 98,530 rows) |
| R1-N2 (score_account_risk) | `df8c0cb` | Components are computed over both directions; `amount_anomaly` uses the dataset standard deviation; `velocity_change` compares consecutive quarters with integer arithmetic; receiver-only accounts are scored; `fraud_history` stays label-based and both the description and the result say so (D12). | `tests/test_risk_scorer.py` |
| R1-N4 + D08, D13 (system prompt) | `df8c0cb` | The prompt states the date range and INTEGER yyyymmdd format, the 16-digit account ids, the bank code ranges, the amount value count, and the Korean `fraud_description` values as stored; the 15-step flow and the "always query first" instruction are gone; it asks for an answer in the language of the question. | `tests/test_agent_tools.py::TestSchema::test_system_prompt_*`; `_datasets/HOFINET.MD` §2/§4 corrected in the same pass |
| L1-003 (funnel vs smurfing) | `df8c0cb` | `detect_smurfing_network` describes one-directional counterparty counts and points to `detect_aml_patterns` funnel for collect-and-forward; "mule accounts" is gone from the smurfing and dormant descriptions and stays only on funnel. | description review; `tests/test_agent_tools.py` schema tests |
| L1-005 (get_statistics) | `df8c0cb` | The description lists the account counts, bank counts and total amount the tool has always returned, and says it takes no filters. | `tests/test_agent_tools.py::TestStatisticsAndSummaries` |
| L1-008 (R003 label) | `df8c0cb` | R003 is "Repeated Identical Amounts" in the rule name and the description (the KR mirror must use "동일 금액 반복"; see `CHANGES.md`). | `tests/test_monitoring.py::TestRuleR003` |
| L5-020, C1-001 (data guards) | `ff6f2d0` | The DuckDB file records the sha256 and row count of the Parquet it was built from; a file with a different schema, no metadata or another source hash is refused with `DatabaseMismatch`; `rebuild_database()` and `python -m src.data.db rebuild` write a new file atomically. | `tests/test_db.py::TestDatabaseGuards` (incl. a Korean-column database) |
| C2-016 (one DB path) | `ff6f2d0` | `get_connection()` is the single entry point for the app, the tools and the runners; `use_connection()` verifies a connection installed from outside; `connection_info()` reports which database is in use. | `tests/test_db.py::TestConnection`, `tests/conftest.py` uses the same path as the runners |
| C1-004 (Streamlit cache / environment) | `ff6f2d0` | `src/provenance.py` records `streamlit_stubbed` together with the commit, data/db/model hashes, prompt and tools hashes and library versions; `requirements-tools.txt` pins every version with `==`. | `python -m src.provenance`; `tests/test_modules.py` treats the UI packages as app-only |
| C1-005, R1C-027 (tests) | `109d64f` | The suite is rewritten on the English schema and around `_execute_tool`, with new threading, determinism and gold-call gates. | `pytest -q`: 492 passed, 15 skipped |
| R1-N5 (response language) | `df8c0cb` | The platform prompt now says "Answer in the language of the user's question" (D13). The other two prompt constants live in the STAR-Bench repository (WS-C). | prompt test |

## Not fixed here

| id | Reason |
|---|---|
| L3-004, L3-007, L3-018, R1-D1, R1-D2, C1-003 | Benchmark data: gold accounts, banks and injected oracle results are rebuilt by WS-D/WS-E on this fixed platform. |
| L3-011 (glossary gold), L3-019 (`period_a_*` keys), C1-006 (catalog disclosure) | Gold and paper changes; the platform side (documented keys, notices, English-only entries) is done. |
| L3-020, L3-022, L3-023, R1C-008, R1C-009, R1C-010 (scoring) | `tools_en.py`, `tools_kr.py`, `benchmark*.py` and `evaluator.py` belong to WS-B/WS-C. |
| L3-001 | Manuscript wording after the rerun. |

## Verification

```
pytest -q                          # 492 passed, 15 skipped, 2 deselected (gold)
python scripts/gold_calls.py       # gold-call smoke run, see below
```

Gold-call smoke run on the benchmark data as it stood at 2026-09-16 08:45,
while WS-D was still rewriting it (the duplicate `*_ex` cases are already gone),
`ok / empty / error / skipped`:

| Directory | calls | ok | empty | error | skipped |
|---|---|---|---|---|---|
| `benchmarks` | 1,063 | 682 | 289 | 19 | 73 |
| `benchmarks_en` | 1,063 | 682 | 289 | 19 | 73 |
| `benchmarks_multiturn` | 200 | 103 | 59 | 2 | 36 |

Per tool, the calls that do not return data:

| Tool | empty | error | why |
|---|---|---|---|
| `get_account_profile` | 52 | 0 | gold account ids are not HOFINET ids |
| `get_receiving_account_profile` | 53 | 0 | same |
| `score_account_risk` | 55 | 1 | same; 1 call has no `account_id` |
| `analyze_network` | 59 | 2 | same; 2 calls have no `account_id` |
| `detect_aml_patterns` | 60 | 0 | ring and layering have no matches in HOFINET; funnel defaults match nothing |
| `detect_smurfing_network` | 10 | 5 | 5 calls omit `direction`; 10 use account ids that do not exist |
| `get_fraud_type_summary` | 0 | 3 | 3 calls omit `fraud_type` |
| `detect_ctr_candidates` | 0 | 2 | 2 calls omit `mode` |
| `predict_fraud` | 0 | 2 | 2 calls omit a feature |
| `validate_str_fields` | 0 | 3 | the single-turn gold carries no draft |
| `get_aml_glossary` | 0 | 1 single-turn, 2 multi-turn | Korean terms ('구조화', '레이어링') are not in the English glossary |
| `lookup_fiu_reference_types` | 6 (multi-turn) | 0 | Korean keywords against an English catalog |
| `get_institution_report` | 4 (multi-turn) | 0 | bank ids outside 101-161 |
| `query_transactions` | - | - | 73 + 36 calls skipped: `sql_contains` with no executable SQL |

Every error is a gold defect, not a tool defect; every empty is an identifier
that does not exist in HOFINET or a pattern the dataset does not contain. Both
disappear as WS-D and WS-E rebuild the cases on real entities and contract 1
adds `expected.reference_calls.query_transactions.sql`, which the harness
already reads.
