"""#857: a provider safety refusal gets five tries over about half an hour, then a visible hold. Never a dead letter.

Everything here is made up from the wording the issue quotes and from the shapes the adapter reads: no real provider
output, no live store, no real model. Fake spawners, a fake wall clock and fake sleeps only. The refusal text carries a
marker word so a test can prove it never reaches a summary, the attempt record, a notice, health or the retry prompt.
"""

from __future__ import annotations

import json

import pytest

from agenttalk import attention, cli
from agenttalk.wrapper import codex_adapter, events, loop, run, session
from agenttalk.wrapper import usage_park as park
from test_usage_park_loop import AGENT, T0, Clock, Crash, Seen, Spawner, head, ledger, make_store

MARKER = "SECRETPROMPTECHO"  # stands for anything the provider's text might carry
REFUSAL_TEXT = f"{MARKER} This request was flagged for possible cybersecurity risk."
WAITS = [60, 180, 420, 900]


# ------------------------------------------------------------------------------------------------ made-up events


def failed(code="cyber_policy", *, where="error", message=REFUSAL_TEXT):
    """A terminal turn.failed with a structured reason in the ``error`` object, beside it, or none."""
    err = {"message": message}
    event = {"type": "turn.failed", "error": err}
    if code is not None and where == "error":
        err["codex_error_info"] = code
    elif code is not None:
        event["codex_error_info"] = code
    return [{"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"}, event]


def refused():
    return failed("cyber_policy")


def ok_turn():
    return [
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
        {"type": "turn.completed"},
    ]


def other_failure():
    return failed(None, message="tool execution failed: bad arg")


def lines(events_):
    return [json.dumps(e) for e in events_]


def drive_once(tmp_path, events_, *, cli_name="codex"):
    store = make_store(tmp_path)
    state = (
        session.SessionState(cli="codex")
        if cli_name == "codex"
        else session.SessionState(cli="claude", claude_session_id="sid-1")
    )
    drive = run.make_drive(
        store, AGENT, cli_name, state, [cli_name], spawn=lambda a, i: lines(events_), clock=lambda: 0.0, render=False
    )
    return drive(
        {
            "id": head(store).id,
            "body": "one",
            "from": "alpha",
            "to": AGENT,
            "kind": "message",
            "subject": None,
            "request_id": None,
            "broadcast_id": None,
            "correlation_id": None,
        }
    )


class Recorder(Spawner):
    """A spawner that also keeps everything the model would have been shown."""

    def __init__(self, *steps):
        super().__init__(*steps)
        self.prompts: list[str] = []

    def __call__(self, argv, stdin):
        self.prompts.append(" ".join(str(a) for a in argv) + "\n" + (stdin or ""))
        return super().__call__(argv, stdin)


def go(store, spawner, clock, *, polls, generation="g1", park_on=True, routed=True, seen=None, rejoin=False, **loop_kw):
    seen = seen or Seen()

    def escalate(info):
        seen.notices.append(info)
        seen.events.append(("notice", info.get("failure_class")))
        return routed

    drive = run.make_drive(
        store,
        AGENT,
        "codex",
        session.SessionState(cli="codex"),
        ["codex"],
        spawn=spawner,
        clock=clock.now,
        render=False,
        heartbeat=lambda: seen.events.append("drive-stamp"),
        usage_limit_park=park_on,
        rejoin_for=cli._interruption_rejoin_for(store, AGENT, 3) if rejoin else None,
    )

    def counted(record):
        seen.events.append("drive")
        outcome = drive(record)
        seen.events.append("drive-end")
        return outcome

    def health(rec, reason, reason_detail=None):
        seen.events.append(("health", reason, reason_detail))

    seen.turns = loop.run_loop(
        store,
        AGENT,
        counted,
        clock=clock.now,
        sleep=clock.sleep,
        now_iso=clock.iso,
        max_polls=polls,
        wrapper_generation=generation,
        usage_limit_park=park_on,
        on_escalate=escalate,
        heartbeat=lambda: seen.events.append("stamp"),
        on_health_parked=health,
        on_runtime_idle=lambda: seen.events.append("idle"),
        **loop_kw,
    )
    return seen


