"""The experiment recorder: durable, per-process journals of what a pytest run did (audit step P3).

The recorder is a pytest plugin that exists only on request.  `tests/conftest.py` calls `add_option` and
`configure`; with `--experiment-record=DIR` absent (and no nested-run handoff, below) `configure` registers
nothing, so there are no hooks and no files.  The reducer, `reduce_journals`, reads the journals back and checks
them against the serial collection.  JUnit XML and `user_properties` are a convenience only, never the evidence.

Write the option as `--experiment-record=DIR`, one argument.  Given as two arguments, the folder looks like a path
argument once it exists, pytest counts it when it looks for the rootdir (when no ini file fixes it), the workers
get another rootdir than the controller, and their node ids no longer match the serial collection's.

Security note (docs/SECURE-CODING.md, written before the code).  Boundaries: the folder named on the command line or
in the nested handoff; node ids, skip reasons and error text from the tests; the journal files the reducer reads.
S3: the folder is resolved and must not lie inside any basetemp (pytest would delete it); a journal is created
exclusively (never reusing or following an existing name) and checked on the opened file; the reducer opens without
waiting and checks on the opened file that it is a plain file with one name.  S7: every refusal says which input was
bad; nothing is swallowed.  S8: error text is cut at 64 KiB, reasons at 4 KiB, the handoff is limited to 4 KiB and a
journal read to 64 MiB; a refusal closes what it opened.  S9: JSON only.  S1: a node id or an error text is data.

Journal files
-------------
One journal per process, `journal-<role>-<pid>-<started_ms>.jsonl` in the record folder.  `role` is `serial` (no
xdist), `controller` (the xdist controller), `worker` (an xdist worker) or `nested` (the main process of a nested
pytest run that was started through `nested_environment`).  `started_ms` is the wall time, in milliseconds, at which
the recorder started in that process (the nearest portable stand-in for the process start time); together with the
pid it keeps a reused pid from colliding.  The file is created exclusively, held open for appending by one handle,
and `os.fsync` is called on it after every line.  A process that dies loses at most the line in flight; a torn last
line is possible and the reducer reports it.  The claim stops there: a killed process proves the records survive the
process, not a power or storage failure.

Each line is one JSON object, UTF-8, `ensure_ascii=False`, keys sorted.  Read a journal by splitting on "\\n" only
(U+2028 can appear inside a string).  A lone surrogate is written as a `\\udXXX` escape.

Common fields of every record
-----------------------------
v                 schema version, 1.
seq               1, 2, 3, ... with no gap, per journal.
kind              the event kind, below.
role, worker      the process role; the xdist worker id (`gw0`) for a worker, else null.
pid               the process id.
t_wall, t_mono    `time.time()` and `time.monotonic()` when the record was written.

Event kinds and their fields
----------------------------
process-start     first record.  started_ms (int); python, pytest (version strings); dist (the `--dist` value) and
                  loadgroup (bool: group suffixes are expected in node ids); plugins (sorted list of the names of
                  the plugins loaded in this process, without conftest paths and without unnamed plugins: the D06
                  inventory); nested_token and parent_pid (for a nested run and its workers, else null).
collection-finish count (items collected), raw_ids_sha256 (SHA-256 over the raw ids joined by "\\n"),
                  digest_algorithm ("sha256").  Not written by an xdist controller.
item-start        nodeid (the raw node id, with the `@group` suffix xdist adds), requested_group (the xdist_group
                  marker's name or null), effective_group (the group when the raw id ends with `@<group>`, else
                  null), suffix_missing (bool: a group was requested but the raw id lacks its suffix).
phase             one per setup/call/teardown report: nodeid, when ("setup", "call", "teardown", or "???" for the
                  controller's report of a crashed worker), outcome ("passed", "failed", "skipped"), duration,
                  reason (skip or xfail reason, bounded, else null), xfail (bool).  A failed phase also carries
                  the error fields below.  The controller writes only the "???" report, never the workers' phases.
item-end          nodeid, elapsed (monotonic seconds since item-start).
collection-error  a failed collection report: nodeid and the error fields.
internal-error    `pytest_internalerror`: the error fields.
worker-down       controller only, xdist's `pytest_testnodedown`: down_worker (the worker id), has_error (bool); the
                  error fields when has_error.
nested-launch     written by `nested_environment`: token (16 hex digits) for the nested run it prepares.
exit-status       at session finish: exitstatus (int).  0 and 1 are not errors; any other value is.
trailer           last record: complete (true), records (how many records came before it), exitstatus, plugins.

Error fields (on phase, collection-error, internal-error, worker-down)
-----------------------------------------------------------------------
error_text            the text, cut to at most 64 KiB (MAX_ERROR_TEXT) of UTF-8.
error_truncated       true when the text was cut.
error_length          the length in UTF-8 bytes of the full text.
error_digest          SHA-256 over the UTF-8 bytes of `str(report.longrepr)` (the full text, not the cut one),
                      lowercase hex.  A lone surrogate is encoded as a backslash escape first.
error_digest_algorithm  "sha256": the record names the algorithm.

The reducer
-----------
`reduce_journals(folder, expected_ids=None, nested_seen=None)` returns a dict:

schema            1.
status            "complete" when every journal ends with its trailer, else "incomplete".
accepted          true only when status is "complete", there is no problem and no error record.  A failing test
                  does not by itself stop acceptance; it is reported in first_failure.
problems          a list of {"kind", "detail", ...}; at most 20 per kind are listed, problem_counts has the totals.
                  Kinds: journal-not-plain, journal-too-large, bad-encoding, torn-last-line, bad-line,
                  sequence-gap, no-process-start, plugin-inventory-missing, no-trailer, records-after-trailer,
                  item-unfinished, suffix-missing, group-split, duplicate-id, missing-id, unexpected-id,
                  nested-journal-missing, nested-journal-unlaunched.
first_error       the earliest error record (collection-error, internal-error, worker-down with an error,
                  exit-status other than 0 or 1) across all journals, ordered by t_wall, journal name, seq; or
                  null.  Nothing written later, a trailer included, replaces it.
first_failure     the earliest failed phase, the same way, or null.
processes         per journal: file, role, worker, pid, complete, records, plugins, exitstatus, nested_token.
items             canonical id -> {started, ended, workers, group}, from serial/worker journals (nested runs are
                  separate).  The canonical id is the raw id minus a trailing `@<requested group>`, removed only
                  when it equals that suffix (`canonical_id`).
groups            effective group -> sorted worker ids that started its members.
nested            {"launched": launches written, "journaled": launches that have a nested journal}.

When `expected_ids` (the serial collection's ids) is given, the join must be one to one: each expected id started
exactly once.  A serial run is a one-worker run.

Nested pytest runs
------------------
A nested run is recorded only through an explicit handoff that the recorder alone sets, for the one process it
starts: `nested_environment(env)` returns a copy of `env` with `HANDOFF_ENV` (a JSON object with v, dir, token,
parent_pid) and writes a `nested-launch` record.  The recorder never puts the variable into its own environment, and
a nested run removes it from its own, so ordinary nested runs do not inherit it.  Without an active recorder the
helper hands off nothing.  A launch with no nested journal is a failure (`nested-journal-missing`), never
compliance; so is `nested_seen` larger than the number of nested journals.  Workers get the folder through
xdist's `workerinput`, never through the environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

SCHEMA_VERSION = 1
OPTION = "--experiment-record"
PLUGIN_NAME = "agenttalk-experiment-record"
HANDOFF_ENV = "AGENTTALK_EXPERIMENT_RECORD_HANDOFF"
MAX_ERROR_TEXT = 64 * 1024
MAX_REASON_TEXT = 4096
MAX_HANDOFF_BYTES = 4096
MAX_JOURNAL_BYTES = 64 * 1024 * 1024
MAX_PROBLEMS_PER_KIND = 20
DIGEST_ALGORITHM = "sha256"

_TOKEN = re.compile(r"[0-9a-f]{16}")
_ACTIVE: Recorder | None = None


def add_option(parser: pytest.Parser) -> None:
    parser.addoption(
        OPTION,
        dest="experiment_record",
        default=None,
        metavar="DIR",
        help="record what this run did in durable per-process journals in DIR (outside every basetemp)",
    )


def canonical_id(raw_id: str, requested_group: str | None) -> str:
    """The raw id minus xdist's `@<group>` suffix, removed only when it equals the requested group."""
    if requested_group:
        suffix = "@" + requested_group
        if raw_id.endswith(suffix):
            return raw_id[: -len(suffix)]
    return raw_id


