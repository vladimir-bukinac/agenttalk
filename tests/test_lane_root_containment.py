"""#850: a store at the root of a filesystem or drive can have lanes.

Two checks compared a folder with the store's folder as text, `root + "/"` or `root.rstrip(sep) + sep`. At a root
that text is `//`, or the root itself, so assigning a lane was refused as "outside the store folder", and the walk up
from a checkout to the store looked at the store's own `.agenttalk` as if it were another store's. The rule is now
component by component, and the walk stops before it looks at the owning root.

The root shapes are tested as pure functions with `posixpath` and `ntpath` (nothing is written to a real root), and at
the two real callers with the path functions replaced by a simulated root of this machine's kind."""

import itertools
import ntpath
import os
import posixpath
import types

import pytest

from agenttalk import cli, lanes
from agenttalk.store import Store
from test_lane_checkout_paths import _link_directory

NT = os.name == "nt"
HOST_ROOT = "c:\\" if NT else "/"
HOST_ROOT_TOKEN = "c:/" if NT else "/"
HOST_SEP = "\\" if NT else "/"


def _under_root(*names: str) -> str:
    return HOST_ROOT + HOST_SEP.join(names)


# ------------------------------------------------------------------------------------- the pure containment rule

INSIDE = [
    # (module, path, root, strictly inside?)
    (posixpath, "/a/b", "/a", True),
    (posixpath, "/a/b/", "/a", True),  # a trailing separator
    (posixpath, "/a", "/a", False),  # the root itself is not inside it
    (posixpath, "/a/", "/a", False),
    (posixpath, "/ab", "/a", False),  # a sibling that shares the prefix
    (posixpath, "/", "/", False),
    (posixpath, "/x", "/", True),  # a store at the root of the file system
    (posixpath, "/x/y", "/", True),
    (posixpath, "/A/b", "/a", False),  # case counts on POSIX
    (posixpath, "/a/./b", "/a", False),  # not a resolved path: not proven
    (posixpath, "/a/../b", "/a", False),
    (posixpath, "x/y", "/", False),  # not absolute
    (ntpath, "C:\\x", "C:\\", True),  # a store at the root of a drive
    (ntpath, "C:\\x\\y", "c:\\", True),  # case does not count on Windows
    (ntpath, "c:\\X\\Y", "C:\\x", True),
    (ntpath, "C:\\x\\", "C:\\x", False),
    (ntpath, "C:\\xy", "C:\\x", False),
    (ntpath, "C:\\", "C:\\", False),
    (ntpath, "C:\\x", "C:", False),  # a drive without a separator names the folder you are in, not the root
    (ntpath, "D:\\x", "C:\\", False),  # another drive
    (ntpath, "c:/x/y", "C:\\x", True),  # forward slashes
    (ntpath, "\\\\server\\share\\x", "\\\\server\\share\\", True),  # a share root, with and without the separator
    (ntpath, "\\\\server\\share\\x", "\\\\server\\share", True),
    (ntpath, "\\\\server\\other\\x", "\\\\server\\share", False),  # another share
    (ntpath, "\\\\server\\share", "\\\\server\\share", False),
    (ntpath, "\\\\server", "\\\\server\\share", False),
    (ntpath, "\\\\?\\UNC\\server\\share\\x", "\\\\server\\share\\", True),  # one share, written two ways
    (ntpath, "\\\\server\\share\\x", "\\\\?\\UNC\\server\\share\\", True),
    (ntpath, "\\\\?\\UNC\\server\\other\\x", "\\\\server\\share\\", False),
    (ntpath, "\\\\?\\C:\\x", "C:\\", True),
    (ntpath, "C:\\x", "\\\\?\\C:\\", True),
    (ntpath, "\\\\?\\Volume{0}\\x", "C:\\", False),  # a spelling that cannot be compared is not proven
    (ntpath, "\\\\.\\C:\\x", "C:\\", False),
    (ntpath, "C:x", "C:\\", False),  # drive-relative
    (ntpath, "\\x", "C:\\", False),  # rooted, no drive
]


@pytest.mark.parametrize(("mod", "path", "root", "expected"), INSIDE)
def test_strictly_inside_compares_whole_folder_names_not_text(mod, path, root, expected):
    assert cli._lane_path_inside(path, root, mod) is expected, (path, root)


