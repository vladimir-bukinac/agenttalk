"""Lesson packs from an outside folder, and the export of a team's own lessons as review candidates.

An outside pack is a folder the user checked out themselves (agenttalk never fetches it). It loads with
the rules of a shipped pack, under its own identity (key prefix ``pack.ext.<name>:``, tag
``pack-ext.<name>``), and the ledger records where it came from. The export writes a pack file of
verified team lessons and a separate provenance file that stays with the exporting team.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agenttalk import cli, knowledge as kn, knowledge_pack as kp, lesson_context as lc
from agenttalk.store import Store

PROCESS = kn.PROCESS_DOMAIN
PREFIX = "pack.ext.team-x:"


def _run(root: Path, *argv: str) -> int:
    return cli.main(["--root", str(root), *argv])


def _events(root: Path) -> list[dict]:
    return kn.read_events(Store(root))[0]


def _notes(root: Path) -> Path:
    return Store(root).dir / "knowledge" / "notes.jsonl"


def _ledger_file(root: Path) -> Path:
    return Store(root).dir / "knowledge" / "packs.json"


def _ledger(root: Path) -> dict:
    return json.loads(_ledger_file(root).read_text(encoding="utf-8"))


def _line(slug: str, *, pack: str = "team-x", version: int = 1,
          body: str = "Do the thing. Why: it matters. Check: look.", tags: tuple[str, ...] = ("migration",),
          confirmed_at: str | None = None) -> dict:
    line = {"key": slug, "scope": "process", "trigger": f"When {slug} applies", "body": body,
            "applies_to": list(tags), "evidence": "a practice run", "pack": pack, "pack_version": version}
    if confirmed_at is not None:
        line["confirmed_at"] = confirmed_at
    return line


@pytest.fixture
def shipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The packs that ship with this install: one called demo, so tests never load the real migration pack."""
    folder = tmp_path / "shipped"
    folder.mkdir()
    (folder / "demo.jsonl").write_text(json.dumps(_line("alpha", pack="demo")) + "\n", encoding="utf-8")
    monkeypatch.setattr(kp, "PACKS_DIR", folder)
    return folder


@pytest.fixture
def root(tmp_path: Path, shipped: Path) -> Path:
    path = tmp_path / "store"
    path.mkdir()
    store = Store(path)
    store.init(["lead", "dev"])
    store.set_role("lead", "lead")
    return path


@pytest.fixture
def outside(tmp_path: Path):
    """An outside pack folder with a space in its name; returns (folder, writer)."""
    folder = tmp_path / "shared lessons"
    folder.mkdir()

    def write(lines: list[dict], retired: list[str] | None = None, name: str = "team-x",
              raw: str | None = None) -> Path:
        path = folder / f"{name}.jsonl"
        path.write_text(raw if raw is not None else "".join(json.dumps(x) + "\n" for x in lines),
                        encoding="utf-8")
        retired_file = folder / f"{name}.retired.json"
        if retired is None:
            retired_file.unlink(missing_ok=True)
        else:
            retired_file.write_text(json.dumps(retired), encoding="utf-8")
        return path
    return folder, write


def _load(root: Path, folder: Path | str, name: str = "team-x", *extra: str) -> int:
    return _run(root, "knowledge", "pack", "load", name, "--from", str(folder), *extra)


def _live(root: Path, slug: str, prefix: str = PREFIX) -> dict | None:
    return kn.current_view(_events(root)).get((PROCESS, f"{prefix}{slug}"))


def _team_event(key: str, *, supersedes: tuple[str, ...] = (), body: str = "Team text. Why: x. Check: y.",
                tags: tuple[str, ...] = ("migration",), scope: str = "process") -> dict:
    return kn.new_publish_event(
        note_id=kn.new_note_id(), key=key, type=kn.TYPE_LESSON, domain_id=PROCESS, body=body, anchor=None,
        verified_against_sha=None, domain_registry_hash="rh",
        domain_definition_hash=kn.VIRTUAL_PROCESS_DOMAIN_HASH, author="dev",
        resolved_from="active_agent", at="2026-10-16T18:00:00Z",
        lesson={"scope": scope, "trigger": f"When {key} applies", "evidence_ref": f"PR for {key}",
                "owner": "dev", "review_after": "2099-01-01", "expires_at": "2100-01-01",
                "applies_to": list(tags), "supersedes": list(supersedes)})


