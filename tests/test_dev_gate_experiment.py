"""P6: experimental calls remain bound, non-voting, and separate from the gate."""

from __future__ import annotations

import copy
import importlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agenttalk import dev_gate as gate
from agenttalk import dev_gate_trial as trial
from test_dev_gate import _leg_artifact, _manifest


@pytest.fixture
def exp():
    return importlib.import_module("agenttalk.dev_gate_experiment")


@pytest.fixture
def request_factory(exp, tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    manifest = _manifest()
    (checkout / "dev-gate.json").write_text(json.dumps(manifest), encoding="utf-8")
    contract = json.loads((Path(__file__).parents[1] / "dev-gate-experiment.json").read_text())
    (checkout / "dev-gate-experiment.json").write_text(json.dumps(contract), encoding="utf-8")
    binding = SimpleNamespace(candidate_sha="a" * 40, clean=True)
    monkeypatch.setattr(gate, "capture_candidate_binding", lambda root: binding)
    monkeypatch.setattr(gate, "_platform_label", lambda: "windows")
    monkeypatch.setattr(
        exp,
        "installed_identity",
        lambda root: {
            "commit": "a" * 40,
            "version": "1.0",
            "record_sha256": "b" * 64,
        },
    )
    frozen = {
        "contract_sha256": exp.contract_hash(contract),
        "commit": "a" * 40,
        "environments": {"3.12": {"freeze_sha256": "c" * 64}},
    }
    record = tmp_path / "frozen.json"
    record.write_text(json.dumps(frozen), encoding="utf-8")
    counter = 0

    def make(**kwargs):
        nonlocal counter
        counter += 1
        options = {
            "checkout": checkout,
            "record": record,
            "output": tmp_path / f"out{counter}",
            "leg": "windows/3.12",
            "modes": ("source", "wheel"),
            "arm": "serial",
            "probe": None,
        }
        options.update(kwargs)
        return exp.prepare_request(**options)

    make.checkout, make.record, make.contract, make.manifest = checkout, record, contract, manifest
    return make


def capture_ordinary(monkeypatch, manifest, mode, paths, env):
    """Use the actual ordinary-gate argv/environment/timeout path as the oracle."""
    captured = {}
    monkeypatch.setattr(gate, "_probe_python_module", lambda *a, **k: "pytest")
    monkeypatch.setattr(gate, "import_probe", lambda **k: {})
    monkeypatch.setattr(gate, "_platform_label", lambda: "windows")

    def run(**kwargs):
        captured.update(kwargs)
        log = paths["logs"] / "ordinary.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("pass", encoding="utf-8")
        return gate.CommandOutcome(tuple(kwargs["argv"]), 0, 1, "pass", None, "", log)

    monkeypatch.setattr(gate, "run_command", run)
    gate._run_pytest_mode(
        mode=mode,
        interpreter=gate.InterpreterInfo("3.12", Path(sys.executable), "CPython", platform.python_version()),
        source_root=paths["source"],
        import_root=paths["imports"],
        env=env,
        expected_version="1.0",
        manifest=manifest,
        basetemp=paths["bt"],
        logs_dir=paths["logs"],
    )
    return captured


@pytest.mark.parametrize("mode", ["source", "wheel"])
def test_01_serial_equivalence_and_parallel_has_only_d4(exp, request_factory, tmp_path, monkeypatch, mode):
    req = request_factory(modes=(mode,))
    paths = {name: tmp_path / name for name in ("source", "imports", "bt", "logs", "records")}
    env = gate._base_env(tmp_path)
    ordinary = capture_ordinary(monkeypatch, req.manifest, mode, paths, env)
    call = exp.pytest_call(req, mode, Path(sys.executable), paths, env)
    expected = ordinary["argv"][: -len(req.manifest["checks"]["pytest"]["paths"])]
    expected += ["--experiment-record", str(paths["records"])] + req.manifest["checks"]["pytest"]["paths"]
    assert call["argv"] == expected
    assert call["env"] == ordinary["env"] and call["timeout_seconds"] == ordinary["timeout_seconds"]
    assert call["checks"] == trial.partition(req.manifest, req.leg, mode)
    req.arm = "parallel"
    parallel = exp.pytest_call(req, mode, Path(sys.executable), paths, env)
    insert = len(expected) - len(req.manifest["checks"]["pytest"]["paths"])
    expected[insert:insert] = req.contract["arms"]["parallel"]
    assert parallel["argv"] == expected


def test_02_ordinary_windows_parallel_evidence_still_rejected():
    manifest = _manifest()
    artifact = _leg_artifact(manifest, "windows/3.12")
    check = next(c for c in artifact["checks"] if c["kind"] == "pytest")
    check["argv"][-1:-1] = manifest["checks"]["pytest"]["posix_parallel_args"]
    with pytest.raises(gate.GateBlock):
        gate.validate_run_artifact(artifact, manifest)


def test_03_posix_switch_refused_even_when_empty(exp, request_factory, monkeypatch):
    monkeypatch.setenv("AGENTTALK_DEV_GATE_POSIX_PARALLEL", "")
    with pytest.raises(gate.GateBlock, match="POSIX"):
        request_factory()


def test_04_experiment_artifact_never_votes(exp, request_factory, tmp_path):
    artifact = exp.artifact_header(request_factory())
    assert artifact["artifact_type"] == "agenttalk-windows-workers-preparation-v1"
    assert artifact["authoritative"] is False
    with pytest.raises(gate.GateBlock):
        gate.validate_run_artifact(artifact, _manifest())
    with pytest.raises(gate.GateBlock):
        gate.validate_aggregate_artifact(artifact, _manifest())
    (tmp_path / "trial.json").write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(gate.GateBlock):
        trial.validate_part(tmp_path, {}, _manifest(), "windows/3.12", "source")


@pytest.mark.parametrize("change", ["hash", "probe", "arm", "leg", "missing-gate", "missing-contract"])
def test_05_preflight_refuses_unbound_inputs(exp, request_factory, change):
    options = {}
    if change == "hash":
        data = json.loads(request_factory.record.read_text())
        data["contract_sha256"] = "0" * 64
        request_factory.record.write_text(json.dumps(data), encoding="utf-8")
    elif change in {"probe", "arm", "leg"}:
        options[change] = "linux/3.12" if change == "leg" else "unexpected"
        if change == "probe":
            options["arm"] = None
    else:
        name = "dev-gate.json" if change == "missing-gate" else "dev-gate-experiment.json"
        (request_factory.checkout / name).unlink()
    with pytest.raises(gate.GateBlock):
        request_factory(**options)


def test_05_cli_requires_checkout_and_rejects_extra_flags(exp):
    with pytest.raises(SystemExit):
        exp.parse_args(
            [
                "accept",
                "--arm",
                "serial",
                "--leg",
                "windows/3.12",
                "--modes",
                "source",
                "--record",
                "freeze.json",
                "--output",
                "out",
            ]
        )
    with pytest.raises(SystemExit):
        exp.parse_args(
            [
                "run",
                "--checkout",
                ".",
                "--probe",
                "p10",
                "--arm",
                "serial",
                "--leg",
                "windows/3.12",
                "--modes",
                "source",
                "--record",
                "freeze.json",
                "--output",
                "out",
            ]
        )


def test_06_windows_timeout_is_9000(exp, request_factory, tmp_path):
    req = request_factory()
    paths = {name: tmp_path / name for name in ("source", "imports", "bt", "logs", "records")}
    assert exp.pytest_call(req, "source", Path(sys.executable), paths, {})["timeout_seconds"] == 9000


def test_07_installed_commit_mismatch_refused(exp, request_factory, monkeypatch):
    monkeypatch.setattr(
        exp,
        "installed_identity",
        lambda root: {
            "commit": "d" * 40,
            "version": "1.0",
            "record_sha256": "b" * 64,
        },
    )
    with pytest.raises(gate.GateBlock, match="installed"):
        request_factory()


@pytest.mark.parametrize("proof", [None, {"complete": True}, {"complete": True, "plugins": ["experiment.audit_probe"]}])
def test_08_acceptance_requires_complete_clean_plugin_inventory(exp, proof):
    with pytest.raises(gate.GateBlock):
        exp.validate_inventory(proof, acceptance=True)


def test_08_probe_and_arm_cannot_mix(exp, request_factory):
    with pytest.raises(gate.GateBlock):
        request_factory(arm="serial", probe="p10")


def test_08_acceptance_rejects_probe_files(exp):
    with pytest.raises(gate.GateBlock):
        exp.validate_install(
            {"freeze_sha256": "c" * 64, "probe_files": ["observer.pth"], "gateway_policy": "error"}, "c" * 64
        )


def test_wheel_install_proof_requires_separate_wheel_identity(exp):
    proof = {"freeze_sha256": "c" * 64, "probe_files": [], "gateway_policy": "error"}
    with pytest.raises(gate.GateBlock, match="wheel fingerprint"):
        exp.validate_install(proof, "c" * 64, mode="wheel")


@pytest.mark.parametrize("field", ["argv", "env", "timeout_seconds"])
def test_09_undeclared_call_difference_rejected(exp, request_factory, tmp_path, field):
    req = request_factory()
    paths = {name: tmp_path / name for name in ("source", "imports", "bt", "logs", "records")}
    expected = exp.pytest_call(req, "source", Path(sys.executable), paths, {"Path": "safe"})
    actual = copy.deepcopy(expected)
    if field == "argv":
        actual[field].append("--unexpected")
    elif field == "env":
        actual[field]["EXTRA"] = "1"
    else:
        actual[field] -= 1
    with pytest.raises(gate.GateBlock):
        exp.validate_call(actual, expected)


def test_environment_case_and_only_own_root_are_normalised(exp, tmp_path):
    left = {"argv": [str(tmp_path / "a" / "file")], "env": {"Path": "safe"}, "timeout_seconds": 9000}
    right = {"argv": [str(tmp_path / "b" / "file")], "env": {"PATH": "safe"}, "timeout_seconds": 9000}
    exp.validate_call(right, left, actual_root=tmp_path / "b", expected_root=tmp_path / "a")


def test_contract_hash_is_canonical(exp, request_factory):
    data = request_factory.contract
    reversed_keys = dict(reversed(list(data.items())))
    assert exp.contract_hash(data) == exp.contract_hash(json.loads(json.dumps(reversed_keys, indent=4) + "\r\n"))


def test_production_dependencies_fail_closed(exp, request_factory):
    with pytest.raises(gate.GateBlock, match="P7|P3"):
        exp.production_dependencies(request_factory())


def test_credentialed_proxy_refused_without_echo(exp, request_factory, tmp_path):
    req = request_factory()
    paths = {name: tmp_path / name for name in ("source", "imports", "bt", "logs", "records")}
    supplied = "http://fixture:fixture@127.0.0.1:8080"
    with pytest.raises(gate.GateBlock) as caught:
        exp.pytest_call(req, "source", Path(sys.executable), paths, {"HTTPS_PROXY": supplied})
    assert supplied not in str(caught.value)


def observe_fixture_suite(suite, work, *, exp, request, experimental, mode):
    """Bounded pytest control: record collection marks separately from runtime reports."""
    work.mkdir()
    copy_root = work / "suite"
    shutil.copytree(suite, copy_root)
    (copy_root / "conftest.py").write_text(
        "import json\nfrom pathlib import Path\n"
        "observations = {'collection': [], 'skips': []}\n"
        "def pytest_addoption(parser): parser.addoption('--experiment-record')\n"
        "def pytest_collection_finish(session):\n"
        "    observations['collection'] = [\n"
        "        (i.nodeid, sorted(m.name for m in i.iter_markers())) for i in session.items]\n"
        "def pytest_runtest_logreport(report):\n"
        "    if report.skipped:\n"
        "        reason = str(report.longrepr[-1]).removeprefix('Skipped: ')\n"
        "        observations['skips'].append({'id': report.nodeid, 'phase': report.when, 'reason': reason})\n"
        "def pytest_sessionfinish(session):\n"
        "    observations['lifecycle'] = Path('lifecycle').read_text().splitlines()\n"
        "    Path('observations.json').write_text(json.dumps(observations))\n",
        encoding="utf-8",
    )
    (copy_root / "tests").mkdir()
    (copy_root / "test_fixture.py").rename(copy_root / "tests" / "test_fixture.py")
    paths = {"source": copy_root, "imports": copy_root, "bt": work / "bt", "records": work / "journals"}
    env = gate._base_env(work)
    if experimental:
        argv = exp.pytest_call(request, mode, Path(sys.executable), paths, env)["argv"]
    else:
        spec = request.manifest["checks"]["pytest"]
        argv = gate.isolated_tool_argv(
            sys.executable,
            "pytest",
            *spec["args"],
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(paths["bt"]),
            *spec["paths"],
            candidate_import_root=copy_root if mode == "source" else None,
        )
    outcome = gate.run_command(
        check_id="bounded-control", argv=argv, cwd=copy_root, env=env, timeout_seconds=45, logs_dir=work / "logs"
    )
    assert outcome.status == "pass", outcome.diagnostic
    return json.loads((copy_root / "observations.json").read_text())


@pytest.mark.parametrize("mode", ["source", "wheel"])
def test_01_real_collection_and_runtime_skips_setup_cleanup_match(exp, request_factory, tmp_path, mode):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_fixture.py").write_text(
        "import pytest\nfrom pathlib import Path\n"
        "@pytest.fixture\ndef resource():\n"
        "    Path('lifecycle').open('a').write('setup\\n')\n"
        "    yield\n    Path('lifecycle').open('a').write('cleanup\\n')\n"
        "def test_pass(resource): pass\n"
        "@pytest.mark.skip(reason='collection-mark')\ndef test_mark(): pass\n"
        "def test_body_skip(): pytest.skip('body-skip')\n"
        "@pytest.fixture\ndef unavailable(): pytest.skip('setup-skip')\n"
        "def test_setup_skip(unavailable): pass\n",
        encoding="utf-8",
    )
    observations = [
        observe_fixture_suite(
            suite, tmp_path / arm, exp=exp, request=request_factory(), experimental=arm == "experimental", mode=mode
        )
        for arm in ("ordinary", "experimental")
    ]
    assert observations[0] == observations[1]
    assert len(observations[0]["collection"]) == 4
    assert {row["reason"] for row in observations[0]["skips"]} == {"collection-mark", "body-skip", "setup-skip"}
    assert observations[0]["lifecycle"] == ["setup", "cleanup"]


