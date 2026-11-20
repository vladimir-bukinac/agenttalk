"""#872: a per-seat state file nested too deeply is damaged, exactly like a malformed one.

Every reader of a per-seat state file must give the same answer for a file nested too deeply as it gives for
plain damaged text, and every caller must carry on. The expected value is never written down twice: each test
runs the same call over ``MALFORMED`` and over the deep file in the same store and compares.
"""

import json
import re
from pathlib import Path

import pytest

from agenttalk import checkpoint, cli, coordination_stall, lead_loop_cadence, lead_routine, reply_refusals
from agenttalk import supervisor, web
from agenttalk.store import Store, unusable_restart_request_marker
from agenttalk.wrapper import session as wrapper_session

MALFORMED = "{not json"
DEEP = "[" * 200000 + "]" * 200000


@pytest.fixture(params=["deep", "forced"])
def too_deep(request, monkeypatch):
    """The text of a file the JSON decoder cannot read: really 200,000 levels deep, or a decoder made to fail."""
    if request.param == "deep":
        try:
            json.loads(DEEP)
        except RecursionError:
            return DEEP
        pytest.skip("JSON decoder accepts the 200,000-level input on this runtime")
    content = '{"force_recursion": true}'
    original = json.loads

    def loads(value, *args, **kwargs):
        if value == content:
            raise RecursionError("forced decoder failure")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", loads)
    return content


@pytest.fixture
def forced_deep(monkeypatch):
    """A decoder made to fail on one text, so a whole command can be run over every file quickly."""
    content = '{"force_recursion": true}'
    original = json.loads

    def loads(value, *args, **kwargs):
        if value == content:
            raise RecursionError("forced decoder failure")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", loads)
    return content


def _store(tmp_path):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    return store


# The per-seat files: where each lives, taken from the code's own path helpers where there is one.
FILES = {
    "waiting": lambda s: s.state_dir / "alpha.waiting",
    "health": lambda s: s.health_path("alpha"),
    "threadstate": lambda s: s.state_dir / "alpha.threadstate.json",
    "lead-loop-lease": lambda s: s.lead_loop_lease_path("alpha"),
    "stand-down": lambda s: s._stand_down_path("alpha"),
    "wrapper-session": lambda s: wrapper_session._session_path(s, "alpha"),
    "composing": lambda s: s.state_dir / "alpha.composing.json",
    "restart-request": lambda s: s.state_dir / "alpha.restart-request",
    "fresh-request": lambda s: s._fresh_request_path("alpha"),
    "gateway-held": lambda s: s._gateway_held_path("alpha"),
    "lead-loop-exit": lambda s: s.lead_loop_exit_path("alpha"),
    "lead-loop-cadence": lambda s: s.lead_loop_cadence_path("alpha"),
    "work-heartbeat": lambda s: s.work_heartbeat_status_path("alpha"),
    "config-blocked-hold": lambda s: s.config_blocked_hold_path("alpha"),
    "usage-limit-park": lambda s: s.usage_limit_park_path("alpha"),
    "dead-letter-attempts": lambda s: s._attempts_path("alpha"),
    "awaiting": lambda s: s._awaiting_path("alpha", "gen1", "tok1"),
    "awaiting-superseded": lambda s: s._waiting_superseded_path("alpha", "tok1"),
    "lead-routine": lambda s: lead_routine.record_path(s, "alpha"),
    "reply-refusal": lambda s: reply_refusals._record_path(s, "alpha", "m1"),
}


