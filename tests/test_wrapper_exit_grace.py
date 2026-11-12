"""#683: once the model child has exited and its turn has finished, a leftover process that inherited
the wrapper's output pipe must not keep `agenttalk wrap` (plain or --loop) waiting for end of output.

Every test runs the wrapper in a thread with its own hard timeout, so a regression fails instead of
hanging, and ends every process it started by its exact process id.

Stated limit: a model that exits WITHOUT finishing its turn (no turn-end event) while a leftover process
holds the pipe still keeps the wrapper waiting, as before; the supervisor's stuck-turn recovery is its bound.
The grace cannot start at exit alone, because a launcher can hand off and exit early (see the hand-off test).
The end-of-run record must also arrive as a complete, newline-terminated line for the grace to start: a final
record without its line ending, while a leftover process holds the pipe, still waits, as on master."""

from __future__ import annotations

import errno
import gc
import inspect
import os
import select
import signal
import subprocess
import sys
import textwrap
import threading
import time
import types
import warnings
from pathlib import Path

import pytest

from agenttalk.store import Store
from agenttalk.wrapper import run, session
from agenttalk.wrapper.events import EventType
from agenttalk.wrapper.turn_watchdog import TurnWatchdogConfig

pytestmark = pytest.mark.subprocess

# getattr keeps these tests runnable against a wrapper without the grace, where they must fail.
GRACE = getattr(run, "OUTPUT_GRACE_AFTER_EXIT_SECONDS", 2.0)
HARD_TIMEOUT = GRACE + 10.0
SLOW = GRACE + 2.0  # longer than the grace, so a grace started too early ends the read too soon


def _process_identity(pid):
    """Who has this process number: a text that names ONE process for as long as it exists (its creation time), or
    None when it cannot be read. A number that was handed to a new process answers with a different text, so a
    clean-up can tell the helper a test started from a stranger that got its number (#749). Self-contained: the
    stand-in model embeds this source to record each helper's identity at the moment it starts it."""
    import os
    import subprocess

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetProcessTimes.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            ok = kernel.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)
            )
            if not ok:
                return None
            return f"nt:{(created.dwHighDateTime << 32) | created.dwLowDateTime}"
        finally:
            kernel.CloseHandle(handle)
    try:  # Linux: the start time, in clock ticks after boot (field 22 of /proc/<pid>/stat)
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as stat:
            return "proc:" + stat.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        pass
    try:  # macOS and others: the start time as the process list prints it
        done = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = " ".join(done.stdout.split())
    return f"ps:{text}" if done.returncode == 0 and text else None


# A stand-in model: it prints a `codex exec --json` turn, then does what its mode asks.
MODEL = textwrap.dedent(r'''
    import json, subprocess, sys, time

    mode, pidfile, slow = sys.argv[1], sys.argv[2], float(sys.argv[3])
    # A helper watches this file and leaves when it appears (or after 120 s, as before): the clean-up asks it to stop by
    # itself, so no signal has to be sent to a number that may by then belong to another process (#749).
    STOP = pidfile + ".stop"
    SLEEPER = [sys.executable, "-c", """import os, sys, time
    end = time.time() + 120
    while time.time() < end and not os.path.exists(sys.argv[1]):
        time.sleep(0.05)
    """, STOP]
    # Logs a line every 0.3 s, like a dev server. Once nobody reads its output it ignores the failed
    # writes and keeps running, so a test can see that the wrapper did not stop it.
    WRITER = [sys.executable, "-c", """import os, sys, time
    for i in range(400):
        if os.path.exists(sys.argv[1]):
            break
        try:
            print('GET /', i, flush=True)
        except OSError:
            pass
        time.sleep(0.3)
    """, STOP]
    NULL = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def say(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def message(text):
        say({"type": "item.completed", "item": {"type": "agent_message", "text": text}})

    def turn():
        say({"type": "turn.started"})
        message("done")
        say({"type": "turn.completed"})

    def spawn(argv, **kwargs):
        child = subprocess.Popen(argv, **kwargs)
        identity = _process_identity(child.pid) or "-"  # who this number is NOW: the clean-up stops only that process
        with open(pidfile, "a", encoding="utf-8") as handle:
            handle.write(f"{child.pid}\t{identity}\n")

    def again(next_mode):
        return [sys.executable, __file__, next_mode, pidfile, str(slow)]

    if mode.startswith("survivor-"):
        turn()
        spawn(SLEEPER, **{
            "survivor-nofds-null": dict(close_fds=False, **NULL),
            "survivor-nofds-inherit": dict(close_fds=False),
            "survivor-default-inherit": {},
            "survivor-default-null": NULL,
        }[mode])
    elif mode == "writing":  # a leftover that keeps writing after the turn's end
        turn()
        spawn(WRITER)
    elif mode == "burst-then-writing":  # many last lines just before the end event, then a writer
        say({"type": "turn.started"})
        for i in range(3000):
            message(f"line {i}")
        say({"type": "turn.completed"})
        spawn(WRITER)
    elif mode == "odd-codex":         # events whose type is a list or an object, then a valid turn
        say({"type": []})
        say({"type": {}})
        turn()
    elif mode == "odd-claude":
        say({"type": []})
        say({"type": {}})
        say({"type": "stream_event", "event": {"type": "message_start"}})
        say({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}})
        say({"type": "stream_event", "event": {"type": "message_stop"}})
        say({"type": "result", "subtype": "success", "is_error": False, "result": "done"})
    elif mode == "claude-handoff":    # a Claude launcher that hands off; the turn calls a tool first
        spawn(again("claude-brain"))
    elif mode == "claude-brain":
        def stream(event):
            say({"type": "stream_event", "event": event})
        stream({"type": "message_start"})
        stream({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash"}})
        stream({"type": "message_stop"})  # the tool-use message ends; the invocation does not
        time.sleep(slow)                   # the tool runs for longer than the grace
        stream({"type": "message_start"})
        say({"type": "assistant", "message": {"content": [{"type": "text", "text": "final answer"}]}})
        stream({"type": "message_stop"})
        say({"type": "result", "subtype": "success", "is_error": False, "result": "final answer"})
    elif mode == "handoff":           # a launcher that hands the turn to a child and exits at once
        spawn(again("brain"))
    elif mode == "brain":
        say({"type": "turn.started"})
        time.sleep(slow)
        message("done")
        say({"type": "turn.completed"})
    elif mode == "late-tail":         # a helper still writing after the model has exited
        turn()
        spawn(again("tail-after"))
    elif mode == "tail-after":
        time.sleep(0.5)
        message("late")
    elif mode == "quiet-then-tail":   # the model finishes its turn but keeps running, quietly
        turn()
        time.sleep(slow)
        message("tail")
    elif mode == "partial-survivor":  # a last line without a newline, then a survivor
        turn()
        sys.stdout.write("partial")
        sys.stdout.flush()
        spawn(SLEEPER)
''')
MODEL = inspect.getsource(_process_identity) + "\n\n" + MODEL

SURVIVORS = [
    "survivor-nofds-null",      # close_fds=False, stdio on null: shares the pipe on Windows
    "survivor-nofds-inherit",   # close_fds=False, stdio inherited
    "survivor-default-inherit",  # default close_fds, stdio inherited: Windows, and stdout on POSIX
]
CONTROL = "survivor-default-null"  # stdio on null: never shares the pipe


@pytest.fixture
def model(tmp_path: Path) -> Path:
    path = tmp_path / "model.py"
    path.write_text(MODEL, encoding="utf-8")
    return path


def _argv(model: Path, mode: str, pidfile: Path) -> list[str]:
    return [sys.executable, str(model), mode, str(pidfile), str(SLOW)]


