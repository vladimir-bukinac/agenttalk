"""#887: acceptance reads a project's commit, tree and roots with Git's replace refs ignored.

A replace ref makes ordinary Git show one object in place of another. These are regression tests of acceptance's own
reads: each builds a throwaway repository, adds a replace ref there, and checks that what acceptance verifies is the
stored commit's, never the substitute's. They also pin which Git calls acceptance makes, so a new call that reads
history cannot skip the option unnoticed."""

import ast
import inspect
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from agenttalk import acceptance, acceptance_audit


def run_git(project, *args, env=None, data=None):
    base = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    result = subprocess.run(
        ["git", "-C", str(project), *args], capture_output=True, input=data, env={**base, **(env or {})}, check=True
    )
    return result.stdout.decode().strip()


@pytest.fixture
def history(tmp_path, acceptance_candidate_template):
    """A copy of the two-commit candidate repository (a base commit and a candidate on top of it), clean, with its
    facts read before any replace ref exists."""
    template, sha = acceptance_candidate_template
    project = tmp_path / "project"
    shutil.copytree(template, project)
    return SimpleNamespace(
        project=project,
        sha=sha,
        base=run_git(project, "rev-parse", sha + "^"),
        stored_tree=run_git(project, "--no-replace-objects", "rev-parse", f"{sha}^{{tree}}"),
        fresh=acceptance.verify_project(project, sha, live=False),
        live=acceptance.verify_project(project, sha),
    )


def substitute(history, content=b"substituted content\n"):
    """A commit whose tree differs from the project's commit (source.txt changed) and that has the same parents, and
    a replace ref that shows it in place of the project's commit. Returns the substitute's commit id."""
    project, sha = history.project, history.sha
    blob = run_git(project, "hash-object", "-w", "--stdin", data=content)
    index = project / ".git" / "substitute-index"
    env = {"GIT_INDEX_FILE": str(index)}
    try:
        run_git(project, "read-tree", sha, env=env)
        run_git(project, "update-index", "--cacheinfo", f"100644,{blob},source.txt", env=env)
        tree = run_git(project, "write-tree", env=env)
    finally:
        index.unlink(missing_ok=True)
    commit = run_git(project, "commit-tree", tree, "-p", history.base, "-m", "substitute")
    run_git(project, "replace", sha, commit)
    return commit


def test_a_substitute_tree_is_not_what_acceptance_verifies(history):
    """Same repository, with and without a replace ref for the project's commit: the same tree, roots and project_id,
    read from the stored commit."""
    substitute(history)
    # The premise: ordinary Git does show the substitute's tree. Without it the test proves nothing.
    assert run_git(history.project, "rev-parse", f"{history.sha}^{{tree}}") != history.stored_tree

    fresh = acceptance.verify_project(history.project, history.sha, live=False)
    live = acceptance.verify_project(history.project, history.sha)

    assert fresh == history.fresh and live == history.live
    assert fresh["tree"] == history.stored_tree
    assert acceptance.project_id(fresh) == acceptance.project_id(history.fresh)


def test_a_grafted_start_of_history_does_not_change_the_roots_or_the_project_id(history):
    """`git replace --graft <commit>` with no parent makes the commit a root. Acceptance's roots, and so its
    project_id, stay those of the stored history."""
    run_git(history.project, "replace", "--graft", history.sha)
    # The premise: ordinary Git now reports the candidate commit itself as a root.
    assert run_git(history.project, "rev-list", "--max-parents=0", history.sha) == history.sha

    after = acceptance.verify_project(history.project, history.sha, live=False)

    assert after["roots"] == history.fresh["roots"] != [history.sha]
    assert acceptance.project_id(after) == acceptance.project_id(history.fresh)
    assert acceptance.verify_project(history.project, history.sha) == history.live


