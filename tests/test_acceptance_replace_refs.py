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


def process_call_sites(path):
    """(file, enclosing function) of every call that starts a process or runs a command in `path`."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = set()

    def visit(node, function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and function == "<module>":
            function = node.name  # the outermost function: a helper defined inside it belongs to it
        if isinstance(node, ast.Call):
            target = node.func
            owner = target.value.id if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) else ""
            name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            if owner in {"subprocess", "os"} and name in {
                "run",
                "Popen",
                "call",
                "check_call",
                "check_output",
                "system",
                "popen",
                "spawnl",
                "spawnv",
            }:
                found.add((path.name, function))
            if name in {"Popen", "check_output", "check_call"} and not owner:
                found.add((path.name, function))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, "<module>")
    return found


def test_the_inventory_of_acceptance_git_calls_is_closed_and_each_one_ignores_replace_refs():
    """The inventory (#887): in the acceptance modules and the modules they call (close, gates, the Git read cache)
    two functions start a process, and both are Git readers that ignore replace refs. A third one fails here, so a
    new Git call that reads history cannot be added without choosing, in this test, how it ignores them."""
    sites = set().union(*(process_call_sites(path) for path in SOURCES))
    assert sites == {("acceptance.py", "_project_git"), ("acceptance_audit.py", "_git")}, sites
    assert '"--no-replace-objects"' in inspect.getsource(acceptance._project_git)
    audit_source = inspect.getsource(acceptance_audit._git)
    assert 'env["GIT_NO_REPLACE_OBJECTS"] = "1"' in audit_source and "env=env" in audit_source
