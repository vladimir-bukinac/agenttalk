"""A seat that runs through the paid gateway (an external worker) can never give a required sign-off (#447).

The roster refuses to name such a seat as a candidate, but the lists can be edited by hand afterwards. A close
therefore re-checks at the moment it matters: who may sign, and whose sign-off counts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttalk import cli, close
from agenttalk.store import Store

SHA = "a" * 40
POLICY = {
    "schema_version": 1,
    "risk_policies": {"security": [{
        "id": "sec", "required_count": 1, "candidates": {"roles": ["sec"]}}]},
    "allow_unmapped": False,
}


def _run(argv: list[str], root: Path) -> int:
    return cli.main(["--root", str(root), *argv])


def _store(tmp_path: Path, *, normal_signer: bool) -> Path:
    """The issue's steps: the paid seat gets role `sec` while no policy exists (allowed), then the policy is
    written by hand."""
    store = Store(tmp_path)
    store.init(["lead", "gw", "alice"])
    store.set_role("lead", "lead")
    store.set_trust_class("gw", "external-worker")
    store.set_role("gw", "sec")
    if normal_signer:
        store.set_role("alice", "sec")
    (store.dir / "signoffs.json").write_text(json.dumps(POLICY), encoding="utf-8")
    return tmp_path


def _open(root: Path) -> list[str]:
    assert _run(["close", "open", "--id", "rel", "--from", "lead", "--scope", "release", "--revision", SHA,
                 "--derive-signoffs", "--risk-class", "security", "--changed-path", "src/a.py",
                 "--dirty-artifact", "d:1", "--non-lane-isolation-not-asserted"], root) == 0
    return close.load_close(Store(root), "rel")["required_signoffs"][0]["generated_lens_ids"]


def _sign(root: Path, agent: str, slot: str) -> int:
    return _run(["close", "ack", "--id", "rel", "--lens", slot, "--status", "accept", "--from", agent,
                 "--risk-class", "none", "--release-blocker", "no", "--tests-referenced", "n/a",
                 "--tests-executed", "n/a", "--residual-risk", "n/a", "--na-reason", "lw", "--evidence", "p"],
                 root)


def test_the_plan_leaves_the_paid_seat_out_and_says_so(tmp_path: Path, capsys) -> None:
    root = _store(tmp_path, normal_signer=False)
    _open(root)
    capsys.readouterr()
    assert _run(["close", "signoffs", "plan", "--id", "rel", "--risk-class", "security",
                 "--changed-path", "src/a.py", "--json"], root) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["resolved_candidates"] == {"security:sec": []}
    assert plan["excluded_external_workers"] == {"security:sec": ["gw"]}
    assert _run(["close", "signoffs", "plan", "--id", "rel", "--risk-class", "security",
                 "--changed-path", "src/a.py"], root) == 0
    text = capsys.readouterr().out
    assert "none - would be unroutable" in text and "paid gateway seat(s) cannot give a sign-off: gw" in text


def test_a_close_cannot_be_satisfied_by_the_paid_seat_alone(tmp_path: Path, capsys) -> None:
    """The issue's reproduction: on master the plan lists the paid seat as the only candidate and its sign-off
    lets the close through."""
    root = _store(tmp_path, normal_signer=False)
    slot = _open(root)[0]
    assert _sign(root, "gw", slot) == 2                       # refused when it is given
    assert slot not in close.load_close(Store(root), "rel")["lens_acks"]
    assert "paid gateway" in capsys.readouterr().err
    assert _run(["close", "check", "--id", "rel", "--json"], root) == 3     # still HOLD
    result = json.loads(capsys.readouterr().out)
    details = [h["detail"] for h in result["holds"]]
    assert any("run through the paid gateway" in d and "gw" in d for d in details)
    assert close.HOLD_UNROUTABLE_SIGNOFF in {h["code"] for h in result["holds"]}
    assert result["signoff_exclusions"] == {"security:sec": ["gw"]}


def test_a_sign_off_already_in_the_record_from_the_paid_seat_does_not_count(tmp_path: Path, capsys) -> None:
    """Even if the record was edited so that the paid seat's sign-off is there, the count ignores it."""
    root = _store(tmp_path, normal_signer=True)
    slot = _open(root)[0]
    store = Store(root)
    record = close.load_close(store, "rel")
    close.apply_ack(record, lens_id=slot, status="accept", agent="gw", from_role="sec", at="t",
                    evidence={"risk_class": "none"})
    path = close.close_path(store, "rel")
    path.write_text(json.dumps(record), encoding="utf-8")
    capsys.readouterr()
    assert _run(["close", "check", "--id", "rel", "--json"], root) == 3
    result = json.loads(capsys.readouterr().out)
    missing = [h["detail"] for h in result["holds"] if "needs 1 distinct qualifying" in h["detail"]]
    assert missing and "ignored the sign-off of gw" in missing[0]