def _encode(text: str) -> bytes:
    return text.encode("utf-8", "backslashreplace")


def _bounded(text: str, limit: int) -> tuple[str, bool, str, int]:
    """(kept text, truncated, SHA-256 hex of the full text, full length in bytes)."""
    data = _encode(text)
    kept = data[:limit].decode("utf-8", "ignore") if len(data) > limit else data.decode("utf-8")
    return kept, len(data) > limit, hashlib.sha256(data).hexdigest(), len(data)


def _error_fields(text: str) -> dict[str, Any]:
    kept, truncated, digest, length = _bounded(text, MAX_ERROR_TEXT)
    return {
        "error_text": kept,
        "error_truncated": truncated,
        "error_length": length,
        "error_digest": digest,
        "error_digest_algorithm": DIGEST_ALGORITHM,
    }


def _requested_group(item: pytest.Item) -> str | None:
    """The group name xdist uses for this item (the same rule as xdist's own collection hook)."""
    mark = item.get_closest_marker("xdist_group")
    if mark is None:
        return None
    return str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))


def open_journal(directory: Path, role: str, pid: int, started_ms: int) -> tuple[Path, int]:
    """Create the journal exclusively and return (path, file descriptor); an existing name is never reused."""
    path = Path(directory) / f"journal-{role}-{pid}-{started_ms}.jsonl"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError(f"{path} is not a plain file with a single name")
    except BaseException:
        os.close(fd)
        raise
    return path, fd


