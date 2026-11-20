"""#496: a run that parsed no supported source file must not say plain ``complete``.

The shape (maintainers' blind challenge on #496, RESHAPE, accepted): the run is ``degraded``,
with the one new reason ``no_supported_source``, ONLY when BOTH hold:

  * zero supported source files were parsed (``.java`` today; ``pom.xml`` / ``web.xml``
    descriptors are not source), and
  * at least one unsupported, code-bearing file was selected (for example ``.py``).

Java plus Python helper scripts stays ``complete``. No new status value; exit codes unchanged
(a published degraded run still exits 0). One additive count, ``supported_source_files_parsed``,
in ``status`` and in ``report`` ``counts``. One plain line (``note``) in scan, status and report
when the reason fires, and one sentence in the scan help that says what ``complete`` means.
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
NOTE_START = "No supported source files were parsed"
NOTE_RULE = "fixed list of programming languages and code file types"


@pytest.fixture(autouse=True)
def _inprocess_worker(monkeypatch):
    monkeypatch.setattr(
        scan_pipeline.worker,
        "run_sanitized_worker",
        lambda root, relative_paths, **_kwargs: workermod.process_paths(root, relative_paths),
    )


@pytest.fixture(autouse=True)
def _no_agent_identity(monkeypatch):
    monkeypatch.delenv("AGENTTALK_SELF", raising=False)


def _repo(root: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)  # noqa: S603,S607  # nosec B603 B607
    subprocess.run(  # noqa: S603,S607  # nosec B603 B607
        ["git", "-C", str(root), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(  # noqa: S603,S607  # nosec B603 B607
        ["git", "-C", str(root), "config", "user.name", "t"], check=True
    )
    (root / ".gitignore").write_text(".agenttalk/\n", encoding="utf-8")
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


PY = "def main():\n    print(1)\n"
JAVA = "package p;\nclass App {\n  public static void main(String[] args) {}\n}\n"
POM = (
    '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>'
    "<groupId>g</groupId><artifactId>a</artifactId><version>1</version></project>\n"
)

PYTHON_ONLY = {"app.py": PY}
JAVA_ONLY = {"src/main/java/p/App.java": JAVA}
JAVA_PLUS_PY_HELPER = {"src/main/java/p/App.java": JAVA, "scripts/release.py": PY}
PYTHON_PLUS_POM = {"app.py": PY, "pom.xml": POM}
SQL_ONLY = {"db/schema.sql": "create table t (id int);\n"}
DOCS_ONLY = {"README.md": "# hello\n"}
TOOLING_ONLY = {"Dockerfile": "FROM scratch\n", "ci.yml": "a: 1\n"}
# Not code, or tooling by choice (see worker._UNSUPPORTED_SOURCE_EXTENSIONS): stays complete.
LICENSE_README_UNKNOWN = {"LICENSE": "MIT\n", "README.md": "# x\n", "data.xyz": "1 2 3\n"}
SHELL_AND_MAKE_DEPS = {"build.sh": "echo hi\n", "deploy.ps1": "Write-Host hi\n", "main.d": "main.o: main.c\n"}
ELIXIR_ONLY = {"main.ex": "defmodule Main do\n  def hello, do: :world\nend\n"}
HASKELL_ONLY = {"Main.hs": 'main :: IO ()\nmain = putStrLn "hi"\n'}
# Files that only share a suffix with a listed language (see worker._is_listed_source_file):
QT_TS = (
    '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n'
    '<TS version="2.1" language="fr_FR"><context><name>Main</name></context></TS>\n'
)
REAL_TS = "export function hello(name: string): string {\n  return name;\n}\n"
FREEMIND_MM = '<map version="1.0.1">\n<node TEXT="root"/>\n</map>\n'
OBJC_MM = "#import <Foundation/Foundation.h>\nint main() { return 0; }\n"
QT_TS_COMMENT_LED = '<!-- translation file -->\n<TS version="2.1" language="fr"><context/></TS>\n'
TS_GENERIC_ARROW = "<TS extends unknown>(x: TS) => x;\n"
QT_TS_ONLY = {"translations/fr.ts": QT_TS}
QT_TS_COMMENT_LED_ONLY = {"translations/fr.ts": QT_TS_COMMENT_LED}
TS_GENERIC_ONLY = {"src/main.ts": TS_GENERIC_ARROW}
REAL_TS_ONLY = {"src/index.ts": REAL_TS}
QT_TS_PLUS_PY_HELPER = {"translations/fr.ts": QT_TS, "tools/gen.py": PY}
FREEMIND_ONLY = {"notes/plan.mm": FREEMIND_MM}
OBJC_ONLY = {"App.mm": OBJC_MM}
BLANKS = "\n\n"


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


def _scan_then_status(root: Path, capsys) -> dict:
    _text(["comprehension", "scan"], root, capsys)
    return _json(["comprehension", "status", "--json"], root, capsys)


# ------------------------------------------------------- green today: the facts of the report


def test_python_only_repo_has_nothing_parsed_and_one_unsupported_language_warning(
    tmp_path: Path,
    capsys,
) -> None:
    """Green before and after: the numbers that show nothing was understood."""
    _repo(tmp_path, PYTHON_ONLY)
    scan = _json(["comprehension", "scan", "--json"], tmp_path, capsys)
    report = _json(["comprehension", "report"], tmp_path, capsys)
    counts = report["counts"]
    assert counts["units"] == 2  # file units are discovery evidence, not parsed code
    assert counts["features"] == 0
    assert counts["dependencies"] == 0
    assert counts["entry_points"] == 0
    warnings = [p for p in report["problems"] if p["reason_code"] == "unsupported_language"]
    assert [p["path"] for p in warnings] == ["app.py"]
    assert scan["scan_id"] == report["scan_id"]


# ------------------------------------------------------- the reproduction (red on master)


def test_python_only_scan_json_is_degraded_and_names_the_reason(tmp_path: Path, capsys) -> None:
    _repo(tmp_path, PYTHON_ONLY)
    scan = _json(["comprehension", "scan", "--json"], tmp_path, capsys)
    assert scan["status"] == "degraded", f"scan --json: {scan}"
    assert scan.get("degraded_by") == [REASON], f"scan --json: {scan}"
    assert scan["note"].startswith(NOTE_START), f"scan --json: {scan}"
    assert NOTE_RULE in scan["note"], f"scan --json: {scan}"


def test_python_only_scan_human_output_says_degraded_with_one_plain_line(
    tmp_path: Path,
    capsys,
) -> None:
    _repo(tmp_path, PYTHON_ONLY)
    out = _text(["comprehension", "scan"], tmp_path, capsys)
    assert "status:  degraded" in out, f"scan printed:\n{out}"
    assert out.count(NOTE_START) == 1, f"scan printed:\n{out}"


def test_python_only_status_human_and_json(tmp_path: Path, capsys) -> None:
    _repo(tmp_path, PYTHON_ONLY)
    status = _scan_then_status(tmp_path, capsys)
    assert status["status"] == "degraded", f"status --json: {status['status']}"
    assert status["degraded_by"] == [REASON]
    assert status["supported_source_files_parsed"] == 0
    assert status["note"].startswith(NOTE_START)
    assert status["problem_count"] == 2  # the per-file warning stays; the run-level problem joins it
    assert [r["status"] for r in status["run_summaries"]] == ["degraded"]
    out = _text(["comprehension", "status"], tmp_path, capsys)
    assert "status:   degraded" in out, f"status printed:\n{out}"
    assert f"degraded_by: {REASON}" in out
    assert out.count(NOTE_START) == 1, f"status printed:\n{out}"


def test_python_only_report_json_carries_reason_count_note_and_a_problem_record(
    tmp_path: Path,
    capsys,
) -> None:
    _repo(tmp_path, PYTHON_ONLY)
    _text(["comprehension", "scan"], tmp_path, capsys)
    report = _json(["comprehension", "report"], tmp_path, capsys)
    assert report["status"] == "degraded", f"report status: {report['status']}"
    assert report["degraded_by"] == [REASON]
    assert report["counts"]["supported_source_files_parsed"] == 0
    assert report["counts"]["units"] == 2  # existing key unchanged, next to the new one
    assert report["note"].startswith(NOTE_START)
    assert NOTE_RULE in report["note"]
    codes = sorted(p["reason_code"] for p in report["problems"])
    assert codes == [REASON, "unsupported_language"], f"report problems: {codes}"


def test_python_only_stored_run_index_and_validation_agree(tmp_path: Path, capsys) -> None:
    _repo(tmp_path, PYTHON_ONLY)
    scan = _json(["comprehension", "scan", "--json"], tmp_path, capsys)
    run_dir = Path(scan["run_dir"])
    stored = json.loads((run_dir / "scan.json").read_text(encoding="utf-8"))
    assert stored["status"] == "degraded", f"stored scan.json status: {stored['status']}"
    assert stored["degraded_by"] == [REASON]
    assert stored["problem_count"] == 2
    assert stored["supported_source_files_parsed"] == 0
    problems = json.loads((run_dir / "problems.json").read_text(encoding="utf-8"))["problems"]
    assert REASON in {p["reason_code"] for p in problems}, "no problem record backs the reason"
    validation = _json(["comprehension", "validate", "--json"], tmp_path, capsys)
    assert validation["valid"] is True, f"validate: {validation}"


def test_python_plus_maven_descriptor_is_degraded(tmp_path: Path, capsys) -> None:
    """A pom.xml is a descriptor the adapter reads, not source: it does not count as parsed."""
    _repo(tmp_path, PYTHON_PLUS_POM)
    status = _scan_then_status(tmp_path, capsys)
    assert status["status"] == "degraded"
    assert REASON in status["degraded_by"]
    assert status["supported_source_files_parsed"] == 0


def test_sql_only_stays_degraded_and_now_also_says_no_supported_source(
    tmp_path: Path,
    capsys,
) -> None:
    _repo(tmp_path, SQL_ONLY)
    status = _scan_then_status(tmp_path, capsys)
    assert status["status"] == "degraded"
    assert status["degraded_by"] == [REASON, "unsupported_language"]


def test_scan_help_defines_complete_in_one_sentence(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["comprehension", "scan", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "complete means" in text, text
    assert "fixed list of programming languages and code file types" in text, text
    assert "not on that list does not count" in text, text
    assert REASON in text, text


@pytest.mark.parametrize(
    "files",
    [ELIXIR_ONLY, HASKELL_ONLY, REAL_TS_ONLY, OBJC_ONLY, QT_TS_PLUS_PY_HELPER, TS_GENERIC_ONLY],
    ids=[
        "elixir",
        "haskell",
        "typescript",
        "objective-c++",
        "qt-translation-plus-python-helper",
        "typescript-generic-arrow",
    ],
)
def test_other_unsupported_languages_are_degraded_too(tmp_path: Path, capsys, files) -> None:
    """codex-rev's #496 finding: a repository of only `main.ex` was reported complete."""
    _repo(tmp_path, files)
    scan = _json(["comprehension", "scan", "--json"], tmp_path, capsys)
    assert scan["status"] == "degraded", f"scan --json: {scan}"
    assert scan["degraded_by"] == [REASON]
    status = _json(["comprehension", "status", "--json"], tmp_path, capsys)
    assert status["supported_source_files_parsed"] == 0