def test_a_normal_seat_still_satisfies_the_sign_off_and_the_exclusion_is_reported(tmp_path: Path, capsys) -> None:
    root = _store(tmp_path, normal_signer=True)
    slot = _open(root)[0]
    assert _sign(root, "gw", slot) == 2                       # the paid seat is refused
    assert _sign(root, "alice", slot) == 0                    # a trusted seat counts
    capsys.readouterr()
    assert _run(["close", "check", "--id", "rel"], root) == 0           # GO
    out = capsys.readouterr().out
    assert "paid gateway seat(s) gw cannot give a sign-off and are not counted" in out


def test_the_roster_time_refusal_still_works(tmp_path: Path) -> None:
    """Step 4 of the issue: with the policy in place, naming the paid seat is refused as before."""
    root = _store(tmp_path, normal_signer=False)
    with pytest.raises(ValueError, match="cannot be a signoff candidate"):
        Store(root).set_role("gw", "sec")


def test_the_candidate_contract_excludes_by_default_and_the_roster_guard_can_still_see_them(tmp_path: Path) -> None:
    root = _store(tmp_path, normal_signer=True)
    cfg = Store(root).load_config()
    args = {"candidate_refset": {"roles": ["sec"]}, "default_reviewers": {}, "use_default_reviewers": False,
            "domain_refset": {}, "include_domain_reviewers": False}
    assert close.resolve_signoff_candidates(cfg, **args) == ["alice"]
    assert sorted(close.resolve_signoff_candidates(cfg, exclude_external_workers=False, **args)) == ["alice", "gw"]
    assert close.split_signoff_candidates(cfg, **args) == (["alice"], ["gw"])
    assert close.external_worker_agents(cfg) == {"gw"}


def _make_gw_a_lead(root: Path) -> None:
    """The reviewer's reproduction: a hand edit of the roster (the roster commands refuse this) makes the paid
    seat a close lead, which is what unlocks `--override`."""
    path = Store(root).config_path
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["roles"]["lead"] = "worker"          # a lead only counts when it is the sole one
    cfg["roles"]["gw"] = "lead"
    path.write_text(json.dumps(cfg), encoding="utf-8")


def test_an_overriding_sign_off_from_the_paid_seat_is_refused_and_keeps_the_trusted_one(
        tmp_path: Path, capsys) -> None:
    root = _store(tmp_path, normal_signer=True)
    slot = _open(root)[0]
    assert _sign(root, "alice", slot) == 0
    assert _run(["close", "check", "--id", "rel"], root) == 0                # GO on alice's sign-off
    before = close.load_close(Store(root), "rel")["lens_acks"][slot]
    _make_gw_a_lead(root)
    capsys.readouterr()
    assert _run(["close", "ack", "--id", "rel", "--lens", slot, "--status", "accept", "--from", "gw",
                 "--override", "--risk-class", "none", "--release-blocker", "no", "--tests-referenced", "n/a",
                 "--tests-executed", "n/a", "--residual-risk", "n/a", "--na-reason", "lw", "--evidence", "p"],
                root) == 2
    assert "not even as an override" in capsys.readouterr().err
    after = close.load_close(Store(root), "rel")["lens_acks"][slot]
    assert after == before and after["from"] == "alice"                      # the trusted ack is untouched
    assert _run(["close", "check", "--id", "rel"], root) == 0                # still GO