def _pidfile_rows(pidfile: Path) -> tuple[list[tuple[int, str | None]], list[tuple[int, str]]]:
    """The pid file as (helpers, bad rows). A helper is a process the stand-in started: its number and the identity it
    had then (None: none was recorded). A row that is not a positive number (a torn or damaged write; zero and negative
    numbers would name no process, or a process group) is not a helper: it is set aside with its line number, so one
    bad row cannot keep a readable one from being cleaned up (#749 review). Blank lines are skipped."""
    if not pidfile.exists():
        return [], []
    helpers, bad = [], []
    for number_of_line, line in enumerate(pidfile.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        number, _tab, identity = line.partition("\t")
        try:
            pid = int(number)
        except ValueError:
            pid = 0
        if pid <= 0:
            bad.append((number_of_line, line))
        else:
            helpers.append((pid, identity if identity not in ("", "-") else None))
    return helpers, bad


def _helpers(pidfile: Path) -> list[tuple[int, str | None]]:
    """Every process the stand-in started: its number and the identity it had then (None: none was recorded)."""
    return _pidfile_rows(pidfile)[0]


def _pids(pidfile: Path) -> list[int]:
    return [pid for pid, _identity_then in _helpers(pidfile)]


def _identity(pid: int) -> str | None:
    """Who has this number now (see `_process_identity`); the clean-up calls this one so a test can fake the answer."""
    return _process_identity(pid)


_GONE = object()  # what `_open_reference` answers when there is no such process (any more)


class _WindowsReference:
    """An open handle to ONE process (#749 review). While it is open the system cannot give the number to another
    process, and the stop goes through this same handle, so what was checked is what is stopped."""

    _QUERY_LIMITED, _TERMINATE = 0x1000, 0x0001  # PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE

    def __init__(self, kernel, handle):
        self._kernel, self._handle = kernel, handle

    @classmethod
    def open(cls, pid):
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetProcessTimes.restype = ctypes.c_int
        kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel.TerminateProcess.restype = ctypes.c_int
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.GetExitCodeProcess.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(cls._QUERY_LIMITED | cls._TERMINATE, False, pid)
        if not handle:
            return _GONE if ctypes.get_last_error() == 87 else None  # 87: no process has this id
        return cls(kernel, handle)

    def identity(self):
        import ctypes
        from ctypes import wintypes

        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        ok = self._kernel.GetProcessTimes(
            self._handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        return f"nt:{(created.dwHighDateTime << 32) | created.dwLowDateTime}" if ok else None  # as `_process_identity`

    def terminate(self):
        import ctypes

        if not self._kernel.TerminateProcess(self._handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def state(self):
        """Says "alive", "ended" or "unknown" for the process the handle is bound to, whoever has its number now."""
        import ctypes

        code = ctypes.c_ulong()
        if not self._kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            return "unknown"
        return "alive" if code.value == 259 else "ended"  # 259 = STILL_ACTIVE, as in `_state`

    def close(self):
        self._kernel.CloseHandle(self._handle)


class _PidfdReference:
    """Linux: a pidfd refers to ONE process, whoever has its number later; a signal sent through it either reaches
    that process or fails. The identity is read after the pidfd was opened: a number already handed to a stranger
    answers with the stranger's identity, and the pidfd opened on it is then left alone."""

    def __init__(self, pid, fd):
        self._pid, self._fd = pid, fd

    def identity(self):
        return _process_identity(self._pid)

    def terminate(self):
        signal.pidfd_send_signal(self._fd, signal.SIGTERM)

    def state(self):
        """Says "ended" once the pidfd is readable (the process it refers to has ended), whoever has the number now.
        Until then the number still belongs to this process (it is not reaped), so a kernel that shows only a reaped
        process as readable is helped by the number's own zombie check, which can only be early-and-right or late."""
        try:
            readable, _writable, _error = select.select([self._fd], [], [], 0)
        except (OSError, ValueError):
            return "unknown"
        return "ended" if readable else _state(self._pid)

    def close(self):
        os.close(self._fd)


class _ReadOnlyReference:
    """No handle and no pidfd here (macOS, or a Linux without pidfd): nothing binds a stop to the process whose
    identity was read, and a stop by number could reach a stranger that got the number in between. This reference can
    say who has the number (so a stranger is told from the helper) but REFUSES to stop anything: the helpers stop
    themselves (see `_ask_to_stop`), and one that does not is reported for a person to stop."""

    def __init__(self, pid):
        self._pid = pid

    def identity(self):
        return _process_identity(self._pid)

    def terminate(self):
        raise AssertionError(
            f"process {self._pid} started by the test is still running and cannot be stopped safely on this system "
            "(no process handle or pidfd to bind a stop to it); it was not signalled, stop it by hand"
        )

    def state(self):
        return _state(self._pid)  # nothing is bound here; it is never asked after a stop, which this reference refuses

    def close(self):
        pass


def _open_reference(pid):
    """A reference to the process that has this number now, or None (it cannot be opened or identified) or `_GONE`
    (no such process). The identity is asked of the reference and the stop goes through it. Where nothing can bind a
    stop to the process (no handle, no pidfd) the reference refuses to stop: a bare number is never signalled."""
    if os.name == "nt":
        return _WindowsReference.open(pid)
    if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        try:
            return _PidfdReference(pid, os.pidfd_open(pid))
        except ProcessLookupError:
            return _GONE
        except OSError as exc:
            if exc.errno not in (errno.ENOSYS, errno.EINVAL):  # a kernel without pidfd: read-only, below
                return None
    try:
        os.kill(pid, 0)  # a look, not a stop
    except ProcessLookupError:
        return _GONE
    except PermissionError:
        pass
    except OSError:
        return None
    return _ReadOnlyReference(pid)


def _state(pid: int) -> str:
    """ "alive", "ended" or "unknown". A process counts as ended only on positive evidence; a probe that could not
    look (access denied, a failed query) says "unknown", and the clean-up never takes that for stopped."""
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            # ERROR_INVALID_PARAMETER (87) is Windows saying that no process has this id: it has ended (unless the id
            # was handed to a new process, which the handle-based check below then reports as alive).
            return "ended" if ctypes.get_last_error() == 87 else "unknown"
        try:
            code = ctypes.c_ulong()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return "unknown"
            return "alive" if code.value == 259 else "ended"  # 259 = STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "ended"
    except PermissionError:  # the process exists; it is only not ours to signal
        return "alive"
    except OSError:
        return "unknown"
    try:  # a zombie has ended: a container's PID 1 may never reap the helpers it adopts
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as stat:
            return "ended" if stat.read().rsplit(")", 1)[1].split()[0] == "Z" else "alive"
    except (OSError, IndexError):
        return "alive"


def _alive(pid: int) -> bool:
    return _state(pid) == "alive"


def _listed_as_running(pid: int) -> bool | None:
    """Whether the platform's own process list has this id, asked without going through `_state`:
    True or False, or None when the list cannot be read."""
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        ulong, ulong_p = ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)
        kernel.K32EnumProcesses.argtypes = [ulong_p, ulong, ulong_p]
        size = 4096
        while True:
            ids, returned = (ctypes.c_ulong * size)(), ctypes.c_ulong()
            if not kernel.K32EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(returned)):
                return None
            count = returned.value // ctypes.sizeof(ctypes.c_ulong)
            if count < size:  # a full array may have been cut short: ask again with room to spare
                return pid in ids[:count]
            size *= 2
    return _listed_in_proc(pid) if os.path.isdir("/proc/self") else _listed_by_ps(pid)


def _proc_mount_hides_processes(mounts: str) -> bool:
    """True if the text of /proc/mounts shows /proc mounted with hidepid (other users' processes are then not
    listed at all, so an id that is missing from the list proves nothing). The last /proc mount is the one in force."""
    hidden = False
    for line in mounts.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1] == "/proc":
            hidden = any(o.startswith("hidepid=") and o[8:] not in ("0", "off") for o in fields[3].split(","))
    return hidden


def _listed_in_proc(pid: int, proc_root: str = "/proc") -> bool | None:
    """Linux: only a confirmed absence (FileNotFoundError) says unused. Any other error, a /proc mounted with hidepid
    or a mount table that cannot be read says None. A zombie is still listed: counted as in use, the safe way."""
    try:
        with open(os.path.join(proc_root, "mounts"), encoding="utf-8", errors="replace") as mounts:
            if _proc_mount_hides_processes(mounts.read()):
                return None
        os.stat(os.path.join(proc_root, str(pid)))
    except FileNotFoundError as exc:
        return False if exc.filename is not None and os.path.basename(str(exc.filename)) == str(pid) else None
    except OSError:
        return None
    return True


