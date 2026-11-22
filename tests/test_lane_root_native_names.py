"""#850 round: a backslash is an ordinary character of a folder name on POSIX.

The worktrees root is compared with the store's folder as canonical tokens, and the shared token writer replaced every
backslash with `/`. On Linux and macOS that invented a separator: a folder literally named `\\.` below the store was
formatted as `store//.` and refused for an invented `.` step, `\\..` the same, and a sibling named `a\\b` was formatted
as `a/b` and read as inside the folder `a`. The comparison now keeps the host's own components.

Pure path logic with `posixpath` and `ntpath` (nothing is written to disk), so every host runs it, Windows included."""

import ntpath
import posixpath

import pytest

from agenttalk import cli, lanes


def refusal(mod, store, root, git=None):
    """The refusal (or None) for a worktrees root `root` in a store at `store`, both as full resolved paths, built
    exactly as the assignment builds them: native tokens, then the whole-name comparison."""
    sep = "\\" if mod is ntpath else "/"
    token = lambda path: lanes._canonical_token(path, native=True, mod=mod)  # noqa: E731
    return cli._worktrees_root_refusal(
        token(root), token(store), token(git or store.rstrip(sep) + sep + ".git"),
        typed='"t"', folder="f", location="l", mod=mod,
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------ the formatter


@pytest.mark.parametrize("name", ["\\.", "\\..", "a\\b", "a\\"])
def test_posix_tokens_keep_a_backslash_as_a_name_character(name):
    path = "/owner/" + name
    assert lanes._canonical_token(path, native=True, mod=posixpath) == path
    # The canonical tokens that are saved in lane records keep their old form (a separator), so nothing saved changes.
    assert lanes._canonical_token(path, mod=posixpath) == path.replace("\\", "/")


def test_the_saved_canonical_form_is_unchanged():
    assert lanes._canonical_token("/owner/\\.", mod=posixpath) == "/owner//."
    assert lanes._canonical_token("/owner/a\\b", mod=posixpath) == "/owner/a/b"


@pytest.mark.parametrize("native", [False, True])
def test_windows_tokens_always_use_a_slash_and_fold_case(native):
    assert lanes._canonical_token("C:\\Store\\Lanes", native=native, mod=ntpath) == "c:/store/lanes"


# ------------------------------------------------------------------------------- POSIX: native names, one folder each


@pytest.mark.parametrize("name", ["\\.", "\\..", "a\\b", "x\\y\\z"])
def test_a_posix_folder_named_with_a_backslash_is_inside_its_owner(name):
    assert refusal(posixpath, "/owner", "/owner/" + name) is None


@pytest.mark.parametrize("name", ["\\.", "\\..", "a\\b"])
def test_a_posix_worktrees_root_below_such_a_folder_is_inside_the_store(name):
    assert refusal(posixpath, "/owner/" + name, "/owner/" + name + "/.worktrees") is None


def test_a_posix_name_with_a_backslash_is_not_the_folder_with_a_slash():
    """`/owner/a\\b` is one folder named `a\\b` directly below `/owner`; it is not `/owner/a/b`."""
    assert "outside the store folder" in refusal(posixpath, "/owner/a", "/owner/a\\b")
    assert "outside the store folder" in refusal(posixpath, "/owner/a\\b", "/owner/a/b")
    assert "outside the store folder" in refusal(posixpath, "/owner/a/b", "/owner/a\\b/worktrees")


def test_a_posix_name_with_a_backslash_is_not_the_store_itself():
    assert refusal(posixpath, "/owner/a/b", "/owner/a\\b/x") is not None
    assert refusal(posixpath, "/owner/a\\b", "/owner/a\\b") is not None  # the store folder itself, still refused


# ------------------------------------------------------------------------- Windows: unchanged refusals and acceptance


@pytest.mark.parametrize("root", ["C:\\store\\lanes", "C:\\store\\lanes\\deeper", "C:/store/lanes", "c:\\STORE\\Lanes"])
def test_a_windows_folder_below_the_store_is_inside(root):
    assert refusal(ntpath, "C:\\store", root) is None


@pytest.mark.parametrize("root", ["C:\\store", "C:\\store\\.git", "C:\\store\\.git\\hooks"])
def test_the_windows_store_itself_and_its_git_folder_are_refused(root):
    assert "the store folder itself or inside its .git folder" in refusal(ntpath, "C:\\store", root)


@pytest.mark.parametrize("root", ["D:\\store\\lanes", "C:\\store2\\lanes", "C:\\other"])
def test_a_windows_folder_outside_the_store_is_refused(root):
    assert "outside the store folder" in refusal(ntpath, "C:\\store", root)


@pytest.mark.parametrize(
    "token",
    ["c:/store/./lanes", "c:/store/../store/lanes", "c:/store/lanes/.", "//./c:/store/lanes",
     "//?/Volume{1}/store/lanes", "c:store/lanes"],
)  # fmt: skip
def test_windows_dot_steps_device_prefixes_and_drive_relative_names_are_still_refused(token):
    """A token that cannot be read as a full path is never inside: real dot steps, the extended and device spellings,
    a name relative to a drive's current folder. (The tokens are written out: a real resolved path has none.)"""
    assert cli._lane_path_inside(token, "c:/store", ntpath) is False
    assert "outside the store folder" in cli._worktrees_root_refusal(
        token, "c:/store", "c:/store/.git", typed='"t"', folder="f", location="l", mod=ntpath
    )


def test_the_extended_spelling_of_a_drive_is_still_read_as_the_ordinary_one():
    assert cli._lane_path_inside("//?/c:/store/lanes", "c:/store", ntpath) is True


@pytest.mark.parametrize("token", ["/owner/./x", "/owner/../x", "/owner/x/.", "/owner/x/.."])
def test_posix_dot_steps_are_still_refused(token):
    """A real `.` or `..` step is not a name on POSIX either (only `\\.` and `\\..` are)."""
    assert cli._lane_path_inside(token, "/owner", posixpath) is False
