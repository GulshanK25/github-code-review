"""Tests for explicit, diff-anchored behavior checks (no Docker/LLM)."""

import json
from pathlib import Path

import pytest

from agent import behavior_integration as bi


OLD = "def can_delete_account(user):\n    return user.get('role') == 'admin'\n"
NEW = "def can_delete_account(user):\n    return bool(user)\n"
DIFF = ("diff --git a/auth.py b/auth.py\n"
        "--- a/auth.py\n+++ b/auth.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def can_delete_account(user):\n"
        "-    return user.get('role') == 'admin'\n"
        "+    return bool(user)\n")


def case():
    return {
        "name": "auth_case", "filename": "auth.py", "function": "can_delete_account",
        "old_code": OLD, "new_code": NEW, "expected": "bug",
        "probes": [{"args": [{"role": "user"}]}],
    }


def write_cases(path, cases=None):
    path.write_text(json.dumps(cases if cases is not None else [case()]), encoding="utf-8")
    return str(path)


def test_strict_match_against_diff_and_complete_source():
    matched, reason, lines = bi.match_behavior_case(
        case(), DIFF, [{"path": "auth.py", "content": NEW}],
    )
    assert matched is True
    assert "complete source" in reason
    assert lines == {2}


def test_mismatched_diff_cannot_execute(tmp_path, monkeypatch):
    path = write_cases(tmp_path / "cases.json")
    monkeypatch.setattr(bi, "compare_in_docker", lambda _: pytest.fail("Cannot run unmatched"))
    rows = bi.run_review_behavior_cases(path, DIFF.replace("bool(user)", "False"),
        [{"path": "auth.py", "content": NEW}], [], execute=True)
    assert rows[0]["status"] == "skipped_unmatched"


def test_missing_source_skips(tmp_path, monkeypatch):
    path = write_cases(tmp_path / "cases.json")
    monkeypatch.setattr(bi, "compare_in_docker", lambda _: pytest.fail("Cannot run without snapshot"))
    rows = bi.run_review_behavior_cases(path, DIFF, [], [], execute=True)
    assert rows[0]["status"] == "skipped_unmatched"
    assert "source" in rows[0]["details"]


def test_different_source_skips(tmp_path, monkeypatch):
    path = write_cases(tmp_path / "cases.json")
    monkeypatch.setattr(bi, "compare_in_docker", lambda _: pytest.fail("Cannot run mismatched"))
    rows = bi.run_review_behavior_cases(path, DIFF, [{"path": "auth.py", "content": "tampered"}], [], execute=True)
    assert rows[0]["status"] == "skipped_unmatched"


def test_execution_requires_explicit_approval(tmp_path, monkeypatch):
    path = write_cases(tmp_path / "cases.json")
    monkeypatch.setattr(bi, "compare_in_docker", lambda _: pytest.fail("Not approved"))
    rows = bi.run_review_behavior_cases(path, DIFF, [{"path": "auth.py", "content": NEW}], [], execute=False)
    assert rows[0]["status"] == "not_run"


def test_matched_case_calls_docker_only_when_approved(tmp_path, monkeypatch):
    path = write_cases(tmp_path / "cases.json")
    calls = []
    def fake_compare(item):
        calls.append(item)
        return {"status": "completed", "observation": "difference_observed",
                "differences": 1, "probes": [{"probe": 1, "before": False, "after": True}]}
    monkeypatch.setattr(bi, "compare_in_docker", fake_compare)
    findings = [{"file": "auth.py", "line": 2, "line_side": "new"}]
    rows = bi.run_review_behavior_cases(path, DIFF, [{"path": "auth.py", "content": NEW}], findings, execute=True)
    assert len(calls) == 1
    assert rows[0]["differences"] == 1
    assert rows[0]["related_findings"] == ["auth.py:2"]
    assert "False" not in bi.format_behavior_observations(rows)


def test_bad_filename_rejected_before_docker(tmp_path):
    invalid = case()
    invalid["filename"] = "../../auth.py"
    with pytest.raises(ValueError, match="Unsafe Python filename"):
        bi.load_review_cases(write_cases(tmp_path / "cases.json", [invalid]))


def test_cases_limited(tmp_path):
    with pytest.raises(ValueError, match="1 to 12"):
        bi.load_review_cases(write_cases(tmp_path / "cases.json", []))
    data = []
    for n in range(13):
        item = case()
        item["name"] = f"auth_{n}"
        data.append(item)
    with pytest.raises(ValueError, match="1 to 12"):
        bi.load_review_cases(write_cases(tmp_path / "cases.json", data))


def test_duplicate_cases_rejected(tmp_path):
    with pytest.raises(ValueError, match="Duplicate"):
        bi.load_review_cases(write_cases(tmp_path / "cases.json", [case(), case()]))


def test_real_demo_files_are_anchored():
    root = Path(__file__).resolve().parents[1] / "examples" / "behavior_review"
    demo = bi.load_review_cases(str(root / "cases.json"))[0]
    matched, _, lines = bi.match_behavior_case(
        demo, (root / "auth.diff").read_text(encoding="utf-8"),
        [{"path": "auth.py", "content": (root / "auth.py").read_text(encoding="utf-8")}],
    )
    assert matched
    assert lines == {4}


def test_report_is_observational():
    row = {"case": "x", "file": "auth.py", "function": "f", "status": "completed",
           "observation": "no_difference_observed", "probes_run": 2,
           "differences": 0, "details": "", "related_findings": []}
    report = bi.format_behavior_observations([row])
    assert "not proof" in report
    assert "no_difference_observed" in report
