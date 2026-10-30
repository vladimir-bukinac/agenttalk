"""Tests for the experiment recorder (tests/experiment_record.py, audit step P3).

The record schema these tests read is documented in the module docstring of `experiment_record`; the field names
used here are the frozen ones.  Most tests start a real pytest (with two real xdist workers where it matters) in a
throw-away project made by `pytester`.  Plugin autoload is switched off and `-p xdist.plugin` is written out,
exactly as the development gate does.  The record folder is always a sibling of the inner run's basetemp, never
inside it.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest_plugins = ["pytester"]

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
HANDOFF_NAME = "AGENTTALK_EXPERIMENT_RECORD_HANDOFF"


def gate_repair_source():
    """The gate's grouped-ID repair hook, copied exactly as `tests/conftest.py` has it (decorator included), or ""
    if the gate no longer has it. pytest 9.2 reads `_id` where xdist 3.8 writes `_nodeid`, so an inner run on 9.2
    has no `@group` suffix in its raw ids without the repair; on 9.1 the repair changes nothing."""
    source = (TESTS_DIR / "conftest.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == "pytest_collection_finish":
            first = min([decorator.lineno for decorator in node.decorator_list] + [node.lineno])
            return "\n".join(source.splitlines()[first - 1 : node.end_lineno])
    return ""


CONFTEST = (
    """
import experiment_record
import pytest


def pytest_addoption(parser):
    experiment_record.add_option(parser)


def pytest_configure(config):
    experiment_record.configure(config)


"""
    + gate_repair_source()
    + "\n"
)

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


def identity_fields(raw, group):
    """The identity a recorder writes for an item: the canonical id (the raw id minus its `@group` suffix), no
    parameter id (these hand-made ids have none) and the requested and effective group."""
    suffixed = bool(group) and raw.endswith("@" + group)
    return {
        "canonical_id": raw[: -len(group) - 1] if suffixed else raw,
        "param_id": None,
        "requested_group": group,
        "effective_group": group if suffixed else None,
    }


def item_start_fields(raw, group):
    fields = identity_fields(raw, group)
    return {
        "nodeid": raw,
        "requested_group": group,
        "effective_group": fields["effective_group"],
        "suffix_missing": bool(group) and fields["effective_group"] is None,
        "canonical_id": fields["canonical_id"],
        "param_id": None,
    }


def phase_fields(raw, group, when, outcome):
    return {
        "nodeid": raw,
        "when": when,
        "outcome": outcome,
        "duration": 0.01,
        "xfail": False,
        "reason": None,
        "reason_redactions": 0,
        **identity_fields(raw, group),
    }


def manifest_fields(rows, source="session", source_worker=None):
    """A collection manifest for `rows` [(raw id, group)]; the controller's (`source="node"`) has raw ids only."""
    fields = {"source": source, "source_worker": source_worker, "count": len(rows), "raw_ids": [r for r, _ in rows]}
    if source == "session":
        fields["identities"] = [identity_fields(raw, group) for raw, group in rows]
    return fields


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
    phases=None,
    collected=None,
    unfinished=(),
    manifest=True,
):
    """A hand-made, well-formed journal, for the reducer tests.

    Every started item gets the three passed phases unless `phases` says otherwise ({raw id: [(when, outcome), ...]},
    or False for none at all); a serial, worker or nested journal gets a collection manifest of `collected` (default:
    the started items); `unfinished` is [(raw id, group, [(when, outcome), ...])]: started, some phases, no end."""
    start = {"started_ms": 1000, "loadgroup": loadgroup, "nested_token": nested_token}
    if plugins is not None:
        start["plugins"] = list(plugins)
    events = [("process-start", start)]
    if manifest and role in ("serial", "worker", "nested"):
        rows = list(starts) if collected is None else list(collected)
        events.append(("collection-manifest", manifest_fields(rows)))
    for raw, group in starts:
        events.append(("item-start", item_start_fields(raw, group)))
        sequence = [("setup", "passed"), ("call", "passed"), ("teardown", "passed")]
        if phases is False:
            sequence = []
        elif phases is not None and raw in phases:
            sequence = phases[raw]
        for when, outcome in sequence:
            events.append(("phase", phase_fields(raw, group, when, outcome)))
        events.append(("item-end", {"nodeid": raw}))
    for raw, group, seen in unfinished:
        events.append(("item-start", item_start_fields(raw, group)))
        for when, outcome in seen:
            events.append(("phase", phase_fields(raw, group, when, outcome)))
    events.extend(extra)
    if trailer:
        events.append(("trailer", {"complete": True, "records": len(events), "exitstatus": 0}))
    lines = []
    for seq, (kind, fields) in enumerate(events, 1):
        lines.append(
            json.dumps(
                {
                    "v": 2,
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


LATE_MARKER = """
import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.xdist_group(name="g1"))
"""


@pytest.mark.parametrize("shape", ["with-suffix", "without-suffix"])
def test_the_identity_fields_say_what_the_raw_id_shows_in_either_shape(project, er, tmp_path, shape):
    # CI (pytest 9.2 without the gate's repair): an inner run's raw ids carry no `@g1`; with the repair, or on 9.1,
    # they do. The recorder computes the canonical id and the effective group from what the item reports, so in both
    # shapes every record agrees with its own raw id and the join to the serial collection holds.
    suffixed = shape == "with-suffix"
    if suffixed:
        project.makepyfile(test_mod=GROUPED)
    else:
        project.makeconftest(CONFTEST + LATE_MARKER)  # a marker added too late for xdist: no suffix on the raw id
        project.makepyfile(test_mod="def test_x():\n    pass\n\n\ndef test_y():\n    pass\n")
    expected = collected_ids(project)
    rec = tmp_path / "rec"

    run_parallel(project, rec)

    starts = [r for _, r in records(rec, "item-start")]
    phases = [r for n, r in records(rec, "phase") if n.startswith("journal-worker-")]
    assert starts and phases
    for record in [*starts, *phases]:
        assert record["requested_group"] == "g1"
        assert (record["effective_group"] == "g1") is suffixed
        assert record["nodeid"] == record["canonical_id"] + ("@g1" if suffixed else "")
    ((_, manifest),) = [(n, r) for n, r in records(rec, "collection-manifest") if n.startswith("journal-worker-")][:1]
    assert [i["canonical_id"] for i in manifest["identities"]] == expected
    assert len(manifest["raw_ids"]) == len(expected)
    assert all(
        raw == canonical + ("@g1" if suffixed else "")
        for raw, canonical in zip(manifest["raw_ids"], expected, strict=True)
    )
    summary = er.reduce_journals(rec, expected)
    assert sorted(summary["items"]) == sorted(expected)  # the join to the serial collection holds in both shapes
    assert ("suffix-missing" in kinds(summary["problems"])) is not suffixed
    assert summary["accepted"] is suffixed


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
    rows0, rows1 = [("t.py::a@g1", "g1")], [("t.py::b@g2", "g2")]
    nodes = [
        ("collection-manifest", manifest_fields(rows0, "node", "gw0")),
        ("collection-manifest", manifest_fields(rows1, "node", "gw1")),
    ]
    write_journal(tmp_path, "controller", 10, extra=nodes)  # an xdist run has its controller's journal
    write_journal(tmp_path, "worker", 11, worker="gw0", starts=rows0)
    write_journal(tmp_path, "worker", 12, worker="gw1", starts=rows1)
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

NESTED_CONFTEST = json.dumps(CONFTEST)[1:-1]  # the text of a double-quoted Python string literal

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


def test_helper_plus_addopts(tmp_path):
    env = experiment_record.nested_environment()
    # a parent that turned recording on through PYTEST_ADDOPTS: the child inherits the option AND the handoff
    env["PYTEST_ADDOPTS"] = "--experiment-record=" + experiment_record._ACTIVE.directory.as_posix()  # shlex-split
    done = launch(tmp_path, env)
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


# --- fix round 2: N1 shortened long values, CX3 rest (numbers outside the float range) -------------------------------

LONG_SENTINELS = {
    "P3_S_LONG32": "Q7xK2mP9vL4nR8tW3yB6cD1fG5hJ0zA9",
    "P3_S_LONG64": "mZ8cV3bN6qW1eR4tY7uI0oP2aS5dF9gH3jK6lX1zC4vB7nM0qW8eR2tY5uI9oP3a",
}

LONG_TESTS = """
import os


def test_long_32():
    assert os.environ["P3_S_LONG32"] == "short"


def test_long_64():
    assert os.environ["P3_S_LONG64"] == "short"
"""


def windows_of(value, size=8):
    return {value[i : i + size] for i in range(len(value) - size + 1)}


def test_a_long_value_that_pytest_shortens_does_not_reach_the_journal(project, er, tmp_path, monkeypatch):
    # N1 (P1): pytest shows a long compared value as 'head...tail' (about 12 characters each side); neither piece is the
    # whole value, so the first pass cannot find it. The second pass joins head and tail back to one recognised value.
    for name, value in LONG_SENTINELS.items():
        monkeypatch.setenv(name, value)
    project.makepyfile(test_long=LONG_TESTS)
    rec = tmp_path / "rec"

    run_serial(project, rec)

    decoded = "\n".join(
        value for recs in read_journals(rec).values() for r in recs for value in r.values() if isinstance(value, str)
    )
    raw = journal_bytes(rec).decode("utf-8")
    for name, value in LONG_SENTINELS.items():
        leaked = [w for w in windows_of(value) if w in decoded or w in raw]
        assert not leaked, f"{name}: pieces of the value reached the journal: {sorted(leaked)[:3]}"
    phases = phases_of(rec)
    assert "<env:P3_S_LONG32>" in phases[("test_long_32", "call")]["error_text"]
    assert "<env:P3_S_LONG64>" in phases[("test_long_64", "call")]["error_text"]


def test_a_shortened_form_is_joined_back_to_its_value_and_counted(er, tmp_path, monkeypatch):
    value = LONG_SENTINELS["P3_S_LONG32"]
    monkeypatch.setenv("P3_S_LONG32", value)
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields(f"assert '{value[:11]}...{value[-11:]}' == 'x'")
    finally:
        recorder.close()
    assert fields["error_text"] == "assert '<env:P3_S_LONG32>' == 'x'"
    assert fields["error_redactions"] == 1


@pytest.mark.parametrize(
    ("text", "unchanged"),
    [
        ("{h3}...{t3}", True),  # pieces under 4 characters are not recognised
        ("{h4}...{t4}", False),  # 4 and 4 are
        ("{h4}...{o4}", True),  # a head of this value with the tail of another value
        ("Loading...", True),  # an ellipsis in ordinary text
        ("{h4} ... {t4}", True),  # the ellipsis must sit between the pieces
    ],
)
def test_the_shortened_form_needs_both_pieces_of_one_value(er, tmp_path, monkeypatch, text, unchanged):
    value = LONG_SENTINELS["P3_S_LONG32"]
    other = LONG_SENTINELS["P3_S_LONG64"]
    monkeypatch.setenv("P3_S_LONG32", value)
    monkeypatch.setenv("P3_S_LONG64", other)
    given = text.format(h3=value[:3], t3=value[-3:], h4=value[:4], t4=value[-4:], o4=other[-4:])
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields(given)
    finally:
        recorder.close()
    assert (fields["error_text"] == given) is unchanged, fields["error_text"]
    assert fields["error_redactions"] == (0 if unchanged else 1)


def test_a_huge_integer_as_the_time_is_a_bad_field_not_a_crash(er, tmp_path):
    # CX3 rest: math.isfinite(10**400) raises OverflowError; the whole summary was lost.
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None), ("t.py::b", None)])
    damaged(path, "item-end", t_wall=10**400)
    summary = er.reduce_journals(tmp_path, ["t.py::a", "t.py::b"])
    assert "bad-field" in kinds(summary["problems"]) and "sequence-gap" not in kinds(summary["problems"])
    assert summary["items"]["t.py::b"]["started"] == 1


