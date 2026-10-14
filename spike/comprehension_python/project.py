"""Project-level steps for the spike: file walk, packaging evidence, the dialect decision
(design section 5, rules 1-4), import roots and module names (design section 4).

SPIKE CODE - DO NOT MERGE.
"""
from __future__ import annotations

import ast
import configparser
import os
import re
import time
from pathlib import Path

from . import py_reader

SKIP_DIRS = {".git", ".hg", ".svn", ".agenttalk", "__pycache__", "node_modules", ".venv", "venv", ".tox",
             ".mypy_cache", ".pytest_cache", ".eggs", ".nox", "site-packages", ".ruff_cache", "htmlcov"}


def walk_python(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")
                             and not os.path.islink(os.path.join(dirpath, d)))
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            if f.endswith(".py") and not os.path.islink(full):
                out.append(Path(full).relative_to(root).as_posix())
    return out


# ----------------------------------------------------------------------------- packaging evidence

def _setup_py_info(root: Path) -> dict:
    """Literal keywords of setup(...) in setup.py, read with repairs if it is Python 2 (never run)."""
    path = root / "setup.py"
    info: dict = {}
    if not path.is_file():
        return info
    pre = py_reader.prescan("setup.py", path.read_bytes())
    if pre.text is None:
        return info
    text = py_reader.apply_edits(pre.text, pre.edits) if pre.edits and not pre.tuple_parameter else pre.text
    try:
        tree = py_reader._quiet_parse(text)
    except SyntaxError:
        return info
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and py_reader._func_name(n) == "setup":
            for k in n.keywords:
                try:
                    info[k.arg] = ast.literal_eval(k.value)
                except (ValueError, TypeError, SyntaxError, RecursionError):
                    info.setdefault("_non_literal", []).append(k.arg)
        if isinstance(n, ast.Call) and py_reader._func_name(n) == "find_packages" and n.args:
            where = py_reader._str(n.args[0])
            if where:
                info.setdefault("_find_packages_where", []).append(where)
    return info


def packaging_evidence(root: Path) -> dict:
    info = _setup_py_info(root)
    requires = info.get("python_requires")
    classifiers = list(info.get("classifiers") or [])
    cfg = root / "setup.cfg"
    if cfg.is_file():
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(cfg, encoding="utf-8")
            requires = requires or parser.get("options", "python_requires", fallback=None)
            classifiers += [c.strip() for c in parser.get("metadata", "classifiers", fallback="").splitlines() if c.strip()]
        except configparser.Error:
            pass
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib  # Python 3.11+
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project") or {}
            requires = requires or project.get("requires-python")
            classifiers += list(project.get("classifiers") or [])
        except ImportError:
            info.setdefault("_notes", []).append("pyproject.toml not read on this Python (no tomllib)")
        except Exception as exc:  # noqa: BLE001 - spike
            info.setdefault("_notes", []).append(f"pyproject.toml unreadable: {type(exc).__name__}")
    dialect = None
    if isinstance(requires, str):
        spec = requires.replace(" ", "")
        if re.match(r"(>=|>|~=|==)3", spec):
            dialect = "python3"
        elif re.match(r"(<|<=|==)2", spec) or spec.startswith("<3"):
            dialect = "python2"
    if dialect is None:
        py3 = any(re.search(r"Programming Language :: Python :: 3", c) for c in classifiers)
        py2 = any(re.search(r"Programming Language :: Python :: 2", c) for c in classifiers)
        if py3 and not py2:
            dialect = "python3"
        elif py2 and not py3:
            dialect = "python2"
        elif py2 and py3:
            dialect = "python3"   # 2/3-compatible code cannot use except X, e:
    return {"dialect": dialect, "python_requires": requires, "python_classifiers":
            [c for c in classifiers if "Programming Language :: Python" in c], "setup": info}


