"""Offline tests for repeat aggregation. Does not invoke a real model."""

import json

import pytest

from benchmarks.holdout_compare import execute_holdout, save_comparison, summarize_runs


def row(name, expected, outcome):
    return {
        "case": name, "expected": expected, "outcome": outcome,
        "initial_outcome": outcome, "triage_outcome": outcome,
        "off_target_findings": 0,
        "accepted_findings": 1 if outcome in ("TP", "FP") else 0,
        "held_findings": 0,
    }


def test_repeat_metrics_and_instability():
    runs = [
        [row("bug", "bug", "TP"), row("safe", "safe", "TN")],
        [row("bug", "bug", "FN"), row("safe", "safe", "TN")],
    ]
    result = summarize_runs(runs)
    assert result["runs"] == 2
    assert result["unstable_cases"] == ["bug"]
    assert result["metric_summary"]["recall_proxy"]["mean"] == 0.5
    assert result["metric_summary"]["false_alarm_rate"]["mean"] == 0
    assert result["metric_summary"]["precision_proxy"]["mean"] == 1


def test_reject_mismatched_runs():
    with pytest.raises(ValueError, match="same cases"):
        summarize_runs([[row("one", "bug", "TP")], [row("two", "bug", "FN")]])
    with pytest.raises(ValueError, match="non-empty"):
        summarize_runs([])


def test_injectable_benchmark_runner_and_comparison_output(tmp_path):
    called = []

    def fake_run(case, model, graph, verify_findings=False):
        called.append(verify_findings)
        return row(case["name"], case["expected"], "TP" if case["expected"] == "bug" else "TN")

    cases = [{"name": "bug", "expected": "bug"}, {"name": "safe", "expected": "safe"}]
    baseline = execute_holdout(cases, "fake", 2, "evidence", tmp_path, None, run_one=fake_run)
    verified = execute_holdout(cases, "fake", 1, "verified", tmp_path, None, run_one=fake_run)
    assert called == [False, False, False, False, True, True]
    assert (tmp_path / "evidence_run_2.json").exists()
    assert (tmp_path / "verified_run_1.csv").exists()
    output = save_comparison(tmp_path, "fake", tmp_path / "cases.json", {"evidence": baseline, "verified": verified})
    contents = json.loads(output.read_text(encoding="utf-8"))
    assert contents["modes"]["evidence"]["runs"] == 2
    assert "verified" in contents["modes"]
    assert "evidence,1," in output.with_suffix(".csv").read_text(encoding="utf-8")


def test_reject_invalid_repeats(tmp_path):
    with pytest.raises(ValueError, match="repeats"):
        execute_holdout([{"name": "bug"}], "fake", 0, "evidence", tmp_path, None)
