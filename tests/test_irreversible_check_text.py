"""#448: the check before an irreversible action names --epoch, so a request sent before the
latest epoch barrier stops the agent. A plain `check` looks only for a rescind; the epoch is
compared only with --epoch (cli._epoch_verdict reads the request's own epoch_at_send)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agenttalk.install_skills import SKILLS_ROOT
from agenttalk.wrapper.prompt import assemble_turn_prompt

RECORD = {"kind": "task", "from": "lead", "to": "dev", "body": "do it", "meta": {}, "request_id": "tk-1"}
HEADING = "- **Check before irreversible actions (0.14.0).**"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _paragraph(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(HEADING)
    end = text.index("\n- **", start + 1)
    return _norm(text[start:end])


@pytest.mark.parametrize("reply_shell,command", [
    ("powershell", '& "$env:AGENTTALK_PY" -m agenttalk check --for <you> --to-request <id> --epoch --gates'),
    ("bash", '"$AGENTTALK_PY" -m agenttalk check --for <you> --to-request <id> --epoch --gates'),
])
def test_the_turn_prompt_names_the_full_check_command(reply_shell: str, command: str) -> None:
    text = _norm(assemble_turn_prompt(RECORD, reply_shell=reply_shell))
    assert command in text
    assert "stale (sent before the latest epoch barrier)" in text


PAIRS = [
    ("agenttalk.lead.md", "agenttalk-lead", "check --for $SELF --to-request <RID> --epoch --gates"),
    ("agenttalk.listen.md", "agenttalk-listen", "check --for $SELF --to-request <RID> --epoch"),
    ("agenttalk.handoff.md", "agenttalk-handoff", "check --for $SELF --to-request <RID> --epoch"),
]


@pytest.mark.parametrize("claude_file,codex_dir,check", PAIRS)
def test_each_skill_names_epoch_in_the_irreversible_check(claude_file: str, codex_dir: str, check: str) -> None:
    claude = _paragraph(SKILLS_ROOT / "claude" / claude_file)
    codex = _paragraph(SKILLS_ROOT / "codex" / codex_dir / "SKILL.md")
    assert f"`agenttalk {check}`" in claude
    assert f"`python -m agenttalk {check}`" in codex
    assert "sent before the latest epoch barrier" in claude
    # The two copies say the same thing; only the command spelling differs.
    assert codex.replace("`python -m agenttalk ", "`agenttalk ") == claude
