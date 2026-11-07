"""Regression tests for the new static checks and bounded revision routing."""

from agent.test_utils import inspect_generated_tests


def _source():
    return [{"path": "auth.py", "content": "def can_delete_account(user):\n    return bool(user)\n"}]


def test_missing_import_detected():
    code = "def test_non_admin():\n    assert can_delete_account({'role': 'user'}) is False\n"
    issues = inspect_generated_tests(code, _source())
    assert any("Missing import" in issue for issue in issues)


def test_bad_exception_contract_detected():
    code = """import pytest
from auth import can_delete_account

def test_non_admin():
    with pytest.raises(Exception):
        can_delete_account({'role': 'user'})
    assert True
"""
    issues = inspect_generated_tests(code, _source())
    assert any("pytest.raises(Exception)" in issue for issue in issues)


def test_duplicate_test_bodies_detected():
    code = """from auth import can_delete_account

def test_boundary():
    assert can_delete_account({'role': 'user'}) is False

def test_regression():
    assert can_delete_account({'role': 'user'}) is False
"""
    issues = inspect_generated_tests(code, _source())
    assert any("duplicates" in issue for issue in issues)


def test_good_bug_exposing_test_passes_static_validation():
    code = """from auth import can_delete_account

def test_non_admin():
    assert can_delete_account({'role': 'user'}) is False
"""
    assert inspect_generated_tests(code, _source()) == []


def test_incorrect_repo_root_import_detected():
    code = """from examples.sample_project.auth import can_delete_account

def test_non_admin():
    assert can_delete_account({'role': 'user'}) is False
"""
    assert any("not available" in issue for issue in inspect_generated_tests(code, _source()))


def test_forbidden_execution_detected():
    code = """import subprocess

def test_run():
    subprocess.run(['echo', 'hi'])
    assert True
"""
    assert any("Forbidden import" in issue for issue in inspect_generated_tests(code, []))


def test_revise_limit_and_assertion_protection():
    from agent.workflow import MAX_ATTEMPTS, after_execution, after_validation
    assert MAX_ATTEMPTS == 3
    assert after_validation({"validation_errors": ["missing import"], "attempts": 1}) == "revise"
    assert after_validation({"validation_errors": ["missing import"], "attempts": 3}) == "report"
    assert after_validation({"validation_errors": [], "auto_test": True}) == "execute"
    assert after_execution({"attempts": 1, "sandbox_result": {"status": "repair_needed"}}) == "revise"
    assert after_execution({"attempts": 1, "sandbox_result": {"status": "assertion_failures"}}) == "report"


def test_graph_auto_repairs_before_saving(monkeypatch, tmp_path):
    import agent.workflow as workflow
    from agent.models import ReviewResult, TestPlan, ProposedTest

    diff_file = tmp_path / "sample.diff"
    diff_file.write_text("+++ b/auth.py\n+return bool(user)\n", encoding="utf-8")
    (tmp_path / "auth.py").write_text(
        "def can_delete_account(user):\n    return bool(user)\n", encoding="utf-8"
    )
    monkeypatch.setattr(workflow, "review_diff", lambda diff, model: ReviewResult(
        summary="Non-admin can delete", findings=[],
    ))

    def plan(code):
        return TestPlan(summary="Auth tests", tests=[ProposedTest(
            name="test_non_admin", purpose="Catch bypass", expected_behavior="False",
        )], pytest_code=code)

    monkeypatch.setattr(workflow, "generate_tests", lambda *args: plan(
        "def test_non_admin():\n    assert can_delete_account({'role':'user'}) is False\n"
    ))
    calls = []

    def revise(*args):
        calls.append(args)
        return plan(
            "from auth import can_delete_account\n\n"
            "def test_non_admin():\n    assert can_delete_account({'role':'user'}) is False\n"
        )

    monkeypatch.setattr(workflow, "revise_tests", revise)
    monkeypatch.setattr(workflow, "run_in_docker", lambda code, sources: {
        "status": "assertion_failures", "details": "Failed: expected True is False"
    })
    result = workflow.build_graph().invoke({
        "repo": str(tmp_path), "diff_file": str(diff_file), "model": "mock",
        "generate_tests": True, "auto_test": True,
    })
    assert result["attempts"] == 2
    assert len(calls) == 1
    assert not result["validation_errors"]
    assert result["sandbox_result"]["status"] == "assertion_failures"
    assert "NOT rewritten" in result["report"]


def test_graph_stops_after_three_attempts(monkeypatch, tmp_path):
    import agent.workflow as workflow
    from agent.models import ReviewResult, TestPlan

    diff_file = tmp_path / "sample.diff"
    diff_file.write_text("+++ b/auth.py\n+return bool(user)\n", encoding="utf-8")
    (tmp_path / "auth.py").write_text(
        "def can_delete_account(user):\n    return bool(user)\n", encoding="utf-8"
    )
    bad = TestPlan(summary="Bad tests", tests=[], pytest_code=(
        "def test_missing():\n    assert can_delete_account({'role':'user'}) is False\n"
    ))
    monkeypatch.setattr(workflow, "review_diff", lambda *_: ReviewResult(summary="Bug", findings=[]))
    monkeypatch.setattr(workflow, "generate_tests", lambda *args: bad)
    monkeypatch.setattr(workflow, "revise_tests", lambda *args: bad)
    result = workflow.build_graph().invoke({
        "repo": str(tmp_path), "diff_file": str(diff_file), "model": "mock",
        "generate_tests": True, "auto_test": False,
    })
    assert result["attempts"] == 3
    assert result["validation_errors"]
    assert "Static checks: FAILED" in result["report"]
