"""Real Git witnesses; isolated repositories, no network or flag-clearing repair."""

import os
import json
from pathlib import Path

import pytest
import test_acceptance as acceptance_fixtures

from agenttalk import acceptance, acceptance_git, cli, git_index_safety as safety, lanes
from agenttalk.store import Store
from test_hidden_index_real import _flagged
from test_lanes import _assign_worktree, _commit, _git, _lane_branch_present, _repo, _run_raw, _786_assign_args

case = acceptance_fixtures.case
case_v2 = acceptance_fixtures.case_v2


@pytest.mark.parametrize("consumer", ["lane", "acceptance"])
@pytest.mark.parametrize("flag", ["assume", "skip", "both"])
@pytest.mark.parametrize("edited", [False, True])
def test_flagged_checkout_refuses_without_changing_bytes_or_flags(tmp_path, capsys, consumer, flag, edited):
    root, base = _repo(tmp_path)
    lane = _assign_worktree(root, base)
    project = Path(lane["worktree_path"]) if consumer == "lane" else root
    file, data = _flagged(project, flag, edited)
    before = _git(project, "ls-files", "-v", "-z")
    capsys.readouterr()
    if consumer == "lane":
        with pytest.raises(lanes.LaneError, match="not verified clean"):
            cli._verify_lane_worktree(Store(root), lane)
        assert _run_raw(["lane", "check", "--id", lane["lane_id"]], root) == 2
        assert _run_raw(["lane", "deliver", "--id", lane["lane_id"], "--from", "dev"], root) == 3
        saved = lanes.load_lanes(Store(root))["lanes"][lane["lane_id"]]
        assert saved["status"] == lanes.STATUS_ACTIVE
        assert not list((Store(root).dir / "lane-deliveries").glob("*.json"))
    else:
        with pytest.raises(acceptance.AcceptanceError) as error:
            acceptance.verify_project(project, base)
        assert error.value.code == "acceptance_project_unverified"
        acceptance.verify_project(project, base, live=False)
    assert "Checkout folder:" in capsys.readouterr().err
    assert file.read_bytes() == data
    assert _git(project, "ls-files", "-v", "-z") == before


def test_converse_checkout_roots_do_not_poison_clean_consumers(tmp_path):
    root, base = _repo(tmp_path)
    lane = _assign_worktree(root, base)
    wt = Path(lane["worktree_path"])
    original = (root / "src/core/a.py").read_bytes()
    _flagged(root, "assume")
    assert cli._verify_lane_worktree(Store(root), lane)["tracked_tree_clean"] is True
    _git(root, "update-index", "--no-assume-unchanged", "src/core/a.py")
    (root / "src/core/a.py").write_bytes(original)
    _flagged(wt, "assume")
    assert acceptance.verify_project(root, base)["revision"] == base


@pytest.mark.parametrize("value", ["true", "yes", "1"])
def test_ignore_stat_refuses_assign_before_folder_or_branch(tmp_path, capsys, value):
    root, base = _repo(tmp_path)
    _git(root, "config", "core.ignoreStat", value)
    args = _786_assign_args(root, base, "ignored")
    assert _run_raw(args, root) == 2
    assert "core.ignoreStat" in capsys.readouterr().err
    assert not _lane_branch_present(root, "ignored")
    assert not (root / ".worktrees").exists()
    assert "ignored" not in lanes.load_lanes(Store(root)).get("lanes", {})
    with pytest.raises(acceptance.AcceptanceError, match="core.ignoreStat") as error:
        acceptance.verify_project(root, base)
    assert error.value.code == "acceptance_project_unverified"


