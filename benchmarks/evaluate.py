"""Evaluate case-level bug localization and safe-change false alarms.

Run from the repository root:
    python -m benchmarks.evaluate --model qwen2.5-coder:7b

This does not execute benchmark source code. It only sends diffs and source
text through the existing evidence-based LangGraph review workflow.
"""

import argparse
import csv
import difflib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path

from agent.review_quality import changed_line_index

DEFAULT_CASES = Path(__file__).with_name("cases.json")
DEFAULT_OUTPUT = Path("benchmarks/results/latest.json")
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Benchmark cases must be a non-empty JSON array")
    names = set()
    for case in data:
        if not isinstance(case, dict):
            raise ValueError("Each benchmark case must be an object")
        name = case.get("name")
        filename = case.get("filename")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name) or name in names:
            raise ValueError(f"Invalid or duplicate case name: {name!r}")
        names.add(name)
        if (not isinstance(filename, str) or not filename.endswith(".py")
                or Path(filename).name != filename or filename in {".py", "..py"}):
            raise ValueError(f"Invalid source filename in {name}: {filename!r}")
        if case.get("expected") not in {"bug", "safe"}:
            raise ValueError(f"Case {name} needs expected='bug' or 'safe'")
        old = case.get("old_code")
        new = case.get("new_code")
        if not isinstance(old, str) or not isinstance(new, str) or old == new:
            raise ValueError(f"Case {name} must have distinct old_code/new_code strings")
        if len(old) + len(new) > 12_000:
            raise ValueError(f"Case {name} is too large for the compact benchmark")
        if case["expected"] == "bug":
            line = case.get("bug_line")
            if type(line) is not int or line <= 0:
                raise ValueError(f"Case {name} must provide a positive bug_line")
            if (filename, "new", line) not in changed_line_index(make_diff(case)):
                raise ValueError(f"Case {name} bug_line does not point to a changed new line")
    return data


def make_diff(case: dict) -> str:
    filename = case["filename"]
    patch = "".join(difflib.unified_diff(
        case["old_code"].splitlines(keepends=True),
        case["new_code"].splitlines(keepends=True),
        fromfile=f"a/{filename}", tofile=f"b/{filename}", n=3,
    ))
    return f"diff --git a/{filename} b/{filename}\n" + patch


def _outcome_for(case: dict, findings: list[dict]) -> str:
    """Case-level label, not an independent correctness judgment."""
    target = any(
        f.get("file") == case["filename"]
        and f.get("line") == case.get("bug_line")
        and f.get("line_side", "new") == "new"
        for f in findings
    )
    if case["expected"] == "bug":
        return "TP" if target else "FN"
    return "FP" if findings else "TN"


def classify_case(case: dict, result: dict) -> dict:
    """One labeled changed line per buggy case; safe cases have no expected bug.

    Findings on unrelated lines in positive cases are tracked separately.
    Location matching is a proxy and does not prove that an issue is real.
    """
    findings = result.get("findings", [])
    outcome = _outcome_for(case, findings)
    if case["expected"] == "bug":
        off_target = sum(1 for f in findings if not (
            f.get("file") == case["filename"]
            and f.get("line") == case.get("bug_line")
            and f.get("line_side", "new") == "new"
        ))
    else:
        off_target = 0
    verdicts = result.get("review_verdicts", [])
    initial = result.get("review_evidence_findings", findings)
    uncertain = [v["finding"] for v in verdicts if v["decision"] == "uncertain"]
    triaged = findings + uncertain
    return {
        "case": case["name"],
        "expected": case["expected"],
        "outcome": outcome,
        "initial_outcome": _outcome_for(case, initial),
        "triage_outcome": _outcome_for(case, triaged),
        "uncertain_findings": len(uncertain),
        "rejected_findings": sum(v["decision"] == "rejected" for v in verdicts),
        "verdict_details": verdicts,
        "accepted_findings": len(findings),
        "held_findings": len(result.get("review_held", [])),
        "off_target_findings": off_target,
        "summary": result.get("summary", ""),
        "verification_supported": result.get("review_verification", {}).get("supported", 0),
        "verification_rejected": result.get("review_verification", {}).get("rejected", 0),
        "verification_uncertain": result.get("review_verification", {}).get("uncertain", 0),
        "verification_error": result.get("review_verification_error", ""),
        "line_corrections": len(result.get("review_relocations", [])),
        "accepted_details": findings,
        "held_reasons": result.get("review_held", []),
        "line_correction_details": result.get("review_relocations", []),
    }


