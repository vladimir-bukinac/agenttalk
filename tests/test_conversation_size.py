"""#475 part 1: the conversation-size figure and warning (read-only, advisory)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttalk import cli, web
from agenttalk import conversation_size as cs
from agenttalk.store import Store


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    s.init(["claude-a", "codex-b"])
    return s


def _reading(source: str, tokens: int | None) -> dict:
    return {
        "schema_version": 1, "observed_at": _now_iso(), "source": source,
        "primary_used_percent": 10.0, "context_tokens": tokens,
        "context_used_percent": None, "confidence": "observed",
    }


def _session(store: Store, agent: str, turns: int) -> None:
    (store.state_dir / f"{agent}.wrapper-session.json").write_text(
        json.dumps({"turns": turns}), encoding="utf-8")


# ----------------------------------------------------------------- pure function

@pytest.mark.parametrize("cli_name,limit", [("claude", 150_000), ("codex", 190_000)])
def test_reading_present_above_and_below_limit(cli_name: str, limit: int) -> None:
    below = cs.conversation_size(cli_name, {"context_tokens": limit}, 9)
    above = cs.conversation_size(cli_name, {"context_tokens": limit + 1}, 9)
    assert below == {"basis": "context_tokens", "value": limit, "limit": limit,
                     "warn": False, "cli": cli_name}
    assert above["warn"] is True and above["basis"] == "context_tokens"


@pytest.mark.parametrize("cli_name", ["claude", "codex"])
def test_reading_absent_falls_back_to_turns(cli_name: str) -> None:
    for snap in (None, {"context_tokens": None}, {}):
        size = cs.conversation_size(cli_name, snap, 300)
        assert size == {"basis": "turns", "value": 300, "limit": 300,
                        "warn": False, "cli": cli_name}
    assert cs.conversation_size(cli_name, None, 301)["warn"] is True


def test_nothing_known_gives_none() -> None:
    assert cs.conversation_size("claude", None, None) is None
    assert cs.conversation_size("claude", None, True) is None
    assert cs.conversation_size("claude", None, -1) is None


def test_settings_override_and_bad_values_fall_back() -> None:
    assert cs.conversation_size("claude", {"context_tokens": 600}, 0,
                                {"conversation_warn_tokens": 500})["warn"] is True
    per_cli = {"conversation_warn_turns": {"codex": 10}}
    assert cs.conversation_size("codex", None, 11, per_cli)["limit"] == 10
    assert cs.conversation_size("claude", None, 11, per_cli)["limit"] == 300
    for bad in (0, -5, "x", True, float("nan"), float("inf"), {"claude": "x"}):
        got = cs.conversation_size("claude", None, 1, {"conversation_warn_turns": bad})
        assert got["limit"] == 300


def test_unknown_cli_uses_claude_defaults() -> None:
    assert cs.conversation_size(None, None, 5)["cli"] == "claude"


def test_load_settings_ignores_missing_and_broken_files(tmp_path: Path) -> None:
    assert cs.load_settings(tmp_path) == {}
    (tmp_path / "supervisor.json").write_text("{not json", encoding="utf-8")
    assert cs.load_settings(tmp_path) == {}
    (tmp_path / "supervisor.json").write_text(
        json.dumps({"conversation_warn_turns": 7, "other": 1}), encoding="utf-8")
    assert cs.load_settings(tmp_path) == {"conversation_warn_turns": 7}


def test_format_says_which_figure_it_is() -> None:
    tok = cs.format_size(cs.conversation_size("claude", {"context_tokens": 200_000}, 1))
    assert "tokens of context" in tok and "WARN" in tok
    turns = cs.format_size(cs.conversation_size("claude", None, 5))
    assert "turns since fresh start" in turns and "WARN" not in turns


# ------------------------------------------------------------------ status --json

def test_status_json_reading_and_turns_fallback(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.write_capacity("claude-a", _reading("claude_statusline", 160_000))
    _session(s, "claude-a", 12)
    _session(s, "codex-b", 450)
    rows = {r["name"]: r for r in cli._gather_status(s)["agents"]}
    assert rows["claude-a"]["conversation_size"]["basis"] == "context_tokens"
    assert rows["claude-a"]["conversation_size"]["warn"] is True
    assert rows["codex-b"]["conversation_size"] == {
        "basis": "turns", "value": 450, "limit": 300, "warn": True, "cli": "codex"}


def test_status_omits_the_field_when_nothing_is_known(tmp_path: Path) -> None:
    rows = cli._gather_status(_store(tmp_path))["agents"]
    assert all("conversation_size" not in r for r in rows)


def test_status_keeps_existing_keys(tmp_path: Path) -> None:
    s = _store(tmp_path)
    before = set(cli._gather_status(s)["agents"][0])
    _session(s, "claude-a", 3)
    after = set(next(r for r in cli._gather_status(s)["agents"] if r["name"] == "claude-a"))
    assert before <= after and after - before == {"conversation_size"}


def test_status_uses_configured_limit_and_prints_a_warning(tmp_path: Path, capsys) -> None:
    s = _store(tmp_path)
    _session(s, "claude-a", 50)
    (s.dir / "supervisor.json").write_text(
        json.dumps({"conversation_warn_turns": 40}), encoding="utf-8")
    row = next(r for r in cli._gather_status(s)["agents"] if r["name"] == "claude-a")
    assert row["conversation_size"]["limit"] == 40 and row["conversation_size"]["warn"]
    cli.main(["--root", str(tmp_path), "status"])
    out = capsys.readouterr().out
    assert "conversation=50 turns since fresh start WARN(over 40" in out


def test_status_changes_nothing_on_disk(tmp_path: Path) -> None:
    s = _store(tmp_path)
    _session(s, "claude-a", 999)
    snapshot = {p: p.read_bytes() for p in s.dir.rglob("*") if p.is_file()}
    cli._gather_status(s)
    assert {p: p.read_bytes() for p in s.dir.rglob("*") if p.is_file()} == snapshot


# --------------------------------------------------------------------- dashboard

def test_dashboard_entry_carries_the_same_fields(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.write_capacity("codex-b", _reading("codex_rollout", 100_000))
    _session(s, "claude-a", 301)
    cfg = s.load_config()
    entries = {e["name"]: e for e in web._agent_entries(s, cfg, [], None)}
    assert entries["codex-b"]["conversation_size"] == {
        "basis": "context_tokens", "value": 100_000, "limit": 190_000,
        "warn": False, "cli": "codex"}
    assert entries["claude-a"]["conversation_size"]["basis"] == "turns"
    assert entries["claude-a"]["conversation_size"]["warn"] is True


def test_dashboard_omits_the_field_when_unknown(tmp_path: Path) -> None:
    s = _store(tmp_path)
    entries = web._agent_entries(s, s.load_config(), [], None)
    assert all("conversation_size" not in e for e in entries)
