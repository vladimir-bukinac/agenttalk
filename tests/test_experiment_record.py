"""Tests for the experiment recorder (tests/experiment_record.py, audit step P3).

The record schema these tests read is documented in the module docstring of `experiment_record`; the field names
used here are the frozen ones.  Most tests start a real pytest (with two real xdist workers where it matters) in a
throw-away project made by `pytester`.  Plugin autoload is switched off and `-p xdist.plugin` is written out,
exactly as the development gate does.  The record folder is always a sibling of the inner run's basetemp, never
inside it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
HANDOFF_NAME = "AGENTTALK_EXPERIMENT_RECORD_HANDOFF"

CONFTEST = """
import experiment_record


def pytest_addoption(parser):
    experiment_record.add_option(parser)


def pytest_configure(config):
    experiment_record.configure(config)
"""

GROUPED = """
import pytest

pytestmark = pytest.mark.xdist_group("g1")


@pytest.mark.parametrize("value", ["one", "two", "three"])
def test_x(value):
    assert value
"""


@pytest.fixture
def er():
    import experiment_record

    return experiment_record


@pytest.fixture
def project(pytester, monkeypatch, er):
    """A throw-away project whose conftest wires the recorder the way tests/conftest.py does."""
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONPATH", str(TESTS_DIR))
    monkeypatch.delenv(HANDOFF_NAME, raising=False)
    pytester.makeconftest(CONFTEST)
    return pytester


def run_parallel(project, rec, *args):
    return project.runpytest_subprocess(
        "-p", "xdist.plugin", "-n", "2", "--dist", "loadgroup", f"--experiment-record={rec}", *args, timeout=180
    )


def run_serial(project, rec, *args):
    return project.runpytest_subprocess(f"--experiment-record={rec}", *args, timeout=180)


def collected_ids(project, *args):
    result = project.runpytest_subprocess("--collect-only", "-q", *args)
    return [line for line in result.outlines if "::" in line]


def read_journals(rec):
    """{file name: [record, ...]}.  Lines are split on "\\n" only: U+2028 is legal inside a record."""
    found = {}
    for path in sorted(Path(rec).glob("journal-*.jsonl")):
        text = path.read_bytes().decode("utf-8")
        found[path.name] = [json.loads(line) for line in text.split("\n") if line]
    return found


def records(rec, kind):
    return [(name, r) for name, recs in read_journals(rec).items() for r in recs if r["kind"] == kind]


def write_journal(
    rec,
    role,
    pid,
    *,
    worker=None,
    starts=(),
    trailer=True,
    extra=(),
    plugins=("xdist.plugin",),
    nested_token=None,
    loadgroup=True,
):
    """A hand-made, well-formed journal, for the reducer tests."""
    start = {"started_ms": 1000, "loadgroup": loadgroup, "nested_token": nested_token}
    if plugins is not None:
        start["plugins"] = list(plugins)
    events = [("process-start", start)]
    for raw, group in starts:
        suffixed = bool(group) and raw.endswith("@" + group)
        events.append(
            (
                "item-start",
                {
                    "nodeid": raw,
                    "requested_group": group,
                    "effective_group": group if suffixed else None,
                    "suffix_missing": bool(group) and not suffixed,
                },
            )
        )
        events.append(("item-end", {"nodeid": raw}))
    events.extend(extra)
    if trailer:
        events.append(("trailer", {"complete": True, "records": len(events), "exitstatus": 0}))
    lines = []
    for seq, (kind, fields) in enumerate(events, 1):
        lines.append(
            json.dumps(
                {
                    "v": 1,
                    "seq": seq,
                    "kind": kind,
                    "role": role,
                    "worker": worker,
                    "pid": pid,
                    "t_wall": 1000.0 + pid + seq / 100,
                    "t_mono": float(seq),
                    **fields,
                }
            )
        )
    path = Path(rec) / f"journal-{role}-{pid}-1000.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def kinds(problems):
    return {p["kind"] for p in problems}


# --- 1-2: the canonical id -------------------------------------------------------------------------------------


def test_a_parameter_filtered_group_member_joins_to_the_serial_collection(project, er, tmp_path):
    project.makepyfile(test_mod=GROUPED)
    selected = "test_mod.py::test_x[two]"
    expected = collected_ids(project, selected)
    assert expected == [selected]
    rec = tmp_path / "rec"

    run_parallel(project, rec, selected).assert_outcomes(passed=1)

    (start,) = [r for _, r in records(rec, "item-start")]
    assert start["nodeid"] == selected + "@g1"
    assert (start["requested_group"], start["effective_group"], start["suffix_missing"]) == ("g1", "g1", False)
    summary = er.reduce_journals(rec, expected)
    assert summary["accepted"], summary["problems"]
    assert list(summary["items"]) == [selected]


def test_a_parameter_containing_at_and_a_bracket_keeps_its_own_text(project, er, tmp_path):
    project.makepyfile(test_mod=GROUPED.replace('["one", "two", "three"]', '["a@b]", "c@g1", "d"]'))
    expected = collected_ids(project)
    assert len(expected) == 3
    rec = tmp_path / "rec"

    run_parallel(project, rec).assert_outcomes(passed=3)

    raw = sorted(r["nodeid"] for _, r in records(rec, "item-start"))
    assert raw == sorted(f"{i}@g1" for i in expected)
    summary = er.reduce_journals(rec, expected)
    assert summary["accepted"], summary["problems"]
    assert sorted(summary["items"]) == sorted(expected)
    assert "test_mod.py::test_x[c@g1]" in summary["items"]


def test_canonical_id_removes_a_suffix_only_when_it_equals_the_requested_group(er):
    assert er.canonical_id("t.py::t[a@b]]@g", "g") == "t.py::t[a@b]]"
    assert er.canonical_id("t.py::t[x@g]@g", "g") == "t.py::t[x@g]"  # only one suffix goes
    assert er.canonical_id("t.py::t[v@pwsh]", None) == "t.py::t[v@pwsh]"  # no group requested: nothing goes
    assert er.canonical_id("t.py::t[v]@other", "g") == "t.py::t[v]@other"  # a different suffix stays


# --- 3: a missing suffix is a flag, not acceptance ---------------------------------------------------------------


def test_a_missing_group_suffix_is_flagged_and_not_accepted(project, er, tmp_path):
    # A marker added by a plain-priority hook comes too late for xdist, which looks for markers first: the item
    # is in a group on paper, but its node id has no "@group" and the scheduler ignores it.
    project.makeconftest(
        CONFTEST
        + """
