"""Deeply nested damaged files must follow the normal parse-error paths."""

import hashlib
import json
from pathlib import Path

import pytest

from agenttalk import cli, doctor, scratch, supervisor, supervisor_lifecycle
from agenttalk.store import Store
from agenttalk.wrapper.session import _session_path as session_path
from agenttalk.wrapper.session import load_session


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


# --- #871: a damaged capacity reading must be skipped and named, never crash ---

CAPACITY_DEPTH = 200000
DEEP_CAPACITY_JSON = "[" * CAPACITY_DEPTH + "]" * CAPACITY_DEPTH


@pytest.fixture(params=["deep", "forced"])
def bad_capacity_json(request, monkeypatch):
    if request.param == "deep":
        try:
            json.loads(DEEP_CAPACITY_JSON)
        except RecursionError:
            return DEEP_CAPACITY_JSON
        pytest.skip("JSON decoder accepts the 200,000-level input on this runtime")
    content = '{"force_recursion": true}'
    original = json.loads

    def loads(value, *args, **kwargs):
        if value == content:
            raise RecursionError("forced decoder failure")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", loads)
    return content


GOOD_READING = {
    "source_agent": "beta",
    "observed_at": "2026-06-09T08:00:00Z",
    "source": "codex_rollout",
    "primary_used_percent": 12.0,
    "confidence": "observed",
}


def _store_with_bad_capacity(tmp_path, content):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    store.write_capacity("beta", GOOD_READING)
    (store.state_dir / "alpha.capacity.json").write_text(content, encoding="utf-8")
    return store


def test_capacity_readers_skip_nested_json(tmp_path, bad_capacity_json):
    store = _store_with_bad_capacity(tmp_path, bad_capacity_json)
    assert store.read_capacity("alpha") is None
    assert store.read_all_capacities() == {"beta": GOOD_READING}
    readings, unreadable = store.read_capacities_checked()
    assert readings == {"beta": GOOD_READING} and unreadable == ["alpha"]


def test_capacity_readers_skip_invalid_text(tmp_path):
    store = _store_with_bad_capacity(tmp_path, "")
    (store.state_dir / "alpha.capacity.json").write_bytes(b"\xff\xfe\x00{")
    assert store.read_capacity("alpha") is None
    assert store.read_capacities_checked() == ({"beta": GOOD_READING}, ["alpha"])


def test_capacity_checked_reader_does_not_report_absent_or_empty(tmp_path):
    store = _store_with_bad_capacity(tmp_path, "")
    assert store.read_capacities_checked() == ({"beta": GOOD_READING}, [])


@pytest.mark.parametrize("as_json", [False, True], ids=["plain", "json"])
def test_status_names_a_nested_capacity_reading(tmp_path, capsys, bad_capacity_json, as_json):
    _store_with_bad_capacity(tmp_path, bad_capacity_json)
    capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "status"] + (["--json"] if as_json else [])) == 0
    output = capsys.readouterr().out
    if as_json:
        payload = json.loads(output)
        rows = {row["name"]: row for row in payload["agents"]}
        assert "capacity" not in rows["alpha"] and "capacity" in rows["beta"]
        output = "\n".join(payload["warnings"])
    assert "capacity reading for alpha could not be read" in output
    assert "capacity reading for beta" not in output


def test_capacity_show_names_a_nested_capacity_reading(tmp_path, capsys, bad_capacity_json):
    _store_with_bad_capacity(tmp_path, bad_capacity_json)
    capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "capacity"]) == 0
    output = capsys.readouterr().out
    assert "beta" in output
    assert "WARN:" in output and "capacity reading for alpha could not be read" in output


def test_capacity_show_with_only_a_nested_reading_still_works(tmp_path, capsys, bad_capacity_json):
    store = Store(tmp_path)
    store.init(["alpha"])
    (store.state_dir / "alpha.capacity.json").write_text(bad_capacity_json, encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "capacity"]) == 0
    output = capsys.readouterr().out
    assert "capacity reading for alpha could not be read" in output


