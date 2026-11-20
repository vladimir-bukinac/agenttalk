"""Regression checks for the installed and explicit source runtime forms."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

import pytest

import agenttalk
from agenttalk import cli, doctor, skill_currency, supervisor
from agenttalk.wrapper import prompt, run
from agenttalk.store import Store


@pytest.mark.skipif(os.name != "nt", reason="the generated command shim runs on Windows")
@pytest.mark.parametrize("installed", [True, False], ids=["installed-nonzero", "missing"])
def test_installed_shim_only_suggests_install_for_missing_package(tmp_path, installed):
    runtime = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=False).create(runtime)
    python = runtime / "Scripts" / "python.exe"
    if installed:
        package = runtime / "Lib" / "site-packages" / "agenttalk"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "__main__.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    shim = tmp_path / "agenttalk.cmd"
    shim.write_bytes(supervisor.agenttalk_shim(str(python)).encode("utf-8"))
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
    env["ATK_FAKE_SECRET"] = "made-up-test-secret"
    result = subprocess.run(
        [str(Path(env["SystemRoot"]) / "System32" / "cmd.exe"), "/d", "/c", str(shim), "check"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == (3 if installed else 1)
    assert ("pip --user" in result.stderr) is (not installed)


@pytest.mark.parametrize("source", [False, True])
def test_init_and_validation_use_same_recorded_mode(store, source):
    args = ["--root", str(store.root), "supervise", "--init"]
    if source:
        args.append("--source-checkout")
    assert cli.main(args) == 0
    assert supervisor.recorded_source_mode(store) is source
    assert supervisor.validate_artifact_bundle(store)["ok"]


@pytest.mark.parametrize("source", [False, True])
def test_init_validates_in_selected_runtime_process(store, tmp_path, source):
    runtime = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=False).create(runtime)
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = (
        runtime / "Lib/site-packages"
        if os.name == "nt"
        else runtime / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    package_root = store.root / "src" if source else site
    package_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(agenttalk.__file__).parent, package_root / "agenttalk")
    supervisor.init(store, python_exe=str(python), source_checkout=source)
    env = {
        key: os.environ[key]
        for key in ("SystemRoot", "WINDIR", "USERPROFILE", "LOCALAPPDATA", "TEMP", "TMP")
        if key in os.environ
    }
    env["ATK_FAKE_SECRET"] = "made-up-test-secret"
    if source:
        env["PYTHONPATH"] = str(package_root)
    command = [
        str(python),
        *([] if source else ["-I"]),
        "-c",
        "import agenttalk; from agenttalk.store import Store; "
        "from agenttalk.supervisor import validate_artifact_bundle; "
        "import sys; validate_artifact_bundle(Store(sys.argv[1])); print(agenttalk.__file__)",
        str(store.root),
    ]
    result = subprocess.run(command, cwd=store.root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).is_relative_to(package_root)


@pytest.mark.parametrize("source", [False, True])
def test_doctor_reports_runtime_mode_for_claude_only_supervisor(store, source):
    supervisor.init(store, source_checkout=source)
    (store.dir / "supervisor.json").write_text(json.dumps({"agents": {"alice": {"cli": "claude"}}}))
    report = doctor.run(store.root)
    mode = "source" if source else "installed"
    assert any(f"supervisor runtime mode: {mode} (recorded in supervisor.ps1)" in c.details for c in report.checks)


def test_source_checkout_does_not_silently_skip_existing_scripts(store, capsys):
    supervisor.init(store)
    assert cli.main(["--root", str(store.root), "supervise", "--init", "--source-checkout"]) != 0
    assert "--force" in capsys.readouterr().err
    assert not supervisor.recorded_source_mode(store)


def test_source_checkout_requires_init(store, capsys):
    assert cli.main(["--root", str(store.root), "supervise", "--refresh-scripts", "--source-checkout"]) != 0
    assert "--init" in capsys.readouterr().err


@pytest.mark.parametrize("result,reason", [((1, "access denied"), "access denied"), ((0, "not json"), "not json")])
def test_runtime_probe_reports_actual_failure(tmp_path, result, reason):
    message = run.preflight_agenttalk_runtime(workspace_root=tmp_path, runner=lambda *args: result)
    assert "runtime check could not run" in message
    assert reason in message
    assert "install agenttalk" not in message


def test_strict_installed_rule_uses_isolation(tmp_path):
    python = tmp_path / "python.exe"
    python.touch()
    result = prompt.strict_reply_invocation("claude", ["claude", "--permission-mode", "dontAsk"], str(python))
    assert result.endswith('" -I -m agenttalk')


def test_skill_rule_accepts_isolated_invocation():
    text = 'When AGENTTALK_PY is set, use `"$AGENTTALK_PY" -I -m agenttalk`; otherwise use the project form.'
    assert skill_currency._RULE_RE.search(text)


def test_skill_rule_does_not_treat_interactive_flag_as_isolation():
    text = 'When AGENTTALK_PY is set, use `"$AGENTTALK_PY" -i -m agenttalk`; otherwise use the project form.'
    assert not skill_currency._RULE_RE.search(text)


def test_checkout_layout_does_not_select_source_mode(store):
    package = store.root / "src" / "agenttalk"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    bundle = supervisor._marker_placeholder_bundle(store)
    assert b"$SrcOnPyPath = $false" in bundle["supervisor.ps1"]


def test_source_mode_is_explicitly_recorded(store):
    bundle = supervisor._marker_placeholder_bundle(store, source_checkout=True)
    assert b"$SrcOnPyPath = $true" in bundle["supervisor.ps1"]


def test_init_notices_checkout_and_keeps_installed_mode(store, capsys):
    package = store.root / "src" / "agenttalk"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    assert cli.main(["--root", str(store.root), "supervise", "--init"]) == 0
    assert "installed mode selected; use --source-checkout for source mode" in capsys.readouterr().out
    assert not supervisor.recorded_source_mode(store)


def test_source_supervisor_records_and_uses_source(store):
    supervisor.init(store, source_checkout=True)
    assert supervisor.recorded_source_mode(store)
    shim = (store.dir / "bin" / "agenttalk.cmd").read_text()
    assert "PYTHONPATH=" in shim and '"%AGENTTALK_PYTHON%" -m agenttalk' in shim
    inspection = supervisor.inspect_artifact_bundle(store)
    assert inspection["ok"], inspection["errors"]
    assert len({entry["generator_generation"] for entry in inspection["markers"].values()}) == 1
    assert {"supervisor.ps1", "deadman.ps1", "bin/agenttalk.cmd"} <= inspection["markers"].keys()


def test_runtime_identity_requires_deliberate_source(tmp_path, monkeypatch):
    package = tmp_path / "checkout" / "src" / "agenttalk"
    package.mkdir(parents=True)
    bound = package / "__init__.py"
    bound.touch()
    (package.parent.parent / "pyproject.toml").touch()
    other = tmp_path / "installed.py"
    other.touch()
    monkeypatch.setattr(agenttalk, "__file__", str(bound))
    monkeypatch.setattr(run, "_run_startup_check", lambda *a: (0, json.dumps({"file": str(other)})))
    with pytest.raises(ValueError):
        run.select_runtime_mode(sys.executable, tmp_path, {})
    assert run.select_runtime_mode(sys.executable, tmp_path, {"PYTHONPATH": str(package.parent)}) == "source"
    monkeypatch.setattr(run, "_run_startup_check", lambda *a: (0, json.dumps({"file": str(bound)})))
    assert run.select_runtime_mode(sys.executable, tmp_path, {"PYTHONPATH": str(package.parent)}) == "installed"


def test_source_runtime_does_not_hide_probe_denial(tmp_path, monkeypatch):
    package = tmp_path / "checkout" / "src" / "agenttalk"
    package.mkdir(parents=True)
    bound = package / "__init__.py"
    bound.touch()
    (package.parent.parent / "pyproject.toml").touch()
    monkeypatch.setattr(agenttalk, "__file__", str(bound))

    def denied(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(run, "_run_startup_check", denied)
    with pytest.raises(ValueError):
        run.select_runtime_mode(sys.executable, tmp_path, {"PYTHONPATH": str(package.parent)})


def test_source_runtime_allows_a_missing_isolated_install(tmp_path, monkeypatch):
    package = tmp_path / "checkout" / "src" / "agenttalk"
    package.mkdir(parents=True)
    bound = package / "__init__.py"
    bound.touch()
    (package.parent.parent / "pyproject.toml").touch()
    monkeypatch.setattr(agenttalk, "__file__", str(bound))
    monkeypatch.setattr(
        run, "_run_startup_check", lambda *args: (1, "ModuleNotFoundError: No module named 'agenttalk'")
    )
    assert run.select_runtime_mode(sys.executable, tmp_path, {"PYTHONPATH": str(package.parent)}) == "source"


def test_other_installation_is_not_a_source_checkout(tmp_path, monkeypatch):
    package = tmp_path / "site-packages" / "agenttalk"
    package.mkdir(parents=True)
    bound = package / "__init__.py"
    bound.touch()
    other = tmp_path / "other.py"
    other.touch()
    monkeypatch.setattr(agenttalk, "__file__", str(bound))
    monkeypatch.setattr(run, "_run_startup_check", lambda *a: (0, json.dumps({"file": str(other)})))
    with pytest.raises(ValueError):
        run.select_runtime_mode(sys.executable, tmp_path, {"PYTHONPATH": str(package.parent)})


def test_editable_install_matching_bound_file_is_installed(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    package = checkout / "src" / "agenttalk"
    package.mkdir(parents=True)
    bound = package / "__init__.py"
    bound.touch()
    (checkout / "pyproject.toml").touch()
    venv_root = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(venv_root)
    python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = (
        venv_root / "Lib/site-packages"
        if os.name == "nt"
        else venv_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    site.mkdir(parents=True, exist_ok=True)
    (site / "editable.pth").write_text(str(package.parent) + "\n")
    monkeypatch.setattr(agenttalk, "__file__", str(bound))
    env = {"PYTHONPATH": str(package.parent)}
    if os.name == "nt":
        env["SystemRoot"] = os.environ["SystemRoot"]
    assert run.select_runtime_mode(str(python), tmp_path, env) == "installed"


@pytest.mark.parametrize("source", [False, True])
def test_supervisor_admits_the_effective_runtime_command(tmp_path, source):
    row = {
        "cli": "codex",
        "wrapped": True,
        "launch": {
            "windows_file": "python.exe",
            "windows_args": [
                "-m",
                "agenttalk",
                "wrap",
                "--for",
                "alpha",
                "--cli",
                "codex",
                "--loop",
                "--",
                "codex.exe",
            ],
        },
    }
    candidate, error = supervisor._effective_launch_candidate(
        row,
        population="regular",
        agent="alpha",
        root=tmp_path,
        source_checkout=source,
    )
    assert error is None
    assert candidate.argv[0] == ("-m" if source else "-I")


def test_supervisor_recognizes_its_added_isolation_flag():
    command = "python -I -m agenttalk wrap --for alice --cli codex --loop -- codex"
    assert supervisor._agenttalk_argv(command) == ["wrap", "--for", "alice", "--cli", "codex", "--loop", "--", "codex"]


@pytest.mark.parametrize("source", [False, True])
def test_doctor_uses_recorded_source_mode(store, monkeypatch, source):
    package = store.root / "src" / "agenttalk"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (store.dir / "supervisor.ps1").write_text(f"$SrcOnPyPath = ${str(source).lower()}\n")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env, _ = doctor._probe_env(store, {"agenttalk_py": sys.executable}, {})
    assert (str(store.root / "src") in env.get("PYTHONPATH", "")) is source


@pytest.mark.parametrize("source", [False, True])
def test_doctor_runtime_check_uses_recorded_mode(store, monkeypatch, source):
    (store.dir / "supervisor.ps1").write_text(f"$SrcOnPyPath = ${str(source).lower()}\n")
    seen = {}
    monkeypatch.setattr(run, "preflight_agenttalk_runtime", lambda **kwargs: seen.update(kwargs))
    doctor._check_agenttalk_runtime(store.root)
    assert seen["source"] is source


def test_doctor_reports_invalid_recorded_mode(store):
    (store.dir / "supervisor.ps1").write_text("$SrcOnPyPath = $maybe\n")
    (store.dir / "supervisor.json").write_text(json.dumps({"agents": {"alpha": {"cli": "codex"}}}))
    check = doctor._check_supervised_codex(store)
    assert check.status == "error"
    assert "source mode" in check.details


def test_manual_source_preflight_keeps_selected_pythonpath(tmp_path, monkeypatch):
    selected = str(tmp_path / "selected" / "src")
    seen = {}
    monkeypatch.setattr(run, "_child_env", lambda *args: {"AGENTTALK_PY": sys.executable, "PYTHONPATH": selected})

    def runner(argv, cwd, env, timeout):
        seen.update(env)
        return 0, json.dumps({"file": str(tmp_path / "agenttalk" / "__init__.py")})

    run.preflight_agenttalk_runtime(workspace_root=tmp_path, source=True, runner=runner)
    assert seen["PYTHONPATH"] == selected


def test_runtime_preflight_rejects_missing_probe_identity(tmp_path):
    result = run.preflight_agenttalk_runtime(workspace_root=tmp_path, runner=lambda *args: (0, "not json"))
    assert result is not None


def test_runtime_preflight_rejects_unrecognized_probe_failure(tmp_path):
    result = run.preflight_agenttalk_runtime(workspace_root=tmp_path, runner=lambda *args: (1, "probe failed"))
    assert result is not None


@pytest.mark.parametrize("source", [False, True])
def test_doctor_probe_loads_recorded_runtime(store, tmp_path, source):
    venv_root = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(venv_root)
    python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = (
        venv_root / "Lib/site-packages"
        if os.name == "nt"
        else venv_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    for root, label in [(site, "installed"), (store.root / "src", "source")]:
        package = root / "agenttalk"
        package.mkdir(parents=True)
        (package / "__init__.py").touch()
        (package / "__main__.py").write_text(f"print({label!r})\n")
    codex = tmp_path / "codex.exe"
    codex.touch()
    (store.dir / "supervisor.ps1").write_text(f"$SrcOnPyPath = ${str(source).lower()}\n")
    (store.dir / "supervisor.json").write_text(
        json.dumps({"agents": {"alpha": {"cli": "codex", "launch": {"windows_file": str(codex)}}}})
    )
    shim = store.dir / "bin" / "agenttalk.cmd"
    shim.parent.mkdir(exist_ok=True)
    shim.write_text(f'if not defined AGENTTALK_PYTHON set "AGENTTALK_PYTHON={python}"\n')

    def runner(exe, args, timeout, cwd, env):
        if args == ["--version"]:
            return 0, "codex"
        result = subprocess.run([exe, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout + result.stderr

    check = doctor._check_supervised_codex(store, runner=runner)
    assert check.data["codex"][0]["agenttalk_version"] == ("source" if source else "installed")


@pytest.mark.parametrize("kind", ["file", "package"])
def test_isolated_invocation_keeps_working_folder_and_store(tmp_path, kind):
    # A harmless stand-in marks any accidental import from the working folder.
    marker = tmp_path / "collision-ran"
    if kind == "file":
        module = tmp_path / "agenttalk.py"
    else:
        package = tmp_path / "agenttalk"
        package.mkdir()
        module = package / "__init__.py"
    module.write_text(f"open({str(marker)!r}, 'w').write('local')\n")
    venv_root = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(venv_root)
    python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = (
        venv_root / "Lib/site-packages"
        if os.name == "nt"
        else venv_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    installed = site / "agenttalk"
    installed.mkdir(parents=True)
    (installed / "__init__.py").touch()
    (installed / "__main__.py").write_text(
        "import json, os, sys; print(json.dumps([os.getcwd(), os.environ['AGENTTALK_ROOT'], sys.path]))"
    )
    root = tmp_path / "store"
    env = {"AGENTTALK_ROOT": str(root)}
    if os.name == "nt":
        env["SystemRoot"] = os.environ["SystemRoot"]
    result = subprocess.run(
        [str(python), *run.runtime_module_args(source=False)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    cwd, recorded_root, paths = json.loads(result.stdout)
    assert Path(cwd) == tmp_path and recorded_root == str(root)
    assert str(tmp_path) not in paths and "" not in paths
    assert not marker.exists()


@pytest.mark.parametrize("kind", ["file", "package"])
def test_installed_agenttalk_wins_and_respects_store_selection(tmp_path, kind):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    implicit = tmp_path / "implicit"
    explicit = tmp_path / "explicit"
    Store(implicit).init(["implicit-agent"])
    Store(explicit).init(["explicit-agent"])
    marker = workspace / "local-ran"
    if kind == "file":
        local = workspace / "agenttalk.py"
    else:
        (workspace / "agenttalk").mkdir()
        local = workspace / "agenttalk" / "__init__.py"
    local.write_text(f"open({str(marker)!r}, 'w').write('local')\n")
    venv_root = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(venv_root)
    python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = (
        venv_root / "Lib/site-packages"
        if os.name == "nt"
        else venv_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    shutil.copytree(Path(agenttalk.__file__).parent, site / "agenttalk", ignore=shutil.ignore_patterns("__pycache__"))
    env = {
        "AGENTTALK_ROOT": str(implicit),
        "USERPROFILE": str(tmp_path),
        "LOCALAPPDATA": str(tmp_path),
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
        "ATK_FAKE_SECRET": "made-up-test-secret",
    }
    if os.name == "nt":
        env["SystemRoot"] = os.environ["SystemRoot"]
    command = [str(python), *run.runtime_module_args(source=False)]
    implicit_result = subprocess.run([*command, "status"], cwd=workspace, env=env, capture_output=True, text=True)
    explicit_result = subprocess.run(
        [*command, "--root", str(explicit), "status"], cwd=workspace, env=env, capture_output=True, text=True
    )
    assert implicit_result.returncode == 0 and "implicit-agent" in implicit_result.stdout
    assert explicit_result.returncode == 0 and "explicit-agent" in explicit_result.stdout
    assert not marker.exists()
