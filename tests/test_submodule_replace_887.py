"""A replacement in a submodule must not hide its uncommitted work."""

import subprocess

import pytest

from agenttalk import acceptance, git_index_safety


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize("route", ["verify", "close"])
def test_submodule_replace_cannot_hide_dirty_checkout(tmp_path, route):
    child = tmp_path / "child"
    child.mkdir()
    git(child, "init", "-q")
    git(child, "config", "user.name", "Test")
    git(child, "config", "user.email", "test@example.invalid")
    (child / "file.txt").write_text("original\n", encoding="utf-8")
    git(child, "add", "file.txt")
    git(child, "commit", "-qm", "original")
    original = git(child, "rev-parse", "HEAD")
    (child / "file.txt").write_text("replacement\n", encoding="utf-8")
    git(child, "commit", "-qam", "replacement")
    replacement = git(child, "rev-parse", "HEAD")
    git(child, "reset", "--hard", "-q", original)

    parent = tmp_path / "parent"
    parent.mkdir()
    git(parent, "init", "-q")
    git(parent, "config", "user.name", "Test")
    git(parent, "config", "user.email", "test@example.invalid")
    git(parent, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(child), "sub")
    git(parent, "commit", "-qm", "parent")
    revision = git(parent, "rev-parse", "HEAD")
    nested = parent / "sub"
    git(nested, "replace", original, replacement)
    git(nested, "reset", "--hard", "-q", "HEAD")
    assert git(parent, "status", "--porcelain", "--ignore-submodules=none") == ""
    assert git(nested, "--no-replace-objects", "status", "--porcelain")

    if route == "verify":
        with pytest.raises(acceptance.AcceptanceError) as error:
            acceptance.verify_project(parent, revision)
        assert error.value.code == "acceptance_project_unverified"
        assert "checkout is dirty" in str(error.value)
    else:
        assert git_index_safety.check_close_submodules(parent).state != "safe"