def _listed_by_ps(pid: int) -> bool | None:
    """No /proc (macOS, BSD): ps exits 1 with nothing at all printed when no process has the id. A listed id stays
    listed: exit 0 with the id on stdout is True, even if ps also printed a warning on stderr (True never makes the
    caller pick an id). A "not listed" answer needs a silent stderr: any error text on it, any other exit code or
    empty output with exit 0 means the query failed, and the answer is None."""
    try:
        ps = subprocess.run(["ps", "-p", str(pid), "-o", "pid="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if ps.returncode == 0 and ps.stdout.strip():
        return True
    return False if ps.returncode == 1 and not ps.stdout.strip() and not ps.stderr.strip() else None


def _proven_unused_pid(candidates=range(4_000_000, 4_000_040, 4)) -> int | None:
    """An id that the process list shows nothing is using, or None. Not a fixed number: on Linux pid_max can
    reach 4,194,304, so a busy machine can be using the id this test once took for granted. Known limit: another
    process can still take the id between this check and the `_state` call that follows it."""
    return next((pid for pid in candidates if _listed_as_running(pid) is False), None)


def _end_one(pid: int, recorded: str | None) -> None:
    """Stop one helper that did not leave by itself, if it is provably the one the stand-in started, and prove it has
    ended. The stop goes through the reference that was checked (a handle or a pidfd), never by the bare number, so a
    number handed to another process after the check cannot receive it; where no such reference exists it is refused.
    The exit is proven through the same reference: once the helper has been stopped its number may belong to a new
    process, which must neither make the helper look still running nor look ended for it. A helper the first look
    already shows ended, or that went away before the reference could be opened, has been proven gone and is not
    looked at again. A number that now belongs to a different process is left alone (the helper has ended); one whose
    identity was not recorded or cannot be read now is left alone and fails with a message."""
    if _state(pid) == "ended":
        return
    if recorded is None:
        raise AssertionError(f"process {pid} started by the test has no recorded identity, so it is not stopped")
    reference = _open_reference(pid)
    if reference is None:
        raise AssertionError(f"process {pid} started by the test cannot be identified now, so it is not stopped")
    if reference is _GONE:  # it went away between the look and the open: nothing is left to stop
        return
    try:
        current = reference.identity()
        if current is None:
            raise AssertionError(f"process {pid} started by the test cannot be identified now, so it is not stopped")
        if current != recorded:
            warnings.warn(
                f"process number {pid} now belongs to a different process than the helper the test started "
                "(the helper has ended); the other process was not stopped",
                stacklevel=3,
            )
            return
        try:
            reference.terminate()  # TerminateProcess on Windows, pidfd_send_signal on Linux
        except ProcessLookupError:  # it ended between the check and the stop: nothing is left to stop
            pass
        except OSError as exc:
            # Windows says WinError 87 (no such process id), or WinError 5 (access denied) while a handle to the
            # ended process is still open. Accept that only when the process is now positively ended, as the reference
            # says; anything else, or a process still running or not inspectable, fails.
            if getattr(exc, "winerror", None) not in (5, 87) or reference.state() != "ended":
                raise
        deadline = time.monotonic() + 10.0
        while reference.state() != "ended" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert reference.state() == "ended", (
            f"process {pid} started by the test is still running or cannot be inspected"
        )
    finally:
        reference.close()


_COOPERATIVE_WAIT = 5.0  # seconds the helpers get to leave by themselves before any other stop is considered


def _ask_to_stop(pidfile: Path) -> None:
    """The stop that needs no signal: write the stop file the helpers watch, and give them a few seconds to leave. A
    helper that leaves by itself cannot be the wrong process that receives a signal."""
    Path(str(pidfile) + ".stop").write_text("stop", encoding="utf-8")
    deadline = time.monotonic() + _COOPERATIVE_WAIT
    for pid, _identity_then in _helpers(pidfile):
        while time.monotonic() < deadline and _state(pid) != "ended":
            time.sleep(0.05)


def _end_all(pidfile: Path) -> None:
    """Stop every process the stand-in started (see `_end_one`): first by asking them to leave by themselves (the
    stop file), then, for one that did not, through a reference that is bound to it. A helper that cannot be proven or
    stopped does not keep the later helpers from being cleaned up: every one is looked at, and the failures are raised
    after the last (the only one, as it was; several together in one message). The stop file is only the first, gentle
    step: if writing it fails, that error is kept and reported with the rest, and the bound clean-up still runs."""
    failures = []
    try:
        _ask_to_stop(pidfile)
    except Exception as exc:  # noqa: BLE001 - reported below, after the bound clean-up of every helper
        failures.append(exc)
    helpers, bad_rows = _pidfile_rows(pidfile)
    for pid, recorded in helpers:
        try:
            _end_one(pid, recorded)
        except Exception as exc:  # noqa: BLE001 - raised below, after every helper was looked at
            failures.append(exc)
    for number_of_line, line in bad_rows:  # after the readable ones: a damaged row never keeps another from a stop
        failures.append(
            AssertionError(
                f"row {number_of_line} of the pid file ({line!r}) cannot be read as a process number, so no helper was "
                "stopped for it; a process it may have named could still be running"
            )
        )
    if len(failures) == 1:
        raise failures[0]
    if failures:
        raise AssertionError("; ".join(str(failure) for failure in failures)) from failures[0]


def _fast_clock(monkeypatch):
    """A clock that jumps, so the 10 second wait in _end_all does not take 10 seconds."""
    ticks = iter(range(1000))
    clock = types.SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda seconds: None)
    monkeypatch.setattr(sys.modules[__name__], "time", clock)


def _states(monkeypatch, first, then):
    """_state says `first` once (the check before the kill), then `then`, which may be a name or the real probe."""
    real, seen = _state, []

    def state(pid):
        seen.append(pid)
        return first if len(seen) == 1 else (real(pid) if then is None else then)

    monkeypatch.setattr(sys.modules[__name__], "_ask_to_stop", lambda pidfile: None)  # these tests fake the helpers
    monkeypatch.setattr(sys.modules[__name__], "_state", state)
    return seen


SAME = "identity-of-the-helper"  # what a fake reference says for the helper the test started


def _pidfile_for(tmp_path, pid, identity=SAME):
    """A pid file as the stand-in writes it: the id and the identity the helper had when it was started."""
    pidfile = tmp_path / "pids"
    pidfile.write_text(f"{pid}\t{identity}\n", encoding="utf-8")
    return pidfile


class _FakeReference:
    """What `_open_reference` returns in a test: a stand-in for the platform's reference to ONE process. It is bound
    to the process it was opened for (``bound``), whoever has the number later, as a real handle or pidfd is."""

    def __init__(self, identity, *, error=None, on_identity=None, bound="helper", state=None):
        self._identity, self._error, self._on_identity, self.bound = identity, error, on_identity, bound
        self._state_of = state
        self.terminated = []
        self.closed = False
        self.pid = None

    def identity(self):
        answer = self._identity
        if self._on_identity is not None:
            self._on_identity()
        return answer

    def terminate(self):
        if self._error is not None:
            raise self._error
        self.terminated.append(self.bound)

    def state(self):
        """Whether the process this reference is bound to has ended. Without ``state=`` the fake says what the number
        says (the faked `_state`), as the older tests were written; with it, only the bound process counts."""
        return _state(self.pid) if self._state_of is None else self._state_of(self)

    def close(self):
        self.closed = True


def _reference_is(monkeypatch, identity, *, error=None, on_identity=None, bound="helper", state=None):
    """Fake the reference the clean-up opens. ``identity`` is what the reference answers (None: it cannot be read),
    or a dict of answers by number. ``state`` (a function of the reference) is what it says about the bound process
    ending. Returns the references it handed out, in order."""
    handed = []

    def open_reference(pid):
        answer = identity[pid] if isinstance(identity, dict) else identity
        reference = _FakeReference(answer, error=error, on_identity=on_identity, bound=bound, state=state)
        reference.pid = pid
        handed.append(reference)
        return reference

    monkeypatch.setattr(sys.modules[__name__], "_ask_to_stop", lambda pidfile: None)  # these tests fake the helpers
    monkeypatch.setattr(sys.modules[__name__], "_open_reference", open_reference)
    return handed


def _no_reference(monkeypatch, answer):
    """Fake a number that cannot be opened: ``None`` (cannot tell) or ``_GONE`` (no such process)."""
    asked = []

    def open_reference(pid):
        asked.append(pid)
        return answer

    monkeypatch.setattr(sys.modules[__name__], "_ask_to_stop", lambda pidfile: None)  # these tests fake the helpers
    monkeypatch.setattr(sys.modules[__name__], "_open_reference", open_reference)
    return asked


def _stops_by_number(monkeypatch, owner=lambda: "whoever has the number"):
    """Replace the by-number stop with a recorder of who would have received it. A clean-up that stops through the
    reference it checked never calls it, so the list stays empty."""
    received = []

    def kill(pid, sig):
        if sig != 0:  # signal 0 is only a look, never a stop
            received.append(owner())

    monkeypatch.setattr(os, "kill", kill)
    return received


def _kill_raises(monkeypatch, error):
    def kill(pid, sig):
        raise error

    monkeypatch.setattr(os, "kill", kill)


def _stop_primitives(monkeypatch):
    """Recorders for every primitive that can stop a process, so a test can say which one a stop went through.
    ``by_number`` collects what would reach whoever has a bare number (os.kill with a real signal, or at all on
    Windows, where any os.kill ends the process; os.killpg; Popen.terminate/kill/send_signal); ``by_reference``
    collects the pidfd signals, which go to the one process the pidfd was opened for and are still sent. A signal-0
    look is not a stop."""
    by_number, by_reference = [], []
    real_pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)

    def kill(pid, sig):
        if sig != 0 or os.name == "nt":
            by_number.append(("os.kill", pid, sig))

    def killpg(pgid, sig):
        by_number.append(("os.killpg", pgid, sig))

    def pidfd_send_signal(fd, sig, *args, **kwargs):
        by_reference.append((fd, sig))
        return real_pidfd_send_signal(fd, sig, *args, **kwargs)

    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(os, "killpg", killpg, raising=False)
    if real_pidfd_send_signal is not None:
        monkeypatch.setattr(signal, "pidfd_send_signal", pidfd_send_signal)
    for name in ("terminate", "kill"):
        monkeypatch.setattr(
            subprocess.Popen, name, lambda self, name=name: by_number.append((f"Popen.{name}", self.pid, None))
        )
    monkeypatch.setattr(
        subprocess.Popen, "send_signal", lambda self, sig: by_number.append(("Popen.send_signal", self.pid, sig))
    )
    return types.SimpleNamespace(by_number=by_number, by_reference=by_reference)