def refuse_until_held(tmp_path, *, extra=()):
    """Five refused tries on the saved schedule. Returns (store, spawner, clock, seen, times of the refusals)."""
    store = make_store(tmp_path)
    spawner = Recorder(refused(), *extra)
    clock = Clock(T0)
    seen = Seen()
    times = []
    for _ in range(5):
        go(store, spawner, clock, polls=1, seen=seen, rejoin=True)
        times.append(clock.t)
        rec = ledger(store)
        if rec.get("wake_epoch"):
            clock.t = float(rec["wake_epoch"])
    return store, spawner, clock, seen, times


# ------------------------------------------------------------------------------------- the adapter reads the code


@pytest.mark.parametrize(
    "obj, expected",
    [
        ({"type": "turn.failed", "error": {"message": "m", "codex_error_info": "cyber_policy"}}, "cyber_policy"),
        ({"type": "turn.failed", "error": {"message": "m"}, "codex_error_info": "cyber_policy"}, "cyber_policy"),
        ({"type": "turn.failed", "error": {"message": "m", "codex_error_info": " Cyber_Policy "}}, "cyber_policy"),
        ({"type": "turn.failed", "error": {"message": "m", "codex_error_info": {"cyber_policy": {}}}}, "cyber_policy"),
        ({"type": "turn.failed", "error": {"message": "m", "codex_error_info": "something_new"}}, "something_new"),
        # present but unusable: indeterminate, not absent
        ({"type": "turn.failed", "error": {"message": "m", "codex_error_info": 7}}, ""),
        ({"type": "turn.failed", "error": {"message": "m", "codex_error_info": ""}}, ""),
        ({"type": "turn.failed", "error": {"message": "m", "codex_error_info": {"a": 1, "b": 2}}}, ""),
        ({"type": "turn.failed", "error": {"message": "m", "codex_error_info": None}}, ""),
        ({"type": "turn.failed", "error": {"message": "m", "codex_error_info": ["cyber_policy"]}}, ""),
        # absent
        ({"type": "turn.failed", "error": {"message": "m"}}, None),
        ({"type": "turn.failed", "error": "m"}, None),
        ({"type": "turn.failed"}, None),
    ],
)
def test_the_adapter_reads_the_structured_reason_of_a_terminal_failure(obj, expected):
    (event,) = codex_adapter.map_event(obj)
    assert event.type == events.EventType.ADAPTER_ERROR and event.retryable is False
    assert event.error_code == expected


@pytest.mark.parametrize(
    "obj",
    [
        {"type": "error", "message": "m", "codex_error_info": "cyber_policy"},  # transport, retryable
        {"type": "item.completed", "item": {"type": "error", "message": "m", "codex_error_info": "cyber_policy"}},
    ],
)
def test_a_nonterminal_error_never_carries_a_reason(obj):
    (event,) = codex_adapter.map_event(obj)
    assert event.retryable is True and event.error_code is None


# ------------------------------------------------------------------------------------- how a failure is sorted


@pytest.mark.parametrize(
    "label, events_, expected",
    [
        ("structured, in the error", failed("cyber_policy"), "provider_refusal"),
        ("structured, beside it", failed("cyber_policy", where="beside"), "provider_refusal"),
        ("structured wins over neutral wording", failed("cyber_policy", message="request failed"), "provider_refusal"),
        ("wording only: the incident's phrase", failed(None), "provider_refusal"),
        (
            "wording only: content filter",
            failed(None, message=f"{MARKER} flagged by our content filter"),
            "provider_refusal",
        ),
        (
            "wording only: content policy",
            failed(None, message=f"{MARKER} violates our content policy"),
            "provider_refusal",
        ),
        (
            "an unknown structured word is not proof, wording or not",
            failed("something_new", message=f"{MARKER} flagged by our content filter"),
            "ambiguous_or_unknown",
        ),
        (
            "an unusable structured field is not proof either",
            failed(7, message=f"{MARKER} flagged for possible cybersecurity risk"),
            "ambiguous_or_unknown",
        ),
        (
            "an unknown word never becomes poison",
            failed("something_new", message="request failed"),
            "ambiguous_or_unknown",
        ),
        (
            "a size marker keeps its own handling, whatever the code says",
            failed("something_new", message="context length exceeded"),
            "poison_eligible",
        ),
        ("plain size wording is still poison", failed(None, message="prompt is too long"), "poison_eligible"),
        (
            "an unqualified 'flagged by' is neither",
            failed(None, message="flagged by the gateway: rate limited"),
            "ambiguous_or_unknown",
        ),
        (
            "an unqualified 'violates' is neither",
            failed(None, message="request violates server constraints"),
            "ambiguous_or_unknown",
        ),
        ("unrelated wording", failed(None, message="tool execution failed: bad arg"), "ambiguous_or_unknown"),
    ],
)
def test_how_a_codex_failure_is_sorted(tmp_path, label, events_, expected):
    outcome = drive_once(tmp_path, events_)
    assert outcome.ok is False and outcome.failure_class == expected, label
    assert MARKER not in outcome.summary, label  # the provider's own words are never stored


