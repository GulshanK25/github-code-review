# Milestone 5: Independent Holdout Evaluation

This addition provides a separate, **hand-authored 12-case** evaluation set (6 buggy changes and 6 intentionally safe changes) for the existing AI Code Review Agent. It uses the current `benchmarks.evaluate` implementation without changing the reviewer or its prompt.

## Installation

Extract the ZIP into your **existing** `code-review` project directory on branch `feature/review-reliability`. The package adds only these four files:

- `benchmarks/holdout_cases.json`
- `benchmarks/holdout_compare.py`
- `tests/test_holdout_dataset.py`
- `tests/test_holdout_compare.py`

**It does not overwrite existing project source or the original eight-case benchmark.**

## Test offline

```powershell
python -m pytest -q
```

The new tests validate the added dataset against the existing case schema, verify known old and new behavior from **trusted, checked-in fixtures**, and test the comparison runner with a fake reviewer. `pytest` doesn't call Ollama or Docker. Do not execute source code from untrusted external PRs using the fixture oracle.

## Run a small smoke test

Check that Ollama is running and the `qwen2.5-coder:7b` model is available:

```powershell
python -m benchmarks.holdout_compare --model qwen2.5-coder:7b --mode evidence --only holdout_session_expiry_reversal --repeats 1
```

## Run the entire holdout comparison

```powershell
python -m benchmarks.holdout_compare --model qwen2.5-coder:7b --mode both --repeats 1
```

For independent repeated runs:

```powershell
python -m benchmarks.holdout_compare --model qwen2.5-coder:7b --mode both --repeats 2
```

Each case makes one AI review call in evidence mode. Verified mode can make additional AI calls for findings, so 12 cases x 2 modes x 2 repeats will generally be slower than the original 8-case benchmark. Start with `--repeats 1`; use 2 for variability analysis if practical. You can also run only one mode via `--mode evidence` or `--mode verified`.

Results are saved to `benchmarks/results/holdout/`:

- `evidence_run_1.json` and `.csv`
- `verified_run_1.json` and `.csv`
- `comparison.json` and `comparison.csv`

Subsequent runs in the same directory will overwrite files with the same names. You can choose another location with `--results-dir benchmarks/results/holdout_2`.

## Interpretation and limitations

- This is a separate *evaluation set*, not the original 8 development examples. It does not establish an external industry benchmark or that the examples are representative of real GitHub pull requests.
- Each buggy case specifies one labeled new line. A correct line location is only a **detection proxy** and does not prove the explanation is factually sound.
- Each safe case has specific input assumptions. Safe classification means no regression **under those assumptions**, not a guarantee for all possible Python objects or data types.
- Precision and recall in the output are **case-level proxies**, not verified finding-level accuracy.
- Verifier and evidence-only runs independently call the initial LLM, so differences combine verification effects with sampling variation. Repeated runs help expose some of that variability but cannot completely isolate it.
- Rejected and uncertain findings remain auditable under the current workflow; uncertain findings do not count as accepted detections.
- To preserve this holdout's value, **do not tune prompts using these 12 cases**. If you decide to tune after seeing results, mark this dataset as development data and create a new holdout before reporting final performance.
- The fixture tests run trusted local Python snippets. They must **never** be used to execute untrusted PR code directly.