def test_attention_and_dashboard_skip_a_nested_capacity_reading(tmp_path, bad_capacity_json):
    from agenttalk import web

    store = _store_with_bad_capacity(tmp_path, bad_capacity_json)
    assert cli._tripped_capacity_signals(store) == []
    entries = {e["name"]: e for e in web._agent_entries(store, store.load_config(), [], None)}
    assert "capacity" not in entries["alpha"] and "capacity" in entries["beta"]


def _deny_reading(monkeypatch, path, error):
    original = Path.read_text

    def read_text(self, *args, **kwargs):
        if self == path:
            raise error
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)


@pytest.mark.parametrize("as_json", [False, True], ids=["plain", "json"])
def test_an_existing_capacity_file_that_cannot_be_read_is_named(tmp_path, monkeypatch, capsys, as_json):
    store = _store_with_bad_capacity(tmp_path, "{}")
    _deny_reading(monkeypatch, store.state_dir / "alpha.capacity.json", PermissionError("injected denial"))
    assert store.read_capacity("alpha") is None
    assert store.read_capacities_checked() == ({"beta": GOOD_READING}, ["alpha"])
    capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "status"] + (["--json"] if as_json else [])) == 0
    output = capsys.readouterr().out
    if as_json:
        output = "\n".join(json.loads(output)["warnings"])
    assert "capacity reading for alpha could not be read" in output


def test_a_capacity_file_that_vanishes_while_reading_is_just_absent(tmp_path, monkeypatch):
    store = _store_with_bad_capacity(tmp_path, "{}")
    _deny_reading(monkeypatch, store.state_dir / "alpha.capacity.json", FileNotFoundError("gone"))
    assert store.read_capacities_checked() == ({"beta": GOOD_READING}, [])


def test_capacity_show_survives_a_nested_wrapper_session_file(tmp_path, capsys, bad_capacity_json):
    store = Store(tmp_path)
    store.init(["alpha"])
    store.write_capacity("alpha", {"source_agent": "alpha", "source": "codex_rollout"})
    session_path(store, "alpha").write_text(bad_capacity_json, encoding="utf-8")
    assert load_session(store, "alpha", "codex").cli == "codex"  # a damaged file starts a fresh session
    capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "capacity"]) == 0
    assert "alpha" in capsys.readouterr().out


@pytest.mark.parametrize("as_json", [False, True], ids=["plain", "json"])
def test_status_reports_a_nested_supervisor_config(tmp_path, capsys, bad_capacity_json, as_json):
    store = Store(tmp_path)
    store.init(["alpha"])
    (store.dir / "supervisor.json").write_text(bad_capacity_json, encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "status"] + (["--json"] if as_json else [])) == 2
    err = capsys.readouterr().err
    assert "supervisor config is unreadable or invalid" in err
    assert "Traceback" not in err


def test_supervisor_config_loader_reports_nested_json_both_ways(tmp_path, bad_capacity_json):
    path = tmp_path / "supervisor.json"
    path.write_text(bad_capacity_json, encoding="utf-8")
    with pytest.raises(supervisor.SupervisorPersistenceError, match="unreadable or invalid"):
        supervisor.load_supervisor_config(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(supervisor.SupervisorPersistenceError, match="unreadable or invalid"):
        supervisor.load_supervisor_config(path, expected_sha256=digest)


# --- #871 round 2: the file's metadata lookup must not decide "absent" ---


@pytest.mark.parametrize("lookup", ["raises", "says_absent"])
def test_a_capacity_file_whose_metadata_lookup_fails_is_named(tmp_path, monkeypatch, capsys, lookup):
    # Older Pythons let Path.exists raise PermissionError; 3.14 on Windows hides the error and says
    # "absent". Either way the file is there and cannot be read, so it must be named, never crash or vanish.
    store = _store_with_bad_capacity(tmp_path, "{}")
    path = store.state_dir / "alpha.capacity.json"
    _deny_reading(monkeypatch, path, PermissionError("injected denial"))
    original_exists = Path.exists

    def exists(self, *args, **kwargs):
        if self == path:
            if lookup == "raises":
                raise PermissionError("injected stat failure")
            return False
        return original_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists)
    assert store.read_capacity("alpha") is None
    assert store.read_capacities_checked() == ({"beta": GOOD_READING}, ["alpha"])
    capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "status", "--json"]) == 0
    warnings = "\n".join(json.loads(capsys.readouterr().out)["warnings"])
    assert "capacity reading for alpha could not be read" in warnings


