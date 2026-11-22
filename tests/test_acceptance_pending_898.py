from copy import deepcopy
import json
import subprocess

import pytest

from agenttalk import acceptance, acceptance_audit, close
import test_acceptance as attempts
from test_acceptance import command, complete_v3, git, open_attempt, publish_hold, successor, write_json

case, case_v2, case_v3 = attempts.case, attempts.case_v2, attempts.case_v3


def later_open(case, close_id="later"):
    return command(
        case, "open", "--id", close_id, "--from", "lead", "--scope", "milestone", "--revision", case["sha"],
        "--non-lane-isolation-not-asserted", "--acceptance-plan", str(case["inputs"] / "plan.json"),
        "--project-repo", str(case["project"]),
    )


def refuse_freeze(*args, **kwargs):
    raise acceptance.AcceptanceError("acceptance_project_unverified", "injected freeze refusal")


def failed_open(case, monkeypatch):
    with monkeypatch.context() as fault:
        fault.setattr(acceptance, "freeze", refuse_freeze)
        assert open_attempt(case) == 3
    pending = close.load_close(case["store"], "attempt")
    assert pending["acceptance_route"] == {"pending": True}
    return pending


def pending_sibling(case, *, route=None, events=None, name="pending"):
    record = deepcopy(close.load_close(case["store"], "attempt"))
    record.update(close_id=name, acceptance_route={"pending": True} if route is None else route,
                  events=[] if events is None else events)
    write_json(close.close_path(case["store"], name), record)
    return record


def attempts_for(case):
    return list(acceptance_audit.project_attempts(case["store"], close.load_close(case["store"], "attempt")))


def assert_audit_refused(case):
    with pytest.raises(acceptance.AcceptanceError) as error:
        attempts_for(case)
    assert error.value.code == "acceptance_cold_missing"
    assert "cold exposure audit unavailable" in str(error.value)
    assert "restore" in str(error.value) and "quarantine" in str(error.value)


@pytest.mark.parametrize("published", [False, True], ids=["open", "published-hold"])
def test_failed_open_leftover_does_not_block_later_open(case_v3, monkeypatch, published):
    pending = failed_open(case_v3, monkeypatch)
    if published:
        assert command(case_v3, "publish", "--id", "attempt", "--from", "lead", "--verdict", "hold") == 3
        pending = close.load_close(case_v3["store"], "attempt")
        assert pending["status"] == close.PUBLISHED and pending["acceptance_route"] == {"pending": True}
    before = close.close_path(case_v3["store"], "attempt").read_bytes()
    assert later_open(case_v3) == 0
    assert close.load_close(case_v3["store"], "later")["acceptance_route"].get("project_id")
    assert close.close_path(case_v3["store"], "attempt").read_bytes() == before


def test_other_project_open_is_not_blocked_by_pending_without_identity(case_v3, monkeypatch):
    pending = failed_open(case_v3, monkeypatch)
    assert "project_id" not in pending["acceptance_route"]
    first_project_id = case_v3["plan"]["project_id"]
    other = case_v3["project"].parent / "other-project"
    other.mkdir()
    subprocess.run(["git", "init", str(other)], check=True, capture_output=True)
    git(other, "config", "user.name", "Example")
    git(other, "config", "user.email", "example@example.invalid")
    (other / "source.txt").write_text("other base\n", encoding="utf-8")
    git(other, "add", "source.txt")
    git(other, "commit", "-m", "base")
    base = git(other, "rev-parse", "HEAD")
    (other / "source.txt").write_text("other candidate\n", encoding="utf-8")
    git(other, "commit", "-am", "candidate")
    case_v3["project"], case_v3["sha"] = other, git(other, "rev-parse", "HEAD")
    # A different registry identity is prepared from the other repository.
    project = acceptance.verify_project(str(other), case_v3["sha"], live=False)
    case_v3["plan"]["project_id"] = acceptance.project_id(project)
    assert case_v3["plan"]["project_id"] != first_project_id
    case_v3["plan"]["cold_policy"]["change_base"] = base
    write_json(case_v3["inputs"] / "plan.json", case_v3["plan"])
    assert later_open(case_v3) == 0


def test_successor_leftover_does_not_hide_parent_open_counter(case_v3, monkeypatch):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    assert command(case_v3, "ack", "--id", "attempt", "--lens", "acceptance-run-bar", "--from", "runner-a",
                   "--status", "counter", "--counter", "unfixed", "--finding", "still broken") == 0
    publish_hold(case_v3)
    parent = close.load_close(case_v3["store"], "attempt")
    parent_attempt_id = parent["acceptance_route"]["attempt_id"]
    with monkeypatch.context() as fault:
        fault.setattr(acceptance, "freeze", refuse_freeze)
        assert successor(case_v3) == 2
    pending = close.load_close(case_v3["store"], "next")
    assert pending["acceptance_route"] == {"pending": True}
    assert [e["event"] for e in pending["events"] if e["event"].startswith("acceptance:")] == ["acceptance:successor"]
    assert later_open(case_v3) == 0
    current = close.load_close(case_v3["store"], "later")
    assert any(
        c.get("finding") == "still broken"
        and c.get("obligation_source", {}).get("attempt_id") == parent_attempt_id
        for c in current["counters"].values()
    )


