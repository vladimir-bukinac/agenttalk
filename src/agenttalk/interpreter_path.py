"""The Python interpreter path agenttalk hands to child processes (#493).

On Linux and macOS ``python -m venv`` makes the environment's ``python`` a LINK to the system
Python. The packages live with the environment, found through ``pyvenv.cfg`` beside the link, so
the link has to be started as the link: following it (``Path.resolve``) lands on the system Python,
which has no agenttalk ("No module named agenttalk"). The path is therefore used as the process
was started, made absolute but never resolved through links.

Windows keeps the resolved path it always used: a Windows environment holds a copy or launcher
rather than a link, so resolving changes nothing there and the long-standing behaviour is kept.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def launch_path(executable: str | os.PathLike[str] | None = None, *, windows: bool | None = None) -> str:
    """``executable`` (default: the running interpreter) as a launchable absolute path."""
    exe = os.fspath(executable if executable is not None else sys.executable)
    if (os.name == "nt") if windows is None else windows:
        return str(Path(exe).resolve())
    return os.path.abspath(exe)