@pytest.mark.parametrize("handle", ["open", "closed"])
def test_end_all_treats_a_process_that_ended_before_the_kill_as_stopped(tmp_path, monkeypatch, handle):
    # The race: the process is alive when checked and gone when killed. Windows reports that as access denied while a
    # handle to the ended process is still open, and as "parameter is incorrect" once none is; Linux as no such process.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    identity = _identity(child.pid)  # read while it runs, as the stand-in does when it starts a helper
    assert identity is not None
    child.wait()
    pidfile = _pidfile_for(tmp_path, child.pid, identity=identity)
    if handle == "closed":
        del child
        gc.collect()
    seen = _states(monkeypatch, "alive", None)

    _end_all(pidfile)  # must not raise

    # The check said "alive" once. After that the ended process is proven gone through the reference (or, if the number
    # was already free when the reference was opened, by that very answer), never by polling the number again.
    assert len(seen) == 1


def test_end_all_still_fails_for_a_process_that_is_really_still_running(tmp_path, monkeypatch):
    pidfile = _pidfile_for(tmp_path, 4242)
    _reference_is(monkeypatch, SAME, error=ProcessLookupError())  # the stop finds nothing, yet it is reported alive
    _states(monkeypatch, "alive", "alive")
    _fast_clock(monkeypatch)

    with pytest.raises(AssertionError, match="still running"):
        _end_all(pidfile)


@pytest.mark.parametrize("kill", ["denied", "works"])
def test_end_all_never_takes_a_process_it_cannot_inspect_for_stopped(tmp_path, monkeypatch, kill):
    # The probe is denied after the first look (WinError 5 on Windows). Whether the kill is refused too or goes through,
    # "could not look" is not "gone": the clean-up must not return normally.
    pidfile = _pidfile_for(tmp_path, 4242)
    error = PermissionError(13, "Access is denied", None, 5) if kill == "denied" else None
    _reference_is(monkeypatch, SAME, error=error)
    _states(monkeypatch, "alive", "unknown")
    _fast_clock(monkeypatch)

    with pytest.raises(PermissionError if kill == "denied" else AssertionError):
        _end_all(pidfile)


def test_end_all_lets_an_unlisted_error_escape_even_when_the_process_is_confirmed_gone(tmp_path, monkeypatch):
    pidfile = _pidfile_for(tmp_path, 4242)
    _reference_is(monkeypatch, SAME, error=OSError(errno.EIO, "Input/output error"))  # not a listed code
    _states(monkeypatch, "alive", "ended")

    with pytest.raises(OSError, match="Input/output error"):
        _end_all(pidfile)


@pytest.mark.skipif(os.name != "nt", reason="the access-denied and invalid-parameter codes are Windows errors")
def test_end_all_does_not_swallow_a_windows_error_while_the_process_is_still_alive(tmp_path, monkeypatch):
    pidfile = _pidfile_for(tmp_path, 4242)
    _reference_is(monkeypatch, SAME, error=PermissionError(13, "Access is denied", None, 5))
    _states(monkeypatch, "alive", "alive")

    with pytest.raises(PermissionError):
        _end_all(pidfile)


def test_end_all_asks_every_helper_to_stop_itself_before_it_considers_any_other_stop(tmp_path, monkeypatch):
    """The first thing the clean-up does is write the stop file the helpers watch: a helper that stops itself needs no
    signal, so it cannot be the wrong process that receives one."""
    pidfile = tmp_path / "pids"
    pidfile.write_text("", encoding="utf-8")

    _end_all(pidfile)

    assert Path(str(pidfile) + ".stop").exists()


def test_end_all_ends_a_real_helper_without_signalling_it_by_number_or_reference(model, tmp_path, monkeypatch):
    """A real helper (the stand-in's survivor) leaves when the stop file appears: nothing is sent to it."""
    pidfile = tmp_path / "pids.txt"
    subprocess.run(_argv(model, "survivor-default-null", pidfile), capture_output=True, text=True, timeout=60)
    ((pid, _identity_then),) = _helpers(pidfile)
    assert _state(pid) == "alive"  # it is really running before the clean-up
    sent = []
    real_kill = os.kill  # a look (signal 0) is how the probe sees a process; only a real stop is recorded
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)) if sig else real_kill(pid, 0))
    monkeypatch.setattr(sys.modules[__name__], "_open_reference", lambda pid: sent.append(("opened", pid)))

    _end_all(pidfile)

    assert _state(pid) == "ended" and sent == []


def _stop_file_write_fails(monkeypatch, pidfile, code=errno.ENOSPC):
    """Make ONLY the write of the stop file fail, as a full disk or a permission error would."""
    real_write = Path.write_text
    stop_file = str(pidfile) + ".stop"

    def write_text(path, *args, **kwargs):
        if str(path) == stop_file:
            raise OSError(code, "injected stop-file write failure")
        return real_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text)


def test_end_all_still_stops_and_closes_a_bound_helper_when_the_stop_file_cannot_be_written(tmp_path, monkeypatch):
    """The stop file is a courtesy: if writing it fails, the bound clean-up of every helper still runs (#749 review) and
    the write error is reported afterwards, neither swallowed nor replaced by a stop by number."""
    pidfile = _pidfile_for(tmp_path, 4242)
    _stop_file_write_fails(monkeypatch, pidfile)
    stopped, closed = [], []

    class Reference:
        def identity(self):
            return SAME

        def terminate(self):
            stopped.append(4242)

        def state(self):
            return "ended" if stopped else "alive"

        def close(self):
            closed.append(4242)

    monkeypatch.setattr(sys.modules[__name__], "_open_reference", lambda pid: Reference())
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: "ended" if stopped else "alive")
    by_number = _stops_by_number(monkeypatch)

    with pytest.raises(OSError, match="injected stop-file write failure"):
        _end_all(pidfile)

    assert stopped == [4242] and closed == [4242] and by_number == []


def test_end_all_reports_a_stop_file_error_together_with_what_else_it_could_not_clean_up(tmp_path, monkeypatch):
    pidfile = _pidfile_for(tmp_path, 4242)
    _stop_file_write_fails(monkeypatch, pidfile)
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: "alive")
    monkeypatch.setattr(sys.modules[__name__], "_open_reference", lambda pid: _ReadOnlyReference(pid))
    monkeypatch.setattr(sys.modules[__name__], "_process_identity", lambda pid: SAME)
    by_number = _stops_by_number(monkeypatch)

    with pytest.raises(AssertionError) as raised:
        _end_all(pidfile)

    assert "injected stop-file write failure" in str(raised.value) and "cannot be stopped safely" in str(raised.value)
    assert by_number == []


def test_end_all_refuses_to_stop_a_helper_it_cannot_bind_a_stop_to(tmp_path, monkeypatch):
    """No handle and no pidfd (macOS, or a Linux without pidfd): a helper that does not stop itself is reported, never
    killed by number, because a number handed to a stranger in between would be stopped instead."""
    pidfile = _pidfile_for(tmp_path, 4242)
    _states(monkeypatch, "alive", "alive")
    by_number = _stops_by_number(monkeypatch)
    monkeypatch.setattr(sys.modules[__name__], "_open_reference", lambda pid: _ReadOnlyReference(pid))
    monkeypatch.setattr(sys.modules[__name__], "_process_identity", lambda pid: SAME)

    with pytest.raises(AssertionError, match="cannot be stopped safely"):
        _end_all(pidfile)

    assert by_number == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX: what is used when the kernel or the system has no pidfd")
@pytest.mark.parametrize("how", ["no-pidfd", "enosys", "einval"])
def test_without_a_pidfd_the_selector_gives_a_reference_that_never_stops_by_number(tmp_path, monkeypatch, how):
    by_number = _stops_by_number(monkeypatch, owner=lambda: "unrelated replacement")
    monkeypatch.setattr(sys.modules[__name__], "_process_identity", lambda pid: SAME)
    if how == "no-pidfd":
        monkeypatch.delattr(os, "pidfd_open", raising=False)
    else:
        code = errno.ENOSYS if how == "enosys" else errno.EINVAL

        def pidfd_open(pid):
            raise OSError(code, "no pidfd here")

        monkeypatch.setattr(os, "pidfd_open", pidfd_open, raising=False)
        monkeypatch.setattr(signal, "pidfd_send_signal", lambda *a, **k: None, raising=False)

    reference = _open_reference(os.getpid())  # a process that exists: the selector must hand out a reference

    assert isinstance(reference, _ReadOnlyReference) and reference.identity() == SAME
    with pytest.raises(AssertionError, match="cannot be stopped safely"):
        reference.terminate()
    assert by_number == []


