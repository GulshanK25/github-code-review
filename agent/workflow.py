"""LangGraph workflow with bounded AI test revision and optional Docker execution."""

from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent.git_utils import get_repo_diff, validate_diff_size
from agent.llm import generate_tests, review_diff, revise_tests
from agent.models import ReviewResult, TestPlan
from agent.report import format_review, format_test_plan
from agent.sandbox import run_in_docker
from agent.source_utils import load_changed_sources
from agent.test_utils import inspect_generated_tests

MAX_ATTEMPTS = 3  # Initial generation + at most two AI revisions.


class ReviewState(TypedDict, total=False):
    repo: str
    diff_file: str | None
    model: str
    generate_tests: bool
    auto_test: bool
    tests_output: str
    diff: str
    sources: list[dict[str, str]]
    summary: str
    findings: list[dict]
    test_plan: dict
    attempts: int
    validation_errors: list[str]
    sandbox_result: dict
    report: str


def load_changes(state: ReviewState) -> dict:
    if state.get("diff_file"):
        diff = validate_diff_size(Path(state["diff_file"]).read_text(encoding="utf-8"))
    else:
        diff = get_repo_diff(state["repo"])
    sources = (
        load_changed_sources(diff, state.get("repo", "."))
        if state.get("generate_tests") and diff.strip() else []
    )
    return {"diff": diff, "sources": sources}


def review_changes(state: ReviewState) -> dict:
    result = review_diff(state["diff"], state["model"])
    return {
        "summary": result.summary,
        "findings": [finding.model_dump() for finding in result.findings],
    }


def _review(state: ReviewState) -> ReviewResult:
    return ReviewResult.model_validate({
        "summary": state["summary"], "findings": state["findings"],
    })


def generate_test_cases(state: ReviewState) -> dict:
    plan = generate_tests(
        state["diff"], _review(state), state.get("sources", []), state["model"],
    )
    return {"test_plan": plan.model_dump(), "attempts": 1}


def validate_tests(state: ReviewState) -> dict:
    plan = TestPlan.model_validate(state["test_plan"])
    return {
        "validation_errors": inspect_generated_tests(
            plan.pytest_code, state.get("sources", []),
        ),
        "sandbox_result": {},
    }


def revise_test_cases(state: ReviewState) -> dict:
    feedback = state.get("validation_errors", [])
    if not feedback:
        feedback = [state.get("sandbox_result", {}).get("details", "Unknown test error")[-4500:]]
    plan = revise_tests(
        state["diff"], _review(state), state.get("sources", []),
        TestPlan.model_validate(state["test_plan"]),
        feedback, state["model"],
    )
    return {"test_plan": plan.model_dump(), "attempts": state["attempts"] + 1}


def execute_tests(state: ReviewState) -> dict:
    plan = TestPlan.model_validate(state["test_plan"])
    return {"sandbox_result": run_in_docker(plan.pytest_code, state.get("sources", []))}


def build_report(state: ReviewState) -> dict:
    review = (
        _review(state) if state["diff"].strip()
        else ReviewResult(summary="No changes to tracked Python files were found.", findings=[])
    )
    report = format_review(review)
    if "test_plan" in state:
        plan = TestPlan.model_validate(state["test_plan"])
        report += "\n" + format_test_plan(
            plan, state.get("tests_output", "generated_tests/test_ai_generated.py"),
            sources_found=bool(state.get("sources")),
        )
        report += "\n## Automated test validation\n\n"
        report += f"**Generation attempts:** {state.get('attempts', 1)}/{MAX_ATTEMPTS}\n\n"
        problems = state.get("validation_errors", [])
        if problems:
            report += "**Static checks: FAILED**\n\n"
            for problem in problems:
                report += f"- {problem}\n"
            report += "\nNo proposed test file was saved because static validation failed.\n"
        else:
            report += "**Static checks: PASSED** (not a correctness guarantee).\n\n"
            if not state.get("auto_test"):
                report += "**Docker execution:** Not requested.\n"
            else:
                sandbox = state.get("sandbox_result", {})
                status = sandbox.get("status", "not_run")
                report += f"**Docker execution:** {status}\n\n"
                if status == "assertion_failures":
                    report += (
                        "Failing assertions may correctly expose the bug. "
                        "They were deliberately NOT rewritten just to pass.\n\n"
                    )
                if status in {"repair_needed", "environment_error", "timeout", "not_run"}:
                    report += "Execution could not establish test correctness.\n\n"
                if sandbox.get("details"):
                    report += "```text\n" + sandbox["details"][-6500:].replace("```", "'''") + "\n```\n"
    return {"report": report}


def next_step(state: ReviewState) -> str:
    return "review" if state["diff"].strip() else "report"


def after_review(state: ReviewState) -> str:
    return "tests" if state.get("generate_tests", False) else "report"


def after_validation(state: ReviewState) -> str:
    if state.get("validation_errors"):
        return "revise" if state["attempts"] < MAX_ATTEMPTS else "report"
    return "execute" if state.get("auto_test", False) else "report"


def after_execution(state: ReviewState) -> str:
    # A test failure caused by a wrong app implementation is valuable.
    # Revise only for imports/name errors, not failing assertions.
    if (state["sandbox_result"].get("status") == "repair_needed"
            and state["attempts"] < MAX_ATTEMPTS):
        return "revise"
    return "report"


def build_graph():
    builder = StateGraph(ReviewState)
    builder.add_node("load_changes", load_changes)
    builder.add_node("review", review_changes)
    builder.add_node("tests", generate_test_cases)
    builder.add_node("validate", validate_tests)
    builder.add_node("revise", revise_test_cases)
    builder.add_node("execute", execute_tests)
    builder.add_node("report", build_report)

    builder.add_edge(START, "load_changes")
    builder.add_conditional_edges(
        "load_changes", next_step, {"review": "review", "report": "report"},
    )
    builder.add_conditional_edges(
        "review", after_review, {"tests": "tests", "report": "report"},
    )
    builder.add_edge("tests", "validate")
    builder.add_conditional_edges(
        "validate", after_validation,
        {"revise": "revise", "execute": "execute", "report": "report"},
    )
    builder.add_edge("revise", "validate")
    builder.add_conditional_edges(
        "execute", after_execution, {"revise": "revise", "report": "report"},
    )
    builder.add_edge("report", END)
    return builder.compile()
