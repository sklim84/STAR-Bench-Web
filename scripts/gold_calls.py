"""Execute every gold tool call of a STAR-Bench benchmark directory.

The benchmark's gold answers name a tool and the arguments a correct call
carries. This runs each of them against the platform and reports, per tool, how
many calls return data, how many return an empty result, and how many fail.
The round-2 audit ran exactly this check and found that 42.8% of the well-formed
gold calls returned nothing usable, so it belongs in the pre-flight suite.

The benchmark files are read at run time -- they are being rewritten by another
work stream -- and both the old `sql_contains` style checks and the new
`expected.reference_calls.query_transactions.sql` are understood.

Usage:
    python scripts/gold_calls.py ../STAR-Bench/benchmarks ../STAR-Bench/benchmarks_en
    python scripts/gold_calls.py --json report.json <dirs...>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Keys the evaluator uses inside param_checks that are not tool arguments.
CHECK_ONLY_KEYS = {
    "sql_contains", "sql_valid", "sql_conditions", "sql_not_contains",
    "result_contains", "result_row_count_min", "result_row_count_max",
}

DEFAULT_DIRECTORIES = (
    "../STAR-Bench/benchmarks",
    "../STAR-Bench/benchmarks_en",
    "../STAR-Bench/benchmarks_multiturn",
)


@dataclass
class GoldCall:
    source: str
    case_id: str
    tool: str
    arguments: dict
    turn: int | None = None
    executable: bool = True
    reason: str = ""


@dataclass
class CallResult:
    call: GoldCall
    status: str
    detail: str = ""
    elapsed_s: float = 0.0
    result: dict | list | None = field(default=None, repr=False)


def _clean(arguments: dict) -> dict:
    return {k: v for k, v in (arguments or {}).items() if k not in CHECK_ONLY_KEYS}


def _reference_sql(container: dict, tool: str):
    """Returns the executable gold SQL for a tool, if the case carries one."""
    reference = (container or {}).get("reference_calls") or {}
    entry = reference.get(tool)
    if isinstance(entry, dict):
        return entry.get("sql") or entry.get("arguments", {}).get("sql")
    if isinstance(entry, str):
        return entry
    return None


def _calls_from_expected(source: str, case_id: str, expected: dict) -> list[GoldCall]:
    calls = []
    checks = expected.get("param_checks") or {}
    tools = expected.get("tools_must_include") or []
    if expected.get("primary_tool") and expected["primary_tool"] not in tools:
        tools = [expected["primary_tool"], *tools]

    for tool in dict.fromkeys(tools):
        arguments = _clean(checks.get(tool, {}))
        executable, reason = True, ""
        if tool == "query_transactions" and "sql" not in arguments:
            sql = _reference_sql(expected, tool)
            if sql:
                arguments = {"sql": sql}
            else:
                executable, reason = False, "no executable gold SQL"
        calls.append(GoldCall(source, case_id, tool, arguments,
                              executable=executable, reason=reason))
    return calls


def collect_calls(directory: Path) -> list[GoldCall]:
    """Reads every gold call from one benchmark directory."""
    calls: list[GoldCall] = []
    for path in sorted(directory.glob("cases_*.json")):
        cases = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(cases, dict):
            cases = cases.get("cases", [])
        for case in cases:
            case_id = case.get("id", "?")
            if "turns" in case:
                for turn in case["turns"]:
                    for tool_call in turn.get("tool_calls") or []:
                        tool = tool_call.get("name")
                        arguments = _clean(tool_call.get("arguments", {}))
                        executable, reason = True, ""
                        if tool == "query_transactions" and "sql" not in arguments:
                            sql = _reference_sql(turn, tool) or _reference_sql(tool_call, tool)
                            if sql:
                                arguments = {"sql": sql}
                            else:
                                executable, reason = False, "no executable gold SQL"
                        calls.append(GoldCall(path.name, case_id, tool, arguments,
                                              turn=turn.get("turn"),
                                              executable=executable, reason=reason))
                continue

            expected = case.get("expected") or {}
            calls.extend(_calls_from_expected(path.name, case_id, expected))
            for alternative in expected.get("alternatives") or []:
                if isinstance(alternative, dict) and not alternative.get("abstain"):
                    calls.extend(_calls_from_expected(path.name, case_id, alternative))
    return calls


def classify(payload) -> tuple[str, str]:
    """Labels a tool result as ok, empty or error."""
    if isinstance(payload, dict) and "error" in payload:
        detail = payload["error"]
        return "error", detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)

    if isinstance(payload, dict):
        for key in ("result", "results", "path", "channel_stats", "summary_statistics",
                    "components", "edges"):
            value = payload.get(key)
            if value:
                return "ok", ""
        for key in ("count", "total_count", "period_count", "total_returned", "risk_score",
                    "total_score", "valid", "definition", "ReportType"):
            if payload.get(key):
                return "ok", ""
        if "notice" in payload:
            return "empty", payload["notice"]
        return "ok", ""

    if isinstance(payload, list):
        return ("ok", "") if payload else ("empty", "empty list")
    return "ok", ""


def execute(calls: list[GoldCall], keep_results: bool = False) -> list[CallResult]:
    from src.features.agent import _execute_tool

    cache: dict[tuple, CallResult] = {}
    results = []
    for call in calls:
        if not call.executable:
            results.append(CallResult(call, "skipped", call.reason))
            continue
        key = (call.tool, json.dumps(call.arguments, sort_keys=True, ensure_ascii=False))
        if key in cache:
            cached = cache[key]
            results.append(CallResult(call, cached.status, cached.detail, 0.0,
                                      cached.result if keep_results else None))
            continue
        start = time.time()
        raw = _execute_tool(call.tool, dict(call.arguments))
        elapsed = time.time() - start
        try:
            payload = json.loads(raw)
        except ValueError:
            outcome = CallResult(call, "error", "result is not JSON", elapsed)
        else:
            status, detail = classify(payload)
            outcome = CallResult(call, status, detail, elapsed,
                                 payload if keep_results else None)
        cache[key] = outcome
        results.append(outcome)
    return results


def summarize(results: list[CallResult]) -> dict:
    per_tool: dict[str, dict] = {}
    for outcome in results:
        entry = per_tool.setdefault(outcome.call.tool, {
            "ok": 0, "empty": 0, "error": 0, "skipped": 0,
            "errors": [], "empties": [],
        })
        entry[outcome.status] += 1
        if outcome.status == "error" and len(entry["errors"]) < 5:
            entry["errors"].append({
                "case_id": outcome.call.case_id, "turn": outcome.call.turn,
                "arguments": outcome.call.arguments, "detail": outcome.detail,
            })
        if outcome.status == "empty" and len(entry["empties"]) < 5:
            entry["empties"].append({
                "case_id": outcome.call.case_id, "turn": outcome.call.turn,
                "arguments": outcome.call.arguments, "detail": outcome.detail,
            })
    totals = {key: sum(entry[key] for entry in per_tool.values())
              for key in ("ok", "empty", "error", "skipped")}
    return {"totals": totals, "per_tool": per_tool}


def run(directories) -> dict:
    """Executes the gold calls of every directory and returns one report."""
    report = {"directories": {}, "missing": []}
    for directory in directories:
        path = Path(directory)
        if not path.is_dir():
            report["missing"].append(str(path))
            continue
        calls = collect_calls(path)
        results = execute(calls)
        report["directories"][str(path)] = {"calls": len(calls), **summarize(results)}
    return report


def _print(report: dict) -> None:
    for directory, summary in report["directories"].items():
        totals = summary["totals"]
        print(f"\n{directory}: {summary['calls']} gold calls "
              f"(ok {totals['ok']}, empty {totals['empty']}, "
              f"error {totals['error']}, skipped {totals['skipped']})")
        print(f"{'tool':32s} {'ok':>5s} {'empty':>6s} {'error':>6s} {'skip':>5s}  first problem")
        for tool, entry in sorted(summary["per_tool"].items()):
            problem = ""
            if entry["errors"]:
                problem = f"error: {entry['errors'][0]['detail'][:70]}"
            elif entry["empty"]:
                problem = f"empty: {entry['empties'][0]['detail'][:70]}"
            print(f"{tool:32s} {entry['ok']:5d} {entry['empty']:6d} "
                  f"{entry['error']:6d} {entry['skipped']:5d}  {problem}")
    for path in report["missing"]:
        print(f"missing directory: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="*", default=list(DEFAULT_DIRECTORIES))
    parser.add_argument("--json", help="write the full report to this file")
    args = parser.parse_args()

    directories = args.directories or list(DEFAULT_DIRECTORIES)
    report = run(directories)
    _print(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    errors = sum(summary["totals"]["error"] for summary in report["directories"].values())
    return 1 if errors or not report["directories"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
