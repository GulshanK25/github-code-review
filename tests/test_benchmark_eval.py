"""Offline tests for the benchmark runner. No Ollama or Docker needed."""

import json

import pytest

from agent.review_quality import changed_line_index
from benchmarks.evaluate import (
    aggregate, classify_case, load_cases, make_diff, save_results,
)


def case(expected="bug"):
    c = {
        "name": "auth_case", "filename": "auth.py", "expected": expected,
        "old_code": "def gate(user):\n    return user.get('role') == 'admin'\n",
        "new_code": "def gate(user):\n    return bool(user)\n",
    }
    if expected == "bug":
        c["bug_line"] = 2
    return c


def test_generated_diff_indexes_added_and_removed_lines():
    diff = make_diff(case())
    lines = changed_line_index(diff)
    assert lines[("auth.py", "new", 2)] == "    return bool(user)"
    assert lines[("auth.py", "old", 2)] == "    return user.get('role') == 'admin'"


def test_detected_target_is_tp_and_missed_target_is_fn():
    positive = case()
    result = {"findings": [{"file": "auth.py", "line": 2, "line_side": "new"}]}
    assert classify_case(positive, result)["outcome"] == "TP"
    assert classify_case(positive, {"findings": []})["outcome"] == "FN"


def test_safe_change_without_findings_is_tn_with_findings_is_fp():
    safe = case("safe")
    assert classify_case(safe, {"findings": []})["outcome"] == "TN"
    assert classify_case(safe, {"findings": [{"file": "auth.py", "line": 2}]})["outcome"] == "FP"


def test_off_target_findings_are_not_counted_as_bug_detection():
    row = classify_case(case(), {"findings": [{"file": "auth.py", "line": 17}]})
    assert row["outcome"] == "FN"
    assert row["off_target_findings"] == 1


def test_metrics_distinguish_false_alarms_from_missed_bugs():
    rows = [{"outcome": name, "off_target_findings": 0}
            for name in ("TP", "TP", "FP", "FN", "TN")]
    scores = aggregate(rows)
    assert scores["precision_proxy"] == 0.667
    assert scores["recall_proxy"] == 0.667
    assert scores["false_alarm_rate"] == 0.5


def test_no_divide_by_zero_in_empty_subset():
    scores = aggregate([{"outcome": "TN", "off_target_findings": 0}])
    assert scores["recall_proxy"] is None
    assert scores["precision_proxy"] is None


def test_load_cases_checks_expected_bug_line(tmp_path):
    wrong = case()
    wrong["bug_line"] = 25
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([wrong]), encoding="utf-8")
    with pytest.raises(ValueError, match="bug_line"):
        load_cases(p)


def test_load_cases_rejects_duplicate_names_and_invalid_paths(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([case(), case()]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(p)
    wrong = case()
    wrong["filename"] = "../outside.py"
    p.write_text(json.dumps([wrong]), encoding="utf-8")
    with pytest.raises(ValueError, match="filename"):
        load_cases(p)


def test_save_results_writes_json_and_csv(tmp_path):
    output = tmp_path / "results.json"
    rows = [classify_case(case(), {"findings": []})]
    save_results(output, "mock-model", rows)
    assert json.loads(output.read_text(encoding="utf-8"))["metrics"]["fn"] == 1
    assert "auth_case" in output.with_suffix(".csv").read_text(encoding="utf-8")


def test_bundled_cases_have_four_bug_and_four_safe():
    from benchmarks.evaluate import DEFAULT_CASES
    cases = load_cases(DEFAULT_CASES)
    assert len(cases) == 8
    assert sum(c["expected"] == "bug" for c in cases) == 4
    assert sum(c["expected"] == "safe" for c in cases) == 4
