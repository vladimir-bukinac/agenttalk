"""Tests use a non-store scratch folder; hand trials use a scratch store."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agenttalk import cli
from agenttalk.store import Store


def test_init_for_tests_uses_a_folder_outside_the_trial_store(tmp_path, capsys):
    fence = os.environ["AGENTTALK_STORE_FENCE"]
    trial = tmp_path / "trial"
    Store(trial).init(["alpha", "beta"])
    nested = trial / "pytest"

    assert cli.main(["init", "--path", str(nested), "--agents", "alpha,beta"]) == 2
    assert "refusing to create a nested store" in capsys.readouterr().err
    assert not (nested / ".agenttalk").exists()

    separate = tmp_path / "pytest"
    assert cli.main(["init", "--path", str(separate), "--agents", "alpha,beta"]) == 0
    assert Store(separate).initialized()
    assert os.environ["AGENTTALK_STORE_FENCE"] == fence
    assert Path(fence) in separate.parents


@pytest.mark.parametrize("relative, advice", [
    ("CONTRIBUTING.md",
     "Run the project's tests in a separate shell without the scratch-store line."),
    ("src/agenttalk/skills/claude/agenttalk.listen.md",
     "Use the scratch-store line only for trying commands; run the project's tests in a separate shell without it, as CONTRIBUTING.md describes."),
    ("src/agenttalk/skills/codex/agenttalk-listen/SKILL.md",
     "Use the scratch-store line only for trying commands; run the project's tests in a separate shell without it, as CONTRIBUTING.md describes."),
    ("docs/ROLES-SKILLS-PROCEDURES.md",
     "Use the scratch-store line only for trying commands; run the project's tests in a separate shell without it, as CONTRIBUTING.md describes."),
    ("src/agenttalk/skills/claude/agenttalk.lead.md",
     "Use the scratch-store line only for trying commands; run the project's tests in a separate shell without it, as CONTRIBUTING.md describes."),
    ("src/agenttalk/skills/codex/agenttalk-lead/SKILL.md",
     "Use the scratch-store line only for trying commands; run the project's tests in a separate shell without it, as CONTRIBUTING.md describes."),
    ("docs/AGENT-MANUAL.md",
     "Use the scratch-store line only for trying commands; run the project's tests in a separate shell without it, as CONTRIBUTING.md describes."),
    ("docs/AGENTTALK-NEW-USER-MANUAL.md",
     "Use the scratch-store line only for trying commands; run the project's tests in a separate shell without it, as CONTRIBUTING.md describes."),
])
def test_test_shell_advice_is_where_contributors_and_seats_learn_the_recipe(relative, advice):
    repo = Path(__file__).resolve().parents[1]
    text = " ".join((repo / relative).read_text(encoding="utf-8").split())
    assert advice in text