def test_the_structured_reason_is_read_from_the_terminal_failure_only(tmp_path):
    """The phrase in the model's own output, a tool's output or an inbound message is never a refusal."""
    said = [
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": REFUSAL_TEXT}},
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "echo",
                "aggregated_output": REFUSAL_TEXT,
                "exit_code": 0,
                "status": "completed",
            },
        },
        {"type": "turn.completed"},
    ]
    outcome = drive_once(tmp_path, said)
    assert outcome.ok is True and outcome.failure_class is None


def test_a_refusal_carries_its_own_fact_and_never_a_provider_word(tmp_path):
    outcome = drive_once(tmp_path, failed("cyber_policy"))
    assert outcome.limit_fact == "provider_refusal" and outcome.limit_detail == "provider_safety_refusal"
    assert outcome.summary == "provider safety refusal (cyber_policy)"
    wording = drive_once(tmp_path / "w", failed(None))
    assert wording.summary == "provider safety refusal (wording)"


def test_the_wording_route_changes_for_every_seat_not_only_codex(tmp_path):
    """The sorter is shared: a Claude seat refused with policy wording is a refusal too (it was poison before)."""
    claude = [
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": f"{MARKER} flagged by our content filter",
        }
    ]
    outcome = drive_once(tmp_path, claude, cli_name="claude")
    assert outcome.ok is False and outcome.failure_class == "provider_refusal"
    assert MARKER not in outcome.summary


def test_a_refused_resume_turn_is_not_blamed_on_the_session(tmp_path):
    """A refusal says nothing about whether the session still works: it must not count toward giving up the resume."""
    store = make_store(tmp_path)
    state = session.SessionState(cli="codex")
    state.resume_available = True
    state.thread_id = "t-1"
    drive = run.make_drive(
        store, AGENT, "codex", state, ["codex"], spawn=lambda a, i: lines(refused()), clock=lambda: 0.0, render=False
    )
    record = {
        "id": head(store).id,
        "body": "one",
        "from": "alpha",
        "to": AGENT,
        "kind": "message",
        "subject": None,
        "request_id": None,
        "broadcast_id": None,
        "correlation_id": None,
    }
    for _ in range(3):
        outcome = drive(record)
        assert outcome.failure_class == "provider_refusal" and outcome.limit_fact == "provider_refusal"
    assert state.resume_available is True


# ------------------------------------------------------------------------------- the first refusal waits, quietly


def test_the_first_refusal_waits_a_minute_and_changes_nothing_else(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused())
    clock = Clock(T0)
    seen = go(store, spawner, clock, polls=30)
    rec = ledger(store)
    assert spawner.calls == 1
    assert (rec["park_state"], rec["park_kind"], rec["refusal_total"], rec["wake_epoch"]) == (
        "parked",
        "provider_refusal",
        1,
        T0 + 60,
    )
    assert rec["last_failure_class"] == "provider_refusal" and rec["park_detail"] == "provider_safety_refusal"
    assert rec["last_failure_summary"] == "provider safety refusal (cyber_policy)"
    assert (rec["infra_failures"], rec["ambiguous_failures"], rec["poison_eligible_failures"]) == (0, 0, 0)
    assert rec["excluded_attempts"] == 1 and rec["attempts_started"] == 1
    assert store.dead_lettered_count(AGENT) == 0 and store.cursor(AGENT) == "" and head(store).body == "one"
    assert seen.turns == 0 and not store.usage_limit_park_path(AGENT).exists()
    healths = {e for e in seen.events if isinstance(e, tuple) and e[0] == "health"}
    assert healths == {("health", "provider_wait_parked", "provider_safety_refusal")}