def aggregate(rows: list[dict]) -> dict:
    counts = Counter(row["outcome"] for row in rows)
    tp, fp, fn, tn = (counts[key] for key in ("TP", "FP", "FN", "TN"))

    def rate(top: int, bottom: int):
        return round(top / bottom, 3) if bottom else None

    def stage_metrics(key: str) -> dict:
        stage = Counter(row.get(key, row["outcome"]) for row in rows)
        return {
            "tp": stage["TP"], "fp": stage["FP"],
            "fn": stage["FN"], "tn": stage["TN"],
            "recall_proxy": rate(stage["TP"], stage["TP"] + stage["FN"]),
            "false_alarm_rate": rate(stage["FP"], stage["FP"] + stage["TN"]),
        }

    return {
        "cases": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision_proxy": rate(tp, tp + fp),
        "recall_proxy": rate(tp, tp + fn),
        "false_alarm_rate": rate(fp, fp + tn),
        "accuracy_proxy": rate(tp + tn, len(rows)),
        "off_target_findings": sum(row["off_target_findings"] for row in rows),
        # These are separate visibility / triage measures, not verified correctness.
        "initial_evidence_stage": stage_metrics("initial_outcome"),
        "accepted_or_uncertain_stage": stage_metrics("triage_outcome"),
        "uncertain_candidates": sum(row.get("uncertain_findings", 0) for row in rows),
        "rejected_candidates": sum(row.get("rejected_findings", 0) for row in rows),
    }



def run_case(case: dict, model: str, graph, verify_findings: bool = False) -> dict:
    diff = make_diff(case)
    with tempfile.TemporaryDirectory(prefix="review-benchmark-") as workdir:
        root = Path(workdir)
        (root / case["filename"]).write_text(case["new_code"], encoding="utf-8")
        path = root / "change.diff"
        path.write_text(diff, encoding="utf-8")
        result = graph.invoke({
            "repo": str(root), "diff_file": str(path), "model": model,
            "review_mode": "evidence", "generate_tests": False, "auto_test": False,
            "verify_findings": verify_findings,
        })
    return classify_case(case, result)


def save_results(path: Path, model: str, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": model, "metrics": aggregate(rows), "results": rows,
               "note": "Case-level localization proxies, not verified issue-level precision or recall."}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evidence-based code review benchmark")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--only", help="Run one named benchmark case")
    parser.add_argument(
        "--verify-findings", action="store_true",
        help="Add a second-pass AI check after exact-line evidence validation",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    cases = load_cases(args.cases)
    if args.only:
        cases = [case for case in cases if case["name"] == args.only]
        if not cases:
            parser.error(f"Case not found: {args.only}")

    from agent.workflow import build_graph  # Heavy dependencies loaded only for actual runs.
    graph = build_graph()
    rows = []
    for case in cases:
        try:
            result = run_case(case, args.model, graph, verify_findings=args.verify_findings)
        except Exception as exc:
            print(f"ERROR {case['name']}: {exc}")
            raise SystemExit(1) from exc
        rows.append(result)
        print(f"{result['outcome']:>2}  {case['name']}  (accepted={result['accepted_findings']}, "
              f"held={result['held_findings']})")
    save_results(args.output, args.model, rows)
    metrics = aggregate(rows)
    print("\nCase-level evaluation (small benchmark, interpret cautiously):")
    for name in ("tp", "fp", "fn", "tn", "precision_proxy", "recall_proxy", "false_alarm_rate"):
        print(f"  {name}: {metrics[name]}")
    if args.verify_findings:
        print("\nAdditional visibility metrics (NOT confirmed findings):")
        print("  Initial evidence-matched reviewer:", metrics["initial_evidence_stage"])
        print("  Accepted OR uncertain candidates:", metrics["accepted_or_uncertain_stage"])
        print("  Disputed candidates awaiting human review:", metrics["uncertain_candidates"])
        print("  Rejected candidates retained in audit trail:", metrics["rejected_candidates"])
    print(f"Saved JSON: {args.output}")
    print(f"Saved CSV:  {args.output.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
