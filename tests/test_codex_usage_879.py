"""Codex's terminal allowance failure parks only with the seat's own evidence."""
import json
from datetime import datetime, timezone, timedelta

import pytest

from agenttalk.store import Store
from agenttalk.wrapper import loop, run, session

MESSAGE = ("You’ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits "
           "or try again at Nov 22nd, 2026 1:23 PM.")
RECORD = {"id": "20260909-030000-000001-Aaaa", "kind": "message", "from": "alpha", "to": "beta",
          "subject": "", "body": "work"}


class Stream(list):
    returncode = None
    watchdog_result = None


@pytest.mark.parametrize("reading", ["exhausted", "missing", "stale", "below"])
def test_codex_limit_terminal_uses_current_session_reading(tmp_path, monkeypatch, reading):
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    store = Store(tmp_path / "store")
    store.init(["alpha", "beta"])
    reset = int(datetime.now(timezone.utc).timestamp()) + 3600

    def spawn(argv, stdin):
        def events():
            yield json.dumps({"type": "thread.started", "thread_id": "abc"})
            yield json.dumps({"type": "warning", "message": "config warning one"})
            yield json.dumps({"type": "warning", "message": "config warning two"})
            yield json.dumps({"type": "turn.started"})
            if reading != "missing":
                folder = home / "sessions"
                folder.mkdir(parents=True, exist_ok=True)
                observed = datetime.now(timezone.utc) - timedelta(seconds=700 if reading == "stale" else 0)
                payload = {"rate_limits": {"primary": {"used_percent": 99 if reading == "below" else 100,
                                                           "window_minutes": 300, "resets_at": reset}}}
                (folder / "rollout-2026-abc.jsonl").write_text(
                    json.dumps({"timestamp": observed.isoformat(), "payload": payload}) + "\n", encoding="utf-8")
            yield json.dumps({"type": "error", "message": MESSAGE})
            yield json.dumps({"type": "turn.failed", "error": {"message": MESSAGE}})
        class EventStream:
            returncode = None
            watchdog_result = None
            def __iter__(self):
                return events()
        return EventStream()

    drive = run.make_drive(store, "beta", "codex", session.SessionState(cli="codex"), ["codex"],
                           spawn=spawn, clock=lambda: 0.0, render=False, heartbeat=lambda: None,
                           usage_limit_park=True)
    outcome = drive(dict(RECORD))
    if reading == "below":
        assert outcome.failure_class == loop.CLASS_AMBIGUOUS and outcome.limit_fact is None
    else:
        assert outcome.failure_class == loop.CLASS_INFRA
        assert outcome.limit_fact == "usage_limit" and outcome.limit_provider == "codex"
        assert outcome.limit_reset_epoch == (reset if reading == "exhausted" else None)


def test_recheck_probes_keep_the_head_and_send_one_notice(tmp_path):
    from test_usage_park_loop import Clock, make_store, head
    store = make_store(tmp_path, bodies=("task",))
    store.send(sender="alpha", recipient="beta", body="notice", meta={"dead_letter_resolved": "true"})
    clock = Clock(1788900000)
    notices = []
    calls = []

    def drive(record):
        calls.append(record["id"])
        return loop.DriveOutcome(ok=False, failure_class=loop.CLASS_INFRA, limit_fact="usage_limit",
                                 limit_provider="codex", limit_detail="recheck")

    loop.run_loop(store, "beta", drive, clock=clock.now, sleep=clock.sleep, now_iso=clock.iso,
                  idle_interval=300, max_idle_interval=300, max_polls=30, wrapper_generation="g1",
                  usage_limit_park=True, on_escalate=lambda info: notices.append(info) or True)
    record = store.attempt_record("beta", head(store).id)
    assert len(calls) >= 3 and len(set(calls)) == 1
    assert len(notices) == 1
    assert record["park_state"] == "parked" and record["limit_provider"] == "codex"
    assert record["attempts_started"] == record["excluded_attempts"]
    assert record["ambiguous_failures"] == record["infra_failures"] == 0
    assert store.dead_lettered_count("beta") == 0 and store.cursor("beta") == ""
    assert store.read_usage_limit_park("beta", now_epoch=clock.now())["provider"] == "codex"