def test_an_integer_too_long_for_json_is_a_bad_line_not_a_crash(er, tmp_path):
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    lines = path.read_bytes().split(b"\n")
    lines.insert(2, b'{"v": 1, "seq": 3, "kind": "x", "role": "serial", "pid": 11, "t_wall": ' + b"9" * 5000 + b"}")
    path.write_bytes(b"\n".join(lines))
    summary = er.reduce_journals(tmp_path, ["t.py::a"])
    assert "bad-line" in kinds(summary["problems"])
    assert summary["items"]["t.py::a"]["started"] == 1


def test_the_docstring_states_the_limits_of_the_cleaning(er):
    text = er.__doc__.lower()
    assert "node ids are kept exactly as pytest makes them" in text
    assert "recognised only by its first and last characters" in text
    flat = " ".join(text.split())
    assert "both looked for in the original text" in flat
    assert "a 64 kib text full of `...` is cleaned" in flat
    assert "the masked stretch is the union of their spans" in flat
    assert "crafted on purpose to overlap or compete" in flat
    assert "a lone piece is masked as well" in flat
    assert "a lone head or tail under 8 characters" in flat
    assert "the probe jobs run without secrets" in flat


# --- fix round 3: N1 values that start alike, P2 a slow second pass ----------------------------------------------

_LONG32 = LONG_SENTINELS["P3_S_LONG32"]
_LONG64 = LONG_SENTINELS["P3_S_LONG64"]
OVERLAP_SENTINELS = {
    32: _LONG32,
    64: _LONG64,
    200: (_LONG32[::-1] + _LONG64 + _LONG32.swapcase() + _LONG64[::-1] + _LONG32)[:200],
}

OVERLAP_TESTS = "import os\n\nimport pytest\n" + "".join(
    f"""

def test_assert_{size}():
    assert os.environ["P3_S_OVL{size}"] == "short"


def test_raise_{size}():
    value = os.environ["P3_S_OVL{size}"]
    raise ValueError(f"{{value[:12]}}...{{value[-12:]}}")


def test_skip_{size}():
    value = os.environ["P3_S_OVL{size}"]
    pytest.skip(f"{{value[:12]}}...{{value[-12:]}}")
"""
    for size in OVERLAP_SENTINELS
)


def set_overlapping_values(monkeypatch):
    """Each sentinel, and a second variable that holds only its first 12 characters."""
    for size, value in OVERLAP_SENTINELS.items():
        monkeypatch.setenv(f"P3_S_OVL{size}", value)
        monkeypatch.setenv(f"P3_S_OVL{size}_HEAD", value[:12])


def test_a_value_that_is_the_start_of_another_does_not_hide_its_shortened_form(project, er, tmp_path, monkeypatch):
    # N1 (P1, round 4): the whole-value pass used to replace the shared first 12 characters first, so the shortened
    # 'head...tail' could no longer be matched to the long value and its tail was stored.
    set_overlapping_values(monkeypatch)
    project.makepyfile(test_overlap=OVERLAP_TESTS)
    rec = tmp_path / "rec"

    run_serial(project, rec)

    decoded = "\n".join(
        value for recs in read_journals(rec).values() for r in recs for value in r.values() if isinstance(value, str)
    )
    raw = journal_bytes(rec).decode("utf-8")
    for size, value in OVERLAP_SENTINELS.items():
        leaked = [w for w in windows_of(value) if w in decoded or w in raw]
        assert not leaked, f"{size} characters: pieces of the value reached the journal: {sorted(leaked)[:3]}"
    phases = phases_of(rec)
    for size in OVERLAP_SENTINELS:
        assert f"<env:P3_S_OVL{size}>" in phases[(f"test_raise_{size}", "call")]["error_text"]
        assert phases[(f"test_skip_{size}", "call")]["reason"] == f"Skipped: <env:P3_S_OVL{size}>"
        assert phases[(f"test_assert_{size}", "call")]["error_redactions"] >= 1