@pytest.mark.parametrize("mode", ["source", "wheel"])
def test_installer_interface_execution_records_setup_freeze_and_cleanup(exp, request_factory, mode, monkeypatch):
    request = request_factory(modes=(mode,))
    events = []

    def export(binding, destination, archive):
        events.append(destination.name)
        destination.mkdir()

    monkeypatch.setattr(gate, "export_candidate", export)

    class FakeInstaller:
        def prepare(self, request, mode, work):
            events.append("prepare")
            source = work / f"candidate-{mode}"
            checks = [
                c
                for c in exp.partition(request.manifest, request.leg, mode)
                if c not in {"git-binding", "final-binding"} and not c.startswith("pytest-")
            ]
            return exp.PreparedEnvironment(
                Path(sys.executable),
                source,
                source / "src" if mode == "source" else source,
                {"freeze_sha256": "c" * 64, "probe_files": [], "gateway_policy": "error", "wheel_sha256": "d" * 64},
                ["host"] if mode == "source" else ["host", "build", "runtime", "wheel-test"],
                [{"id": c, "status": "pass"} for c in checks],
            )

        def finish(self, prepared):
            events.append("finish")

    class FixtureRecorder:
        def inventory(self, directory):
            events.append("inventory")
            return {"complete": True, "plugins": ["pytest", "experiment_record"]}

    def runner(**kwargs):
        events.append("pytest")
        assert kwargs["check_id"] == f"pytest-{mode}-py312"
        argv = kwargs["argv"]
        Path(argv[argv.index("--basetemp") + 1]).mkdir()
        return SimpleNamespace(status="pass")

    artifact = exp.execute(request, installer=FakeInstaller(), recorder=FixtureRecorder(), runner=runner)
    exports = ["candidate-source"] if mode == "source" else ["candidate-source", "candidate-package", "candidate-wheel"]
    assert events == [*exports, "prepare", "pytest", "inventory", "candidate-static", "finish"]
    assert artifact["status"] == "complete" and artifact["authoritative"] is False
    roles = ["host"] if mode == "source" else ["host", "build", "runtime", "wheel-test"]
    assert artifact["calls"][0]["setup_steps"] == roles
    assert artifact["calls"][0]["cleanup"]["basetemp_removed"] is False
    assert artifact["calls"][0]["cleanup"]["basetemp_present"] is True
    if mode == "wheel":
        assert artifact["calls"][0]["installed_set"]["wheel_sha256"] == "d" * 64
        assert artifact["installed_candidate"]["record_sha256"] == "b" * 64
    assert (request.output / "experiment.json").is_file()


