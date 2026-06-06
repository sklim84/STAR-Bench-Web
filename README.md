# AML Assistant Platform

A web service for analyzing suspicious money-laundering transactions using AI agents.
It gives an anti-money-laundering (AML) analyst a single workspace to explore
de-identified interbank transfer data — from high-level dashboards and transaction-network
graphs to ML-based fraud detection and a conversational agent that drafts Suspicious
Transaction Reports (STRs).

This platform is also the **reference application from which the function-calling tool suite
of the [STAR-Bench](https://github.com/sklim84/STAR-Bench) benchmark was derived**.

---

## What you can do

The app is organized into eight analyst-facing features, reachable from the top menu.

### 📊 Dashboard
Visualize transaction statistics, fraud-type distribution, and patterns by time period and
financial institution. The landing view for sizing up the data and spotting where suspicious
activity concentrates.

![Dashboard](screenshots/2.%20dashboard.png)

### 🕸️ Network Analysis
Build the transaction graph between institutions and accounts and investigate money flow:
centrality, community detection, and AML patterns such as ring (circular) transactions,
layering, smurfing/funnel, and fund-collection/dispersion. Trace an account's neighborhood,
shortest paths, and N-hop reach to follow how funds move.

### 🤖 Fraud Detection
XGBoost-based fraud-probability prediction with on-page model training/evaluation and
feature-importance analysis. Score individual transactions or batches and inspect which
features drive a prediction.

### 💵 CTR Monitoring
Currency Transaction Report (CTR) candidate lookup (high-value cash transactions) and
**structuring** detection — splitting a large amount into several sub-threshold transfers to
evade reporting.

### 🎯 Risk Scoring
Account risk scoring on a 0–100 scale from five behavioral indicators (late-night activity,
amount anomaly, counterparty diversity, velocity change, prior-anomaly history) with a
high-risk account ranking.

### 🚨 Transaction Monitoring
Rule-based suspicious-transaction detection across six rules: nighttime bulk, same-day
rapid-fire, round/fixed amounts, institution concentration, abrupt pattern change, and
dormant-account reactivation.

### 📚 AML Reference
FIU suspicious-transaction reference types, STR field validation, and an AML glossary
(CDD, STR, CTR, RBA, and more) — the regulatory knowledge an analyst reaches for while
writing a report.

### 💬 AI Agent (STR auto-generation)
Query and analyze transactions through natural-language conversation, then auto-generate a
Suspicious Transaction Report. The agent's tools span all of the features above
(transaction queries, fraud prediction, network/pattern analysis, CTR/risk/monitoring, and
regulatory lookups) and it chains them over multiple rounds; `generate_str` composes the
finished STR draft (form sections I–VII) from the accumulated evidence.

> **Money-flow analysis** (smurfing networks and cross-institution flows) is also available
> as a shared analysis capability used by the Network feature and the agent's tools.

---

## How it works

- **Dual-store analytics** — DuckDB (in-memory, Parquet-backed) for aggregation and SQL;
  Memgraph (Cypher) for graph patterns. If Memgraph is not running, the app automatically
  falls back to DuckDB + NetworkX, so graph features degrade gracefully.
- **Conversational agent** — routed through OpenRouter (OpenAI-compatible API, default
  `openai/gpt-4o-mini`, configurable via `OPENROUTER_MODEL`); falls back to direct OpenAI when
  `OPENROUTER_API_KEY` is unset. Native function calling over the full tool suite, up to 5 tool-call rounds.
- **Dark-themed UI** — Streamlit with a custom dark theme and Plotly visualizations.

| Layer | Technology |
|---|---|
| Frontend | Streamlit (dark theme) + Plotly |
| Analytics DB | DuckDB (in-memory, Parquet) |
| Graph DB | Memgraph (optional, Docker) — NetworkX fallback |
| AI agent | OpenRouter / OpenAI `gpt-4o-mini` + function calling |
| ML model | XGBoost (fraud detection) |

---

## Quickstart

**Prerequisites:** Python 3.10+ (and, optionally, Docker for the Memgraph graph store).

```bash
pip install -r requirements.txt

# Prepare data (one-time): convert the source CSV to Parquet
python -m src.data.loader

# Run the app
streamlit run app.py
```

Optional — graph features via Memgraph:

```bash
docker-compose up -d                                              # start Memgraph
python -c "from src.data.graph_etl import run_etl; print(run_etl())"   # DuckDB -> Memgraph ETL
```

Run the tests (not while the app is running — DuckDB file lock):

```bash
pytest tests/ -v
```

### Configuration

Copy `.env.example` to `.env` and set what you need:

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | Agent provider (primary, OpenAI-compatible) |
| `OPENAI_API_KEY` | Agent fallback provider |
| `MEMGRAPH_HOST` / `MEMGRAPH_PORT` | Graph DB connection (optional) |

---

## Data & governance

The platform runs on **HOFINET**, a de-identified synthetic dataset of Korean interbank
transfers (~4.73M transactions, 2021 Q3 – 2024 Q4) with labeled anomaly types. All account
and institution identifiers are replaced with serial numbers and timestamps are quantized.

The **raw dataset is not included in this repository** for data-governance reasons (only the
schema in `_datasets/HOFINET.MD` is shipped). Place `_datasets/HOFINET.parquet` (or `.duckdb`)
locally, or generate it from the source CSV with `python -m src.data.loader`. When the dataset
or trained model is absent, data-dependent features are skipped rather than failing.

---

## Related

- **[STAR-Bench](https://github.com/sklim84/STAR-Bench)** — the AML agent function-calling
  benchmark whose tool suite is derived from this platform.