def test_the_paid_seat_cannot_record_the_set_level_override_either(tmp_path: Path, capsys) -> None:
    root = _store(tmp_path, normal_signer=False)
    _open(root)
    _make_gw_a_lead(root)
    capsys.readouterr()
    assert _run(["close", "signoffs", "override", "--id", "rel", "--set", "security:sec", "--from", "gw",
                 "--reason", "skip it"], root) == 2
    assert "cannot bypass a required sign-off" in capsys.readouterr().err
    assert not close.load_close(Store(root), "rel").get("signoff_overrides")
    assert _run(["close", "check", "--id", "rel"], root) == 3                # still HOLD


def test_a_stored_set_override_from_a_seat_that_is_a_paid_seat_now_does_not_hold(tmp_path: Path, capsys) -> None:
    """A trusted lead records the set-level override; later the same seat becomes a paid gateway seat."""
    root = _store(tmp_path, normal_signer=False)
    _open(root)
    assert _run(["close", "signoffs", "override", "--id", "rel", "--set", "security:sec", "--from", "lead",
                 "--reason", "skip it"], root) == 0
    assert _run(["close", "check", "--id", "rel"], root) == 0                # GO while the lead is trusted
    path = Store(root).config_path                  # the roster commands refuse this, so edit it by hand
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("trust_classes", {})["lead"] = "external-worker"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    capsys.readouterr()
    assert _run(["close", "check", "--id", "rel", "--json"], root) == 3     # HOLD: the override no longer counts
    holds = json.loads(capsys.readouterr().out)["holds"]
    assert any("override" in h["detail"] and "lead" in h["detail"] and "ignored" in h["detail"] for h in holds)


def test_a_trusted_signature_replaces_a_rejected_stored_override(tmp_path: Path, capsys) -> None:
    """The whole recovery: the override is rejected, and a trusted seat's accept then satisfies the set while the
    historical override stays stored."""
    root = _store(tmp_path, normal_signer=True)
    slot = _open(root)[0]
    assert _run(["close", "signoffs", "override", "--id", "rel", "--from", "lead", "--set", "security:sec",
                 "--reason", "skip it"], root) == 0
    path = Store(root).config_path
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["roles"]["lead"] = "worker"
    cfg.setdefault("trust_classes", {})["lead"] = "external-worker"
    cfg["roles"]["alice"] = "sec"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    capsys.readouterr()
    assert _run(["close", "check", "--id", "rel", "--json"], root) == 3
    holds = json.loads(capsys.readouterr().out)["holds"]
    assert any("ignored" in h["detail"] and "lead" in h["detail"] for h in holds)      # the rejection is visible
    assert _sign(root, "alice", slot) == 0
    assert "security:sec" in close.load_close(Store(root), "rel")["signoff_overrides"]  # still stored
    capsys.readouterr()
    assert _run(["close", "check", "--id", "rel"], root) == 0                          # GO on alice's sign-off


@pytest.mark.parametrize("field,value", [
    ("signoff_overrides", ["security:sec"]),
    ("signoff_overrides", "security:sec"),
    ("signoff_overrides", {"security:sec": "x"}),
    ("signoff_overrides", {"security:sec": {"by": ["lead"]}}),
    ("required_signoffs", "x"),
    ("required_signoffs", [{"id": ["a"]}]),
])
def test_a_malformed_stored_sign_off_state_holds_instead_of_crashing(tmp_path: Path, capsys, field, value) -> None:
    root = _store(tmp_path, normal_signer=True)
    _open(root)
    store = Store(root)
    path = close.close_path(store, "rel")
    record = json.loads(path.read_text(encoding="utf-8"))
    record[field] = value
    path.write_text(json.dumps(record), encoding="utf-8")
    capsys.readouterr()
    assert _run(["close", "check", "--id", "rel", "--json"], root) == 3
    assert close.HOLD_MALFORMED in {h["code"] for h in json.loads(capsys.readouterr().out)["holds"]}


