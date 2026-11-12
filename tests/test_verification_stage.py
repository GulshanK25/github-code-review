"""Regression tests for optional independent review verification. No model calls."""
import pytest

from agent.models import (
    Finding, ReviewResult, VerificationResult, VerificationVerdict,
)
from agent.review_quality import validate_review_evidence
import agent.workflow as workflow
import agent.llm as llm

DIFF = '''diff --git a/orders.py b/orders.py
--- a/orders.py
+++ b/orders.py
@@ -1,3 +1,3 @@
 def line_total(price, quantity):
     """Compute total for numeric unit price and quantity."""
-    return price * quantity
+    return quantity * price
'''


def candidate():
    return Finding(
        evidence='    return quantity * price', line_side='new',
        file='orders.py', line=3, severity='high',
        issue='Swapping numeric multiplication produces an incorrect order total.',
        suggestion='Restore price * quantity to avoid a calculation regression.',
    )


def setup_case(tmp_path):
    (tmp_path / 'orders.py').write_text(
        'def line_total(price, quantity):\n'
        '    """Compute total for numeric unit price and quantity."""\n'
        '    return quantity * price\n', encoding='utf-8',
    )
    diff_file = tmp_path / 'sample.diff'
    diff_file.write_text(DIFF, encoding='utf-8')
    return diff_file


def test_verifier_rejects_an_evidence_matched_false_positive(tmp_path, monkeypatch):
    diff_file = setup_case(tmp_path)
    monkeypatch.setattr(workflow, 'review_diff_grounded', lambda *_:
        ReviewResult(summary='Maybe a regression', findings=[candidate()]))
    calls = []

    def verifier(diff, model, sources, review):
        calls.append((diff, model, sources, review))
        return VerificationResult(verdicts=[VerificationVerdict(
            candidate_index=1, decision='rejected',
            reason='Numeric multiplication is commutative for the documented inputs.',
        )])

    monkeypatch.setattr(workflow, 'verify_findings', verifier)
    result = workflow.build_graph().invoke({
        'repo': str(tmp_path), 'diff_file': str(diff_file),
        'model': 'mock', 'review_mode': 'evidence', 'verify_findings': True,
    })
    assert len(calls) == 1
    assert result['findings'] == []
    assert result['review_evidence_count'] == 1
    assert result['review_verification']['rejected'] == 1
    assert any('commutative' in value for value in result['review_held'])
    assert 'Second-pass AI judgments' in result['report']
    assert '1/1' in result['report']


def test_verifier_supported_keeps_finding(tmp_path, monkeypatch):
    diff_file = setup_case(tmp_path)
    monkeypatch.setattr(workflow, 'review_diff_grounded', lambda *_:
        ReviewResult(summary='Issue identified', findings=[candidate()]))
    monkeypatch.setattr(workflow, 'verify_findings', lambda *args:
        VerificationResult(verdicts=[VerificationVerdict(
            candidate_index=1, decision='supported',
            reason='This contrived test confirms the routing keeps supported findings.',
        )]))
    result = workflow.build_graph().invoke({
        'repo': str(tmp_path), 'diff_file': str(diff_file),
        'model': 'mock', 'review_mode': 'evidence', 'verify_findings': True,
    })
    assert len(result['findings']) == 1
    assert result['review_verification']['supported'] == 1


def test_verifier_disabled_does_not_call_model(tmp_path, monkeypatch):
    diff_file = setup_case(tmp_path)
    monkeypatch.setattr(workflow, 'review_diff_grounded', lambda *_:
        ReviewResult(summary='Initial review', findings=[candidate()]))
    monkeypatch.setattr(workflow, 'verify_findings', lambda *args:
        pytest.fail('Verifier must be optional'))
    result = workflow.build_graph().invoke({
        'repo': str(tmp_path), 'diff_file': str(diff_file),
        'model': 'mock', 'review_mode': 'evidence',
    })
    assert len(result['findings']) == 1
    assert 'review_verification' not in result


def test_verifier_failure_explicitly_reported_without_silent_loss(tmp_path, monkeypatch):
    diff_file = setup_case(tmp_path)
    monkeypatch.setattr(workflow, 'review_diff_grounded', lambda *_:
        ReviewResult(summary='Issue candidate', findings=[candidate()]))

    def fails(*args):
        raise RuntimeError('model unavailable')

    monkeypatch.setattr(workflow, 'verify_findings', fails)
    result = workflow.build_graph().invoke({
        'repo': str(tmp_path), 'diff_file': str(diff_file),
        'model': 'mock', 'review_mode': 'evidence', 'verify_findings': True,
    })
    assert len(result['findings']) == 1
    assert 'unavailable' in result['report']
    assert 'model unavailable' in result['report']


def test_duplicate_or_missing_verifier_indices_fail_validation(monkeypatch):
    def fake_structured(*args, **kwargs):
        return '{"verdicts": [{"candidate_index": 2, "decision": "supported", "reason": "This was incorrectly assigned to the second finding."}]}'
    monkeypatch.setattr(llm, '_structured_chat', fake_structured)
    with pytest.raises(RuntimeError, match='incomplete'):
        llm.verify_findings(DIFF, 'mock', [], ReviewResult(summary='test', findings=[candidate()]))


def test_line_recovery_requires_unique_quote_same_file_and_side():
    repeated = '''diff --git a/ratios.py b/ratios.py
--- a/ratios.py
+++ b/ratios.py
@@ -1,2 +1,3 @@
-old
+    if denominator == 1:
+    if denominator == 1:
+other
'''
    finding = Finding(
        file='ratios.py', line=40, line_side='new',
        severity='high', evidence='    if denominator == 1:',
        issue='Zero denominator is no longer guarded and raises ZeroDivisionError.',
        suggestion='Restore the zero denominator guard before dividing.',
    )
    accepted, held = validate_review_evidence(
        ReviewResult(summary='test', findings=[finding]), repeated,
    )
    assert not accepted.findings
    assert 'not an added/removed line' in held[0]


def test_line_recovery_fixes_exact_quote_not_semantics():
    ratio = '''diff --git a/ratios.py b/ratios.py
--- a/ratios.py
+++ b/ratios.py
@@ -1,3 +1,3 @@
 def safe_ratio(numerator, denominator):
-    if denominator == 0:
+    if denominator == 1:
     return numerator / denominator
'''
    finding = Finding(
        file='ratios.py', line=4, line_side='new',
        severity='high', evidence='    if denominator == 1:',
        issue='A zero denominator now reaches division and causes a ZeroDivisionError.',
        suggestion='Restore if denominator == 0 before computing the ratio.',
    )
    corrections = []
    accepted, held = validate_review_evidence(
        ReviewResult(summary='test', findings=[finding]), ratio,
        relocations=corrections,
    )
    assert len(accepted.findings) == 1
    assert accepted.findings[0].line == 2
    assert not held
    assert '4 corrected to 2' in corrections[0]