def test_end_all_does_not_stop_a_process_whose_number_was_reused(tmp_path, monkeypatch):
    """The helper ended and the system gave its number to an unrelated program: the number is alive, but it is not the
    helper, and it is left alone (#749). The helper itself has ended, so there is nothing to stop."""
    pidfile = _pidfile_for(tmp_path, 4242, identity="the-helper")
    handed = _reference_is(monkeypatch, "an-unrelated-program")
    _states(monkeypatch, "alive", "alive")
    by_number = _stops_by_number(monkeypatch)

    with pytest.warns(UserWarning, match="different process"):
        _end_all(pidfile)

    assert [r.terminated for r in handed] == [[]] and by_number == [] and handed[0].closed


def test_end_all_stops_through_the_reference_it_checked_not_by_number(tmp_path, monkeypatch):
    """The number is reused AFTER the identity was read and BEFORE the stop (#749 review): the stop goes through the
    reference that was checked, which still names the helper, so the new owner of the number is never touched."""
    owner = {"now": "helper"}
    pidfile = _pidfile_for(tmp_path, 4242)
    handed = _reference_is(monkeypatch, SAME, on_identity=lambda: owner.update(now="unrelated replacement"))
    answers = iter(["alive", "ended", "ended"])
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: next(answers))
    by_number = _stops_by_number(monkeypatch, owner=lambda: owner["now"])

    _end_all(pidfile)

    assert owner["now"] == "unrelated replacement"  # the number did change hands after the check
    assert handed[0].terminated == ["helper"]  # the stop went to the process that was checked
    assert by_number == []  # and never to whoever has the number now


def test_end_all_does_not_stop_a_process_it_cannot_open_or_identify(tmp_path, monkeypatch):
    pidfile = _pidfile_for(tmp_path, 4242)
    _states(monkeypatch, "alive", "alive")
    by_number = _stops_by_number(monkeypatch)
    asked = _no_reference(monkeypatch, None)  # the number is alive and no reference to it can be opened

    with pytest.raises(AssertionError, match="cannot be identified"):
        _end_all(pidfile)

    assert asked == [4242] and by_number == []


def test_end_all_does_not_stop_a_process_whose_identity_cannot_be_read(tmp_path, monkeypatch):
    pidfile = _pidfile_for(tmp_path, 4242)
    handed = _reference_is(monkeypatch, None)  # a reference opens, but the identity cannot be read through it
    _states(monkeypatch, "alive", "alive")
    by_number = _stops_by_number(monkeypatch)

    with pytest.raises(AssertionError, match="cannot be identified"):
        _end_all(pidfile)

    assert handed[0].terminated == [] and by_number == [] and handed[0].closed


@pytest.mark.parametrize("line", ["4242\n", "4242\t-\n"], ids=["bare-number", "no-identity-read"])
def test_end_all_does_not_stop_a_helper_whose_identity_was_never_recorded(tmp_path, monkeypatch, line):
    pidfile = tmp_path / "pids"
    pidfile.write_text(line, encoding="utf-8")
    handed = _reference_is(monkeypatch, SAME)
    _states(monkeypatch, "alive", "alive")
    by_number = _stops_by_number(monkeypatch)

    with pytest.raises(AssertionError, match="no recorded identity"):
        _end_all(pidfile)

    assert handed == [] and by_number == []


def test_end_all_stops_a_process_that_is_provably_the_helper(tmp_path, monkeypatch):
    pidfile = _pidfile_for(tmp_path, 4242)
    handed = _reference_is(monkeypatch, SAME)
    answers = iter(["alive", "ended", "ended"])  # alive before the stop, ended after it
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: next(answers))

    _end_all(pidfile)

    assert [r.pid for r in handed] == [4242] and handed[0].terminated == ["helper"] and handed[0].closed


def test_end_all_does_not_open_a_reference_when_the_helper_has_ended(tmp_path, monkeypatch):
    pidfile = _pidfile_for(tmp_path, 4242)
    handed = _reference_is(monkeypatch, SAME)
    _states(monkeypatch, "ended", "ended")
    by_number = _stops_by_number(monkeypatch)

    _end_all(pidfile)

    assert handed == [] and by_number == []


def test_end_all_takes_a_number_with_no_such_process_as_ended_not_as_a_failure(tmp_path, monkeypatch):
    pidfile = _pidfile_for(tmp_path, 4242)
    _no_reference(monkeypatch, _GONE)
    _states(monkeypatch, "alive", "ended")
    by_number = _stops_by_number(monkeypatch)

    _end_all(pidfile)  # the helper went away between the look and the open: nothing to stop

    assert by_number == []


def test_end_all_judges_each_helper_on_its_own(tmp_path, monkeypatch):
    """Two helpers: the first number was reused, the second is the helper. Only the second is stopped."""
    pidfile = tmp_path / "pids"
    pidfile.write_text("1111\thelper-1\n2222\thelper-2\n", encoding="utf-8")
    handed = _reference_is(monkeypatch, {1111: "stranger", 2222: "helper-2"})
    status = {1111: iter(["alive"]), 2222: iter(["alive", "ended", "ended"])}
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: next(status[pid]))

    with pytest.warns(UserWarning, match="1111"):
        _end_all(pidfile)

    assert {r.pid: r.terminated for r in handed} == {1111: [], 2222: ["helper"]}


@pytest.mark.parametrize("first", ["no-identity-recorded", "cannot-be-opened", "identity-unreadable"])
def test_end_all_keeps_cleaning_up_after_one_helper_it_cannot_prove(tmp_path, monkeypatch, first):
    """An unknown helper is left alone and reported, but a later helper that IS proven is still stopped (#749 review):
    the failure is raised after every helper was looked at."""
    pidfile = tmp_path / "pids"
    first_identity = "-" if first == "no-identity-recorded" else "helper-1"
    pidfile.write_text(f"1111\t{first_identity}\n2222\thelper-2\n", encoding="utf-8")
    handed = []

    def open_reference(pid):
        if pid == 1111 and first == "cannot-be-opened":
            return None
        unreadable = pid == 1111 and first == "identity-unreadable"
        reference = _FakeReference(None if unreadable else f"helper-{pid // 1111}")
        reference.pid = pid
        handed.append(reference)
        return reference

    monkeypatch.setattr(sys.modules[__name__], "_open_reference", open_reference)
    monkeypatch.setattr(sys.modules[__name__], "_ask_to_stop", lambda pidfile: None)
    status = {1111: iter(["alive"]), 2222: iter(["alive", "ended", "ended"])}
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: next(status[pid]))

    with pytest.raises(AssertionError, match="1111"):
        _end_all(pidfile)

    assert [r.pid for r in handed if r.terminated] == [2222]  # the proven helper was stopped, the unknown one was not


def test_end_all_reports_every_helper_it_could_not_clean_up(tmp_path, monkeypatch):
    pidfile = tmp_path / "pids"
    pidfile.write_text("1111\t-\n2222\t-\n", encoding="utf-8")
    _states(monkeypatch, "alive", "alive")

    with pytest.raises(AssertionError) as raised:
        _end_all(pidfile)

    assert "1111" in str(raised.value) and "2222" in str(raised.value)


BAD_ROWS = ["not-a-number\thelper-1", "12x", "-5\thelper-1", "0\thelper-1", "\t-"]


@pytest.mark.parametrize("position", ["first", "last"])
@pytest.mark.parametrize("bad", BAD_ROWS)
def test_end_all_stops_a_provable_helper_even_when_another_row_cannot_be_read(tmp_path, monkeypatch, position, bad):
    """One damaged row must not leave a later (or earlier) helper that IS provably the stand-in's running (#749 review):
    the readable rows are all cleaned up, and the unreadable one is reported after the last."""
    pidfile = tmp_path / "pids"
    rows = [bad, "2222\thelper-2"] if position == "first" else ["2222\thelper-2", bad]
    pidfile.write_text("\n".join(rows) + "\n", encoding="utf-8")
    handed = _reference_is(monkeypatch, {2222: "helper-2"})
    answers = iter(["alive", "ended", "ended"])
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: next(answers))
    stops = _stop_primitives(monkeypatch)

    with pytest.raises(AssertionError, match="cannot be read") as raised:
        _end_all(pidfile)

    assert repr(bad) in str(raised.value) and f"row {rows.index(bad) + 1} " in str(raised.value)
    assert [r.pid for r in handed if r.terminated] == [2222] and handed[0].closed  # the provable helper was stopped
    assert stops.by_number == []


def test_end_all_reports_every_unreadable_row_with_the_helpers_it_could_not_clean_up(tmp_path, monkeypatch):
    pidfile = tmp_path / "pids"
    pidfile.write_text("abc\n1111\t-\n-3\t-\n", encoding="utf-8")  # two bad rows; one helper without an identity
    _states(monkeypatch, "alive", "alive")

    with pytest.raises(AssertionError) as raised:
        _end_all(pidfile)

    message = str(raised.value)
    assert "row 1 " in message and repr("abc") in message and "row 3 " in message and repr("-3\t-") in message
    assert "1111" in message and "no recorded identity" in message


