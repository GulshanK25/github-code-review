"""LangGraph workflow with bounded AI test revision and optional Docker execution."""

from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent.contracts import contract_pytest_code, load_behavior_contract
from agent.git_utils import get_repo_diff, validate_diff_size
from agent.github_utils import fetch_pull_request
from agent.llm import generate_tests, review_diff, review_diff_grounded, revise_tests, verify_findings
from agent.models import ReviewResult, TestPlan
from agent.review_quality import validate_review_evidence
from agent.report import format_review, format_test_plan
from agent.sandbox import run_in_docker
from agent.source_utils import load_changed_sources
from agent.test_utils import inspect_generated_tests

MAX_ATTEMPTS = 3  # Initial generation + at most two AI revisions.


class ReviewState(TypedDict, total=False):
    repo: str
    pr_url: str | None
    review_mode: str
    review_candidates: int
    review_held: list[str]
    review_evidence_count: int
    review_relocations: list[str]
    review_evidence_findings: list[dict]
    review_verdicts: list[dict]
    verify_findings: bool
    review_verification: dict
    review_verification_error: str
    pr: dict
    diff_file: str | None
    model: str
    generate_tests: bool
    auto_test: bool
    tests_output: str
    contract_path: str | None
    contract: dict
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
    if state.get("pr_url"):
        github_data = fetch_pull_request(
            state["pr_url"], include_sources=bool(
                state.get("generate_tests") or state.get("review_mode") == "evidence"
            ),
        )
        diff = github_data["diff"]
        sources = github_data["sources"]
        pr = github_data["pr"]
        # Do not auto-discover a contract from the agent's own checkout.
        # For PRs, accept only a user-selected local (trusted) contract.
        contract = (
            load_behavior_contract(state.get("repo", "."), state["contract_path"], sources)
            if state.get("contract_path") and state.get("generate_tests") and diff.strip()
            else None
        )
        return {"diff": diff, "sources": sources, "contract": contract, "pr": pr}

    if state.get("diff_file"):
        diff = validate_diff_size(Path(state["diff_file"]).read_text(encoding="utf-8"))
    else:
        diff = get_repo_diff(state["repo"])
    sources = (
        load_changed_sources(diff, state.get("repo", "."))
        if (state.get("generate_tests") or state.get("review_mode") == "evidence")
        and diff.strip() else []
    )
    contract = (
        load_behavior_contract(state.get("repo", "."), state.get("contract_path"), sources)
        if state.get("generate_tests") and diff.strip() else None
    )
    return {"diff": diff, "sources": sources, "contract": contract}


def review_changes(state: ReviewState) -> dict:
    if state.get("review_mode") == "evidence":
        result = review_diff_grounded(
            state["diff"], state["model"], state.get("sources", []),
        )
    else:
        # Backward-compatible mode for existing callers and unit tests.
        result = review_diff(state["diff"], state["model"])
    return {
        "summary": result.summary,
        "findings": [finding.model_dump() for finding in result.findings],
        "review_candidates": len(result.findings),
    }


def validate_review(state: ReviewState) -> dict:
    """Filter unsourced findings before they reach tests or the report."""
    if state.get("review_mode") != "evidence":
        return {}
    relocations = []
    accepted, held = validate_review_evidence(
        _review(state), state["diff"], relocations=relocations,
    )
    return {
        "findings": [finding.model_dump() for finding in accepted.findings],
        "review_held": held,
        "review_evidence_count": len(accepted.findings),
        "review_relocations": relocations,
        "review_evidence_findings": [finding.model_dump() for finding in accepted.findings],
    }


def verify_review(state: ReviewState) -> dict:
    """Optional independent LLM check. Failure never silently removes findings."""
    if (state.get("review_mode") != "evidence"
            or not state.get("verify_findings") or not state.get("findings")):
        return {}
    review = _review(state)
    try:
        judgments = verify_findings(
            state["diff"], state["model"], state.get("sources", []), review,
        )
    except (RuntimeError, ValueError) as exc:
        # Keep findings visible, but do not claim the verification succeeded.
        return {"review_verification_error": str(exc)}
    by_index = {item.candidate_index: item for item in judgments.verdicts}
    accepted = []
    held = list(state.get("review_held", []))
    verdict_details = []
    counts = {"supported": 0, "rejected": 0, "uncertain": 0}
    for index, finding in enumerate(review.findings, start=1):
        verdict = by_index[index]
        counts[verdict.decision] += 1
        verdict_details.append({
            "candidate_index": index,
            "decision": verdict.decision,
            "reason": verdict.reason,
            "finding": finding.model_dump(),
        })
        if verdict.decision == "supported":
            accepted.append(finding)
        else:
            held.append(
                f"AI verification ({verdict.decision}) for candidate {index} "
                f"({finding.file}:{finding.line}): {verdict.reason}"
            )
    return {
        "findings": [finding.model_dump() for finding in accepted],
        "review_held": held,
        "review_verdicts": verdict_details,
        "review_verification": {"total": len(review.findings), **counts},
    }



def _review(state: ReviewState) -> ReviewResult:
    return ReviewResult.model_validate({
        "summary": state["summary"], "findings": state["findings"],
    })


