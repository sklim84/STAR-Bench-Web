# Tests

`tests/` holds the unit tests of the tool layer (`src/`) and the pre-flight
checks a benchmark run depends on.

## What is covered

- Data layer: `test_db.py` (schema and parquet-hash guards, per-call cursors,
  rebuild), `test_loader.py`, `test_graph_etl.py`, `test_graph_db.py`
- Tools as the benchmark calls them: `test_agent_tools.py` (all 23 tools through
  `_execute_tool`), `test_agent_str.py` (STR drafting and validation)
- Feature modules: `test_dashboard.py`, `test_detector.py`, `test_network.py`,
  `test_monitoring.py`, `test_flow_analyzer.py`, `test_ctr_monitor.py`,
  `test_risk_scorer.py`, `test_aml_reference.py`
- Run properties: `test_determinism.py` (the same call twice returns the same
  bytes), `test_concurrency.py` (threaded calls match serial calls)
- Common/config: `test_config.py`, `test_modules.py`, `tests/conftest.py`
- UI helpers: `test_chart_utils.py`
- Benchmark pre-flight: `test_gold_calls.py` (marked `gold`, see below)

## Running

```bash
pytest -q                       # the whole suite except the gold-call harness
pytest -q tests/test_db.py      # one file
HOFINET_DUCKDB_PATH=/tmp/t.duckdb pytest -q   # build the test database elsewhere
```

Every database-backed test skips when `_datasets/transactions.parquet` is absent, so
a fresh clone of the public repository still runs.

## Gold-call smoke harness

`test_gold_calls.py` executes every gold tool call of a STAR-Bench benchmark
directory against this platform and fails on any tool error; empty results are
reported per tool. It is deselected by default (`pytest.ini`) because it tests
the benchmark data as much as the platform:

```bash
pytest -m gold                                    # default directories
STAR_BENCH_GOLD_DIRS=/path/to/benchmarks pytest -m gold
python scripts/gold_calls.py ../STAR-Bench/benchmarks --json report.json
```

Default directories: `../STAR-Bench/benchmarks`, `../STAR-Bench/benchmarks_en`,
`../STAR-Bench/benchmarks_multiturn`. The files are read at run time, and both
`sql_contains` checks and `expected.reference_calls.query_transactions.sql` are
understood.