def test_codex_park_notice_names_provider_and_recheck():
    from agenttalk.cli import _usage_limit_notice_body
    notice = _usage_limit_notice_body({"agent": "beta", "msg_id": "id", "from": "alpha", "usage_limit": {
        "provider": "codex", "recheck": True, "wake_epoch": 1788901800}})
    assert "Codex" in notice and "30 minutes" in notice
    assert "Claude" not in notice


def test_a_resolved_notice_does_not_raise_an_operator_question(tmp_path):
    from agenttalk.cli import _dead_letter_notifier
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    store.operator_facing = lambda: "alpha"
    notify = _dead_letter_notifier(store, "beta")
    notify({"agent": "beta", "msg_id": "id", "failure_class": "ambiguous_or_unknown",
            "dead_letter_resolved": True}, disposed=True)
    assert store.messages_for("alpha") == []


@pytest.mark.parametrize("observed,started,now,expected", [
    (1000.125, 1000.126, 1001.0, "recheck"),
    (1000.125, 1000.125, 1001.0, "recheck"),
    (1000.126, 1000.125, 1001.0, "confirmed"),
    (1000.0, 999.0, 1600.0, "confirmed"),
    (1000.0, 999.0, 1600.001, "recheck"),
    (1000.0, 999.0, 999.999, "recheck"),
])
def test_rollout_time_must_be_after_start_and_at_most_600_seconds_old(
        tmp_path, monkeypatch, observed, started, now, expected):
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    folder = home / "sessions"
    folder.mkdir(parents=True)
    stamp = datetime.fromtimestamp(observed, timezone.utc).isoformat()
    limits = {"primary": {"used_percent": 100, "window_minutes": 300, "resets_at": 2000}}
    (folder / "rollout-abc.jsonl").write_text(
        json.dumps({"timestamp": stamp, "payload": {"rate_limits": limits}}) + "\n", encoding="utf-8")
    fact = run._codex_usage_limit("beta", "abc", started, now=now)
    assert fact is not None
    assert ("recheck" if fact.get("recheck") else "confirmed") == expected


@pytest.mark.parametrize("limits,window,reset", [
    ({"primary": {"used_percent": 100, "window_minutes": 300, "resets_at": 2200},
      "secondary": {"used_percent": 100, "window_minutes": 10080, "resets_at": 2800}}, "seven_day", 2800),
    ({"rate_limit_reached_type": "seven_day", "secondary": {"window_minutes": 10080, "resets_at": 2800}},
     "seven_day", 2800),
    ({"rate_limit_reached_type": "five_hour"}, "five_hour", None),
    ({"primary": {"used_percent": 100, "window_minutes": 300, "resets_at": 2200},
      "secondary": {"used_percent": 100, "window_minutes": 10080}}, "seven_day", None),
])
def test_exhausted_rollout_selects_its_latest_reset(tmp_path, monkeypatch, limits, window, reset):
    folder = tmp_path / "sessions"
    folder.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    stamp = datetime.fromtimestamp(1000.25, timezone.utc).isoformat()
    (folder / "rollout-abc.jsonl").write_text(
        json.dumps({"timestamp": stamp, "payload": {"rate_limits": limits}}) + "\n", encoding="utf-8")
    fact = run._codex_usage_limit("beta", "abc", 1000.0, now=1001.0)
    assert (fact["window"], fact["reset_epoch"], fact.get("recheck")) == (window, reset, None)


def test_resolved_notice_at_head_is_parked_without_escalation(tmp_path):
    from test_usage_park_loop import Clock
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    message = store.send(sender="alpha", recipient="beta", body="resolved", meta={"dead_letter_resolved": "true"})
    clock = Clock(1788900000)
    notices = []
    def drive(record):
        return loop.DriveOutcome(ok=False, failure_class=loop.CLASS_INFRA, limit_fact="usage_limit",
                                 limit_provider="codex", limit_detail="recheck")
    loop.run_loop(store, "beta", drive, clock=clock.now, sleep=clock.sleep, now_iso=clock.iso,
                  max_polls=10, wrapper_generation="g1", usage_limit_park=True,
                  on_dead_letter=lambda info: notices.append(info))
    assert store.cursor("beta") == "" and store.dead_lettered_count("beta") == 0
    assert store.attempt_record("beta", message.id)["park_state"] == "parked" and not notices


