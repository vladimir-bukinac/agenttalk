"""#876: a comprehension document nested too deeply is malformed, exactly like a damaged one.

Every comprehension document is read through ``envelope.strict_json_loads``, which only expected plain damage.
A record nested past what the JSON parser can read used to escape as a bare ``RecursionError``: a traceback from
``scan`` and ``--recover-stale-lock``, and from every other reader of these files. Each reader must now give the
same outcome (error type, exit code, message, recovery advice, what is left on disk) for a too-deep document as
for ``MALFORMED``. The expected value is never written down twice: each test runs the same call over both and
compares. The parser's own detail text is masked, because it differs between Python versions and inputs.

The real 200,000-level document and a decoder forced to fail are both used (as in #863); which Python raises
for what depth differs by version, so the forced variant is the one that is the same everywhere.
"""

import json
import re
import shutil
import subprocess  # nosec B404 - runs git to make a throwaway repository, no shell, no untrusted input
from pathlib import Path

import pytest

from agenttalk import cli
from agenttalk.comprehension import lock as lockmod
from agenttalk.comprehension import paths as pathsmod
from agenttalk.comprehension import publish as pub
from agenttalk.comprehension import scan_pipeline
from agenttalk.comprehension import staging as stg
from agenttalk.comprehension import worker as workermod
from agenttalk.comprehension.envelope import EnvelopeError, read_json_document, strict_json_loads

MALFORMED = "{not json"
DEEP = "[" * 200000 + "]" * 200000
FORCED_TEXT = '{"force_recursion": true}'


@pytest.fixture(params=["deep", "forced"])
def too_deep(request, monkeypatch):
    """The text of a document the JSON decoder cannot read: really 200,000 levels deep, or a decoder made to fail."""
    if request.param == "deep":
        try:
            json.loads(DEEP)
        except RecursionError:
            return DEEP
        pytest.skip("JSON decoder accepts the 200,000-level input on this runtime")
    original = json.loads

    def loads(value, *args, **kwargs):
        if value == FORCED_TEXT:
            raise RecursionError("forced decoder failure")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", loads)
    return FORCED_TEXT


@pytest.fixture(autouse=True)
def _inprocess_worker(monkeypatch):
    monkeypatch.setattr(
        scan_pipeline.worker,
        "run_sanitized_worker",
        lambda root, relative_paths, **_kwargs: workermod.process_paths(root, relative_paths),
    )


def _variants(too_deep):
    return (("malformed", MALFORMED), ("deep", too_deep))


def _scrub(value, *roots):
    """Text with the folders and the parser's own wording masked."""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    for root in roots:
        for form in (str(root), str(root).replace("\\", "\\\\"), str(root).replace("\\", "/")):
            text = text.replace(form, "<root>")
    text = re.sub(r"malformed JSON: [^;\n\"]*", "malformed JSON: <detail>", text)  # up to the advice that follows
    return text


def _outcome(call, *roots):
    """What a call gave: its value, or the type and message of what it raised (a bare RecursionError shows here)."""
    try:
        return ("value", _scrub(call(), *roots))
    except Exception as exc:  # noqa: BLE001 - the type and message are the thing compared
        return ("raised", type(exc).__name__, _scrub(str(exc), *roots))


def _same_for_both(too_deep, make_call, *roots, expect_raised=None):
    """Run ``make_call(text)()`` for the malformed text and for the deep one, in turn; return both and compare."""
    seen = {label: _outcome(make_call(text), *roots) for label, text in _variants(too_deep)}
    assert seen["deep"] == seen["malformed"]
    if expect_raised is not None:  # guard: the comparison is not between two empty successes
        assert seen["malformed"][:2] == ("raised", expect_raised)
    return seen


# --- the shared reader ------------------------------------------------------------------------------------------


def test_strict_json_loads_reports_a_nested_document_as_malformed_json(too_deep):
    seen = {}
    for label, text in _variants(too_deep):
        with pytest.raises(EnvelopeError) as info:
            strict_json_loads(text)
        assert str(info.value).startswith("malformed JSON:")
        seen[label] = (type(info.value).__name__, _scrub(str(info.value)), type(info.value.__cause__).__name__)
    # the same error, and the original parser error is kept as its cause
    assert seen["deep"][:2] == seen["malformed"][:2]
    assert seen["deep"][2] == "RecursionError"


def test_strict_json_loads_still_rejects_a_duplicate_key_and_accepts_valid_input():
    with pytest.raises(EnvelopeError, match="duplicate"):
        strict_json_loads('{"a": 1, "a": 2}')
    assert strict_json_loads('{"a": [1, {"b": null}]}') == {"a": [1, {"b": None}]}


