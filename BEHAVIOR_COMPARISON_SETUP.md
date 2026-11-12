# Milestone 5: Docker behavioral comparison (opt-in prototype)

This update adds a standalone **behavioral comparison experiment**. It does **not** change the existing AI code reviewer, LangGraph pipeline, or benchmark precision/recall calculations.

It reads the already checked-in `benchmarks/holdout_cases.json` dataset. Each case contains an old and a new Python function plus explicit JSON test inputs. The harness compares **returned JSON values and exception types** for the same inputs. Old/new code is executed only in a Docker container, never by the Python interpreter in your VS Code terminal.

## Files added

- `agent/behavior_runner.py`: trusted probe executor copied into Docker.
- `agent/behavior_sandbox.py`: validates input, invokes restricted Docker, and parses the output.
- `benchmarks/behavior_compare.py`: command-line batch runner and JSON/CSV output.
- `tests/test_behavior_sandbox.py`: mocked Docker tests (no Docker run).
- `tests/test_behavior_compare.py`: CLI/report tests (no Docker run).

No existing files need to be overwritten.

## Commands (PowerShell, from project root)

Activate `.venv` if needed:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run application tests:

```powershell
python -m pytest -q
```

Start Docker Desktop in Linux-container mode. Verify its daemon is accessible:

```powershell
docker version
```

Build the existing trusted runner image if not already present:

```powershell
docker build -f Dockerfile.test-runner -t ai-code-review-pytest:local .
```

First try **one safe change**:

```powershell
python -m benchmarks.behavior_compare --execute-in-docker --only holdout_safe_demorgan
```

Then check **one known bug**:

```powershell
python -m benchmarks.behavior_compare --execute-in-docker --only holdout_session_expiry_reversal
```

Finally run all 12 cases:

```powershell
python -m benchmarks.behavior_compare --execute-in-docker
```

Expected behavior for the hand-authored probes: all six `bug` cases show at least one observable difference; all six `safe` cases show no difference on their specified inputs. This is a fixture expectation, not a demonstrated runtime result until you run the commands yourself.

Output is written to:

- `benchmarks/results/behavior/comparison.json`
- `benchmarks/results/behavior/comparison.csv`

The results JSON records each probe's before/after return value or exception type, whether a difference was observed, and whether a known expected value was matched. Do not commit generated results or sensitive inputs. Ensure `benchmarks/results/` is ignored in `.gitignore`.

## How to interpret results

- `difference_observed`: an observable behavior difference on at least one supplied input. **Not automatically a bug**, because intentional changes also produce differences.
- `safe_probes_unchanged`: no differences observed on the tested inputs. **Not a proof** of equivalence for all inputs.
- `bug_not_demonstrated`: the supplied probes did not reveal a difference in a labeled buggy case. Investigate the test inputs, exceptions, or execution results.
- `safe_label_needs_review`: a supposedly safe change produced a difference. Inspect the fixture/requirements.
- `not_run` / `environment_error` / `timeout`: no useful behavioral conclusion. Investigate Docker/image/permissions.

This prototype does **not** automatically approve or reject AI findings. It will be integrated with the review report only after the Docker run succeeds on your machine and we agree on a reliable input/approval interface.

## Important limitations and safeguards

1. Running code taken from a PR is risky. The comparator requires `--execute-in-docker` and is **not automatically triggered** by `main.py --pr-url`.
2. Each case executes in a container with no network, a read-only root and workspace mount, a non-root user, dropped capabilities, CPU/memory/process limits, and a 30-second timeout. Docker isolation reduces risk but cannot eliminate container escape risks. Never use production secrets or privileged Docker mounts.
3. Only JSON-representable output values are compared. Some Python objects, filesystem side effects, database changes, and timing-dependent behavior cannot be meaningfully evaluated by this prototype. A Python exception is represented by its type.
4. The runner executes old/new code using isolated Python namespaces but within the same Docker process. Malicious code could interfere with the probe harness; output should be treated as supporting evidence, not an independent security guarantee.
5. The holdout fixtures were designed with explicit test inputs and expected outputs. These probes validate sample behavior, not the truth of an arbitrary AI finding.
