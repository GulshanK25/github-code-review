from pathlib import Path
import shutil
import subprocess

import pytest

from agent.git_utils import get_repo_diff, validate_diff_size, MAX_DIFF_CHARS


def test_rejects_oversized_diff():
    with pytest.raises(ValueError, match="above"):
        validate_diff_size("a" * (MAX_DIFF_CHARS + 1))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_read_python_diff(tmp_path: Path):
    def git(*args):
        subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True, capture_output=True, text=True,
        )

    git("init", "-q")
    target = tmp_path / "app.py"
    target.write_text("print('old')\n", encoding="utf-8")
    git("add", "app.py")
    git("-c", "user.name=Example", "-c", "user.email=test@example.com", "commit", "-qm", "initial")
    target.write_text("print('new')\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("not Python", encoding="utf-8")

    diff = get_repo_diff(tmp_path)
    assert "+print('new')" in diff
    assert "ignored.txt" not in diff
