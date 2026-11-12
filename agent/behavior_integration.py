"""Attach explicitly approved Docker behavior probes to a real review.

Never guesses probes, downloads executable inputs, or automatically executes PR
code. A case must match both the reviewed patch and the complete source
snapshot before any of its Python snippets may be passed to Docker.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path, PurePosixPath

from agent.behavior_sandbox import compare_in_docker, validate_behavior_case
from agent.review_quality import changed_line_index

MAX_CASES = 12
MAX_CASES_FILE_BYTES = 250_000


def load_review_cases(filename: str) -> list[dict]:
    """Read a user-selected JSON array; do not evaluate source on the host."""
    path = Path(filename)
    if not path.is_file():
        raise ValueError(f"Behavior cases file not found: {path}")
    if path.stat().st_size > MAX_CASES_FILE_BYTES:
        raise ValueError("Behavior cases JSON exceeds the size limit")
    try:
        contents = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Behavior cases must be valid UTF-8 JSON") from exc
    if not isinstance(contents, list) or not 1 <= len(contents) <= MAX_CASES:
        raise ValueError(f"Behavior cases must contain 1 to {MAX_CASES} entries")
    seen = set()
    for case in contents:
        validate_behavior_case(case)
        name = case["name"]
        if name in seen:
            raise ValueError(f"Duplicate behavior case: {name}")
        seen.add(name)
        filename = case.get("filename")
        if not isinstance(filename, str) or not filename.endswith(".py"):
            raise ValueError(f"Behavior case {name} needs filename ending .py")
        path_parts = PurePosixPath(filename)
        if (path_parts.is_absolute() or not path_parts.parts
                or any(part in {".", ".."} for part in path_parts.parts)
                or "\\" in filename or ":" in filename
                or len(filename) > 200 or any(ord(ch) < 32 for ch in filename)
                or "`" in filename or "<" in filename or ">" in filename):
            raise ValueError(f"Unsafe Python filename in behavior case {name}")
    return contents


def _case_index(case: dict) -> dict[tuple[str, str, int], str]:
    """Index changed lines from the *supplied* before/after code."""
    path = case["filename"]
    patch = "".join(difflib.unified_diff(
        case["old_code"].splitlines(keepends=True),
        case["new_code"].splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}", n=3,
    ))
    return changed_line_index(f"diff --git a/{path} b/{path}\n" + patch)


def match_behavior_case(case: dict, diff: str, sources: list[dict]) -> tuple[bool, str, set[int]]:
    """Conservatively anchor each probe case to actual review inputs.

    This is a snapshot/patch check, not proof that the supplied probes are
    relevant to a reported defect or that behavior is equivalent.
    """
    case_lines = _case_index(case)
    actual_lines = changed_line_index(diff)
    if not case_lines or not any(side == "new" for _, side, _ in case_lines):
        return False, "case has no added code lines", set()
    if any(actual_lines.get(key) != value for key, value in case_lines.items()):
        return False, "case's changed lines do not exactly match the reviewed diff", set()
    # Require complete source equality, not a similar name or a cropped snippet.
    snapshot = next((source.get("content") for source in sources
                     if source.get("path") == case["filename"]), None)
    if snapshot is None:
        return False, "complete changed-file source is unavailable", set()
    if snapshot.replace("\r\n", "\n").rstrip("\n") != case["new_code"].replace("\r\n", "\n").rstrip("\n"):
        return False, "case's new source does not match the reviewed file snapshot", set()
    lines = {lineno for (file, side, lineno) in case_lines
             if file == case["filename"] and side == "new"}
    return True, "matched changed lines and complete source snapshot", lines


def run_review_behavior_cases(
    cases_file: str, diff: str, sources: list[dict],
    findings: list[dict], *, execute: bool = False,
) -> list[dict]:
    """Safely skip mismatched cases. Docker is only invoked when approved."""
    cases = load_review_cases(cases_file)
    output = []
    for case in cases:
        matches, reason, changed_lines = match_behavior_case(case, diff, sources)
        row = {
            "case": case["name"],
            "file": case["filename"],
            "function": case["function"],
            "status": "not_run",
            "observation": "not_run",
            "details": reason,
            "differences": None,
            "probes_run": 0,
            "related_findings": [
                f"{finding['file']}:{finding['line']}"
                for finding in findings
                if finding.get("file") == case["filename"]
                and finding.get("line_side", "new") == "new"
                and finding.get("line") in changed_lines
            ],
        }
        if not matches:
            row["status"] = "skipped_unmatched"
        elif not execute:
            row["details"] = "execution was not approved"
        else:
            result = compare_in_docker(case)
            row["status"] = result["status"]
            row["observation"] = result.get("observation", "not_run")
            row["details"] = result.get("details", reason)
            row["differences"] = result.get("differences")
            row["probes_run"] = len(result.get("probes", []))
            # Deliberately do NOT serialize probe inputs or outputs into reports.
            # They may include passwords, tokens, or customer data.
        output.append(row)
    return output


def format_behavior_observations(rows: list[dict]) -> str:
    sections = [
        "## Behavioral comparison (Docker, opt-in)", "",
        "Results are observations on explicitly supplied inputs, not proof of a bug ",
        "or equivalence. This step never changes or suppresses AI findings.", "",
    ]
    for row in rows:
        sections += [
            f"### `{row['case']}`: `{row['file']}`", "",
            f"- Execution: **{row['status']}**", 
            f"- Observation: **{row['observation']}**",
            f"- Probes executed: {row['probes_run']}",
        ]
        if row["differences"] is not None:
            sections.append(f"- Different outcomes: {row['differences']}")
        if row["related_findings"]:
            sections.append("- Related accepted review locations: " + ", ".join(
                f"`{location}`" for location in row["related_findings"]
            ))
        if row["details"]:
            # Avoid dumping untrusted exceptions or file contents into the report.
            sections.append(f"- Note: {row['details'][:500].replace(chr(10), ' ')}")
        sections.append("")
    sections += [
        "Matching results are limited to supplied inputs. Different results can be ",
        "intentional. Docker isolation reduces risk but is not a perfect sandbox.", "",
    ]
    return "\n".join(sections)
