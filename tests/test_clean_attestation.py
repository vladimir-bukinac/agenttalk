"""Consumer boundaries with controlled read failures and independent checkout roots."""

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from agenttalk import acceptance, acceptance_git, cli, git_index_safety as safety, lanes

SHA = "a" * 40


@pytest.fixture
def lane_reads(tmp_path, monkeypatch):
    root = tmp_path / "lane"
    root.mkdir()
    store = SimpleNamespace(root=tmp_path / "store")
    lane = {"lane_id": "clean", "worktree_path": str(root)}
    monkeypatch.setattr(cli, "_common_git_dir", lambda path: "common")
    monkeypatch.setattr(cli, "_git_dir", lambda path: "linked")
    monkeypatch.setattr(cli, "_git_read_one", lambda path, args, label: str(root) if "--show-toplevel" in args else SHA)
    calls = []

    def read(path, args):
        calls.append((path, args))
        return (0, "lane/clean") if args[0] == "symbolic-ref" else (0, "")

    monkeypatch.setattr(cli, "_git", read)
    return store, lane, root, calls


@pytest.mark.parametrize("listing", [b"h file\0", b"s absent\0", b"broken", b"H ../escape\0"])
def test_lane_clean_status_requires_index_inspection(lane_reads, monkeypatch, capsys, listing):
    store, lane, root, calls = lane_reads
    reads = []

    def run(argv, **kwargs):
        reads.append((argv, kwargs))
        if "--show-toplevel" in argv:
            return subprocess.CompletedProcess(argv, 0, os.fsencode(root) + b"\n")
        return subprocess.CompletedProcess(argv, 0, listing)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(lanes.LaneError, match="not verified clean") as error:
        cli._verify_lane_worktree(store, lane)
    assert "Checkout folder:" not in str(error.value)
    assert reads[0][0][:3] == ["git", "-C", str(root)]
    assert reads[0][1].get("env") is None
    assert "Checkout folder:" in capsys.readouterr().err
    assert calls[-1] == (str(root), safety.status_args("no"))


def test_lane_safe_inspection_returns_provenance(lane_reads, monkeypatch):
    store, lane, root, calls = lane_reads
    monkeypatch.setattr(safety, "check_hidden_index_at_root", lambda path: safety.Inspection("safe"))
    assert cli._verify_lane_worktree(store, lane)["tracked_tree_clean"] is True
    assert calls[-1] == (str(root), safety.status_args("no"))


@pytest.mark.parametrize(
    "option",
    ["core.fsmonitor=false", "core.untrackedCache=false", "--ignore-submodules=untracked", "--untracked-files=no"],
)
def test_lane_status_cannot_accept_plausible_cached_clean(lane_reads, monkeypatch, option):
    store, lane, _, _ = lane_reads
    monkeypatch.setattr(safety, "check_hidden_index_at_root", lambda path: safety.Inspection("safe"))

    def read(path, args):
        if args[0] == "symbolic-ref":
            return 0, "lane/clean"
        return 0, " M file" if option in args else ""

    monkeypatch.setattr(cli, "_git", read)
    with pytest.raises(lanes.LaneError, match="tracked changes"):
        cli._verify_lane_worktree(store, lane)


@pytest.fixture
def project_reads(tmp_path, monkeypatch):
    calls = []
    state = {"listing": b"H file\0", "config": "false", "head": SHA}

    def run(argv, **kwargs):
        assert argv[:3] == ["git", "-C", str(tmp_path)]
        assert kwargs.get("env") is not None, "project index must receive the sanitized environment"
        assert not any(key.upper().startswith("GIT_") for key in kwargs["env"])
        if argv[3:] == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(argv, 0, os.fsencode(tmp_path) + b"\n")
        calls.append(argv[3:])
        args = argv[3:]
        if "ls-files" in args:
            return subprocess.CompletedProcess(argv, 0, state["listing"])
        if "--show-toplevel" in args:
            out = str(tmp_path) + "\n" + SHA
        elif args == ["rev-parse", "HEAD", SHA + "^{tree}"]:
            out = state["head"] + "\n" + "b" * 40
        elif args == ["rev-parse", "HEAD"]:
            out = state["head"]
        elif args[0] == "rev-list":
            out = SHA
        elif "status" in args:
            out = ""
        elif args[0] == "config":
            out = state["config"]
        else:
            out = "b" * 40
        return subprocess.CompletedProcess(argv, 0, out)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("GIT_INDEX_FILE", "foreign-index")
    return tmp_path, calls, state