@pytest.mark.parametrize(
    "name",
    [
        "a.ex",
        "a.exs",
        "a.erl",
        "a.hrl",
        "a.kts",
        "a.fs",
        "a.fsx",
        "a.fsi",
        "a.vb",
        "a.m",
        "a.mm",
        "a.hs",
        "a.lhs",
        "a.ml",
        "a.mli",
        "a.clj",
        "a.cljs",
        "a.cljc",
        "a.jl",
        "a.r",
        "a.R",
        "a.zig",
        "a.nim",
        "a.cr",
        "a.f90",
        "a.f95",
        "a.f03",
        "a.f08",
        "a.adb",
        "a.ads",
        "a.pas",
        "a.pm",
        "a.pl",
        "a.elm",
        "a.rkt",
        "a.scm",
        "a.ss",
        "a.lisp",
        "a.lsp",
        "a.el",
        "a.v",
        "a.vala",
        "a.sol",
        "a.py",
        "a.ts",
        "a.rs",
        "dir/Deep.EX",
    ],
)
def test_listed_language_files_count_as_unsupported_code(name: str) -> None:
    assert workermod.is_listed_source_file(name, b"x = 1"), name


@pytest.mark.parametrize(
    "name",
    [
        "LICENSE",
        "README.md",
        "data.xyz",
        "build.sh",
        "run.bash",
        "deploy.ps1",
        "go.bat",
        "main.d",
        "Makefile",
        "app.yml",
        "Dockerfile",
        "notes.txt",
        "x.ex.md",
    ],
)
def test_other_file_types_do_not_count_as_unsupported_code(name: str) -> None:
    assert not workermod.is_listed_source_file(name, b"x = 1"), name


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("fr.ts", QT_TS),
        ("fr.ts", chr(0xFEFF) + "  " + BLANKS + QT_TS),  # BOM, then blank lines
        ("fr.ts", QT_TS_COMMENT_LED),  # comment first, no declaration (codex-rev P1-2)
        ("fr.ts", '<?xml version="1.0"?><!-- c --><!DOCTYPE TS><!-- d --><TS version="2"/>'),
        ("fr.ts", '<!DOCTYPE TS><TS version="2.0"></TS>'),
        ("fr.ts", '<TS version="2.0"></TS>'),
        ("fr.ts", "<TS version='2.0' language='fr'>" + BLANKS),  # single quotes
        ("fr.ts", "<!DOCTYPE TS><TS>" + BLANKS),  # a bare root is fine once XML context is shown
        ("plan.mm", FREEMIND_MM),
        ("plan.mm", '<?xml version="1.0"?><map/>'),
        ("plan.mm", "<!-- exported -->" + BLANKS + FREEMIND_MM),
        ("plan.mm", '<?xml version="1.0"?><!-- c --><map>' + BLANKS),
        ("x.py", '<?xml version="1.0"?><a/>'),  # no other listed language starts with an XML declaration
    ],
)
def test_a_file_that_only_shares_a_suffix_is_not_source(name: str, text: str) -> None:
    assert not workermod.is_listed_source_file(name, text.encode("utf-8")), (name, text[:30])


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("a.ts", REAL_TS),
        ("a.ts", "// translations are in fr.ts" + BLANKS + REAL_TS),
        ("a.ts", '/// <reference path="x.d.ts" />' + BLANKS),
        ("a.ts", "const TS = 1;" + BLANKS),
        ("a.ts", TS_GENERIC_ARROW),  # codex-rev P1-1: a generic arrow function, not XML
        ("a.ts", "<TS,>(x: TS) => x;" + BLANKS),
        ("a.ts", "<TS>(x: TS) => x;" + BLANKS),  # a bare <TS> with no XML context is TypeScript
        ("a.ts", "<TS extends unknown, U>(x: TS, y: U) => x;" + BLANKS),
        ("a.ts", '<?xml version="1.0"?><other version="1"/>'),  # XML, but not a Qt translation
        ("a.ts", '<?xml version="1.0"?>' + BLANKS),  # a declaration with no root at all
        ("a.ts", "<!-- only a comment -->" + BLANKS),  # no root: not recognised, so not excluded
        ("a.ts", "<!-- never closed" + BLANKS + '<TS version="2"/>'),
        ("a.ts", '<!DOCTYPE TS [ <!ENTITY x "y"> ]><TS version="2"/>'),  # an internal subset: unsure
        ("a.ts", '<!DOCTYPE TS><!DOCTYPE TS><TS version="2"/>'),  # only one DOCTYPE is allowed
        ("a.ts", '<TS version="2" language=fr>' + BLANKS),  # not an XML attribute
        ("a.ts", "<!-- " + "x" * 5000 + ' --><TS version="2"/>'),  # root past the 4 KB bound: code
        ("a.mm", OBJC_MM),
        ("a.mm", "// <map> of things" + BLANKS + "int x;" + BLANKS),
        ("a.mm", "<map>" + BLANKS),  # a bare <map> with no XML context
        ("a.mm", "<!-- " + "x" * 5000 + " --><map/>"),
        ("empty.ts", ""),
    ],
)
def test_real_typescript_and_objective_cpp_still_count_as_source(name: str, text: str) -> None:
    assert workermod.is_listed_source_file(name, text.encode("utf-8")), (name, text[:30])