import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.xdist_group(name="g1"))
"""
    )
    project.makepyfile(test_mod="def test_a():\n    pass\n\n\ndef test_b():\n    pass\n")
    expected = collected_ids(project)
    rec = tmp_path / "rec"

    run_parallel(project, rec).assert_outcomes(passed=2)

    starts = [r for _, r in records(rec, "item-start")]
    assert starts and all(r["requested_group"] == "g1" and r["suffix_missing"] for r in starts)
    assert all(r["effective_group"] is None for r in starts)
    summary = er.reduce_journals(rec, expected)
    assert "suffix-missing" in kinds(summary["problems"])
    assert summary["accepted"] is False


# --- 4: the one-to-one join --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case, problem",
    [
        ("duplicate", "duplicate-id"),
        ("missing", "missing-id"),
        ("unexpected", "unexpected-id"),
    ],
)
def test_a_duplicate_missing_or_unexpected_id_fails_the_join(er, tmp_path, case, problem):
    expected = ["t.py::a", "t.py::b"]
    starts0 = [("t.py::a@g", "g")]
    starts1 = [("t.py::b@g", "g")]
    if case == "duplicate":
        starts1.append(("t.py::a@g", "g"))
    if case == "missing":
        starts1 = []
    if case == "unexpected":
        starts1.append(("t.py::zzz@g", "g"))
    write_journal(tmp_path, "worker", 11, worker="gw0", starts=starts0)
    write_journal(tmp_path, "worker", 12, worker="gw1", starts=starts1)

    summary = er.reduce_journals(tmp_path, expected)

    assert problem in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_an_exact_one_to_one_join_is_accepted(er, tmp_path):
    write_journal(tmp_path, "worker", 11, worker="gw0", starts=[("t.py::a@g1", "g1")])
    write_journal(tmp_path, "worker", 12, worker="gw1", starts=[("t.py::b@g2", "g2")])
    summary = er.reduce_journals(tmp_path, ["t.py::a", "t.py::b"])
    assert summary["accepted"], summary["problems"]
    assert summary["status"] == "complete"


# --- 5: cross-file pwsh members share one worker -----------------------------------------------------------------


def test_pwsh_members_of_two_files_run_on_one_worker_and_are_recorded_so(er, tmp_path):
    members = [
        "tests/test_supervisor.py::test_generated_ps1_is_bom_ascii_and_parses",
        "tests/test_coverage_producer.py::test_artifact_writer_refuses_reparse_output_parent",
    ]
    rec = tmp_path / "rec"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_ADDOPTS", "PYTHONPATH"))}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(SRC_DIR))
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "xdist.plugin",
            "-n",
            "2",
            "--dist",
            "loadgroup",
            f"--experiment-record={rec}",
            "--basetemp",
            str(tmp_path / "inner"),
            *members,
        ],
        cwd=TESTS_DIR.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode in (0, 1), done.stdout + done.stderr  # 2, 3 and 4 would be a broken run, not a test outcome

    summary = er.reduce_journals(rec, members)
    assert summary["accepted"], summary["problems"]
    assert {i["group"] for i in summary["items"].values()} == {"pwsh"}
    assert len(summary["groups"]["pwsh"]) == 1, summary["groups"]
    assert "group-split" not in kinds(summary["problems"])


def test_members_of_one_group_on_two_workers_are_a_group_split(er, tmp_path):
    write_journal(tmp_path, "worker", 11, worker="gw0", starts=[("t.py::a@pwsh", "pwsh")])
    write_journal(tmp_path, "worker", 12, worker="gw1", starts=[("u.py::b@pwsh", "pwsh")])
    summary = er.reduce_journals(tmp_path, ["t.py::a", "u.py::b"])
    assert "group-split" in kinds(summary["problems"])
    assert summary["accepted"] is False


# --- 6: a killed worker -------------------------------------------------------------------------------------------


def test_a_worker_killed_mid_test_leaves_its_started_item_and_no_trailer(project, er, tmp_path):
    project.makepyfile(
        test_mod="""
import os


def test_before():
    pass


def test_dies():
    os._exit(7)


def test_after():
    pass
"""
    )
    rec = tmp_path / "rec"

    run_parallel(project, rec, "--max-worker-restart=0")

    journals = read_journals(rec)
    dying = [
        name
        for name, recs in journals.items()
        if any(r["kind"] == "item-start" and r["nodeid"].endswith("::test_dies") for r in recs)
    ]
    assert len(dying) == 1, journals.keys()
    recs = journals[dying[0]]
    victim = [r for r in recs if r.get("nodeid", "").endswith("::test_dies")]
    assert [r["kind"] for r in victim][:2] == ["item-start", "phase"]
    assert victim[1]["when"] == "setup" and victim[1]["outcome"] == "passed"
    assert not any(r["kind"] == "phase" and r["when"] == "call" for r in victim)
    assert all(r["kind"] != "trailer" for r in recs)

    assert any(r["has_error"] and r["error_text"] for _, r in records(rec, "worker-down"))
    summary = er.reduce_journals(rec)
    assert summary["status"] == "incomplete"
    (process,) = [p for p in summary["processes"] if p["file"] == dying[0]]
    assert process["complete"] is False and process["records"] == len(recs)
    assert {"no-trailer", "item-unfinished"} <= kinds(summary["problems"])
    assert summary["accepted"] is False
    assert summary["first_error"] is not None


def test_a_missing_trailer_keeps_the_partial_records_and_is_incomplete(er, tmp_path):
    write_journal(tmp_path, "worker", 11, worker="gw0", starts=[("t.py::a@g", "g")], trailer=False)
    summary = er.reduce_journals(tmp_path, ["t.py::a"])
    assert summary["status"] == "incomplete"
    assert summary["items"]["t.py::a"]["started"] == 1
    assert "no-trailer" in kinds(summary["problems"])
    assert summary["accepted"] is False


# --- 7: the flag off ----------------------------------------------------------------------------------------------


def test_with_the_flag_off_nothing_is_registered_and_no_file_is_written(project, tmp_path):
    project.makepyfile(
        test_mod="""
import os

import experiment_record


def test_nothing_is_registered(pytestconfig):
    manager = pytestconfig.pluginmanager
    assert manager.get_plugin(experiment_record.PLUGIN_NAME) is None
    assert not [p for p in manager.get_plugins() if isinstance(p, experiment_record.Recorder)]
    assert experiment_record.HANDOFF_ENV not in os.environ
