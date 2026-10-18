# Self-compaction pilot: an agent keeps its own conversation small

Status: proposed. Written on 2026-10-18 for work order tk-5be1f80d7c73, after the challenge ch-fc39f8c7-7c05-496c-a616-933674d6a2a8 returned RESHAPE and the lead accepted it in full. Fix round 1 (tk-f935a8bfd62e) answers the seven findings of the Codex read tk-f11f4003d894. Nothing in this document is built. Where it describes how agenttalk works today, it matches master `7a613aeb` (release 0.102.0). Owner: lead. The final read (tk-e78baa38e6a0) passed it with binding requirements for the build; step 0 (W0) is reported in `docs/design/self-compaction-pilot-w0.md`. Section 18 lists every binding requirement from the reads (the two final reads and the automatic reviewer's nine findings on pull request #531), and the text below follows them.

**In plain words:** an agent that agenttalk runs in the background sends its whole conversation to its AI again on every step, so a long conversation makes every turn dearer. Since release 0.102.0 an agent can already ask to start its next turn on a new conversation, but it then starts with nothing from before. This design proposes a small, measured pilot on one kind of agent: Claude Code on its normal subscription. The agent writes a short handover note at the end of a finished turn and, once its conversation has grown large, asks for its own fresh start. agenttalk applies that start only when a set of checks passes and a complete list of the agent's unfinished work can be read from the message bus; every other way a conversation can change on a pilot agent follows the same rules or stops for a person. The design decides the note's format, the checks, how a fresh start is recorded and undone, the crash tests, the measurements and the numbers that decide whether the pilot is extended. The lead's answers to its five questions are in section 16.

Audience: the operator and the lead, who decide; the Codex reader; the builder, who needs sections 4 to 11 and 14. Mode: explanation (a design).

Why a new file and not an update to `docs/design/context-policy.md`: master still holds the 2026-09-22 version of that file, and its refresh for #477 is in pull request #490, which is not merged. This pilot is a narrower first slice that comes before #490's later steps, and editing the same file would mix the two. Section 15 says how they fit together.

## Contents

1. [The problem, measured](#1-the-problem-measured)
2. [What already ships](#2-what-already-ships)
3. [The pilot in one picture](#3-the-pilot-in-one-picture)
4. [The handover note](#4-the-handover-note)
5. [The facts read: a complete list of unfinished work, or no fresh start](#5-the-facts-read-a-complete-list-of-unfinished-work-or-no-fresh-start)
6. [The transition record](#6-the-transition-record)
7. [The loader check](#7-the-loader-check)
8. [The trigger and its guards](#8-the-trigger-and-its-guards)
9. [Every way a conversation changes on a pilot agent](#9-every-way-a-conversation-changes-on-a-pilot-agent)
10. [Delivery, obligations and the crash tests](#10-delivery-obligations-and-the-crash-tests)
11. [The rule for the agent's instructions](#11-the-rule-for-the-agents-instructions)
12. [Older runtimes](#12-older-runtimes)
13. [The pilot: measure first](#13-the-pilot-measure-first)
14. [Work orders for the build](#14-work-orders-for-the-build)
15. [How this fits #475, the roadmap, #490 and #178](#15-how-this-fits-475-the-roadmap-490-and-178)
16. [The lead's answers](#16-the-leads-answers)
17. [What it does not do](#17-what-it-does-not-do)
18. [Binding requirements from the reads](#18-binding-requirements-from-the-reads)

## 1. The problem, measured

A wrapped agent keeps one conversation with its AI for as long as its wrapper runs. Each turn continues it, and every step inside a turn (each model call) sends the whole conversation again.

- **2026-10-13:** a lead on the maintainers' second machine had reached 830 turns. Each idle check cost about half a point of its subscription's weekly allowance. It had to be started on a new conversation by hand (#475).
- **2026-10-16 to 10-18, one Claude developer agent on this desktop** (the agent that wrote this design), from its own Claude Code transcript:
  - 3,000 model calls; the context sent per call had a median of 479,283 tokens and a maximum of 966,800;
  - most of that was read back from the provider's prompt cache: 1.41 billion cache-read tokens, 21.4 million cache-write tokens, 3.7 million output tokens;
  - 26 calls wrote more than 100,000 tokens of cache each (13.3 million in total): the cache had expired while the agent was idle, so the whole conversation was written to the cache again.
  - Weighted by the provider's price ratios (section 13), cache reads were 76% of the cost, cache writes 14% and output 10%. The size of the conversation, times the number of calls, is what costs.
- **Four quantities that are easy to mix up.** That transcript file is 214,851,125 bytes on disk, while the conversation sent on each call was about 231,000 tokens at the time of measuring. Transcript bytes, the bytes of one request, context tokens and the subscription's allowance are different things. This design never converts one into another, and it does not use the transcript's size as the size of a request.

## 2. What already ships

### The pieces this design reuses

| Piece | What it does today | Where |
|---|---|---|
| **Fresh start on request** (#475 step 1, release 0.102.0) | `agenttalk session fresh --for <agent> --reason "..."` writes a request marker. The agent itself, a lead or the operator-facing agent may ask. The agent's own wrapper applies it between turns: it copies the session record aside first (no copy, no reset), gives Claude a new session id or clears Codex's thread, saves the record, then clears the marker. When the save fails, it reads the record on disk again: a save that landed is adopted, one that did not is undone in memory and retried. It records the last outcome in the session record (`fresh_request_*` fields). Only the wrapper that claimed the agent last may apply it. | `cmd_session_fresh` in `cli.py`; `write_fresh_request`, `read_fresh_request`, `clear_fresh_request` in `store.py`; `apply_fresh_request` and `_backup_session_record` in `wrapper/session.py`; `_apply_fresh_request`, `claim_wrapper_ownership` and `is_active_wrapper` in `wrapper/run.py`; `_apply_fresh_when_idle` inside `_wrap_loop_mode` in `cli.py` |
| **Where the request is applied** | At the start of every message turn (`make_drive`), at the start of every lead-loop cadence turn (`make_cadence_drive`), and on every idle poll. | `wrapper/run.py`, `cli.py` |
| **The size warning** | `status` and the dashboard show the context size of the agent's last turn, or else its total turn count, and warn above 150,000 tokens (Claude), 190,000 (Codex) or 300 turns. The limits are set with `conversation_warn_tokens` and `conversation_warn_turns` in `supervisor.json`. | `conversation_size.py`; `_gather_status` in `cli.py`; `web.py`; `conversationSizeText` in `web_static/console.js` |
| **The complete read of the bus** | `store.valid_messages()` reads every message file in the live log through the trust gate (schema, roster, and the message signature when signing is enforced), with no size or time cap. `agenttalk threads` feeds it to `threads.derive_threads` with the agent's cursor to work out what the agent owes and waits for. `store.validated_messages_with_problems(since_id=None)` also reports the files it rejected, and, under the publication locks, every id in the durable publication order whose file is absent. Two limits matter here: it counts a compacted message as absent, and it skips the absent-file check when it cannot read the order (section 5). | `store.py`; `cmd_threads` in `cli.py`; `threads.py` |
| **Compaction of old messages** | Optional (`agenttalk compact`; automatic compaction is off by default). It moves messages below a keep floor into `archived/compacted/`, which no live view reads again; the files' entries stay in the publication order. It records its last floor in `state/compact.json`, a best-effort stamp: a failed write is ignored and a later run replaces it. | `archive_messages_batched`, `read_compact_stamp` in `store.py`; the compaction command in `cli.py` |
| **The compaction checkpoint** | `agenttalk checkpoint save / resume / show`, run by Claude Code's own `PreCompact` and `SessionStart` hooks, which the supervisor installs. It saves the context reading, the git state and the agent's open threads to `.agenttalk/checkpoints/<agent>.json`, with the last ten kept as history. Its bus read is deliberately best effort: it stops after 512 files, 8 MiB or 15 seconds, and on a time-out or error it returns empty lists marked `truncated`. | `checkpoint.py` (`build_checkpoint`, `collect_bus_state`, `collect_git_state`, `save_checkpoint`); `_CHECKPOINT_HOOK_SPECS` in `supervisor.py` |
| **Message delivery** | The wrapper loop records an attempt before every turn and moves the agent's cursor past a message only after a clean turn, or when it dead-letters the message. A crash during a turn delivers the message again. Section 10 says exactly what this does and does not promise. | `_run_continuous` in `wrapper/loop.py`; `recv_api.commit` |
| **The delivery commit gate** | Optional (`AGENTTALK_COMMIT_GATE_POLICY`). It admits only `question` messages that are not consults; for every other kind it answers "kind is detection log-only". For an admitted question it proves that the answer landed before the cursor moves. | `wrapper/obligations.py` |
| **The draft channel** | The prompt names a file; the agent writes its reply there; the wrapper collects it after the turn. It works in every sandbox. | `reply_draft_path` in `reply_transport.py` |
| **The turn journal** | Optional (`agenttalk wrap --loop --turn-events`). One event per dispatch, with whether the conversation was new or continued (`cli_session`), and for Claude the turn's four token totals by kind, taken from the stream's `result` event. It can drop events when its queue or disk is full; each event carries a sequence number, so a gap shows. | `turn_events.py`; `_result_usage` in `wrapper/run.py` |
| **Quiet lead ticks** | A wrapped lead's cadence tick spends no model turn when nothing in its snapshot is actionable. | `cadence_actionable` in `lead_loop_cadence.py` |
| **Self-healing a conversation that cannot continue** | After two failures that belong to the conversation, the wrapper starts a new one by itself and tells the liaison once. A failed first turn of a new Claude conversation gets a new session id. A changed model or effort setting starts a new conversation at relaunch. | `make_drive`, `make_cadence_drive` in `wrapper/run.py`; `reset_claude_session`, `mark_resume_unavailable`, `reconcile_runtime_fingerprint` in `wrapper/session.py` |

### What is missing

1. **A fresh start loses everything.** The README says so: "Handover notes are not part of this command, so the agent starts without its old conversation."
2. **The size figure is not tied to one conversation, so it cannot trigger anything safely.**
   - Without a current token reading, it falls back to `turns_total`, which a fresh start does not reset.
   - The token reading comes from the capacity snapshot, which expires after 600 seconds (`DEFAULT_STALE_AFTER_SECONDS` in `capacity.py`). So for an agent that has been idle for ten minutes, there is no reading at all.
   - The reading is not stamped with the conversation it describes; `status` can only drop readings older than the last fresh start.
3. **The first turn of a new conversation cannot be told it is new.** In `make_drive` and `make_cadence_drive` the prompt is assembled before the fresh-start request is applied.
4. **Only the last fresh start is recorded,** and nothing records which backup belongs to which fresh start once a later request replaces the last-outcome fields.
5. **The ready-made bus read is best effort.** The checkpoint's read can return empty lists on a busy or slow bus, so it cannot be the source of "what this agent still owes".
6. **Automatic new conversations start with nothing:** the self-heal, a model change, and an unreadable session record (which `load_session` treats as a reason to start fresh).
7. **Nobody has measured** whether a fresh start with a note costs less than continuing, and the journal does not keep what such a measurement needs (section 13).
8. **The checkpoint reads the wrong folder for a wrapped agent.** `build_checkpoint` reads git state from the project's root folder (`collect_git_state(store.root)`), not from the folder the agent works in (#477, finding 9).

## 3. The pilot in one picture

On a pilot agent, one fresh start goes like this:

1. **The wrapper measures** the context of the agent's last model call at the end of every finished turn, and stamps the reading with the conversation it belongs to (section 8).
2. **Above the note mark** (100,000 tokens), the turn's prompt shows the size and names a draft file for the handover note. The agent writes the note there as its last step (section 4).
3. **Above the fresh-start mark** (150,000 tokens, today's warning limit), the prompt also advises a fresh start. The agent writes the note, runs `agenttalk session fresh --for <itself>`, and replies as usual (section 11).
4. **The turn finishes.** The wrapper seals the note: it freezes it in a file that is never changed again and records its fingerprint (a SHA-256 hash) in the session record.
5. **Between turns,** the existing fresh-start handler checks the request against its guards (section 8), checks the note (section 7), and reads the bus completely (section 5). If everything passes, it records a transition (section 6) and applies the fresh start as today. If the bus cannot be read completely, the request waits. If a guard or the note fails, it refuses and says why, and the conversation continues.
6. **At the next message,** the wrapper checks the frozen note and reads the bus completely again, then starts the new conversation with: the standing rules, the facts it just read, the note marked as data, and the message. If either check fails, the message waits, or the wrapper goes back to the old conversation (section 7).

There is no new decision-maker: step 5 is today's fresh-start handler with guards added. The agent asks; the handler decides. The automatic ways a conversation changes go through the same steps or stop for a person (section 9).

## 4. The handover note

### What the agent writes

- **Free text, at most 3,200 bytes** (about 800 tokens), the same limit as #490. A longer note is refused, not cut, and the next prompt says so.
- Suggested headings: what is done, what is next, open questions, decisions taken and why, commands that worked with their exact flags.
- **Where:** the draft file the prompt names, `.agenttalk/state/handover-drafts/<agent>/<turn-id>.md` (proposed). The turn id is the one the wrapper already makes for each turn (`turn-<12 hex>`, used today for lesson exposure and the turn journal). Writing a file needs no new command and works in every sandbox, like the reply draft.
- **When:** as the last step before the reply, when the prompt asks for it. Above the note mark the prompt asks when the newest sealed note is five or more finished turns old, or was written for another work item, and always in a turn where it advises a fresh start. Below the mark it never asks.
- **What it must not hold:** secrets, keys, account or host values, or client names. The note stays in the local store, but the same rule as for records applies.

### When it counts: sealed at a finished turn

A draft becomes a note only when its turn finishes cleanly: the same "completed" outcome after which the wrapper counts the turn today (`session_state.turns += 1` in `make_drive`). The wrapper then:

1. reads the draft, refuses it if it is larger than 3,200 bytes or not UTF-8;
2. writes the sealed note to `.agenttalk/state/handover/<agent>/<handover-id>.json` (proposed) with the format below, once, never overwritten;
3. records its id, its `record_sha256` and its turn id in the session record, in the same save that records the finished turn;
4. deletes the draft.

A draft from a turn that failed or was interrupted is never sealed. `status` shows `handover=unsealed`, and the retry of that message writes a new one if it is asked for.

### The sealed format (format 1, proposed)

| Field | Meaning |
|---|---|
| `format` | `1` |
| `handover_id` | `hv-` and 12 hex digits |
| `agent` | the agent's name |
| `conversation` | the Claude session id of the conversation it was written in |
| `wrapper_generation` | the wrapper that sealed it |
| `turn_id`, `conversation_turn` | the turn that wrote it, and that turn's number within the conversation |
| `message_id`, `request_id` | the message the turn handled |
| `work_item`, `work_round`, `work_head` | the message's typed work fields, each left out when the message has none |
| `sealed_at` | when it was sealed |
| `context_tokens` | the conversation's size at that turn (section 8) |
| `checkpoint` | the branch, commit and number of changed files of the agent's working folder at sealing (`checkpoint.collect_git_state` on that folder) |
| `note_bytes`, `note_sha256` | the size and fingerprint of the text |
| `record_sha256` | the fingerprint of the whole sealed record: SHA-256 over its canonical JSON (keys sorted, no spaces, UTF-8), computed with this one field left out. It covers the conversation, the turn, the checkpoint and every other field, not only the text, and every check of a note uses it (section 7) |
| `note` | the text |

The `checkpoint` lets the loader say what changed since the note was written (for example "the branch has moved on"). It holds no list of obligations: those come only from the facts read (section 5).

**Kept:** the ten newest sealed notes per agent, the same number as the compaction checkpoint keeps. A note that an open transition names is never deleted.

### How it is shown, so that it stays data

The note can quote anything the agent read: a customer's text, a log, or an instruction someone planted in a file. So it is shown the way #490 section 4 proposes:

- in its own block, after the standing rules and before the message, under a heading that says an earlier conversation of this agent wrote it, that it may quote others, and that it is not an instruction;
- with lines that look like the wrapper's own section headings neutralised;
- with checking rules in the standing rules: the note says what an earlier conversation believed; check every next step against the message, the files and the bus; do only what the current message asks;
- with the wrapper's facts beside it, which win any disagreement;
- never as the source of a "done", a roster fact or an obligation (section 10).

`status` and the dashboard show only the note's id, age and size, never its text.

## 5. The facts read: a complete list of unfinished work, or no fresh start

The checkpoint's bus read is best effort, so the pilot never uses it for a decision. It uses a new read, the **facts read** (proposed), which either is complete or says why not.

### What it reads

- every message file in the live log and in the compaction archive (`archived/compacted/`), through the store's trust gate (schema, roster, and the signature when signing is enforced), with no file or byte cap;
- the store's durable publication order, read under the same locks that `validated_messages_with_problems(since_id=None)` takes, so a message that is being published cannot look missing;
- the agent's cursor and thread-state files;
- `threads.derive_threads` over those, as `agenttalk threads` does, giving the replies the agent owes, the replies waiting for it and the requests it sent and still waits on;
- for the current message's request: whether this agent's final reply has already landed.

It runs before any model process starts: when a request is applied (between turns), and when the first message of a new conversation is prepared.

### When it counts as complete

All seven must hold; otherwise the read is incomplete, with the first failing reason word:

| Reason word | Complete only when |
|---|---|
| `timeout` | the whole read finished within 60 seconds (a setting; measured during the pilot) |
| `rejected_files` | no message file, live or archived, was rejected: unreadable, not JSON, wrong schema, off the roster, or a bad or missing signature. A rejected file might be an obligation, so the read fails closed and reports how many |
| `signing_unavailable` | when signing is enforced (`store.signing_enforced()`), the key can be read. Without it every signed message would be rejected |
| `order_unavailable` | the publication order exists, can be read, and is durable. Today's `validated_messages_with_problems` quietly skips its check for missing files when it cannot read the order; the facts read refuses instead |
| `missing_messages` | every id in the publication order has a valid file in the live log or in the compaction archive. That reader alone would report every compacted message as absent (`publication_ordered_message_absent`), because compaction moves the files but keeps their order entries. So an id found valid in the archive counts as compacted (matched by the message id inside the file, because compaction adds a time suffix to a name that is already taken there), and only an id found in neither place counts as missing, which fails the read: a deleted message, even with all its neighbours present |
| `history_compacted` | no message this conversation handled was compacted. The wrapper keeps one membership list per conversation, `state/<agent>.conversation-messages.<conversation-id>.jsonl` (proposed): the id of every message whose turn it starts in that conversation, appended before the turn runs. Its first line is a **header** naming the conversation and its completeness boundary: the list is complete only when the header says it was created by the transition that started this conversation, before its first turn. A handled broadcast is on the list like any other message, because the list records what was handled, not how it was addressed. The read fails when an id on the list is found in the compaction archive. Messages between other agents, and messages to this agent that this conversation never handled, do not count. **Each entry carries its own identity:** a sequence number (1, 2, 3 and so on within the conversation, never reused), the message id and the attempt id of the turn it starts. The entry is written and flushed before the turn runs; if it cannot be written durably, the turn does not start and the message waits, as with an incomplete facts read. A failed attempt and its retry each get their own entry. The session record keeps `membership_high_water`, the highest sequence number written, saved together with every finished turn, and for each finished turn the sequence number of its entry. **The list counts as complete only when** its sequence numbers run from 1 without a gap, its last number is at least `membership_high_water`, and the entry of every finished turn is present with the same message id; counts are never compared. Cadence turns of a wrapped lead carry no bus message, so they add no entry and play no part in this proof. **The list counts as incomplete** when it is unreadable, when its header is missing or names another conversation, when it was created after the conversation began (for example when the pilot was switched on mid-conversation), or when any of those proofs fails (an entry was lost). A new conversation gets a new file, so a transition never truncates the old list; a rollback selects the old conversation's file again by its id, and if that file is gone the list counts as incomplete. The files of the three newest conversations are kept. If the list is incomplete, the guard falls back to a broader rule that can only hold too much, never too little: any archived message to or from this agent, broadcasts included, with an id at or after `conversation_first_message_id`. The archive itself is the record; the best-effort stamp `state/compact.json` is not used, because a crash or a later run can lose or lower it. Compaction's floor is designed to keep open obligations live, but the pilot does not rely on that |
| `state_unreadable` | the cursor and thread-state files read cleanly |

### What happens when it is incomplete

- **When a request would be applied:** the request waits. It is not refused, because a time-out or a lock usually clears. The handler tries again on each idle poll, backing off from one minute to fifteen, and `status` shows `fresh=pending(facts:<reason>)`. After two hours it is refused (`refused_facts_<reason>`) and the liaison is told once: a rejected file or a missing key needs a person. **While the agent's own request waits, its old conversation takes no further turn:** new messages for the agent are held the same way as in the next point, with no attempt recorded, so the note the request was written with stays the conversation's newest. When the request is applied or refused, the held messages go ahead.
- **When the first message of a new conversation is prepared:** the facts read runs in the wrapper loop **before** the loop writes its attempt record for the message (`record_attempt_start`), so neither a wait nor a crash during the read charges an attempt. While the read is incomplete, the message waits: it is not driven and no attempt is recorded, as with today's gateway hold (`CLASS_GATEWAY_HELD`, `_hold_park` in `wrapper/loop.py`), and the read is tried again on the next poll. After two hours the transition becomes `blocked(facts_<reason>)`, the agent stays held, and the liaison is told once.
- **A lead's explicit choice:** `session fresh --for <agent> --no-handover` starts a new conversation without the note and without the completeness requirement, as step 1 does today. The new conversation's prompt says that its facts were not checked. A held agent is released with its hold id instead (section 6).

## 6. The transition record

A transition is one change from an old conversation to a new one. The session record holds at most one open transition, `fresh_transition` (proposed), saved in the same write that changes the conversation.

### What it holds

| Field | Meaning |
|---|---|
| `transition_id` | `ft-` and 12 hex digits |
| `reason_code` | `fresh_requested`, `resume_unavailable` or `runtime_config_changed` (section 9) |
| `request_id`, `requested_by` | the fresh-start request and who asked, or `auto` for the automatic reasons |
| `from_conversation`, `to_conversation` | the session ids before and after |
| `backup_file`, `backup_sha256` | the exact copy of the session record taken before the change (today's `<agent>.wrapper-session.before-fresh-<id>.json`) and its fingerprint |
| `handover_id`, `handover_record_sha256` | the note to load and its record fingerprint (section 4), or none after `--no-handover` |
| `evidence` | what each decision rested on, kept for the report (below) |
| `state` | `pending_load`, `rollback_started`, `rolled_back`, `blocked`, `released` or `loaded` |
| `blocked_reason`, `started_at`, `updated_at` | why it is blocked, and when |

**Ending a transition.** `pending_load` ends as `loaded` when the first turn of the new conversation finishes; a rollback ends as `rolled_back`. Both are terminal, and both end the same way, in three steps:
1. The save that makes the transition terminal also gives it a `terminal_event`: the next sequence number, an event id (the transition id and its final state) and the SHA-256 of the exact line to append.
2. The wrapper looks for that sequence number in the decisions file (the current file and the one older file). If the line is there with the same event id and fingerprint, the step is done. If a different line holds that number, the agent is held as `blocked(decisions_conflict)` and the liaison is told. If the number is absent, it appends exactly that line and flushes it to disk. A partial last line left by a crash is first moved to a side file, never overwritten.
3. One save then clears `fresh_transition` and records the number as `decisions_seq`.

A crash at any point leaves the terminal transition, with its `terminal_event`, in the record, and the next start repeats from step 2. A last number that is equal or higher never counts as proof by itself: only the matching event id and fingerprint do. The clean-up never touches the accounting below.

### Accounting, kept apart from the diagnostic list

- `fresh_applied_times`: the times of applied transitions in the last seven days (when there are more than 64, the oldest go first, but none from the last 24 hours), and `fresh_last_applied_at`. The cooldown and the daily limit (section 8) read only these.
- **What counts:** every applied transition, whoever asked and for whatever reason, including automatic ones. A transition that was rolled back still counts: it was applied, and counting it stops a loop of apply, roll back, apply. Refused and waiting requests do not count.
- `rotation_log`: the last 20 decisions, for `status` only. It never decides anything, so refusals pushing applications out of it change nothing.
- **The pilot's full record:** `.agenttalk/state/<agent>.fresh-decisions.jsonl` (proposed), one line per decision (applied, refused, waiting, rolled back, blocked, loaded), capped at 1 MiB with one older file kept. Each line carries a sequence number that only grows, and the session record keeps the last one as `decisions_seq`, saved together with the decision. A file whose last number is below `decisions_seq` has lost an append, even after the transition field was cleared, and the report shows it.
- **The evidence kept per transition,** never with note text: the facts read at apply and at load (complete, or its reason word; the counts; a fingerprint of the inventory); the ids of the replies owed, the replies awaited and the open requests at both moments, with the cursor; and the note's id, its `record_sha256` and the outcome of each check. B1 and B2 are judged only from this evidence (section 13).

### Rolling back, as a recoverable change

**Only a requested transition is rolled back, and only when its old conversation can still be resumed** (its `reason_code` is `fresh_requested` and the backup says `resume_available`). An automatic transition (`resume_unavailable`, `runtime_config_changed`) is never rolled back: its old conversation already failed, or the operator changed the model, and a rollback would resume the old conversation under the new settings. It becomes `blocked`, and the agent is held (section 9). For a requested transition, when the loader cannot use the note after the change (section 7), the wrapper goes back to the old conversation:

1. **Mark the start:** save `state=rollback_started`. The session record on disk is the authority after every write. A save that fails is handled as today's fresh start does: read the record on disk; adopt it if the write landed; otherwise undo in memory and try again on the next poll.
2. **Check the backup:** the file named in `backup_file` exists, its fingerprint is `backup_sha256`, and its session id is `from_conversation`. If not, the transition becomes `blocked(backup_missing)` or `blocked(backup_corrupt)`, the agent is not dispatched, the liaison is told once, and a lead releases it (below).
3. **Restore only the conversation fields** from the backup, in one write, together with `state=rolled_back`:
   - restored: `claude_session_id`, `codex_thread_id`, `resume_available`, `resume_unavailable_reason`, and the conversation's own fields (`conversation_id`, `conversation_turns`, the size readings, `conversation_first_message_id`, the last finished turn and the newest note). The old conversation's membership list is selected again by its conversation id (section 5); it is never replaced by the new conversation's list;
   - never restored: the all-time `turns`, the `fresh_request_*` outcome, `fresh_applied_times`, `fresh_last_applied_at`, `rotation_log`, the runtime fingerprint and the rate-limit reading. So a rollback cannot bring back the accounting from before the change.
4. **Append** the outcome to the decisions file.

**After a restart,** before it dispatches anything, the wrapper reads `fresh_transition`: `rollback_started` is finished first (steps 2 to 4 again; they are safe to repeat); a terminal `loaded`, `rolled_back` or `released` gets its clean-up; `blocked` holds the agent; `pending_load` goes on to the loader.

**One transition at a time.** A fresh-start request that arrives while a transition is open is left pending, not refused, and is handled when the transition ends, including after a rollback.

**Every hold has its own identity.** Whenever the wrapper holds an agent (a blocked transition, an unreadable session record, or a decisions conflict), it writes `state/<agent>.fresh-hold` (proposed): a hold id (`fh-` and 12 hex digits), the reason, the wrapper generation that made it, the time and, when there is one, the transition id. The file lives outside the session record, so it survives when that record is damaged; `status` shows the hold id. **At every start the wrapper reads the hold file before the session record.** A hold holds the agent whatever the session record says, even when that record is missing, until the matching release; a wrapper that starts again keeps the same hold id.

**Releasing a held agent** cannot use the request slot, because today's `write_fresh_request` refuses a second marker while one is pending. The release is a separate marker, `state/<agent>.fresh-release` (proposed), which only a lead or the operator-facing agent can write, with `session fresh --for <agent> --release <hold-id> --no-handover`.
- It names the hold, so it releases nothing else. A release whose id is not the current hold's, or that arrives when no hold exists, is refused, recorded and cleared.
- Only the active wrapper takes it, and it takes it before any pending request.
- **When the hold belongs to a blocked transition,** the release resolves that transition first, in this order, each step safe to repeat:
  1. one save sets the transition's state to `released`, an override that is terminal, with the release's id and the hold id;
  2. the new conversation is started without a note, and the prompt says the facts were not checked, unless a complete facts read passes;
  3. the transition gets the terminal clean-up described above (its event appended, then the field cleared);
  4. the hold file is removed, and last the release marker is cleared.

  A start that finds a transition in `released` with this hold's id continues the release at the next step; it never holds the agent again. A pending request is left for afterwards.
- **For an unreadable session record, the order is fixed,** so that a crash at any point leaves the agent held:
  1. **The hold first.** The wrapper writes the hold file, with the reason `session_record_unreadable` and the damaged record's size and SHA-256, and flushes it to disk. If the hold cannot be written durably, the original record stays where it is, nothing is dispatched, and the wrapper stops with a plain error; the next start tries again.
  2. **Then the quarantine.** It copies the damaged bytes to `<agent>.wrapper-session.damaged-<hold-id>.json`, checks the copy against the fingerprint in the hold, and only then removes the original. If the original is already gone, a matching copy shows that this step finished.
  3. **The release** writes a new session record that names the hold id it was released from, then removes the hold file, then clears the release marker, in that order. The damaged copy is kept for inspection.
  4. **Every step can be repeated.** A start that finds the hold reads which steps are done (copy present and matching, original gone, new record naming this hold) and does only the next one. A new record is never written twice for one release.

## 7. The loader check

The note is checked twice, and the change of conversation happens only between the two checks.

### Before the change (when the request is applied)

The handler reads the newest sealed note of the conversation that is about to end and checks:

1. the file exists, reads as JSON and has `format` 1;
2. `agent` is this agent;
3. `conversation` is the conversation that is about to end;
4. `record_sha256` matches the record's canonical form and what the session record names, and `note_sha256` matches the text;
5. `note_bytes` is at most 3,200;
6. **freshness:** for the agent's own request, the note was sealed at the conversation's newest finished turn, and that is the turn that wrote the request (section 8, guard `handover`). For a lead's request and for the automatic reasons (section 9), the newest sealed note of the conversation is used, with its age in turns shown beside it.

It also needs a complete facts read (section 5).

**If a note check fails, nothing changes.** The marker is cleared with the outcome `refused_handover_<check>`, `status` warns, and the conversation continues. A lead who wants a start with nothing says so with `--no-handover`; the agent cannot use that flag for itself.

**If everything passes,** the handler applies the change as today (backup first, then reset, then clear the marker), and the same save records the transition (section 6) with `state=pending_load`.

### Before the first message of the new conversation is processed

1. **The order changes:** `make_drive` and `make_cadence_drive` apply a pending request before they assemble the prompt, not after. Only then can the prompt know that the conversation is new.
2. With a transition in `pending_load`, the wrapper reads the named note and repeats every check of the first one (format, agent, conversation, turn, size) against the transition's `handover_record_sha256`, so a change to any field is caught, not only a change to the text. It also runs the facts read again.
3. **Both pass:** the prompt gets two blocks. The facts block holds what the wrapper read at this moment: why the conversation is new; the note's id, its age in turns and what changed since its `checkpoint`; every reply the agent owes, every reply waiting for it and every request it still waits on; whether its final reply to the current message's request has already landed; and the branch, commit and changed files of the agent's working folder (`checkpoint.collect_git_state` on the folder the agent runs in, not the project root). The note block follows it.
4. **The facts read is incomplete:** the message waits (section 5).
5. **The note check fails** (the file was deleted or altered after the change): the wrapper does not run a new conversation without its note. A requested transition whose old conversation can be resumed rolls back (section 6); any other becomes `blocked` and holds the agent. Either way the liaison is told once.
6. If the first turn of the new conversation fails, the transition stays in `pending_load`, so the retry gets the note again (a failed first Claude turn already gets a new session id today; it replaces `to_conversation`).

## 8. The trigger and its guards

### The measurement belongs to one conversation

At the end of every finished turn, the wrapper records in the session record (new fields, proposed):

- `conversation_id`: the Claude session id the reading belongs to;
- `conversation_turns`: finished turns in this conversation, set to 0 by every transition;
- `conversation_context_tokens` and `conversation_context_at`: the input side (input + cache read + cache write tokens) of the turn's last **complete** model call, by the W0 report's completion rule, read from that call's `message_start`. It is recorded only when the dispatch passes the rule's cross-check (its complete calls agree with `num_turns` and `result.usage`) and its final call is complete. Otherwise the turn records no new reading, and the old one keeps its own time, so a missing or conflicting reading can never authorise a fresh start. It is never read from an `assistant` event;
- `conversation_baseline_tokens`: the reading after the conversation's first finished turn (that turn's last complete call, with the dispatch's cross-check passed), recorded only for a conversation whose first turn the wrapper saw start; for any other conversation it stays absent;
- `conversation_first_message_id`: the first message the conversation handled (used in section 5).

The trigger never uses `turns_total` and never uses the capacity snapshot. A reading whose `conversation_id` is not the current conversation counts as no reading.

### The two marks

| Mark | Starting value for Claude | Effect |
|---|---|---|
| Note mark | 100,000 tokens | the prompt shows the size and asks for a note (section 4) |
| Fresh-start mark | 150,000 tokens (today's `conversation_warn_tokens`) | the prompt also advises the agent to ask for its own fresh start |

Both are set per agent in the agent's `supervisor.json` entry, under a new `self_compaction` object. The object also switches the pilot on for that agent; without it, nothing in this design runs.

### The guards on the agent's own request

When the request came from the agent itself, the handler applies it only when all of these hold. The first one that fails is named in the outcome (`refused_<guard>`).

1. **`measured`**: a reading of the current conversation exists, from one of its finished turns.
2. **`min_size`**: the reading is at least 60,000 tokens. Below that, a new conversation with the standing prompt, the facts and the note saves too little to be worth the lost context.
3. **`growth`**: the reading is at least twice `conversation_baseline_tokens`. A new conversation that starts large (a long standing prompt and note) can therefore never ask again at once. This is the guard against fresh starts that repeat without new growth.
4. **`cooldown`**: at least 10 finished turns in this conversation, and at least 60 minutes since `fresh_last_applied_at`.
5. **`daily_cap`**: fewer than 4 entries of `fresh_applied_times` in the last 24 hours.
6. **`handover`**: the note check of section 7 passes, and the request was written in the turn that sealed the note. For this, `session fresh` records the turn id it finds in `AGENTTALK_TURN_ID` (proposed; the wrapper sets it for the child, next to `AGENTTALK_SELF`). A request from a turn that then failed names a turn that never finished, so it is refused.
7. **`turn_answered`**: the request that this turn handled no longer owes a reply from this agent, according to the facts read. So a fresh start never follows a turn that used up a task without answering it (section 10).
8. **Today's conditions stay:** only between turns, only by the active wrapper, only after the backup copy succeeded, and only when no transition is open (section 6).

A complete facts read (section 5) is needed as well; when it is incomplete, the request waits rather than being refused.

A refusal clears the marker. There is no automatic retry: the next prompt shows the refusal and the guard, and the agent may ask again on a later turn when the guard allows.

**Requests by a lead or the operator-facing agent** keep step 1's meaning: a person or the lead decided. Guards 1 to 5 and 7 do not stop them, but they are evaluated and logged, and the transition counts. On a pilot agent the note check and the facts read apply to them too, unless `--no-handover` is given.

### When the conversation is already too large to write a note

The design never asks an oversized conversation to summarise itself: that turn would fail like the others.

- **What counts as too large:** the conversation's last turn failed as "prompt too long" or "request too large" (the existing failure classification in `wrapper/run.py`), or its reading is above 85% of the model's context window. The window is taken from the stream if Claude Code reports it there (checked in step 0); otherwise from the agent's `too_large_tokens` setting, and without that setting only the failure counts. A fixed default would be wrong both ways: agents on the 1-million-token window run far above 85% of 200,000.
- **Then:** the prompt no longer asks for a note, and `status` warns `handover=too_large`. The way out is a lead's fresh start, or the self-heal after two failures (section 9). Both load the newest valid sealed note of that conversation, with a plain statement of its age: written N turns before the end, so the files and the bus may have moved on, and the facts beside it are current.
- **Why a valid note normally exists:** the note mark (100,000) is far below the fresh-start mark and the window, so a sealed note at most five turns old normally exists before the conversation gets this large.

## 9. Every way a conversation changes on a pilot agent

No path may start a new conversation on a pilot agent without the newest valid note and a complete facts read. Where that cannot be met, the agent is held for a person.

| Path | Where today | On a pilot agent |
|---|---|---|
| A fresh-start request (the agent, a lead, the operator-facing agent) | `apply_fresh_request` | a transition `fresh_requested`, with the guards of section 8 for the agent's own request and the checks of section 7 for every request |
| Two failures that belong to the conversation (the self-heal) | `make_drive` and `make_cadence_drive` in `wrapper/run.py`, through `reset_claude_session` | a transition `resume_unavailable`. It needs the newest valid sealed note of the old conversation (of any age; the age is shown) and a complete facts read. Without them the agent is held: the message waits, the liaison is told once (today's continuity-loss notice, saying why), `status` shows `fresh=blocked(<reason>)` with the hold id, and a lead releases it with `session fresh --for <agent> --release <hold-id> --no-handover` (section 6) |
| A changed model or effort setting at relaunch | `reconcile_runtime_fingerprint` in `wrapper/session.py` | a transition `runtime_config_changed`, with the same requirement and the same hold |
| A failed first turn of a new conversation | `make_drive` (`fresh_session_turn_failed`) | inside an open transition: the same transition, with the new session id as `to_conversation`; the note stays pending. Outside one (the agent's very first conversation): nothing to carry, as today |
| An unreadable session record when the wrapper starts | `load_session` in `wrapper/session.py` starts fresh, and treats a missing record as a first start | a hold with its own id is written and flushed first; only then is the damaged record copied aside and the original removed (section 6). Every start reads the hold before the session record, so a missing record after a crash never looks like a first start. The agent is held and the liaison is told once; it never starts fresh silently, and the release with the hold id starts a new record |
| A Codex reset | `mark_resume_unavailable` | not in the pilot |

Guards 1 to 5 never stop an automatic transition, because the old conversation cannot go on or the operator changed the model. Automatic transitions are counted like all others. If the note check fails after an automatic transition was applied, it becomes `blocked`; it is never rolled back (section 6).

## 10. Delivery, obligations and the crash tests

### How a message is kept until it is handled, today

- **Every kind except an admitted question:**
  - the wrapper loop records an attempt before each turn (`record_attempt_start`, written ahead);
  - it moves the cursor (`recv_api.commit`) only after a clean turn, or when it dead-letters the message: by default after 3 failures that are the message's own fault, or 20 failures of unclear cause, and for failures of the infrastructure only after at least four hours and 100 attempts;
  - a crash during a turn leaves the cursor where it was, so the message is delivered again on restart, with a rejoin block.
- **A clean turn moves the cursor whether or not the agent's reply landed.** A task that a turn used up without answering is not delivered again. Its thread stays owed on the bus, and only the bus shows it.
- **A redelivered message whose reply already landed** (the reply landed, then the wrapper stopped before moving the cursor) is driven again.
- **The commit gate changes this only for admitted questions:** with `AGENTTALK_COMMIT_GATE_POLICY` set, a question that is not a consult moves the cursor only with proof that its answer landed, and a redelivered question whose answer already landed is not driven again (`resolve_landed_response`). Every other kind is "detection log-only".

### The pilot's policy

1. The pilot changes no delivery rule, and it works with the commit gate on or off.
2. **Guard `turn_answered`** (section 8): the agent's own fresh start is refused while the request its turn handled still owes a reply.
3. **Every owed reply goes into the facts block,** including a task that a clean turn used up without answering, because the facts read lists every thread the agent owes.
4. **A redelivery after a landed reply is named:** the facts block says that the final reply to the current message's request has already landed, and the standing rule says not to answer twice.
5. **No list of obligations ever comes from the note,** from the checkpoint's best-effort read, or from an incomplete facts read.

### The crash and edge matrix

**Change and load.**

| # | Crash or case | What must hold after the wrapper starts again |
|---|---|---|
| K1 | after the agent wrote the draft, before the turn finished | the draft is not sealed; the message is delivered again; a request from that turn is refused (`handover`); the conversation continues |
| K2 | after the note was sealed, before the session record was saved | the record does not name the note, so a request is refused (`handover`); the message is delivered again as today; the orphan note is pruned later |
| K3 | after the record was saved, before the request was applied | the next wrapper applies it at its first idle poll, with all guards and a complete facts read |
| K4 | after the backup copy, before the change was saved | today's rule: the marker stays and the request is applied again |
| K5 | after the change was saved, before the marker was cleared | today's rule: the saved request id matches, so only the marker is cleared |
| K6 | after the change, before the next message was processed | the transition is in `pending_load`; the next message is still in the inbox; its turn gets the note and the facts |
| K7 | during the first turn of the new conversation | the transition stays in `pending_load`; the retry gets the note again; the message is delivered again |
| K8 | the note file, or any field of its record, was altered or deleted between K5 and K6 | the second check fails; a requested transition rolls back (section 6), an automatic one becomes `blocked` |

**Rollback.**

| # | Crash or case | What must hold |
|---|---|---|
| R1 | after `rollback_started` was saved, before the restore | the next start finishes the rollback before dispatching anything |
| R2 | the backup file is missing | `blocked(backup_missing)`; no dispatch; one notice; a lead's release with the hold id releases it |
| R3 | the backup's fingerprint or session id is wrong | `blocked(backup_corrupt)`, as R2 |
| R4 | the restore write fails and did not land | the record on disk still says `rollback_started`; tried again on the next poll; no dispatch meanwhile |
| R5 | the restore write lands, then the flush to disk fails | the record on disk is read again and says `rolled_back`; it is adopted |
| R6 | interrupted before the decisions file was appended | the session record is the authority; the report shows the gap |
| R7 | a new fresh-start request arrives while a transition is open | it stays pending and is handled after the transition ends |
| R8 | a rollback inside the 24-hour window | the rolled-back change still counts; the accounting is the same after the restore and after a restart |
| R9 | an agent blocked with a fresh-start request pending; a lead writes the release | the release is taken first; the pending request is handled afterwards; a release that names another hold or another agent is refused |
| R10 | a crash after the append and before the clearing | the next start finds the line by number, event id and fingerprint, does not append it again, and clears the transition; the accounting is unchanged |
| R10b | a partial last line in the decisions file | the partial line is moved to a side file; the exact line is appended once |
| R10c | a different line already holds the sequence number | `blocked(decisions_conflict)`; nothing is overwritten; one notice |
| R10d | the decisions file was rotated between the append and the check | the line is found in the older file and not appended again |
| R11 | the second check fails after an automatic transition | `blocked`; no rollback; the runtime fingerprint stays the new one |
| R12 | a blocked transition while a fresh-start request occupies the request slot | the release with the hold id is taken first; the pending request is handled afterwards |
| R13 | a release naming an old hold id, another agent's hold, or no current hold | refused, recorded and cleared; the current hold stays |
| R14 | the release of a hold made by a blocked transition, with a stop after each of its four steps | the transition becomes `released`, then is cleared; every restart continues the release at the next step and never holds the agent again |

**Accounting.**

| # | Case | What must hold |
|---|---|---|
| A-1 | 4 applied, then 25 refused, within 24 hours | the next own request is refused `daily_cap` |
| A-2 | A-1 with a wrapper restart in between | the same |
| A-3 | a lead's request when the limit is reached | applied and counted; the agent's next own request is refused `daily_cap` |

**Facts read.**

| # | Case | What must hold |
|---|---|---|
| F-1 | more than 512 message files, the owed task in file 600 | the read is complete and lists the task |
| F-2 | the read takes longer than its time limit | `timeout`; the request waits; the first message of a new conversation waits; after two hours, refused or blocked |
| F-3 | one rejected message file | `rejected_files`, as F-2 |
| F-4 | signing enforced, key unreadable | `signing_unavailable`, as F-2 |
| F-5 | compaction moved messages this conversation handled | `history_compacted`, as F-2 |
| F-6 | a published task opener deleted, with unrelated messages still present | `missing_messages`, as F-2 |
| F-7 | messages compacted before this conversation began | complete: their ids are found valid in the archive |
| F-8 | the publication order unreadable or not durable | `order_unavailable`, as F-2 |
| F-9 | the agent's own request waits on an incomplete read while a second message is queued | the second message is held; the request's note stays the newest; the request is applied once the read completes |
| F-10 | the wrapper stops during the facts read for a held message | no attempt was recorded; after the restart the read runs again |
| F-11 | messages between other agents are compacted after this conversation began | `history_compacted` does not fire |
| F-13 | a message addressed to this agent, but never handled in this conversation, is compacted | `history_compacted` does not fire |
| F-14 | a broadcast this conversation handled is compacted | `history_compacted` fires |
| F-15 | the membership list is unreadable | the broader rule applies: an archived message to or from this agent since the conversation began fires the guard |
| F-16 | the pilot is switched on in the middle of a conversation | before the activation, the agent's own request is refused by the first failing guard (`measured` before any reading, then `growth`: no baseline) and the broader rule applies; after the activation, the baseline is the reading after the new conversation's first finished turn, also when that turn made several calls, and the list is complete |
| F-17 | a membership list created after its conversation began, or with a gap in its sequence numbers | counted as incomplete; the broader rule applies |
| F-18 | a transition, then a rollback | the old conversation's own list is selected again; if that file is gone, the broader rule applies |
| F-19 | a failed attempt at A, a successful A, a successful B, then B's entry lost (valid header, valid JSON) | the list is incomplete: its last sequence number is below `membership_high_water` and B's finished turn has no entry; the broader rule applies |
| F-20 | a wrapped lead with cadence turns between message turns | the cadence turns add no entry and do not make the list incomplete |
| F-21 | the membership entry cannot be written before a turn | the turn does not start; the message waits; no attempt is charged |
| F-12 | a dispatch with a complete call followed by an incomplete final call | no new size reading is recorded; the agent's own fresh start cannot be authorised by it |

**Every path** (section 9).

| # | Case | What must hold |
|---|---|---|
| T1 | two failures that belong to the conversation, with a valid note, an older owed request and a second queued task | a transition `resume_unavailable`; the first prompt lists the older owed request and holds the note; the queued task is delivered after |
| T2 | T1 without a valid note | held; no dispatch; one notice; both tasks kept |
| T3 | a model change with a valid note | a transition `runtime_config_changed` |
| T4 | a model change without a valid note | held, as T2 |
| T5 | a failed first turn inside a transition | the same transition, with the new session id; the note still pending |
| T6 | an unreadable session record at start | held with a hold id, the damaged record kept aside, never a silent fresh start; the release with that id starts a new record |
| T6a | a stop before the hold is written | the original record is still in place; the next start begins again at step 1 |
| T6b | a stop after the hold is flushed, before the copy | held under that hold id; the original record is still in place |
| T6c | a stop after the copy, before the original is removed | held under the same id; the copy matches the fingerprint; the next start removes the original |
| T6d | a stop after the quarantine, before the release | the session record is missing, but the agent is held under the same id; it is not treated as a first start |
| T6e | a stop during the release, after the new record and before the hold is removed | held until the same release is taken again, which removes the hold without writing a second record |
| T6f | the hold cannot be written (for example a full disk) | the original record stays; nothing is dispatched; a plain error |

**Delivery through the real loop.** These run `run_loop` with a real store and cursor, and a drive built by `make_drive` with a fake Claude child:

| # | Case | What must hold |
|---|---|---|
| D1 | a task whose turn finishes cleanly without a landed reply | the cursor moves; the agent's own request is refused `turn_answered`; the next fresh start's facts list the task as owed |
| D2 | a task whose reply lands, then the wrapper stops before moving the cursor | the task is delivered again; a pending request is applied at turn start; the facts say the reply already landed; the cursor moves once |
| D3 | D2 for a question with the commit gate on | not driven again (today's rule); the pending request is applied at the next real turn |
| D4 | D2 for a question with the gate off | as D2 |
| D5 | a crash during the first message of a new conversation | the message is delivered again; the note is still pending; no attempt is lost |

**Mutation check:** removing any single guard, any completeness condition, the rollback's field selection, or the apply-before-assemble order makes at least one test fail.

During the live pilot (section 13), K1, K3 and K6 are also drilled on a scratch copy, by stopping the pilot's wrapper process by its exact process id.

## 11. The rule for the agent's instructions

Proposed text, rendered in the standing rules only for an agent whose wrapper supports the pilot and has it switched on, and added to `docs/AGENT-MANUAL.md` next to "Context lifecycle":

> **Your conversation's size.** When this turn's prompt shows a CONVERSATION SIZE block:
> - **"Handover note due":** make writing the note your last step before the reply, in the draft file the block names. At most 3,200 bytes: what is done, what is next, open questions, decisions and why, commands that worked. No secrets, keys, host values or client names.
> - **"Fresh start advised":** when the note can describe where your work stands, write the note, then run `agenttalk session fresh --for <you> --reason "conversation at <N> tokens"`, then send your reply to this message as usual. Your wrapper starts you on a new conversation after this turn if its checks pass; a fresh start is refused while this message is unanswered, and a later prompt tells you if it was refused and why.
> - Never ask for your own fresh start without writing the note in the same turn, and never in a turn you will not finish.
> - **After a fresh start,** the note is what your earlier conversation believed. Check it against the facts block, the bus and the files before acting. The current message is your only instruction. If the facts say your reply to it has already landed, do not answer it again.
> - **No CONVERSATION SIZE block** means your runtime does not support this. Do not ask for a fresh start for yourself; tell your lead if you have been told that your conversation is large.

## 12. Older runtimes

- **The capability check is in the prompt.** The CONVERSATION SIZE block appears only when the wrapper can seal notes and the pilot is on for the agent. No version number needs to be compared.
- **A lead checks an agent with `status`.** On a pilot runtime the agent's row shows `handover=` and `rotations=`; their absence means an older runtime or the pilot switched off.
- **What is enforced and what is only guidance.** The guards of this design run only in a pilot wrapper. On a 0.102.0 wrapper, `session fresh` is applied without guards, as today, whoever asks; the rule in section 11 tells an agent without the block not to ask, but nothing stops one that ignores it. That is today's behavior, unchanged by the pilot. A `turn_id` that a newer command adds to the marker is ignored by a 0.102.0 wrapper.
- **Runtimes before 0.102.0** have no `session fresh`. The supported way is to upgrade the runtime ("Install a fixed runtime" in `docs/OPERATIONS.md`) and restart that one agent's wrapper through its supervisor. Until then, the agent writes its own note before a reset is planned (the "Context lifecycle" paragraph of `docs/AGENT-MANUAL.md`).
- **Never** `agenttalk reset` (it resets the whole bus), and never edit the session record of a wrapper that is running. Only an agent's own wrapper changes its session record.

## 13. The pilot: measure first

### The pair

**Claude Code on the normal Anthropic subscription** (the default backend, not the `ovh-qwen` gateway profile).

- The turn journal records token counts only for Claude (`_result_usage` reads Claude's `result` event).
- The measured cost problem of section 1 is on Claude agents.
- Codex reports its usage differently and is left out of the pilot.

**Agents:** the pilot agent (a Claude developer agent on this desktop) and one control agent on the same model. Both run with the new telemetry (below) from the baseline week on.

### The telemetry the report needs (work order W2)

Today's journal keeps four token totals per dispatch; it keeps no per-call context and no call count. So before any baseline week, the journal gets a schema version 2 (proposed) whose `dispatch_ended` event adds:

| Field | Meaning |
|---|---|
| `model_calls` | the number of complete model calls in the dispatch, by the W0 report's completion rule (a call is identified by its `message_start`; start, delta and stop in order). Interrupted or conflicting calls are counted apart and never added. A dispatch whose complete calls disagree with `num_turns` or `result.usage` is marked conflicting. It is never a count of `assistant` events: one call can produce several |
| `calls_with_usage`, `calls_without_usage` | how many calls reported usage, and how many did not |
| `context_hist` | the input side of every call (input + cache read + cache write), counted into 15 fixed buckets with edges at 10, 20, 40, 60, 80, 100, 125, 150, 200, 300, 400, 600 and 800 thousand and 1 million tokens; bounded, so one event stays under the journal's 4,096-byte line limit |
| `context_max`, `context_sum`, `context_last` | the largest, the total and the last of those per-call values |
| `note_cost` | for a dispatch that wrote a note: for each complete call that issued a write of the draft file, that call's output tokens (reasoning tokens included once, as part of output), plus the input side, both kinds of cache write and the cache read of the complete call right after it. Several writes add up; a last write with no following call counts its output only. `unknown` when a write cannot be tied to a complete call (a shell command wrote the file, or a call has no usage). Each kind of token is priced once, by the formula below; the result is an estimate of the note's extra cost and is labelled so |
| `transition` | `none`, or the reason code of a transition this dispatch started or loaded |
| `conversation_seq` | the number of this agent's conversation (1, 2, 3...), never the session id, so the journal keeps its rule of holding no identifiers that are not on the bus |

**Missing and dropped data:**

- The journal can drop events; each event has a sequence number, and the stream records how many were dropped.
- The report compares the dispatches in the journal with the attempts the wrapper recorded for the same messages. The share it finds is the coverage.
- **A measure counts only with at least 95% coverage** in its window, at most 5% of calls without usage, and, for B7, at most 20% of note dispatches with `note_cost` unknown. Otherwise the measure is **inconclusive**, and an inconclusive measure is never a go.
- **The cost gates need complete data.** For A1, B5 and B7, missing cost can never help a go: a count of missing calls says nothing about how expensive they were, and no observed figure bounds a call that was not seen. These gates pass only on complete, reconciled cost data for every dispatch they cover, on both sides of each comparison, including B5's control agent: every dispatch present, its complete calls agreeing with its `result.usage`, and every note's cost known. Any missing or unknown cost makes the gate inconclusive; no estimate fills the gap.
- **The safety measures need every transition.** The coverage rule qualifies only the cost and size estimates. B1, B2 and B3 are judged from the transition evidence (section 6): a transition without its evidence, or a gap in the decisions file's sequence numbers, makes them inconclusive.

**Cost per work order:** a work order's cost is the sum over every dispatch tagged with its `work_item`, of every kind and every attempt, failed ones included. Dispatches without a `work_item` are reported apart. **When a work item counts as completed:** when every obligation of the item is closed, that is, every request opened under that `work_item` (tasks, questions, reviews, follow-up exchanges) has its final reply and none is still owed. **Only a terminal reply event counts:** a final reply to that request on the bus, dated before the observation cut-off. A manual close (for example `ack --to-request`, which the thread derivation treats as closed through its `closed_rids` override) does not complete a request; such an item stays open for this rule and is reported as "closed without a final reply". A later message's final reply does not close an earlier one. The item is assigned to the window in which its last obligation closed, and all its dispatches count towards it, whatever window they ran in. **A reopen:** a new request under the same `work_item` after it closed takes it out of the completed set, the earlier completion is recorded as superseded, and it counts again only when all its obligations close again. The report is computed at a fixed observation cut-off (the end of phase B plus 24 hours), applied to the reply events themselves; nothing after it changes the result, and an item still open at the cut-off is reported as open, with its cost. When less than 90% of a window's dispatch cost can be tied to a `work_item`, B5 is inconclusive. Messages that were dead-lettered or failed delivery are reported apart, with their cost, and count in B6.

### Request size (W0, item f)

The accepted reshape asks for the size of the requests themselves, measured separately. A transcript's size is not that; it is not used.

- **The pass rule in step 0:** an observer approved by the operator records the byte size of every request this agent sends, without keeping the request's content or headers.
- **Candidates for this pair:**
  - Claude Code's own telemetry, if it reports request sizes (checked in step 0);
  - a pass-through on the local machine through `ANTHROPIC_BASE_URL` that counts bytes only. It would sit between the agent and its subscription's credential, so it needs the operator's explicit approval and its own security read before it runs.
- **If neither is available or approved, the pilot says so plainly:** request size is not measured, and the pilot makes no claim about oversized requests.
- **Where the reported failure happened:** the "Request too large (max 32MB)" of 2026-10-18 was on a Qwen agent behind agenttalk's own gateway. That gateway's front already reads each request's `Content-Length` and refuses one above its limit (`ovh_gateway_front.py`). Recording that size there is the natural observer for that backend, but that backend is outside this pilot; it is a separate item.

### Phase A: paired bench (one to two days, under the starting conditions of the W0 report; the budget is approved)

Equivalent work, run both ways:

1. Pick 10 work orders the pilot agent has **not** seen: orders done by another agent of the same kind, each with a check that says whether it was done right (the tests or reads the order named). An order the pilot agent already did would let arm R recall its own solution.
2. For each order and **each arm**: its own new scratch store and its own clean worktree at the order's base commit, so neither arm can see the other's code changes, test output or replies. Replies go to that arm's scratch store only, never to the live bus.
3. **Arm R (resume):** continue a fork of the pilot agent's current conversation with the order (Claude Code's `--resume <id> --fork-session` starts a copy and leaves the original untouched; checked in step 0).
4. **Arm F (fresh with note):** in another fork of the same conversation, ask for the handover note (its cost is counted to arm F), then start a new conversation with the standing rules, the facts block, the note and the order.
5. Same model, effort and standing rules for both arms, with the new telemetry on.
6. **The sample:** ten valid pairs, five starting with each arm. A pair that misses the W0 report's starting conditions is kept and reported apart, with its cost, and replaced by a new unseen order within the approved budget. If the budget cannot give ten valid pairs, A1 and A3 are inconclusive.

### The baseline week, then phase B

- **Baseline (work order W3):** five working days with the new telemetry on for both agents and the pilot switched off.
- **Switching the pilot on (activation):** the baseline week runs with the pilot off, so a pilot agent enters phase B in the middle of a long conversation that has no baseline reading and no complete membership list. Phase B therefore begins, for each pilot agent, with one measured fresh start:
  1. the pilot is switched on in the agent's `supervisor.json` entry;
  2. the agent's next prompt asks for a handover note at once, whatever the conversation's size;
  3. once that note is sealed, the lead requests the fresh start (`session fresh --for <agent> --reason "pilot activation"`), with the note check of section 7;
  4. the new conversation is the first fully observed one: the reading after its first finished turn sets `conversation_baseline_tokens` (section 8), and its membership list starts with a header and a completeness boundary (section 5).

  Until that activation, `conversation_baseline_tokens` is absent, so the agent's own fresh-start requests are refused by the first guard that fails (`measured` while there is no reading yet, otherwise `growth`), and `history_compacted` uses the broader fallback. The activation transition is recorded as such and does not count towards B8.
- **Phase B:** five working days in which the pilot agent does its normal work with the pilot switched on, from its activation, compared with its own baseline week and with the control agent over the same days.

### What is counted, each on its own

| Quantity | Source | Use |
|---|---|---|
| Context tokens per model call | `context_hist` | the mechanism: does the conversation stay small |
| Tokens per dispatch, by kind (input, cache write, cache read, output) | the journal's totals | cost, through the proxy below |
| **Input-equivalent tokens:** input + 1.25 × five-minute cache write + 2 × one-hour cache write + 0.1 × cache read + 5 × output (the one-hour weight corrected by W0) | computed from the row above, over complete calls only | the primary figure for every comparison (the lead's decision): a proxy for what the turn takes from the allowance, using the provider's price ratios between the kinds; it is not a bill. Claude Code's `total_cost_usd` is kept as a list-price cross-check (W0 report), in the same unit: the formula's tokens times the base input price recorded for that model and price-table version, against the list increment of the same complete calls. The gap is measured against the list figure. With a zero or unknown list figure, or unknown call coverage, there is no cross-check. A gap above 10% is flagged, never a gate |
| Model calls per work order | `model_calls`, summed over attempts | whether fresh conversations need more steps |
| The note's own cost | `note_cost`, priced as above | counted against the saving |
| The subscription's weekly percentage | the capacity snapshot | shown as a sanity check, never a gate: it is coarse and shared |
| Request bytes | the observer, if W0 item f passes | reported as the median, 95th percentile and largest, before and after; not a gate |
| Transitions | `fresh_applied_times` and the decisions file | applied, refused by which guard, waiting, rolled back, blocked |
| Failures | the journal's failure classes | by class |
| Obligations | the facts read, just before and after each transition | lost or kept |

### Go or no-go for more agents

Extend to more agents (and then to Codex, the gateway backend and other systems, one at a time) only when **all** of these hold and none is inconclusive:

| # | Measure | Go when |
|---|---|---|
| A1 | Phase A cost: median input-equivalent tokens per order, arm F including its note, against arm R | F ≤ 0.6 × R |
| A2 | Phase A work | arm R passes the order's check in at least 7 of the 10 valid pairs, and arm F passes in every order arm R passes; with fewer than 7 successful R arms, A2 is inconclusive. A1 and A3 are computed over the pairs where both arms passed (the quality-comparable pairs), and need at least 7 of them |
| A3 | Phase A steps: median `model_calls` per order | F ≤ 1.3 × R |
| B1 | Lost obligations | zero, judged from the transition evidence; inconclusive if any transition lacks it |
| B2 | Wrong notes loaded (another agent, conversation or turn, or a record fingerprint mismatch that was not stopped) | zero; every load checked, judged from the transition evidence |
| B3 | Loops | zero own fresh starts applied without the growth guard; at most 4 applied per day; zero applied on a missing or old reading |
| B4 | Context tokens per model call, median, from `context_hist` (read to its bucket: the pilot week's upper bucket edge against the baseline's lower edge, so the rounding can only count against the pilot; a median in the open top bucket, 1 million tokens and above, makes B4 inconclusive) | at most 40% of the pilot agent's baseline week |
| B5 | Input-equivalent tokens per completed work order (grouped by `work_item`), median, all attempts included | at most 0.75 × the baseline week, and better than the control agent's change over the same days |
| B6 | Failed dispatches as a share of all dispatches; and dead-lettered or failed messages as a share of all messages | each at most 2 percentage points above the baseline week, judged apart |
| B7 | The note's own cost | at most 10% of the input-equivalent tokens of the dispatches that wrote one |
| B8 | Enough data | at least 10 applied transitions, not counting the activation, and 100 dispatches; otherwise extend phase B by up to five days, then decide |

**Stop at once** (the challenge's kill signals), switch off the agent's own requests and keep only the measurement when:

- fresh starts repeat without new growth;
- a new conversation misses an obligation;
- recovery needs the oversized conversation to summarise itself;
- the net cost does not improve (B5 fails at the end of phase B).

## 14. Work orders for the build

Each work order is built, read by another agent, and merged on its own. W5 to W8 and W10 also get a failure-path review.

| # | Work order | Size | Needs | Done when |
|---|---|---|---|---|
| W0 | **Step 0 spike** (throwaway): check six assumptions, each with a written pass rule. (a) Claude Code's stream gives `usage` with the three input fields on every `assistant` event; (b) `--resume <id> --fork-session` leaves the original session unchanged; (c) applying the fresh-start request before assembling the prompt breaks no existing test; (d) `AGENTTALK_TURN_ID` reaches the child on both backend paths of `_child_env`; (e) whether the stream reports the model's context window; (f) an approved observer records request sizes without content (section 13) | half a day | none | each assumption passes, or the design is changed before W1; for (f), either an approved observer works or request size is marked not measured |
| W1 | **The measurement belongs to one conversation:** the new session-record fields, read from the stream by the completion rule, reset by every transition; the size warning in `status` and the dashboard uses them first and says "in this conversation" | half a day | W0 | tests for each reset path and F-12; closes #475's open warning part |
| W2 | **Telemetry, journal schema 2:** the fields of section 13, the note-call detection, coverage and the treatment of missing and dropped data; the call completion rule and the cost lineage of the W0 report | 1 day | W1 | schema and bucket tests; a fixture journal with drops, missing usage and an unknown note cost gives the expected coverage and inconclusive results; the W0 report's stream and lineage fixtures pass, all before W3 |
| W3 | **Baseline week** for the pilot and control agents, the pilot switched off | 5 working days, little effort | W2 deployed | coverage at least 95% |
| W4 | **Notes:** the CONVERSATION SIZE block and draft path on pilot agents, sealing after a finished turn, the sealed record and its `record_sha256` (one canonical form shared with both checks), the sealed files and their retention, the size limit, `handover=` in `status` | 1 day | W1 | tests for sealed, refused and unsealed notes; a change to any metadata field, not only the text, fails the checks |
| W5 | **The facts read:** the complete read, the seven completeness conditions of section 5, the gate before the attempt record, waiting and holding with back-off, `turn_answered` | 1 day | W1 | F-1 to F-21 and D1 pass |
| W6 | **The transition record and the guards** in `apply_fresh_request`: `fresh_transition`, the accounting, the decisions file, guards 1 to 8, `turn_id` in the marker, `--no-handover`, `rotations=` in `status`, the too-large warning | 1 day | W4, W5 | one test per guard; A-1 to A-3 |
| W7 | **The loader and the rollback:** apply before assemble in both drives; both checks; the facts block and the note block; the rollback steps, the terminal clean-up, the hold file and the release, and the start-up check of section 6 | 1.5 days | W6 | K6 to K8 and R1 to R14 |
| W8 | **Every path:** the self-heal, the model change, a failed first turn and an unreadable record go through the transition or hold the agent, with a hold id written before any quarantine | 1 day | W7 | T1 to T6f |
| W9 | **The rule text:** the standing rule (pilot agents only), `docs/AGENT-MANUAL.md`, the README row for `session fresh` with `--release <hold-id>`, the changelog | half a day | W8 | docs tests pass |
| W10 | **The rest of the matrix** of section 10 (K1 to K5, D2 to D5), with its mutation check | 1 day | W8 | all cases pass; the mutants fail |
| W11 | **The pilot report:** a read-only script, kept out of the package, that reads the journal, the session records, the decisions files and the bus, and prints the table of section 13 with coverage and inconclusive marks, and the token formula against the list figure over the same calls (W0 report) | half a day | W2 | run on the baseline week; plus fixtures that must not give GO: one transition's evidence dropped, a gap in the decisions sequence, and nine excluded bench pairs with one passing; and a work item whose earlier task is still unanswered while a later review got its final reply must not count as completed; nor may a request closed only by a manual acknowledgement; and a run with missing cost in arm F, the pilot week or a note must be judged with the bounds of section 13, never by leaving the missing cost out |
| W12 | **Phase A** bench, under the starting conditions fixed in the W0 report (cold parent, both arms back to back, alternating order), each arm with its own store and clean worktree | 1 to 2 days | W10, W11 | A1 to A3 measured |
| W13 | **Phase B** live, with the three crash drills | 5 working days, little effort | W12 passes, W3 done | B1 to B8 measured |
| W14 | **The decision:** a short go or no-go record for the lead | half a day | W13 | the lead decides |

Each work order also carries the binding requirements of section 18. Build effort is about nine days (W0 to W2 and W4 to W11), up from six in the first version and well above the challenge's one to three days. The increase is what the read asked for: the complete facts read, the transition record and its rollback, every automatic path, the telemetry, and the delivery tests through the real loop.

## 15. How this fits #475, the roadmap, #490 and #178

- **#475:** step 1 shipped in release 0.102.0. Its open part is the warning: it does not describe the current conversation when the token reading is missing or old, because it then counts all turns ever. W1 makes the warning describe the current conversation.
- **Roadmap §6.11:** the operator approved three steps for conversations that grow too long. This pilot is a measured slice of step 2 (the note), plus the agent's own request. Step 3 (agenttalk choosing before each turn) waits for this pilot's go or no-go. Until then, the lead's rule stays: restart an idle agent on a fresh conversation once it passes about 300 turns.
- **#490 and #477:** the note's limit and its data framing follow #490 section 4, so #490's later steps can use the sealed format. This pilot differs in three ways:
  - notes are drafted in a file, not with a `handover write` command;
  - a note counts only once sealed at a finished turn;
  - the thread excerpt, cold reviews and the per-turn choice stay in #490.

  Three of #477's findings are touched here: 3 (the note is data), 5 (a failed turn's draft is never sealed, and the retry keeps working) and 9 (the facts read the agent's working folder).
- **#178:** the note never decides whether a work order is done; the bus does today, and #178's record will later.

## 16. The lead's answers

The lead answered the five questions of the first version on 2026-10-18:

1. **The pilot agent** is a Claude developer agent on this desktop. The first extension is the lead on the maintainers' second machine, after its runtime is upgraded to 0.102.0 (the upgrade is prepared).
2. **The marks** are 100,000 tokens for the note and 150,000 for a fresh start, as starting values.
3. **A lead's request when the note check fails** is refused unless `--no-handover` is given.
4. **The paired bench** is approved as a fixed budget.
5. **The pilot stays in its own file.**

## 17. What it does not do

- **No second controller.** The wrapper does not decide by itself to start a conversation fresh to save cost. The agent asks; today's fresh-start handler decides, with guards. The automatic paths that exist today stay, but on a pilot agent they follow the same rules or hold the agent (section 9). agenttalk choosing before each turn is #490's step 3, after this pilot.
- **No cold reviews,** no `--context` flag for senders, no fresh start per work item, no thread excerpt for older threads (#490).
- **Not in the pilot:** Codex, the `ovh-qwen` gateway backend, a lead that runs as an ordinary interactive session (the wrapper does not start it), and machines other than the pilot's.
- **Never** `agenttalk reset`, and never an edit of another running wrapper's session record.
- **No change to how messages are delivered,** and no dependence on the commit gate (section 10).
- **No promise** of a bounded cost per turn or per week. The pilot lowers the conversation's size and measures what that saves. The allowance reading is shown, not controlled.
- **The note is never authority:** not for "done" (#178), not for obligations and not for the roster.
- **No new stores** beyond the notes, the transition record and the decisions file: no project knowledge pack, no memory store per agent, no usage ledger.
- **No change to the message format.** The fresh-start marker gains an optional `turn_id`; the session record and the journal gain fields; nothing on the bus changes.
- **Nothing about idle wakeups:** the lead loop already spends no model turn on a quiet tick.
- **No claim about oversized requests** unless step 0 finds an approved way to measure request sizes on this pair (section 13).

## 18. Binding requirements from the reads

These come from three reads: the design's final read (tk-e78baa38e6a0), the W0 report's final read (tk-ac7c677dd860), and the automatic Codex reviewer's nine findings on pull request #531 (head `78a44dcc`). The lead accepted all of them as binding. Each row says what the build must do, which work order it binds, and where this document now says it.

| # | From | Rule | Binds | In this document |
|---|---|---|---|---|
| DF1 | design final read, P2 | A deleted message makes the facts read incomplete: compare the validated files with the durable publication order, under the publication locks. Test a published task opener that was deleted while other messages remain. Refined by CN3 and CN7 | W5 | section 5; F-6 |
| DF2 | design final read, P2 | Finish the rollback: a terminal clean-up for `rolled_back`, recovered after a crash on either side; a request queued during a transition goes ahead after a rollback; releasing a blocked agent has its own way in (`fresh-release`), tested through the loader, and leaves unrelated newer requests alone; no rollback after a model change (CN5) | W6, W7 | section 6; R9 to R11 |
| DF3 | design final read, P2 | Keep the evidence for the zero-loss claims: per transition, the completeness result, the obligation ids and their state, and the note's identity and check outcomes, without note text. A durable sequence number shows a lost final append. Coverage never certifies zero losses; a transition without its evidence makes B1 to B3 inconclusive; a report fixture that drops one transition's evidence must not give GO | W6, W11 | sections 6 and 13 |
| DF4 | design final read, P2 | Request size stays "not measured", an explicit exception for the pilot and expansion decision; no credential-bearing proxy without the operator's approval and a security read | W0, W14 | section 13; W0 report (f) |
| DF5 | design final read, P3 | Fix the arithmetic before the baseline, with fixtures: the note-cost cases (reasoning tokens, several writes, a last write with no following call, shell writes, repeated events, missing usage); each kind of token priced once and labelled an estimate; unknown stays unknown; B6's two shares judged apart; a B4 median in the open top bucket is inconclusive | W2, W11 | section 13 |
| WF1 | W0 final read, P2 | The old `model_calls` fallback is retired: the completion rule decides; the repeated-`assistant` fixture gives two calls; missing or conflicting data follows the coverage rules | W1, W2 | section 13, `model_calls` |
| WF2 | W0 final read, P2 | Ten valid bench pairs after exclusions, five starting with each arm; excluded pairs kept with their cost; replacements within the fixed budget; otherwise A1 and A3 are inconclusive. A fixture with nine excluded pairs and one passing pair must not give GO | W11, W12, W14 | section 13, phase A step 6 |
| WF3 | W0 final read, P3 | The list-price cross-check in one unit: the formula's tokens times the recorded base input price for that model and price version, against the list increment of the same calls; the gap measured against the list figure; no cross-check with a zero or missing price or unknown coverage; the 10% flag is advisory, never a gate | W2, W11 | section 13, the formula row |
| WF4 | W0 final read, note | The 65-minute idle rule is a declared precondition about the conversation's lineage, not proof that every shared prefix is cold. A pair is not dropped because it read cache; an order whose last-use history is unknown cannot count as meeting it | W12 | W0 report, the bench's starting conditions |
| WF5 | W0 final read, note | The W0 report's single cache-write weight of 1.25 is labelled as the pre-W0 formula | documents | W0 report (a) |
| CN1 | automatic reviewer, P2 | Persist the obligation snapshots of each transition, so the report can judge B1 after the cursor moves or messages are compacted (as DF3) | W7, W11 | section 6, the evidence |
| CN2 | automatic reviewer, P2 | The bench uses orders the pilot agent has not seen, so arm R cannot recall a solution it already wrote | W12 | section 13, phase A step 1 |
| CN3 | automatic reviewer, P1 | A deleted message is caught before the facts count as complete, and the read fails when the publication order is unavailable or not durable | W5 | section 5, `missing_messages` and `order_unavailable`; F-6, F-8 |
| CN4 | automatic reviewer, P2 | Compaction is judged from the compaction archive itself, not from the best-effort stamp `state/compact.json` | W5 | section 5, `history_compacted`; F-5, F-7 |
| CN5 | automatic reviewer, P2 | Only a requested transition whose old conversation can be resumed is rolled back; an automatic transition that fails its check is held | W7, W8 | sections 6, 7 and 9; K8, R11 |
| CN6 | automatic reviewer, P2 | Cost is grouped by `work_item`, over every dispatch and attempt; below 90% attributable cost, B5 is inconclusive | W11 | section 13; B5 |
| CN7 | automatic reviewer, P2 | The completeness check recognises messages that are valid in the compaction archive, and still catches messages that are really missing | W5 | section 5, `missing_messages`; F-6, F-7 |
| CN8 | automatic reviewer, P2 | The fingerprint covers the whole canonical sealed record, and both note checks use it | W4, W6, W7 | sections 4 and 7; K8; W4's done criteria |
| CN9 | automatic reviewer, P2 | While the agent's own request waits on the facts read, the old conversation takes no further turn | W5, W7 | section 5; F-9 |
| DR1 | docs delta read, P2 | The size reading that drives the trigger comes from the last complete call of a dispatch that passes the cross-check; a missing or conflicting reading never authorises a fresh start (same as CR2) | W1, W2 | section 8; F-12 |
| DR2 | docs delta read, P2 | The terminal clean-up saves the event's identity (sequence number, event id, line fingerprint) before appending; recovery checks that exact event, never a bare number. Tests: crash after append, a partial tail, a conflicting row, rotation | W6, W7, W11 | section 6; R10 to R10d |
| DR3 | docs delta read, P2 | A hold with no readable transition still has a release: a hold file with its own id outside the session record, the damaged record kept, stale and wrong-target releases refused; the command examples agree (same as CR4) | W7, W8, W9 | sections 5, 6, 9; R2, R12, R13, T6 |
| DR4 | docs delta read, P3 | W4, the note sealer, produces `record_sha256` with the same canonical form as both checks; a metadata-only change must fail | W4 | W4's done criteria; section 4 |
| CR1 | automatic reviewer, second run, P1 | Each bench arm has its own scratch store and clean worktree at the same base commit | W12 | section 13, phase A step 2 |
| CR2 | automatic reviewer, second run, P2 | The context reading comes from complete calls by the completion rule, never from an `assistant` event (same as DR1) | W1, W2 | section 8 |
| CR3 | automatic reviewer, second run, P2 | W5 is done only with all seven completeness conditions and their tests | W5 | W5's done criteria |
| CR4 | automatic reviewer, second run, P1 | An unreadable session record has a release path that needs no transition id (same as DR3) | W7, W8 | section 6; T6 |
| CR5 | automatic reviewer, second run, P2 | The compaction guard counts only this conversation's messages, not unrelated traffic (refined by FD2: the handled membership list, with the to-or-from rule only as its fallback) | W5 | section 5, `history_compacted`; F-11 |
| CR6 | automatic reviewer, second run, P2 | W11 is done only when the dropped-evidence and excluded-pair fixtures cannot give GO | W11 | W11's done criteria |
| CR7 | automatic reviewer, second run, P2 | The facts read runs before the write-ahead attempt record, so a wait or a crash during it charges no attempt | W5 | section 5; F-10 |
| FD1 | final delta read, P1 | The hold is written and flushed before the damaged record moves; if it cannot be written, the original stays and nothing is dispatched. Every start honours a hold before ordinary loading, even with no session record. Quarantine and release can be repeated, and the damaged bytes are kept | W7, W8 | sections 6 and 9; T6a to T6f |
| FD2 | final delta read, P2 | The compaction guard uses the conversation's own membership list (handled messages, broadcasts included); the broader to-or-from rule is only the fallback when that list is unreadable | W5 | section 5, `history_compacted`; F-11, F-13 to F-15 |
| FD3 | final delta read, P2 | A work item counts as completed only when all its obligations are closed, at a fixed observation cut-off, with a reopen rule; an earlier unanswered task keeps it open even after a later review's final reply | W11 | section 13, cost per work order; W11's done criteria |
| FD4 | final delta read, P3 | R9 names another hold or agent, not another transition | W7 | section 10, R9 |
| AC1 | automatic reviewer, fourth run, P1 | Phase B starts each pilot agent with a measured fresh start (the activation), which sets the baseline from its first complete call and starts a complete membership list; before it, own requests are refused (no baseline) and the broader fallback applies | W5, W6, W13 | section 13, switching the pilot on; F-16; B8 |
| AC2 | automatic reviewer, fourth run, P2 | A membership list created after its conversation began, or with missing entries, is incomplete through its header's completeness boundary, and the broader fallback applies | W5 | section 5, `history_compacted`; F-17 |
| AC3 | automatic reviewer, fourth run, P2 | A1, B5 and B7 never pass on missing cost; the estimated bound first proposed here was dropped by MC5, so only complete, reconciled cost data passes | W2, W11 | section 13, the cost gates; W11's done criteria |
| AC4 | automatic reviewer, fourth run, P2 | A request is completed only by a terminal reply event before the cut-off; a manual close does not count | W11 | section 13, cost per work order; W11's done criteria |
| AC5 | FD read (tk-5663132ea261), P2 | The membership list belongs to its conversation and survives a rollback: one file per conversation, selected again by id on rollback, or the fallback when it is gone | W5, W6, W7 | sections 5 and 6; F-18 |
| MC1 | automatic reviewer, fifth run, P1 (safety); also closes the AC read's P2 A | Membership completeness is proven from per-entry identities and sequence continuity against a durable high-water mark and each finished turn's entry, never from comparing counts; a failed attempt and its retry cannot mask a lost entry | W5, W6 | section 5, `history_compacted`; F-19, F-21 |
| MC2 | automatic reviewer, fifth run, P1 | Releasing a hold made by a blocked transition moves that transition to `released`, a terminal override, and clears it; each step is safe to repeat and a restart never holds the agent again | W6, W7 | section 6; R14 |
| MC3 | automatic reviewer, fifth run, P2 | Cadence turns add no membership entry and play no part in the completeness proof | W5 | section 5; F-20 |
| MC4 | automatic reviewer, fifth run, P2 | A2 needs at least 7 successful R arms among the 10 valid pairs, else it is inconclusive; A1 and A3 use the quality-comparable pairs | W11, W12 | section 13, A2 |
| MC5 | AC read (tk-403c24004ab9), P2 B | The cost gates pass only on complete, reconciled cost data on both sides of each comparison; the estimated bound is dropped, and missing cost makes the gate inconclusive | W2, W11 | section 13, the cost gates |
| MC6 | AC read (tk-403c24004ab9), P3 | One baseline definition: the cross-checked reading after the first finished turn, only for a conversation seen from its start; F-16 names the first failing guard | W1, W6 | sections 8 and 13; F-16 |