@pytest.mark.parametrize(
    ("mod", "path", "root", "expected"),
    [
        (posixpath, "/r/.git", "/r/.git", True),  # the exclusion also covers the folder itself
        (posixpath, "/r/.git/hooks", "/r/.git", True),
        (posixpath, "/r/.gitx", "/r/.git", False),
        (posixpath, "/r", "/r/.git", False),
        (posixpath, "/.git", "/.git", True),  # a store at the root: its .git
        (posixpath, "/.git/x", "/.git", True),
        (posixpath, "/.github", "/.git", False),
        (ntpath, "C:\\.GIT\\x", "c:\\.git", True),
        (ntpath, "C:\\.gitx", "C:\\.git", False),
        (ntpath, "D:\\.git", "C:\\.git", False),
    ],
)
def test_the_git_folder_exclusion_is_component_aware_and_keeps_equality(mod, path, root, expected):
    assert cli._lane_path_inside(path, root, mod, equal_ok=True) is expected


@pytest.mark.parametrize(
    ("mod", "one", "other", "expected"),
    [
        (posixpath, "/a/b", "/a/b/", True),
        (posixpath, "/a/b", "/a/B", False),
        (ntpath, "C:\\a\\b", "c:/A/b/", True),
        (ntpath, "\\\\server\\share\\", "\\\\?\\UNC\\server\\share", True),
        (ntpath, "C:\\a", "D:\\a", False),
        (posixpath, "a", "a", False),  # not a full path: never "the same place"
    ],
)
def test_the_same_place_is_judged_by_components(mod, one, other, expected):
    assert cli._lane_path_same(one, other, mod) is expected


# ----------------------------------------------------------------------------------- the pure ancestor traversal

WALKS = [
    (posixpath, "/a/b/c", "/a", ["/a/b"]),
    (posixpath, "/x/y", "/", ["/x"]),  # the root itself is never yielded
    (posixpath, "/x", "/", []),  # a direct child of the root has nothing between
    (ntpath, "C:\\x\\y\\z", "C:\\", ["C:\\x\\y", "C:\\x"]),
    (ntpath, "c:\\x\\y", "C:\\", ["c:\\x"]),
    (ntpath, "C:\\x", "C:\\", []),
    (ntpath, "\\\\s\\sh\\a\\b", "\\\\s\\sh\\", ["\\\\s\\sh\\a"]),
    (ntpath, "\\\\?\\UNC\\s\\sh\\a\\b", "\\\\s\\sh", ["\\\\?\\UNC\\s\\sh\\a"]),
]


@pytest.mark.parametrize(("mod", "path", "root", "between"), WALKS)
def test_the_ancestor_walk_stops_before_the_owning_root(mod, path, root, between):
    assert list(itertools.islice(cli._lane_ancestors_below(path, root, mod), 50)) == between


@pytest.mark.parametrize(
    ("mod", "path", "root"),
    [
        (posixpath, "/a/b", "/c"),  # not below the root: the walk would leave it
        (posixpath, "/a", "/a"),
        (posixpath, "/ab/c", "/a"),
        (ntpath, "D:\\x\\y", "C:\\"),
        (ntpath, "C:\\x", "C:\\x"),
        (ntpath, "\\\\server\\other\\x\\y", "\\\\server\\share"),
        (ntpath, "C:x\\y", "C:\\"),
    ],
)
def test_an_ancestry_that_is_not_proven_below_the_root_is_refused(mod, path, root):
    with pytest.raises(ValueError):
        list(itertools.islice(cli._lane_ancestors_below(path, root, mod), 50))


def test_a_walk_that_stops_advancing_before_the_root_is_refused_not_looped():
    """The guard: a path function whose parent never changes must end in a refusal, not an endless walk. The loop is
    bounded here, so the old behaviour shows as a failed test and not as a hang."""

    class Stuck:
        splitdrive = staticmethod(posixpath.splitdrive)
        normcase = staticmethod(posixpath.normcase)
        dirname = staticmethod(lambda path: path)  # never reaches the root

    with pytest.raises(ValueError):
        list(itertools.islice(cli._lane_ancestors_below("/a/b", "/a", Stuck), 100))


# ------------------------------------------------------------------- the walk up from a checkout, at its real caller


