"""Exercise the classic refresh loop with deterministic timers and slow requests."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest


POLLED_FETCHERS = (
    "fetchState",
    "fetchAttention",
    "fetchLeadChat",
    "fetchIntents",
    "fetchGates",
    "fetchRiskRegister",
)
_JS_COMMENTS_AND_STRINGS = re.compile(r"""//[^\r\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'""")
_FETCH_CALL = re.compile(r"\b(function\s+)?(" + "|".join(POLLED_FETCHERS) + r")\s*\(")


def _direct_polled_calls(source: str) -> list[str]:
    # Comments and quoted text are not code. Preserve line breaks so nearby tokens stay separate.
    code = _JS_COMMENTS_AND_STRINGS.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), source)
    # Definitions are the only allowed `name(...)` forms. Calls are scheduled by passing
    # the function itself to refreshEndpoint(...) or startEndpointPoll(...).
    return [m.group(2) for m in _FETCH_CALL.finditer(code) if not m.group(1)]


def test_polled_fetchers_are_only_invoked_via_the_scheduler():
    console = Path(__file__).resolve().parents[1] / "src/agenttalk/web_static/console.js"
    assert _direct_polled_calls(console.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("name", POLLED_FETCHERS)
def test_direct_call_scanner_handles_definitions_comments_and_strings(name):
    allowed = (
        f"function {name}() {{}}\n"
        f"refreshEndpoint({name}); startEndpointPoll({name});\n"
        f"// {name}()\n/* {name}() */\n"
        f'const url = "https://example.invalid/{name}()";\n'
    )
    assert _direct_polled_calls(allowed) == []
    assert _direct_polled_calls(allowed + f"{name}();") == [name]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize(
    "scenario",
    [
        "busy",
        "followup",
        "idle",
        "failure",
        "throw",
        "view-lead-chat",
        "view-sessions",
        "view-gates",
        "view-risk-register",
        "outside-gates",
        "outside-risk-register",
        "switch-in-flight",
    ],
)
def test_refresh_scheduler(scenario):
    script = Path(__file__).with_name("console_refresh_poll.test.mjs")
    result = subprocess.run(["node", str(script), scenario], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