"""
    )
    result = project.runpytest_subprocess("-p", "xdist.plugin", "-n", "2", "--dist", "loadgroup", timeout=180)
    result.assert_outcomes(passed=1)
    assert not list(project.path.rglob("journal-*"))


def test_the_real_conftest_registers_the_recorder_only_when_asked(er, tmp_path):
    test = "tests/test_dev_gate.py::test_committed_pytest_timeout_has_wheel_leg_headroom"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_ADDOPTS", "PYTHONPATH"))}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(SRC_DIR))

    def run(*extra, name):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--trace-config",
                "--basetemp",
                str(tmp_path / name),
                test,
                *extra,
            ],
            cwd=TESTS_DIR.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

    off = run(name="off")
    assert off.returncode == 0, off.stdout + off.stderr
    assert "experiment_record.Recorder" not in off.stdout

    rec = tmp_path / "rec"
    on = run(f"--experiment-record={rec}", name="on")
    assert on.returncode == 0, on.stdout + on.stderr
    assert "experiment_record.Recorder" in on.stdout
    summary = er.reduce_journals(rec, [test])
    assert summary["accepted"], summary["problems"]
    assert [p["role"] for p in summary["processes"]] == ["serial"]


# --- 8-9: errors are records --------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["serial", "parallel"])
def test_a_module_that_raises_at_import_gives_a_collection_error_and_is_the_first_error(project, er, tmp_path, mode):
    project.makepyfile(test_ok="def test_ok():\n    pass\n", test_bad="raise RuntimeError('boom at import')\n")
    rec = tmp_path / "rec"

    (run_serial if mode == "serial" else run_parallel)(project, rec)

    found = records(rec, "collection-error")
    assert found and all(r["nodeid"] == "test_bad.py" for _, r in found)
    assert all("boom at import" in r["error_text"] for _, r in found)
    summary = er.reduce_journals(rec, ["test_ok.py::test_ok"])
    assert summary["first_error"]["kind"] == "collection-error"
    assert summary["first_error"]["nodeid"] == "test_bad.py"
    assert summary["accepted"] is False


def test_a_hook_that_raises_gives_an_internal_error_and_a_clean_trailer_does_not_hide_it(project, er, tmp_path):
    # The second plugin is registered after the recorder and answers the hook itself, as the terminal reporter
    # does: the recorder must still have recorded the error. (pytest 9.1 calls every implementation, so this check
    # cannot tell tryfirst apart there; on a pytest where the hook stops at the first answer it can.)
    project.makeconftest(
        """
import experiment_record


def pytest_addoption(parser):
    experiment_record.add_option(parser)


class Eater:
    def pytest_internalerror(self, excrepr):
        return True


def pytest_configure(config):
    experiment_record.configure(config)
    config.pluginmanager.register(Eater())


def pytest_runtest_logstart(nodeid, location):
    raise RuntimeError("hook exploded")
"""
    )
    project.makepyfile(test_mod="def test_a():\n    pass\n")
    rec = tmp_path / "rec"

    run_serial(project, rec)

    (journal,) = read_journals(rec).values()
    order = [r["kind"] for r in journal]
    assert "internal-error" in order
    assert order.index("internal-error") < order.index("exit-status") < order.index("trailer") == len(order) - 1
    assert journal[-1]["complete"] is True
    summary = er.reduce_journals(rec)
    assert summary["status"] == "complete"
    assert summary["first_error"]["kind"] == "internal-error"
    assert "hook exploded" in summary["first_error"]["error_text"]
    assert summary["accepted"] is False


def test_the_first_error_is_never_replaced_by_a_later_one(er, tmp_path):
    first = ("collection-error", {"nodeid": "a.py", "error_text": "first"})
    later = ("internal-error", {"error_text": "later"})
    write_journal(tmp_path, "serial", 11, extra=[first, later, ("exit-status", {"exitstatus": 3})])
    summary = er.reduce_journals(tmp_path)
    assert summary["first_error"]["error_text"] == "first"


# --- 10: every event is fsynced -----------------------------------------------------------------------------------


def test_every_journal_event_calls_fsync_once_on_the_journal_file(project, monkeypatch, tmp_path):
    project.makepyfile(test_mod="def test_a():\n    pass\n\n\ndef test_b():\n    pass\n")
    rec = tmp_path / "rec"
    real_fsync = os.fsync
    seen = []

    def counting_fsync(fd):
        info = os.fstat(fd)
        seen.append((info.st_dev, info.st_ino))
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    project.runpytest_inprocess(f"--experiment-record={rec}").assert_outcomes(passed=2)
    monkeypatch.undo()

    (journal,) = Path(rec).glob("journal-*.jsonl")
    info = os.stat(journal)
    events = len([line for line in journal.read_bytes().split(b"\n") if line])
    assert events >= 8
    assert seen.count((info.st_dev, info.st_ino)) == events


# --- D06: the plugin inventory -------------------------------------------------------------------------------------


def test_every_process_records_the_plugins_it_loaded_and_a_missing_field_is_flagged(project, er, tmp_path):
    project.makepyfile(test_mod="def test_a():\n    pass\n\n\ndef test_b():\n    pass\n")
    rec = tmp_path / "rec"
    run_parallel(project, rec).assert_outcomes(passed=2)

    starts = records(rec, "process-start")
    assert {r["role"] for _, r in starts} >= {"controller", "worker"}
    for _, r in starts:
        assert isinstance(r["plugins"], list) and "xdist.plugin" in r["plugins"], r["role"]
        assert r["plugins"] == sorted(r["plugins"])
    clean = er.reduce_journals(rec)
    assert "plugin-inventory-missing" not in kinds(clean["problems"])
    assert all(p["plugins"] and "xdist.plugin" in p["plugins"] for p in clean["processes"])

    # the control: the same record without the field is flagged
    name, _ = next((n, r) for n, r in starts if r["role"] == "worker")
    path = Path(rec) / name
    lines = path.read_bytes().decode("utf-8").split("\n")
    first = json.loads(lines[0])
    del first["plugins"]
    lines[0] = json.dumps(first, ensure_ascii=False)
    path.write_bytes("\n".join(lines).encode("utf-8"))
    flagged = er.reduce_journals(rec)
    assert "plugin-inventory-missing" in kinds(flagged["problems"])
    assert flagged["accepted"] is False


# --- D08: nested pytest runs ---------------------------------------------------------------------------------------

NESTED_CONFTEST = CONFTEST.replace("\n", "\\n")

NESTED_PARENT = """
import os
import subprocess
import sys

import experiment_record

CONFTEST = "{conftest}"


def launch(tmp_path, env):
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tmp_path / "test_child.py").write_text(
        "import os\\n\\n\\ndef test_child():\\n"
        f"    assert {experiment_record.HANDOFF_ENV!r} not in os.environ\\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "bt"),
         str(tmp_path / "test_child.py")],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120,
    )


def test_with_the_helper(tmp_path):
    done = launch(tmp_path, experiment_record.nested_environment())
    assert done.returncode == 0, done.stdout + done.stderr


def test_without_the_helper(tmp_path):
    assert experiment_record.HANDOFF_ENV not in os.environ
    done = launch(tmp_path, dict(os.environ))
    assert done.returncode == 0, done.stdout + done.stderr