def generate_test_cases(state: ReviewState) -> dict:
    args = (state["diff"], _review(state), state.get("sources", []), state["model"])
    contract = state.get("contract")
    plan = (
        generate_tests(*args, contract=contract) if contract
        else generate_tests(*args)
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
    args = (
        state["diff"], _review(state), state.get("sources", []),
        TestPlan.model_validate(state["test_plan"]), feedback, state["model"],
    )
    contract = state.get("contract")
    plan = (
        revise_tests(*args, contract=contract) if contract
        else revise_tests(*args)
    )
    return {"test_plan": plan.model_dump(), "attempts": state["attempts"] + 1}


def execute_tests(state: ReviewState) -> dict:
    plan = TestPlan.model_validate(state["test_plan"])
    contract = state.get("contract")
    if contract:
        result = run_in_docker(
            plan.pytest_code, state.get("sources", []),
            contract_code=contract_pytest_code(contract),
        )
    else:
        result = run_in_docker(plan.pytest_code, state.get("sources", []))
    return {"sandbox_result": result}


def build_report(state: ReviewState) -> dict:
    review = (
        _review(state) if state["diff"].strip()
        else ReviewResult(summary="No changes to tracked Python files were found.", findings=[])
    )
    report = format_review(review)
    if state.get("review_mode") == "evidence" and state["diff"].strip():
        count = state.get("review_candidates", 0)
        held = state.get("review_held", [])
        evidence_count = state.get("review_evidence_count", len(review.findings))
        note = (
            "## Evidence validation\n\n"
            f"**Findings with matching changed-line evidence:** {evidence_count}/{count}\n\n"
            f"**Candidates held for review:** {len(held)}\n\n"
            "Evidence matching does not prove a finding is true. "
            "The reviewer may miss bugs or safeguards in files not provided.\n\n"
        )
        if state.get("review_relocations"):
            note += "**Exact-quote line corrections:**\n\n"
            for correction in state["review_relocations"]:
                note += f"- {correction}\n"
            note += "\n"
        if state.get("verify_findings"):
            verification = state.get("review_verification")
            error = state.get("review_verification_error")
            if error:
                note += (
                    "**AI verification:** unavailable; evidence-matched findings "
                    f"remain unverified. Reason: {error}\n\n"
                )
            elif verification:
                note += (
                    "**Second-pass AI judgments (not proof):** "
                    f"supported={verification['supported']}, "
                    f"rejected={verification['rejected']}, "
                    f"uncertain={verification['uncertain']}\n\n"
                )
            else:
                note += "**Second-pass AI verification:** no evidence-matched candidates to check.\n\n"
        verdict_details = state.get("review_verdicts", [])
        for decision, heading in (
            ("uncertain", "Disputed findings: manual review required"),
            ("rejected", "Findings rejected by the AI verifier (audit trail)"),
        ):
            matches = [entry for entry in verdict_details if entry["decision"] == decision]
            if not matches:
                continue
            note += f"### {heading}\n\n"
            note += (
                "These evidence-matched candidates are not counted as accepted findings. "
                "An AI rejection is not proof that a problem is absent.\n\n"
            )
            for entry in matches:
                candidate = entry["finding"]
                location = f"{candidate['file']}:{candidate.get('line') or '?'}"
                evidence = (candidate.get("evidence") or "").strip().replace("`", "'")
                note += (
                    f"**Candidate {entry['candidate_index']} | `{location}`**\n\n"
                    f"- Proposed issue: {candidate['issue']}\n"
                    f"- Changed-line evidence: `{evidence}`\n"
                    f"- Suggested fix: {candidate['suggestion']}\n"
                    f"- AI verifier rationale: {entry['reason']}\n\n"
                )
        evidence_held = [reason for reason in held if not reason.startswith("AI verification (")]
        if evidence_held:
            note += "**Evidence-check reasons findings were held:**\n\n"
            for reason in evidence_held:
                note += f"- {reason}\n"
            note += "\n"
        if held and not review.findings:
            report = report.replace(
                "No actionable issues were identified.",
                "No findings are currently accepted. "
                "Held or disputed candidates may still warrant manual investigation.",
                1,
            )
        report = report.replace("# AI Code Review\n\n", "# AI Code Review\n\n" + note, 1)
    if state.get("pr"):
        pr = state["pr"]
        title = pr["title"].replace("`", "'")
        report = (
            f"## GitHub pull request\n\n"
            f"**PR:** {pr['url']}\n\n"
            f"**Title:** {title}\n\n"
            f"**Changed Python files:** {pr['python_files']}\n\n"
            "**Access:** Read-only GitHub API requests.\n\n"
        ) + report
        if ((state.get("generate_tests") or state.get("review_mode") == "evidence")
                and pr["sources_loaded"] < pr["python_files"]):
            report += (
                "\n**Source context limitation:** Some changed Python files were "
                "not loaded (size or source-file limits). The reviewer may "
                "lack context; Docker tests may require additional source files.\n"
            )
    if "test_plan" in state:
        plan = TestPlan.model_validate(state["test_plan"])
        report += "\n" + format_test_plan(
            plan, state.get("tests_output", "generated_tests/test_ai_generated.py"),
            sources_found=bool(state.get("sources")),
        )
        contract = state.get("contract")
        if contract:
            report += (
                "\n## Behavioral contract\n\n"
                f"**Function:** `{contract['module']}.{contract['function']}`\n\n"
                f"**Requirements:** {len(contract['test_cases'])} explicit cases\n\n"
                "The contract guides AI generation and revisions. With Docker enabled, "
                "independent contract checks are executed in a separate test module "
                "alongside the AI-generated tests.\n\n"
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
    builder.add_node("validate_review", validate_review)
    builder.add_node("verify_review", verify_review)
    builder.add_node("tests", generate_test_cases)
    builder.add_node("validate", validate_tests)
    builder.add_node("revise", revise_test_cases)
    builder.add_node("execute", execute_tests)
    builder.add_node("report", build_report)

    builder.add_edge(START, "load_changes")
    builder.add_conditional_edges(
        "load_changes", next_step, {"review": "review", "report": "report"},
    )
    builder.add_edge("review", "validate_review")
    builder.add_edge("validate_review", "verify_review")
    builder.add_conditional_edges(
        "verify_review", after_review, {"tests": "tests", "report": "report"},
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
