"""How large an agent's current conversation is, and whether that deserves a warning (#475).

Read-only and advisory. Every turn of a long-lived wrapped agent sends its whole
conversation again, so a long conversation makes every turn dearer. This module only
*describes* the size; it never restarts, stops or changes an agent and sends no message.

Two figures, never mixed: the context size the agent's CLI reported on its last turn
(``capacity`` snapshot, ``context_tokens``) where a reading exists, else the number of
turns since the agent's last fresh start (the wrapper session record's ``turns``).

Defaults (``DEFAULT_WARN_TOKENS`` / ``DEFAULT_WARN_TURNS``) and how they were chosen:
  * tokens: Claude reports a 200000-token window (a 1000000-token variant exists) and Codex
    reports 258400 in its rollouts. Auto-compaction starts near the top of the window, so the
    warning sits well below it: 150000 for Claude (75% of 200000) and 190000 for Codex
    (about 74% of 258400).
  * turns: the incident behind #475 was a conversation of 830 turns; healthy desktop
    agents sit at 170 to 230. 300 stays quiet for them and fires long before 830.
They can be changed in ``supervisor.json`` with ``conversation_warn_tokens`` and
``conversation_warn_turns`` (a number for every CLI, or ``{"claude": n, "codex": n}``).
"""
from __future__ import annotations

import json
from pathlib import Path

BASIS_TOKENS = "context_tokens"
BASIS_TURNS = "turns"

DEFAULT_WARN_TOKENS = {"claude": 150_000, "codex": 190_000}
DEFAULT_WARN_TURNS = {"claude": 300, "codex": 300}
_CONFIG_TOKENS_KEY = "conversation_warn_tokens"
_CONFIG_TURNS_KEY = "conversation_warn_turns"
_FALLBACK_CLI = "claude"


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        return None
    return int(value)


def _limit(raw: object, defaults: dict[str, int], cli: str) -> int:
    """Configured limit for ``cli``; any unusable setting falls back to the default."""
    if isinstance(raw, dict):
        value = _positive_int(raw.get(cli))
    else:
        value = _positive_int(raw)
    return value if value is not None else defaults.get(cli, defaults[_FALLBACK_CLI])


def load_settings(store_dir: Path) -> dict:
    """The two warning settings from ``supervisor.json`` (``{}`` when absent or unreadable).

    Reads only the two keys and never raises: a broken file must not hide the status."""
    try:
        data = json.loads(Path(store_dir, "supervisor.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in (_CONFIG_TOKENS_KEY, _CONFIG_TURNS_KEY) if k in data}


def conversation_size(cli: str | None, capacity_snap: dict | None, turns: object,
                      settings: dict | None = None) -> dict | None:
    """``{basis, value, limit, warn, cli}`` or None when neither figure is known.

    ``capacity_snap`` is a ``capacity.current_view`` result (so an expired reading shows
    ``context_tokens`` as None and falls back to turns). ``turns`` may be None/absent."""
    settings = settings or {}
    cli_key = cli if cli in DEFAULT_WARN_TOKENS else _FALLBACK_CLI
    tokens = _positive_int(capacity_snap.get("context_tokens")) if isinstance(capacity_snap, dict) else None
    if tokens is not None:
        limit = _limit(settings.get(_CONFIG_TOKENS_KEY), DEFAULT_WARN_TOKENS, cli_key)
        return {"basis": BASIS_TOKENS, "value": tokens, "limit": limit,
                "warn": tokens > limit, "cli": cli_key}
    count = turns if isinstance(turns, int) and not isinstance(turns, bool) and turns >= 0 else None
    if count is None:
        return None
    limit = _limit(settings.get(_CONFIG_TURNS_KEY), DEFAULT_WARN_TURNS, cli_key)
    return {"basis": BASIS_TURNS, "value": count, "limit": limit,
            "warn": count > limit, "cli": cli_key}


def format_size(size: dict) -> str:
    """One short phrase for a terminal row, saying which figure it is."""
    unit = "tokens of context" if size["basis"] == BASIS_TOKENS else "turns since fresh start"
    text = f"conversation={size['value']:,} {unit}"
    if size["warn"]:
        text += f" WARN(over {size['limit']:,}: every turn re-sends it; consider a fresh start)"
    return text
