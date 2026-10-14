"""#488: `agenttalk release` stands a PARKED agent down between turns.

The real wrapper loop on throwaway stores. A wrapper reads only its oldest unread message and a held head (a
config_blocked park, a gateway hold) is not consumed, so a release queued behind it was never read. Now the loop notices
a valid release behind a held head, records it as honoured, and leaves between turns: it starts no turn after that,
and the held head is neither consumed nor reordered. The release stays unread (one cursor) until the head is
resolved; a later wrapper that reaches it consumes it without standing down again.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttalk import cli
from agenttalk.store import Store
from agenttalk.wrapper import loop, recv_api, run, session


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    s.init(["lead", "beta"])
    s.set_operator_facing("lead")
    return s


def _send(s: Store, body: str = "work"):
    return s.send(sender="lead", recipient="beta", body=body, kind="message", meta={})


def _release(tmp_path: Path) -> str:
    rc = cli.main(["--root", str(tmp_path), "release", "--from", "lead", "--to", "beta", "--relay-human",
                   "-m", "gateway window"])
    assert rc == 0
    rel = [m for m in Store(tmp_path).messages_for("beta") if m.kind == "release"]
    return rel[-1].id


def _blocked() -> loop.DriveOutcome:
    return loop.DriveOutcome(ok=False, failure_class=loop.CLASS_CONFIG_BLOCKED, summary="gateway is held")


def _run(s: Store, drive, *, generation: str = "gen-a", max_polls: int = 6, **kw) -> int:
    return loop.run_loop(s, "beta", drive, clock=lambda: 0.0, sleep=lambda d: None, max_polls=max_polls,
                         k_poison=0, k_escalate=50, wrapper_generation=generation, **kw)


class _Drive:
    """A drive that records every call and answers with a scripted outcome."""

    def __init__(self, outcome=None) -> None:
        self.calls: list[str] = []
        self.outcome = outcome

    def __call__(self, rec):
        self.calls.append(rec["id"])
        return self.outcome() if callable(self.outcome) else self.outcome


def _park(s: Store, tmp_path: Path):
    """Run a wrapper until the head is parked (config_blocked), return the head message."""
    head = _send(s)
    d = _Drive(_blocked)
    _run(s, d, max_polls=3)
    assert d.calls  # the head was driven and is now held
    assert s.attempt_record("beta", head.id)["last_failure_class"] == loop.CLASS_CONFIG_BLOCKED
    return head


# ------------------------------------------------------- a release behind a parked head


def test_a_release_behind_a_parked_head_stands_the_agent_down_without_a_turn(tmp_path) -> None:
    s = _store(tmp_path)
    head = _park(s, tmp_path)
    rel = _release(tmp_path)

    d = _Drive(_blocked)
    returned_early = _run(s, d, max_polls=50)

    assert d.calls == []                                   # no turn after the stand-down was accepted
    assert recv_api.next_record(s, "beta")["id"] == head.id  # the held head is still first, unread
    assert s.cursor("beta") in ("", None)                   # nothing was consumed
    assert s.stand_down_honoured("beta", rel)               # recorded before the loop returned
    assert returned_early == 0


def test_it_returns_at_once_not_after_the_poll_budget(tmp_path) -> None:
    s = _store(tmp_path)
    _park(s, tmp_path)
    _release(tmp_path)
    polls = {"n": 0}

    def count_poll() -> None:
        polls["n"] += 1

    _run(s, _Drive(_blocked), max_polls=500, on_idle_poll=count_poll)

    assert polls["n"] <= 2   # one look, then out; a loop that never reads the release would run all 500


# ------------------------------------------------------- a new wrapper generation


def test_a_new_generation_stands_down_before_it_re_probes_the_parked_head(tmp_path) -> None:
    s = _store(tmp_path)
    head = _park(s, tmp_path)                 # generation A parked it
    rel = _release(tmp_path)

    d = _Drive(lambda: pytest.fail("a turn was started after the release was waiting"))
    _run(s, d, generation="gen-b", max_polls=50)   # generation B would normally re-probe the head once

    assert d.calls == []
    assert recv_api.next_record(s, "beta")["id"] == head.id
    assert s.stand_down_honoured("beta", rel)


def test_a_wrapper_started_after_the_stand_down_runs_and_is_not_stood_down_again(tmp_path) -> None:
    s = _store(tmp_path)
    head = _park(s, tmp_path)
    rel = _release(tmp_path)
    _run(s, _Drive(_blocked), max_polls=50)         # stands down, honoured
    assert s.stand_down_honoured("beta", rel)

    # the operator starts the agent again and the head is resolved (the drive now succeeds)
    later = _send(s, "after")
    s.clear_attempt("beta", head.id)                # whatever resolved the block
    d = _Drive(True)
    _run(s, d, generation="gen-c", max_polls=12)

    assert d.calls[0] == head.id and later.id in d.calls    # it ran the head, then the later message
    assert s.cursor("beta") >= later.id                      # and consumed the release on the way, silently
    assert s.read_stand_down_status("beta") is None          # nothing is pending any more


# ------------------------------------------------------- arrival order


def test_a_release_that_arrives_first_is_the_head_and_stands_down_as_before(tmp_path) -> None:
    s = _store(tmp_path)
    rel = _release(tmp_path)
    _send(s)
    d = _Drive(True)

    _run(s, d, max_polls=20)

    assert d.calls == []                       # work behind the release is never started
    assert s.cursor("beta") == rel               # the release itself was consumed (the idle path, unchanged)
    assert not s.stand_down_honoured("beta", rel)


def test_head_and_release_both_waiting_before_the_loop_starts(tmp_path) -> None:
    s = _store(tmp_path)
    head = _send(s)
    rel = _release(tmp_path)
    d = _Drive(_blocked)

    _run(s, d, max_polls=50)

    assert d.calls == [head.id]                  # the head had its one attempt, was parked, then the loop left
    assert s.stand_down_honoured("beta", rel)
    assert recv_api.next_record(s, "beta")["id"] == head.id


# ------------------------------------------------------- what is NOT honoured


def test_an_unauthorised_release_behind_a_parked_head_does_nothing(tmp_path) -> None:
    s = Store(tmp_path)
    s.init(["lead", "beta", "mallory"])
    s.set_operator_facing("lead")
    _park(s, tmp_path)
    s.send(sender="mallory", recipient="beta", body="go away", kind="release", meta={})
    d = _Drive(_blocked)

    _run(s, d, max_polls=8)

    assert s.read_stand_down_status("beta") is None
    assert not s._read_stand_down("beta")


def test_a_release_without_the_operator_marker_is_not_honoured(tmp_path) -> None:
    s = _store(tmp_path)
    _park(s, tmp_path)
    s.send(sender="lead", recipient="beta", body="done for now", kind="release", meta={})   # unmarked
    polls = {"n": 0}
    _run(s, _Drive(_blocked), max_polls=8, on_idle_poll=lambda: polls.__setitem__("n", polls["n"] + 1))
    assert polls["n"] == 8 and not s._read_stand_down("beta")


def test_a_held_head_without_a_release_stays_held(tmp_path) -> None:
    s = _store(tmp_path)
    head = _park(s, tmp_path)
    polls = {"n": 0}
    _run(s, _Drive(_blocked), max_polls=7, on_idle_poll=lambda: polls.__setitem__("n", polls["n"] + 1))
    assert polls["n"] == 7                                  # nothing else about parking changed
    assert recv_api.next_record(s, "beta")["id"] == head.id


def test_an_unwritable_honoured_record_keeps_the_agent_running(tmp_path, monkeypatch) -> None:
    s = _store(tmp_path)
    _park(s, tmp_path)
    _release(tmp_path)
    monkeypatch.setattr(Store, "record_stand_down_honoured", lambda *a, **k: False)
    polls = {"n": 0}
    _run(s, _Drive(_blocked), max_polls=6, on_idle_poll=lambda: polls.__setitem__("n", polls["n"] + 1))
    assert polls["n"] == 6                                  # fail closed: no unrecorded stand-down


# ------------------------------------------------------- the other holds


def test_a_gateway_hold_that_is_re_driven_every_poll_stands_down_too(tmp_path) -> None:
    s = _store(tmp_path)
    head = _send(s)
    held = _Drive(lambda: loop.DriveOutcome(ok=False, failure_class=loop.CLASS_GATEWAY_HELD,
                                            summary="gateway held (ledger_not_ready)"))
    _run(s, held, max_polls=3)
    assert len(held.calls) >= 1                            # re-driven each poll while held
    rel = _release(tmp_path)
    before = len(held.calls)

    _run(s, held, max_polls=50, generation="gen-a")

    assert len(held.calls) <= before + 1                    # at most the one re-drive of the new run's first poll
    assert s.stand_down_honoured("beta", rel)
    assert recv_api.next_record(s, "beta")["id"] == head.id


# ------------------------------------------------------- both real drives (Claude and Codex)


@pytest.mark.parametrize("cli_name", ["claude", "codex"])
def test_both_drives_stand_down_a_parked_agent_without_spawning(tmp_path, cli_name) -> None:
    s = _store(tmp_path)
    head = _send(s)
    spawns: list = []

    def denied(argv, _stdin):
        spawns.append(list(argv))
        raise PermissionError(13, "Access is denied")

    state = session.SessionState(cli=cli_name, claude_session_id="sess-1" if cli_name == "claude" else None)
    drive = run.make_drive(s, "beta", cli_name, state, [cli_name], spawn=denied, clock=lambda: 0.0, render=False)
    _run(s, drive, max_polls=3)
    assert spawns                                         # one real attempt, now parked (config_blocked)
    assert s.attempt_record("beta", head.id)["last_failure_class"] == loop.CLASS_CONFIG_BLOCKED
    rel = _release(tmp_path)
    before = len(spawns)

    _run(s, drive, generation="gen-new", max_polls=50)    # a new generation would re-probe the head once

    assert len(spawns) == before                           # no child process was started
    assert s.stand_down_honoured("beta", rel)
    assert recv_api.next_record(s, "beta")["id"] == head.id


# ------------------------------------------------------- how it shows


def test_status_shows_the_stand_down_until_the_release_is_consumed(tmp_path, capsys) -> None:
    s = _store(tmp_path)
    _park(s, tmp_path)
    rel = _release(tmp_path)
    _run(s, _Drive(_blocked), max_polls=50)
    capsys.readouterr()                                    # the release command printed its own lines

    assert cli.main(["--root", str(tmp_path), "status", "--json"]) == 0
    row = next(a for a in json.loads(capsys.readouterr().out)["agents"] if a["name"] == "beta")
    assert row["stand_down"]["release_id"] == rel

    assert cli.main(["--root", str(tmp_path), "status"]) == 0
    assert "stand_down=honoured" in capsys.readouterr().out


def test_a_wrapper_started_while_the_head_is_still_parked_is_not_stood_down_by_the_honoured_release(tmp_path) -> None:
    s = _store(tmp_path)
    _park(s, tmp_path)
    _release(tmp_path)
    _run(s, _Drive(_blocked), max_polls=50)             # stands down once, the release is honoured
    polls = {"n": 0}

    _run(s, _Drive(_blocked), generation="gen-d", max_polls=9,
         on_idle_poll=lambda: polls.__setitem__("n", polls["n"] + 1))

    assert polls["n"] == 9                              # still parked and running: the spent release is not read again