@pytest.mark.parametrize("kind", ["large", "deep", "duplicate", "hard-link", "escape"])
def test_json_input_is_bounded_plain_unambiguous_and_contained(exp, tmp_path, kind):
    root = tmp_path / "config"
    root.mkdir()
    path = root / "input.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    if kind == "large":
        path.write_text(json.dumps({"payload": "a" * exp.MAX_JSON_BYTES}), encoding="utf-8")
    elif kind == "deep":
        path.write_text('{"a":' * 30 + "0" + "}" * 30, encoding="utf-8")
    elif kind == "duplicate":
        path.write_text('{"ok":true,"ok":false}', encoding="utf-8")
    elif kind == "hard-link":
        os.link(path, root / "second-name.json")
    else:
        path = tmp_path / "outside.json"
        path.write_text("{}", encoding="utf-8")
    with pytest.raises(gate.GateBlock):
        exp.read_json(path, within=root)


@pytest.mark.parametrize("change", [None, "editable", "missing-commit", "wrong-version", "source-entry", "record-link"])
def test_installed_distribution_provenance_and_record(exp, tmp_path, monkeypatch, change):
    root = tmp_path / "installed"
    info = root / "agenttalk-1.dist-info"
    info.mkdir(parents=True)
    record = info / "RECORD"
    record.write_text("candidate-fingerprint\n", encoding="utf-8")
    direct = {"vcs_info": {"commit_id": "a" * 40}}
    if change == "editable":
        direct["dir_info"] = {"editable": True}
    elif change == "missing-commit":
        direct = {}
    elif change == "record-link":
        os.link(record, info / "linked-record")
    (info / "direct_url.json").write_text(json.dumps(direct), encoding="utf-8")
    distribution = SimpleNamespace(
        version="2.0" if change == "wrong-version" else "1.0",
        files=[Path("agenttalk-1.dist-info/RECORD"), Path("agenttalk-1.dist-info/direct_url.json")],
        locate_file=lambda path: root / path,
    )
    monkeypatch.setattr(exp.importlib.metadata, "distribution", lambda name: distribution)
    monkeypatch.setattr(
        exp, "__file__", str(tmp_path / "outside.py" if change == "source-entry" else root / "entry.py")
    )
    monkeypatch.setattr(gate, "_committed_version", lambda checkout: "1.0")
    if change is not None:
        with pytest.raises(gate.GateBlock):
            exp.installed_identity(tmp_path)
    else:
        identity = exp.installed_identity(tmp_path)
        assert identity == {
            "commit": "a" * 40,
            "version": "1.0",
            "record_sha256": gate.sha256_bytes(record.read_bytes()),
        }