def _write(store, kind, text):
    path = FILES[kind](store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _outcome(call, *args):
    """What a call gave: its value, or the name of a ValueError (a refusal), never a crash."""
    try:
        # A message may name the parser's error (JSONDecodeError or RecursionError); that name is the only difference.
        return ("value", re.sub(r"JSONDecodeError|RecursionError", "<parse error>", repr(call(*args))))
    except ValueError:
        return ("refused",)


# Every reader: (file, how to read it). The damaged-file value is whatever the malformed text gives.
READERS = {
    "read_waiting": ("waiting", lambda s: s.read_waiting("alpha")),
    "read_health_raw": ("health", lambda s: s.read_health_raw("alpha")),
    "read_health": ("health", lambda s: s.read_health("alpha", now_epoch=1000.0)),
    "read_threadstate": ("threadstate", lambda s: s.read_threadstate("alpha")),
    "read_lead_loop_lease": ("lead-loop-lease", lambda s: s.read_lead_loop_lease("alpha")),
    "read_stand_down_status": ("stand-down", lambda s: s.read_stand_down_status("alpha")),
    "stand_down_honoured_ids": ("stand-down", lambda s: s.stand_down_honoured_ids("alpha")),
    "stand_down strict": ("stand-down", lambda s: s._read_stand_down("alpha", strict=True)),
    "read_wrapper_runtime": ("wrapper-session", lambda s: s.read_wrapper_runtime("alpha")),
    "read_last_fresh_reset_at": ("wrapper-session", lambda s: s.read_last_fresh_reset_at("alpha")),
    "read_fresh_status": ("wrapper-session", lambda s: s.read_fresh_status("alpha")),
    "session _saved_record": ("wrapper-session", lambda s: wrapper_session._saved_record(s, "alpha")),
    "session _session_backup_valid": (
        "wrapper-session",
        lambda s: wrapper_session._session_backup_valid(wrapper_session._session_path(s, "alpha")),
    ),
    "load_session": ("wrapper-session", lambda s: wrapper_session.load_session(s, "alpha", "codex").cli),
    "read_composing_intent": ("composing", lambda s: s.read_composing_intent("alpha")),
    "read_restart_request": ("restart-request", lambda s: s.read_restart_request("alpha")),
    "read_fresh_request": ("fresh-request", lambda s: s.read_fresh_request("alpha")),
    "read_gateway_held": ("gateway-held", lambda s: s.read_gateway_held("alpha")),
    "read_lead_loop_exit": ("lead-loop-exit", lambda s: s.read_lead_loop_exit("alpha")),
    "read_lead_loop_cadence": ("lead-loop-cadence", lambda s: s.read_lead_loop_cadence("alpha")),
    "read_work_heartbeat_status": ("work-heartbeat", lambda s: s.read_work_heartbeat_status("alpha")),
    "read_config_blocked_hold": ("config-blocked-hold", lambda s: s.read_config_blocked_hold("alpha")),
    "read_usage_limit_park": ("usage-limit-park", lambda s: s.read_usage_limit_park("alpha", now_epoch=1000.0)),
    "dead_letter_attempts": ("dead-letter-attempts", lambda s: s.dead_letter_attempts("alpha")),
    "list_awaiting": ("awaiting", lambda s: s.list_awaiting("alpha")),
    "waiting_superseded": ("awaiting-superseded", lambda s: s.waiting_superseded("alpha", "tok1")),
    "lead_routine.read": ("lead-routine", lambda s: lead_routine.read(s, "alpha")),
    "list_reply_refusals": ("reply-refusal", lambda s: reply_refusals.list_reply_refusals(s, "alpha")),
    "read_reply_refusal": ("reply-refusal", lambda s: reply_refusals.read_reply_refusal(s, "alpha", "m1")),
    "checkpoint _closed_request_ids": (
        "threadstate",
        lambda s: checkpoint._closed_request_ids(s, "alpha"),
    ),
    "send kind-support check": (
        "health",
        lambda s: cli._recipients_behind_kind(s, ["alpha"], kind="task", exclude="beta"),
    ),
}


@pytest.mark.parametrize("name", sorted(READERS))
def test_reader_treats_a_nested_file_like_a_malformed_one(tmp_path, too_deep, name):
    kind, read = READERS[name]
    store = _store(tmp_path)
    _write(store, kind, MALFORMED)
    damaged = _outcome(read, store)
    _write(store, kind, too_deep)
    assert _outcome(read, store) == damaged


def test_a_nested_restart_or_fresh_request_reads_as_the_unusable_marker_never_as_absent(tmp_path, too_deep):
    store = _store(tmp_path)
    for kind, read in (("restart-request", store.read_restart_request), ("fresh-request", store.read_fresh_request)):
        assert read("alpha") is None  # nothing there yet
        _write(store, kind, too_deep)
        assert read("alpha") == unusable_restart_request_marker()


def test_a_nested_stand_down_file_still_lets_the_strict_retry_loop_run(tmp_path, too_deep):
    store = _store(tmp_path)
    _write(store, "stand-down", too_deep)
    with pytest.raises(ValueError, match="nested too deeply"):
        store._read_stand_down("alpha", strict=True)
    assert store._read_stand_down("alpha") == []
    assert store.record_stand_down_honoured("alpha", ["r1"]) is True  # replaces the bad file
    assert store.stand_down_honoured_ids("alpha") == {"r1"}


# --- commands and callers: they carry on, and the other seat still shows ---------------------------------


@pytest.mark.parametrize("as_json", [False, True], ids=["plain", "json"])
@pytest.mark.parametrize(
    "kind", ["waiting", "health", "threadstate", "lead-loop-lease", "stand-down", "wrapper-session"]
)
def test_status_shows_the_other_seat_when_a_seat_file_is_nested(tmp_path, capsys, too_deep, kind, as_json):
    store = _store(tmp_path)
    _write(store, kind, too_deep)
    capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "status"] + (["--json"] if as_json else [])) == 0
    out = capsys.readouterr().out
    names = [a["name"] for a in json.loads(out)["agents"]] if as_json else [w for w in ("alpha", "beta") if w in out]
    assert sorted(names) == ["alpha", "beta"]


