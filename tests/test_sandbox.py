"""Verify sandbox commands without executing Docker or AI-generated code."""

import subprocess

from agent.sandbox import run_in_docker


def test_missing_sources_not_executed():
    assert run_in_docker("def test_x(): assert True", [])["status"] == "not_run"


def test_docker_is_checked_before_running(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 1, "", "No image")
        raise AssertionError("Should not run a container if image is missing")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_in_docker("def test_x(): assert True", [{"path": "auth.py", "content": "pass"}])
    assert result["status"] == "not_run"
    assert len(calls) == 1


def test_sandbox_constraints_and_assertion_classification(monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "[]", "")
        assert "--network" in command and command[command.index("--network") + 1] == "none"
        assert "--read-only" in command
        assert "--cap-drop" in command
        assert "--memory" in command
        assert "--user" in command
        return subprocess.CompletedProcess(command, 1, "1 failed\nFAILED test_ai_generated.py::test_non_admin - AssertionError", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_in_docker("def test_x(): assert False", [{"path": "auth.py", "content": "pass"}])
    assert result["status"] == "assertion_failures"
    assert len(commands) == 2