def test_a_seat_that_gets_through_by_itself_sends_no_notice(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused(), refused(), ok_turn())
    clock = Clock(T0)
    seen = Seen()
    message_id = head(store).id
    for _ in range(3):
        go(store, spawner, clock, polls=1, seen=seen)
        rec = store.attempt_record(AGENT, message_id)
        if rec and rec.get("wake_epoch"):
            clock.t = float(rec["wake_epoch"])
    assert spawner.calls == 3 and not seen.notices
    assert store.cursor(AGENT) == message_id and store.attempt_record(AGENT, message_id) is None


def test_a_refusal_followed_by_success_consumes_the_message_and_clears_the_refusal(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused(), ok_turn())
    clock = Clock(T0)
    go(store, spawner, clock, polls=1)
    message_id = head(store).id
    clock.t = float(ledger(store)["wake_epoch"])
    seen = go(store, spawner, clock, polls=1)
    assert seen.turns == 1 and store.cursor(AGENT) == message_id
    assert store.attempt_record(AGENT, message_id) is None and store.dead_lettered_count(AGENT) == 0


# ------------------------------------------------------------------------ five tries, then a hold that is kept


def test_five_tries_on_the_saved_schedule_then_a_hold_with_no_wake_time(tmp_path):
    store, spawner, clock, seen, times = refuse_until_held(tmp_path)
    rec = ledger(store)
    assert spawner.calls == 5 and rec["refusal_total"] == 5
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert [round(g) for g in gaps] == WAITS  # 1, 3, 7 and 15 minutes between the tries
    assert round(times[-1] - times[0]) == sum(WAITS) == 1560  # 26 minutes of waiting: about half an hour
    assert "wake_epoch" not in rec and rec["park_state"] == "parked" and park.is_held(rec)
    assert rec["refusal_first_at"] and rec["refusal_last_at"] and rec["refusal_first_at"] != rec["refusal_last_at"]
    assert store.dead_lettered_count(AGENT) == 0 and store.cursor(AGENT) == "" and head(store).body == "one"
    assert (rec["infra_failures"], rec["ambiguous_failures"], rec["poison_eligible_failures"]) == (0, 0, 0)


def test_the_hold_sends_one_notice_with_counts_and_no_provider_words(tmp_path):
    store, spawner, clock, seen, times = refuse_until_held(tmp_path)
    go(store, spawner, clock, polls=40, seen=seen)  # many more polls: still one notice
    assert len(seen.notices) == 1
    facts = seen.notices[0]["usage_limit"]
    assert (facts["kind"], facts["tries"], facts["budget"], facts["held"]) == ("provider_refusal", 5, 5, True)
    assert facts["next_try_epoch"] is None and facts["notice_key"] == "rev:2"
    assert MARKER not in json.dumps(seen.notices)
    body = cli._usage_limit_notice_body(seen.notices[0])
    assert body.startswith("[provider-refusal-held] ") and MARKER not in body
    assert "NOT lost" in body and "NOT dead-lettered" in body
    assert "agenttalk request-restart --for beta" in body and "agenttalk ack --for beta --id" in body
    for word in ("reword", "rephrase", "bypass", "circumvent", "get past"):
        assert word not in body.lower()


def test_an_unrouted_hold_notice_is_retried_a_bounded_number_of_times_and_never_clears_the_hold(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused())
    clock = Clock(T0)
    seen = Seen()
    for _ in range(5):
        go(store, spawner, clock, polls=1, seen=seen, routed=False)
        rec = ledger(store)
        if rec.get("wake_epoch"):
            clock.t = float(rec["wake_epoch"])
    for _ in range(40):
        clock.t += 1000
        go(store, spawner, clock, polls=1, seen=seen, routed=False)
    rec = ledger(store)
    assert 1 <= len(seen.notices) <= park.NOTICE_MAX_TRIES and rec["notice_routed"] is False
    assert park.is_held(rec) and spawner.calls == 5 and store.dead_lettered_count(AGENT) == 0


def test_a_hold_stays_for_ever_without_a_restart(tmp_path):
    store, spawner, clock, seen, times = refuse_until_held(tmp_path)
    for _ in range(20):
        clock.t += 86400  # a day at a time, the same wrapper
        go(store, spawner, clock, polls=3, seen=seen)
    assert spawner.calls == 5 and park.is_held(ledger(store))
    assert store.dead_lettered_count(AGENT) == 0 and store.cursor(AGENT) == "" and head(store).body == "one"


