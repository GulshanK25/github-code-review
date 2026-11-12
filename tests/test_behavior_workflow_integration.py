"""Integration tests using the actual LangGraph graph and mocked model/Docker."""

import json
from pathlib import Path

import pytest

pytest.importorskip("langgraph")

import agent.workflow as workflow
from agent.models import Finding, ReviewResult

DEMO = Path(__file__).resolve().parents[1] / "examples" / "behavior_review"


def fake_review(diff, model, sources):
    return ReviewResult(summary="Auth bypass found", findings=[Finding(
        severity="high", file="auth.py", line=4, line_side="new",
        evidence="    return bool(user)",
        issue="Non-admin user can delete another account after the role check was removed.",
        suggestion="Restore explicit administrator authorization check.",
    )])


def test_behavior_is_reported_without_changing_review_findings(monkeypatch):
    monkeypatch.setattr(workflow, "review_diff_grounded", fake_review)
    called = []
    def fake_compare(item):
        called.append(item["name"])
        return {"status": "completed", "observation": "difference_observed",
                "probes": [{"before": {}, "after": {}, "different": True}],
                "differences": 1}
    monkeypatch.setattr("agent.behavior_integration.compare_in_docker", fake_compare)
    out = workflow.build_graph().invoke({
        "repo": str(DEMO), "diff_file": str(DEMO / "auth.diff"),
        "behavior_cases": str(DEMO / "cases.json"),
        "execute_behavior_in_docker": True, "review_mode": "evidence", "model": "mock",
    })
    assert called == ["auth_regression_demo"]
    assert len(out["findings"]) == 1
    assert "Behavioral comparison" in out["report"]
    assert "difference_observed" in out["report"]
    assert "auth.py:4" in out["report"]


def test_ordinary_review_never_calls_behavior_runner(monkeypatch):
    monkeypatch.setattr(workflow, "review_diff_grounded", fake_review)
    monkeypatch.setattr("agent.behavior_integration.compare_in_docker",
                        lambda _: pytest.fail("Unexpected execution"))
    out = workflow.build_graph().invoke({
        "repo": str(DEMO), "diff_file": str(DEMO / "auth.diff"),
        "review_mode": "evidence", "model": "mock",
    })
    assert "Behavioral comparison" not in out["report"]


def test_bad_behavior_cases_does_not_break_review(monkeypatch):
    monkeypatch.setattr(workflow, "review_diff_grounded", fake_review)
    out = workflow.build_graph().invoke({
        "repo": str(DEMO), "diff_file": str(DEMO / "auth.diff"),
        "behavior_cases": "missing-cases-file.json",
        "execute_behavior_in_docker": True, "review_mode": "evidence", "model": "mock",
    })
    assert len(out["findings"]) == 1
    assert "not_run" in out["report"]
    assert "input_validation" in out["report"]