def test_a_replacement_synced_into_the_working_tree_is_an_uncommitted_change(history):
    """The files of a replacement written into the working tree are not the stored commit's: acceptance refuses the
    checkout as dirty, with the same refusal as for any other uncommitted change."""
    content = b"substituted content\n"
    substitute(history, content)
    # Syncing the replacement into the working tree: ordinary Git, which shows HEAD as the substitute, resets the
    # index and the files to it.
    run_git(history.project, "reset", "--hard", "--quiet")
    assert (history.project / "source.txt").read_bytes().replace(b"\r\n", b"\n") == content
    # The premise: ordinary Git calls this checkout clean, which is how a read that honoured the replace ref would
    # have accepted files the commit does not hold.
    assert run_git(history.project, "status", "--porcelain", "--untracked-files=all") == ""

    with pytest.raises(acceptance.AcceptanceError) as synced:
        acceptance.verify_project(history.project, history.sha)

    assert synced.value.code == "acceptance_project_unverified"
    assert str(synced.value).startswith("acceptance project checkout is dirty:")
    # Any other uncommitted change is refused as the same kind of refusal.
    run_git(history.project, "replace", "-d", history.sha)
    run_git(history.project, "reset", "--hard", "--quiet")
    assert acceptance.verify_project(history.project, history.sha) == history.live  # clean again at the commit
    (history.project / "source.txt").write_bytes(b"something else\n")
    with pytest.raises(acceptance.AcceptanceError) as other:
        acceptance.verify_project(history.project, history.sha)
    assert other.value.code == synced.value.code
    assert str(other.value).startswith("acceptance project checkout is dirty:")


def test_the_working_tree_at_the_stored_commit_still_verifies_with_a_replace_ref_present(history):
    substitute(history)
    assert acceptance.verify_project(history.project, history.sha) == history.live


# ---------------------------------------------------------------------------- every acceptance Git read


def recorded_git_calls(monkeypatch):
    calls = []
    real = subprocess.run

    def observed(args, *a, **kw):
        if args and args[0] == "git":
            calls.append((list(args), kw.get("env") or {}))
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", observed)
    return calls


def ignores_replace_refs(args, env):
    return "--no-replace-objects" in args[:3] or env.get("GIT_NO_REPLACE_OBJECTS") == "1"


@pytest.mark.parametrize("replaced", [False, True])
def test_every_git_read_acceptance_makes_ignores_replace_refs(history, monkeypatch, replaced):
    """The project facts (toplevel and commit, tree, roots, HEAD, status), the shallow check on a refusal, and the cold
    audit (history completeness, ancestry, the commit check, the diff and its patch id) are all run, and every Git
    call among them ignores replace refs: by the global option, or by the environment variable the audit sets."""
    if replaced:
        substitute(history)
    calls = recorded_git_calls(monkeypatch)
    project = history.fresh
    plan = {"cold_policy": {"change_base": history.base}}

    acceptance.verify_project(history.project, history.sha, live=False)
    acceptance.verify_project(history.project, history.sha)
    with pytest.raises(acceptance.AcceptanceError):
        acceptance._project_mismatch(history.project, "project changed")
    related = acceptance_audit.related_revisions(project, history.base, history.sha)
    identity = acceptance_audit.change_identity(project, plan)

    names = ("rev-parse", "rev-list", "status", "merge-base", "diff", "patch-id")
    subcommands = {name for args, _ in calls for name in names if name in args}
    assert {"rev-parse", "rev-list", "status", "merge-base", "diff", "patch-id"} <= subcommands, subcommands
    assert "--is-shallow-repository" in {arg for args, _ in calls for arg in args}
    assert all(ignores_replace_refs(args, env) for args, env in calls), [
        args for args, env in calls if not ignores_replace_refs(args, env)
    ]
    assert related is True and identity["revision"] == history.sha