def _call_status(store, root):
    return cli.main(["--root", root, "status", "--json"])


def _call_doctor(store, root):
    return cli.main(["--root", root, "doctor"])


def _call_threads(store, root):
    return cli.main(["--root", root, "threads", "--for", "alpha"])


CALLERS = {
    "status --json": _call_status,
    "doctor": _call_doctor,
    "threads": _call_threads,
    "dashboard entries": lambda s, r: web._agent_entries(s, s.load_config(), [], None),
    "supervisor report": lambda s, r: supervisor.build_report(s, now_epoch=1000.0),
    "coordination stall": lambda s, r: coordination_stall.build_snapshot(s),
    "lead cadence": lambda s, r: lead_loop_cadence.build_cadence_snapshot(s, "alpha", now_epoch=1000.0),
    "acquire lease": lambda s, r: s.acquire_lead_loop_lease("alpha", owner_pid=1) is not None,
    "write waiting": lambda s, r: s.write_waiting("alpha", {"pid": 1}),
    "mark thread seen": lambda s, r: s.mark_thread_seen("alpha", "rid", "m1"),
    "lead_loop_state": lambda s, r: s.lead_loop_state("alpha"),
}


@pytest.mark.parametrize("kind", sorted(FILES))
@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_every_caller_carries_on_over_a_nested_seat_file(tmp_path, capsys, forced_deep, caller, kind):
    results = []
    for label, text in (("malformed", MALFORMED), ("deep", forced_deep)):  # a fresh store each: callers may write
        root = tmp_path / label
        store = _store(root)
        _write(store, kind, text)
        results.append(_caller_result(CALLERS[caller], store, str(root)))
        capsys.readouterr()
    assert results[0] == results[1]


def _caller_result(call, store, root):
    """Whether the call ran (and an exit code it returned), never its detailed value."""
    try:
        result = call(store, root)
    except RecursionError:
        return "crashed with RecursionError"
    except Exception as exc:  # noqa: BLE001 - any other outcome only has to be the same for both files
        return type(exc).__name__
    return result if isinstance(result, int) else "ran"


# --- the list itself is part of the review: a seat file the code names must be accounted for -------------------


# Suffixes of `<seat>.<suffix>` files named in the code that are NOT JSON read through a parser (or are read
# elsewhere), each with the reason. Anything else the code names must be in FILES above.
NOT_COVERED_HERE = {
    "cursor": "a plain message id, not JSON",
    "heartbeat": "a timestamp, not JSON",
    "wrapper-owner": "written to claim ownership, never parsed as JSON",
    "waiting.lock": "a lock file; its small owner record is read with a size limit",
    "lead-routine.lock": "a lock file; its small owner record is read with a size limit",
    "lead-loop-lease.lock": "a lock file; its small owner record is read with a size limit",
    "capacity.json": "the capacity reading, fixed in #871",
}
FILE_SUFFIXES = {
    "waiting": ".waiting",
    "health": ".health.json",
    "threadstate": ".threadstate.json",
    "lead-loop-lease": ".lead-loop-lease.json",
    "stand-down": ".stand-down.json",
    "wrapper-session": ".wrapper-session.json",
    "composing": ".composing.json",
    "restart-request": ".restart-request",
    "fresh-request": ".fresh-request",
    "gateway-held": ".gateway-held.json",
    "lead-loop-exit": ".lead-loop-exit.json",
    "lead-loop-cadence": ".lead-loop-cadence.json",
    "lead-routine": ".lead-routine.json",
}


def test_every_per_seat_file_named_in_the_code_is_covered_or_explained():
    source_dir = Path(__file__).resolve().parents[1] / "src" / "agenttalk"
    named = set()
    for path in source_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        named.update(re.findall(r'state_dir / f"\{[^}]+\}\.([A-Za-z0-9][A-Za-z0-9.-]*)"', text))
        named.update(re.findall(r'state_dir / \("%s\.([A-Za-z0-9][A-Za-z0-9.-]*)" %', text))
    assert named, "the search found no per-seat file names: the pattern is out of date"
    covered = {suffix.lstrip(".") for suffix in FILE_SUFFIXES.values()}
    unaccounted = sorted(named - covered - set(NOT_COVERED_HERE))
    assert not unaccounted, f"per-seat files named in the code but not in this test: {unaccounted}"
    for kind in FILE_SUFFIXES:
        assert kind in FILES, kind
