"""Real-browser check of the console v2 stream and B8 work board (the one browser-driving test is
skipped when no Chromium-family browser or node is present; the launch-flags unit test below it
always runs).

The DOM stub in the node tests models detachment and focus, but only a real browser proves that
(F1) a thread scrolled while detached loses its position and (F2) a redraw that replaces a focused
control drops focus to <body>. The page under test is the REAL /v2 shell and scripts, served with
the console CSP by a tiny stdlib server that also answers the four feeds with fixed JSON (30 chat
messages, two needs cards and two board items, all of whose ages grow on every read). The browser
is driven over the DevTools protocol by tests/console2_browser_check.mjs, which also drives the
board: hash-navigating to #board, then proving its keyed cards keep focus and scroll across an
ordinary redraw exactly like the stream's needs-you cards and chat thread do, plus j/k/Escape.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agenttalk import web

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK = REPO_ROOT / "tests" / "console2_browser_check.mjs"
LEAD = "claude-agenttalk-lead"
PROJECT = "proj-browser"

# PR #230 delta review, F2: the subprocess timeout must exceed the check's OWN worst-case elapsed
# time - the SUM of every phase, each already independent/sequential, never nested (the startup
# phase is now itself ONE shared 90s budget, not two 90s budgets composed - see
# console2_browser_check.mjs's STARTUP_BUDGET_MS/makeDeadline):
#   startup (DevTools up AND a page target found - ONE shared budget) ......... 90.0s
#   page load wait (document.readyState "complete", LOAD_BUDGET_MS, #750) ...... 30.0s
#   post-load head start before the first-draw wait (HEAD_START_MS) ............. 3.5s
#   F1 stream redraw wait (waitForTextChange, its own independent 30s budget) . 30.0s
#   F2 stream redraw wait (waitForTextChange) .................................. 30.0s
#   board-cards-render wait loop (100 attempts x 150ms) ......................... 15.0s
#   board meta redraw wait (waitForTextChange) .................................. 30.0s
#   first-draw wait (thread and watched label, FIRST_DRAW_BUDGET_MS, #315) ..... 20.0s
#   misc small fixed sleeps and CDP round-trips (keyboard/overlay steps, etc.) ...  5.0s
#                                                                              ----------
#   worst case, one full scenario ............................................ 253.5s
# 270s leaves ~16s of headroom above that computed worst case. (A second attempt after a
# network-buffer error, see run_check, is a separate subprocess with its own timeout.)
BROWSER_CHECK_TIMEOUT_S = 270

# #315: the one console line a Windows runner prints when it runs out of network buffers after hours of
# tests. It is the machine, not the page, so it alone earns one more try; any other problem never does.
BUFFER_SPACE_PROBLEM = "log: Failed to load resource: net::ERR_NO_BUFFER_SPACE"

# #750: the exit code of console2_browser_check.mjs when the page itself did not load (a script that failed
# or never answered, or a page that did not finish loading in time). Its stdout is then one JSON object,
# {"loadFailure": <why>, "problems": [<the page's own errors>]}, never the measurements. Pinned against the
# script's own value by test_the_checks_default_limits_and_load_failure_exit_code_are_pinned.
LOAD_FAILURE_EXIT_CODE = 17


def _only_buffer_space_problems(problems: list[str]) -> bool:
    return bool(problems) and all(problem == BUFFER_SPACE_PROBLEM for problem in problems)


def _load_failure(result) -> dict:
    """What a check that exited with LOAD_FAILURE_EXIT_CODE printed: {"loadFailure": ..., "problems": [...]}."""
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise AssertionError(
            f"the check exited with the load-failure code but printed no data: {result.stdout!r} {result.stderr}"
        ) from None


def _ended_on_buffer_space_alone(result) -> bool:
    """The attempt ended with the network-buffer line as its ONLY problem: it ran to the end with that as its
    only console problem (#315), or the page failed to load with nothing but that line (#750). Anything else
    - another error, a mix, no error at all, or any other failure of the check - is final."""
    if result.returncode == 0:
        return _only_buffer_space_problems(json.loads(result.stdout).get("problems") or [])
    if result.returncode == LOAD_FAILURE_EXIT_CODE:
        return _only_buffer_space_problems(_load_failure(result).get("problems") or [])
    return False


def run_check(url: str, profile: Path, flags: list[str], *, browser: str | None = None,
              run=subprocess.run, extra_args: tuple[str, ...] = (), behaviour=None, before_retry=None):
    """Run console2_browser_check.mjs and return the finished process (the last attempt's).

    If an attempt ends on the network-buffer line alone (see _ended_on_buffer_space_alone) it runs ONCE more,
    in a fresh browser process (a new random debugging port) with a fresh profile folder, and says so in the
    test output. A second such attempt is returned as it is, so the test fails as before. A check that
    exits with any other error, a "label not found" after the page loaded, any other page problem: never
    retried, the first result is the result.

    The retry forgives only the machine's network error, never a page that misbehaved. So before the
    retry is granted after a finished run, `behaviour` (the test's own assertions on every other
    measurement) runs on the FIRST result: if it fails, that failure is the result and a clean second run
    cannot erase it.

    The second attempt must start from the same state as the first. `before_retry` (the page fixture's
    `restart_clock`) runs just before it, so the fixture's cards, which age at 60x real time from the
    first request, do not carry the time the first attempt took into the second.
    """
    browser = browser or BROWSER
    result = None
    for attempt in (1, 2):
        attempt_profile = profile if attempt == 1 else profile.with_name(profile.name + "-retry")
        result = run(
            ["node", str(CHECK), browser, url, str(attempt_profile), json.dumps(flags), *extra_args],
            capture_output=True, text=True, encoding="utf-8", timeout=BROWSER_CHECK_TIMEOUT_S, cwd=REPO_ROOT,
        )
        if attempt == 1 and _ended_on_buffer_space_alone(result):
            if behaviour is not None and result.returncode == 0:
                behaviour(json.loads(result.stdout))  # the first run's other measurements must already pass
            print("console2 browser check: the runner ran out of network buffers "
                  f"({BUFFER_SPACE_PROBLEM!r}); retrying once with a fresh profile and port (#315)")
            if before_retry is not None:
                before_retry()
            continue
        break
    return result


def run_browser_check(url: str, profile: Path, flags: list[str], **kwargs) -> dict:
    """run_check, then the measurements it printed. A check that did not finish is a hard FAILURE, never a
    skip: a browser binary that exists but fails to start (result.stderr carries the launched process's own
    stderr on that path, see the .mjs), or a page that failed to load (its own errors are in the message)."""
    result = run_check(url, profile, flags, **kwargs)
    if result.returncode == LOAD_FAILURE_EXIT_CODE:
        load = _load_failure(result)
        raise AssertionError(f"the page failed to load: {load.get('loadFailure')}; "
                             f"the page's own errors: {load.get('problems')}")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _find_browser() -> str | None:
    env = os.environ.get("AGENTTALK_TEST_BROWSER")
    if env and Path(env).is_file():
        return env
    for name in ("msedge", "chrome", "chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    for path in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ):
        if Path(path).is_file():
            return path
    return None


def _browser_launch_flags(system: str) -> list[str]:
    """The Chromium-family launch flags for `system` (a `platform.system()`-shaped string:
    "Linux", "Darwin" or "Windows" - never queried internally, so every branch is exercisable
    from any host, including this one, where CI's linux/macos legs cannot actually be run).

    Fix for PR #214: this check was written and only ever exercised against Edge on Windows;
    on a linux CI runner (typically containerized, often effectively root, with a small
    /dev/shm) the SAME flags the Windows leg used let the browser process fail to start at
    all, with no sandbox or shared-memory workaround. macOS needs neither: it is not
    containerized and Chrome's normal sandbox works there in CI the same as anywhere else.

    Fix for PR #221 (N4 follow-up): a headless target with no real OS window can still
    "occlude" itself and drift `document.hidden`/`visibilityState` back to backgrounded mid-run
    (observed even after an explicit `/json/activate` - console2_browser_check.mjs re-asserts it
    before the board section for exactly this reason), which stalls the board's OWN F6 hidden-tab
    pause indefinitely. These two flags are Chromium's own documented switches for headless/CI
    testing to disable that occlusion-based throttling at the source.
    """
    common = [
        "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
    ]
    if system == "Linux":
        return common + ["--no-sandbox", "--disable-dev-shm-usage"]
    return common


def test_browser_launch_flags_are_correct_per_platform() -> None:
    """Pure-function unit test: runs unconditionally (no browser or node required), and so is
    the one part of this fix actually verified locally - the real launch on linux/macos CI is
    not (see the module docstring)."""
    linux = _browser_launch_flags("Linux")
    assert "--no-sandbox" in linux and "--disable-dev-shm-usage" in linux
    assert "--headless=new" in linux and "--disable-gpu" in linux
    assert "--disable-backgrounding-occluded-windows" in linux and "--disable-renderer-backgrounding" in linux
    for other_system in ("Darwin", "Windows"):
        flags = _browser_launch_flags(other_system)
        assert "--no-sandbox" not in flags and "--disable-dev-shm-usage" not in flags
        assert "--headless=new" in flags and "--disable-gpu" in flags
        assert "--disable-backgrounding-occluded-windows" in flags and "--disable-renderer-backgrounding" in flags


BROWSER = _find_browser()


def _iso(when: datetime) -> str:
    return when.isoformat().replace("+00:00", "Z")


def _state(now: datetime, grown: int = 0) -> dict:
    def agent(name: str, state: str, since_s: int) -> dict:
        return {
            "name": name, "cli": name.split("-")[0], "last_seen": _iso(now - timedelta(seconds=3)),
            "last_seen_age_seconds": 3,
            "health": {"state": state, "since": _iso(now - timedelta(seconds=since_s)), "updated_at": _iso(now),
                       "last_progress_at": None, "age_seconds": 1, "stale": False, "reason_code": "x", "warnings": []},
        }
    return {"schema_version": 1, "generated_at": _iso(now), "roots": [{
        "label": "browser", "path": "x", "project_id": PROJECT, "errors": [], "operator_facing": LEAD,
        # the second agent's age is inflated by "grown" (like /api/attention below) so the roster's
        # own rendered text really does change on every poll, exercising the rail render path -
        # not merely relying on it being skipped because nothing in the view changed at all.
        "agents": [agent(LEAD, "idle_waiting", 3000),
                   agent("claude-agenttalk-developer-2", "idle_waiting", 2000 + grown)],
        "recent": [{"id": "1", "ts": _iso(now - timedelta(seconds=5)), "from": LEAD, "to": "operator",
                    "kind": "message", "subject": "s"}],
    }]}


def _handler(monotonic=time.monotonic, api_delay_s: float = 0.0, inject_js: str = "", *,
             script_delay_s: float = 0.0, script_status: int | None = None, script_hangs: bool = False):
    # PR #230 delta review, F1: aging used to start at HANDLER-CONSTRUCTION time (before Chromium
    # even launches), so a longer (but healthy) browser startup - #229's own fix allows up to 90s -
    # directly ate into the fixture's own 3600s (1h) granularity budget: the reviewer reproduced
    # this exactly by backdating `started` by 65s and getting "waiting 1h" on the very first read.
    # Aging is decoupled from startup duration by starting the clock lazily, on the FIRST request
    # this server actually receives (the earliest a page could possibly be exercising it) rather
    # than at construction time - real startup time, however long, is no longer charged against it.
    # `monotonic` is injectable (round 2, N2) so the real-browser fixture uses real time.monotonic
    # while the F1 regression test below can drive it with fixed readings instead of a real sleep.
    clock = {"started": None, "api_release": None}
    release_hung_requests = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # noqa: D401 - silence the test server
            return

        @staticmethod
        def restart_clock() -> None:
            """Start the aging (and the slow-data release) over, as for a brand-new attempt: the next
            request this server answers is its first again (see the note above on F1)."""
            clock["started"] = None
            clock["api_release"] = None

        @staticmethod
        def release() -> None:
            """Let any request held by `script_hangs` go, so the server can shut down."""
            release_hung_requests.set()

        def _send(self, body: bytes, ctype: str, csp: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Security-Policy", csp)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if clock["started"] is None:
                clock["started"] = monotonic()
            path = self.path.split("?", 1)[0]
            if api_delay_s and path.startswith("/api/"):
                # A slow runner: every data request waits until one moment, measured from the first of them,
                # so the page's first draw comes late. The cards age from that moment, not from the wait.
                if clock["api_release"] is None:
                    clock["api_release"] = monotonic() + api_delay_s
                time.sleep(max(0.0, clock["api_release"] - monotonic()))
            if path.endswith("/console2.js"):
                # #750: the page's own script (where the test-only fault is injected) arrives late, answers
                # with an error, or never answers - what a slow or failing runner network does to it.
                if script_hangs:
                    release_hung_requests.wait(timeout=300)
                    return
                time.sleep(script_delay_s)
                if script_status is not None:
                    self.send_error(script_status)
                    return
            now = datetime.now(timezone.utc)
            aging_from = clock["api_release"] if clock["api_release"] is not None else clock["started"]
            grown = int(max(0.0, monotonic() - aging_from) * 60)  # cards age 60 s per second: a new label every read
            if path == "/v2":
                self._send(web.render_console2(), "text/html; charset=utf-8", web._DASHBOARD_CSP)
            elif path.startswith("/static/") and path[len("/static/"):] in web._STATIC_ASSETS:
                ctype, data = web._STATIC_ASSETS[path[len("/static/"):]]
                if inject_js and path.endswith("/console2.js"):
                    data = data + b";" + inject_js.encode()  # a test-only fault, appended to the page's own script
                self._send(data, ctype, web._DEFAULT_CSP)
            elif path == "/api/state":
                self._send(json.dumps(_state(now, grown)).encode(), "application/json", web._DEFAULT_CSP)
            elif path == "/api/attention":
                # Both cards now start near zero (not ~1000s+, as before): a card's rendered age
                # label crosses from "Nm" to hour ("Nh") granularity at 3600 simulated seconds,
                # which this fixture's own 60x-accelerated `grown` reaches from a near-zero base
                # about a real MINUTE after `clock["started"]` is set (F1: the FIRST request this
                # server actually answers, not construction time - a slow browser startup, however
                # long, is never charged against this margin) - comfortably longer than this
                # check's own total run time on any realistic runner, however slow. From ~1000s+,
                # that margin was only ~40 real seconds, which is exactly what a real CI runner
                # exceeded (fix). card-2 is kept SLIGHTLY older (oldest-first queue order, "card-2
                # then card-1" - unchanged) so it is still the SURVIVING card once the M4b/R2/R3
                # key-path steps below defer the other one away; console2_browser_check.mjs
                # watches THIS card specifically, by its own stable data-c2-card key, never "the
                # first .c2-age" (which is what a real CI runner's queue/render order handed it,
                # non-deterministically, before this fix).
                items = [
                    {"id": "card-1", "source": "escalation", "source_label": "ESCALATION", "severity": "high",
                     "title": "Question 1", "agent": None, "detail": "why it matters",
                     "age_seconds": grown, "human_can_unblock_now": True},
                    {"id": "card-2", "source": "escalation", "source_label": "ESCALATION", "severity": "high",
                     "title": "Question 2", "agent": None, "detail": "why it matters",
                     "age_seconds": 50 + grown, "human_can_unblock_now": True},
                ]
                self._send(json.dumps({"target_root_project_id": PROJECT, "items": items}).encode(),
                           "application/json", web._DEFAULT_CSP)
            elif path == "/api/work-board":
                # B8: two real-envelope-shaped board items. board-a's last_work_event_at recedes by
                # the SAME accelerated `grown` counter as /api/attention above, so its rendered
                # "active ... ago" meta text changes on every ordinary redraw - the console2_browser_
                # check.mjs board section watches it the same way F1/F2 watch WATCHED_AGE_SELECTOR.
                items = [
                    {"work_item": "board-a", "title": None, "cycle": 1, "round": None, "legacy_cycle": False,
                     "candidate": None,
                     "obligations": [{"request_id": "rq-a1", "recipient": "claude-agenttalk-developer-2",
                                      "stage": "build", "state": "outstanding", "verdict": None}],
                     "verdicts": {}, "integration": {}, "workflow_column": "building", "reason": "build accepted",
                     "evidence": ["rq-a1"], "checks": None, "issues": [],
                     "first_dispatch_at": _iso(now - timedelta(seconds=1800)),
                     "last_work_event_at": _iso(now - timedelta(seconds=30 + grown))},
                    {"work_item": "board-b", "title": "Second item", "cycle": 2, "round": 1,
                     "legacy_cycle": False, "candidate": "a" * 40,
                     "obligations": [{"request_id": "rq-b1", "recipient": "codex-agenttalk-reviewer-1",
                                      "stage": "read", "state": "done", "verdict": "GO"}],
                     "verdicts": {"a" * 40: [{"reviewer": "codex-agenttalk-reviewer-1", "verdict": "GO",
                                              "reply": "rp-b1", "independent": True, "vendor": "openai"}]},
                     "integration": {}, "workflow_column": "ready",
                     "reason": "reviewed; independent GO; local checks not tracked",
                     "evidence": ["rq-b1"], "checks": "local checks not tracked", "issues": [],
                     "first_dispatch_at": _iso(now - timedelta(seconds=3600)),
                     "last_work_event_at": _iso(now - timedelta(seconds=10))},
                ]
                # Padding cards so the list genuinely overflows #c2-board's viewport - the scroll
                # check below is meaningless if two short cards never need a scrollbar at all.
                items += [
                    {"work_item": f"board-pad-{n}", "title": None, "cycle": 1, "round": None,
                     "legacy_cycle": False, "candidate": None,
                     "obligations": [{"request_id": f"rq-pad-{n}", "recipient": "claude-agenttalk-developer-2",
                                      "stage": "build", "state": "outstanding", "verdict": None}],
                     "verdicts": {}, "integration": {}, "workflow_column": "queued", "reason": "start unconfirmed",
                     "evidence": [f"rq-pad-{n}"], "checks": None, "issues": [],
                     "first_dispatch_at": _iso(now - timedelta(seconds=600)),
                     "last_work_event_at": _iso(now - timedelta(seconds=600))}
                    for n in range(12)
                ]
                payload = {
                    "schema_version": 1, "target_root_project_id": PROJECT, "generated_at": _iso(now),
                    "coverage": {"status": "complete"}, "items": items,
                    "legacy": {"open_request_count": 0, "known_lower_bound": 0}, "unassigned": {"count": 0},
                    "total_count": len(items), "truncated": False, "omitted_count": 0, "errors": [],
                    "window_days": 7,
                }
                self._send(json.dumps(payload).encode(), "application/json", web._DEFAULT_CSP)
            elif path == "/api/lead-chat":
                msgs = [{"id": f"m{n:03d}", "from": "operator" if n % 3 == 0 else LEAD, "to": LEAD,
                         "body": f"Message number {n} " + "x" * 60, "ts": _iso(now - timedelta(minutes=60 - n))}
                        for n in range(30)]
                self._send(json.dumps({"target_root_project_id": PROJECT, "available": True, "operator": "operator",
                                       "lead": LEAD, "messages": msgs}).encode(), "application/json", web._DEFAULT_CSP)
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self.send_error(404)
    return Handler


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class _Page(tuple):
    """(url, profile), which also knows how to restart the fixture's aging clock for a retry."""

    def __new__(cls, url: str, profile: Path, restart_clock):
        page = super().__new__(cls, (url, profile))
        page.restart_clock = restart_clock
        return page


@pytest.fixture
def page(tmp_path: Path):
    handler = _handler()
    srv = _serve(handler)
    try:
        yield _Page(f"http://127.0.0.1:{srv.server_address[1]}/v2", tmp_path / "profile", handler.restart_clock)
    finally:
        srv.shutdown()
        srv.server_close()


# One page query for the watched card raises a TypeError, once - what a real page exception during the
# check's first-draw wait looks like to the check.
_ONE_SHOT_QUERY_ERROR = (
    "(function () { var q = document.querySelector.bind(document), n = 0;"
    " document.querySelector = function (s) {"
    " if (String(s).indexOf('card-2') >= 0 && n++ === 0) { throw new TypeError('injected query failure'); }"
    " return q(s); }; })();"
)


@pytest.fixture
def one_shot_query_error_page(tmp_path: Path):
    srv = _serve(_handler(inject_js=_ONE_SHOT_QUERY_ERROR))
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v2", tmp_path / "profile"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def serve_page(tmp_path: Path):
    """`serve_page(**options)` starts the fixture page with the given `_handler` options and returns
    (url, profile); every server it started is shut down, and any held request released, afterwards."""
    started = []

    def start(**options):
        handler = _handler(**options)
        srv = _serve(handler)
        started.append((srv, handler))
        return f"http://127.0.0.1:{srv.server_address[1]}/v2", tmp_path / "profile"

    try:
        yield start
    finally:
        for srv, handler in started:
            handler.release()
            srv.shutdown()
            srv.server_close()


@pytest.fixture
def slow_first_draw_page(tmp_path: Path):
    """The same page, but its data arrives 6 seconds late, longer than the check's fixed settle sleep."""
    srv = _serve(_handler(api_delay_s=6.0))
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v2", tmp_path / "profile"
    finally:
        srv.shutdown()
        srv.server_close()


def test_fixture_aging_starts_on_first_request_not_construction() -> None:
    """PR #230 delta review, F1 regression, made deterministic in round 2 (N2): a real (but short)
    gap between constructing the fixture and its FIRST request (standing in for however long a real
    browser takes to start) must never be charged against the fixture's own aging clock. Before the
    F1 fix, `_handler(started)` took `time.monotonic()` as a constructor argument - a slow start was
    indistinguishable from genuine card age.

    Round 1 exercised this with a real 2s sleep and a loose `first_grown < 10` bound - which was
    itself load-sensitive (N2): do_GET reads the injected clock TWICE on the first request (once to
    lazily set clock["started"], once to compute `grown`), and under real time.monotonic those two
    reads can legitimately drift apart by more than 167ms of scheduler jitter alone, at this
    fixture's 60x acceleration - a correctly-lazy first request descheduled for 200ms between those
    two reads reports grown=12 and fails outright, adding a load-sensitive flake to a flake fix.

    Injecting a controllable `monotonic` callable removes both the real sleep AND the wall-clock
    bound: the TEST advances the clock explicitly (standing in for however long a real gap is,
    without waiting for one), so the exact epoch semantics can be asserted precisely instead of
    merely bounded. A plain canned reading sequence cannot express this: since nothing calls
    monotonic() during the "gap" itself, a sequential fake would hand the same next value to
    "started" whether the code reads it eagerly at construction or lazily at the first request -
    the two are only distinguishable if the clock can advance independently of being read."""

    class FakeMonotonic:
        def __init__(self, value: float) -> None:
            self.value = value

        def __call__(self) -> float:
            return self.value

    fake = FakeMonotonic(100.0)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(monotonic=fake))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        # The exact 65s the reviewer used to reproduce the original bug ("backdating `started` by
        # 65s ... 'waiting 1h' on the very first read") - a healthy but slow browser startup gap,
        # advanced directly with no real sleep and no other code ever reading the clock meanwhile.
        fake.value += 65.0
        with urllib.request.urlopen(f"{base}/api/attention", timeout=5) as resp:  # noqa: S310  # nosec B310  # nosemgrep
            first = json.loads(resp.read())
        # card-2's age is "50 + grown" (see the /api/attention branch below). Lazy (correct): started
        # is set to 165.0 AT this first read, so grown=(165.0-165.0)*60=0 EXACTLY. Eager (the F1 bug):
        # started would have been captured as 100.0 at construction, so grown=(165.0-100.0)*60=3900 -
        # unmistakably not 0.
        assert first["items"][1]["age_seconds"] - 50 == 0
        fake.value += 1.0   # a whole second - exact in binary float, no int()-truncation surprises
        with urllib.request.urlopen(f"{base}/api/attention", timeout=5) as resp:  # noqa: S310  # nosec B310  # nosemgrep
            second = json.loads(resp.read())
        # grown=(166.0-165.0)*60=60 EXACTLY - ages forward from the FIRST request's start, not from
        # construction, and is not re-latched on every request.
        assert second["items"][1]["age_seconds"] - 50 == 60
    finally:
        srv.shutdown()
        srv.server_close()


def _assert_measurements(out: dict) -> None:
    """Every measurement of the real-browser check except its console problems (see the test below)."""
    # F1: the thread is scrolled to its end on the first draw (it has 30 messages: it must overflow)
    initial = out["initial"]
    assert initial["connected"] and initial["height"] > initial["client"]
    assert abs(initial["top"] - (initial["height"] - initial["client"])) <= 1, initial
    # F1: scrolled up to 250, ordinary redraws (ages moved) leave it there, on the same element
    assert out["threadKept"] is True
    assert out["afterRedraw"]["top"] == 250, out["afterRedraw"]
    # F2: the focused Later button is still focused, and is the very same element, after redraws
    assert out["ageMoved"] is True, "the redraws really happened"
    assert out["focusAfter"]["tag"] == "BUTTON" and out["focusAfter"]["same"] is True, out["focusAfter"]
    assert out["focusAfter"]["key"].endswith("|later"), out["focusAfter"]
    # F2: deferring the focused card moves focus to another control in the stream, never to <body>
    after_later = out["focusAfterLater"]
    assert after_later["tag"] == "BUTTON" and after_later["inStream"] is True, after_later
    # F2: the rail is reconciled in place too - the avatar <img> survives an ordinary redraw
    assert out["railImageKept"] is True, out
    # M4b/R2: one key path (run first, focus still untouched from page load) - j selects the first
    # card (A), Enter focuses its first action (Later)
    assert out["firstCardSelectedAfterJ"] is True, out
    after_enter = out["focusAfterEnterOnSelected"]
    assert after_enter["tag"] == "BUTTON" and after_enter["sameAsFirstCardLater"] is True, after_enter
    # R3: a second j must move real focus WITH the selection, onto card B itself - never left behind
    # on card A's Later
    assert out["secondJMovedFocusToCardB"] is True, out
    # R2/R3: Enter opens B (the actually-highlighted card, an interactive control - its Later button);
    # a second native Enter must defer B specifically, never A, never diverted back to the selection
    assert out["focusAfterEnterOnB"]["tag"] == "BUTTON", out
    assert out["cardsAfterSecondEnter"] == 1, out
    assert out["remainingCardIsA"] is True, out
    # R2: a native Enter on a focused, unrelated interactive control (a theme button), with a card
    # still selected, must activate THAT control - never get diverted to the selection shortcut
    assert out["themeButtonKeptNativeEnter"] is True, out
    # R4: closing help restores focus to wherever it was invoked from - here, a focused Later button -
    # never a blanket default to the ? button
    assert out["r4FocusInOverlay"] is True, out
    assert out["r4FocusRestoredToInvoker"] is True, out
    assert out["r4InvokerStillConnected"] is True, out
    # M4b: the ? button opens the keyboard overlay, moves focus into it
    assert out["overlayOpenAfterClick"] is True, out
    assert out["focusInOverlayAfterClick"] is True, out
    # R1: native Tab and Shift+Tab are trapped on the overlay's one focusable control, never escaping
    # to the page beneath (the "Classic view" link); the background is genuinely `inert` while open
    assert out["focusAfterNativeTab"] is True, out
    assert out["focusAfterNativeShiftTab"] is True, out
    assert out["backgroundInertWhileOpen"] is True, out
    # R1: a native Enter on the (correctly still-focused) Close button closes the dialog and never
    # reaches the link outside it - the page never navigates away, and the background un-inerts
    assert out["overlayClosedAfterNativeEnterOnClose"] is True, out
    assert out["pathUnchangedAfterNativeEnter"] is True, out
    assert out["backgroundInertRemovedAfterClose"] is True, out
    # a native Escape still closes the overlay too, and returns focus to the button that opened it
    assert out["overlayClosedAfterNativeEscape"] is True, out
    assert out["focusBackOnKeysBtnAfterEscape"] is True, out
    # B8: the board - hash-navigating to #board swaps the stream/rail out for the board/detail pair
    assert out["boardShellSwapped"] is True, out
    # j selects the first card with REAL focus and the selected class together
    assert out["boardFirstSelectedWithFocus"] is True, out
    # a second j moves focus WITH the selection onto the next card, never left behind
    assert out["boardSecondJMovedFocus"] is True, out
    # the detail panel shows the selection (not the "select a card" placeholder) once one exists
    assert out["boardDetailShowsSelection"] is True, out
    # scrolling the board, then an ordinary redraw (the watched card's own age ticked) - the
    # container, the selected card and its focus all survive, exactly like the stream's thread/rail
    assert out["boardScrollKept"] is True, out
    assert out["boardContainerKept"] is True, out
    assert out["boardFocusKept"] is True, out
    # Escape clears the board selection
    assert out["boardSelectionClearedByEscape"] is True, out
    # F4: native Enter and Space (real CDP key events, not synthetic DOM ones) activate whichever
    # board card actually holds focus - a role="button" article gets none of this for free
    assert out["boardEnterActivatesFocusedCard"] is True, out
    assert out["boardSpaceActivatesFocusedCard"] is True, out
    # N2 (PR #221 delta round 2): the board's own Enter/Space handler must consume a key ONLY when
    # it actually handled a board card - a focused Conversation link or help button, both real
    # server-rendered/page-built controls unrelated to any card, keep their own native activation
    assert out["n2ConversationLinkNavigatesOnEnter"] is True, out
    assert out["n2HelpButtonStillOpensOnEnter"] is True, out


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser on this runner")
@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_thread_scroll_and_focus_survive_redraws_in_a_real_browser(page) -> None:
    url, profile = page
    out = run_browser_check(url, profile, _browser_launch_flags(platform.system()), behaviour=_assert_measurements,
                            before_retry=page.restart_clock)
    _assert_measurements(out)
    # the page raised no exception and the console CSP blocked nothing
    assert out["problems"] == [], out["problems"]


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser on this runner")
@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_check_catches_a_redraw_that_breaks_scroll_after_setup(page) -> None:
    """Negative control for dev-4 finding F1: console2_browser_check.mjs's own "scroll" sabotage
    mode installs a MutationObserver that snaps the thread back to its bottom on every age
    redraw. If the scroll-setup (capturing the thread, writing scrollTop=250) and the age
    baseline it waits against were ever split back into two separate CDP round-trips, a redraw
    landing BETWEEN them would satisfy waitForAgeChange on evidence of the WRONG redraw - one
    that happened BEFORE our own scrollTop=250 write - and this sabotage would go completely
    undetected (afterRedraw.top would still read 250, the value WE just wrote, not yet touched
    by the sabotage's own reaction to a LATER redraw). With setup and baseline atomic, the
    sabotage is reliably caught: this must fail (afterRedraw.top != 250), never pass.
    """
    url, profile = page
    flags = _browser_launch_flags(platform.system())
    result = subprocess.run(
        ["node", str(CHECK), BROWSER, url, str(profile), json.dumps(flags), "scroll"],
        capture_output=True, text=True, encoding="utf-8", timeout=BROWSER_CHECK_TIMEOUT_S, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["ageMoved"] is True, "the redraws really happened"
    assert out["afterRedraw"]["top"] != 250, (
        "the sabotage should have snapped scrollTop away from 250 on the redraw that followed "
        "setup - if this is 250, the atomic setup+baseline fix has regressed and a redraw "
        "landing before setup is being mistaken for one that happened after it"
    )


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser on this runner")
@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_check_waits_for_a_late_first_draw_instead_of_failing_on_a_missing_label(slow_first_draw_page) -> None:
    """#315, second symptom ("watched age label not found" on a loaded Windows runner): the check used to
    sleep a fixed 3.5 s after loading the page and then look for the watched label ONCE. On a runner whose
    first draw took longer, that one look found nothing and the test failed on a race, not on a real fault.
    The data here arrives 6 s late: the check must wait for the draw (bounded) and then pass."""
    url, profile = slow_first_draw_page
    flags = _browser_launch_flags(platform.system())
    result = subprocess.run(
        ["node", str(CHECK), BROWSER, url, str(profile), json.dumps(flags)],
        capture_output=True, text=True, encoding="utf-8", timeout=BROWSER_CHECK_TIMEOUT_S, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["initial"]["connected"] is True
    assert out["watchedLabelInitialText"], out
    assert out["problems"] == [], out["problems"]  # no console error and no page exception while it waited



# --- #315: the buffer-space retry, proved with a stand-in for the node check (no browser needed) ----

class _Exit:
    """A check that ended with this exit code, standard output and standard error."""

    def __init__(self, code: int, stdout: str = "", stderr: str = "the check broke") -> None:
        self.code, self.stdout, self.stderr = code, stdout, stderr


def _load_failed(problems: list[str], why: str = "the page did not finish loading (stand-in)") -> _Exit:
    """A check that stopped because the page did not load, as the real one reports it (#750)."""
    return _Exit(LOAD_FAILURE_EXIT_CODE, json.dumps({"loadFailure": why, "problems": problems}), why)


def _standin(*answers):
    """A stand-in for subprocess.run that returns the given check results one after another, and
    records every command line it was given."""
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        answer = answers[len(calls) - 1]
        if isinstance(answer, _Exit):
            return subprocess.CompletedProcess(command, answer.code, stdout=answer.stdout, stderr=answer.stderr)
        if isinstance(answer, int):  # a check that exits with an error
            return subprocess.CompletedProcess(command, answer, stdout="", stderr="the check broke")
        measured = answer if isinstance(answer, dict) else {"problems": answer}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(measured), stderr="")

    return run, calls


def _check_with(*answers, tmp_path: Path, behaviour=None):
    run, calls = _standin(*answers)
    out = run_browser_check("http://x/v2", tmp_path / "profile", ["--f"], browser="browser", run=run,
                            behaviour=behaviour)
    return out, calls


def test_one_buffer_space_error_is_retried_once_in_a_fresh_profile_and_then_passes(tmp_path, capsys) -> None:
    out, calls = _check_with([BUFFER_SPACE_PROBLEM], [], tmp_path=tmp_path)
    assert out["problems"] == [] and len(calls) == 2
    assert calls[0][4] != calls[1][4] and calls[1][4].endswith("profile-retry")  # a fresh profile folder
    printed = capsys.readouterr().out
    assert "retrying once" in printed and "ERR_NO_BUFFER_SPACE" in printed  # said in the test output


def test_a_second_buffer_space_error_is_not_retried_again_and_so_fails_the_test(tmp_path) -> None:
    out, calls = _check_with([BUFFER_SPACE_PROBLEM], [BUFFER_SPACE_PROBLEM, BUFFER_SPACE_PROBLEM],
                             tmp_path=tmp_path)
    assert len(calls) == 2  # exactly one retry
    assert out["problems"] == [BUFFER_SPACE_PROBLEM, BUFFER_SPACE_PROBLEM]  # the test's own check then fails


@pytest.mark.parametrize("problems", [
    ["log: Failed to load resource: net::ERR_CONNECTION_REFUSED"],
    ['exception: "Uncaught TypeError"'],
    [BUFFER_SPACE_PROBLEM, "log: Refused to load the script because it violates the Content Security Policy"],
    ["log: Failed to load resource: net::ERR_NO_BUFFER_SPACE_2"],
], ids=["other network error", "page exception", "mixed with a real error", "a similar but different line"])
def test_any_other_console_problem_fails_at_once_without_a_retry(problems, tmp_path, capsys) -> None:
    out, calls = _check_with(problems, [], tmp_path=tmp_path)
    assert len(calls) == 1 and out["problems"] == problems
    assert "retrying" not in capsys.readouterr().out


def test_a_check_that_exits_with_an_error_is_never_retried(tmp_path) -> None:
    run, calls = _standin(1)
    with pytest.raises(AssertionError, match="the check broke"):
        run_browser_check("http://x/v2", tmp_path / "profile", [], browser="browser", run=run)
    assert len(calls) == 1


def test_a_clean_first_run_runs_the_check_once(tmp_path) -> None:
    out, calls = _check_with([], tmp_path=tmp_path)
    assert out["problems"] == [] and len(calls) == 1


def _page_behaves(out: dict) -> None:
    """A small stand-in for _assert_measurements: the page kept its scroll position."""
    assert out["threadKept"] is True and out["afterRedraw"]["top"] == 250, out


def test_a_buffer_error_does_not_excuse_a_page_that_misbehaved_in_the_same_run(tmp_path, capsys) -> None:
    """The retry forgives the machine's network error, never broken page behaviour. The first run has the
    buffer line AND a lost scroll position; a clean second run must not wipe that out."""
    broken_first = {"problems": [BUFFER_SPACE_PROBLEM], "threadKept": False, "afterRedraw": {"top": 999}}
    clean_second = {"problems": [], "threadKept": True, "afterRedraw": {"top": 250}}
    with pytest.raises(AssertionError):
        _check_with(broken_first, clean_second, tmp_path=tmp_path, behaviour=_page_behaves)
    assert "retrying" not in capsys.readouterr().out


def test_a_buffer_error_with_otherwise_good_measurements_is_still_retried(tmp_path) -> None:
    good_first = {"problems": [BUFFER_SPACE_PROBLEM], "threadKept": True, "afterRedraw": {"top": 250}}
    clean_second = {"problems": [], "threadKept": True, "afterRedraw": {"top": 250}}
    out, calls = _check_with(good_first, clean_second, tmp_path=tmp_path, behaviour=_page_behaves)
    assert out["problems"] == [] and len(calls) == 2


# --- #750: the same one retry for a page that failed to LOAD on the network-buffer line alone ------------

def test_a_load_failure_with_only_the_buffer_space_error_is_retried_once_and_then_passes(tmp_path, capsys) -> None:
    out, calls = _check_with(_load_failed([BUFFER_SPACE_PROBLEM]), [], tmp_path=tmp_path)
    assert out["problems"] == [] and len(calls) == 2
    assert calls[1][4].endswith("profile-retry")  # a fresh profile folder (and the check picks a fresh port)
    printed = capsys.readouterr().out
    assert "retrying once" in printed and "ERR_NO_BUFFER_SPACE" in printed  # said in the test output


def test_a_second_load_failure_is_not_retried_again_and_fails_with_its_cause(tmp_path) -> None:
    run, calls = _standin(_load_failed([BUFFER_SPACE_PROBLEM]), _load_failed([BUFFER_SPACE_PROBLEM], "again"))
    with pytest.raises(AssertionError, match="the page failed to load: again"):
        run_browser_check("http://x/v2", tmp_path / "profile", [], browser="browser", run=run)
    assert len(calls) == 2  # exactly one retry


_HTTP_500 = "log: Failed to load resource: the server responded with a status of 500 (Internal Server Error)"


@pytest.mark.parametrize("problems", [
    [_HTTP_500],
    ["log: Failed to load resource: net::ERR_CONNECTION_REFUSED"],
    [BUFFER_SPACE_PROBLEM, _HTTP_500],
    ["log: Failed to load resource: net::ERR_NO_BUFFER_SPACE_2"],
    [],
], ids=["a 500 answer", "other network error", "mixed with a real error", "a similar but different line",
        "no error at all (a plain time-out)"])
def test_any_other_load_failure_fails_at_once_without_a_retry(problems, tmp_path, capsys) -> None:
    run, calls = _standin(_load_failed(problems), [])
    with pytest.raises(AssertionError, match="the page failed to load"):
        run_browser_check("http://x/v2", tmp_path / "profile", [], browser="browser", run=run)
    assert len(calls) == 1
    assert "retrying" not in capsys.readouterr().out


def test_a_label_not_found_after_the_page_loaded_is_never_retried_even_with_the_buffer_line_in_it(tmp_path) -> None:
    """After the page loaded, a missing label means the page's error may have been hidden: that is a real
    failure, whatever the page reported meanwhile (the check prints it in the message, not as load data)."""
    missing = _Exit(1, stderr=f"watched age label not found ...; the page reported: {BUFFER_SPACE_PROBLEM}")
    run, calls = _standin(missing, [])
    with pytest.raises(AssertionError, match="watched age label not found"):
        run_browser_check("http://x/v2", tmp_path / "profile", [], browser="browser", run=run)
    assert len(calls) == 1


def test_the_retry_is_one_per_check_across_both_kinds_of_buffer_error(tmp_path) -> None:
    """A finished run with the buffer line and a failed load with it share ONE retry, in either order."""
    out, calls = _check_with(_load_failed([BUFFER_SPACE_PROBLEM]), [BUFFER_SPACE_PROBLEM], tmp_path=tmp_path)
    assert len(calls) == 2 and out["problems"] == [BUFFER_SPACE_PROBLEM]  # not a third attempt
    run, calls = _standin([BUFFER_SPACE_PROBLEM], _load_failed([BUFFER_SPACE_PROBLEM]))
    with pytest.raises(AssertionError, match="the page failed to load"):
        run_browser_check("http://x/v2", tmp_path / "profile", [], browser="browser", run=run)
    assert len(calls) == 2


def test_a_load_failure_does_not_run_the_behaviour_assertions_and_still_gets_its_retry(tmp_path) -> None:
    """There are no measurements to assert on after a failed load; the retry must not trip over that."""
    clean = {"problems": [], "threadKept": True, "afterRedraw": {"top": 250}}
    out, calls = _check_with(_load_failed([BUFFER_SPACE_PROBLEM]), clean, tmp_path=tmp_path, behaviour=_page_behaves)
    assert len(calls) == 2 and out["threadKept"] is True


def test_the_injected_error_check_gets_the_same_one_retry_and_nothing_more(tmp_path, capsys) -> None:
    """run_check, which the injected-error test uses, retries a buffer-only load failure once and hands back
    the second attempt as it is - here the page's reported injected error, which then passes that test."""
    injected = _Exit(1, stderr="TypeError: injected query failure")
    run, calls = _standin(_load_failed([BUFFER_SPACE_PROBLEM]), injected)
    result = run_check("http://x/v2", tmp_path / "profile", [], browser="browser", run=run)
    assert len(calls) == 2 and "injected query failure" in result.stderr
    assert "retrying once" in capsys.readouterr().out
    # a different load failure is final, with its own data for the test to show
    run, calls = _standin(_load_failed(["log: Failed to load resource: net::ERR_CONNECTION_REFUSED"]), injected)
    result = run_check("http://x/v2", tmp_path / "profile", [], browser="browser", run=run)
    assert len(calls) == 1 and result.returncode == LOAD_FAILURE_EXIT_CODE


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser on this runner")
@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_check_does_not_hide_a_page_exception_raised_while_it_waits_for_the_first_draw(
        one_shot_query_error_page) -> None:
    """The first-draw wait retries a label that is not there yet, and nothing else. A query that raises in
    the page (here one injected TypeError, once) must fail the check with its cause, not be retried until a
    later good query hides it."""
    url, profile = one_shot_query_error_page
    # Same one-time retry as the main test (#750): a runner's network-buffer error that stops the page loading
    # is not this test's fault to find; any other outcome of the first attempt is final.
    result = run_check(url, profile, _browser_launch_flags(platform.system()))
    assert result.returncode != LOAD_FAILURE_EXIT_CODE, f"the page failed to load: {result.stdout} {result.stderr}"
    assert result.returncode != 0, "the injected page exception was swallowed"
    assert "injected query failure" in result.stderr, result.stderr
    assert "watched age label not found" not in result.stderr, result.stderr  # not replaced by the absent-label message


# --- #750: the check waits for the page to LOAD before its first-draw clock starts ---------------------

def _with_limits(**limits_ms: int) -> tuple[str, str]:
    """The check's own optional arguments after the launch flags: no sabotage, then limits in milliseconds
    (loadMs, headStartMs, firstDrawMs; any left out keeps its default). Test-only: it lets a test that waits
    for a late or missing script finish in seconds instead of the real 25-50."""
    return "", json.dumps(limits_ms)


# What the check's own constants must be (console2_browser_check.mjs), asked of the script itself.
_CHECK_DEFAULTS = {
    "loadMs": 30000, "headStartMs": 3500, "firstDrawMs": 20000, "startupMs": 90000, "loadFailureExitCode": 17,
}
_ASK_THE_CHECK = """
const m = await import(process.argv[1]);
const d = m.resolveLimits(undefined);
let bad = null;
try { m.resolveLimits('{"loadMs": "x"}'); } catch (e) { bad = String(e.message); }
console.log(JSON.stringify({
  loadMs: d.loadMs, headStartMs: d.headStartMs, firstDrawMs: d.firstDrawMs, startupMs: m.STARTUP_BUDGET_MS,
  loadFailureExitCode: m.LOAD_FAILURE_EXIT_CODE, partial: m.resolveLimits('{"loadMs": 5}'), bad,
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_the_checks_default_limits_and_load_failure_exit_code_are_pinned() -> None:
    """#750: the new page-load limit has a stated default (30 s), pinned here with the existing first-draw
    (20 s) and startup (90 s) limits, the 3.5 s head start and the exit code this file reads. With no limits
    argument the check uses exactly these; the argument is for tests that shrink them."""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _ASK_THE_CHECK, CHECK.as_uri()],
        capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    asked = json.loads(result.stdout)
    assert {key: asked[key] for key in _CHECK_DEFAULTS} == _CHECK_DEFAULTS, asked
    assert asked["loadFailureExitCode"] == LOAD_FAILURE_EXIT_CODE
    # a limit that is given changes only itself; the others keep their defaults
    assert asked["partial"] == {"loadMs": 5, "headStartMs": 3500, "firstDrawMs": 20000}, asked["partial"]
    assert "loadMs" in asked["bad"], asked["bad"]  # a limit that is not a number is refused, never ignored


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser on this runner")
@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_a_late_page_script_does_not_use_up_the_first_draw_wait(serve_page) -> None:
    """#750, the cause: the 20 s first-draw wait started while the page's own script was still loading, so a
    late script left the page without the test-only fault, nothing threw, and the wait ended in "label not
    found". Here the script is 1 s late and the first-draw wait (and the head start) are shrunk far below
    that: the check must still wait for the load first, and so report the injected error."""
    url, profile = serve_page(inject_js=_ONE_SHOT_QUERY_ERROR, script_delay_s=1.0)
    result = run_check(url, profile, _browser_launch_flags(platform.system()),
                       extra_args=_with_limits(headStartMs=0, firstDrawMs=500))
    assert result.returncode not in (0, LOAD_FAILURE_EXIT_CODE), (result.returncode, result.stdout, result.stderr)
    assert "injected query failure" in result.stderr, result.stderr
    assert "watched age label not found" not in result.stderr, result.stderr


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser on this runner")
@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_a_page_script_that_never_answers_fails_within_the_load_limit_and_says_so(serve_page) -> None:
    """#750: the load wait has its own limit. The script request never answers, the limit is shrunk to 3 s:
    the check must stop with the load-failure code and a message about the LOAD, not about a missing label."""
    url, profile = serve_page(script_hangs=True)
    result = run_check(url, profile, _browser_launch_flags(platform.system()),
                       extra_args=_with_limits(loadMs=3000, headStartMs=0, firstDrawMs=500))
    assert result.returncode == LOAD_FAILURE_EXIT_CODE, (result.returncode, result.stdout, result.stderr)
    load = _load_failure(result)
    assert "did not finish loading within 3s" in load["loadFailure"], load
    assert "label not found" not in load["loadFailure"] + result.stderr


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser on this runner")
@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_a_page_script_that_fails_to_load_is_reported_as_a_load_failure_not_a_missing_label(serve_page) -> None:
    """#750: a script that answers 500 still ends the page load ("complete"), so a check that only waits for
    that would go on to a 20 s "label not found". The page's own error must stop it at once: the load-failure
    code, the page's error as data and in the message, and never the label message."""
    url, profile = serve_page(inject_js=_ONE_SHOT_QUERY_ERROR, script_status=500)
    result = run_check(url, profile, _browser_launch_flags(platform.system()),
                       extra_args=_with_limits(headStartMs=0, firstDrawMs=500))
    assert result.returncode == LOAD_FAILURE_EXIT_CODE, (result.returncode, result.stdout, result.stderr)
    load = _load_failure(result)
    assert any("Failed to load resource" in problem for problem in load["problems"]), load
    assert "Failed to load resource" in load["loadFailure"] and "page failed to load" in load["loadFailure"], load
    assert "label not found" not in load["loadFailure"] + result.stderr


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser on this runner")
@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_a_first_draw_failure_says_when_the_clock_started_and_that_the_page_reported_no_errors(serve_page) -> None:
    """#750: every failure of the first-draw wait names the page's own errors, or says there were none, and
    its message says the wait began after the page finished loading (which is now true)."""
    url, profile = serve_page(api_delay_s=30.0)  # the data never comes in time: the label is never drawn
    result = run_check(url, profile, _browser_launch_flags(platform.system()),
                       extra_args=_with_limits(headStartMs=0, firstDrawMs=1500))
    assert result.returncode not in (0, LOAD_FAILURE_EXIT_CODE), (result.returncode, result.stdout, result.stderr)
    assert "watched age label not found" in result.stderr, result.stderr
    assert "after the page finished loading" in result.stderr, result.stderr
    assert "the page reported no errors" in result.stderr, result.stderr


@pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser on this runner")
@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this runner")
def test_a_page_error_during_the_first_draw_wait_is_printed_when_the_wait_gives_up(serve_page) -> None:
    """#750: the errors the check collected while it waited were thrown away when the wait gave up. A page
    exception half a second after load (the label never drawn) must be named in the failure."""
    late_exception = "setTimeout(function () { throw new Error('a late page fault'); }, 500);"
    url, profile = serve_page(api_delay_s=30.0, inject_js=late_exception)
    result = run_check(url, profile, _browser_launch_flags(platform.system()),
                       extra_args=_with_limits(headStartMs=0, firstDrawMs=3000))
    assert result.returncode not in (0, LOAD_FAILURE_EXIT_CODE), (result.returncode, result.stdout, result.stderr)
    assert "watched age label not found" in result.stderr, result.stderr
    assert "the page reported: exception: " in result.stderr, result.stderr
    assert "the page reported no errors" not in result.stderr, result.stderr


def _watched_card_age(url: str) -> int:
    """What the page's own data request would show for the watched card (card-2) right now."""
    origin = url.rsplit("/", 1)[0]
    with urllib.request.urlopen(origin + "/api/attention", timeout=10) as reply:  # noqa: S310 - the local fixture
        items = json.loads(reply.read())["items"]
    return next(item["age_seconds"] for item in items if item["id"] == "card-2")


def test_the_retry_starts_its_cards_young_again_even_if_the_first_attempt_took_long(tmp_path) -> None:
    """#315: the retry used a fresh browser profile but the same test server, whose aging clock starts once
    and runs at 60x. With a 65 s gap between the attempts the retry's watched card was already 3,950 s old
    (shown as "1h") instead of 50 s, and the check refused a healthy page. The clock must restart for
    every attempt."""
    now = {"t": 1000.0}
    handler = _handler(monotonic=lambda: now["t"])
    srv = _serve(handler)
    ages: list[int] = []
    url = f"http://127.0.0.1:{srv.server_address[1]}/v2"
    try:
        def run(command, **kwargs):
            ages.append(_watched_card_age(url))  # the page's first data request of this attempt
            if len(ages) == 1:
                now["t"] += 65.0  # the first attempt takes long to finish, the second to start
                measured = {"problems": [BUFFER_SPACE_PROBLEM]}
            else:
                measured = {"problems": []}
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(measured), stderr="")

        out = run_browser_check(url, tmp_path / "profile", [], browser="browser", run=run,
                                before_retry=handler.restart_clock)
    finally:
        srv.shutdown()
        srv.server_close()
    assert out["problems"] == []
    assert ages == [50, 50], ages  # not [50, 3950]

