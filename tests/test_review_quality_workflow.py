"""Workflow-level regressions for evidence mode, with mocked model and PR."""

import agent.workflow as workflow
from agent.models import Finding, ReviewResult

DIFF = '''diff --git a/auth.py b/auth.py
--- a/auth.py
+++ b/auth.py
@@ -1,2 +1,2 @@
 def can_delete_account(user):
-    return False
+    return bool(user)
'''


def test_grounded_review_passes_source_context_and_filters_generic(tmp_path, monkeypatch):
    path = tmp_path / "sample.diff"
    path.write_text(DIFF, encoding="utf-8")
    (tmp_path / "auth.py").write_text(
        "def can_delete_account(user):\n    return bool(user)\n", encoding="utf-8"
    )
    calls = []

    def fake_grounded(diff, model, sources):
        calls.append((diff, model, sources))
        return ReviewResult(summary="Possible regression", findings=[
            Finding(
                severity="high", file="auth.py", line=2,
                evidence="    return bool(user)",
                issue="A non-admin user is allowed because a nonempty dictionary is truthy.",
                suggestion="Compare the user's role against the admin role instead.",
            ),
            Finding(
                severity="high", file="auth.py", line=2,
                evidence="    return bool(user)",
                issue="Potential security risk", suggestion="Validate user inputs first.",
            ),
        ])

    monkeypatch.setattr(workflow, "review_diff_grounded", fake_grounded)
    monkeypatch.setattr(workflow, "review_diff", lambda *_: (_ for _ in ()).throw(
        AssertionError("Should not call basic review")
    ))
    output = workflow.build_graph().invoke({
        "repo": str(tmp_path), "diff_file": str(path), "model": "fake-model",
        "review_mode": "evidence", "generate_tests": False,
    })
    assert calls and calls[0][2][0]["path"] == "auth.py"
    assert len(output["findings"]) == 1
    assert len(output["review_held"]) == 1
    assert "1/2" in output["report"]
    assert "Changed-line evidence" in output["report"]
    assert "Potential security risk" not in output["report"]


def test_pr_grounded_mode_requests_source_context(monkeypatch):
    url = "https://github.com/acme/sample/pull/42"

    def fake_fetch(pr_url, include_sources=False):
        assert pr_url == url
        assert include_sources is True
        return {
            "diff": DIFF,
            "sources": [{"path": "auth.py", "content": "def can_delete_account(user):\n    return bool(user)\n"}],
            "pr": {
                "url": url, "title": "Auth fix", "python_files": 1,
                "sources_loaded": 1, "head_sha": "a" * 40,
            },
        }

    monkeypatch.setattr(workflow, "fetch_pull_request", fake_fetch)
    monkeypatch.setattr(workflow, "review_diff_grounded", lambda diff, model, sources:
        ReviewResult(summary="No supported issues", findings=[]))
    out = workflow.build_graph().invoke({
        "repo": ".", "pr_url": url, "model": "fake", "review_mode": "evidence",
    })
    assert "GitHub pull request" in out["report"]
    assert "0/0" in out["report"]
    assert "No actionable issues" in out["report"]


def test_legacy_review_still_works_without_flag(tmp_path, monkeypatch):
    path = tmp_path / "sample.diff"
    path.write_text(DIFF, encoding="utf-8")
    monkeypatch.setattr(workflow, "review_diff", lambda *_:
        ReviewResult(summary="Legacy", findings=[]))
    monkeypatch.setattr(workflow, "review_diff_grounded", lambda *args: (_ for _ in ()).throw(
        AssertionError("Should not call grounded review")))
    out = workflow.build_graph().invoke({
        "repo": str(tmp_path), "diff_file": str(path), "model": "mock",
    })
    assert "Legacy" in out["report"]
    assert "Evidence validation" not in out["report"]
