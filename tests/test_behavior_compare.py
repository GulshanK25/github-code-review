"""Offline CLI/output tests using injected Docker results."""

import json

import pytest

from benchmarks import behavior_compare


def cases():
    return [
        {"name": "bug", "expected": "bug"},
        {"name": "safe", "expected": "safe"},
    ]


def fake_compare(case):
    diff = 1 if case["expected"] == "bug" else 0
    return {"status": "completed", "differences": diff,
            "probes": [{"before": {"kind": "value", "value": 1},
                        "after": {"kind": "value", "value": 2 if diff else 1}}]}


def test_observation_categories():
    assert behavior_compare.classify_observation(cases()[0], fake_compare(cases()[0])) == "difference_observed"
    assert behavior_compare.classify_observation(cases()[1], fake_compare(cases()[1])) == "safe_probes_unchanged"
    assert behavior_compare.classify_observation(cases()[0], {"status": "not_run"}) == "not_run"
    assert behavior_compare.classify_observation(cases()[0],
        {"status": "completed", "differences": 0}) == "bug_not_demonstrated"
    assert behavior_compare.classify_observation(cases()[1],
        {"status": "completed", "differences": 1}) == "safe_label_needs_review"


def test_run_and_save(tmp_path):
    rows = behavior_compare.run_cases(cases(), comparator=fake_compare)
    out = tmp_path / "observations.json"
    behavior_compare.save_observations(out, tmp_path / "cases.json", rows)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["completed"] == 2
    assert data["summary"]["differences_observed"] == 1
    assert data["summary"]["safe_probes_unchanged"] == 1
    assert "bug,difference" not in out.with_suffix(".csv").read_text(encoding="utf-8")
    assert "safe_probes_unchanged" in out.with_suffix(".csv").read_text(encoding="utf-8")


def test_run_stops_if_docker_missing():
    out = behavior_compare.run_cases(cases(), comparator=lambda _: {"status": "not_run", "details": "no Docker"})
    assert len(out) == 1
    assert out[0]["status"] == "not_run"


def test_cli_requires_explicit_opt_in():
    with pytest.raises(SystemExit):
        behavior_compare.main(["--only", "holdout_safe_demorgan"])
