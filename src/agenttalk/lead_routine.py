"""The lead routine's record: what was completed, by what, and when (lead loop, slice 1).

``state/<lead>.lead-routine.json`` holds the sweep block (what the controller attempted and covered) and one entry per
completed part. Two kinds of writer share it, the controller's sweep and the public ``lead-routine complete``, so the
file is NOT single-writer: every update is a serialised read-modify-write under ``state/<lead>.lead-routine.lock``
(a store lock path, which the lock inventory treats as a leaf). Atomic replacement alone prevents torn JSON, not lost
updates. Each write bumps ``generation``; a controller write that carries an OLDER ``controller_start`` than the stored
one is refused, so a stale controller cannot overwrite a newer controller's record.

A completion names exactly what completed (``part``, ``kind``, what it ``covered`` and what ``failed``) and never
renews another part. Parts without a machine half (``handover``, ``resources``, ``scheduled``) are manual: they are
listed under ``manual_parts`` and are not covered by any automatic health (design, section 3).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable

from agenttalk import lead_relay
from agenttalk._atomic import write_text as _atomic_write_text
from agenttalk.store import Store, validate_agent_name

VERSION = 1
MACHINE_PARTS = ("bus", "relay")                                     # parts with a machine half the sweep can complete
JUDGEMENT_PARTS = ("seats", "spend", "gates", "learning", "self-check")
MANUAL_PARTS = ("handover", "resources", "scheduled")                # no machine half, no automatic trigger
ALL_PARTS = MACHINE_PARTS + JUDGEMENT_PARTS + MANUAL_PARTS
KINDS = ("sweep", "turn", "self-reported")


def _iso(now_epoch: float | None = None) -> str:
    dt = datetime.fromtimestamp(time.time() if now_epoch is None else now_epoch, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def record_path(store: Store, agent: str):
    return store.state_dir / ("%s.lead-routine.json" % validate_agent_name(agent))


def _lock_path(store: Store, agent: str):
    return store.state_dir / ("%s.lead-routine.lock" % validate_agent_name(agent))


def _blank() -> dict:
    return {"v": VERSION, "generation": 0, "controller_start": None, "sweep": None, "completion": {}}


def read(store: Store, agent: str) -> dict:
    """The record, degrade-safe: a missing, torn or unreadable file reads as 'nothing recorded' (a cache, not an
    authority: the obligations themselves are derived from the bus)."""
    path = record_path(store, agent)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank()
    if not isinstance(data, dict):
        return _blank()
    out = _blank()
    try:
        out["generation"] = int(data.get("generation") or 0)
    except (TypeError, ValueError):
        out["generation"] = 0
    if isinstance(data.get("controller_start"), str):
        out["controller_start"] = data["controller_start"]
    if isinstance(data.get("sweep"), dict):
        out["sweep"] = data["sweep"]
    comp = data.get("completion")
    if isinstance(comp, dict):
        out["completion"] = {k: v for k, v in comp.items() if isinstance(k, str) and isinstance(v, dict)}
    return out


def update(store: Store, agent: str, mutate: Callable[[dict], None], *, controller_start: str | None = None) -> bool:
    """Serialised read-modify-write. ``controller_start`` marks a controller write: refused (False) when the stored
    record belongs to a LATER controller start. Returns True when the record was written."""
    store.state_dir.mkdir(parents=True, exist_ok=True)
    with store._exclusive_lock(_lock_path(store, agent), timeout=5.0, what="lead routine record"):
        record = read(store, agent)
        stored = record.get("controller_start")
        if controller_start is not None:
            if isinstance(stored, str) and stored > controller_start:
                return False
            record["controller_start"] = controller_start
        mutate(record)
        record["generation"] = int(record.get("generation") or 0) + 1
        record["v"] = VERSION
        _atomic_write_text(record_path(store, agent), json.dumps(record, indent=2))
    return True


def complete(store: Store, agent: str, part: str, *, kind: str = "self-reported", covered: list[str] | None = None,
             failed: list[str] | None = None, note: str = "", now_epoch: float | None = None) -> dict:
    """Record that ``part`` was completed, by ``kind``. Changes only this part's entry."""
    if part not in ALL_PARTS:
        raise ValueError("unknown part %r (known: %s)" % (part, ", ".join(ALL_PARTS)))
    if kind not in KINDS:
        raise ValueError("unknown kind %r" % kind)
    entry = {"at": _iso(now_epoch), "kind": kind, "covered": list(covered or []), "failed": list(failed or [])}
    if note:
        entry["note"] = note[:200]

    def mutate(record: dict) -> None:
        record["completion"][part] = entry

    update(store, agent, mutate)
    return entry


def record_sweep(store: Store, agent: str, *, controller_start: str, attempted: list[str], failed: list[str],
                 now_epoch: float | None = None) -> bool:
    """The controller's write after a sweep: the sweep block, and a ``sweep`` completion for every machine part whose
    sections were read without failure. A part with a failed section gets ``failed`` instead and is NOT renewed."""
    at = _iso(now_epoch)
    sections = {"bus": ("threads", "dead_letters", "unrouted_escalations"), "relay": ("relay",)}

    def mutate(record: dict) -> None:
        record["sweep"] = {"at": at, "attempted": list(attempted), "failed": list(failed),
                           "controller_start": controller_start}
        for part, needed in sections.items():
            bad = [s for s in needed if s in failed]
            old = record["completion"].get(part, {})
            if bad:
                record["completion"][part] = {**old, "failed": bad, "failed_at": at}
            else:
                record["completion"][part] = {"at": at, "kind": "sweep", "failed": [],
                                              "covered": [s for s in needed if s in attempted]}

    return update(store, agent, mutate, controller_start=controller_start)


def status_field(store: Store, agent: str, *, now_epoch: float | None = None) -> dict | None:
    """The additive ``lead_routine`` field of a lead's ``status`` row, or None when there is nothing to show."""
    record = read(store, agent)
    try:
        obligations = lead_relay.open_obligations(lead_relay.obligations_for(store, agent))
    except Exception:  # noqa: BLE001 - advisory
        obligations = []
    now = time.time() if now_epoch is None else now_epoch
    if not record["completion"] and not record["sweep"] and not obligations:
        return None
    parts = {k: v for k, v in record["completion"].items() if k not in MANUAL_PARTS}
    manual = {k: v for k, v in record["completion"].items() if k in MANUAL_PARTS}
    overdue = [o for o in obligations if lead_relay.age_seconds(o, now) >= lead_relay.RELAY_DEADLINE_SECONDS]
    return {"sweep": record["sweep"], "parts": parts, "manual_parts": manual, "open_relays": len(obligations),
            "overdue_relays": len(overdue), "generation": record["generation"]}
