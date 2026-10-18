"""PR #528 fix round 3: nine fixes from the connector's third review and the delta read of df2dc511.

Each test was written first and run red on df2dc511 (see the reply of the fix round); the numbers are the items of
the order. Item 7 and item 8 cover the routine record and the escalation schedule.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from agenttalk import lead_loop_cadence as cad
from agenttalk import lead_relay as relay
from agenttalk import lead_routine as routine
from agenttalk.store import Store


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    s.init(["lead", "lead2", "reviewer", "builder", "other"])
    s.set_role("lead", "lead")
    return s


def _request(s: Store, rid: str, kind: str = "review-request", lead: str = "lead", **meta) -> str:
    return s.send(sender=lead, recipient="reviewer", kind=kind, body="please", meta=dict(meta, request_id=rid)).id


def _result(s: Store, rid: str, lead: str = "lead") -> str:
    return s.send(sender="reviewer", recipient=lead, kind="review-result", body="done",
                  meta={"request_id": rid, "status": "approved"}).id


def _declare(s: Store, seat: str, rid: str, to: str = "lead") -> str:
    return s.send(sender=seat, recipient=to, body="I wait", meta={"waiting_on": rid}).id


def _states(s: Store, lead: str = "lead") -> dict:
    return {(o.seat, o.request_id): o.state for o in relay.derive(s.valid_messages(), lead, retired=s.retired_agents())}


def _broadcast(s: Store, rid: str, members: list[str]) -> None:
    for member in members:
        s.send(sender="lead", recipient=member, kind="question", body="who can?",
               meta={"request_id": rid, "broadcast_id": "B-" + rid, "audience": "all"})


def _answer(s: Store, member: str, rid: str) -> str:
    return s.send(sender=member, recipient="lead", kind="message", body="I can", meta={"request_id": rid}).id


# 1 -------------------------------------------- the publication precheck knows the retired members (P1)
def test_a_broadcast_completed_through_retirement_can_be_forwarded(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _broadcast(s, "Q1", ["reviewer", "other"])
    _declare(s, "builder", "Q1")
    reply = _answer(s, "reviewer", "Q1")
    s.retire_agent("other", reason="gone")
    assert _states(s) == {("builder", "Q1"): relay.OWED}                 # shown as owed ...
    msg, created = relay.publish_handoff(s, "lead", "builder", result_id=reply, body="decision")   # ... and closable
    assert created and msg.meta["relay_of"] == reply
    assert _states(s) == {("builder", "Q1"): relay.CLOSED_FORWARDED}


# 2 ------------------------------------------------------- a redeclared waiter can receive a second closing
def test_a_seat_that_waits_again_gets_a_second_forwarded_closing(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    _declare(s, "builder", "R1")
    first, created = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    assert created
    again, created_again = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    assert not created_again and again.id == first.id                       # a retry inside one generation: one message
    _declare(s, "builder", "R1")                                            # the seat waits again
    assert _states(s) == {("builder", "R1"): relay.OWED}
    second, created_second = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    assert created_second and second.id != first.id                         # the same answer, a new generation
    assert _states(s) == {("builder", "R1"): relay.CLOSED_FORWARDED}
    third, created_third = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    assert not created_third and third.id == second.id


def test_a_different_answer_for_a_new_generation_is_not_a_payload_conflict(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    _declare(s, "builder", "R1")
    relay.publish_handoff(s, "lead", "builder", result_id=result, body="first answer")
    _declare(s, "builder", "R1")
    _, created = relay.publish_handoff(s, "lead", "builder", result_id=result, body="a better answer")
    assert created and _states(s) == {("builder", "R1"): relay.CLOSED_FORWARDED}


def test_a_seat_that_waits_again_gets_a_second_unresolved_note(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _declare(s, "builder", "GONE")
    first, _ = relay.publish_handoff(s, "lead", "builder", request_id="GONE", outcome=relay.OUTCOME_UNRESOLVED)
    _declare(s, "builder", "GONE")
    assert _states(s) == {("builder", "GONE"): relay.UNRESOLVED}
    second, created = relay.publish_handoff(s, "lead", "builder", request_id="GONE", outcome=relay.OUTCOME_UNRESOLVED)
    assert created and second.id != first.id
    assert _states(s) == {("builder", "GONE"): relay.CLOSED_UNRESOLVED}


# 3 -------------------------------------------------- no hand-off starves, however many are open
def _fake_obligations(n: int) -> list[relay.Obligation]:
    return [relay.Obligation("lead", "builder", "R%04d" % i, "M%04d" % i, relay.OWED,
                             "2026-01-01T00:00:%02dZ" % (i % 60), "D%04d" % i) for i in range(n)]


def test_the_snapshot_carries_every_open_hand_off_and_every_one_is_reminded(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = _store(tmp_path)
    total = 600                                           # more than the old 500-entry cap
    monkeypatch.setattr(relay, "obligations_for", lambda store, agent: _fake_obligations(total))
    now = time.time() + 10 * relay.RELAY_DEADLINE_SECONDS + 10 * 365 * 86400
    snap = cad.build_cadence_snapshot(s, "lead", now_epoch=now)
    assert len(snap["relay"]) == total
    cstate = {"relay_reminded": {}}
    seen: set[str] = set()
    for _ in range(total):                                # a fresh snapshot every sweep, as the controller does
        items = [i for i in cad.cadence_actionable(snap, cstate, now_epoch=now, reminder_after_seconds=1800)
                 if i["type"] == "relay_overdue"]
        if not items:
            break
        seen |= {i["request_id"] for i in items}
        cstate = cad.apply_tick_success(cstate, now_epoch=now, reminded_keys=[], escalation_keys=[],
                                        relay_reminded={i["key"]: i["bucket"] for i in items})
    assert len(seen) == total


def test_the_prompt_snapshot_is_bounded_and_says_how_many_are_open() -> None:
    snap = {"agent": "lead", "relay": [{"request_id": "R%d" % i} for i in range(300)], "threads": []}
    shown = cad.snapshot_for_prompt(snap)
    assert len(shown["relay"]) == cad.RELAY_PROMPT_LIMIT and shown["relay_open_total"] == 300
    assert len(snap["relay"]) == 300                       # the full list is not touched


# 4 ----------------------------------------------- the waiting-seat view keeps the owner scope
def test_the_seat_view_ignores_another_leads_cancel(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _declare(s, "builder", "GONE", to="lead")
    s.send(sender="builder", recipient="lead2", body="off", meta={"waiting_off": "GONE"})
    assert _states(s, "lead") == {("builder", "GONE"): relay.UNRESOLVED}
    assert [o.state for o in relay.derive_for_seat(s.valid_messages(), "builder")] == [relay.UNRESOLVED]


def test_the_seat_view_ignores_another_leads_closing(tmp_path: Path) -> None:
    s = _store(tmp_path)
    decl = _declare(s, "builder", "GONE", to="lead")
    note = {"relay_of": "GONE", "relay_outcome": relay.OUTCOME_UNRESOLVED, "relay_decl": decl,
            "relay_nonce": relay.handoff_nonce("lead2", "GONE", "builder", relay.OUTCOME_UNRESOLVED, decl)}
    s.send(sender="lead2", recipient="builder", body="unresolved", meta=note)       # a valid closing of ANOTHER lead
    assert _states(s, "lead") == {("builder", "GONE"): relay.UNRESOLVED}
    states = [(o.lead, o.state) for o in relay.derive_for_seat(s.valid_messages(), "builder")]
    assert states == [("lead", relay.UNRESOLVED)]


# 5 --------------------------------------------- a completed broadcast keeps its result id
def test_a_late_follow_up_does_not_change_a_completed_broadcasts_result(tmp_path: Path) -> None:
    from agenttalk import threads
    s = _store(tmp_path)
    _broadcast(s, "Q1", ["reviewer", "other"])
    _declare(s, "builder", "Q1")
    _answer(s, "reviewer", "Q1")
    completing = _answer(s, "other", "Q1")
    relay.publish_handoff(s, "lead", "builder", result_id=completing, body="decision")
    assert _states(s) == {("builder", "Q1"): relay.CLOSED_FORWARDED}
    _answer(s, "reviewer", "Q1")                          # a follow-up long after the broadcast was complete
    ((_, terminal),) = threads.terminal_responses(s.valid_messages(), "lead").values()
    assert terminal.id == completing
    assert _states(s) == {("builder", "Q1"): relay.CLOSED_FORWARDED}


# 6 ----------------------------------------- an unresolved note is not the closing of a real result
def test_an_unresolved_note_never_closes_a_real_result(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    _declare(s, "builder", "R1")                           # a real obligation: the result id is `result`
    _declare(s, "builder", result)                         # and an unresolved one whose "request id" is that very id
    relay.publish_handoff(s, "lead", "builder", request_id=result, outcome=relay.OUTCOME_UNRESOLVED)
    assert _states(s) == {("builder", "R1"): relay.OWED, ("builder", result): relay.CLOSED_UNRESOLVED}


def test_a_forwarded_closing_never_closes_an_unresolved_declaration(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    _declare(s, "builder", "R1")
    _declare(s, "builder", result)
    relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    assert _states(s) == {("builder", "R1"): relay.CLOSED_FORWARDED, ("builder", result): relay.UNRESOLVED}


# 7 ------------------------------------- the lease check and the routine write are one atomic step
def test_a_replacement_cannot_take_the_lease_between_the_ownership_check_and_the_write(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = _store(tmp_path)
    s.set_managed_lead_loop("lead")
    lease = s.acquire_lead_loop_lease("lead", owner_pid=1, ttl_seconds=600)
    assert lease is not None
    outcome: dict = {}
    real_write = routine._atomic_write_text

    def probing_write(path, text, *a, **k):
        def other_controller() -> None:
            try:
                with s._exclusive_lock(s.state_dir / "lead.lead-loop-lease.lock", timeout=0.4, what="replacement"):
                    outcome["took_the_lease_lock"] = True
            except Exception as exc:  # noqa: BLE001 - the refusal is the expected path
                outcome["refused"] = type(exc).__name__
        t = threading.Thread(target=other_controller)
        t.start()
        t.join(timeout=30)
        return real_write(path, text, *a, **k)

    monkeypatch.setattr(routine, "_atomic_write_text", probing_write)
    assert routine.record_sweep(s, "lead", controller_start=lease["acquired_at"], lease_id=lease["lease_id"],
                                attempted=["threads", "dead_letters", "unrouted_escalations", "relay"], failed=[])
    assert "took_the_lease_lock" not in outcome and "refused" in outcome, outcome


def test_the_controller_check_uses_the_lease_id_it_acquired(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.set_managed_lead_loop("lead")
    lease = s.acquire_lead_loop_lease("lead", owner_pid=1, ttl_seconds=600)
    assert lease is not None
    stale = {"lease_id": "not-the-live-lease", "controller_start": lease["acquired_at"]}
    assert not routine.record_sweep(s, "lead", attempted=["relay"], failed=[], **stale)
    assert not routine.record_path(s, "lead").exists()
    assert routine.record_sweep(s, "lead", controller_start=lease["acquired_at"], lease_id=lease["lease_id"],
                                attempted=["relay"], failed=[])


# 8 ------------------------------------------------------ the operator is told at the third bucket, then daily
def test_operator_escalation_follows_the_documented_schedule() -> None:
    d = relay.RELAY_DEADLINE_SECONDS
    ages = {1: d, 2: 2 * d, 3: 4 * d, 4: 8 * d, 5: 8 * d + 86400, 6: 8 * d + 2 * 86400}
    flags = {}
    for bucket, age in ages.items():
        assert relay.reminder_bucket(age) == bucket
        flags[bucket] = relay.escalates(bucket)
    assert flags == {1: False, 2: False, 3: True, 4: False, 5: True, 6: True}
    snap = {"relay": [{"seat": "builder", "request_id": "R1", "result_id": "M1", "declaration_id": "D1",
                       "state": "owed", "age_seconds": 8 * d + 5}]}
    (item,) = cad.cadence_actionable(snap, {"relay_reminded": {}}, now_epoch=0.0, reminder_after_seconds=1800)
    assert item["bucket"] == 4 and item["escalate"] is False


# 9 ----------------------------------------------------- a request id with a comma cannot open an obligation
def test_a_request_id_with_a_comma_is_refused_where_it_can_open_a_request(tmp_path: Path) -> None:
    s = _store(tmp_path)
    with pytest.raises(ValueError, match="comma"):
        _request(s, "R,1")
    with pytest.raises(ValueError, match="comma"):
        _request(s, "T,2", kind="task")
    assert not [m for m in s.valid_messages() if m.kind in ("review-request", "task")]
    _request(s, "R-1")                                       # ordinary ids are untouched


def test_a_declaration_list_is_still_split_on_commas(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.send(sender="builder", recipient="lead", body="I wait", meta={"waiting_on": "A, B"})
    assert set(_states(s)) == {("builder", "A"), ("builder", "B")}
