"""#496 failing reproduction: a Python-only repository is reported "complete".

WAITING FOR THE MAINTAINERS' VERDICT. The maintainers asked to hold the #496 build until
their blind challenge on the issue is answered, because the change alters what a Python-only
run reports (`complete` becomes `degraded`). This file is only the failing reproduction, written
first. It is RED on purpose: the assertions describe the outcome proposed in the architect's
plan (issue #496), not today's behaviour. Do not treat the red result as a regression, and do
not build against it until the verdict is posted. If the verdict changes the outcome, change
these assertions to match.

Proposed outcome pinned here (from the plan on #496):
  * a run that finds source files but parsed none with a bundled adapter is not `complete`:
    it is `degraded`, using the existing status (no new status value);
  * the run-level reason code is `no_supported_source`, listed in `degraded_by` and backed by
    a problem record in `problems.json` (the per-file `unsupported_language` warning stays);
  * scan (human and `--json`), status (human and `--json`), report (`--json`), the stored
    `scan.json`, the index summary and `validate` all agree;
  * exit code stays 0 for a successfully published run (degradation is report data).

Assumed, not fixed by the plan: scan's `--json` carries the reason as a `degraded_by` list,
the same name status and report already use. Rename here if the verdict says otherwise.

Today's facts, which stay true after the fix and are checked by the green test below: one
Python file gives two file units, zero features, zero dependencies, zero entry points and one
`unsupported_language` warning.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agenttalk import cli
from agenttalk.comprehension import scan_pipeline
from agenttalk.comprehension import worker as workermod

REASON = "no_supported_source"


@pytest.fixture(autouse=True)
def _inprocess_worker(monkeypatch):
    monkeypatch.setattr(
        scan_pipeline.worker, "run_sanitized_worker",
        lambda root, relative_paths, **_kwargs: workermod.process_paths(root, relative_paths),
    )


@pytest.fixture(autouse=True)
def _no_agent_identity(monkeypatch):
    monkeypatch.delenv("AGENTTALK_SELF", raising=False)


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)  # noqa: S603,S607  # nosec B603 B607
    subprocess.run(  # noqa: S603,S607  # nosec B603 B607
        ["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(  # noqa: S603,S607  # nosec B603 B607
        ["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / ".gitignore").write_text(".agenttalk/\n", encoding="utf-8")


@pytest.fixture()
def python_repo(tmp_path: Path) -> Path:
    """The tiny Python-only repository: one source file, no Java, no descriptors."""
    _init_git_repo(tmp_path)
    (tmp_path / "app.py").write_text("def main():\n    print(1)\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def java_repo(tmp_path: Path) -> Path:
    """Control: a supported-language repository must stay `complete`."""
    _init_git_repo(tmp_path)
    app_dir = tmp_path / "src" / "main" / "java" / "p"
    app_dir.mkdir(parents=True)
    (app_dir / "App.java").write_text(
        "package p;\nclass App {\n  public static void main(String[] args) {}\n}\n",
        encoding="utf-8",
    )
    return tmp_path


def _run(argv: list[str], root: Path) -> int:
    return cli.main(["--root", str(root), *argv])


def _json(argv: list[str], root: Path, capsys) -> dict:
    capsys.readouterr()
    assert _run(argv, root) == 0
    return json.loads(capsys.readouterr().out)


def _text(argv: list[str], root: Path, capsys) -> str:
    capsys.readouterr()
    assert _run(argv, root) == 0
    return capsys.readouterr().out


def _stored_run(root: Path, scan_id: str) -> Path:
    return root / ".agenttalk" / "comprehension" / "runs" / scan_id


# ---------------------------------------------------------------- green: today's facts

def test_python_only_repo_today_has_nothing_parsed_and_one_unsupported_language_warning(
    python_repo: Path, capsys,
) -> None:
    """Green before and after the fix: the numbers that show nothing was understood."""
    scan = _json(["comprehension", "scan", "--json"], python_repo, capsys)
    report = _json(["comprehension", "report", "--json"], python_repo, capsys)
    counts = report["counts"]
    assert counts["units"] == 2  # discovery evidence only: a unit is not a parsed file
    assert counts["features"] == 0
    assert counts["dependencies"] == 0
    assert counts["entry_points"] == 0
    warnings = [p for p in report["problems"] if p["reason_code"] == "unsupported_language"]
    assert [p["path"] for p in warnings] == ["app.py"]
    assert scan["scan_id"] == report["scan_id"]


def test_control_java_repo_stays_complete(java_repo: Path, capsys) -> None:
    """Green before and after the fix: a supported language is still `complete`."""
    scan = _json(["comprehension", "scan", "--json"], java_repo, capsys)
    assert scan["status"] == "complete"
    status = _json(["comprehension", "status", "--json"], java_repo, capsys)
    assert status["degraded_by"] == []


# ---------------------------------------------------------------- red: proposed outcome

def test_scan_human_output_says_degraded_with_the_reason(python_repo: Path, capsys) -> None:
    out = _text(["comprehension", "scan"], python_repo, capsys)
    assert "status:  degraded" in out, f"scan printed:\n{out}"
    assert REASON in out, f"scan did not name the reason right after scanning:\n{out}"


def test_scan_json_says_degraded_with_the_reason(python_repo: Path, capsys) -> None:
    scan = _json(["comprehension", "scan", "--json"], python_repo, capsys)
    assert scan["status"] == "degraded", f"scan --json: {scan}"
    assert REASON in scan.get("degraded_by", []), f"scan --json has no reason: {scan}"


def test_status_human_output_says_degraded_with_the_reason(python_repo: Path, capsys) -> None:
    _text(["comprehension", "scan"], python_repo, capsys)
    out = _text(["comprehension", "status"], python_repo, capsys)
    assert "status:   degraded" in out, f"status printed:\n{out}"
    assert f"degraded_by: {REASON}" in out, f"status printed:\n{out}"


def test_status_json_says_degraded_with_the_reason_and_two_problems(
    python_repo: Path, capsys,
) -> None:
    _text(["comprehension", "scan"], python_repo, capsys)
    status = _json(["comprehension", "status", "--json"], python_repo, capsys)
    assert status["status"] == "degraded", f"status --json: {status['status']}"
    assert status["degraded_by"] == [REASON], f"degraded_by: {status['degraded_by']}"
    # the per-file warning stays, and the run-level problem is added to it
    assert status["problem_count"] == 2, f"problem_count: {status['problem_count']}"
    assert [r["status"] for r in status["run_summaries"]] == ["degraded"]


def test_report_json_says_degraded_with_the_reason_backed_by_a_problem(
    python_repo: Path, capsys,
) -> None:
    _text(["comprehension", "scan"], python_repo, capsys)
    report = _json(["comprehension", "report", "--json"], python_repo, capsys)
    assert report["status"] == "degraded", f"report status: {report['status']}"
    assert report["degraded_by"] == [REASON], f"report degraded_by: {report['degraded_by']}"
    codes = sorted(p["reason_code"] for p in report["problems"])
    assert codes == [REASON, "unsupported_language"], f"report problems: {codes}"
    assert report["counts"]["problems"] == 2


def test_stored_run_index_and_validation_agree(python_repo: Path, capsys) -> None:
    scan = _json(["comprehension", "scan", "--json"], python_repo, capsys)
    run_dir = _stored_run(python_repo, scan["scan_id"])
    stored = json.loads((run_dir / "scan.json").read_text(encoding="utf-8"))
    assert stored["status"] == "degraded", f"stored scan.json status: {stored['status']}"
    assert stored["degraded_by"] == [REASON]
    assert stored["problem_count"] == 2
    problems = json.loads((run_dir / "problems.json").read_text(encoding="utf-8"))["problems"]
    assert REASON in {p["reason_code"] for p in problems}, "no problem record backs the reason"
    # the run is still valid: scan.json, problems.json and the index must agree with each other
    validation = _json(["comprehension", "validate", "--json"], python_repo, capsys)
    assert validation["valid"] is True, f"validate: {validation}"
