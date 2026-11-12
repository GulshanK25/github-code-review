"""Validated response formats used by the local reviewer and test generator."""

from typing import Literal
from pydantic import BaseModel, Field


class Finding(BaseModel):
    evidence: str | None = None
    line_side: Literal["new", "old"] = "new"
    severity: Literal["high", "medium", "low"]
    file: str
    line: int | None = Field(default=None, ge=1)
    issue: str
    suggestion: str


class GroundedFinding(Finding):
    """Stricter schema used only for evidence-based review mode."""
    evidence: str = Field(min_length=1)
    line: int = Field(ge=1)


class GroundedReview(BaseModel):
    summary: str
    findings: list[GroundedFinding]


class ReviewResult(BaseModel):
    summary: str
    findings: list[Finding]


class VerificationVerdict(BaseModel):
    """One independent LLM judgment, not proof of correctness."""
    candidate_index: int = Field(ge=1)
    decision: Literal["supported", "rejected", "uncertain"]
    reason: str = Field(min_length=15, max_length=1000)


class VerificationResult(BaseModel):
    verdicts: list[VerificationVerdict]


class GroundedVerificationVerdict(VerificationVerdict):
    """Require explicit before/after behavior for live model judgments.

    A contradictory judgment is held for human review, not treated as proof.
    """
    example_input: str = Field(min_length=1, max_length=500)
    before_behavior: str = Field(min_length=1, max_length=500)
    after_behavior: str = Field(min_length=1, max_length=500)
    regression_introduced: bool | None
    rejection_basis: Literal[
        "equivalent_behavior", "existing_safeguard", "wrong_input_assumption",
        "not_introduced", "none",
    ]


class GroundedVerificationResult(BaseModel):
    verdicts: list[GroundedVerificationVerdict]


class ProposedTest(BaseModel):
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)


class TestPlan(BaseModel):
    summary: str
    tests: list[ProposedTest]
    pytest_code: str = Field(min_length=1, max_length=20_000)
