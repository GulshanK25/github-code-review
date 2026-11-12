"""Opt-in Docker behavioral probes for checked-in before/after benchmark cases.

Unlike AI review evaluation, this runner executes old/new snippets, but ONLY
inside restricted Docker. This script does not modify reviewer decisions.

  python -m benchmarks.behavior_compare --execute-in-docker
  python -m benchmarks.behavior_compare --execute-in-docker --only holdout_safe_demorgan
"""

import argparse
import csv
import json
from pathlib import Path

from agent.behavior_sandbox import compare_in_docker
from benchmarks.evaluate import load_cases
from benchmarks.holdout_compare import HOLDOUT_CASES

DEFAULT_OUTPUT = Path("benchmarks/results/behavior/comparison.json")


def classify_observation(case: dict, result: dict) -> str:
    if result.get("status") != "completed":
        return "not_run"
    if case["expected"] == "bug":
        return "difference_observed" if result["differences"] else "bug_not_demonstrated"
    return "safe_probes_unchanged" if result["differences"] == 0 else "safe_label_needs_review"


def run_cases(cases: list[dict], comparator=compare_in_docker) -> list[dict]:
    rows = []
    for case in cases:
        result = comparator(case)
        label = classify_observation(case, result)
        row = {
            "case": case["name"], "expected": case["expected"],
            "status": result["status"], "observation": label,
            "probes_run": len(result.get("probes", [])),
            "differences": result.get("differences"),
            "expected_value_mismatches": sum(
                probe.get(key) is False
                for probe in result.get("probes", [])
                for key in ("before_expected_match", "after_expected_match")
            ),
            "details": result.get("details", ""),
            "probe_results": result.get("probes", []),
        }
        rows.append(row)
        print(f"{label:<25} {case['name']} "
              f"(differences={row['differences']}, probes={row['probes_run']})", flush=True)
        if result["status"] == "not_run":
            # Missing Docker/image is a global problem; avoid repeated calls.
            print(result.get("details", "Docker unavailable"), flush=True)
            break
    return rows


def save_observations(path: Path, cases_path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": str(cases_path),
        "notes": [
            "Execution was opt-in and confined to resource-limited Docker containers.",
            "Observed differences are not necessarily defects; changes may be intentional.",
            "No observed difference on these probes does NOT prove equivalent behavior.",
            "Probe values are supplied by the dataset, not independently selected by the reviewer.",
            "These results do not alter AI reviewer findings or precision/recall metrics.",
        ],
        "summary": {
            "cases_attempted": len(rows),
            "completed": sum(row["status"] == "completed" for row in rows),
            "differences_observed": sum(row["observation"] == "difference_observed" for row in rows),
            "safe_probes_unchanged": sum(row["observation"] == "safe_probes_unchanged" for row in rows),
            "expected_value_mismatches": sum(row["expected_value_mismatches"] for row in rows),
            "inconclusive_or_error": sum(row["observation"] in {
                "not_run", "bug_not_demonstrated", "safe_label_needs_review",
            } for row in rows),
        },
        "results": rows,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=[
            "case", "expected", "status", "observation", "probes_run", "differences",
            "expected_value_mismatches", "details",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in writer.fieldnames})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compare behavior of old/new code in restricted Docker")
    parser.add_argument("--cases", type=Path, default=HOLDOUT_CASES)
    parser.add_argument("--only", help="Run one named case")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--execute-in-docker", action="store_true",
        help="Required: explicit approval to execute benchmark code inside restricted Docker",
    )
    args = parser.parse_args(argv)
    if not args.execute_in_docker:
        parser.error("Behavior probes execute Python code. Add --execute-in-docker to opt in.")
    if args.output.resolve() == args.cases.resolve():
        parser.error("Output must not overwrite the input dataset")
    cases = load_cases(args.cases)
    if args.only:
        cases = [case for case in cases if case["name"] == args.only]
        if not cases:
            parser.error(f"Unknown case name: {args.only}")
    rows = run_cases(cases)
    save_observations(args.output, args.cases, rows)
    print(f"Saved JSON: {args.output}")
    print(f"Saved CSV:  {args.output.with_suffix('.csv')}")
    return 0 if len(rows) == len(cases) and all(row["status"] == "completed" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
