"""Every file under docs/ that a test opens ships in the source package (sdist), so the tests
inside an unpacked sdist find it. A file only cited in a comment or a sentence does not count.
Inside an unpacked sdist this passes by construction: only shipped docs are there."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _file_names(source: str) -> set[str]:
    """The last path part of every string in the code; comments are not code."""
    return {node.value.replace("\\", "/").rsplit("/", 1)[-1] for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def test_a_path_in_code_counts_but_a_comment_or_a_sentence_does_not() -> None:
    source = 'open("docs\\\\ops\\\\a.md")\nopen(REPO / "docs" / "b.json")  # c.md\nprint("see d.md first")\n'
    assert {"a.md", "b.json"} <= _file_names(source)
    assert not {"c.md", "d.md"} & _file_names(source)


def test_every_docs_file_a_test_opens_is_in_the_sdist() -> None:
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    # Each entry is one file or folder; none is a pattern today.
    include = [entry.strip("/") for entry in pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]]
    named = set().union(*(_file_names(test.read_text(encoding="utf-8")) for test in (REPO / "tests").rglob("*.py")))
    docs = [path.relative_to(REPO).as_posix() for path in (REPO / "docs").rglob("*") if path.is_file()]
    missing = sorted(path for path in docs if path.rsplit("/", 1)[-1] in named
                     and not any(path == entry or path.startswith(entry + "/") for entry in include))
    assert missing == [], f"add to [tool.hatch.build.targets.sdist] include in pyproject.toml: {missing}"
