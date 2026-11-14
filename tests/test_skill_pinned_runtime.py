"""Skills run agenttalk through the seat's pinned runtime when there is one (B4-1).

The rule, stated once per skill family: run agenttalk commands with `"$AGENTTALK_PY" -m agenttalk` when
`AGENTTALK_PY` is set (the seat's pinned runtime); otherwise use the form the project's agent manual gives
(`python -m agenttalk` under Codex, `agenttalk` elsewhere).

What this does and does not promise: the skills SAY to use the pinned runtime when there is one. A command form
cannot make an agenttalk any newer, so nothing here claims the same version or protects against an older install.

The lint (`skill_currency`) keeps it that way: a plain `python -m agenttalk` is flagged in a Claude skill, and in a
Codex or devkit skill unless that skill states the rule (it names `AGENTTALK_PY`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agenttalk import __version__
from agenttalk import install_skills as iskl
from agenttalk import skill_currency as sc

ROOT = Path(__file__).resolve().parents[1]
SKILLS = iskl.SKILLS_ROOT
TOKEN = "python -m agenttalk"
DEVKIT_RUNNERS = ["craft-code", "refactor-code", "fix-ci", "assurance-scan"]
FRONT = '---\nname: x\ndescription: d\nreviewed-against: "0.105"\n---\n'


def pinned_findings(tmp_path: Path, kind: str, body: str) -> list[sc.Finding]:
    """The pinned-runtime findings the lint reports for one skill file of the given kind."""
    path = tmp_path / ("x.md" if kind == "claude" else "x/SKILL.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FRONT + body, encoding="utf-8")
    found = sc.check_skill_file(
        path,
        kind=kind,
        inventory=sc.build_command_inventory(),
        current=sc.current_major_minor(__version__),
        require_stamp=False,
    )
    return [f for f in found if f.token == TOKEN]


# ------------------------------------------------------------------------------ the lint, on invented skills


@pytest.mark.parametrize(
    "body",
    [
        "Run `python -m agenttalk lane workspace --id x` first.\n",
        "```bash\npython -m agenttalk lane workspace --id x\n```\n",
        "Run `python -m agenttalk.assurance --root .` first.\n",
    ],
    ids=["inline", "fenced", "assurance-module"],
)
def test_a_plain_python_form_is_flagged_in_a_claude_skill_even_if_it_names_the_variable(tmp_path, body) -> None:
    found = pinned_findings(tmp_path, "claude", body + "Use AGENTTALK_PY when set.\n")
    assert len(found) == 1 and found[0].level == "error" and found[0].line > 0, found


def test_bare_agenttalk_and_the_pinned_form_are_clean_in_a_claude_skill(tmp_path) -> None:
    body = 'Run `agenttalk lane workspace --id x`, or `"$AGENTTALK_PY" -m agenttalk lane workspace --id x`.\n'
    assert pinned_findings(tmp_path, "claude", body) == []


@pytest.mark.parametrize("kind", ["codex", "devkit"])
def test_a_plain_python_form_is_flagged_in_a_codex_or_devkit_skill_that_does_not_state_the_rule(tmp_path, kind) -> None:
    found = pinned_findings(tmp_path, kind, "Run `python -m agenttalk lane workspace --id x` first.\n")
    assert len(found) == 1 and found[0].level == "error" and "AGENTTALK_PY" in found[0].reason, found


@pytest.mark.parametrize("kind", ["codex", "devkit"])
def test_the_same_form_is_clean_when_the_skill_states_the_rule(tmp_path, kind) -> None:
    body = (
        'Run agenttalk with `"$AGENTTALK_PY" -m agenttalk` when `AGENTTALK_PY` is set.\n'
        "Run `python -m agenttalk lane workspace --id x` first.\n"
    )
    assert pinned_findings(tmp_path, kind, body) == []


def test_the_assurance_module_form_needs_the_rule_in_a_devkit_skill_too(tmp_path) -> None:
    body = "Run `python -m agenttalk.assurance --root .` first.\n"
    assert len(pinned_findings(tmp_path, "devkit", body)) == 1
    assert pinned_findings(tmp_path, "devkit", body + "Set AGENTTALK_PY first.\n") == []


def test_the_ignore_comment_silences_one_line(tmp_path) -> None:
    body = "<!-- agenttalk-skill-lint: ignore-line --> `python -m agenttalk x`\n"
    assert pinned_findings(tmp_path, "claude", body) == []
    assert len(pinned_findings(tmp_path, "claude", body + "And `python -m agenttalk y`.\n")) == 1


def test_every_occurrence_in_a_claude_skill_is_reported_with_its_own_line(tmp_path) -> None:
    found = pinned_findings(tmp_path, "claude", "a `python -m agenttalk x`\nb\nc `python -m agenttalk y`\n")
    assert [f.line for f in found] == [len(FRONT.splitlines()) + 1, len(FRONT.splitlines()) + 3]


# ------------------------------------------------------------------------------ the real skills


def test_the_bundled_skills_have_no_pinned_runtime_finding() -> None:
    found = [f for f in sc.check_bundled_skills(SKILLS, __version__) if f.token == TOKEN]
    assert found == [], "; ".join(f"{f.file}:{f.line} {f.reason}" for f in found)


def test_the_claude_lead_lines_use_the_files_own_bare_form() -> None:
    text = (SKILLS / "claude" / "agenttalk.lead.md").read_text(encoding="utf-8")
    assert TOKEN not in text
    assert "`agenttalk lane assign ...`" in text and "`agenttalk lane workspace --id <id>`" in text


@pytest.mark.parametrize("skill", DEVKIT_RUNNERS)
def test_each_devkit_skill_that_runs_agenttalk_states_the_rule_once(skill) -> None:
    text = " ".join((SKILLS / "devkit" / skill / "SKILL.md").read_text(encoding="utf-8").split())
    assert text.count('"$AGENTTALK_PY" -m agenttalk') == 1, text
    assert "when `agenttalk_py` is set" in text.lower() and "otherwise" in text
    if skill != "assurance-scan":
        assert "`python -m agenttalk` under Codex, `agenttalk` elsewhere" in text


# ------------------------------------------------------------------------------ install-skills sync


def test_installed_copies_carry_the_rule_and_match_the_bundled_files(tmp_path) -> None:
    cl_bus, cx_bus, cl_dev, cx_dev = (tmp_path / n for n in ("clb", "cxb", "cld", "cxd"))
    result = iskl.install(
        claude_dir=cl_bus, codex_dir=cx_bus, devkit=True, claude_skills_dir=cl_dev, codex_skills_dir=cx_dev
    )
    assert not result.counts().get("skipped")
    for skill in DEVKIT_RUNNERS:
        bundled = (SKILLS / "devkit" / skill / "SKILL.md").read_bytes()
        for installed in (cl_dev / skill / "SKILL.md", cx_dev / skill / "SKILL.md"):
            assert installed.read_bytes() == bundled
            assert b"AGENTTALK_PY" in bundled
    assert (cl_bus / "agenttalk.lead.md").read_bytes() == (SKILLS / "claude" / "agenttalk.lead.md").read_bytes()
    for copy in [
        *cl_bus.glob("*.md"),
        *cl_dev.glob("*/SKILL.md"),
        *cx_dev.glob("*/SKILL.md"),
        *cx_bus.glob("*/SKILL.md"),
    ]:
        text = copy.read_text(encoding="utf-8")
        if copy.parent == cl_bus:
            assert TOKEN not in text, copy
        elif TOKEN in text:
            assert "AGENTTALK_PY" in text, copy
    again = iskl.install(
        claude_dir=cl_bus, codex_dir=cx_bus, devkit=True, claude_skills_dir=cl_dev, codex_skills_dir=cx_dev
    )
    assert again.counts().get("unchanged") and not again.counts().get("copied")


# ------------------------------------------------------------------------------ honest wording


def test_the_changelog_entry_says_only_what_the_change_does() -> None:
    changelog = " ".join((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split())
    unreleased = changelog[changelog.index("## [Unreleased]") : changelog.index("## [0.105.0]")]
    match = re.search(r"pinned runtime", unreleased)
    assert match and "when there is one" in unreleased[max(0, match.start() - 200) : match.end() + 200]
    for promise in ("same version", "never an older install", "prevents older client", "never an older client"):
        assert promise not in unreleased.lower(), promise