def test_health_says_held_with_the_closed_cause(tmp_path):
    store, spawner, clock, seen, times = refuse_until_held(tmp_path)
    go(store, spawner, clock, polls=3, seen=seen)
    healths = [e for e in seen.events if isinstance(e, tuple) and e[0] == "health"]
    assert healths[-1] == ("health", "provider_refusal_held", "provider_safety_refusal")
    assert ("health", "provider_wait_parked", "provider_safety_refusal") in healths  # while it still waited


# ----------------------------------------------------------------------------------------------- restarts


def test_a_restart_while_waiting_never_tries_sooner(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused())
    clock = Clock(T0)
    go(store, spawner, clock, polls=1)
    for generation in ("g2", "g3", "g4"):
        go(store, spawner, clock, polls=3, generation=generation)
    rec = ledger(store)
    assert spawner.calls == 1 and rec["refusal_total"] == 1 and rec["wake_epoch"] == T0 + 60


def test_a_restart_at_the_hold_gives_one_try_and_never_a_new_set_of_five(tmp_path):
    store, spawner, clock, seen, times = refuse_until_held(tmp_path)
    for n, generation in enumerate(("g2", "g3", "g4"), start=1):
        go(store, spawner, clock, polls=1, generation=generation, seen=seen)
        rec = ledger(store)
        assert spawner.calls == 5 + n and rec["refusal_total"] == 5 + n and park.is_held(rec)
        go(store, spawner, clock, polls=5, generation=generation, seen=seen)  # the same start: no more tries
        assert spawner.calls == 5 + n
    assert len(seen.notices) == 1 and store.dead_lettered_count(AGENT) == 0


def test_a_restart_after_each_refusal_keeps_the_count(tmp_path):
    """The loop is started again between every two tries: the count carries on and the schedule is not shortened."""
    store = make_store(tmp_path)
    spawner = Recorder(refused())
    clock = Clock(T0)
    for n in range(1, 6):
        go(store, spawner, clock, polls=1, generation=f"g{n}")
        rec = ledger(store)
        assert rec["refusal_total"] == n and spawner.calls == n
        if n < 5:
            assert WAITS[n - 1] - 1 <= rec["wake_epoch"] - clock.t <= WAITS[n - 1], n  # never shortened
            clock.t = float(rec["wake_epoch"])
    assert park.is_held(ledger(store))


def test_a_refusal_then_success_after_a_restart_in_the_hold_ends_it(tmp_path):
    store, spawner, clock, seen, times = refuse_until_held(tmp_path, extra=())
    spawner.steps = [ok_turn()]
    message_id = head(store).id
    seen = go(store, spawner, clock, polls=1, generation="g2")
    assert seen.turns == 1 and store.cursor(AGENT) == message_id and store.attempt_record(AGENT, message_id) is None


def test_a_crash_in_a_try_uses_the_try_and_a_hold_after_it_still_holds(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused(), Crash())
    clock = Clock(T0)
    go(store, spawner, clock, polls=1)
    clock.t = float(ledger(store)["wake_epoch"])
    with pytest.raises(Crash):
        go(store, spawner, clock, polls=1)
    assert spawner.calls == 2
    go(store, spawner, clock, polls=3, generation="g2")  # restarted: the unreported try is counted
    rec = ledger(store)
    assert spawner.calls == 2 and rec["refusal_total"] == 2 and rec["park_state"] == "parked"
    assert rec["wake_epoch"] > clock.t and store.dead_lettered_count(AGENT) == 0 and store.cursor(AGENT) == ""


def test_crashes_cannot_give_unlimited_tries(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused(), Crash())
    clock = Clock(T0)
    go(store, spawner, clock, polls=1)
    for n in range(2, 9):
        clock.t = float(ledger(store)["wake_epoch"]) if ledger(store).get("wake_epoch") else clock.t
        if park.is_held(ledger(store)):
            break
        with pytest.raises(Crash):
            go(store, spawner, clock, polls=1, generation=f"g{n}")
        go(store, spawner, clock, polls=1, generation=f"g{n}")  # the unreported try is counted here
    assert park.is_held(ledger(store)) and park.refusal_total(ledger(store)) == 5
    assert spawner.calls == 5 and store.dead_lettered_count(AGENT) == 0


