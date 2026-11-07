from pathlib import Path

from agent.source_utils import (
    changed_python_paths,
    load_changed_sources
)


def test_changed_paths_deduplicate_and_reject_traversal():

    diff = "\n".join([
        "+++ b/auth.py",
        "+++ b/auth.py",
        "+++ b/../secret.py",
        "+++ b/other.txt",
        "+++ b/sub/api.py",
        "+++ /dev/null",
    ])

    assert changed_python_paths(diff) == [
        "auth.py",
        "sub/api.py"
    ]


def test_read_changed_source_inside_repo(tmp_path: Path):

    (tmp_path / "auth.py").write_text(
        "def verify():\n    return False\n",
        encoding="utf-8"
    )

    result = load_changed_sources(
        "+++ b/auth.py",
        tmp_path
    )

    assert result[0]["path"] == "auth.py"

    assert "def verify()" in result[0]["content"]


def test_symlink_outside_repo_cannot_be_loaded(
    tmp_path: Path
):

    root = tmp_path / "repo"
    root.mkdir()

    outside = tmp_path / "private.py"

    outside.write_text(
        "SECRET",
        encoding="utf-8"
    )

    try:
        (root / "private.py").symlink_to(outside)

    except (OSError, NotImplementedError):
        return

    assert load_changed_sources(
        "+++ b/private.py",
        root
    ) == []


def test_oversized_source_is_skipped(tmp_path: Path):

    (tmp_path / "large.py").write_text(
        "x" * 6100,
        encoding="utf-8"
    )

    assert load_changed_sources(
        "+++ b/large.py",
        tmp_path
    ) == []