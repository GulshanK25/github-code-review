# AI-Powered Code Review and Test Generation Agent

A staged portfolio project using **Python, LangGraph, Ollama, Pydantic, and Git**.

**Current status: Milestone 2.** The application reviews Git diffs and optionally
**proposes pytest test cases and Python test code**. It does **not** execute generated
code, fix the source, or post to GitHub. Docker-based safe validation is a later milestone.

## Architecture

```text
Git diff or .diff file
        |
   [load_changes] -- reads matching source files if available
        |
       diff empty? -------------------- yes ----------> [report]
        |
        no
        v
   [review via Ollama] -- Pydantic validates structured findings
        |
   --generate-tests?
      |         |
      no       yes
      |         v
      |    [generate_tests via Ollama] -- Pydantic + syntax checks
      |         |
      +---------+
            |
         [report] ------> review_report.md
            |
            +----------> generated_tests/test_ai_generated.py (if requested)
```

A `StateGraph` coordinates the steps. For test generation, we supply the Git
diff, code review findings, and matching local source files when available.

## Setup (Windows PowerShell)

Requires Python 3.11+, Git, Ollama running, and a local model such as `llama3:latest`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama list
```

If Llama 3 is missing, run `ollama pull llama3`.

## Milestone 1: Review a bundled example

```powershell
.\.venv\Scripts\python.exe main.py --diff-file examples\sample.diff
```

Open `review_report.md`. The bundled diff replaces an administrator check
with `bool(user)`, which incorrectly permits any non-empty user dictionary.

## Milestone 2: Generate pytest proposals

```powershell
.\.venv\Scripts\python.exe main.py --diff-file examples\sample.diff --repo examples\sample_project --generate-tests
```

Open these outputs:

- `review_report.md`: code review plus plain-English test plan.
- `generated_tests/test_ai_generated.py`: AI-proposed Python pytest tests.

`examples/sample_project/auth.py` is a deliberately buggy implementation of
the function in the diff, so the model has real source code for context.
A good test asserts that an ordinary user **cannot** delete an account; such
a regression test would **fail** against the buggy implementation.

For this milestone, **inspect the generated tests but do not run them yet**.
Parsing tests for syntax does not make them safe. The model can also suggest
incorrect imports or inaccurate assertions. Sandboxed testing is Milestone 3.

To generate again, remove or rename the previous generated file, or choose a
new filename:

```powershell
.\.venv\Scripts\python.exe main.py --diff-file examples\sample.diff --repo examples\sample_project --generate-tests --tests-output generated_tests\test_second_attempt.py
```

## Review a real Git repository

After changing a tracked Python file in a Git repository with at least one commit:

```powershell
.\.venv\Scripts\python.exe main.py --repo "C:\path\to\your\repo" --generate-tests
```

Review mode includes tracked Python changes (staged and unstaged) since HEAD.
Untracked and already-committed changes are not included. Files with more than
6,000 characters are not supplied as complete source context; tests for them
may be less reliable. The diff is restricted to 20,000 characters.

## Unit tests (safe, mocked model responses)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests under `tests/` verify our own handwritten application code and use
fake LLM responses. They do **not** execute AI-generated tests and do not need
Ollama running.

## Key files

| File | Responsibility |
|------|----------------|
| `main.py` | CLI arguments, invokes workflow, writes report and optional test file |
| `agent/workflow.py` | LangGraph nodes and conditional routing |
| `agent/git_utils.py` | Loads tracked Python Git diff |
| `agent/source_utils.py` | Reads changed Python files (size and path constraints) |
| `agent/llm.py` | Two Ollama prompts: review and generate tests |
| `agent/models.py` | Pydantic `ReviewResult` and `TestPlan` schemas |
| `agent/test_utils.py` | Syntax-checks generated test code without executing it |
| `agent/report.py` | Markdown review and test-plan formatting |
| `examples/sample.diff` | Deliberate authorization regression |
| `examples/sample_project/auth.py` | Vulnerable example source code |
| `tests/` | Handwritten unit tests for our app |

## Planned milestones

1. **Local code review**: done.
2. **AI pytest test generation**: done as a *proposal*, without execution.
3. **Sandboxed validation**: human approval, Docker isolation, run tests, collect and analyze errors.
4. **GitHub integration**: review PR diffs; draft reviews, never auto-post without approval.
5. **API and evaluation**: FastAPI and quantitative evaluation of defect detection and tests.

## Safety and accuracy limits

- All model output is untrusted. The generated file is **not automatically run**.
- The prompt discourages dangerous operations, but **prompts are not a security boundary**.
- Python syntax validation does not verify imports, behavior, correctness, or safety.
- Test files are written outside the reviewed repo by default and never overwrite
  an existing generated test file.
- Diff content and source files can contain secrets. Review what you send, even
  when the model runs locally.
- A failing regression test may be intentional: it exposes the buggy implementation.

The `pytest.ini` configuration restricts default pytest discovery to the
handwritten `tests/` directory, so `python -m pytest -q` will not accidentally
collect proposed tests from `generated_tests/`. Running a specific generated
file explicitly still bypasses this protection.

## Milestone 2.5: Automatic AI test validation and revision

This update adds a bounded LangGraph feedback loop:

`generate → static checks → [revise up to twice] → Docker pytest (optional) → report`

The static checks detect invalid Python syntax, missing imports for known
changed functions, obvious duplicate test bodies, broad `pytest.raises(Exception)`
assertions, and a short list of disallowed operations. Static checks are **not**
a security boundary and cannot establish logical correctness.

Optional Docker execution isolates the generated test from the host Python
interpreter. The runner copies only the changed source files and generated test
into a temporary workspace, mounts it read-only, disables network access,
drops Linux capabilities, limits memory/CPU/processes, and enforces a timeout.
Docker sandboxing reduces risk, but cannot guarantee zero risk or demonstrate
that generated test expectations are correct. Never expose production secrets
or mount your entire development environment for generated code.

### Local setup on Windows (PowerShell)

Start Docker Desktop and Ollama first. Build the trusted pytest image once:

```powershell
docker build -f Dockerfile.test-runner -t ai-code-review-pytest:local .
```

Generate, revise, and execute proposed tests in Docker:

```powershell
python main.py --diff-file examples\sample.diff --repo examples\sample_project --generate-tests --auto-test --tests-output generated_tests\test_ai_generated_v3.py
```

Use a fresh `--tests-output` filename if that file already exists. Without
`--auto-test`, the agent still performs static validation and AI retries, but
never executes AI-generated code. Without a Docker image or matching source,
the report records `not_run` instead of silently running tests on the host.

### Interpreting the result

- `passed`: all generated tests passed on the changed code. This does not imply
  that the tests are correct or strong.
- `assertion_failures`: tests contain failed assertions, which may be **good**
  evidence that a regression test catches the deliberately buggy code. The
  agent does **not** rewrite these assertions merely to make them pass.
- `repair_needed`: import/name/collection problems were detected; the agent
  feeds the diagnostics to Ollama and retries, up to three total generations.
- `not_run`, `timeout`, `environment_error`: Docker execution was unavailable,
  interrupted, or could not reliably evaluate the tests.

The final Markdown report includes static checks, generation attempt count,
and Docker/pytest output. The application never edits your production source.

Run the handwritten application tests separately:

```powershell
python -m pytest -q
```