def _simulated_walk(monkeypatch, root, *, stores=(), unreadable=(), cap=50):
    """Make `_lane_checkout_place` see `root` as the store's folder and every path as already resolved. `stores` are
    folders that hold a store of their own, `unreadable` ones that cannot be listed. Returns the folders looked at. The
    walk is capped, so a walk that never ends fails the test instead of hanging it."""
    looked: list[str] = []

    def strict_real(path, *, missing_tail_ok=False):
        return os.path.normcase(os.fspath(path))

    def has_store(directory):
        looked.append(directory)
        assert len(looked) <= cap, "the walk did not stop"
        if os.path.normcase(directory) in {os.path.normcase(p) for p in unreadable}:
            raise PermissionError(5, "access denied", directory)
        return os.path.normcase(directory) in {os.path.normcase(p) for p in stores}

    monkeypatch.setattr(cli, "_strict_real", strict_real)
    monkeypatch.setattr(cli, "_lane_dir_has_store_folder", has_store)
    return looked, types.SimpleNamespace(root=root)


@pytest.mark.parametrize(
    "names",
    [("lane-1",), (".worktrees", "lane-1"), ("a", "b", "lane-1")],
    ids=["direct child", "one folder between", "two folders between"],
)
def test_a_checkout_under_a_store_at_a_root_is_its_own_and_the_root_is_not_looked_at(monkeypatch, names):
    folder = _under_root(*names)
    looked, store = _simulated_walk(monkeypatch, HOST_ROOT, stores={HOST_ROOT})  # the root holds the owning store
    assert cli._lane_checkout_place(store, folder) is None
    assert os.path.normcase(HOST_ROOT) not in {os.path.normcase(p) for p in looked}
    assert len(looked) == len(names) - 1  # only the folders between the root and the checkout


def test_the_root_of_the_store_is_not_looked_at_even_when_it_cannot_be_read(monkeypatch):
    """The owning root is deliberately not inspected: it is not an intervening store, readable or not."""
    looked, store = _simulated_walk(monkeypatch, HOST_ROOT, unreadable={HOST_ROOT})
    assert cli._lane_checkout_place(store, _under_root(".worktrees", "lane-1")) is None
    assert looked == [_under_root(".worktrees")]


def test_a_store_between_the_root_and_the_checkout_still_blocks(monkeypatch):
    mid = _under_root("mid")
    _looked, store = _simulated_walk(monkeypatch, HOST_ROOT, stores={HOST_ROOT, mid})
    place = cli._lane_checkout_place(store, os.path.join(mid, "lane-1"))
    assert place is not None and place[0] == "outside"
    assert cli._lane_checkout_outside_store(store, os.path.join(mid, "lane-1")) is not None


def test_an_unreadable_folder_between_is_not_proven_and_the_walk_says_so(monkeypatch):
    mid = _under_root("mid")
    _looked, store = _simulated_walk(monkeypatch, HOST_ROOT, unreadable={mid})
    place = cli._lane_checkout_place(store, os.path.join(mid, "lane-1"))
    assert place is not None and place[0] == "unknown"


@pytest.mark.parametrize("folder", [HOST_ROOT, _under_root("..", "x")], ids=["the root itself", "dot-dot"])
def test_the_root_itself_and_unresolved_paths_are_not_inside(monkeypatch, folder):
    _looked, store = _simulated_walk(monkeypatch, HOST_ROOT, stores={HOST_ROOT})
    place = cli._lane_checkout_place(store, folder)
    assert place is not None and place[0] == "outside"


@pytest.mark.skipif(not NT, reason="another drive is a Windows case")
def test_a_checkout_on_another_drive_is_not_inside_a_drive_root_store(monkeypatch):
    _looked, store = _simulated_walk(monkeypatch, "c:\\")
    place = cli._lane_checkout_place(store, "d:\\lane-1")
    assert place is not None and place[0] == "outside"


# --------------------------------------------------------------------- the same walk on real folders (the controls)


def test_a_real_store_between_the_owner_and_a_checkout_blocks_and_a_direct_child_does_not(tmp_path):
    owner = tmp_path / "owner"
    (owner / ".agenttalk").mkdir(parents=True)
    (owner / "inner" / ".agenttalk").mkdir(parents=True)  # a real store of its own between
    (owner / "inner" / "checkout").mkdir()
    (owner / ".worktrees" / "plain").mkdir(parents=True)
    (owner / "checkout").mkdir()
    store = Store(owner)
    assert cli._lane_checkout_outside_store(store, str(owner / "inner" / "checkout")) is not None
    assert cli._lane_checkout_outside_store(store, str(owner / ".worktrees" / "plain")) is None
    assert cli._lane_checkout_outside_store(store, str(owner / "checkout")) is None
    assert (owner / "inner" / ".agenttalk").is_dir()


