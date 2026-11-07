# AI-Powered Code Review and Test Generation Agent

A portfolio project built in stages using Python, LangGraph, local Ollama models, and Git.

**Current status: Milestone 1, local Git diff reviewer.** Test generation, execution,
GitHub pull request integration, and web UI are planned, not implemented yet.

## Architecture (Milestone 1)

```text
Git diff or local .diff file
          |
          v
     [load_changes]
          |
          +-- no changes -------------------+
          |                                  |
          v                                  |
   [review via Ollama]                       |
          |                                  |
          +--------------+-------------------+
                         v
                   [report]
                         |
                   Markdown file
```

A LangGraph `StateGraph` coordinates the steps. The reviewer uses an Ollama model
with a Pydantic-generated JSON schema for findings.

## Requirements

- Python 3.11 or later
- Git
- Ollama installed and running
- An installed local model (default: `llama3:latest`)

## Setup (Windows PowerShell)

Unzip the starter, open its folder in VS Code, and open a terminal there.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama list
```

If your `ollama list` output does not show `llama3:latest`, run:

```powershell
ollama pull llama3
```

Make sure Ollama is running. On Windows it often runs in the background after
launching the Ollama application.

## Try the bundled example

```powershell
.\.venv\Scripts\python.exe main.py --diff-file examples\sample.diff
```

The sample diff contains a deliberate authorization regression. The local model
should identify that converting a role check to `bool(user)` allows non-admin users
with non-empty user dictionaries to pass.

Open `review_report.md` to see the result. Model findings are not guaranteed.

## Review a real repository

After changing a **tracked** Python file in a Git repository that already has at
least one commit:

```powershell
.\.venv\Scripts\python.exe main.py --repo "C:\path\to\other-repo"
```

This reviews staged and unstaged changes in tracked `*.py` paths relative to HEAD.
Untracked files, non-Python files, and already-committed changes are **not**
reviewed by the initial version. Large diffs are refused rather than truncated.

## Run unit tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Unit tests use fake model responses, so they don't need an active Ollama server.

## Planned milestones

1. **Local code review**: parse Git diffs, perform LLM analysis, save Markdown findings.
2. **Test generation**: propose pytest test cases from changed functions and review findings.
3. **Validation**: human-approved tests run in an isolated Docker container, with results fed back to the agent.
4. **GitHub integration**: inspect PR diffs and optionally draft (not auto-publish) reviews.
5. **API and evaluation**: FastAPI frontend/backend, measured defect-detection quality, false positives, and generated test usefulness.

## Safety and limitations

- Diff content is untrusted, and model findings can be wrong.
- Do not feed secrets into any LLM, even a local one, unnecessarily.
- This version does **not** execute generated code or post comments to GitHub.
- Later, automatically generated tests must run only with explicit approval in a
  sandbox with restricted network, filesystem, resources, and credentials.