def test_read_json_document_reports_a_nested_file_as_malformed_json(tmp_path, too_deep):
    path = tmp_path / "doc.json"

    def read(text):
        def call():
            path.write_text(text, encoding="utf-8")
            return read_json_document(path)

        return call

    _same_for_both(too_deep, read, tmp_path, expect_raised="EnvelopeError")


# --- the scan lock: fails closed; only confirmed attended recovery clears it ------------------------------------


def _lock_file(comprehension_dir):
    path = comprehension_dir / "scan.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_ordinary_lock_acquisition_refuses_a_nested_record_and_leaves_it_alone(
    comprehension_dir, comprehension_privacy, too_deep
):
    lock_file = _lock_file(comprehension_dir)

    def acquire(text):
        def call():
            lock_file.write_text(text, encoding="utf-8")
            try:
                return lockmod.acquire_scan_lock(
                    comprehension_dir, privacy=comprehension_privacy, predecessor_index_digest=None
                )
            finally:
                assert lock_file.read_bytes() == text.encode("utf-8")  # never taken over, never rewritten

        return call

    seen = _same_for_both(too_deep, acquire, comprehension_dir, expect_raised="ScanLockUnrecoverable")
    assert "scan.lock record is malformed" in seen["deep"][2]
    assert "--recover-stale-lock" in seen["deep"][2]  # the recovery advice is the malformed record's


def test_releasing_a_lock_whose_record_became_nested_refuses_and_keeps_the_file(
    comprehension_dir, comprehension_privacy, too_deep
):
    handle = lockmod.acquire_scan_lock(comprehension_dir, privacy=comprehension_privacy, predecessor_index_digest=None)

    def release(text):
        def call():
            handle.path.write_text(text, encoding="utf-8")
            try:
                return lockmod.release_scan_lock(handle)
            finally:
                assert handle.path.read_bytes() == text.encode("utf-8")  # not deleted

        return call

    seen = _same_for_both(too_deep, release, comprehension_dir, expect_raised="ScanLockUnrecoverable")
    assert "could not be read at release time" in seen["deep"][2]


def test_confirmed_recovery_clears_a_nested_record_and_returns_the_unreadable_sentinel(comprehension_dir, too_deep):
    lock_file = _lock_file(comprehension_dir)

    def recover(text):
        def call():
            lock_file.write_text(text, encoding="utf-8")
            try:
                return lockmod.recover_stale_lock(comprehension_dir)
            finally:
                assert not lock_file.exists()

        return call

    seen = _same_for_both(too_deep, recover, comprehension_dir)
    assert seen["deep"][0] == "value" and "record_unreadable" in seen["deep"][1]


# --- the scan command over a nested lock record -----------------------------------------------------------------


