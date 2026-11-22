"""#849: Git reports that a lane's checkout was removed, but its folder is still there.

Every test drives the real `lane` commands on a throwaway repository and store. Git's own removal runs; a stand-in
then makes the folder again (or leaves something else in its place), which is how a folder survives a successful Git
removal. Each printed recovery step is run literally.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from agenttalk import cli, lanes
from agenttalk.store import Store

from test_lanes import _assign_worktree, _commit, _git, _repo, _run_raw  # noqa: F401

PREFIX = "Git reported the checkout removed, but "


def make_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def drop_link(link: Path) -> None:
    link.rmdir() if os.name == "nt" else link.unlink()


def view(store, lane_id):
    row = lanes.load_lanes(store)["lanes"][lane_id]
    keys = (
        "status",
        "cleanup_pending",
        "worktree_state",
        "worktree_cleanup_error",
        "delivery_artifact",
        "delivered_head",
        "delivery_transaction_id",
        "publish_pending",
    )
    return {key: row.get(key) for key in keys}


def git_leaves(monkeypatch, kind="folder", tmp_path=None):
    """Git's removal runs and reports success; then `kind` is left at the path (a folder, a file, a junction to
    somewhere, a junction to nothing). Returns the list of removal calls."""
    real = cli._git_write
    calls = []

    def fake(root, argv, **kwargs):
        result = real(root, argv, **kwargs)
        if argv[:2] == ["worktree", "remove"] and result[0] == 0:
            calls.append(argv[-1])
            left = Path(argv[-1])
            if kind == "folder":
                left.mkdir()
            elif kind == "file":
                left.write_text("left behind")
            elif kind in ("link", "dangling"):
                target = tmp_path / "link-target"
                target.mkdir(exist_ok=True)
                (target / "keep.txt").write_text("not the lane's")
                make_link(left, target)
                if kind == "dangling":
                    shutil.rmtree(target)
        return result

    monkeypatch.setattr(cli, "_git_write", fake)
    return calls


def delivered_lane(tmp_path, lane_id="d1"):
    root, base = _repo(tmp_path)
    wt = Path(_assign_worktree(root, base, lane_id)["worktree_path"])
    _commit(wt, "src/core/a.py", f"base\n{lane_id}\n")
    return root, wt


def deliver(root, lane_id="d1"):
    return _run_raw(["lane", "deliver", "--id", lane_id, "--from", "dev"], root)


def lane_item(capsys, argv, root, lane_id):
    assert _run_raw(argv, root) == 0
    out = capsys.readouterr().out
    return next(item for item in json.loads(out)["items"] if item["lane_id"] == lane_id)


# ---------------------------------------------------------------- 1. delivery, Git succeeded, the folder is there


def test_delivery_keeps_the_cleanup_pending_when_the_folder_is_still_there(tmp_path, monkeypatch, capsys):
    root, wt = delivered_lane(tmp_path)
    store = Store(root)
    git_leaves(monkeypatch)

    deliver(root)
    capsys.readouterr()

    row = view(store, "d1")
    assert wt.exists()
    assert row["status"] == lanes.STATUS_DELIVERED and row["cleanup_pending"] is True
    assert row["worktree_state"] == lanes.STATUS_CLEANUP_FAILED
    assert row["worktree_cleanup_error"].startswith(PREFIX) and str(wt) in row["worktree_cleanup_error"]
    assert row["publish_pending"] is False and row["delivery_artifact"] and row["delivered_head"]
    assert _run_raw(["lane", "status"], root) == 0
    status = capsys.readouterr().out
    line = next(line for line in status.splitlines() if "d1" in line)
    assert str(wt) in line and "lane deliver --id d1" in line and "ignored files" in line, status


# ---------------------------------------------------------------- 2. abandon


@pytest.mark.parametrize("delete_branch", [False, True])
@pytest.mark.parametrize("as_json", [False, True])
def test_abandon_keeps_the_cleanup_pending_and_suggests_no_branch_command(
    tmp_path, monkeypatch, capsys, delete_branch, as_json
):
    root, base = _repo(tmp_path)
    wt = Path(_assign_worktree(root, base, "a1")["worktree_path"])
    git_leaves(monkeypatch)
    argv = [
        "lane",
        "abandon",
        "--id",
        "a1",
        *(["--delete-branch"] if delete_branch else []),
        *(["--json"] if as_json else []),
    ]
    capsys.readouterr()

    assert _run_raw(argv, root) == 0
    out = capsys.readouterr()

    row = view(Store(root), "a1")
    assert wt.exists() and row["status"] == lanes.STATUS_ABANDONED
    assert row["worktree_state"] == lanes.STATUS_CLEANUP_FAILED
    assert row["worktree_cleanup_error"].startswith(PREFIX)
    assert "branch -d" not in out.out and "branch -d" not in out.err
    if as_json:
        result = json.loads(out.out)
        assert "branch_delete_command" not in result and result["branch_deleted"] is False
        if delete_branch:
            assert result["branch_kept_reason"].startswith(PREFIX)
        assert set(result) <= {"lane_id", "branch_deleted", "branch_kept_reason"}
    elif delete_branch:
        assert f"branch kept: {PREFIX}" in out.err
    assert "worktree cleanup is not finished" in out.err


# ---------------------------------------------------------------- 3. gc --delete


def abandoned_with_failed_removal(tmp_path, monkeypatch, lane_id="g1"):
    root, base = _repo(tmp_path)
    wt = Path(_assign_worktree(root, base, lane_id)["worktree_path"])
    real = cli._git_write

    def refuse(r, argv, **kwargs):
        if argv[:2] == ["worktree", "remove"]:
            return 1, "", "injected teardown failure"
        return real(r, argv, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(cli, "_git_write", refuse)
        assert _run_raw(["lane", "abandon", "--id", lane_id], root) == 0
    return root, wt


@pytest.mark.parametrize("as_json", [False, True])
def test_gc_delete_does_not_call_a_leftover_removed(tmp_path, monkeypatch, capsys, as_json):
    root, wt = abandoned_with_failed_removal(tmp_path, monkeypatch)
    git_leaves(monkeypatch)
    capsys.readouterr()

    assert _run_raw(["lane", "gc", "--delete", *(["--json"] if as_json else [])], root) == 0
    out = capsys.readouterr()

    assert wt.exists()
    assert "branch -d" not in out.out
    if as_json:
        item = next(item for item in json.loads(out.out)["items"] if item["lane_id"] == "g1")
        assert item["worktree_removed"] is False and "remove_error" not in item
        assert item["branch_delete_checks_passed"] is False
        assert "branch_delete_command" not in item and item["reason"].startswith(PREFIX)
    else:
        assert "branch kept:" in out.err and PREFIX in out.err


# ---------------------------------------------------------------- 4. a second gc on the leftover


def test_a_second_gc_says_git_does_not_list_the_leftover_folder(tmp_path, monkeypatch, capsys):
    root, wt = abandoned_with_failed_removal(tmp_path, monkeypatch)
    git_leaves(monkeypatch)
    assert _run_raw(["lane", "gc", "--delete"], root) == 0
    capsys.readouterr()
    monkeypatch.undo()

    item = lane_item(capsys, ["lane", "gc", "--json"], root, "g1")

    assert wt.exists() and item["branch_delete_checks_passed"] is False
    assert "registered worktree" not in item["reason"]
    assert "does not list" in item["reason"] and str(wt) in item["reason"], item["reason"]


# ---------------------------------------------------------------- 5. retry while the leftover remains


def spies(monkeypatch):
    calls = []
    real_git, real_verify = cli._git_write, cli._verify_lane_worktree

    def git(root, argv, **kwargs):
        calls.append(("git", argv[:2]))
        return real_git(root, argv, **kwargs)

    def verify(*args, **kwargs):
        calls.append(("verify",))
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(cli, "_git_write", git)
    monkeypatch.setattr(cli, "_verify_lane_worktree", verify)
    return calls


def test_a_delivery_retry_repeats_the_saved_reason_and_calls_nothing(tmp_path, monkeypatch, capsys):
    root, wt = delivered_lane(tmp_path)
    store = Store(root)
    with monkeypatch.context() as patch:
        git_leaves(patch)
        deliver(root)
    saved = view(store, "d1")
    capsys.readouterr()
    calls = spies(monkeypatch)

    deliver(root)

    out = capsys.readouterr()
    assert calls == [] and view(store, "d1") == saved
    assert wt.exists() and saved["worktree_cleanup_error"] in out.err or PREFIX in out.err


def test_an_abandon_retry_repeats_the_saved_reason_and_calls_nothing(tmp_path, monkeypatch, capsys):
    root, base = _repo(tmp_path)
    wt = Path(_assign_worktree(root, base, "a1")["worktree_path"])
    store = Store(root)
    with monkeypatch.context() as patch:
        git_leaves(patch)
        assert _run_raw(["lane", "abandon", "--id", "a1"], root) == 0
    saved = view(store, "a1")
    capsys.readouterr()
    calls = spies(monkeypatch)

    assert _run_raw(["lane", "abandon", "--id", "a1"], root) == 0

    assert calls == [] and view(store, "a1") == saved and wt.exists()
    assert PREFIX in capsys.readouterr().err


# ---------------------------------------------------------------- 6. the printed steps, run literally


def test_the_printed_delivery_step_finishes_the_cleanup_once_the_folder_is_gone(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTTALK_SELF", "dev")
    root, wt = delivered_lane(tmp_path)
    store = Store(root)
    with monkeypatch.context() as patch:
        git_leaves(patch)
        deliver(root)
    before = view(store, "d1")
    capsys.readouterr()
    assert _run_raw(["lane", "status"], root) == 0
    printed = re.search(r"`(lane deliver --id d1)`", capsys.readouterr().out)
    assert printed, "status names no `lane deliver --id d1` step"
    shutil.rmtree(wt)  # the person inspects the folder, saves what they need, and removes it
    calls = spies(monkeypatch)

    assert _run_raw(shlex.split(printed.group(1)), root) == 0

    after = view(store, "d1")
    assert after["status"] == lanes.STATUS_DELIVERED and after["cleanup_pending"] is False
    assert after["worktree_state"] == lanes.STATUS_DELIVERED
    assert {k: after[k] for k in ("delivery_artifact", "delivered_head", "delivery_transaction_id")} == {
        k: before[k] for k in ("delivery_artifact", "delivered_head", "delivery_transaction_id")
    }
    assert ("git", ["worktree", "remove"]) not in calls


def test_the_printed_abandon_step_finishes_an_abandoned_lane_once_the_folder_is_gone(tmp_path, monkeypatch, capsys):
    root, base = _repo(tmp_path)
    wt = Path(_assign_worktree(root, base, "a1")["worktree_path"])
    with monkeypatch.context() as patch:
        git_leaves(patch)
        assert _run_raw(["lane", "abandon", "--id", "a1"], root) == 0
    capsys.readouterr()
    assert _run_raw(["lane", "status"], root) == 0
    printed = re.search(r"`(lane abandon --id a1 --acknowledge-missing-worktree)`", capsys.readouterr().out)
    assert printed, "status names no acknowledgement step"
    shutil.rmtree(wt)

    assert _run_raw(shlex.split(printed.group(1)), root) == 0

    assert view(Store(root), "a1")["worktree_state"] == lanes.STATUS_CLEANUP_ACKNOWLEDGED


# ---------------------------------------------------------------- 7. what counts as left behind


@pytest.mark.parametrize("kind", ["folder", "file", "link", "dangling"])
def test_whatever_is_left_at_the_path_is_a_leftover(tmp_path, monkeypatch, capsys, kind):
    root, wt = delivered_lane(tmp_path)
    store = Store(root)
    git_leaves(monkeypatch, kind, tmp_path)
    try:
        deliver(root)
        row = view(store, "d1")
        assert os.path.lexists(wt)
        assert row["cleanup_pending"] is True and row["worktree_cleanup_error"].startswith(PREFIX), row
    finally:
        if kind in ("link", "dangling") and os.path.lexists(wt):
            drop_link(wt)
    if kind == "link":
        assert (tmp_path / "link-target" / "keep.txt").exists()  # what the link points at is never touched


def test_a_look_that_fails_is_unknown_never_gone(tmp_path):
    folder = tmp_path / "wt"
    folder.mkdir()
    real = os.lstat

    def lstat(path, *args, **kwargs):
        if os.path.normcase(os.fspath(path)) == os.path.normcase(str(folder)):
            raise PermissionError(13, "Access is denied")
        return real(path, *args, **kwargs)

    os.lstat = lstat
    try:
        reason = cli._lane_removal_leftover(str(folder))
    finally:
        os.lstat = real
    assert reason is not None and reason.startswith(PREFIX) and "could not be established" in reason


def test_the_after_check_says_gone_only_for_an_absent_path(tmp_path):
    assert cli._lane_removal_leftover(str(tmp_path / "nothing-here")) is None
    folder = tmp_path / "there"
    folder.mkdir()
    assert cli._lane_removal_leftover(str(folder)).startswith(PREFIX)


@pytest.mark.skipif(sys.platform != "win32", reason="a junction-only checkout is a Windows case")
def test_a_checkout_that_is_only_a_junction_is_refused_before_git_and_its_target_is_untouched(
    tmp_path, monkeypatch, capsys
):
    root, base = _repo(tmp_path)
    wt = Path(_assign_worktree(root, base, "j1")["worktree_path"])
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep.txt").write_text("not the lane's")
    shutil.rmtree(wt)
    make_link(wt, target)
    calls = spies(monkeypatch)
    try:
        _run_raw(["lane", "abandon", "--id", "j1"], root)
    finally:
        drop_link(wt)
    assert ("git", ["worktree", "remove"]) not in calls
    assert (target / "keep.txt").read_text() == "not the lane's"


# ----------------------------------------------- 9. gc, Git lists none, a saved path that is not a full path


def test_gc_keeps_a_branch_whose_saved_path_is_relative_and_never_looks_it_up_from_here(tmp_path, monkeypatch, capsys):
    root, base = _repo(tmp_path)
    _assign_worktree(root, base, "r1")
    assert _run_raw(["lane", "abandon", "--id", "r1"], root) == 0
    path = Store(root).dir / "state" / "lanes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["lanes"]["r1"]["worktree_path"] = "no-such-folder-here"
    path.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()

    item = lane_item(capsys, ["lane", "gc", "--json"], root, "r1")

    assert item["branch_delete_checks_passed"] is False, item
    assert "branch_delete_command" not in item
    assert "not a full path" in item["reason"] or "relative" in item["reason"], item["reason"]


# ----------------------------------------------- 10. abandon refuses a delivered lane whose cleanup is at a leftover


@pytest.mark.parametrize("acknowledge", [False, True])
def test_abandon_refuses_a_delivered_lane_whose_cleanup_stopped_at_a_leftover_and_names_lane_deliver(
    tmp_path, monkeypatch, capsys, acknowledge
):
    root, wt = delivered_lane(tmp_path)
    store = Store(root)
    with monkeypatch.context() as patch:
        git_leaves(patch)
        deliver(root)
    before = view(store, "d1")
    assert before["cleanup_pending"] is True and before["status"] == lanes.STATUS_DELIVERED
    assert before["worktree_cleanup_error"].startswith(PREFIX)
    capsys.readouterr()

    code = _run_raw(
        ["lane", "abandon", "--id", "d1", *(["--acknowledge-missing-worktree"] if acknowledge else [])], root
    )

    err = capsys.readouterr().err
    assert code != 0 and view(store, "d1") == before
    assert "lane deliver --id d1" in err and "nothing was changed" in err.lower(), err
    # The step it names is the one that works: the person removes the folder, then runs it, as printed.
    printed = re.search(r"`(lane deliver --id d1)`", err)
    assert printed, err
    shutil.rmtree(wt)
    _git(root, "worktree", "prune")
    monkeypatch.setenv("AGENTTALK_SELF", "dev")
    calls = spies(monkeypatch)

    assert _run_raw(shlex.split(printed.group(1)), root) == 0

    after = view(store, "d1")
    assert after["status"] == lanes.STATUS_DELIVERED and after["cleanup_pending"] is False
    assert after["delivery_artifact"] == before["delivery_artifact"] and ("git", ["worktree", "remove"]) not in calls


# ---------------------------------------------------------------- 11. controls: a real removal still completes


def test_a_real_removal_still_completes_delivery_abandon_and_gc(tmp_path, capsys):
    root, wt = delivered_lane(tmp_path, "c1")
    assert deliver(root, "c1") == 0
    row = view(Store(root), "c1")
    assert not wt.exists() and row["cleanup_pending"] is False and row["worktree_state"] == lanes.STATUS_DELIVERED

    wt2 = Path(_assign_worktree(root, _git(root, "rev-parse", "HEAD").strip(), "c2")["worktree_path"])
    capsys.readouterr()
    assert _run_raw(["lane", "abandon", "--id", "c2", "--delete-branch", "--json"], root) == 0
    result = json.loads(capsys.readouterr().out)
    assert not wt2.exists() and "branch -d -- lane/c2" in result["branch_delete_command"]
    assert view(Store(root), "c2")["worktree_state"] == lanes.STATUS_ABANDONED


def test_a_real_gc_removal_still_completes_and_suggests_the_branch_command(tmp_path, monkeypatch, capsys):
    root, wt = abandoned_with_failed_removal(tmp_path, monkeypatch, "g2")
    capsys.readouterr()

    item = lane_item(capsys, ["lane", "gc", "--delete", "--json"], root, "g2")

    assert not wt.exists() and item["worktree_removed"] is True
    assert item["branch_delete_checks_passed"] is True and "branch -d -- lane/g2" in item["branch_delete_command"]


def test_the_release_check_reads_a_delivered_lane_that_holds_a_saved_leftover(tmp_path, monkeypatch):
    """#853/#843: the release check reads such a row as it reads any delivered lane: it names the leftover folder, and
    an unrelated checkout is not held by it."""
    from agenttalk import janitor, lane_occupancy, worktree_release

    root, wt = delivered_lane(tmp_path)
    other = root / ".worktrees" / "unrelated"
    _git(root, "worktree", "add", "-q", "-b", "unrelated", str(other))
    with monkeypatch.context() as patch:
        git_leaves(patch)
        deliver(root)
    assert wt.exists()
    cfg = janitor.JanitorConfig.load(root)

    assert worktree_release._free_lanes(cfg, wt, lane_occupancy.peek) == ["d1"]
    assert worktree_release._free_lanes(cfg, other, lane_occupancy.peek) == []  # raises Refused if the row held it


# ---------------------------------------------------------------- the refusal and the advice are keyed on the markers

MISSING = object()


def leftover_row(tmp_path, monkeypatch, **fields):
    """A delivered lane whose cleanup stopped at a leftover folder, then the saved row changed by `fields` (a value of
    MISSING removes the field)."""
    root, wt = delivered_lane(tmp_path)
    with monkeypatch.context() as patch:
        git_leaves(patch)
        deliver(root)
    store = Store(root)
    path = store.dir / "state" / "lanes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["lanes"]["d1"]
    assert row["worktree_cleanup_error"].startswith(PREFIX)
    for key, value in fields.items():
        if value is MISSING:
            row.pop(key, None)
        else:
            row[key] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    return root, wt, store


@pytest.mark.parametrize("acknowledge", [False, True])
@pytest.mark.parametrize("pending", [None, "pending", MISSING])
def test_abandon_refuses_a_saved_leftover_when_the_cleanup_marker_is_not_exactly_true(
    tmp_path, monkeypatch, capsys, acknowledge, pending
):
    """`cleanup_recovery_required` (a complete publication, a cleanup marker that is not exactly false) is the rule, not
    the marker being exactly true: a null, missing or damaged marker is a delivered lane with unfinished cleanup too."""
    root, wt, store = leftover_row(tmp_path, monkeypatch, cleanup_pending=pending)
    before = lanes.load_lanes(store)["lanes"]["d1"]
    capsys.readouterr()

    code = _run_raw(
        ["lane", "abandon", "--id", "d1", *(["--acknowledge-missing-worktree"] if acknowledge else [])], root
    )

    err = capsys.readouterr().err
    assert code != 0 and lanes.load_lanes(store)["lanes"]["d1"] == before
    assert before["status"] == lanes.STATUS_DELIVERED and "lane deliver --id d1" in err, err


@pytest.mark.parametrize("acknowledge", [False, True])
@pytest.mark.parametrize("state", [MISSING, lanes.STATUS_DELIVERED, lanes.STATUS_CLEANUP_PENDING])
def test_the_abandon_refusal_does_not_depend_on_the_worktree_state(tmp_path, monkeypatch, capsys, acknowledge, state):
    """The refusal reads the markers and the saved reason; `worktree_state` is only a label."""
    root, wt, store = leftover_row(tmp_path, monkeypatch, worktree_state=state)
    before = lanes.load_lanes(store)["lanes"]["d1"]
    capsys.readouterr()

    code = _run_raw(
        ["lane", "abandon", "--id", "d1", *(["--acknowledge-missing-worktree"] if acknowledge else [])], root
    )

    err = capsys.readouterr().err
    assert code != 0 and lanes.load_lanes(store)["lanes"]["d1"] == before
    assert "lane deliver --id d1" in err, err


@pytest.mark.parametrize("publish", [MISSING, None])
def test_status_offers_the_leftover_step_only_when_the_publication_marker_is_exactly_false(
    tmp_path, monkeypatch, capsys, publish
):
    """With a missing or null publication marker `lane deliver` exits 2, so the status must keep the marker-repair
    advice and not tell the person to remove the folder and run it. (Exactly false: test 1 shows the leftover step.)"""
    root, wt, store = leftover_row(tmp_path, monkeypatch, publish_pending=publish)
    capsys.readouterr()

    assert _run_raw(["lane", "status"], root) == 0
    status = capsys.readouterr().out
    assert deliver(root) == 2  # the step the leftover advice would have named cannot run
    capsys.readouterr()

    line = next(line for line in status.splitlines() if "d1" in line)
    assert "lane deliver --id d1" not in line and "remove the folder" not in line, line
    assert "lane recover" in line, line


def test_a_saved_leftover_with_a_damaged_checkout_field_keeps_the_damage_step_that_works(tmp_path, monkeypatch, capsys):
    """The refusal is not for a damaged checkout field: `lane deliver` refuses there, and the acknowledgement named in
    the damage message (#771) is the step that works. With the folder gone, that step runs as it did before."""
    root, wt, store = leftover_row(tmp_path, monkeypatch, worktree_path="")
    shutil.rmtree(wt)
    capsys.readouterr()

    code = _run_raw(["lane", "abandon", "--id", "d1", "--acknowledge-missing-worktree"], root)

    assert code == 0, capsys.readouterr().err
    assert lanes.load_lanes(store)["lanes"]["d1"]["status"] == lanes.STATUS_ABANDONED


# ------------------------------------------- the advice is built on `lane deliver` only when it can finish the lane


def broken_evidence(tmp_path, kind):
    if kind == "null":
        return None
    if kind == "no-file":
        return str(tmp_path / "gone" / "delivery.json")
    garbage = tmp_path / "garbage.json"
    garbage.write_text("not a delivery artifact", encoding="utf-8")
    return str(garbage)


@pytest.mark.parametrize("kind", ["null", "no-file", "garbage"])
def test_status_does_not_tell_the_person_to_remove_the_folder_when_deliver_cannot_finish(
    tmp_path, monkeypatch, capsys, kind
):
    """With the delivery evidence missing or invalid, `lane deliver` exits 2 whatever happens to the folder: the
    remove-then-deliver step is not shown."""
    root, wt, store = leftover_row(tmp_path, monkeypatch, delivery_artifact=broken_evidence(tmp_path, kind))
    capsys.readouterr()

    assert _run_raw(["lane", "status"], root) == 0
    status = capsys.readouterr().out

    line = next(line for line in status.splitlines() if "d1" in line)
    assert "remove the folder" not in line and "lane deliver --id d1" not in line, line
    shutil.rmtree(wt)
    monkeypatch.setenv("AGENTTALK_SELF", "dev")
    assert deliver(root) == 2  # the step it would have named cannot run


@pytest.mark.parametrize("kind", ["null", "no-file", "garbage"])
def test_abandon_does_not_refuse_a_delivered_leftover_lane_that_deliver_cannot_finish(
    tmp_path, monkeypatch, capsys, kind
):
    """No refusal then: today's way out stays. Plain abandon records the lane as abandoned and keeps the leftover
    reason; the step status then prints for an abandoned lane runs once the folder is gone."""
    root, wt, store = leftover_row(tmp_path, monkeypatch, delivery_artifact=broken_evidence(tmp_path, kind))
    capsys.readouterr()

    assert _run_raw(["lane", "abandon", "--id", "d1"], root) == 0

    row = lanes.load_lanes(store)["lanes"]["d1"]
    assert row["status"] == lanes.STATUS_ABANDONED and row["worktree_cleanup_error"].startswith(PREFIX)
    capsys.readouterr()
    assert _run_raw(["lane", "status"], root) == 0
    printed = re.search(r"`(lane abandon --id d1 --acknowledge-missing-worktree)`", capsys.readouterr().out)
    assert printed, "status names no acknowledgement step"
    shutil.rmtree(wt)

    assert _run_raw(shlex.split(printed.group(1)), root) == 0
    assert lanes.load_lanes(store)["lanes"]["d1"]["worktree_state"] == lanes.STATUS_CLEANUP_ACKNOWLEDGED


@pytest.mark.parametrize("kind", ["null", "no-file", "garbage"])
def test_the_acknowledgement_is_not_refused_either_when_deliver_cannot_finish(tmp_path, monkeypatch, capsys, kind):
    root, wt, store = leftover_row(tmp_path, monkeypatch, delivery_artifact=broken_evidence(tmp_path, kind))
    shutil.rmtree(wt)
    capsys.readouterr()

    code = _run_raw(["lane", "abandon", "--id", "d1", "--acknowledge-missing-worktree"], root)

    assert code == 0, capsys.readouterr().err
    assert lanes.load_lanes(store)["lanes"]["d1"]["status"] == lanes.STATUS_ABANDONED


# ------------------------------------------- malformed delivery evidence never crashes the recovery paths


@pytest.mark.parametrize("version", [[], {}, "three", 3.5])
@pytest.mark.parametrize("command", ["status", "abandon"])
def test_a_malformed_delivery_artifact_does_not_crash_status_or_abandon(
    tmp_path, monkeypatch, capsys, command, version
):
    """The shared validator can raise something other than LaneError on a malformed artifact (an integrity version that
    is a list raises TypeError). The check only decides what to advise: whatever goes wrong in it, the evidence is
    unusable, the recovery stays open and nothing crashes."""
    root, wt, store = leftover_row(tmp_path, monkeypatch)
    artifact = Path(lanes.load_lanes(store)["lanes"]["d1"]["delivery_artifact"])
    content = json.loads(artifact.read_text(encoding="utf-8"))
    content["integrity_version"] = version
    artifact.write_text(json.dumps(content), encoding="utf-8")
    capsys.readouterr()

    code = _run_raw(["lane", "status"] if command == "status" else ["lane", "abandon", "--id", "d1"], root)

    out = capsys.readouterr()
    assert code == 0, out.err
    if command == "status":
        line = next(line for line in out.out.splitlines() if "d1" in line)
        assert "remove the folder" not in line and "lane deliver" not in line and "lane abandon --id d1" in line, line
    else:
        assert lanes.load_lanes(store)["lanes"]["d1"]["status"] == lanes.STATUS_ABANDONED


@pytest.mark.parametrize("kind", ["null", "no-file", "garbage"])
def test_status_names_the_way_out_when_deliver_cannot_finish_instead_of_telling_to_run_it(
    tmp_path, monkeypatch, capsys, kind
):
    """With the evidence missing or invalid `lane deliver` exits 2, so status does not say to run it: it names plain
    `lane abandon`, which is open there, and what to do first."""
    root, wt, store = leftover_row(tmp_path, monkeypatch, delivery_artifact=broken_evidence(tmp_path, kind))
    capsys.readouterr()

    assert _run_raw(["lane", "status"], root) == 0
    line = next(line for line in capsys.readouterr().out.splitlines() if "d1" in line)

    assert "lane deliver" not in line and "lane abandon --id d1" in line, line
    assert "inspect the folder" in line and "evidence" in line, line


# ------------------------------- an abandon through the leftover shortcut keeps a pending cleanup state in the row


def damage_evidence(tmp_path, store, kind):
    """Make the delivery evidence of lane d1 unusable in the way `kind` names."""
    path = store.dir / "state" / "lanes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["lanes"]["d1"]
    artifact = Path(row["delivery_artifact"])
    if kind == "null":
        row["delivery_artifact"] = None
    elif kind == "no-file":
        row["delivery_artifact"] = str(tmp_path / "gone" / "delivery.json")
    elif kind == "invalid-json":
        artifact.write_text("{not json", encoding="utf-8")
    elif kind == "bad-integrity":
        content = json.loads(artifact.read_text(encoding="utf-8"))
        content["integrity_version"] = []
        artifact.write_text(json.dumps(content), encoding="utf-8")
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("label", [MISSING, lanes.STATUS_DELIVERED], ids=["state-missing", "state-delivered"])
@pytest.mark.parametrize("kind", ["null", "no-file", "invalid-json", "bad-integrity"])
def test_abandon_through_the_leftover_shortcut_keeps_the_folder_listed_with_its_acknowledge_step(
    tmp_path, monkeypatch, capsys, kind, label
):
    """The shortcut keeps the saved leftover reason and calls nothing; the row must also keep a pending cleanup state,
    or the abandoned-lane listing (which shows only cleanup pending or failed) hides the folder and the step."""
    root, wt, store = leftover_row(tmp_path, monkeypatch, worktree_state=label)
    damage_evidence(tmp_path, store, kind)
    capsys.readouterr()
    assert _run_raw(["lane", "abandon", "--id", "d1"], root) == 0
    capsys.readouterr()

    assert _run_raw(["lane", "status"], root) == 0
    status = capsys.readouterr().out

    row = lanes.load_lanes(store)["lanes"]["d1"]
    assert row["status"] == lanes.STATUS_ABANDONED and row["worktree_state"] in (
        lanes.STATUS_CLEANUP_FAILED,
        lanes.STATUS_CLEANUP_PENDING,
    )
    assert "active lanes: none" not in status or "abandoned lanes with the worktree cleanup" in status, status
    line = next(line for line in status.splitlines() if line.strip().startswith("d1:"))
    assert PREFIX in line or str(wt) in line, line
    printed = re.search(r"`(lane abandon --id d1 --acknowledge-missing-worktree)`", line)
    assert printed, line
    shutil.rmtree(wt)

    assert _run_raw(shlex.split(printed.group(1)), root) == 0
    assert lanes.load_lanes(store)["lanes"]["d1"]["worktree_state"] == lanes.STATUS_CLEANUP_ACKNOWLEDGED
