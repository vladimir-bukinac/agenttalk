"""Deeply nested damaged files must follow the normal parse-error paths."""

import json
import os
import time

import pytest

from agenttalk import cli, doctor, scratch, supervisor_lifecycle
from agenttalk.store import Store
from agenttalk import store as store_module


DEPTH = 30000
DEEP_JSON = "[" * DEPTH + "]" * DEPTH

try:
    json.loads(DEEP_JSON)
except RecursionError:
    DEEP_DECODER_RAISES = True
else:
    DEEP_DECODER_RAISES = False


@pytest.fixture(params=["deep", "forced"])
def bad_json(request, monkeypatch):
    if request.param == "deep":
        if not DEEP_DECODER_RAISES:
            pytest.skip("JSON decoder accepts the 30,000-level input on this runtime")
        return DEEP_JSON
    content = '{"force_recursion": true}'
    original = json.loads

    def loads(value, *args, **kwargs):
        if value == content:
            raise RecursionError("forced decoder failure")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", loads)
    return content


def test_selection_reader_reports_nested_json(tmp_path, bad_json):
    store = Store(tmp_path)
    store.dir.mkdir(parents=True)
    path = supervisor_lifecycle.selection_path(store)
    path.write_text(bad_json, encoding="utf-8")
    assert path.stat().st_size < 64 * 1024
    with pytest.raises(supervisor_lifecycle.SupervisorLifecycleError, match="selection is malformed"):
        supervisor_lifecycle.read_selected_host_locked(store)


def test_doctor_reports_nested_selection(tmp_path, monkeypatch, bad_json):
    store = Store(tmp_path)
    store.dir.mkdir(parents=True)
    supervisor_lifecycle.selection_path(store).write_text(bad_json, encoding="utf-8")
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    check = doctor._check_powershell_host(store)
    assert check.status == "error" and "selection is malformed" in check.details


def test_config_reader_reports_nested_json(tmp_path, bad_json):
    store = Store(tmp_path)
    store.init(["alpha"])
    store.config_path.write_text(bad_json, encoding="utf-8")
    with pytest.raises(ValueError, match="config"):
        store.load_config()


