"""`agenttalk session fresh` (#475): a start-fresh REQUEST the wrapper applies itself between turns.

The wrapper loads its session record once and saves its own copy after turns, so the command
only writes a request marker; the wrapper applies it (new Claude session id / cleared Codex
thread), saves, records the outcome and clears the marker. Fakes and throwaway stores only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttalk import cli
from agenttalk import wrapper_runtime as wr
from agenttalk.store import Store
from agenttalk.wrapper import loop, recv_api, run, session

OLD_ID = "11111111-1111-4111-8111-111111111111"


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    s.init(["lead", "beta", "gamma"])
    s.set_operator_facing("lead")
    return s


def _run(root: Path, *argv: str) -> int:
    return cli.main(["--root", str(root), *argv])


def _session_file(s: Store) -> Path:
    return s.state_dir / "beta.wrapper-session.json"


def _claude_state(**kw) -> session.SessionState:
    return session.SessionState(cli="claude", claude_session_id=OLD_ID, turns=5,
                                resume_available=True, **kw)


def _saved(s: Store):
    return lambda st: session.save_session(s, "beta", st)


def _request(s: Store, rid: str = "fr-aaaaaaaaaaaa", reason: str = "conversation too big") -> None:
    assert s.write_fresh_request("beta", {"agent": "beta", "request_id": rid, "reason": reason,
                                          "requested_by": "lead", "at": "2026-10-13T12:00:00Z"})


def _ok_lines() -> list[str]:
    return [json.dumps({"type": "stream_event", "event": {"type": "message_start"}}),
            json.dumps({"type": "stream_event", "event": {"type": "message_stop"}})]


# ------------------------------------------------------------------ the command


def test_the_command_writes_a_request_and_never_touches_the_session_record(tmp_path, capsys) -> None:
    s = _store(tmp_path)
    session.save_session(s, "beta", _claude_state())
    before = _session_file(s).read_bytes()

    assert _run(tmp_path, "session", "fresh", "--for", "beta", "--from", "lead",
                "--reason", "  too   big  ") == 0

    marker = s.read_fresh_request("beta")
    assert marker["agent"] == "beta" and marker["requested_by"] == "lead"
    assert marker["reason"] == "too big" and marker["request_id"].startswith("fr-")
    assert _session_file(s).read_bytes() == before  # a request, not an edit
    assert "applies it between turns" in capsys.readouterr().out


def test_the_command_requires_a_reason_a_roster_agent_and_an_authorised_requester(tmp_path) -> None:
    s = _store(tmp_path)
    with pytest.raises(SystemExit) as no_reason:
        _run(tmp_path, "session", "fresh", "--for", "beta", "--from", "lead")
    assert no_reason.value.code == 2
    assert _run(tmp_path, "session", "fresh", "--for", "beta", "--from", "lead", "--reason", " ") == 2
    assert _run(tmp_path, "session", "fresh", "--for", "ghost", "--from", "lead", "--reason", "x") == 2
    # another worker may not reset beta; beta itself and the operator-facing lead may
    assert _run(tmp_path, "session", "fresh", "--for", "beta", "--from", "gamma", "--reason", "x") == 2
    assert s.read_fresh_request("beta") is None
    assert _run(tmp_path, "session", "fresh", "--for", "beta", "--from", "beta", "--reason", "x") == 0


def test_a_second_request_while_one_is_pending_is_refused_not_duplicated(tmp_path) -> None:
    s = _store(tmp_path)
    assert _run(tmp_path, "session", "fresh", "--for", "beta", "--from", "lead", "--reason", "one") == 0
    first = s.read_fresh_request("beta")

    assert _run(tmp_path, "session", "fresh", "--for", "beta", "--from", "lead", "--reason", "two") == 1

    assert s.read_fresh_request("beta") == first


# ------------------------------------------------------- the wrapper applies it


def test_claude_gets_a_new_session_id_and_never_resumes_the_old_conversation(tmp_path) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    session.save_session(s, "beta", state)
    _request(s)

    outcome = session.apply_fresh_request(s, "beta", state, _saved(s))

    assert outcome["outcome"] == "applied"
    assert state.claude_session_id != OLD_ID
    spec = session.build_turn(state, "hello")
    assert "--resume" not in spec.args and OLD_ID not in spec.args
    assert "--session-id" in spec.args and state.claude_session_id in spec.args
    saved = json.loads(_session_file(s).read_text(encoding="utf-8"))
    assert saved["claude_session_id"] == state.claude_session_id
    assert saved["fresh_request_id"] == "fr-aaaaaaaaaaaa" and saved["fresh_request_outcome"] == "applied"
    assert saved["fresh_request_reason"] == "conversation too big" and saved["fresh_request_turn"] == 5
    assert s.read_fresh_request("beta") is None  # the request is consumed
    backup = s.state_dir / "beta.wrapper-session.before-fresh-fr-aaaaaaaaaaaa.json"
    assert json.loads(backup.read_text(encoding="utf-8"))["claude_session_id"] == OLD_ID


def test_codex_gets_its_thread_cleared_and_starts_a_fresh_exec(tmp_path) -> None:
    s = _store(tmp_path)
    state = session.SessionState(cli="codex", codex_thread_id="thread-old", turns=9, resume_available=True)
    _request(s)

    session.apply_fresh_request(s, "beta", state, _saved(s))

    assert state.codex_thread_id is None
    spec = session.build_turn(state, "hello")
    assert "resume" not in spec.args and "thread-old" not in spec.args


def test_a_request_is_applied_exactly_once_even_when_the_clearing_was_lost(tmp_path) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    _request(s)
    session.apply_fresh_request(s, "beta", state, _saved(s))
    applied_id = state.claude_session_id

    _request(s)  # the same marker survives, as after a crash between "saved" and "cleared"
    assert session.apply_fresh_request(s, "beta", state, _saved(s)) is None

    assert state.claude_session_id == applied_id  # not reset a second time
    assert s.read_fresh_request("beta") is None
    _request(s, rid="fr-bbbbbbbbbbbb")  # a genuinely new request applies again
    assert session.apply_fresh_request(s, "beta", state, _saved(s))["outcome"] == "applied"
    assert state.claude_session_id != applied_id


def test_a_failed_save_keeps_the_request_until_the_reset_is_saved_to_disk(tmp_path) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    session.save_session(s, "beta", state)  # the initial record is on disk
    _request(s)
    failures = {"left": 1}

    def flaky(st) -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise OSError("disk full")
        session.save_session(s, "beta", st)

    run._apply_fresh_request(s, "beta", state, flaky)  # never raises into the wrapper

    assert s.read_fresh_request("beta") is not None  # still pending: nothing durable yet
    assert session.load_session(s, "beta", "claude").claude_session_id == OLD_ID
    reset_id = state.claude_session_id
    run._apply_fresh_request(s, "beta", state, flaky)  # the same-process retry saves it
    assert state.claude_session_id == reset_id  # the retry did not reset a second time
    assert s.read_fresh_request("beta") is None
    reloaded = session.load_session(s, "beta", "claude")
    assert reloaded.claude_session_id == reset_id != OLD_ID  # a restart would not resume the old one
    assert reloaded.fresh_request_id == "fr-aaaaaaaaaaaa"


def test_a_restart_after_a_failed_save_still_finds_the_request(tmp_path) -> None:
    for cli_name, old in (("claude", OLD_ID), ("codex", "thread-old")):
        root = tmp_path / cli_name
        s = _store(root)
        state = (_claude_state() if cli_name == "claude"
                 else session.SessionState(cli="codex", codex_thread_id=old, turns=4))
        session.save_session(s, "beta", state)
        _request(s)

        def broken(_st) -> None:
            raise OSError("disk full")

        run._apply_fresh_request(s, "beta", state, broken)
        restarted = session.load_session(s, "beta", cli_name)  # the old record, as on disk
        assert s.read_fresh_request("beta") is not None
        session.apply_fresh_request(s, "beta", restarted, _saved(s))
        spec = session.build_turn(restarted, "hello")
        assert "--resume" not in spec.args and "resume" not in spec.args and old not in spec.args


def test_no_backup_means_no_reset_and_the_request_stays_pending(tmp_path, monkeypatch) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    session.save_session(s, "beta", state)
    _request(s)

    def no_copy(*_a, **_k):
        raise OSError("read-only folder")

    monkeypatch.setattr(session.shutil, "copyfile", no_copy)
    run._apply_fresh_request(s, "beta", state, _saved(s))

    assert state.claude_session_id == OLD_ID and state.fresh_request_id == ""
    assert s.read_fresh_request("beta") is not None
    assert json.loads(_session_file(s).read_text(encoding="utf-8"))["claude_session_id"] == OLD_ID
    monkeypatch.undo()
    run._apply_fresh_request(s, "beta", state, _saved(s))  # the folder is writable again
    assert state.claude_session_id != OLD_ID and s.read_fresh_request("beta") is None


def test_the_requester_is_kept_in_the_applied_record_and_status(tmp_path) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    _request(s)
    assert s.read_fresh_status("beta")["pending"]["requested_by"] == "lead"

    session.apply_fresh_request(s, "beta", state, _saved(s))

    assert json.loads(_session_file(s).read_text(encoding="utf-8"))["fresh_request_by"] == "lead"
    assert s.read_fresh_status("beta")["applied"]["requested_by"] == "lead"


def test_a_superseded_wrapper_leaves_the_request_for_its_replacement(tmp_path) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    _request(s)
    old = wr.WrapperRuntimeWriter(s.state_dir, "beta", "generation-old", wrapper_pid=1111, wrapper_start="a")
    old.idle()
    assert run.is_active_wrapper(s, "beta", "generation-old")
    new = wr.WrapperRuntimeWriter(s.state_dir, "beta", "generation-new", wrapper_pid=2222, wrapper_start="b")
    new.idle()  # the replacement takes over the runtime record

    old_owner = lambda: run.is_active_wrapper(s, "beta", "generation-old")  # noqa: E731
    run._apply_fresh_request(s, "beta", state, _saved(s), owner_check=old_owner)

    assert s.read_fresh_request("beta") is not None and state.claude_session_id == OLD_ID
    new_owner = lambda: run.is_active_wrapper(s, "beta", "generation-new")  # noqa: E731
    run._apply_fresh_request(s, "beta", state, _saved(s), owner_check=new_owner)
    assert s.read_fresh_request("beta") is None and state.claude_session_id != OLD_ID


def test_no_runtime_record_yet_is_not_the_active_wrapper(tmp_path) -> None:
    assert not run.is_active_wrapper(_store(tmp_path), "beta", "generation-new")


def test_an_unreadable_request_is_removed_and_recorded_without_a_reset(tmp_path) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    (s.state_dir / "beta.fresh-request").write_text("{not json", encoding="utf-8")

    outcome = session.apply_fresh_request(s, "beta", state, _saved(s))

    assert outcome["outcome"] == "unreadable_request_removed"
    assert state.claude_session_id == OLD_ID and state.resume_available
    assert s.read_fresh_request("beta") is None


def test_a_cli_without_support_records_it_and_resets_nothing(tmp_path) -> None:
    s = _store(tmp_path)
    state = session.SessionState(cli="other", turns=3)
    _request(s)

    outcome = session.apply_fresh_request(s, "beta", state, _saved(s))

    assert outcome["outcome"] == "unsupported_cli"
    assert state.resume_available and s.read_fresh_request("beta") is None


# ------------------------------------------------------------ between turns only


def test_a_request_that_arrives_during_a_turn_waits_for_the_turn_to_end(tmp_path) -> None:
    s = _store(tmp_path)
    for body in ("first", "second"):
        s.send(sender="lead", recipient="beta", body=body, kind="message", meta={})
    state = _claude_state()
    calls: list[list[str]] = []

    def spawn(argv, _stdin):
        calls.append(list(argv))
        if len(calls) == 1:  # the request lands while turn one is running
            _request(s)
        return _ok_lines()

    drive = run.make_drive(s, "beta", "claude", state, ["claude"], spawn=spawn,
                           clock=lambda: 0.0, render=False, persist=_saved(s))
    loop.run_loop(s, "beta", drive, clock=lambda: 0.0, sleep=lambda d: None, max_turns=2)

    assert "--resume" in calls[0] and OLD_ID in calls[0]  # turn one ran on the old conversation
    assert "--session-id" in calls[1] and OLD_ID not in calls[1]  # turn two on a fresh one
    assert "--resume" not in calls[1]
    assert state.fresh_request_outcome == "applied" and s.read_fresh_request("beta") is None
    assert recv_api.next_record(s, "beta") is None


def test_an_ordinary_empty_idle_poll_applies_a_request_written_while_idle(tmp_path) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    _request(s)

    loop.run_loop(s, "beta", lambda rec: True, clock=lambda: 0.0, sleep=lambda d: None, max_polls=2,
                  on_idle_poll=lambda: run._apply_fresh_request(s, "beta", state, _saved(s)))

    assert state.claude_session_id != OLD_ID and s.read_fresh_request("beta") is None


# ------------------------------------------------------------------ status


def test_status_shows_pending_then_applied_with_the_reason(tmp_path, capsys) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    session.save_session(s, "beta", state)
    _request(s)

    assert _run(tmp_path, "status", "--json") == 0
    rows = {a["name"]: a for a in json.loads(capsys.readouterr().out)["agents"]}
    assert rows["beta"]["fresh_request"]["pending"]["reason"] == "conversation too big"
    assert "fresh_request" not in rows["gamma"]

    session.apply_fresh_request(s, "beta", state, _saved(s))
    assert _run(tmp_path, "status", "--json") == 0
    rows = {a["name"]: a for a in json.loads(capsys.readouterr().out)["agents"]}
    applied = rows["beta"]["fresh_request"]["applied"]
    assert applied["outcome"] == "applied" and applied["reason"] == "conversation too big"
    assert applied["turns_before"] == 5 and applied["request_id"] == "fr-aaaaaaaaaaaa"
    assert "session_id" not in json.dumps(rows["beta"]["fresh_request"])  # no session identities

    assert _run(tmp_path, "status") == 0
    assert "fresh=applied" in capsys.readouterr().out


def test_the_dashboard_state_shows_a_pending_then_applied_request(tmp_path) -> None:
    from agenttalk import web

    s = _store(tmp_path)
    state = _claude_state()
    session.save_session(s, "beta", state)
    _request(s)

    def beta_entry() -> dict:
        root = web.build_state([web.RootDescriptor(store=s, label="root")])["roots"][0]
        return next(a for a in root["agents"] if a["name"] == "beta")

    assert beta_entry()["fresh_request"] == {"state": "pending", "at": "2026-10-13T12:00:00Z",
                                             "requested_by": "lead"}
    session.apply_fresh_request(s, "beta", state, _saved(s))
    entry = beta_entry()
    assert entry["fresh_request"]["state"] == "applied" and entry["fresh_request"]["requested_by"] == "lead"
    assert "conversation too big" not in json.dumps(entry)  # no free text on the dashboard
    assert OLD_ID not in json.dumps(entry) and state.claude_session_id not in json.dumps(entry)


def test_the_dashboard_projection_knows_the_new_reset_reason(tmp_path) -> None:
    s = _store(tmp_path)
    state = _claude_state()
    _request(s)
    session.apply_fresh_request(s, "beta", state, _saved(s))

    assert s.read_wrapper_runtime("beta")["reset_reason"] == "fresh_requested"
