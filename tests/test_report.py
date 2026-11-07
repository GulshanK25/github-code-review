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


def test_test_plan_is_in_report():
    from agent.models import ProposedTest, TestPlan
    from agent.report import format_test_plan
    plan = TestPlan(
        summary="Regression tests", tests=[ProposedTest(
            name="test_permissions", purpose="Detect bypass", expected_behavior="Denied",
        )], pytest_code="def test_permissions():\n    assert True\n",
    )
    text = format_test_plan(plan, "generated_tests/test_ai_generated.py", True)
    assert "test_permissions" in text
    assert "need interpretation" in text
