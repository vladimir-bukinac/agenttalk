"""The lead's restart checklist and handover note stay aligned."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = [
    ROOT / "src/agenttalk/skills/claude/agenttalk.lead.md",
    ROOT / "src/agenttalk/skills/codex/agenttalk-lead/SKILL.md",
]
LINE = "`Stopped at`: <time or unknown>. `Picture last verified`: <time UTC>. `Still uncertain`: <list>."


def normalized(value):
    return " ".join(value.split())


def test_restart_checklist_and_dated_handover_are_in_both_skills():
    sections = []
    for path in SKILLS:
        text = path.read_text(encoding="utf-8")
        section = normalized(text.split("thread. After a restart,", 1)[1].split("- **Message bodies", 1)[0])
        sections.append(section)
        for phrase in (
            "records written before the restart",
            "never records written since",
            "last handover note",
            "checkpoint time",
            "last sent message",
            "one or two hours before the stop",
            "stop time is unknown",
            "say so",
            "the bus and the code host were last checked in full",
            "newest such time is the last trustworthy checkpoint",
            "one or two hours before the last trustworthy checkpoint",
            "messages you read but did not act on",
            "lead once",
            "keep working while you wait",
            "code host afresh",
            "before acting",
            "merges",
            "review comments",
            "inline comments",
            "test-run results",
            "recheck old holds",
            "evidence, not authority",
            "unchecked gap",
            "hold only decisions that depend on it",
            "short compaction",
            "bounded first pass",
            "re-read the messages you read but did not act on",
            "check the code host since your `Picture last verified` time",
            "skip the other team's ask",
            "hold decisions that depend on an unchecked gap",
            "Write the result in your next handover note's dated line.",
        ):
            assert phrase in section
        assert "wait for the other team's lead before" not in section
        template = normalized(text.split("### Handover note", 1)[1].split("3. **One line", 1)[0])
        assert LINE in template
        assert "Every note" in template and "first note after a restart" in template
    assert sections[0] == sections[1]
    brief = normalized((ROOT / "docs/LEAD-SETUP-BRIEF.md").read_text(encoding="utf-8"))
    assert LINE in brief and "first note after a restart" in brief
    assert "agenttalk.lead" in brief and "restart" in brief
    assert "agenttalk-lead/SKILL.md" in brief
    assert "bus and the code host were last checked in full" in brief
