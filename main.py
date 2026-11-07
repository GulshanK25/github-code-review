"""Run a local LangGraph-based code reviewer and optional pytest generator."""

import argparse
import os
from pathlib import Path

from agent.test_utils import validate_pytest_code
from agent.workflow import build_graph


def main():
    parser = argparse.ArgumentParser(
        description="Review Git diffs with local AI"
    )

    parser.add_argument(
        "--repo",
        default=".",
        help="Path to Git repository or source directory"
    )

    parser.add_argument(
        "--diff-file",
        help="Optional existing .diff file for testing"
    )

    parser.add_argument(
        "--model",
        default=os.getenv("OLLAMA_MODEL", "llama3:latest"),
        help="Locally installed Ollama model name"
    )

    parser.add_argument(
        "--output",
        default="review_report.md"
    )

    parser.add_argument(
        "--generate-tests",
        action="store_true",
        help="Ask Ollama to propose a pytest file (never auto-executed)"
    )

    parser.add_argument(
        "--tests-output",
        default="generated_tests/test_ai_generated.py",
        help="Where to save proposed pytest code"
    )

    args = parser.parse_args()

    # Prevent accidentally overwriting input or output files.
    if args.generate_tests:
        target = Path(args.tests_output).resolve()

        protected = {Path(args.output).resolve()}

        if args.diff_file:
            protected.add(Path(args.diff_file).resolve())

        if target in protected:
            parser.error(
                "--tests-output must differ from input diff and report output"
            )

        if target.suffix != ".py":
            parser.error("--tests-output must be a .py filename")

        if target.exists():
            parser.error(
                f"Generated test output already exists: {target}. "
                "Choose another --tests-output path or remove the old file."
            )

    # Build and execute LangGraph workflow.
    graph = build_graph()

    result = graph.invoke({
        "repo": args.repo,
        "diff_file": args.diff_file,
        "model": args.model,
        "generate_tests": args.generate_tests,
        "tests_output": args.tests_output,
    })

    # Save AI-generated test code, without executing it.
    if "test_plan" in result:
        target = Path(args.tests_output)

        code = validate_pytest_code(
            result["test_plan"]["pytest_code"]
        )

        target.parent.mkdir(parents=True, exist_ok=True)

        with target.open("x", encoding="utf-8") as handle:
            handle.write(code.rstrip() + "\n")

        print(
            f"Proposed pytest file saved (NOT executed): "
            f"{target.resolve()}"
        )

    # Save final review report.
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    output.write_text(
        result["report"],
        encoding="utf-8"
    )

    print(result["report"])

    print(f"\nReport saved to: {output.resolve()}")


if __name__ == "__main__":
    main()