def test_an_unrelated_failure_between_refusals_never_gives_the_count_back(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused(), other_failure(), refused(), other_failure(), refused())
    clock = Clock(T0)
    go(store, spawner, clock, polls=1)
    assert ledger(store)["refusal_total"] == 1
    clock.t = float(ledger(store)["wake_epoch"])
    go(store, spawner, clock, polls=2)  # the probe ends on an unrelated failure,
    rec = ledger(store)  # the park closes, the next try is refused
    assert spawner.calls == 3 and rec["refusal_total"] == 2
    assert rec["wake_epoch"] - clock.t <= WAITS[1] + 5 and rec["wake_epoch"] - clock.t >= WAITS[1] - 5


def test_a_lower_disposal_ceiling_never_disposes_of_a_refusal_only_history(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused())
    clock = Clock(T0)
    ceilings = {"k_poison": 1, "k_escalate": 2, "noninfra_sub_ceiling": 1, "k_interrupted": 1}
    for n in range(1, 10):
        go(store, spawner, clock, polls=1, generation=f"g{n}", **ceilings)
        rec = ledger(store)
        if rec.get("wake_epoch"):
            clock.t = float(rec["wake_epoch"])
        assert store.dead_lettered_count(AGENT) == 0 and store.cursor(AGENT) == "", n
    assert park.is_held(ledger(store)) and head(store).body == "one"


def test_with_stopping_retries_switched_off_a_refusal_is_driven_as_an_unknown_failure_as_before(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused())
    clock = Clock(T0)
    seen = go(store, spawner, clock, polls=3, park_on=False)
    rec = ledger(store)
    assert spawner.calls == 3 and rec["ambiguous_failures"] == 3 and "park_state" not in rec
    assert rec["last_failure_class"] == "ambiguous_or_unknown" and not seen.notices


# -------------------------------------------------------------------------------- what the next turn is told


def test_a_retry_is_told_the_neutral_sentence_and_never_the_providers_words(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused(), ok_turn())
    clock = Clock(T0)
    go(store, spawner, clock, polls=1, rejoin=True)
    clock.t = float(ledger(store)["wake_epoch"])
    go(store, spawner, clock, polls=1, rejoin=True)
    sentence = (
        "The previous attempt was refused by the provider. Background work from that attempt may have "
        "stopped; check its state before relying on it."
    )
    assert sentence not in spawner.prompts[0] and sentence in spawner.prompts[1]
    assert all(MARKER not in prompt for prompt in spawner.prompts)
    for word in ("reword", "rephrase", "bypass", "circumvent", "safeguard"):
        assert word not in spawner.prompts[1].lower()


def test_the_sentence_survives_a_restart_because_it_is_read_from_the_ledger(tmp_path):
    store = make_store(tmp_path)
    spawner = Recorder(refused(), ok_turn())
    clock = Clock(T0)
    go(store, spawner, clock, polls=1, rejoin=True)
    clock.t = float(ledger(store)["wake_epoch"])
    go(Store_again(tmp_path), spawner, clock, polls=1, rejoin=True, generation="g2")
    assert "The previous attempt was refused by the provider." in spawner.prompts[1]


def Store_again(tmp_path):  # noqa: N802 - a fresh handle
    from agenttalk.store import Store

    return Store(tmp_path)


def test_no_provider_word_is_kept_anywhere_in_the_record(tmp_path):
    store, spawner, clock, seen, times = refuse_until_held(tmp_path)
    assert MARKER not in json.dumps(store.dead_letter_attempts(AGENT))
    assert MARKER not in json.dumps(seen.events, default=str) and MARKER not in json.dumps(seen.notices)


# ---------------------------------------------------------------------------------------------------- readers


def view(**kw):
    base = {
        "present": True,
        "state": "parked",
        "kind": "provider_refusal",
        "message_id": "m1",
        "tries": 2,
        "held": False,
        "next_try_epoch": T0 + 180,
        "park_rev": 1,
        "parked_at": park.epoch_iso(T0),
        "fresh": True,
        "window": None,
        "reset_epoch": None,
        "wake_epoch": None,
    }
    base.update(kw)
    return base


def test_the_status_flags_say_the_try_and_the_hold():
    assert cli._usage_limit_park_flag(view()) == (
        f"provider_refusal_retrying(try=2/5,retry={park.format_epoch(T0 + 180)})"
    )
    assert cli._usage_limit_park_flag(view(state="stale")) == (
        "provider_refusal_retrying(try=2/5,wrapper_not_responding)"
    )
    assert cli._usage_limit_park_flag(view(held=True, tries=5, next_try_epoch=None)) == (
        "provider_refusal_held(tries=5)"
    )