class Recorder:
    """The plugin: one journal for this process, one line per event."""

    def __init__(
        self,
        config: pytest.Config,
        directory: Path,
        role: str,
        worker: str | None,
        token: str | None,
        parent_pid: int | None,
        distributed: bool = False,
    ) -> None:
        self.config = config
        self.distributed = distributed  # an xdist controller: the workers' journals hold the phases
        self.directory = directory
        self.role = role
        self.worker = worker
        self.token = token
        self.parent_pid = parent_pid
        self.pid = os.getpid()
        self.started_ms = int(time.time() * 1000)
        self.seq = 0
        self.path, self._fd = open_journal(directory, role, self.pid, self.started_ms)
        self._closed = False

    # -- writing ----------------------------------------------------------------------------------------------

    def append(self, kind: str, **fields: Any) -> None:
        self.seq += 1
        record = {
            "v": SCHEMA_VERSION,
            "seq": self.seq,
            "kind": kind,
            "role": self.role,
            "worker": self.worker,
            "pid": self.pid,
            "t_wall": time.time(),
            "t_mono": time.monotonic(),
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        view = memoryview(_encode(line))
        while view:
            view = view[os.write(self._fd, view) :]
        os.fsync(self._fd)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            os.close(self._fd)

    # -- start ------------------------------------------------------------------------------------------------

    def start(self) -> None:
        option = self.config.option
        self.append(
            "process-start",
            started_ms=self.started_ms,
            python=sys.version.split()[0],
            pytest=pytest.__version__,
            dist=getattr(option, "dist", None),
            loadgroup=bool(getattr(option, "loadgroup", False)),
            plugins=self._plugins(),
            nested_token=self.token,
            parent_pid=self.parent_pid,
        )

    def _plugins(self) -> list[str]:
        names = (name for name, plugin in self.config.pluginmanager.list_name_plugin() if plugin is not None)
        return sorted(n for n in names if not n.isdigit() and not any(c in n for c in "/\\:"))

    # -- collection -------------------------------------------------------------------------------------------

    @pytest.hookimpl(trylast=True)  # after conftest.py's workaround that copies xdist's group suffix
    def pytest_collection_finish(self, session: pytest.Session) -> None:
        ids = [item.nodeid for item in session.items]
        self.append(
            "collection-finish",
            count=len(ids),
            digest_algorithm=DIGEST_ALGORITHM,
            raw_ids_sha256=hashlib.sha256(_encode("\n".join(ids))).hexdigest(),
        )

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.append("collection-error", nodeid=report.nodeid, **_error_fields(str(report.longrepr)))

    # -- running ----------------------------------------------------------------------------------------------

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: pytest.Item, nextitem: pytest.Item | None):
        raw = item.nodeid
        group = _requested_group(item)
        suffixed = group is not None and raw.endswith("@" + group)
        started = time.monotonic()
        self.append(
            "item-start",
            nodeid=raw,
            requested_group=group,
            effective_group=group if suffixed else None,
            suffix_missing=group is not None and not suffixed,
        )
        yield  # the outcome is never read, so an exception from another hook propagates unchanged
        self.append("item-end", nodeid=raw, elapsed=time.monotonic() - started)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if self.distributed and report.when != "???":
            return  # the workers' own journals hold their phases
        extra: dict[str, Any] = {}
        reason = getattr(report, "wasxfail", None)
        if reason is None and report.skipped and isinstance(report.longrepr, tuple):
            reason = report.longrepr[2]
        if report.failed:
            extra.update(_error_fields(str(report.longrepr)))
        self.append(
            "phase",
            nodeid=report.nodeid,
            when=report.when,
            outcome=report.outcome,
            duration=report.duration,
            reason=None if reason is None else _bounded(str(reason), MAX_REASON_TEXT)[0],
            xfail=hasattr(report, "wasxfail"),
            **extra,
        )

    # -- errors -----------------------------------------------------------------------------------------------

    @pytest.hookimpl(tryfirst=True)  # a first-result hook on some pytest versions: ask the recorder before others
    def pytest_internalerror(self, excrepr: Any, excinfo: Any = None) -> None:
        self.append("internal-error", **_error_fields(str(excrepr)))

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node: Any, error: Any) -> None:
        fields = _error_fields(str(error)) if error else {}
        self.append("worker-down", down_worker=node.gateway.id, has_error=bool(error), **fields)

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node: Any) -> None:
        node.workerinput["experiment_record_dir"] = str(self.directory)
        node.workerinput["experiment_record_token"] = self.token
        node.workerinput["experiment_record_parent_pid"] = self.parent_pid

    # -- finish -----------------------------------------------------------------------------------------------

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        self.append("exit-status", exitstatus=int(exitstatus))
        self.append("trailer", complete=True, records=self.seq - 1, exitstatus=int(exitstatus), plugins=self._plugins())

    def pytest_unconfigure(self, config: pytest.Config) -> None:
        global _ACTIVE
        if _ACTIVE is self:
            _ACTIVE = None
        self.close()

    # -- nested runs ------------------------------------------------------------------------------------------

    def handoff(self, env: dict[str, str]) -> dict[str, str]:
        token = secrets.token_hex(8)
        self.append("nested-launch", token=token)
        env[HANDOFF_ENV] = json.dumps(
            {"v": SCHEMA_VERSION, "dir": str(self.directory), "token": token, "parent_pid": self.pid}, sort_keys=True
        )
        return env


