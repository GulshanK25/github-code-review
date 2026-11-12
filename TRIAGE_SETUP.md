# Milestone 5: preserve disputed review findings

This incremental update retains the evidence-only reviewer and the optional
second-pass verifier. It does **not** change the verifier's LLM prompt or claim
to correct its decisions. Instead, it makes potentially real bugs visible to
humans while keeping reported precision/recall conservative.

## Install (PowerShell)

From your existing project checkout, preferably a feature branch:

```powershell
# First ensure local work is committed or backed up; extraction overwrites named files.
Expand-Archive -Path "$HOME\Downloads\ai-code-review-m5-triage-update.zip" -DestinationPath . -Force
python -m pytest -q
```

The update replaces only `agent/workflow.py` and `benchmarks/evaluate.py` and
adds `tests/test_triage_visibility.py` and this setup document. Existing
workflow and benchmark tests are retained.

## Verify the new reviewer report

```powershell
python main.py --diff-file examples\sample.diff --repo examples\benchmark_auth --model qwen2.5-coder:7b --review-mode evidence --verify-findings --output review_triage.md
```

With second-pass verification, the report now shows three mutually exclusive
categories for evidence-backed candidates:

- **Accepted findings**: the verifier says supported. These appear in the
  normal Findings section, but are still AI suggestions, not proven defects.
- **Disputed findings**: the verifier says uncertain, including verdicts that
  failed the consistency check. These appear in a separately labeled manual
  review queue with code evidence, issue, suggestion, and the reason.
- **Rejected candidates**: the verifier says rejected. They remain visible in
  an audit-trail section and are not automatically considered safe.

If the verifier fails, evidence-matched findings remain visible and a clear
failure reason is reported, as before.

## Benchmark

```powershell
python -m benchmarks.evaluate --model qwen2.5-coder:7b --verify-findings --output benchmarks/results/triage.json
```

The usual `tp`, `fp`, `fn`, `tn`, precision and recall are unchanged in meaning:
**only accepted findings count as detection**. Additional metrics show:

- `initial_evidence_stage`: detection *before* the optional verifier.
- `accepted_or_uncertain_stage`: coverage of findings that either passed the
  verifier or remain in the manual review queue.
- `uncertain_candidates` and `rejected_candidates` audit counts.

A safe case with an uncertain finding counts as a false alarm for **triage**.
Triage coverage must never be labeled as confirmed recall or precision.

The benchmark consists of only eight hand-labeled cases. Neither the LLM nor
this benchmark can independently prove the real-world correctness of a finding.

## Testing note

The source snapshot was checked with an offline harness (mocked LangGraph and
Ollama entry points) and all 94 collected tests passed. The developer's actual
Windows environment has additional tests and real dependencies, so verify the
full suite there. Live Qwen behavior has not been checked in this environment.
