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
from agenttalk import supervisor, web, wrapper_runtime
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
    "capacity": lambda s: s.state_dir / "alpha.capacity.json",
    "operation-intent": lambda s: s._operation_intent_path("alpha", "0" * 32),
    "restart-barrier": lambda s: supervisor._coordination_barrier_path(s, "alpha"),
    "wrapper-runtime-record": lambda s: wrapper_runtime.runtime_path(s.state_dir, "alpha"),
    "availability": lambda s: supervisor._coordination_availability_path(s),
    "checkpoint": lambda s: checkpoint.checkpoint_path(s, "alpha"),
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
    "read_capacity": ("capacity", lambda s: s.read_capacity("alpha")),
    "read_operation_intent": ("operation-intent", lambda s: s.read_operation_intent("alpha", "0" * 32)),
    "read_all_capacities": ("capacity", lambda s: s.read_all_capacities()),
    "coordination barrier observations": (
        "restart-barrier",
        lambda s: supervisor.read_coordination_barrier_observations(s),
    ),
    "coordination availability observation": (
        "availability",
        lambda s: supervisor.read_coordination_availability_observation(s),
    ),
    "wrapper_runtime.read_runtime": (
        "wrapper-runtime-record",
        lambda s: wrapper_runtime.read_runtime(s.state_dir, "alpha", now_epoch=1000.0),
    ),
    "checkpoint _closed_request_ids": (
        "threadstate",
        lambda s: checkpoint._closed_request_ids(s, "alpha"),
    ),
    "send kind-support check": (
        "health",
        lambda s: cli._recipients_behind_kind(s, ["alpha"], kind="task", exclude="beta"),
    ),
    "checkpoint read_checkpoint": ("checkpoint", lambda s: checkpoint.read_checkpoint(s, "alpha")),
}


REJECTS_BY_SIZE_FIRST = {"wrapper_runtime.read_runtime"}


@pytest.mark.parametrize("name", sorted(READERS))
def test_reader_treats_a_nested_file_like_a_malformed_one(tmp_path, too_deep, name):
    kind, read = READERS[name]
    if name in REJECTS_BY_SIZE_FIRST and too_deep == DEEP:
        pytest.skip("this reader refuses a file this large by size before it parses it; the forced variant covers it")
    store = _store(tmp_path)
    _write(store, kind, MALFORMED)
    damaged = _outcome(read, store)
    _write(store, kind, too_deep)
    assert _outcome(read, store) == damaged


@pytest.mark.parametrize(
    ("name", "levels"),
    [
        ("coordination barrier observations", 2000),  # 4,000 bytes: under its 4,096-byte limit
        ("coordination availability observation", 100000),  # 200,000 bytes: under its 262,144-byte limit
        ("wrapper_runtime.read_runtime", 8000),  # 16,000 bytes: under its 16,384-byte limit
    ],
)
def test_size_limited_reader_treats_a_file_nested_within_its_limit_like_a_malformed_one(tmp_path, name, levels):
    text = "[" * levels + "]" * levels
    try:
        json.loads(text)
    except RecursionError:
        pass
    else:
        pytest.skip(f"JSON decoder accepts {levels} levels on this runtime")
    kind, read = READERS[name]
    store = _store(tmp_path)
    _write(store, kind, MALFORMED)
    damaged = _outcome(read, store)
    _write(store, kind, text)
    assert _outcome(read, store) == damaged


def test_a_nested_restart_or_fresh_request_reads_as_the_unusable_marker_never_as_absent(tmp_path, too_deep):
    store = _store(tmp_path)
    for kind, read in (("restart-request", store.read_restart_request), ("fresh-request", store.read_fresh_request)):
        assert read("alpha") is None  # nothing there yet
        _write(store, kind, too_deep)
        assert read("alpha") == unusable_restart_request_marker()