def nested_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of `env` (default: the environment) for ONE nested pytest process the caller starts.

    With an active recorder it carries the handoff and a `nested-launch` record is written; otherwise any stale
    handoff is dropped and nothing is handed off.  Names are compared without regard to case (Windows)."""
    result = dict(os.environ if env is None else env)
    for name in [n for n in result if n.upper() == HANDOFF_ENV]:
        del result[name]
    return _ACTIVE.handoff(result) if _ACTIVE is not None else result


# -- wiring ---------------------------------------------------------------------------------------------------


def _basetemps(config: pytest.Config) -> set[Path]:
    found: set[Path] = set()
    given = config.option.basetemp
    if given:
        found.add(Path(os.path.abspath(given)).resolve())
    factory = getattr(config, "_tmp_path_factory", None)
    if factory is not None:
        basetemp = Path(factory.getbasetemp()).resolve()
        found.add(basetemp)
        if not given:
            found.add(basetemp.parent)  # pytest-of-<user>: older numbered folders there are deleted too
    return found


def _checked_directory(config: pytest.Config, text: str, *, create: bool, source: str) -> Path:
    path = Path(text)
    if not path.is_absolute():
        path = Path(config.invocation_params.dir) / path
    resolved = path.resolve()
    for basetemp in _basetemps(config):
        if resolved == basetemp or basetemp in resolved.parents:
            raise pytest.UsageError(
                f"{source}: the record folder {resolved} is inside the basetemp {basetemp}, where pytest would "
                f"delete it; give a folder outside every basetemp"
            )
    if create:
        resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        raise pytest.UsageError(f"{source}: the record folder {resolved} is not an existing folder")
    return resolved


def _read_handoff(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8", "replace")) > MAX_HANDOFF_BYTES:
        raise pytest.UsageError(f"{HANDOFF_ENV} is too long")
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        raise pytest.UsageError(f"{HANDOFF_ENV} is not valid JSON") from None
    if not isinstance(data, dict) or data.get("v") != SCHEMA_VERSION:
        raise pytest.UsageError(f"{HANDOFF_ENV} is not a version {SCHEMA_VERSION} handoff object")
    token, directory, parent = data.get("token"), data.get("dir"), data.get("parent_pid")
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise pytest.UsageError(f"{HANDOFF_ENV} has a bad token")
    if not isinstance(directory, str) or not os.path.isabs(directory):
        raise pytest.UsageError(f"{HANDOFF_ENV} needs an absolute folder")
    if not isinstance(parent, int) or isinstance(parent, bool):
        raise pytest.UsageError(f"{HANDOFF_ENV} has a bad parent_pid")
    return data


def configure(config: pytest.Config) -> Recorder | None:
    """Register the recorder if this process was asked to record; otherwise do nothing at all."""
    global _ACTIVE
    existing = config.pluginmanager.get_plugin(PLUGIN_NAME)
    if existing is not None:
        return existing
    workerinput = getattr(config, "workerinput", None)
    handoff_text = None
    for name in [n for n in os.environ if n.upper() == HANDOFF_ENV]:
        handoff_text = os.environ.pop(name)  # a recorded process never passes the handoff on by accident
    token = parent = None
    if workerinput is not None:
        if not workerinput.get("experiment_record_dir"):
            return None
        directory = _checked_directory(
            config, workerinput["experiment_record_dir"], create=False, source="xdist workerinput"
        )
        role, worker, distributed = "worker", str(workerinput["workerid"]), False
        token, parent = workerinput.get("experiment_record_token"), workerinput.get("experiment_record_parent_pid")
    elif config.option.experiment_record:
        directory = _checked_directory(config, config.option.experiment_record, create=True, source=OPTION)
        numprocesses = getattr(config.option, "numprocesses", None)
        role, worker, distributed = ("controller" if numprocesses else "serial"), None, bool(numprocesses)
    elif handoff_text is not None:
        data = _read_handoff(handoff_text)
        directory = _checked_directory(config, data["dir"], create=False, source=HANDOFF_ENV)
        role, worker, token, parent = "nested", None, data["token"], data["parent_pid"]
        distributed = bool(getattr(config.option, "numprocesses", None))
    else:
        return None
    recorder = Recorder(config, directory, role, worker, token, parent, distributed)
    try:
        config.pluginmanager.register(recorder, PLUGIN_NAME)
        recorder.start()
    except BaseException:
        recorder.close()
        raise
    _ACTIVE = recorder
    return recorder


# -- the reducer ----------------------------------------------------------------------------------------------


class _Problems:
    def __init__(self) -> None:
        self.listed: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()

    def add(self, kind: str, detail: str, **extra: Any) -> None:
        self.counts[kind] += 1
        if self.counts[kind] <= MAX_PROBLEMS_PER_KIND:
            self.listed.append({"kind": kind, "detail": detail, **extra})


def _read_journal(path: Path, problems: _Problems) -> list[dict[str, Any]] | None:
    """The journal's records, or None when the file is refused.  Opens without waiting; checks the open file."""
    no_wait = getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        with open(path, "rb", opener=lambda p, flags: os.open(p, flags | no_wait)) as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                problems.add("journal-not-plain", "the journal must be a plain file with a single name", file=path.name)
                return None
            data = handle.read(MAX_JOURNAL_BYTES + 1)
    except OSError as error:
        problems.add("journal-not-plain", f"cannot open the journal: {error}", file=path.name)
        return None
    if len(data) > MAX_JOURNAL_BYTES:
        problems.add("journal-too-large", f"the journal is over {MAX_JOURNAL_BYTES} bytes", file=path.name)
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        problems.add("bad-encoding", "the journal is not valid UTF-8", file=path.name)
        return None
    lines = text.split("\n")
    last = lines.pop()
    if last:
        problems.add("torn-last-line", "the last line has no end; its process died while writing", file=path.name)
    found = []
    for number, line in enumerate(lines, 1):
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            record = None
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("seq"), int)
            or not isinstance(record.get("kind"), str)
        ):
            problems.add("bad-line", f"line {number} is not a record", file=path.name)
            continue
        found.append(record)
    return found


