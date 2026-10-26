"""The tests that compare fixed dates with the product's idea of "now" must not depend on the real date.

#566 was a console test whose fixed "now" aged out of a 30-day rule. The same pattern sat in the Python
tests (lesson review and expiry dates, the legacy-lessons fixture, a "future" timestamp). Those tests now
take their "now" from a clock they control or derive their dates from the ambient clock. This test proves
it: it runs them in a child pytest with the real clock moved far into the past and far into the future
(``tests/clockshift_plugin.py``) and expects the same result as today.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO_ROOT = TESTS.parent

# (file, -k expression): the learning API tests, the future-onboarding test, the lesson tests that use
# the shared lesson helpers and the legacy-lessons fixture.
SELECTED = [
    ("tests/test_web.py", "test_api_learning or future_onboarding_timestamp"),
    ("tests/test_knowledge.py", "lesson or legacy"),
]


def _seconds_until(year: int) -> int:
    target = datetime(year, 1, 1, tzinfo=timezone.utc)
    return int((target - datetime.now(timezone.utc)).total_seconds())


@pytest.mark.parametrize(
    "label,offset_seconds",
    [("400 days back", -400 * 86400), ("to 2101-01-01", None)],
)
@pytest.mark.parametrize("path,expression", SELECTED, ids=[p.rsplit("/", 1)[-1] for p, _ in SELECTED])
def test_dated_tests_do_not_depend_on_the_real_clock(
    path: str, expression: str, label: str, offset_seconds: int | None, tmp_path: Path
) -> None:
    offset = _seconds_until(2101) if offset_seconds is None else offset_seconds
    env = {
        **os.environ,
        "AGENTTALK_TEST_CLOCK_OFFSET_S": str(offset),
        "PYTHONPATH": os.pathsep.join(filter(None, [str(TESTS), os.environ.get("PYTHONPATH", "")])),
    }
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "clockshift_plugin", "-p", "no:cacheprovider", "-q",
         f"--basetemp={tmp_path / 'child'}", "-k", expression, path],
        capture_output=True, text=True, encoding="utf-8", timeout=600, cwd=REPO_ROOT, env=env,
    )
    assert r.returncode == 0, f"{path} -k {expression!r} with the clock moved {label}:\n{r.stdout}{r.stderr}"
    assert " passed" in r.stdout.splitlines()[-1], r.stdout
