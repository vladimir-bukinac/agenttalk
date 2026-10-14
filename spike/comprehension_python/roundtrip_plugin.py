"""pytest plugin for spike question S4: every Java result the comprehension tests produce at a public
boundary is round-tripped through FileClaims, and the session reports any that do not come back exactly.

Boundaries checked (finished results only, not the adapter's intermediate objects):
- what parse_java_source returns;
- what file_result_to_json is given (the worker's wire format, so pom.xml and web.xml results too);
- what file_result_from_json returns (what the scan pipeline reads back).

Use: PYTHONPATH=src;spike  python -m pytest -p comprehension_python.roundtrip_plugin tests/test_*comprehension*.py
Results go to the file named by SPIKE_ROUNDTRIP_OUT (JSON).

SPIKE CODE - DO NOT MERGE.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter

from agenttalk.comprehension.adapters import java as java_adapter

from .java_convert import round_trip_problem

_STATS = Counter()
_SEEN_DIGESTS: set[str] = set()
_FAILURES: list[str] = []
_original_to_json = java_adapter.file_result_to_json


def _check(result, where: str) -> None:
    _STATS[f"checked_at_{where}"] += 1
    digest = hashlib.sha256(json.dumps(_original_to_json(result), sort_keys=True).encode()).hexdigest()
    if digest in _SEEN_DIGESTS:
        return
    _SEEN_DIGESTS.add(digest)
    problem = round_trip_problem("x.java", result)
    if problem:
        _STATS["failed"] += 1
        if len(_FAILURES) < 20:
            _FAILURES.append(f"{where}: {problem}")


def _wrap(name: str, check_arg: bool):
    original = getattr(java_adapter, name)

    def wrapper(*args, **kwargs):
        if check_arg and args:
            _check(args[0], name)
        result = original(*args, **kwargs)
        if not check_arg:
            _check(result, name)
        return result

    setattr(java_adapter, name, wrapper)


_wrap("parse_java_source", check_arg=False)
_wrap("file_result_to_json", check_arg=True)
_wrap("file_result_from_json", check_arg=False)


def pytest_sessionfinish(session, exitstatus):
    report = {"distinct_results": len(_SEEN_DIGESTS), "failed": _STATS["failed"], "failures": _FAILURES,
              "checks_by_boundary": {k: v for k, v in _STATS.items() if k.startswith("checked_at_")},
              "pytest_exit_status": int(exitstatus)}
    out = os.environ.get("SPIKE_ROUNDTRIP_OUT")
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