def _repo(root: Path) -> Path:
    """A throwaway git repository with a store ignored by git and one small Java file."""
    root.mkdir(parents=True, exist_ok=True)
    for argv in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True)  # noqa: S603,S607  # nosec B603 B607
    (root / ".gitignore").write_text(".agenttalk/\n", encoding="utf-8")
    app = root / "src" / "main" / "java" / "p"
    app.mkdir(parents=True)
    (app / "App.java").write_text(
        "package p;\nclass App {\n  public static void main(String[] a) {}\n}\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def need_git():
    if shutil.which("git") is None:
        pytest.skip("git is required for comprehension fixtures")


def _comp_dir(root):
    return pathsmod.comprehension_dir(root / ".agenttalk")


def _cli(root, argv, capsys):
    capsys.readouterr()
    code = cli.main(["--root", str(root), *argv])
    captured = capsys.readouterr()
    return code, _scrub(captured.out, root), _scrub(captured.err, root)


@pytest.mark.parametrize(
    "argv",
    [["comprehension", "scan"], ["comprehension", "scan", "--recover-stale-lock"]],
    ids=["scan", "recover-unconfirmed"],
)
def test_scan_refuses_a_nested_lock_record_like_a_malformed_one_and_leaves_it(
    tmp_path, capsys, need_git, too_deep, argv, monkeypatch
):
    monkeypatch.delenv("AGENTTALK_SELF", raising=False)
    repo = _repo(tmp_path)
    lock_file = _lock_file(_comp_dir(repo))
    seen = {}
    for label, text in _variants(too_deep):
        lock_file.write_text(text, encoding="utf-8")
        seen[label] = _cli(repo, argv, capsys)
        assert lock_file.read_bytes() == text.encode("utf-8")  # the record stays; nothing was taken over
    assert seen["deep"] == seen["malformed"]
    assert seen["malformed"][0] == 2  # the refusal exit, not a traceback
    assert "malformed" in seen["malformed"][2] or "AGENTTALK_SELF" in seen["malformed"][2]


def test_scan_with_confirmed_recovery_clears_a_nested_record_and_traces_it(
    tmp_path, capsys, need_git, too_deep, monkeypatch
):
    monkeypatch.setattr(cli, "_comprehension_confirm_attended", lambda prompt_lines: True)
    seen = {}
    for label, text in _variants(too_deep):
        repo = _repo(tmp_path / label)
        lock_file = _lock_file(_comp_dir(repo))
        lock_file.write_text(text, encoding="utf-8")
        code, out, err = _cli(repo, ["comprehension", "scan", "--recover-stale-lock"], capsys)
        status = scan_pipeline.get_status(repo)
        problems = json.loads(
            (pathsmod.run_dir(_comp_dir(repo), status["latest_scan_id"]) / "problems.json").read_text(encoding="utf-8")
        )["problems"]
        trace = [p["detail"] for p in problems if p["reason_code"] == "scan_lock_forcibly_recovered"]
        seen[label] = (code, _scrub(err, repo), lock_file.exists(), [_scrub(t, repo) for t in trace])
    assert seen["deep"] == seen["malformed"]
    assert seen["deep"][0] == 0 and seen["deep"][2] is False
    assert len(seen["deep"][3]) == 1 and "pid unknown" in seen["deep"][3][0]


# --- staging owner record ---------------------------------------------------------------------------------------


def test_reclaim_retains_a_staging_directory_whose_owner_record_is_nested(tmp_path, too_deep):
    owner = tmp_path / ".staging" / "scan-x-abcdef" / "owner.json"
    owner.parent.mkdir(parents=True)

    def reclaim(text):
        def call():
            owner.write_text(text, encoding="utf-8")
            report = stg.reclaim_abandoned_staging(tmp_path)
            assert owner.parent.exists()  # retained, never deleted
            return (report.reclaimed, report.retained)

        return call

    seen = _same_for_both(too_deep, reclaim, tmp_path)
    assert seen["deep"][0] == "value" and "missing or malformed" in seen["deep"][1]


def test_prune_staging_command_reports_a_nested_owner_record_as_retained(tmp_path, capsys, need_git, too_deep):
    repo = _repo(tmp_path)
    owner = _comp_dir(repo) / ".staging" / "scan-x-abcdef" / "owner.json"
    owner.parent.mkdir(parents=True)
    seen = {}
    for label, text in _variants(too_deep):
        owner.write_text(text, encoding="utf-8")
        seen[label] = _cli(repo, ["comprehension", "prune", "--staging"], capsys)
    assert seen["deep"] == seen["malformed"]
    assert seen["deep"][0] == 0 and "missing or malformed" in seen["deep"][1]


def test_publishing_refuses_a_staging_directory_whose_owner_record_is_nested(
    comprehension_dir, comprehension_privacy, too_deep
):
    lock = lockmod.acquire_scan_lock(comprehension_dir, privacy=comprehension_privacy, predecessor_index_digest=None)
    staging = stg.create_staging_dir(scan_id="scan-1", lock_handle=lock)
    (staging.path / "scan.json").write_text("x", encoding="utf-8")

    def publish(text):
        def call():
            (staging.path / "owner.json").write_text(text, encoding="utf-8")
            try:
                return pub.rename_staging_to_run(staging, lock)
            finally:
                assert staging.path.exists()  # nothing was published

        return call

    _same_for_both(too_deep, publish, comprehension_dir, expect_raised="StagingSourceEscapesRoot")


# --- the current index ------------------------------------------------------------------------------------------


def test_reading_the_current_index_reports_a_nested_one_as_malformed(tmp_path, too_deep):
    index = tmp_path / "index.json"

    def read(text):
        def call():
            index.write_text(text, encoding="utf-8")
            return pub.read_current_index(tmp_path)

        return call

    _same_for_both(too_deep, read, tmp_path, expect_raised="EnvelopeError")


def test_the_index_update_refuses_and_cleans_up_when_the_index_is_nested(tmp_path, too_deep):
    index = tmp_path / "index.json"

    def update(text):
        def call():
            index.write_text(text, encoding="utf-8")
            try:
                return pub.publish_index_cas(
                    tmp_path, scan_id="scan-1", run_summary={"scan_id": "scan-1"}, predecessor_index_digest=None
                )
            finally:
                assert index.read_bytes() == text.encode("utf-8")  # the index is left as it was
                assert sorted(p.name for p in tmp_path.iterdir()) == ["index.json"]  # no temporary file left

        return call

    _same_for_both(too_deep, update, tmp_path, expect_raised="EnvelopeError")


def test_the_index_update_refuses_and_cleans_up_when_the_index_becomes_nested_before_the_swap(
    tmp_path, too_deep, monkeypatch
):
    index = tmp_path / "index.json"
    real = pub.read_current_index

    def update(text):
        calls = []

        def second_read_sees_the_bad_text(directory):
            calls.append(1)
            if len(calls) == 2:  # the re-read just before the replace
                index.write_text(text, encoding="utf-8")
            return real(directory)

        def call():
            index.unlink(missing_ok=True)
            monkeypatch.setattr(pub, "read_current_index", second_read_sees_the_bad_text)
            try:
                return pub.publish_index_cas(
                    tmp_path, scan_id="scan-1", run_summary={"scan_id": "scan-1"}, predecessor_index_digest=None
                )
            finally:
                assert len(calls) == 2
                assert sorted(p.name for p in tmp_path.iterdir()) == ["index.json"]  # the temporary file is cleaned

        return call

    _same_for_both(too_deep, update, tmp_path, expect_raised="EnvelopeError")


@pytest.mark.parametrize("command", ["status", "report", "validate"])
def test_read_commands_report_a_nested_index_like_a_malformed_one(tmp_path, capsys, need_git, too_deep, command):
    repo = _repo(tmp_path)
    scan_pipeline.run_scan(repo)
    index = pathsmod.index_path(_comp_dir(repo))
    seen = {}
    for label, text in _variants(too_deep):
        index.write_text(text, encoding="utf-8")
        seen[label] = _cli(repo, ["comprehension", command], capsys)
    assert seen["deep"] == seen["malformed"]
    assert seen["deep"][0] == 2 and "malformed JSON" in seen["deep"][2]


def test_a_new_scan_over_a_nested_index_refuses_and_leaves_no_lock_or_staging(tmp_path, capsys, need_git, too_deep):
    repo = _repo(tmp_path)
    scan_pipeline.run_scan(repo)
    comp = _comp_dir(repo)
    index = pathsmod.index_path(comp)
    seen = {}
    for label, text in _variants(too_deep):
        index.write_text(text, encoding="utf-8")
        code, out, err = _cli(repo, ["comprehension", "scan"], capsys)
        staging = comp / ".staging"
        seen[label] = (
            code,
            out,
            err,
            (comp / "scan.lock").exists(),
            sorted(p.name for p in staging.iterdir()) if staging.exists() else [],
            sorted(p.name for p in (comp / "runs").iterdir()),
            index.read_bytes() == text.encode("utf-8"),
        )
    assert seen["deep"] == seen["malformed"]
    assert seen["deep"][0] == 2 and seen["deep"][3] is False and seen["deep"][6] is True


# --- the artifacts of a run -------------------------------------------------------------------------------------


@pytest.mark.parametrize("artifact", ["scan.json", "modules.json"])
def test_commands_report_a_nested_run_artifact_like_a_malformed_one(tmp_path, capsys, need_git, too_deep, artifact):
    repo = _repo(tmp_path)
    outcome = scan_pipeline.run_scan(repo)
    target = outcome.run_dir / artifact
    original = target.read_bytes()
    seen = {}
    for label, text in _variants(too_deep):
        target.write_text(text, encoding="utf-8")
        seen[label] = {
            command: _cli(repo, ["comprehension", command, "--run", outcome.scan_id, *extra], capsys)
            for command, extra in (("status", []), ("report", []), ("validate", ["--json"]))
        }
        target.write_bytes(original)
    assert seen["deep"] == seen["malformed"]
    for command, (_code, _out, err) in seen["deep"].items():
        assert "RecursionError" not in err, command
    # at least the readers of this artifact refuse (or report the run invalid) rather than succeed
    assert any(code != 0 for code, _out, _err in seen["malformed"].values())


def test_the_run_artifact_loader_names_the_run_and_the_unreadable_artifact(tmp_path, need_git, too_deep):
    repo = _repo(tmp_path)
    outcome = scan_pipeline.run_scan(repo)
    target = outcome.run_dir / "scan.json"

    def load(text):
        def call():
            target.write_text(text, encoding="utf-8")
            return scan_pipeline.get_status(repo, run_id=outcome.scan_id)

        return call

    seen = _same_for_both(too_deep, load, repo, expect_raised="ComprehensionError")
    assert "scan.json could not be read" in seen["deep"][2]
