"""Deterministic evidence checks for AI-generated code-review findings.

These checks confirm that a quoted line really occurs in the supplied diff.
They DO NOT prove that an alleged bug is real, or that no bugs were missed.
"""

import re

from agent.models import ReviewResult

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# Generic titles previously hallucinated by the model. Avoid overblocking
# substantive findings that happen to discuss security or memory usage.
GENERIC_ISSUE = re.compile(
    r"^(?:potential\s+(?:security\s+)?risk|security\s+(?:risk|issue|vulnerability)|"
    r"large\s+diff\s+handling|missing\s+validation|input\s+validation|"
    r"error\s+handling|code\s+quality|performance\s+issue)\.?$",
    re.IGNORECASE,
)


def changed_line_index(diff: str) -> dict[tuple[str, str, int], str]:
    """Map (repo path, new|old, line number) to exact changed line text.

    For an addition, ``line`` is the new-file line number. For a deletion,
    ``line`` is the old-file line number. Context lines are not indexed.
    """
    result: dict[tuple[str, str, int], str] = {}
    path: str | None = None
    old_line = new_line = 0
    in_hunk = False

    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path = None
            in_hunk = False
            continue
        if raw.startswith("+++ ") and not in_hunk:
            header_path = raw[4:]
            path = header_path[2:] if header_path.startswith("b/") else None
            in_hunk = False
            continue
        match = HUNK_HEADER.match(raw)
        if match:
            old_line, new_line = map(int, match.groups())
            in_hunk = path is not None
            continue
        if not in_hunk:
            continue
        if raw.startswith("+"):
            result[(path, "new", new_line)] = raw[1:]
            new_line += 1
        elif raw.startswith("-"):
            result[(path, "old", old_line)] = raw[1:]
            old_line += 1
        elif raw.startswith(" "):
            old_line += 1
            new_line += 1
        elif raw.startswith("\\ No newline"):
            continue
        else:
            # Stop indexing malformed or unsupported hunks.
            in_hunk = False

    return result


def _normalized_line(line: str) -> str:
    # The prompt asks for exact code, but permit harmless Markdown backticks.
    return line.strip().strip("`").strip()


def validate_review_evidence(
    review: ReviewResult,
    diff: str,
    relocations: list[str] | None = None,
) -> tuple[ReviewResult, list[str]]:
    """Return findings with diff-backed evidence and reasons for held findings."""
    line_index = changed_line_index(diff)
    accepted = []
    held = []
    seen = set()

    for index, finding in enumerate(review.findings, start=1):
        # A model may cite a surrounding context line rather than the changed
        # line it quotes. Correct the location ONLY when the quote uniquely
        # matches a changed line in the SAME file AND the SAME side.
        if finding.evidence and finding.evidence.strip():
            expected_here = line_index.get((finding.file, finding.line_side, finding.line))
            if expected_here is None or _normalized_line(finding.evidence) != _normalized_line(expected_here):
                matches = [
                    lineno for (file, side, lineno), text in line_index.items()
                    if file == finding.file and side == finding.line_side
                    and _normalized_line(text) == _normalized_line(finding.evidence)
                ]
                if len(matches) == 1:
                    original = finding.line
                    finding = finding.model_copy(update={"line": matches[0]})
                    if relocations is not None:
                        relocations.append(
                            f"Candidate {index} ({finding.file}, {finding.line_side}): "
                            f"line {original} corrected to {matches[0]} from exact diff text"
                        )
        location = f"{finding.file}:{finding.line or '?'}"
        reason = None
        if not finding.evidence or not finding.evidence.strip():
            reason = "missing an exact changed-line quote"
        elif finding.line is None:
            reason = "missing a changed-line number"
        elif GENERIC_ISSUE.fullmatch(finding.issue.strip()):
            reason = "generic issue description without a concrete failure scenario"
        elif len(finding.issue.strip()) < 25:
            reason = "issue description is too vague to evaluate"
        elif len(finding.suggestion.strip()) < 12:
            reason = "suggested fix is too vague to evaluate"
        else:
            expected = line_index.get((finding.file, finding.line_side, finding.line))
            if expected is None:
                reason = "line is not an added/removed line in this diff"
            elif _normalized_line(finding.evidence) != _normalized_line(expected):
                reason = "quoted evidence does not match that changed line"

        dedupe = (finding.file, finding.line_side, finding.line, finding.issue.strip().lower())
        if reason is None and dedupe in seen:
            reason = "duplicate finding"
        if reason:
            held.append(f"Candidate {index} ({location}): {reason}")
        else:
            seen.add(dedupe)
            accepted.append(finding)

    return ReviewResult(summary=review.summary, findings=accepted), held
