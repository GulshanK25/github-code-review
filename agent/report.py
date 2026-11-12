"""Turn validated reviewer findings and proposed tests into Markdown."""

from agent.models import ReviewResult, TestPlan


def format_review(review: ReviewResult) -> str:
    lines = ["# AI Code Review", "", "## Summary", "", review.summary, ""]
    if not review.findings:
        lines.extend([
            "## Findings", "", "No actionable issues were identified. ",
            "This does not guarantee that the code is correct or secure.", "",
        ])
    else:
        lines.extend(["## Findings", ""])
        for index, finding in enumerate(review.findings, start=1):
            location = f"{finding.file}:{finding.line}" if finding.line else finding.file
            lines.extend([
                f"### {index}. {finding.severity.upper()} | `{location}`", "",
                f"**Issue:** {finding.issue}", "",
            ])
            if finding.evidence:
                side = "original file" if finding.line_side == "old" else "new file"
                lines.extend([
                    f"**Changed-line evidence ({side}):** `{finding.evidence.strip()}`", "",
                ])
            lines.extend([f"**Suggestion:** {finding.suggestion}", ""])
    lines.extend([
        "---", "",
        "*AI suggestions are unverified. Review them before changing code.*", "",
    ])
    return "\n".join(lines)


def format_test_plan(plan: TestPlan, output_file: str, sources_found: bool) -> str:
    lines = [
        "## Proposed pytest tests (Milestone 2)", "", plan.summary, "",
        f"**Generated test module:** `{output_file}`", "",
        "**Source context:** " + (
            "Changed Python source files were supplied to the test generator."
            if sources_found else
            "No matching source files were found; tests are based on the diff only."
        ), "",
        "**Safety:** AI-generated test assertions are unverified. The optional Docker "
        "runner isolates execution, but test outcomes still need interpretation.", "",
    ]
    if not plan.tests:
        lines.extend(["No individual test cases were described.", ""])
    else:
        for number, test in enumerate(plan.tests, start=1):
            lines.extend([
                f"### Test {number}: `{test.name}`", "",
                f"**Purpose:** {test.purpose}", "",
                f"**Expected result:** {test.expected_behavior}", "",
            ])
    return "\n".join(lines)
