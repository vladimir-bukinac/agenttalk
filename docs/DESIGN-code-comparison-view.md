# Design: a code comparison view in the dashboard ("compare")

**Status:** design only, round 1. No code is written by this document.
**Base:** `origin/master` at `bdc775cb5727970b960d6ee76c785b5652c1f0dd`. Every line number below is at that commit.
**Request:** tk-97cf01713d22. **Binding input:** the accepted challenge (`ch-b8f7fbb4-63e7-47b4-99d5-bbbe88d70874`, RESHAPE), eight points, quoted by number as "C1" to "C8" below.
**Builder:** one Qwen seat, `qwen-agenttalk-dev-2`. **Reader:** a named Codex seat reads each slice.

**How to read the labels.** Every claim is marked **FACT** (I read it in the code or docs at the commit above, with the file and line), **ESTIMATE** (a number I reasoned out, with its assumption) or **ASSUMPTION** (something I could not check, and what changes if it is wrong). Anything unmarked is a definition, not a claim.

---

## 0. In plain words

**What the operator asked for.** A page in the dashboard that shows the original code on the left, the code the team's members made on the right, and, beside it, what the team recorded about that work: who was asked to build it, who reviewed it, what each reviewer said, and which exact version of the code each reviewer was looking at.

**What we are building first (slice 1).** One page, `/compare`, for one explicitly chosen pair of commits (a "comparison"). It shows:
- a **status banner** that says, in plain words, whether the exact version on screen is approved, not approved, waiting for a review, or cannot be told;
- the **changed files**, with counts, and a **side-by-side text view** of one file at a time;
- a panel called **"Recorded rationale"** (not "reasoning": it shows what was written down, not why anyone thought something) that lists each recorded task and review for this work, with a link to its transcript.

**The rule that matters most.** An approval belongs to one exact version of the code. If the version on screen is newer than the one a reviewer approved, the page says so in a different colour *and* different words ("approved an EARLIER version; the changes after it are NOT covered"). If the records are missing, contradictory or still being gathered, the page says **"cannot tell"** and never shows a green approval.

**What it does not do (deferred, per C6).** No comments pinned to lines, no round-by-round playback, no scanning of old history, no syntax colouring, no editing, no merging.

