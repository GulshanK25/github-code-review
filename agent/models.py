"""Validated response formats used by reviewer and test generator."""

from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    severity: Literal["high", "medium", "low"]
    file: str
    line: int | None = Field(default=None, ge=1)
    issue: str
    suggestion: str


class ReviewResult(BaseModel):
    summary: str
    findings: list[Finding]


class ProposedTest(BaseModel):
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)


class TestPlan(BaseModel):
    summary: str
    tests: list[ProposedTest]
    pytest_code: str = Field(
        min_length=1,
        max_length=20_000
    )