def test_codex_unknown_park_status_shows_recheck_time():
    from agenttalk.cli import _usage_limit_park_flag
    view = {"present": True, "state": "parked", "provider": "codex", "reset_epoch": None,
            "wake_epoch": 1788901800}
    assert "retry=" in _usage_limit_park_flag(view)


def test_recheck_survives_crash_without_rearming_notice():
    from agenttalk.wrapper import usage_park
    rec = {"park_state": "probing", "probe_marker": True, "limit_provider": "codex",
           "limit_recheck": True, "notice_key": "park:1", "notice_routed": True,
           "wake_epoch": 1788901800, "probed_wake_epoch": 1788901800}
    usage_park.apply_crash_reconcile(rec, 1788901801)
    assert rec["park_state"] == "parked" and rec["wake_epoch"] == 1788903601
    assert rec["notice_key"] == "park:1" and rec["notice_routed"] is True


@pytest.mark.parametrize("terminal,expected", [
    ("You've hit your usage limit. Try again later.", True),
    ("You’ve hit your usage limit. Try again later.", True),
    ("rate limit exceeded", False),
])
def test_only_the_specific_terminal_phrase_can_start_a_codex_park(tmp_path, terminal, expected):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    events = [{"type": "thread.started", "thread_id": "abc"}, {"type": "turn.started"},
              {"type": "turn.failed", "error": {"message": terminal}}]
    drive = run.make_drive(store, "beta", "codex", session.SessionState(cli="codex"), ["codex"],
                           spawn=lambda a, b: Stream(json.dumps(e) for e in events), clock=lambda: 0.0,
                           render=False, heartbeat=lambda: None, usage_limit_park=True)
    outcome = drive(dict(RECORD))
    assert (outcome.limit_fact == "usage_limit") is expected


def test_phrase_in_model_output_is_not_a_terminal_limit(tmp_path):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    events = [{"type": "thread.started", "thread_id": "abc"}, {"type": "turn.started"},
              {"type": "item.completed", "item": {"type": "agent_message", "text": MESSAGE}},
              {"type": "turn.failed", "error": {"message": "unrelated failure"}}]
    drive = run.make_drive(store, "beta", "codex", session.SessionState(cli="codex"), ["codex"],
                           spawn=lambda a, b: Stream(json.dumps(e) for e in events), clock=lambda: 0.0,
                           render=False, heartbeat=lambda: None, usage_limit_park=True)
    assert drive(dict(RECORD)).limit_fact is None


@pytest.mark.parametrize("cause,classification", [
    ({"watchdog": {"summary": "watchdog"}}, loop.CLASS_AMBIGUOUS),
    ({"config_blocked": True}, loop.CLASS_CONFIG_BLOCKED),
    ({"bus_failure": {"summary": "bus"}}, loop.CLASS_AMBIGUOUS),
    ({"terminal_code": "cyber_policy"}, loop.CLASS_PROVIDER_REFUSAL),
])
def test_local_failure_or_refusal_precedes_codex_limit(cause, classification):
    sig = {"terminal": True, "terminal_text": MESSAGE, "codex_limit": {"recheck": True}, **cause}
    assert run._classify_drive_failure(sig)[0] == classification


def test_resolve_reports_the_current_park(tmp_path, capsys):
    from test_dead_letter_resolve import _store, _dead_letter, _run
    from test_usage_park_loop import Clock
    store = _store(tmp_path)
    mid = _dead_letter(store)
    store.send(sender="claude", recipient="beta", body="next task")
    clock = Clock(1788900000)
    def drive(record):
        return loop.DriveOutcome(ok=False, failure_class=loop.CLASS_INFRA, limit_fact="usage_limit",
                                 limit_provider="codex", limit_detail="recheck")
    loop.run_loop(store, "beta", drive, clock=clock.now, sleep=clock.sleep, now_iso=clock.iso,
                  max_polls=2, wrapper_generation="g1", usage_limit_park=True)
    assert _run(tmp_path, "dead-letter", "resolve", "--from", "claude", "--agent", "beta", "--id", mid,
                "--reason", "handled") == 0
    assert "parked" in capsys.readouterr().out.lower()