def _verify(root: Path, key: str) -> int:
    return _run(root, "knowledge", "curate", "verify", "--from", "lead", "--domain", PROCESS, "--key", key)


def _retract(root: Path, key: str) -> int:
    return _run(root, "knowledge", "curate", "retract", "--from", "lead", "--domain", PROCESS,
                "--key", key, "--reason", "does not fit us")


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# ---- loading from an outside folder

def test_dry_run_then_load_from_a_folder(root: Path, outside, capsys) -> None:
    folder, write = outside
    write([_line("alpha"), _line("beta")])
    assert _load(root, folder, "team-x", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "would publish 2" in out and "ext.team-x" in out
    assert not _notes(root).exists() and not _ledger_file(root).exists()

    assert _load(root, folder) == 0
    events = _events(root)
    assert [e["event"] for e in events] == ["publish", "curate", "publish", "curate"]
    assert all(e["key"].startswith(PREFIX) and kn.has_loader_marks(e) for e in events)
    live = _live(root, "alpha")
    assert live["authority"]["state"] == kn.AUTH_VERIFIED and "pack-ext.team-x" in live["lesson"]["applies_to"]
    entry = _ledger(root)["packs"]["ext.team-x"]
    assert set(entry["keys"]) == {PREFIX + "alpha", PREFIX + "beta"}
    import hashlib
    assert entry["source"]["folder"] == str(folder.resolve())
    assert entry["source"]["file_sha256"] == hashlib.sha256((folder / "team-x.jsonl").read_bytes()).hexdigest()
    assert "team-x" not in _ledger(root)["packs"]                      # the bare name is never a ledger id


def test_reloading_an_unchanged_outside_pack_writes_nothing(root: Path, outside) -> None:
    folder, write = outside
    write([_line("alpha"), _line("beta")])
    assert _load(root, folder) == 0
    notes, ledger = _notes(root).read_bytes(), _ledger_file(root).read_bytes()
    assert _load(root, folder) == 0
    assert _notes(root).read_bytes() == notes and _ledger_file(root).read_bytes() == ledger


def test_a_changed_line_updates_the_lesson(root: Path, outside) -> None:
    folder, write = outside
    write([_line("alpha"), _line("beta")])
    _load(root, folder)
    count = len(_events(root))
    write([_line("alpha", body="Changed. Why: new. Check: new."), _line("beta")])
    assert _load(root, folder) == 0
    assert _live(root, "alpha")["body"].startswith("Changed.") and kn.is_curated(_live(root, "alpha"))
    assert len(_events(root)) == count + 2                              # one publish and one curate


def test_a_retired_slug_is_taken_back(root: Path, outside) -> None:
    folder, write = outside
    write([_line("keep"), _line("retire-me")])
    _load(root, folder)
    write([_line("keep", version=2)], retired=["retire-me"])
    assert _load(root, folder) == 0
    assert kn.is_retracted(_live(root, "retire-me")) and "retired" in _live(root, "retire-me")["retract_reason"]
    assert not kn.is_retracted(_live(root, "keep"))
    assert _ledger(root)["packs"]["ext.team-x"]["version"] == 2


def test_unload_takes_back_an_outside_pack_and_leaves_the_shipped_one(root: Path, outside) -> None:
    folder, write = outside
    write([_line("alpha")])
    assert _run(root, "knowledge", "pack", "load", "demo") == 0
    _load(root, folder)
    assert _run(root, "knowledge", "pack", "unload", "team-x") == 0
    assert kn.is_retracted(_live(root, "alpha"))
    assert not kn.is_retracted(_live(root, "alpha", prefix="pack.demo:"))
    assert _load(root, folder) == 0                                     # its own retraction is undone
    assert not kn.is_retracted(_live(root, "alpha"))
    assert _run(root, "knowledge", "pack", "unload", "team-x", "--outside") == 0
    assert kn.is_retracted(_live(root, "alpha"))


def test_unloading_a_pack_that_was_never_loaded_names_it(root: Path, capsys) -> None:
    assert _run(root, "knowledge", "pack", "unload", "nope") == 2
    assert "'nope' is not loaded" in capsys.readouterr().err
    assert _run(root, "knowledge", "pack", "unload", "demo", "--outside") == 2
    assert "'demo' is not loaded as an outside pack" in capsys.readouterr().err


def test_a_lesson_the_team_retracted_or_replaced_stays_the_teams_after_a_reload(root: Path, outside) -> None:
    folder, write = outside
    write([_line("alpha"), _line("beta"), _line("gamma")])
    _load(root, folder)
    assert _retract(root, PREFIX + "alpha") == 0
    kn.append_event(Store(root), _team_event("team.better", supersedes=(PREFIX + "beta",)))
    assert _verify(root, "team.better") == 0
    count = len(_events(root))
    write([_line(s, body="Changed. Why: new. Check: new.") for s in ("alpha", "beta")] + [_line("gamma")])
    assert _load(root, folder) == 0
    assert len(_events(root)) == count                                  # nothing written for alpha or beta
    assert _live(root, "alpha")["curated_by"] == "lead" and kn.is_retracted(_live(root, "alpha"))
    assert _live(root, "beta")["body"].startswith("Do the thing.")


def test_outside_lessons_never_take_an_injected_slot(root: Path, outside) -> None:
    folder, write = outside
    write([_line("alpha")])
    _load(root, folder)
    assert lc.select_lessons(_events(root), context_scope="process", tags=["migration"], limit=5) == []


def test_the_event_schema_stays_closed(root: Path, outside) -> None:
    folder, write = outside
    write([_line("alpha", confirmed_at="2026-09-01")])
    _run(root, "knowledge", "pack", "load", "demo")
    _load(root, folder)
    events = _events(root)
    shipped_pub, outside_pub = events[0], events[2]
    assert set(outside_pub) == set(shipped_pub) and set(outside_pub["lesson"]) == set(shipped_pub["lesson"])
    assert set(events[3]) == set(events[1])
    text = _notes(root).read_text(encoding="utf-8")
    assert "confirmed_at" not in text and "shared lessons" not in text


# ---- identity

def test_a_name_a_shipped_pack_uses_is_refused(root: Path, outside, capsys) -> None:
    folder, write = outside
    write([_line("alpha", pack="demo")], name="demo")
    assert _load(root, folder, "demo") == 2
    assert "ships with agenttalk" in capsys.readouterr().err
    assert not _notes(root).exists() and not _ledger_file(root).exists()


def test_the_real_migration_name_is_refused_too(tmp_path: Path, outside, capsys) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    Store(root).init(["lead", "dev"])
    folder, write = outside
    write([_line("alpha", pack="migration")], name="migration")
    assert _load(root, folder, "migration") == 2
    assert "ships with agenttalk" in capsys.readouterr().err
    assert not _notes(root).exists()


def test_outside_keys_and_tags_never_meet_a_shipped_packs(root: Path, outside, shipped: Path) -> None:
    # Shipped names that look like the outside namespace: "ext" and "ext-team-x".
    for name in ("ext", "ext-team-x"):
        (shipped / f"{name}.jsonl").write_text(json.dumps(_line("alpha", pack=name)) + "\n", encoding="utf-8")
    folder, write = outside
    write([_line("alpha")])
    for name in ("ext", "ext-team-x"):
        assert _run(root, "knowledge", "pack", "load", name) == 0
    assert _load(root, folder) == 0
    views = kn.current_view(_events(root))
    keys = sorted(k for (_d, k) in views)
    assert keys == ["pack.ext-team-x:alpha", "pack.ext.team-x:alpha", "pack.ext:alpha"]
    tags = {k: [t for t in v["lesson"]["applies_to"] if t.startswith("pack")] for (_d, k), v in views.items()}
    assert tags == {"pack.ext-team-x:alpha": ["pack-ext-team-x"], "pack.ext.team-x:alpha": ["pack-ext.team-x"],
                    "pack.ext:alpha": ["pack-ext"]}
    assert _run(root, "knowledge", "pack", "unload", "team-x") == 0
    views = kn.current_view(_events(root))
    assert [k for (_d, k), v in views.items() if kn.is_retracted(v)] == ["pack.ext.team-x:alpha"]


# ---- refused packs write nothing

_MALFORMED = [
    pytest.param('{"key": "alpha", oops}\n', "line 1", id="bad-json"),
    pytest.param(json.dumps(_line("Bad Slug")) + "\n", "line 1", id="bad-slug"),
    pytest.param(json.dumps(_line("alpha")) + "\n" + json.dumps(_line("pack.migration:x")) + "\n",
                 "line 2", id="reserved-prefix-in-key"),
    pytest.param(json.dumps(_line("alpha", tags=("pack-migration",))) + "\n", "line 1",
                 id="reserved-prefix-in-tag"),
    pytest.param(json.dumps(_line("alpha")) + "\n" + json.dumps(_line("alpha")) + "\n", "line 2",
                 id="duplicate-slug"),
    pytest.param(json.dumps({**_line("alpha"), "role": "lead"}) + "\n", "line 1", id="unknown-field"),
    pytest.param(json.dumps(_line("alpha", pack="other")) + "\n", "line 1", id="other-pack-name"),
    pytest.param(json.dumps(_line("alpha", confirmed_at="last tuesday")) + "\n", "line 1",
                 id="bad-confirmed-at"),
    pytest.param(json.dumps(_line("alpha", confirmed_at="2999-01-01")) + "\n", "line 1",
                 id="future-confirmed-at"),
]


@pytest.mark.parametrize(("raw", "where"), _MALFORMED)
def test_a_malformed_pack_is_refused_naming_the_line_and_writes_nothing(
        root: Path, outside, raw: str, where: str, capsys) -> None:
    folder, write = outside
    write([], raw=raw)
    assert _load(root, folder) == 2
    err = capsys.readouterr().err
    assert where in err and "team-x" in err
    assert not _notes(root).exists() and not _ledger_file(root).exists()


@pytest.mark.parametrize("missing", ["file", "folder"])
def test_a_missing_pack_file_or_folder_is_refused(root: Path, outside, missing: str, capsys) -> None:
    folder, _write = outside
    target = folder if missing == "file" else folder / "no such folder"
    assert _load(root, target) == 2
    assert "team-x.jsonl" in capsys.readouterr().err or missing == "folder"
    assert not _notes(root).exists() and not _ledger_file(root).exists()


def test_a_bad_retired_file_is_refused(root: Path, outside, capsys) -> None:
    folder, write = outside
    write([_line("alpha")], retired=["Not A Slug"])
    assert _load(root, folder) == 2
    assert "team-x.retired.json" in capsys.readouterr().err
    assert not _notes(root).exists()


# ---- freshness

def test_confirmed_at_drives_the_review_and_expiry_dates(root: Path, outside) -> None:
    folder, write = outside
    write([_line("old", confirmed_at="2024-03-01"), _line("plain")])
    before = datetime.now(timezone.utc)
    assert _load(root, folder) == 0
    after = datetime.now(timezone.utc)
    old = _live(root, "old")["lesson"]
    assert _dt(old["review_after"]) == datetime(2024, 3, 1, tzinfo=timezone.utc) + timedelta(days=kp.REVIEW_AFTER_DAYS)
    assert _dt(old["expires_at"]) == datetime(2024, 3, 1, tzinfo=timezone.utc) + timedelta(days=kp.EXPIRES_AFTER_DAYS)
    plain = _live(root, "plain")["lesson"]                              # no confirmed_at: relative to the load
    review = _dt(plain["review_after"]) - timedelta(days=kp.REVIEW_AFTER_DAYS)
    assert before - timedelta(seconds=1) <= review <= after + timedelta(seconds=1)
    # A newer confirmation of the same text is a change: the dates move.
    write([_line("old", confirmed_at="2026-01-15T08:30:00Z"), _line("plain")])
    assert _load(root, folder) == 0
    assert _dt(_live(root, "old")["lesson"]["review_after"]) == (
        datetime(2026, 1, 15, 8, 30, tzinfo=timezone.utc) + timedelta(days=kp.REVIEW_AFTER_DAYS))
    count = len(_events(root))
    assert _load(root, folder) == 0 and len(_events(root)) == count      # and a reload is still idempotent


def test_a_shipped_pack_line_may_carry_confirmed_at_too(shipped: Path) -> None:
    (shipped / "demo.jsonl").write_text(json.dumps(_line("alpha", pack="demo", confirmed_at="2025-05-05")) + "\n",
                                        encoding="utf-8")
    lesson = kp.read_pack("demo").lessons[0]
    stored = kp.lesson_for_store(lesson, datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert stored["review_after"].startswith("2026-05-05")


# ---- where it came from

def test_a_git_checkout_records_its_commit_and_is_left_untouched(root: Path, outside) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    folder, write = outside
    write([_line("alpha")])

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@e.invalid",
                               "-c", "commit.gpgsign=false", *args],
                              check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "lessons")
    head = git("rev-parse", "HEAD")
    listing = sorted(p.name for p in folder.iterdir())
    assert _load(root, folder) == 0
    assert _ledger(root)["packs"]["ext.team-x"]["source"]["commit"] == head
    assert git("rev-parse", "HEAD") == head and git("status", "--porcelain") == ""
    assert sorted(p.name for p in folder.iterdir()) == listing


