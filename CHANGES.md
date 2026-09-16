# Interface changes for the parallel work streams

The 23 tool names and every parameter name, type, enum and `required` list are
identical to `main` (checked by comparing the parsed schema). One pair of
defaults changed -- `detect_aml_patterns.min_inflow` 10 -> 5 and
`max_outflow` 3 -> 5, see section 4 -- and 20 tool descriptions and several
parameter descriptions were rewritten. The tool *results* changed where the
audit required it. The Korean schema mirror (`tools_kr.py`), the evaluator and
the data rebuild need the lists below.

## 1. Descriptions to mirror in the Korean schema

Same structure, new wording. The substantive points:

| Tool | What the description now says |
|---|---|
| `query_transactions` | `date` is an INTEGER yyyymmdd; result carries `total_count`, `returned_count` and up to 100 rows |
| `predict_fraud` | returns `fraud_risk_score`, an uncalibrated score, not a probability |
| `rank_risky_transactions` | same score; the ground-truth label is not returned |
| `generate_str` | no "always query first"; transactions fill in the report when given |
| `analyze_network` | hops 1-5, no Memgraph; hops-1 neighbourhood definition |
| `get_statistics` | account counts, bank counts and total amount are advertised |
| `get_account_profile` | counts both directions (sender_acc or receiver_acc) |
| `get_institution_report` | outbound and inbound side, top banks both ways, quarterly trend |
| `detect_aml_patterns` | ring/layering/funnel/shortest_path/risk_score defined in terms of transfers, no Memgraph; it states that HOFINET's graph is acyclic (ring and layering return nothing) and that no account there forwards to fewer than 4 counterparties; `min_inflow` and `max_outflow` say which side of the funnel they count |
| `detect_ctr_candidates` | `threshold` applies to both modes |
| `score_account_risk` | 5 components incl. label-derived `fraud_history`; both directions |
| `detect_monitoring_alerts` | R001 night slots 21/0/3 and 5,000,000 KRW; R002 10 same-day; R003 repeated identical amounts (>= 2,000,000, 3 times) — the KR label must be "동일 금액 반복", not "정액" or "라운드 금액"; R004 half the transactions to one receiving institution; R005 default window; `date_from`/`date_to`/`account_id` apply to every rule |
| `detect_dormant_reactivation` | no "mule accounts" wording |
| `detect_smurfing_network` | counterparty counts only, one direction; funnel belongs to `detect_aml_patterns` |
| `get_trend_analysis` | period labels `2024-07` / `2024Q3`, 14 quarters |
| `analyze_channel_risk` | the 7 HOFINET `media_type` channels (no ATM/PB/Counter, no `medium_type`) |
| `get_receiving_account_profile` | distinct senders and sending banks |
| `lookup_fiu_reference_types` | English catalog, English keywords that match (structuring, cash, non-face-to-face, virtual asset, dormancy, gambling, balance certificate), empty keyword lists everything |
| `validate_str_fields` | the required sections and fields, by name |
| `get_aml_glossary` | the 13 English terms, no Korean entries |
| system prompt | adds one line of scope: a term the glossary holds is answered with `get_aml_glossary`, any other conceptual explanation without a tool (D10, WS-D request 8) |

## 2. Result keys that changed

