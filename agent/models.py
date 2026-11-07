"""Validated response format for the local reviewer model."""

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
