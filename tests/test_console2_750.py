"""Regression checks for browser-check budgets and timeout diagnostics."""

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import test_console2_browser as browser


def test_750_derived_timeout_and_pinned_budgets():
    budgets = browser.phase_budgets_ms()
    assert budgets["startup"] == 90000
    assert budgets["firstDraw"] == 45000
    assert budgets["headStart"] == 3500
    assert budgets["streamRedraw1"] == budgets["streamRedraw2"] == budgets["boardRedraw"] == 30000
    assert browser.browser_check_timeout_s() == sum(budgets.values()) / 1000 + 30


@pytest.mark.parametrize(
    "stderr",
    [
        "console2 check: phase startup started at 0 ms\nconsole2 check: phase first-draw started at 5 ms\n",
        b"console2 check: phase startup started at 0 ms\nconsole2 check: phase first-draw started at 5 ms\n",
    ],
)
def test_750_timeout_reports_last_phase_and_does_not_retry(tmp_path, stderr):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], stderr=stderr)

    with pytest.raises(pytest.fail.Exception, match="phase first-draw") as failure:
        browser.run_browser_check("http://example.invalid", tmp_path / "profile", [], browser="browser", run=run)
    assert len(calls) == 1
    assert "phase startup started" in str(failure.value)


@pytest.mark.parametrize("scenario", ["unanswered", "exit-and-close"])
def test_750_protocol_standin(scenario):
    result = subprocess.run(
        ["node", str(browser.REPO_ROOT / "tests" / "console2_750.test.mjs"), scenario],
        text=True,
        capture_output=True,
        timeout=20,
        cwd=browser.REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["passed"] == 1


def test_750_phase_budgets_are_used_by_the_check():
    source = browser.CHECK.read_text(encoding="utf-8")
    for name in (
        "startup",
        "navigate",
        "head-start",
        "first-draw",
        "keys",
        "stream-redraw-1",
        "stream-redraw-2",
        "board-render",
        "board-redraw",
    ):
        assert f"phase('{name}'," in source
    assert "sleep(HEAD_START_MS)" in source
    assert "timeoutMs = REDRAW_BUDGET_MS" in source
    assert "BOARD_RENDER_BUDGET_MS / 150" in source
    assert "firstDrawDiagnostics(problems)" in source


@pytest.mark.skipif(not browser.BROWSER or not shutil.which("node"), reason="node or browser unavailable")
@pytest.mark.parametrize("script_fails", [False, True])
def test_750_first_draw_expiry_reports_phase_and_page_errors(tmp_path, script_fails):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/missing.js":
                self.send_response(500)
                self.end_headers()
                return
            self.send_response(200 if self.path == "/" else 204)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if self.path == "/" and script_fails:
                self.wfile.write(b'<script src="/missing.js"></script>')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        result = subprocess.run(
            [
                "node",
                str(browser.CHECK),
                browser.BROWSER,
                url,
                str(tmp_path / "profile"),
                json.dumps(browser._browser_launch_flags(browser.platform.system())),
                "",
                '{"firstDrawMs": 500}',
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            cwd=browser.REPO_ROOT,
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert result.returncode != 0
    if "watched age label not found" not in result.stderr:
        pytest.fail(result.stderr)
    assert "phase first-draw" in result.stderr and "first-draw" in result.stderr.split("phases:")[-1]
    assert "(unfinished)" in result.stderr
    if script_fails:
        assert "Failed to load resource" in result.stderr
    else:
        assert "the page reported no errors" in result.stderr
