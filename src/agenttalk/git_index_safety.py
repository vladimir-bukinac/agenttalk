"""Read-only checks for work that status and parent WIP commits can miss."""

from dataclasses import dataclass
import ntpath
import os
from pathlib import Path
import re
import stat
import subprocess  # nosec B404

from agenttalk import printed_commands as pc

HIDDEN = (
    "Git is skipping checks on tracked files; save or inspect them before clearing assume-unchanged or skip-worktree"
)
UNKNOWN = "could not check whether Git is hiding tracked files"
SUBMODULE = (
    "checkout contains a materialized submodule; save its work separately and remove or deinitialize it "
    "yourself before retrying"
)
SUBMODULE_UNKNOWN = "could not check whether this checkout contains a materialized submodule"
IGNORE_STAT = (
    "core.ignoreStat is enabled: Git can skip checks on tracked files; save or inspect the work, "
    "disable that setting and refresh the index before retrying"
)


def status_args(untracked="normal"):
    """Fixed policies for tracked lanes, removals and complete acceptance checks."""
    if untracked not in {"no", "normal", "all"}:
        raise ValueError("unsupported untracked policy")
    return [
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "status",
        "--porcelain",
        f"--untracked-files={untracked}",
        "--ignore-submodules=untracked" if untracked == "no" else "--ignore-submodules=none",
    ]


STATUS_ARGS = [
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.untrackedCache=false",
    "status",
    "--porcelain",
    "--untracked-files=normal",
    "--ignore-submodules=none",
]


@dataclass(frozen=True)
class Inspection:
    state: str
    reason: str | None = None


def _checkout_root(root, *, env=None):
    command = ["git", "-C", str(root), "rev-parse", "--show-toplevel"]
    # Fixed read-only Git command, with no shell or user-selected operation.
    result = subprocess.run(command, capture_output=True, timeout=15, env=env)  # noqa: S603  # nosec B603
    if result.returncode != 0 or not isinstance(result.stdout, bytes) or not result.stdout.endswith(b"\n"):
        raise ValueError("checkout root read failed")
    raw = result.stdout[:-1]
    name = os.fsdecode(raw)
    checkout = Path(name)
    if not raw or b"\0" in raw or os.fsencode(name) != raw or not checkout.is_absolute():
        raise ValueError("invalid checkout root")
    return checkout


def _records(root, option, *, env=None):
    command = ["git", "-C", str(root), "ls-files", "--cached", option, "-z", "--full-name"]
    # Fixed read-only Git command, with no shell or user-selected operation.
    result = subprocess.run(  # noqa: S603  # nosec B603
        command,
        capture_output=True,
        timeout=15,
        env=env,
    )
    if result.returncode != 0 or not isinstance(result.stdout, bytes):
        raise ValueError("index read failed")
    output = result.stdout
    if not output:
        return []
    if not output.endswith(b"\0"):
        raise ValueError("incomplete index listing")
    return output[:-1].split(b"\0")


def _path(raw):
    name = os.fsdecode(raw)
    if (
        os.fsencode(name) != raw
        or not name
        or (os.name == "nt" and ntpath.splitdrive(name)[0])
        or name.startswith("/")
        or (os.name == "nt" and name.startswith("\\"))
        or (os.name == "nt" and ":" in name)
    ):
        raise ValueError("invalid index path")
    parts = re.split(r"[\\/]" if os.name == "nt" else "/", name)
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("escaping index path")
    return Path(*parts)


def _plain_directory(info):
    return (
        stat.S_ISDIR(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and not (getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    )


def _entry(root, relative):
    """Absence is safe only below verified plain directory prefixes."""
    current = Path(root)
    if not _plain_directory(os.lstat(current)):
        raise ValueError("uncertain checkout root")
    parts = relative.parts
    for number, part in enumerate(parts):
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            # Every earlier prefix was proved to be a real directory. In particular,
            # Windows WinError 3 below a plain file cannot reach this exception.
            return None
        if number == len(parts) - 1:
            return info
        if not _plain_directory(info):
            raise ValueError("uncertain index path ancestry")
    raise ValueError("empty index path")


def check_hidden_index(root) -> Inspection:
    try:
        return check_hidden_index_at_root(_checkout_root(root))
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return Inspection("unverifiable", UNKNOWN)


def check_hidden_index_at_root(root, *, env=None) -> Inspection:
    """Inspect an absolute checkout top level already verified by the caller.

    This entry does not discover or authenticate a root. Acceptance verifies it
    earlier in its command and rechecks live HEAD at every original boundary.
    """
    try:
        root = Path(root)
        if not root.is_absolute():
            raise ValueError("relative checkout root")
        hidden = False
        for record in _records(root, "-v", env=env):
            if len(record) < 3 or record[1:2] != b" " or record[:1] not in [bytes([c]) for c in b"HSMRCK?hsmrck"]:
                raise ValueError("invalid index tag")
            tag, path = record[:1], _path(record[2:])
            if tag in [bytes([c]) for c in b"hsmrck"]:
                hidden = True
            elif tag == b"S" and _entry(root, path) is not None:
                hidden = True
        return Inspection("hidden", HIDDEN) if hidden else Inspection("safe")
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return Inspection("unverifiable", UNKNOWN)


def check_materialized_submodules(root) -> Inspection:
    try:
        root = _checkout_root(root)
        hidden = False
        for record in _records(root, "--stage"):
            header, separator, raw = record.partition(b"\t")
            if not separator or not re.fullmatch(
                rb"(?:100644|100755|120000|160000) [0-9a-f]{40}(?:[0-9a-f]{24})? [0-3]", header
            ):
                raise ValueError("invalid staged index record")
            path = _path(raw)
            if not header.startswith(b"160000 "):
                continue
            info = _entry(root, path)
            if info is None:
                continue
            if not _plain_directory(info):
                hidden = True
            else:
                with os.scandir(Path(root) / path) as entries:
                    if next(entries, None) is not None:
                        hidden = True
        return Inspection("hidden", SUBMODULE) if hidden else Inspection("safe")
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return Inspection("unverifiable", SUBMODULE_UNKNOWN)


def keep_reason(root) -> str | None:
    flags = check_hidden_index(root)
    return flags.reason or check_materialized_submodules(root).reason


def inspection_guidance(folder, *, uncertain=False, env=None) -> str:
    label = "Checkout folder"
    try:
        folder = _checkout_root(folder, env=env)
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        label = "Folder checked"
        templates = ["git -C {folder} rev-parse --show-toplevel"]
        uncertain = True
    else:
        templates = ["git -C {folder} ls-files -v"]
    if not uncertain:
        templates += [
            "git -C {folder} update-index --no-assume-unchanged -- <file>",
            "git -C {folder} update-index --no-skip-worktree -- <file>",
        ]
    commands, note = pc.cmds(
        templates,
        folder=str(folder),
        shown_limit=pc.PATH_SHOWN_MAX_CHARACTERS,
        source="is the local folder being inspected",
        lookup="use the full checkout path from this operation; select a file only after inspection",
    )
    text = (
        f"{label}: {pc.line(str(folder))}. First save or inspect the work. "
        "List the files: lowercase tags mean assume-unchanged, "
        "and S means skip-worktree. "
    )
    if not uncertain:
        text += "Lowercase s means both. Clear only the flag you have inspected, then retry. "
    if "--show-toplevel" in templates[0]:
        text += "Resolve the checkout top-level first, then use that folder to inspect the index. "
    text += "Replace the placeholders before running a template. " + "; ".join(f"`{command}`" for command in commands)
    return text + (f" ({note})" if note else "")
