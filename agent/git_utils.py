"""Read local changes without executing code from the repository."""

from pathlib import Path
import subprocess

MAX_DIFF_CHARS = 20_000


def get_repo_diff(repo_path: str | Path) -> str:
    """Return changes to tracked Python files, staged and unstaged, since HEAD.

    Untracked files are not included. We intentionally reject oversized diffs
    rather than silently reviewing incomplete code.
    """
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise ValueError(f"Repository directory does not exist: {repo}")

    command = [
        "git", "-C", str(repo), "diff", "--no-ext-diff", "--no-color",
        "HEAD", "--", "*.py",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Git is not installed or is not on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "unknown error").strip()
        raise RuntimeError(
            "Could not obtain a Git diff. Make sure this is an initialized "
            f"repository with at least one commit. Git said: {detail}"
        ) from exc

    return validate_diff_size(result.stdout)


def validate_diff_size(diff: str) -> str:
    if len(diff) > MAX_DIFF_CHARS:
        raise ValueError(
            f"Diff has {len(diff):,} characters, above the "
            f"{MAX_DIFF_CHARS:,}-character limit. Review smaller changes first."
        )
    return diff