@pytest.mark.parametrize("command", ["save", "resume", "show"])
def test_checkpoint_commands_treat_a_nested_checkpoint_like_a_malformed_one(tmp_path, capsys, too_deep, command):
    results = []
    for label, text in (("malformed", MALFORMED), ("deep", too_deep)):  # a fresh store each: save writes
        root = tmp_path / label
        store = _store(root)
        _write(store, "checkpoint", text)
        capsys.readouterr()
        try:
            code = cli.main(["--root", str(root), "checkpoint", command, "--for", "alpha"])
        except RecursionError:
            code = "crashed with RecursionError"
        out = capsys.readouterr()
        folder = checkpoint.checkpoint_path(store, "alpha").parent
        kept = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
        results.append((code, (out.out + out.err).replace(str(root), "<root>"), kept))
    assert results[0] == results[1]


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


# --- the list itself is part of the review: a per-seat path the code builds must be accounted for ---------------

_SUFFIX = r"[A-Za-z0-9][A-Za-z0-9.-]*"
# The seat part may be any variable, attribute or call: `seat`, `args.agent`, `validate_agent_name(agent)`.
_CALL_ARGS = r"\((?:[^()]|\([^()]*\))*\)"
_SEAT = r"[\w.]+(?:" + _CALL_ARGS + r")?"
_FORMAT_FIELD = r"\{(?:(?!(?P=format_quote))[^{}])*\}"
_F_FIELD = r"\{(?:(?!(?P=f_quote))[^{}])+\}"
_FILE_NAME = (
    r"""(?:(?i:rf|fr|f)(?P<f_quote>["'])"""
    + _F_FIELD
    + r"(?:\."
    + _F_FIELD
    + r")?\."
    + r"(?P<f_suffix>"
    + _SUFFIX
    + r")(?P=f_quote)"
    + r"|\(\s*"
    + _SEAT
    + r"""\s*\+\s*(?i:r|u)?(?P<concat_quote>["'])\."""
    + r"(?P<concat_suffix>"
    + _SUFFIX
    + r")(?P=concat_quote)\s*\)"
    + r"""|\(?\s*(?i:r|u)?(?P<percent_quote>["'])%s(?:\.%s)?\."""
    + r"(?P<percent_suffix>"
    + _SUFFIX
    + r")(?P=percent_quote)\s*%"
    + r"""|(?i:r|u)?(?P<format_quote>["'])"""
    + _FORMAT_FIELD
    + r"(?:\."
    + _FORMAT_FIELD
    + r")?\."
    + r"(?P<format_suffix>"
    + _SUFFIX
    + r")(?P=format_quote)\.format\s*\("
    + r")"
)
# Right after the state folder, or at the start of a line that goes on from one naming it.
_AFTER_STATE = r"(?:state_dir\)?\s*/\s*|^\s*/\s*)"
_IN_FOLDER = re.compile(
    _AFTER_STATE
    + r"""(?:(?P<folder_quote>["'])(?P<folder_name>[\w-]+)(?P=folder_quote)"""
    + r"|(?P<folder_constant>_[A-Z_]+))\s*/\s*"
    + _FILE_NAME
)
_IN_STATE = re.compile(_AFTER_STATE + _FILE_NAME)
_AGENT_FOLDER = re.compile(
    r"""([\w.]+(?:\([\w.]*\))?|(?P<seat_quote>["'])(?P<seat_name>[\w-]+)(?P=seat_quote)) / """
    r"(?:validate_agent_name" + _CALL_ARGS + r"|agent|args\.agent|path_agent|ag|name(?= / generation))(?![\w.])"
)


def _suffix(match):
    return next(
        match.group(name)
        for name in ("f_suffix", "concat_suffix", "percent_suffix", "format_suffix")
        if match.group(name) is not None
    )