@pytest.mark.parametrize("listing", [b"h file\0", b"s absent\0", b"invalid", b"H /escape\0"])
def test_acceptance_refuses_hidden_or_unverifiable(project_reads, capsys, listing):
    root, calls, state = project_reads
    state["listing"] = listing
    with pytest.raises(acceptance.AcceptanceError, match="not verified clean") as error:
        acceptance.verify_project(root, SHA)
    assert error.value.code == "acceptance_project_unverified"
    assert "Checkout folder:" not in str(error.value)
    assert any(args[0] == "ls-files" for args in calls)
    # The guidance root query is separate from the sanitized attestation reads.
    assert "First save or inspect" in capsys.readouterr().err


def test_live_checks_are_repeated_but_historical_reads_skip_visibility(project_reads):
    root, calls, state = project_reads
    with acceptance_git.command_scope():
        acceptance.verify_project(root, SHA)
        state["listing"] = b"h file\0"
        with pytest.raises(acceptance.AcceptanceError):
            acceptance.verify_project(root, SHA)
        before = len(calls)
        acceptance.verify_project(root, SHA, live=False)
        assert len(calls) == before
    assert sum(args[0] == "ls-files" for args in calls) == 2
    assert sum("status" in args for args in calls) == 2


def test_live_head_recheck_precedes_cached_root_inspection(project_reads):
    root, calls, state = project_reads
    with acceptance_git.command_scope():
        acceptance.verify_project(root, SHA)
        state["head"] = "c" * 40
        calls.clear()
        with pytest.raises(acceptance.AcceptanceError, match="HEAD must equal"):
            acceptance.verify_project(root, SHA)
        assert calls == [["rev-parse", "HEAD"]]


def test_acceptance_names_ignore_stat(project_reads, capsys):
    root, _, state = project_reads
    state["config"] = "true"
    with pytest.raises(acceptance.AcceptanceError, match="core.ignoreStat") as error:
        acceptance.verify_project(root, SHA)
    assert error.value.code == "acceptance_project_unverified"
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "mode,pair", [("no", ("no", "untracked")), ("normal", ("normal", "none")), ("all", ("all", "none"))]
)
def test_only_fixed_status_policies(mode, pair):
    args = safety.status_args(mode)
    assert args == [
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "status",
        "--porcelain",
        f"--untracked-files={pair[0]}",
        f"--ignore-submodules={pair[1]}",
    ]
    args.clear()
    assert safety.status_args(mode)
    assert safety.STATUS_ARGS == safety.status_args("normal")
    with pytest.raises(ValueError):
        safety.status_args("arbitrary")


def test_at_root_rejects_relative_without_git(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("relative root reached Git"))
    assert safety.check_hidden_index_at_root(Path("relative")).state == "unverifiable"


