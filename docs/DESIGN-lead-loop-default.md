# DESIGN: a default, required lead loop

**In plain words:** Today a lead has two helpers that do not know about each other. One is a written routine (check the bus, check the seats, check the work, write a handover note) that the lead is told to run every 30 minutes, with a timer the lead sets up and has to remember to renew. The other is the managed lead loop, a program that owns the lead's mailbox and wakes the lead on a short cycle, but only for three kinds of trouble. This design joins them without adding a new timer or a second reader of the mailbox. When a result arrives, such as a review verdict, the lead's own turn must pass the decision to the seat that is waiting for it, and agenttalk writes down who got it and when. If the lead forgets, the existing cycle notices and raises it. A "last completed" record says what the routine really did and when, so a status screen can tell running, overdue, switched off on purpose, and not possible here apart, and never says "healthy" just because a timer exists. Starting a managed lead turns the routine on unless the team has switched it off on purpose; installing the skills alone starts nothing.

Status: design only, no code in this round. Base: `origin/master` at `bdc775cb5727970b960d6ee76c785b5652c1f0dd`. Branch `design/lead-loop-default`. Author: claude-agenttalk-developer-6. Request `tk-92c2d309ee5d`; the challenge (`ch-765ea8cb-231d-40fb-8473-15f20b2209b8`, RESHAPE) is binding and each of its seven points is answered in section 12.

How to read the tags. **FACT** = I read it in this tree at the commit above (a path is given). **ESTIMATE** = a number or effort I reasoned out and did not measure. **ASSUMPTION** = something the design relies on that I did not verify; each one is listed again in section 13 with how to check it.

## 1. What changes for whom

**A new team.** Setting up a managed lead (`agenttalk managed-lead-loop set <lead>` and starting it with `agenttalk wrap --loop --lead-loop`) now also switches the lead routine on, with no extra step. The routine's progress is recorded and shown in `status`, `overview` and `doctor`. A team that does not want it runs one command to switch it off, with a reason; the choice survives restarts and upgrades. (ASSUMPTION: "starting a managed lead" means the controller acquiring its lease, the point where `cli.py` already knows it is a lead loop.)

**An existing team that already has a managed lead.** The first controller start after the upgrade turns the routine on, writes one visible notice ("routine switched on by default; here is how to switch it off") and sends it to the operator-facing seat. Nothing is switched on for a team that has no managed lead. An existing team keeps every current command and file.

**An existing team whose lead is a person-style interactive session** (the usual Claude Code or Codex window). Nothing starts by itself, because an interactive session cannot be driven from outside. The routine stays a written procedure, and what is new is the record: the routine's last step writes "completed", and health reads that record. Without a record the state is "not recorded", not "healthy".

**The seats waiting on a result.** A builder that waits on a review verdict or a gate result gets the lead's decision within an agreed deadline, even if the lead was busy or restarted in between (section 5).

## 2. What exists today (all FACT, read at the commit above)

