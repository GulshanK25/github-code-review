"""Run a local LangGraph-based code review from your terminal."""

import argparse
import os
from pathlib import Path

from agent.workflow import build_graph


def main():
    parser = argparse.ArgumentParser(description="Review Python Git diffs with local AI")
    parser.add_argument("--repo", default=".", help="Path to Git repository")
    parser.add_argument("--diff-file", help="Optional existing .diff file for testing")
    parser.add_argument(
        "--model", default=os.getenv("OLLAMA_MODEL", "llama3:latest"),
        help="Locally installed Ollama model name",
    )
    parser.add_argument("--output", default="review_report.md")
    args = parser.parse_args()

    graph = build_graph()
    result = graph.invoke({
        "repo": args.repo, "diff_file": args.diff_file, "model": args.model,
    })

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result["report"], encoding="utf-8")
    print(result["report"])
    print(f"\nReport saved to: {output.resolve()}")


if __name__ == "__main__":
    main()