def test_another_threads_rollout_cannot_confirm_this_seat(tmp_path, monkeypatch):
    folder = tmp_path / "sessions"
    folder.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    stamp = datetime.fromtimestamp(1000.5, timezone.utc).isoformat()
    limits = {"primary": {"used_percent": 100, "window_minutes": 300, "resets_at": 2000}}
    (folder / "rollout-other.jsonl").write_text(
        json.dumps({"timestamp": stamp, "payload": {"rate_limits": limits}}) + "\n", encoding="utf-8")
    fact = run._codex_usage_limit("beta", "abc", 1000.0, now=1001.0)
    assert fact["recheck"] is True and fact["reset_epoch"] is None


def test_recheck_arms_exactly_thirty_minutes_and_close_clears_it():
    from agenttalk.wrapper import usage_park
    rec = {}
    usage_park.apply_limit_result(rec, at="2026-09-09T00:00:00Z", generation="g1", window="",
                                  reset_epoch=None, provider="codex", now_epoch=1788900000, recheck=True)
    assert rec["wake_epoch"] == 1788901800 and rec["limit_recheck"] is True
    usage_park.apply_park_close(rec, at_epoch=1788900010)
    assert "limit_recheck" not in rec and "wake_epoch" not in rec


@pytest.mark.parametrize("reset,wake", [(1788900000, None), (1788903600, 1788903630),
                                        (1788900000 + 8 * 86400, 1789591230),
                                        (1788900001 + 8 * 86400, None)])
def test_codex_reset_is_bounded_before_scheduling(tmp_path, reset, wake):
    from test_usage_park_loop import Clock, make_store, head
    store = make_store(tmp_path)
    clock = Clock(1788900000)
    def drive(record):
        return loop.DriveOutcome(ok=False, failure_class=loop.CLASS_INFRA, limit_fact="usage_limit",
                                 limit_provider="codex", limit_window="five_hour", limit_reset_epoch=reset)
    loop.run_loop(store, "beta", drive, clock=clock.now, sleep=clock.sleep, now_iso=clock.iso,
                  max_polls=2, wrapper_generation="g1", usage_limit_park=True)
    assert store.attempt_record("beta", head(store).id).get("wake_epoch") == wake


def test_restart_gives_one_probe_and_keeps_one_notice(tmp_path):
    from test_usage_park_loop import Clock, make_store, head
    store = make_store(tmp_path)
    notices, calls = [], []
    def drive(record):
        calls.append(record["id"])
        return loop.DriveOutcome(ok=False, failure_class=loop.CLASS_INFRA, limit_fact="usage_limit",
                                 limit_provider="codex", limit_detail="recheck")
    for generation in ("g1", "g2"):
        clock = Clock(1788900000)
        loop.run_loop(store, "beta", drive, clock=clock.now, sleep=clock.sleep, now_iso=clock.iso,
                      max_polls=4, wrapper_generation=generation, usage_limit_park=True,
                      on_escalate=lambda info: notices.append(info) or True)
    rec = store.attempt_record("beta", head(store).id)
    assert len(calls) == 2 and len(notices) == 1
    assert rec["attempts_started"] == rec["excluded_attempts"] == 2


def test_recheck_wake_is_not_reused_after_a_backward_clock_or_crash():
    from agenttalk.wrapper import usage_park
    rec = {"park_state": "probing", "probe_marker": True, "limit_provider": "codex",
           "limit_recheck": True, "probed_wake_epoch": 1788901800}
    usage_park.apply_crash_reconcile(rec, 1788900000)
    assert rec["wake_epoch"] > 1788901800
    assert usage_park.unused_wake(rec) == rec["wake_epoch"]


