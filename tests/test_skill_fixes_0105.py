"""The bundled skills after the 0.105.0 skills review (batch 1): each fixed piece of advice stays fixed.

The pilot read the send, listen and lead skills (both assistants), the shared devkit holder and the
evidence reference against the real commands. What it found and what these tests keep from coming back:

* a message body with non-ASCII text must go through `--file <path>`; piping it into `--file -` is read in the
  Windows code page and stored garbled (the README says the same);
* the roster check is not proof of who sent a message; an unmarked `end` does not end the loop;
* the lead's "is the worktree clean?" check must see new files (`--untracked-files=all`) and quote the path (#93);
* reply examples name the sender; longer bodies go in a file; `na_reason` is a bus requirement.

The tests read the shipped files as text; they need no network and no store.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src" / "agenttalk" / "skills"
README = ROOT / "README.md"

SEND = [SKILLS / "claude" / "agenttalk.send.md", SKILLS / "codex" / "agenttalk-send" / "SKILL.md"]
LISTEN = [SKILLS / "claude" / "agenttalk.listen.md", SKILLS / "codex" / "agenttalk-listen" / "SKILL.md"]
LEAD = [SKILLS / "claude" / "agenttalk.lead.md", SKILLS / "codex" / "agenttalk-lead" / "SKILL.md"]
EVIDENCE = SKILLS / "devkit" / "_shared" / "references" / "evidence.md"
HOLDER = SKILLS / "devkit" / "_shared" / "SKILL.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def flat(path: Path) -> str:
    """The text with markdown bold removed and all white space made single spaces."""
    return " ".join(read(path).replace("**", "").split())


def ids(paths: list[Path]) -> list[str]:
    return [f"{p.parent.name}/{p.name}" for p in paths]


# ------------------------------------------------------------------------------ the body goes in a file


@pytest.mark.parametrize("path", [*SEND, *LISTEN, *LEAD, README], ids=ids([*SEND, *LISTEN, *LEAD, README]))
def test_no_text_recommends_piping_a_body_into_file_dash(path: Path) -> None:
    """Every `--file -` is inside a paragraph that tells the reader NOT to pipe a body into it."""
    for paragraph in read(path).replace("**", "").split("\n\n"):
        if "--file -" in paragraph:
            assert re.search(r"\bnot\b[^.]{0,20}\bpipe", paragraph), paragraph


@pytest.mark.parametrize("path", SEND, ids=ids(SEND))
def test_the_send_skills_teach_a_utf8_file_and_say_why(path: Path) -> None:
    text = flat(path)
    assert "UTF-8 text file" in text
    assert re.search(r'--file "?\$BODYFILE"?', text)
    assert "Windows code page" in text and "garbled" in text


def test_the_readme_windows_note_teaches_a_file_not_a_pipe() -> None:
    text = flat(README)
    assert "Write the body to a UTF-8 file and pass `--file <path>`" in text
    assert "pipe a PowerShell here-string" not in text


# ------------------------------------------------------------------------------ what the roster check proves


@pytest.mark.parametrize("path", LISTEN, ids=ids(LISTEN))
def test_the_listen_skills_do_not_call_a_roster_check_authentication(path: Path) -> None:
    text = flat(path)
    assert "explicitly-authenticated" not in text
    assert "and forged sender" not in text
    assert "not proof of who" in text and "unless the store is signed" in text


@pytest.mark.parametrize("path", LISTEN, ids=ids(LISTEN))
def test_the_listen_table_rows_for_end_and_release_name_the_authority_rule(path: Path) -> None:
    rows = {
        line.split("|")[1].strip(): line
        for line in read(path).splitlines()
        if line.startswith("| `end`") or line.startswith("| `release`")
    }
    assert set(rows) == {"`end`", "`release`"}
    for row in rows.values():
        assert "full authority envelope" in row, row
    assert "unmarked `end`" in rows["`end`"] and "ignored" in rows["`end`"]


# ------------------------------------------------------------------------------ the lead's clean-worktree check


@pytest.mark.parametrize("path", LEAD, ids=ids(LEAD))
def test_the_clean_check_sees_new_files_and_quotes_the_worktree_path(path: Path) -> None:
    text = read(path)
    assert "git status --porcelain --untracked-files=all" in text
    assert "status.showUntrackedFiles=no" in text  # the reason, right where the command is
    assert not re.search(r"^\s*git -C .*status --porcelain(?! --untracked-files=all)", text, re.MULTILINE)
    assert "an empty `git status --porcelain --untracked-files=all`" in " ".join(text.split())
    assert "-C <worktree>" not in text
    assert text.count('git -C "<worktree>"') == 3  # status, log and the push alternative


# ------------------------------------------------------------------------------ smaller slips


@pytest.mark.parametrize("path", [*SEND, *LISTEN, *LEAD], ids=ids([*SEND, *LISTEN, *LEAD]))
def test_every_reply_example_names_the_sender(path: Path) -> None:
    assert not re.findall(r"agenttalk reply (?!--from)--to-", read(path))


@pytest.mark.parametrize("path", [*LISTEN, *LEAD], ids=ids([*LISTEN, *LEAD]))
def test_longer_bodies_in_lead_and_listen_examples_use_a_file(path: Path) -> None:
    text = read(path)
    for inline in (
        '-m "<goal, scope',
        '-m "<result>"',
        '-m "<what each recipient should answer>"',
        '-m "<your rationale>"',
        '-m "<proposal body>"',
        '-m "<your critique>"',
    ):
        assert inline not in text, inline


def test_na_reason_is_described_as_a_bus_requirement_with_the_accepted_spellings() -> None:
    text = read(EVIDENCE)
    line = next(line for line in text.splitlines() if line.startswith("- `na_reason`"))
    assert "BUS-VALIDATED" in line
    flat_text = " ".join(text.split())
    assert "`na_reason_<field>`, `na_reason.<field>` or `na_reason`" in flat_text


STAMPED = [*SEND, *LISTEN, *LEAD, EVIDENCE, HOLDER]


@pytest.mark.parametrize("path", STAMPED, ids=ids(STAMPED))
def test_the_eight_files_the_pilot_read_in_full_carry_the_0105_stamp(path: Path) -> None:
    assert re.search(r'^reviewed-against: "0\.105"$', read(path), re.MULTILINE)