@pytest.mark.parametrize("size", sorted(OVERLAP_SENTINELS))
def test_overlapping_values_keep_the_digest_of_the_original_text(er, tmp_path, monkeypatch, size):
    set_overlapping_values(monkeypatch)
    value = OVERLAP_SENTINELS[size]
    shortened = f"{value[:12]}...{value[-12:]}"
    text = f"ValueError: '{shortened}' and in full {value}"
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields(text)
        reason = recorder.reason_fields(shortened)
    finally:
        recorder.close()
    label = f"<env:P3_S_OVL{size}>"
    assert fields["error_text"] == f"ValueError: '{label}' and in full {label}"
    assert fields["error_redactions"] == 2
    assert fields["error_digest"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert fields["error_length"] == len(text.encode("utf-8"))
    assert (reason["reason"], reason["reason_redactions"]) == (label, 1)


def test_a_value_that_ends_inside_a_head_is_one_replacement_with_the_longer_label(er, tmp_path, monkeypatch):
    # The two spans start in different places: the value `pre-<first 6 characters>` begins 4 characters before the head.
    value = LONG_SENTINELS["P3_S_LONG32"]
    monkeypatch.setenv("P3_S_LONG32", value)
    monkeypatch.setenv("P3_S_ENDING", "pre-" + value[:6])
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields(f"got 'pre-{value[:11]}...{value[-11:]}' here")
    finally:
        recorder.close()
    assert fields["error_text"] == "got '<env:P3_S_LONG32>' here"
    assert fields["error_redactions"] == 1


def test_two_neighbouring_values_are_still_two_replacements(er, tmp_path, monkeypatch):
    # Spans that only touch are not merged: each value keeps its own label and its own count.
    monkeypatch.setenv("P3_S_FIRST", "first-value-9Qw2")
    monkeypatch.setenv("P3_S_SECOND", "second-value-4Zr7")
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields("first-value-9Qw2second-value-4Zr7")
    finally:
        recorder.close()
    assert fields["error_text"] == "<env:P3_S_FIRST><env:P3_S_SECOND>"
    assert fields["error_redactions"] == 2


CLEAN_TIME_LIMIT = 5.0  # seconds a child process may take to clean each text below; the real figure is far smaller

TIMING_SCRIPT = """
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])
import experiment_record

directory = Path(sys.argv[2])
config = SimpleNamespace(option=SimpleNamespace(basetemp=None), _tmp_path_factory=None)
redactor = experiment_record.Redactor(config, directory)
size = 64 * 1024
form = "{head}...{tail} ".format(head=os.environ["P3_S_TIME00"][:11], tail=os.environ["P3_S_TIME00"][-11:])
texts = {
    "dots": "." * size,
    "ellipses": "..." * (size // 3),
    "shortened forms": form * (size // len(form)),
    "heads without tails": (os.environ["P3_S_TIME00"][:11] + "... ") * (size // 16),
    "tails without heads": ("..." + os.environ["P3_S_TIME00"][-11:] + " ") * (size // 15),
}
seconds = {}
for name, text in texts.items():
    started = time.perf_counter()
    cleaned, count = redactor.clean(text)
    seconds[name] = round(time.perf_counter() - started, 3)
print(json.dumps(seconds))
"""


def test_a_long_text_full_of_ellipses_is_cleaned_within_a_small_time_limit(tmp_path):
    # P2 (round 4): the shortened-form pass tried every value at up to 256 lengths for every '...', so 64 KiB of dots
    # took over a minute. It runs in a child process so that a slow pass is stopped by the timeout, not waited for.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "AGENTTALK_", "PYTHONPATH"))}
    for number in range(60):
        env[f"P3_S_TIME{number:02d}"] = f"time-value-{number:02d}-" + "wQ7zK2mP9vL4nR8tW3yB6cD1fG5hJ0"
    done = subprocess.run(
        [sys.executable, "-I", "-c", TIMING_SCRIPT, str(TESTS_DIR), str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    seconds = json.loads(done.stdout.strip().splitlines()[-1])
    assert set(seconds) == {"dots", "ellipses", "shortened forms", "heads without tails", "tails without heads"}
    slow = {name: taken for name, taken in seconds.items() if taken > CLEAN_TIME_LIMIT}
    assert not slow, f"cleaning took longer than {CLEAN_TIME_LIMIT} seconds: {slow}"


# --- fix round 4: N1 the union of every valid shortened-form match -------------------------------------------------

COMPETING_HEAD = "Hq3vN8zK2mXw"
COMPETING_TAIL = "Ry5tB7cJ9dLp"
COMPETING_B64 = COMPETING_HEAD + "Z" * 40 + COMPETING_TAIL
COMPETING_A200 = COMPETING_HEAD + "A" * 184 + COMPETING_TAIL[:4]

COMPETING_TESTS = """
import os

import pytest


def pieces():
    big = os.environ["P3_S_CB64"]
    return big[:12], big[-12:]


def test_raise():
    head, tail = pieces()
    raise ValueError(f"{head}...{tail}")


def test_skip():
    head, tail = pieces()
    pytest.skip(f"{head}...{tail}")
"""


def set_competing_values(monkeypatch):
    """Two values that both fit `H...T` (the longer one shows only T[:4] of the tail) and a third that equals H."""
    monkeypatch.setenv("P3_S_CB64", COMPETING_B64)
    monkeypatch.setenv("P3_S_CA200", COMPETING_A200)
    monkeypatch.setenv("P3_S_CHEAD", COMPETING_HEAD)


def test_two_values_that_fit_one_shortened_form_are_masked_by_their_union(er, tmp_path, monkeypatch):
    # N1 (P1, round 5): the first value that fitted (the longer A200) masked only T[:4] and left T[4:] of B64 stored.
    set_competing_values(monkeypatch)
    text = f"{COMPETING_HEAD}...{COMPETING_TAIL}"
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields(text)
        reason = recorder.reason_fields(text)
    finally:
        recorder.close()
    assert fields["error_text"] == "<env:P3_S_CB64>"
    assert fields["error_redactions"] == 1
    assert (reason["reason"], reason["reason_redactions"]) == ("<env:P3_S_CB64>", 1)
    assert fields["error_digest"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert fields["error_length"] == len(text.encode("utf-8"))


def test_the_union_of_matches_reaches_the_journal_of_a_real_run(project, er, tmp_path, monkeypatch):
    # The same case through a real pytest child: a raised message and a skip reason, nothing of B64's tail stored.
    set_competing_values(monkeypatch)
    project.makepyfile(test_competing=COMPETING_TESTS)
    rec = tmp_path / "rec"

    run_serial(project, rec)

    decoded = "\n".join(
        value for recs in read_journals(rec).values() for r in recs for value in r.values() if isinstance(value, str)
    )
    raw = journal_bytes(rec).decode("utf-8")
    leaked = [w for w in windows_of(COMPETING_TAIL) if w in decoded or w in raw]
    assert not leaked, f"pieces of the longer value's tail reached the journal: {sorted(leaked)[:3]}"
    phases = phases_of(rec)
    assert "<env:P3_S_CB64>" in phases[("test_raise", "call")]["error_text"]
    assert phases[("test_skip", "call")]["reason"] == "Skipped: <env:P3_S_CB64>"


# --- fix round 5: N1 a lone head or a lone tail of one value ------------------------------------------------------

LONE_VALUE = LONG_SENTINELS["P3_S_LONG64"]
LONE_NEIGHBOUR = "a-long-neighbouring-item-0123456789"

LONE_TESTS = """
import os

VALUE = os.environ["P3_S_ONE"]
NEIGHBOUR = "a-long-neighbouring-item-0123456789"


def test_list_value_first():
    assert [VALUE, NEIGHBOUR] == ["x"]


def test_list_value_last():
    assert [NEIGHBOUR, VALUE] == ["x"]


def test_dict_value_as_the_first_key():
    assert {VALUE: 1, "z": NEIGHBOUR} == {"x": 1}


def test_dict_value_last():
    assert {"z": NEIGHBOUR, "k": VALUE} == {"x": 1}
"""


def test_a_lone_head_or_tail_of_one_value_in_a_real_run_is_masked(project, er, tmp_path, monkeypatch):
    # N1 (P1, round 6): pytest shortens the container's repr, so a value first in a list shows only its head before the
    # '...', and a value last shows only its tail after it. The cleaner used to need both pieces.
    monkeypatch.setenv("P3_S_ONE", LONE_VALUE)
    project.makepyfile(test_lone=LONE_TESTS)
    rec = tmp_path / "rec"

    run_serial(project, rec)

    decoded = "\n".join(
        value for recs in read_journals(rec).values() for r in recs for value in r.values() if isinstance(value, str)
    )
    raw = journal_bytes(rec).decode("utf-8")
    leaked = [w for w in windows_of(LONE_VALUE) if w in decoded or w in raw]
    assert not leaked, f"pieces of the value reached the journal: {sorted(leaked)[:3]}"
    phases = phases_of(rec)
    for name in ("list_value_first", "list_value_last", "dict_value_as_the_first_key", "dict_value_last"):
        assert "<env:P3_S_ONE>" in phases[(f"test_{name}", "call")]["error_text"], name


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("['{head}...m-0123456789']", "['<env:P3_S_ONE>...m-0123456789']"),  # the value first: only its head shows
        ("['a-long-lea...{tail}']", "['a-long-lea...<env:P3_S_ONE>']"),  # the value last: only its tail shows
        ("{{'{head}...m-0123456789': 1}}", "{{'<env:P3_S_ONE>...m-0123456789': 1}}"),
        ("{{'z': 'a-long-lea...{tail}'}}", "{{'z': 'a-long-lea...<env:P3_S_ONE>'}}"),
    ],
)
def test_a_lone_head_or_tail_of_one_value_is_masked_by_the_cleaner(er, tmp_path, monkeypatch, template, expected):
    monkeypatch.setenv("P3_S_ONE", LONE_VALUE)
    text = template.format(head=LONE_VALUE[:11], tail=LONE_VALUE[-11:])
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields(text)
        reason = recorder.reason_fields(text)
    finally:
        recorder.close()
    want = expected.format()
    assert fields["error_text"] == want
    assert fields["error_redactions"] == 1
    assert (reason["reason"], reason["reason_redactions"]) == (want, 1)
    assert fields["error_digest"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    ("template", "unchanged"),
    [
        ("{h7}...rest", True),  # a piece under 8 characters stays as it is (the stated limit)
        ("{h8}...rest", False),
        ("rest...{t7}", True),
        ("rest...{t8}", False),
        ("{m11}...rest", True),  # a stretch from the middle of the value is not its start
        ("rest...{m11}", True),  # nor its end
        ("{h11} ...rest", True),  # the ellipsis must touch the piece
        ("rest... {t11}", True),
    ],
)
def test_a_lone_piece_needs_eight_characters_and_must_be_a_start_or_an_end(
    er, tmp_path, monkeypatch, template, unchanged
):
    monkeypatch.setenv("P3_S_ONE", LONE_VALUE)
    v = LONE_VALUE
    given = template.format(h7=v[:7], h8=v[:8], t7=v[-7:], t8=v[-8:], m11=v[20:31], h11=v[:11], t11=v[-11:])
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields(given)
    finally:
        recorder.close()
    assert (fields["error_text"] == given) is unchanged, fields["error_text"]
    assert fields["error_redactions"] == (0 if unchanged else 1)


# --- fix round 6: R1 collection manifest, R2 identity on every phase, R3 missing outcomes -----------------------

MIXED = """
import pytest


@pytest.mark.xdist_group("g1")
@pytest.mark.parametrize("value", ["a@b]", "plain"])
def test_param(value):
    assert value


def test_ordinary():
    pass


@pytest.mark.skip(reason="not today")
def test_skipped():
    pass


@pytest.mark.xfail(reason="known")
def test_xfailed():
    assert False
"""

IDENTITY = {
    # canonical id: (parameter id, requested group, effective group in the parallel run)
    "test_mixed.py::test_param[a@b]]": ("a@b]", "g1", "g1"),
    "test_mixed.py::test_param[plain]": ("plain", "g1", "g1"),
    "test_mixed.py::test_ordinary": (None, None, None),
    "test_mixed.py::test_skipped": (None, None, None),
    "test_mixed.py::test_xfailed": (None, None, None),
}


def manifest_records(rec, role):
    return [(n, r) for n, r in records(rec, "collection-manifest") if n.startswith(f"journal-{role}-")]


def test_a_serial_run_writes_the_ordered_collection_manifest(project, er, tmp_path):
    # R1: the ordered collected identities are in the journal, not only a count and a hash.
    project.makepyfile(test_mixed=MIXED)
    expected = collected_ids(project)
    rec = tmp_path / "rec"

    run_serial(project, rec).assert_outcomes(passed=3, skipped=1, xfailed=1)

    ((_, manifest),) = records(rec, "collection-manifest")
    assert (manifest["source"], manifest["source_worker"], manifest["count"]) == ("session", None, 5)
    assert manifest["raw_ids"] == expected  # the same ids in the same order as the serial collection
    by_raw = dict(zip(manifest["raw_ids"], manifest["identities"], strict=True))
    for canonical, (param, group, _effective) in IDENTITY.items():
        assert by_raw[canonical] == {
            "canonical_id": canonical,
            "param_id": param,
            "requested_group": group,
            "effective_group": None,  # a serial run adds no `@group` suffix
        }
    summary = er.reduce_journals(rec, expected)
    assert summary["accepted"], summary["problems"]
    assert summary["collection"] == {"collected": 5, "never_started": [], "nodes": {}}


def test_the_controller_writes_a_manifest_for_each_worker_that_equals_the_workers_own(project, er, tmp_path):
    # R1: "a collection manifest written by the controller".
    project.makepyfile(test_mixed=MIXED)
    expected = collected_ids(project)
    rec = tmp_path / "rec"

    run_parallel(project, rec).assert_outcomes(passed=3, skipped=1, xfailed=1)

    nodes = {r["source_worker"]: r for _, r in manifest_records(rec, "controller")}
    own = {r["worker"]: r for _, r in manifest_records(rec, "worker")}
    assert sorted(nodes) == ["gw0", "gw1"] == sorted(own)
    for worker, record in nodes.items():
        assert record["source"] == "node" and "identities" not in record
        assert record["raw_ids"] == own[worker]["raw_ids"], "the controller and the worker saw different ids"
        assert record["count"] == 5
    raw_ids = nodes["gw0"]["raw_ids"]
    assert [i["canonical_id"] for i in own["gw0"]["identities"]] == expected
    assert [raw for raw in raw_ids if raw.endswith("@g1")] == [
        "test_mixed.py::test_param[a@b]]@g1",
        "test_mixed.py::test_param[plain]@g1",
    ]
    summary = er.reduce_journals(rec, expected)
    assert summary["accepted"], summary["problems"]
    assert summary["collection"] == {"collected": 5, "never_started": [], "nodes": {"gw0": 5, "gw1": 5}}


def test_a_run_stopped_by_the_first_failure_shows_the_items_that_never_started(project, er, tmp_path):
    project.makepyfile(
        test_mod="def test_a():\n    assert False\n\n\ndef test_b():\n    pass\n\n\ndef test_c():\n    pass\n"
    )
    expected = collected_ids(project)
    rec = tmp_path / "rec"

    run_serial(project, rec, "-x").assert_outcomes(failed=1)

    for reference in (expected, None):  # the manifest alone is enough; the serial reference only adds to it
        summary = er.reduce_journals(rec, reference)
        assert summary["collection"]["never_started"] == expected[1:]
        assert "never-started" in kinds(summary["problems"])
        assert summary["accepted"] is False
        assert list(summary["items"]) == expected[:1]


KILLED_GROUP = """
import os

import pytest

pytestmark = pytest.mark.xdist_group("g1")


def test_before():
    pass


def test_dies():
    os._exit(7)


def test_after():
    pass
"""


def test_a_killed_workers_unstarted_items_and_crashed_item_are_visible(project, er, tmp_path):
    # R1 and R2: the group runs on one worker; it dies in the second test, so the third never starts, and the
    # controller's crash report (no item object there) is joined to the manifest by its raw id.
    project.makepyfile(test_mod=KILLED_GROUP)
    expected = collected_ids(project)
    rec = tmp_path / "rec"

    run_parallel(project, rec, "--max-worker-restart=0")

    summary = er.reduce_journals(rec, expected)
    assert summary["collection"]["never_started"] == [expected[2]]
    assert {"never-started", "item-unfinished"} <= kinds(summary["problems"])
    unfinished = next(p for p in summary["problems"] if p["kind"] == "item-unfinished")
    assert unfinished["crash_recorded"] is True and unfinished["phases_seen"] == ["setup"]
    assert "crash-unrecorded" not in kinds(summary["problems"])
    ((_, crash),) = [(n, r) for n, r in records(rec, "phase") if r["when"] == "???"]
    assert crash["nodeid"] == expected[1] + "@g1"
    assert (crash["canonical_id"], crash["param_id"], crash["requested_group"], crash["effective_group"]) == (
        None,
        None,
        None,
        None,
    )  # the controller has no item: the identity is the manifest row of the same raw id
    assert summary["first_failure"]["resolved"] == {
        "canonical_id": expected[1],
        "param_id": None,
        "requested_group": "g1",
        "effective_group": "g1",
    }
    (start,) = [r for _, r in records(rec, "item-start") if r["canonical_id"] == expected[1]]
    assert (start["nodeid"], start["param_id"], start["requested_group"], start["effective_group"]) == (
        expected[1] + "@g1",
        None,
        "g1",
        "g1",
    )


def test_every_phase_record_carries_the_identity_of_its_item(project, er, tmp_path):
    # R2: ordinary, parameterized, skipped and xfail items; every phase, not only the item-start.
    project.makepyfile(test_mixed=MIXED)
    rec = tmp_path / "rec"

    run_parallel(project, rec).assert_outcomes(passed=3, skipped=1, xfailed=1)

    phases = [r for n, r in records(rec, "phase") if n.startswith("journal-worker-")]
    by_item: dict[str, list] = {}
    for record in phases:
        by_item.setdefault(record["canonical_id"], []).append(record)
    assert sorted(by_item) == sorted(IDENTITY)
    for canonical, (param, group, effective) in IDENTITY.items():
        for record in by_item[canonical]:
            assert (record["param_id"], record["requested_group"], record["effective_group"]) == (
                param,
                group,
                effective,
            )
            assert record["nodeid"] == canonical + (f"@{effective}" if effective else "")
    whens = {canonical: [r["when"] for r in rows] for canonical, rows in by_item.items()}
    assert whens["test_mixed.py::test_skipped"] == ["setup", "teardown"]  # a setup skip has no call phase
    assert all(w == ["setup", "call", "teardown"] for c, w in whens.items() if c != "test_mixed.py::test_skipped")
    skipped = by_item["test_mixed.py::test_skipped"][0]
    assert (skipped["outcome"], skipped["reason"]) == ("skipped", "Skipped: not today")
    (xfailed,) = [r for r in by_item["test_mixed.py::test_xfailed"] if r["when"] == "call"]
    assert (xfailed["outcome"], xfailed["xfail"], xfailed["reason"]) == ("skipped", True, "known")
    starts = {r["canonical_id"]: r for n, r in records(rec, "item-start")}
    assert starts["test_mixed.py::test_param[a@b]]"]["param_id"] == "a@b]"
    assert er.reduce_journals(rec, collected_ids(project))["accepted"]


def test_the_manifest_tells_a_controller_and_a_worker_that_disagree(er, tmp_path):
    rows = [("t.py::a@g", "g"), ("t.py::b@g", "g")]
    write_journal(tmp_path, "controller", 10, extra=[("collection-manifest", manifest_fields(rows[:1], "node", "gw0"))])
    write_journal(tmp_path, "worker", 11, worker="gw0", starts=rows, collected=rows)

    summary = er.reduce_journals(tmp_path)

    assert "manifest-disagreement" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_a_process_that_wrote_no_collection_manifest_is_not_accepted(er, tmp_path):
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)], manifest=False)

    summary = er.reduce_journals(tmp_path, ["t.py::a"])

    assert kinds(summary["problems"]) == {"manifest-missing"}
    assert summary["accepted"] is False
    assert summary["collection"]["collected"] is None