| Part | What it does | Where |
|---|---|---|
| Lead skill, "Lead routine" | A 7-step check-in "for example every 30 minutes" (bus, seat health, threads, reviews, capacity, knowledge, spend), a handover note every two hours, one line per timer, renew timers before they expire. The routine says plainly that it cannot promise a timer never lapses. | `src/agenttalk/skills/claude/agenttalk.lead.md` (section "Lead routine"); the Codex copy has the same text with `python -m agenttalk` commands (diff of the section shows only command spelling) in `skills/codex/agenttalk-lead/SKILL.md` |
| Timers in the skill | Claude Code: `/loop 30m` in the session. Codex: "the CLI has no built-in timer"; use an operating-system scheduled task. | same files, "Switching the timers on" |
| Managed lead loop | An agent named in config `managed_lead_loop` is consumed by a wrapped controller (`agenttalk wrap --loop --lead-loop`) that holds a renewable lease; a second consumer is refused by a guard on `recv`, `drain`, `wait`, `ack`. | `cli.py` `_guard_lead_loop_consumer`, `_wrap_loop_mode`; `store.py` lease functions |
| Per-record ownership check | `_lead_loop_drive` re-verifies the lease before every record, then runs the normal model turn. | `cli.py` around the `_lead_loop_drive` definition |
| Cadence sweep | When the bus is quiet and `cadence_seconds` (default 300) has passed, the controller builds a bounded read-only snapshot and runs a model turn **only if** one of three item types is actionable: `outbound_reminder` (open thread older than 1800 s), `dead_letter`, `unrouted_escalation`. Otherwise it records the sweep and spends no turn. Failures back off and escalate once after 5. | `lead_loop_cadence.py` (`cadence_due`, `build_cadence_snapshot`, `cadence_actionable`); `wrapper/prompt.py` `_CADENCE_RULES`; defaults in `store.py` (`LEAD_LOOP_*`) |
| Cadence state | `state/<agent>.lead-loop-cadence.json`: last tick, reminders sent, escalation dedup, failure count. Single writer. | `store.py` `read_lead_loop_cadence`, `write_lead_loop_cadence` |
| The skill says the sweep is not the routine | "The supervised lead loop ... does not run the check-in or the handover note." | lead skill, end of "Switching the timers on" |
| Health today | `lead_loop_state` gives managed, present, owner alive, expired, heartbeat stale, armed, reason. `doctor` check `lead_loop`: an unarmed managed lead is an ERROR; a legacy lead or liaison with open work and no live heartbeat is a WARN. `status` rows carry `lead_loop`; the dashboard lists "lead-loop unarmed" signals. | `store.py` `lead_loop_state`; `doctor.py` `_check_lead_loop`; `cli.py` status rows; `web.py` signals |
| Checkpoints and compaction hooks | `agenttalk supervise --install-activity-hook` writes Claude hooks: heartbeat on PostToolUse, `checkpoint save` on PreCompact, `checkpoint resume` on SessionStart (compact). For Codex it writes only the heartbeat hook, "no Codex checkpoint hooks". | `docs/USER-MANUAL.md` (checkpoint section); `checkpoint.py` |
| Relay command | `agenttalk relay` has two verbs today: `operator-answer`, `operator-command`. Nothing forwards a result to a waiting seat, and nothing records that anyone did. | `cli.py` relay commands (grep of `relay`) |
| Waiting seat | No field says "seat S waits for request R". Threads know who owes the next reply (`next_owner`, `next_action`); the work board has no dependency field (grep of `waiting_on`, `blocked_by`, `depends_on` finds nothing in `work_board.py` or `threads.py`). | `threads.py`, `work_board.py` |
| A trap | `set_managed_lead_loop(enabled=True)` rebuilds the agent's whole config entry from three fields, so any extra key stored in that entry is erased by a later `managed-lead-loop set`. An opt-out must therefore live in its own config key. | `store.py` `set_managed_lead_loop` |
| Reset | `reset` deletes `messages/`, `state/`, `checkpoints/`; `config.json` stays. | `store.py` `reset` |
| Hosts and systems | `wrap --lead-loop` is refused for backend profile `ovh-qwen`. The bundled supervisor needs Windows and PowerShell 7; "a monitor that restarts seats on Linux and macOS is not built yet" (#356). The README says the project's tests run on Windows, Linux and macOS. | `cli.py` (`ovh-qwen` branch); `README.md` requirements; `docs/supervisor-hosting.md` |
| Skill lint | `skill_currency.py` checks that every `agenttalk` command in a bundled skill resolves against the live command parser, and that a skill is not older than the package major/minor. It cannot prove prose is right. | `skill_currency.py` |

## 3. The procedure: generic steps, and where a project adds its own

The procedure is one versioned text, shipped inside the two lead skills (ASSUMPTION: a constant `LEAD_ROUTINE_VERSION` next to the text, so code can compare). It names **parts**, each with what a machine can check and what needs the lead's judgement. The 13-step template from the lead's own checklist maps onto these generic parts; nothing project-specific is copied.

| Part | Machine part (no model turn) | Judgement part (a turn, only if the machine part finds something) |
|---|---|---|
| 1 Bus | read-only snapshot of threads (exists) | answer what is owed |
| 2 Relay | open relay records, overdue ones (new, section 5) | forward the decision, or record "none needed" |
| 3 Seat health | `status` health states and heartbeats (exist) | look into a stuck or parked seat |
| 4 Spend | budget feed when the team has one (exists, optional) | tell the person in charge before the limit |
| 5 Merge gates | list of review-results with GO not yet merged; `board verify-merges` (exist) | merge or hold, inline review comments, per the skill's gates |
| 6 Learning | count of uncurated lessons (`knowledge pull`, exists) | verify or retract |
| 7 Memory delta | none (the lead's own notes) | write the handover note |
| 8 Machine resources | none today ("agenttalk does not check the machine's memory", FACT, skill) | the lead's own OS check |
| 9 Scheduled items | the project's own list (project layer below) | act on what is due |
| 10 Self-check | version and rule comparison (section 6) | read the exposed change, acknowledge it |

**Where a project adds its own.** A project keeps its rules in its own instruction files and, optionally, one more file the project owns: `.agenttalk/lead-routine.project.md` (ASSUMPTION: this name; any name works if config points to it). The procedure never edits it. It does three things with these files, all read-only:
1. It lists the files it read and a fingerprint (sha256) of each in the routine record. The list of files to watch is config `lead_routine.rule_sources` (ASSUMPTION), defaulting to the instruction files of the lead's own host that exist in the project folder (`CLAUDE.md`, `AGENTS.md`) plus the project file above.
2. The project file's text is included in the model turn's prompt after the generic text, labelled as the project's additions. A project line can add a step or tighten one. It cannot remove or weaken a generic step: the prompt says so, and the self-check (section 6) refuses a project file that claims to switch off a part by comparing the part names it mentions against the generic list (ESTIMATE: simple pattern match, review needed).
3. When a fingerprint changes from the last acknowledged one, the change is exposed, never applied (section 6).

## 4. Records and where they live

All new records follow the pattern already in use: single-writer files under `state/`, atomic writes, degrade-safe reads that treat a missing or torn file as "nothing recorded" (FACT: the cadence state reader does exactly this).

| Record | File | Writer | Survives `reset`? |
|---|---|---|---|
| Relay events (section 5) | `state/<lead>.relay.jsonl` (append-only) | the lead's controller or `relay result` | No, on purpose: it points at message ids that `reset` deletes (FACT: `reset` deletes `messages/` and `state/`) |
| Routine record: procedure version seen, last completion per part, rule fingerprints acknowledged | `state/<lead>.lead-routine.json` | controller, or `lead-routine complete` / `ack-rules` | No (same reason) |
| Opt-out and default-on notice | config key `lead_routine` (a map by agent name, like `managed_lead_loop`) holding `{enabled, reason, by, at}` | `lead-routine disable` / `enable` | **Yes**: it lives in `config.json` (FACT: reset keeps config) and is separate from `managed_lead_loop`, because `managed-lead-loop set` would erase it (FACT, section 2) |

The config key needs a validator next to `validate_managed_lead_loop` (FACT that one exists; ASSUMPTION that unknown top-level keys are otherwise tolerated).

## 5. The relay record: a result reaches the waiting seat

**The rule.** A result is a terminal `task-response` or `review-result` on a request the lead issued (the lead is the requester). When it is delivered, agenttalk opens a relay record. The lead's turn closes it by naming, for each waiting seat, what was passed on, or why nothing was needed. The periodic sweep catches records that stay open.

**Who is a waiting seat.** Waiting is a bus fact, so it survives a restart. Two declarations, both ordinary message metadata (ASSUMPTION: neither key is reserved by the audit guard; a first-slice check):
- `relay_to=<seat>[,<seat>]` on the request the lead sends: "when this finishes, these seats wait for my decision".
- `waiting_on=<request id>` on any message a seat sends: "I am waiting for the outcome of that request".
The waiting set of a result is the union of both, read from `valid_messages()` (FACT: the cadence snapshot already reads it without moving a cursor). If the set is empty the record closes at once as `no-waiter`.

**Data shape** (one JSON object per line; ESTIMATE of size: under 300 bytes per event):

```
{"v":1,"event":"opened","result_id":"<msg id>","request_id":"<rid>","kind":"review-result","verdict":"GO",
 "waiters":["seat-a"],"at":"<iso>","deadline_at":"<iso>"}
{"v":1,"event":"forwarding","result_id":"...","to":"seat-a","at":"<iso>"}
{"v":1,"event":"forwarded","result_id":"...","to":"seat-a","message_id":"<id of the forward>","at":"<iso>"}
{"v":1,"event":"closed","result_id":"...","disposition":"forwarded|no-waiter|not-needed","reason":"...","at":"<iso>"}
```
Open means an `opened` event with no `closed` event. A record has one state per waiter: `owed`, `forwarding`, `forwarded`, `not-needed`.

**On the message path (wrapped lead).** In `_lead_loop_drive`, after the ownership check and before the model turn, the controller calls a pure function that appends `opened` for the record being delivered, and the turn prompt gains an "owed relay" block: the result, the waiting seats, the deadline, and the one command to close it. After the turn the controller does nothing more. A turn that ends with the record still open is not an error and not a dead letter; the sweep raises it (FACT: cadence turns never advance a cursor or dead-letter, and `_build_turn_journal` already treats `cadence` as unmanaged).

**The command.** `agenttalk relay result --result-id <id> --to <seat> -m "<decision>"` sends the decision as an ordinary message to that seat with `relay_of=<result id>` in its metadata, and writes `forwarding` before and `forwarded` after. `agenttalk relay result --result-id <id> --none-needed --reason "<why>"` closes without a send. Both are typed wrappers over `send`, as the two existing relay verbs are (FACT: they "stamp reserved audit metadata through the audit guard").

**No duplicate action.** Before it sends, the command scans the bus for a message from the lead to that seat whose metadata says `relay_of=<this result id>`. If one exists it writes `forwarded` for it and exits 0 without sending. So a crash between the send and the record, a restart, and a second run of the command all end in exactly one forward. The bus is the truth; the record is a view of it.

**Interactive lead.** There is no controller, so the open step runs inside `agenttalk drain` (the interactive consumer, so there is still one consumer; ASSUMPTION: drain can write the record in the same call, to check in the first slice). Drain's output gains the same "owed relay" block, and `lead-routine status` lists open records.

**What the sweep adds.** `cadence_actionable` gets a fourth item type `relay_overdue` for any open record past its deadline, with the same once-per-state dedup as reminders (FACT: dedup by key exists). `_CADENCE_RULES` gains the one instruction for it. The deadline is `relay_deadline_seconds`, default 600 (ESTIMATE: twice the default sweep interval; to be tuned).

**The limit that cannot be removed.** A wrapped lead handles one record at a time. While the lead is inside a long turn, a new result waits undelivered, so the relay record opens only when that turn ends. The turn is bounded by the turn watchdog (FACT: it exists, `turn_elapsed_seconds` in `supervisor.py` and `DESIGN-202`; ESTIMATE of the default bound: not read here). The deadline is therefore counted **from delivery**, and the demonstration (section 9) states the worst case as turn bound plus one idle poll. A reader that opens the record while the lead is busy would be a second reader of the mailbox, which the challenge forbids (section 12, point 7).

## 6. The self-check: is the procedure itself still right?

The operator's wish ("check if the loop itself needs to be updated") becomes three checks that **expose** and never rewrite rules.

1. **Procedure version.** The routine record stores the `LEAD_ROUTINE_VERSION` the lead last ran. If the shipped version is newer, the sweep raises `procedure_stale` once per version: "the shipped routine changed; read it and run `lead-routine complete --part self-check`". For an interactive lead the same text appears in `lead-routine status`.
2. **Rule sources.** The sweep fingerprints each file in `rule_sources` and compares it with the acknowledged fingerprint. A change raises `rules_changed` with the file name, the old and new fingerprint and the size change, and is sent to the lead and, through `escalate`, to the operator. It is cleared only by `lead-routine ack-rules`, which is a command a person or the lead runs deliberately. Agenttalk never edits a rule file and never decides that a changed rule means a looser procedure.
3. **Derived notes.** The routine's derived notes (which parts apply, the timer lines for an interactive lead, the file list) are regenerated automatically into `state/<lead>.lead-routine.json`. These are the only things the self-check rewrites, and they are derived from the procedure and the project files, never the other way round.

**Timers.** A managed lead has no timer to renew: the cycle is in-process and the lease renews with it (FACT). An interactive lead keeps the skill's existing rule (compare the note with what is scheduled, renew by replacing). What changes is that its health never depends on that comparison, because agenttalk cannot read a session timer (ASSUMPTION; the skill itself says "Nothing tells you when one is gone").

## 7. Health: four states and what each shows

Health is computed by one pure function `lead_routine_state(store, agent, now)` next to `lead_loop_state` (ASSUMPTION: new, same style), and every screen calls it. It reads only records and the capability table in section 8, never whether a timer is registered.

| State | When | `status` row `lead_routine` | `overview` line | `doctor` |
|---|---|---|---|---|
| **running** | enabled, supported, last completion newer than 1.5 x interval (default interval 1800 s), no relay past its deadline, and for a managed lead the controller is armed and its sweep clock moved within 3 x cadence | `state: running`, `last_completion`, `last_kind` (`sweep` or `routine-turn`), `open_relays: n` | "Lead routine: running (last done 12 min ago)" | no entry |
| **overdue** | enabled and supported, and any of: completion older than 1.5 x interval; a relay open past its deadline; the sweep clock stale; a pending `procedure_stale` or `rules_changed` older than one interval | the same fields plus `reasons: [...]` | "Lead routine: OVERDUE (3 reasons)" | new check `lead_routine`: WARN (the existing `lead_loop` ERROR for an unarmed managed lead is unchanged) |
| **deliberately disabled** | an opt-out record exists | `state: disabled`, `by`, `at`, `reason` | "Lead routine: off on purpose since <date> (<reason>)" | an INFO line; never a warning |
| **unsupported** | no automatic driver exists for this host and mode, and nothing was ever recorded (section 8) | `state: unsupported`, `why`, `fallback` | "Lead routine: not available here: <why>. Fallback: <fallback>" | an INFO line |

An interactive lead that records completions is shown as running or overdue like any other, with `last_kind: self-reported`. One that never records is `unsupported` with the fallback text, not `running`. A sweep with nothing to do records `last_kind: sweep`; it says what was checked (the machine parts of section 3) and is not presented as a judgement turn. This keeps the record honest: the cheap path never claims the lead's judgement happened.

## 8. Support by host, mode and operating system

Each row states what exists (FACT unless tagged) and the fallback. "Driver" means what makes the routine run without a person remembering.

| Host and mode | Driver | Compaction | Fallback and health |
|---|---|---|---|
| Claude Code, wrapped managed lead | the cadence sweep inside the controller (FACT) plus the new item types | the model child starts per message with resume (FACT: sessions persist across message and cadence turns, `make_cadence_drive`); the controller also saves a recovery snapshot each sweep (ASSUMPTION: `checkpoint save --trigger auto` callable there) | none needed; health from records |
| Claude Code, interactive | none by agenttalk; the session's own `/loop` is session-scoped (FACT, skill) | the installed hooks: save on PreCompact, resume on SessionStart (FACT); the resume text gains open relays and the last completion (ASSUMPTION, small change in `checkpoint.py`) | the routine's last step runs `lead-routine complete`; health is `self-reported` |
| Codex, wrapped managed lead | the same cadence sweep (FACT: `--lead-loop` is generic by agent name and not refused for Codex; refused only for `ovh-qwen`) | no Codex checkpoint hook (FACT, manual); so the periodic notes are called **recovery snapshots**: the controller saves one per sweep and a restarted turn reads it from the prompt | none needed |
| Codex, interactive | none: "the CLI has no built-in timer" (FACT, skill) | none | `unsupported` with the fallback "an operating-system scheduled task that nudges the lead, or run `lead-routine complete` by hand" |
| `ovh-qwen` profile | none: `wrap --lead-loop` is refused (FACT) | n/a | `unsupported`, reason shown |
| Windows | all of the above; the bundled supervisor restarts a crashed controller (FACT: needs Windows and PowerShell 7) | as above | as above |
| Linux, macOS | `wrap --lead-loop` works as a command (ASSUMPTION: nothing in it is Windows-only; to check); **no restarter exists** (FACT: #356), so a crashed controller stays down until a person starts it | as above; Codex needs `reply_shell` set (FACT, README) | health reports `overdue` and the existing `lead_loop` ERROR for an unarmed managed lead; the fallback text says "restart `wrap --lead-loop`" |

## 9. The acceptance demonstration (the challenger's scenario, made repeatable)

Run on a fixture store with a fake clock and a fake model child (the existing wrapper tests already drive the loop with a fake spawn; ASSUMPTION: the same seams serve here). Seats: `lead`, `reviewer`, `builder`. Agreed deadline: `relay_deadline_seconds` after delivery (default 600; the worst case when the lead is mid-turn is the turn bound plus one idle poll, which the demonstration prints).

1. `builder` sends a message with `waiting_on=<request id>`; `lead` issued that request to `reviewer`.
2. `lead` is made busy: the fake model child holds an in-progress turn.
3. `reviewer` sends a `review-result` GO for the request. Expected: nothing is delivered yet, no relay record, health `running`.
4. The busy turn ends. Expected: the result is delivered, an `opened` record with `waiters: ["builder"]` is written, the prompt carries the owed-relay block.
5. **Restart:** the controller is killed after the lead's turn started but before it closes the record, then restarted (new process, same store). Expected: the record is still open, the sweep raises `relay_overdue` only after the deadline, no second `opened`.
6. The lead (fake child) runs `relay result --to builder`. Expected: exactly one message to `builder` carrying `relay_of=<result id>`, events `forwarding`, `forwarded`, `closed`, within the deadline.
7. **No duplicate:** run the same command again, and also run it after deleting the `forwarded` line (simulated crash). Expected: still exactly one message on the bus; the record is repaired from the bus.
8. **Stale procedure:** change the shipped version constant in the fixture. Expected: one `procedure_stale` item, once; `lead-routine complete --part self-check` clears it.
9. **Changed rule:** edit a rule source file. Expected: one `rules_changed` item and an escalation naming the file; the routine's generic parts are unchanged; it stays raised until `ack-rules`.
10. **Persistent opt-out:** `lead-routine disable --for lead --reason ...`, then `managed-lead-loop set lead` (which rebuilds its own entry), then restart. Expected: still `disabled`.
11. **Scheduling unavailable:** fixture with no cadence ticks and no completions; then an interactive lead with no records. Expected: the first is `overdue` (sweep clock stale) and never `running`; the second is `unsupported` with its fallback; neither is `running`.

## 10. The smallest first slice (result forwarding plus the last-completion record)

1. A relay event file and a pure open/close module, with one `relay result` command that forwards or records "none needed", idempotent through the bus scan (section 5).
2. Open a record when `_lead_loop_drive` delivers a result (and in `drain` for an interactive lead), and add the owed-relay block to the turn prompt.
3. One new item type, `relay_overdue`, in the existing sweep and its rules text. No new timer, no second consumer.
4. `lead-routine complete`, writing the last-completion record, called by the last step of the routine text in both lead skills; one new field `lead_routine` (state, last completion, open relays) in the existing `status` row and `overview` line.
5. Tests (section 11), both skill texts and `docs/LEAD-GUIDE.md` updated. Default-on at controller start, the opt-out command, the self-check items and the `unsupported` fallbacks are slice 2.

ESTIMATE of size for slice 1: about 400 lines of code and 600 lines of tests, one to two days for one builder including the Codex read; not measured against any earlier slice.

## 11. Tests

Slice 1 (each is a new test file or additions to `tests/test_lead_loop*.py`, `tests/test_relay_wp4.py`):
- relay record: open, forward, close, no-waiter, not-needed; torn or missing file reads as empty; one event per line.
- idempotency: the command run twice, after a lost `forwarded` line, after a crash between send and record; bus scan finds the earlier forward.
- waiting-set derivation: `relay_to`, `waiting_on`, union, retired seat dropped (FACT: `derive_threads` already drops retired peers), empty set.
- `cadence_actionable`: `relay_overdue` is raised past the deadline, not before, once per state; existing three types unchanged.
- the controller path with the fake child: record opened before the turn, a turn that leaves it open is not a dead letter and moves no cursor.
- `drain` for an interactive lead opens the record and prints the block.
- `lead-routine complete` and `lead_routine_state`: running, overdue, self-reported; a registered timer alone never gives running.
- skill lint (`test_skill_lint.py`, `test_skill_currency.py`): the new commands resolve; both lead skills carry the same step.
- a mutation check per rule (remove the bus scan, remove the deadline, treat an empty waiting set as open): each turns a test red.

Slice 2 adds: opt-out survives `managed-lead-loop set`, reset and upgrade; default-on at controller start writes exactly one notice; procedure and rule changes exposed and never applied; the capability table per host, mode and OS; compaction resume text with relays.

## 12. How the challenge's seven points are met

1. **Extend, no new timer, one consumer.** Everything hangs on the existing cadence sweep, lease and controller. The relay open step reads the bus without moving a cursor. `drain` and the controller stay the only consumers. (Section 5.)
2. **Decisions on the message path.** The record opens at delivery, the closing command is in the same turn, and the record names the seat and the time. The sweep catches omissions; a checklist alone is not relied on. (Section 5.)
3. **Four honest states.** running, overdue, deliberately disabled, unsupported, computed from records, never from a timer. (Section 7.)
4. **On by default for a managed lead, with a persistent opt-out.** Slice 2; skills alone start nothing; the opt-out is its own config key because of the `set` trap. (Sections 1, 4.)
5. **Versioned, project-agnostic, exposes rule changes.** Section 3 and 6: derived notes rewritten, rules only exposed.
6. **Compaction and host support.** Hooks where they exist (Claude Code), recovery snapshots elsewhere; the table gives capability and fallback per host, mode and system. (Section 8.)
7. **Kill signals, checked.** Second mailbox consumer: not needed, and the busy-lead latency limit is stated instead of fixed with one. Healthy from timer registration: refused by section 7. Self-maintenance weakening rules: not possible by construction, because no part of the design writes a rule file.

## 13. Assumptions to verify, risks, and open questions

1. `relay_of`, `relay_to` and `waiting_on` are not reserved metadata keys (check the audit guard; if reserved, use the typed relay wrapper path the existing verbs use).
2. `drain` can write the record in the same call without breaking its read-marking contract.
3. A constant `LEAD_ROUTINE_VERSION` can live beside the skill text and be read by code without a file read of the installed skill.
4. `checkpoint save --trigger auto` is callable from the controller's sweep.
5. Nothing in `wrap --lead-loop` is Windows-only (the README's own platform note and the missing restarter suggest only the supervisor is).
6. Seats will actually set `waiting_on`. If they do not, the set is only what the lead declared with `relay_to`; the sweep cannot know about an undeclared waiter. This is the design's largest honest gap, and the lead skill text must say it.
7. Cost of default-on: the sweep spends no turn when nothing is actionable (FACT), and the new items add turns only when a relay is overdue or a change is exposed. ESTIMATE: a quiet team adds no model turns; a busy one adds at most one per sweep interval. Not measured.
8. The opt-out validator and the `lead_routine` config key may interact with `init --force` (it "rewrites the config but intentionally keeps state", FACT, `reset` docstring); check that it keeps the key.
9. The busy-lead delay is a real limit; if the operator needs a hard deadline during long turns, the answer is a second reader, which the challenge forbids, or a shorter turn bound for leads. This needs an operator decision, not a design workaround.
10. Linux and macOS have no restarter, so "default on" there means "on while the controller runs".

## 14. Files touched (slice 1 and slice 2)

Slice 1: new `src/agenttalk/lead_relay.py` (record, open, close, bus scan), new `src/agenttalk/lead_routine.py` (completion record, `lead_routine_state`); edits to `src/agenttalk/cli.py` (the `relay result` verb, `lead-routine complete`, `_lead_loop_drive`, `drain` output, `status` row), `src/agenttalk/lead_loop_cadence.py` (`relay_overdue`), `src/agenttalk/wrapper/prompt.py` (`_CADENCE_RULES`, the owed-relay block), `src/agenttalk/store.py` (path helpers only), `src/agenttalk/overview.py` and `src/agenttalk/web.py` (one field and one line), both lead skills (`skills/claude/agenttalk.lead.md`, `skills/codex/agenttalk-lead/SKILL.md`), `docs/LEAD-GUIDE.md`, `docs/AGENT-MANUAL.md`, `CHANGELOG.md`; tests as in section 11.

Slice 2 adds: `src/agenttalk/store.py` (the `lead_routine` config key and validator), `src/agenttalk/doctor.py` (check `lead_routine`), `src/agenttalk/checkpoint.py` (resume text), `src/agenttalk/cli.py` (the `lead-routine` group), `docs/USER-MANUAL.md`, `docs/OPERATIONS.md`.

This document itself: `docs/DESIGN-lead-loop-default.md` only. It is not opened by any test and is not listed in the source package list (FACT: `tests/test_sdist_docs.py` requires only docs that a test opens to be listed; the other `DESIGN-*.md` files are not listed either).
