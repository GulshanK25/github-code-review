"""CLI opt-in protection tests; no Ollama or Docker required."""

import sys

import pytest

import main


@pytest.mark.parametrize("flags", [
    ["--behavior-cases", "cases.json"],
    ["--execute-behavior-in-docker"],
    ["--review-mode", "basic", "--behavior-cases", "cases.json", "--execute-behavior-in-docker"],
    ["--diff-file", "examples/sample.diff", "--output", "examples/sample.diff"],
    ["--behavior-cases", "cases.json", "--execute-behavior-in-docker", "--output", "cases.json"],
])
def test_cli_rejects_unsafe_flag_combinations(monkeypatch, flags):
    monkeypatch.setattr(sys, "argv", ["main.py", *flags])
    with pytest.raises(SystemExit) as raised:
        main.main()
    assert raised.value.code == 2


def test_cli_explicit_behavior_flags_are_passed_to_graph(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    states = []

    class FakeGraph:
        def invoke(self, state):
            states.append(state)
            return {"report": "# Demo report\n", "behavior_results": [{"status": "completed"}]}

    monkeypatch.setattr(main, "build_graph", lambda: FakeGraph())
    monkeypatch.setattr(sys, "argv", ["main.py", "--behavior-cases", "cases.json",
                                        "--execute-behavior-in-docker"])
    main.main()
    assert states[0]["behavior_cases"] == "cases.json"
    assert states[0]["execute_behavior_in_docker"] is True
    assert (tmp_path / "review_report.md").is_file()


def test_cli_fails_closed_on_skipped_behavior(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class FakeGraph:
        def invoke(self, state):
            return {"report": "# Skipped behavior\n", "behavior_results": [
                {"status": "skipped_unmatched"}]}

    monkeypatch.setattr(main, "build_graph", lambda: FakeGraph())
    monkeypatch.setattr(sys, "argv", ["main.py", "--behavior-cases", "cases.json",
                                        "--execute-behavior-in-docker"])
    with pytest.raises(SystemExit) as raised:
        main.main()
    assert raised.value.code == 2
    assert (tmp_path / "review_report.md").is_file()