def test_the_park_text_says_the_try_and_the_hold_without_provider_words():
    waiting = park.park_text(view())
    assert waiting.startswith("waiting after the provider refused a turn (try 2 of 5); tries again at ")
    held = park.park_text(view(held=True, tries=5, next_try_epoch=None))
    assert held == (
        "held: the provider refused this message 5 times; it is kept and not retried until the seat is started again"
    )


def test_the_attention_card_for_a_hold_names_both_ways_out_and_no_reword():
    item = attention._usage_limit_park_item(view(held=True, tries=5, next_try_epoch=None, state="parked"))
    text = json.dumps(item).lower()
    assert "refused 5 turns" in text and "agenttalk request-restart --for" in text and "agenttalk ack --for" in text
    assert "not dead-lettered" in text
    for word in ("reword", "rephrase", "bypass", "circumvent"):
        assert word not in text


def test_the_attention_card_for_a_wait_says_it_tries_by_itself():
    item = attention._usage_limit_park_item(view())
    text = json.dumps(item).lower()
    assert "try 2 of 5" in text and "tries again by itself" in text and "request-restart" not in text


def test_the_shared_reader_shows_the_tries_and_the_hold(tmp_path):
    store, spawner, clock, seen, times = refuse_until_held(tmp_path)
    shown = store.usage_limit_park_view(AGENT, now_epoch=clock.t)
    assert shown is not None and shown["kind"] == "provider_refusal"
    assert shown["tries"] == 5 and shown["held"] is True and shown["next_try_epoch"] is None
    assert "held" in park.park_text(shown)


def test_doctor_lists_a_held_message_with_the_way_out(tmp_path):
    from agenttalk import doctor

    store, spawner, clock, seen, times = refuse_until_held(tmp_path)
    store.write_heartbeat(AGENT)
    check = doctor._check_usage_limit_parks(store)
    assert check is not None and check.status == "warn"
    assert "held" in check.details and "request-restart" in check.fix and "ack --for" in check.fix
    assert MARKER not in json.dumps(check.data, default=str)


# ------------------------------------------------------------------------------------------ the scoped path


def scoped_store(tmp_path):
    store = make_store(tmp_path, bodies=())
    store.send(sender="alpha", recipient=AGENT, body="the task", meta={"request_id": "rq-1"})
    return store


def refusal_outcome():
    return loop.DriveOutcome(
        ok=False,
        failure_class="provider_refusal",
        summary="provider safety refusal (x)",
        limit_fact="provider_refusal",
        limit_detail="provider_safety_refusal",
    )


def run_scoped(store, drive, clock, *, generation="s1", **kw):
    return loop.run_loop(
        store,
        AGENT,
        drive,
        clock=clock.now,
        sleep=clock.sleep,
        now_iso=clock.iso,
        only_request_id="rq-1",
        wrapper_generation=generation,
        **kw,
    )


def test_a_scoped_refusal_is_counted_in_the_ledger_and_waits_for_its_saved_time(tmp_path):
    store = scoped_store(tmp_path)
    clock = Clock(T0)
    calls = []

    def drive(record):
        calls.append(record["id"])
        return refusal_outcome()

    turns = run_scoped(store, drive, clock, max_polls=3, max_wall=30.0)
    rec = store.attempt_record(AGENT, calls[0])
    assert turns == 0 and len(calls) == 1  # the 60 s wait does not fit in the 30 s bound
    assert (rec["refusal_total"], rec["park_kind"], rec["wake_epoch"]) == (1, "provider_refusal", T0 + 60)
    assert store.thread_seen(AGENT, "rq-1") in ("", None) and store.dead_lettered_count(AGENT) == 0


def test_a_scoped_run_that_can_wait_waits_then_tries_again(tmp_path):
    store = scoped_store(tmp_path)
    clock = Clock(T0)
    outcomes = [refusal_outcome(), loop.DriveOutcome(ok=True)]
    calls = []

    def drive(record):
        calls.append(clock.t)
        return outcomes.pop(0)

    turns = run_scoped(store, drive, clock, max_polls=10, max_turns=1, max_wall=600.0)
    assert turns == 1 and len(calls) == 2 and calls[1] - calls[0] >= 60
    assert store.attempt_record(AGENT, store.messages_for(AGENT)[0].id) is None  # cleared on success