**How much work is it?** About **three work orders** for the one builder, roughly **1,500 lines of product code and 1,400 lines of tests** (ESTIMATE, section 10). Elapsed time is about **a day and a half** including the Codex reads between orders (ESTIMATE). Builder spend is guessed at **8 to 25 EUR** in total including rework (ASSUMPTION: there is no measured build workload yet, which is the challenge's own complaint; the first checkpoint measures it).

**The stop rule (C7).** After work order 3 we run one checkpoint on a made-up repository. A reader who is told nothing must be able to say what is approved. We also give a second reader the same facts with only an editor's diff and a short index page. **If the second reader does as well and as fast, we stop here** and keep the index page.

**One decision I need from the lead before the build (section 1).** The existing rule says the dashboard server never runs Git. The comparison needs repository text. My recommendation keeps the rule: a command run by a person (`agenttalk compare register`) reads the repository once and stores a bounded, read-only snapshot; the page only reads that snapshot.

---

## 1. Decisions needed before the build, with my recommendation

| # | Question | Recommendation (default used by the work orders) | If the lead decides otherwise |
|---|---|---|---|
| D1 | **Does the server run Git on a request?** FACT: it must not today. `docs/WORK-BOARD-FEED.md` ("Integration facts and the Done lane") says the snapshot worker "never runs Git", and records "the operator's decision of 2026-09-30" that replaced an in-server Git observer by a lead-run command. FACT: `work_board_facts.py:1-6` repeats it ("the server never runs Git"). | **No.** Registration takes the snapshot with Git; the three GET endpoints read stored files only (section 5). This satisfies C4 (limits, no helpers, no fetching, only the registered range) with the strongest form of "no subprocess on a request". | Section 5.9 lists exactly what changes if the operator grants an exception: the same functions run on a request behind a one-slot gate. That is a different security review, and I do not recommend it for slice 1. |
| D2 | **Where is "the registered repository" registered?** FACT: `work_repos` in the project config is already "an access allowlist of operator-approved local checkouts, not an item registry" (`docs/WORK-BOARD-FEED.md`, "Setup"; `work_board_facts.py:69-104`). It is edited by hand; there is no command for it. | **Reuse `work_repos` as the repository allowlist.** `compare register` refuses an alias that is not there. A second, parallel allowlist would drift. A command to add an alias is out of slice 1. | A separate allowlist adds one config key and one command (about 60 lines, one more work-order task). |
| D3 | **Where do snapshots live?** | `.agenttalk/compare/` (outside `state/`, so a store reset does not silently delete deliberate evidence). ASSUMPTION: nothing enumerates unknown directories under `.agenttalk/`. I checked `knowledge/` (FACT: `knowledge.py:39` `STORE_DIRNAME = "knowledge"`, a sibling directory that already exists), but I did not read every cleaner. The builder checks `janitor.py`, `doctor.py` and `docs/BACKUP.md` first (work order 1, step 1). | If a cleaner would touch it, move it under `state/compare/` and note that a store reset removes it. |
| D4 | **Show reply text in the rationale panel?** The reducer never reads bodies (FACT: `work_board.py:3-4`, "Bodies and subjects are never read"). The existing transcript route does carry bodies (FACT: `web.py` route list, `GET /api/thread/<rid>`, "CARRIES bodies"). | **Yes, a 600-character excerpt of each verdict reply, as inert text**, because "reasoning" is what the operator asked for and links alone make the operator leave the page. The excerpt is only read from messages already in the validated active window. | Links only: delete the `excerpt` field and one test. |
| D5 | **A link from console v2 to the new page?** | **Not in slice 1.** `/compare` is a separate page with its own assets, so a mistake cannot break `/v2` (the board model tests are exact-equality tests; see section 9, risk R3). | One header link in `console2.js`, one test. |

---

## 2. What the operator will see

### 2.1 The two pages

**`GET /compare`** is a small HTML shell (no inline script, no inline style). It loads `/static/compare.css`, `/static/compare-model.js` and `/static/compare.js`, and reads `?id=<cid>` from its own address. Without `id` it shows the list of registered comparisons; with `id` it shows one comparison.

**List page** (one row per registered comparison, newest first):

```
agenttalk / compare                                         project: agenttalk   [data as of 10:42:05Z]

  Comparisons (2)
  --------------------------------------------------------------------------------------------
  demo-greeting   fixture   9a1b2c3d4e5f..3f9c2a41d0e7   2 files   +9 -3    registered 10:31Z
     status:  CANNOT TELL (2 reasons)                                         [open]
  agenttalk-pr-500   agenttalk   5c1d...8e02..a07b...19cc   14 files   +402 -88
     status:  APPROVED (this head)                                            [open]
```

The status on the list is the same banner text as on the detail page (section 7), so the list can never look greener than the page it opens.

**Detail page** (the checkpoint screen):

```
agenttalk / compare / demo-greeting                           project: agenttalk   [data as of 10:42:05Z]

+-- STATUS ---------------------------------------------------------------------------------+
|  [X]  CANNOT TELL whether this head is approved.                                          |
|        * The board cannot place this work: multiple candidates without supersession.      |
|        * A link is missing: required correlation history (1 record).                      |
|  This head   3f9c2a41d0e7   (full 3f9c2a41...)     Base   9a1b2c3d4e5f                   |
|  2 commits  .  2 files changed  (1 modified, 1 added)  .  +9 -3                          |
|  Work item: demo-greeting   cycle 1   board column: unknown                              |
+-----------------------------------------------------------------------------------------+

+-- FILES -----------------+  +-- SIDE BY SIDE: greet.py   M   +4 -1 ------------------------+
| M  greet.py        +4 -1 |  | ORIGINAL  (base 9a1b2c3)     | CHANGED  (head 3f9c2a4)       |
| A  tests/test.py   +5    |  |  1 def greet(name):          |  1 def greet(name):           |
|                          |  |  2     return "Hello " + name|  2     if name is None:       |
|                          |  |                              |  3         return "Hello, you"|
|                          |  |                              |  4     return "Hello " + name |
+--------------------------+  +--------------------------------------------------------------+

+-- RECORDED RATIONALE   (what the team wrote down about this work; not a full account) -----+
| time       who                      stage  says     applies to                              |
| 10:05Z  reviewer-a -> lead       read   CHANGES REQUESTED   an EARLIER head (b7e1...)  [log]|
|    "greet(None) crashes; add a guard and a test." (excerpt, 600 characters max)             |
| 10:12Z  reviewer-b -> lead       read   APPROVED            an EARLIER head (b7e1...)  [log]|
|    NOT this head: the changes after b7e1... are not covered.                                |
| 10:30Z  reviewer-a  (asked, no answer yet)   read   -       THIS head (3f9c...)            |
| !  1 record could not be found: review-result 20261017-000000-000000-miss (named by a reply)|
|  each row ends with: project id . request id . reply id (select to copy)                     |
+---------------------------------------------------------------------------------------------+
```

Notes on the sketch:
- Every state uses a **word and a mark**, never colour alone. `[X]`, `[!]`, `[ok]` are real text; colour is added on top.
- "Head" always shows the first 12 characters, and the full 40 or 64 characters in a line directly under or beside it (not a tooltip).
- The left column is labelled **ORIGINAL (base ...)** and the right **CHANGED (head ...)**.
- The "who" column shows agent names as recorded. FACT: names are compared as identities and never parsed (`work_board.py:3-4`).

### 2.2 Page states the builder must render (each has a test)

| State | When | What the page shows |
|---|---|---|
| loading | request in flight | the words "Loading comparison..." |
| list empty | no comparisons registered | "No comparisons are registered. Run `agenttalk compare register --help`." |
| ok | detail loaded | everything above |
| not found | HTTP 404 | "This comparison is not registered (id ...)" with a link back to the list |
| busy | HTTP 503 | "The dashboard is busy. Retrying in N seconds" and one automatic retry after `Retry-After` seconds, then a button |
| server error | HTTP 5xx, bad JSON, network failure | "Could not load: ..." with the reason. **Never a blank page and never a stale green banner.** (Lesson `process/inventory-read-the-error-path-before-saying-already-handled`: a screen only "copes" if the failed-read path was read.) |
| evidence unavailable | the board has no such item, is still building, or is stale | the status banner is CANNOT TELL with the reason; the code view still works |
| snapshot incomplete | the stored snapshot was cut short (limits) | an explicit line per cut ("500 of 731 files shown") |
| file too large / binary / not text | per file | "Not shown: binary file (12,044 bytes)", "Not shown: larger than 262,144 bytes", and so on |

---

## 3. What I read, and what it means for the design (FACTS)

1. **The board is a pure reducer over validated envelopes** (`src/agenttalk/work_board.py:1-14`, `reduce` at `:289`). It already computes, per work item, a `verdicts` map from reviewed head to a list of `{reviewer, verdict, reply, independent, vendor}` (`:459-469`), the current candidate head (`item["candidate"]`, set in `_place`, `:532`), `issues` and `reason`/`evidence` (`:493-501`), `repo_binding` (`:473-474`), `previous_cycles` (`:484-490`) and the current-cycle `obligations` (`:480-481`). **Consequence:** the comparison page reuses this output and invents no second correlation logic (C3).
2. **A verdict is filed under the commit its reviewer named** (`_adopt_reply_head`, `:147-172`; reply heads via `_reply_head`, `:139-144`). Reviewers who name different commits become a conflict of the request (`:156-163`). A `HOLD` is kept as evidence under its own head (`:462-467`). **Consequence:** heads are already bound to verdicts; the page's job is to compare each verdict's head with the head on screen.
3. **A verdict map key can be `None`** (a reviewer who named no commit). `json.dumps` turns a `None` key into the string `"null"`. FACT by language rule, not by a test I ran; the builder pins it with a test (work order 2, test `test_null_head_key_is_no_head`).
4. **The reducer marks missing or conflicting history rather than guessing**: a reference that does not resolve is `MISSING = "missing required correlation history"` (`:24`, `:240-241`); the item then becomes Unknown with the reason and evidence ids (`:493-497`). **Consequence:** the "missing link" at the checkpoint is a real reducer outcome, not something the page invents.
5. **The reducer is total**: an internal fault makes the item Unknown rather than raising (`:289-297`, `:412-421`). **Consequence:** the page must handle `column == "unknown"` as a first-class state.
6. **The board feed is cached and bounded**: at most 100 cards and 256 KiB (`work_board_feed.py:bounded`, defaults at `:34`; `docs/WORK-BOARD-FEED.md`). It includes Done items only for seven days. **Consequence:** the comparison may name an item that is not on the feed. That is state "evidence unavailable: not on the board feed", shown explicitly.
7. **The server's contract** (`src/agenttalk/web.py:1-103`): loopback only; strict path allowlist; "Actions off by default" (GET/HEAD only unless enabled); nosniff, `X-Frame-Options: DENY`, `Cache-Control: no-store` on every response (`:4361-4366`); a Host gate on every request (`:4302-4330`); a per-route CSP, where the console routes use `_DASHBOARD_CSP` (`:216-218`: `script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self'`). HEAD is GET without a body (`do_HEAD`, `:4419-4420`; `_send`, `:4372-4388`). **Consequence:** the new GET routes copy the exact pattern of `/api/work-board` and `/api/thread/<rid>` (`:5098-5109`, `:5223-5246`).
8. **Static assets are an exact-name allowlist** (`_load_static_assets`, `web.py:801-829`; route `:5210-5221`). A new asset needs one more tuple there and a file under `web_static/`.
9. **There is already a bounded-wait gate for scans** (`_SCAN_CONCURRENCY_LIMIT = 2`, `_SCAN_WAIT_TIMEOUT_SECONDS = 3.0`, `_acquire_scan_slot` at `web.py:967-978`, `ScanBusy` answered as HTTP 503 with `Retry-After` by `do_GET` at `:4436-4454`). **Consequence:** the comparison reads reuse the same shape with their own constants.
10. **Existing hardened Git pattern** (`work_board_facts.py:133-155`, `_git`): validated arguments, no shell, drop every inherited `GIT_*` variable, set `GIT_NO_LAZY_FETCH=1`, `GIT_NO_REPLACE_OBJECTS=1`, `GIT_TERMINAL_PROMPT=0`, pass `--no-replace-objects -c core.fsmonitor=false -C <repo>`, `stdin=DEVNULL`, timeout 15 s (`PROBE_TIMEOUT_SECONDS`, `:32`; raised from 2 s after Windows CI flakes, comment at `:24-31`). Only `rev-parse`, `merge-base` and `cat-file` are allowed. **Consequence:** I reuse the pattern in a new module with a wider but still closed allowlist; I do not edit `_git`, so `verify-merges` keeps its exact behaviour.
11. **The repository allowlist and checkout checks already exist** (`repo_aliases`, `:69-104`; `_open_repo`, `:158-185`: canonical path, top of a work tree, not shallow, ref resolution). I import `repo_aliases` and re-use the checks by calling a shared copy (see section 5.2), not by loosening them.
12. **The existing lead-run command is the template for the new one** (`cmd_board`, `cli.py:8611-8640`; parser `:16703-16720`; run lock `RUN_LOCK_FILE = "work-board-verify.lock"`, `work_board_facts.py:22`, taken with `timeout=0`, `:229-233`; atomic write via `_atomic.write_text`, `:393`). Errors raised as `ValueError` reach `main()` and end as exit 2 with the message on stderr (comment at `cli.py:8622`).
13. **Lock ranks** (`lock_order.py:12-46`): an unknown lock name is a leaf lock (rank 210) that "must never call back into a store transaction" (`:46-47`); `work-board-verify.lock` is rank 205. A test pins how many lock sites each file has (`tests/test_lock_order.py:80-86`, exact-equality dict), and `docs/LOCK-ORDER.md` lists every lock. **Consequence:** registration takes one new leaf lock and the builder must update the dict and the doc in the same commit.
14. **The tests I will lean on**: `tests/test_work_board_reducer.py:25-79` has a `Bus` class that builds work-board stories through the real publication normaliser (`task`, `reply`, `rescind`; `reply(opener, status, verdict)`); `tests/test_work_board_feed.py` shows how a real `Store` is built; `tests/test_console2_web.py` pins the allowlisted assets (`:27-36`) and `tests/test_web.py` serves a real server in a thread (`web.serve_in_thread`). `REVIEW_PAIRS` is `{("approved","GO"), ("rejected","FIX"), ("rejected","HOLD"), ("needs-info","HOLD")}` (`work_tags.py:196`).
15. **Release plumbing**: static files ship as package data automatically (`pyproject.toml:108-112`: do not add `force-include`). The dev gate pins two required wheel resources, `console.css` and `console.js` (`dev_gate.py:360-361`); new assets need no change there.

**Not found (so not claimed):** no existing diff view, no code-reading route and no repository registry other than `work_repos` (searched `web.py`, `console2.js`, `work_board*.py`, `docs/`).

---

## 4. Registration: `agenttalk compare register`

### 4.1 The command

```
agenttalk compare register --repo <alias> --base <rev> --head <rev>
                           [--work-item <slug>] [--label <text>] [--json]
agenttalk compare list [--json]
agenttalk compare show <cid> [--json]      # prints the manifest, no file contents
```

(`--root <store>` and the usual store options are inherited from the main parser, as for `board verify-merges`: FACT, `cmd_board` calls `_get_store(args)`.)

- `--repo` is an alias that must exist in `work_repos` (D2) and pass `repo_aliases()` validation.
- `--base` and `--head` are any revision names a person types (a branch, a tag, a full or short commit). They are **resolved once, at registration**, to full commit ids, and **only the ids are stored**. After that the comparison is immutable (C2): moving a branch never changes it.
- `--work-item` is an optional work-item slug (`^[a-z0-9][a-z0-9-]{0,63}$`, FACT: `_SLUG` in `work_board_facts.py:35`). It names the board item whose recorded evidence is shown beside the code. Without it the page says "No work item is linked to this comparison" (state shown, not hidden).
- `--label` is up to 120 characters of plain text, shown as the title. Control characters are refused.
- `compare list` and `compare show` never run Git and never write.

`compare register` is the **only** place this feature runs Git (D1). It also writes the whole snapshot (section 5).

### 4.2 What registration checks, in order (each failure is one exit-2 message)

1. `git --version` parses and is at least **2.32** (needed for `GIT_CONFIG_GLOBAL`; ASSUMPTION: older Gits ignore it, so refuse them rather than guess). Message: `compare register: git 2.32 or newer is required (found X)`.
2. The alias exists and is valid (`repo_aliases(store.load_config())`); an invalid alias is refused with the reasons `repo_aliases` already returns.
3. The checkout is usable: canonical path, top of a work tree, **not shallow**, and **not a partial clone** (section 5.4 command `C3`). A partial clone could fetch missing objects, which C4 forbids.
4. `--base` and `--head` resolve to **commits** (`C4`, then `C5`: object type must be `commit`).
5. **`--base` is an ancestor of `--head`** (`C6`), so "the original" really is the starting point of the changes. Otherwise: `base is not an ancestor of head; register a pair on one line of history`. (ASSUMPTION: slice 1 needs only linear ranges; criss-cross comparisons are deferred.)
6. The range is not too big (section 5.3 limits). A range over the limit is **registered with `truncated` flags**, never refused, so the operator sees what was cut.
7. Registry capacity: at most **20** comparisons; the 21st is refused with `remove one first` (a `compare remove <cid>` command is out of slice 1; the operator deletes the directory; the message prints the path).

### 4.3 Stored format (schema version 1)

Directory: `<store>/.agenttalk/compare/` (D3).

```
.agenttalk/compare/
  registry.json              <= 64 KiB   the index
  <cid>/manifest.json        <= 256 KiB  facts about the range
  <cid>/files/0001.json ...  <= 1.5 MiB each, at most 500 files; one record per changed file
```

`cid` = `"cmp-" + first 12 hex digits of sha256("<project_id>|<alias>|<base_oid>|<head_oid>")`. Registering the same range again is a no-op that prints the existing id (exit 0); it never rewrites the snapshot (immutable).

`registry.json`:

```json
{
  "schema_version": 1,
  "comparisons": [
    {"id": "cmp-3f9c2a41d0e7", "label": "demo greeting", "repo_alias": "fixture",
     "base": "9a1b2c...(40 or 64 hex)", "head": "3f9c2a...", "work_item": "demo-greeting",
     "created_at": "2026-10-17T10:31:00+00:00", "project": "<project id>",
     "counts": {"files": 2, "added": 1, "modified": 1, "deleted": 0, "binary": 0, "not_shown": 0,
                "lines_added": 9, "lines_removed": 3, "commits": 2},
     "truncated": {"files": false, "commits": false}}
  ]
}
```

`manifest.json` adds: `git_version`, `repo_path` (the canonical path, display only, never used to read), the **commit list** (up to 200 commits, oldest first: `{oid, parent_count, author_name, author_date, subject}`; names and subjects as text, subject cut at 200 characters), the **file list** (up to 500: `{index, path, status, old_mode, new_mode, old_oid, new_oid, state, lines_added, lines_removed}`), `limits` (every limit value used, so a later change of limits cannot silently reinterpret an old snapshot) and `built_at`.

Every reader of these files uses a **bounded read** (read at most limit+1 bytes, refuse if over), checks `schema_version == 1`, validates every field's type and shape, and on any doubt answers "snapshot unreadable" (an error state, never a partial render). FACT: this is exactly how `work_board_facts._read` and `_valid_fact` behave (`:293-326`).

Writes are atomic (`agenttalk._atomic.write_text`, FACT: imported at `work_board_facts.py:15`), files first and `registry.json` last, so a crash leaves a registry that names only complete snapshots (an orphan directory is harmless and is reported by `compare list`).

### 4.4 Concurrency of registration (the one place with a lock)

One lock for the whole command: `store._exclusive_lock(store.dir / "compare-register.lock", timeout=0, what="compare register lock")`. A second run is refused at once: `compare register: another run is in progress` (exit 2). FACT pattern: `work_board_facts.py:229-233`. The lock is taken **before** any Git call and released after `registry.json` is written. It is a leaf lock (rank 210, FACT `lock_order.py:46-47`); nothing inside it may call a store transaction. The builder updates `tests/test_lock_order.py:80-86` (`"compare_snapshot.py": 1`) and the table in `docs/LOCK-ORDER.md`.

---

## 5. Reading the repository (registration time only)

### 5.1 Principles (C4)

- Plumbing commands only: `rev-parse`, `cat-file`, `merge-base`, `rev-list`, `diff-tree`, `config`. **Never** `diff`, `show`, `log`, `status`, `archive`, `grep`, `blame`, `fetch`, `pull`, `checkout`, or anything that can run a diff driver, a text-conversion filter, a hook, an editor or a pager.
- Only **file contents named by the registered range** are ever read: the old and new blob ids that `diff-tree` lists for `base..head`. A blob id that is not in that list is never requested. This is how "registration must not expose every historical secret" is met: the readable set is exactly the blobs of the changed paths on both sides, not the repository.
- **No object is fetched.** Partial clones and shallow checkouts are refused; `GIT_NO_LAZY_FETCH=1` is set as a second layer.
- **Counts are exact or marked.** Anything cut by a limit sets a `truncated` flag that the page shows.

### 5.2 The exact process environment and argument prefix

**Environment** (start from the current environment, then **remove every key that starts with `GIT_`**, case-insensitively, then set):

| Variable | Value | Why |
|---|---|---|
| `GIT_NO_LAZY_FETCH` | `1` | never fetch missing objects (FACT: already used, `work_board_facts.py:149`; ASSUMPTION: honoured from Git 2.44, so partial clones are refused separately in `C3`) |
| `GIT_NO_REPLACE_OBJECTS` | `1` | a replace ref cannot swap an object |
| `GIT_TERMINAL_PROMPT` | `0` | no credential prompt |
| `GIT_OPTIONAL_LOCKS` | `0` | reads never write the index or refs |
| `GIT_CONFIG_NOSYSTEM` | `1` | ignore the system config (`/etc/gitconfig`, Git for Windows' own) |
| `GIT_CONFIG_GLOBAL` | `os.devnull` (`NUL` on Windows, `/dev/null` elsewhere) | ignore the user's `~/.gitconfig` (diff drivers, aliases, `core.pager`); Git 2.32+. ASSUMPTION: Git for Windows accepts `NUL` here; the work order tests it on Windows |
| `GIT_ATTR_NOSYSTEM` | `1` | ignore system attributes |
| `LC_ALL` | `C` | stable, untranslated messages |

**Argument prefix for every call** (a Python list, never a shell string; `shell=False`; `stdin` is `DEVNULL` unless the call feeds a list on stdin):

```
[git_exe, "--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "protocol.allow=never",
 "-c", "diff.external=", "-c", "core.attributesFile=<os.devnull>", "-C", "<canonical repo path>", <subcommand>, ...]
```

`git_exe` is `shutil.which("git")` resolved **once** per run and refused if it is relative or missing. FACT: the existing probe uses the bare name `"git"` (`GIT = ("git",)`, `work_board_facts.py:33`); resolving once is a small hardening for the new module and does not change the old one.

**Closed allowlist (a dict in code, checked before every call):**

| Subcommand | Allowed argument patterns (everything else raises `ValueError("git call not allowed")` before a process starts) |
|---|---|
| `rev-parse` | `--show-toplevel`; `--is-shallow-repository`; `--verify --quiet --end-of-options <oid-or-rev>^{commit}` |
| `config` | `--local --get-regexp <the one fixed pattern in C3>` |
| `cat-file` | `-t <oid>`; `--batch-check=<fixed format>` (oids on stdin); `--batch` (oids on stdin) |
| `merge-base` | `--is-ancestor <oid> <oid>` |
| `rev-list` | `--topo-order --reverse --max-count=201 --end-of-options <oid> ^<oid>` |
| `diff-tree` | `-r -z --raw --no-renames --no-ext-diff --no-textconv --no-abbrev --end-of-options <oid> <oid>` |

Every `<oid>` argument must match `^[0-9a-f]{40}$|^[0-9a-f]{64}$` exactly. The only free-text revisions (`--base`, `--head` as typed) go through one call, `C4`, with `--end-of-options`, after a character check (`^[A-Za-z0-9._/@^~-]{1,200}$`, and not starting with `-`).

### 5.3 The calls, in order

| Id | argv after the prefix | Reads | Success / failure |
|---|---|---|---|
| C0 | (not a git call) `git --version` is run as `[git_exe, "--version"]` | the version text | parsed `major.minor`; below 2.32 refuse |
| C1 | `rev-parse --show-toplevel` | the work tree top | must equal the alias path after `os.path.normcase(os.path.normpath(...))` (FACT: `_open_repo`, `:158-185`) |
| C2 | `rev-parse --is-shallow-repository` | `true` / `false` | must print `false` |
| C3 | `config --local --get-regexp ^(extensions\.partialclone|remote\..*\.(promisor|partialclonefilter))$` | repo-local keys | exit 1 (no match) is success; any match refuses: `partial clone: objects may be fetched` |
| C4 | `rev-parse --verify --quiet --end-of-options <rev>^{commit}` (once for base, once for head) | a full oid | prints exactly one oid, else `cannot resolve <rev> to a commit` |
| C5 | `cat-file -t <oid>` | `commit` | must print `commit` (a second check; refuses a tag object that peeled oddly) |
| C6 | `merge-base --is-ancestor <base> <head>` | exit code | 0 yes, 1 no (refuse), other = error (refuse) |
| C7 | `rev-list --topo-order --reverse --max-count=201 --end-of-options <head> ^<base>` | oids, one per line | at most 201 lines read (output capped at 64 KiB); 201 lines means `truncated.commits = true`, keep the first 200 |
| C8 | `cat-file --batch` with the (at most 200) commit oids on stdin | the raw commit objects | parse header lines `author`, `committer`, the first line of the message; total output capped at 2 MiB |
| C9 | `diff-tree -r -z --raw --no-renames --no-ext-diff --no-textconv --no-abbrev --end-of-options <base> <head>` | `:<old mode> <new mode> <old oid> <new oid> <status>\0<path>\0 ...` | output capped at 4 MiB (the process is killed if it would exceed it); keep the first 500 entries in path order; `truncated.files = true` if more |
| C10 | `cat-file --batch-check=%(objectname) %(objecttype) %(objectsize)` with the old and new blob oids of the kept entries on stdin | one line per oid | gives each side's size without reading content |
| C11 | `cat-file --batch` with only the oids whose size is within the limit (section 5.5), on stdin | `<oid> blob <size>\n<bytes>\n` per blob | total output capped at the sum of the chosen sizes plus 64 bytes per blob |

**Notes the builder must follow:**
- All process output is read as **bytes** (`text=False`). Nothing is decoded until after the size checks.
- **Timeouts:** each call has a **15 s** timeout (FACT: the existing constant, raised after Windows flakes, `work_board_facts.py:24-32`; use the same value, not a smaller one) and the whole `register` run has a **180 s** budget checked between calls. A timeout kills the child (`subprocess.run(timeout=...)` does this) and refuses the registration with `git timed out (call C#)`; nothing is written.
- A **non-zero exit** from any call other than the expected `C3` exit 1 and `C6` exit 1 refuses the registration with the call id and the first 200 bytes of stderr, decoded with `errors="replace"` and stripped of control characters.
- `cat-file --batch` and `--batch-check` are fed by `subprocess.run(..., input=<bytes>)` (not by a writer thread). This keeps the builder out of pipe-deadlock territory: there is **no threading anywhere in the Git module**. If the stdin list is large (at most 1,000 oids x 41 bytes = 41 KB) it still fits in one `input=` call.
- **Windows, Linux, macOS.** Arguments are lists, so no quoting differs. Paths: the canonical path from the alias is passed to `-C` as a string. On Windows `os.devnull` is `NUL`; the path in `core.attributesFile=<os.devnull>` is built with an f-string, not a shell. Git prints paths with `/`; the paths in `-z` output are bytes, decoded with UTF-8 `errors="replace"`, and the stored `path` is the decoded text plus a flag `path_lossy` if any replacement happened. Line endings are never translated (bytes in, bytes out). macOS: Apple's Git may be older than 2.44; the version gate (C0) and C3 cover that. ASSUMPTION: Apple Git 2.39 or newer is what the operator has; the work order records the version it was tested on in the snapshot's `git_version`.
- `GIT_NO_LAZY_FETCH` and `GIT_CONFIG_GLOBAL` are environment variables, so a Git that does not know them ignores them silently; that is why C0 and C3 exist and are not optional.

### 5.4 What `cat-file --batch` does and does not do (so the builder does not add flags)

FACT (Git documentation, not re-verified here; the builder's test below proves it for the installed Git): `cat-file --batch` prints the **raw object content**. It applies no filters, no line-ending conversion and no text conversion unless `--filters` or `--textconv` is given, and the allowlist never allows those two flags. `diff-tree --raw` prints modes and ids only; `--no-ext-diff` and `--no-textconv` are present as a second layer. Test `test_cat_file_returns_raw_bytes_despite_a_hostile_gitattributes_and_config` (work order 1) builds a repo whose `.gitattributes` says `* filter=evil diff=evil text eol=crlf` and whose local config defines an `evil` filter and textconv that would write a marker file; the test asserts the bytes are unchanged and **the marker file does not exist**.

### 5.5 Limits and what happens at each (every number is a constant in `compare_git.py`)

| Constant | Value | When exceeded |
|---|---|---|
| `MAX_COMPARISONS` | 20 | registration refused |
| `MAX_COMMITS` | 200 | list cut, `truncated.commits = true`, banner line "first 200 of N commits" (N unknown: shown as "more than 200") |
| `MAX_FILES` | 500 | list cut (path order), `truncated.files = true`; the exact total is unknown, shown as "more than 500" |
| `MAX_BLOB_BYTES` | 262,144 (256 KiB) per side | that file's `state = "too_large"`, both sizes shown, no content stored |
| `MAX_LINES` | 2,000 per side | `state = "too_large"` (lines), no diff computed |
| `MAX_LINE_CHARS` | 2,000 | the line is cut and ends with `... (+N characters)` |
| `MAX_FILE_RECORD_BYTES` | 1,572,864 (1.5 MiB) | the record is replaced by `state = "too_large"` |
| `MAX_SNAPSHOT_BYTES` | 16,777,216 (16 MiB) in total | remaining files get `state = "not_stored"` (counted, listed, not shown) |
| `GIT_CALL_TIMEOUT_S` | 15 | registration refused, nothing written |
| `REGISTER_BUDGET_S` | 180 | same |
| `GIT_OUTPUT_CAP_BYTES` | rev-list 64 KiB, diff-tree 4 MiB, cat-file --batch as in C8/C11 | the child is killed, registration refused |
| `EXCERPT_CHARS` | 600 | the excerpt is cut and ends with `...` |
| `MAX_VERDICT_ROWS` | 50 | list cut, "50 of N shown" |
| `MAX_OUTSTANDING_ROWS` | 20 | list cut, "20 of N shown" |

### 5.6 Turning two blobs into side-by-side rows

No Git diff output is used. The builder uses Python's `difflib.SequenceMatcher(None, left_lines, right_lines)` with default settings (default `autojunk=True`: deterministic, and bounded in practice by `MAX_LINES`; ESTIMATE: well under a second for 2,000 x 2,000 lines of ordinary code; the work order measures the worst case on the 2,000-line fixture and records it).

Steps for one changed path (all text work is on already-decoded strings):
1. **Binary?** A blob with a NUL byte in its first 8,000 bytes is binary (Git's own rule). `state = "binary"`, sizes shown, no content.
2. **Symlink or submodule?** Mode `120000`: show the link target text (a blob of at most 4 KiB) as a one-line text; mode `160000`: a gitlink has no blob; `state = "submodule"`, show the two commit ids. Mode `100755` vs `100644` only: `state = "mode_only"`.
3. **Missing object?** If `cat-file --batch` answers `<oid> missing`, `state = "missing_object"` (never fetched).
4. **Decode** each side as UTF-8 with `errors="replace"`; `invalid_text = true` if any replacement happened. Split on `"\n"` only (not `str.splitlines`, which also splits on form feeds and line separators). If a line ends in `"\r"`, drop it and record `crlf = true` for that side.
5. **Make the text inert** (section 8.3): replace every C0 control character except tab, the DEL character, and every Unicode bidirectional control character (U+202A to U+202E, U+2066 to U+2069, U+200E, U+200F) by a visible escape such as `<U+202E>`. Tabs stay.
6. **Cut long lines** to `MAX_LINE_CHARS`.
7. **Rows.** From `get_opcodes()`: `equal` runs longer than 6 lines keep 3 lines of context at each end and one `gap` row ("N unchanged lines") between; `replace` pairs left and right lines in order and leaves the surplus as `add` or `del`; `insert` -> `add`; `delete` -> `del`. A row is `{"t": "eq|chg|add|del|gap", "l": left line number or null, "r": right line number or null, "a": left text or null, "b": right text or null}`; a gap row is `{"t": "gap", "skipped": N}`.
8. `stats = {"added": count of right lines in add/chg rows, "removed": count of left lines in del/chg rows}`.

One file record (`files/NNNN.json`):

```json
{"schema_version": 1, "index": 1, "path": "greet.py", "status": "M",
 "old": {"oid": "...", "mode": "100644", "size": 97, "lines": 5, "crlf": false},
 "new": {"oid": "...", "mode": "100644", "size": 211, "lines": 9, "crlf": false},
 "state": "text", "invalid_text": false, "path_lossy": false,
 "stats": {"added": 4, "removed": 1}, "rows": [ {"t": "eq", "l": 1, "r": 1, "a": "def greet(name):", "b": "def greet(name):"} ],
 "rows_truncated": false}
```

`status` is one of `A`, `M`, `D`, `T` (type change). `--no-renames` means a moved file is a deletion plus an addition (ASSUMPTION: acceptable for slice 1; rename detection invokes a similarity engine whose cost is not bounded by our limits).

### 5.7 Why a snapshot and not a live read (D1)

- It keeps the standing rule: **the server never runs Git** (FACT, `WORK-BOARD-FEED.md`, `web.py` module docstring route list has no Git).
- Every limit in C4 is enforced in one place, once, by a command a person runs, with a lock, instead of on every request by a handler thread. This removes the one thing the builder is weak at (concurrency) from the part of the system that has concurrency.
- The page cannot read outside the registered range **by construction**: the three GET endpoints open only files under `.agenttalk/compare/<cid>/`, chosen by a validated id and a validated index.
- The cost is that a comparison does not follow a moving branch. That is the intended meaning of "immutable base/head commits" (C2).

### 5.8 Where the confidentiality boundary sits (C4, C5)

- The snapshot holds **file text of the changed paths** (and commit subjects and author names) inside the store. For slice 1 the repository is the synthetic fixture or agenttalk itself, which is public.
- A repository that holds client code is **never registered** during this build (C5). The builder's instructions say so in the work order header, and a test (section 9) asserts that `compare register` refuses an alias whose canonical path is not under the test's own temporary directory or the agenttalk checkout when the environment variable `AGENTTALK_COMPARE_FIXTURE_ONLY=1` is set (the builder's seat environment sets it). ASSUMPTION: the lead can set that variable for the builder's seat; if not, the work order's written rule is the control.
- Nothing in this feature sends any content anywhere: the page loads only local assets (CSP, section 8.1), and the builder's model sees only the fixture and the agenttalk source it is editing.

### 5.9 If the lead grants a server-side Git read (not recommended): the delta

The same `compare_git` functions are called from a request handler. Required changes: a module-level `threading.BoundedSemaphore(1)` per store root with `acquire(timeout=3.0)` and the exact `ScanBusy` mapping to 503 (FACT pattern: `web.py:967-978`, `:4436-4454`); a per-request budget of 15 s; the object-level allowlist (only blob ids named by `diff-tree`, which the handler would have to recompute on each request or cache); and a security review of every handler thread that can hold a child process. The operator's decision of 2026-09-30 would need to be re-opened first.

---

## 6. The GET endpoints (all new, all GET and HEAD only)

**General rules (FACT patterns, `web.py:4286-4454` and `:5076-5246`).**
- Dispatch in `_route`, after the Host gate, the peer gate and the method gate that already exist. POST, PUT, DELETE and PATCH on these paths behave exactly as on every other path (405 or the existing action-gated path); the builder adds **no** `do_POST` branch (test `test_compare_paths_refuse_post_put_delete`).
- Root selection: the same `_root_selection(self._request_params())` as `/api/work-board` (`:5098-5101`); an unknown root is `400 bad_root` through `_bad_root()`.
- **Query strings are closed:** only `root` is accepted (once, non-empty). Any other key, or a repeated key, is `400 {"error": "bad_query", ...}`. (Defence in depth: nothing from a query string ever reaches a path.)
- Responses use `_send_json` (so `nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`, the default no-script CSP: FACT `:4372-4388`). The HTML shell uses `_DASHBOARD_CSP` like `/v2` (`:5206-5209`).
- Response size caps are **checked after serialising**: if a body would exceed its cap the handler answers `500 {"error": "response_too_large"}` instead (it can only happen if a stored file violates its own limits; the snapshot reader should already have refused it).
- **Concurrency gate** (the only threading code in the whole feature, copy it exactly):

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

  (One gate for the whole process, not per store: the gate protects handler threads, not data. `ScanBusy` and `_acquire_scan_slot` are FACT at `web.py:947-978`.) Each handler wraps its whole body in `with _compare_slot():`.

### 6.1 `GET /compare` (HTML) and `GET /static/compare.css`, `/static/compare-model.js`, `/static/compare.js`

HTML shell generated by a function `render_compare()` modelled on `render_console2()` (`web.py:723`), `csp=_DASHBOARD_CSP`. It carries no comparison data. The three assets are added to the exact-name allowlist in `_load_static_assets` (`web.py:810-820`) with the content types of their neighbours. Errors: none beyond the existing 404 for an unknown asset name.

### 6.2 `GET /api/compare` (list)

- **Inputs:** `root` (optional).
- **Output (200):** `{"schema_version": 1, "target_root_project_id": "<project id>", "comparisons": [<registry entries, newest first, each with "banner": {"state", "text"}>], "errors": []}`.
  The banner for the list row is computed with the same function as the detail page (section 7) from the cached board feed; if the evidence cannot be read the banner is `unknown` with the reason. The list reads **only** `registry.json` (<= 64 KiB) plus the cached board feed.
- **Cap:** 64 KiB. **Limits:** 20 comparisons.
- **Errors:** `400 bad_root` / `bad_query`; `200` with `"comparisons": []` and `"errors": ["no comparisons are registered"]` when the directory or file does not exist (an empty registry is normal, not an error); `200` with `"errors": ["registry unreadable: <reason>"]` and an empty list when the file is over its bound, malformed or of another schema (never a 500: the page shows the reason); `503 busy`.

### 6.3 `GET /api/compare/<cid>` (detail)

- **Inputs:** `<cid>` must match `^cmp-[0-9a-f]{12}$` **before any disk access** (FACT pattern: `_MESSAGE_ID_RE` check at `web.py:5228-5231`); `root` optional.
- **Output (200):**

```json
{"schema_version": 1, "id": "cmp-...", "label": "...", "repo_alias": "fixture",
 "base": "<oid>", "head": "<oid>", "work_item": "demo-greeting|null",
 "created_at": "...", "counts": {...}, "truncated": {"files": false, "commits": false},
 "commits": [ {"oid": "...", "author_name": "...", "author_date": "...", "subject": "..."} ],
 "files": [ {"index": 1, "path": "greet.py", "status": "M", "state": "text",
             "lines_added": 4, "lines_removed": 1, "old_size": 97, "new_size": 211} ],
 "evidence": { ...section 7.4... },
 "project": {"project_id": "...", "label": "...", "path": "..."}}
```
  `project` is `_root_info(root)` (FACT `web.py:345-350`). Commit author names and subjects are text.
- **Cap:** 512 KiB. **Limits:** 200 commits, 500 files, 50 verdict rows, 20 outstanding rows.
- **Errors:** `400 bad_root` / `bad_query`; `404 {"error": "comparison not found"}` for an id not in the registry **or** whose directory is missing; `200` with `"snapshot": {"status": "unreadable", "reason": "..."}` and empty `commits`/`files` when a stored file is over its bound or invalid (the evidence block is still computed); `503 busy`.

### 6.4 `GET /api/compare/<cid>/file/<n>` (one side-by-side file)

- **Inputs:** `<cid>` as above; `<n>` must match `^[1-9][0-9]{0,3}$` and be at most the manifest's file count; `root` optional.
- **Output (200):** the file record from section 5.6, exactly as stored, plus `"id"` and `"n"`.
- **Cap:** 2 MiB. **Limit:** the stored record is <= 1.5 MiB.
- **Errors:** `400 bad_root` / `bad_query`; `404 comparison not found` / `404 file not found`; `200` with `"state": "unreadable"` and `"reason"` when the stored record is invalid; `503 busy`.

### 6.5 What every handler must do before returning

1. Validate path pieces (ids, index) by regex **first**. 2. Select the root. 3. Take the gate. 4. Open files only by joining `store.dir / "compare" / <validated cid> / ...` (no `..`, no separators can survive the regexes; test `test_no_path_traversal_in_cid_or_index`). 5. Read with the byte bound. 6. Validate shape. 7. Build the response. 8. Check the cap. 9. Send.

---

## 7. Binding verdicts to heads (C3)

### 7.1 Where the evidence comes from (reuse, no new correlation)

For a comparison with `work_item = S`:
1. **The reduced board item.** From the same cached feed `/api/work-board` serves: `service = (snapshots or {}).get(str(root.store.root.resolve()))`, then `service.board()` (FACT: `web.py:5102-5108`; `board()` is `envelope_snapshot.py:378`, "No source reads/rebuilds"). Find the item with `work_item == S` in `payload["items"]`. The feed also carries `coverage` (status, generated_at) and `errors`.
2. **The messages of the active window**, to map a verdict's reply id to its request, opener and excerpt: `msgs, invalid, freshness = snapshots[...].active_with_freshness(cfg)` (FACT: the same call `/api/state` uses, `web.py:1858`; `envelope_snapshot.py:321`). Build one dict `by_id = {m.id: m for m in msgs}` per request (bounded by the envelope limit; ESTIMATE: milliseconds).
3. **Never** run `_all_messages` or a store scan from these handlers (that would take the scan semaphore and the disk).

If `snapshots` is `None` (a server built without workers, as some tests do), `service` is `None` and the evidence status is `board_unavailable` (FACT: the existing route already has this branch, `web.py:5103-5107`).

### 7.2 The relation of a verdict's head to the head on screen

Let `H` = the comparison's head, `B` = its base, `C` = the stored commit list (oids). For a verdict filed under head `vh` (the key of `item["verdicts"]`; the string `"null"` means no head was named, see section 3 item 3):

| Relation | Rule | Plain text |
|---|---|---|
| `this_head` | `vh == H` | "THIS head" |
| `earlier_in_range` | `vh in C` and `vh != H` | "an EARLIER head in this comparison" |
| `base` | `vh == B` | "the base (before these changes)" |
| `outside_range` | `vh` is a full oid, not in `C`, not `B`, not `H`, and `truncated.commits` is false | "a commit outside this comparison" |
| `unknown_relation` | `truncated.commits` is true and `vh` is not in `C` | "a commit we cannot place (the comparison has more than 200 commits)" |
| `no_head` | `vh == "null"` | "no commit was named" |

This needs **no Git at read time**: `earlier_in_range` is exactly "an ancestor of H inside base..H", because `C` was produced by `rev-list H ^B` (section 5.3 C7). It also keeps working when the board gains new verdicts after the snapshot was taken.

### 7.3 Row labels (exact strings; the page copies them, it never composes its own)

| Verdict | Relation | Row label | Mark |
|---|---|---|---|
| GO | `this_head` | `APPROVED: this head` | `[ok]` |
| GO | `earlier_in_range` | `Approved an EARLIER head. The changes after it are NOT covered.` | `[!]` |
| GO | any other | `Approval of a different head. It does not apply to this comparison.` | `[!]` |
| FIX | `this_head` | `CHANGES REQUESTED on this head` | `[X]` |
| FIX | other | `Changes were requested on <relation text>` | `[!]` |
| HOLD | `this_head` | `ON HOLD / needs information on this head` | `[X]` |
| HOLD | other | `A hold was recorded on <relation text>` | `[!]` |
| (outstanding review request, no reply) | head of its opener | `Asked <reviewer>; no answer yet. For <relation text>` | `[ ]` |

If the reducer says the reviewer is **not independent** (`independent == false`), append ` (the reviewer also built this work: not independent)` and **never** use `[ok]`.

### 7.4 The status banner (one pure function; test every row)

Inputs: the board item (or why it is missing), the board `coverage`, the verdict rows with their relations, the outstanding rows, `H`.

Evaluate in this order; the first rule that applies decides:

| # | State | Applies when | Banner text |
|---|---|---|---|
| 1 | `unknown` | no `work_item` linked; or the item is missing from the feed; or the feed is `building`, `stale` or `last_known`, or its coverage is not `complete`; or `item.column == "unknown"` or `item.workflow_column == "unknown"`; or `item.issues` is not empty; or the board's `item.candidate` is not `H` | `CANNOT TELL whether this head is approved.` followed by one bullet per reason, **verbatim from the board** (`item.reason`, each entry of `item.issues`, the coverage status, "this work item is not on the board feed", "no work item is linked to this comparison", "the board's current candidate is <12 chars>, not this head") |
| 2 | `changes_requested` | a FIX or HOLD row with relation `this_head` exists | `NOT APPROVED: changes were requested on this head.` |
| 3 | `approved` | a GO row with relation `this_head`, `independent == true`, exists; and rule 1 and 2 did not apply; and no outstanding review for `this_head` | `APPROVED: an independent review approved exactly this head.` plus, if the item's `integration` mapping has `H`, ` It is merged into <target>.` |
| 4 | `awaiting` | an outstanding review exists for `this_head`, or the item has no verdict at all | `WAITING for a review of this head.` |
| 5 | `older_only` | at least one GO row exists, all with relation other than `this_head` | `NOT APPROVED: the only approval is for a different head (<relation text>).` |
| 6 | `none` | anything else | `NO REVIEW RECORDED for this head.` |

**Never** show `approved` unless rule 3 applies. The banner state is part of the API (`evidence.banner.state`), so the list page, the detail page and the tests read the same value.

`evidence` block returned in the detail response:

```json
{"status": "ok|no_work_item|not_on_board|board_building|board_unavailable|board_stale",
 "board": {"generated_at": "...", "coverage_status": "complete|...", "column": "unknown", "reason": "...",
           "candidate": "<oid>|null", "issues": ["..."], "integration": {}},
 "banner": {"state": "unknown", "text": "CANNOT TELL ...", "reasons": ["..."]},
 "verdicts": [ {"head": "<oid>|null", "relation": "earlier_in_range", "reviewer": "seat", "vendor": "unverified",
                "independent": true, "verdict": "GO", "label": "Approved an EARLIER head...", "mark": "[!]",
                "reply_id": "...", "request_id": "...", "status": "approved", "ts": "...",
                "excerpt": "...", "transcript": "/api/thread/<request_id>"|null, "reply_in_window": true} ],
 "outstanding": [ {"request_id": "...", "recipient": "seat", "stage": "read", "head": "<oid>|null", "relation": "this_head", "label": "..."} ],
 "previous_cycles": [ {"cycle": 1, "outstanding": [], "note": null} ],
 "missing": [ {"reason": "missing required correlation history", "ids": ["..."]} ],
 "identity": {"project_id": "...", "board_generation": "..."} }
```

- `transcript` is the **existing** path `/api/thread/<request_id>` (FACT route `web.py:5223-5246`); the page opens it as a normal link (JSON). `null` if the reply was not in the active window (`reply_in_window: false`; the row then says "transcript is in the archive, not in the live window").
- `request_id`, `status`, `ts`, `excerpt` come from `by_id[reply_id]` (`meta.request_id`, `meta.status`, `ts`, `body[:600]` after the same inert-text clean-up as code lines). If the reply is not in `by_id`, those fields are `null` and the row still shows (it never disappears).
- `outstanding` comes from `item["obligations"]` (current cycle; entries with `state == "outstanding"` and `stage` in `work_tags.REVIEWS`), joined to the opener message by `request_id` to read `meta.work_head` (FACT: `reduce` gives obligations `{request_id, recipient, stage, state, verdict}` only, `work_board.py:480-481`).
- `missing` is `item.issues` entries that carry evidence ids, plus the reducer's `evidence` list when `reason` is a conflict (FACT: `item["evidence"]` at `:500`).
- **Identity binding (C3):** every verdict row carries its `reviewer` seat, `request_id`, `reply_id` and the page prints `project_id` and `board_generation` in the rationale footer. A verdict is **never** matched to a head by a message id order or a timestamp (FACT: the reducer itself refuses to, `work_board.py:3-4`). The only join is `reply_id -> message -> meta.request_id`, and the head comes from the reducer's own filing, not from the page.
- The function that builds `evidence` is **pure** (takes the feed payload, the message dict, the manifest; returns the dict) so it can be tested without a server.

---

## 8. How the page renders code safely (C4)

### 8.1 Page policy
- Document and assets are served with `_DASHBOARD_CSP`: `default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'` (FACT, `web.py:216-218`). **No inline script, no inline style, no `eval`, no remote anything.** The shell has no `style=` attributes and no `<script>` body.
- No third-party library, font or icon. The three files are written by hand.

### 8.2 Building the DOM
- Every string from the API (paths, commit subjects, reviewer names, labels, excerpts, code lines) enters the page **only** through `document.createTextNode` or `element.textContent`. The words `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `DOMParser`, `createContextualFragment` and `eval` **must not appear** in `compare.js` or `compare-model.js` (test: a source grep that fails the build; FACT: the existing console states the same rule, `web.py:92-99`, "its client builds DOM via `textContent` only").
- Links: the only `href` values the page creates are (a) `"/compare?id=" + id` where `id` matches `^cmp-[0-9a-f]{12}$`, (b) `"/api/thread/" + requestId` where the request id matches the server's `_MESSAGE_ID_RE`-style pattern (the page re-validates with the same regex before creating the element; a value that fails is shown as plain text, not as a link). No `javascript:` or `data:` can survive these checks.
- Code lines use `white-space: pre` and `tab-size: 4` in `compare.css`; the two columns scroll horizontally independently of the page; line numbers are separate cells (so copying code does not copy numbers).
- At most **400 rows** are added to the DOM at once; a "Show next 400 rows" button adds more (so a 2,000-line file never builds 4,000 nodes at once).

### 8.3 Inert text (done once, when the snapshot is made, and checked again by the page)
- Replace C0 controls except tab, DEL, and the bidirectional controls U+202A-U+202E, U+2066-U+2069, U+200E, U+200F by their visible escape `<U+XXXX>`. A line that contained any replacement carries a small mark `[escaped]` in the page. The page repeats the check on what it receives (a snapshot written by something else cannot smuggle a control character in); the check lives in `compare-model.js` as a pure function with the same table as the Python one (a test runs both on one list of hostile strings and compares the outputs).
- Lines are cut at 2,000 characters (section 5.5) and say how many characters were dropped.

### 8.4 What the page never does
Never fetches anything except `/api/compare...` and the three static files. Never writes to the address bar except `?id=`. Never stores data in cookies or local storage. Never runs anything it received. Never calls POST.

---

## 9. The synthetic fixture, the checkpoint, the tests

### 9.1 The fixture (built by a function, never committed as a repository)

`tests/compare_fixture.py` defines `build_fixture(tmp_path)`; it runs `git init` in `tmp_path / "repo"` with a **fixed identity and fixed dates** (environment `GIT_AUTHOR_NAME="Fixture Author"`, `GIT_AUTHOR_EMAIL="fixture@example.invalid"`, the same for the committer, `GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE` of `2026-10-17T10:00:00+0000` plus one minute per commit), so object ids are reproducible on every machine. It writes three commits and returns their full ids:

| Commit | Files | Why |
|---|---|---|
| **BASE** | `greet.py` (5 lines, `greet(name)` returns `"Hello " + name`), `README.md` (3 lines), `data.bin` (64 bytes with a NUL), `unsafe.txt` (one line containing a bidi override character U+202E and the text `<script>alert(1)</script>`), `crlf.txt` (2 lines ending `\r\n`), `big.txt` (300,000 bytes of `x` lines) | covers text, binary, hostile text, CRLF, too-large |
| **H1** (first build) | `greet.py` changed (adds a feature, with the bug: `greet(None)` raises), `big.txt` changed, `unsafe.txt` changed | the reviewed "first version" |
| **H2** (the fix; the head on screen) | `greet.py` fixed (guard for `None`), `tests/test_greet.py` added, `README.md` changed, `data.bin` changed | the fixed version |

Registration: `compare register --repo fixture --base BASE --head H2 --work-item demo-greeting --label "demo greeting"`, with a store whose config has `work_repos.fixture = {path: <repo>, targets: ["refs/heads/main"], default: true}` and branch `main` at H2.

`build_story(bus, ids)` (using the `Bus` class from `tests/test_work_board_reducer.py:25-79`, FACT) publishes the recorded history for work item `demo-greeting`, through the real publication normaliser, with the fixture's ids as `work_head`:

1. `build` task `tk-build` to `qwen-agenttalk-dev-2`, reply `done` (policy `no_gates_reason`, like `reviewed()` at `test_work_board_reducer.py:78-83`).
2. `read` review request `tk-read-1` to `codex-agenttalk-reviewer-1`, `work_head=H1`, reply **status `rejected`, verdict `FIX`** (the rejected review).
3. `fix` task `tk-fix-1` to `qwen-agenttalk-dev-2`, reply `done` (the fix that produced H2).
4. `read` review request `tk-read-2` to `claude-agenttalk-reviewer-3`, `work_head=H1`, reply **status `approved`, verdict `GO`** (the approval of an older head).
5. `read` review request `tk-read-3` to `codex-agenttalk-reviewer-1`, `work_head=H2`, **no reply** (the review of the head on screen is still outstanding).
6. One **raw** `review-result` from `codex-agenttalk-reviewer-1` with `in_reply_to` = `"20261017-000000-000000-miss"` (an id that is not in the store) and `request_id = tk-read-3`, inserted with `raw=True` (FACT: the helper supports it, `test_work_board_reducer.py:52-55`). The reducer flags it `MISSING` (FACT `work_board.py:240-241`): this is the **missing link**.

**Expected result (the golden file `tests/golden/compare_checkpoint.json`, produced once by the builder and then frozen; a later change needs the reader's agreement):**
- `evidence.banner.state == "unknown"`; `banner.reasons` contains `"missing required correlation history"` (FACT: `MISSING`, `work_board.py:24`) and the reducer's own reason for two surviving candidates (`"multiple candidates without supersession"`, FACT `work_board.py:453`). If the reducer words either differently, the golden file records the reducer's actual words; the builder **must not** edit the reducer to match this document.
- `verdicts`: the FIX under H1 with relation `earlier_in_range`; the GO under H1 with relation `earlier_in_range`, label `Approved an EARLIER head. The changes after it are NOT covered.`; and `outstanding` has one row for `tk-read-3` with relation `this_head`.
- No row carries `[ok]`.

### 9.2 The checkpoint demonstration (C7)

Run after work order 3, by the lead and the Codex reader, not by the builder alone.

1. Build the fixture and register as in 9.1; start the dashboard on loopback; open `/compare?id=<cid>`.
2. **Reader 1** (a seat that was not told the story; the reader is shown only the page) answers in writing: (a) *Is the version on the right approved?* (b) *Why, or why not?* (c) *What is the one approval on record, and what does it cover?* (d) *Is anything missing from the record?* **Pass:** (a) "no / cannot tell", (b) names the missing record **or** the outstanding review, (c) says the approval is for an earlier version and does not cover the fix, (d) says one record is missing.
3. **Reader 2** gets the **editor alternative**: the same two commits in the reader's own editor's diff, plus a one-page index the lead writes by hand (about 20 lines: item, commit ids, and the same list of tasks and reviews with their heads, from `/api/thread` links). Same four questions.
4. **Record** for each reader: elapsed minutes from first sight to written answers, and correctness per question; for the builder: elapsed minutes and gateway spend per work order (settled spend from `agenttalk gateway status` before and after each order; **an `open` ledger line is a reservation ceiling, not money spent**, so the spend is the change in the settled October total, not the sum of open lines; FACT: the lead's relay of 2026-10-17 11:24 UTC).
5. **Decision:** if reader 2 answered all four correctly in no more time than reader 1, **stop**: keep the index page, close the project. Otherwise continue to the deferred items only if the lead asks.

### 9.3 Kill signals, and where each is guarded

| C8 signal | Guard in this design |
|---|---|
| the screen implies approval of an unreviewed head | section 7.4: `approved` only by rule 3; tests `test_banner_*` (every row), `test_old_head_approval_is_never_green`, `test_null_head_key_is_no_head`, `test_unknown_board_never_shows_approved` |
| needs client content sent to builders | section 5.8: fixture only; `AGENTTALK_COMPARE_FIXTURE_ONLY` test; the work-order header rule |
| repository reads cannot be bounded | section 5: closed allowlist, caps on output, timeouts; tests `test_every_git_call_is_in_the_allowlist`, `test_output_cap_kills_the_child`, `test_timeout_refuses_and_writes_nothing` |
| budget checkpoint arrives without the demonstration | section 9.2 happens after work order 3; the lead stops there |

### 9.4 The tests, by file (names are the contract; the builder may add more)

**`tests/test_compare_git.py`** (work order 1; uses real `git`, skipped with a clear message if `git` is older than 2.32)
- `test_environment_drops_every_inherited_git_variable_and_sets_the_safe_ones` (plant `GIT_DIR`, `GIT_EXTERNAL_DIFF`, `git_pager` in lower case; assert they are absent in the child's environment, using a tiny wrapper script as `git_exe` that dumps its environment)
- `test_every_git_call_is_in_the_allowlist` (call each wrapper with a forbidden subcommand or a flag outside the table; each raises before a process starts: assert no process was created by monkeypatching `subprocess.run`)
- `test_unsafe_revision_text_is_refused_before_git_runs` (leading `-`, spaces, `;`, newline, 201 characters)
- `test_shallow_and_partial_clones_are_refused` (a `--depth 1` clone; a repo whose local config has `extensions.partialclone`)
- `test_base_must_be_an_ancestor_of_head`
- `test_cat_file_returns_raw_bytes_despite_a_hostile_gitattributes_and_config` (section 5.4; asserts the marker file is absent)
- `test_diff_tree_never_runs_an_external_diff` (`diff.external` and `core.pager` set to scripts that write a marker file; marker absent)
- `test_only_blobs_named_by_the_range_are_requested` (spy on the stdin given to `cat-file --batch`; assert every oid is in the `diff-tree` list)
- `test_output_cap_kills_the_child` (wrapper `git_exe` that prints more than the cap; assert the call fails and the child is gone)
- `test_timeout_refuses_and_writes_nothing` (wrapper that sleeps; use a patched 1 s timeout)
- `test_windows_paths_and_spaces` (a repo path with a space; on Windows the real `NUL` device is accepted for `GIT_CONFIG_GLOBAL`)

**`tests/test_compare_snapshot.py`** (work order 1)
- `test_register_is_idempotent_and_the_snapshot_is_immutable`
- `test_register_stores_ids_not_names_so_a_moved_branch_changes_nothing`
- `test_second_concurrent_register_is_refused_at_once` (hold the lock in the test; `timeout=0`)
- `test_limits_set_truncated_flags_and_never_crash` (monkeypatch the limits to small values; a 4-file range with limit 2)
- `test_binary_symlink_submodule_mode_only_missing_object_states`
- `test_text_is_made_inert` (bidi override, C0 controls, a `<script>` line, a 3,000-character line)
- `test_crlf_is_recorded_and_not_shown_as_a_change`
- `test_the_rows_of_the_fixture_match_the_golden_rows` (`tests/golden/compare_rows_greet.json`)
- `test_registry_reader_refuses_oversize_malformed_and_foreign_schema` (each of the three, byte-bounded)
- `test_fixture_only_environment_variable_refuses_foreign_repositories`
- `test_atomic_write_order_registry_last` (fail the second file write; the registry still names only complete snapshots)

**`tests/test_compare_evidence.py`** (work order 2; pure, no server)
- `test_banner_unknown_when_*` (one case each: no work item, item missing, board building, board stale, coverage incomplete, column unknown, issues present, candidate is another head)
- `test_banner_changes_requested_beats_everything_but_unknown`
- `test_banner_approved_only_for_an_independent_go_on_exactly_this_head`
- `test_old_head_approval_is_never_green` (the checkpoint story)
- `test_not_independent_go_is_never_ok`
- `test_null_head_key_is_no_head` (feed round-tripped through `json.dumps`/`loads` so the `None` key is `"null"`)
- `test_relations_use_the_stored_commit_list_only` (no git, no subprocess: monkeypatch `subprocess.run` to raise)
- `test_truncated_commit_list_gives_unknown_relation`
- `test_reply_outside_the_active_window_keeps_the_row_without_a_transcript`
- `test_excerpt_is_cut_and_made_inert`
- `test_checkpoint_story_matches_the_golden_evidence` (`tests/golden/compare_checkpoint.json`)

**`tests/test_compare_web.py`** (work order 2; real server in a thread, the style of `tests/test_web.py` and `tests/test_console2_web.py`)
- `test_list_detail_and_file_endpoints_return_the_documented_shape`
- `test_head_requests_match_get_without_a_body`
- `test_compare_paths_refuse_post_put_delete` (and GET-only even when actions are enabled)
- `test_unknown_or_repeated_query_keys_are_400_bad_query`
- `test_bad_root_is_400_bad_root`
- `test_cid_and_index_are_validated_before_any_disk_access` (`cmp-../..`, `cmp-%2e%2e`, uppercase hex, index `0`, `00001`, `99999`)
- `test_no_path_traversal_in_cid_or_index` (create a secret file next to the compare directory; no input reaches it)
- `test_missing_empty_oversize_and_malformed_snapshots_are_error_states_not_500s`
- `test_response_caps` (64 KiB list, 512 KiB detail, 2 MiB file)
- `test_the_server_never_runs_git` (monkeypatch `subprocess` to raise during every compare request)
- `test_fifth_concurrent_read_gets_503_with_retry_after` (hold four slots by calling `_compare_slot` in the test; the fifth answers 503 within about 3.5 s)
- `test_headers_are_the_standard_set_and_the_shell_uses_the_dashboard_csp`
- `test_static_assets_are_allowlisted_with_the_right_types`

**`tests/compare_model.test.mjs`** and **`tests/compare_view.test.mjs`** (work order 3; same style as `tests/console2_board_model.test.mjs`)
- model: `escapeInert` table matches Python's; relation/label/banner formatting copies the server strings; state machine for loading/ok/not found/busy/error.
- view (DOM, same harness as `tests/console2_harness.mjs`): each page state of section 2.2; banner text for each state; rows for the checkpoint golden payload; "Show next 400 rows"; **a payload full of hostile strings creates no element other than the expected ones** (count nodes by tag; no `script`, no `img`, no `a` except the two permitted kinds); the source grep for forbidden calls; keyboard: Tab order reaches file list, side-by-side, rationale.
- error path (lesson `process/dashboard-contract-needs-real-projection-test`): a **saved store** -> real `/api/compare/<cid>` payload -> rendered DOM, in one test, on the checkpoint fixture (extends `tests/test_console2_browser.py`'s approach; if no browser is available the DOM harness stands in and the work order says so).

**Existing tests to keep green and one to update:** `tests/test_lock_order.py:80-86` (add `"compare_snapshot.py": 1`); `tests/test_console2_web.py` (unchanged; the new assets are separate); `tests/test_work_board_reducer.py` and `tests/test_work_board_feed.py` (**unchanged**: the design does not touch the reducer or the feed).

---

## 10. The work, split into three work orders

Each order is for the one builder (`qwen-agenttalk-dev-2`); a Codex seat reads the commit before the next order starts. **Standing rules for every order:** work only on the synthetic fixture and the agenttalk repository; no client file is opened; local branch only; run the named tests and the existing suites listed; reply with the head SHA copied from `git rev-parse HEAD`.

### Work order 1: read the repository and take the snapshot (no HTTP, no page)

- **Files (new):** `src/agenttalk/compare_git.py` (the environment, the closed allowlist, calls C0-C11, limits), `src/agenttalk/compare_snapshot.py` (registration, the row builder, the readers, the lock), `tests/compare_fixture.py` (section 9.1, repository only), `tests/test_compare_git.py`, `tests/test_compare_snapshot.py`, `tests/golden/compare_rows_greet.json`.
- **Files (edited):** `src/agenttalk/cli.py` (a `compare` parser with `register`, `list`, `show`, handler `cmd_compare` modelled on `cmd_board` at `:8611` and the parser block at `:16703`); `tests/test_lock_order.py:80-86` (+ `"compare_snapshot.py": 1`); `docs/LOCK-ORDER.md` (a new row for `compare-register.lock`, rank 210 leaf, with one line of why); `CHANGELOG.md` (an Unreleased "Added" entry in plain words, written with the write-for-humans rules).
- **Step 1 (before any code):** read `janitor.py`, `doctor.py` and `docs/BACKUP.md` for anything that enumerates directories under `.agenttalk/`; report what you found in the commit message (decision D3).
- **Acceptance:** every test named under `test_compare_git.py` and `test_compare_snapshot.py` in section 9.4 passes; `pytest tests/test_work_board_facts.py tests/test_lock_order.py` still passes; `agenttalk compare register` on the fixture prints the new id, a second run prints the same id and changes nothing, `compare list` and `compare show <cid> --json` print the documented fields; **no test or command in this order starts a thread**.
- **Done means:** the above, plus `git diff --stat` touches only the listed files, plus the commit message lists the measured worst-case time of the 2,000-line row builder on the host that ran it (section 5.6).
- **ESTIMATE:** about 420 lines of product code, 520 of tests; one builder session of 4 to 8 model turns plus one rework round; 3 to 8 EUR (ASSUMPTION, see section 0).

### Work order 2: the evidence binding and the three GET endpoints

- **Files (new):** `src/agenttalk/compare_evidence.py` (the pure function of section 7: relations, labels, banner; no I/O), `tests/test_compare_evidence.py`, `tests/test_compare_web.py`, `tests/golden/compare_checkpoint.json`.
- **Files (edited):** `src/agenttalk/web.py` (module docstring route list; `_COMPARE_*` constants and `_compare_slot`; the three routes inside `_route` after `/api/work-board` at `:5098-5109`; `render_compare()` and the `/compare` route next to `/v2` at `:5206-5209`; the three asset names in `_load_static_assets` at `:810-820`, files may be empty placeholders until order 3); `tests/compare_fixture.py` (add `build_story`).
- **Does not touch:** `work_board.py`, `work_board_feed.py`, `work_board_facts.py`, `envelope_snapshot.py`, `console2*.js`.
- **Acceptance:** every test named under `test_compare_evidence.py` and `test_compare_web.py` in section 9.4 passes; the golden checkpoint file is produced from the fixture and **frozen** (the commit message states the reducer's actual words for each reason); `pytest tests/test_web.py tests/test_web_host_gate.py tests/test_console2_web.py tests/test_work_board_reducer.py tests/test_work_board_feed.py` still passes unchanged; `grep -n "subprocess" src/agenttalk/compare_evidence.py` prints nothing; the only threading code added to `web.py` is the 12 lines of section 6.
- **Done means:** the above, plus a short `docs/COMPARE-VIEW.md` "API reference" section copying section 6 (so the next reader has one place), plus the reply names the three response sizes measured on the fixture.
- **ESTIMATE:** about 330 lines of product code (`compare_evidence.py` 190, `web.py` 140), 470 of tests; 4 to 8 turns plus one rework round; 3 to 8 EUR (ASSUMPTION).

### Work order 3: the page, the model, the demonstration

- **Files (new):** `src/agenttalk/web_static/compare.css`, `compare-model.js` (pure; dual Node and browser like `console2-board-model.js`, FACT: `docs/STEP-WORK-BOARD.md:17`), `compare.js`, `tests/compare_model.test.mjs`, `tests/compare_view.test.mjs`, `docs/COMPARE-VIEW.md` (operator guide in plain words: what the page shows, how to register, how to read the banner, what the limits are, how to run the checkpoint).
- **Files (edited):** `tests/test_console2_browser.py` or a new `tests/test_compare_browser.py` (the saved-store-to-DOM test; skipped with a stated reason if no browser is installed); `CHANGELOG.md` (extend the entry).
- **Acceptance:** every `.mjs` test named in section 9.4 passes under `node --test`; the page renders every state of section 2.2 against canned API payloads; the saved-store-to-DOM test passes on the checkpoint fixture; the source grep forbids `innerHTML` and friends; `pytest tests/test_console2_web.py` passes unchanged; **the lead runs the checkpoint of section 9.2** and the result (both readers' answers, elapsed minutes, spend) is written to `docs/COMPARE-VIEW.md` under "Checkpoint 1" by the lead, not the builder.
- **Done means:** the above, plus screenshots of the list page, the detail page on the checkpoint fixture, and one error state, saved under `docs/images/` (small PNGs, no personal data).
- **ESTIMATE:** about 760 lines of product code (`compare.js` 420, `compare-model.js` 200, `compare.css` 140), 400 of tests; 6 to 10 turns plus one or two rework rounds; 4 to 10 EUR (ASSUMPTION).

### Totals and the question "how much work is it?"
- **ESTIMATE:** product code about 1,500 lines, tests about 1,400 lines, docs about 250 lines; three builder orders and three Codex reads; **8 to 25 EUR** of builder spend (ASSUMPTION; recorded cheap turns today are 0.4 to 1.0 EUR for a read, and an open ledger line is a ceiling, not a charge); **about a day and a half** of elapsed time (ESTIMATE: three orders of 3 to 6 hours each, with the reads between them).
- **Cheaper alternative** (the one the challenge named): the editor's own diff plus a one-page index that the lead writes by hand. **ESTIMATE:** one to two hours, no new code. That is the second reader's material at the checkpoint.

---

## 11. Risks I see, and how the design answers them

| # | Risk | Answer |
|---|---|---|
| R1 | A hostile repository tries to run code through a diff driver, a filter, a hook or fsmonitor | closed allowlist; only plumbing; `--no-ext-diff --no-textconv`; `cat-file --batch` without `--filters`; `core.fsmonitor=false`; global and system config ignored; a planted-marker test for each |
| R2 | The page shows a green approval for a head nobody reviewed | one pure banner function; `approved` only by rule 3; golden fixture with an old-head approval; the list page reuses the same function |
| R3 | A change breaks console v2 (its board tests are exact-equality tests: FACT `tests/test_work_board_reducer.py:186,342`; `tests/test_console2_browser.py:224`) | the design adds no field to the reducer or the feed and no change to `console2*.js` (D5) |
| R4 | The builder introduces a race | the only thread-related code is the 12-line semaphore of section 6 (copied, not designed); registration uses the existing lock helper with `timeout=0`; the Git module is single-threaded with `input=` calls |
| R5 | The snapshot hides that the repository moved on | by design: the comparison names two commit ids and says so; the page shows `created_at`; "follow a branch" is deferred |
| R6 | Windows differences (NUL device, paths, `git.exe` lookup, CRLF) | section 5.3 notes; a Windows test; CRLF is bytes-in bytes-out and recorded as a flag, never as a change |
| R7 | A partial clone or shallow checkout makes missing objects look like deletions | both refused at registration; `missing_object` is its own state |
| R8 | The recorded rationale is mistaken for complete reasoning | the panel is titled "Recorded rationale", carries the sentence "what the team wrote down about this work; not a full account", and the excerpt is capped |
| R9 | Evidence changes after the snapshot (new reviews) | evidence is **not** snapshotted: it is read live from the cached board on each request; only code and commit facts are immutable |
| R10 | The store directory grows | 20 comparisons x at most 16 MiB; the registry refuses the 21st; the operator removes by deleting a directory (message prints the path) |

---

## 12. What this design deliberately leaves out (C6) and what would follow
Line-pinned findings; round-by-round playback; a history backfill; syntax colouring; rename detection; intra-line highlighting; following a branch; a command to add a repository alias; a link from console v2; comparing non-linear ranges; any write action. Each can be a later slice **only if** the checkpoint shows the linkage helps.

## 13. Self-check before sending this design to the reader
- Every line reference was read at `bdc775cb`; the reader should spot-check at least: `work_board.py:459-469`, `:147-172`, `:493-501`; `web.py:216-218`, `:801-829`, `:967-978`, `:4436-4454`, `:5098-5109`, `:5206-5221`; `work_board_facts.py:133-155`, `:158-185`, `:229-233`; `lock_order.py:12-47`; `tests/test_lock_order.py:80-86`.
- Claims marked ASSUMPTION that the reader can settle quickly: `GIT_CONFIG_GLOBAL=NUL` on Git for Windows; `diff-tree --end-of-options` on Git 2.32; nothing in `janitor.py` or `doctor.py` flags an unknown `.agenttalk/compare/` directory; Apple Git's version.
- **What I did not do:** I ran no Git command and no test, and wrote no code (design round). The command forms in section 5.3 are therefore **untested**; work order 1 tests each of them on the three platforms the lead has.