def test_the_worker_records_per_file_whether_an_unsupported_file_is_code(tmp_path: Path) -> None:
    """The Qt file and the Python helper are both unsupported_language warnings; only the helper
    is code."""
    _repo(tmp_path, QT_TS_PLUS_PY_HELPER)
    result = workermod.process_paths(tmp_path, ["translations/fr.ts", "tools/gen.py"])
    flags = {p.relative_path: p.code_bearing for p in result.problems if p.reason_code == "unsupported_language"}
    assert flags == {"translations/fr.ts": False, "tools/gen.py": True}
    code = [p.relative_path for p in result.problems if workermod.is_unsupported_code_bearing_problem(p)]
    assert code == ["tools/gen.py"]


# ------------------------------------------------------- controls: must stay as they are


@pytest.mark.parametrize(
    ("files", "parsed"),
    [
        (JAVA_ONLY, 1),
        (JAVA_PLUS_PY_HELPER, 1),  # a Python helper in a Java repository stays non-degrading
        (DOCS_ONLY, 0),  # nothing code-bearing was selected
        (TOOLING_ONLY, 0),  # tooling and config files are not code-bearing
        (LICENSE_README_UNKNOWN, 0),  # a file type not on the list does not count
        (QT_TS_ONLY, 0),
        (QT_TS_COMMENT_LED_ONLY, 0),  # Qt translation XML is not TypeScript
        (FREEMIND_ONLY, 0),  # a FreeMind mind map is not Objective-C++
        (SHELL_AND_MAKE_DEPS, 0),  # shell scripts and make .d files are tooling, by decision
        ({}, 0),  # an empty repository
    ],
    ids=[
        "java",
        "java-plus-python-helper",
        "docs-only",
        "tooling-only",
        "license-readme-unknown",
        "qt-translation",
        "qt-translation-comment-led",
        "freemind",
        "shell-and-make-deps",
        "empty",
    ],
)
def test_control_runs_stay_complete_and_quiet(tmp_path: Path, capsys, files, parsed) -> None:
    _repo(tmp_path, files)
    scan = _json(["comprehension", "scan", "--json"], tmp_path, capsys)
    assert scan["status"] == "complete", f"scan --json: {scan}"
    assert "degraded_by" not in scan and "note" not in scan, f"scan --json: {scan}"
    status = _json(["comprehension", "status", "--json"], tmp_path, capsys)
    assert status["degraded_by"] == []
    assert "note" not in status
    assert status["supported_source_files_parsed"] == parsed
    report = _json(["comprehension", "report"], tmp_path, capsys)
    assert "note" not in report
    assert report["counts"]["supported_source_files_parsed"] == parsed
    out = _text(["comprehension", "scan"], tmp_path, capsys)
    assert "status:  complete" in out and NOTE_START not in out


def test_a_run_written_before_this_change_has_no_count_and_none_is_invented() -> None:
    """scan.json of an older run lacks the count: readers omit the key, never guess a number."""
    assert scan_pipeline._optional_scan_count({"status": "complete"}) is None
    assert scan_pipeline._optional_scan_count({"supported_source_files_parsed": 3}) == 3