def test_a_plain_folder_records_no_commit(root: Path, outside, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(outside[0].parent))
    folder, write = outside
    write([_line("alpha")])
    assert _load(root, folder) == 0
    assert "commit" not in _ledger(root)["packs"]["ext.team-x"]["source"]


def test_paths_with_spaces_and_both_separator_styles(root: Path, outside) -> None:
    folder, write = outside
    write([_line("alpha")])
    native, forward = str(folder), folder.as_posix()
    mixed = str(folder.parent) + "/" + folder.name                      # on Windows: backslashes, then a slash
    assert " " in native
    assert _load(root, native) == 0
    notes, ledger = _notes(root).read_bytes(), _ledger_file(root).read_bytes()
    for spelling in (forward, mixed, native + os.sep):
        assert _load(root, spelling) == 0
        assert _notes(root).read_bytes() == notes and _ledger_file(root).read_bytes() == ledger


def test_list_shows_an_outside_pack_and_where_it_came_from(root: Path, outside, capsys) -> None:
    folder, write = outside
    write([_line("alpha"), _line("beta")])
    _load(root, folder)
    capsys.readouterr()
    assert _run(root, "knowledge", "pack", "list", "--json") == 0
    rows = json.loads(capsys.readouterr().out)
    (row,) = [r for r in rows if r["origin"] == "outside"]
    assert row["name"] == "team-x" and row["live"] == 2 and row["from"] == str(folder.resolve())
    assert [r["origin"] for r in rows if r["name"] == "demo"] == ["shipped"]
    assert _run(root, "knowledge", "pack", "list") == 0
    assert "team-x" in capsys.readouterr().out