def _per_seat_paths_in(lines):
    """Find the claimed single-line f-string, concatenation, percent and str.format path spellings.

    Inspect state_dir, a quoted or constant folder beneath it, its one continuation line,
    and seat-named folders. It reports at most one label per line. Triple quotes, implicitly joined strings, joinpath,
    os.path.join, with_name, with_suffix, Path(folder, name), and names stored in
    variables then joined later are outside this line search. The session backup
    uses with_name and turn events use os.path.join; both are checked separately.
    """
    found = set()
    previous = ""
    for line in lines:
        goes_on = line.lstrip().startswith("/") and "state_dir" in previous
        previous = line
        if "state_dir" in line or goes_on:
            folder = _IN_FOLDER.search(line)
            if folder:
                found.add(f"{folder.group('folder_name') or folder.group('folder_constant')}/*.{_suffix(folder)}")
                continue
            plain = _IN_STATE.search(line)
            if plain:
                found.add("." + _suffix(plain))
                continue
        seat_folder = _AGENT_FOLDER.search(line)
        if seat_folder:
            name = seat_folder.group(1)
            if seat_folder.group("seat_name") is not None:
                name = '"' + seat_folder.group("seat_name") + '"'
            found.add("folder " + name)
    return found


def _per_seat_paths_named_in_the_code():
    found = set()
    for path in (Path(__file__).resolve().parents[1] / "src" / "agenttalk").rglob("*.py"):
        found |= _per_seat_paths_in(path.read_text(encoding="utf-8").split("\n"))
    return found


# label -> the FILES entry that tests it
COVERED = {
    ".capacity.json": "capacity",
    ".composing.json": "composing",
    ".fresh-request": "fresh-request",
    ".gateway-held.json": "gateway-held",
    ".health.json": "health",
    ".lead-loop-cadence.json": "lead-loop-cadence",
    ".lead-loop-exit.json": "lead-loop-exit",
    ".lead-loop-lease.json": "lead-loop-lease",
    ".lead-routine.json": "lead-routine",
    ".restart-request": "restart-request",
    ".stand-down.json": "stand-down",
    ".threadstate.json": "threadstate",
    ".waiting": "waiting",
    ".wrapper-runtime.json": "wrapper-runtime-record",
    ".wrapper-session.json": "wrapper-session",
    "_COORDINATION_BARRIER_DIR/*.json": "restart-barrier",
    "config-blocked-hold/*.json": "config-blocked-hold",
    "dead-letter-attempts/*.json": "dead-letter-attempts",
    "usage-limit-park/*.json": "usage-limit-park",
    "operation-intents/*.json": "operation-intent",
    "waiting-superseded/*.json": "awaiting-superseded",
    "work-heartbeat/*.json": "work-heartbeat",
    "folder self.awaiting_dir": "awaiting",
    "folder reply_refusal_dir(store)": "reply-refusal",
    "checkpoints/*.json": "checkpoint",
}
# label -> why the search cannot find it: covered above, but the path is built outside the state folder and is not a
# seat-named folder, the two places the search reads. Found by hand.
OUTSIDE_THE_SEARCH = {
    "checkpoints/*.json": "<store>/checkpoints/<seat>.json (checkpoint.checkpoint_path), found by hand in #872",
}
# label -> why it is not a per-seat JSON read that needs this test
NOT_COVERED = {
    ".cursor": "a plain message id, not JSON",
    ".heartbeat": "a timestamp, not JSON",
    ".wrapper-owner": "written to claim ownership, never parsed as JSON",
    ".waiting.lock": "a lock file; its small owner record is read with a 4,096-byte limit",
    ".lead-loop-lease.lock": "a lock file; its small owner record is read with a 4,096-byte limit",
    ".lead-routine.lock": "a lock file; its small owner record is read with a 4,096-byte limit",
    'folder "codex-home"': "the seat's own Codex home folder, not agenttalk state",
    'folder "drafts"': "the wrapper's own reply drafts and ledger, with their own rebuild path",
    'folder "reply-drafts"': "reply drafts are Markdown, not JSON",
    "folder _te.default_turn_events_root(store.root)": "turn events: every read already catches RecursionError",
    "folder resolve_scratch_root(project_root)": "scratch folders, not state",
    "folder self.dead_letter_dir": "dead letters, their notes and requeue records: message records, not seat state",
    "folder store.dead_letter_dir": "dead letters, their notes and requeue records: message records, not seat state",
    "folder root": "the dead-letter listing, and the reply-refusal listing (covered as reply-refusal)",
    "folder loop": "a code comment, not a path",
}