def test_exact_codex_event_sequence_parks_the_queue_until_reset(tmp_path, monkeypatch):
    from test_usage_park_loop import Clock, make_store, head
    store = make_store(tmp_path, bodies=("task",))
    store.send(sender="alpha", recipient="beta", body="resolved notice", meta={"dead_letter_resolved": "true"})
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    clock = Clock(1788900000)
    calls = []
    def spawn(argv, stdin):
        calls.append(1)
        def events():
            yield json.dumps({"type": "thread.started", "thread_id": "abc"})
            yield json.dumps({"type": "warning", "message": "config warning one"})
            yield json.dumps({"type": "warning", "message": "config warning two"})
            yield json.dumps({"type": "turn.started"})
            folder = home / "sessions"
            folder.mkdir(parents=True, exist_ok=True)
            record = {"timestamp": datetime.now(timezone.utc).isoformat(), "payload": {"rate_limits": {
                "secondary": {"used_percent": 100, "window_minutes": 10080, "resets_at": 1788903600}}}}
            (folder / "rollout-abc.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            yield json.dumps({"type": "error", "message": MESSAGE})
            yield json.dumps({"type": "turn.failed", "error": {"message": MESSAGE}})
        class EventStream:
            returncode = None
            watchdog_result = None
            def __iter__(self):
                return events()
        return EventStream()
    drive = run.make_drive(store, "beta", "codex", session.SessionState(cli="codex"), ["codex"],
                           spawn=spawn, clock=clock.now, render=False, heartbeat=lambda: None,
                           usage_limit_park=True)
    notices = []
    loop.run_loop(store, "beta", drive, clock=clock.now, sleep=clock.sleep, now_iso=clock.iso,
                  max_polls=15, wrapper_generation="g1", usage_limit_park=True,
                  on_dead_letter=lambda info: notices.append(info))
    rec = store.attempt_record("beta", head(store).id)
    assert len(calls) == 1 and rec["wake_epoch"] == 1788903630
    assert rec["attempts_started"] == rec["excluded_attempts"] == 1
    assert store.cursor("beta") == "" and store.dead_lettered_count("beta") == 0 and not notices


def test_confirmed_codex_park_status_names_the_provider():
    from agenttalk.cli import _usage_limit_park_flag
    view = {"present": True, "state": "parked", "provider": "codex", "reset_epoch": 1788903600,
            "wake_epoch": 1788903630}
    assert "provider=codex" in _usage_limit_park_flag(view)


def test_a_resolved_notice_that_dead_letters_never_escalates(tmp_path):
    from agenttalk.cli import _dead_letter_notifier
    from test_usage_park_loop import Clock
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    store.set_operator_facing("alpha")
    store.send(sender="alpha", recipient="beta", body="resolved", meta={"dead_letter_resolved": "true"})
    emit = _dead_letter_notifier(store, "beta")
    clock = Clock(1788900000)
    loop.run_loop(store, "beta", lambda rec: False, clock=clock.now, sleep=clock.sleep, now_iso=clock.iso,
                  max_polls=4, k_poison=1, k_escalate=1,
                  on_escalate=lambda info: emit(info, disposed=False),
                  on_dead_letter=lambda info: emit(info, disposed=True))
    assert store.dead_lettered_count("beta") == 1
    assert not [m for m in store.messages_for("alpha") if m.meta.get("needs_operator") == "true"]


def test_recheck_status_uses_durable_wake_when_marker_is_missing(tmp_path):
    import time
    from agenttalk.cli import _usage_limit_park_flag
    from test_usage_park_loop import Clock, make_store
    store = make_store(tmp_path)
    clock = Clock(time.time())
    def drive(record):
        return loop.DriveOutcome(ok=False, failure_class=loop.CLASS_INFRA, limit_fact="usage_limit",
                                 limit_provider="codex", limit_detail="recheck")
    loop.run_loop(store, "beta", drive, clock=clock.now, sleep=clock.sleep, now_iso=clock.iso,
                  max_polls=2, wrapper_generation="g1", usage_limit_park=True)
    store.clear_usage_limit_park("beta")
    store.write_heartbeat("beta")
    view = store.usage_limit_park_view("beta")
    assert view["provider"] == "codex" and view["wake_epoch"] is not None
    assert "retry=" in _usage_limit_park_flag(view)


def test_codex_uses_the_latest_reading_even_when_its_reset_is_earlier():
    from agenttalk.wrapper import usage_park
    rec = {}
    usage_park.apply_limit_result(rec, at="2026-09-09T00:00:00Z", generation="g1", window="seven_day",
                                  reset_epoch=1788907200, provider="codex", now_epoch=1788900000)
    usage_park.apply_limit_result(rec, at="2026-09-09T00:01:00Z", generation="g2", window="five_hour",
                                  reset_epoch=1788903600, provider="codex", now_epoch=1788900060)
    assert rec["reset_epoch"] == 1788903600 and rec["wake_epoch"] == 1788903630


def test_disabling_the_park_keeps_codex_failure_ambiguous(tmp_path):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    events = [{"type": "thread.started", "thread_id": "abc"}, {"type": "turn.started"},
              {"type": "turn.failed", "error": {"message": MESSAGE}}]
    drive = run.make_drive(store, "beta", "codex", session.SessionState(cli="codex"), ["codex"],
                           spawn=lambda a, b: Stream(json.dumps(e) for e in events), clock=lambda: 0.0,
                           render=False, heartbeat=lambda: None, usage_limit_park=False)
    outcome = drive(dict(RECORD))
    assert outcome.failure_class == loop.CLASS_AMBIGUOUS and outcome.limit_fact is None


def test_codex_does_not_keep_an_old_wake_when_current_reset_is_unknown():
    from agenttalk.wrapper import usage_park
    rec = {}
    usage_park.apply_limit_result(rec, at="2026-09-09T00:00:00Z", generation="g1", window="seven_day",
                                  reset_epoch=1788907200, provider="codex", now_epoch=1788900000)
    usage_park.apply_limit_result(rec, at="2026-09-09T00:01:00Z", generation="g2", window="seven_day",
                                  reset_epoch=None, provider="codex", now_epoch=1788900060)
    assert rec.get("reset_epoch") is None and usage_park.unused_wake(rec) is None


def test_confirmed_status_uses_durable_reset_when_marker_is_missing(tmp_path):
    import time
    from agenttalk.cli import _usage_limit_park_flag
    from test_usage_park_loop import Clock, make_store
    store = make_store(tmp_path)
    clock = Clock(int(time.time()))
    reset = int(clock.now()) + 3600
    def drive(record):
        return loop.DriveOutcome(ok=False, failure_class=loop.CLASS_INFRA, limit_fact="usage_limit",
                                 limit_provider="codex", limit_window="five_hour", limit_reset_epoch=reset)
    loop.run_loop(store, "beta", drive, clock=clock.now, sleep=clock.sleep, now_iso=clock.iso,
                  max_polls=2, wrapper_generation="g1", usage_limit_park=True)
    store.clear_usage_limit_park("beta")
    store.write_heartbeat("beta")
    view = store.usage_limit_park_view("beta")
    assert view["provider"] == "codex" and view["reset_epoch"] == reset
    assert "until=" in _usage_limit_park_flag(view) and "restarted" not in _usage_limit_park_flag(view)


@pytest.mark.parametrize("invalid", [-1, 101])
def test_an_invalid_percentage_is_not_proof_of_exhaustion_or_room(tmp_path, monkeypatch, invalid):
    folder = tmp_path / "sessions"
    folder.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    stamp = datetime.fromtimestamp(1000.5, timezone.utc).isoformat()
    limits = {"primary": {"used_percent": invalid, "window_minutes": 300, "resets_at": 2000}}
    (folder / "rollout-abc.jsonl").write_text(
        json.dumps({"timestamp": stamp, "payload": {"rate_limits": limits}}) + "\n", encoding="utf-8")
    assert run._codex_usage_limit("beta", "abc", 1000.0, now=1001.0)["recheck"] is True


def test_reached_type_confirms_even_if_percentage_is_invalid(tmp_path, monkeypatch):
    folder = tmp_path / "sessions"
    folder.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    stamp = datetime.fromtimestamp(1000.5, timezone.utc).isoformat()
    limits = {"rate_limit_reached_type": "five_hour",
              "primary": {"used_percent": 101, "window_minutes": 300, "resets_at": 2000}}
    (folder / "rollout-abc.jsonl").write_text(
        json.dumps({"timestamp": stamp, "payload": {"rate_limits": limits}}) + "\n", encoding="utf-8")
    fact = run._codex_usage_limit("beta", "abc", 1000.0, now=1001.0)
    assert fact == {"window": "five_hour", "reset_epoch": 2000}