def test_force_init_repairs_nested_config(tmp_path, monkeypatch, bad_json, capsys):
    store = Store(tmp_path)
    store.init(["alpha"])
    store.config_path.write_text(bad_json, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()
    assert cli.main(["init", "--here", "--agents", "alpha,beta", "--force"]) == 0
    assert json.loads(store.config_path.read_text(encoding="utf-8"))["agents"] == ["alpha", "beta"]


def test_doctor_reports_nested_config(tmp_path, bad_json):
    store = Store(tmp_path)
    store.init(["alpha"])
    store.config_path.write_text(bad_json, encoding="utf-8")
    check = doctor._check_init(store)
    assert check.status == "error" and "config" in check.details
    report = doctor.run(tmp_path)
    assert report.overall == "error"
    assert any(item.name == "store.initialized" and item.status == "error" for item in report.checks)


def test_scratch_config_ignores_nested_json(tmp_path, bad_json):
    store = Store(tmp_path)
    store.init(["alpha"])
    store.config_path.write_text(bad_json, encoding="utf-8")
    assert scratch._read_scratch_config(tmp_path) == {}


@pytest.mark.parametrize("file_kind", ["config", "selection"])
@pytest.mark.parametrize("as_json", [False, True], ids=["plain", "json"])
def test_full_doctor_reports_nested_file(tmp_path, monkeypatch, capsys, bad_json, file_kind, as_json):
    store = Store(tmp_path)
    store.init(["alpha"])
    path = store.config_path if file_kind == "config" else supervisor_lifecycle.selection_path(store)
    path.write_text(bad_json, encoding="utf-8")
    host_check = doctor._check_powershell_host

    def check_as_windows(selected_store):
        with monkeypatch.context() as host_patch:
            host_patch.setattr(doctor.sys, "platform", "win32")
            return host_check(selected_store)

    monkeypatch.setattr(doctor, "_check_powershell_host", check_as_windows)
    capsys.readouterr()
    args = ["--root", str(tmp_path), "doctor"] + (["--json"] if as_json else [])
    assert cli.main(args) == 2
    output = capsys.readouterr().out
    if as_json:
        report = json.loads(output)
        check_name = "store.initialized" if file_kind == "config" else "powershell_host"
        check = next(item for item in report["checks"] if item["name"] == check_name)
        assert check["status"] == "error"
        output = check["details"]
    assert ("config" if file_kind == "config" else "selection is malformed") in output


@pytest.fixture(params=["deep", "forced"])
def lock_json_875(request, monkeypatch):
    original = json.loads
    forced_values = set()

    def loads(value, *args, **kwargs):
        if value in forced_values:
            raise RecursionError("forced lock record decoder failure")
        return original(value, *args, **kwargs)

    if request.param == "forced":
        monkeypatch.setattr(json, "loads", loads)

    def make(pid=None):
        prefix = "" if pid is None else f'"pid": {pid}, '
        value = "{" + prefix + '"nested":' + "[" * 2000 + "]" * 2000 + "}"
        assert len(value.encode("utf-8")) <= 4096
        if request.param == "deep":
            try:
                original(value)
            except RecursionError:
                pass
            else:
                pytest.skip("decoder accepts the bounded deeply nested record")
        else:
            forced_values.add(value)
        return value

    return make


@pytest.mark.parametrize("with_pid", [False, True])
def test_875_reader_follows_damaged_record_path(tmp_path, lock_json_875, with_pid):
    pid = os.getpid() if with_pid else None
    path = tmp_path / "owner.lock"
    path.write_text(lock_json_875(pid), encoding="utf-8")
    found_pid, identity, record = store_module._read_lock_owner(path)
    assert found_pid == pid
    assert identity.st_size <= 4096
    assert record is None


def test_875_prepare_recovery_preserves_both_names(tmp_path, lock_json_875):
    path = tmp_path / "owner.lock"
    alias = tmp_path / "prepare.lock"
    path.write_text(lock_json_875(), encoding="utf-8")
    os.link(path, alias)
    assert store_module._recover_published_prepare_link(path) is False
    assert path.exists() and alias.exists()
    assert os.path.samefile(path, alias)


@pytest.mark.parametrize("kind", ["nested", "damaged"])
@pytest.mark.parametrize("age,live", [(0, False), (60, True), (60, False)])
def test_875_lock_rules_match_damaged_records(tmp_path, lock_json_875, kind, age, live):
    path = tmp_path / "owner.lock"
    pid = os.getpid() if live else None
    if kind == "nested":
        value = lock_json_875(pid)
    else:
        value = f'{{"pid": {pid}, broken' if live else "{broken"
    path.write_text(value, encoding="utf-8")
    timestamp = time.time() - age
    os.utime(path, (timestamp, timestamp))
    store = Store(tmp_path)
    if age and not live:
        with store._exclusive_lock_unordered(path, timeout=1, poll=0.01):
            assert path.exists()
        assert not path.exists()
    else:
        with pytest.raises(store_module.LockContention):
            with store._exclusive_lock_unordered(path, timeout=0.1, poll=0.01):
                pytest.fail("a fresh or live-owner lock was broken")
        assert path.read_text(encoding="utf-8") == value


def test_875_stranded_sweep_leaves_unreadable_owner(tmp_path, lock_json_875):
    path = tmp_path / "owner.lock"
    path.write_text(lock_json_875(os.getpid()), encoding="utf-8")
    store_module._remember_stranded_marker(path, path.stat(), "generation")
    try:
        assert Store(tmp_path).complete_stranded_lock_releases() == 0
        assert path.exists()
    finally:
        store_module._forget_stranded_marker(path, "generation")
