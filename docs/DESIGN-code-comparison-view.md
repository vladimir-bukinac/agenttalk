# Design: a code comparison view in the dashboard ("compare")

**Status:** design only, round 3 (fix rounds 1 and 2 folded in). No code is written by this document.
**Base:** `origin/master` at `bdc775cb5727970b960d6ee76c785b5652c1f0dd`. Every line number below is at that commit.
**Request:** tk-97cf01713d22. **Reads:** round 1 tk-f0287d325cc6 (FIX: 2 P1, 9 P2, 2 P3), folded in by tk-f5b1097b77f9; round 2 tk-9e0cc9033b0b (FIX: 2 P1, 6 P2, 1 P3), folded in by tk-c603223a644b.
**Binding input:** the accepted challenge (`ch-b8f7fbb4-63e7-47b4-99d5-bbbe88d70874`, RESHAPE), eight points, called "C1" to "C8" below.
**Builder:** one Qwen seat, `qwen-agenttalk-dev-2`. **Reader:** `codex-agenttalk-reviewer-1` reads each slice.

**How to read the labels.** Every claim is marked **FACT** (I read it in the code or docs at the commit above, with file and line), **ESTIMATE** (a number I reasoned out, with its assumption) or **ASSUMPTION** (something I could not check, and what changes if it is wrong). Unmarked text is a definition, not a claim.

---

## 0. In plain words

**What the operator asked for.** A page in the dashboard with the original code on the left, the code the team's members made on the right, and beside them what the team recorded about the work: who was asked to build it, what each fix task did, who reviewed it, what each reviewer said, and which exact version each reviewer was looking at.

**What we build first (slice 1).** One page, `/compare`, for one explicitly chosen pair of commits (a "comparison"). It shows:
- a **status banner** that repeats what the work board says about this exact version, in plain words, and says **"cannot tell"** whenever the board cannot be tied to this comparison;
- the **changed files** with counts, and a **side-by-side text view** of one file at a time;
- a panel called **"Recorded rationale"** (not "reasoning": it shows what was written down) with the recorded tasks, fix tasks and reviews for this work, each with a link to its transcript.

**The rule that matters most.** The page never decides by itself whether code is approved. The current status comes only from the work board's own placement, and only when the board's record is tied to this repository, this store session, this work cycle and this exact commit. A review that approved an older version is shown as **history**, in different words from the current status, and never turns the banner green. If anything cannot be established, the banner says "cannot tell" and gives the reason.

**What it does not do (deferred, C6).** No comments pinned to lines, no round-by-round playback, no scanning of old history, no syntax colouring, no editing, no merging.

**How much work is it?** About **three work orders** for the one builder: roughly **2,100 lines of product code and 1,950 lines of tests** (ESTIMATE, section 11). The first work order is a thin end-to-end slice for ordinary text and binary files, with an early checkpoint and a **10 EUR Qwen stop-after threshold** (the builder starts no new paid work once 8 EUR is spent in that window; it is not a hard cap). Builder spend for all three is guessed at **13 to 21 EUR** (ASSUMPTION: no measured build workload exists yet).

**The stop rule (C7).** After work order 1 we run the checkpoint on a made-up repository. A reader who is told nothing must be able to say what the page shows. A second reader gets the editor-plus-index alternative. **If the second reader does as well and as fast, we stop** and keep the index page. Work orders 2 and 3 are not dispatched without a GO there.

**The five operator-side answers are settled** (lead, tk-4f1dff3e212a): the server does not run Git, so registration takes a bounded snapshot; repositories come from `work_repos`; snapshots live in `.agenttalk/compare/`; reply excerpts are 600 characters; console v2 gets no link in slice 1.

---

## 1. Decisions (settled, with the facts they rest on)

| # | Decision | Why (FACT) |
|---|---|---|
| D1 | **The server never runs Git.** `agenttalk compare register` reads the repository once and stores a bounded read-only snapshot; the three GET endpoints read stored files only. | `docs/WORK-BOARD-FEED.md` ("Integration facts and the Done lane") records the operator's decision of 2026-09-30; `work_board_facts.py:1-6` repeats it. |
| D2 | **Repositories come from `work_repos`.** `compare register` refuses an alias that is not there. | `work_repos` is already "an access allowlist of operator-approved local checkouts" (`docs/WORK-BOARD-FEED.md` "Setup"; `work_board_facts.py:69-104`). |
| D3 | **Snapshots live in `.agenttalk/compare/`.** | Outside `state/`, so a store reset does not silently delete deliberate evidence (a reset is exactly what the session binding in section 7.3 handles). **Consequence read in the code:** `recovery.py:162-173` enumerates every file under the store recursively (`_relative_files`), so the snapshots are part of store backups and recovery. Section 5.8 states what that means. |
| D4 | **Each verdict reply shows a 600-character excerpt**, as inert text. | The existing transcript route already carries bodies (`web.py` route list, `GET /api/thread/<rid>`). The reducer never reads bodies (`work_board.py:3-4`); the excerpt is read from messages already in the validated active window. |
| D5 | **No link from console v2 in slice 1.** | Keeps the change away from `console2*.js`. |

---

## 2. What the operator sees

### 2.1 The pages

**`GET /compare`** is a small HTML shell (no inline script, no inline style). It loads `/static/compare.css`, `/static/compare-model.js` and `/static/compare.js`. It reads `?id=<cid>` and `?root=<project id>` from its own address. Without `id` it shows the list; with `id` it shows one comparison. **The project selector is carried everywhere:** the page passes `root` unchanged to every API request, to the back link, to the list-to-detail links and to the transcript links. When the address has no `root`, the first API answer names the project (`project.project_id`) and the page uses that from then on for every link it builds.

**List page** (newest first; the status text is the same function as the detail page, so the list can never look greener than the page it opens):

```
agenttalk / compare                                         project: agenttalk   [data as of 10:42:05Z]

  Comparisons (2)
  --------------------------------------------------------------------------------------------
  demo-greeting   fixture   9a1b2c3d4e5f..3f9c2a41d0e7   2 files   +9 -3    registered 10:31Z
     status:  CANNOT TELL (2 reasons)                                         [open]
  agenttalk-pr-500   agenttalk   5c1d...8e02..a07b...19cc   14 files   +402 -88
     status:  READY (board: reviewed; independent GO; required checks green)  [open]
```

**Detail page** (the checkpoint screen):

```
agenttalk / compare / demo-greeting                           project: agenttalk   [data as of 10:42:05Z]

+-- STATUS (from the work board, for THIS head) --------------------------------------------+
|  [X]  CANNOT TELL whether this head is ready.                                             |
|        * The board cannot place this work: multiple candidates without supersession.      |
|        * A link is missing: required correlation history (1 record).                      |
|  This head   3f9c2a41d0e7   (full 3f9c2a41...)     Base   9a1b2c3d4e5f                   |
|  2 commits  .  2 files changed  (1 modified, 1 added)  .  +9 -3                          |
|  Work item: demo-greeting   cycle 1 (board: cycle 1)   repository: fixture (matches)      |
+-----------------------------------------------------------------------------------------+

+-- FILES -----------------+  +-- SIDE BY SIDE: greet.py   M   +4 -1 ------------------------+
| M  greet.py        +4 -1 |  | ORIGINAL  (base 9a1b2c3)     | CHANGED  (head 3f9c2a4)       |
| A  tests/test.py   +5    |  |  1 def greet(name):          |  1 def greet(name):           |
|                          |  |  2     return "Hello " + name|  2     if name is None:       |
|                          |  |                              |  3         return "Hello, you"|
|                          |  |                              |  4     return "Hello " + name |
+--------------------------+  +--------------------------------------------------------------+

+-- RECORDED RATIONALE   (what the team wrote down about this work; not a full account) -----+
| TASKS                                                                                      |
| 09:40Z  lead -> qwen-agenttalk-dev-2   build   done   "Add greet(name) ..." (excerpt) [log]|
| 10:20Z  lead -> qwen-agenttalk-dev-2   fix     done   "Guard None ..."  (excerpt)   [log]|
| REVIEWS (history; the status above does not come from this list)                           |
| 10:05Z  reviewer-a  read  changes requested on an EARLIER head (b7e1...)   [log]           |
|    "greet(None) crashes; add a guard and a test." (excerpt, 600 characters max)            |
| 10:12Z  reviewer-b  read  a GO was recorded on an EARLIER head (b7e1...). The changes      |
|    after it are NOT covered.                                                    [log]      |
| 10:30Z  reviewer-a  read  asked, no answer yet (head of the request: not available)        |
| !  1 record could not be found: review-result 20261017-000000-000000-miss (named by a reply)|
|  each row ends with: project id . request id . reply id (select to copy)                    |
+---------------------------------------------------------------------------------------------+
```

Notes: every state uses a **word and a mark** (`[X]`, `[!]`, `[ok]`), never colour alone. "Head" shows the first 12 characters and, on the next line, the full id (not a tooltip). The left column is **ORIGINAL (base ...)**, the right **CHANGED (head ...)**. A row whose displayed text looks identical but whose bytes differ shows a **changed** mark with the words "differs in bytes not visible here" (section 5.6).

### 2.2 Page states (each has a test)

| State | When | What the page shows |
|---|---|---|
| loading | request in flight | "Loading comparison..." |
| list empty | no comparisons registered | "No comparisons are registered. Run `agenttalk compare register --help`." |
| ok | detail loaded | everything above |
| not found | HTTP 404 | "This comparison is not registered (id ...)" and a link back to the list (with `root`) |
| busy | HTTP 503 | "The dashboard is busy. Retrying in N seconds", one automatic retry after `Retry-After`, then a button |
| server error | HTTP 5xx, bad JSON, network failure | "Could not load: <reason>". **Never a blank page and never a stale status.** (Lesson `process/inventory-read-the-error-path-before-saying-already-handled`.) |
| evidence unavailable | the board has no such item, is building, stale or incomplete | banner CANNOT TELL with the reason; the code view still works |
| identity mismatch | session, cycle or repository differs (section 7.3) | banner CANNOT TELL naming the two values that differ |
| snapshot incomplete | cut by limits | one line per cut ("first 500 files shown; more exist") |
| per file | binary, too large, withheld, symlink, submodule, mode only, missing object | one plain line saying why nothing is shown |

---

## 3. What I read, and what it means for the design (FACTS)

