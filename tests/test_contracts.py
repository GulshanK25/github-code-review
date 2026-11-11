"""Behavioral-contract tests. They never invoke Ollama or real Docker."""

import json

import pytest

from agent.contracts import contract_pytest_code, load_behavior_contract


CONTRACT = {
    "module": "auth",
    "function": "can_delete_account",
    "description": "Only admins can delete accounts",
    "test_cases": [
        {"name": "admin", "input": {"role": "admin"}, "expected": True},
        {"name": "user", "input": {"role": "user"}, "expected": False},
        {"name": "empty", "input": {}, "expected": False},
    ],
}


def write_example(tmp_path, contract=None):
    (tmp_path / "auth.py").write_text(
        "def can_delete_account(user):\n    return bool(user)\n", encoding="utf-8"
    )
    (tmp_path / "behavior_contract.json").write_text(
        json.dumps(contract if contract is not None else CONTRACT), encoding="utf-8"
    )
    return [{"path": "auth.py", "content": (tmp_path / "auth.py").read_text()}]


def test_contract_is_discovered_and_validated(tmp_path):
    sources = write_example(tmp_path)
    actual = load_behavior_contract(tmp_path, sources=sources)
    assert actual["module"] == "auth"
    assert actual["test_cases"][1]["expected"] is False


def test_missing_implicit_contract_keeps_old_behavior(tmp_path):
    assert load_behavior_contract(tmp_path) is None


def test_contract_rejects_non_boolean_expected(tmp_path):
    invalid = json.loads(json.dumps(CONTRACT))
    invalid["test_cases"][0]["expected"] = "True"
    write_example(tmp_path, invalid)
    with pytest.raises(ValueError, match="Invalid behavior contract"):
        load_behavior_contract(tmp_path)


def test_contract_rejects_mismatched_source(tmp_path):
    sources = write_example(tmp_path)
    invalid = json.loads(json.dumps(CONTRACT))
    invalid["function"] = "other_function"
    (tmp_path / "behavior_contract.json").write_text(json.dumps(invalid))
    with pytest.raises(ValueError, match="not found"):
        load_behavior_contract(tmp_path, sources=sources)


def test_contract_rejects_path_outside_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    other = tmp_path / "other.json"
    other.write_text(json.dumps(CONTRACT))
    with pytest.raises(ValueError, match="inside --repo"):
        load_behavior_contract(root, str(other))


def test_contract_pytest_module_has_explicit_expected_results():
    code = contract_pytest_code(CONTRACT)
    compile(code, "test_behavior_contract.py", "exec")
    assert "from auth import can_delete_account" in code
    assert "({'role': 'user'}, False)" in code
    assert "({'role': 'admin'}, True)" in code
    assert "test_behavior_contract" in code


def test_workflow_uses_contract_for_generation_and_docker(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    import agent.workflow as workflow
    from agent.models import ReviewResult, TestPlan, ProposedTest

    write_example(tmp_path)
    diff_file = tmp_path / "sample.diff"
    diff_file.write_text("+++ b/auth.py\n+return bool(user)\n", encoding="utf-8")
    observed = {}

    def fake_generate(diff, review, sources, model, contract=None):
        observed["generator_contract"] = contract
        return TestPlan(
            summary="Contract based tests",
            tests=[ProposedTest(name="test_non_admin", purpose="Catch bug", expected_behavior="False")],
            pytest_code=(
                "from auth import can_delete_account\n\n"
                "def test_non_admin():\n"
                "    assert can_delete_account({'role': 'user'}) is False\n"
            ),
        )

    def fake_docker(code, sources, contract_code=None):
        observed["contract_code"] = contract_code
        return {"status": "assertion_failures", "details": "contract and AI regression failed"}

    monkeypatch.setattr(workflow, "review_diff", lambda *_: ReviewResult(summary="Bug", findings=[]))
    monkeypatch.setattr(workflow, "generate_tests", fake_generate)
    monkeypatch.setattr(workflow, "run_in_docker", fake_docker)
    result = workflow.build_graph().invoke({
        "repo": str(tmp_path), "diff_file": str(diff_file),
        "model": "mock", "generate_tests": True, "auto_test": True,
    })
    assert observed["generator_contract"]["module"] == "auth"
    assert "test_behavior_contract" in observed["contract_code"]
    assert "Behavioral contract" in result["report"]
    assert result["sandbox_result"]["status"] == "assertion_failures"


def test_contract_is_supplied_to_revision(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    import agent.workflow as workflow
    from agent.models import ReviewResult, TestPlan

    write_example(tmp_path)
    diff_file = tmp_path / "sample.diff"
    diff_file.write_text("+++ b/auth.py\n+return bool(user)\n", encoding="utf-8")
    faulty = TestPlan(summary="Wrong", tests=[], pytest_code=(
        "def test_non_admin():\n    assert can_delete_account({'role':'user'}) is False\n"
    ))
    monkeypatch.setattr(workflow, "review_diff", lambda *_: ReviewResult(summary="Bug", findings=[]))
    monkeypatch.setattr(workflow, "generate_tests", lambda *args, **kwargs: faulty)
    seen = []

    def fake_revise(*args, contract=None):
        seen.append(contract)
        return faulty

    monkeypatch.setattr(workflow, "revise_tests", fake_revise)
    result = workflow.build_graph().invoke({
        "repo": str(tmp_path), "diff_file": str(diff_file),
        "model": "mock", "generate_tests": True, "auto_test": False,
    })
    assert len(seen) == 2
    assert seen[0]["test_cases"][1]["expected"] is False
    assert result["attempts"] == 3
