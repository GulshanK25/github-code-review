"""Read GitHub pull-request diffs and Python source without git checkout.

All requests are GETs to api.github.com. No PR code is executed by this module.
GitHub API tokens are read from the environment but never written to reports.
"""

import base64
import binascii
import json
import os
import re
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from agent.git_utils import validate_diff_size
from agent.source_utils import (
    MAX_SOURCE_CHARS_PER_FILE,
    MAX_SOURCE_FILES,
    MAX_TOTAL_SOURCE_CHARS,
)

API_ROOT = "https://api.github.com"
MAX_PR_FILES = 200
MAX_JSON_BYTES = 2_000_000
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_SHA = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    """Accept only github.com/owner/repo/pull/<positive integer> URLs."""
    try:
        parsed = urlsplit(pr_url)
    except ValueError as exc:
        raise ValueError("Invalid GitHub pull request URL") from exc
    parts = parsed.path.strip("/").split("/")
    if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or len(parts) != 4 or parts[2] != "pull"
            or not _IDENTIFIER.fullmatch(parts[0])
            or not _IDENTIFIER.fullmatch(parts[1])
            or not parts[3].isdigit() or int(parts[3]) < 1):
        raise ValueError("Use a GitHub PR URL like https://github.com/OWNER/REPO/pull/123")
    return parts[0], parts[1], int(parts[3])


def _get_json(api_path: str):
    """Request one known GitHub API path, limiting downloaded response size."""
    if not api_path.startswith("/repos/"):
        raise ValueError("Unexpected GitHub API path")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-code-review-agent",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(API_ROOT + api_path, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read(MAX_JSON_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(
                "GitHub API denied the request (authentication, permissions or rate limit). "
                "For a private repository set GITHUB_TOKEN with read-only PR and Contents access."
            ) from exc
        if exc.code == 404:
            raise RuntimeError("GitHub PR or file not found, or your token lacks access") from exc
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Unable to reach the GitHub API") from exc
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("GitHub API response is too large to review safely")
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("GitHub API returned an invalid JSON response") from exc


def _safe_repo_path(path: str) -> bool:
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    parsed = PurePosixPath(path)
    return (not parsed.is_absolute() and bool(parsed.parts)
            and all(part not in {".", ".."} for part in parsed.parts))


def _safe_python_path(path: str) -> bool:
    return _safe_repo_path(path) and path.endswith(".py")


def _load_blob(owner: str, repo: str, blob_sha: str) -> str | None:
    """Load a small text blob. Oversized/binary files cannot become source context."""
    if not isinstance(blob_sha, str) or not _SHA.fullmatch(blob_sha):
        return None
    data = _get_json(f"/repos/{owner}/{repo}/git/blobs/{blob_sha}")
    if not isinstance(data, dict) or data.get("encoding") != "base64":
        return None
    if not isinstance(data.get("size"), int) or data["size"] > MAX_SOURCE_CHARS_PER_FILE:
        return None
    try:
        raw = base64.b64decode(data["content"], validate=False)
        text = raw.decode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, binascii.Error):
        return None
    if len(text) > MAX_SOURCE_CHARS_PER_FILE or "\x00" in text:
        return None
    return text


def fetch_pull_request(pr_url: str, include_sources: bool = False) -> dict:
    """Return a validated Python diff, optional PR-head files, and PR metadata.

    Refuses to review truncated patches rather than silently missing changes.
    PR-head source files are treated as untrusted and may only run in Docker.
    """
    owner, repo, number = parse_pr_url(pr_url)
    canonical = f"https://github.com/{owner}/{repo}/pull/{number}"
    pr = _get_json(f"/repos/{owner}/{repo}/pulls/{number}")
    if not isinstance(pr, dict) or not isinstance(pr.get("title"), str):
        raise RuntimeError("Malformed GitHub pull request metadata")
    head_repo = (pr.get("head") or {}).get("repo") or {}
    head_owner = (head_repo.get("owner") or {}).get("login")
    head_name = head_repo.get("name")
    if not isinstance(head_owner, str) or not _IDENTIFIER.fullmatch(head_owner):
        head_owner, head_name = owner, repo
    if not isinstance(head_name, str) or not _IDENTIFIER.fullmatch(head_name):
        head_owner, head_name = owner, repo

    file_items = []
    for page in range(1, 4):
        batch = _get_json(
            f"/repos/{owner}/{repo}/pulls/{number}/files?per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise RuntimeError("GitHub file list was not a JSON array")
        file_items.extend(batch)
        if len(file_items) > MAX_PR_FILES:
            raise ValueError(
                f"PR has more than {MAX_PR_FILES} changed files; use a smaller PR"
            )
        if len(batch) < 100:
            break

    diff_sections = []
    candidates = []
    for file in file_items:
        if not isinstance(file, dict):
            raise RuntimeError("Malformed GitHub PR file entry")
        path = file.get("filename")
        if isinstance(path, str) and path.endswith(".py") and not _safe_python_path(path):
            raise ValueError("Unsafe Python filename in GitHub PR")
        if not _safe_python_path(path):
            continue
        status = file.get("status")
        if status not in {"added", "modified", "renamed", "removed", "changed"}:
            raise ValueError(f"Unsupported changed Python file status: {status}")
        patch = file.get("patch")
        if not isinstance(patch, str) or not patch.startswith("@@"):
            raise ValueError(
                f"GitHub did not provide a usable patch for '{path}'. "
                "This PR cannot be reviewed completely through the file list API."
            )
        old_path = file.get("previous_filename", path) if status == "renamed" else path
        if not _safe_repo_path(old_path):
            raise ValueError("Unsafe original filename in GitHub PR")
        new_header = "/dev/null" if status == "removed" else f"b/{path}"
        old_header = "/dev/null" if status == "added" else f"a/{old_path}"
        section = (
            f"diff --git a/{old_path} b/{path}\n"
            f"--- {old_header}\n+++ {new_header}\n{patch.rstrip()}\n"
        )
        diff_sections.append(section)
        if status != "removed":
            candidates.append((path, file.get("sha")))

    diff = validate_diff_size("".join(diff_sections))
    sources = []
    used = 0
    if include_sources:
        for path, blob_sha in candidates[:MAX_SOURCE_FILES]:
            code = _load_blob(head_owner, head_name, blob_sha)
            if code is None:
                continue
            if used + len(code) > MAX_TOTAL_SOURCE_CHARS:
                break
            sources.append({"path": path, "content": code})
            used += len(code)
    return {
        "diff": diff,
        "sources": sources,
        "pr": {
            "url": canonical,
            "title": " ".join(pr["title"].split())[:200],
            "head_sha": str((pr.get("head") or {}).get("sha", ""))[:64],
            "python_files": len(diff_sections),
            "sources_loaded": len(sources),
        },
    }
