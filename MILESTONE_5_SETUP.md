# Milestone 5, phase 1: Evidence-based code review

This update builds on the existing GitHub PR reviewer. It does not replace GitHub
read-only access, behavioral contracts, AI test generation, or Docker execution.

## New behavior

CLI review now defaults to `--review-mode evidence`. This mode:

1. Fetches small changed Python source files for additional context, even during
   review-only PR runs (up to existing repository size limits).
2. Asks Qwen2.5-Coder to cite an exact added or removed line for each finding.
3. Checks each quoted line against the actual unified diff and its old/new line
   numbering, and holds generic or unsourced findings from the main report.
4. Reports accepted and held candidate counts plus reasons.

This check does not prove correctness. A line may be cited correctly and the
model's interpretation still be wrong. It may also hold valid findings if the
model fails to supply a correct quote, and it may miss defects in unchanged files.
There are no automatic GitHub comments or code modifications.

## Use it in Windows PowerShell

From your active `.venv` and project directory:

```powershell
python -m pytest -q
python main.py --pr-url "https://github.com/GulshanK25/github-code-review/pull/1" --model qwen2.5-coder:7b --review-mode evidence
```

For a baseline comparison with the earlier behavior:

```powershell
python main.py --pr-url "https://github.com/GulshanK25/github-code-review/pull/1" --model qwen2.5-coder:7b --review-mode basic --output review_report_basic.md
```

Review the `Evidence validation` section of the new `review_report.md`.
Don't interpret `0/0` as a security certification: it means the model made no
candidate findings. `0/2` means it suggested two, but neither passed the exact
citation checks.

For local diffs, you can also use:

```powershell
python main.py --diff-file examples\sample.diff --repo examples\sample_project --model qwen2.5-coder:7b --review-mode evidence
```

## Changed files

- `main.py`: adds `--review-mode {evidence,basic}`, with evidence as CLI default.
- `agent/models.py`: backward-compatible evidence fields and strict grounded schema.
- `agent/llm.py`: new grounded review prompt and Ollama request.
- `agent/review_quality.py`: new unified-diff indexing and evidence checks.
- `agent/workflow.py`: new review-validation node plus source context routing.
- `agent/report.py`: displays quoted changed-line evidence.
- `tests/test_review_quality.py`: deterministic filter tests.
- `tests/test_review_quality_workflow.py`: mocked LangGraph routing tests.

## Next phase

After we evaluate a real PR, we can introduce a second verification pass that
checks findings against surrounding code and add a benchmark of known bug fixes.
That will be more informative than just counting how many findings are held.