# ---- export

def _publish(root: Path, key: str, *, tags: str = "shared", scope: str = "review",
             body: str | None = None) -> None:
    assert _run(root, "knowledge", "publish", "--from", "dev", "--type", "lesson", "--key", key,
                "--scope", scope, "--trigger", f"When {key} applies", "--evidence-ref", f"PR for {key}",
                "--applies-to", tags, "--review-after", "2099-01-01", "--expires-at", "2100-01-01",
                "-m", body or f"Lesson {key}. Why: x. Check: y.") == 0


def _export(root: Path, out: Path | str, *argv: str, name: str = "shared") -> int:
    return _run(root, "knowledge", "pack", "export", "--name", name, "--out", str(out), *argv)


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_slug_conversion() -> None:
    assert kp.slug_for_key("Team.Rule_v2:alpha") == "team-rule-v2-alpha"
    assert kp.slug_for_key("a..b--c") == "a-b-c"
    assert kp.slug_for_key("review.check-the-pdf") == "review-check-the-pdf"
    long_a, long_b = "x" * 120 + ".a", "x" * 120 + ".b"
    for key in (long_a, long_b):
        slug = kp.slug_for_key(key)
        assert len(slug) <= 60 and kp._SLUG_RE.match(slug) and kp.slug_for_key(key) == slug   # noqa: SLF001
    assert kp.slug_for_key(long_a) != kp.slug_for_key(long_b)


