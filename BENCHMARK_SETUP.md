# Milestone 5: Repeatable code review benchmark

This update only adds files. It does not overwrite `main.py`, `workflow.py`, or your existing tests.

## Files

- `benchmarks/cases.json`: 8 hand-labeled, compact Python diffs (4 real regressions, 4 behavior-preserving changes). Each case includes old/new source and an expected label. Positive cases record a changed target line.
- `benchmarks/evaluate.py`: runs each case through the existing LangGraph evidence-based reviewer and summarizes the findings.
- `benchmarks/__init__.py`: Python package marker.
- `tests/test_benchmark_eval.py`: 10 offline tests for dataset/diff construction and metrics.

## Commands from project root, inside .venv

```powershell
python -m pytest -q
python -m benchmarks.evaluate --model qwen2.5-coder:7b --only auth_role_bypass
python -m benchmarks.evaluate --model qwen2.5-coder:7b
```

Outputs are saved to `benchmarks/results/latest.json` and `benchmarks/results/latest.csv`.
Add `benchmarks/results/` to `.gitignore` if you don't want to commit local run results.

## How to interpret

- TP: a known buggy case had an accepted finding at the labeled changed line.
- FN: a known buggy case had no accepted finding at that line.
- FP: a labeled safe case received any accepted finding.
- TN: a labeled safe case received no accepted finding.

Precision and recall are *case-level localization proxies*, not verified issue-level quality. A matching line number does not prove the issue explanation is correct. Inspect the evidence and issue content manually before using results in a CV or presentation. Outcomes may vary across local model runs.

No Docker, generated test execution, or GitHub access is required by this benchmark. Benchmark snippets are supplied as untrusted text context only and are not executed by the runner.
