"""PR #528 fix round 5: the closing/declaration rule, structural, and proven over every ordering.

The rule (design, "Fix round 5"):
  1. a closing this code generates names the declaration it answers (``relay_decl``; ``none`` means "no declaration"
     and never closes anything); a closing without the field is not a closing;
  2. the closing index keeps the generation in its key: a stale closing neither closes nor hides a current one;
  3. a cancellation wins over any closing;
  4. publication needs an open obligation for exactly that target and seat.

Part A: the review cases as named examples. Part B: a model test over every event sequence against a short
reference model written separately from the code under test.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from agenttalk import lead_relay as relay
from agenttalk.store import Message, Store


NO_DECL = getattr(relay, "NO_DECLARATION", "none")


# ------------------------------------------------------------------------------------------ part A: named cases
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


def _cancel(s: Store, seat: str, rid: str) -> str:
    return s.send(sender=seat, recipient="lead", body="off", meta={"waiting_off": rid}).id


def _states(s: Store) -> dict:
    derived = relay.derive(s.valid_messages(), "lead", retired=s.retired_agents())
    return {(o.seat, o.request_id): o.state for o in derived}


def _closing(s: Store, result: str, generation: str, seat: str = "builder") -> str:
    meta = {"relay_of": result, "relay_decl": generation, "relay_request": "R1",
            "relay_nonce": relay.handoff_nonce("lead", result, seat, relay.OUTCOME_FORWARDED, generation)}
    return s.send(sender="lead", recipient=seat, body="decision", meta=meta).id


def test_a_closing_made_before_the_first_declaration_never_closes_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """developer-4 P1: the command read "no declaration", the seat's first declaration landed before the append."""
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    _closing(s, result, NO_DECL)
    d1 = _declare(s, "builder", "R1")
    assert _states(s) == {("builder", "R1"): relay.OWED}
    assert [(o.state, o.declaration_id) for o in relay.derive_for_seat(s.valid_messages(), "builder")] == [
        (relay.OWED, d1)]