def test_a_collection_that_differs_from_the_serial_reference_is_refused(er, tmp_path):
    rows = [("t.py::a", None), ("t.py::b", None)]
    write_journal(tmp_path, "serial", 11, starts=rows)

    summary = er.reduce_journals(tmp_path, ["t.py::a", "t.py::c"])

    assert "collection-mismatch" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_collected_items_that_were_not_started_are_listed_from_the_manifest_alone(er, tmp_path):
    collected = [("t.py::a", None), ("t.py::b", None), ("t.py::c", None)]
    write_journal(tmp_path, "serial", 11, starts=collected[:1], collected=collected)

    summary = er.reduce_journals(tmp_path)

    assert summary["collection"]["never_started"] == ["t.py::b", "t.py::c"]
    assert [p["nodeid"] for p in summary["problems"] if p["kind"] == "never-started"] == ["t.py::b", "t.py::c"]
    assert summary["accepted"] is False


# R3: every started item must have the outcomes pytest gives it.

PASSED = [("setup", "passed"), ("call", "passed"), ("teardown", "passed")]


@pytest.mark.parametrize(
    ("phases", "problem"),
    [
        (PASSED, None),
        ([("setup", "skipped"), ("teardown", "passed")], None),  # a setup skip: no call
        ([("setup", "failed"), ("teardown", "passed")], None),  # a setup failure: no call
        ([("setup", "passed"), ("call", "failed"), ("teardown", "passed")], None),
        ([("setup", "passed"), ("call", "skipped"), ("teardown", "failed")], None),
        ([], "phase-missing"),  # nothing recorded at all
        ([("setup", "passed"), ("teardown", "passed")], "phase-missing"),  # the call after a good setup is lost
        ([("setup", "passed"), ("call", "passed")], "phase-missing"),  # an interrupted teardown
        ([("call", "passed"), ("teardown", "passed")], "phase-missing"),  # no setup
        ([("setup", "skipped"), ("call", "passed"), ("teardown", "passed")], "phase-order"),  # a call after a skip
        ([("setup", "failed"), ("call", "passed"), ("teardown", "passed")], "phase-order"),  # and after a failure
        ([("setup", "passed"), ("call", "passed"), ("call", "passed"), ("teardown", "passed")], "phase-order"),
        ([("teardown", "passed"), ("setup", "passed"), ("call", "passed")], "phase-order"),
    ],
    ids=[
        "ordinary",
        "setup-skip",
        "setup-failure",
        "call-failure",
        "skip-then-teardown-failure",
        "no-phase-at-all",
        "call-lost",
        "teardown-lost",
        "setup-lost",
        "call-after-skip",
        "call-after-failure",
        "call-twice",
        "wrong-order",
    ],
)
def test_the_phases_of_an_ended_item_are_checked_against_what_pytest_does(er, tmp_path, phases, problem):
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)], phases={"t.py::a": phases})

    summary = er.reduce_journals(tmp_path, ["t.py::a"])

    found = kinds(summary["problems"])
    assert found == ({problem} if problem else set()), summary["problems"]
    assert summary["accepted"] is (problem is None)


