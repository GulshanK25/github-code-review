"""Conservative consistency checks for second-pass LLM judgments.

A structured judgment is still fallible. These checks only catch contradictions
between the model's own explicit fields; they do not prove code correctness.
"""

from agent.models import GroundedVerificationResult, VerificationResult


def reconcile_verification(result: GroundedVerificationResult) -> VerificationResult:
    """Downgrade internally inconsistent or unsupported definitive verdicts.

    Never auto-promote an inconsistent rejection to 'supported'. It is
    'uncertain' and remains visible for human investigation.
    """
    checked = []
    for verdict in result.verdicts:
        problem = None
        if verdict.regression_introduced is None and verdict.decision != "uncertain":
            problem = "No definite claim about whether this change introduces a regression"
        elif verdict.decision == "supported" and verdict.regression_introduced is False:
            problem = "Verdict says supported, but regression_introduced is false"
        elif verdict.decision == "rejected" and verdict.regression_introduced is True:
            problem = "Verdict says rejected, but regression_introduced is true"
        elif verdict.decision == "rejected" and verdict.rejection_basis == "none":
            problem = "Rejection does not identify a basis for disproving the finding"
        if problem:
            verdict = verdict.model_copy(update={
                "decision": "uncertain",
                "reason": f"Inconsistent AI verification: {problem}. Original rationale: {verdict.reason}",
            })
        checked.append(verdict)
    return VerificationResult(verdicts=checked)