1. **The board is a pure reducer over validated envelopes** (`work_board.py:1-14`; `reduce` at `:289`). Per work item it already yields `verdicts` (head to list of `{reviewer, verdict, reply, independent, vendor}`, built at `:459-469`), `candidate` (set in `_place`, `:532`), `obligations` for the current cycle (`:480-481`: `request_id, recipient, stage, state, verdict`), `issues`, `reason`, `evidence`, `repo_binding` (`:474`), `previous_cycles` (`:484-490`), `integration` (`:428`) and the placement `column` / `workflow_column` (`_place`, `:532-592`). **Consequence:** the comparison page reuses this output and invents no correlation or approval logic (C3).
2. **`verdicts` is history, not status.** It holds every GO, FIX and HOLD of the current cycle under the commit each reviewer named (`:459-469`). Whether a GO still counts is decided in `_place` by many other facts: an active fix task (`:567-571`), an unresolved FIX unless discharged by a replacement chain (`:538-548`), outstanding reviews (`:578-580`), blockers (`_blockers`, `:595-640`) and policy. The column `ready` is reached only when none of those apply (`:586-589`). **Consequence (reader finding 1):** the banner is a pure function of the board's placement; the verdict map only feeds the history list. I confirm the reader's two reproductions from the code alone: an independent GO plus an outstanding fix task gives `fix_round` (`:567-571`) and a FIX discharged by a replacement review at the same head leaves a `ready` card whose map holds both verdicts (`:538-548`, `:586-589`).
3. **A verdict map key can be `None`** (a reviewer who named no commit). `json.dumps` writes a `None` key as `"null"`. The builder pins it with a test.
4. **Missing or conflicting history is a reducer outcome**, not something the page invents: `MISSING = "missing required correlation history"` (`work_board.py:24`, `:240-241`); conflicts make the item Unknown with the reason and evidence ids (`:493-501`). The reducer is total: an internal fault makes the item Unknown (`:412-421`).
5. **`repo_binding`** is `{"repo": alias, "target": ref}`, `None`, or the string `"ambiguous"` (`work_board.py:656-662`). **`integration`** maps head to a **boolean-like value** (`:428`), where `False` is a real, different answer from `True`. Integration yields the `done` column only when the value is truthy and no execution is outstanding (`:549-551`).
6. **The board feed is cached and bounded**: at most 100 cards and 256 KiB; Done items only for seven days (`work_board_feed.py`; `docs/WORK-BOARD-FEED.md`). The comparison may name an item that is not on the feed; that is a shown state.
7. **The board and the message window do NOT always come from one refresh.** The worker publishes `self.current` (the messages), `self._board` and `self._board_error` inside one `with self._lock:` block (`envelope_snapshot.py:293-300`), **but when the board projection raises, the `except` branch at `:289-291` keeps the old board** (`board, board_error = self._board, type(exc).__name__`) while `self.current` advances to the new messages and `self.error` is cleared. So the published pair can be an **old board with new messages**, and the old board can still say `coverage: complete` and a `ready` item. `board()` (`:378-400`) handles this: it reads `_board_error`, forces `coverage.status = "stale"`, sets `last_known`, and appends `board projection failed: <type>` to `errors`. `active_with_freshness()` (`:321-350`) does none of that and returns age and error text, not a generation. The lock is a plain `threading.Lock()` (`:166`), **not reentrant**. **Consequence (round-2 finding 1):** the new accessor must keep every rule of `board()` and carry the board's own generation (section 7.1).
8. **The server's contract** (`web.py:1-103`): loopback only; strict path allowlist; actions off by default; nosniff, `X-Frame-Options: DENY`, `Cache-Control: no-store` on every response (`:4361-4366`); a Host gate (`:4302-4330`); console routes use `_DASHBOARD_CSP` (`:216-218`). HEAD is GET without a body (`do_HEAD`, `:4419-4420`; `_send`, `:4372-4388`).
9. **Project selector.** `_root_selection` (`web.py:4889-4908`) takes `root` as a project id or a unique label, and **without `root` it silently takes `roots[0]`** (`:4892-4893`). **Consequence (reader finding 6):** every link must carry `root`.
10. **Static assets are an exact-name allowlist** (`_load_static_assets`, `web.py:801-829`; route `:5210-5221`).
11. **A bounded-wait gate for scans already exists** (`_SCAN_CONCURRENCY_LIMIT = 2`, `_SCAN_WAIT_TIMEOUT_SECONDS = 3.0`, `_acquire_scan_slot` at `web.py:967-978`; `ScanBusy` answered as 503 with `Retry-After` at `:4436-4454`).
12. **Existing hardened Git pattern** (`work_board_facts.py:133-155`, `_git`): validated arguments, no shell, every inherited `GIT_*` variable dropped, `GIT_NO_LAZY_FETCH=1`, `GIT_NO_REPLACE_OBJECTS=1`, `GIT_TERMINAL_PROMPT=0`, `--no-replace-objects -c core.fsmonitor=false -C <repo>`, `stdin=DEVNULL`, timeout 15 s (`PROBE_TIMEOUT_SECONDS`, `:32`, raised from 2 s after Windows CI flakes, comment `:24-31`). Only `rev-parse`, `merge-base`, `cat-file`. I reuse the pattern in a new module and do not edit `_git`.
13. **Repository allowlist and checkout checks exist** (`repo_aliases`, `work_board_facts.py:69-104`; `_open_repo`, `:158-185`).
14. **Store-session binding is an existing idiom.** Integration facts carry `session_id`; a run refuses to publish after a reset (`work_board_facts.py:312-313`) and the reader refuses facts from another session (`:349-350`). The store session is `cfg.get("session_id")`.
15. **The lead-run command template** (`cmd_board`, `cli.py:8611-8640`; parser `:16703-16720`; run lock with `timeout=0`, `work_board_facts.py:229-233`). `ValueError` reaches `main()` as exit 2 with the message on stderr.
16. **`_atomic.write_text` is not always atomic.** On Windows, when the rename keeps failing with a permission error, it falls back to a direct write of the final path and latches that mode (`_atomic.py:46-51`, `:60-81`, `:96-98`); its own docstring says a reader can catch a half-write there. **Consequence (reader finding 4):** the compare module has its own strict publication step and does not use that helper (section 4.5).
17. **Lock ranks** (`lock_order.py:12-46`): an unknown lock name is a leaf lock (rank 210); a test pins how many lock sites each file has (`tests/test_lock_order.py:80-86`) and `docs/LOCK-ORDER.md` lists every lock.
18. **Spend records.** The gateway's child-turn receipt page has the closed key set `actual_micro_eur, calls, charge_period, closed_at, input_tokens, outcome, output_tokens, quota_lease_ref_sha256, seq` (`ovh_gateway.py:3960-3970`, checked at `:3995-4040`). **It has no seat name.** An open ledger line is a reservation ceiling, not money spent (lead relay of 2026-10-17 11:24 UTC). Section 11.2 says what that makes measurable.
19. **Tests I will lean on**: `tests/test_work_board_reducer.py:25-79` (`Bus`: `task`, `reply`, `rescind`, `add(raw=True)`); `tests/test_work_board_feed.py` (a real `Store`); `tests/test_console2_web.py` pins the allowlisted assets; `tests/test_web.py` serves a real server in a thread. `REVIEW_PAIRS = {("approved","GO"), ("rejected","FIX"), ("rejected","HOLD"), ("needs-info","HOLD")}` (`work_tags.py:196`).
20. **Release plumbing**: static files ship as package data (`pyproject.toml:108-112`); the dev gate pins only `console.css` and `console.js` (`dev_gate.py:360-361`).

**Not found (so not claimed):** no existing diff view, no code-reading route, no repository registry other than `work_repos`.

---

## 4. Registration and its lifecycle

### 4.1 Commands

```
agenttalk compare register --repo <alias> --base <rev> --head <rev>
                           [--work-item <slug> --work-cycle <n>] [--label <text>] [--json]
agenttalk compare amend    <cid> [--work-item <slug> --work-cycle <n> | --clear-work-item] [--label <text>]
agenttalk compare remove   <cid>
agenttalk compare remove   --reconcile
agenttalk compare list [--json]
agenttalk compare show <cid> [--json]       # manifest only, no file text
```

- `--repo` must exist in `work_repos` (D2) and pass `repo_aliases()`.
- `--base` and `--head` are resolved once to full commit ids; **only ids are stored**, so moving a branch changes nothing (C2).
- `--work-item` (`^[a-z0-9][a-z0-9-]{0,63}$`, FACT `_SLUG` in `work_board_facts.py:35`) and `--work-cycle` (an integer 1 to 9999) **are given together or not at all**. The operator says which cycle of the work the comparison belongs to; the page checks that against the board (section 7.3).
- `--label` is up to 120 characters; control characters are refused.
- `list` and `show` never run Git and never write.

### 4.2 What registration checks, in order (each failure is one exit-2 message)

1. `git --version` parses and is at least **2.32** (ASSUMPTION: older Gits ignore `GIT_CONFIG_GLOBAL`, so they are refused rather than guessed at).
2. The alias exists and is valid.
3. The checkout is usable: canonical path, top of a work tree, **not shallow**, **not a partial clone** (call C3).
4. `--base` and `--head` resolve to commits (C4, C5).
5. `--base` is an ancestor of `--head` (C6).
6. **The whole range has no merge commit.** A separate call, `rev-list --merges --max-count=1 --end-of-options <head> ^<base>` (call C7a), looks at **every** commit of the range, not at the displayed list. Any output refuses the registration: `range contains a merge commit; slice 1 compares linear ranges`. The displayed commit list (C7b) is independent of this check. Merge-containing ranges are **not** supported in slice 1.
7. Capacity: at most **20** comparisons; the 21st is refused with `remove one first: agenttalk compare remove <cid>`.
8. **WO1 only (until work order 2): the range may contain only ordinary regular files** (added, modified or deleted; text, binary or too large). A changed path that is a symlink, a submodule, a type change, a mode change of any kind (including the executable bit), a path whose mode is not one of `100644`, `100755`, `120000`, `160000`, a missing object, or a path matching the withheld names of 5.8 **refuses the registration** and names the first five such paths and their kind: `unsupported in this version: <kind> at <path>`. It is never processed as an ordinary file. Work order 2 replaces this refusal by the states of 5.6.
9. Anything over a size limit is **registered with `truncated` flags**, never refused (section 5.5).

### 4.3 Stored format (schema version 1)

Directory `<store.dir>/compare/` (D3):

```
compare/registry.json              <= 64 KiB
compare/<cid>/manifest.json        <= 256 KiB
compare/<cid>/files/0001.json ...  <= 1.5 MiB each, at most 500
compare/.staging-<cid>-<random>/   exists only during a registration
```

`cid` = `"cmp-" + first 12 hex of sha256("<project_id>|<alias>|<base_oid>|<head_oid>")` (the work item and label are **not** part of the id, so correcting them keeps the id).

Each registry entry: `id, label, repo_alias, base, head, work_item (or null), work_cycle (or null), project (project id), session_id (the store session at registration), created_at, counts, truncated`. The manifest adds `git_version`, `repo_path` (display only, never used to read), the commit list (up to 200 commits, oldest first: `oid, parents, author_name, author_date, subject`), the file list (up to 500: `index, path, status, old/new mode and oid, state, lines_added, lines_removed, old_size, new_size`), `limits` (every limit value used) and `built_at`.

Every reader of these files reads at most limit+1 bytes, refuses if over, checks `schema_version == 1`, validates every field's type and shape, and on any doubt answers "snapshot unreadable" (an error state, never a partial render). FACT: `work_board_facts._read` behaves this way (`:293-326`).

### 4.4 Same range again, corrections, removal