def test_export_by_key_writes_the_pack_and_the_provenance_file(root: Path, tmp_path: Path) -> None:
    _publish(root, "review.check-it", tags="review,shared")
    _publish(root, "craft.other")
    for key in ("review.check-it", "craft.other"):
        assert _verify(root, key) == 0
    out = tmp_path / "out dir"
    assert _export(root, out, "--key", "review.check-it") == 0
    (line,) = _read_lines(out / "shared.jsonl")
    assert list(line) == [*kp._LINE_KEYS, "confirmed_at"]                       # noqa: SLF001
    curated = kn.resolve_views(_events(root))[(PROCESS, "review.check-it")]["curated"]
    assert line == {"key": "review-check-it", "scope": "review", "trigger": "When review.check-it applies",
                    "body": "Lesson review.check-it. Why: x. Check: y.", "applies_to": ["review", "shared"],
                    "evidence": "PR for review.check-it", "pack": "shared", "pack_version": 1,
                    "confirmed_at": curated["curated_at"]}
    provenance = json.loads((out / "shared.provenance.json").read_text(encoding="utf-8"))
    assert provenance["lessons"] == {"review-check-it": {"key": "review.check-it", "domain": PROCESS,
                                                         "event_id": curated["id"]}}


def test_export_by_tag_takes_only_verified_team_lessons(root: Path, tmp_path: Path, capsys) -> None:
    _publish(root, "team.verified")
    _publish(root, "team.unverified")
    _publish(root, "team.retracted")
    _publish(root, "team.other-tag", tags="elsewhere")
    for key in ("team.verified", "team.retracted", "team.other-tag"):
        assert _verify(root, key) == 0
    assert _retract(root, "team.retracted") == 0
    (Path(kp.PACKS_DIR) / "demo.jsonl").write_text(
        json.dumps(_line("alpha", pack="demo", tags=("shared",))) + "\n", encoding="utf-8")
    assert _run(root, "knowledge", "pack", "load", "demo") == 0                # a pack lesson with the tag
    _publish(root, "team.old")
    assert _verify(root, "team.old") == 0
    kn.append_event(Store(root), _team_event("team.new", supersedes=("team.old",), tags=("shared",)))
    assert _verify(root, "team.new") == 0                                       # team.old is replaced
    out = tmp_path / "out"
    capsys.readouterr()
    assert _export(root, out, "--tag", "shared") == 0
    assert [x["key"] for x in _read_lines(out / "shared.jsonl")] == ["team-new", "team-verified"]
    report = capsys.readouterr().out
    for key in ("team.unverified", "team.retracted", "team.old", "pack.demo:alpha"):
        assert key in report.split("skipped", 1)[1]