| Tool | Before | Now |
|---|---|---|
| `query_transactions` | bare JSON list for <= 100 rows, dict otherwise | always `{total_count, returned_count, result[, notice]}` |
| `predict_fraud` | `fraud_probability` | `fraud_risk_score`, plus `score_type` |
| `rank_risky_transactions` | `fraud_probability`, `is_fraud_actual` | `fraud_risk_score`; label removed; rows carry all six features |
| `get_account_profile` | `fraud_ratio` (fraction), error on no history | `fraud_ratio_percent`, `outbound_count`, `inbound_count`, counterparties carry `direction`, `notice` on no history |
| `get_receiving_account_profile` | `fraud_rate` (fraction), `unique_senders` capped at 5 | `fraud_ratio_percent`, true `unique_senders`, `unique_sender_banks` |
| `get_trend_analysis` | `fraud_rate`, `period` 202407 / 20243, 13 quarters | `fraud_ratio_percent`, `period` "2024-07" / "2024Q3", 14 quarters |
| `analyze_channel_risk` | `channel_code`, `channel`, `fraud_rate` | `media_type`, `channel_name`, `fraud_ratio_percent` |
| `analyze_cross_institution_flow` | `fraud_ratio` | `fraud_ratio_percent` |
| `analyze_network` | `fraud_ratio` on the empty path; edge-based fraud count | `fraud_ratio_percent`; `fraud_tx_count` counts transactions |
| `get_institution_report` | flat sender-side totals | `outbound` / `inbound` blocks, `top_source_banks`, `quarterly_trend` |
| `get_fraud_type_summary` | notice only | notice plus `bank_filter` and `total_count` |
| `detect_monitoring_alerts` | `all` keyed `R001_Nighttime_Bulk` with `top` | `all` keyed `R001`..`R005` with `rule_name`, `count`, `result`; every response echoes `filters`; R003 rows are `(sender_acc, amount, repeat_count, total_amount, first_date, last_date, receiver_count)`; R004 `concentration_percent`; R005 `count_change_multiple` / `amount_change_multiple` |
| `detect_dormant_reactivation` | one row per transaction | daily aggregation, plus `reactivation_day_tx_count` / `reactivation_day_amount` |
| `detect_ctr_candidates` | `threshold` only for structuring | `threshold` always echoed |
| `score_account_risk` | error on no history | `notice`, plus `role`, `total_count`, `sent_count`, `received_count` |
| `detect_aml_patterns` | Memgraph notices; shortest_path `amounts`/`dates` | pattern notices that state the HOFINET fact; shortest_path returns `edges`; risk_score components `fraud_ratio_percent`, `neighbor_fraud_ratio_percent`, `cycle_count`, `in_out_imbalance_percent`; funnel echoes `criteria` |
| `generate_str` | `ReportingDate` = today | fixed reference date 2024-12-31; `VI_TransactionType` adds `SectionVICode`, `HOFINETFraudType`, `HOFINETFraudTypeName` |
| `validate_str_fields` | `{valid, missing_required, sections_checked}` | adds `missing_optional`; documented section and field names |
| `lookup_fiu_reference_types` | `{keyword, count, result}` | adds `industry` and a `notice` when nothing matches |
| `get_aml_glossary` | free-text notice | `available_terms` with the 13 terms |

Ratios are percentages everywhere, under a key ending in `_percent`; sums are
returned as integers.

## 3. Platform API for the runners

- `src.data.db.get_connection()` is the single entry point. Do not assign
  `db._conn` directly: `db.use_connection(conn)` installs an existing
  connection and checks it against the released schema first.
- A DuckDB file that does not match the released Parquet is refused with
  `db.DatabaseMismatch`; rebuild it with `python -m src.data.db rebuild`.
- `src.provenance.get_provenance()` returns the platform commit, the
  parquet/db/model sha256, the system-prompt and tools hashes, the
  `streamlit_stubbed` flag and the library versions, for the run record.
- `config.DUCKDB_PATH` and `config.PARQUET_PATH` accept the environment
  overrides `HOFINET_DUCKDB_PATH` and `HOFINET_PARQUET_PATH`;
  `config.REFERENCE_DATE` (20241231) is the "today" the tools use.
- Module-level renames: `monitoring.detect_round_amounts` ->
  `monitoring.detect_repeated_amounts`; `monitoring.run_all_rules(date_from,
  date_to, account_id, limit)`; `monitoring.run_rule(rule_id, ...)`;
  `network.summarize_account_network(account_id, hops)`;
  `network.get_account_ego_network(account_id, hops, edge_limit)`;
  `detector.predict_from_db` writes `prob` and samples deterministically.

## 4. The one schema default that changed

`detect_aml_patterns` funnel defaults: `min_inflow` 10 -> 5, `max_outflow` 3 -> 5.

Requested by WS-D (request 9): 12 single-turn funnel gold calls returned nothing
because the old defaults cannot match HOFINET. Of the 414 accounts that both
receive and send, the fewest outgoing counterparties any of them has is 4, and
the largest inflow among those with 5 or fewer outgoing counterparties is 5, so
(10, 3) matches 0 accounts and (5, 5) matches 3. Measured counts are in
`_datasets/HOFINET.MD` §7. The Korean schema must carry the same two defaults,
and a gold call that omits them now executes with (5, 5).

## 5. Section VI pattern mapping (2026-09-16)

`_AML_PATTERN_ITEMS` no longer maps *ring*/*cycle* to the Section VI item "Structured transactions":
that item belongs to fraud type 3 (분할 거래), not to circular transfers, and HOFINET's transfer graph is
acyclic, so a ring claim now falls through to the Section VII narrative fallback. 대포통장 and 집금 stay as
recognition aliases for *funnel* only, for a model that writes them. The benchmark questions themselves
use the bare token `funnel`, in the Korean arm as well as the English one, and never 깔때기 or 집금:
STAR-Bench `_experiments/scripts/data_fixes/TERMINOLOGY.md` states that convention and
`p23_terminology_residue` screens both arms for it.
