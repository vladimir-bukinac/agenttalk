"""Regression checks for Codex park notices and unavailable reset times."""

import pytest

from agenttalk.cli import _dead_letter_notifier
from agenttalk.store import Store
from agenttalk.wrapper import loop
from test_usage_park_loop import Clock, head, make_store

T0 = 1788900000
RESOLVED = {"dead_letter_resolved": "true", "operator_answer": "true", "dead_letter_msg_id": "original-id"}


@pytest.mark.parametrize("kind", ["limit", "recheck", "config"])
def test_resolve_notice_at_head_still_sends_the_park_or_alarm(tmp_path, kind):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    store.operator_facing = lambda: "alpha"
    store.send(sender="alpha", recipient="beta", kind="message", body="resolved", meta=RESOLVED)
    store.send(sender="alpha", recipient="beta", body="work behind")
    notifier = _dead_letter_notifier(store, "beta")
    clock = Clock(T0)
    if kind == "config":
        outcome = loop.DriveOutcome(ok=False, failure_class=loop.CLASS_CONFIG_BLOCKED, summary="configuration error")
    else:
        outcome = loop.DriveOutcome(
            ok=False,
            failure_class=loop.CLASS_INFRA,
            limit_fact="usage_limit",
            limit_provider="codex",
            limit_window="five_hour",
            limit_reset_epoch=T0 + 86400 if kind == "limit" else None,
            limit_detail="recheck" if kind == "recheck" else None,
        )
    loop.run_loop(
        store,
        "beta",
        lambda rec: outcome,
        clock=clock.now,
        sleep=clock.sleep,
        now_iso=clock.iso,
        max_polls=20,
        wrapper_generation="g1",
        usage_limit_park=True,
        on_escalate=lambda info: notifier(info, disposed=False),
        on_dead_letter=lambda info: notifier(info, disposed=True),
    )
    notices = store.messages_for("alpha")
    assert len(notices) == 1
    assert notices[0].subject == ("wrapper config-blocked" if kind == "config" else "usage-limit park notice")
    assert (notices[0].meta.get("needs_operator") == "true") is (kind == "config")
    assert store.cursor("beta") == "" and store.dead_lettered_count("beta") == 0


def test_a_resolve_flag_alone_does_not_suppress_a_dead_letter(tmp_path):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    store.operator_facing = lambda: "alpha"
    store.send(
        sender="alpha",
        recipient="beta",
        kind="message",
        body="not a resolve notice",
        meta={"dead_letter_resolved": "true"},
    )
    notifier = _dead_letter_notifier(store, "beta")
    clock = Clock(T0)
    loop.run_loop(
        store,
        "beta",
        lambda rec: False,
        clock=clock.now,
        sleep=clock.sleep,
        now_iso=clock.iso,
        max_polls=4,
        k_poison=1,
        k_escalate=1,
        on_dead_letter=lambda info: notifier(info, disposed=True),
    )
    assert store.dead_lettered_count("beta") == 1
    assert any(m.meta.get("needs_operator") == "true" for m in store.messages_for("alpha"))


def test_a_real_resolve_notice_does_not_raise_a_new_dead_letter_question(tmp_path):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    store.operator_facing = lambda: "alpha"
    store.send(sender="alpha", recipient="beta", kind="message", body="resolved", meta=RESOLVED)
    notifier = _dead_letter_notifier(store, "beta")
    clock = Clock(T0)
    loop.run_loop(
        store,
        "beta",
        lambda rec: False,
        clock=clock.now,
        sleep=clock.sleep,
        now_iso=clock.iso,
        max_polls=4,
        k_poison=1,
        k_escalate=1,
        on_dead_letter=lambda info: notifier(info, disposed=True),
    )
    assert store.dead_lettered_count("beta") == 1
    assert not [m for m in store.messages_for("alpha") if m.meta.get("needs_operator") == "true"]


@pytest.mark.parametrize(
    "window,reset",
    [
        ("five_hour", None),
        (None, None),
        ("seven_day", None),
        ("five_hour", T0 - 1),
        ("seven_day", T0 + 10 * 86400),
    ],
)
def test_codex_limit_without_a_usable_reset_rechecks_without_new_notices(tmp_path, window, reset):
    store = make_store(tmp_path)
    clock = Clock(T0)
    calls, notices = [], []

    def drive(record):
        calls.append(clock.now())
        return loop.DriveOutcome(
            ok=False,
            failure_class=loop.CLASS_INFRA,
            limit_fact="usage_limit",
            limit_provider="codex",
            limit_window=window,
            limit_reset_epoch=reset,
        )

    loop.run_loop(
        store,
        "beta",
        drive,
        clock=clock.now,
        sleep=clock.sleep,
        now_iso=clock.iso,
        idle_interval=300,
        max_idle_interval=300,
        max_polls=30,
        wrapper_generation="g1",
        usage_limit_park=True,
        on_escalate=lambda info: notices.append(info) or True,
    )
    rec = store.attempt_record("beta", head(store).id)
    assert len(calls) >= 3 and len(notices) == 1
    assert rec["limit_recheck"] is True and rec["attempts_started"] == rec["excluded_attempts"]
    assert not rec["ambiguous_failures"] and not rec["infra_failures"]
    assert store.cursor("beta") == "" and store.dead_lettered_count("beta") == 0


