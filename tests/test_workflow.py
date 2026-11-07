from agent.models import Finding, ReviewResult
import agent.workflow as workflow


def test_graph_produces_report_without_calling_real_model(tmp_path, monkeypatch):
    diff_file = tmp_path / "sample.diff"
    diff_file.write_text("diff --git a/auth.py b/auth.py\n+return True\n", encoding="utf-8")

    def fake_review(diff, model):
        assert "return True" in diff
        return ReviewResult(
            summary="Found a potential bug.",
            findings=[Finding(
                severity="high", file="auth.py", line=1,
                issue="Authorization bypass", suggestion="Restore role checking",
            )],
        )

    monkeypatch.setattr(workflow, "review_diff", fake_review)
    result = workflow.build_graph().invoke({
        "repo": ".", "diff_file": str(diff_file), "model": "mock-model",
    })
    assert "Authorization bypass" in result["report"]


def test_empty_diff_skips_model(tmp_path, monkeypatch):
    diff_file = tmp_path / "empty.diff"
    diff_file.write_text("", encoding="utf-8")

    def must_not_call_model(diff, model):
        pytest.fail("Model should not be called for empty diffs")

    import pytest
    monkeypatch.setattr(workflow, "review_diff", must_not_call_model)
    result = workflow.build_graph().invoke({
        "repo": ".", "diff_file": str(diff_file), "model": "mock-model",
    })
    assert "No changes" in result["report"]
