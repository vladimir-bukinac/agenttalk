"""Compaction and the owed hand-off: protection of what an obligation depends on, the explicit ``unresolved``
outcome for a declaration that arrives after its request was archived, and a race between a declaration and a
compaction.

Design: docs/DESIGN-lead-loop-default.md, section 5 (late declarations, compaction), cases 12 and 12d of section 11.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agenttalk import cli
from agenttalk import lead_relay as relay
from agenttalk.store import Store


def _later() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


def _compact(s: Store, keep_count: int = 2):
    return cli._run_compaction(s, s.load_config(), keep_count=keep_count, keep_age_days=0.0, dry_run=False,
                               now=_later())


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    s.init(["lead", "reviewer", "builder"])
    return s


def _finished_request(s: Store, rid: str = "R1") -> str:
    s.send(sender="lead", recipient="reviewer", kind="review-request", body="please", meta={"request_id": rid})
    return s.send(sender="reviewer", recipient="lead", kind="review-result", body="GO",
                  meta={"request_id": rid, "status": "approved"}).id


def _old_fillers(s: Store, n: int = 4) -> list[str]:
    return [s.send(sender="lead", recipient="reviewer", body="old filler %d" % i).id for i in range(n)]


def _fillers_and_cursors(s: Store, n: int = 4) -> None:
    last = ""
    for i in range(n):
        last = s.send(sender="lead", recipient="reviewer", body="filler %d" % i).id
    for agent in ("lead", "reviewer", "builder"):
        s.set_cursor(agent, last)      # everybody has read everything: only the protection can keep a message


def _live_ids(s: Store) -> set[str]:
    return {m.id for m in s.valid_messages()}


def _states(s: Store) -> dict:
    return {(o.seat, o.request_id): o.state for o in relay.derive(s.valid_messages(), "lead")}


def test_a_declaration_then_compaction_keeps_what_the_obligation_depends_on(tmp_path: Path) -> None:
    s = _store(tmp_path)
    old = _old_fillers(s)
    result = _finished_request(s)
    decl = s.send(sender="builder", recipient="lead", body="I wait", meta={"waiting_on": "R1"}).id
    _fillers_and_cursors(s)
    res = _compact(s)
    assert {r["id"] for r in res["archived"]} == set(old), "only the messages before the protected group may go"
    live = _live_ids(s)
    assert result in live and decl in live
    assert _states(s) == {("builder", "R1"): relay.OWED}
    assert res["components"]["relay"] is not None


def test_without_a_declaration_the_request_is_archived_and_a_later_declaration_is_unresolved(tmp_path: Path) -> None:
    s = _store(tmp_path)
    result = _finished_request(s)
    _fillers_and_cursors(s)
    _compact(s)
    assert result not in _live_ids(s)                                  # the closed request left live history
    s.send(sender="builder", recipient="lead", body="I wait for R1", meta={"waiting_on": "R1"})
    assert _states(s) == {("builder", "R1"): relay.UNRESOLVED}         # never silent: explicit outcome
    seat_view = relay.derive_for_seat(s.valid_messages(), "builder")
    assert [(o.request_id, o.state) for o in seat_view] == [("R1", relay.UNRESOLVED)]
    note, created = relay.publish_handoff(s, "lead", "builder", request_id="R1", outcome=relay.OUTCOME_UNRESOLVED)
    again, created2 = relay.publish_handoff(s, "lead", "builder", request_id="R1", outcome=relay.OUTCOME_UNRESOLVED)
    assert created and not created2 and note.id == again.id
    assert [(o.request_id, o.state) for o in relay.derive_for_seat(s.valid_messages(), "builder")] == \
        [("R1", relay.CLOSED_UNRESOLVED)]


def test_an_unresolved_declaration_is_itself_protected_until_it_is_closed(tmp_path: Path) -> None:
    s = _store(tmp_path)
    old = _old_fillers(s)
    decl = s.send(sender="builder", recipient="lead", body="I wait", meta={"waiting_on": "GONE"}).id
    _fillers_and_cursors(s)
    res = _compact(s)
    assert {r["id"] for r in res["archived"]} == set(old) and decl in _live_ids(s)
    relay.publish_handoff(s, "lead", "builder", request_id="GONE", outcome=relay.OUTCOME_UNRESOLVED)
    _fillers_and_cursors(s)
    _compact(s, keep_count=1)
    assert decl not in _live_ids(s)                                    # closed: no longer protected


def test_a_closed_obligation_no_longer_protects_its_request(tmp_path: Path) -> None:
    s = _store(tmp_path)
    result = _finished_request(s)
    s.send(sender="builder", recipient="lead", body="I wait", meta={"waiting_on": "R1"})
    relay.publish_handoff(s, "lead", "builder", result_id=result, body="merge")
    _fillers_and_cursors(s)
    _compact(s, keep_count=1)
    assert result not in _live_ids(s)


@pytest.mark.parametrize("round_", range(12))
def test_a_declaration_racing_a_compaction_ends_owed_or_unresolved_never_absent(tmp_path: Path, round_: int) -> None:
    s = _store(tmp_path)
    _finished_request(s)
    _fillers_and_cursors(s, n=30)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def declare() -> None:
        try:
            barrier.wait(timeout=20)
            s.send(sender="builder", recipient="lead", body="I wait", meta={"waiting_on": "R1"})
        except BaseException as exc:  # noqa: BLE001 - reported by the assertion below
            errors.append(exc)

    def compact() -> None:
        try:
            barrier.wait(timeout=20)
            _compact(s, keep_count=1)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=declare), threading.Thread(target=compact)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    states = _states(s)
    assert ("builder", "R1") in states, "the declaration vanished from the derivation"
    assert states[("builder", "R1")] in (relay.OWED, relay.UNRESOLVED)


def test_a_dry_run_moves_nothing_and_takes_no_lock(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _finished_request(s)
    _fillers_and_cursors(s)
    before = _live_ids(s)
    res = cli._run_compaction(s, s.load_config(), keep_count=1, keep_age_days=0.0, dry_run=True,
                              now=_later())
    assert res["archived"] and _live_ids(s) == before
