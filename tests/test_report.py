from agent.models import Finding, ReviewResult
from agent.report import format_review


def test_report_contains_finding_and_location():
    result = ReviewResult(
        summary="Potential authorization bug.",
        findings=[
            Finding(
                severity="high",
                file="auth.py",
                line=2,
                issue="Non-admin users are permitted.",
                suggestion="Check the role explicitly.",
            )
        ],
    )
    report = format_review(result)
    assert "auth.py:2" in report
    assert "HIGH" in report
    assert "Check the role explicitly" in report


def test_empty_report_notes_limitations():
    report = format_review(ReviewResult(summary="No issues found.", findings=[]))
    assert "does not guarantee" in report