def test_an_unreadable_row_is_set_aside_not_taken_for_a_helper(tmp_path):
    pidfile = tmp_path / "pids"
    pidfile.write_text("11\tnt:123\nabc\tx\n\n22\n-3\n0\n", encoding="utf-8")

    helpers, bad = _pidfile_rows(pidfile)

    assert helpers == [(11, "nt:123"), (22, None)] == _helpers(pidfile)  # the readers that only want helpers still work
    assert bad == [(2, "abc\tx"), (5, "-3"), (6, "0")]  # numbered by line: a blank line is counted but never reported
    assert _pidfile_rows(tmp_path / "absent") == ([], [])


def test_asking_the_helpers_to_stop_survives_an_unreadable_row(tmp_path, monkeypatch):
    pidfile = tmp_path / "pids"
    pidfile.write_text("abc\n2222\thelper-2\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: seen.append(pid) or "ended")

    _ask_to_stop(pidfile)  # must not raise: the stop file is written and the readable helper is waited for

    assert Path(str(pidfile) + ".stop").exists() and seen == [2222]


def _a_number_that_changes_hands_after_the_stop(monkeypatch):
    """The bare number reads "alive" at every look (an unrelated program took it after the helper was stopped), while
    the reference, bound to the helper, says it ended once it was stopped. Returns the faked references, the list of
    bare-number looks and the stop recorders."""
    looks = []

    def state(pid):
        looks.append(pid)
        return "alive"

    handed = _reference_is(monkeypatch, SAME, state=lambda ref: "ended" if ref.terminated else "alive")
    monkeypatch.setattr(sys.modules[__name__], "_state", state)
    return handed, looks, _stop_primitives(monkeypatch)


def test_end_all_asks_the_reference_it_stopped_through_whether_the_helper_ended_not_the_number(tmp_path, monkeypatch):
    """After a bound stop the exit is proven through the same reference (#749 review): a replacement process that took
    the number must not make the clean-up report the helper it stopped as still running."""
    pidfile = _pidfile_for(tmp_path, 4242)
    handed, looks, stops = _a_number_that_changes_hands_after_the_stop(monkeypatch)

    _end_all(pidfile)  # must not raise

    assert handed[0].terminated == ["helper"] and handed[0].closed
    assert looks == [4242]  # the one look before the reference was opened; none after the stop
    assert stops.by_number == []


@pytest.mark.parametrize("answer", ["alive", "unknown"])
def test_end_all_does_not_take_the_number_saying_ended_for_a_helper_its_reference_says_is_not(
    tmp_path, monkeypatch, answer
):
    """The other direction: the number may look free or reused ("ended") while the reference still says the process it
    was stopped through is running (or cannot say). Only the reference counts."""
    pidfile = _pidfile_for(tmp_path, 4242)
    handed = _reference_is(monkeypatch, SAME, state=lambda ref: answer)
    looks = iter(["alive"])
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: next(looks, "ended"))
    _fast_clock(monkeypatch)

    with pytest.raises(AssertionError, match="still running or cannot be inspected"):
        _end_all(pidfile)

    assert handed[0].terminated == ["helper"] and handed[0].closed


@pytest.mark.parametrize("answer, outcome", [("ended", None), ("alive", PermissionError), ("unknown", PermissionError)])
def test_a_denied_stop_is_accepted_only_if_the_reference_says_the_helper_ended(tmp_path, monkeypatch, answer, outcome):
    """Windows says access denied when the process ended before the stop. Whether that is an ended process is asked of
    the reference, not of the number (which may have a new owner, or be free while the helper still runs)."""
    pidfile = _pidfile_for(tmp_path, 4242)
    error = PermissionError(13, "Access is denied")
    error.winerror = 5  # what Windows adds (the constructor takes it only there); the rule is the same everywhere
    handed = _reference_is(monkeypatch, SAME, error=error, state=lambda ref: answer)
    looks = iter(["alive"])
    monkeypatch.setattr(sys.modules[__name__], "_state", lambda pid: next(looks, "ended"))  # the number says ended
    _fast_clock(monkeypatch)

    if outcome is None:
        _end_all(pidfile)
    else:
        with pytest.raises(outcome):
            _end_all(pidfile)

    assert handed[0].closed


