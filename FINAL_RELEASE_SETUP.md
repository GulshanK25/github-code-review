# Final integration update (Milestone 5 close-out + Milestone 6 preparation)

This update connects the **existing** Docker behavior comparator to the main LangGraph review as an **explicit opt-in**, and includes CI, release docs, an honest current README, one safe demo, and regression tests. It does not enable Docker execution in ordinary review mode or auto-execute code from GitHub PRs.

## Apply the ZIP

From `code-review` in PowerShell, on `feature/behavioral-verification`:

```powershell
Expand-Archive -Path "$HOME\Downloads\ai-code-review-final-release-update.zip" -DestinationPath . -Force
python -m pytest -q
```

The ZIP includes updated `main.py`, `agent/workflow.py`, `README.md`, and new files. It **also includes the standalone behavioral comparator files** so it is safe to apply to a branch freshly created from the merged Milestone 5 `main`. Extraction overwrites the named files: commit or back up any local edits before extracting.

Do not overwrite your existing `.gitignore`. Append any missing patterns from `GITIGNORE_ADDITIONS.txt`, for example in PowerShell:

```powershell
Get-Content GITIGNORE_ADDITIONS.txt | Add-Content .gitignore
```

## Local demo

```powershell
docker version
docker build -f Dockerfile.test-runner -t ai-code-review-pytest:local .
python main.py --diff-file examples\behavior_review\auth.diff --repo examples\behavior_review --model qwen2.5-coder:7b --review-mode evidence --behavior-cases examples\behavior_review\cases.json --execute-behavior-in-docker --output review_behavior_demo.md
```

The sample intentionally changes the admin role check to `bool(user)`. The approved Docker probes should show differences for regular-user and guest cases. Model findings may vary; behavior observations never alter accepted finding status.

## Release

Follow `docs/RELEASE_CHECKLIST.md`. The GitHub Actions workflow uses the repository's unit tests only, with no model, Docker, or secrets required. Do not commit local reports, generated tests, or benchmark results.

The CLI exits with status 2 if any approved behavioral check was skipped or could not complete. The report is still saved with the reason.

The update was checked with 142 passing offline-harness tests, which used substitutes for the missing LangGraph/Ollama packages. Your installed dependencies, Docker runtime, and GitHub Actions are the final integration tests. Your total test count may be higher because of files already present in your branch.
