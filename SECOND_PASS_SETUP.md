# Milestone 5: Line recovery and optional independent AI verification

This update builds on the evidence-mode reviewer and the eight-case benchmark.

## Files changed
- `agent/review_quality.py`: if the original line number is wrong, correct it only when the quoted code uniquely matches an added or removed line in the **same file and same diff side**. Ambiguous or invented quotes remain held. Corrections are disclosed.
- `agent/models.py`: structured per-candidate verifier verdicts.
- `agent/llm.py`: separate skeptical Qwen call to check the actual claimed bug, assumptions, and safeguards.
- `agent/workflow.py`: optional verifier node and explicit reporting of supported/rejected/uncertain AI judgments. A verifier failure is shown, never silently treated as success.
- `main.py`: `--verify-findings` flag (evidence mode only).
- `benchmarks/evaluate.py`: optional verification flag, detailed results in JSON/CSV.
- `tests/test_review_quality.py`, `tests/test_verification_stage.py`: compatibility and new tests.

## Apply from PowerShell
After checking `git status`, extract `ai-code-review-milestone5-verifier-update.zip` into the existing `code-review` root. Commit or back up any local changes to those files before replacement.

## Test
```
python -m pytest -q
```
Expected: **87 passed** (80 previous tests, one modified to reflect the new behavior, seven added tests). This count was verified locally using simulated LangGraph and Ollama, not your live Windows environment.

## Run the benchmark twice
```
python -m benchmarks.evaluate --model qwen2.5-coder:7b --output benchmarks/results/evidence_only.json
python -m benchmarks.evaluate --model qwen2.5-coder:7b --verify-findings --output benchmarks/results/with_verifier.json
```
Both runs have new unique-line recovery; only the second invokes the additional LLM verification step. Compare TP, FP, FN, TN and also inspect `held_reasons` and `accepted_details` in the JSON files. Results are non-deterministic. These are case-level proxy metrics, NOT true measured general bug-detection accuracy.

## Verify a GitHub PR (read-only)
```
python main.py --pr-url "https://github.com/GulshanK25/github-code-review/pull/1" --model qwen2.5-coder:7b --review-mode evidence --verify-findings --output review_pr_verified.md
```

## Safety and limitations
- The verification model is fallible; a `supported` verdict is not a proof. A model may also incorrectly reject true bugs.
- If the verifier rejects/marks a finding uncertain, it is held with the model's reason rather than silently discarded.
- If verification fails (e.g. Ollama unavailable or malformed response), the original evidence-matched findings remain visible and the error is reported explicitly.
- Code and diffs remain untrusted input. This step does not execute them. Docker test execution remains separately opt-in.
- Evaluate on unseen cases before making claims about improvement. The eight-case benchmark is tiny.
