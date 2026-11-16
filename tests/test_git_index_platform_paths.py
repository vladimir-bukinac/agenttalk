"""Index names follow the host platform's path rules (#808)."""

import os
from pathlib import PurePosixPath, PureWindowsPath
import subprocess
from types import SimpleNamespace

import pytest

from agenttalk import git_index_safety as safety


NAMES = ["C:", "C:/x", "a:b/c", "a:b.txt", "\\file", "\\\\server/file"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("platform", ["posix", "nt"])
@pytest.mark.parametrize("tag,state", [(b"H", "safe"), (b"h", "hidden")])
def test_index_names_follow_platform(tmp_path, monkeypatch, name, platform, tag, state):
    monkeypatch.setattr(safety, "os", SimpleNamespace(name=platform, fsencode=os.fsencode, fsdecode=os.fsdecode))
    monkeypatch.setattr(safety, "Path", PureWindowsPath if platform == "nt" else PurePosixPath)
    monkeypatch.setattr(safety, "_checkout_root", lambda root: root)
    monkeypatch.setattr(safety, "_records", lambda root, option: [tag + b" " + os.fsencode(name)])
    assert safety.check_hidden_index(tmp_path).state == ("unverifiable" if platform == "nt" else state)


@pytest.mark.parametrize("uncertain", [False, True])
@pytest.mark.parametrize("resolved", [False, True])
def test_guidance_labels_only_resolved_checkout(tmp_path, monkeypatch, uncertain, resolved):
    def checkout(root):
        if not resolved:
            raise ValueError("lookup failed")
        return root

    monkeypatch.setattr(safety, "_checkout_root", checkout)
    text = safety.inspection_guidance(tmp_path, uncertain=uncertain)
    assert text.startswith("Checkout folder:" if resolved else "Folder checked:")


@pytest.mark.skipif(os.name == "nt", reason="Windows cannot create these legal POSIX Git names")
@pytest.mark.parametrize("name", NAMES)
def test_real_git_posix_names_are_safe_then_hidden(tmp_path, name):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "Synthetic Author")
    git("config", "user.email", "synthetic@example.invalid")
    git("config", "commit.gpgsign", "false")
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"original\n")
    git("add", "--", name)
    git("commit", "-qm", "base")
    assert git("status", "--porcelain").stdout == b""
    assert safety.check_hidden_index(tmp_path).state == "safe"
    assert safety.check_materialized_submodules(tmp_path).state == "safe"
    git("update-index", "--assume-unchanged", "--", name)
    path.write_bytes(b"hidden edit\n")
    assert git("status", "--porcelain").stdout == b""
    assert safety.check_hidden_index(tmp_path).state == "hidden"
    assert path.read_bytes() == b"hidden edit\n"
