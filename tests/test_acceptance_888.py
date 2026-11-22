"""Damaged stored review requirements must stop acceptance before reuse."""

from copy import deepcopy

import pytest
import test_acceptance as fixtures

from agenttalk import close, printed_commands as pc
from test_acceptance import (
    cold_phase, command, complete_v3, open_attempt,
    publish_hold, successor, bundle_v2, attach, write_json,
)

case = fixtures.case
case_v2 = fixtures.case_v2
case_v3 = fixtures.case_v3

DAMAGED = ["damaged", {"id": "x", "allowed_agents": "wrong"}, {"id": 12},
           {"id": "x", "allowed_groups": [["group"]]}, "broken\nentry"]


def damage(case, entry):
    path = close.close_path(case["store"], "attempt")
    record = close.load_close(case["store"], "attempt")
    record["required_lenses"].append(deepcopy(entry))
    index = len(record["required_lenses"]) - 1
    write_json(path, record)
    return path, path.read_bytes(), index


def assert_guidance(text, entry, index):
    assert "malformed_state" in text
    assert "attempt" in text and f"required_lenses[{index}]" in text
    assert pc.shown(entry) in text
    if isinstance(entry, str) and "\n" in entry:
        assert entry not in text
    assert "1 damaged entry" in text
    assert text.index("trusted backup") < text.index("move")
    assert "Only if no backup exists" in text
    assert "findings" in text and "remediation items" in text and "requirements" in text
    assert "write down" in text and "edit" in text and "in place" in text
    assert "Traceback" not in text


def store_files(store):
    return {str(p.relative_to(store.dir)): p.read_bytes() for p in store.dir.rglob("*") if p.is_file()}


@pytest.mark.parametrize("entry", DAMAGED)
def test_888_successor_refuses_before_writes(case_v3, capsys, entry):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    publish_hold(case_v3)
    case_v3["plan"]["plan_id"] = "changed-plan"
    write_json(case_v3["inputs"] / "plan.json", case_v3["plan"])
    backup = close.close_path(case_v3["store"], "attempt").read_bytes()
    path, saved, index = damage(case_v3, entry)
    blobs = case_v3["store"].dir / "acceptance" / "sha256"
    before = {p.name: p.read_bytes() for p in blobs.iterdir() if p.is_file()}
    before_store = store_files(case_v3["store"])
    capsys.readouterr()
    assert successor(case_v3) == 2
    err = capsys.readouterr().err
    assert_guidance(err, entry, index)
    assert "or start a new attempt:" not in err
    assert "agenttalk close open --id <new-id>" not in err
    assert path.read_bytes() == saved
    assert {p.name: p.read_bytes() for p in blobs.iterdir() if p.is_file()} == before
    assert store_files(case_v3["store"]) == before_store
    assert not close.close_path(case_v3["store"], "next").exists()
    path.write_bytes(backup)
    assert successor(case_v3) == 0


def test_888_noncold_successor_keeps_new_attempt_guidance(case_v2, capsys):
    assert open_attempt(case_v2) == 0
    bundle_v2(case_v2)
    assert attach(case_v2) == 0
    publish_hold(case_v2)
    damage(case_v2, "damaged")
    capsys.readouterr()
    assert successor(case_v2) == 2
    err = capsys.readouterr().err
    assert "or start a new attempt:" in err
    assert "agenttalk close open --id <new-id>" in err


@pytest.mark.parametrize("value", [None, "damaged", {"id": "bad"}])
def test_888_non_list_damage_names_field(value):
    text = close._damaged_lenses_text({"close_id": "attempt", "required_lenses": value})
    assert "required_lenses is " in text
    assert "required_lenses[0]" not in text
    assert pc.shown(value) in text


@pytest.mark.parametrize("entry", DAMAGED)
def test_888_attach_refuses_before_writes(case_v3, capsys, entry):
    assert open_attempt(case_v3) == 0
    assert cold_phase(case_v3, "commit") == 0
    data = bundle_v2(case_v3)
    data["schema_version"] = 3
    write_json(case_v3["inputs"] / "bundle.json", data)
    backup = close.close_path(case_v3["store"], "attempt").read_bytes()
    path, saved, index = damage(case_v3, entry)
    blobs = case_v3["store"].dir / "acceptance" / "sha256"
    before = {p.name: p.read_bytes() for p in blobs.iterdir() if p.is_file()}
    before_store = store_files(case_v3["store"])
    capsys.readouterr()
    assert attach(case_v3) == 2
    assert_guidance(capsys.readouterr().err, entry, index)
    assert path.read_bytes() == saved
    assert {p.name: p.read_bytes() for p in blobs.iterdir() if p.is_file()} == before
    assert store_files(case_v3["store"]) == before_store
    path.write_bytes(backup)
    assert attach(case_v3) == 0


@pytest.mark.parametrize("entry", DAMAGED)
def test_888_inherit_refuses_before_retaining(case_v3, capsys, entry):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    publish_hold(case_v3)
    path, saved, index = damage(case_v3, entry)
    blobs = case_v3["store"].dir / "acceptance" / "sha256"
    from agenttalk import acceptance_coverage as coverage, acceptance
    prior_hash = acceptance._hash(coverage.canonical(close.load_close(case_v3["store"], "attempt")))
    assert not (blobs / prior_hash).exists()
    catalog_hash = acceptance._hash(coverage.canonical([prior_hash]))
    capsys.readouterr()
    assert open_attempt(case_v3, "--id", "next") == 3
    err = capsys.readouterr().err
    assert_guidance(err, entry, index)
    assert "next" in err and "not frozen" in err and "fresh attempt" in err
    move = err.split("Move the unfrozen close ", 1)[1].split(";", 1)[0]
    assert pc.shown("next") in move
    assert pc.shown("attempt") not in move
    assert "out of .agenttalk/closes" in move
    assert path.read_bytes() == saved
    assert not (blobs / prior_hash).exists()
    assert not (blobs / catalog_hash).exists()
    assert close.load_close(case_v3["store"], "next")["acceptance_route"] == {"pending": True}

