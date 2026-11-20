"""#873: a reply already written and saved is sent even when its refusal is held.

A refused turn can leave a saved reply: the reply command was run on the draft, so the gate can send it again by its
own bounded retry without asking the model. In a scoped run, when the refusal came with that saved reply and the hold
was set at once (stopping retries switched off, the first refusal) or by the fifth refusal, the hold used to stop the
run before the saved reply was tried: it waited for the next wrapper start. It now goes out in the same run, with no
further model turn, and the hold stays for everything else.

Made-up events, a real gate, fake spawners and a fake clock only, as in test_provider_refusal.py.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agenttalk.wrapper import usage_park as park
from agenttalk.wrapper.obligations import DetectionCommitGate, LandedResponseResult, Resolution, ResolverState
from test_owed_action_detection import _record_captured_intent
from test_provider_refusal import (
    gate_ledger,
    gate_store,
    only_admission,
    owed_question,
    real_gate,
    refusal_outcome,
    run_gated,
    sent_refusal_outcome,
)
from test_usage_park_loop import AGENT, T0, Clock

BODY = "399"
# The gate's own bound on retrying a saved reply, after the turn that left it (the number the issue measured).
RETRY_BOUND = 15

LOOPS = pytest.mark.parametrize("scoped", [True, False], ids=["scoped", "continuous"])
SETTINGS = pytest.mark.parametrize(
    ("park_on", "capture_on"),
    [(False, 1), (True, 5)],
    ids=["retries-off-first-refusal", "retries-on-fifth-refusal"],
)


def _drive(store, gate, capture_on, calls):
    """Refuses every turn. The ``capture_on``-th turn also leaves a saved reply (the reply command was run on its
    draft); the ones before it leave nothing."""

    def drive(record):
        calls.append(record["owed_action"]["purpose"])
        if len(calls) < capture_on:
            return refusal_outcome()
        draft = Path(record["owed_action"]["draft_path"])
        draft.write_text(BODY, encoding="utf-8")
        digest, admission = next(iter(gate_ledger(gate)["obligations"].items()))
        nonce = next(n for n, row in admission["reservations"].items() if row["state"] == "dispatching")
        _record_captured_intent(store, gate, SimpleNamespace(key_digest=digest, nonce=nonce, draft_path=draft))
        return sent_refusal_outcome()

    return drive


def _replies(store):
    """The replies this seat sent to the asker: what a person waiting for it would see."""
    return [m for m in store.messages_for("alpha") if m.sender == AGENT and m.body == BODY]


def _world(tmp_path):
    store = gate_store(tmp_path)
    inbound = owed_question(store)
    return store, inbound, real_gate(store), Clock(T0)


def _spy_replays(monkeypatch, *, outcome=None):
    """Count the gate's saved-reply retries. With ``outcome`` given the retry is replaced by it (a delivery that
    never lands); otherwise the real retry runs."""
    replays = []
    real = DetectionCommitGate.retry_captured_operation

    def spy(self, permit, record):
        replays.append(1)
        return real(self, permit, record) if outcome is None else outcome

    monkeypatch.setattr(DetectionCommitGate, "retry_captured_operation", spy)
    return replays


# --- the two cases: the saved reply goes out in the same run --------------------------------------------------------


@SETTINGS
def test_a_saved_reply_that_came_with_a_held_refusal_is_delivered_once_in_the_same_run(tmp_path, park_on, capture_on):
    store, inbound, gate, clock = _world(tmp_path)
    calls = []
    turns = run_gated(
        store, gate, _drive(store, gate, capture_on, calls), clock, scoped=True, park_on=park_on, max_turns=1
    )
    assert len(calls) == capture_on, calls  # no model turn beyond the one that was refused
    assert len(_replies(store)) == 1  # delivered, and only once
    assert turns == 1
    assert store.thread_seen(AGENT, "rq-1") == inbound.id  # the request is finished
    status = gate.delivery_status("rq-1", "alpha")
    assert status is None or status.get("state") != "delivery_failed", status


@SETTINGS
def test_a_later_fresh_start_sends_nothing_more_after_the_saved_reply_went_out(
    tmp_path, monkeypatch, park_on, capture_on
):
    store, _inbound, gate, clock = _world(tmp_path)
    calls = []
    run_gated(store, gate, _drive(store, gate, capture_on, calls), clock, scoped=True, park_on=park_on, max_turns=1)
    assert len(_replies(store)) == 1
    monkeypatch.setattr("agenttalk.wrapper.obligations._process_liveness", lambda _pid: "dead")
    replays = _spy_replays(monkeypatch)
    restarted = real_gate(store, "wrapper-2")
    run_gated(
        store,
        restarted,
        _drive(store, restarted, 99, calls),
        clock,
        scoped=True,
        park_on=park_on,
        generation="wrapper-2",
        max_turns=1,
        max_polls=10,
    )
    assert len(_replies(store)) == 1 and replays == []
    assert len(calls) == capture_on


@SETTINGS
def test_a_saved_reply_that_does_not_land_is_retried_by_the_gates_bound_and_the_hold_stays(
    tmp_path, monkeypatch, park_on, capture_on
):
    store, inbound, gate, clock = _world(tmp_path)
    calls, replays = [], _spy_replays(monkeypatch, outcome=False)
    run_gated(store, gate, _drive(store, gate, capture_on, calls), clock, scoped=True, park_on=park_on, max_turns=1)
    assert len(calls) == capture_on  # still no further model turn
    assert len(replays) == RETRY_BOUND  # the gate's own bound, no more and no fewer
    assert _replies(store) == []  # nothing was sent
    assert park.is_held(store.attempt_record(AGENT, inbound.id))  # the refusal's hold is not cleared by the retries


# --- what must stay as it was ---------------------------------------------------------------------------------------


@LOOPS
@SETTINGS
def test_the_gates_bound_on_retrying_a_saved_reply_is_the_same_in_every_combination(
    tmp_path, monkeypatch, scoped, park_on, capture_on
):
    store, _inbound, gate, clock = _world(tmp_path)
    calls, replays = [], _spy_replays(monkeypatch, outcome=False)
    run_gated(store, gate, _drive(store, gate, capture_on, calls), clock, scoped=scoped, park_on=park_on, max_turns=1)
    assert len(replays) == RETRY_BOUND, (len(replays), calls)
    assert len(calls) == capture_on


@LOOPS
@SETTINGS
def test_the_saved_reply_is_delivered_once_in_either_loop_with_either_setting(tmp_path, scoped, park_on, capture_on):
    store, inbound, gate, clock = _world(tmp_path)
    calls = []
    run_gated(store, gate, _drive(store, gate, capture_on, calls), clock, scoped=scoped, park_on=park_on, max_turns=1)
    assert len(_replies(store)) == 1 and len(calls) == capture_on
    assert store.cursor(AGENT) == inbound.id or store.thread_seen(AGENT, "rq-1") == inbound.id


@SETTINGS
def test_a_held_refusal_with_no_saved_reply_still_stops_without_asking_the_gate_anything(
    tmp_path, monkeypatch, park_on, capture_on
):
    store, inbound, gate, clock = _world(tmp_path)
    calls, replays = [], _spy_replays(monkeypatch)
    asked = []
    for name in ("admit_or_finalize", "reserve_dispatch", "resolve"):
        real = getattr(DetectionCommitGate, name)

        def spy(self, *args, _real=real, _name=name, **kwargs):
            asked.append(_name)
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(DetectionCommitGate, name, spy)

    def drive(record):
        calls.append(1)
        return refusal_outcome()  # a plain refusal: nothing was saved

    run_gated(store, gate, drive, clock, scoped=True, park_on=park_on, max_turns=1, max_polls=60)
    assert park.is_held(store.attempt_record(AGENT, inbound.id))
    before = (len(calls), len(asked))
    run_gated(store, gate, drive, clock, scoped=True, park_on=park_on, max_turns=1, max_polls=20)
    assert (len(calls), len(asked)) == before  # the second run is held for good: no turn, the gate is not asked
    assert replays == [] and _replies(store) == []
    assert only_admission(gate)["state"] == "open"


@SETTINGS
def test_a_held_refusal_whose_saved_reply_is_not_there_when_looked_for_stops_without_asking_the_gate_more(
    tmp_path, monkeypatch, park_on, capture_on
):
    """The run is only let on when the read-only look finds the saved reply. When it finds none, nothing else of the
    gate is asked: the run stops held, as for any hold."""
    store, inbound, gate, clock = _world(tmp_path)
    calls, asked, asked_at_the_look = [], [], []
    real_admit = DetectionCommitGate.admit_or_finalize

    def admit(self, record):
        asked.append(1)
        return real_admit(self, record)

    def nothing_saved(self, record):
        asked_at_the_look.append(len(asked))
        return None

    monkeypatch.setattr(DetectionCommitGate, "admit_or_finalize", admit)
    monkeypatch.setattr(DetectionCommitGate, "captured_operation_for", nothing_saved)
    run_gated(
        store,
        gate,
        _drive(store, gate, capture_on, calls),
        clock,
        scoped=True,
        park_on=park_on,
        max_turns=1,
        max_polls=60,
    )
    assert len(calls) == capture_on and asked_at_the_look
    assert len(asked) == asked_at_the_look[-1]  # not asked again after the look found nothing
    assert _replies(store) == [] and park.is_held(store.attempt_record(AGENT, inbound.id))


# --- the two stops: a run let past a hold only to send a saved reply never starts a model turn ---------------------


@SETTINGS
def test_the_run_stops_held_when_the_saved_reply_is_gone_by_the_time_the_gate_is_asked(
    tmp_path, monkeypatch, park_on, capture_on
):
    """Stop 2. The first look finds the saved reply (that is what lets the run past the hold); the gate's own look
    finds none, so the only next step is a model turn: the run must stop held instead."""
    store, inbound, gate, clock = _world(tmp_path)
    calls = []
    real_captured, real_purpose = DetectionCommitGate.captured_operation, DetectionCommitGate.next_dispatch_purpose
    refused = lambda: len(calls) >= capture_on  # noqa: E731 - once the turn that left the saved reply is over
    monkeypatch.setattr(
        DetectionCommitGate, "captured_operation", lambda self, key: None if refused() else real_captured(self, key)
    )
    # and the gate would hand out a model turn if asked (it does so when no reply is saved and one is still owed)
    monkeypatch.setattr(
        DetectionCommitGate,
        "next_dispatch_purpose",
        lambda self, key: "recovery" if refused() else real_purpose(self, key),
    )
    run_gated(
        store,
        gate,
        _drive(store, gate, capture_on, calls),
        clock,
        scoped=True,
        park_on=park_on,
        max_turns=1,
        max_polls=60,
    )
    assert len(calls) == capture_on  # no model turn after the held one
    assert _replies(store) == []
    assert park.is_held(store.attempt_record(AGENT, inbound.id))


@SETTINGS
def test_the_run_stops_held_when_the_gate_says_nothing_is_owed_any_more(tmp_path, monkeypatch, park_on, capture_on):
    """Stop 1. The gate answers that the legacy path may go on (nothing is owed) once the refused turn is over: the
    only next step is a model turn, which a hold does not allow."""
    store, inbound, gate, clock = _world(tmp_path)
    calls = []
    real = DetectionCommitGate.admit_or_finalize

    def admit(self, record):
        if len(calls) >= capture_on:
            return Resolution(ResolverState.NOT_OWED, "forced for the test")
        return real(self, record)

    monkeypatch.setattr(DetectionCommitGate, "admit_or_finalize", admit)
    # and the legacy path would go on to a model turn if it were let (nothing landed, nothing refuses it)
    monkeypatch.setattr(DetectionCommitGate, "resolve_landed_response", lambda self, record: LandedResponseResult())
    monkeypatch.setattr(
        DetectionCommitGate, "authorize_no_admission_drive", lambda self, record, resolution: resolution
    )
    run_gated(
        store,
        gate,
        _drive(store, gate, capture_on, calls),
        clock,
        scoped=True,
        park_on=park_on,
        max_turns=1,
        max_polls=60,
    )
    assert len(calls) == capture_on  # no model turn after the held one
    assert park.is_held(store.attempt_record(AGENT, inbound.id))