@pytest.mark.parametrize(
    "mode",
    [
        "untracked",
        "tracked-config",
        "tracked-config-dirty",
        "tracked-modules",
        "tracked-modules-dirty",
        "tracked-diff",
        "head",
        "clean",
    ],
)
def test_submodule_policy_is_tracked_only_for_lanes(tmp_path, mode):
    folder = tmp_path / "project"
    folder.mkdir()
    root, _ = _repo(folder)
    source = tmp_path / "local-submodule"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Synthetic Author")
    _git(source, "config", "user.email", "synthetic@example.invalid")
    _commit(source, "tracked", "base\n")
    _git(root, "-c", "protocol.file.allow=always", "submodule", "add", str(source), "src/core/sub")
    if mode.startswith("tracked-modules"):
        _git(
            root,
            "config",
            "-f",
            ".gitmodules",
            "submodule.src/core/sub.ignore",
            "dirty" if mode.endswith("dirty") else "all",
        )
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "local submodule")
    base = _git(root, "rev-parse", "HEAD").strip()
    lane = _assign_worktree(root, base)
    wt = Path(lane["worktree_path"])
    _git(wt, "-c", "protocol.file.allow=always", "submodule", "update", "--init")
    sub = wt / "src/core/sub"
    if mode == "untracked":
        (sub / "output").write_bytes(b"build output")
    elif mode.startswith("tracked"):
        if mode.startswith("tracked-config"):
            _git(wt, "config", "submodule.src/core/sub.ignore", "dirty" if mode.endswith("dirty") else "all")
        elif mode == "tracked-diff":
            _git(wt, "config", "diff.ignoreSubmodules", "all")
        (sub / "tracked").write_bytes(b"hidden tracked edit")
        assert not _git(wt, "status", "--porcelain", "--untracked-files=no").strip()
    elif mode == "head":
        _git(sub, "config", "user.name", "Synthetic Author")
        _git(sub, "config", "user.email", "synthetic@example.invalid")
        _commit(sub, "tracked", "moved head\n")
    if mode in {"clean", "untracked"}:
        assert cli._verify_lane_worktree(Store(root), lane)["tracked_tree_clean"] is True
    else:
        with pytest.raises(lanes.LaneError, match="tracked changes"):
            cli._verify_lane_worktree(Store(root), lane)
    if mode == "clean":
        acceptance.verify_project(wt, base)
    else:
        with pytest.raises(acceptance.AcceptanceError, match="dirty"):
            acceptance.verify_project(wt, base)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits drive-like Git names")
@pytest.mark.parametrize("consumer", ["lane", "acceptance"])
def test_posix_drive_name_is_clean_then_hidden(tmp_path, consumer):
    root, _ = _repo(tmp_path)
    (root / "C:").mkdir()
    base = _commit(root, "C:/tracked", "base\n")
    lane = _assign_worktree(root, base)
    project = Path(lane["worktree_path"]) if consumer == "lane" else root
    if consumer == "lane":
        assert cli._verify_lane_worktree(Store(root), lane)["tracked_tree_clean"] is True
    else:
        acceptance.verify_project(project, base)
    _git(project, "update-index", "--assume-unchanged", "--", "C:/tracked")
    (project / "C:/tracked").write_bytes(b"hidden edit")
    assert not _git(project, "status", "--porcelain").strip()
    with pytest.raises((lanes.LaneError, acceptance.AcceptanceError), match="not verified clean"):
        if consumer == "lane":
            cli._verify_lane_worktree(Store(root), lane)
        else:
            acceptance.verify_project(project, base)
    if consumer == "lane":
        assert _run_raw(["lane", "check", "--id", lane["lane_id"]], root) == 2
        assert _run_raw(["lane", "deliver", "--id", lane["lane_id"], "--from", "dev"], root) == 3
    assert (project / "C:/tracked").read_bytes() == b"hidden edit"


def test_acceptance_each_live_boundary_observes_new_flag(tmp_path):
    root, base = _repo(tmp_path)
    with acceptance_git.command_scope():
        acceptance.verify_project(root, base)
        _flagged(root, "assume")
        with pytest.raises(acceptance.AcceptanceError, match="not verified clean"):
            acceptance.verify_project(root, base)
        assert acceptance.verify_project(root, base, live=False)["revision"] == base
    assert safety.check_hidden_index(root).state == "hidden"


def _acceptance_flag(case):
    root = case["project"]
    _git(root, "update-index", "--assume-unchanged", "--", "source.txt")
    (root / "source.txt").write_bytes(b"hidden acceptance edit\n")
    assert "h source.txt\0" in _git(root, "ls-files", "-v", "-z")
    assert not _git(root, "status", "--porcelain").strip()


