"""Evidence validation regression tests, no Ollama/GitHub requests."""

from agent.models import Finding, ReviewResult
from agent.review_quality import changed_line_index, validate_review_evidence

DIFF = '''diff --git a/auth.py b/auth.py
--- a/auth.py
+++ b/auth.py
@@ -1,2 +1,2 @@
 def can_delete_account(user):
-    return user.get("role") == "admin"
+    return bool(user)
diff --git a/more.py b/more.py
--- a/more.py
+++ b/more.py
@@ -7,2 +7,2 @@
 def check():
-    return False
+    return True
'''


def finding(**overrides):
    base = dict(
        severity="high", file="auth.py", line=2,
        evidence="    return bool(user)", line_side="new",
        issue="Any regular user can delete an account, because their dictionary is nonempty.",
        suggestion="Check user.get('role') == 'admin' instead of dictionary truthiness.",
    )
    base.update(overrides)
    return Finding(**base)


def test_diff_index_has_precise_changed_line_numbers():
    index = changed_line_index(DIFF)
    assert index[("auth.py", "new", 2)] == "    return bool(user)"
    assert index[("auth.py", "old", 2)] == '    return user.get("role") == "admin"'
    assert index[("more.py", "new", 8)] == "    return True"
    assert ("auth.py", "new", 1) not in index


def test_valid_evidence_keeps_finding():
    result, held = validate_review_evidence(ReviewResult(summary="bug", findings=[finding()]), DIFF)
    assert len(result.findings) == 1
    assert held == []


def test_old_line_evidence_for_removed_guard():
    removed = finding(
        line_side="old", evidence='    return user.get("role") == "admin"',
        issue="The administrator role guard was removed, allowing non-admin access to deletion.",
    )
    result, held = validate_review_evidence(ReviewResult(summary="bug", findings=[removed]), DIFF)
    assert len(result.findings) == 1 and not held


def test_generic_claim_is_not_reported_as_finding():
    generic = finding(issue="Potential security risk")
    result, held = validate_review_evidence(ReviewResult(summary="risk", findings=[generic]), DIFF)
    assert not result.findings
    assert "generic" in held[0]


def test_unique_exact_quote_recovers_wrong_line_but_invented_quote_is_held():
    bad_location = finding(line=99)
    bad_quote = finding(evidence="    return True")
    corrections = []
    result, held = validate_review_evidence(
        ReviewResult(summary="bad", findings=[bad_location, bad_quote]),
        DIFF, relocations=corrections,
    )
    assert len(result.findings) == 1
    assert result.findings[0].line == 2
    assert len(corrections) == 1
    assert "99 corrected to 2" in corrections[0]
    assert len(held) == 1
    assert "does not match" in held[0]


def test_missing_quote_and_duplicate_are_held():
    result, held = validate_review_evidence(
        ReviewResult(summary="bad", findings=[finding(), finding(), finding(evidence=None)]), DIFF
    )
    assert len(result.findings) == 1
    assert len(held) == 2
    assert "duplicate" in held[0]
    assert "missing" in held[1]


def test_double_plus_line_in_diff_is_valid_change():
    special = '''diff --git a/c.py b/c.py
--- a/c.py
+++ b/c.py
@@ -1 +1 @@
-old
+++ not a header
'''
    assert changed_line_index(special)[("c.py", "new", 1)] == "++ not a header"
