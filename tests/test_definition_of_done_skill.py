"""The definition-of-done skill keeps its promises in step with the files it points at.

- the frontmatter, the dispatch table and the canonical evidence profiles agree (the record goes in the
  existing profile of the task's kind, never in a second production record);
- the pinning text promises only what a repository convention can give (a git tree id, nothing installed);
- the next owner keeps both the lens and the seat, and the independent read is not a precondition of the
  builder's done;
- the shared evidence rules are part of the pin, and the replay evidence is linked, not a local path;
- the risk rule exempts review and investigation completion from creating another review;
- the replay's ledger recomputes the totals the report states.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from agenttalk import install_skills as iskl
from agenttalk import skill_currency as sc

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = iskl.SKILLS_ROOT / "devkit" / "definition-of-done"
SKILL = SKILL_DIR / "SKILL.md"
EVIDENCE = iskl.SKILLS_ROOT / "devkit" / "_shared" / "references" / "evidence.md"
LEDGER = ROOT / "docs" / "research" / "DOD-REPLAY-2026-10-ledger.csv"
REPORT = ROOT / "docs" / "research" / "DOD-REPLAY-2026-10.md"

EXPECTED_PROFILES = {"production-handoff", "review-result", "qa-result", "planning-artifact"}
KIND_TO_PROFILE = {
    "documentation": "production-handoff", "bug-fix": "production-handoff", "refactor": "production-handoff",
    "ci-fix": "production-handoff", "feature": "production-handoff",
    "project-or-release": "production-handoff", "migration-slice": "production-handoff",
    "migration": "production-handoff", "review-only": "review-result", "qa-test": "qa-result",
    "investigation": "planning-artifact",
}


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    m = re.search(r"^## %s.*?$(.*?)(?=^## |\Z)" % re.escape(heading), text, re.S | re.M)
    assert m, heading
    return m.group(1)


def test_frontmatter_lists_the_four_profiles_the_task_kinds_dispatch_to() -> None:
    text = _text()
    block = re.search(r"evidence-profile:\n((?:  - .*\n)+)", text).group(1)
    listed = set(re.findall(r"  - (\S+)", block))
    assert listed == EXPECTED_PROFILES, listed
    canonical = sc.parse_evidence_profiles(EVIDENCE.read_text(encoding="utf-8"))
    assert EXPECTED_PROFILES <= set(canonical)


def test_every_task_kind_is_dispatched_to_one_existing_profile() -> None:
    section = _section(_text(), "WHERE THE RECORD GOES")
    rows = [ln for ln in section.splitlines() if ln.startswith("| `")]
    seen: dict[str, str] = {}
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        kinds = re.findall(r"`([a-z-]+)`", cells[0])
        profile = re.findall(r"`([a-z-]+)`", cells[1])
        assert len(profile) == 1, ln
        for kind in kinds:
            assert kind not in seen, "kind %s dispatched twice" % kind
            seen[kind] = profile[0]
    assert seen == KIND_TO_PROFILE
    # the profiles table of the skill names exactly these kinds
    profiles_table = _section(_text(), "Profiles")
    in_table = set(re.findall(r"^\| `([a-z-]+)` \|", profiles_table, re.M))
    assert in_table == set(KIND_TO_PROFILE)


def test_the_non_primary_profiles_list_their_canonical_required_fields() -> None:
    canonical = sc.parse_evidence_profiles(EVIDENCE.read_text(encoding="utf-8"))
    section = _section(_text(), "WHERE THE RECORD GOES")
    for profile in ("review-result", "qa-result", "planning-artifact"):
        for name in canonical[profile]:
            assert "`%s`" % name in section, "%s: field %s missing from the dispatch text" % (profile, name)
    # the mapping table uses only fields that exist in the profile of its row
    for ln in section.splitlines():
        if not ln.startswith("| `"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        profile = re.findall(r"`([a-z-]+)`", cells[1])[0]
        for cell in cells[2:]:
            for field in re.findall(r"`([a-z_]+)`", cell):
                alias = profile == "planning-artifact" and field == "proposal"       # "decision or proposal"
                assert field in canonical[profile] or alias, "%s is not a %s field" % (field, profile)


def test_no_second_production_record_is_appended() -> None:
    text = _text()
    assert "Never append a separate production record" in text
    assert text.count("## Evidence") == 1


def test_pinning_promises_only_a_repository_convention() -> None:
    text = _section(_text(), "PINNING")
    for needle in ("tree <id> evidence <blob>", "_shared/references/evidence.md",
                   "git rev-parse <tag>:src/agenttalk/skills/devkit/_shared/references/evidence.md",
                   "git rev-parse <tag>:src/agenttalk/skills/devkit/definition-of-done",
                   "git ls-tree -r <id>", "git hash-object --no-filters", "does not do",
                   "policy text not verified", "Never fall back silently", "overlay: <repository> <path> blob <id>"):
        assert needle in text, needle
    # the claim the read objected to must be gone
    assert "gives every vendor's seat the same text" not in _text()
    assert "Every vendor's seat gets it" not in _text()


def test_a_kind_the_table_does_not_list_still_gets_a_base_record() -> None:
    text = " ".join(_section(_text(), "WHERE THE RECORD GOES").split())
    assert "A task kind this table does not list" in text
    assert "Never leave the handoff without a done record" in text


def test_the_next_owner_keeps_the_seat_and_the_lens() -> None:
    text = " ".join(_section(_text(), "WHERE THE RECORD GOES").split())
    assert "next-owner: <seat> - <action>" in text
    assert "write each lens as `<lens>: <seat>`" in text
    rows = [ln for ln in _section(_text(), "WHERE THE RECORD GOES").splitlines() if ln.startswith("| `")]
    assert rows and all("`next-owner` entry in `evidence`" in ln for ln in rows), "every dispatch row names the seat"


def test_the_independent_read_is_not_a_precondition_of_the_builders_done() -> None:
    text = " ".join(_text().split())
    migration = " ".join((SKILL_DIR / "references" / "migration.md").read_text(encoding="utf-8").split())
    assert "A different seat reviewed it" not in text
    assert "It is not a precondition of the builder's `done`" in text
    assert "build closes first, then the lead creates the" in migration
    assert "docs/ROLES-SKILLS-PROCEDURES.md" in text


def test_the_migration_profile_carries_the_newest_source_rules() -> None:
    migration = " ".join((SKILL_DIR / "references" / "migration.md").read_text(encoding="utf-8").split())
    assert "must exercise the changed component" in migration and "stubs the component" in migration
    assert "probed for everything it can now answer" in migration and "write the expected answer" in migration
    assert "against the vendor's own advisory page" in migration and "never released" in migration


def test_the_replay_evidence_is_linked_not_a_local_path() -> None:
    technical = _section(_text(), "Technical detail")
    assert "https://github.com/zoolok17/agenttalk/blob/master/docs/research/DOD-REPLAY-2026-10.md" in technical
    assert "https://github.com/zoolok17/agenttalk/blob/master/docs/research/DOD-REPLAY-2026-10-ledger.csv" in technical
    stripped = re.sub(r"https://\S+", "", _text())
    assert "docs/research/" not in stripped, "a local path would not exist in an installed skill"


def test_the_overlay_has_an_identity_and_the_round_limits_live_there() -> None:
    overlay = " ".join((SKILL_DIR / "references" / "project-overlay.md").read_text(encoding="utf-8").split())
    migration = " ".join((SKILL_DIR / "references" / "migration.md").read_text(encoding="utf-8").split())
    assert "Identity of an overlay" in overlay and "blob id" in overlay
    assert "how many review rounds a slice gets" in overlay
    assert "After one fix round and one final read" not in migration
    assert "fixed" in migration and "shown not to block the agreed scope" in migration
    assert "authorised scope or risk decision" in migration
    assert "does not finish a finding that still breaks the agreed scope" in migration


def test_the_risk_rule_never_creates_a_review_of_a_review() -> None:
    text = _text()
    assert "never creates a review of a review" in text
    assert "creates no further review obligation" in text
    assert "security review that finishes with FIX" in text


def test_a_procedure_rehearsal_is_a_literal_row_of_the_documentation_and_migration_profiles() -> None:
    text = " ".join(_text().split())
    migration = " ".join((SKILL_DIR / "references" / "migration.md").read_text(encoding="utf-8").split())
    assert "was followed in order, from its stated starting state" in text
    assert "followed in order, from their stated starting state" in migration


# ------------------------------------------------------------------------------------------------ the ledger
def _ledger() -> list[dict]:
    with LEDGER.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_the_ledger_has_one_valid_entry_per_counted_finding_and_recomputes_the_report() -> None:
    rows = _ledger()
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    assert all(r["classification"] in {"unambiguous", "judgement", "not-caught"} for r in rows)
    assert all(r["source"] and r["finding"] and r["literal_row"] and r["origin"] for r in rows)
    assert len({r["source"] for r in rows}) == len(rows), "a source reference is used twice"
    total = {c: sum(1 for r in rows if r["classification"] == c) for c in ("unambiguous", "judgement", "not-caught")}
    report = REPORT.read_text(encoding="utf-8")
    m = re.search(r"\|\s*\|\s*\*\*Total\*\*\s*\|\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|"
                  r"\s*\*\*(\d+)\*\*", report)
    assert m, "the report's total row"
    assert (len(rows), total["unambiguous"], total["judgement"], total["not-caught"]) == tuple(
        int(x) for x in m.groups())
    # per job
    by_job: dict[str, list[dict]] = {}
    for r in rows:
        by_job.setdefault(r["job"].split("-")[0], []).append(r)
    for m2 in re.finditer(r"^\| (\d) \| [^|]+\| [^|]+\| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", report, re.M):
        job = by_job[m2.group(1)]
        stated = tuple(int(x) for x in m2.groups()[1:])
        counted = (len(job), *(sum(1 for r in job if r["classification"] == c)
                               for c in ("unambiguous", "judgement", "not-caught")))
        assert stated == counted, (m2.group(1), stated, counted)


def test_the_unambiguous_rows_name_a_literal_row_and_the_not_caught_ones_name_none() -> None:
    for r in _ledger():
        if r["classification"] == "not-caught":
            assert r["literal_row"] == "none" and r["origin"] == "review value"
        else:
            assert r["literal_row"] != "none"