def test_a_record_of_another_schema_version_is_refused_and_the_docstring_says_so(er, tmp_path):
    assert er.SCHEMA_VERSION == 2 and er.HANDOFF_VERSION == 1
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None), ("t.py::b", None)])
    damaged(path, "item-start", v=1)

    summary = er.reduce_journals(tmp_path, ["t.py::a", "t.py::b"])

    assert "bad-field" in kinds(summary["problems"]) and summary["accepted"] is False
    flat = " ".join(er.__doc__.split())
    for text in (
        "schema version, 2",
        "collection-manifest the ordered collected identities",
        "EVERY phase carries them",
        "joins them and shows the row as `resolved`",
        "phase-missing (an item that ended lacks its setup",
        "never-started (collected but never started",
        "crash-unrecorded (an unfinished item of a worker",
        "passes `require_phases=False`",
    ):
        assert text in flat, text


def test_a_phase_that_belongs_to_no_started_item_is_reported(er, tmp_path):
    extra = [("phase", phase_fields("t.py::ghost", None, "call", "passed"))]
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)], extra=extra)

    summary = er.reduce_journals(tmp_path, ["t.py::a"])

    assert "phase-outside-item" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_a_probe_run_without_test_bodies_can_ask_not_to_need_phases(er, tmp_path):
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None), ("t.py::b", None)], phases=False)

    assert er.reduce_journals(tmp_path, ["t.py::a", "t.py::b"])["accepted"] is False
    summary = er.reduce_journals(tmp_path, ["t.py::a", "t.py::b"], require_phases=False)
    assert summary["accepted"], summary["problems"]