""".replace("{conftest}", NESTED_CONFTEST)


def test_a_nested_run_started_with_the_helper_has_its_own_journal_tied_to_the_launch(project, er, tmp_path):
    project.makepyfile(test_parent=NESTED_PARENT)
    rec = tmp_path / "rec"

    run_serial(project, rec, "-k", "test_with_the_helper").assert_outcomes(passed=1)

    journals = read_journals(rec)
    assert len(journals) == 2, journals.keys()
    ((_, launch),) = records(rec, "nested-launch")
    ((_, parent_start),) = [(n, r) for n, r in records(rec, "process-start") if r["role"] == "serial"]
    ((_, nested_start),) = [(n, r) for n, r in records(rec, "process-start") if r["role"] == "nested"]
    assert nested_start["nested_token"] == launch["token"]
    assert nested_start["parent_pid"] == parent_start["pid"]
    assert nested_start["pid"] != parent_start["pid"]
    summary = er.reduce_journals(rec, ["test_parent.py::test_with_the_helper"])
    assert summary["accepted"], summary["problems"]
    assert summary["nested"] == {"launched": 1, "journaled": 1}
    assert sorted(p["role"] for p in summary["processes"]) == ["nested", "serial"]


def test_an_ordinary_nested_run_never_inherits_the_handoff(project, er, tmp_path):
    project.makepyfile(test_parent=NESTED_PARENT)
    rec = tmp_path / "rec"

    run_serial(project, rec, "-k", "test_without_the_helper").assert_outcomes(passed=1)

    assert list(read_journals(rec)) and len(read_journals(rec)) == 1
    assert [r["role"] for _, r in records(rec, "process-start")] == ["serial"]
    assert records(rec, "nested-launch") == []


def test_a_launch_without_a_nested_journal_is_a_failure_never_compliance(er, tmp_path):
    write_journal(
        tmp_path, "serial", 11, starts=[("t.py::a", None)], extra=[("nested-launch", {"token": "0123456789abcdef"})]
    )
    summary = er.reduce_journals(tmp_path, ["t.py::a"])
    assert "nested-journal-missing" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_nested_sessions_seen_elsewhere_but_not_journaled_are_a_failure(er, tmp_path):
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    assert er.reduce_journals(tmp_path, ["t.py::a"], nested_seen=0)["accepted"]
    summary = er.reduce_journals(tmp_path, ["t.py::a"], nested_seen=2)
    assert "nested-journal-missing" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_a_nested_journal_nobody_launched_is_flagged(er, tmp_path):
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    write_journal(tmp_path, "nested", 12, nested_token="fedcba9876543210")
    summary = er.reduce_journals(tmp_path, ["t.py::a"])
    assert "nested-journal-unlaunched" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_the_helper_without_a_recorder_hands_off_nothing_and_drops_a_stale_entry(er):
    env = er.nested_environment({"Agenttalk_Experiment_Record_Handoff": "stale", "A": "1"})
    assert env == {"A": "1"}


@pytest.mark.parametrize(
    "value, message",
    [
        ("not json", "is not valid JSON"),
        (json.dumps({"v": 1, "dir": "rel", "token": "0123456789abcdef", "parent_pid": 1}), "needs an absolute folder"),
        (
            json.dumps({"v": 1, "dir": "ABSOLUTE-MISSING", "token": "0123456789abcdef", "parent_pid": 1}),
            "not an existing",
        ),
        (json.dumps({"v": 1, "dir": "ABSOLUTE-OK", "token": "../../escape", "parent_pid": 1}), "has a bad token"),
        (json.dumps({"v": 2, "dir": "ABSOLUTE-OK", "token": "0123456789abcdef", "parent_pid": 1}), "not a version 1"),
        ("x" * 5000, "is too long"),
    ],
    ids=["not-json", "relative-dir", "missing-dir", "bad-token", "bad-version", "too-long"],
)
def test_a_bad_handoff_is_refused_and_the_message_names_it(project, monkeypatch, tmp_path, value, message):
    (tmp_path / "exists").mkdir()
    (project.path / "rel").mkdir()  # a relative folder that does exist from the run's own folder
    value = value.replace("ABSOLUTE-MISSING", json.dumps(str(tmp_path / "nope"))[1:-1])
    value = value.replace("ABSOLUTE-OK", json.dumps(str(tmp_path / "exists"))[1:-1])
    monkeypatch.setenv(HANDOFF_NAME, value)
    project.makepyfile(test_mod="def test_a():\n    pass\n")

    result = project.runpytest_subprocess()

    assert result.ret == 4, result.stdout.str() + result.stderr.str()
    assert HANDOFF_NAME in result.stderr.str() and message in result.stderr.str(), result.stderr.str()
    assert not list(tmp_path.rglob("journal-*"))
    assert not list(project.path.rglob("journal-*"))


# --- the folder, the files, the text -----------------------------------------------------------------------------


def test_a_record_folder_inside_a_basetemp_is_refused(project, tmp_path):
    project.makepyfile(test_mod="def test_a():\n    pass\n")
    basetemp = project.path / "bt"

    result = project.runpytest_subprocess("--basetemp", str(basetemp), f"--experiment-record={basetemp / 'rec'}")

    assert result.ret == 4, result.stdout.str() + result.stderr.str()
    assert "inside the basetemp" in result.stderr.str()
    assert not (basetemp / "rec").exists()


def test_the_record_folder_reaches_workers_through_workerinput_not_the_environment(project, tmp_path):
    rec = tmp_path / "rec"
    project.makepyfile(
        test_mod=f"""
import os


def test_a():
    assert not [k for k, v in os.environ.items() if {str(rec)!r} in v], "the record folder is in the environment"


def test_b():
    test_a()
