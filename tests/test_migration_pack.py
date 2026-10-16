"""The migration lesson pack and the playbook that goes with it are well formed."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "src" / "agenttalk" / "knowledge_packs" / "migration.jsonl"
PLAYBOOK = REPO / "docs" / "MIGRATION-PLAYBOOK.md"

KEYS = ["key", "scope", "trigger", "body", "applies_to", "evidence", "pack", "pack_version"]
SCOPES = {"test", "review", "process", "craft", "ops", "release", "security", "docs"}
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")  # a bare slug: the loader adds its own prefix
STAGE_TAGS = {"stage-assess", "stage-baseline", "stage-step", "stage-prove", "stage-concurrency-data",
              "stage-packaging-runtime", "stage-review-handover"}
# Four lessons depend on how a payment provider answers: they stay in the pack, not in the guide.
NOT_IN_GUIDE = {"data-same-order-same-moment", "data-claim-before-charge", "data-provider-answer-three-way",
                "data-lock-order-and-neighbours"}
STAGES = ("Assess", "Baseline", "One step at a time", "Prove it", "Concurrency and data",
          "Packaging and runtime", "Review and hand-over")


def _lessons() -> list[dict]:
    return [json.loads(line) for line in PACK.read_text(encoding="utf-8").splitlines()]


def test_every_pack_line_has_exactly_the_agreed_keys() -> None:
    lessons = _lessons()
    assert 60 <= len(lessons) <= 124
    for lesson in lessons:
        assert list(lesson) == KEYS, lesson.get("key")
        assert lesson["pack"] == "migration" and lesson["pack_version"] == 1


def test_keys_are_unique_bare_slugs_with_known_scopes() -> None:
    lessons = _lessons()
    keys = [lesson["key"] for lesson in lessons]
    assert len(keys) == len(set(keys))
    for lesson in lessons:
        assert SLUG.match(lesson["key"]) and len(lesson["key"]) <= 60, lesson["key"]
        assert lesson["scope"] in SCOPES, lesson["key"]
        assert lesson["applies_to"][0] == "migration", lesson["key"]
        assert len(STAGE_TAGS & set(lesson["applies_to"])) == 1, lesson["key"]


def test_bodies_are_short_and_say_why_and_how_to_check() -> None:
    for lesson in _lessons():
        assert len(lesson["body"]) <= 600, lesson["key"]
        assert " Why: " in lesson["body"] and " Check: " in lesson["body"], lesson["key"]
        assert lesson["trigger"].strip() and lesson["evidence"].strip(), lesson["key"]


def test_the_playbook_opens_plainly_and_covers_every_stage() -> None:
    text = PLAYBOOK.read_text(encoding="utf-8")
    opener = text.split("\n", 1)[1].lstrip("\n").split("\n\n", 1)[0]
    assert opener.startswith("**In plain words:**")
    assert 3 <= len(re.findall(r"[.!?](?=\s|$)", opener)) <= 6
    for number, stage in enumerate(STAGES, 1):
        assert f"## {number}. {stage}\n" in text
    assert 250 <= len(text.splitlines()) <= 700


def test_the_guide_has_every_lesson_except_the_four_provider_specific_ones() -> None:
    text = PLAYBOOK.read_text(encoding="utf-8")
    for lesson in _lessons():
        rule = lesson["body"].split(" Why: ")[0]
        assert (rule in text) is (lesson["key"] not in NOT_IN_GUIDE), lesson["key"]
        if lesson["key"] in NOT_IN_GUIDE:
            assert "payments" in lesson["applies_to"], lesson["key"]