@pytest.mark.parametrize("rc,value", [(0, "true"), (2, ""), (0, "invalid")])
def test_assignment_checks_boolean_setting_before_any_preparation(tmp_path, monkeypatch, capsys, rc, value):
    store = SimpleNamespace(root=tmp_path, load_config=lambda: {"agents": ["lead", "dev"]})
    monkeypatch.setattr(cli, "_get_store", lambda args: store)
    monkeypatch.setattr(cli, "_resolve_self", lambda *args, **kwargs: "lead")
    monkeypatch.setattr(cli, "_load_domain_registry", lambda store: SimpleNamespace(data={"domains": {"core": {}}}))
    calls = []

    def read(root, args):
        calls.append((root, args))
        return rc, value

    monkeypatch.setattr(cli, "_git", read)
    monkeypatch.setattr(cli, "_lane_resolve", lambda *args: pytest.fail("setting must be checked first"))
    monkeypatch.setattr(cli, "_prepare_worktrees_root", lambda *args: pytest.fail("must not create a folder"))
    args = cli.build_parser().parse_args(
        [
            "lane",
            "assign",
            "--id",
            "ignored",
            "--from",
            "lead",
            "--assignee",
            "dev",
            "--domain",
            "core",
            "--base",
            SHA,
            "--target",
            "main",
        ]
    )
    assert cli._cmd_lane(args) == 2
    assert calls == [(tmp_path, ["config", "--bool", "--get", "core.ignoreStat"])]
    output = capsys.readouterr().err
    assert "core.ignoreStat" in output
    if value == "true":
        assert "turn core.ignoreStat off" in output
        assert "assign again" in output
        assert "save or inspect" not in output


@pytest.mark.parametrize("consumer", ["lane", "acceptance"])
@pytest.mark.parametrize("fault", ["exit", "timeout", "oserror"])
def test_index_transport_failure_refuses(consumer, fault, lane_reads, project_reads, monkeypatch):
    original = subprocess.run

    def run(argv, **kwargs):
        if consumer == "lane" and "--show-toplevel" in argv:
            return subprocess.CompletedProcess(argv, 0, os.fsencode(lane_reads[2]) + b"\n")
        if "ls-files" in argv:
            if fault == "exit":
                return subprocess.CompletedProcess(argv, 1, b"H plausible\0")
            if fault == "timeout":
                raise subprocess.TimeoutExpired(argv, 15)
            raise OSError("index unavailable")
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    if consumer == "lane":
        with pytest.raises(lanes.LaneError, match="not verified clean"):
            cli._verify_lane_worktree(lane_reads[0], lane_reads[1])
    else:
        with pytest.raises(acceptance.AcceptanceError, match="not verified clean") as error:
            acceptance.verify_project(project_reads[0], SHA)
        assert error.value.code == "acceptance_project_unverified"


@pytest.mark.parametrize(
    "option", ["core.fsmonitor=false", "core.untrackedCache=false", "--ignore-submodules=none", "--untracked-files=all"]
)
def test_acceptance_status_cannot_accept_plausible_cached_clean(project_reads, monkeypatch, option):
    original = subprocess.run

    def run(argv, **kwargs):
        if "status" in argv:
            return subprocess.CompletedProcess(argv, 0, " M dirty" if option in argv else "")
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(acceptance.AcceptanceError, match="dirty"):
        acceptance.verify_project(project_reads[0], SHA)


@pytest.mark.parametrize("hidden", ["ignoreStat", "assume"])
def test_acceptance_cli_prints_refusal_once(project_reads, monkeypatch, capsys, hidden):
    root, _, state = project_reads
    state["config"] = "true" if hidden == "ignoreStat" else "false"
    state["listing"] = b"H file\0" if hidden == "ignoreStat" else b"h file\0"
    store = SimpleNamespace(root=root, load_config=lambda: {"agents": ["lead"]})
    monkeypatch.setattr(cli, "_get_store", lambda args: store)

    def prepare(*args, **kwargs):
        return acceptance.verify_project(root, SHA)

    monkeypatch.setattr(acceptance, "prepare", prepare)
    assert (
        cli.main(
            [
                "close",
                "open",
                "--id",
                "attempt",
                "--from",
                "lead",
                "--scope",
                "milestone",
                "--revision",
                SHA,
                "--acceptance-plan",
                "plan.json",
                "--project-repo",
                str(root),
            ]
        )
        == 3
    )
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert output.count("acceptance_project_unverified") == 1
    if hidden == "ignoreStat":
        assert output.count(safety.IGNORE_STAT) == 1
    else:
        assert output.count("First save or inspect") == 1
        assert output.count("not verified clean") == 1
