"""Turn validated reviewer findings into a simple Markdown artifact."""

from agent.models import ReviewResult


def format_review(review: ReviewResult) -> str:
    lines = ["# AI Code Review", "", "## Summary", "", review.summary, ""]
    if not review.findings:
        lines.extend([
            "## Findings", "", "No actionable issues were identified. ",
            "This does not guarantee that the code is correct or secure.", "",
        ])
    else:
        lines.extend(["## Findings", ""])
        for index, finding in enumerate(review.findings, start=1):
            location = f"{finding.file}:{finding.line}" if finding.line else finding.file
            lines.extend([
                f"### {index}. {finding.severity.upper()} | `{location}`",
                "",
                f"**Issue:** {finding.issue}",
                "",
                f"**Suggestion:** {finding.suggestion}",
                "",
            ])
    lines.extend([
        "---", "",
        "*AI suggestions are unverified. Review them before changing code.*", "",
    ])
    return "\n".join(lines)
