"""`agenttalk overview`: one read-only screen built only from the dashboard's own builders."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agenttalk import budget, cli, overview, web
from agenttalk.store import Store


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    s.init(["lead", "claude-a", "codex-b"])
    s.send(sender="lead", recipient="claude-a", body="please look", kind="question",
           subject="check the thing", meta={"request_id": "q-ov1"})
    s.send(sender="lead", recipient="codex-b", body="and this", kind="question",
           subject="another thing", meta={"request_id": "q-ov2"})
    return s


def _run(tmp_path: Path, capsys, *argv: str) -> str:
    assert cli.main(["--root", str(tmp_path), "overview", *argv]) == 0
    return capsys.readouterr().out


def _files(root: Path) -> dict[Path, tuple[bytes, int]]:
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------- parity

def test_counts_match_the_dashboard_builders(tmp_path: Path, capsys) -> None:
    s = _store(tmp_path)
    desc = web.RootDescriptor(store=s, label=s.root.name)
    state = web.build_state([desc])["roots"][0]
    attention = web.build_attention(desc, state["agents"])
    gates = web.build_gates(desc)

    data = json.loads(_run(tmp_path, capsys, "--json"))
    assert data["state"]["counts"] == state["counts"]
    assert [a["name"] for a in data["state"]["agents"]] == [a["name"] for a in state["agents"]]
    assert data["attention"]["count"] == attention["count"]
    assert data["gates"]["verdict"] == gates["verdict"]
    assert [t["request_id"] for t in data["state"]["threads"]] == [t["request_id"] for t in state["threads"]]

    text = _run(tmp_path, capsys)
    assert f"{len(state['agents'])} agents" in text
    assert f"{state['counts']['open_threads']} open conversations" in text
    assert f"{attention['count']} items needing attention" in text
    assert f"release checks: {gates['verdict']}" in text
    for agent in state["agents"]:
        assert agent["name"] in text


def test_json_has_exactly_the_three_builder_payloads(tmp_path: Path, capsys) -> None:
    _store(tmp_path)
    data = json.loads(_run(tmp_path, capsys, "--json"))
    assert set(data) == {"state", "attention", "gates"}
    assert {"counts", "agents", "threads", "label"} <= set(data["state"])
    assert {"items", "count"} <= set(data["attention"])
    assert {"verdict", "gates"} <= set(data["gates"])


# ------------------------------------------------------------------- read-only

def test_it_changes_nothing_and_moves_no_cursor(tmp_path: Path, capsys) -> None:
    s = _store(tmp_path)
    cursors = {a: s.cursor(a) for a in ("lead", "claude-a", "codex-b")}
    before = _files(s.dir)
    _run(tmp_path, capsys)
    _run(tmp_path, capsys, "--json")
    assert _files(s.dir) == before
    assert {a: s.cursor(a) for a in cursors} == cursors


# ----------------------------------------------------------------------- spend

class _Boom:
    def __init__(self, *a, **k):
        raise AssertionError("the spend ledger must not be touched without --enable-budget")


def test_spend_is_off_by_default(tmp_path: Path, capsys, monkeypatch) -> None:
    _store(tmp_path)
    monkeypatch.setattr(budget, "BudgetFeed", _Boom)
    text = _run(tmp_path, capsys)
    assert "SPEND" not in text
    assert "budget" not in json.loads(_run(tmp_path, capsys, "--json"))


def test_spend_appears_only_with_the_flag(tmp_path: Path, capsys, monkeypatch) -> None:
    _store(tmp_path)

    class Fake:
        def get(self):
            return {"status": "ok", "committed_micro_eur": 1_500_000,
                    "trial_cutoff_micro_eur": 10_000_000, "external_ceiling_micro_eur": 12_000_000,
                    "service_hold": False, "unresolved_attempts": 0}

    monkeypatch.setattr(budget, "BudgetFeed", Fake)
    text = _run(tmp_path, capsys, "--enable-budget")
    assert "SPEND" in text and "spent this month: 1.50 EUR" in text
    assert json.loads(_run(tmp_path, capsys, "--json", "--enable-budget"))["budget"]["status"] == "ok"


@pytest.mark.parametrize("status,words", [("not_set_up", "not set up"), ("busy", "busy"),
                                          ("unavailable", "could not be read")])
def test_spend_problems_are_said_in_words_not_shown_as_zero(status: str, words: str) -> None:
    lines = overview._budget_lines({"status": status})
    assert words in " ".join(lines) and "EUR" not in " ".join(lines)


# ---------------------------------------------------------------- rendering only

def test_the_screen_translates_builder_values_and_leaves_missing_fields_out() -> None:
    data = {
        "state": {"label": "proj", "counts": {"open_threads": 1}, "agents": [
            {"name": "a", "role": "lead", "health": {"state": "working_turn", "stale": True},
             "last_seen_age_seconds": 300, "capacity": {"rate_used_pct": 40.0, "context_used_pct": None},
             "usage_limit_park": {"present": True}, "conversation_size": {"warn": True}},
            {"name": "b"},
        ], "threads": [{"request_id": "q-1", "subject": "Fix it", "next_owner": "b", "age_seconds": 7200}]},
        "attention": {"count": 1, "items": [
            {"severity": "high", "title": "Reply owed", "agent": "b", "age_seconds": 120, "age_unknown": False}]},
        "gates": {"verdict": "HOLD", "gates": [{"name": "ci", "blocks": True, "reason": "red"}]},
    }
    text = " ".join(overview.render(data, width=400).split())
    assert "a (lead): working, (that status is old), paused on a usage limit, seen 5 min ago, " \
           "limit used 40%, conversation getting long" in text
    assert "b: status unknown" in text
    assert "memory used" not in text            # a null percentage is left out, not shown as 0
    assert "Fix it: next move is b's, open 2 h" in text
    assert "[high] Reply owed (b), 2 min" in text
    assert "RELEASE CHECKS HOLDING" in text and "ci: red" in text
    assert "1 agent," not in text and "2 agents" in text


def test_a_builder_error_is_said_plainly() -> None:
    data = {"state": {"label": "p", "errors": ["boom"], "agents": [], "threads": []},
            "attention": {"items": []}, "gates": {}}
    assert "Could not read the team: boom" in overview.render(data)


def test_long_lists_are_cut_with_a_pointer() -> None:
    items = [{"severity": "low", "title": f"t{i}", "age_unknown": True} for i in range(9)]
    threads = [{"request_id": f"q-{i}", "age_seconds": 1} for i in range(9)]
    text = overview.render({"state": {"label": "p", "agents": [], "threads": threads},
                            "attention": {"items": items, "count": 9}, "gates": {}})
    assert "... and 4 more (agenttalk attention)" in text
    assert "... and 3 more (agenttalk threads)" in text


def test_the_text_is_plain_ascii_and_fits_the_width() -> None:
    data = {"state": {"label": "café — " + "x" * 300, "agents": [], "threads": []},
            "attention": {"items": []}, "gates": {}}
    text = overview.render(data, width=80)
    assert text.isascii()
    assert max(len(line) for line in text.splitlines()) < 80


def test_the_terminal_text_uses_no_programmer_words_beyond_commands(tmp_path: Path, capsys) -> None:
    _store(tmp_path)
    text = _run(tmp_path, capsys)
    assert not re.search(r"\b(json|schema|epoch|cursor|nonce|hmac)\b", text, re.I)
