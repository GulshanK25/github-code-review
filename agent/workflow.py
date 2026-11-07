"""LangGraph workflow: load diff, review changes, assemble report."""

from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent.git_utils import get_repo_diff, validate_diff_size
from agent.llm import review_diff
from agent.models import ReviewResult
from agent.report import format_review


class ReviewState(TypedDict, total=False):
    repo: str
    diff_file: str | None
    model: str
    diff: str
    summary: str
    findings: list[dict]
    report: str


def load_changes(state: ReviewState) -> dict:
    if state.get("diff_file"):
        path = Path(state["diff_file"])
        diff = validate_diff_size(path.read_text(encoding="utf-8"))
    else:
        diff = get_repo_diff(state["repo"])
    return {"diff": diff}


def review_changes(state: ReviewState) -> dict:
    result = review_diff(state["diff"], state["model"])
    return {
        "summary": result.summary,
        "findings": [finding.model_dump() for finding in result.findings],
    }


def build_report(state: ReviewState) -> dict:
    if not state["diff"].strip():
        result = ReviewResult(
            summary="No changes to tracked Python files were found.",
            findings=[],
        )
    else:
        result = ReviewResult.model_validate({
            "summary": state["summary"],
            "findings": state["findings"],
        })
    return {"report": format_review(result)}


def next_step(state: ReviewState) -> str:
    return "review" if state["diff"].strip() else "report"


def build_graph():
    builder = StateGraph(ReviewState)
    builder.add_node("load_changes", load_changes)
    builder.add_node("review", review_changes)
    builder.add_node("report", build_report)

    builder.add_edge(START, "load_changes")
    builder.add_conditional_edges(
        "load_changes", next_step, {"review": "review", "report": "report"},
    )
    builder.add_edge("review", "report")
    builder.add_edge("report", END)
    return builder.compile()