def _assert_every_path_accounted_for(named):
    unaccounted = sorted(named - set(COVERED) - set(NOT_COVERED))
    assert not unaccounted, f"per-seat paths named in the code but not accounted for in this test: {unaccounted}"
    stale = sorted((set(COVERED) | set(NOT_COVERED)) - named - set(OUTSIDE_THE_SEARCH))
    assert not stale, f"entries here that the code no longer names: {stale}"


def test_every_per_seat_path_named_in_the_code_is_covered_or_explained():
    named = _per_seat_paths_named_in_the_code()
    assert len(named) > 20, "the search found too few per-seat paths: the patterns are out of date"
    _assert_every_path_accounted_for(named)


def test_a_path_outside_the_search_is_covered_and_still_where_the_label_says(tmp_path):
    named = _per_seat_paths_named_in_the_code()
    store = _store(tmp_path)
    for label in OUTSIDE_THE_SEARCH:
        assert label in COVERED, label
        assert label not in named, f"{label}: the search finds it now, so it no longer needs this exemption"
        folder, pattern = label.split("/")
        path = FILES[COVERED[label]](store)
        assert path.relative_to(store.dir).as_posix() == f"{folder}/{pattern.replace('*', 'alpha')}"


# One planted line (or two) per way of building the path: each names a file no table knows, so the guard must fail.
PLANTED = {
    "f-string, another variable": ('path = store.state_dir / f"{seat}.planted.json"', ".planted.json"),
    "f-string, an attribute": ('path = self.state_dir / f"{args.agent}.planted.json"', ".planted.json"),
    "f-string, a call": ('path = store.state_dir / f"{validate_agent_name(seat)}.planted.json"', ".planted.json"),
    "concatenation, a call": (
        'path = store.state_dir / (validate_agent_name(agent) + ".planted.json")',
        ".planted.json",
    ),
    "concatenation, a variable": ('path = store.state_dir / (seat + ".planted.json")', ".planted.json"),
    "percent": ('path = store.state_dir / ("%s.planted.json" % seat)', ".planted.json"),
    "on the next line, f-string": ('        Path(state_dir)\n        / f"{seat}.planted.json"', ".planted.json"),
    "on the next line, concatenation": (
        '        Path(state_dir)\n        / (validate_agent_name(seat) + ".planted.json")',
        ".planted.json",
    ),
    "folder, f-string": ('path = store.state_dir / "planted" / f"{seat}.json"', "planted/*.json"),
    "folder, f-string with a second part": (
        'path = store.state_dir / "planted" / f"{seat}.{nonce}.json"',
        "planted/*.json",
    ),
    "folder constant, f-string": ('path = store.state_dir / _PLANTED_DIR / f"{seat}.json"', "_PLANTED_DIR/*.json"),
    "folder, concatenation": (
        'path = store.state_dir / "planted" / (validate_agent_name(seat) + ".json")',
        "planted/*.json",
    ),
    "folder, percent": ('path = store.state_dir / "planted" / ("%s.json" % seat)', "planted/*.json"),
    "folder named for the seat": ('path = store.root / "planted" / validate_agent_name(seat)', 'folder "planted"'),
}

# Each spelling is also checked after a quoted folder, a constant folder and
# the one continuation line the census promises to inspect.
for prefix in ("f", "F", "rf", "rF", "Rf", "RF", "fr", "fR", "Fr", "FR"):
    for quote in ("'", '"'):
        expression = f"{prefix}{quote}{{seat}}.planted.json{quote}"
        PLANTED[f"{prefix} {quote} direct"] = (f"p = s.state_dir / {expression}", ".planted.json")

