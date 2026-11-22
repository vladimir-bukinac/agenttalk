from copy import deepcopy

import pytest

from agenttalk import close
import test_acceptance as attempts
import test_acceptance_pending_898 as pending_tests
from test_acceptance import command, complete_v3, open_attempt, publish_hold, successor, write_json

case, case_v2, case_v3 = attempts.case, attempts.case_v2, attempts.case_v3


@pytest.mark.parametrize("kind", ["plain", "hold", "successor"])
def test_pending_finding_refuses_later_open(case_v3, monkeypatch, capsys, kind):
    if kind == "successor":
        assert open_attempt(case_v3) == 0
        complete_v3(case_v3)
        publish_hold(case_v3)
        with monkeypatch.context() as fault:
            fault.setattr(pending_tests.acceptance, "freeze", pending_tests.refuse_freeze)
            assert successor(case_v3) == 2
        close_id = "next"
    else:
        pending_tests.failed_open(case_v3, monkeypatch)
        close_id = "attempt"
    assert command(case_v3, "ack", "--id", close_id, "--lens", "acceptance-run-bar", "--from", "runner-a",
                   "--status", "counter", "--counter", "unfixed", "--finding", "pending finding") == 0
    if kind == "hold":
        assert command(case_v3, "publish", "--id", close_id, "--from", "lead", "--verdict", "hold") == 3
        assert close.load_close(case_v3["store"], close_id)["status"] == close.PUBLISHED
    assert close.load_close(case_v3["store"], close_id)["counters"]["unfixed"]["finding"] == "pending finding"
    capsys.readouterr()
    assert pending_tests.later_open(case_v3) == 3
    message = capsys.readouterr().err
    assert "cold exposure audit unavailable" in message
    assert "restore" in message and "quarantine" in message


@pytest.mark.parametrize("field", ["lens_acks", "counters", "remediation_items"])
def test_pending_with_own_state_refuses_even_without_an_ack_event(case_v3, field):
    assert open_attempt(case_v3) == 0
    pending = pending_tests.pending_sibling(case_v3)
    pending[field] = {"new": {"finding": "own finding"}}
    write_json(close.close_path(case_v3["store"], "pending"), pending)
    pending_tests.assert_audit_refused(case_v3)


@pytest.mark.parametrize("remediation", [False, True])
def test_pending_successor_preserves_unmodified_parent_state(case_v3, monkeypatch, remediation):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    assert command(case_v3, "ack", "--id", "attempt", "--lens", "acceptance-run-bar", "--from", "runner-a",
                   "--status", "counter", "--counter", "unfixed", "--finding", "parent finding") == 0
    if remediation:
        assert command(case_v3, "counter", "decide", "--id", "attempt", "--counter", "unfixed", "--from", "lead",
                       "--decision", "accept", "--reason", "confirmed", "--rem-owner", "lead", "--rem-fix", "repair",
                       "--rem-verification", "rerun", "--blocker", "--gate", "repair-proof") == 0
    publish_hold(case_v3)
    parent = close.load_close(case_v3["store"], "attempt")
    with monkeypatch.context() as fault:
        fault.setattr(pending_tests.acceptance, "freeze", pending_tests.refuse_freeze)
        assert successor(case_v3) == 2
    child = close.load_close(case_v3["store"], "next")
    assert child["counters"] == parent["counters"] and not child["lens_acks"]
    assert child["remediation_items"] == parent["remediation_items"]
    assert bool(child["remediation_items"]) == remediation
    assert pending_tests.later_open(case_v3) == 0
    later = close.load_close(case_v3["store"], "later")
    assert any(c.get("finding") == "parent finding" for c in later["counters"].values())


@pytest.mark.parametrize("field", ["counters", "remediation_items"])
def test_modified_successor_state_refuses(case_v3, monkeypatch, field):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    publish_hold(case_v3)
    with monkeypatch.context() as fault:
        fault.setattr(pending_tests.acceptance, "freeze", pending_tests.refuse_freeze)
        assert successor(case_v3) == 2
    child = close.load_close(case_v3["store"], "next")
    child[field] = deepcopy(child[field])
    child[field]["extra"] = {"finding": "own finding"}
    write_json(close.close_path(case_v3["store"], "next"), child)
    assert pending_tests.later_open(case_v3) == 3


def test_successor_counter_must_match_parent_json_types(case_v3, monkeypatch):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    assert command(case_v3, "ack", "--id", "attempt", "--lens", "acceptance-run-bar", "--from", "runner-a",
                   "--status", "counter", "--counter", "unfixed", "--finding", "parent finding") == 0
    with close.close_transaction(case_v3["store"], "attempt") as transaction:
        transaction.record["counters"]["unfixed"]["flag"] = True
        transaction.commit()
    publish_hold(case_v3)
    with monkeypatch.context() as fault:
        fault.setattr(pending_tests.acceptance, "freeze", pending_tests.refuse_freeze)
        assert successor(case_v3) == 2
    child = close.load_close(case_v3["store"], "next")
    child["counters"]["unfixed"]["flag"] = 1
    write_json(close.close_path(case_v3["store"], "next"), child)
    assert pending_tests.later_open(case_v3) == 3


@pytest.mark.parametrize("damage", ["missing-hash", "missing-parent", "changed-parent", "duplicate-link"])
def test_successor_with_unverifiable_parent_refuses(case_v3, monkeypatch, damage):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    publish_hold(case_v3)
    with monkeypatch.context() as fault:
        fault.setattr(pending_tests.acceptance, "freeze", pending_tests.refuse_freeze)
        assert successor(case_v3) == 2
    child = close.load_close(case_v3["store"], "next")
    link = next(event for event in child["events"] if event["event"] == "acceptance:successor")
    if damage == "missing-hash":
        del link["parent_record_hash"]
    elif damage == "missing-parent":
        parent = close.load_close(case_v3["store"], "attempt")
        parent["close_id"] = "elsewhere"
        write_json(close.close_path(case_v3["store"], "attempt"), parent)
    elif damage == "changed-parent":
        parent = close.load_close(case_v3["store"], "attempt")
        parent["counters"]["new"] = {"finding": "new parent finding"}
        write_json(close.close_path(case_v3["store"], "attempt"), parent)
    else:
        child["events"].append(deepcopy(link))
    write_json(close.close_path(case_v3["store"], "next"), child)
    assert pending_tests.later_open(case_v3) == 3
