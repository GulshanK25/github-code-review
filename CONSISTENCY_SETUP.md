# Milestone 5: Verifier consistency update

The verifier now requires structured reasoning with concrete before/after behavior
and an explicit `regression_introduced` field. A decision that contradicts that
field is downgraded to `uncertain`. Rejections without a stated refutation
basis are likewise downgraded. These checks do **not** prove correctness or
fix all contradictions in natural-language reasoning.

Copy the extracted `agent` and `tests` files into your existing project root.
From Windows PowerShell, assuming the ZIP is in Downloads:

```powershell
Expand-Archive -Path "$HOME\Downloads\ai-code-review-m5-consistency-update.zip" -DestinationPath . -Force
python -m pytest -q
python -m benchmarks.evaluate --model qwen2.5-coder:7b --verify-findings --output benchmarks/results/verifier_consistency.json
```

Compare with prior `benchmarks/results/evidence_only.json` and
`benchmarks/results/with_verifier.json`. This is a single small stochastic
benchmark, not a generalization claim. Inspect `held_reasons` and
`accepted_details` for decisions. False positives, false negatives, and
uncertainty should be reported separately.

The original evidence-only mode and legacy CLI flags are unchanged. The
second-pass verifier is still opt-in with `--verify-findings`.
