"""#475 part 1: the conversation-size figure and warning (read-only, advisory)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
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
        assert size == {"basis": "turns_total", "value": 300, "limit": 300,
                        "warn": False, "cli": cli_name}
    assert cs.conversation_size(cli_name, None, 301)["warn"] is True


def test_a_real_reading_of_zero_is_a_reading() -> None:
    size = cs.conversation_size("claude", {"context_tokens": 0}, 999)
    assert size["basis"] == "context_tokens" and size["value"] == 0 and size["warn"] is False
    assert cs.conversation_size("claude", None, 0)["value"] == 0  # a known count of zero


def test_readings_must_be_non_negative_whole_numbers() -> None:
    for bad in (-1, 1.5, "7", True, float("nan")):
        assert cs.conversation_size("claude", {"context_tokens": bad}, 5)["basis"] == "turns_total"


def test_a_limit_must_be_a_positive_whole_number() -> None:
    for bad in (0.5, 0, -1, "9", True, float("nan"), float("inf")):
        got = cs.conversation_size("claude", None, 1, {"conversation_warn_turns": bad})
        assert got["limit"] == 300
    assert cs.conversation_size("claude", None, 1, {"conversation_warn_turns": 40.0})["limit"] == 40


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


def test_load_settings_accepts_a_byte_order_mark(tmp_path: Path) -> None:
    (tmp_path / "supervisor.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"conversation_warn_turns": 7,
                                       "agents": {"x": {"cli": "codex"}}}).encode())
    got = cs.load_settings(tmp_path)
    assert got["conversation_warn_turns"] == 7 and got["agent_cli"] == {"x": "codex"}


def test_resolve_cli_prefers_the_supervisor_entry() -> None:
    settings = {"agent_cli": {"helper": "codex"}}
    assert cs.resolve_cli("helper", settings, {"cli": "claude"}, None) == "codex"
    assert cs.resolve_cli("helper", {}, {"cli": "claude"}, None) == "claude"
    assert cs.resolve_cli("helper", {}, {}, {"source": "codex_rollout"}) == "codex"
    assert cs.resolve_cli("codex-x", {}, {}, None) == "codex"
    assert cs.resolve_cli("helper", {}, {}, None) is None


def test_format_says_which_figure_it_is() -> None:
    tok = cs.format_size(cs.conversation_size("claude", {"context_tokens": 200_000}, 1))
    assert "tokens of context" in tok and "WARN" in tok
    turns = cs.format_size(cs.conversation_size("claude", None, 5))
    assert "turns in total" in turns and "WARN" not in turns


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
        "basis": "turns_total", "value": 450, "limit": 300, "warn": True, "cli": "codex"}


def test_status_and_dashboard_agree_for_a_configured_codex_seat(tmp_path: Path) -> None:
    s = Store(tmp_path)
    s.init(["helper"])
    (s.dir / "supervisor.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"agents": {"helper": {"cli": "codex"}}}).encode())
    s.write_capacity("helper", _reading("codex_rollout", 170_000))
    status = cli._gather_status(s)["agents"][0]["conversation_size"]
    dash = web._agent_entries(s, s.load_config(), [], None)[0]["conversation_size"]
    assert status == dash and status["cli"] == "codex" and status["limit"] == 190_000
    assert status["warn"] is False  # 170,000 is under Codex's 190,000 (Claude's would warn)


def test_an_absent_turn_counter_is_unknown_not_zero(tmp_path: Path) -> None:
    s = _store(tmp_path)
    (s.state_dir / "claude-a.wrapper-session.json").write_text("{}", encoding="utf-8")
    assert s.read_wrapper_runtime("claude-a")["turns_known"] is False
    row = next(r for r in cli._gather_status(s)["agents"] if r["name"] == "claude-a")
    assert "conversation_size" not in row
    entries = {e["name"]: e for e in web._agent_entries(s, s.load_config(), [], None)}
    assert "conversation_size" not in entries["claude-a"]
    _session(s, "claude-a", 0)
    row = next(r for r in cli._gather_status(s)["agents"] if r["name"] == "claude-a")
    assert row["conversation_size"]["value"] == 0  # a recorded zero is a count


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
    assert "conversation=50 turns in total WARN(over 40" in out
    assert "a fresh start does not reset it" in out


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
    assert entries["claude-a"]["conversation_size"]["basis"] == "turns_total"
    assert entries["claude-a"]["conversation_size"]["warn"] is True


def test_dashboard_omits_the_field_when_unknown(tmp_path: Path) -> None:
    s = _store(tmp_path)
    entries = web._agent_entries(s, s.load_config(), [], None)
    assert all("conversation_size" not in e for e in entries)


# --------------------------------------------------------- dashboard JavaScript

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_the_dashboard_line_is_pinned_by_a_node_test() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([NODE, str(root / "tests" / "console_conversation_size.test.mjs")],
                            capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr
    passed, total = re.search(r"(\d+)/(\d+) passed", result.stdout.strip().splitlines()[-1]).groups()
    assert passed == total and int(total) > 0


def test_the_dashboard_script_uses_the_tested_helper() -> None:
    """Holds without Node: the card must build its line with the helper the Node test covers."""
    js = (Path(__file__).resolve().parents[1] / "src" / "agenttalk" / "web_static" / "console.js"
          ).read_text(encoding="utf-8")
    assert "function conversationSizeText(" in js
    assert "conversationSizeText(a.conversation_size)" in js
    assert ".tc-cap-warn" in (Path(__file__).resolve().parents[1] / "src" / "agenttalk"
                              / "web_static" / "console.css").read_text(encoding="utf-8")


# ------------------------------------------- a malformed setting must not break anything

@pytest.mark.parametrize("bad", [["codex"], {"x": 1}, 7, None, True])
def test_a_malformed_cli_entry_is_skipped_and_the_rest_still_apply(tmp_path: Path, bad) -> None:
    s = _store(tmp_path)
    s.write_capacity("codex-b", _reading("codex_rollout", 200_000))
    _session(s, "claude-a", 500)
    (s.dir / "supervisor.json").write_text(json.dumps({
        "conversation_warn_turns": 400,
        "agents": {"unrelated": {"cli": bad}, "codex-b": {"cli": "codex"}, "claude-a": {"cli": bad}},
    }), encoding="utf-8")
    assert cs.load_settings(s.dir)["agent_cli"] == {"codex-b": "codex"}
    rows = {r["name"]: r for r in cli._gather_status(s)["agents"]}
    entries = {e["name"]: e for e in web._agent_entries(s, s.load_config(), [], None)}
    for got in (rows, entries):
        assert got["codex-b"]["conversation_size"]["limit"] == 190_000
        assert got["codex-b"]["conversation_size"]["warn"] is True
        # the valid warning setting still applies; the bad entry falls back to the name prefix
        assert got["claude-a"]["conversation_size"] == {
            "basis": "turns_total", "value": 500, "limit": 400, "warn": True, "cli": "claude"}


@pytest.mark.parametrize("bad", [["codex"], {"x": 1}])
def test_a_malformed_health_cli_does_not_crash_the_resolver(bad) -> None:
    assert cs.resolve_cli("codex-x", {}, {"cli": bad}, None) == "codex"
    assert cs.resolve_cli("zzz", {"agent_cli": {"zzz": bad}}, {}, None) is None