def test_a_scoped_hold_is_not_forgotten_by_the_next_invocation_and_the_gate_is_never_asked(tmp_path):
    store = scoped_store(tmp_path)
    clock = Clock(T0)
    calls = []

    class Gate:
        def __getattr__(self, name):
            if name == "fence":  # the one thing run_loop reads at the very start
                raise AttributeError(name)
            raise AssertionError(f"the commit gate must not be asked while a refusal is held: {name}")

    def drive(record):
        calls.append(clock.t)
        return refusal_outcome()

    message_id = store.messages_for(AGENT)[0].id
    for n in range(1, 6):  # five invocations, each started after the saved time
        run_scoped(store, drive, clock, generation=f"s{n}", max_polls=2, max_wall=30.0)
        rec = store.attempt_record(AGENT, message_id)
        if rec.get("wake_epoch"):
            clock.t = float(rec["wake_epoch"])
    assert len(calls) == 5 and park.is_held(store.attempt_record(AGENT, message_id))
    for n in range(6, 12):  # six more invocations: nothing is driven, the gate is untouched
        turns = run_scoped(store, drive, clock, generation=f"s{n}", max_polls=2, max_wall=30.0, commit_gate=Gate())
        assert turns == 0
    assert len(calls) == 5 and store.dead_lettered_count(AGENT) == 0
    assert store.thread_seen(AGENT, "rq-1") in ("", None)  # the request is still unseen, not consumed


def test_a_scoped_crash_in_a_try_uses_the_try(tmp_path):
    store = scoped_store(tmp_path)
    clock = Clock(T0)
    message_id = store.messages_for(AGENT)[0].id
    run_scoped(store, lambda record: refusal_outcome(), clock, max_polls=2, max_wall=30.0)
    clock.t = float(store.attempt_record(AGENT, message_id)["wake_epoch"])

    def crash(record):
        raise Crash()

    with pytest.raises(Crash):
        run_scoped(store, crash, clock, generation="s2", max_polls=2, max_wall=30.0)
    run_scoped(store, lambda record: refusal_outcome(), clock, generation="s3", max_polls=2, max_wall=30.0)
    rec = store.attempt_record(AGENT, message_id)
    assert rec["refusal_total"] == 2 and rec["wake_epoch"] > clock.t


def test_a_scoped_retry_gets_the_neutral_sentence_from_the_ledger(tmp_path):
    store = scoped_store(tmp_path)
    rejoin = cli._interruption_rejoin_for(store, AGENT, 3)
    clock = Clock(T0)
    seen = []
    run_scoped(store, lambda record: refusal_outcome(), clock, max_polls=2, max_wall=30.0)
    record = {"id": store.messages_for(AGENT)[0].id}
    seen.append(rejoin(record))
    assert seen[0] is not None and seen[0].startswith("The previous attempt was refused by the provider.")


def test_a_scoped_refusal_is_not_counted_against_the_gates_compliance_bound():
    """The gate's "computed but did not emit" bound is for an agent that failed to reply; a refused turn is the
    provider's, so the scoped loop reports it to the gate as an infrastructure failure, like an outage."""
    import inspect

    source = inspect.getsource(loop._run_one_shot)
    assert "CLASS_INFRA, CLASS_PROVIDER_REFUSAL" in source


def test_the_supervisor_row_carries_the_refusal_kind_with_its_tries_and_only_for_that_kind():
    from agenttalk import supervisor

    row = supervisor._usage_limit_park_row(view(held=True, tries=5, next_try_epoch=None))
    assert (row["kind"], row["tries"], row["held"], row["next_try_epoch"]) == ("provider_refusal", 5, True, None)
    other = supervisor._usage_limit_park_row({"present": True, "state": "parked", "kind": "overloaded"})
    assert other["kind"] == "overloaded" and "tries" not in other and "held" not in other


def test_the_park_view_of_every_other_kind_keeps_exactly_the_keys_it_had():
    plain = park.park_view({"fresh": True, "kind": "throttled", "message_id": "m1"}, None, heartbeat_age=1.0)
    assert "tries" not in plain and "held" not in plain
    shown = park.park_view(
        {"fresh": True, "kind": "provider_refusal", "tries": 3, "held": False, "message_id": "m1"},
        None,
        heartbeat_age=1.0,
    )
    assert shown["kind"] == "provider_refusal" and shown["tries"] == 3 and shown["held"] is False