@pytest.mark.parametrize("boundary", ["prepare", "freeze", "attach", "publish"])
def test_acceptance_late_flags_hold_without_success_evidence(case_v2, monkeypatch, capsys, boundary):
    from agenttalk import close

    case = case_v2
    if boundary == "prepare":
        _acceptance_flag(case)
    if boundary == "freeze":
        original = acceptance.prepare

        def prepare(*args, **kwargs):
            result = original(*args, **kwargs)
            _acceptance_flag(case)
            return result

        monkeypatch.setattr(acceptance, "prepare", prepare)
    result = acceptance_fixtures.open_attempt(case)
    if boundary in {"prepare", "freeze"}:
        assert result == 3
        if close.close_path(case["store"], "attempt").exists():
            record = close.load_close(case["store"], "attempt")
            route = record.get("acceptance_route")
            assert route is None or not route.get("bundle_hash")
            assert record.get("final") is None
        assert "acceptance_project_unverified" in capsys.readouterr().err
        return
    assert result == 0
    acceptance_fixtures.bundle_v2(case)
    if boundary == "attach":
        _acceptance_flag(case)
        assert acceptance_fixtures.attach(case) == 2
        record = close.load_close(case["store"], "attempt")
        assert record["acceptance_route"]["bundle_hash"] is None
    else:
        assert acceptance_fixtures.attach(case) == 0
        acceptance_fixtures.accept_all(case)
        _acceptance_flag(case)
        assert acceptance_fixtures.command(case, "publish", "--id", "attempt", "--from", "lead", "--verdict", "go") == 3
        record = close.load_close(case["store"], "attempt")
        assert not record.get("final") or record["final"]["verdict"] != "GO"
    output = capsys.readouterr()
    assert "acceptance_project_unverified" in output.out + output.err
    assert "Checkout folder:" in output.err


@pytest.mark.parametrize("boundary", ["final", "terminal"])
def test_lane_late_flags_stop_delivery_after_evaluation(tmp_path, monkeypatch, capsys, boundary):
    root, base = _repo(tmp_path)
    lane = _assign_worktree(root, base)
    wt = Path(lane["worktree_path"])
    target_before = _git(root, "rev-parse", lane["target_ref"]).strip()
    _commit(wt, "src/core/a.py", "base\ndelivered\n")
    original = cli._lane_eval
    calls = []

    def evaluate(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result)
        # Initial evaluation is followed by a final check; terminal evaluation
        # runs after the pending delivery is retained and is checked again.
        if len(calls) == (1 if boundary == "final" else 2):
            _flagged(wt, "assume")
        return result

    monkeypatch.setattr(cli, "_lane_eval", evaluate)
    assert _run_raw(["lane", "deliver", "--id", lane["lane_id"], "--from", "dev"], root) == 3
    assert len(calls) >= (1 if boundary == "final" else 2)
    saved = lanes.load_lanes(Store(root))["lanes"][lane["lane_id"]]
    assert saved["status"] != lanes.STATUS_DELIVERED
    assert wt.is_dir() and _lane_branch_present(root, lane["lane_id"])
    assert _git(root, "rev-parse", lane["target_ref"]).strip() == target_before
    artifacts = (Store(root).dir / "lane-deliveries").glob("*.json")
    assert all(json.loads(path.read_text())["artifact_state"] != lanes.ARTIFACT_COMMITTED for path in artifacts)
    assert (wt / "src/core/a.py").read_bytes() == b"precious hidden work\n"
    assert "Checkout folder:" in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["cone", "non-cone", "sparse-index"])
