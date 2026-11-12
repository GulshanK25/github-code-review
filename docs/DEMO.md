# Five-minute demonstration walkthrough

This demo uses the intentionally vulnerable `examples/behavior_review/auth.py`. It does not require a real GitHub repository or private data.

## Prepare

```powershell
.\.venv\Scripts\Activate.ps1
ollama list
python -m pytest -q
docker version
docker build -f Dockerfile.test-runner -t ai-code-review-pytest:local .
```

## 1. AI detects the vulnerability

```powershell
python main.py --diff-file examples\behavior_review\auth.diff --repo examples\behavior_review --model qwen2.5-coder:7b --review-mode evidence --output review_demo.md
```

Inspect `review_demo.md`. The model is expected to notice that `return bool(user)` grants permission to a nonempty non-admin user. If not, report that as a real model failure rather than editing the score.

## 2. Opt-in behavior comparison in Docker

```powershell
python main.py --diff-file examples\behavior_review\auth.diff --repo examples\behavior_review --model qwen2.5-coder:7b --review-mode evidence --behavior-cases examples\behavior_review\cases.json --execute-behavior-in-docker --output review_behavior_demo.md
```

In the report's **Behavioral comparison** section, the approved probes should produce at least two changed outcomes (regular user and guest). These are demonstrations of the specified scenarios, not formal verification. If Docker is missing, inspect the `not_run` status and build the runner image.

## 3. Show the alternative GitHub PR input

```powershell
python main.py --pr-url "https://github.com/GulshanK25/github-code-review/pull/1" --model qwen2.5-coder:7b --review-mode evidence --output review_pr_demo.md
```

PR review does not execute code by default and does not post GitHub comments. The actual findings may vary; display what the model genuinely returned.

## 4. Discuss the evaluation candidly

Explain the two stages:

1. Qwen2.5-Coder proposes candidate findings, deterministic Python validates changed-line evidence.
2. Optional Docker probes supply concrete before/after observations; neither matching outputs nor a different output automatically proves correctness or a defect.

Mention the 12-case holdout evaluation: evidence-only 6 TP, 3 FP, 0 FN, 3 TN on each of three runs. The second AI verifier reduced alarms but missed five of six bugs in one run, so it is **experimental** rather than the default.

## 5. Clean up generated artifacts

Keep generated `review_*.md` and `benchmarks/results/` out of commits. Don't include real API tokens, private PR diffs, or production secrets in the recording.
