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


HANDOFF = [SKILLS / "claude" / "agenttalk.handoff.md", SKILLS / "codex" / "agenttalk-handoff" / "SKILL.md"]
PROPOSE = [SKILLS / "claude" / "agenttalk.propose.md", SKILLS / "codex" / "agenttalk-propose" / "SKILL.md"]
SENDER_NAMED = [*SEND, *LISTEN, *LEAD, *HANDOFF, *PROPOSE]


@pytest.mark.parametrize("path", SENDER_NAMED, ids=ids(SENDER_NAMED))
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


BATCH2 = [
    SKILLS / "claude" / "agenttalk.challenge.md",
    SKILLS / "claude" / "agenttalk.consult.md",
    SKILLS / "claude" / "agenttalk.propose.md",
    SKILLS / "claude" / "agenttalk.md",
    SKILLS / "devkit" / "review-code" / "SKILL.md",
]
STAMPED = [*SEND, *LISTEN, *LEAD, EVIDENCE, HOLDER, *BATCH2]


@pytest.mark.parametrize("path", STAMPED, ids=ids(STAMPED))
def test_the_files_the_pilot_read_in_full_carry_the_0105_stamp(path: Path) -> None:
    assert re.search(r'^reviewed-against: "0\.105"$', read(path), re.MULTILINE)


@pytest.mark.parametrize("path", HANDOFF, ids=ids(HANDOFF))
def test_the_handoff_skills_do_not_end_the_session_on_a_bare_end(path: Path) -> None:
    text = flat(path)
    assert "the session is over" not in text
    assert "even one from the lead" in text and "carries no authority and is ignored" in text
    assert re.search(r'^reviewed-against: "0\.(43|55|75)"$', read(path), re.MULTILINE)  # not stamped: not re-read yet


def test_the_lead_and_listen_notes_do_not_call_every_inline_body_unsafe() -> None:
    for path in [*LEAD, *LISTEN]:
        text = flat(path)
        assert "has quotes in it" in text, path


# ------------------------------------------------------------------------------ round 2: batch 2 (handoff, propose)


@pytest.mark.parametrize("path", HANDOFF, ids=ids(HANDOFF))
def test_the_handoff_status_example_sees_untracked_files_and_says_why(path: Path) -> None:
    text = flat(path)
    assert "`git status --short --untracked-files=all`" in text
    assert "status.showUntrackedFiles" in text
    assert not re.search(r"<paste `git status --short` ", text)


@pytest.mark.parametrize("path", PROPOSE, ids=ids(PROPOSE))
def test_the_proposal_keeps_the_chosen_decision_maker(path: Path) -> None:
    """The send step must not set the target back to the default peer after step 2 chose one."""
    text = read(path)
    assert re.search(r'TARGET="\$\{TARGET:-|if \(-not \$TARGET\)', text)
    assert not re.search(r'^\s*\$?TARGET\s*=\s*(?:if \(\$env:AGENTTALK_PEER\)|"\$\{AGENTTALK_PEER)', text, re.M)


@pytest.mark.parametrize("path", PROPOSE, ids=ids(PROPOSE))
def test_a_managed_wrapper_turn_sends_the_proposal_with_an_await_and_returns(path: Path) -> None:
    text = flat(path)
    assert "AGENTTALK_WRAPPER_GENERATION" in text
    assert re.search(r"send --from \S+ --to \S+ --kind proposal", text)
    assert "--await-reply" in text and "records no across-turn wait" in text
    assert "There is no `propose --await-reply`" in text
    assert "return immediately to the wrapper" in text
    assert "In a manual (unwrapped) session, wait for the response" in text


@pytest.mark.parametrize("path", PROPOSE, ids=ids(PROPOSE))
def test_the_counter_example_names_the_proposal_it_closes(path: Path) -> None:
    text = flat(path)
    assert re.search(r"reply --from \S+ --to-request <old-request-id> --kind proposal-response", text)
    assert "newest message you received" in text


# ------------------------------------------------------------------------------ round 2: batch 3 (devkit)

DEVKIT = SKILLS / "devkit"


def test_the_close_recipe_names_the_isolation_flags_and_the_hold_code() -> None:
    text = flat(DEVKIT / "system-review-protocol" / "SKILL.md")
    assert "`--lane-artifact <path>`" in text and "`--non-lane-isolation-not-asserted`" in text
    assert (
        text.count("worktree_isolation_unverified") == 2
    )  # at open (what happens without a flag) and in the HOLD list


def test_the_pin_check_compares_after_turning_crlf_into_lf() -> None:
    text = flat(DEVKIT / "definition-of-done" / "SKILL.md")
    assert "after turning any CRLF line endings into LF" in text
    assert "git hash-object --stdin" in text
    assert "On a seat, `git hash-object --no-filters <installed file>` for each file" not in text


def test_the_release_readiness_skill_says_where_secondary_risks_go() -> None:
    text = flat(DEVKIT / "review-release-readiness" / "SKILL.md")
    assert "`risk_class` takes exactly ONE value" in text and "`residual_risk`" in text


def test_routing_names_each_bus_skill_in_both_vendors_forms() -> None:
    text = flat(DEVKIT / "_shared" / "references" / "routing.md")
    assert "agenttalk-lead (Claude: /agenttalk.lead)" in text
    assert "agenttalk-listen (Claude: /agenttalk.listen)" in text
    assert "(Claude: /agenttalk.lead, /agenttalk.listen, /agenttalk.handoff, /agenttalk.send)" in text


def test_system_review_protocol_names_the_handoff_and_lead_skills_in_both_forms() -> None:
    text = flat(DEVKIT / "system-review-protocol" / "SKILL.md")
    assert "use agenttalk-handoff, or /agenttalk.handoff in Claude" in text
    assert "use agenttalk-lead, or /agenttalk.lead in Claude" in text