def test_sparse_omissions_pass_but_materialized_flags_refuse(tmp_path, mode):
    root, _ = _repo(tmp_path)
    (root / "included").mkdir()
    (root / "omitted").mkdir()
    _commit(root, "included/a", "included\n")
    base = _commit(root, "omitted/b", "omitted\n")
    lane = _assign_worktree(root, base)
    wt = Path(lane["worktree_path"])
    init = ["sparse-checkout", "init", "--no-cone" if mode == "non-cone" else "--cone"]
    if mode == "sparse-index":
        init.append("--sparse-index")
    _git(wt, *init)
    _git(wt, "sparse-checkout", "set", "included")
    assert not (wt / "omitted/b").exists()
    assert "S omitted/b\0" in _git(wt, "ls-files", "-v", "-z")
    assert cli._verify_lane_worktree(Store(root), lane)["tracked_tree_clean"] is True
    acceptance.verify_project(wt, base)
    _git(wt, "config", "sparse.expectFilesOutsideOfPatterns", "true")
    (wt / "omitted").mkdir(exist_ok=True)
    (wt / "omitted/b").write_bytes(b"hidden sparse work")
    assert "S omitted/b\0" in _git(wt, "ls-files", "-v", "-z")
    with pytest.raises(lanes.LaneError, match="not verified clean"):
        cli._verify_lane_worktree(Store(root), lane)
    with pytest.raises(acceptance.AcceptanceError, match="not verified clean"):
        acceptance.verify_project(wt, base)


def test_top_level_untracked_policy_stays_distinct(tmp_path):
    root, base = _repo(tmp_path)
    lane = _assign_worktree(root, base)
    wt = Path(lane["worktree_path"])
    (wt / "untracked-output").write_bytes(b"output")
    assert cli._verify_lane_worktree(Store(root), lane)["tracked_tree_clean"] is True
    with pytest.raises(acceptance.AcceptanceError, match="dirty"):
        acceptance.verify_project(wt, base)


def test_nested_bus_and_foreign_index_cannot_hide_project_flags(tmp_path, monkeypatch):
    root, base = _repo(tmp_path)
    lane = _assign_worktree(root, base)
    wt = Path(lane["worktree_path"])
    bus = root / "nested-bus"
    bus.mkdir()
    (root / ".git/info/exclude").write_text("nested-bus/\n", encoding="utf-8")
    Store(bus).init(["lead"])
    _flagged(root, "assume")
    foreign_git = _git(wt, "rev-parse", "--absolute-git-dir").strip()
    monkeypatch.setenv("GIT_DIR", foreign_git)
    monkeypatch.setenv("GIT_INDEX_FILE", str(Path(foreign_git) / "index"))
    monkeypatch.setenv("GIT_WORK_TREE", str(wt))
    with pytest.raises(acceptance.AcceptanceError, match="not verified clean"):
        acceptance.verify_project(root, base)


def test_assignment_refuses_a_flag_planted_before_initial_verification(tmp_path, monkeypatch, capsys):
    root, base = _repo(tmp_path)
    original = cli._verify_lane_worktree
    planted = []

    def verify(store, lane, **kwargs):
        wt = Path(lane["worktree_path"])
        planted.append((wt, *_flagged(wt, "assume")))
        return original(store, lane, **kwargs)

    monkeypatch.setattr(cli, "_verify_lane_worktree", verify)
    assert _run_raw(_786_assign_args(root, base, "initial-flag"), root) == 2
    assert "not verified clean" in capsys.readouterr().err
    assert len(planted) == 1
    wt, file, data = planted[0]
    assert wt.is_dir() and file.read_bytes() == data
    assert _lane_branch_present(root, "initial-flag")
    assert "initial-flag" not in lanes.load_lanes(Store(root)).get("lanes", {})


def test_acceptance_ignore_stat_refuses_before_status(tmp_path, monkeypatch):
    root, base = _repo(tmp_path)
    _git(root, "config", "core.ignoreStat", "true")
    original = acceptance.subprocess.run

    def run(argv, **kwargs):
        if "status" in argv or "ls-files" in argv:
            pytest.fail("ignoreStat must refuse before status or index inspection")
        return original(argv, **kwargs)

    monkeypatch.setattr(acceptance.subprocess, "run", run)
    with pytest.raises(acceptance.AcceptanceError, match="core.ignoreStat") as error:
        acceptance.verify_project(root, base)
    assert error.value.code == "acceptance_project_unverified"
    assert _git(root, "config", "--bool", "--get", "core.ignoreStat").strip() == "true"
