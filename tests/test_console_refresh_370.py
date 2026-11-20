"""Exercise the classic refresh loop with deterministic timers and slow requests."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("scenario", ["busy", "followup", "idle", "failure", "throw", "view-lead-chat",
                                      "view-sessions", "view-gates", "view-risk-register"])
def test_refresh_scheduler(scenario):
    script = Path(__file__).with_name("console_refresh_poll.test.mjs")
    result = subprocess.run(["node", str(script), scenario], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