@pytest.mark.parametrize("mutate", [
    lambda r, lid: r["required_signoffs"][0].__setitem__("generated_lens_ids", [["a"]]),
    lambda r, lid: r["lens_acks"].__setitem__(lid, {"from": ["a"], "status": "accept"}),
    lambda r, lid: r["lens_acks"].__setitem__(lid, "x"),
])
def test_a_malformed_ack_or_lens_list_holds_instead_of_crashing(tmp_path: Path, capsys, mutate) -> None:
    root = _store(tmp_path, normal_signer=True)
    lid = _open(root)[0]
    path = close.close_path(Store(root), "rel")
    record = json.loads(path.read_text(encoding="utf-8"))
    mutate(record, lid)
    path.write_text(json.dumps(record), encoding="utf-8")
    capsys.readouterr()
    assert _run(["close", "check", "--id", "rel", "--json"], root) == 3
    assert close.HOLD_MALFORMED in {h["code"] for h in json.loads(capsys.readouterr().out)["holds"]}


def _plain_store(tmp_path: Path, *, signer: bool) -> Path:
    """Only trusted seats (no paid seat in the roster, so the roster commands can change roles freely)."""
    store = Store(tmp_path)
    store.init(["lead", "alice"])
    store.set_role("lead", "lead")
    if signer:
        store.set_role("alice", "sec")
    (store.dir / "signoffs.json").write_text(json.dumps(POLICY), encoding="utf-8")
    return tmp_path



def _demote(store: Store, who: str) -> None:
    store.set_role(who, "worker")


def _external(store: Store, who: str) -> None:
    _demote(store, who)
    store.set_trust_class(who, "external-worker")


def _remove_and_readd(store: Store, who: str) -> None:
    store.remove_agent(who)
    store.add_agent(who)


# change, what happens to a stored OVERRIDE by that author, what happens to a stored ACK by that author
# (an override has no role re-check: a trusted active author keeps counting; an ack also needs a candidate role)
STANDING_CHANGES = [
    ("unchanged", lambda st, w: None, 0, 0),
    ("demoted to worker", _demote, 0, 3),
    ("reclassified external-worker", _external, 3, 3),
    ("trust class removed", lambda st, w: st.set_trust_class(w, None), 0, 0),
    ("retired", lambda st, w: st.retire_agent(w), 3, 3),
    ("removed", lambda st, w: st.remove_agent(w), 3, 3),
    ("renamed away", lambda st, w: st.rename_agent(w, w + "2"), 3, 3),
    ("removed and re-added, same name", _remove_and_readd, 0, 3),
]


@pytest.mark.parametrize("label,change,override_verdict,ack_verdict", STANDING_CHANGES,
                         ids=[c[0] for c in STANDING_CHANGES])
def test_standing_change_of_a_stored_override_author(tmp_path: Path, capsys, label, change, override_verdict,
                                                     ack_verdict) -> None:
    root = _plain_store(tmp_path, signer=False)
    _open(root)
    assert _run(["close", "signoffs", "override", "--id", "rel", "--from", "lead", "--set", "security:sec",
                 "--reason", "skip it"], root) == 0
    change(Store(root), "lead")
    assert _run(["close", "check", "--id", "rel"], root) == override_verdict, label


@pytest.mark.parametrize("label,change,override_verdict,ack_verdict", STANDING_CHANGES,
                         ids=[c[0] for c in STANDING_CHANGES])
def test_standing_change_of_a_stored_ack_author(tmp_path: Path, capsys, label, change, override_verdict,
                                                ack_verdict) -> None:
    root = _plain_store(tmp_path, signer=True)
    slot = _open(root)[0]
    assert _sign(root, "alice", slot) == 0
    change(Store(root), "alice")
    assert _run(["close", "check", "--id", "rel"], root) == ack_verdict, label
