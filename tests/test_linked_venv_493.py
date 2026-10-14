"""#493: a wrapped agent must start from a linked virtual environment (Linux and macOS).
"

On POSIX `python -m venv` makes the environment's python a link to the system Python, and the
packages are found through `pyvenv.cfg` beside that link. Following the link lands on a Python
without agenttalk. These tests build a real linked environment that can import agenttalk only
through its own link (a `.pth` file inside it) and run the wrapper's own code from it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from agenttalk import interpreter_path
from agenttalk.wrapper import run as wrapper_run

REPO = Path(__file__).resolve().parents[1]
POSIX = os.name != "nt"


def _env_without_python_paths() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME", "AGENTTALK_PY"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


@pytest.fixture()
def linked_venv(tmp_path: Path) -> Path:
    """A real linked virtual environment whose own python can import agenttalk and whose
"
    resolved (system) python cannot."""
    if not POSIX:
        pytest.skip("linked virtual environments are a Linux/macOS layout")
    home = tmp_path / "venv"
    venv.EnvBuilder(symlinks=True, with_pip=False, clear=True).create(home)
    python = home / "bin" / "python"
    if not python.is_symlink():
        pytest.skip("this Python builds environments without links")
    site = next((home / "lib").glob("python*/site-packages"))
    (site / "agenttalk_src.pth").write_text(str(REPO / "src") + "\n", encoding="utf-8")
    return python


@pytest.fixture()
def isolated_venv(linked_venv: Path, tmp_path: Path) -> Path:
    """The same environment, only when the Python behind the link cannot import agenttalk (the
    premise of the bug). Where agenttalk is also installed into the base Python (as CI does),
    the failure cannot show, so these tests skip."""
    behind = subprocess.run([str(linked_venv.resolve()), "-c", "import agenttalk"], capture_output=True,
                            text=True, env=_env_without_python_paths(), cwd=tmp_path)
    if behind.returncode == 0:
        pytest.skip("agenttalk is importable from the base Python here, so the bug cannot show")
    return linked_venv


def _run_in_venv(python: Path, code: str, cwd: Path) -> str:
    done = subprocess.run([str(python), "-c", code], capture_output=True, text=True,
                          env=_env_without_python_paths(), cwd=cwd, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout.strip()


def test_the_wrapper_names_the_environments_own_python(linked_venv: Path, tmp_path: Path) -> None:
    got = _run_in_venv(linked_venv, "from agenttalk.wrapper import run; print(run._agenttalk_py())", tmp_path)
    assert got == str(linked_venv)
    assert got != str(linked_venv.resolve())


def test_the_launch_self_check_passes_from_a_linked_environment(isolated_venv: Path, tmp_path: Path) -> None:
    """The real preflight (`<python> -m agenttalk --version`) run from inside the environment."""
    linked_venv = isolated_venv
    code = (
        "import sys, pathlib\n"
        "from agenttalk.wrapper import run\n"
        "ws = pathlib.Path(sys.argv[1])\n"
        "r = run.preflight_launch_runtime([sys.executable, '--version'], 'claude', ws)\n"
        "print('BLOCKED=' + str(r.blocked))\n"
    )
    done = subprocess.run([str(linked_venv), "-c", code, str(tmp_path)], capture_output=True, text=True,
                          env=_env_without_python_paths(), cwd=tmp_path, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip().endswith("BLOCKED=None"), done.stdout + done.stderr


def test_the_probe_command_itself_runs_from_the_link(isolated_venv: Path, tmp_path: Path) -> None:
    linked_venv = isolated_venv
    pinned = _run_in_venv(linked_venv, "from agenttalk.wrapper import run; print(run._agenttalk_py())", tmp_path)
    done = subprocess.run([pinned, "-m", "agenttalk", "--version"], capture_output=True, text=True,
                          env=_env_without_python_paths(), cwd=tmp_path, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    # and the old answer (the followed link) is exactly what fails
    old = subprocess.run([str(linked_venv.resolve()), "-m", "agenttalk", "--version"], capture_output=True,
                         text=True, env=_env_without_python_paths(), cwd=tmp_path, timeout=120)
    assert old.returncode != 0 and "No module named agenttalk" in old.stderr


def test_the_child_seat_is_told_to_use_the_environments_python(linked_venv: Path, tmp_path: Path) -> None:
    code = (
        "import pathlib, sys\n"
        "from agenttalk.wrapper import run\n"
        "print(run._child_env(pathlib.Path(sys.argv[1]))['AGENTTALK_PY'])\n"
    )
    done = subprocess.run([str(linked_venv), "-c", code, str(tmp_path)], capture_output=True, text=True,
                          env=_env_without_python_paths(), cwd=tmp_path, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip() == str(linked_venv)


def test_the_owed_action_dispatch_keeps_the_environments_python(linked_venv: Path, tmp_path: Path) -> None:
    code = (
        "from agenttalk.wrapper.obligations import DetectionCommitGate\n"
        "print(DetectionCommitGate._pinned_executable())\n"
    )
    env = _env_without_python_paths()
    env["AGENTTALK_PY"] = str(linked_venv)
    done = subprocess.run([str(linked_venv), "-c", code], capture_output=True, text=True, env=env,
                          cwd=tmp_path, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip() == str(linked_venv)


# ----------------------------------------- everywhere (no link needed)

def test_the_path_is_not_resolved_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self, *a, **k):
        raise AssertionError("must not follow links")

    monkeypatch.setattr(Path, "resolve", boom)
    here = os.path.abspath("env/bin/python")
    assert interpreter_path.launch_path("env/bin/python", windows=False) == here
    monkeypatch.setattr(sys, "executable", here)
    assert interpreter_path.launch_path(windows=False) == here


def test_windows_keeps_the_resolved_path(tmp_path: Path) -> None:
    exe = tmp_path / "x" / ".." / "python.exe"
    assert interpreter_path.launch_path(exe, windows=True) == str(exe.resolve())


def test_the_wrapper_uses_the_shared_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(interpreter_path, "launch_path", lambda *a, **k: "SENTINEL")
    monkeypatch.setattr(wrapper_run, "launch_path", interpreter_path.launch_path)
    assert wrapper_run._agenttalk_py() == "SENTINEL"
