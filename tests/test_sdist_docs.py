"""Every file under docs/ that a test opens ships in the source package (sdist), so the tests
inside an unpacked sdist find it. A file only cited in a comment or a sentence does not count.
Inside an unpacked sdist this passes by construction: only shipped docs are there."""

from __future__ import annotations

import ast
import re
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


def _local_links(name: str) -> set[str]:
    """Relative link targets in a Markdown file at the top of the repository (no address, no anchor)."""
    text = (REPO / name).read_text(encoding="utf-8")
    links = set(re.findall(r"\]\(([^)\s#]+)(?:#[^)]*)?\)", text))
    return {link for link in links if not re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", link)}


def test_the_links_in_the_readme_and_the_contributing_guide_find_their_files() -> None:
    """Both files ship in the sdist, so each link must point at a file that exists, and a link from the
    contributing guide, or from the README to a top-level file, must find that file in the sdist too
    (a checkout always has it, which hides the gap)."""
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    include = [entry.strip("/") for entry in pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]]
    shipped = "LICENSE"  # the build adds the licence file by itself
    readme_links, guide_links = _local_links("README.md"), _local_links("CONTRIBUTING.md")
    assert {"CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md"} <= readme_links
    assert {"docs/LEAD-SETUP-BRIEF.md", "SECURITY.md"} <= guide_links
    nowhere = sorted(link for link in readme_links | guide_links if not (REPO / link).exists())
    assert nowhere == [], f"these links point at files that do not exist: {nowhere}"
    wanted = guide_links | {link for link in readme_links if "/" not in link}
    missing = sorted(link for link in wanted if link != shipped
                     and not any(link == entry or link.startswith(entry + "/") for entry in include))
    assert missing == [], f"add to [tool.hatch.build.targets.sdist] include in pyproject.toml: {missing}"
