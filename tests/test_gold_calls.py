"""Smoke harness: execute the benchmark's gold tool calls on this platform.

Marked `gold` and excluded from the default run (see pytest.ini), because it
tests the benchmark data as much as the platform: run it with `pytest -m gold`
before a benchmark run, or through `python scripts/gold_calls.py`.

Directories come from STAR_BENCH_GOLD_DIRS (os.pathsep separated) and default to
../STAR-Bench/benchmarks, benchmarks_en and benchmarks_multiturn. The files are
read at run time, and both `sql_contains` and the newer
`expected.reference_calls.query_transactions.sql` are understood.
"""

import os
from pathlib import Path

import pytest

from scripts.gold_calls import DEFAULT_DIRECTORIES, collect_calls, execute, summarize

pytestmark = pytest.mark.gold

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _directories():
    configured = os.environ.get("STAR_BENCH_GOLD_DIRS")
    raw = configured.split(os.pathsep) if configured else list(DEFAULT_DIRECTORIES)
    return [p if p.is_absolute() else (PROJECT_ROOT / p).resolve()
            for p in (Path(item) for item in raw)]


@pytest.fixture(scope="module")
def gold_report():
    directories = [d for d in _directories() if d.is_dir()]
    if not directories:
        pytest.skip("no benchmark directory found; set STAR_BENCH_GOLD_DIRS")
    report = {}
    for directory in directories:
        results = execute(collect_calls(directory))
        report[directory.name] = summarize(results)
    return report


def test_every_gold_call_executes_without_error(gold_report):
    failures = []
    for name, summary in gold_report.items():
        for tool, entry in sorted(summary["per_tool"].items()):
            if entry["error"]:
                first = entry["errors"][0]
                failures.append(
                    f"{name}/{tool}: {entry['error']} errors, "
                    f"e.g. {first['case_id']} {first['arguments']} -> {first['detail']}"
                )
    assert failures == [], "\n".join(failures)


def test_report_empty_results_per_tool(gold_report, capsys):
    with capsys.disabled():
        for name, summary in gold_report.items():
            totals = summary["totals"]
            print(f"\n{name}: ok {totals['ok']}, empty {totals['empty']}, "
                  f"error {totals['error']}, skipped {totals['skipped']}")
            for tool, entry in sorted(summary["per_tool"].items()):
                if entry["empty"] or entry["skipped"]:
                    print(f"  {tool:32s} empty {entry['empty']:4d} skipped {entry['skipped']:4d}"
                          f"  {entry['empties'][0]['detail'][:60] if entry['empties'] else ''}")