"""
    )
    run_parallel(project, rec).assert_outcomes(passed=2)
    roles = {r["role"] for _, r in records(rec, "process-start")}
    assert roles == {"controller", "worker"}
    assert len(records(rec, "trailer")) == 3
    assert not [r for n, r in records(rec, "phase") if n.startswith("journal-controller-")]
    worker_phases = sorted(r["when"] for n, r in records(rec, "phase") if n.startswith("journal-worker-"))
    assert worker_phases == ["call", "call", "setup", "setup", "teardown", "teardown"]


def test_a_serial_run_is_a_one_worker_run_for_the_reducer(project, er, tmp_path):
    project.makepyfile(test_mod="def test_a():\n    pass\n\n\ndef test_b():\n    pass\n")
    expected = collected_ids(project)
    rec = tmp_path / "rec"
    run_serial(project, rec).assert_outcomes(passed=2)
    summary = er.reduce_journals(rec, expected)
    assert summary["accepted"], summary["problems"]
    assert [p["role"] for p in summary["processes"]] == ["serial"]
    assert sorted(summary["items"]) == sorted(expected)
    ((_, collection),) = records(rec, "collection-finish")
    assert collection["count"] == 2 and collection["digest_algorithm"] == "sha256"
    assert collection["raw_ids_sha256"] == hashlib.sha256("\n".join(expected).encode("utf-8")).hexdigest()


def test_a_journal_name_carries_the_role_pid_and_start_time(project, tmp_path):
    project.makepyfile(test_mod="def test_a():\n    pass\n")
    rec = tmp_path / "rec"
    run_serial(project, rec).assert_outcomes(passed=1)
    ((name, start),) = records(rec, "process-start")
    pid, started = re.fullmatch(r"journal-serial-(\d+)-(\d+)\.jsonl", name).groups()
    assert (start["pid"], start["started_ms"]) == (int(pid), int(started))
    assert [r["seq"] for r in read_journals(rec)[name]] == list(range(1, len(read_journals(rec)[name]) + 1))


def test_non_ascii_text_is_written_as_utf_8_not_escaped(project, tmp_path):
    project.makeini("[pytest]\ndisable_test_id_escaping_and_forfeit_all_rights_to_community_support = true\n")
    project.makepyfile(
        test_mod="""
import pytest


@pytest.mark.parametrize("value", ["caf\\u00e9-\\u00fc", "\\u65e5\\u672c"])
def test_x(value):
    assert value
"""
    )
    rec = tmp_path / "rec"
    run_serial(project, rec).assert_outcomes(passed=2)
    (path,) = Path(rec).glob("journal-*.jsonl")
    raw = path.read_bytes()
    assert "café-ü".encode() in raw and "日本".encode() in raw
    assert b"\\u00e9" not in raw and b"\\u65e5" not in raw


def test_a_long_error_text_is_bounded_with_a_flag_and_the_digest_of_the_full_text(project, er, tmp_path):
    project.makepyfile(
        test_mod="""
def test_big():
    assert False, "x" * 200000 + "\\u2028tail \\u00e9"


def test_small():
    assert False, "short\\u2028line \\u00e9"
"""
    )
    rec = tmp_path / "rec"
    reprec = project.inline_run(f"--experiment-record={rec}")
    reports = {r.nodeid.split("::")[1]: r for r in reprec.getreports("pytest_runtest_logreport") if r.when == "call"}

    phases = {r["nodeid"].split("::")[1]: r for _, r in records(rec, "phase") if r["when"] == "call"}
    for name, bounded in (("test_big", True), ("test_small", False)):
        full = str(reports[name].longrepr)
        record = phases[name]
        assert record["error_digest_algorithm"] == "sha256"
        assert record["error_digest"] == hashlib.sha256(full.encode("utf-8")).hexdigest()
        assert record["error_truncated"] is bounded
        assert record["error_length"] == len(full.encode("utf-8"))
        assert len(record["error_text"].encode("utf-8")) <= er.MAX_ERROR_TEXT
        if not bounded:
            assert record["error_text"] == full
    (path,) = Path(rec).glob("journal-*.jsonl")
    assert path.read_bytes().count(b"\n") == len(read_journals(rec)[path.name])


def test_skip_and_xfail_reasons_are_recorded_with_the_phase(project, tmp_path):
    project.makepyfile(
        test_mod="""
import pytest


@pytest.mark.skip(reason="not today")
def test_skipped():
    pass


@pytest.mark.xfail(reason="known gap")
def test_xfailed():
    assert False


def test_body_skip():
    pytest.skip("body says no")
