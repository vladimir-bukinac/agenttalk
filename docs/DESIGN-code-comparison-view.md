# Design: a code comparison view in the dashboard ("compare")

**Status:** design only, round 2 (fix round 1 folded in). No code is written by this document.
**Base:** `origin/master` at `bdc775cb5727970b960d6ee76c785b5652c1f0dd`. Every line number below is at that commit.
**Request:** tk-97cf01713d22. **Read of round 1:** tk-f0287d325cc6 (FIX: 2 P1, 9 P2, 2 P3), folded in by tk-f5b1097b77f9.
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

**How much work is it?** About **three work orders** for the one builder: roughly **1,750 lines of product code and 1,700 lines of tests** (ESTIMATE, section 11). The first work order is a thin end-to-end slice with an early checkpoint and a **10 EUR Qwen allowance**. Builder spend for all three is guessed at **12 to 22 EUR** (ASSUMPTION: no measured build workload exists yet).

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
2. **`verdicts` is history, not status.** It holds every GO, FIX and HOLD of the current cycle under the commit each reviewer named (`:459-469`). Whether a GO still counts is decided in `_place` by many other facts: an active fix task (`:569-571`), an unresolved FIX unless discharged by a replacement chain (`:538-548`), outstanding reviews (`:578-580`), blockers (`_blockers`, `:595-640`) and policy. The column `ready` is reached only when none of those apply (`:586-589`). **Consequence (reader finding 1):** the banner is a pure function of the board's placement; the verdict map only feeds the history list. I confirm the reader's two reproductions from the code alone: an independent GO plus an outstanding fix task gives `fix_round` (`:569-571`) and a FIX discharged by a replacement review at the same head leaves a `ready` card whose map holds both verdicts (`:538-548`, `:586-589`).
3. **A verdict map key can be `None`** (a reviewer who named no commit). `json.dumps` writes a `None` key as `"null"`. The builder pins it with a test.
4. **Missing or conflicting history is a reducer outcome**, not something the page invents: `MISSING = "missing required correlation history"` (`work_board.py:24`, `:240-241`); conflicts make the item Unknown with the reason and evidence ids (`:493-501`). The reducer is total: an internal fault makes the item Unknown (`:412-421`).
5. **`repo_binding`** is `{"repo": alias, "target": ref}`, `None`, or the string `"ambiguous"` (`work_board.py:656-662`). **`integration`** maps head to a **boolean-like value** (`:428`), where `False` is a real, different answer from `True`. Integration yields the `done` column only when the value is truthy and no execution is outstanding (`:553-556`).
6. **The board feed is cached and bounded**: at most 100 cards and 256 KiB; Done items only for seven days (`work_board_feed.py`; `docs/WORK-BOARD-FEED.md`). The comparison may name an item that is not on the feed; that is a shown state.
7. **The board and the message window come from one refresh, but the existing accessors read them separately.** The worker stores `self.current` (the messages) and `self._board` inside one `with self._lock:` block (`envelope_snapshot.py`, end of the refresh function). But `board()` (`:378-397`) and `active_with_freshness()` (`:321-350`) each take the lock on their own, so a refresh can publish between two calls, and `active_with_freshness` returns age and error text, not a generation. **Consequence (reader finding 5):** a new accessor reads both under one lock (section 7.1).
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
6. **The range has no merge commit** (C8 reads each commit's `parent` lines; a commit with more than one parent refuses the registration: `range contains a merge commit; slice 1 compares linear ranges`). This settles the reader's question: merge-containing ranges are **not** supported in slice 1.
7. Capacity: at most **20** comparisons; the 21st is refused with `remove one first: agenttalk compare remove <cid>`.
8. Anything over a size limit is **registered with `truncated` flags**, never refused (section 5.5).

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

- **Same range, same metadata:** a no-op that prints the existing id (exit 0). It also **verifies the stored snapshot is complete** (manifest present, every listed file present and within its bound). If not: exit 2 `snapshot is incomplete: run compare remove <cid> and register again`. It never reports success for missing content.
- **Same range, different `--work-item`, `--work-cycle` or `--label`:** **an explicit error** (exit 2): `already registered with different metadata; use compare amend <cid>`. It is never silently ignored.
- **`compare amend`** is the one deliberately scoped metadata replacement: it rewrites only `label`, `work_item`, `work_cycle` of one registry entry, under the lock, through the publication step of 4.5. It never touches code, commits or the snapshot directory. `--clear-work-item` sets both to null.
- **`compare remove <cid>`:** under the lock, (1) publish a registry without the entry, then (2) delete the directory. A crash between the two leaves an **orphan directory** that is no longer listed anywhere readable.
- **`compare remove --reconcile`:** under the lock, (1) drop every registry entry whose directory is missing or incomplete, (2) delete every directory under `compare/` that is not named by the registry and every `.staging-*` directory. It prints what it dropped and deleted. This is how a full registry gets room back after someone deleted a directory by hand.
- **Register meets an orphan:** a directory `<cid>` exists but the registry does not list it: register (under the lock) deletes that directory and builds fresh.
- **Capacity message** names `compare remove` and `compare remove --reconcile`, not "delete the directory".

### 4.5 One strict publication step (reader finding 4)

`compare_snapshot._publish_bytes(path, data)`: write a temporary file in the same directory, `fsync` it, then `os.replace`. On Windows, retry `os.replace` up to 5 times with 100 ms pauses on `PermissionError` (a reader holding the file). **If it still fails, the registration is refused** with `cannot publish atomically on this host; nothing was changed` and the staging directory is removed. **There is no direct-write fallback** and the shared helper `_atomic.write_text` is neither used nor changed.

A registration builds everything in `.staging-<cid>-<random>/` (manifest and every file, each published by the step above), then renames the staging directory to `<cid>` (`os.rename`; refused if the destination exists), and **publishes `registry.json` last**. So a reader sees either the old registry or the new complete one, and the registry only ever names complete directories. Readers still treat a torn or missing file as an error state (defence in depth, not the guarantee).

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
| `rev-list` | `--topo-order --reverse --max-count=201 --end-of-options <oid> ^<oid>` |
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
| C7 | `rev-list --topo-order --reverse --max-count=201 --end-of-options <head> ^<base>` | at most 201 lines read; 201 lines means `truncated.commits`, keep the first 200 |
| C8 | `cat-file --batch` over the (at most 200) commit ids | parse `parent`, `author`, first message line; refuse a commit with two or more parents |
| C9 | `diff-tree -r -z --raw --no-renames --no-ext-diff --no-textconv --no-abbrev --end-of-options <base> <head>` | keep the first 500 entries in path order; more sets `truncated.files` |
| C10 | `cat-file --batch-check=%(objectname) %(objecttype) %(objectsize)` over the old and new blob ids of the kept entries | sizes without reading content |
| C11 | `cat-file --batch` over only the ids whose size is within the limit | `<oid> blob <size>\n<bytes>\n` per blob |

All output is read as **bytes**; nothing is decoded before the size checks.

### 5.4 One bounded-reader strategy (reader finding 7)

`subprocess.run(capture_output=True)` collects everything before returning, so a size check afterwards cannot bound memory or time. The Git module therefore has **one** function, `compare_git._run(argv, *, stdin_bytes, stdout_cap, stderr_cap, deadline)`, and nothing else starts a process.

- **No threads and no pipes for data.** `stdin` is a temporary file we wrote (the object-id list) and rewound; `stdout` and `stderr` are two **temporary files** in the staging directory. Nothing can fill an OS pipe, so there is no pipe deadlock and no writer thread.
- The parent uses `subprocess.Popen(argv, stdin=<file>, stdout=<file>, stderr=<file>, shell=False, env=<env>)` and a **poll loop every 20 ms**: `proc.poll()`, `os.fstat` on both output files, and the deadline. If stdout is over its cap, stderr over 64 KiB, the per-call 15 s limit passed or the registration deadline passed, it calls `proc.kill()` then `proc.wait()` and raises. `try/finally` guarantees `kill` and `wait` on every error path, and the temp files are closed and deleted.
- **Honest bound:** a child can write between two polls. The overshoot is the child's write speed times 20 ms (ESTIMATE: a few MB at most on a local disk); the module never reads more than the cap, refuses if the file is larger, and the staging directory is deleted on failure. The test shows this: a child that never stops writing is killed within about 1 second and leaves less than the cap plus 32 MiB on disk (ESTIMATE; the work order records the measured number).
- After a normal exit the module reads at most `cap + 1` bytes of each file and refuses if the extra byte exists.
- **Deadline.** `REGISTER_BUDGET_S = 180` is one `Deadline` object passed to **every phase**: each Git call (C0 to C11), the row building of each file, serialising and publishing each file, the directory rename and the registry publication. It is checked before each call, between files, and before each publication. **A single `difflib` call cannot be interrupted**; it is bounded by the line limits (section 5.5), and the builder measures and records the worst case on the 2,000-line fixture. If the deadline passed, the registration is refused and staging removed.

### 5.5 Limits and what happens at each

| Constant | Value | When exceeded |
|---|---|---|
| `MAX_COMPARISONS` | 20 | registration refused |
| `MAX_COMMITS` | 200 | list cut, `truncated.commits`; banner text "more than 200 commits" |
| `MAX_FILES` | 500 | list cut (path order), `truncated.files` |
| `MAX_BLOB_BYTES` | 262,144 per side | that file `state = "too_large"`, both sizes shown, no content |
| `MAX_LINES` | 2,000 per side | `state = "too_large"` (lines) |
| `MAX_LINE_CHARS` | 2,000 | **only the displayed cell** is cut and ends with `... (+N characters)`; the comparison uses the full line |
| `MAX_FILE_RECORD_BYTES` | 1,572,864 | the record is replaced by `state = "too_large"` |
| `MAX_SNAPSHOT_BYTES` | 16,777,216 in total | remaining files get `state = "not_stored"` (listed, counted, not shown) |
| `GIT_CALL_TIMEOUT_S` | 15 | registration refused, nothing published |
| `REGISTER_BUDGET_S` | 180 | same, all phases (5.4) |
| `GIT_OUTPUT_CAP_BYTES` | rev-list 64 KiB; diff-tree 4 MiB; commit objects 2 MiB; blobs the sum of chosen sizes plus 64 bytes per blob; stderr 64 KiB | the child is killed, registration refused |
| `EXCERPT_CHARS` | 600 | excerpt cut and ends with `...` |
| `MAX_HISTORY_ROWS` | 50 | "50 of N shown" |
| `MAX_TASK_ROWS` | 20 | "20 of N shown" |
| `MAX_OBLIGATION_ROWS` | 20 | "20 of N shown" |

### 5.6 Side-by-side rows without losing changes (reader finding 2)

**Rule: equality and change counts are decided from the raw bytes. Escaping and shortening apply only to the displayed cells.** No Git diff output is used; the builder uses `difflib.SequenceMatcher(None, a, b)` (default `autojunk`) over **raw lines**.

For one changed path:
1. **Binary?** A NUL byte in the first 8,000 bytes (Git's own rule): `state = "binary"`, sizes only.
2. **Symlink, submodule, mode only:** mode `120000` shows the link target text (a blob of at most 4 KiB) as one line; mode `160000` (a gitlink has no blob): `state = "submodule"`, both commit ids; modes differing only in the executable bit: `state = "mode_only"`.
3. **Missing object** (`cat-file --batch` answers `<oid> missing`): `state = "missing_object"`; never fetched.
4. **Raw lines.** Split each side's bytes on `b"\n"`. Each line is a pair `(line_bytes, has_eol)`: **a CR before the newline stays inside `line_bytes`** and the last line records whether the file ended with a newline. So `x` versus `x\r`, `x\n` versus `x` (no final newline) are different lines.
5. **Opcodes** from `SequenceMatcher` on those pairs.
6. **Display cells** (made after the decision): decode the line bytes as UTF-8 with replacement; replace every C0 control character except tab, DEL, and every bidirectional control (U+202A-U+202E, U+2066-U+2069, U+200E, U+200F) by the visible escape `<U+XXXX>`; cut at 2,000 characters.
7. **Row kinds:** `eq`, `chg` (a `replace` pair), `add`, `del`, `gap` ("N unchanged lines"; an `equal` run longer than 6 lines keeps 3 lines of context at each end).
8. **Every `chg` row carries why the bytes differ when the cells look the same.** If the two display cells are **equal text** (the lines differ only in bytes the preview hides), the row gets `same_preview: true` and `diff_at` (the first differing byte offset) plus `reason`: one of `line_ending` (CR present on one side only), `final_newline`, `invalid_utf8`, `escaped_or_cut` (the preview escaped or cut the difference away) or `other`. The page shows the row as **changed** with the words "bytes differ; the difference is not visible in this preview (<reason>)". Encoding differences that produce a NUL become `binary` (rule 1); other encoding differences are exactly the `invalid_utf8` and `other` reasons.
9. `stats.added` counts right lines in `add` and `chg` rows; `stats.removed` counts left lines in `del` and `chg` rows. They come from the raw decision, so the counts are non-zero whenever any byte differs.
10. A row is `{"t": "eq|chg|add|del|gap", "l": left line number or null, "r": right line number or null, "a": display cell or null, "b": display cell or null, "same_preview": bool, "diff_at": int or null, "reason": str or null}`; a gap row is `{"t": "gap", "skipped": N}`; a line with any replacement carries `"esc": true`.

**Collision cases** (golden file `tests/golden/compare_rows_collisions.json`, plus the rendered-view tests): (a) 2,000 identical characters followed by `allowed` versus `blocked`; (b) a real U+202E versus the literal text `<U+202E>`; (c) a line with byte `\xff` versus the same line with `\xfe`; (d) `x\n` versus `x\r\n`; (e) a file with and without its final newline; (f) two identical files except one byte after column 2,000. Each must give `chg`, `same_preview` where the cells match, and non-zero counts.

One file record (`files/NNNN.json`): `schema_version, index, path, status, old {oid, mode, size, lines}, new {...}, state, invalid_text, path_lossy, stats, rows, rows_truncated`. `status` is `A`, `M`, `D` or `T`. `--no-renames` means a moved file is a deletion plus an addition (ASSUMPTION: acceptable for slice 1).

### 5.7 Why a snapshot and not a live read (D1)
It keeps the standing rule; every limit lives in one place, in a command a person runs with a lock; and the endpoints can only open files under `.agenttalk/compare/<cid>/` chosen by a validated id and index, so the page cannot read outside the registered range **by construction**. The cost is that a comparison does not follow a moving branch; that is the meaning of "immutable base and head" (C2).

### 5.8 What the snapshot exposes, and the operator's part (reader finding 12)

- **The precise guarantee.** Reads are limited to the blobs of the paths **changed between the two registered commits**, on both sides. That avoids a repository-wide history browser. It does **not** make the content safe to publish: a changed or deleted credential file is among the old and new blobs, and so is any secret that was added or removed in the range.
- **The operator's responsibility.** The operator chooses which repositories and ranges to register and must only register content that may sit in the store. In this build that is the fixture and agenttalk itself (public) (C5). A **content-selection policy for confidential repositories does not exist in slice 1 and registering one is out of scope** until the lead defines one.
- **Best-effort withholding, not a promise.** A changed path whose file name matches `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `.netrc`, `credentials*` or `*.kdbx` is listed with `state = "withheld"` and **no content stored** (work order 2). This is a convenience, not a guarantee: secrets live in other names.
- **Containment of reads.** Before the server opens a stored file it checks, for `compare/`, `compare/<cid>/` and the file itself, that the entry is not a symbolic link and (Windows) not a reparse point or junction (`os.lstat`, `stat.S_ISREG`, `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`), and that the resolved path is inside `compare/`. A violation is the "snapshot unreadable" state. The cid and index regexes already exclude separators; this protects against a link planted in the directory.
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

### 7.1 One consistent evidence projection (reader finding 5)

Add **one method** to `SnapshotService` (`envelope_snapshot.py`, next to `board()` at `:378`): `compare_view(cfg)`. Under **one** `with self._lock:` it reads, from the same generation, a deep copy of the board feed, its coverage, the active messages (`self.current.active`), the invalid count, the freshness and the **generation number** (`value.generation`), and returns them together; it applies the same checks as `active_with_freshness` (config digest, building, real failure). FACT that this is safe: the worker publishes `self.current` and `self._board` inside one lock block (`envelope_snapshot.py`, end of refresh), so reading both under one lock yields one generation. About 30 lines, no behaviour change to `board()` or `active_with_freshness()`.

The handlers call `compare_view`, never `board()` and `active_with_freshness()` separately, and never scan the store. The response prints the `generation` so a test can prove the join used one generation. If `snapshots` is `None` (a server without workers), the evidence status is `board_unavailable` (FACT: the existing route has this branch, `web.py:5103-5107`). **WO1 therefore edits `envelope_snapshot.py` (one added method) and adds a test for it**; the earlier "do not touch" list is amended accordingly.

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
| 1 | `cannot_tell` | no work item linked; the board is unavailable, building, stale, `last_known` or its coverage is not `complete`; the item is not on the feed; any of B3 to B7 fails; `item.column` or `workflow_column` is `unknown`; `item.issues` is not empty | `CANNOT TELL whether this head is ready.` plus one bullet per reason: the reducer's `reason` and each `issues` entry verbatim, or one of: `no work item is linked to this comparison`, `this work item is not on the board feed`, `the board is still building`, `the board is stale or incomplete`, `registered in an earlier store session`, `registered for cycle N; the board is on cycle M`, `the work item declares repository X, not Y` (or `declares no repository`), `the board's current candidate is <12 characters>, not this head` |
| 2 | `done` | `column == "done"` **and** the integration value for this head is true **and** B5 holds | `DONE: this head is integrated in the configured target (<target from repo_binding>).` plus the reducer's reason |
| 3 | `ready` | `column == "ready"` | `READY: the board places this head as ready (<reducer reason>).` |
| 4 | `not_ready` | `column` is `fix_round`, `building` or `queued` | `NOT READY: <fix round / being built / not started> (<reducer reason>).` |
| 5 | `waiting` | `column == "independent_review"` | `WAITING for a review (<reducer reason>).` |
| 6 | `needs_operator` | `column == "needs_you"` | `NEEDS THE OPERATOR: an incident is open for this work.` |
| 7 | `cannot_tell` | any other column, or `done` without a true integration value for this head | `CANNOT TELL: the board's placement is "<column>".` |

**The page never prints "approved" in the status.** An independent GO is part of how the board reaches `ready`; the page reports the board's own word. **Integration** (reader finding 10) shows three ways: value true with B5 holding: "integrated in the configured target (<target>)"; value `False`: "checked: NOT integrated"; absent: "integration not checked"; anything with B5 failing: "integration cannot be tied to this repository". `<target>` is `repo_binding["target"]`, the declared target (FACT `:660`); if it is `None` the text says "the configured target".

### 7.5 History rows (shown as history, never as status)

Let `H` = the comparison's head, `B` = its base, `C` = the stored commit list. For a verdict filed under head `vh` (a key of `item["verdicts"]`; `"null"` means no head named):

| Relation | Rule | Text |
|---|---|---|
| `this_head` | `vh == H` | "this head" |
| `earlier_in_range` | `vh in C`, `vh != H` | "an EARLIER head in this comparison" |
| `base` | `vh == B` | "the base (before these changes)" |
| `outside_range` | a full id not in `C`, not `B`, not `H`, and `truncated.commits` is false | "a commit outside this comparison" |
| `unknown_relation` | `truncated.commits` is true and `vh` is not in `C` | "a commit we cannot place (more than 200 commits)" |
| `no_head` | `vh == "null"` | "no commit was named" |

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

### 7.6 Task, fix and review records (reader finding 8; included at the lead's decision)

Source: the board item's current-cycle `obligations` (`request_id, recipient, stage, state, verdict`, FACT `work_board.py:480-481`) joined to the messages of the **same generation** (7.1) by **identity**:
- **Task rows** (stage `design`, `build`, `fix`): the **opener** is the message whose `meta.request_id == request_id` and `kind` is a task, from the requester; the **replies** are messages with `meta.request_id == request_id`, `from == recipient`, `kind` a task response (sorted by `ts`, at most 3 per request). Row fields: stage, requester, recipient, `ts`, opener excerpt (600 characters, inert text), obligation `state`, reply `status` and excerpt, `work_head` of the opener when present, transcript link.
- **Review rows** (stages in `work_tags.REVIEWS`): the same join, for the obligation list, **plus** the history rows of 7.5 for those that reached a verdict.
- **Identity, not order:** a record is joined only by `request_id` plus the recorded sender; never by timestamp or message order (FACT: the reducer itself refuses to, `work_board.py:3-4`).
- **Missing and out-of-window states (each shown, never dropped):**
  - obligation present, opener not in the live window: `opener is not in the live window (archived)`, with no excerpt and no link; the obligation's state is still shown (so a pending review is **not** hidden when its head cannot be recovered; its head reads `not available`);
  - obligation `done` but no reply in the window: `reply is not in the live window`;
  - a verdict reply id from the verdict map that is not among the messages: `reply 20261017-... was named by the board but is not in the live window`;
  - the reducer's own missing-history entries (`item.issues` with evidence ids): listed under "records that could not be found".
- Bounded: 20 task rows, 50 history rows, 20 obligation rows; "N of M shown".
- **Deferred (C6):** round playback; the earlier cycles appear only as the reducer's own `previous_cycles` summary lines.

### 7.7 `evidence` block (detail response)

```json
{"status": {"state": "cannot_tell", "text": "CANNOT TELL ...", "reasons": ["..."]},
 "binding": {"session": "match|mismatch", "cycle": {"registered": 1, "board": 1},
             "repository": {"alias": "fixture", "board": "fixture"}, "project": "match",
             "candidate": "match|mismatch"},
 "board": {"generated_at": "...", "coverage_status": "complete", "generation": "...",
           "column": "unknown", "reason": "...", "candidate": "<oid>|null", "issues": ["..."],
           "integration": "true|false|absent|not_tied"},
 "history": [ {"head": "<oid>|null", "relation": "earlier_in_range", "reviewer": "seat", "vendor": "unverified",
               "independent": true, "verdict": "GO", "label": "...", "mark": "[!]", "reply_id": "...",
               "request_id": "...", "status": "approved", "ts": "...", "excerpt": "...",
               "transcript": "/api/thread/<request_id>?root=<project id>", "reply_in_window": true} ],
 "tasks": [ {"request_id": "...", "stage": "build|fix|design", "requester": "...", "recipient": "...",
             "state": "done", "ts": "...", "head": "<oid>|null", "opener_excerpt": "...", "opener_in_window": true,
             "replies": [ {"reply_id": "...", "status": "done", "ts": "...", "excerpt": "..."} ],
             "note": null, "transcript": "..."} ],
 "obligations": [ {"request_id": "...", "recipient": "...", "stage": "read", "state": "outstanding",
                   "head": "<oid>|null", "head_note": "not available", "relation": "...", "label": "..."} ],
 "previous_cycles": [ {"cycle": 1, "outstanding": [], "note": null} ],
 "missing": [ {"reason": "missing required correlation history", "ids": ["..."]} ],
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
- Code lines use `white-space: pre`, `tab-size: 4`; the two columns scroll independently; line numbers are separate cells. At most **400 rows** are in the DOM at once; "Show next 400 rows" adds more.

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
| repository reads cannot be bounded | 5.2 allowlist; 5.4 reader; 5.5 limits; tests `test_every_git_call_is_in_the_allowlist`, `test_runaway_child_is_killed_and_resource_use_is_bounded`, `test_timeout_refuses_and_publishes_nothing` |
| budget checkpoint arrives without the demonstration | the checkpoint is after work order 1; the allowance is 10 EUR (11.2) |

---

## 10. Tests, by file (names are the contract; the builder may add more)

**`tests/test_compare_git.py`** (real `git`; skipped with a stated reason below 2.32)
- `test_environment_drops_every_inherited_git_variable_and_sets_the_safe_ones` (plant `GIT_DIR`, `GIT_EXTERNAL_DIFF`, lower-case `git_pager`; a wrapper `git_exe` dumps its environment)
- `test_every_git_call_is_in_the_allowlist` (each forbidden subcommand or flag raises before a process starts; `Popen` is monkeypatched to fail the test if reached)
- `test_unsafe_revision_text_is_refused_before_git_runs`
- `test_shallow_and_partial_clones_are_refused`
- `test_base_must_be_an_ancestor_of_head`, `test_a_range_with_a_merge_commit_is_refused`
- `test_cat_file_returns_raw_bytes_despite_a_hostile_gitattributes_and_config` (filter and textconv scripts that would write a marker file; bytes unchanged; marker absent)
- `test_diff_tree_never_runs_an_external_diff` (marker absent)
- `test_only_blobs_named_by_the_range_are_requested` (spy on the id file given to `cat-file --batch`)
- `test_runaway_child_is_killed_and_resource_use_is_bounded` (a wrapper that never stops writing to stdout: killed within about 1 second, reaped, output file smaller than the cap plus the measured overshoot, no leftover child process; the same for stderr; the same for a child that never exits, by deadline)
- `test_child_is_reaped_on_every_error_path` (timeout, cap, non-zero exit, exception in the caller)
- `test_deadline_covers_row_building_and_publication` (a patched clock passes the deadline between files; nothing is published)
- `test_windows_paths_and_spaces` (a repo path with a space; on Windows the real `NUL` is accepted for `GIT_CONFIG_GLOBAL`)

**`tests/test_compare_snapshot.py`**
- `test_register_stores_ids_not_names_so_a_moved_branch_changes_nothing`
- `test_same_range_same_metadata_is_a_noop_that_verifies_the_snapshot`
- `test_same_range_with_different_metadata_is_an_error_not_a_noop` (and `amend` fixes it, keeping the id)
- `test_work_item_and_cycle_must_be_given_together`
- `test_lock_refuses_a_second_writer_at_once` (hold the lock in the test, `timeout=0`; two real processes racing)
- `test_publication_refuses_without_atomic_rename_and_leaves_no_staging` (patch `os.replace` to fail permanently: exit 2, no registry change, no `.staging-*`)
- `test_interrupted_publication_leaves_a_registry_naming_only_complete_snapshots` (crash after the directory rename, before the registry; and after the first file)
- `test_a_reader_polling_during_registration_never_sees_a_partial_file`
- `test_remove_and_reconcile_free_a_slot_and_delete_orphans` (hand-deleted directory; orphan directory; stale `.staging-*`; concurrent register)
- `test_register_deletes_an_orphan_directory_before_building`
- `test_limits_set_truncated_flags_and_never_crash` (limits patched small)
- `test_binary_symlink_submodule_mode_only_missing_object_withheld_states`
- `test_text_is_made_inert_for_display_only`
- `test_rows_decide_changes_from_raw_bytes` (all collision cases (a) to (f) of 5.6; counts non-zero; `same_preview` and `reason` as documented; golden `tests/golden/compare_rows_collisions.json`)
- `test_the_rows_of_the_fixture_match_the_golden_rows` (`tests/golden/compare_rows_greet.json`)
- `test_registry_reader_refuses_oversize_malformed_and_foreign_schema`
- `test_readers_refuse_symlinks_and_junctions` (symlink where the platform allows; a junction on Windows; skipped with a stated reason elsewhere)
- `test_fixture_only_environment_variable_refuses_foreign_repositories`
- `test_fixture_object_ids_are_reproducible` (the three constants)

**`tests/test_compare_evidence.py`** (pure, no server; real-reducer stories)
- `test_status_cannot_tell_when_*` (no work item; item missing; board building; stale; incomplete; column unknown; issues; candidate is another head; **session changed after a reset**; **cycle mismatch**; **repository mismatch (two repositories share H)**; **alias changed by `amend`**; project mismatch)
- `test_f1_active_fix_after_go_is_not_ready`, `test_f2_discharged_fix_with_replacement_go_is_ready_and_shows_both_verdicts`, `test_f3_outstanding_review_with_archived_opener_keeps_the_board_status`
- `test_old_head_approval_is_never_green` (the checkpoint story)
- `test_history_rows_never_say_approved_and_never_use_ok`
- `test_not_independent_go_is_labelled`
- `test_null_head_key_is_no_head` (feed round-tripped through `json.dumps`/`loads`)
- `test_relations_use_the_stored_commit_list_only` (`subprocess` patched to raise)
- `test_truncated_commit_list_gives_unknown_relation`
- `test_integration_true_false_absent_and_not_tied` (four separate cases; target text comes from the declared binding)
- `test_status_is_computed_before_rows_are_limited` (more than 50 history rows)
- `test_task_rows_join_by_request_id_and_sender_not_by_order` (two requests with overlapping ids in two roots are in `test_compare_web.py`)
- `test_task_rows_show_missing_and_out_of_window_states` (opener archived; reply archived; reply named by the board but absent)
- `test_excerpt_is_cut_and_made_inert`
- `test_checkpoint_story_matches_the_golden_evidence` (`tests/golden/compare_checkpoint.json`) and one golden each for F1, F2, F3

**`tests/test_envelope_snapshot_compare_view.py`**
- `test_compare_view_reads_board_and_messages_from_one_generation` (a controlled refresh between the old two calls changes the answer; `compare_view` still returns one generation)
- `test_compare_view_refuses_like_active_with_freshness` (building, config digest changed, real failure)

**`tests/test_compare_web.py`** (real server in a thread, the style of `tests/test_web.py`)
- `test_list_detail_and_file_endpoints_return_the_documented_shape`
- `test_list_and_detail_status_agree` (with an outstanding obligation and with an archived request)
- `test_head_requests_match_get_without_a_body`
- `test_compare_paths_refuse_post_put_delete` (also when actions are enabled)
- `test_unknown_or_repeated_query_keys_are_400_bad_query`, `test_bad_root_is_400_bad_root`
- `test_two_roots_with_overlapping_request_ids_and_different_bodies` (the transcript link and every link carry `root`; opening them returns the right body)
- `test_cid_and_index_are_validated_before_any_disk_access`
- `test_no_path_traversal_in_cid_or_index`
- `test_missing_empty_oversize_malformed_and_linked_snapshots_are_error_states_not_500s`
- `test_response_caps`
- `test_the_server_never_runs_git` (`subprocess` patched to raise during every compare request)
- `test_fifth_concurrent_read_gets_503_with_retry_after`
- `test_headers_are_the_standard_set_and_the_shell_uses_the_dashboard_csp`
- `test_static_assets_are_allowlisted_with_the_right_types`

**`tests/compare_model.test.mjs`**, **`tests/compare_view.test.mjs`** (same style as `tests/console2_board_model.test.mjs`, harness `tests/console2_harness.mjs`)
- model: `escapeInert` table matches Python's; status text, labels and relation text copy the server strings; the page-state machine; links carry `root`.
- view: each state of section 2.2; the status banner for each state; the checkpoint golden payload; the collision rows show the **changed** mark and "differs in bytes" text; "Show next 400 rows"; a hostile payload creates no element but the expected ones (no `script`, `img`, and no `a` except the two permitted kinds); the source grep for forbidden calls; keyboard order.
- error path (lesson `process/dashboard-contract-needs-real-projection-test`): a **saved store, then the real `/api/compare/<cid>` payload, then the rendered DOM**, in one test on the checkpoint fixture (a browser test if one is available; otherwise the DOM harness, and the work order says which).

**Existing tests kept green:** `tests/test_lock_order.py:80-86` (updated), `tests/test_console2_web.py` (unchanged), `tests/test_work_board_reducer.py`, `tests/test_work_board_feed.py` (unchanged), and the envelope-snapshot tests that exist today (the added method must not change them).

---

## 11. The work orders

Each order is for the one builder (`qwen-agenttalk-dev-2`); `codex-agenttalk-reviewer-1` reads the commit afterwards. **Standing rules for every order:** the fixture and the agenttalk repository only; no client file is opened; local branch only; run the named tests and the existing suites listed; reply with the head SHA copied from `git rev-parse HEAD`; stop and report when the order's acceptance tests pass or after 12 turns, whichever is first (ASSUMPTION: a turn cap is the only brake the builder can apply itself; section 11.2 says who watches spend).

### Work order 1: the thin end-to-end slice (then the checkpoint)

Scope: **snapshot plus CLI, the evidence join for one comparison, the three GET endpoints, and a minimal page** with the status rule of 7.4 and the lossless rows of 5.6, on the synthetic fixture. **Not in WO1:** `amend`, `remove`, `--reconcile`, withholding by file name, the symlink and junction checks beyond a plain regular-file check, the per-file states other than text and binary, "Show next 400 rows", the browser projection test, screenshots.

- **Files (new):** `src/agenttalk/compare_git.py` (environment, allowlist, `_run`, calls C0-C11, limits), `src/agenttalk/compare_snapshot.py` (register, list, show, row builder, readers, strict publication, the lock), `src/agenttalk/compare_evidence.py` (pure: binding checks, status, history, tasks), `src/agenttalk/web_static/compare.css`, `compare-model.js`, `compare.js` (minimal), `tests/compare_fixture.py` (repository, story, F1-F3), `tests/test_compare_git.py`, `tests/test_compare_snapshot.py`, `tests/test_compare_evidence.py`, `tests/test_envelope_snapshot_compare_view.py`, `tests/test_compare_web.py`, `tests/compare_model.test.mjs`, `tests/compare_view.test.mjs`, goldens under `tests/golden/`.
- **Files (edited):** `src/agenttalk/cli.py` (`compare register|list|show`, modelled on `cmd_board` at `:8611`, parser near `:16703`); `src/agenttalk/envelope_snapshot.py` (the one added `compare_view` method, next to `board()` at `:378`); `src/agenttalk/web.py` (docstring route list; `_COMPARE_*` constants and `_compare_slot`; the routes after `/api/work-board` at `:5098-5109`; `render_compare()` next to `/v2` at `:5206-5209`; the three asset names at `:810-820`); `tests/test_lock_order.py:80-86`; `docs/LOCK-ORDER.md`; `CHANGELOG.md` (an Unreleased "Added" entry in plain words).
- **Does not touch:** `work_board.py`, `work_board_feed.py`, `work_board_facts.py`, `_atomic.py`, `console2*.js`.
- **Step 1 (before any code):** read `janitor.py`, `doctor.py`, `recovery.py` and `docs/BACKUP.md` for anything that enumerates the store; report in the commit message what the snapshots do there (D3).
- **Acceptance:** every test named in section 10 for the files above, **except** those marked WO2 below, passes; `pytest tests/test_work_board_facts.py tests/test_lock_order.py tests/test_web.py tests/test_web_host_gate.py tests/test_console2_web.py tests/test_work_board_reducer.py tests/test_work_board_feed.py` and the existing envelope-snapshot tests still pass unchanged; `node --test` passes the two `.mjs` files; `agenttalk compare register` on the fixture prints the new id, a second run prints the same id; the page on the checkpoint fixture shows the status banner, the file list, one side-by-side file and the rationale panel; **`grep -n "subprocess\|Popen" src/agenttalk/compare_evidence.py src/agenttalk/web.py` prints nothing new**; the only threading code added to `web.py` is the gate of section 6.
  *WO2 tests (not required in WO1):* amend, remove and reconcile tests; withheld, symlink, submodule, mode-only and missing-object states; junction containment; the full list of page states beyond loading, ok, not found and error.
- **Done means:** the above, plus `git diff --stat` touches only the listed files, plus the commit message lists the measured worst-case time of the 2,000-line row builder and the measured overshoot of the runaway-child test.
- **ESTIMATE:** about 1,000 lines of product code (`compare_git.py` 220, `compare_snapshot.py` 330, `compare_evidence.py` 230, `web.py` 120, `envelope_snapshot.py` 30, CLI 70, JS and CSS 450 of which minimal) and 950 of tests (the checkpoint needs the fixtures, goldens and one real-process race); about 12 turns including one rework round after the read. **6 to 10 EUR of Qwen spend, with a hard allowance of 10 EUR for WO1 including its rework round** (ASSUMPTION: this is the order most likely to reach the allowance; if the lead wants it thinner, drop the task rows of 7.6 to WO2 and say so before dispatch).

### Checkpoint (after WO1's read and rework)
Section 9.3. **WO2 and WO3 are dispatched only after a GO there.**

### Work order 2: lifecycle and hardening (after a GO)
- **Files:** `compare_snapshot.py` (amend, remove, reconcile, withheld paths, symlink/junction containment, all per-file states), `compare_git.py` (any gap the read found), tests for the WO2 list, `docs/LOCK-ORDER.md` if the lock site count changes.
- **Acceptance:** every WO2 test of section 10 passes; the WO1 suites stay green.
- **Done means:** the above plus a manual note in `docs/COMPARE-VIEW.md` on how a full registry is reconciled.
- **ESTIMATE:** about 380 lines of product code and 500 of tests; 3 to 6 EUR (ASSUMPTION).

### Work order 3: the finished page, docs, screenshots (after a GO)
- **Files:** `compare.js`, `compare-model.js`, `compare.css` (all states of 2.2, "Show next 400 rows", keyboard order, the project selector on every link), `tests/test_compare_browser.py` (the saved-store-to-DOM test; skipped with a stated reason if no browser exists), the `.mjs` tests, `docs/COMPARE-VIEW.md` (an operator guide in plain words: what the page shows, how to register, how to read the status, the limits, the backup consequence, how to run the checkpoint), `CHANGELOG.md`.
- **Acceptance:** every `.mjs` test of section 10 passes; `pytest tests/test_console2_web.py` passes unchanged; the saved-store-to-DOM test passes on the checkpoint fixture.
- **Done means:** the above plus screenshots of the list, the checkpoint detail page and one error state under `docs/images/` (small PNGs, no personal data).
- **ESTIMATE:** about 400 lines of product code and 250 of tests; 3 to 6 EUR (ASSUMPTION).

### 11.1 Totals (corrected, reader finding 13)
- **ESTIMATE:** product code about 1,780 lines (1,000 + 380 + 400), tests about 1,700 lines (950 + 500 + 250), docs about 250 lines.
- **Spend:** the sum of the three ranges is **12 to 22 EUR** (6-10 + 3-6 + 3-6), of which WO1 has the hard allowance of 10 EUR. These are guesses with no measured build workload behind them.
- **Elapsed time:** about two days including the reads and the checkpoint (ESTIMATE).
- **Cheaper alternative:** an editor diff plus a hand-written index page, one to two hours and no new code. That is reader 2's material.

### 11.2 How spend is attributed to this seat, and what is measurable
- **FACT:** the child-turn receipts the gateway exposes (`ovh_gateway.py:3960-3970`) carry `seq`, `closed_at`, `calls`, tokens, `actual_micro_eur`, `charge_period`, `outcome` and a hashed lease reference. **They carry no seat name.** An open ledger line is a reservation ceiling, not money spent.
- **Measurable (ASSUMPTION that the lead can read receipts with `agenttalk gateway receipts --json --after <seq>`, FACT that the command exists at `cli.py:10305-10347`):** the lead notes the highest receipt `seq` **before dispatching** the order and after the builder's reply and after each rework turn, and sums `actual_micro_eur` of the receipts in between. That is the settled spend of **every** Qwen turn in the window, **not only this seat's**.
- **Contamination:** if another Qwen seat runs during the window, the figure is an **upper bound** for this order. The lead either keeps other Qwen seats idle during WO1 or reports the figure as an upper bound. The order's own per-seat attribution cannot be proven from receipts alone; it can be cross-checked by the builder's own turn count (12-turn cap) and the commit times.
- **Stop rule:** the lead reads the receipts after each builder turn; at **10 EUR** (settled sum for the window, including the rework round after the read) the lead stops and reports. The gateway cap is not changed. The Codex read is another vendor's cost and is not in this figure.

---

## 12. Risks, and how the design answers them

| # | Risk | Answer |
|---|---|---|
| R1 | A hostile repository runs code through a diff driver, filter, hook or fsmonitor | closed allowlist; plumbing only; `--no-ext-diff --no-textconv`; `cat-file --batch` without `--filters`; fsmonitor off; global and system config ignored; a planted-marker test for each |
| R2 | The page shows a green status for a head nobody reviewed, or an old approval | status only from the board's placement after seven binding checks; history never green and never "approved"; F1, F2, F3 and the checkpoint story |
| R3 | A change breaks console v2 | no change to the reducer, the feed or `console2*.js`; `web.py` and `envelope_snapshot.py` are edited, so the v2, work-board and snapshot suites are in the acceptance list and must pass unchanged (the new assets are separate files, but shared code is not isolated by that) |
| R4 | The builder introduces a race | the only thread code is the copied 12-line gate; the Git module is single-threaded with file-based I/O; one lock for writers; strict publication order for readers |
| R5 | The snapshot hides that the repository moved on | by design: two ids and `created_at` are shown; "follow a branch" is deferred |
| R6 | Windows differences (NUL device, paths, `git.exe` lookup, CRLF, atomic rename, junctions) | section 5 notes; Windows-specific tests; **CRLF is read as bytes and kept inside the line for comparison, so a line-ending change is a visible change; only the display cell shows a line without its trailing CR** |
| R7 | A partial clone or shallow checkout makes missing objects look like deletions | refused at registration; `missing_object` is its own state |
| R8 | The recorded rationale is mistaken for complete reasoning | titled "Recorded rationale", carries "what the team wrote down about this work; not a full account"; excerpts capped |
| R9 | Evidence changes after the snapshot | evidence is **not** snapshotted: it is read from the cached board on each request, from one generation; only code and commit facts are immutable |
| R10 | The store grows | 20 comparisons of at most 16 MiB; the 21st is refused; `compare remove` and `--reconcile` free room |
| R11 | Comparison snapshots end up in backups | stated in 5.8 and the operator guide; `compare remove` does not purge earlier backups |
| R12 | WO1 is large for a 10 EUR allowance | the allowance and the stop rule are explicit (11.2); the cut line is named in WO1 |

---

## 13. Left out on purpose (C6), and what would follow
Line-pinned findings; round-by-round playback; a history backfill; syntax colouring; rename detection; intra-line highlighting; following a branch; a command to add a repository alias; a link from console v2; non-linear ranges (merge commits are refused); a content-selection policy for confidential repositories; any write action. Each can be a later slice **only if** the checkpoint shows the linkage helps.

## 14. Self-check before sending this design to the reader
- Line references read at `bdc775cb`; the reader should spot-check: `work_board.py:24`, `:240-241`, `:453`, `:459-469`, `:474`, `:480-481`, `:538-592`, `:656-662`; `envelope_snapshot.py:321-350`, `:378-397`; `web.py:216-218`, `:801-829`, `:967-978`, `:4436-4454`, `:4889-4908`, `:5098-5109`; `work_board_facts.py:133-155`, `:312-313`, `:349-350`; `_atomic.py:46-51`, `:60-81`; `recovery.py:162-173`; `ovh_gateway.py:3960-3970`; `lock_order.py:12-47`; `tests/test_lock_order.py:80-86`.
- ASSUMPTIONS the reader can settle quickly: `GIT_CONFIG_GLOBAL=NUL` on Git for Windows; `diff-tree --end-of-options` on Git 2.32; Apple Git's version; that `agenttalk gateway receipts` is usable by the lead in the way 11.2 describes; that nothing else enumerates the store directory in a way the snapshots disturb (I read `recovery.py` only; `janitor.py` and `doctor.py` are WO1 step 1).
- **What I did not do:** I ran no Git command and no test, and wrote no code. The command forms in 5.3 are therefore **untested** (the reader ran C9 successfully on Windows in the round-1 read); WO1 tests each one.
