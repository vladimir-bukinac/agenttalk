"""Lesson packs: curated lessons that a new team's store starts with.

A pack is a file in ``knowledge_packs/`` (``<name>.jsonl``, one lesson per line; an optional
``<name>.retired.json`` lists slugs a later version took back). Loading writes ordinary
``process`` lessons into the team's knowledge store, so retract, search and ``lessons_used``
citations work as for any lesson. What marks a pack lesson:

  * the key ``pack.<name>:<slug>`` (the ``pack.`` prefix is reserved for new publishes),
  * the author, owner and curator ``agenttalk-pack``, and the tag ``pack-<name>``,
  * the provenance pair that proves the loader wrote an event: the author and ``authority.resolved_from``
    set to ``pack``. No ordinary command can set it, so a team member who is called ``agenttalk-pack``
    cannot fake it (the name is also reserved for new rosters and new publishes),
  * the rank: the team's own lessons always come first, and pack lessons never take one of the
    lesson slots injected into a turn. That rank is by where the CONTENT came from: each event carries the
    origin of the publish that produced it, so a reader gets the origin of the version it displays
    (``knowledge.pack_origin_ids``). A team's verify of an unchanged pack lesson does not make it the
    team's. Ownership on reload and unload is a different question, by who acted LAST (a team
    curation is a touch).

The pack name and version are NOT in the events (the event schema is closed). They live in a
ledger, ``knowledge/packs.json``: per pack its version and, per key, the hash of what was loaded.
Who owns a lesson is read from the store (the provenance pair above), not from the ledger, so a run cut
short before the ledger was written is recovered by the next one. The team always wins: a key the team
retracted, republished, re-verified or superseded with a lesson of its own is left alone on every reload,
upgrade and unload; the loader undoes only its own retraction.

An outside pack is the same file in a folder the user checked out themselves (``load <name> --from
<folder>``; agenttalk never fetches it). Its id is ``ext.<name>``: keys ``pack.ext.<name>:<slug>``, tag
``pack-ext.<name>``, ledger entry ``ext.<name>``. A shipped pack name cannot hold a dot, so no shipped
pack, today's or a later one, can meet an outside pack's keys or tags. The ledger entry also records
where the pack came from (folder, file hash, and the HEAD commit when the folder is a git checkout).
Only lessons are read from the folder, never roles, prompts or brief templates.

``export`` goes the other way: it writes some of the team's own verified lessons as a pack file, as
review candidates for another team, and a separate provenance file that stays with the exporting team.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import re
import shutil
import subprocess  # nosec B404 - one fixed read-only git argv, shell disabled
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from agenttalk import _atomic, knowledge as kn

PACKS_DIR = Path(__file__).resolve().parent / "knowledge_packs"
LEDGER_FILENAME = "packs.json"
LEDGER_SCHEMA = 1
PACK_AUTHOR = kn.PACK_AUTHOR
PACK_RESOLVED_FROM = kn.PACK_RESOLVED_FROM
DEFAULT_PACKS = ("migration",)
REVIEW_AFTER_DAYS = 365
EXPIRES_AFTER_DAYS = 730
OUTSIDE_PREFIX = "ext."             # outside pack ids; shipped pack names never contain a dot

_PACK_NAME_RE = re.compile(r"\A[a-z][a-z0-9-]{0,39}\Z")
_SLUG_RE = re.compile(r"\A[a-z0-9]+(-[a-z0-9]+)*\Z")
_SLUG_MAX = 60
_LINE_KEYS = ["key", "scope", "trigger", "body", "applies_to", "evidence", "pack", "pack_version"]
_CONFIRMED_AT = "confirmed_at"      # optional last line field: when the lesson was last confirmed
_RESERVED_TAG_PREFIXES = ("pack-", kn.PACK_KEY_PREFIX)
_COMMIT_RE = re.compile(r"\A[0-9a-f]{40}([0-9a-f]{24})?\Z")
_STATE_LOADED = "loaded"
_STATE_RETRACTED = "retracted"      # retracted by the loader (retired, removed or unloaded)


@dataclass(frozen=True)
class PackLesson:
    slug: str
    key: str                # pack.<id>:<slug>
    scope: str
    trigger: str
    body: str
    tags: tuple[str, ...]
    evidence: str
    source_hash: str
    confirmed_at: datetime | None = None


@dataclass(frozen=True)
class Pack:
    name: str               # the pack id: a shipped name, or ext.<name> for an outside pack
    version: int
    lessons: tuple[PackLesson, ...]
    retired: tuple[str, ...] = ()
    source: dict[str, str] | None = None    # outside packs only: where the pack came from


@dataclass
class Report:
    pack: str
    version: int
    published: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    retracted: list[str] = field(default_factory=list)
    kept_for_team: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    source: dict[str, str] | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {"pack": self.pack, "version": self.version, "published": self.published,
               "updated": self.updated, "retracted": self.retracted,
               "kept_for_team": self.kept_for_team, "unchanged": self.unchanged}
        if self.source is not None:
            out["source"] = self.source
        return out

    def changed(self) -> bool:
        return bool(self.published or self.updated or self.retracted)


def pack_key(name: str, slug: str) -> str:
    return f"{kn.PACK_KEY_PREFIX}{name}:{slug}"


def _check_name(name: object) -> str:
    if not isinstance(name, str) or not _PACK_NAME_RE.match(name):
        raise kn.KnowledgeError(f"{name!r} is not a valid pack name")
    return name


def available() -> list[str]:
    """Names of the packs that ship with this install."""
    if not PACKS_DIR.is_dir():
        return []
    return sorted(p.stem for p in PACKS_DIR.glob("*.jsonl") if _PACK_NAME_RE.match(p.stem))


def outside_id(name: str) -> str:
    """The id an outside pack is stored under; it holds a dot, which no shipped pack name can."""
    return f"{OUTSIDE_PREFIX}{name}"


def _refuse_shipped_name(name: str, what: str) -> None:
    if name in available():
        raise kn.KnowledgeError(
            f"{name!r} is the name of a pack that ships with agenttalk; give the {what} another name")


def read_pack(name: str, *, folder: Path | str | None = None, now: datetime | None = None) -> Pack:
    """Read and validate a pack file; any bad line refuses the whole pack. Without ``folder`` it is a
    shipped pack; with it, the outside pack ``<folder>/<name>.jsonl`` under the id ``ext.<name>``."""
    _check_name(name)
    if folder is None:
        pack_id, path = name, PACKS_DIR / f"{name}.jsonl"
        if not path.is_file():
            raise kn.KnowledgeError(f"unknown pack {name!r} (available: {', '.join(available()) or 'none'})")
    else:
        _refuse_shipped_name(name, "outside pack")
        directory = Path(folder).resolve()
        if not directory.is_dir():
            raise kn.KnowledgeError(f"pack {name}: the folder {directory} does not exist")
        pack_id, path = outside_id(name), directory / f"{name}.jsonl"
        if not path.is_file():
            raise kn.KnowledgeError(f"pack {name}: there is no file {path}")
    at = now or datetime.now(timezone.utc)
    data = path.read_bytes()
    lessons, versions, line_of = _parse_lessons(data, name=name, pack_id=pack_id, at=at)
    if not lessons:
        raise kn.KnowledgeError(f"pack {name} has no lessons")
    if len(versions) != 1:
        raise kn.KnowledgeError(f"pack {name}: every line must carry the same pack_version, got {sorted(versions)}")
    retired_path = path.with_name(f"{name}.retired.json")
    retired = _read_retired(name, retired_path)
    carried = [slug for slug in retired if slug in line_of]
    if carried:      # the retirement would silently cancel these lessons
        raise kn.KnowledgeError(
            f"pack {name}: {retired_path.name} retires "
            + ", ".join(f"{slug!r} (line {line_of[slug]})" for slug in carried)
            + ", which the pack still carries; take each one out of one of the two files")
    source = None
    if folder is not None:
        source = {"folder": str(path.parent), "file_sha256": hashlib.sha256(data).hexdigest()}
        if retired_path.is_file():
            source["retired_sha256"] = hashlib.sha256(retired_path.read_bytes()).hexdigest()
        commit = _git_head(path.parent)
        if commit:
            source["commit"] = commit
    return Pack(name=pack_id, version=versions.pop(), lessons=tuple(lessons), retired=retired, source=source)


def _physical_lines(data: bytes) -> list[bytes]:
    """The records of a JSONL file. Only a newline ends a record: ``str.splitlines()`` would also split at
    U+0085, U+2028 and U+2029, which JSON writes unescaped inside a string."""
    return [line.removesuffix(b"\r") for line in data.removeprefix(codecs.BOM_UTF8).split(b"\n")]


def _parse_lessons(data: bytes, *, name: str, pack_id: str,
                   at: datetime) -> tuple[list[PackLesson], set[int], dict[str, int]]:
    """Every lesson in a pack file, the versions its lines carry, and the line of each slug. Any bad line
    refuses the pack, with the pack name and the line number."""
    lessons: list[PackLesson] = []
    versions: set[int] = set()
    line_of: dict[str, int] = {}
    seen: set[str] = set()
    for number, chunk in enumerate(_physical_lines(data), 1):
        try:
            line = chunk.decode("utf-8")
            if not line.strip():
                continue
            lesson, version = _read_line(line, name=name, pack_id=pack_id, seen=seen, at=at)
        except UnicodeDecodeError as exc:
            raise kn.KnowledgeError(f"pack {name} line {number}: not UTF-8 text ({exc.reason})") from exc
        except kn.KnowledgeError as exc:
            raise kn.KnowledgeError(f"pack {name} line {number}: {exc}") from exc
        versions.add(version)
        lessons.append(lesson)
        line_of[lesson.slug] = number
    return lessons, versions, line_of


def _read_line(line: str, *, name: str, pack_id: str, seen: set[str], at: datetime) -> tuple[PackLesson, int]:
    """One pack line as a lesson, validated the way the store will validate it."""
    try:
        raw = json.loads(line)
    except ValueError as exc:
        raise kn.KnowledgeError(f"invalid json: {exc}") from exc
    try:
        json.dumps(raw, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError as exc:       # an escaped half of a surrogate pair, alone
        raise kn.KnowledgeError("the text holds invalid Unicode (an unpaired surrogate)") from exc
    if not isinstance(raw, dict) or list(raw) not in (_LINE_KEYS, [*_LINE_KEYS, _CONFIRMED_AT]):
        raise kn.KnowledgeError(f"keys must be exactly {_LINE_KEYS}, optionally followed by {_CONFIRMED_AT!r}")
    slug = raw["key"]
    if isinstance(slug, str) and slug.startswith(kn.PACK_KEY_PREFIX):
        raise kn.KnowledgeError(
            f"key {slug!r} uses the reserved prefix {kn.PACK_KEY_PREFIX!r}: write the bare slug, "
            "agenttalk adds the pack's own prefix")
    if not isinstance(slug, str) or not _SLUG_RE.match(slug) or len(slug) > _SLUG_MAX:
        raise kn.KnowledgeError(f"key {slug!r} is not a safe slug")
    if slug in seen:
        raise kn.KnowledgeError(f"duplicate key {slug!r}")
    seen.add(slug)
    if raw["pack"] != name:
        raise kn.KnowledgeError(f"pack field is {raw['pack']!r}")
    version = raw["pack_version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise kn.KnowledgeError("pack_version must be a whole number")
    tags = raw["applies_to"]
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise kn.KnowledgeError("applies_to must be a list of tags")
    for tag in tags:
        if tag.casefold().startswith(_RESERVED_TAG_PREFIXES):
            raise kn.KnowledgeError(f"tag {tag!r} is reserved: agenttalk adds the pack's own tag")
    for text_field in ("scope", "trigger", "body", "evidence"):
        if not isinstance(raw[text_field], str):
            raise kn.KnowledgeError(f"{text_field} must be text")
    lesson = PackLesson(
        slug=slug, key=pack_key(pack_id, slug), scope=raw["scope"], trigger=raw["trigger"],
        body=raw["body"], tags=tuple(tags), evidence=raw["evidence"],
        # The version is left out, so a new pack version rewrites only the lessons whose text changed.
        source_hash=hashlib.sha256(json.dumps(
            {k: v for k, v in raw.items() if k != "pack_version"}, sort_keys=True).encode("utf-8")).hexdigest(),
        confirmed_at=_confirmed_at(raw.get(_CONFIRMED_AT), at) if _CONFIRMED_AT in raw else None)
    lesson_for_store(lesson, at)
    kn.validate_key(lesson.key)
    kn.validate_body(lesson.body)
    return lesson, version


def _confirmed_at(value: object, at: datetime) -> datetime:
    """When the lesson was last confirmed: an ISO date or date and time, never later than the load (a date
    in the future would make the advice look fresher than it is)."""
    if not isinstance(value, str):
        raise kn.KnowledgeError(f"{_CONFIRMED_AT} must be an ISO date or date and time")
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise kn.KnowledgeError(f"{_CONFIRMED_AT} {value!r} is not an ISO date or date and time") from exc
    moment = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
    if moment > at:
        raise kn.KnowledgeError(f"{_CONFIRMED_AT} {value!r} is in the future")
    return moment


def _read_retired(name: str, path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise kn.KnowledgeError(f"pack {name}: {path.name} is not valid json: {exc}") from exc
    if not isinstance(raw, list) or not all(isinstance(s, str) and _SLUG_RE.match(s) for s in raw):
        raise kn.KnowledgeError(f"pack {name}: {path.name} must be a list of lesson slugs")
    return tuple(raw)


def _git_head(folder: Path) -> str | None:
    """The HEAD commit of the git checkout that holds ``folder``, or None. Read only: ``rev-parse``
    changes nothing, and agenttalk never fetches or authenticates."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        done = subprocess.run(  # nosec B603 - resolved executable, argv list
            [git, "-C", str(folder), "rev-parse", "--verify", "--quiet", "HEAD"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    head = done.stdout.strip()
    return head if done.returncode == 0 and _COMMIT_RE.match(head) else None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def lesson_for_store(lesson: PackLesson, now: datetime) -> dict[str, Any]:
    """The store's lesson object for a pack lesson: evidence becomes evidence_ref, the pack tag is
    added, and the dates count from when the lesson was last confirmed, or else from the load."""
    name = lesson.key[len(kn.PACK_KEY_PREFIX):].split(":", 1)[0]
    tags = list(dict.fromkeys([*lesson.tags, f"pack-{name}"]))
    base = lesson.confirmed_at or now
    stored = {
        "scope": lesson.scope, "trigger": lesson.trigger, "evidence_ref": lesson.evidence,
        "applies_to": tags, "owner": PACK_AUTHOR,
        "review_after": _iso(base + timedelta(days=REVIEW_AFTER_DAYS)),
        "expires_at": _iso(base + timedelta(days=EXPIRES_AFTER_DAYS)),
    }
    return kn.validate_lesson(stored, default_status=kn.LESSON_STATUS_PROPOSED)


# ---------------------------------------------------------------- the ledger

def ledger_path(store) -> Path:
    return kn.knowledge_dir(store) / LEDGER_FILENAME


def read_ledger(store) -> dict[str, Any]:
    path = ledger_path(store)
    if not path.is_file():
        return {"schema_version": LEDGER_SCHEMA, "packs": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise kn.KnowledgeError(f"{path} is not valid json ({exc}); fix or remove it") from exc
    if not isinstance(data, dict) or not isinstance(data.get("packs"), dict):
        raise kn.KnowledgeError(f"{path} is not a pack ledger; fix or remove it")
    problem = _ledger_problem(data)
    if problem:
        raise kn.KnowledgeError(f"{path} is not a pack ledger ({problem}); fix or remove it")
    return data


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _ledger_problem(data: dict) -> str:
    """Why a ledger with a valid top level cannot be used, or an empty string. Every later command indexes
    entry["version"] and entry["keys"], so a hand-edited or newer ledger must stop here, with a plain error."""
    if data.get("schema_version") != LEDGER_SCHEMA:
        return f"schema_version {data.get('schema_version')!r}, expected {LEDGER_SCHEMA}"
    for name, entry in data["packs"].items():
        if (not isinstance(entry, dict) or not _is_count(entry.get("version"))
                or not isinstance(entry.get("keys"), dict)):
            return f"pack {name!r} needs a whole-number version and a keys object"
        for key, state in entry["keys"].items():
            if not isinstance(state, dict) or not all(isinstance(v, str) for v in state.values()):
                return f"pack {name!r}, key {key!r}: the key state must be an object of text values"
        source = entry.get("source", {})
        if not isinstance(source, dict) or not all(isinstance(v, str) for v in source.values()):
            return f"pack {name!r}: the source must be an object of text values"
    return ""


def _write_ledger(store, ledger: dict[str, Any]) -> None:
    _atomic.write_text(ledger_path(store), json.dumps(ledger, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------- who owns a lesson

def _is_ours(event: dict | None) -> bool:
    """True when the loader wrote this event. The proof is its provenance pair (author and
    ``authority.resolved_from == "pack"``), which no ordinary command can produce: a member of the team
    who is called ``agenttalk-pack`` still publishes as ``active_agent`` and curates as curator, owner or
    lead. The name alone is never enough."""
    return bool(event) and kn.has_loader_marks(event)


def _retracted_by_loader(latest: dict) -> bool:
    return kn.is_retracted(latest) and _is_ours(latest)


def _team_touched(view: dict | None, superseded: set[str], key: str) -> bool:
    """True when the team has done anything to a lesson the loader wrote: replaced its text, retracted it,
    re-verified it (the latest event is no longer the loader's), or superseded it with a lesson of its own.

    Ownership is read from the store itself, not from the ledger, so a load or unload that was cut short
    before the ledger was written is recovered on the next run. The one thing the loader undoes is its
    own retraction (an earlier unload or retirement)."""
    if view is None:
        return False
    if not _is_ours(view.get("latest")):
        return True
    return key in superseded


def _superseded_keys(views: dict[tuple, dict]) -> set[str]:
    curated = [rec["curated"] for rec in views.values()
               if rec.get("curated") is not None
               and rec["curated"].get("type") == kn.TYPE_LESSON
               and kn.is_curated(rec["curated"]) and not kn.is_retracted(rec["curated"])]
    return kn.lesson_superseded_keys(curated)


def _matches(latest: dict, lesson: PackLesson) -> bool:
    """True when the stored lesson has the text of the pack lesson. Dates count only when the line says
    when it was last confirmed: then a newer confirmation is a change. Otherwise they are the load's."""
    stored = latest.get("lesson") or {}
    wanted = lesson_for_store(lesson, datetime.now(timezone.utc))
    fields = ("scope", "trigger", "evidence_ref", "applies_to")
    if lesson.confirmed_at is not None:
        fields += ("review_after", "expires_at")
    return latest.get("body") == lesson.body and all(stored.get(f) == wanted[f] for f in fields)


def _store_keys(views: dict[tuple, dict], name: str) -> set[str]:
    prefix = pack_key(name, "")
    return {key for (domain, key) in views if domain == kn.PROCESS_DOMAIN and key.startswith(prefix)}


RegistryHashes = Callable[[], "tuple[str, str]"]     # () -> (registry_hash, process_definition_hash)


def _publish_events(lesson: PackLesson, *, hashes: tuple[str, str], at: datetime) -> tuple[dict, dict]:
    registry_hash, definition_hash = hashes
    when = _iso(at)
    publish = kn.new_publish_event(
        note_id=kn.new_note_id(), key=lesson.key, type=kn.TYPE_LESSON, domain_id=kn.PROCESS_DOMAIN,
        body=lesson.body, anchor=None, verified_against_sha=None, domain_registry_hash=registry_hash,
        domain_definition_hash=definition_hash, author=PACK_AUTHOR, resolved_from=PACK_RESOLVED_FROM,
        at=when, lesson=lesson_for_store(lesson, at))
    curate = kn.new_curate_event(
        base=publish, action="verify", curated_by=PACK_AUTHOR, resolved_from=PACK_RESOLVED_FROM,
        at=when, reason=None, domain_registry_hash=registry_hash, domain_definition_hash=definition_hash)
    return publish, curate


def _retract_event(latest: dict, *, reason: str, hashes: tuple[str, str], at: datetime) -> dict:
    registry_hash, definition_hash = hashes
    return kn.new_curate_event(
        base=latest, action="retract", curated_by=PACK_AUTHOR, resolved_from=PACK_RESOLVED_FROM,
        at=_iso(at), reason=reason, domain_registry_hash=registry_hash,
        domain_definition_hash=definition_hash)


def _ledger_entry(latest: dict, source_hash: str, state: str) -> dict[str, str]:
    return {"hash": kn.payload_hash(latest), "source": source_hash, "state": state}


# ---------------------------------------------------------------- load and unload

def load(store, name: str, *, registry: RegistryHashes, now: datetime | None = None,
         dry_run: bool = False, folder: Path | str | None = None) -> Report:
    """Load (or upgrade) a pack: a shipped one, or with ``folder`` an outside one. Writes nothing when
    the same version is already loaded.

    The events are written first and the ledger last. A run cut short between the two is recovered by
    the next load, which adopts the lessons it finds already written by the loader (same author, same
    text) instead of writing them again, and completes a lesson whose curate event is missing."""
    at = now or datetime.now(timezone.utc)
    pack = read_pack(name, folder=folder, now=at)
    name = pack.name
    report = Report(pack=name, version=pack.version, source=pack.source)
    with store._config_lock():
        hashes = registry()
        views, _problems = kn.resolve_views_with_problems(kn.read_events(store)[0])
        superseded = _superseded_keys(views)
        ledger = read_ledger(store)
        entry = ledger["packs"].get(name) or {"version": 0, "keys": {}}
        if pack.version < entry.get("version", 0):
            raise kn.KnowledgeError(
                f"pack {name} version {pack.version} is older than the loaded version {entry['version']}")
        keys: dict[str, dict] = {k: dict(v) for k, v in entry["keys"].items()}
        writes: list[dict] = []
        wanted = {lesson.key: lesson for lesson in pack.lessons}
        retired = {pack_key(name, slug) for slug in pack.retired}

        # Take back what a later version retired or removed, unless the team touched it.
        known = set(keys) | _store_keys(views, name)
        for key in sorted((known - set(wanted)) | (retired & known)):
            view = views.get((kn.PROCESS_DOMAIN, key))
            if view is None or (key not in keys and not _is_ours(view.get("latest"))):
                continue                                    # nothing written, or a key the team made
            if _team_touched(view, superseded, key):
                report.kept_for_team.append(key)
                continue
            latest = view["latest"]
            if not _retracted_by_loader(latest):
                why = "retired" if key in retired else "removed"
                writes.append(_retract_event(
                    latest, reason=f"{why} in pack {name} version {pack.version}", hashes=hashes, at=at))
                report.retracted.append(key)
            keys[key] = {**keys.get(key, {"hash": kn.payload_hash(latest), "source": ""}),
                         "state": _STATE_RETRACTED}

        for lesson in pack.lessons:
            key = lesson.key
            if key in retired:
                continue
            view = views.get((kn.PROCESS_DOMAIN, key))
            if view is None:
                action = "published"
            elif _team_touched(view, superseded, key):
                report.kept_for_team.append(key)            # always checked first: the team wins
                continue
            else:
                latest = view["latest"]
                if _retracted_by_loader(latest) or not kn.is_curated(latest):
                    action = "published"                    # reopen our own retraction, or finish a cut-short load
                elif _matches(latest, lesson):
                    report.unchanged.append(key)
                    keys[key] = _ledger_entry(latest, lesson.source_hash, _STATE_LOADED)
                    continue
                else:
                    action = "updated"
            publish, curate = _publish_events(lesson, hashes=hashes, at=at)
            writes.extend([publish, curate])
            keys[key] = _ledger_entry(publish, lesson.source_hash, _STATE_LOADED)
            (report.published if action == "published" else report.updated).append(key)

        if dry_run:
            return report
        for event in writes:
            kn.write_event_locked(store, event)
        new_entry: dict[str, Any] = {"version": pack.version, "keys": keys}
        if pack.source is not None:
            new_entry["source"] = pack.source
        if new_entry != entry:
            ledger["packs"][name] = new_entry
            ledger["schema_version"] = LEDGER_SCHEMA
            _write_ledger(store, ledger)
    return report


def _held(ledger: dict, views: dict[tuple, dict], pack_id: str) -> tuple[dict | None, set[str]]:
    """The ledger entry of a pack and the keys whose latest event the loader wrote."""
    ours = {key for key in _store_keys(views, pack_id) if _is_ours(views[(kn.PROCESS_DOMAIN, key)].get("latest"))}
    return ledger["packs"].get(pack_id), ours


def unload(store, name: str, *, registry: RegistryHashes, now: datetime | None = None,
           dry_run: bool = False, outside: bool = False) -> Report:
    """Retract every lesson of the pack that the team has not touched. Works from the store, so it also
    removes what a cut-short load wrote before the ledger existed.

    ``name`` is a shipped pack, or an outside one when no shipped pack of that name is known here;
    ``outside`` picks the outside pack of that name in any case."""
    _check_name(name)
    at = now or datetime.now(timezone.utc)
    with store._config_lock():
        hashes = registry()
        ledger = read_ledger(store)
        views, _problems = kn.resolve_views_with_problems(kn.read_events(store)[0])
        asked, name = name, outside_id(name) if outside else name
        entry, ours = _held(ledger, views, name)
        if not outside and entry is None and not ours and name not in available():
            name = outside_id(name)
            entry, ours = _held(ledger, views, name)
        if entry is None and not ours:
            raise kn.KnowledgeError(f"pack {asked!r} is not loaded" + (" as an outside pack" if outside else ""))
        entry = entry or {"version": 0, "keys": {}}
        report = Report(pack=name, version=entry.get("version", 0))
        superseded = _superseded_keys(views)
        keys = {k: dict(v) for k, v in entry["keys"].items()}
        writes: list[dict] = []
        for key in sorted(set(keys) | ours):
            view = views.get((kn.PROCESS_DOMAIN, key))
            if view is None:
                continue
            if _team_touched(view, superseded, key):
                report.kept_for_team.append(key)
                continue
            latest = view["latest"]
            if not _retracted_by_loader(latest):
                writes.append(_retract_event(latest, reason=f"pack {name} unloaded", hashes=hashes, at=at))
                report.retracted.append(key)
            keys[key] = {**keys.get(key, {"hash": kn.payload_hash(latest), "source": ""}),
                         "state": _STATE_RETRACTED}
        if dry_run:
            return report
        for event in writes:
            kn.write_event_locked(store, event)
        new_entry = {**entry, "version": entry.get("version", 0), "keys": keys}
        if new_entry != entry:
            ledger["packs"][name] = new_entry
            _write_ledger(store, ledger)
    return report


def _counts(views: dict[tuple, dict], superseded: set[str], pack_id: str) -> dict[str, int]:
    live = retracted_by_loader = retracted_by_team = changed_by_team = 0
    for key in _store_keys(views, pack_id):
        latest = views[(kn.PROCESS_DOMAIN, key)].get("latest") or {}
        if _team_touched(views[(kn.PROCESS_DOMAIN, key)], superseded, key):
            if kn.is_retracted(latest) or key in superseded:
                retracted_by_team += 1
            else:
                changed_by_team += 1
        elif _retracted_by_loader(latest):
            retracted_by_loader += 1
        elif kn.is_curated(latest):
            live += 1
    return {"live": live, "retracted_by_pack": retracted_by_loader, "retracted_by_team": retracted_by_team,
            "changed_by_team": changed_by_team}


def describe(store) -> list[dict[str, Any]]:
    """One row per available pack, then one per outside pack this store has loaded: its version and size,
    and what this store holds now. The counts are folded from the store (what is live, what the team
    retracted or changed), not read from the ledger. An outside pack's folder is not read again, so its
    size is unknown (``lessons`` is None)."""
    ledger = read_ledger(store)["packs"]
    views, _problems = kn.resolve_views_with_problems(kn.read_events(store)[0])
    superseded = _superseded_keys(views)
    rows = []
    for name in available():
        pack = read_pack(name)
        entry = ledger.get(name)
        counts = _counts(views, superseded, name)
        rows.append({"name": name, "origin": "shipped", "version": pack.version, "lessons": len(pack.lessons),
                     "loaded_version": entry["version"] if entry else None,
                     "loaded": bool(entry) and counts["live"] > 0, **counts})
    for pack_id in sorted(p for p in ledger if p.startswith(OUTSIDE_PREFIX)):
        entry, source = ledger[pack_id], ledger[pack_id].get("source", {})
        counts = _counts(views, superseded, pack_id)
        rows.append({"name": pack_id[len(OUTSIDE_PREFIX):], "origin": "outside", "version": entry["version"],
                     "lessons": None, "loaded_version": entry["version"], "loaded": counts["live"] > 0,
                     **counts, "from": source.get("folder"), "commit": source.get("commit"),
                     "file_sha256": source.get("file_sha256")})
    return rows


# ---------------------------------------------------------------- export

Ident = tuple[str, str]         # (domain, key): a lesson's identity in the store


def _label(ident: Ident) -> str:
    """A lesson as the user names it: domain/key, as ``knowledge search`` prints it (neither part can hold a
    slash)."""
    return f"{ident[0]}/{ident[1]}"


@dataclass
class ExportReport:
    pack: str
    version: int
    out: str
    written: list[dict[str, str]] = field(default_factory=list)     # slug, domain and key of each lesson
    skipped: list[dict[str, str]] = field(default_factory=list)     # domain, key and why, for --tag
    unchanged: bool = False             # the folder already holds this pack file
    provenance_changed: bool = False    # the provenance file is written (in a dry run: would be)

    def as_dict(self) -> dict[str, Any]:
        return {"pack": self.pack, "version": self.version, "out": self.out, "written": self.written,
                "skipped": self.skipped, "unchanged": self.unchanged,
                "provenance_changed": self.provenance_changed}


def slug_for_key(key: str) -> str:
    """A pack slug for a store key: lower case, and each run of other characters becomes one dash. A slug
    longer than 60 characters is cut and ends in 8 characters of the key's hash, so it stays unique."""
    slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
    if len(slug) > _SLUG_MAX:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
        slug = slug[:_SLUG_MAX - len(digest) - 1].rstrip("-") + "-" + digest
    return slug


def _not_exportable(rec: dict, key: str, superseded: set[str]) -> str:
    """Why a lesson cannot be exported, or an empty string. Only the team's own current verified content goes."""
    curated = rec.get("curated")
    if curated is None:
        return "is not verified"
    if rec.get("tombstoned"):
        return "is retracted"
    if rec.get("curated_origin"):       # where the verified content came from, never how the key is spelled
        return "comes from a lesson pack"
    if key in superseded:               # supersedes names bare keys, and the store applies them in every domain
        return "is replaced by a newer lesson"
    return ""


def _verified_at(note: dict) -> datetime:
    try:
        return datetime.fromisoformat(str(note.get("curated_at")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise kn.KnowledgeError("has no readable verify time") from exc


def _dump_line(line: dict[str, Any]) -> str:
    """How the export writes a pack line, and how its checks see it. Text is kept as it is, not escaped, so
    a person can read the pack before sharing it; the loader splits records at newlines only."""
    return json.dumps(line, ensure_ascii=False)


def _line_problem(rec: dict, key: str, name: str) -> str:
    """Why the loader would refuse this lesson's pack line, or an empty string: an export never writes a
    pack that its own loader refuses."""
    try:
        line = _dump_line(_export_line(rec, name=name, slug=slug_for_key(key), version=1))
        _read_line(line, name=name, pack_id=outside_id(name), seen=set(), at=datetime.now(timezone.utc))
    except kn.KnowledgeError as exc:
        return f"cannot be a pack line ({exc})"
    return ""


def _export_line(rec: dict, *, name: str, slug: str, version: int) -> dict[str, Any]:
    note = rec["curated"]
    lesson = note["lesson"]
    confirmed = _verified_at(note)
    return {"key": slug, "scope": lesson["scope"], "trigger": lesson["trigger"], "body": note["body"],
            "applies_to": list(lesson.get("applies_to") or []), "evidence": lesson["evidence_ref"],
            "pack": name, "pack_version": version, _CONFIRMED_AT: _iso(confirmed)}


def _render(named: list[tuple[str, Ident, dict]], *, name: str, version: int) -> tuple[str, str]:
    lines = [_export_line(rec, name=name, slug=slug, version=version) for slug, _ident, rec in named]
    provenance = {
        "pack": name, "pack_version": version,
        "note": ("Keep this file with the team that exported the pack; do not share it. It links each "
                 "lesson to its key and event in that team's store."),
        "lessons": {slug: {"key": key, "domain": domain, "event_id": rec["curated"]["id"]}
                    for slug, (domain, key), rec in named},
    }
    return ("".join(_dump_line(line) + "\n" for line in lines),
            json.dumps(provenance, indent=2, ensure_ascii=False) + "\n")


def _existing_version(path: Path) -> int | None:
    try:
        first = next(line for line in _physical_lines(path.read_bytes()) if line.strip())
        version = json.loads(first).get("pack_version")
    except (OSError, ValueError, StopIteration, AttributeError):
        return None
    return version if _is_count(version) and version >= 1 else None


def _read_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        raise kn.KnowledgeError(f"{path} is not UTF-8 text, so it is not a file this export wrote; "
                                "move it away, then export again") from exc


def _refuse_retired_conflict(path: Path, name: str, slugs: set[str]) -> None:
    """Refuse an export whose folder holds a retirement file that the loader would refuse, or that retires
    lessons this export includes: a team loading the folder would not get them. The file is the pack's own
    record of what it took back, so it is never changed here; the person decides."""
    try:
        retired = _read_retired(name, path)
    except kn.KnowledgeError as exc:
        raise kn.KnowledgeError(f"{exc}; a team could not load this folder: fix or remove {path}") from exc
    clash = [slug for slug in retired if slug in slugs]
    if clash:
        raise kn.KnowledgeError(
            f"{path} retires {', '.join(repr(s) for s in clash)}, which this export includes, so a team loading "
            "this folder would not get them; take them out of that file, or export to another folder")


def _pick(lessons: dict[Ident, dict], wanted: str) -> Ident:
    """The lesson a --key names: ``domain/key``, or a bare key that only one domain holds. A bare key held
    by several domains is refused, never guessed: the wrong one could be content that must not be shared."""
    domain, slash, key = wanted.partition("/")
    if slash:
        found = [(domain, key)] if (domain, key) in lessons else []
    else:
        found = [ident for ident in lessons if ident[1] == wanted]
    if not found:
        raise kn.KnowledgeError(f"lesson {wanted!r} is not a lesson in this store")
    if len(found) > 1:
        raise kn.KnowledgeError(
            f"lesson {wanted!r} is in {len(found)} domains ({', '.join(_label(i) for i in found)}); "
            "name the one to export as --key <domain>/<key>")
    return found[0]


def export(store, name: str, *, out: Path | str, keys: tuple[str, ...] | list[str] = (),
           tag: str | None = None, dry_run: bool = False, force: bool = False) -> ExportReport:
    """Write the team's own verified lessons, chosen by key or by tag, as review candidates: the pack
    file ``<out>/<name>.jsonl`` and the provenance file ``<out>/<name>.provenance.json``. Writes nothing
    in the store, and never publishes, commits or pushes. A lesson that is not verified, is retracted or
    came from a pack is never exported: by key it refuses the export, by tag it is skipped. A retirement
    file already in the folder that retires an exported lesson refuses the export.

    A lesson is its (domain, key) pair throughout: a key held by several domains must be named as
    ``domain/key``, and two lessons that would share a slug refuse the export rather than lose one."""
    _check_name(name)
    _refuse_shipped_name(name, "exported pack")
    if bool(keys) == bool(tag):
        raise kn.KnowledgeError("choose the lessons with --key (one or more) or with --tag, not both")
    views, _problems = kn.resolve_views_with_problems(kn.read_events(store)[0])
    lessons = {ident: rec for ident, rec in sorted(views.items(), key=lambda item: (item[0][1], item[0][0]))
               if (rec.get("curated") or rec["latest"]).get("type") == kn.TYPE_LESSON}
    superseded = _superseded_keys(views)
    chosen: dict[Ident, dict] = {}
    skipped: list[dict[str, str]] = []
    if keys:
        for wanted in keys:
            ident = _pick(lessons, wanted)
            rec = lessons[ident]
            why = _not_exportable(rec, ident[1], superseded) or _line_problem(rec, ident[1], name)
            if why:
                raise kn.KnowledgeError(
                    f"lesson {_label(ident)!r} {why}; only the team's own verified lessons are exported")
            chosen[ident] = rec
    else:
        for ident, rec in lessons.items():
            shown = rec.get("curated") or rec["latest"]
            if tag not in ((shown.get("lesson") or {}).get("applies_to") or []):
                continue
            why = _not_exportable(rec, ident[1], superseded) or _line_problem(rec, ident[1], name)
            if why:
                skipped.append({"domain": ident[0], "key": ident[1], "why": why})
            else:
                chosen[ident] = rec
        if not chosen:
            raise kn.KnowledgeError(f"no verified lesson of this team carries the tag {tag!r}")
    by_slug: dict[str, list[Ident]] = {}
    for ident in chosen:
        by_slug.setdefault(slug_for_key(ident[1]), []).append(ident)
    clashes = [idents for idents in by_slug.values() if len(idents) > 1]
    if clashes:
        raise kn.KnowledgeError("these lessons would get the same slug: " + "; ".join(
            " and ".join(repr(_label(i)) for i in idents) for idents in clashes) + "; export them in separate packs")
    named = sorted(((slug_for_key(ident[1]), ident, rec) for ident, rec in chosen.items()), key=lambda row: row[0])

    folder = Path(out).resolve()
    if folder.exists() and not folder.is_dir():
        raise kn.KnowledgeError(f"{folder} is not a folder")
    pack_path, provenance_path = folder / f"{name}.jsonl", folder / f"{name}.provenance.json"
    _refuse_retired_conflict(folder / f"{name}.retired.json", name, {slug for slug, _ident, _rec in named})
    existing = _existing_version(pack_path)
    version = existing or 1
    lines, provenance = _render(named, name=name, version=version)
    seen = _read_or_none(pack_path)
    report = ExportReport(pack=name, version=version, out=str(folder), skipped=skipped,
                          written=[{"slug": slug, "domain": domain, "key": key} for slug, (domain, key), _rec in named])
    # Only the pack file decides "a different pack": the provenance file may have been moved away, as asked.
    report.unchanged = seen == lines
    if seen is not None and not report.unchanged:
        if not force:
            raise kn.KnowledgeError(
                f"{folder} already holds a different pack called {name!r}; add --force to replace it")
        report.version = (existing or 0) + 1
        lines, provenance = _render(named, name=name, version=report.version)
    try:                # the exact bytes, read the way the loader reads them
        loaded, _versions, _line_of = _parse_lessons(lines.encode("utf-8"), name=name, pack_id=outside_id(name),
                                                     at=datetime.now(timezone.utc))
    except kn.KnowledgeError as exc:
        raise kn.KnowledgeError(f"the export would write a pack its own loader refuses: {exc}") from exc
    if len(loaded) != len(named):
        raise kn.KnowledgeError(f"the export would write {len(named)} lessons, but the loader reads {len(loaded)}")
    report.provenance_changed = _read_or_none(provenance_path) != provenance
    if dry_run:
        return report
    if not report.unchanged:
        _atomic.write_text(pack_path, lines)
    if report.provenance_changed:
        _atomic.write_text(provenance_path, provenance)
    return report