def test_an_unfinished_item_with_a_crash_record_says_so_and_one_without_is_a_new_problem(er, tmp_path):
    unfinished = [("t.py::a@g", "g", [("setup", "passed")])]
    write_journal(tmp_path, "worker", 11, worker="gw0", trailer=False, unfinished=unfinished)

    lonely = er.reduce_journals(tmp_path)
    assert {"item-unfinished", "crash-unrecorded"} <= kinds(lonely["problems"])

    down = [("worker-down", {"down_worker": "gw0", "has_error": True, "error_text": "crashed"})]
    write_journal(tmp_path, "controller", 10, extra=down)
    recorded = er.reduce_journals(tmp_path)
    assert "item-unfinished" in kinds(recorded["problems"])
    assert "crash-unrecorded" not in kinds(recorded["problems"])
    assert next(p for p in recorded["problems"] if p["kind"] == "item-unfinished")["crash_recorded"] is True
    assert recorded["accepted"] is False


NEGATIVE_CONFTEST = """
import experiment_record

experiment_record.Recorder.pytest_runtest_logreport = lambda self, report: None  # the phase writer is off


def pytest_addoption(parser):
    experiment_record.add_option(parser)


def pytest_configure(config):
    experiment_record.configure(config)
"""


def test_a_failing_test_whose_phase_lines_were_never_written_is_not_accepted(project, er, tmp_path):
    # R3: with only the phase writer disabled, the reducer used to say complete, accepted, no problem, no failure.
    project.makeconftest(NEGATIVE_CONFTEST)
    project.makepyfile(test_mod="def test_fails():\n    assert False\n\n\ndef test_ok():\n    pass\n")
    expected = collected_ids(project)
    rec = tmp_path / "rec"

    run_serial(project, rec).assert_outcomes(failed=1, passed=1)

    assert not list(records(rec, "phase"))
    summary = er.reduce_journals(rec, expected)
    assert summary["status"] == "complete" and summary["first_failure"] is None  # the symptom the maintainers saw
    assert summary["problem_counts"]["phase-missing"] == 2
    assert summary["accepted"] is False


def without_phases(rec):
    """Remove every phase line of every journal in `rec`, renumber the rest and fix the trailer's count."""
    for path in Path(rec).glob("journal-*.jsonl"):
        kept = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]
        kept = [r for r in kept if r["kind"] != "phase"]
        for number, record in enumerate(kept, 1):
            record["seq"] = number
            if record["kind"] == "trailer":
                record["records"] = number - 1
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in kept) + "\n", encoding="utf-8")


@pytest.mark.parametrize("parallel", [False, True], ids=["serial", "parallel"])
def test_real_journals_with_every_phase_line_removed_are_refused(project, er, tmp_path, parallel):
    project.makepyfile(test_mixed=MIXED)
    expected = collected_ids(project)
    rec = tmp_path / "rec"
    (run_parallel if parallel else run_serial)(project, rec).assert_outcomes(passed=3, skipped=1, xfailed=1)
    assert er.reduce_journals(rec, expected)["accepted"], "the real journals are accepted before the lines go"

    without_phases(rec)

    summary = er.reduce_journals(rec, expected)
    assert summary["status"] == "complete" and "sequence-gap" not in kinds(summary["problems"])
    assert summary["problem_counts"]["phase-missing"] == 5  # one per item
    assert summary["accepted"] is False


MANY_OUTCOMES = """
import pytest


@pytest.fixture
def broken_setup():
    raise RuntimeError("setup")


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown")


def test_fail():
    assert False


def test_setup_error(broken_setup):
    pass


def test_teardown_error(broken_teardown):
    pass


@pytest.mark.skipif(True, reason="never")
def test_skip():
    pass


@pytest.mark.xfail(reason="x")
def test_xfail():
    assert False


@pytest.mark.xfail(reason="x")
def test_xpass():
    pass


def test_ok():
    pass
"""


def test_every_ordinary_pytest_outcome_is_reconciled_without_a_problem(project, er, tmp_path):
    # Guard against a check that is too strict: failures, errors in setup and teardown, skips and xfail are valid.
    project.makepyfile(test_many=MANY_OUTCOMES)
    expected = collected_ids(project)
    rec = tmp_path / "rec"

    run_serial(project, rec)

    summary = er.reduce_journals(rec, expected)
    assert summary["problems"] == [], summary["problems"]
    assert summary["accepted"] is True and summary["first_failure"] is not None


# --- the PR 588 CI addendum: pytest's own run variables are not masked -------------------------------------------

RUN_VARIABLES = (
    "PYTEST_CURRENT_TEST",
    "PYTEST_VERSION",
    "PYTEST_XDIST_WORKER",
    "PYTEST_XDIST_TESTRUNUID",
    "PYTEST_ADDOPTS",
)


def test_pytests_own_run_variables_are_not_masked_but_an_ordinary_value_next_to_them_is(er, tmp_path, monkeypatch):
    # CI on Linux: PYTEST_CURRENT_TEST holds the current test's id, and `:` is the path separator there, so its
    # part `test_mod.py` matched ordinary error text: `test_mod.py:6: AssertionError` became `<env:...>:6: ...`.
    current = os.pathsep.join(["test_mod.py", "test_x (call)"])
    monkeypatch.setenv("PYTEST_CURRENT_TEST", current)
    others = {name: f"{name.lower()}-value-1234" for name in RUN_VARIABLES if name != "PYTEST_CURRENT_TEST"}
    for name, value in others.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("P3_S_NEXT_TO_IT", "ordinary-value-9Kq2")
    text = " | ".join(["test_mod.py:6: AssertionError", current, *others.values(), "ordinary-value-9Kq2"])
    recorder, _ = _recorder(er, tmp_path)
    try:
        fields = recorder.error_fields(text)
        reason = recorder.reason_fields(text)
    finally:
        recorder.close()
    kept = text.replace("ordinary-value-9Kq2", "<env:P3_S_NEXT_TO_IT>")
    assert fields["error_text"] == kept
    assert fields["error_redactions"] == 1
    assert (reason["reason"], reason["reason_redactions"]) == (kept, 1)
    assert fields["error_digest"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_docstring_states_that_pytests_run_variables_are_not_masked(er):
    flat = " ".join(er.__doc__.split())
    assert "except the variables whose names start with `PYTEST_`" in flat
    assert "pytest's own run variables (every `PYTEST_*`" in flat


# --- fix round 8: nested runs reconciled, a missing controller journal, require_phases and order -----------------

NESTED_NEGATIVE_PARENT = (
    NESTED_PARENT.replace(NESTED_CONFTEST, json.dumps(NEGATIVE_CONFTEST)[1:-1])  # the child's phase writer is off
    .replace('f"    assert {experiment_record.HANDOFF_ENV!r} not in os.environ\\n"', '"    assert False\\n"')
    .replace("assert done.returncode == 0", "assert done.returncode == 1")  # the child's test fails, as it should
)


def test_a_nested_run_whose_phase_lines_were_never_written_is_not_accepted(project, er, tmp_path):
    # R3 for a nested run: with only the phase writer off in a nested child that has a failing test, the reducer said
    # accepted, no problem, no failure, because nested journals skipped the reconciliation.
    project.makepyfile(test_parent=NESTED_NEGATIVE_PARENT)
    rec = tmp_path / "rec"

    run_serial(project, rec, "-k", "test_with_the_helper").assert_outcomes(passed=1)

    ((_, launch),) = records(rec, "nested-launch")
    summary = er.reduce_journals(rec, ["test_parent.py::test_with_the_helper"])
    assert summary["nested"] == {"launched": 1, "journaled": 1} and summary["first_failure"] is None
    missing = [p for p in summary["problems"] if p["kind"] == "phase-missing"]
    assert [p["nested_run"] for p in missing] == [launch["token"]], summary["problems"]
    assert list(summary["items"]) == ["test_parent.py::test_with_the_helper"]  # no nested id in the root collection
    assert summary["accepted"] is False


NESTED_TOKEN = "0123456789abcdef"


def test_nested_journals_are_reconciled_per_run_and_their_ids_stay_out_of_the_root_collection(er, tmp_path):
    launch = [("nested-launch", {"token": NESTED_TOKEN})]
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)], extra=launch)
    backwards = [("teardown", "passed"), ("setup", "passed"), ("call", "passed")]
    write_journal(
        tmp_path, "nested", 12, nested_token=NESTED_TOKEN, starts=[("t.py::a", None)], phases={"t.py::a": backwards}
    )

    summary = er.reduce_journals(tmp_path, ["t.py::a"])

    assert [(p["kind"], p["nested_run"]) for p in summary["problems"]] == [("phase-order", NESTED_TOKEN)]
    assert summary["items"]["t.py::a"]["started"] == 1  # the nested item of the same id is not the root item
    assert summary["accepted"] is False


