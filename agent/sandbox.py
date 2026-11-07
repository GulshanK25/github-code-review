"""Run untrusted generated pytest code in a tightly restricted Docker container.

Never runs source code or generated tests with the host Python interpreter.
Only changed source files and the generated test are copied to a temporary
read-only mount. Docker itself must be installed and trusted by the user.
"""

from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import uuid

IMAGE = "ai-code-review-pytest:local"
OUTPUT_LIMIT = 9000


def run_in_docker(code: str, sources: list[dict[str, str]]) -> dict:
    if not sources:
        return {"status": "not_run", "details": "No source files available to execute tests against."}

    # Check Docker and the prebuilt image without fetching anything from the network.
    try:
        check = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            capture_output=True, text=True, timeout=12, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"status": "not_run", "details": "Docker is not available or not responding."}
    if check.returncode != 0:
        return {
            "status": "not_run",
            "details": f"Missing Docker image '{IMAGE}'. Build it first: "
                       f"docker build -f Dockerfile.test-runner -t {IMAGE} .",
        }

    with tempfile.TemporaryDirectory(prefix="ai-review-") as tmp:
        root = Path(tmp).resolve()
        for source in sources:
            rel = PurePosixPath(source["path"])
            if (rel.is_absolute() or not rel.parts or
                    any(part in {".", ".."} for part in rel.parts) or
                    "\\" in source["path"]):
                return {"status": "not_run", "details": "Unsafe source file path rejected."}
            path = root.joinpath(*rel.parts)
            if not path.resolve().is_relative_to(root):
                return {"status": "not_run", "details": "Source path escapes sandbox."}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source["content"], encoding="utf-8")
        (root / "test_ai_generated.py").write_text(code, encoding="utf-8")

        name = "ai-review-" + uuid.uuid4().hex[:12]
        command = [
            "docker", "run", "--rm", "--pull", "never", "--name", name,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "64",
            "--memory", "256m", "--cpus", "1", "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
            "--mount", f"type=bind,source={root},target=/workspace,readonly",
            "--workdir", "/workspace", "-e", "PYTHONPATH=/workspace",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
            IMAGE, "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "test_ai_generated.py",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                timeout=45, check=False,
            )
        except subprocess.TimeoutExpired:
            # Ensure the container cannot continue running after the client timed out.
            subprocess.run(["docker", "rm", "-f", name],
                           capture_output=True, timeout=10, check=False)
            return {"status": "timeout", "details": "Docker tests timed out after 45 seconds."}

        output = (result.stdout + "\n" + result.stderr)[-OUTPUT_LIMIT:]
        if result.returncode == 0:
            status = "passed"
        elif any(word in output for word in (
            "ERROR collecting", "ModuleNotFoundError", "ImportError",
            "NameError", "SyntaxError", "AttributeError", "INTERNALERROR",
        )):
            status = "repair_needed"
        elif "FAILED" in output or "AssertionError" in output or "DID NOT RAISE" in output:
            # A failing assertion may demonstrate the bug under review.
            # DO NOT automatically turn these assertions into passing tests.
            status = "assertion_failures"
        else:
            status = "environment_error"
        return {"status": status, "details": output, "exit_code": result.returncode}
