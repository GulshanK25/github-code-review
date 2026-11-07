"""LangGraph workflow for code review and test generation."""

from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent.git_utils import get_repo_diff, validate_diff_size
from agent.llm import generate_tests, review_diff
from agent.models import ReviewResult, TestPlan
from agent.report import format_review, format_test_plan
from agent.source_utils import load_changed_sources


class ReviewState(TypedDict, total=False):

    repo: str
    diff_file: str | None
    model: str

    generate_tests: bool
    tests_output: str

    diff: str
    sources: list[dict[str, str]]

    summary: str
    findings: list[dict]

    test_plan: dict
    report: str


def load_changes(state: ReviewState) -> dict:

    if state.get("diff_file"):

        path = Path(state["diff_file"])

        diff = validate_diff_size(
            path.read_text(encoding="utf-8")
        )

    else:
        diff = get_repo_diff(state["repo"])

    sources = (
        load_changed_sources(
            diff,
            state.get("repo", ".")
        )
        if state.get("generate_tests") and diff.strip()
        else []
    )

    return {
        "diff": diff,
        "sources": sources
    }


def review_changes(state: ReviewState) -> dict:

    result = review_diff(
        state["diff"],
        state["model"]
    )

    return {
        "summary": result.summary,
        "findings": [
            finding.model_dump()
            for finding in result.findings
        ],
    }


def generate_test_cases(state: ReviewState) -> dict:

    review = ReviewResult.model_validate({
        "summary": state["summary"],
        "findings": state["findings"],
    })

    result = generate_tests(
        state["diff"],
        review,
        state.get("sources", []),
        state["model"],
    )

    return {
        "test_plan": result.model_dump()
    }


def build_report(state: ReviewState) -> dict:

    if not state["diff"].strip():

        review = ReviewResult(
            summary="No changes to tracked Python files were found.",
            findings=[],
        )

    else:

        review = ReviewResult.model_validate({
            "summary": state["summary"],
            "findings": state["findings"],
        })

    report = format_review(review)

    if "test_plan" in state:

        plan = TestPlan.model_validate(
            state["test_plan"]
        )

        report += "\n" + format_test_plan(
            plan,
            state.get(
                "tests_output",
                "generated_tests/test_ai_generated.py"
            ),
            sources_found=bool(state.get("sources")),
        )

    return {"report": report}


def next_step(state: ReviewState) -> str:

    if state["diff"].strip():
        return "review"

    return "report"


def after_review(state: ReviewState) -> str:

    if state.get("generate_tests", False):
        return "tests"

    return "report"


def build_graph():

    builder = StateGraph(ReviewState)

    # Register workflow nodes.
    builder.add_node("load_changes", load_changes)
    builder.add_node("review", review_changes)
    builder.add_node("tests", generate_test_cases)
    builder.add_node("report", build_report)

    # Start by reading code changes.
    builder.add_edge(
        START,
        "load_changes"
    )

    # Skip AI review if there are no changes.
    builder.add_conditional_edges(
        "load_changes",
        next_step,
        {
            "review": "review",
            "report": "report"
        },
    )

    # Decide whether test generation is enabled.
    builder.add_conditional_edges(
        "review",
        after_review,
        {
            "tests": "tests",
            "report": "report"
        },
    )

    # Generate final report.
    builder.add_edge("tests", "report")
    builder.add_edge("report", END)

    return builder.compile()