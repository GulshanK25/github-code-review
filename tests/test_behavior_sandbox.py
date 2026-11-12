"""Behavioral Docker runner contract tests, without executing Docker or source."""

import json
import subprocess
from pathlib import Path

import pytest

from agent.behavior_sandbox import compare_in_docker, validate_behavior_case


def fixture_case():
    return {
        "name": "simple_bug", "expected": "bug", "function": "f",
        "old_code": "def f(x): return x + 1\n",
        "new_code": "def f(x): return x + 2\n",
        "probes": [{"args": [3], "before": 4, "after": 5}],
    }


@pytest.mark.parametrize("change,phrase", [
    ({"function": "x;rm"}, "identifier"),
    ({"name": "../../oops"}, "simple name"),
    ({"old_code": ""}, "old_code"),
    ({"old_code": "def f(x): return x + 2\n"}, "identical"),
    ({"probes": []}, "probes"),
    ({"probes": [{"args": "hello"}]}, "args"),
    ({"probes": [{"kwargs": {"a-b": 5}}]}, "kwargs"),
    ({"expected": "unknown"}, "label"),
])
def test_rejects_bad_cases(change, phrase):
    case = {**fixture_case(), **change}
    with pytest.raises(ValueError, match=phrase):
        validate_behavior_case(case)


def test_rejects_oversize_and_non_json_probes():
    case = fixture_case()
    case["new_code"] = "x" * 12001
    with pytest.raises(ValueError, match="bounded"):
        validate_behavior_case(case)
    case = fixture_case()
    case["probes"][0]["args"] = [float("nan")]
    with pytest.raises(ValueError, match="invalid JSON"):
        validate_behavior_case(case)


def test_no_docker_no_execution(monkeypatch):
    calls = []

    def missing_docker(cmd, **kwargs):
        calls.append(cmd)
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", missing_docker)
    result = compare_in_docker(fixture_case())
    assert result["status"] == "not_run"
    assert len(calls) == 1


def test_no_image_no_execution(monkeypatch):
    calls = []

    def image_missing(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(subprocess, "run", image_missing)
    result = compare_in_docker(fixture_case())
    assert result["status"] == "not_run"
    assert "docker build" in result["details"]
    assert len(calls) == 1


def test_docker_is_restricted_and_reports_observation(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        if cmd[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        assert cmd[:2] == ["docker", "run"]
        for flag, value in (("--network", "none"), ("--memory", "256m"),
                            ("--user", "65534:65534")):
            assert cmd[cmd.index(flag) + 1] == value
        assert "--read-only" in cmd
        assert "--cap-drop" in cmd
        assert "--pull" in cmd and cmd[cmd.index("--pull") + 1] == "never"
        assert cmd[-4:] == ["python", "-I", "-B", "/workspace/behavior_runner.py"]
        mount = cmd[cmd.index("--mount") + 1]
        folder = Path(mount.split("source=", 1)[1].split(",target=", 1)[0])
        sandbox_payload = json.loads((folder / "case.json").read_text(encoding="utf-8"))
        assert "expected" not in sandbox_payload
        assert "before" not in sandbox_payload["probes"][0]
        assert "after" not in sandbox_payload["probes"][0]
        answer = {"results": [{"before": {"kind": "value", "value": 4},
                               "after": {"kind": "value", "value": 5}}]}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(answer), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = compare_in_docker(fixture_case())
    assert len(seen) == 2
    assert result["status"] == "completed"
    assert result["observation"] == "difference_observed"
    assert result["differences"] == 1
    assert result["probes"][0]["before_expected_match"] is True
    assert result["probes"][0]["after_expected_match"] is True


def test_matching_results_are_not_called_equivalent(monkeypatch):
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        output = {"results": [{"before": {"kind": "value", "value": 4},
                               "after": {"kind": "value", "value": 4}}]}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(output), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = compare_in_docker(fixture_case())
    assert result["status"] == "completed"
    assert result["observation"] == "no_difference_observed"
    assert result["same"] == 1
    assert result["probes"][0]["after_expected_match"] is False


def test_exceptions_are_comparable(monkeypatch):
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        data = {"results": [{"before": {"kind": "value", "value": 0},
                             "after": {"kind": "exception", "type": "ZeroDivisionError"}}]}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(data), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = compare_in_docker(fixture_case())
    assert result["differences"] == 1
    assert result["probes"][0]["after"]["type"] == "ZeroDivisionError"


def test_invalid_container_result_fails_closed(monkeypatch):
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        return subprocess.CompletedProcess(cmd, 0, "not json", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert compare_in_docker(fixture_case())["status"] == "environment_error"


def test_timeout_removes_container(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        if cmd[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(cmd, 30)
        if cmd[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = compare_in_docker(fixture_case())
    assert result["status"] == "timeout"
    assert calls[-1][:3] == ["docker", "rm", "-f"]
