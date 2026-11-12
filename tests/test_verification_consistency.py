"""Unit tests for structured before/after verifier consistency.

No Ollama calls or benchmark data labels are used by the validator.
"""
import json

import pytest

import agent.llm as llm
from agent.models import GroundedVerificationResult, ReviewResult
from agent.verification_quality import reconcile_verification


def sample(decision, regression, basis="none"):
    return {
        "verdicts": [{
            "candidate_index": 1,
            "decision": decision,
            "reason": "A concrete evaluation of the old and new code and assumptions.",
            "example_input": "numerator=2, denominator=0",
            "before_behavior": "returns 0",
            "after_behavior": "raises ZeroDivisionError",
            "regression_introduced": regression,
            "rejection_basis": basis,
        }]
    }


def judge(data):
    return reconcile_verification(GroundedVerificationResult.model_validate(data)).verdicts[0]


def test_rejected_but_admits_regression_is_uncertain():
    v = judge(sample("rejected", True, "not_introduced"))
    assert v.decision == "uncertain"
    assert "Inconsistent AI verification" in v.reason
    assert "regression_introduced is true" in v.reason


def test_supported_but_denies_regression_is_uncertain():
    v = judge(sample("supported", False))
    assert v.decision == "uncertain"


def test_rejected_without_refutation_basis_is_uncertain():
    v = judge(sample("rejected", False))
    assert v.decision == "uncertain"


def test_rejected_with_equivalent_behavior_can_remain_rejected():
    data = sample("rejected", False, "equivalent_behavior")
    data["verdicts"][0].update({
        "example_input": "price=3, quantity=4",
        "before_behavior": "returns 12",
        "after_behavior": "returns 12",
    })
    assert judge(data).decision == "rejected"


def test_supported_regression_remains_supported():
    assert judge(sample("supported", True)).decision == "supported"


def test_null_regression_cannot_be_definitive():
    assert judge(sample("rejected", None, "wrong_input_assumption")).decision == "uncertain"


def test_missing_before_after_facts_fail_validation():
    data = sample("supported", True)
    data["verdicts"][0].pop("before_behavior")
    with pytest.raises(Exception):
        GroundedVerificationResult.model_validate(data)


def test_llm_verification_runs_consistency_check(monkeypatch):
    monkeypatch.setattr(llm, "_structured_chat", lambda *args: json.dumps(
        sample("rejected", True, "not_introduced")
    ))
    result = llm.verify_findings("some diff", "mock", [], ReviewResult(
        summary="Test", findings=[{
            "file": "ratios.py", "line": 3, "line_side": "new",
            "evidence": "    if denominator == 1:", "severity": "high",
            "issue": "The changed guard allows zero denominator to reach division.",
            "suggestion": "Restore zero guard.",
        }],
    ))
    assert result.verdicts[0].decision == "uncertain"
