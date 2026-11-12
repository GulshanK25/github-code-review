"""Offline checks for our hand-authored holdout labels. No Ollama or Docker.

IMPORTANT: Probes execute ONLY the trusted Python examples checked into
benchmarks/holdout_cases.json. Do not load or execute untrusted PR code here.
"""

import copy
from pathlib import Path

from benchmarks.evaluate import DEFAULT_CASES, load_cases, make_diff
from benchmarks.holdout_compare import HOLDOUT_CASES


def _call(source, function, args):
    local = {}
    # The fixed, repository-controlled holdout fixtures contain only pure
    # standard-library functions; never point this oracle at external code.
    exec(compile(source, "<trusted-holdout>", "exec"), local)
    return local[function](*copy.deepcopy(args))


def test_holdout_distinct_from_development_benchmark():
    holdout = load_cases(HOLDOUT_CASES)
    development = load_cases(DEFAULT_CASES)
    assert len(holdout) == 12
    assert {c["name"] for c in holdout}.isdisjoint({c["name"] for c in development})
    assert sum(c["expected"] == "bug" for c in holdout) == 6
    assert sum(c["expected"] == "safe" for c in holdout) == 6
    assert len({c["filename"] for c in holdout}) == 12


def test_every_case_has_two_behavior_probes_and_valid_diff():
    for case in load_cases(HOLDOUT_CASES):
        assert case.get("function")
        assert len(case.get("probes", [])) >= 2
        assert "diff --git" in make_diff(case)


def test_gold_labels_match_executable_behavior():
    """Check the examples actually differ for bugs and agree for safe cases."""
    for case in load_cases(HOLDOUT_CASES):
        observed_regression = False
        for probe in case["probes"]:
            old = _call(case["old_code"], case["function"], probe["args"])
            new = _call(case["new_code"], case["function"], probe["args"])
            assert old == probe["before"], (case["name"], "old", old, probe)
            assert new == probe["after"], (case["name"], "new", new, probe)
            observed_regression |= old != new
            if case["expected"] == "safe":
                assert old == new, (case["name"], probe)
        assert observed_regression == (case["expected"] == "bug"), case["name"]