- **Same range, same metadata:** a no-op that prints the existing id (exit 0). It also **verifies the stored snapshot is complete** (manifest present, every listed file present and within its bound; absence and corruption are told apart from I/O failure, see below). If not: exit 2 `snapshot is incomplete: run compare remove <cid> and register again`. It never reports success for missing content.
- **Same range, different `--work-item`, `--work-cycle` or `--label`:** **an explicit error** (exit 2): `already registered with different metadata; use compare amend <cid>`.
- **`compare amend`** rewrites only `label`, `work_item`, `work_cycle` of one registry entry, under the lock, through the publication step of 4.5. It never touches code, commits or the snapshot directory. `--clear-work-item` sets both to null.
- **Owned names (the closed set).** The compare commands own, and may delete, only these entries directly under `compare/`: directories named `cmp-<12 hex>`; directories named `.staging-cmp-<12 hex>-<8 hex>`; files named `registry.json` and `registry.json.<random>` (the temporary file of 4.5). **Every other name is left alone and reported** ("not owned by compare: <name>"); it is never deleted.
- **Deleting is no-follow, at every level.** The deleter walks with `os.scandir` and `os.lstat`, never follows a link, and never calls a recursive delete that follows links. A symbolic link, a Windows reparse point or a junction is removed **as the link itself** (never its target); a regular file is unlinked; a directory is emptied and then removed. Before descending into `compare/`, `<cid>/` and `files/` the deleter checks each component is a real directory (not a link, not a reparse point); if not, it refuses to descend and reports it.
- **Three kinds of "not fine", told apart.** (a) **Absent** (`FileNotFoundError`): the entry is missing. (b) **Corrupt** (the file reads but is over its bound, malformed, of another schema, or the manifest and files disagree): the entry is incomplete. (c) **Unreadable** (`PermissionError` or any other `OSError` while checking): **not evidence of anything**. Reconcile **never drops or deletes an entry because of (c)**: it skips it, reports `could not check <cid>: <error>`, and exits 2 at the end.
- **`compare remove <cid>`:** under the lock, (1) publish a registry without the entry, then (2) delete the directory by the no-follow rule. If step 2 fails the message says exactly that: `the comparison is no longer listed; its directory could not be deleted (<error>); run compare remove --reconcile`.
- **`compare remove --reconcile`:** under the lock, (1) drop every registry entry whose directory is **absent or corrupt** (a and b only), (2) delete every owned directory not named by the registry and every owned `.staging-*` directory and temp file, (3) print what it dropped, deleted, skipped and left alone. This is how a full registry gets room back after someone deleted a directory by hand.
- **Register meets an orphan:** an owned directory `<cid>` exists but the registry does not list it: register (under the lock) deletes it by the rule above and builds fresh.
- **Readers during remove, reconcile and re-register.** A reader holds no lock. It opens the registry first, then the directory. If the directory has vanished between the two, the request answers `404 comparison not found` (or the list shows the entry's snapshot as unreadable); it never crashes and never mixes files of two registrations: a re-registration of the same id writes byte-identical content (immutable), and `amend` touches only the registry.
- **Capacity message** names `compare remove` and `compare remove --reconcile`.

### 4.5 One strict publication step

`compare_snapshot._publish_bytes(path, data)`: write a temporary file in the same directory, `fsync` it, then `os.replace`. On Windows, retry `os.replace` up to 5 times with 100 ms pauses on `PermissionError` (a reader holding the file). **If it still fails, the step raises** and the registration is refused. There is **no direct-write fallback**, and the shared helper `_atomic.write_text` is neither used nor changed (FACT: `_atomic.py:46-51`, `:60-81`).

A registration builds everything in `.staging-cmp-<12 hex>-<8 hex>/` (manifest and every file, each published by the step above), then renames the staging directory to `cmp-<12 hex>` (`os.rename`, refused if the destination exists), and **publishes `registry.json` last**. A reader therefore sees either the old registry or the new complete one, and the registry only ever names complete directories. Readers still treat a torn or missing file as an error state (defence in depth, not the guarantee).

**What the error message says depends on how far the registration got (exact):**
- failure before the directory rename: `registration failed; nothing was published` (staging removed);
- failure after the directory rename and before or during the registry publication: the command first tries to delete the just-renamed directory by the no-follow rule. If that works: `registration failed; nothing remains`. If it does not: `registration failed after the snapshot directory was created; it is an unlisted orphan (<cid>); run compare remove --reconcile`. **It never claims "nothing was changed" when a directory exists.**

**Durability claim, stated narrowly:** a crash or kill of the **process** at any point leaves a registry that names only complete directories and at most one harmless orphan or staging directory. Power-loss durability is **not** claimed on Windows. Where the platform supports it (POSIX), the writer also `fsync`s the containing directory after each rename.

### 4.6 Concurrency between writers

One lock for register, amend, remove and reconcile: `store._exclusive_lock(store.dir / "compare.lock", timeout=0, what="compare lock")`; a second writer is refused at once (`another compare command is running`). It is a leaf lock (rank 210, FACT `lock_order.py:46-47`); nothing inside it calls a store transaction. The builder updates `tests/test_lock_order.py:80-86` (`"compare_snapshot.py": <number of sites>`) and `docs/LOCK-ORDER.md`. HTTP readers take no lock; the publication order above is what keeps them safe.

---

## 5. Reading the repository (registration time only)

### 5.1 Principles (C4)

- Plumbing commands only: `rev-parse`, `config`, `cat-file`, `merge-base`, `rev-list`, `diff-tree`. **Never** `diff`, `show`, `log`, `status`, `archive`, `grep`, `blame`, `fetch`, `pull`, `checkout`, or anything that can run a diff driver, text-conversion filter, hook, editor or pager.
- Only **blobs named by the registered range** are read: the old and new blob ids that `diff-tree` lists for `base..head`. No other object id is ever requested.
- **No object is fetched.** Shallow checkouts and partial clones are refused; `GIT_NO_LAZY_FETCH=1` is a second layer.
- **Counts are exact or marked.** Anything cut by a limit sets a `truncated` flag the page shows.

### 5.2 The process environment and argument prefix

**Environment:** start from the current environment, **remove every key that starts with `GIT_`** (case-insensitively), then set:

| Variable | Value | Why |
|---|---|---|
| `GIT_NO_LAZY_FETCH` | `1` | never fetch missing objects (FACT: already used, `work_board_facts.py:149`) |
| `GIT_NO_REPLACE_OBJECTS` | `1` | a replace ref cannot swap an object |
| `GIT_TERMINAL_PROMPT` | `0` | no credential prompt |
| `GIT_OPTIONAL_LOCKS` | `0` | reads never write the index or refs |
| `GIT_CONFIG_NOSYSTEM` | `1` | ignore the system config |
| `GIT_CONFIG_GLOBAL` | `os.devnull` | ignore the user's config (Git 2.32+). ASSUMPTION: Git for Windows accepts `NUL`; the work order tests it on Windows |
| `GIT_ATTR_NOSYSTEM` | `1` | ignore system attributes |
| `LC_ALL` | `C` | stable messages |

**Argument prefix for every call** (a list, `shell=False`):

```
[git_exe, "--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "protocol.allow=never",
 "-c", "diff.external=", "-c", "core.attributesFile=<os.devnull>", "-C", "<canonical repo path>", <subcommand>, ...]
```

`git_exe` is `shutil.which("git")`, resolved once per run, refused if missing or relative.

**Closed allowlist** (a dict in code, checked before every call; anything else raises `ValueError("git call not allowed")` before a process starts):

| Subcommand | Allowed argument patterns |
|---|---|
| `rev-parse` | `--show-toplevel`; `--is-shallow-repository`; `--verify --quiet --end-of-options <rev>^{commit}` |
| `config` | `--local --get-regexp <the fixed pattern of C3>` |
| `cat-file` | `-t <oid>`; `--batch-check=<fixed format>`; `--batch` (ids come from a file) |
| `merge-base` | `--is-ancestor <oid> <oid>` |
| `rev-list` | `--merges --max-count=1 --end-of-options <oid> ^<oid>`; `--topo-order --max-count=201 --end-of-options <oid> ^<oid>` |
| `diff-tree` | `-r -z --raw --no-renames --no-ext-diff --no-textconv --no-abbrev --end-of-options <oid> <oid>` |

Every `<oid>` must match `^[0-9a-f]{40}$|^[0-9a-f]{64}$`. The only free-text revisions (`--base`, `--head` as typed) go through call C4 after the check `^[A-Za-z0-9._/@^~-]{1,200}$` (not starting with `-`) and `--end-of-options`.

### 5.3 The calls

| Id | argv after the prefix | Success / failure |
|---|---|---|
| C0 | (no prefix) `[git_exe, "--version"]` | parsed; below 2.32 refuse |
| C1 | `rev-parse --show-toplevel` | equals the alias path after `normcase(normpath(...))` (FACT `_open_repo`, `:158-185`) |
| C2 | `rev-parse --is-shallow-repository` | must print `false` |
| C3 | `config --local --get-regexp ^(extensions\.partialclone|remote\..*\.(promisor|partialclonefilter))$` | exit 1 (no match) is success; any match refuses |
| C4 | `rev-parse --verify --quiet --end-of-options <rev>^{commit}` (base, head) | exactly one oid |
| C5 | `cat-file -t <oid>` | must print `commit` |
| C6 | `merge-base --is-ancestor <base> <head>` | 0 yes; 1 refuse; other = error |
| **C7a** | `rev-list --merges --max-count=1 --end-of-options <head> ^<base>` | **any output refuses the registration** (a merge anywhere in the **whole** range); runs over the full range, independent of what is displayed |
| **C7b** | `rev-list --topo-order --max-count=201 --end-of-options <head> ^<base>` | **Git applies `--max-count` to the traversal from the head, so this returns the NEWEST 201 commits, newest first** (the `--reverse` of round 2 is dropped: with it, the head itself could be the omitted entry). At most 201 lines read; 201 lines means `truncated.commits`; keep the first 200 (the **newest 200, always including the head**) and reverse them in Python for display (oldest first). The page says "the newest 200 commits are shown; the range is longer". The head is always in the list; the base's child may not be |
| C8 | `cat-file --batch` over the (at most 200) kept commit ids | parse `parent`, `author`, first message line (display only; the merge decision is C7a's) |
| C9 | `diff-tree -r -z --raw --no-renames --no-ext-diff --no-textconv --no-abbrev --end-of-options <base> <head>` | keep the first 500 entries in path order; more sets `truncated.files` |
| C10 | `cat-file --batch-check=%(objectname) %(objecttype) %(objectsize)` over the old and new blob ids of the kept entries | sizes without reading content |
| C11 | `cat-file --batch` over the ids of a **selected batch** (5.4: at most `MAX_BLOB_BATCH_BYTES` of blob bytes per call, several calls if needed) | `<oid> blob <size>\n<bytes>\n` per blob |

All output is read as **bytes**; nothing is decoded before the size checks. The relation of a verdict head to the range (7.5) uses the C7b list; when `truncated.commits` is true, a head that is not in the list is `unknown_relation` (never "outside the range"), **except** that the base id and a null head are decided first.

### 5.4 One bounded-reader strategy, and what it does and does not bound

`subprocess.run(capture_output=True)` collects everything before returning, so a size check afterwards cannot bound memory or time. The Git module therefore has **one** function, `compare_git._run(argv, *, stdin_bytes, stdout_cap, stderr_cap, deadline)`, and nothing else starts a process.

- **No threads and no pipes for data.** `stdin` is a temporary file we wrote (the object-id list) and rewound; `stdout` and `stderr` are two **temporary files** in the staging directory. Nothing can fill an OS pipe, so there is no pipe deadlock and no writer thread.
- The parent uses `subprocess.Popen(argv, stdin=<file>, stdout=<file>, stderr=<file>, shell=False, env=<env>)` and a **poll loop with a nominal 20 ms pause**: `proc.poll()`, `os.fstat` on both output files, and the deadline. If stdout is over its cap, stderr over 64 KiB, the per-call 15 s limit passed or the registration deadline passed, it calls `proc.kill()` then `proc.wait()` and raises. A `try/finally` guarantees `kill` and `wait` on every error path, **including a failure of the poll, of a file read, or of the clean-up itself** (the finally block kills first, then closes and deletes files, and each step is guarded so a later failure cannot skip an earlier one).
- After a normal exit the module reads at most `cap + 1` bytes of each file and refuses if the extra byte exists.

**Three different limits, kept apart (round-2 finding 5):**

| Resource | What bounds it | Strength |
|---|---|---|
| **Memory** of the Python process | it never reads more than `cap + 1` bytes of a child's output; a C11 batch is at most `MAX_BLOB_BATCH_BYTES` (8 MiB) of blob bytes, chosen from the C10 sizes **before** the call; the row builder works on at most 256 KiB x 2 sides of text and 2,000 lines per side | **enforced** (by what is read) |
| **Temporary disk** during a Git call | the polling loop kills the child when it sees an output file over its cap | **soft**: the sleep is nominal, the parent can be descheduled for longer, so the amount written before the kill is **not bounded by the write speed times 20 ms** and no number is promised. Legitimate output is bounded by design (diff-tree 4 MiB cap, commit objects 2 MiB, one blob batch 8 MiB plus headers), so the soft bound only matters for a broken or hostile child. On any failure the staging directory, with its temporary files, is deleted. **This soft limit is accepted and documented**; the operator guide says so |
| **Final snapshot** on disk | `MAX_SNAPSHOT_BYTES` (16 MiB): every file record is added to a running total **before it is published**; a record that would exceed it becomes `state = "not_stored"`. The blobs of such files are **not read** (the batch selection in 5.5 stops once the total of old and new blob bytes selected for stored files would exceed `MAX_SELECTED_BLOB_BYTES`, 8 MiB, an ESTIMATE of half the snapshot limit because the stored rows repeat the text and add escapes) | **enforced** |

**Deadline.** `REGISTER_BUDGET_S = 180` is one `Deadline` object passed to **every phase**: each Git call, the row building of each file, serialising and publishing each file, the directory rename and the registry publication. It is **a checked deadline, not a hard wall-clock ceiling**: it is checked before each call, between files and before each publication, so the overrun is at most one work unit. A single `difflib` call cannot be interrupted; it is bounded by the line limits (5.5) and the builder measures and records the worst case on the 2,000-line fixture. If the deadline passed at a check, the registration is refused and staging removed.

**What the tests may and may not assert.** Termination, reaping and clean-up are asserted exactly. Timing and disk size are asserted only with **generous tolerances** (the runaway-child test requires the child gone within 10 seconds and the staging directory deleted; it never asserts "about 1 second" or "cap plus 32 MiB"); the measured numbers are recorded in the commit message as observations, not guarantees.

### 5.5 Limits and what happens at each

| Constant | Value | When exceeded |
|---|---|---|
| `MAX_COMPARISONS` | 20 | registration refused |
| `MAX_COMMITS` | 200 (the newest 200) | list cut, `truncated.commits`; page text "the newest 200 commits are shown" |
| `MAX_FILES` | 500 | list cut (path order), `truncated.files` |
| `MAX_BLOB_BYTES` | 262,144 per side | that file `state = "too_large"`, both sizes shown, no content |
| `MAX_LINES` | 2,000 per side | `state = "too_large"` (lines) |
| `MAX_LINE_CHARS` | 2,000 | **only the displayed cell** is cut and ends with `... (+N characters)`; the comparison uses the full line |
| `MAX_BLOB_BATCH_BYTES` | 8,388,608 of blob bytes per `cat-file --batch` call | more blobs go in a further call |
| `MAX_SELECTED_BLOB_BYTES` | 8,388,608 in total (old plus new sides of stored files) | later files get `state = "not_stored"` and their blobs are not read |
| `MAX_FILE_RECORD_BYTES` | 1,572,864 | the record is replaced by `state = "too_large"` |
| `MAX_SNAPSHOT_BYTES` | 16,777,216 in total | remaining files get `state = "not_stored"` (listed, counted, not shown) |
| `GIT_CALL_TIMEOUT_S` | 15 | registration refused, nothing published |
| `REGISTER_BUDGET_S` | 180, checked between work units (5.4) | registration refused |
| `GIT_OUTPUT_CAP_BYTES` | rev-list 64 KiB; diff-tree 4 MiB; commit objects 2 MiB; one blob batch 8 MiB plus 64 bytes per blob; stderr 64 KiB | the child is killed (soft disk bound, 5.4), registration refused |
| `EXCERPT_CHARS` | 600 | excerpt cut and ends with `...` |
| `MAX_HISTORY_ROWS` | 50 | "50 of N shown" |
| `MAX_TASK_ROWS` | 20 | "20 of N shown" |
| `MAX_OBLIGATION_ROWS` | 20 | "20 of N shown" |

### 5.6 Side-by-side rows without losing changes

**Rule: equality and change counts are decided from the raw bytes. Escaping and shortening apply only to the displayed cells.** No Git diff output is used; the builder uses `difflib.SequenceMatcher(None, a, b)` (default `autojunk`) over **raw lines**.

**Step 0: what kind is each side?** From the mode in the `diff-tree` record: **regular** (`100644`, `100755`), **symlink** (`120000`), **gitlink** (`160000`), or **unsupported**. A missing side (added or deleted path) has no kind and **no lines**.

| Old kind | New kind | blob ids | State and display |
|---|---|---|---|
| regular | regular | equal, modes differ | `mode_only`: no content shown; the header says `mode 100644 -> 100755` |
| regular | regular | **differ** | compare the **raw bytes** (steps 1 to 10 below) **and** show the mode change **separately**: when the modes differ, the file header carries `mode_change: {old, new}` ("mode 100644 -> 100755") above the rows, and the file list marks the path `M+mode`. The content is never hidden by a mode change |
| symlink | symlink | differ | the targets are small blobs (at most 4 KiB); compare them as raw bytes, one line each, with the same rows and markers |
| regular | symlink, or symlink | regular | `type_change`: **not paired**. The left cell shows the old side by **its own kind** (regular: its text rows or "binary"; symlink: `symlink -> <target>`), the right cell the new side by its own kind. Rows are all `del` on the left and all `add` on the right; counts come from the raw lines of the regular side (a symlink side counts as one line). The new source file is **never** shown as "a one-line symlink target", nor the target as file text |
| regular or symlink | gitlink, or gitlink | regular or symlink | `type_change` as above, with the gitlink side shown as `submodule <commit id>` |
| gitlink | gitlink | differ | `submodule`: both commit ids, no content |
| any | unsupported mode | | `unsupported_mode`: the mode text and ids, no content |
| any | any | blob object missing | `missing_object` (never fetched) |

**Rows for two regular sides, or two symlink targets:**
1. **Binary?** A NUL byte in the first 8,000 bytes of either side (Git's own rule): `state = "binary"`, sizes only (a mode change is still shown by the table above).
2. **Raw lines.** Split each side's bytes on `b"\n"`. **Empty data has zero lines** (a missing or empty side is never "one blank line"). Otherwise, if the data ends with `\n` the trailing empty piece is **dropped** and `has_eol = True` for the last line; if it does not, the last line has `has_eol = False`. Each line is a pair `(line_bytes, has_eol)`; a CR before the newline **stays inside `line_bytes`**. So `x` versus `x\r`, and `x\n` versus `x` (no final newline), are different lines.
3. **Opcodes** from `SequenceMatcher` on those pairs.
4. **Display cells** (made after the decision): decode the line bytes as UTF-8 with replacement; replace every C0 control character except tab (**this includes a trailing CR, which is shown as the visible `<U+000D>`**, the one rule everywhere; the file header also says `line endings: CRLF` or `mixed` when it applies, so a whole CRLF file's markers are explained; ASSUMPTION: the noise is acceptable for slice 1 and the checkpoint readers judge it), the DEL character, and every bidirectional control (U+202A-U+202E, U+2066-U+2069, U+200E, U+200F) by the visible escape `<U+XXXX>`; cut at 2,000 characters.
5. **Row kinds:** `eq`, `chg` (a `replace` pair), `add`, `del`, `gap` ("N unchanged lines"; an `equal` run longer than 6 lines keeps 3 lines of context at each end).
6. **Every `chg` row says why the bytes differ when the cells look the same.** If the two display cells are **equal text**, the row gets `same_preview: true`, `diff_at` and `reason`. **`diff_at` is the first differing byte offset in each line's full byte form, `line_bytes + (b"\n" if has_eol else b"")`**, so a change that is only the final newline has `diff_at = len(line_bytes)` even though `line_bytes` are equal. `reason` is one of `line_ending`, `final_newline`, `invalid_utf8`, `escaped_or_cut` or `other`. The page shows the row as **changed** with "bytes differ; the difference is not visible in this preview (<reason>)".
7. `stats.added` counts right lines in `add` and `chg` rows; `stats.removed` counts left lines in `del` and `chg` rows, from the raw decision.
8. A row is `{"t": "eq|chg|add|del|gap", "l", "r", "a", "b", "same_preview": bool, "diff_at": int or null, "reason": str or null}`; a gap row is `{"t": "gap", "skipped": N}`; a line with any replacement carries `"esc": true`.

**Collision cases** (golden `tests/golden/compare_rows_collisions.json`, plus the rendered-view tests): (a) 2,000 identical characters then `allowed` versus `blocked`; (b) a real U+202E versus the literal `<U+202E>`; (c) byte `\xff` versus `\xfe`; (d) `x\n` versus `x\r\n`; (e) with and without a final newline; (f) one differing byte after column 2,000; (g) **empty file versus a file holding one empty line**; (h) **a final-newline-only change** (`diff_at = len(line_bytes)`). **Mode and type cases** (golden `tests/golden/compare_rows_kinds.json`): (i) content edit plus `100644 -> 100755` (rows shown, mode shown separately); (j) mode only with equal ids; (k) symlink target change; (l) symlink to regular file; (m) regular file to symlink; (n) regular file to submodule.

One file record (`files/NNNN.json`): `schema_version, index, path, status, old {oid, mode, kind, size, lines}, new {...}, mode_change, state, invalid_text, path_lossy, stats, rows, rows_truncated`. `status` is `A`, `M`, `D` or `T`. `--no-renames` means a moved file is a deletion plus an addition (ASSUMPTION: acceptable for slice 1).

### 5.7 Why a snapshot and not a live read (D1)
It keeps the standing rule; every limit lives in one place, in a command a person runs with a lock; and the endpoints can only open files under `.agenttalk/compare/<cid>/` chosen by a validated id and index, so the page cannot read outside the registered range **by construction**. The cost is that a comparison does not follow a moving branch; that is the meaning of "immutable base and head" (C2).

### 5.8 What the snapshot exposes, and the operator's part (reader finding 12)

- **The precise guarantee.** Reads are limited to the blobs of the paths **changed between the two registered commits**, on both sides. That avoids a repository-wide history browser. It does **not** make the content safe to publish: a changed or deleted credential file is among the old and new blobs, and so is any secret that was added or removed in the range.
- **The operator's responsibility.** The operator chooses which repositories and ranges to register and must only register content that may sit in the store. In this build that is the fixture and agenttalk itself (public) (C5). A **content-selection policy for confidential repositories does not exist in slice 1 and registering one is out of scope** until the lead defines one.
- **Best-effort withholding, not a promise.** A changed path whose file name matches `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `.netrc`, `credentials*` or `*.kdbx` is listed with `state = "withheld"` and **no content stored** (work order 2). This is a convenience, not a guarantee: secrets live in other names.
- **Containment of reads and of deletes.** On **both** the reader path and the writer and deleter paths, for **every component** (`compare/`, `compare/<cid>/`, `compare/<cid>/files/`, and the leaf file) the code checks that the entry is not a symbolic link and (Windows) not a reparse point or junction (`os.lstat`, `stat.S_ISREG` or `S_ISDIR`, `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`), and that the resolved path is inside `compare/`. A reader violation is the "snapshot unreadable" state; a writer or deleter violation refuses to descend (4.4). The cid and index regexes already exclude separators; this protects against a link planted in the directory.
- **Backup and recovery.** `recovery.py:162-173` copies every file under the store recursively. The snapshot text therefore ends up in store backups and recovery copies, and `compare remove` does not delete earlier backups. Retention of those copies is the backup's retention. The operator guide (`docs/COMPARE-VIEW.md`) says so.
- **Nothing is sent anywhere.** The page loads only local assets (CSP, section 8.1), and the builder's model only sees the fixture and agenttalk source (C5). A test refuses a foreign repository when `AGENTTALK_COMPARE_FIXTURE_ONLY=1` is set: an alias whose canonical path is not under the test's temporary directory or the agenttalk checkout (ASSUMPTION: the lead can set that variable for the builder's seat; otherwise the written work-order rule is the control).

### 5.9 Not in the design
A server-side Git read is **not** an option here (D1). It is not described further.

---

## 6. The GET endpoints (all new, GET and HEAD only)

**General rules (FACT patterns, `web.py:4286-4454`, `:5076-5246`).**
- Dispatch in `_route` after the existing Host, peer and method gates. POST, PUT, DELETE and PATCH on these paths behave exactly as on every other path; **no `do_POST` branch is added** (test `test_compare_paths_refuse_post_put_delete`).
- **Root selection** is `_root_selection(self._request_params())` as for `/api/work-board`; an unknown root is `400 bad_root`.
- **Query strings are closed:** only `root` (once, non-empty) is accepted. Any other key or a repeat is `400 {"error": "bad_query"}`. The page itself puts only `id` and `root` in its own address (the `/compare` HTML shell accepts exactly those two keys; anything else is the same 400).
- Responses use `_send_json` (nosniff, `X-Frame-Options: DENY`, `Cache-Control: no-store`, default CSP). The HTML shell uses `_DASHBOARD_CSP`.
- **Caps are checked after serialising**: an over-cap body becomes `500 {"error": "response_too_large"}`.
- **Concurrency gate** (copy exactly; the only threading code of the feature):

```python
_COMPARE_READ_LIMIT = 4            # at most 4 comparison reads at once per server
_COMPARE_WAIT_SECONDS = 3.0        # then answer 503 instead of blocking the handler thread
_compare_gate = threading.BoundedSemaphore(_COMPARE_READ_LIMIT)

@contextlib.contextmanager
def _compare_slot():
    if not _compare_gate.acquire(timeout=_COMPARE_WAIT_SECONDS):
        raise ScanBusy()           # do_GET already maps ScanBusy to 503 + Retry-After
    try:
        yield
    finally:
        _compare_gate.release()
```

  (`ScanBusy` and the pattern: `web.py:947-978`, `:4436-4454`.) Each handler wraps its whole body in `with _compare_slot():`. The gate limits handler threads; it does not make two reads consistent; section 7.1 does.

### 6.1 `GET /compare` and the three static files
HTML shell from `render_compare()` modelled on `render_console2()` (`web.py:723`), `csp=_DASHBOARD_CSP`, no data inside. `compare.css`, `compare-model.js`, `compare.js` are added to `_load_static_assets` (`web.py:810-820`).

### 6.2 `GET /api/compare` (list)
- **Inputs:** `root` optional.
- **Output (200):** `{"schema_version": 1, "project": {"project_id", "label", "path"}, "generation": <board generation>, "comparisons": [<entry + "status": {...}>], "errors": []}`. Each row's `status` is the function of section 7.4, computed from **the registry entry plus the board item plus the board's coverage and the store session**: exactly the inputs the detail uses, so list and detail agree (the verdict relations are history only and are not inputs).
- **Cap:** 64 KiB. **Limit:** 20 comparisons.
- **Errors:** `400 bad_root` / `bad_query`; `200` with an empty list and `errors: ["no comparisons are registered"]` when nothing exists; `200` with an empty list and `errors: ["registry unreadable: <reason>"]` when the file is over its bound, malformed, of another schema or fails containment; `503 busy`.

### 6.3 `GET /api/compare/<cid>` (detail)
- **Inputs:** `<cid>` must match `^cmp-[0-9a-f]{12}$` **before any disk access**; `root` optional.
- **Output (200):** the registry entry, `commits`, `files` (index, path, status, state, counts, sizes), `project`, and `evidence` (section 7.5).
- **Cap:** 512 KiB. **Limits:** 200 commits, 500 files, 50 history rows, 20 task rows, 20 obligation rows. The status is computed **before** any row limiting.
- **Errors:** `400 bad_root` / `bad_query`; `404 {"error": "comparison not found"}` for an unlisted id or a missing directory; `200` with `"snapshot": {"status": "unreadable", "reason": ...}` and empty `commits`/`files` when a stored file is invalid (evidence is still computed); `503 busy`.

### 6.4 `GET /api/compare/<cid>/file/<n>`
- **Inputs:** `<cid>` as above; `<n>` matches `^[1-9][0-9]{0,3}$` and is at most the manifest's file count; `root` optional.
- **Output (200):** the stored file record, plus `id` and `n`.
- **Cap:** 2 MiB.
- **Errors:** `400`; `404 comparison not found` / `404 file not found`; `200` with `"state": "unreadable"` and `reason` for an invalid record; `503 busy`.

### 6.5 Every handler, in order
1. Validate path pieces by regex. 2. Select the root. 3. Take the gate. 4. Open files only under `store.dir / "compare" / <cid> / ...` after the containment checks (5.8). 5. Read with the byte bound. 6. Validate shape. 7. Build the response. 8. Check the cap. 9. Send.

---

## 7. Tying the board's record to the comparison (C3)

### 7.1 One consistent evidence projection that keeps every board rule (round-2 finding 1)

**The problem (FACT, section 3 item 7).** A board-only projection failure leaves an old board with new messages. A projection that only checked the messages would show a green READY from the old board.

**The fix: `SnapshotService.compare_view(cfg)`** (in `envelope_snapshot.py`, next to `board()`), built so the rules of `board()` cannot diverge from it:

1. **Extract, do not copy.** The body of `board()` is split into two private pieces: `_board_locked()` (called with the lock held; returns a deep copy of `self._board`, the coverage dict from `_coverage_locked()`, and `self._board_error`) and a pure `_finish_board(feed, status, board_error)` (called **after** the lock is released; applies **every** rule `board()` applies today: the `building` placeholder when there is no board; `coverage.status` forced to `stale` when `board_error` is set; the `last_known` marking and `total_count = None` when coverage is not `complete`; the `board projection failed: <type>` entry in `errors`; then `bounded()`). `board()` becomes `with lock: parts = _board_locked()` then `return _finish_board(*parts)`. **A behaviour-preserving extraction**: the existing board tests pass unchanged.
2. **`active_with_freshness()` is extracted the same way** into `_active_locked(cfg)` (called with the lock held; same checks: building, config digest, real failure) so the new method can use it under its own lock.
3. **`compare_view(cfg)`** does `with self._lock:` **once**, calls `_board_locked()` and `_active_locked(cfg)` (the private helpers, **never the public accessors**: the lock is a plain non-reentrant `threading.Lock()`, `:166`, so a public accessor called while holding it would deadlock), and reads `self._board_generation`; it releases the lock, then runs `_finish_board(...)` on the copy. It returns `{"board": <finished feed>, "messages": <deep copy>, "invalid_count", "freshness", "messages_generation": value.generation, "board_generation": <below>, "board_error": <type or None>}`.
4. **The board's own generation.** The worker gets one new field, `self._board_generation`, set **inside the same publication block** as `self._board` (`:293-300`): `value.generation` when the board was built in this refresh (`board_error is None`), **left unchanged when the old board was retained** (`board_error` set). It is therefore the generation the board was really built from. The compare response **never labels the board with the messages' generation**.
5. **Mismatch is visible or rejected.** If `board_generation != messages_generation`, or `board_error` is set, or the finished feed has `last_known`, a coverage status other than `complete`, or any `errors` entry, the status function (7.4 rule 1) returns `cannot_tell` with the reason `the board is from an earlier refresh than the messages` (or `the board projection failed (<type>)`, `the board is last-known`), and the history rows carry the note "from an earlier board; messages are newer". The response prints **both** generations.
6. If `snapshots` is `None` (a server without workers) the evidence status is `board_unavailable` (FACT: the existing route has this branch, `web.py:5103-5107`).

**Edited files:** `envelope_snapshot.py` (the extraction, `compare_view`, `_board_generation`; about 60 lines changed). **Tests (WO1, `tests/test_envelope_snapshot_compare_view.py`):**
- `test_compare_view_matches_board_and_active_rules_exactly` (the finished feed equals `board()` on the same state, for a complete board, a building board, an incomplete board and a failed projection);
- `test_compare_view_reads_board_and_messages_under_one_lock` (a refresh forced between the two old calls cannot split `compare_view`'s answer);
- **`test_board_only_projection_failure_is_never_ready_or_done`** (the reader's test): a **good refresh** with a ready item; then `work_board_feed.build` patched to raise and a second refresh (so messages advance and the old board is retained); assert `compare_view` returns `board_generation < messages_generation`, `board_error` set, `last_known`, coverage `stale`; and, through the **real** `/api/compare/<cid>` payload, assert `evidence.status.state == "cannot_tell"` with that reason, never `ready` or `done`; and, through the **DOM harness**, assert the rendered page shows the CANNOT TELL banner and **no element with the ready or done state**. (This is in WO1: the saved-state-to-API-to-DOM check of lesson `process/dashboard-contract-needs-real-projection-test`.)
- `test_compare_view_refuses_like_active_with_freshness` (building, config digest changed, real failure);
- `test_existing_board_and_active_accessors_unchanged_by_the_extraction` (the existing envelope-snapshot suites run unchanged).

### 7.2 What status uses and what history uses
- **Status** uses only: the registry entry, the board item for `work_item`, the board's coverage, and the store session. It never uses the verdict map, the messages or the manifest.
- **History** (verdict rows, task rows, obligation rows) uses the verdict map, the obligations and the messages. If any history join fails, that row says so; **the status does not change** and is never made to look better or worse by a failed join.

### 7.3 The binding checks (reader finding 3)

A comparison is tied to the board item only when **all** of these hold; the first that fails sets the status to CANNOT TELL with the exact two values that differ:

| # | Check | Source |
|---|---|---|
| B1 | the comparison links a work item and a cycle | registry `work_item`, `work_cycle` |
| B2 | the item is on the feed | feed `items` |
| B3 | **session**: the comparison's `session_id` equals the store's current `session_id` | registry vs `store.load_config()["session_id"]` (idiom: `work_board_facts.py:312-313`, `:349-350`) |
| B4 | **cycle**: the registry `work_cycle` equals the item's `cycle` | item `cycle` (`work_board.py:478`) |
| B5 | **repository**: item `repo_binding` is a dict whose `repo` equals the comparison's `repo_alias`; `None` or `"ambiguous"` fails | item `repo_binding` (`:656-662`) |
| B6 | **project**: the registry `project` equals the served root's project id | registry vs `root.store.project_id()` |
| B7 | **commit**: the item's `candidate` equals the comparison's `head` | item `candidate` (`:532`) |

A store reset changes the session, so B3 fails: the old comparison stays visible and its status is CANNOT TELL ("registered in an earlier store session"). A later cycle reusing the slug fails B4 and the page shows the board's cycle beside the registered one; the operator may `compare amend` to rebind it deliberately. Two repositories that contain the same commit fail B5 unless the work item declared this alias.

### 7.4 The status function (one pure function; every row tested)

Inputs: registry entry, board item (or the reason it is missing), board coverage, current store session, served project id. Output: `{"state", "text", "reasons"}`. Evaluate in order; the first rule that applies decides.

| # | State | Applies when | Text |
|---|---|---|---|
| 1 | `cannot_tell` | no work item linked; the board is unavailable, building, stale or `last_known`, its coverage is not `complete`, its feed has any `errors` entry, a board projection failure is recorded, or `board_generation != messages_generation` (7.1); the item is not on the feed; any of B3 to B7 fails; `item.column` or `workflow_column` is `unknown`; `item.issues` is not empty | `CANNOT TELL whether this head is ready.` plus one bullet per reason: the reducer's `reason` and each `issues` entry verbatim, or one of: `no work item is linked to this comparison`, `this work item is not on the board feed`, `the board is still building`, `the board is stale, last-known or incomplete`, `the board projection failed (<type>)`, `the board is from an earlier refresh than the messages`, `registered in an earlier store session`, `registered for cycle N; the board is on cycle M`, `the work item declares repository X, not Y` (or `declares no repository`), `the board's current candidate is <12 characters>, not this head` |
| 2 | `done` | `column == "done"` **and** the integration value for this head is true **and** B5 holds | `DONE: this head is integrated in the configured target (<target from repo_binding>).` plus the reducer's reason |
| 3 | `ready` | `column == "ready"` | `READY: the board places this head as ready (<reducer reason>).` |
| 4 | `not_ready` | `column` is `fix_round`, `building` or `queued` | `NOT READY: <fix round / being built / not started> (<reducer reason>).` |
| 5 | `waiting` | `column == "independent_review"` | `WAITING for a review (<reducer reason>).` |
| 6 | `needs_operator` | `column == "needs_you"` | `NEEDS THE OPERATOR: an incident is open for this work.` |
| 7 | `cannot_tell` | any other column, or `done` without a true integration value for this head | `CANNOT TELL: the board's placement is "<column>".` |

**The page never prints "approved" in the status.** An independent GO is part of how the board reaches `ready`; the page reports the board's own word. **Integration** (reader finding 10) shows three ways: value true with B5 holding: "integrated in the configured target (<target>)"; value `False`: "checked: NOT integrated"; absent: "integration not checked"; anything with B5 failing: "integration cannot be tied to this repository". `<target>` is `repo_binding["target"]`, the declared target (FACT `:660`); if it is `None` the text says "the configured target".

### 7.5 History rows (shown as history, never as status)

Let `H` = the comparison's head, `B` = its base, `C` = the stored commit list. For a verdict filed under head `vh` (a key of `item["verdicts"]`; `"null"` means no head named):

Rules are evaluated **in this order** (a null head is decided first, so it is never described as an unplaceable commit):

| # | Relation | Rule | Text |
|---|---|---|---|
| 1 | `no_head` | `vh == "null"` | "no commit was named" |
| 2 | `this_head` | `vh == H` | "this head" |
| 3 | `base` | `vh == B` | "the base (before these changes)" |
| 4 | `earlier_in_range` | `vh in C` (the newest-200 list of C7b) | "an EARLIER head in this comparison" |
| 5 | `unknown_relation` | `truncated.commits` is true and `vh` is not in `C` | "a commit we cannot place (the range has more than 200 commits)" |
| 6 | `outside_range` | a full id not in `C` and `truncated.commits` is false | "a commit outside this comparison" |

Relation uses only the stored commit list: no Git at read time. Row labels (exact strings; the page copies them):

| Verdict | Relation | Label | Mark |
|---|---|---|---|
| GO | `this_head` | `Recorded GO on this head.` | `[ ]` |
| GO | `earlier_in_range` | `A GO was recorded on an EARLIER head. The changes after it are NOT covered.` | `[!]` |
| GO | other | `A GO was recorded on <relation text>. It does not apply to this comparison.` | `[!]` |
| FIX | `this_head` | `Changes were requested on this head.` | `[ ]` |
| FIX | other | `Changes were requested on <relation text>.` | `[ ]` |
| HOLD | any | `A hold was recorded on <relation text>.` | `[ ]` |

A non-independent reviewer gets ` (the reviewer also built this work: not independent)`. **A history row never uses `[ok]` and never uses the word APPROVED**; the only green mark anywhere is the status states `ready` and `done`, produced by the board's placement.

### 7.6 Task, fix and review records (included at the lead's decision; round-2 finding 4)

Source: the board item's current-cycle `obligations` (`request_id, recipient, stage, state, verdict`, FACT `work_board.py:480-481`) joined to the messages of the **same generation** (7.1). **These joins feed history rows only; they never feed the status** (7.2). The join follows the reducer's own correlation rules (`work_board.py:236-261`), which allow more than one opener copy per request and replies that carry only an anchor.

**Opener selection (executable rule).** Let `copies = [m for m in messages if m.kind in work_tags.OPENERS and m.meta.request_id == request_id]` (a fan-out sends one copy per recipient with the same request id and requester). For an obligation with recipient `R`:
- candidates = the copies with `m.to == R`;
- **exactly one** candidate: it is the opener; **requester = `opener.from`**; its `ts`, `meta.work_head` and excerpt are used;
- **zero** candidates but copies exist: `no opener for this recipient in the live window`; no excerpt, no head;
- **zero** copies: `opener is not in the live window (archived)`;
- **more than one** candidate (two copies to the same recipient): **ambiguous**; the row says `N opener copies for this recipient; not shown`, no excerpt, no head. The page never picks one.

**Reply selection (the reducer's rule).** For each message `m` with `m.kind in work_tags.REPLIES` and `m.from == R`, its request is `m.meta.request_id`, **or, when that is absent, the `request_id` of the message named by `m.meta.in_reply_to`** (looked up by id in the same message list; FACT `work_board.py:259-260`). A reply belongs to the obligation when that request equals `request_id`. So an **anchor-only reply is found**, not reported as "out of window". Replies are sorted by `ts`, at most 3 per request. If a reply's anchor id names a message that is not present, it is not joined (the reducer flags it `missing required correlation history`, and that flag is shown in the missing list below). Two replies of the same recipient to one request are both shown, labelled "N replies".

**Identity, not order:** nothing is joined by timestamp or message order (FACT: the reducer refuses to, `work_board.py:3-4`).

**Row fields.** Task rows (stages `design`, `build`, `fix`): stage, requester, recipient, `ts`, opener excerpt (600 characters, inert text), obligation `state`, replies with `status` and excerpt, the opener's `work_head` when present, a transcript link. Review rows (stages in `work_tags.REVIEWS`): the same join for the obligation list, plus the history rows of 7.5 for those that reached a verdict.

**Missing and out-of-window states (each shown, never dropped):** `opener is not in the live window (archived)` (the obligation's state is still shown, so a pending review is **not** hidden; its head reads `not available`); `no opener for this recipient in the live window`; `N opener copies for this recipient; not shown`; obligation `done` with no reply found: `reply is not in the live window`; a verdict reply id from the verdict map that is not among the messages: `reply <id> was named by the board but is not in the live window`.

**The "could not be found" list (exact pairing).** `item["issues"]` is a **list of strings with no per-entry evidence ids** (FACT: `work_board.py:493-501`: `item["issues"] += sorted({reason ...})`), and `item["evidence"]` is **one** sorted list of ids for the whole item with `item["reason"]` the leading reason. So the page shows two things and does **not** pair them entry by entry: the reasons (`reason`, then each `issues` string, verbatim) and, below, "records the board points at" with the ids from `item["evidence"]` (each id marked "in the live window" or "not in the live window"). The earlier claim of per-reason ids is withdrawn.

Bounded: 20 task rows, 50 history rows, 20 obligation rows; "N of M shown". **Deferred (C6):** round playback; earlier cycles appear only as the reducer's `previous_cycles` summary lines.

### 7.7 `evidence` block (detail response)

```json
{"status": {"state": "cannot_tell", "text": "CANNOT TELL ...", "reasons": ["..."]},
 "binding": {"session": "match|mismatch", "cycle": {"registered": 1, "board": 1},
             "repository": {"alias": "fixture", "board": "fixture"}, "project": "match",
             "candidate": "match|mismatch"},
 "board": {"generated_at": "...", "coverage_status": "complete", "generation": "...",
           "board_generation": 12, "messages_generation": 12, "board_error": null, "last_known": false,
           "column": "unknown", "reason": "...", "candidate": "<oid>|null", "issues": ["..."],
           "evidence_ids": [{"id": "...", "in_window": true}],
           "integration": "true|false|absent|not_tied"},
 "history": [ {"head": "<oid>|null", "relation": "earlier_in_range", "reviewer": "seat", "vendor": "unverified",
               "independent": true, "verdict": "GO", "label": "...", "mark": "[!]", "reply_id": "...",
               "request_id": "...", "status": "approved", "ts": "...", "excerpt": "...",
               "transcript": "/api/thread/<request_id>?root=<project id>", "reply_in_window": true} ],
 "tasks": [ {"request_id": "...", "stage": "build|fix|design", "requester": "...", "recipient": "...",
             "state": "done", "ts": "...", "head": "<oid>|null", "opener_excerpt": "...", "opener_in_window": true,
             "replies": [ {"reply_id": "...", "status": "done", "ts": "...", "excerpt": "..."} ],
             "note": null, "opener_state": "one|archived|no_copy_for_recipient|ambiguous", "transcript": "..."} ],
 "obligations": [ {"request_id": "...", "recipient": "...", "stage": "read", "state": "outstanding",
                   "head": "<oid>|null", "head_note": "not available", "relation": "...", "label": "..."} ],
 "previous_cycles": [ {"cycle": 1, "outstanding": [], "note": null} ],
 "missing": {"reasons": ["missing required correlation history"], "evidence_ids": ["..."]},
 "counts": {"history": [shown, total], "tasks": [shown, total], "obligations": [shown, total]}}
```

`transcript` is the existing `/api/thread/<request_id>` path **with the same `root` the request used** (reader finding 6), or `null` when the opener or reply is not in the window. The function that builds `evidence` is **pure** (inputs: registry entry, manifest, one `compare_view` result, the session id, the project id) so it is tested without a server.

---

## 8. Rendering code safely (C4)

### 8.1 Page policy
`_DASHBOARD_CSP` (FACT `web.py:216-218`: `default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'`). No inline script or style, no `eval`, nothing remote. No third-party library, font or icon.

### 8.2 Building the DOM
- Every string from the API enters only through `createTextNode` or `textContent`. `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `DOMParser`, `createContextualFragment` and `eval` must not appear in `compare.js` or `compare-model.js` (a source-grep test; FACT: the existing console states the same rule, `web.py:92-99`).
- The only `href`s the page creates: `/compare?id=<cid>&root=<encoded project id>` (cid matches `^cmp-[0-9a-f]{12}$`) and the server-provided `transcript` path, **re-validated** against `^/api/thread/[A-Za-z0-9._-]{1,128}(\?root=[^&#\s]{1,200})?$`; a value failing it is shown as plain text. No `javascript:` or `data:` can pass.
- **Address bar:** the page reads and writes only `id` and `root` (amended from "only `id`"). Both are validated (`id` by its pattern, `root` as an opaque string of at most 200 characters without control characters) before use.
- Code lines use `white-space: pre`, `tab-size: 4`; the two columns scroll independently; line numbers are separate cells. The side-by-side first renders **400 rows**; a "Show next 400 rows" button **appends** the next 400 (no virtualisation, nothing is removed). A file is bounded by `MAX_LINES` (2,000 per side), so at most about 4,000 row nodes exist for one file; that is the stated bound, not "400 at once".

### 8.3 Inert text
Display cells are made inert **once, after the comparison decision** (5.6 step 6), and the page checks again what it receives with a pure function in `compare-model.js` using the same table (a test runs both on one list of hostile strings and compares). A line with any replacement shows `[escaped]`. **Because escaping can make different lines look the same, the page never decides "changed" from what it displays**; it uses the row kind and `same_preview` from the snapshot.

### 8.4 What the page never does
Never fetches anything except `/api/compare...`, `/api/thread/...` links the user opens, and the three static files. Never stores data in cookies or local storage. Never runs anything it received. Never calls POST.

---

## 9. The synthetic fixture and the checkpoint

### 9.1 Fixture, pinned (reader finding 13)

`tests/compare_fixture.py: build_fixture(tmp_path)` runs, with `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` pointing at the null device and `GIT_CONFIG_NOSYSTEM=1`:

```
git init --initial-branch=main --object-format=sha1
git -c core.autocrlf=false -c core.safecrlf=false -c core.eol=lf -c commit.gpgsign=false
    -c tag.gpgsign=false -c user.useConfigOnly=false commit ...
```

Fixed identity (`Fixture Author <fixture@example.invalid>`), fixed dates (`2026-10-17T10:00:00+0000` plus one minute per commit), no `.gitattributes`. **File bytes are written from Python `bytes` literals** (never through a text mode), so the object ids are reproducible on every platform; the test asserts the three commit ids equal constants recorded in the test (the first build records them; a later difference means the environment leaks into the fixture).

| Commit | Files | Why |
|---|---|---|
| **BASE** | `greet.py`, `README.md`, `data.bin` (64 bytes with a NUL), `unsafe.txt` (a U+202E and `<script>alert(1)</script>`), `crlf.txt` (2 lines `\r\n`), `big.txt` (300,000 bytes), `collide.txt` (the collision lines of 5.6) | text, binary, hostile text, CRLF, too large, collisions |
| **H1** (first build) | `greet.py` changed (the bug: `greet(None)` raises), `big.txt`, `unsafe.txt`, `collide.txt` | the reviewed first version |
| **H2** (the fix; the head on screen) | `greet.py` fixed, `tests/test_greet.py` added, `README.md`, `data.bin` changed | the fixed version |

**This checkpoint fixture contains only ordinary regular files**, so WO1 can register it (4.2 step 8). A **second fixture, `build_kinds_fixture(tmp_path)`** (work order 2), is built the same way with `git hash-object -w` and `git update-index --add --cacheinfo` (so symlinks and submodule entries need no operating-system support) and holds: a file with content changed and mode `100644 -> 100755`; a mode-only change; a symlink with a changed target; a regular file replaced by a symlink and back; a regular file replaced by a submodule entry; a credential-named file (withheld); and a missing blob (a repository whose object is removed).

Registration: `compare register --repo fixture --base BASE --head H2 --work-item demo-greeting --work-cycle 1 --label "demo greeting"` with `work_repos.fixture = {path, targets: ["refs/heads/main"], default: true}` and `main` at H2.

### 9.2 The recorded story (checkpoint fixture) and three more real-reducer fixtures

`build_story(bus, ids)` uses the `Bus` helper (`tests/test_work_board_reducer.py:25-79`) through the real publication normaliser.

**Checkpoint story `demo-greeting`** (the conflicted demonstration the lead asked for):
1. `build` task `tk-build` to `qwen-agenttalk-dev-2`, reply `done`.
2. `read` review `tk-read-1` to `codex-agenttalk-reviewer-1`, `work_head=H1`: **rejected, FIX**.
3. `fix` task `tk-fix-1`, reply `done` (this produced H2).
4. `read` review `tk-read-2` to `claude-agenttalk-reviewer-3`, `work_head=H1`: **approved, GO** (the approval of an older head).
5. `read` review `tk-read-3` to `codex-agenttalk-reviewer-1`, `work_head=H2`, **no reply**.
6. One **raw** `review-result` with an `in_reply_to` that does not exist (FACT: `add(raw=True)`, `:52-55`): the **missing link**.

Expected: status `cannot_tell` with the reducer's own reasons (`multiple candidates without supersession` is FACT at `work_board.py:453`; `missing required correlation history` is FACT at `:24`); history rows for the FIX and the GO on H1 both `earlier_in_range`, labelled as history, no green mark; the obligation row for `tk-read-3`; both task rows. If the reducer words anything differently, the golden file records the reducer's actual words; **the builder must not change the reducer to match this document**.

**Three more fixtures, each its own real-reducer story and its own golden** (reader finding 1; `tests/test_compare_evidence.py`):
- **F1 active fix after a GO:** a completed independent GO at H, then an outstanding `fix` task. Expected: status `not_ready` (column `fix_round`), text from the reducer's reason (`fix dispatched`/`running`); history still shows the GO on this head; **no `ready` and no green**.
- **F2 discharged FIX at the same head:** FIX at H, then an explicit replacement review superseding it with a GO at H. Expected: status `ready`; history shows **both** the FIX and the GO (both `this_head`), neither hidden.
- **F3 outstanding review whose opener left the live window:** an outstanding review obligation known only from archived history. Expected: status taken from the board (`waiting`, or `cannot_tell` if the board says so); the obligation row says `opener is not in the live window (archived)` and head `not available`; **the status does not become "nothing pending"**.

### 9.3 The checkpoint (C7) after work order 1

Run by the lead and the Codex reader, not by the builder alone.
1. Build the fixture, register, start the dashboard on loopback, open `/compare?id=<cid>&root=<project id>`.
2. **Reader 1** (told nothing, shown only the page) answers in writing: (a) *Is the version on the right ready?* (b) *Why, or why not?* (c) *What approval is on record, and what does it cover?* (d) *Is anything missing from the record?* **Pass:** (a) no / cannot tell; (b) names the missing record or the unresolved placement; (c) says the GO is for an earlier version and does not cover the fix; (d) says one record is missing.
3. **Reader 2** gets the editor alternative: the same two commits in the reader's own editor's diff plus a one-page index (about 20 lines, written by hand: item, commit ids, the tasks and reviews with their heads and `/api/thread` links). Same four questions.
4. **Record** per reader: elapsed minutes and correctness per question; for the builder: elapsed minutes and spend as in section 11.2.
5. **Decision:** if reader 2 answered all four correctly in no more time than reader 1, **stop**: keep the index page, close the project. Otherwise the lead decides whether to dispatch work orders 2 and 3.

### 9.4 Kill signals, and where each is guarded

| C8 signal | Guard |
|---|---|
| the screen implies approval of an unreviewed head | status only from the board's placement (7.4) after the binding checks (7.3); never "approved" wording; tests F1, F2, F3 and `test_old_head_approval_is_never_green`, `test_unknown_board_never_cannot_be_ready` |
| needs client content sent to builders | 5.8: fixture and agenttalk only; `AGENTTALK_COMPARE_FIXTURE_ONLY` test; the work-order header rule |
| repository reads cannot be bounded | 5.2 allowlist; 5.4 reader; 5.5 limits; tests `test_every_git_call_is_in_the_allowlist`, `test_runaway_child_is_killed_and_reaped`, `test_timeout_refuses_and_publishes_nothing`, `test_merge_anywhere_in_a_long_range_is_refused`; the soft temporary-disk limit is stated, not promised (5.4) |
| budget checkpoint arrives without the demonstration | the checkpoint is after work order 1; the stop-after threshold is 10 EUR with no new paid work from 8 EUR (11.2) |

---

## 10. Tests, by file and by work order

**Rule.** Every test below carries the work order that must make it pass. A test tagged **[WO1]** is required for WO1 acceptance and no other test is; a test tagged [WO2] or [WO3] is **not** required before that order. Names are the contract; the builder may add more. Mixed tests of the first draft are split so that no test needs a feature of a later order. Tests that need a real `git` are skipped with a stated reason below Git 2.32.

### 10.1 `tests/test_compare_git.py`
- **[WO1]** `test_environment_drops_every_inherited_git_variable_and_sets_the_safe_ones` (plant `GIT_DIR`, `GIT_EXTERNAL_DIFF`, lower-case `git_pager`; a wrapper `git_exe` dumps its environment)
- **[WO1]** `test_every_git_call_is_in_the_allowlist` (each forbidden subcommand or flag raises before a process starts; `Popen` is patched to fail the test if reached)
- **[WO1]** `test_unsafe_revision_text_is_refused_before_git_runs`
- **[WO1]** `test_shallow_and_partial_clones_are_refused`
- **[WO1]** `test_base_must_be_an_ancestor_of_head`
- **[WO1]** `test_merge_anywhere_in_a_long_range_is_refused` (with `MAX_COMMITS` patched small: a merge **at the head** of a range longer than the limit, and a merge **earlier than the displayed window**; both refused by call C7a)
- **[WO1]** `test_commit_list_keeps_the_newest_commits_including_the_head` (a range longer than the limit: the head is in the list, the list is newest-200 shown oldest-first, `truncated.commits` is true)
- **[WO1]** `test_cat_file_returns_raw_bytes_despite_a_hostile_gitattributes_and_config` (filter and textconv scripts that would write a marker file; bytes unchanged; marker absent)
- **[WO1]** `test_diff_tree_never_runs_an_external_diff` (marker absent)
- **[WO1]** `test_only_blobs_named_by_the_range_are_requested` (spy on the id file given to `cat-file --batch`)
- **[WO1]** `test_blob_batches_respect_the_batch_and_selected_limits` (a range of many 256 KiB blobs: no call exceeds `MAX_BLOB_BATCH_BYTES`; files past `MAX_SELECTED_BLOB_BYTES` are `not_stored` and their blobs are not requested)
- **[WO1]** `test_runaway_child_is_killed_and_reaped` (a wrapper that never stops writing to stdout, one for stderr, one that never exits; asserts: raised, child gone, staging directory deleted, within a **generous 10 second tolerance**; it asserts no precise timing or disk size; the measured numbers go to the commit message as observations)
- **[WO1]** `test_child_is_reaped_on_every_error_path` (timeout, cap, non-zero exit, an exception in the caller, a failing poll, a failing output-file read, a failing clean-up step: in each the child is killed and reaped)
- **[WO1]** `test_deadline_covers_row_building_and_publication` (a patched clock passes the deadline between files; nothing is published)
- **[WO1]** `test_windows_paths_and_spaces` (a repo path with a space; on Windows the real `NUL` is accepted for `GIT_CONFIG_GLOBAL`)

### 10.2 `tests/test_compare_snapshot.py`
- **[WO1]** `test_register_stores_ids_not_names_so_a_moved_branch_changes_nothing`
- **[WO1]** `test_same_range_same_metadata_is_a_noop_that_verifies_the_snapshot`
- **[WO1]** `test_same_range_with_different_metadata_is_an_error_not_a_noop`
- **[WO1]** `test_work_item_and_cycle_must_be_given_together`
- **[WO1]** `test_lock_refuses_a_second_writer_at_once` (hold the lock in the test with `timeout=0`; and two real processes racing)
- **[WO1]** `test_publication_refuses_without_atomic_rename_and_leaves_no_staging` (patch `os.replace` to fail permanently: exit 2, no registry change, no `.staging-*`)
- **[WO1]** `test_failure_after_the_directory_rename_reports_the_orphan_accurately` (patch the registry publication to fail: the message is either `nothing remains` or names the orphan; never "nothing was changed" while a directory exists)
- **[WO1]** `test_interrupted_publication_leaves_a_registry_naming_only_complete_snapshots` (a kill after the directory rename and before the registry; and after the first file)
- **[WO1]** `test_a_reader_polling_during_registration_never_sees_a_partial_file`
- **[WO1]** `test_limits_set_truncated_flags_and_never_crash` (limits patched small)
- **[WO1]** `test_binary_state` and `test_too_large_state` (bytes and lines)
- **[WO1]** `test_wo1_refuses_unsupported_kinds` (one case each: symlink, submodule, type change, a mode-only change, a content-plus-mode change, an unsupported mode, a missing object, a withheld file name; each exits 2 with `unsupported in this version: <kind> at <path>` and publishes nothing)
- **[WO1]** `test_text_is_made_inert_for_display_only`
- **[WO1]** `test_rows_decide_changes_from_raw_bytes` (collision cases (a) to (h) of 5.6, including the empty-file case, the final-newline-only case and `diff_at`; golden `tests/golden/compare_rows_collisions.json`)
- **[WO1]** `test_the_rows_of_the_fixture_match_the_golden_rows` (`tests/golden/compare_rows_greet.json`)
- **[WO1]** `test_registry_reader_refuses_oversize_malformed_and_foreign_schema`
- **[WO1]** `test_readers_refuse_links_at_every_component` (`compare/`, `<cid>/`, `files/`, the leaf: a symlink where the platform allows, a junction on Windows; skipped with a stated reason elsewhere)
- **[WO1]** `test_fixture_only_environment_variable_refuses_foreign_repositories`
- **[WO1]** `test_fixture_object_ids_are_reproducible` (the three constants)
- **[WO2]** `test_amend_fixes_metadata_and_keeps_the_id`
- **[WO2]** `test_remove_unlists_then_deletes_and_reports_a_failed_delete_exactly`
- **[WO2]** `test_reconcile_drops_only_absent_or_corrupt_entries_and_deletes_only_owned_names` (a hand-deleted directory; an orphan; a stale `.staging-*`; **a foreign name is left alone and reported**)
- **[WO2]** `test_reconcile_never_drops_an_entry_it_could_not_check` (an injected `PermissionError` while checking: the entry stays, the command exits 2 and says `could not check <cid>`)
- **[WO2]** `test_deletion_never_follows_links_at_any_level` (a link or junction planted as `<cid>`, as `files/` and as a file inside it, each pointing at a directory holding a sentinel file: the link is removed, the sentinel survives)
- **[WO2]** `test_readers_during_remove_reconcile_and_reregister_never_crash_or_mix` (the directory vanishes between the registry read and the file read: 404, no crash)
- **[WO2]** `test_register_deletes_an_orphan_directory_before_building`, `test_register_with_a_full_registry_after_reconcile_succeeds`
- **[WO2]** `test_registry_publication_is_directory_synced_where_supported` (the call is made on POSIX; skipped with a stated reason on Windows, where only the process-crash guarantee is claimed)
- **[WO2]** the kind tests, one each, on `build_kinds_fixture`: `test_symlink_target_change`, `test_regular_to_symlink_and_back_is_a_type_change_not_a_symlink_line`, `test_regular_to_submodule`, `test_submodule_change`, `test_unsupported_mode`, `test_missing_object_is_never_fetched`, `test_withheld_names_store_no_content`, **`test_mode_only_requires_equal_blob_ids`**, **`test_content_change_with_an_executable_bit_change_shows_content_and_mode`**, and the golden `tests/golden/compare_rows_kinds.json` for cases (i) to (n)

### 10.3 `tests/test_compare_evidence.py` (pure, no server; real-reducer stories) **[all WO1]**
- `test_status_cannot_tell_when_*` (no work item; item missing; board building; stale; last-known; incomplete; **board projection failed**; **board generation older than the messages**; column unknown; issues; candidate is another head; **session changed after a reset**; **cycle mismatch**; **repository mismatch (two repositories share H)**; **alias changed by `amend` (a registry edit in the test)**; project mismatch)
- `test_f1_active_fix_after_go_is_not_ready`, `test_f2_discharged_fix_with_replacement_go_is_ready_and_shows_both_verdicts`, `test_f3_outstanding_review_with_archived_opener_keeps_the_board_status`
- `test_old_head_approval_is_never_green` (the checkpoint story)
- `test_history_rows_never_say_approved_and_never_use_ok`
- `test_not_independent_go_is_labelled`
- `test_null_head_key_is_no_head` (feed round-tripped through `json.dumps` and `loads`), `test_a_null_head_in_a_truncated_range_is_no_head_not_unknown_relation`
- `test_relations_use_the_stored_commit_list_only` (`subprocess` patched to raise), `test_truncated_commit_list_gives_unknown_relation`
- `test_integration_true_false_absent_and_not_tied` (four separate cases; the target text comes from the declared binding)
- `test_status_is_computed_before_rows_are_limited` (more than 50 history rows)
- `test_opener_is_selected_by_request_and_recipient` (fan-out copies to two recipients with one request id: each obligation shows its own recipient's task text)
- `test_two_opener_copies_for_one_recipient_are_shown_as_ambiguous_not_guessed`
- `test_anchor_only_reply_is_joined_to_its_request` (a reply with no `request_id` and an `in_reply_to` that resolves)
- `test_two_replies_to_one_request_are_both_shown` and `test_a_reply_with_an_unresolved_anchor_is_not_joined_and_is_listed_as_missing`
- `test_task_rows_show_archived_opener_no_copy_for_recipient_and_missing_reply_states`
- `test_missing_reasons_and_evidence_ids_are_shown_as_two_lists_not_paired`
- `test_excerpt_is_cut_and_made_inert`
- `test_checkpoint_story_matches_the_golden_evidence` (`tests/golden/compare_checkpoint.json`) and one golden each for F1, F2, F3

### 10.4 `tests/test_envelope_snapshot_compare_view.py` **[all WO1]**
The five tests of 7.1, including **`test_board_only_projection_failure_is_never_ready_or_done`** (good refresh, then a board-only projection failure; real response; DOM harness).

### 10.5 `tests/test_compare_web.py` (real server in a thread) **[all WO1]**
- `test_list_detail_and_file_endpoints_return_the_documented_shape`
- `test_list_and_detail_status_agree` (with an outstanding obligation and with an archived request)
- `test_head_requests_match_get_without_a_body`
- `test_compare_paths_refuse_post_put_delete` (also when actions are enabled)
- `test_unknown_or_repeated_query_keys_are_400_bad_query`, `test_bad_root_is_400_bad_root`
- `test_two_roots_with_overlapping_request_ids_and_different_bodies` (every link carries `root`; opening them returns the right body)
- `test_cid_and_index_are_validated_before_any_disk_access`, `test_no_path_traversal_in_cid_or_index`
- `test_missing_empty_oversize_malformed_and_linked_snapshots_are_error_states_not_500s`
- `test_response_caps`
- `test_the_server_never_runs_git` (`subprocess` patched to raise during every compare request)
- `test_fifth_concurrent_read_gets_503_with_retry_after`
- `test_headers_are_the_standard_set_and_the_shell_uses_the_dashboard_csp`
- `test_static_assets_are_allowlisted_with_the_right_types`

### 10.6 JavaScript tests (same style as `tests/console2_board_model.test.mjs`, harness `tests/console2_harness.mjs`)
- **[WO1]** `tests/compare_model.test.mjs`: `escapeInert` table matches Python's; status text, labels and relation text copy the server strings; links carry `root`; the page-state machine (loading, ok, not found, error, busy text).
- **[WO1]** `tests/compare_view.test.mjs`: the states loading, list empty, ok, not found, server error, evidence unavailable and identity mismatch; the status banner for each state; the checkpoint golden payload; the collision rows show the **changed** mark and the "bytes differ" text; a minimal hostile payload (no `script` or `img` element; the only `a` elements are the two permitted kinds); the source grep for forbidden calls; **the projection test**: a saved store, then the real `/api/compare/<cid>` payload from a real test server, then the DOM harness, on the checkpoint fixture **and** on the board-only-failure state of 7.1.
- **[WO3]** the same file gains: the busy state's single automatic retry after `Retry-After`; the "snapshot incomplete" lines; the per-file state lines (binary, too large, withheld, symlink, submodule, mode only, type change, missing object); "Show next 400 rows" (appends, nothing removed); the full hostile-payload suite; keyboard order; `tests/test_compare_browser.py` (the same projection in a real browser).
- **Acceptance when no browser is installed (WO3):** the WO1 projection test, which uses a real server and the DOM harness, **stands in**, the reply states that no browser ran, and the reader decides whether to accept that. It is never reported as a browser result.

### 10.7 Existing tests kept green (every order)
`tests/test_lock_order.py:80-86` (updated in WO1); `tests/test_console2_web.py`, `tests/test_work_board_reducer.py` and `tests/test_work_board_feed.py` (unchanged); the existing envelope-snapshot suites, including `test_board_fault_preserves_active_state_and_last_known_feed` (unchanged: the extraction of 7.1 must not change them).

## 11. The work orders

Each order is for the one builder (`qwen-agenttalk-dev-2`); `codex-agenttalk-reviewer-1` reads the commit afterwards. **Standing rules for every order:** the fixture and the agenttalk repository only; no client file is opened; local branch only; run the named tests and the existing suites listed; reply with the head SHA copied from `git rev-parse HEAD`; stop and report when the order's acceptance tests pass or after 12 turns, whichever is first (ASSUMPTION: a turn cap is the only brake the builder can apply to itself; section 11.2 says who watches spend and what the threshold means).

### Work order 1: the thin end-to-end slice for ordinary files (then the checkpoint)

Scope: **snapshot plus CLI, the evidence join for one comparison, the three GET endpoints, and a minimal page**, with the status rule of 7.4, the one-lock evidence projection of 7.1, and the lossless rows of 5.6, on the synthetic checkpoint fixture. **WO1 handles ordinary regular files only** (added, modified or deleted; text, binary or too large) and **refuses every other kind** as in 4.2 step 8. **Root propagation is in WO1** (every link and API call carries `root`).

- **Not in WO1:** `amend`, `remove`, `--reconcile`; withholding by file name (a withheld-name path is **refused**); the states of symlink, submodule, type change, mode change, unsupported mode and missing object (each is **refused**); the writer and deleter containment (the reader containment **is** in WO1); the busy auto-retry, the "Show next 400 rows" button, the per-file state lines, keyboard order, the browser test and the screenshots.
- **Files (new):** `src/agenttalk/compare_git.py`, `src/agenttalk/compare_snapshot.py`, `src/agenttalk/compare_evidence.py`, `src/agenttalk/web_static/compare.css`, `compare-model.js`, `compare.js`, `tests/compare_fixture.py`, `tests/test_compare_git.py`, `tests/test_compare_snapshot.py`, `tests/test_compare_evidence.py`, `tests/test_envelope_snapshot_compare_view.py`, `tests/test_compare_web.py`, `tests/compare_model.test.mjs`, `tests/compare_view.test.mjs`, goldens under `tests/golden/`.
- **Files (edited):** `src/agenttalk/cli.py` (`compare register|list|show`, modelled on `cmd_board` at `:8611`, parser near `:16703`); `src/agenttalk/envelope_snapshot.py` (the extraction, `compare_view` and `_board_generation` of 7.1, next to `board()` at `:378`); `src/agenttalk/web.py` (docstring route list; the gate; the routes after `/api/work-board` at `:5098-5109`; `render_compare()` next to `/v2` at `:5206-5209`; the three asset names at `:810-820`); `tests/test_lock_order.py:80-86`; `docs/LOCK-ORDER.md`; `CHANGELOG.md` (an Unreleased "Added" entry in plain words).
- **Does not touch:** `work_board.py`, `work_board_feed.py`, `work_board_facts.py`, `_atomic.py`, `console2*.js`.
- **Step 1 (before any code):** read `janitor.py`, `doctor.py`, `recovery.py` and `docs/BACKUP.md` for anything that enumerates the store; report in the commit message what the snapshots do there (D3).
- **Acceptance:** every test tagged **[WO1]** in section 10 passes, and **no test tagged WO2 or WO3 is required**; `pytest tests/test_work_board_facts.py tests/test_lock_order.py tests/test_web.py tests/test_web_host_gate.py tests/test_console2_web.py tests/test_work_board_reducer.py tests/test_work_board_feed.py` and the existing envelope-snapshot suites pass unchanged; `node --test` passes the two WO1 `.mjs` files; `agenttalk compare register` on the checkpoint fixture prints the id, a second run prints the same id; the page on the checkpoint fixture shows the status banner, the file list, one side-by-side file and the rationale panel; **`grep -n "subprocess\\|Popen" src/agenttalk/compare_evidence.py src/agenttalk/web.py` prints nothing new**; the only threading code added to `web.py` is the gate of section 6.
- **Done means:** the above, plus `git diff --stat` touches only the listed files, plus the commit message lists the **observed** worst-case time of the 2,000-line row builder and the observed behaviour of the runaway-child test (observations, not guarantees, 5.4).
- **ESTIMATE:** about **1,360 lines of product code**: `compare_git.py` 240, `compare_snapshot.py` 340, `compare_evidence.py` 260, `web.py` 120, `envelope_snapshot.py` 50, CLI 70, and **the minimal subset of the page (`compare.js`, `compare-model.js`, `compare.css`) 280**; and about **1,100 lines of tests**. About 12 turns including one rework round after the read. **7 to 10 EUR of Qwen spend** (ASSUMPTION: no measured workload; this is the order most likely to reach the threshold). The **stop-after threshold, the no-new-work line at 8 EUR and the measuring rules are in 11.2**. If the lead wants WO1 thinner, the first thing to drop to WO2 is the task rows of 7.6; say so before dispatch.

### Checkpoint (after WO1's read and rework)
Section 9.3. **WO2 and WO3 are dispatched only after a GO there.**

### Work order 2: the other file kinds, the lifecycle and the deletion rules (after a GO)
- **Files:** `compare_git.py` and `compare_snapshot.py` (the states of 5.6 replace the WO1 refusals; `amend`; `remove`; `--reconcile`; withheld names; owned-names, no-follow and three-kinds-of-failure rules of 4.4; the accurate error messages and the directory sync of 4.5), `tests/compare_fixture.py` (`build_kinds_fixture`), the WO2 tests of section 10, `tests/golden/compare_rows_kinds.json`, `docs/LOCK-ORDER.md` if the lock-site count changes.
- **Acceptance:** every test tagged **[WO2]** passes; the WO1 suites stay green; `test_wo1_refuses_unsupported_kinds` is **replaced** by the kind tests (the refusal exists no longer).
- **Done means:** the above plus a manual note in `docs/COMPARE-VIEW.md` on how a full registry is reconciled and what `compare remove` leaves in backups.
- **ESTIMATE:** about 450 lines of product code and 600 of tests; 3 to 6 EUR (ASSUMPTION).

### Work order 3: the finished page, docs, screenshots (after a GO)
- **Files:** `compare.js`, `compare-model.js`, `compare.css` (the remaining states of 2.2, "Show next 400 rows", keyboard order), `tests/compare_view.test.mjs` (the WO3 additions), `tests/test_compare_browser.py`, `docs/COMPARE-VIEW.md` (an operator guide in plain words: what the page shows, how to register, how to read the status, the limits, the soft temporary-disk limit, the backup consequence, how to run the checkpoint), `CHANGELOG.md`.
- **Acceptance:** every test tagged **[WO3]** passes (the browser test, or the stated stand-in of 10.6); `pytest tests/test_console2_web.py` passes unchanged.
- **Done means:** the above plus screenshots of the list, the checkpoint detail page and one error state under `docs/images/` (small PNGs, no personal data).
- **ESTIMATE:** about 300 lines of product code (the page grows from 280 to about 580 lines) and 250 of tests; 3 to 5 EUR (ASSUMPTION).

### 11.1 Totals
- **ESTIMATE:** product code about **2,110 lines** (1,360 + 450 + 300), tests about **1,950 lines** (1,100 + 600 + 250), docs about 250 lines.
- **Spend:** the sum of the three ranges is **13 to 21 EUR** (7-10 + 3-6 + 3-5). These are guesses with no measured build workload behind them.
- **Elapsed time:** about two days including the reads and the checkpoint (ESTIMATE).
- **Cheaper alternative:** an editor diff plus a hand-written index page, one to two hours and no new code. That is reader 2's material.

### 11.2 The 10 EUR number, and how spend is measured (round-2 finding 7; lead decision)
- **The 10 EUR for WO1 and its rework round is a STOP-AFTER threshold, not a hard cap.** A turn that starts below the threshold can end above it, and the work-order cap is not enforced by the gateway. **The global gateway caps are unchanged.**
- **The rule:** the builder starts **no new paid work once 8 EUR is spent in the WO1 window** (the 2 EUR of headroom is for one more turn). At that point the lead stops the order and reports. Reaching 10 EUR after one last turn is expected and is not a breach; starting a turn at or above 8 EUR is.
- **Spend is measured by the lead, from receipts.** FACT: the gateway's child-turn receipts carry `seq`, `closed_at`, `calls`, tokens, `actual_micro_eur`, `charge_period`, `outcome` and a hashed lease reference, and **no seat name** (`ovh_gateway.py:3960-3970`). An open ledger line is a reservation ceiling, not money spent.
- **Complete pagination is required.** FACT: `agenttalk gateway receipts --json --after <seq>` returns **exactly one page**, default limit 100 (`cli.py:10305-10339`). The lead notes the highest receipt `seq` **before dispatch**, then reads **every page** (following `has_more` and the next sequence number until `has_more` is false) after the builder's reply and after each rework turn, and sums `actual_micro_eur` of the receipts after the noted `seq`. A total taken from one page only is **not** a measurement.
- **No receipts means stop.** If the receipts cannot be read (the command is refused, a page fails its checks, or pagination cannot be completed), spend is **unknown** and the order **stops** until the lead can measure it. The builder is never allowed to continue "because nothing was reported".
- **Contamination:** the sum covers every Qwen turn in the window, not only this seat's. If another Qwen seat ran, the figure is an **upper bound** for this order; the lead either keeps other Qwen seats idle during WO1 or reports an upper bound. The builder's own turn cap (12) and the commit times are a cross-check, not a measurement.
- The Codex read is another vendor's cost and is not in the Qwen figure.

## 12. Risks, and how the design answers them

| # | Risk | Answer |
|---|---|---|
| R1 | A hostile repository runs code through a diff driver, filter, hook or fsmonitor | closed allowlist; plumbing only; `--no-ext-diff --no-textconv`; `cat-file --batch` without `--filters`; fsmonitor off; global and system config ignored; a planted-marker test for each |
| R2 | The page shows a green status for a head nobody reviewed, or an old approval | status only from the board's placement after seven binding checks; history never green and never "approved"; F1, F2, F3 and the checkpoint story |
| R3 | A change breaks console v2 | no change to the reducer, the feed or `console2*.js`; `web.py` and `envelope_snapshot.py` are edited, so the v2, work-board and snapshot suites are in the acceptance list and must pass unchanged (the new assets are separate files, but shared code is not isolated by that) |
| R4 | The builder introduces a race | the only thread code is the copied 12-line gate; the Git module is single-threaded with file-based I/O; one lock for writers; strict publication order for readers |
| R5 | The snapshot hides that the repository moved on | by design: two ids and `created_at` are shown; "follow a branch" is deferred |
| R6 | Windows differences (NUL device, paths, `git.exe` lookup, CRLF, atomic rename, junctions) | section 5 notes; Windows-specific tests; **CRLF is read as bytes and kept inside the line for comparison, so a line-ending change is a visible change; the display shows a trailing CR as the visible `<U+000D>` (5.6 step 4)** |
| R7 | A partial clone or shallow checkout makes missing objects look like deletions | refused at registration; `missing_object` is its own state |
| R8 | The recorded rationale is mistaken for complete reasoning | titled "Recorded rationale", carries "what the team wrote down about this work; not a full account"; excerpts capped |
| R9 | Evidence changes after the snapshot | evidence is **not** snapshotted: it is read from the cached board on each request, from one generation; only code and commit facts are immutable |
| R10 | The store grows | 20 comparisons of at most 16 MiB; the 21st is refused; `compare remove` and `--reconcile` free room |
| R11 | Comparison snapshots end up in backups | stated in 5.8 and the operator guide; `compare remove` does not purge earlier backups |
| R12 | WO1 is large for a 10 EUR stop-after threshold | the threshold, the 8 EUR no-new-work line and the unavailable-receipts stop are explicit (11.2); WO1 is limited to ordinary regular files (4.2 step 8); the cut line is named in WO1 |
| R13 | A board-only failure makes an old board look current | `compare_view` keeps every rule of `board()`, carries the board's own generation and refuses a mismatch (7.1); a failure-path test reaches the DOM |
| R14 | A mode or type change hides a content change | classification by kind and blob id before any state (5.6); combined and type-transition tests |
| R15 | A deletion path follows a link or removes valid data after a transient error | closed owned names, no-follow deletion at every level, "unreadable" is never "absent" (4.4); WO2 fault tests |

---

## 13. Left out on purpose (C6), and what would follow
Line-pinned findings; round-by-round playback; a history backfill; syntax colouring; rename detection; intra-line highlighting; following a branch; a command to add a repository alias; a link from console v2; non-linear ranges (merge commits are refused); a content-selection policy for confidential repositories; any write action. Each can be a later slice **only if** the checkpoint shows the linkage helps.

## 14. Self-check before sending this design to the reader
- Line references read at `bdc775cb`; the reader should spot-check: `work_board.py:24`, `:240-241`, `:453`, `:459-469`, `:474`, `:480-481`, `:538-592`, `:656-662`; `envelope_snapshot.py:166`, `:289-300`, `:321-350`, `:378-400`; `web.py:216-218`, `:801-829`, `:967-978`, `:4436-4454`, `:4889-4908`, `:5098-5109`; `work_board_facts.py:133-155`, `:312-313`, `:349-350`; `_atomic.py:46-51`, `:60-81`; `recovery.py:162-173`; `ovh_gateway.py:3960-3970`; `lock_order.py:12-47`; `tests/test_lock_order.py:80-86`.
- ASSUMPTIONS the reader can settle quickly: `GIT_CONFIG_GLOBAL=NUL` on Git for Windows; `diff-tree --end-of-options` on Git 2.32; Apple Git's version; that `agenttalk gateway receipts` is usable by the lead in the way 11.2 describes; that nothing else enumerates the store directory in a way the snapshots disturb (I read `recovery.py` only; `janitor.py` and `doctor.py` are WO1 step 1).
- Round-3 facts the reader should spot-check: `envelope_snapshot.py:289-300` (the retained board on failure), `work_board.py:236-261` (anchor-based reply correlation), `work_board.py:493-501` (`issues` strings and one `evidence` list), `cli.py:10305-10339` (one receipt page, default limit 100).
- **What I did not do:** I ran no Git command and no test, and wrote no code. The command forms in 5.3 are therefore **untested** (the reader ran C9 successfully on Windows in the round-1 read); WO1 tests each one.
