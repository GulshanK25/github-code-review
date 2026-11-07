import pytest

from agent.models import (
    Finding,
    ProposedTest,
    ReviewResult,
    TestPlan as GeneratedTestPlan
)

import agent.workflow as workflow


def fake_review(diff, model):

    assert "return True" in diff

    return ReviewResult(
        summary="Found a potential bug.",
        findings=[
            Finding(
                severity="high",
                file="auth.py",
                line=1,
                issue="Authorization bypass",
                suggestion="Restore role checking",
            )
        ],
    )


def fake_tests(diff, review, sources, model):

    assert review.findings[0].issue == "Authorization bypass"
    assert model == "mock-model"

    return GeneratedTestPlan(
        summary="One authorization regression test.",
        tests=[
            ProposedTest(
                name="test_non_admin_denied",
                purpose="Prevent permission bypass",
                expected_behavior="Non-admin users are denied",
            )
        ],
        pytest_code=(
            "def test_non_admin_denied():\n"
            "    assert False\n"
        ),
    )


def test_graph_produces_review_without_generation(
    tmp_path,
    monkeypatch
):

    diff_file = tmp_path / "sample.diff"

    diff_file.write_text(
        "diff --git a/auth.py b/auth.py\n+return True\n",
        encoding="utf-8"
    )

    monkeypatch.setattr(
        workflow,
        "review_diff",
        fake_review
    )

    def must_not_generate(*args, **kwargs):
        pytest.fail(
            "No test generation without --generate-tests"
        )

    monkeypatch.setattr(
        workflow,
        "generate_tests",
        must_not_generate
    )

    result = workflow.build_graph().invoke({
        "repo": ".",
        "diff_file": str(diff_file),
        "model": "mock-model",
    })

    assert "Authorization bypass" in result["report"]
    assert "test_plan" not in result


def test_graph_produces_proposed_tests(
    tmp_path,
    monkeypatch
):

    diff_file = tmp_path / "sample.diff"

    diff_file.write_text(
        "+++ b/auth.py\n+return True\n",
        encoding="utf-8"
    )

    (tmp_path / "auth.py").write_text(
        "def check():\n    return True\n",
        encoding="utf-8"
    )

    monkeypatch.setattr(
        workflow,
        "review_diff",
        fake_review
    )

    monkeypatch.setattr(
        workflow,
        "generate_tests",
        fake_tests
    )

    result = workflow.build_graph().invoke({
        "repo": str(tmp_path),
        "diff_file": str(diff_file),
        "model": "mock-model",
        "generate_tests": True,
        "tests_output": "generated_tests/test_ai_generated.py",
    })

    assert "test_non_admin_denied" in result["report"]

    assert (
        "test_non_admin_denied"
        in result["test_plan"]["pytest_code"]
    )

    assert result["sources"][0]["path"] == "auth.py"


def test_empty_diff_skips_both_models(
    tmp_path,
    monkeypatch
):

    diff_file = tmp_path / "empty.diff"

    diff_file.write_text(
        "",
        encoding="utf-8"
    )

    def must_not_call_model(*args, **kwargs):
        pytest.fail(
            "Model should not be called for empty diffs"
        )

    monkeypatch.setattr(
        workflow,
        "review_diff",
        must_not_call_model
    )

    monkeypatch.setattr(
        workflow,
        "generate_tests",
        must_not_call_model
    )

    result = workflow.build_graph().invoke({
        "repo": ".",
        "diff_file": str(diff_file),
        "model": "mock-model",
        "generate_tests": True,
    })

    assert "No changes" in result["report"]
    assert "test_plan" not in result