def test_a_nested_workers_unfinished_item_needs_a_crash_record_of_its_own_run(er, tmp_path):
    launch = [("nested-launch", {"token": NESTED_TOKEN})]
    root_down = [("worker-down", {"down_worker": "gw0", "has_error": True, "error_text": "root crash"})]
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)], extra=launch)
    write_journal(tmp_path, "controller", 10, extra=root_down)  # a crash of ANOTHER run's gw0
    unfinished = [("n.py::x@g", "g", [("setup", "passed")])]
    write_journal(tmp_path, "worker", 13, worker="gw0", nested_token=NESTED_TOKEN, trailer=False, unfinished=unfinished)

    lonely = er.reduce_journals(tmp_path)
    assert {"item-unfinished", "crash-unrecorded"} <= kinds(lonely["problems"])

    nested_down = [("worker-down", {"down_worker": "gw0", "has_error": True, "error_text": "nested crash"})]
    write_journal(tmp_path, "nested", 12, nested_token=NESTED_TOKEN, extra=nested_down)
    recorded = er.reduce_journals(tmp_path)
    assert "crash-unrecorded" not in kinds(recorded["problems"])
    assert next(p for p in recorded["problems"] if p["kind"] == "item-unfinished")["crash_recorded"] is True


def test_a_two_worker_run_without_its_controller_journal_is_refused(project, er, tmp_path):
    # The manifest checks used to depend on the controller journal being there; removing it left accepted=true.
    project.makepyfile(test_mixed=MIXED)
    expected = collected_ids(project)
    rec = tmp_path / "rec"
    run_parallel(project, rec).assert_outcomes(passed=3, skipped=1, xfailed=1)
    assert er.reduce_journals(rec, expected)["accepted"], "the real journals are accepted before the file goes"

    (controller,) = rec.glob("journal-controller-*.jsonl")
    controller.unlink()

    summary = er.reduce_journals(rec, expected)
    assert "controller-missing" in kinds(summary["problems"])
    assert summary["accepted"] is False


def test_worker_journals_with_no_controller_journal_are_refused_and_a_serial_run_is_not(er, tmp_path):
    write_journal(tmp_path, "worker", 11, worker="gw0", starts=[("t.py::a@g", "g")])
    assert "controller-missing" in kinds(er.reduce_journals(tmp_path, ["t.py::a"])["problems"])
    other = tmp_path / "serial"
    other.mkdir()
    write_journal(other, "serial", 12, starts=[("t.py::a", None)])
    assert er.reduce_journals(other, ["t.py::a"])["accepted"]


@pytest.mark.parametrize(
    "phases",
    [
        PASSED,
        [("setup", "passed"), ("teardown", "passed")],
        [("setup", "passed")],
        [("teardown", "passed"), ("setup", "passed"), ("call", "passed")],
        [("setup", "skipped"), ("call", "passed"), ("teardown", "passed")],
        [("setup", "passed"), ("call", "passed"), ("call", "passed"), ("teardown", "passed")],
    ],
    ids=["ordinary", "call-lost", "setup-only", "wrong-order", "call-after-skip", "call-twice"],
)
def test_require_phases_false_refuses_any_phase_of_a_started_item(er, tmp_path, phases):
    # The lead's ruling: a no-body probe has NO phase at all, so any phase (a probe that ran a body by mistake, a phase
    # out of order, a lone setup) is a problem of its own kind, and the run is not accepted.
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)], phases={"t.py::a": phases})

    summary = er.reduce_journals(tmp_path, ["t.py::a"], require_phases=False)

    assert kinds(summary["problems"]) == {"phase-in-no-body-probe"}, summary["problems"]
    assert summary["problems"][0]["nodeid"] == "t.py::a"
    assert summary["accepted"] is False


def test_require_phases_false_accepts_a_probe_with_no_phase_and_the_default_still_refuses_it(er, tmp_path):
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)], phases={"t.py::a": []})

    accepted = er.reduce_journals(tmp_path, ["t.py::a"], require_phases=False)
    refused = er.reduce_journals(tmp_path, ["t.py::a"])

    assert accepted["problems"] == [] and accepted["accepted"] is True
    assert kinds(refused["problems"]) == {"phase-missing"} and refused["accepted"] is False


def test_require_phases_false_also_refuses_phases_of_an_unfinished_item_and_of_a_nested_run(er, tmp_path):
    unfinished = [("t.py::a", None, [("setup", "passed")])]
    write_journal(tmp_path, "serial", 11, trailer=False, unfinished=unfinished)
    summary = er.reduce_journals(tmp_path, require_phases=False)
    assert "phase-in-no-body-probe" in kinds(summary["problems"])

    other = tmp_path / "nested"
    other.mkdir()
    launch = [("nested-launch", {"token": NESTED_TOKEN})]
    write_journal(other, "serial", 11, starts=[("t.py::a", None)], phases={"t.py::a": []}, extra=launch)
    write_journal(other, "nested", 12, nested_token=NESTED_TOKEN, starts=[("n.py::x", None)])  # ran its body
    nested = er.reduce_journals(other, ["t.py::a"], require_phases=False)
    assert [(p["kind"], p["nested_run"]) for p in nested["problems"]] == [("phase-in-no-body-probe", NESTED_TOKEN)]


def test_the_docstring_states_the_round_8_rules(er):
    flat = " ".join(er.__doc__.split())
    for text in (
        "controller-missing (worker journals of a root run and no controller journal",
        "Nested journals are reconciled the same way, run by run",
        "requires that a started item has NO phase at all",
        "phase-in-no-body-probe (under `require_phases=False`",
        "about 3 KB per item",
        "P8's dry run measures the real serial journal size",
    ):
        assert text in flat, text


# --- fix round 9: the automated reviewer's P1 (reparse points) and three P2 ----------------------------------------