@pytest.mark.parametrize("which", ["team.unverified", "team.retracted", "pack.demo:alpha", "team.missing"])
def test_export_refuses_a_key_that_is_not_a_verified_team_lesson(
        root: Path, tmp_path: Path, which: str, capsys) -> None:
    _publish(root, "team.unverified")
    _publish(root, "team.retracted")
    assert _verify(root, "team.retracted") == 0 and _retract(root, "team.retracted") == 0
    assert _run(root, "knowledge", "pack", "load", "demo") == 0
    out = tmp_path / "out"
    assert _export(root, out, "--key", which) == 2
    assert which in capsys.readouterr().err
    assert not out.exists()


def test_export_dry_run_writes_nothing(root: Path, tmp_path: Path, capsys) -> None:
    _publish(root, "team.one")
    _verify(root, "team.one")
    out = tmp_path / "out"
    assert _export(root, out, "--key", "team.one", "--dry-run") == 0
    assert "would write 1" in capsys.readouterr().out and not out.exists()


def test_export_refuses_a_different_pack_of_the_same_name_unless_forced(root: Path, tmp_path: Path) -> None:
    for key in ("team.one", "team.two"):
        _publish(root, key)
        _verify(root, key)
    out = tmp_path / "out"
    assert _export(root, out, "--key", "team.one") == 0
    first = (out / "shared.jsonl").read_bytes()
    assert _export(root, out, "--key", "team.one") == 0                         # the same pack again: fine
    assert (out / "shared.jsonl").read_bytes() == first
    (out / "shared.provenance.json").unlink()                                   # moved away, as the help asks
    assert _export(root, out, "--key", "team.one") == 0
    assert (out / "shared.jsonl").read_bytes() == first and (out / "shared.provenance.json").is_file()
    assert _export(root, out, "--key", "team.two") == 2
    assert (out / "shared.jsonl").read_bytes() == first
    assert _export(root, out, "--key", "team.one", "--key", "team.two", "--force") == 0
    lines = _read_lines(out / "shared.jsonl")
    assert [x["key"] for x in lines] == ["team-one", "team-two"] and {x["pack_version"] for x in lines} == {2}