"""
    )
    rec = tmp_path / "rec"
    run_serial(project, rec).assert_outcomes(skipped=2, xfailed=1)
    reasons = {
        r["nodeid"].split("::")[1]: (r["outcome"], r["reason"]) for _, r in records(rec, "phase") if r.get("reason")
    }
    assert "not today" in reasons["test_skipped"][1]
    assert "body says no" in reasons["test_body_skip"][1]
    assert reasons["test_xfailed"] == ("skipped", "known gap")


def test_the_item_end_is_recorded_when_a_no_body_hook_answers_true(project, er, tmp_path):
    project.makeconftest(
        CONFTEST
        + """
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    return True
"""
    )
    project.makepyfile(test_mod="def test_a():\n    pass\n")
    rec = tmp_path / "rec"
    run_serial(project, rec)
    (journal,) = read_journals(rec).values()
    order = [r["kind"] for r in journal if r["kind"].startswith("item")]
    assert order == ["item-start", "item-end"]


def test_an_existing_journal_file_is_never_reused(er, tmp_path):
    existing = tmp_path / "journal-serial-5-6.jsonl"
    existing.write_bytes(b"keep\n")
    with pytest.raises(FileExistsError):
        er.open_journal(tmp_path, "serial", 5, 6)
    assert existing.read_bytes() == b"keep\n"


def test_the_reducer_refuses_a_journal_with_two_names(er, tmp_path):
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    os.link(path, tmp_path / "journal-serial-99-1000.jsonl")
    summary = er.reduce_journals(tmp_path, ["t.py::a"])
    assert "journal-not-plain" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_the_reducer_refuses_a_journal_over_the_size_limit(er, tmp_path, monkeypatch):
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    monkeypatch.setattr(er, "MAX_JOURNAL_BYTES", 100)
    summary = er.reduce_journals(tmp_path, ["t.py::a"])
    assert "journal-too-large" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_a_torn_last_line_and_a_bad_line_are_reported(er, tmp_path):
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)], trailer=False)
    with open(path, "ab") as handle:
        handle.write(b'{"v": 1, "seq": 99, "kind": "phase", "no')
    summary = er.reduce_journals(tmp_path, ["t.py::a"])
    assert {"torn-last-line", "no-trailer"} <= kinds(summary["problems"])
    other = write_journal(tmp_path, "serial", 12, starts=[], trailer=False)
    other.write_bytes(other.read_bytes() + b"not json\n")
    assert "bad-line" in kinds(er.reduce_journals(tmp_path)["problems"])


def test_the_reducer_flags_a_gap_a_missing_start_records_after_the_trailer_and_bad_bytes(er, tmp_path):
    def lines(path):
        return path.read_bytes().split(b"\n")[:-1]

    gap = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    kept = lines(gap)
    gap.write_bytes(b"\n".join(kept[:1] + kept[2:]) + b"\n")
    assert "sequence-gap" in kinds(er.reduce_journals(tmp_path)["problems"])

    nostart = write_journal(tmp_path, "serial", 12, starts=[("t.py::b", None)])
    nostart.write_bytes(b"\n".join(lines(nostart)[1:]) + b"\n")
    assert "no-process-start" in kinds(er.reduce_journals(tmp_path)["problems"])

    after = write_journal(tmp_path, "serial", 13, starts=[])
    extra = json.loads(lines(after)[-1])
    extra.update(seq=extra["seq"] + 1, kind="exit-status", exitstatus=0)
    after.write_bytes(after.read_bytes() + json.dumps(extra).encode() + b"\n")
    summary = er.reduce_journals(tmp_path)
    assert "records-after-trailer" in kinds(summary["problems"])
    assert summary["status"] == "incomplete"

    garbage = tmp_path / "journal-serial-14-1000.jsonl"
    garbage.write_bytes(b"\xff\xfe\n")
    assert "bad-encoding" in kinds(er.reduce_journals(tmp_path)["problems"])


class _Factory:
    def __init__(self, basetemp):
        self._basetemp = basetemp

    def getbasetemp(self):
        return self._basetemp


def _fake_config(tmp_path, basetemp, given=None):
    from types import SimpleNamespace

    basetemp.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        option=SimpleNamespace(basetemp=given),
        _tmp_path_factory=_Factory(basetemp),
        invocation_params=SimpleNamespace(dir=tmp_path),
    )


def test_record_folder_containment_survives_dot_segments_case_and_a_name_prefix_sibling(er, tmp_path):
    root = tmp_path / "pytest-of-someone"
    basetemp = root / "pytest-3"
    config = _fake_config(tmp_path, basetemp)

    def check(path):
        return er._checked_directory(config, str(path), create=False, source="test")

    detour = tmp_path / "elsewhere" / ".." / "pytest-of-someone" / "pytest-3" / "rec"  # dot segments lead back in
    for inside in (basetemp / "rec", detour, root / "pytest-1" / "rec"):
        with pytest.raises(pytest.UsageError, match="inside the basetemp"):
            check(inside)
    if os.name == "nt":
        with pytest.raises(pytest.UsageError, match="inside the basetemp"):
            check(str(basetemp / "rec").upper())
    other = tmp_path / "pytest-of-someone-else"  # shares the root's name prefix, is not inside it
    other.mkdir()
    assert check(other) == other.resolve()

    # with an explicit --basetemp the numbered siblings are not at risk; a name-prefix sibling of it is outside
    given = tmp_path / "chosen"
    explicit = _fake_config(tmp_path, basetemp, given=str(given))
    for outside in (root / "pytest-1", root / "pytest-3-extra", tmp_path / "chosen-extra"):
        outside.mkdir()
        assert er._checked_directory(explicit, str(outside), create=False, source="test") == outside.resolve()
    given.mkdir()
    with pytest.raises(pytest.UsageError, match="inside the basetemp"):
        er._checked_directory(explicit, str(given / "rec"), create=False, source="test")


# --- fix round 1: CX1 redaction, CX2 torn tail, CX3 damaged fields, CX4 trailer count, CX5 spacing -----------------


def journal_bytes(rec):
    return b"\n".join(path.read_bytes() for path in sorted(Path(rec).glob("journal-*.jsonl")))


def fake_home(tmp_path, monkeypatch):
    home = str(tmp_path / "fake-home-folder-abcdef")
    monkeypatch.setenv("USERPROFILE", home)
    monkeypatch.setenv("HOME", home)
    return home


LEAKS = """
import os

import pytest


def test_assertion():
    assert os.environ["P3_S_ASSERT"] == "something else entirely"


def test_raise():
    raise RuntimeError("boom " + os.environ["P3_S_RAISE"])


def test_skip():
    pytest.skip("skip " + os.environ["P3_S_SKIP"])


@pytest.mark.xfail(reason="xfail marker " + os.environ["P3_S_XFAIL"])
def test_xfail_marker():
    assert False


def test_xfail_call():
    pytest.xfail("xfail call " + os.environ["P3_S_XFAIL"])


def test_home():
    assert os.path.expanduser("~") == "nowhere"
"""

SENTINELS = {
    "P3_S_ASSERT": "sentinel-assert-7Hq2",
    "P3_S_RAISE": "sentinel-raise-9Kd4",
    "P3_S_SKIP": "sentinel-skip-3Fw8",
    "P3_S_XFAIL": "sentinel-xfail-6Zr1",
    "P3_S_COLLECT": "sentinel-collect-5Tb0",
    "P3_S_INTERNAL": "sentinel-internal-2Nx7",
}


def plant(monkeypatch):
    for name, value in SENTINELS.items():
        monkeypatch.setenv(name, value)


def phases_of(rec):
    return {(r["nodeid"].split("::")[-1], r["when"]): r for _, r in records(rec, "phase")}


def test_environment_values_and_the_home_folder_never_reach_a_journal_from_failures_skips_and_xfails(
    project, er, tmp_path, monkeypatch
):
    # CX1, ruling 2-4: values from the recording process's environment (8 characters or longer) and the home folder are
    # replaced in every stored free text, whatever put them there: an assertion, a raised message, a skip reason, an
    # xfail marker's reason, an xfail called in the body.
    plant(monkeypatch)
    home = fake_home(tmp_path, monkeypatch)
    project.makepyfile(test_leaks=LEAKS.replace('"nowhere"', repr(home + "-is-not-it")))
    rec = tmp_path / "rec"

    run_serial(project, rec)

    # Search the DECODED text too: in the file JSON doubles every backslash, which hides a Windows path from a
    # byte search.
    raw = journal_bytes(rec)
    decoded = "\n".join(
        value for recs in read_journals(rec).values() for r in recs for value in r.values() if isinstance(value, str)
    )
    for name, value in SENTINELS.items():
        assert value.encode() not in raw and value not in decoded, f"{name} reached the journal"
    for form in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:
        assert form.encode() not in raw and form not in decoded, f"the home folder reached the journal: {form}"
    phases = phases_of(rec)
    assert "<env:P3_S_ASSERT>" in phases[("test_assertion", "call")]["error_text"]
    assert phases[("test_assertion", "call")]["error_redactions"] >= 1
    assert "<env:P3_S_RAISE>" in phases[("test_raise", "call")]["error_text"]
    assert "<home>" in phases[("test_home", "call")]["error_text"]
    assert "<env:P3_S_SKIP>" in phases[("test_skip", "call")]["reason"]
    assert phases[("test_skip", "call")]["reason_redactions"] >= 1
    assert "<env:P3_S_XFAIL>" in phases[("test_xfail_marker", "call")]["reason"]
    assert "<env:P3_S_XFAIL>" in phases[("test_xfail_call", "call")]["reason"]


def test_a_collection_error_text_is_cleaned(project, er, tmp_path, monkeypatch):
    # CX1, ruling 3: collection-error text.
    plant(monkeypatch)
    project.makepyfile(test_bad="import os\nraise RuntimeError('import ' + os.environ['P3_S_COLLECT'])\n")
    rec = tmp_path / "rec"
    run_serial(project, rec)
    ((_, record),) = records(rec, "collection-error")
    assert "<env:P3_S_COLLECT>" in record["error_text"] and record["error_redactions"] >= 1
    assert SENTINELS["P3_S_COLLECT"].encode() not in journal_bytes(rec)


def test_an_internal_error_text_is_cleaned(project, er, tmp_path, monkeypatch):
    # CX1, ruling 3: internal-error text.
    plant(monkeypatch)
    project.makeconftest(
        CONFTEST
        + """
