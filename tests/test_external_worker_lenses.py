"""A paid gateway seat (external worker) can satisfy no required close lens, however the lens was declared (#454).

Also: a malformed close record is reported as a HOLD before any evaluator reads it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttalk import cli, close
from agenttalk.store import Store

SHA = "a" * 40


def _run(argv: list[str], root: Path) -> int:
    return cli.main(["--root", str(root), *argv])


def _init(tmp_path: Path) -> Path:
    store = Store(tmp_path)
    store.init(["lead", "gw", "alice"])
    store.set_role("lead", "lead")
    store.set_trust_class("gw", "external-worker")
    return tmp_path


def _open(root: Path, *allow: str) -> None:
    argv = ["close", "open", "--id", "rel", "--from", "lead", "--scope", "release", "--revision", SHA,
            "--non-lane-isolation-not-asserted", "--dirty-artifact", "d:1"]
    for entry in allow:
        argv += ["--lens", entry.split(":")[0], "--allow", entry]
    assert _run(argv, root) == 0


def _ack(root: Path, agent: str, lens: str = "sec", status: str = "accept", *extra: str) -> int:
    return _run(["close", "ack", "--id", "rel", "--lens", lens, "--status", status, "--from", agent, *extra,
                 "--risk-class", "none", "--release-blocker", "no", "--tests-referenced", "n/a",
                 "--tests-executed", "n/a", "--residual-risk", "n/a", "--na-reason", "lw", "--evidence", "p",
                 "--reason", "not applicable"], root)


def _edit(root: Path, change) -> None:
    path = close.close_path(Store(root), "rel")
    record = json.loads(path.read_text(encoding="utf-8"))
    change(record)
    path.write_text(json.dumps(record), encoding="utf-8")


def _verdict(root: Path, capsys) -> tuple[int, dict]:
    capsys.readouterr()
    code = _run(["close", "check", "--id", "rel", "--json"], root)
    return code, json.loads(capsys.readouterr().out)


def test_a_paid_seat_cannot_ack_a_hand_declared_required_lens(tmp_path: Path, capsys) -> None:
    root = _init(tmp_path)
    _open(root, "sec:gw")
    capsys.readouterr()
    assert _ack(root, "gw") == 2
    assert "paid gateway" in capsys.readouterr().err
    assert "sec" not in close.load_close(Store(root), "rel")["lens_acks"]
    code, result = _verdict(root, capsys)
    assert code == 3
    assert close.HOLD_MISSING_LENS in {h["code"] for h in result["holds"]}


@pytest.mark.parametrize("status", ["accept", "na"])
def test_a_stored_paid_seat_ack_on_a_required_lens_does_not_count(tmp_path: Path, capsys, status) -> None:
    root = _init(tmp_path)
    _open(root, "sec:gw", "ops:alice")
    assert _ack(root, "alice", "ops") == 0
    # the record was edited so that the paid seat's ack is there
    store = Store(root)
    record = close.load_close(store, "rel")
    close.apply_ack(record, lens_id="sec", status=status, agent="gw", from_role=None, at="t",
                    evidence={"risk_class": "none"}, reason="not applicable")
    close.close_path(store, "rel").write_text(json.dumps(record), encoding="utf-8")
    code, result = _verdict(root, capsys)
    assert code == 3
    details = [h["detail"] for h in result["holds"]]
    assert any("sec" in d and "paid gateway" in d for d in details), details


def test_an_override_ack_from_a_paid_seat_on_a_hand_declared_lens_is_refused(tmp_path: Path, capsys) -> None:
    root = _init(tmp_path)
    _open(root, "sec:alice")
    path = Store(root).config_path
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["roles"]["lead"] = "worker"          # hand edit: the paid seat becomes the sole lead
    cfg["roles"]["gw"] = "lead"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    capsys.readouterr()
    assert _ack(root, "gw", "sec", "accept", "--override") == 2
    assert "paid gateway" in capsys.readouterr().err
    assert "sec" not in close.load_close(Store(root), "rel")["lens_acks"]


def test_a_trusted_seat_still_satisfies_a_hand_declared_lens(tmp_path: Path, capsys) -> None:
    root = _init(tmp_path)
    _open(root, "sec:alice")
    assert _ack(root, "alice") == 0
    code, _result = _verdict(root, capsys)
    assert code in (0, 3)       # the lens is satisfied; any hold is not about the lens
    _code, result = _verdict(root, capsys)
    assert close.HOLD_MISSING_LENS not in {h["code"] for h in result["holds"]}


def test_an_optional_lens_is_out_of_scope(tmp_path: Path, capsys) -> None:
    root = _init(tmp_path)
    assert _run(["close", "open", "--id", "rel", "--from", "lead", "--scope", "release", "--revision", SHA,
                 "--non-lane-isolation-not-asserted", "--dirty-artifact", "d:1", "--optional-lens", "extra",
                 "--allow", "extra:gw"], root) == 0
    assert _ack(root, "gw", "extra") == 0                       # an optional lens feeds no verdict


def test_the_malformed_record_holds_before_any_evaluator_reads_it(tmp_path: Path, capsys, monkeypatch) -> None:
    """`close check` used to build the Definition-of-Done evidence (which reads the acks) before the verdict
    noticed the record was malformed."""
    root = _init(tmp_path)
    _open(root, "sec:alice")
    _edit(root, lambda r: r.update(lens_acks="x"))

    def reads_the_record(*_args, **_kwargs):
        raise AssertionError("an evaluator read a malformed record")

    monkeypatch.setattr(cli, "_build_dod_eval", reads_the_record)
    monkeypatch.setattr(cli, "_close_worktree_eval", reads_the_record)
    monkeypatch.setattr(cli, "_build_signoff_eval", reads_the_record)
    code, result = _verdict(root, capsys)
    assert code == 3
    assert close.HOLD_MALFORMED in {h["code"] for h in result["holds"]}


def test_an_acceptance_lens_ack_from_a_paid_seat_is_named_and_ignored(tmp_path: Path) -> None:
    from agenttalk import acceptance
    store = Store(_init(tmp_path))
    record = {"lens_acks": {"acceptance-run-a": {"from": "gw"}, "acceptance-cold": {"from": "alice"},
                            "sec": {"from": "gw"}, "acceptance-notes": {"from": "gw"}},
              "required_lenses": [{"id": "acceptance-run-a"}, {"id": "acceptance-cold"}, {"id": "sec"},
                                  {"id": "acceptance-notes", "required": False}]}
    holds: list = []
    acceptance._external_worker_acks(store, record, holds)
    assert [code for code, _detail in holds] == ["acceptance_lens_not_independent"]
    assert "acceptance-run-a" in holds[0][1]


def test_an_optional_acceptance_note_from_a_paid_seat_stays_neutral(tmp_path: Path) -> None:
    from agenttalk import acceptance
    store = Store(_init(tmp_path))
    record = {"lens_acks": {"acceptance-notes": {"from": "gw"}},
              "required_lenses": [{"id": "acceptance-notes", "required": False}]}
    holds: list = []
    acceptance._external_worker_acks(store, record, holds)
    assert holds == []


# ----------------------------------------------------- the paid seat is remembered after it leaves the roster

POLICY = {
    "schema_version": 1,
    "risk_policies": {"security": [{"id": "sec", "required_count": 1, "candidates": {"roles": ["sec"]}}]},
    "allow_unmapped": False,
}

LEAVING = [
    ("retired", lambda st, who: st.retire_agent(who)),
    ("removed", lambda st, who: st.remove_agent(who)),
    ("renamed away", lambda st, who: st.rename_agent(who, who + "2")),
]


def _store_with_old_ack(tmp_path: Path, kind: str, author: str) -> Path:
    """A close with a stored accepting ack on a required lens, made by `author`. The paid seat `gw` was external
    when it acked; alice is a trusted reviewer."""
    store = Store(tmp_path)
    store.init(["lead", "gw", "alice"])
    store.set_role("lead", "lead")
    store.set_trust_class("gw", "external-worker")
    store.set_role("alice", "sec")
    if kind == "signoff-set":
        store.set_role("gw", "sec")                     # allowed while no policy exists
        (store.dir / "signoffs.json").write_text(json.dumps(POLICY), encoding="utf-8")
        assert _run(["close", "open", "--id", "rel", "--from", "lead", "--scope", "release", "--revision", SHA,
                     "--derive-signoffs", "--risk-class", "security", "--changed-path", "src/a.py",
                     "--dirty-artifact", "d:1", "--non-lane-isolation-not-asserted"], tmp_path) == 0
        lens = close.load_close(store, "rel")["required_signoffs"][0]["generated_lens_ids"][0]
    else:
        lens = "acceptance-run-x" if kind == "acceptance" else "sec"
        assert _run(["close", "open", "--id", "rel", "--from", "lead", "--scope", "release", "--revision", SHA,
                     "--non-lane-isolation-not-asserted", "--dirty-artifact", "d:1", "--lens", lens,
                     "--allow", f"{lens}:gw", "--allow", f"{lens}:alice"], tmp_path) == 0
    record = close.load_close(store, "rel")
    close.apply_ack(record, lens_id=lens, status="accept", agent=author, from_role="sec", at="t",
                    evidence={"risk_class": "none"})
    close.close_path(store, "rel").write_text(json.dumps(record), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("kind", ["hand-declared", "acceptance", "signoff-set"])
@pytest.mark.parametrize("label,leave", LEAVING, ids=[x[0] for x in LEAVING])
def test_a_paid_seats_old_ack_stays_ignored_after_it_leaves(tmp_path: Path, capsys, kind, label, leave) -> None:
    root = _store_with_old_ack(tmp_path, kind, "gw")
    code, _ = _verdict(root, capsys)
    assert code == 3                                      # ignored while it is a paid seat
    if kind == "signoff-set" and label == "renamed away":
        # the roster guard refuses to move a paid seat that is a sign-off candidate; the close stays on HOLD
        with pytest.raises(ValueError, match="signoff candidate"):
            leave(Store(root), "gw")
    else:
        leave(Store(root), "gw")
    code, result = _verdict(root, capsys)
    assert code == 3, (kind, label)
    if kind != "signoff-set":
        assert any("paid gateway" in h["detail"] for h in result["holds"])
    assert _run(["close", "publish", "--id", "rel", "--from", "lead", "--verdict", "go"], root) != 0


@pytest.mark.parametrize("kind", ["hand-declared", "acceptance"])
@pytest.mark.parametrize("label,leave", LEAVING[:2], ids=[x[0] for x in LEAVING[:2]])
def test_a_trusted_seats_old_ack_keeps_counting_after_it_retires(tmp_path: Path, capsys, kind, label, leave) -> None:
    root = _store_with_old_ack(tmp_path, kind, "alice")
    leave(Store(root), "alice")
    _code, result = _verdict(root, capsys)
    assert close.HOLD_MISSING_LENS not in {h["code"] for h in result["holds"]}
    assert not any("paid gateway" in h["detail"] for h in result["holds"])


def test_the_remembered_paid_seat_survives_a_rename_for_both_names(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.init(["lead", "gw"])
    store.set_trust_class("gw", "external-worker")
    store.rename_agent("gw", "gw2")
    assert close.external_worker_agents(store.load_config()) == {"gw", "gw2"}


def test_a_removed_paid_seat_cannot_be_added_again_under_the_same_name(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.init(["lead", "gw"])
    store.set_trust_class("gw", "external-worker")
    store.remove_agent("gw")
    with pytest.raises(ValueError, match="tombstone"):
        store.add_agent("gw")
    assert close.external_worker_agents(store.load_config()) == {"gw"}


def test_a_trusted_seat_is_never_remembered_as_a_paid_seat(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.init(["lead", "alice"])
    store.retire_agent("alice")
    assert close.external_worker_agents(store.load_config()) == set()


def test_publish_refuses_a_malformed_record_with_its_existing_error(tmp_path: Path, capsys) -> None:
    """`close check` reports the malformed state as a HOLD; `close publish` stays fail-closed with its own error."""
    root = _init(tmp_path)
    _open(root, "sec:alice")
    _edit(root, lambda r: r.update(lens_acks="x"))
    capsys.readouterr()
    assert _run(["close", "publish", "--id", "rel", "--from", "lead", "--verdict", "go"], root) == 2
    assert "malformed" in capsys.readouterr().err


def test_the_roster_refuses_to_clear_a_paid_seats_class(tmp_path: Path) -> None:
    """The only way out of the paid class is to retire the identity, which the close remembers."""
    store = Store(tmp_path)
    store.init(["lead", "gw"])
    store.set_trust_class("gw", "external-worker")
    with pytest.raises(ValueError, match="cannot be cleared"):
        store.set_trust_class("gw", None)