for quote in ("'", '"'):
    forms = {
        "f-string": f"f{quote}{{seat}}.planted.json{quote}",
        "concatenation": f"(seat + {quote}.planted.json{quote})",
        "percent": f"({quote}%s.planted.json{quote} % seat)",
        "format auto": f"{quote}{{}}.planted.json{quote}.format(seat)",
        "format index": f"{quote}{{0}}.planted.json{quote}.format(seat)",
        "format named": f"{quote}{{seat}}.planted.json{quote}.format(seat=seat)",
    }
    for name, expression in forms.items():
        PLANTED[f"{name} {quote} direct"] = (f"p = s.state_dir / {expression}", ".planted.json")
        PLANTED[f"{name} {quote} quoted folder"] = (
            f"p = s.state_dir / {quote}planted{quote} / {expression}",
            "planted/*.planted.json",
        )
        PLANTED[f"{name} {quote} constant folder"] = (
            f"p = s.state_dir / _PLANTED_DIR / {expression}",
            "_PLANTED_DIR/*.planted.json",
        )
        PLANTED[f"{name} {quote} next line"] = (f"p = Path(state_dir)\n / {expression}", ".planted.json")

PLANTED["single-quoted seat folder"] = ("p = root / 'planted' / agent", 'folder "planted"')
PLANTED["mixed folder and filename quotes"] = ("p = s.state_dir / 'planted' / f\"{seat}.json\"", "planted/*.json")
PLANTED["double-quoted f-string with single-quoted key"] = (
    '''p = state_dir / f"{row['agent']}.planted.json"''', ".planted.json"
)
PLANTED["single-quoted f-string with double-quoted key"] = (
    """p = state_dir / f'{row["agent"]}.planted.json'""", ".planted.json"
)
PLANTED["double-quoted format with single-quoted key"] = (
    '''p = state_dir / "{row['agent']}.planted.json".format(row=row)''', ".planted.json"
)
PLANTED["single-quoted format with double-quoted key"] = (
    '''p = state_dir / '{row["agent"]}.planted.json'.format(row=row)''', ".planted.json"
)
PLANTED["format with second field"] = (
    "p = s.state_dir / '{seat}.{nonce}.json'.format(seat=seat, nonce=nonce)",
    ".json",
)
PLANTED["format conversion"] = ("p = s.state_dir / '{0!s}.planted.json'.format(seat)", ".planted.json")
PLANTED["format spec"] = ("p = s.state_dir / '{seat:s}.planted.json'.format(seat=seat)", ".planted.json")
PLANTED["format attribute"] = ("p = s.state_dir / '{a.name}.planted.json'.format(a=a)", ".planted.json")
PLANTED["format index"] = ("p = s.state_dir / '{a[0]}.planted.json'.format(a=a)", ".planted.json")
for prefix in ("r", "R", "u", "U"):
    for name, expression in {
        "concatenation": f"(seat + {prefix}'.planted.json')",
        "percent": f"({prefix}'%s.planted.json' % seat)",
        "format": f"{prefix}'{{}}.planted.json'.format(seat)",
    }.items():
        PLANTED[f"{prefix} string {name}"] = (f"p = s.state_dir / {expression}", ".planted.json")


@pytest.fixture(scope="module")
def census_for_planted_rows():
    return _per_seat_paths_named_in_the_code()


@pytest.mark.parametrize("style", sorted(PLANTED))
def test_the_guard_fails_on_a_new_per_seat_path_in_every_style(style, census_for_planted_rows):
    code, label = PLANTED[style]
    found = _per_seat_paths_in(code.split("\n"))
    assert found == {label}
    with pytest.raises(AssertionError, match=re.escape(repr(label))):
        _assert_every_path_accounted_for(census_for_planted_rows | found)


def test_the_guard_does_not_cross_the_outer_quote_and_reports_one_label_per_line():
    assert _per_seat_paths_in(['p = state_dir / f"{row["agent"]}.planted.json"']) == set()
    assert _per_seat_paths_in(["p = state_dir / f'{row['agent']}.planted.json'"]) == set()
    assert _per_seat_paths_in(['a = state_dir / f"{seat}.first.json"; b = state_dir / f"{seat}.second.json"']) == {
        ".first.json"
    }


def test_every_covered_file_has_a_path_and_a_reader_test():
    tested_kinds = {kind for kind, _read in READERS.values()}
    for label, kind in COVERED.items():
        assert kind in FILES, (label, kind)
        assert kind in tested_kinds, f"{label}: no reader in READERS reads the {kind} file"