def _a_journal_outside(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    return write_journal(outside, "serial", 11, starts=[("t.py::a", None)])


def _folder_with_a_link_to(target, tmp_path):
    folder = tmp_path / "record"
    folder.mkdir()
    link = folder / target.name
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot create a symbolic link here")
    return folder


def test_a_symbolic_link_named_like_a_journal_is_refused(er, tmp_path):
    # P1: Windows has no O_NOFOLLOW, so the open followed the link and fstat saw only a plain target.
    folder = _folder_with_a_link_to(_a_journal_outside(tmp_path), tmp_path)

    summary = er.reduce_journals(folder, ["t.py::a"])

    assert kinds(summary["problems"]) >= {"journal-not-plain"}, summary["problems"]
    assert summary["status"] == "incomplete" and summary["items"] == {}
    assert summary["accepted"] is False


def _lstat_that(monkeypatch, name, change):
    """os.lstat of the path whose last part is `name` answers through `change(result, call_number)`."""
    real = os.lstat
    calls = []

    def fake(path, *args, **kwargs):
        result = real(path, *args, **kwargs)
        if Path(path).name != name:
            return result
        calls.append(path)
        fields = {k: getattr(result, k) for k in ("st_mode", "st_dev", "st_ino", "st_nlink", "st_size")}
        fields["st_file_attributes"] = getattr(result, "st_file_attributes", 0)
        return SimpleNamespace(**change(fields, len(calls)))

    monkeypatch.setattr(os, "lstat", fake)


@pytest.mark.parametrize("looks", ["every-look", "first-look-only"])
def test_a_journal_that_lstat_shows_as_a_reparse_point_is_refused_on_every_system(er, tmp_path, monkeypatch, looks):
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    assert er.reduce_journals(tmp_path, ["t.py::a"])["accepted"], "the journal is fine before the attribute is set"
    first_only = looks == "first-look-only"

    _lstat_that(
        monkeypatch,
        path.name,
        lambda fields, call: {**fields, "st_file_attributes": 1024 * (call == 1 or not first_only)},
    )

    summary = er.reduce_journals(tmp_path, ["t.py::a"])
    assert kinds(summary["problems"]) >= {"journal-not-plain"}, summary["problems"]
    assert summary["accepted"] is False


def test_a_journal_that_becomes_a_reparse_point_while_it_is_opened_is_refused(er, tmp_path, monkeypatch):
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    _lstat_that(monkeypatch, path.name, lambda fields, call: {**fields, "st_file_attributes": 1024 * (call > 1)})

    summary = er.reduce_journals(tmp_path, ["t.py::a"])

    assert "journal-not-plain" in kinds(summary["problems"]), summary["problems"]
    assert summary["accepted"] is False


def test_a_journal_whose_identity_changes_while_it_is_opened_is_refused(er, tmp_path, monkeypatch):
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    _lstat_that(monkeypatch, path.name, lambda fields, call: {**fields, "st_ino": fields["st_ino"] + (call > 1)})

    summary = er.reduce_journals(tmp_path, ["t.py::a"])

    assert kinds(summary["problems"]) >= {"journal-not-plain"}, summary["problems"]
    assert summary["accepted"] is False


def test_a_record_folder_that_is_a_link_is_refused(er, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    write_journal(real, "serial", 11, starts=[("t.py::a", None)])
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot create a symbolic link here")

    summary = er.reduce_journals(link, ["t.py::a"])

    assert "folder-not-plain" in kinds(summary["problems"]), summary["problems"]
    assert summary["processes"] == [] and summary["accepted"] is False


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is a Windows reparse point")
def test_a_record_folder_that_is_a_real_junction_is_refused(er, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    write_journal(real, "serial", 11, starts=[("t.py::a", None)])
    junction = tmp_path / "junction"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(real)], capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip(f"cannot create a junction here: {made.stdout} {made.stderr}")

    summary = er.reduce_journals(junction, ["t.py::a"])

    assert "folder-not-plain" in kinds(summary["problems"]), summary["problems"]
    assert summary["processes"] == [] and summary["accepted"] is False
    assert er.reduce_journals(real, ["t.py::a"])["accepted"], "the target itself is a plain folder"


def test_a_record_folder_that_lstat_shows_as_a_reparse_point_is_refused_on_every_system(er, tmp_path, monkeypatch):
    folder = tmp_path / "record"
    folder.mkdir()
    write_journal(folder, "serial", 11, starts=[("t.py::a", None)])
    _lstat_that(monkeypatch, "record", lambda fields, call: {**fields, "st_file_attributes": 1024})

    summary = er.reduce_journals(folder, ["t.py::a"])

    assert "folder-not-plain" in kinds(summary["problems"]), summary["problems"]
    assert summary["accepted"] is False


def test_a_missing_or_plain_folder_is_not_a_folder_problem(er, tmp_path):
    write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    assert er.reduce_journals(tmp_path, ["t.py::a"])["accepted"]
    assert er.reduce_journals(tmp_path / "nowhere")["problems"] == []  # nothing to read: incomplete, as before


def test_a_nested_run_whose_parent_also_turned_recording_on_through_pytest_addopts_is_still_nested(
    project, er, tmp_path
):
    # P2: the inherited option won over the handoff, so the child was labelled `serial` and the join failed.
    project.makepyfile(test_parent=NESTED_PARENT)
    rec = tmp_path / "rec"

    run_serial(project, rec, "-k", "test_helper_plus_addopts").assert_outcomes(passed=1)

    ((_, launch),) = records(rec, "nested-launch")
    roles = sorted(r["role"] for _, r in records(rec, "process-start"))
    assert roles == ["nested", "serial"], roles
    ((_, nested_start),) = [(n, r) for n, r in records(rec, "process-start") if r["role"] == "nested"]
    assert nested_start["nested_token"] == launch["token"]
    summary = er.reduce_journals(rec, ["test_parent.py::test_helper_plus_addopts"])
    assert summary["accepted"], summary["problems"]
    assert summary["nested"] == {"launched": 1, "journaled": 1}


@pytest.mark.parametrize(
    "version",
    [1, 3, 0, "2", 2.0, True, [2], None],
    ids=["one", "three", "zero", "text", "float", "bool", "list", "missing"],
)
def test_a_record_with_any_other_schema_version_is_refused(er, tmp_path, version):
    # P2: the common `v` field is checked for every record; a missing, damaged or other version is a bad-field.
    path = write_journal(tmp_path, "serial", 11, starts=[("t.py::a", None)])
    assert er.reduce_journals(tmp_path, ["t.py::a"])["accepted"] and er.reduce_journals(tmp_path)["schema"] == 2
    damaged(path, "process-start", v=version)

    summary = er.reduce_journals(tmp_path, ["t.py::a"])

    assert "bad-field" in kinds(summary["problems"]), summary["problems"]
    assert summary["accepted"] is False


def test_too_many_journal_bytes_are_refused_before_any_is_parsed(er, tmp_path, monkeypatch):
    # P2: each journal may be 64 MiB and all parsed journals were kept until the end.
    for pid in (11, 12, 13):
        write_journal(tmp_path, "serial", pid, starts=[("t.py::a", None)])
    total = sum(p.stat().st_size for p in tmp_path.glob("journal-*.jsonl"))
    monkeypatch.setattr(er, "_read_journal", lambda *a, **k: pytest.fail("a journal was parsed"))
    monkeypatch.setattr(er, "MAX_TOTAL_JOURNAL_BYTES", total - 1)

    summary = er.reduce_journals(tmp_path, ["t.py::a"])

    assert "input-too-large" in kinds(summary["problems"]), summary["problems"]
    assert summary["processes"] == [] and summary["status"] == "incomplete" and summary["accepted"] is False


def test_too_many_journals_are_refused_before_any_is_parsed(er, tmp_path, monkeypatch):
    for pid in (11, 12, 13):
        write_journal(tmp_path, "serial", pid, starts=[("t.py::a", None)])
    monkeypatch.setattr(er, "_read_journal", lambda *a, **k: pytest.fail("a journal was parsed"))
    monkeypatch.setattr(er, "MAX_JOURNALS", 2)

    summary = er.reduce_journals(tmp_path, ["t.py::a"])

    assert "input-too-large" in kinds(summary["problems"]), summary["problems"]
    assert summary["accepted"] is False


def test_input_exactly_at_the_limits_is_read(er, tmp_path, monkeypatch):
    write_journal(tmp_path, "worker", 11, worker="gw0", starts=[("t.py::a@g", "g")])
    write_journal(tmp_path, "worker", 12, worker="gw1", starts=[("t.py::b@g", "g")])
    total = sum(p.stat().st_size for p in tmp_path.glob("journal-*.jsonl"))
    monkeypatch.setattr(er, "MAX_TOTAL_JOURNAL_BYTES", total)
    monkeypatch.setattr(er, "MAX_JOURNALS", 2)

    summary = er.reduce_journals(tmp_path)

    assert "input-too-large" not in kinds(summary["problems"]) and len(summary["processes"]) == 2


def test_the_docstring_states_the_round_9_limits(er):
    flat = " ".join(er.__doc__.split())
    assert er.MAX_TOTAL_JOURNAL_BYTES == 256 * 1024 * 1024 and er.MAX_JOURNALS == 512
    for text in (
        "input-too-large",
        "folder-not-plain",
        "a link or a reparse point",
        "A valid nested handoff decides the role",
        "at most 512 journals and 256 MiB",
    ):
        assert text in flat, text