@pytest.mark.parametrize("entry", DAMAGED)
def test_888_successor_inherits_damaged_sibling(case_v3, capsys, entry):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    publish_hold(case_v3)
    assert successor(case_v3, new_id="sibling") == 0
    assert command(case_v3, "publish", "--id", "sibling", "--from", "lead", "--verdict", "hold") == 3
    path = close.close_path(case_v3["store"], "sibling")
    record = close.load_close(case_v3["store"], "sibling")
    record["required_lenses"].append(deepcopy(entry))
    index = len(record["required_lenses"]) - 1
    write_json(path, record)
    saved = path.read_bytes()
    from agenttalk import acceptance_coverage as coverage, acceptance
    prior_hash = acceptance._hash(coverage.canonical(record))
    blobs = case_v3["store"].dir / "acceptance" / "sha256"
    capsys.readouterr()
    assert successor(case_v3, new_id="next") == 2
    err = capsys.readouterr().err
    assert_guidance(err, entry, index)
    assert "malformed_state" in err and "sibling" in err and "next" in err
    assert f"required_lenses[{index}]" in err and pc.shown(entry) in err
    assert "not frozen" in err and "fresh attempt" in err
    assert path.read_bytes() == saved
    assert not (blobs / prior_hash).exists()
    assert close.load_close(case_v3["store"], "next")["acceptance_route"] == {"pending": True}


@pytest.mark.parametrize("move_pending", [False, True])
def test_888_restoration_steps_allow_a_fresh_attempt(case_v3, capsys, move_pending):
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    publish_hold(case_v3)
    path = close.close_path(case_v3["store"], "attempt")
    backup = path.read_bytes()
    damage(case_v3, "damaged")
    capsys.readouterr()
    assert open_attempt(case_v3, "--id", "next") == 3
    err = capsys.readouterr().err
    guidance = err.split("was created but not frozen;", 1)[1]
    path.write_bytes(backup)
    if move_pending:
        if "Publish this close as HOLD" in guidance:
            assert command(case_v3, "publish", "--id", "next", "--from", "lead", "--verdict", "hold",
                           "--reason", "test recovery") == 3
        else:
            assert f"Move the unfrozen close {pc.shown('next')} out of .agenttalk/closes" in guidance
            close.close_path(case_v3["store"], "next").replace(case_v3["inputs"] / "unfrozen-next.json")
    capsys.readouterr()
    rc = open_attempt(case_v3, "--id", "retry")
    if move_pending:
        assert rc == 0, capsys.readouterr().err
        assert close.load_close(case_v3["store"], "retry")["acceptance_route"] != {"pending": True}
    else:
        assert rc == 3
        assert "cold exposure audit unavailable" in capsys.readouterr().err
    assert "publish" not in guidance.lower()


def test_888_two_damaged_entries_counted():
    record = {"close_id": "attempt", "required_lenses": ["bad", "also bad"]}
    text = close._damaged_lenses_text(record)
    assert "required_lenses[0]" in text
    assert "2 damaged entries" in text


def test_888_audit_reads_damaged_record_without_refusing_at_sources(case_v3, capsys):
    from agenttalk import acceptance, acceptance_audit as audit, acceptance_coverage as coverage
    from agenttalk import acceptance_obligations as obligations
    assert open_attempt(case_v3) == 0
    complete_v3(case_v3)
    publish_hold(case_v3)
    damage(case_v3, "damaged")
    record = close.load_close(case_v3["store"], "attempt")
    assert isinstance(audit.provenance(case_v3["store"], record), tuple)
    source_hash = acceptance._retain(case_v3["store"], coverage.canonical(record))
    catalog_hash = acceptance._retain(case_v3["store"], coverage.canonical([source_hash]))
    route = {**record["acceptance_route"], "obligations_hash": catalog_hash}
    assert obligations.sources(case_v3["store"], route)[0][1] == record
    assert source_hash in obligations.evidence(case_v3["store"], route)
    current = {**record, "acceptance_route": route}
    with pytest.raises(acceptance.AcceptanceError) as error:
        obligations.inherit(case_v3["store"], current, case_v3["plan"], capture=False)
    assert error.value.code == "malformed_state"
    assert "required_lenses[" in str(error.value)
    capsys.readouterr()
    assert command(case_v3, "check", "--id", "attempt", "--json") == 3
    assert "malformed_state" in capsys.readouterr().out


def test_888_all_acceptance_lens_reads_are_listed():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "agenttalk"
    allowed = {
        ("acceptance.py", "freeze"): "uses freshly validated lenses",
        ("acceptance.py", "_external_worker_acks"): "evaluation turns errors into holds",
        ("acceptance_history.py", "successor"): "checks the parent before copying",
        ("acceptance_obligations.py", "inherit"): "checks captured and retained records",
        ("acceptance_cold.py", "reproduction_lenses"): "attach checks the record first",
        ("acceptance_audit.py", "provenance"): "leaves lens entries out",
    }
    found = set()
    for path in root.glob("acceptance*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(child, ast.Constant) and child.value == "required_lenses" for child in ast.walk(node)
            ):
                found.add((path.name, node.name))
    assert found == set(allowed)