@pytest.mark.parametrize("event", ["acceptance:cold-commit", "acceptance:cold-reconcile", "acceptance:attach"])
def test_pending_with_exposure_event_still_refuses(case_v3, event):
    assert open_attempt(case_v3) == 0
    pending_sibling(case_v3, events=[{"event": event, "by": "lead", "at": "2026-01-01T00:00:00Z"}])
    assert_audit_refused(case_v3)


def test_pending_allows_link_and_other_non_acceptance_events(case_v3):
    assert open_attempt(case_v3) == 0
    pending_sibling(case_v3, events=[{"event": "acceptance:successor"}, {"event": "draft"}])
    assert attempts_for(case_v3) == []


@pytest.mark.parametrize("events", [None, {}, [None], [{"event": None}]])
def test_pending_with_malformed_events_still_refuses(case_v3, events):
    assert open_attempt(case_v3) == 0
    record = pending_sibling(case_v3)
    record["events"] = events
    write_json(close.close_path(case_v3["store"], "pending"), record)
    assert_audit_refused(case_v3)


@pytest.mark.parametrize("route", [{"pending": True, "extra": 1}, {"pending": "yes"}, {"pending": 1}])
def test_only_exact_boolean_pending_can_be_skipped(case_v3, route):
    assert open_attempt(case_v3) == 0
    pending_sibling(case_v3, route=route)
    assert_audit_refused(case_v3)


@pytest.mark.parametrize("damage", ["json", "invalid", "missing-blob"])
def test_damaged_or_invalid_close_still_refuses(case_v3, damage):
    assert open_attempt(case_v3) == 0
    record = pending_sibling(case_v3)
    path = close.close_path(case_v3["store"], "pending")
    if damage == "json":
        path.write_bytes(b"{")
    elif damage == "invalid":
        record["required_lenses"] = None
        write_json(path, record)
    else:
        record["acceptance_route"] = deepcopy(close.load_close(case_v3["store"], "attempt")["acceptance_route"])
        write_json(path, record)
        (case_v3["store"].dir / "acceptance" / "sha256" / record["acceptance_route"]["plan_hash"]).unlink()
    assert_audit_refused(case_v3)


def test_pending_that_cannot_be_loaded_still_refuses(case_v3, monkeypatch):
    assert open_attempt(case_v3) == 0
    pending_sibling(case_v3)
    real_load = close.load_close

    def unreadable(store, close_id):
        if close_id == "pending":
            raise close.CloseError("simulated unreadable close")
        return real_load(store, close_id)

    monkeypatch.setattr(close, "load_close", unreadable)
    assert_audit_refused(case_v3)


def test_same_name_damaged_frozen_close_is_not_skipped(case_v3):
    assert open_attempt(case_v3) == 0
    pending_sibling(case_v3, name="formerly-pending")
    assert attempts_for(case_v3) == []
    path = close.close_path(case_v3["store"], "formerly-pending")
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["acceptance_route"] = deepcopy(close.load_close(case_v3["store"], "attempt")["acceptance_route"])
    write_json(path, changed)
    (case_v3["store"].dir / "acceptance" / "sha256" / changed["acceptance_route"]["plan_hash"]).unlink()
    assert_audit_refused(case_v3)


def test_cold_commit_and_check_ignore_pending_sibling(case_v3, capsys):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    pending_sibling(case_v3)
    record = close.load_close(case_v3["store"], "attempt")
    _, plan = acceptance._policy(case_v3["store"], record)
    assert acceptance_audit.check_prior_exposure(case_v3["store"], record, plan, "cold")
    capsys.readouterr()
    assert command(case_v3, "check", "--id", "attempt", "--json") in {0, 3}
    result = json.loads(capsys.readouterr().out)
    assert "acceptance_cold_missing" not in {hold["code"] for hold in result["holds"]}


def test_inheritance_does_not_retain_pending_sibling(case_v3):
    assert open_attempt(case_v3) == 0
    pending = pending_sibling(case_v3)
    assert later_open(case_v3) == 0
    from agenttalk import acceptance_coverage, acceptance_obligations
    current = close.load_close(case_v3["store"], "later")
    entries = acceptance_obligations.sources(case_v3["store"], current["acceptance_route"])
    assert all(prior["close_id"] != "pending" for _, prior, _, _ in entries)
    pending_hash = acceptance._hash(acceptance_coverage.canonical(pending))
    assert not (case_v3["store"].dir / "acceptance" / "sha256" / pending_hash).exists()