import os


def pytest_runtest_logstart(nodeid, location):
    raise RuntimeError("hook " + os.environ["P3_S_INTERNAL"])
"""
    )
    project.makepyfile(test_mod="def test_a():\n    pass\n")
    rec = tmp_path / "rec"
    run_serial(project, rec)
    ((_, record),) = records(rec, "internal-error")
    assert "<env:P3_S_INTERNAL>" in record["error_text"] and record["error_redactions"] >= 1
    assert SENTINELS["P3_S_INTERNAL"].encode() not in journal_bytes(rec)


def _recorder(er, tmp_path):
    config = _fake_config(tmp_path, tmp_path / "bt")
    directory = tmp_path / "record-folder"
    directory.mkdir()
    return er.Recorder(config, directory, "serial", None, None, None), directory


def test_a_worker_down_text_is_cleaned(er, tmp_path, monkeypatch):
    # CX1, ruling 3: worker-down text (the controller's record of a crashed worker).
    monkeypatch.setenv("P3_S_WORKER", "sentinel-worker-4Vc9")
    recorder, directory = _recorder(er, tmp_path)
    try:
        node = type("Node", (), {"gateway": type("Gateway", (), {"id": "gw7"})()})()
        recorder.pytest_testnodedown(node, "worker crashed near sentinel-worker-4Vc9")
    finally:
        recorder.close()
    ((_, record),) = records(directory, "worker-down")
    assert "<env:P3_S_WORKER>" in record["error_text"] and record["error_redactions"] == 1
    assert b"sentinel-worker-4Vc9" not in journal_bytes(directory)


def test_the_digest_is_over_the_original_text_and_the_stored_copy_is_cleaned(er, tmp_path, monkeypatch):
    # CX1, ruling 1: error_digest, error_length and the algorithm come from the ORIGINAL full text; the stored copy is
    # cleaned afterwards and error_redactions counts the replacements.
    monkeypatch.setenv("P3_S_DIGEST", "sentinel-digest-8Lp3")
    recorder, directory = _recorder(er, tmp_path)
    original = "left sentinel-digest-8Lp3 and again sentinel-digest-8Lp3 é"
    try:
        fields = recorder.error_fields(original)
    finally:
        recorder.close()
    assert fields["error_digest"] == hashlib.sha256(original.encode("utf-8")).hexdigest()
    assert fields["error_length"] == len(original.encode("utf-8"))
    assert fields["error_digest_algorithm"] == "sha256"
    assert fields["error_text"] == "left <env:P3_S_DIGEST> and again <env:P3_S_DIGEST> é"
    assert fields["error_redactions"] == 2


def test_a_value_is_cleaned_from_eight_characters_and_not_below(er, tmp_path, monkeypatch):
    # CX1, ruling 2 and 5: 'values shorter than 8 characters cannot be recognised'; the limit is stated, and exact.
    monkeypatch.setenv("P3_SEVEN", "abcdefg")
    monkeypatch.setenv("P3_EIGHT", "hijklmno")
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields("seven abcdefg eight hijklmno")
    finally:
        recorder.close()
    assert fields["error_text"] == "seven abcdefg eight <env:P3_EIGHT>"


def test_every_part_of_a_path_list_value_is_cleaned_and_a_blank_value_is_not(er, tmp_path, monkeypatch):
    # CX1, ruling 2: 'every os.pathsep-separated part of such a value'; a value of blanks would erase every run
    # of spaces.
    monkeypatch.setenv("P3_LIST", f"first-part-folder{os.pathsep}second-part-folder")
    monkeypatch.setenv("P3_BLANK", " " * 12)
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields("in second-part-folder only, with gaps            kept")
    finally:
        recorder.close()
    assert fields["error_text"] == "in <env:P3_LIST> only, with gaps            kept"


def test_the_longest_value_is_replaced_first(er, tmp_path, monkeypatch):
    # CX1, ruling 2: 'longest first': a long value that contains a shorter one is replaced whole.
    monkeypatch.setenv("P3_LONG", "ABCDEFGHIJKLMNOP")
    monkeypatch.setenv("P3_SHORT_ONE", "ABCDEFGH")
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields("x ABCDEFGHIJKLMNOP y ABCDEFGH z")
    finally:
        recorder.close()
    assert fields["error_text"] == "x <env:P3_LONG> y <env:P3_SHORT_ONE> z"


def test_the_known_folders_are_named_not_shown(er, tmp_path, monkeypatch):
    # CX1, ruling 2: home -> <home>, temp -> <temp>, the record folder -> <record>, the basetemp -> <basetemp>,
    # in either slash direction (and without regard to case on Windows).
    import tempfile

    home = fake_home(tmp_path, monkeypatch)
    temp = str(tmp_path / "fake-temp-folder-ghijkl")
    monkeypatch.setattr(tempfile, "tempdir", temp)
    recorder, directory = _recorder(er, tmp_path)
    basetemp = str(tmp_path / "bt")
    try:
        text = " | ".join(
            [
                home + "\\a.py",
                temp + "/b.py",
                str(directory) + "\\c.json",
                basetemp + "/d.txt",
                str(directory).replace("\\", "/") + "/e",
                repr(home)[1:-1] + "\\g.py",
            ]
        )
        fields = recorder.error_fields(text)
        shouted = recorder.error_fields(str(directory).upper() + "\\f")
    finally:
        recorder.close()
    assert fields["error_text"] == (
        "<home>\\a.py | <temp>/b.py | <record>\\c.json | <basetemp>/d.txt | <record>/e | <home>\\g.py"
    )
    assert fields["error_redactions"] == 6
    if os.name == "nt":
        assert shouted["error_text"] == "<record>\\f"


def test_a_value_cut_by_the_size_limit_cannot_leak_a_fragment(er, tmp_path, monkeypatch):
    # CX1, ruling 2: 'cleaned, before it is bounded': a secret that straddles the 64 KiB cut is replaced first, so no
    # half of it is stored.
    monkeypatch.setenv("P3_S_EDGE", "sentinel-edge-1Qa5-extra-long-tail")
    recorder, _ = _recorder(er, tmp_path)
    text = "x" * (er.MAX_ERROR_TEXT - 6) + "sentinel-edge-1Qa5-extra-long-tail" + "y" * 100
    try:
        fields = recorder.error_fields(text)
    finally:
        recorder.close()
    assert fields["error_truncated"] is True
    assert "sentinel" not in fields["error_text"] and "Qa5" not in fields["error_text"]
    assert fields["error_digest"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_a_child_killed_inside_a_multibyte_character_keeps_the_complete_lines_before_it(project, er, tmp_path):
    # CX2: the writer dies after the first byte of a two-byte character. The earlier complete lines are durable; the
    # reducer keeps them and reports the damaged tail, instead of dropping the whole journal.
    project.makepyfile(
        test_mod="""