def test_export_refuses_two_keys_that_become_one_slug(root: Path, tmp_path: Path, capsys) -> None:
    for key in ("team.a-b", "team.a.b"):
        _publish(root, key)
        _verify(root, key)
    assert _export(root, tmp_path / "out", "--tag", "shared") == 2
    err = capsys.readouterr().err
    assert "team.a-b" in err and "team.a.b" in err


def test_export_refuses_a_shipped_pack_name(root: Path, tmp_path: Path, capsys) -> None:
    _publish(root, "team.one")
    _verify(root, "team.one")
    assert _export(root, tmp_path / "out", "--key", "team.one", name="demo") == 2
    assert "ships with agenttalk" in capsys.readouterr().err


def test_an_exported_pack_loads_into_another_store(root: Path, tmp_path: Path) -> None:
    _publish(root, "team.one", tags="review,shared")
    _verify(root, "team.one")
    out = tmp_path / "out"
    assert _export(root, out, "--key", "team.one") == 0
    other = tmp_path / "other"
    other.mkdir()
    Store(other).init(["lead"])
    assert _load(other, out, "shared") == 0
    live = _live(other, "team-one", prefix="pack.ext.shared:")
    confirmed = _dt(_read_lines(out / "shared.jsonl")[0]["confirmed_at"])
    assert _dt(live["lesson"]["review_after"]) == confirmed + timedelta(days=kp.REVIEW_AFTER_DAYS)
    assert live["body"] == "Lesson team.one. Why: x. Check: y." and "pack-ext.shared" in live["lesson"]["applies_to"]


def test_export_help_says_the_provenance_file_stays_with_the_team(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["knowledge", "pack", "export", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "provenance" in text and "stays with your team" in text
