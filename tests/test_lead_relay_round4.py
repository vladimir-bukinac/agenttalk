"""PR #528 fix round 4: the closing generation race (P1) and the broadcast result under a later retirement (P2).

Written first and run red on dc9fb080 (see the reply of the fix round).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agenttalk import lead_relay as relay
from agenttalk import threads
from agenttalk.store import Store


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    s.init(["lead", "lead2", "reviewer", "builder", "other"])
    s.set_role("lead", "lead")
    return s


def _request(s: Store, rid: str, **meta) -> str:
    return s.send(sender="lead", recipient="reviewer", kind="review-request", body="please",
                  meta=dict(meta, request_id=rid)).id


def _result(s: Store, rid: str) -> str:
    return s.send(sender="reviewer", recipient="lead", kind="review-result", body="done",
                  meta={"request_id": rid, "status": "approved"}).id


def _declare(s: Store, seat: str, rid: str) -> str:
    return s.send(sender=seat, recipient="lead", body="I wait", meta={"waiting_on": rid}).id


def _states(s: Store) -> dict:
    derived = relay.derive(s.valid_messages(), "lead", retired=s.retired_agents())
    return {(o.seat, o.request_id): o.state for o in derived}


def _closing_for(s: Store, result: str, generation: str, body: str = "decision") -> str:
    """A valid closing message for the given declaration generation, sent now (so its id is the newest)."""
    meta = {"relay_of": result, "relay_nonce": relay.handoff_nonce("lead", result, "builder", relay.OUTCOME_FORWARDED,
                                                                   generation),
            "relay_decl": generation}
    return s.send(sender="lead", recipient="builder", body=body, meta=meta).id


# 1 -------------------------------------------------------------------- a closing answers only its own declaration
def test_a_stale_closing_published_after_a_newer_declaration_does_not_close_it(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    d1 = _declare(s, "builder", "R1")
    d2 = _declare(s, "builder", "R1")                          # the seat declares again ...
    _closing_for(s, result, d1)                                # ... and a delayed closing for D1 lands afterwards
    assert _states(s) == {("builder", "R1"): relay.OWED}       # D2 is still owed, whatever the message order says
    assert [(o.state, o.declaration_id) for o in relay.derive_for_seat(s.valid_messages(), "builder")] == [
        (relay.OWED, d2)]
    _closing_for(s, result, d2)
    assert _states(s) == {("builder", "R1"): relay.CLOSED_FORWARDED}


def test_a_closing_made_for_the_current_declaration_still_closes_it(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    d1 = _declare(s, "builder", "R1")
    _closing_for(s, result, d1)
    assert _states(s) == {("builder", "R1"): relay.CLOSED_FORWARDED}


def test_a_declaration_inserted_after_the_generation_read_is_not_closed_and_a_retry_closes_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    d1 = _declare(s, "builder", "R1")
    real_send = Store.send
    inserted: dict = {}

    def send_with_a_declaration_first(self, **kwargs):
        # the interleaving: the seat declares again between the generation read and the closing's append
        if (kwargs.get("meta") or {}).get("relay_of") == result and "d2" not in inserted:
            inserted["d2"] = real_send(self, sender="builder", recipient="lead", body="I wait again",
                                       meta={"waiting_on": "R1"}).id
        return real_send(self, **kwargs)

    monkeypatch.setattr(Store, "send", send_with_a_declaration_first)
    first, created = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    monkeypatch.setattr(Store, "send", real_send)
    assert created and inserted["d2"] > d1
    state = _states(s)
    assert state[("builder", "R1")] in (relay.OWED, relay.CLOSED_FORWARDED)
    if first.meta.get("relay_decl") != inserted["d2"]:
        assert state == {("builder", "R1"): relay.OWED}        # a closing for D1 never closes D2
    again, created_again = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    final = _states(s)
    assert final == {("builder", "R1"): relay.CLOSED_FORWARDED}
    assert again.meta["relay_decl"] == inserted["d2"]          # the closing that closed D2 is for D2
    again2, created_again2 = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    assert not created_again2 and again2.id == again.id        # and an exact retry is the same message


def test_the_generation_is_read_again_inside_the_publication_lock(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    _declare(s, "builder", "R1")
    real = relay._declaration_generation
    calls = {"n": 0}

    def reading_then_declaring(store, lead, seat, outcome, target):
        value = real(store, lead, seat, outcome, target)
        calls["n"] += 1
        if calls["n"] == 1:                                    # a declaration lands right after the first read
            store.send(sender="builder", recipient="lead", body="again", meta={"waiting_on": "R1"})
        return value

    monkeypatch.setattr(relay, "_declaration_generation", reading_then_declaring)
    msg, created = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    latest = max((m for m in s.valid_messages() if (m.meta or {}).get("waiting_on") == "R1"), key=lambda m: m.id)
    assert created and msg.meta["relay_decl"] == latest.id     # the published generation is the one current at send
    assert calls["n"] >= 2                                     # it was read again under the lock
    assert _states(s) == {("builder", "R1"): relay.CLOSED_FORWARDED}


# 2 ------------------------------------------------ a later retirement does not rewrite a completed broadcast's result
def _broadcast(s: Store, rid: str, members: list[str]) -> None:
    for member in members:
        s.send(sender="lead", recipient=member, kind="question", body="who can?",
               meta={"request_id": rid, "broadcast_id": "B-" + rid, "audience": "all"})


def _answer(s: Store, member: str, rid: str) -> str:
    return s.send(sender=member, recipient="lead", kind="message", body="I can", meta={"request_id": rid}).id


def test_retiring_the_completing_responder_keeps_the_result_and_the_closed_state(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _broadcast(s, "Q1", ["reviewer", "other"])
    _declare(s, "builder", "Q1")
    _answer(s, "reviewer", "Q1")
    completing = _answer(s, "other", "Q1")                     # B completes the broadcast
    relay.publish_handoff(s, "lead", "builder", result_id=completing, body="decision")
    assert _states(s) == {("builder", "Q1"): relay.CLOSED_FORWARDED}
    s.retire_agent("other", reason="gone")                     # B retires afterwards
    ((_, terminal),) = threads.terminal_responses(s.valid_messages(), "lead", retired=set(s.retired_agents())).values()
    assert terminal.id == completing
    assert _states(s) == {("builder", "Q1"): relay.CLOSED_FORWARDED}


def test_a_member_who_never_replied_and_retired_still_lets_the_others_complete(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _broadcast(s, "Q1", ["reviewer", "other"])
    _declare(s, "builder", "Q1")
    first = _answer(s, "reviewer", "Q1")
    s.retire_agent("other", reason="gone")
    ((_, terminal),) = threads.terminal_responses(s.valid_messages(), "lead", retired=set(s.retired_agents())).values()
    assert terminal.id == first                                # retirement stands in for the silent member only
    assert _states(s) == {("builder", "Q1"): relay.OWED}


def test_a_late_follow_up_still_does_not_change_the_result(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _broadcast(s, "Q1", ["reviewer", "other"])
    _answer(s, "reviewer", "Q1")
    completing = _answer(s, "other", "Q1")
    _answer(s, "reviewer", "Q1")
    ((_, terminal),) = threads.terminal_responses(s.valid_messages(), "lead").values()
    assert terminal.id == completing