def test_a_sibling_that_shares_the_stores_name_is_not_inside_it(tmp_path):
    owner = tmp_path / "proj"
    (owner / ".agenttalk").mkdir(parents=True)
    sibling = tmp_path / "proj2" / "checkout"
    sibling.mkdir(parents=True)
    assert cli._lane_checkout_outside_store(Store(owner), str(sibling)) is not None


def test_a_link_that_resolves_outside_the_store_is_not_inside_it(tmp_path):
    owner = tmp_path / "owner"
    (owner / ".agenttalk").mkdir(parents=True)
    (owner / ".worktrees").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = owner / ".worktrees" / "out"
    _link_directory(link, elsewhere)
    assert cli._lane_checkout_outside_store(Store(owner), str(link)) is not None


# ----------------------------------------------------------------------- assigning a lane at a root, the first check


def _assignment_at_a_simulated_root(monkeypatch, tmp_path, *, store_token=HOST_ROOT_TOKEN, root_token=None):
    """`_prepare_worktrees_root` with the store's folder, the worktrees root and its `.git` read as `store_token` and
    its children (nothing is written to the real root: the folder that is made is under `tmp_path`)."""
    base = store_token.rstrip("/")  # "" or "c:" for a root, so base + "/x" is the child
    root_token = root_token or base + "/.worktrees"
    git_token = base + "/.git"
    made = tmp_path / "made"

    def canonical(value, **kwargs):
        return git_token if str(value).endswith(".git") else store_token

    monkeypatch.setattr(lanes, "worktrees_root", lambda store, configured=None: made)
    monkeypatch.setattr(lanes, "resolve_creation_folder", lambda path: str(path))
    monkeypatch.setattr(lanes, "_canonical_token", lambda resolved, **kwargs: root_token)
    monkeypatch.setattr(lanes, "canonical_host_path_checked", canonical)
    return cli._prepare_worktrees_root(types.SimpleNamespace(root=tmp_path), None), made


def test_a_worktrees_root_inside_a_store_at_a_root_is_accepted(monkeypatch, tmp_path):
    root, made = _assignment_at_a_simulated_root(monkeypatch, tmp_path)
    assert root == made and (made / lanes.WORKTREE_MARKER_FILENAME).is_file()


@pytest.mark.parametrize("where", ["the store folder", "its .git folder", "inside .git"])
def test_the_store_folder_and_its_git_folder_stay_refused_at_a_root(monkeypatch, tmp_path, where):
    token = {
        "the store folder": HOST_ROOT_TOKEN,
        "its .git folder": HOST_ROOT_TOKEN + ".git",
        "inside .git": HOST_ROOT_TOKEN + ".git/hooks",
    }[where]
    with pytest.raises(lanes.LaneError, match="the store folder itself or inside its .git folder"):
        _assignment_at_a_simulated_root(monkeypatch, tmp_path, root_token=token)


def test_a_worktrees_root_outside_a_store_at_a_root_stays_refused(monkeypatch, tmp_path):
    """A different drive (Windows) or a folder that merely shares the text (a sibling of a store that is not at the
    root) is outside."""
    if NT:
        with pytest.raises(lanes.LaneError, match="outside the store folder"):
            _assignment_at_a_simulated_root(monkeypatch, tmp_path, root_token="d:/.worktrees")
    with pytest.raises(lanes.LaneError, match="outside the store folder"):
        _assignment_at_a_simulated_root(
            monkeypatch,
            tmp_path,
            store_token="c:/proj" if NT else "/home/me/proj",
            root_token="c:/proj2/.worktrees" if NT else "/home/me/proj2/.worktrees",
        )


def test_a_worktrees_root_inside_an_ordinary_store_is_accepted_as_before(monkeypatch, tmp_path):
    token = "c:/home/proj" if NT else "/home/proj"
    root, made = _assignment_at_a_simulated_root(
        monkeypatch, tmp_path, store_token=token, root_token=token + "/.worktrees"
    )
    assert root == made
