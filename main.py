"""CLI for local AI code review, test generation, and sandboxed validation."""

import argparse
import os
from pathlib import Path

from agent.github_utils import parse_pr_url
from agent.test_utils import validate_pytest_code
from agent.workflow import build_graph


def main():
    parser = argparse.ArgumentParser(description="Review Git diffs with local AI")
    parser.add_argument("--repo", default=".", help="Source root or Git repository")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--diff-file", help="Optional .diff file")
    inputs.add_argument(
        "--pr-url", help="GitHub PR URL; retrieves Python changes through the read-only API",
    )
    parser.add_argument(
        "--model", default=os.getenv("OLLAMA_MODEL", "llama3:latest"),
        help="Locally installed Ollama model",
    )
    parser.add_argument(
        "--review-mode", choices=("evidence", "basic"), default="evidence",
        help="Evidence-based review with changed-line validation (default), "
             "or legacy basic mode",
    )
    parser.add_argument("--output", default="review_report.md")
    parser.add_argument(
        "--verify-findings", action="store_true",
        help="Run an optional independent AI reasoning check on evidence-matched findings",
    )
    parser.add_argument(
        "--contract",
        help="Behavior contract JSON within --repo (auto-detected if omitted)",
    )
    parser.add_argument("--generate-tests", action="store_true", help="Generate proposed pytest tests")
    parser.add_argument(
        "--auto-test", action="store_true",
        help="Run proposed tests automatically, but ONLY in restricted Docker",
    )
    parser.add_argument(
        "--tests-output", default="generated_tests/test_ai_generated.py",
        help="Where to save proposed tests",
    )
    args = parser.parse_args()

    if args.verify_findings and args.review_mode != "evidence":
        parser.error("--verify-findings requires --review-mode evidence")
    if args.pr_url:
        try:
            parse_pr_url(args.pr_url)
        except ValueError as exc:
            parser.error(str(exc))
    if args.contract and not args.generate_tests:
        parser.error("--contract requires --generate-tests")
    if args.auto_test and not args.generate_tests:
        parser.error("--auto-test requires --generate-tests")
    if args.generate_tests:
        target = Path(args.tests_output).resolve()
        protected = {Path(args.output).resolve()}
        if args.diff_file:
            protected.add(Path(args.diff_file).resolve())
        if target in protected:
            parser.error("--tests-output must differ from input diff and report output")
        if target.suffix != ".py":
            parser.error("--tests-output must be a .py filename")
        if target.exists():
            parser.error(f"Generated test output already exists: {target}. Use a new filename.")

    graph = build_graph()
    result = graph.invoke({
        "repo": args.repo, "diff_file": args.diff_file, "pr_url": args.pr_url,
        "review_mode": args.review_mode,
        "verify_findings": args.verify_findings,
        "model": args.model,
        "generate_tests": args.generate_tests, "auto_test": args.auto_test,
        "tests_output": args.tests_output, "contract_path": args.contract,
    })

    if "test_plan" in result and not result.get("validation_errors"):
        code = validate_pytest_code(result["test_plan"]["pytest_code"])
        target = Path(args.tests_output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            handle.write(code.rstrip() + "\n")
        print(f"Proposed pytest file saved: {target.resolve()}")
        if args.auto_test:
            print("Docker status:", result.get("sandbox_result", {}).get("status", "not_run"))
    elif result.get("validation_errors"):
        print("Generated tests were not saved: static validation failed after retries.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result["report"], encoding="utf-8")
    print(result["report"])
    print(f"\nReport saved to: {output.resolve()}")


if __name__ == "__main__":
    main()