import os

import experiment_record


def test_dies(pytestconfig):
    recorder = pytestconfig.pluginmanager.get_plugin(experiment_record.PLUGIN_NAME)
    os.write(recorder._fd, bytes([0xC3]))
    os._exit(77)
"""
    )
    rec = tmp_path / "rec"
    result = run_serial(project, rec)
    assert result.ret == 77
    (path,) = Path(rec).glob("journal-*.jsonl")
    assert path.read_bytes().endswith(bytes([0xC3]))

    summary = er.reduce_journals(rec)
    (process,) = summary["processes"]
    assert process["records"] >= 4, summary["problems"]
    assert {"torn-last-line", "no-trailer"} <= kinds(summary["problems"])
    assert "bad-encoding" not in kinds(summary["problems"])
    assert summary["items"]["test_mod.py::test_dies"]["started"] == 1
    assert summary["status"] == "incomplete" and summary["accepted"] is False


def test_a_complete_line_that_is_not_utf_8_costs_only_that_line(er, tmp_path):
    # CX2: bad bytes inside a COMPLETE line are reported for that line alone; the lines around it are kept.
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None), ("t.py::b", None)])
    lines = path.read_bytes().split(b"\n")
    lines.insert(3, b'{"seq": 3, "kind": "x", "bad": "\xff"}')
    path.write_bytes(b"\n".join(lines))
    summary = er.reduce_journals(tmp_path, ["t.py::a", "t.py::b"])
    assert "bad-encoding" in kinds(summary["problems"])
    assert summary["items"]["t.py::a"]["started"] == 1 and summary["items"]["t.py::b"]["started"] == 1


def damaged(path, match, **changes):
    """Rewrite the first record whose kind is `match`: a value of None deletes the key."""
    lines = path.read_bytes().decode("utf-8").split("\n")
    for index, line in enumerate(lines):
        if line and json.loads(line)["kind"] == match:
            record = json.loads(line)
            for key, value in changes.items():
                if value is None:
                    record.pop(key, None)
                else:
                    record[key] = value
            lines[index] = json.dumps(record)
            break
    else:
        raise AssertionError(f"no {match} record")
    path.write_bytes("\n".join(lines).encode("utf-8"))


@pytest.mark.parametrize(
    "kind, changes",
    [
        ("item-end", {"t_wall": {}}),
        ("item-start", {"t_wall": "yesterday"}),
        ("item-start", {"nodeid": None}),
        ("item-start", {"nodeid": 7}),
        ("item-start", {"requested_group": ["g"]}),
        ("phase", {"outcome": ["failed"]}),
        ("item-end", {"pid": "x"}),
        ("process-start", {"role": 5}),
        ("process-start", {"plugins": [1, 2]}),
        ("process-start", {"nested_token": 12}),
        ("trailer", {"records": "many"}),
        ("trailer", {"records": True}),
        ("item-end", {"pid": True}),
        ("trailer", {"complete": "yes"}),
        ("exit-status", {"exitstatus": "ok"}),
        ("worker-down", {"has_error": ["boom"]}),
        ("collection-error", {"error_text": 3}),
        ("nested-launch", {"token": 9}),
    ],
    ids=lambda v: v if isinstance(v, str) else next(iter(v)),
)
def test_a_record_with_a_damaged_field_is_reported_and_the_rest_is_kept(er, tmp_path, kind, changes):
    # CX3: a valid JSON line with a malformed field is a problem to report, never an exception from the reducer;
    # the usable evidence is kept (here: the second item still joins).
    extra = [
        ("phase", {"nodeid": "t.py::a", "when": "call", "outcome": "passed", "duration": 0.1}),
        ("worker-down", {"down_worker": "gw0", "has_error": True, "error_text": "x"}),
        ("collection-error", {"nodeid": "c.py", "error_text": "boom"}),
        ("exit-status", {"exitstatus": 1}),
        ("nested-launch", {"token": "0123456789abcdef"}),
    ]
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None), ("t.py::b", None)], extra=extra)
    damaged(path, kind, **changes)

    summary = er.reduce_journals(tmp_path, ["t.py::a", "t.py::b"])

    assert "bad-field" in kinds(summary["problems"]), summary["problems"]
    assert "sequence-gap" not in kinds(summary["problems"]), "a set-aside record must keep its place in the sequence"
    assert summary["accepted"] is False
    assert "t.py::b" in summary["items"] and summary["items"]["t.py::b"]["started"] == 1


def test_a_trailer_counts_every_record_before_it_in_a_real_journal(project, er, tmp_path):
    # CX4: `records` is how many records precede the trailer; asserted against a real written journal.
    project.makepyfile(test_mod="def test_a():\n    pass\n\n\ndef test_b():\n    pass\n")
    rec = tmp_path / "rec"
    run_serial(project, rec).assert_outcomes(passed=2)
    (recs,) = read_journals(rec).values()
    trailer = recs[-1]
    assert trailer["kind"] == "trailer"
    assert trailer["records"] == len(recs) - 1
    assert er.reduce_journals(rec)["status"] == "complete"


def test_a_trailer_that_miscounts_is_reported(er, tmp_path):
    # CX4: the reducer checks the count too.
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    damaged(path, "trailer", records=99)
    summary = er.reduce_journals(tmp_path, ["t.py::a"])
    assert "trailer-count-mismatch" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_the_conftest_wiring_line_is_formatted_as_ruff_wants():
    # CX5: two spaces before an inline comment, on the one line P3 adds to tests/conftest.py (the file was already
    # unformatted elsewhere; P3 must not add to that).
    text = (TESTS_DIR / "conftest.py").read_text(encoding="utf-8")
    (line,) = [row for row in text.splitlines() if "experiment_record.configure(config)" in row]
    code = line.split("#", 1)[0].rstrip()
    assert code.endswith(")"), repr(line)
    assert line.index("#") - len(code) == 2, repr(line)