def test_codex_future_reset_becomes_usable_at_the_next_recheck(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(T0)
    calls = []
    reset = T0 + 8 * 86400 + 1

    def drive(record):
        calls.append(clock.now())
        return loop.DriveOutcome(
            ok=False,
            failure_class=loop.CLASS_INFRA,
            limit_fact="usage_limit",
            limit_provider="codex",
            limit_reset_epoch=reset,
        )

    loop.run_loop(
        store,
        "beta",
        drive,
        clock=clock.now,
        sleep=clock.sleep,
        now_iso=clock.iso,
        idle_interval=300,
        max_idle_interval=300,
        max_polls=30,
        wrapper_generation="g1",
        usage_limit_park=True,
    )
    rec = store.attempt_record("beta", head(store).id)
    assert len(calls) == 2
    assert rec["wake_epoch"] == reset + 30
    assert not rec.get("limit_recheck")


def test_claude_limit_without_reset_keeps_restart_only_behavior(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(T0)
    calls = []

    def drive(record):
        calls.append(1)
        return loop.DriveOutcome(
            ok=False,
            failure_class=loop.CLASS_INFRA,
            limit_fact="usage_limit",
            limit_provider="claude",
            limit_window="five_hour",
        )

    loop.run_loop(
        store,
        "beta",
        drive,
        clock=clock.now,
        sleep=clock.sleep,
        now_iso=clock.iso,
        idle_interval=300,
        max_idle_interval=300,
        max_polls=30,
        wrapper_generation="g1",
        usage_limit_park=True,
    )
    assert len(calls) == 1 and store.attempt_record("beta", head(store).id).get("wake_epoch") is None


@pytest.mark.parametrize(
    "partial",
    [
        {"dead_letter_resolved": "true", "operator_answer": "true"},
        {"dead_letter_resolved": "true", "dead_letter_msg_id": "original-id"},
        {"dead_letter_resolved": "true", "operator_answer": "true", "dead_letter_msg_id": ""},
    ],
)
def test_partial_resolve_metadata_does_not_hide_a_dead_letter(tmp_path, partial):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    store.operator_facing = lambda: "alpha"
    store.send(sender="alpha", recipient="beta", kind="message", body="ordinary", meta=partial)
    notifier = _dead_letter_notifier(store, "beta")
    clock = Clock(T0)
    loop.run_loop(
        store,
        "beta",
        lambda rec: False,
        clock=clock.now,
        sleep=clock.sleep,
        now_iso=clock.iso,
        max_polls=4,
        k_poison=1,
        on_dead_letter=lambda info: notifier(info, disposed=True),
    )
    assert any(m.meta.get("needs_operator") == "true" for m in store.messages_for("alpha"))


def test_a_not_yet_disposed_resolve_notice_keeps_its_backstop_alarm(tmp_path):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    store.operator_facing = lambda: "alpha"
    notifier = _dead_letter_notifier(store, "beta")
    assert notifier(
        {
            "agent": "beta",
            "msg_id": "head",
            "from": "alpha",
            "kind": "message",
            "failure_class": loop.CLASS_AMBIGUOUS,
            "dead_letter_resolved": True,
        },
        disposed=False,
    )
    assert any(m.meta.get("needs_operator") == "true" for m in store.messages_for("alpha"))


@pytest.mark.parametrize(
    "limits",
    [
        {"rate_limit_reached_type": "five_hour", "primary": {"window_minutes": 300}},
        {"rate_limit_reached_type": "primary"},
        {"primary": {"used_percent": 100, "window_minutes": 300}},
    ],
)
def test_confirmed_rollout_without_reset_carries_recheck_detail(tmp_path, monkeypatch, limits):
    import json
    from datetime import datetime, timezone

    from agenttalk.wrapper import run, session
    from test_codex_usage_879 import MESSAGE, RECORD

    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    store = Store(tmp_path / "store")
    store.init(["alpha", "beta"])

    def spawn(argv, stdin):
        def events():
            yield json.dumps({"type": "thread.started", "thread_id": "abc"})
            yield json.dumps({"type": "turn.started"})
            folder = home / "sessions"
            folder.mkdir(parents=True, exist_ok=True)
            rec = {"timestamp": datetime.now(timezone.utc).isoformat(), "payload": {"rate_limits": limits}}
            (folder / "rollout-abc.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
            yield json.dumps({"type": "turn.failed", "error": {"message": MESSAGE}})

        class Stream:
            returncode = None
            watchdog_result = None

            def __iter__(self):
                return events()

        return Stream()

    drive = run.make_drive(
        store,
        "beta",
        "codex",
        session.SessionState(cli="codex"),
        ["codex"],
        spawn=spawn,
        clock=lambda: 0.0,
        render=False,
        heartbeat=lambda: None,
        usage_limit_park=True,
    )
    outcome = drive(dict(RECORD))
    assert outcome.limit_fact == "usage_limit" and outcome.limit_detail == "recheck"