def test_the_cold_audit_gives_the_same_answers_with_a_replace_ref_present(history):
    """The audit's own Git helper (the environment variable, not the option): a graft that cuts the candidate loose
    from its base, and a substitute for it, change neither the ancestry nor the change's patch id."""
    plan = {"cold_policy": {"change_base": history.base}}
    before = (
        acceptance_audit.related_revisions(history.fresh, history.base, history.sha),
        acceptance_audit.change_identity(history.fresh, plan),
    )
    run_git(history.project, "replace", "--graft", history.sha)
    # The premise: ordinary Git no longer sees the base as the candidate's ancestor.
    assert (
        subprocess.run(
            ["git", "-C", str(history.project), "merge-base", "--is-ancestor", history.base, history.sha],
            capture_output=True,
        ).returncode
        == 1
    )

    after = (
        acceptance_audit.related_revisions(history.fresh, history.base, history.sha),
        acceptance_audit.change_identity(history.fresh, plan),
    )

    assert after == before and before[0] is True


SOURCES = sorted(
    [
        *Path(acceptance.__file__).parent.glob("acceptance*.py"),
        *(Path(acceptance.__file__).parent / name for name in ("close.py", "gates.py")),
    ]
)


# What starts a process or runs a command, by module. `subprocess` and `os` are the ones these modules could reach.
LAUNCHERS = {
    "subprocess": {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"},
    "os": {
        "system", "popen", "startfile", "posix_spawn", "posix_spawnp",
        "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
        "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    },
}  # fmt: skip


def launch_references(source, filename):
    """Every use of a launcher in `source`, counted per (file, outermost function), and what cannot be followed.

    A use is the attribute (`subprocess.run`, `sp.run` after `import subprocess as sp`) or the name (`run` after
    `from subprocess import run`, `co` after `... import check_output as co`), whether it is called or only bound, so
    `runner = subprocess.run` is found too. Imports anywhere in the file bind names for the whole file. A star import
    from a launcher module, and dynamic imports (`__import__`, `importlib`), cannot be followed and are reported."""
    tree = ast.parse(source)
    modules, names, problems = {}, {}, []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in LAUNCHERS and "." not in alias.name:
                    modules[alias.asname or alias.name] = alias.name
                elif alias.name.split(".")[0] == "importlib":
                    problems.append("importlib is imported")
        elif isinstance(node, ast.ImportFrom) and not node.level:
            if node.module == "importlib":
                problems.append("importlib is imported")
            for alias in node.names:
                if node.module in LAUNCHERS:
                    if alias.name == "*":
                        problems.append(f"star import from {node.module}")
                    elif alias.name in LAUNCHERS[node.module]:
                        names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Name) and node.id == "__import__":
            problems.append("__import__ is used")
    found = Counter()

    def visit(node, function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and function == "<module>":
            function = node.name  # the outermost function: a helper defined inside it belongs to it
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = modules.get(node.value.id)
            if module and node.attr in LAUNCHERS[module]:
                found[(filename, function)] += 1
        elif isinstance(node, ast.Name) and node.id in names and isinstance(node.ctx, ast.Load):
            found[(filename, function)] += 1
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, "<module>")
    return found, problems


def inventory(paths):
    found, problems = Counter(), []
    for path in paths:
        counted, trouble = launch_references(path.read_text(encoding="utf-8-sig"), path.name)
        found.update(counted)
        problems += [f"{path.name}: {text}" for text in trouble]
    return found, problems


def test_the_inventory_of_acceptance_git_calls_is_closed_and_each_one_ignores_replace_refs():
    """The inventory (#887): in the acceptance modules and the modules they call (close, gates, the Git read cache)
    exactly two uses of a process launcher exist, one in each of two functions, and both are Git readers that ignore
    replace refs. A third use, in any spelling, fails here, so a new Git call that reads history cannot be added
    without choosing, in this test, how it ignores them. (This is also why the runtime guard above, which watches
    `subprocess.run`, is enough: a name imported directly would be found here.)"""
    found, problems = inventory(SOURCES)
    assert not problems, problems
    assert found == {("acceptance.py", "_project_git"): 1, ("acceptance_audit.py", "_git"): 1}, found
    assert '"--no-replace-objects"' in inspect.getsource(acceptance._project_git)
    audit_source = inspect.getsource(acceptance_audit._git)
    assert 'env["GIT_NO_REPLACE_OBJECTS"] = "1"' in audit_source and "env=env" in audit_source


@pytest.mark.parametrize(
    "source, expected",
    [
        ("from subprocess import run\ndef peek(r):\n    return run(['git', 'rev-list', 'HEAD'])\n", {"peek": 1}),
        ("import subprocess as sp\ndef peek(r):\n    return sp.check_output(['git', 'log'])\n", {"peek": 1}),
        ("from subprocess import check_output as co\ndef peek(r):\n    return co(['git', 'log'])\n", {"peek": 1}),
        (
            "from subprocess import call, Popen\ndef a():\n    call(['x'])\ndef b():\n    Popen(['x'])\n",
            {"a": 1, "b": 1},
        ),
        ("import os\ndef peek(r):\n    return os.system('git log')\n", {"peek": 1}),
        ("from os import popen\ndef peek(r):\n    return popen('git log')\n", {"peek": 1}),
        ("import subprocess\nrunner = subprocess.run\n", {"<module>": 1}),
        ("def peek(r):\n    import subprocess\n    return subprocess.run(['git'])\n", {"peek": 1}),
        ("import subprocess\ndef two(r):\n    subprocess.run(['a'])\n    subprocess.run(['b'])\n", {"two": 2}),
        (
            "import subprocess\ndef outer():\n    def inner():\n        subprocess.run(['a'])\n    inner()\n",
            {"outer": 1},
        ),
    ],
    ids=[
        "from-import-run",
        "module-alias",
        "from-import-alias",
        "from-import-two-functions",
        "os-system",
        "from-os-import-popen",
        "bound-not-called",
        "import-inside-function",
        "two-calls-one-function",
        "nested-function",
    ],
)
def test_the_inventory_finds_every_spelling_of_a_process_launch(source, expected):
    found, problems = launch_references(source, "extra.py")
    assert not problems
    assert found == {("extra.py", function): count for function, count in expected.items()}


def test_the_inventory_ignores_what_does_not_start_a_process():
    source = (
        "import os\nimport subprocess\n"
        "def f(x):\n"
        "    try:\n        return subprocess.PIPE, os.path.join(x, 'a'), os.environ\n"
        "    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):\n        return None\n"
    )
    assert launch_references(source, "extra.py") == (Counter(), [])


@pytest.mark.parametrize(
    "source",
    [
        "from subprocess import *\n",
        "import importlib\n",
        "from importlib import import_module\n",
        "def f():\n    return __import__('subprocess')\n",
    ],
)
def test_the_inventory_reports_what_it_cannot_follow(source):
    assert launch_references(source, "extra.py")[1]


def test_a_new_acceptance_module_that_imports_run_directly_fails_the_inventory(tmp_path):
    """The case the first version missed: an unguarded Git read through a directly imported `run`."""
    extra = tmp_path / "acceptance_extra.py"
    extra.write_text(
        "from subprocess import run\n\n\ndef history(repo):\n    return run(['git', '-C', repo, 'rev-list', 'HEAD'])\n",
        encoding="utf-8",
    )
    found, problems = inventory([*SOURCES, extra])
    assert not problems
    assert found != {("acceptance.py", "_project_git"): 1, ("acceptance_audit.py", "_git"): 1}
    assert found[("acceptance_extra.py", "history")] == 1


def test_a_second_launch_in_an_inventoried_function_changes_the_inventory():
    """The set of function names alone cannot tell one call from two: the count is pinned."""
    text = Path(acceptance.__file__).read_text(encoding="utf-8-sig")
    assert launch_references(text, "acceptance.py")[0] == Counter({("acceptance.py", "_project_git"): 1})
    doubled = text.replace(
        "        result = subprocess.run(",
        "        subprocess.run(['git', 'rev-list', 'HEAD'])\n        result = subprocess.run(",
        1,
    )
    assert doubled != text
    assert launch_references(doubled, "acceptance.py")[0] == Counter({("acceptance.py", "_project_git"): 2})