def decide_project_dialect(evidence: dict, prescans: dict) -> tuple[str, str, dict]:
    """Rules 1-4 of the design. Returns (dialect, rule, counts)."""
    py2_files = sum(1 for p in prescans.values() if p.py2_markers)
    py3_files = sum(1 for p in prescans.values() if p.py3_markers)
    counts = {"files_with_python2_markers": py2_files, "files_with_python3_markers": py3_files}
    if evidence["dialect"]:
        return evidence["dialect"], "packaging", counts
    if py2_files and not py3_files:
        return "python2", "one_marker_kind", counts
    if py3_files and not py2_files:
        return "python3", "one_marker_kind", counts
    if py2_files and py3_files:
        return ("python2" if py2_files > py3_files else "python3"), "mixed", counts
    return "python2", "no_markers_default", counts


def file_dialect(project: str, rule: str, pre) -> tuple[str, str]:
    if rule == "mixed":
        if pre.py2_markers and not pre.py3_markers:
            return "python2", "own_markers"
        if pre.py3_markers and not pre.py2_markers:
            return "python3", "own_markers"
        return project, "mixed_majority"
    return project, rule


# ----------------------------------------------------------------------------- import roots

def module_names(root: Path, files: list[str], evidence: dict) -> dict[str, dict]:
    """relative path -> {"module": primary dotted name, "aliases": [...], "is_package": bool, "root": str}."""
    have_init = {f.rsplit("/", 1)[0] if "/" in f else "" for f in files if f.endswith("__init__.py")}
    declared: dict[str, str] = {}   # directory -> package name prefix ('' for a root)
    package_dir = evidence["setup"].get("package_dir")
    if isinstance(package_dir, dict):
        for name, d in package_dir.items():
            declared[str(d).strip("/")] = str(name)
    for where in evidence["setup"].get("_find_packages_where", []):
        declared.setdefault(where.strip("/"), "")
    out = {}
    for f in files:
        directory = f.rsplit("/", 1)[0] if "/" in f else ""
        stem = f.rsplit("/", 1)[-1][:-3]
        is_package = stem == "__init__"
        # rule 2: climb the unbroken __init__.py chain, never into or above the scan root ("")
        top = None
        d = directory
        while d and d in have_init:
            top = d
            d = d.rsplit("/", 1)[0] if "/" in d else ""
        chain_root = (top.rsplit("/", 1)[0] if top and "/" in top else "") if top else directory
        names = []
        for base_dir, prefix in [(chain_root, "")] + sorted(declared.items()):
            if base_dir and not (directory == base_dir or directory.startswith(base_dir + "/")):
                continue
            rel_dir = directory[len(base_dir):].strip("/") if base_dir else directory
            parts = ([prefix] if prefix else []) + ([p for p in rel_dir.split("/") if p] if rel_dir else [])
            if not is_package:
                parts.append(stem)
            if parts:
                names.append(".".join(parts))
        primary = names[0] if names else None
        out[f] = {"module": primary, "aliases": sorted(set(names[1:]) - {primary}), "is_package": is_package,
                  "root": chain_root}
    return out


# ----------------------------------------------------------------------------- the whole read

def read_project(root: Path) -> dict:
    timings = {}
    t0 = time.perf_counter()
    files = walk_python(root)
    timings["walk_s"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    prescans = {f: py_reader.prescan(f, (root / f).read_bytes()) for f in files}
    timings["prescan_s"] = time.perf_counter() - t0
    evidence = packaging_evidence(root)
    dialect, rule, counts = decide_project_dialect(evidence, prescans)
    names = module_names(root, files, evidence)
    t0 = time.perf_counter()
    claims = []
    for f in files:
        d, frule = file_dialect(dialect, rule, prescans[f])
        ctx = py_reader.FileContext(f, names[f]["module"], names[f]["is_package"], d, frule, py_reader.classify(f))
        fc = py_reader.read(prescans[f], ctx)
        fc.extras["module_aliases"] = names[f]["aliases"]
        fc.extras["is_package"] = names[f]["is_package"]
        claims.append(fc)
    timings["read_s"] = time.perf_counter() - t0
    return {"files": files, "claims": claims, "evidence": evidence, "dialect": dialect, "dialect_rule": rule,
            "marker_counts": counts, "timings": timings}
