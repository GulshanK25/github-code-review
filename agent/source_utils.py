"""Safely read changed Python source files for test generation."""

from pathlib import Path, PurePosixPath


MAX_SOURCE_FILES = 4
MAX_SOURCE_CHARS_PER_FILE = 6_000
MAX_TOTAL_SOURCE_CHARS = 16_000


def changed_python_paths(diff: str) -> list[str]:

    """Extract changed Python file paths from a Git diff."""

    paths: list[str] = []

    for line in diff.splitlines():

        if not line.startswith("+++ b/"):
            continue

        path = line[len("+++ b/"):]

        parsed = PurePosixPath(path)

        if (
            not parsed.is_absolute()
            and path.endswith(".py")
            and not any(
                part in (".", "..")
                for part in parsed.parts
            )
            and "\\" not in path
            and path not in paths
        ):
            paths.append(path)

    return paths[:MAX_SOURCE_FILES]


def load_changed_sources(
    diff: str,
    repo_path: str | Path
) -> list[dict[str, str]]:

    """
    Read matching Python files from the given repository.

    Reject files outside the repository and never execute source code.
    """

    root = Path(repo_path).resolve()

    if not root.is_dir():
        return []

    results: list[dict[str, str]] = []
    used = 0

    for relative in changed_python_paths(diff):

        file_path = (root / relative).resolve()

        if not file_path.is_relative_to(root):
            continue

        if not file_path.is_file():
            continue

        with file_path.open(
            "r",
            encoding="utf-8",
            errors="replace"
        ) as handle:

            source = handle.read(
                MAX_SOURCE_CHARS_PER_FILE + 1
            )

        # Avoid giving the model incomplete source files.
        if len(source) > MAX_SOURCE_CHARS_PER_FILE:
            continue

        if used + len(source) > MAX_TOTAL_SOURCE_CHARS:
            break

        results.append({
            "path": relative,
            "content": source
        })

        used += len(source)

    return results