# --- #871 round 2: a supervisor STATE file nested too deeply is damaged, like a malformed one ---

MALFORMED = "{not json"
VALID_STATE = {"agents": {"alpha": {"note": "kept"}}}


def _state_paths(tmp_path):
    path = tmp_path / "supervisor-state.json"
    return path, supervisor.supervisor_state_backup_path(path)


def _same_outcome(text):
    """What a message says, without the name of the parser error (JSONDecodeError or RecursionError)."""
    import re

    return re.sub(r"(unreadable or invalid): \w+", r"\1", text)


def _outcome(action, *args):
    try:
        return ("ok", action(*args))
    except supervisor.SupervisorPersistenceError as exc:
        return ("failed closed", _same_outcome(str(exc)))


def _write_state(path, content):
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


@pytest.mark.parametrize("backup", ["valid", "damaged", "missing"])
def test_load_state_treats_a_nested_primary_like_a_malformed_one(tmp_path, bad_capacity_json, backup):
    outcomes = []
    for primary_text in (MALFORMED, bad_capacity_json):
        path, backup_path = _state_paths(tmp_path / ("m" if primary_text == MALFORMED else "d"))
        path.parent.mkdir(parents=True)
        _write_state(path, primary_text)
        if backup == "valid":
            _write_state(backup_path, VALID_STATE)
        elif backup == "damaged":
            _write_state(backup_path, bad_capacity_json)
        outcomes.append(_outcome(supervisor.load_supervisor_state, path))
    assert outcomes[0] == outcomes[1]
    if backup == "valid":
        assert outcomes[1] == ("ok", VALID_STATE)
    else:
        assert outcomes[1][0] == "failed closed" and "supervisor state is unreadable or invalid" in outcomes[1][1]


@pytest.mark.parametrize("backup", ["valid", "damaged"])
def test_load_state_treats_a_nested_backup_like_a_malformed_one(tmp_path, bad_capacity_json, backup):
    outcomes = []
    for backup_text in (MALFORMED, bad_capacity_json):
        path, backup_path = _state_paths(tmp_path / ("m" if backup_text == MALFORMED else "d"))
        path.parent.mkdir(parents=True)
        if backup == "valid":  # a good primary is returned and the damaged backup is never needed
            _write_state(path, VALID_STATE)
        _write_state(backup_path, backup_text)
        outcomes.append(_outcome(supervisor.load_supervisor_state, path))
    assert outcomes[0] == outcomes[1]
    if backup == "valid":
        assert outcomes[1] == ("ok", VALID_STATE)
    else:
        assert (
            outcomes[1][0] == "failed closed" and "supervisor state backup is unreadable or invalid" in outcomes[1][1]
        )


@pytest.mark.parametrize("backup", ["valid", "damaged", "missing"])
def test_save_state_treats_a_nested_primary_like_a_malformed_one(tmp_path, bad_capacity_json, backup):
    new_state = {"agents": {"beta": {}}}
    results = []
    for primary_text in (MALFORMED, bad_capacity_json):
        path, backup_path = _state_paths(tmp_path / ("m" if primary_text == MALFORMED else "d"))
        path.parent.mkdir(parents=True)
        _write_state(path, primary_text)
        if backup == "valid":
            _write_state(backup_path, VALID_STATE)
        elif backup == "damaged":
            _write_state(backup_path, bad_capacity_json)
        outcome = _outcome(supervisor.save_supervisor_state, path, new_state)
        left = {
            "primary": json.loads(path.read_text(encoding="utf-8"))
            if outcome[0] == "ok"
            else path.read_text(encoding="utf-8"),
            "backup_exists": backup_path.exists(),
        }
        results.append((outcome, left["backup_exists"], outcome[0] == "ok" and left["primary"]))
    assert results[0] == results[1]
    if backup == "valid":
        assert results[1][0][0] == "ok" and results[1][2] == new_state
    else:
        assert results[1][0][0] == "failed closed"
        assert "supervisor state is unreadable or invalid" in results[1][0][1]
