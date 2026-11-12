"""Repeatable comparison of evidence-only versus optional AI verification.

This uses the existing benchmark evaluator and a separate holdout dataset.
No benchmark application code is executed by this runner.

Examples:
    python -m benchmarks.holdout_compare --repeats 1 --mode evidence
    python -m benchmarks.holdout_compare --repeats 2 --mode both
"""

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path

from benchmarks.evaluate import aggregate, load_cases, run_case, save_results

HOLDOUT_CASES = Path(__file__).with_name("holdout_cases.json")
DEFAULT_RESULTS_DIR = Path("benchmarks/results/holdout")
METRICS = ("precision_proxy", "recall_proxy", "false_alarm_rate")
MODES = {"evidence": False, "verified": True}


def summarize_runs(runs: list[list[dict]]) -> dict:
    """Summarize complete benchmark repetitions without pooling away variation."""
    if not runs or any(not run for run in runs):
        raise ValueError("At least one non-empty benchmark run is required")
    reference = [row["case"] for row in runs[0]]
    if len(reference) != len(set(reference)):
        raise ValueError("Duplicate case in benchmark run")
    for run in runs:
        if [row["case"] for row in run] != reference:
            raise ValueError("All runs must contain the same cases in the same order")

    per_run = [aggregate(rows) for rows in runs]
    metric_summary = {}
    for metric in METRICS:
        values = [summary[metric] for summary in per_run if summary[metric] is not None]
        metric_summary[metric] = (
            {"mean": round(statistics.mean(values), 3),
             "min": min(values), "max": max(values),
             "population_stddev": round(statistics.pstdev(values), 3)}
            if values else {"mean": None, "min": None, "max": None, "population_stddev": None}
        )
    case_stability = []
    for index, name in enumerate(reference):
        outcomes = [run[index]["outcome"] for run in runs]
        initial_outcomes = [run[index].get("initial_outcome", run[index]["outcome"]) for run in runs]
        case_stability.append({
            "case": name,
            "expected": runs[0][index]["expected"],
            "outcomes": outcomes,
            "initial_outcomes": initial_outcomes,
            "stable": len(set(outcomes)) == 1,
            "outcome_counts": dict(Counter(outcomes)),
        })
    return {
        "runs": len(runs),
        "cases_per_run": len(reference),
        "per_run_metrics": per_run,
        "metric_summary": metric_summary,
        "case_stability": case_stability,
        "unstable_cases": [row["case"] for row in case_stability if not row["stable"]],
    }


def execute_holdout(
    cases: list[dict], model: str, repeats: int, mode: str,
    results_dir: Path, graph, run_one=run_case,
) -> dict:
    """Execute a mode and save individual runs. run_one is injectable for offline tests."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}")
    if not cases:
        raise ValueError("Cannot run an empty case list")
    runs = []
    for index in range(1, repeats + 1):
        print(f"\n[{mode}] Run {index}/{repeats} ({len(cases)} cases)", flush=True)
        rows = []
        for case in cases:
            result = run_one(case, model, graph, verify_findings=MODES[mode])
            rows.append(result)
            print(f"  {result['outcome']:>2}  {case['name']} "
                  f"(accepted={result['accepted_findings']}, held={result['held_findings']})", flush=True)
        save_results(results_dir / f"{mode}_run_{index}.json", model, rows)
        runs.append(rows)
        scores = aggregate(rows)
        print(f"  Precision: {scores['precision_proxy']}  Recall: {scores['recall_proxy']}  "
              f"False-alarm rate: {scores['false_alarm_rate']}", flush=True)
    return summarize_runs(runs)


def save_comparison(directory: Path, model: str, cases_path: Path, summaries: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "comparison.json"
    payload = {
        "model": model,
        "dataset": str(cases_path),
        "evaluation_kind": "case-level changed-line localization, not independently verified issue-level accuracy",
        "notes": [
            "Hand-authored holdout set, distinct from the original eight training/development examples.",
            "Model runs are stochastic; the two modes re-run the initial review rather than sharing identical proposals.",
            "Uncertain verifier findings are retained for audit but not counted as confirmed true positives.",
            "Do not tune the model prompt to this holdout dataset; create another holdout for future comparisons.",
        ],
        "modes": summaries,
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (directory / "comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["mode", "run", "cases", "tp", "fp", "fn", "tn",
                         "precision_proxy", "recall_proxy", "false_alarm_rate", "uncertain_candidates"])
        for mode, summary in summaries.items():
            for i, metrics in enumerate(summary["per_run_metrics"], start=1):
                writer.writerow([mode, i, metrics["cases"], metrics["tp"], metrics["fp"],
                                 metrics["fn"], metrics["tn"], metrics["precision_proxy"],
                                 metrics["recall_proxy"], metrics["false_alarm_rate"],
                                 metrics.get("uncertain_candidates", 0)])
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run independent holdout code-review benchmark")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--cases", type=Path, default=HOLDOUT_CASES)
    parser.add_argument("--mode", choices=("evidence", "verified", "both"), default="both")
    parser.add_argument("--repeats", type=int, default=1,
                        help="Number of independent full repeats per mode (1 to 5)")
    parser.add_argument("--only", help="Evaluate one named holdout case for a smoke test")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    args = parser.parse_args()

    if not 1 <= args.repeats <= 5:
        parser.error("--repeats must be between 1 and 5")
    cases = load_cases(args.cases)
    if args.only:
        cases = [case for case in cases if case["name"] == args.only]
        if not cases:
            parser.error(f"Unknown case: {args.only}")
    modes = list(MODES) if args.mode == "both" else [args.mode]

    # Import LangGraph only for a real model run, not for unit tests/data validation.
    from agent.workflow import build_graph
    graph = build_graph()
    results = {}
    for mode in modes:
        try:
            results[mode] = execute_holdout(cases, args.model, args.repeats,
                                            mode, args.results_dir, graph)
        except Exception as exc:
            print(f"ERROR during {mode} benchmark: {exc}")
            raise SystemExit(1) from exc

    output = save_comparison(args.results_dir, args.model, args.cases, results)
    print("\nSummary across repeats:")
    for mode, result in results.items():
        metrics = result["metric_summary"]
        print(f"  {mode}: precision={metrics['precision_proxy']['mean']}, "
              f"recall={metrics['recall_proxy']['mean']}, "
              f"false_alarm_rate={metrics['false_alarm_rate']['mean']}, "
              f"unstable_cases={len(result['unstable_cases'])}")
    print(f"Saved comparison: {output}")
    print(f"Saved table: {output.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
