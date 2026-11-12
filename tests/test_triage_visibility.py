"""Regression tests for retaining independent verifier decisions for human review."""

from agent.models import Finding, ReviewResult, VerificationResult, VerificationVerdict
from benchmarks.evaluate import aggregate, classify_case
import agent.workflow as workflow

DIFF = '''diff --git a/auth.py b/auth.py
--- a/auth.py
+++ b/auth.py
@@ -1,3 +1,3 @@
 def can_delete_account(user):
     """Only admins may delete accounts."""
-    return user.get("role") == "admin"
+    return bool(user)
'''


def finding():
    return Finding(
        evidence='    return bool(user)', line_side='new',
        file='auth.py', line=3, severity='high',
        issue='A user with role user can delete an account.',
        suggestion='Restore explicit admin role check.',
    )


def setup_graph(tmp_path, monkeypatch, decision, reason):
    (tmp_path / 'auth.py').write_text(
        'def can_delete_account(user):\n'
        '    """Only admins may delete accounts."""\n'
        '    return bool(user)\n', encoding='utf-8'
    )
    diff_path = tmp_path / 'auth.diff'
    diff_path.write_text(DIFF, encoding='utf-8')
    monkeypatch.setattr(workflow, 'review_diff_grounded', lambda *_: ReviewResult(
        summary='Review found authorization regression', findings=[finding()],
    ))
    monkeypatch.setattr(workflow, 'verify_findings', lambda *args: VerificationResult(
        verdicts=[VerificationVerdict(
            candidate_index=1, decision=decision, reason=reason,
        )],
    ))
    return workflow.build_graph().invoke({
        'repo': str(tmp_path), 'diff_file': str(diff_path),
        'model': 'mock', 'review_mode': 'evidence',
        'verify_findings': True,
    })


def test_uncertain_candidate_is_visible_with_all_details(tmp_path, monkeypatch):
    result = setup_graph(tmp_path, monkeypatch, 'uncertain',
                         'Contradictory reasoning; needs human investigation.')
    assert result['findings'] == []
    assert result['review_evidence_count'] == 1
    assert len(result['review_evidence_findings']) == 1
    assert result['review_verification']['uncertain'] == 1
    assert result['review_verdicts'][0]['finding']['evidence'].strip() == 'return bool(user)'
    assert result['review_verdicts'][0]['decision'] == 'uncertain'
    report = result['report']
    assert 'Disputed findings: manual review required' in report
    assert 'auth.py:3' in report
    assert 'return bool(user)' in report
    assert 'Restore explicit admin role check.' in report
    assert 'Contradictory reasoning' in report
    assert 'not counted as accepted findings' in report


def test_rejected_candidate_stays_in_audit_trail(tmp_path, monkeypatch):
    result = setup_graph(tmp_path, monkeypatch, 'rejected',
                         'Model rejects the candidate (this judgment may be wrong).')
    assert result['findings'] == []
    assert result['review_verification']['rejected'] == 1
    assert 'Findings rejected by the AI verifier (audit trail)' in result['report']
    assert 'Model rejects the candidate' in result['report']
    assert 'Restore explicit admin role check.' in result['report']


def test_supported_candidate_is_not_repeated_as_disputed(tmp_path, monkeypatch):
    result = setup_graph(tmp_path, monkeypatch, 'supported',
                         'Admin role bypass is demonstrated by a normal user input.')
    assert len(result['findings']) == 1
    assert 'Disputed findings: manual review required' not in result['report']
    assert 'Findings rejected by the AI verifier (audit trail)' not in result['report']


def case(expected='bug'):
    value = {'name': 'auth_case', 'filename': 'auth.py', 'expected': expected}
    if expected == 'bug':
        value['bug_line'] = 3
    return value


def test_benchmark_distinguishes_accepted_and_visible_uncertain_bug():
    f = finding().model_dump()
    result = {'findings': [], 'review_evidence_findings': [f],
              'review_verdicts': [{'candidate_index': 1, 'decision': 'uncertain',
                                   'reason': 'Could be real', 'finding': f}],
              'review_held': ['verifier uncertain']}
    row = classify_case(case(), result)
    assert row['outcome'] == 'FN'
    assert row['initial_outcome'] == 'TP'
    assert row['triage_outcome'] == 'TP'
    assert row['uncertain_findings'] == 1
    summary = aggregate([row])
    assert summary['tp'] == 0
    assert summary['recall_proxy'] == 0
    assert summary['initial_evidence_stage']['recall_proxy'] == 1
    assert summary['accepted_or_uncertain_stage']['recall_proxy'] == 1
    assert summary['uncertain_candidates'] == 1


def test_uncertain_safe_change_counts_as_triage_false_alarm():
    f = finding().model_dump()
    result = {'findings': [], 'review_evidence_findings': [f],
              'review_verdicts': [{'candidate_index': 1, 'decision': 'uncertain',
                                   'reason': 'Unknown', 'finding': f}]}
    row = classify_case(case('safe'), result)
    assert row['outcome'] == 'TN'
    assert row['initial_outcome'] == 'FP'
    assert row['triage_outcome'] == 'FP'
    metrics = aggregate([row])
    assert metrics['false_alarm_rate'] == 0
    assert metrics['accepted_or_uncertain_stage']['false_alarm_rate'] == 1


def test_benchmark_tracks_wrong_rejection_as_initial_detection_but_not_triaged():
    f = finding().model_dump()
    row = classify_case(case(), {
        'findings': [], 'review_evidence_findings': [f],
        'review_verdicts': [{'candidate_index': 1, 'decision': 'rejected',
                             'reason': 'False claim', 'finding': f}],
    })
    assert row['outcome'] == 'FN'
    assert row['initial_outcome'] == 'TP'
    assert row['triage_outcome'] == 'FN'
    assert row['rejected_findings'] == 1
    assert aggregate([row])['rejected_candidates'] == 1