def test_a_field_less_closing_closes_nothing(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    _declare(s, "builder", "R1")
    legacy = {"relay_of": result, "relay_nonce": relay.handoff_nonce("lead", result, "builder",
                                                                      relay.OUTCOME_FORWARDED, "")}
    s.send(sender="lead", recipient="builder", body="old style", meta=legacy)
    assert _states(s) == {("builder", "R1"): relay.OWED}


@pytest.mark.parametrize("stale_first", [True, False])
def test_a_stale_closing_neither_closes_nor_hides_the_current_one(tmp_path: Path, stale_first: bool) -> None:
    """developer-4 P2: both arrival orders, live history."""
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    d1 = _declare(s, "builder", "R1")
    d2 = _declare(s, "builder", "R1")
    order = [d1, d2] if stale_first else [d2, d1]
    for generation in order:
        _closing(s, result, generation)
    assert _states(s) == {("builder", "R1"): relay.CLOSED_FORWARDED}
    assert [o.state for o in relay.derive_for_seat(s.valid_messages(), "builder")] == [relay.CLOSED_FORWARDED]


@pytest.mark.parametrize("stale_first", [True, False])
def test_a_stale_closing_does_not_hide_the_current_one_in_retained_history(tmp_path: Path, stale_first: bool) -> None:
    s = _store(tmp_path)
    opener = _request(s, "R1")
    result = _result(s, "R1")
    d1 = _declare(s, "builder", "R1")
    d2 = _declare(s, "builder", "R1")
    for generation in ([d1, d2] if stale_first else [d2, d1]):
        _closing(s, result, generation)
    s.archive_messages_below(d1)                               # the request and the result leave live history
    assert opener not in {m.id for m in s.valid_messages()}
    assert _states(s) == {("builder", "R1"): relay.CLOSED_FORWARDED}
    assert [o.state for o in relay.derive_for_seat(s.valid_messages(), "builder")] == [relay.CLOSED_FORWARDED]


def test_a_cancellation_wins_over_a_closing(tmp_path: Path) -> None:
    """Reviewer P2-1: the seat cancelled after its declaration; a closing that names it changes nothing."""
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    d1 = _declare(s, "builder", "R1")
    _cancel(s, "builder", "R1")
    _closing(s, result, d1)
    assert _states(s) == {("builder", "R1"): relay.CANCELLED}


def test_publication_is_refused_for_a_cancelled_declaration(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    _declare(s, "builder", "R1")
    _cancel(s, "builder", "R1")
    with pytest.raises(relay.RelayRefused, match="no open hand-off"):
        relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    assert not [m for m in s.valid_messages() if (m.meta or {}).get("relay_of")]


def test_publication_to_a_seat_that_never_declared_is_refused(tmp_path: Path) -> None:
    """Reviewer P2-3: a mistyped --to naming another roster member."""
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    _declare(s, "builder", "R1")
    with pytest.raises(relay.RelayRefused, match="no open hand-off"):
        relay.publish_handoff(s, "lead", "other", result_id=result, body="decision")
    assert _states(s) == {("builder", "R1"): relay.OWED}


def test_an_unresolved_note_without_a_declaration_is_refused(tmp_path: Path) -> None:
    s = _store(tmp_path)
    with pytest.raises(relay.RelayRefused, match="no open hand-off"):
        relay.publish_handoff(s, "lead", "builder", request_id="GONE", outcome=relay.OUTCOME_UNRESOLVED)


def test_every_published_closing_names_its_declaration(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    d1 = _declare(s, "builder", "R1")
    msg, _ = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    assert msg.meta["relay_decl"] == d1 and msg.meta["relay_request"] == "R1"
    d2 = _declare(s, "other", "GONE")
    note, _ = relay.publish_handoff(s, "lead", "other", request_id="GONE", outcome=relay.OUTCOME_UNRESOLVED)
    assert note.meta["relay_decl"] == d2


def test_the_first_declaration_race_through_the_real_command_never_loses_the_obligation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rule 4 plus rule 1: no declaration at read time means the command is refused, not closed-by-order."""
    s = _store(tmp_path)
    _request(s, "R1")
    result = _result(s, "R1")
    with pytest.raises(relay.RelayRefused):
        relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    _declare(s, "builder", "R1")
    assert _states(s) == {("builder", "R1"): relay.OWED}


def test_a_former_leads_open_hand_offs_stay_inspectable_after_the_role_moves(
        tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reviewer P2-2, bounded: no automatic reminder after the move, but the explicit status shows and closes them."""
    from agenttalk import cli
    s = _store(tmp_path)
    monkeypatch.setenv("AGENTTALK_ROOT", str(tmp_path))
    monkeypatch.delenv("AGENTTALK_SELF", raising=False)
    _request(s, "R1")
    _declare(s, "builder", "R1")
    s.set_role("lead2", "lead")                                 # the lead role moves from "lead" to "lead2"
    result = _result(s, "R1")
    assert relay.notice_for(s, "lead") == ""                    # the automatic notice follows the role (the bound)
    assert cli.main(["lead-routine", "status", "--for", "lead"]) == 0
    assert result in capsys.readouterr().out                    # but the explicit status still shows it
    msg, created = relay.publish_handoff(s, "lead", "builder", result_id=result, body="decision")
    assert created and _states(s) == {("builder", "R1"): relay.CLOSED_FORWARDED}


# ------------------------------------------------------------------------ part B: the model test over all orderings
EVENTS = ("D", "X", "R", "A", "U", "H", "E", "T", "C")
# D declare   X cancel   R the relay command reads the generation   A the command appends its closing (the generation
# it read)   U the same for an unresolved note   H a field-less hand-written closing   E an ordinary reply that
# mentions the result   T the seat retires   C compaction (the request and the result leave live history)
SEQUENCE_LENGTH = 6


def _msg(n: int, sender: str, recipient: str, kind: str = "message", body: str = "x", **meta) -> Message:
    ts = "2026-10-18T%02d:%02d:%02dZ" % (n // 3600, n // 60 % 60, n % 60)
    return Message(id="20261018-000000-%06d-AAAA" % n, ts=ts, sender=sender, recipient=recipient, kind=kind,
                   subject="", body=body, meta=dict(meta))


def _run_real(events: tuple[str, ...]) -> tuple[list[Message], set[str]]:
    """The messages the events produce, built the way the code builds them (no store: pure data)."""
    opener = _msg(1, "lead", "reviewer", "review-request", request_id="R1")
    result = _msg(2, "reviewer", "lead", "review-result", request_id="R1", status="approved")
    msgs = [opener, result]
    retired: set[str] = set()
    remembered = NO_DECL
    latest = None
    n = 3
    for ev in events:
        n += 1
        if ev == "D":
            m = _msg(n, "builder", "lead", waiting_on="R1")
            latest = m.id
        elif ev == "X":
            m = _msg(n, "builder", "lead", waiting_off="R1")
        elif ev == "R":
            remembered = latest or NO_DECL
            continue
        elif ev == "A":
            m = _msg(n, "lead", "builder", relay_of=result.id, relay_decl=remembered, relay_request="R1",
                     relay_nonce=relay.handoff_nonce("lead", result.id, "builder", relay.OUTCOME_FORWARDED, remembered))
        elif ev == "U":
            m = _msg(n, "lead", "builder", relay_of="R1", relay_outcome=relay.OUTCOME_UNRESOLVED,
                     relay_decl=remembered,
                     relay_nonce=relay.handoff_nonce("lead", "R1", "builder", relay.OUTCOME_UNRESOLVED, remembered))
        elif ev == "H":
            m = _msg(n, "lead", "builder", relay_of=result.id,
                     relay_nonce=relay.handoff_nonce("lead", result.id, "builder", relay.OUTCOME_FORWARDED, ""))
        elif ev == "E":
            m = _msg(n, "lead", "builder", relay_of=result.id)
        elif ev == "T":
            retired.add("builder")
            continue
        else:                                                      # "C"
            msgs = [x for x in msgs if x.id not in (opener.id, result.id)]
            continue
        msgs.append(m)
    return msgs, retired


def _reference(events: tuple[str, ...]) -> str:
    """The rule, in a few lines, independent of the code under test: "none", "open", "closed", "cancelled" or
    "retired"."""
    latest = None            # the current declaration (the n-th D)
    cancelled = False        # a cancel after the current declaration
    remembered = "none"
    closings: set[tuple[str, str]] = set()      # (kind, generation) of every closing that carries a generation
    compacted = retired = False
    count = 0
    for ev in events:
        if ev == "D":
            count += 1
            latest, cancelled = "D%d" % count, False
        elif ev == "X":
            cancelled = True
        elif ev == "R":
            remembered = latest or "none"
        elif ev == "A":
            closings.add(("result", remembered))
        elif ev == "U":
            closings.add(("request", remembered))
        elif ev == "T":
            retired = True
        elif ev == "C":
            compacted = True
        # H and E: a closing without the field and an ordinary reply: never anything
    if latest is None:
        return "none"
    if cancelled:
        return "cancelled"
    # live: only a forwarded closing names the result; after compaction the forwarded one is found through the
    # request it names, and an unresolved note answers the request itself
    kinds = {"result", "request"} if compacted else {"result"}
    if any((kind, latest) in closings for kind in kinds):
        return "closed"
    return "retired" if retired else "open"


_STATE_NAME = {relay.OWED: "open", relay.UNRESOLVED: "open", relay.CLOSED_FORWARDED: "closed",
               relay.CLOSED_NOT_NEEDED: "closed", relay.CLOSED_UNRESOLVED: "closed",
               relay.CANCELLED: "cancelled", relay.CLOSED_RECIPIENT_RETIRED: "retired"}


def _view(obligations: list[relay.Obligation]) -> str:
    mine = [o for o in obligations if o.seat == "builder" and o.request_id == "R1"]
    assert len(mine) <= 1
    return _STATE_NAME[mine[0].state] if mine else "none"


def test_the_lead_view_and_the_seat_view_agree_with_the_reference_over_every_sequence() -> None:
    ran = 0
    disagreements: list[str] = []
    for length in range(1, SEQUENCE_LENGTH + 1):
        for events in itertools.product(EVENTS, repeat=length):
            msgs, retired = _run_real(events)
            expected = _reference(events)
            lead_view = _view(relay.derive(msgs, "lead", retired=retired))
            seat_view = _view(relay.derive_for_seat(msgs, "builder", retired=retired))
            ran += 1
            if not (lead_view == seat_view == expected):
                disagreements.append("%s: reference=%s lead=%s seat=%s" % ("".join(events), expected, lead_view,
                                                                           seat_view))
                if len(disagreements) >= 15:
                    break
        if len(disagreements) >= 15:
            break
    assert not disagreements, "\n".join(disagreements)
    assert ran == sum(len(EVENTS) ** n for n in range(1, SEQUENCE_LENGTH + 1))
    print("model test: %d sequences of up to %d events over %d event kinds, all agree" % (
        ran, SEQUENCE_LENGTH, len(EVENTS)))
