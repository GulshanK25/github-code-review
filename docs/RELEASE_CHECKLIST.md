# Portfolio release checklist

## Before committing

- [ ] Confirm you're on a new branch, such as `feature/behavioral-verification`, based on up-to-date `main`.
- [ ] Check `.gitignore` contains `.venv/`, `generated_tests/`, `benchmarks/results/`, and local review reports.
- [ ] Run `python -m pytest -q` and inspect any failures.
- [ ] If Docker Desktop is available, run the opt-in behavior demo and inspect the report.
- [ ] Verify no keys, customer data, model weights, local caches, or secrets are staged.
- [ ] Review `git diff --cached` before committing.

## Create a pull request

```powershell
git status -sb
git add .gitignore main.py README.md FINAL_RELEASE_SETUP.md BEHAVIOR_COMPARISON_SETUP.md GITIGNORE_ADDITIONS.txt
git add agent/workflow.py agent/behavior_integration.py agent/behavior_sandbox.py agent/behavior_runner.py
git add benchmarks/behavior_compare.py tests/test_behavior_integration.py tests/test_behavior_workflow_integration.py tests/test_behavior_cli.py tests/test_behavior_sandbox.py tests/test_behavior_compare.py
git add examples/behavior_review/ .github/workflows/ci.yml docs/
git diff --cached --stat
git commit -m "feat: integrate opt-in Docker behavior verification and release CI"
git push -u origin feature/behavioral-verification
```

Open a PR with base `main` and compare `feature/behavioral-verification`. Check GitHub Actions tests for Python 3.12/3.13. Fix failures before merging. Use **Squash and merge** if that matches the repository's history policy.

## After merging

```powershell
git switch main
git pull origin main
python -m pytest -q
```

Recommended optional finishing touches: add screenshots of your own sample results to a `docs/images/` directory, record a short demo, tag a release, and add a portfolio link. Do not claim the project is production-hardened or that benchmark scores generalize to arbitrary pull requests.
