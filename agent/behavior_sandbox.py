"""Explicit, Docker-only behavioral comparison of old/new Python snippets.

Never executes the snippets on the host, and never runs automatically when
reviewing GitHub PRs. Results are observations on supplied test inputs, not a
proof of equivalence or of the presence/absence of a vulnerability.
"""

import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from agent.sandbox import IMAGE

MAX_CODE_CHARS = 12_000
MAX_CASE_BYTES = 70_000
MAX_DOCKER_STDOUT = 100_000
MAX_PROBES = 24
TIMEOUT_SECONDS = 30
_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_CASE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_behavior_case(case: dict) -> None:
    """Validate metadata/size before passing a case to Docker.

    This validation is NOT a Python-code security scanner. Docker isolation is
    mandatory because even a two-line function can run arbitrary code.
    """
    if not isinstance(case, dict):
        raise ValueError("Behavior case must be a JSON object")
    if not isinstance(case.get("name"), str) or not _CASE_NAME.fullmatch(case["name"]):
        raise ValueError("Behavior case needs a simple name")
    if not isinstance(case.get("function"), str) or not _IDENT.fullmatch(case["function"]):
        raise ValueError(f"Case {case['name']} needs a Python function identifier")
    for field in ("old_code", "new_code"):
        value = case.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_CODE_CHARS:
            raise ValueError(f"Case {case['name']} needs bounded {field}")
    if case["old_code"] == case["new_code"]:
        raise ValueError(f"Case {case['name']} contains identical source text")
    probes = case.get("probes")
    if not isinstance(probes, list) or not 1 <= len(probes) <= MAX_PROBES:
        raise ValueError(f"Case {case['name']} needs 1 to {MAX_PROBES} probes")
    for index, probe in enumerate(probes, start=1):
        if not isinstance(probe, dict):
            raise ValueError(f"Case {case['name']} probe {index} must be an object")
        if not isinstance(probe.get("args", []), list):
            raise ValueError(f"Case {case['name']} probe {index} args must be a list")
        if not isinstance(probe.get("kwargs", {}), dict) or not all(
            isinstance(key, str) and _IDENT.fullmatch(key)
            for key in probe.get("kwargs", {})
        ):
            raise ValueError(f"Case {case['name']} probe {index} kwargs must have identifier keys")
    if case.get("expected", "bug") not in {"bug", "safe"}:
        raise ValueError(f"Case {case['name']} has unsupported expected label")
    try:
        encoded = json.dumps(case, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError(f"Case {case['name']} contains invalid JSON data") from exc
    if len(encoded) > MAX_CASE_BYTES:
        raise ValueError(f"Case {case['name']} is too large")


def _error(status: str, message: str) -> dict:
    return {"status": status, "details": message}


def _valid_outcome(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("kind") == "exception":
        return set(value) == {"kind", "type"} and isinstance(value["type"], str)
    if value.get("kind") == "value":
        return set(value) == {"kind", "value"}
    return False


def _validate_response(data: object, count: int) -> list[dict]:
    if (not isinstance(data, dict) or not isinstance(data.get("results"), list)
            or len(data["results"]) != count):
        raise ValueError("Invalid response from sandboxed behavior runner")
    for result in data["results"]:
        if (not isinstance(result, dict) or not _valid_outcome(result.get("before"))
                or not _valid_outcome(result.get("after"))):
            raise ValueError("Malformed before/after probe result")
    return data["results"]


def _matching_expected(observed: dict, probe: dict, key: str, expected_key: str) -> bool | None:
    if expected_key not in probe:
        return None
    return observed[key].get("kind") == "value" and observed[key].get("value") == probe[expected_key]


def compare_in_docker(case: dict) -> dict:
    """Run one explicit case in a resource-limited Linux Docker container."""
    validate_behavior_case(case)
    try:
        inspected = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            capture_output=True, text=True, timeout=12, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return _error("not_run", "Docker is unavailable or not responding")
    if inspected.returncode:
        return _error(
            "not_run", f"Docker image '{IMAGE}' is missing. Build it with: "
            f"docker build -f Dockerfile.test-runner -t {IMAGE} .",
        )

    with tempfile.TemporaryDirectory(prefix="ai-behavior-") as folder:
        root = Path(folder).resolve()
        # Never expose benchmark labels or expected answers to the code under
        # inspection. Expected values are checked only after Docker returns.
        payload = {
            "function": case["function"],
            "old_code": case["old_code"],
            "new_code": case["new_code"],
            "probes": [
                {"args": item.get("args", []), "kwargs": item.get("kwargs", {})}
                for item in case["probes"]
            ],
        }
        payload_path = root / "case.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        trusted_runner = Path(__file__).with_name("behavior_runner.py")
        runner_path = root / "behavior_runner.py"
        runner_path.write_bytes(trusted_runner.read_bytes())
        # tempfile directories are 0700 on POSIX. A non-root Docker user must
        # be able to traverse the read-only mount and read these two files.
        # Do not make the directory listable to other host users.
        root.chmod(0o711)
        payload_path.chmod(0o644)
        runner_path.chmod(0o644)
        name = "ai-behavior-" + uuid.uuid4().hex[:12]
        cmd = [
            "docker", "run", "--rm", "--pull", "never", "--name", name,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "64",
            "--memory", "256m", "--cpus", "1", "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
            "--mount", f"type=bind,source={root},target=/workspace,readonly",
            "--workdir", "/workspace", "-e", "PYTHONDONTWRITEBYTECODE=1",
            IMAGE, "python", "-I", "-B", "/workspace/behavior_runner.py",
        ]
        try:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", name],
                    capture_output=True, timeout=10, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            return _error("timeout", f"Docker behavior check exceeded {TIMEOUT_SECONDS} seconds")
        except OSError as exc:
            return _error("environment_error", f"Unable to start Docker: {type(exc).__name__}")

    if completed.returncode:
        return _error("environment_error", f"Docker behavior runner exited {completed.returncode}: "
                      f"{completed.stderr[-500:]}")
    if len(completed.stdout) > MAX_DOCKER_STDOUT:
        return _error("environment_error", "Docker behavior output exceeded size limit")
    try:
        data = json.loads(completed.stdout)
        raw_rows = _validate_response(data, len(case["probes"]))
    except (ValueError, TypeError, json.JSONDecodeError):
        return _error("environment_error", "Invalid Docker behavior result")

    rows = []
    for index, (original, probe) in enumerate(zip(raw_rows, case["probes"]), start=1):
        before, after = original["before"], original["after"]
        rows.append({
            "probe": index,
            "before": before,
            "after": after,
            "different": before != after,
            "before_expected_match": _matching_expected(original, probe, "before", "before"),
            "after_expected_match": _matching_expected(original, probe, "after", "after"),
        })
    differences = sum(row["different"] for row in rows)
    return {
        "status": "completed", "case": case["name"], "function": case["function"],
        "probes": rows, "differences": differences, "same": len(rows) - differences,
        "observation": "difference_observed" if differences else "no_difference_observed",
    }