@pytest.mark.skipif(
    os.name != "nt" and not (hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")),
    reason="needs a process handle or a pidfd to bind a stop to",
)
def test_a_real_helper_is_proven_ended_through_its_own_reference_while_its_number_looks_taken(monkeypatch):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    recorded = _identity(child.pid)
    assert recorded is not None
    real_state, looks = _state, []

    def state(pid):  # an unrelated program has the number as soon as the first look is over
        looks.append(pid)
        return real_state(pid) if len(looks) == 1 else "alive"

    monkeypatch.setattr(sys.modules[__name__], "_state", state)
    try:
        with monkeypatch.context() as patch:
            stops = _stop_primitives(patch)
            _end_one(child.pid, recorded)  # must not raise: the reference says it ended
        assert stops.by_number == []
        assert child.wait(timeout=30) is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_the_pid_file_lists_numbers_and_identities_and_still_reads_a_bare_number(tmp_path):
    pidfile = tmp_path / "pids"
    pidfile.write_text("11\tnt:123\n22\tps:Mon Nov 11 10:00:00 2026\n33\n44\t-\n", encoding="utf-8")

    assert _pids(pidfile) == [11, 22, 33, 44]
    assert _helpers(pidfile) == [(11, "nt:123"), (22, "ps:Mon Nov 11 10:00:00 2026"), (33, None), (44, None)]
    assert _helpers(tmp_path / "absent") == []


def test_the_identity_of_a_running_process_is_readable_and_stable():
    """Not that two different processes differ (two may start in the same clock tick): that ONE process answers the
    same every time, which is all the check against its own recorded identity needs."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        first, second = _identity(child.pid), _identity(child.pid)
    finally:
        child.kill()
        child.wait()

    assert first is not None and first == second


def test_the_identity_of_an_unused_number_is_unreadable():
    unused = _proven_unused_pid()
    if unused is None:
        pytest.skip("no candidate id could be shown unused by the platform's process list")

    assert _identity(unused) is None


def test_a_reference_to_an_unused_number_is_never_opened():
    unused = _proven_unused_pid()
    if unused is None:
        pytest.skip("no candidate id could be shown unused by the platform's process list")

    assert _open_reference(unused) in (_GONE, None)


@pytest.mark.parametrize(
    "how",
    [
        "native",
        "read-only",
        pytest.param("no-pidfd", marks=pytest.mark.skipif(os.name == "nt", reason="POSIX: a kernel without pidfd")),
    ],
)
def test_the_real_reference_names_the_process_it_was_opened_for_and_stops_exactly_that_one(monkeypatch, how):
    if how == "read-only":  # what macOS, and a Linux without pidfd, hand out (forced, so every system runs it)
        monkeypatch.setattr(sys.modules[__name__], "_open_reference", lambda pid: _ReadOnlyReference(pid))
    elif how == "no-pidfd":
        monkeypatch.delattr(os, "pidfd_open", raising=False)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    reference = None
    try:
        reference = _open_reference(child.pid)
        assert reference not in (None, _GONE), "a reference to a live process of this user must open"
        assert reference.identity() == _identity(child.pid)  # one scheme: what the stand-in records is what this reads
        # Where nothing binds a stop to the process (macOS, a Linux without pidfd) the reference refuses, by design;
        # where something does, it stops exactly that process. Either way, nothing is stopped by the bare number.
        stoppable = not isinstance(reference, _ReadOnlyReference)
        if how != "native":
            assert not stoppable
        with monkeypatch.context() as patch:
            stops = _stop_primitives(patch)
            if stoppable:
                reference.terminate()
                child.wait(timeout=30)  # the process it was opened for ended
            else:
                with pytest.raises(AssertionError, match="cannot be stopped safely"):
                    reference.terminate()
                assert child.poll() is None  # refused: it was not signalled and still runs
        assert stops.by_number == []
        # a pidfd signal was sent, and only where there is a pidfd to send it through
        assert (len(stops.by_reference) == 1) is (stoppable and os.name != "nt")
    finally:
        if reference not in (None, _GONE):
            reference.close()
        if child.poll() is None:
            child.kill()
            child.wait()

    assert child.returncode is not None


@pytest.mark.skipif(
    os.name != "nt" and not (hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")),
    reason="needs a process handle or a pidfd to bind a stop to",
)
def test_a_real_reference_says_whether_the_process_it_is_bound_to_has_ended():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    reference = None
    try:
        reference = _open_reference(child.pid)
        assert reference not in (None, _GONE)
        assert reference.state() == "alive"
        child.kill()
        child.wait(timeout=30)
        assert reference.state() == "ended"
    finally:
        if reference not in (None, _GONE):
            reference.close()
        if child.poll() is None:
            child.kill()
            child.wait()


def test_the_stand_in_records_the_identity_of_the_helper_it_starts(model, tmp_path):
    pidfile = tmp_path / "pids.txt"
    try:
        done = subprocess.run(
            _argv(model, "survivor-default-null", pidfile), capture_output=True, text=True, timeout=60, check=False
        )
        helpers = _helpers(pidfile)
        assert done.returncode == 0 and len(helpers) == 1
        pid, recorded = helpers[0]
        assert recorded is not None and recorded == _identity(pid)  # what it wrote is what the lookup says now
    finally:
        _end_all(pidfile)


def test_the_probe_tells_running_and_ended_processes_apart():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert _state(child.pid) == "alive"
    finally:
        child.kill()
        child.wait()
    assert _state(child.pid) == "ended"
    del child
    gc.collect()


def test_the_probe_says_ended_for_an_id_that_the_process_list_shows_unused():
    unused = _proven_unused_pid()
    if unused is None:
        pytest.skip("no candidate id could be shown unused by the platform's process list")

    assert _state(unused) == "ended"  # no such process (WinError 87 / ProcessLookupError)


def test_an_id_that_is_in_use_is_never_taken_for_unused():
    listed = _listed_as_running(os.getpid())
    if listed is None:
        pytest.skip("the platform's process list cannot be read here")

    assert listed is True
    assert _proven_unused_pid([os.getpid()]) is None


@pytest.mark.parametrize(
    "answers,expected",
    [
        ([None, None, None], None),  # nothing could be read: no id is proven unused
        ([True, True, True], None),  # everything is in use
        ([True, None, True], None),  # in use or unknown, never absent
        ([None, False, True], 11),  # an earlier unknown is passed over, never taken
        ([True, None, False, False], 12),  # the first confirmed absence, not a later one
        ([False, None, None], 10),
        ([], None),
    ],
)
def test_the_selector_takes_only_a_confirmed_absence_never_an_unknown_answer(monkeypatch, answers, expected):
    ids = [10 + i for i in range(len(answers))]
    asked = []

    def listed(pid):
        asked.append(pid)
        return answers[ids.index(pid)]

    monkeypatch.setattr(sys.modules[__name__], "_listed_as_running", listed)

    assert _proven_unused_pid(ids) == expected
    if expected is not None:
        assert asked == ids[: ids.index(expected) + 1]  # it stops at the first confirmed absence


@pytest.mark.parametrize(
    "mounts,hidden",
    [
        ("proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0\n", False),
        ("proc /proc proc rw,hidepid=2 0 0\n", True),
        ("proc /proc proc rw,hidepid=invisible,gid=100 0 0\n", True),
        ("proc /proc proc rw,hidepid=0 0 0\n", False),
        ("proc /proc proc rw,hidepid=off 0 0\n", False),
        ("proc /other proc rw,hidepid=2 0 0\nproc /proc proc rw,hidepid=1 0 0\nproc /proc proc rw 0 0\n", False),
        ("", False),
    ],
)
def test_a_proc_mounted_with_hidepid_is_recognised(mounts, hidden):
    assert _proc_mount_hides_processes(mounts) is hidden


def _fake_proc(tmp_path, mounts="proc /proc proc rw 0 0\n", live=()):
    (tmp_path / "mounts").write_text(mounts, encoding="utf-8")
    for pid in live:
        (tmp_path / str(pid)).mkdir()
    return str(tmp_path)


def test_proc_says_in_use_for_a_listed_id_and_unused_only_for_a_confirmed_absence(tmp_path):
    root = _fake_proc(tmp_path, live=[7])

    assert _listed_in_proc(7, root) is True
    assert _listed_in_proc(8, root) is False


def test_proc_says_nothing_when_an_entry_cannot_be_read(tmp_path, monkeypatch):
    root = _fake_proc(tmp_path, live=[7])
    real_stat = os.stat

    def stat(path, *args, **kwargs):
        if os.path.basename(str(path)) == "7":
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)

    assert _listed_in_proc(7, root) is None


def test_proc_says_nothing_under_hidepid_or_without_a_mount_table(tmp_path):
    hidden = _fake_proc(tmp_path, mounts="proc /proc proc rw,hidepid=2 0 0\n")
    assert _listed_in_proc(8, hidden) is None  # absence proves nothing: other users' processes are not listed
    (tmp_path / "mounts").unlink()
    assert _listed_in_proc(8, hidden) is None


def _ps_answers(monkeypatch, returncode, stdout="", stderr=""):
    done = subprocess.CompletedProcess(["ps"], returncode, stdout, stderr)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: done)


@pytest.mark.parametrize(
    "returncode,stdout,stderr,expected",
    [
        (0, "  4000000\n", "", True),
        (0, "  4000000\n", "ps: warning: some entries were skipped\n", True),  # listed stays listed
        (1, "", "", False),  # the no-match answer
        (1, "", "ps: cannot read process table: Permission denied\n", None),  # a failed query, same exit code
        (0, "", "", None),
        (2, "", "", None),
    ],
)
def test_ps_tells_a_no_match_answer_from_a_failed_query(monkeypatch, returncode, stdout, stderr, expected):
    _ps_answers(monkeypatch, returncode, stdout, stderr)

    assert _listed_by_ps(4_000_000) is expected


def test_ps_that_cannot_run_says_nothing(monkeypatch):
    def run(*args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, "ps")

    monkeypatch.setattr(subprocess, "run", run)

    assert _listed_by_ps(4_000_000) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX: how os.kill(pid, 0) errors are read")
@pytest.mark.parametrize(
    "error,expected",
    [(PermissionError(errno.EPERM, "not permitted"), "alive"), (OSError(errno.EINVAL, "bad"), "unknown")],
)
def test_the_posix_probe_reads_a_permission_error_as_alive_and_any_other_error_as_unknown(monkeypatch, error, expected):
    _kill_raises(monkeypatch, error)

    assert _state(1) == expected


def _bounded(call):
    """Run call in a thread for at most HARD_TIMEOUT; a wrapper still waiting is a failure, not a hang."""
    box: dict = {}

    def target() -> None:
        try:
            box["result"] = call()
        except BaseException as exc:  # noqa: BLE001 - reported by the test
            box["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    started = time.monotonic()
    worker.start()
    worker.join(HARD_TIMEOUT)
    return worker, box, time.monotonic() - started


def _run_plain(model: Path, mode: str, pidfile: Path, seen: list, cli: str = "codex") -> int:
    return run.run_wrapper(cli=cli, agent="worker", argv=_argv(model, mode, pidfile), render=False,
                           min_interval=0.0, heartbeat_fn=lambda event, now: seen.append(event),
                           restart_fn=lambda sig: None)


def _finished_messages(seen: list) -> tuple[bool, list[str]]:
    texts = [((event.raw or {}).get("item") or {}).get("text") for event in seen]
    return any(event.type == EventType.TURN_FINISHED for event in seen), [t for t in texts if t]


@pytest.mark.parametrize("mode", [*SURVIVORS, CONTROL])
def test_plain_wrap_stops_waiting_after_the_grace_when_a_survivor_holds_the_pipe(
        model: Path, tmp_path: Path, mode: str) -> None:
    pidfile, seen = tmp_path / "pids.txt", []
    try:
        worker, box, elapsed = _bounded(lambda: _run_plain(model, mode, pidfile, seen))
        survivors_alive = [pid for pid in _pids(pidfile) if _alive(pid)]
    finally:
        _end_all(pidfile)
        worker.join(10.0)
    assert not worker.is_alive() and elapsed < HARD_TIMEOUT, "wrap was still waiting for end of output"
    assert box.get("result") == 0, box
    assert _finished_messages(seen) == (True, ["done"])
    assert len(survivors_alive) == 1, "the survivor is left running, not killed"
    if mode == CONTROL:
        assert elapsed < GRACE, f"a normal end of output must not wait for the grace ({elapsed:.2f} s)"


def _drive(store: Store, model: Path, mode: str, pidfile: Path, *, watchdog=None, cli: str = "codex"):
    def spawn(argv, stdin):  # the stand-in ignores the prompt, so none is written to it
        return run._ProcStream(_argv(model, mode, pidfile), None, watchdog=watchdog,
                               watchdog_snapshot_fn=lambda: None, watchdog_kill_fn=lambda pids: [])

    state = session.SessionState(cli=cli, claude_session_id="sid-1" if cli == "claude" else None)
    drive = run.make_drive(store, "beta", cli, state, [cli], spawn=spawn,
                           clock=time.monotonic, render=False)
    return drive({"id": "msg-1", "from": "alpha", "to": "beta", "kind": "question", "subject": "s",
                  "body": "b", "correlation_id": "q-1", "request_id": "q-1", "broadcast_id": None,
                  "meta": {"request_id": "q-1"}})


@pytest.mark.parametrize("watchdog", [None, TurnWatchdogConfig(enabled=True)], ids=["plain-stream", "watchdog"])
@pytest.mark.parametrize("mode", [*SURVIVORS, CONTROL])
def test_loop_turn_stops_waiting_after_the_grace_when_a_survivor_holds_the_pipe(
        model: Path, tmp_path: Path, mode: str, watchdog) -> None:
    store = Store(tmp_path / "store")
    store.init(["alpha", "beta"])
    pidfile = tmp_path / "pids.txt"
    try:
        worker, box, elapsed = _bounded(lambda: _drive(store, model, mode, pidfile, watchdog=watchdog))
        survivors_alive = [pid for pid in _pids(pidfile) if _alive(pid)]
    finally:
        _end_all(pidfile)
        worker.join(10.0)
    assert not worker.is_alive() and elapsed < HARD_TIMEOUT, "wrap --loop was still waiting for end of output"
    assert box.get("result") is not None and box["result"].ok is True, box
    assert len(survivors_alive) == 1, "the survivor is left running, not killed"
    if mode == CONTROL:
        assert elapsed < GRACE + 1.0, f"a normal turn must not wait for the grace ({elapsed:.2f} s)"


def test_plain_wrap_reads_a_handed_off_turn_to_its_end(model: Path, tmp_path: Path) -> None:
    """A launcher that hands the turn to a child and exits at once: its exit alone must not start the
    grace, or the turn would be cut off while the real model is still working."""
    pidfile, seen = tmp_path / "pids.txt", []
    try:
        worker, box, elapsed = _bounded(lambda: _run_plain(model, "handoff", pidfile, seen))
    finally:
        _end_all(pidfile)
        worker.join(10.0)
    assert not worker.is_alive(), "wrap was still waiting for end of output"
    assert box.get("result") == 0, box
    assert _finished_messages(seen) == (True, ["done"]), "the handed-off turn was cut short"
    assert elapsed >= SLOW


@pytest.mark.parametrize("how", ["plain", "loop"])
@pytest.mark.parametrize("cli", ["codex", "claude"])
def test_an_event_whose_type_is_a_list_or_an_object_is_ignored_as_on_master(
        model: Path, tmp_path: Path, cli: str, how: str) -> None:
    """The end-of-run check reads a raw JSON value: a list or an object there must not raise."""
    pidfile, seen, mode = tmp_path / "pids.txt", [], f"odd-{cli}"
    if how == "plain":
        def call():
            return _run_plain(model, mode, pidfile, seen, cli=cli)
    else:
        store = Store(tmp_path / "store")
        store.init(["alpha", "beta"])

        def call():
            return _drive(store, model, mode, pidfile, cli=cli)
    try:
        worker, box, _elapsed = _bounded(call)
    finally:
        _end_all(pidfile)
        worker.join(10.0)
    assert "error" not in box, box
    assert box.get("result") == 0 if how == "plain" else box["result"].ok is True, box


@pytest.mark.parametrize("how", ["plain", "loop"])
def test_a_handed_off_claude_turn_is_read_past_its_tool_use_to_the_final_answer(
        model: Path, tmp_path: Path, how: str) -> None:
    """Claude reports turn_finished for each assistant message, a tool-use one too. Only the final
    `result` ends the invocation, so a tool that runs longer than the grace must not end the read."""
    pidfile, seen = tmp_path / "pids.txt", []
    if how == "plain":
        def call():
            return _run_plain(model, "claude-handoff", pidfile, seen, cli="claude")
    else:
        store = Store(tmp_path / "store")
        store.init(["alpha", "beta"])

        def call():
            return _drive(store, model, "claude-handoff", pidfile, cli="claude")
    try:
        worker, box, elapsed = _bounded(call)
    finally:
        _end_all(pidfile)
        worker.join(10.0)
    assert not worker.is_alive(), "wrap was still waiting for end of output"
    assert elapsed >= SLOW, f"the read ended before the final answer ({elapsed:.2f} s)"
    if how == "plain":
        assert box.get("result") == 0, box
        assert any(event.text == "final answer" for event in seen), "the final answer was dropped"
    else:
        assert box["result"].ok is True, box


@pytest.mark.parametrize("how", ["plain", "loop", "loop-watchdog"])
def test_a_survivor_that_keeps_writing_does_not_keep_wrap_waiting(model: Path, tmp_path: Path, how: str) -> None:
    """The grace is a hard bound from the turn's end: output still arriving then belongs to the survivor."""
    pidfile, seen = tmp_path / "pids.txt", []
    if how == "plain":
        def call():
            return _run_plain(model, "writing", pidfile, seen)
    else:
        store = Store(tmp_path / "store")
        store.init(["alpha", "beta"])
        watchdog = TurnWatchdogConfig(enabled=True) if how == "loop-watchdog" else None

        def call():
            return _drive(store, model, "writing", pidfile, watchdog=watchdog)
    try:
        worker, box, elapsed = _bounded(call)
        survivors_alive = [pid for pid in _pids(pidfile) if _alive(pid)]
    finally:
        _end_all(pidfile)
        worker.join(10.0)
    assert not worker.is_alive() and elapsed < GRACE + 3.0, f"wrap kept reading a writing survivor ({elapsed:.2f} s)"
    assert box.get("result") == 0 if how == "plain" else box["result"].ok is True, box
    assert len(survivors_alive) == 1, "the writing survivor is left running, not stopped"


def test_the_last_lines_before_the_turn_end_are_kept(model: Path, tmp_path: Path) -> None:
    pidfile, seen = tmp_path / "pids.txt", []
    try:
        worker, box, elapsed = _bounded(lambda: _run_plain(model, "burst-then-writing", pidfile, seen))
    finally:
        _end_all(pidfile)
        worker.join(10.0)
    assert not worker.is_alive() and elapsed < GRACE + 3.0, f"wrap kept reading a writing survivor ({elapsed:.2f} s)"
    assert box.get("result") == 0, box
    assert _finished_messages(seen) == (True, [f"line {i}" for i in range(3000)])


def _read_lines(model: Path, mode: str, pidfile: Path) -> tuple[bool, dict]:
    """Read the stand-in's output as the wrapper does, with the turn already finished."""
    proc = subprocess.Popen(_argv(model, mode, pidfile), stdout=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        worker, box, _elapsed = _bounded(lambda: list(run._iter_output_lines(proc, lambda: True)))
        timed_out = worker.is_alive()
    finally:
        _end_all(pidfile)
        proc.wait(10.0)
        worker.join(10.0)  # never close a pipe under a reader that is still running
        proc.stdout.close()
    return timed_out, box


def test_output_still_arriving_after_the_model_exits_is_kept(model: Path, tmp_path: Path) -> None:
    timed_out, box = _read_lines(model, "late-tail", tmp_path / "pids.txt")
    assert not timed_out
    assert any('"late"' in line for line in box["result"]), "output that arrived within the grace was dropped"


def test_the_grace_does_not_start_while_the_model_is_still_running(model: Path, tmp_path: Path) -> None:
    timed_out, box = _read_lines(model, "quiet-then-tail", tmp_path / "pids.txt")
    assert not timed_out
    assert any('"tail"' in line for line in box["result"]), "the read ended before the model exited"


def test_a_last_line_without_a_newline_is_kept_when_the_grace_ends(model: Path, tmp_path: Path) -> None:
    timed_out, box = _read_lines(model, "partial-survivor", tmp_path / "pids.txt")
    assert not timed_out, "the read was still waiting for end of output"
    assert box["result"][-1] == "partial"


FD_SETSIZE = 1024  # select.select refuses a descriptor at or above this


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor numbers; Windows checks the pipe with PeekNamedPipe")
def test_plain_wrap_reads_a_turn_whose_pipe_descriptor_is_above_fd_setsize(
        model: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import resource

    need = FD_SETSIZE + 64
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    raise_soft = soft != resource.RLIM_INFINITY and soft < need
    if raise_soft and hard != resource.RLIM_INFINITY and hard < need:
        pytest.skip(f"RLIMIT_NOFILE allows only {hard} open descriptors; this test needs {need}")
    real_read, pipe_fds = run._read_ready_pipe_chunk, []

    def reading(pipe):
        pipe_fds.append(pipe.fileno())
        return real_read(pipe)

    monkeypatch.setattr(run, "_read_ready_pipe_chunk", reading)
    pidfile, seen, fillers, worker = tmp_path / "pids.txt", [], [], None
    if raise_soft:
        resource.setrlimit(resource.RLIMIT_NOFILE, (need, hard))
    try:
        while not fillers or fillers[-1] < FD_SETSIZE + 8:  # every lower number taken: the pipe gets a higher one
            fillers.append(os.open(os.devnull, os.O_RDONLY))
        worker, box, _elapsed = _bounded(lambda: _run_plain(model, CONTROL, pidfile, seen))
    finally:
        for fd in fillers:
            os.close(fd)
        _end_all(pidfile)
        if worker is not None:
            worker.join(10.0)
        if raise_soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
    assert pipe_fds and min(pipe_fds) >= FD_SETSIZE, f"the pipe got descriptor(s) {set(pipe_fds)}: nothing proven"
    assert not worker.is_alive(), "wrap was still waiting for end of output"
    assert box.get("result") == 0, box
    assert _finished_messages(seen) == (True, ["done"])
