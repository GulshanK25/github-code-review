"""Mocked GitHub API tests. Never calls github.com."""

import base64

import pytest

import agent.github_utils as github


PR = "https://github.com/acme/sample/pull/42"


def sample_pr():
    return {
        "title": " Fix incorrect admin check  ",
        "head": {"sha": "c" * 40, "repo": {"name": "sample-fork", "owner": {"login": "contributor"}}},
    }


def sample_file(patch=None):
    return {
        "filename": "auth.py",
        "status": "modified",
        "sha": "a" * 40,
        "patch": "@@ -1 +1 @@\n-return True\n+return bool(user)" if patch is None else patch,
    }


def test_parse_pr_url():
    assert github.parse_pr_url(PR + "/") == ("acme", "sample", 42)


@pytest.mark.parametrize("bad", [
    "http://github.com/acme/sample/pull/42",
    "https://evil.com/acme/sample/pull/42",
    "https://github.com.evil.com/acme/sample/pull/42",
    "https://github.com/acme/sample/issues/42",
    "https://github.com/acme/sample/pull/0",
    "https://github.com/acme/sample/pull/42?x=y",
    "https://github.com/acme/sample/pull/42/commits",
    "https://github.com/acme/sample/pull/not-a-number",
    "https://github.com/acme/sample/pull/1#fragment",
])
def test_rejects_bad_url(bad):
    with pytest.raises(ValueError, match="GitHub PR URL"):
        github.parse_pr_url(bad)


def test_fetch_python_patch_and_source_from_fork(monkeypatch):
    calls = []
    payloads = {
        "/repos/acme/sample/pulls/42": sample_pr(),
        "/repos/acme/sample/pulls/42/files?per_page=100&page=1": [
            sample_file(),
            {"filename": "README.md", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"},
        ],
        "/repos/contributor/sample-fork/git/blobs/" + "a" * 40: {
            "encoding": "base64", "size": 33,
            "content": base64.b64encode(b"def can_delete_account(user):\n    return bool(user)\n").decode("ascii"),
        },
    }

    def fake_get(path):
        calls.append(path)
        return payloads[path]

    monkeypatch.setattr(github, "_get_json", fake_get)
    result = github.fetch_pull_request(PR, include_sources=True)
    assert result["pr"]["title"] == "Fix incorrect admin check"
    assert result["pr"]["python_files"] == 1
    assert "+++ b/auth.py" in result["diff"]
    assert "README.md" not in result["diff"]
    assert result["sources"][0]["path"] == "auth.py"
    assert "return bool(user)" in result["sources"][0]["content"]
    assert calls[-1].startswith("/repos/contributor/sample-fork/git/blobs/")


def test_review_only_does_not_download_source(monkeypatch):
    monkeypatch.setattr(github, "_get_json", lambda path: (
        sample_pr() if path.endswith("/pulls/42") else [sample_file()]
    ))
    monkeypatch.setattr(github, "_load_blob", lambda *_: pytest.fail("No blob downloads"))
    result = github.fetch_pull_request(PR, include_sources=False)
    assert result["sources"] == []
    assert "return bool(user)" in result["diff"]


def test_reject_missing_patch(monkeypatch):
    f = sample_file()
    f.pop("patch")
    monkeypatch.setattr(github, "_get_json", lambda path: (
        sample_pr() if path.endswith("/pulls/42") else [f]
    ))
    with pytest.raises(ValueError, match="usable patch"):
        github.fetch_pull_request(PR)


def test_reject_large_diff(monkeypatch):
    oversized = sample_file(patch="@@ -1 +1 @@\n" + "+x\n" * 12_000)
    monkeypatch.setattr(github, "_get_json", lambda path: (
        sample_pr() if path.endswith("/pulls/42") else [oversized]
    ))
    with pytest.raises(ValueError, match="above"):
        github.fetch_pull_request(PR)


def test_safe_paths():
    assert github._safe_python_path("pkg/auth.py")
    assert not github._safe_python_path("../secret.py")
    assert github._safe_python_path(".github/ci.py")
    assert not github._safe_python_path("C:\\private.py")
    assert not github._safe_python_path("notes.txt")


def test_no_python_changes(monkeypatch):
    monkeypatch.setattr(github, "_get_json", lambda path: (
        sample_pr() if path.endswith("/pulls/42") else [
            {"filename": "README.md", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"}
        ]
    ))
    result = github.fetch_pull_request(PR)
    assert result["diff"] == ""
    assert result["pr"]["python_files"] == 0
