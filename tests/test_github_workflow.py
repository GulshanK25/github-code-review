"""Test that GitHub PR mode enters the existing LangGraph workflow."""

import pytest

pytest.importorskip("langgraph")

import agent.workflow as workflow
from agent.models import Finding, ReviewResult


def test_pr_review_uses_remote_diff_not_local_git(monkeypatch):
    def fake_fetch(url, include_sources=False):
        assert url == "https://github.com/acme/sample/pull/42"
        assert include_sources is False
        return {
            "diff": "diff --git a/auth.py b/auth.py\n--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@\n-return False\n+return True\n",
            "sources": [],
            "pr": {
                "url": url, "title": "Authorization regression", "python_files": 1,
                "sources_loaded": 0, "head_sha": "c" * 40,
            },
        }

    monkeypatch.setattr(workflow, "fetch_pull_request", fake_fetch)
    monkeypatch.setattr(workflow, "get_repo_diff", lambda *_: pytest.fail("Should not call Git"))
    monkeypatch.setattr(workflow, "review_diff", lambda diff, model: ReviewResult(
        summary="Tested PR changes", findings=[Finding(
            severity="high", file="auth.py", line=1,
            issue="Authorization changed", suggestion="Restore checking",
        )],
    ))
    result = workflow.build_graph().invoke({
        "pr_url": "https://github.com/acme/sample/pull/42",
        "repo": ".", "model": "mock", "generate_tests": False,
    })
    assert "GitHub pull request" in result["report"]
    assert "Tested PR changes" in result["report"]
    assert "https://github.com/acme/sample/pull/42" in result["report"]