def reduce_journals(
    folder: str | os.PathLike[str], expected_ids: Sequence[str] | None = None, nested_seen: int | None = None
) -> dict[str, Any]:
    """Join the journals in `folder` (see the module docstring for the result)."""
    problems = _Problems()
    processes: list[dict[str, Any]] = []
    loaded: list[tuple[str, dict[str, Any], list[dict[str, Any]]]] = []
    for path in sorted(Path(folder).glob("journal-*.jsonl")):
        recs = _read_journal(path, problems)
        if recs is None:
            processes.append(
                {
                    "file": path.name,
                    "role": None,
                    "worker": None,
                    "pid": None,
                    "complete": False,
                    "records": 0,
                    "plugins": None,
                    "exitstatus": None,
                    "nested_token": None,
                }
            )
            continue
        start = next((r for r in recs if r["kind"] == "process-start"), None)
        trailers = [i for i, r in enumerate(recs) if r["kind"] == "trailer"]
        trailer = recs[-1] if trailers == [len(recs) - 1] and recs[-1].get("complete") is True else None
        info = {
            "file": path.name,
            "role": (start or recs[0] if recs else {}).get("role"),
            "worker": (start or {}).get("worker"),
            "pid": (start or {}).get("pid"),
            "complete": trailer is not None,
            "records": len(recs),
            "plugins": (start or {}).get("plugins"),
            "exitstatus": (trailer or {}).get("exitstatus"),
            "nested_token": (start or {}).get("nested_token"),
        }
        processes.append(info)
        loaded.append((path.name, info, recs))
        if [r["seq"] for r in recs] != list(range(1, len(recs) + 1)):
            problems.add("sequence-gap", "the sequence numbers are not 1, 2, 3, ...", file=path.name)
        if start is None or recs[0] is not start:
            problems.add("no-process-start", "the journal does not begin with process-start", file=path.name)
        elif not isinstance(start.get("plugins"), list):
            problems.add("plugin-inventory-missing", "process-start has no plugins field", file=path.name)
        if not trailers:
            problems.add("no-trailer", "the journal has no completion trailer", file=path.name)
        elif trailer is None:
            problems.add(
                "records-after-trailer", "the trailer is not the last record, or is not complete", file=path.name
            )

    items: dict[str, dict[str, Any]] = {}
    groups: dict[str, set[str]] = {}
    errors: list[tuple[tuple[float, str, int], dict[str, Any]]] = []
    failures: list[tuple[tuple[float, str, int], dict[str, Any]]] = []
    launches: list[str] = []
    journaled: set[str] = set()
    for name, info, recs in loaded:
        if info["nested_token"]:
            journaled.add(info["nested_token"])
        nested_tree = bool(info["nested_token"])
        loadgroup = bool(next((r for r in recs if r["kind"] == "process-start"), {}).get("loadgroup"))
        open_items: dict[str, int] = {}
        canonical_of: dict[str, str] = {}
        for record in recs:
            kind, key = record["kind"], (float(record.get("t_wall", 0)), name, record["seq"])
            entry = {**record, "file": name}
            if kind == "nested-launch":
                launches.append(str(record.get("token")))
            elif (
                kind == "worker-down"
                and record.get("has_error")
                or kind in ("collection-error", "internal-error")
                or (kind == "exit-status" and record.get("exitstatus") not in (0, 1))
            ):
                errors.append((key, entry))
            elif kind == "phase" and record.get("outcome") == "failed":
                failures.append((key, entry))
            elif kind == "item-start" and not nested_tree and info["role"] in ("serial", "worker"):
                group = record.get("requested_group")
                canonical = canonical_of[record["nodeid"]] = canonical_id(record["nodeid"], group)
                item = items.setdefault(canonical, {"started": 0, "ended": 0, "workers": [], "group": group})
                item["started"] += 1
                item["workers"].append(info["worker"] or info["role"])
                open_items[record["nodeid"]] = open_items.get(record["nodeid"], 0) + 1
                if record.get("effective_group"):
                    groups.setdefault(record["effective_group"], set()).add(info["worker"] or info["role"])
                if record.get("suffix_missing") and loadgroup:
                    problems.add(
                        "suffix-missing",
                        "a group member has no @group suffix in its node id",
                        nodeid=record["nodeid"],
                        file=name,
                    )
            elif kind == "item-end" and not nested_tree and info["role"] in ("serial", "worker"):
                if record["nodeid"] in canonical_of:
                    items[canonical_of[record["nodeid"]]]["ended"] += 1
                open_items[record["nodeid"]] = open_items.get(record["nodeid"], 0) - 1
        for nodeid, count in open_items.items():
            if count > 0:
                problems.add("item-unfinished", "an item started and never ended", nodeid=nodeid, file=name)

    for group, workers in sorted(groups.items()):
        if len(workers) > 1:
            problems.add("group-split", f"members of group {group} ran on {sorted(workers)}", group=group)
    if expected_ids is not None:
        expected = Counter(expected_ids)
        for canonical, item in sorted(items.items()):
            if canonical not in expected:
                problems.add("unexpected-id", "started but not in the serial collection", nodeid=canonical)
            elif item["started"] > 1:
                problems.add("duplicate-id", f"started {item['started']} times", nodeid=canonical)
        for canonical in sorted(expected):
            if canonical not in items:
                problems.add("missing-id", "in the serial collection but never started", nodeid=canonical)
    unlaunched = journaled - set(launches)
    for token in sorted(unlaunched):
        problems.add("nested-journal-unlaunched", "a nested journal has no launch record", token=token)
    for token in sorted(set(launches) - journaled):
        problems.add("nested-journal-missing", "a nested run was launched but left no journal", token=token)
    if nested_seen is not None and nested_seen > len(journaled):
        problems.add("nested-journal-missing", f"{nested_seen} nested sessions were seen, {len(journaled)} journaled")

    first_error = min(errors, key=lambda pair: pair[0])[1] if errors else None
    first_failure = min(failures, key=lambda pair: pair[0])[1] if failures else None
    status = "complete" if processes and all(p["complete"] for p in processes) else "incomplete"
    return {
        "schema": SCHEMA_VERSION,
        "status": status,
        "accepted": status == "complete" and not problems.counts and first_error is None,
        "problems": problems.listed,
        "problem_counts": dict(problems.counts),
        "first_error": first_error,
        "first_failure": first_failure,
        "processes": processes,
        "items": items,
        "groups": {g: sorted(w) for g, w in groups.items()},
        "nested": {"launched": len(launches), "journaled": len(set(launches) & journaled)},
    }
