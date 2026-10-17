# DESIGN: a default, required lead loop

**In plain words:** Today a lead has two helpers that do not know about each other. One is a written routine (check the bus, check the seats, check the work, write a handover note) that the lead is told to run every 30 minutes, with a timer the lead sets up and has to remember to renew. The other is the managed lead loop, a program that owns the lead's mailbox and wakes the lead on a short cycle, but only for three kinds of trouble. This design joins them without adding a new timer or a second reader of the mailbox. When a result arrives, such as a review verdict, the lead has to pass the decision to each seat that is waiting for it. Whether that happened is worked out from the messages themselves, so it cannot be lost with a file, and the hand-off is sent once even if two commands race or the machine stops half way. If the lead forgets, the existing cycle reminds again and escalates, and it never claims more than it can keep: the design lists every case in which no delivery time can be promised. A status screen shows what really ran and when, and never says "healthy" because a timer exists. Starting a managed lead turns the routine on unless the team switched it off on purpose; that choice survives a forced re-initialisation. Installing the skills alone starts nothing.

Status: design, revision 2 (fix round 1 after the read in `tk-682a6b30d61e`: no P1, six P2, two P3; all eight answered in section 12). No code in this round. Base: `origin/master` at `bdc775cb5727970b960d6ee76c785b5652c1f0dd`. Branch `design/lead-loop-default`. Author: claude-agenttalk-developer-6. Requests `tk-92c2d309ee5d`, `tk-06901411d7a4`. The challenge (`ch-765ea8cb-231d-40fb-8473-15f20b2209b8`, RESHAPE) stays binding; its seven points are in section 13.

How to read the tags. **FACT** = I read it in this tree at the commit above (a path is given). **ESTIMATE** = a number or effort I reasoned out and did not measure. **ASSUMPTION** = something the design relies on that I did not verify; each is listed again in section 14 with how to check it.

## 1. What changes for whom

**A new team.** Setting up a managed lead (`agenttalk managed-lead-loop set <lead>` and starting it with `agenttalk wrap --loop --lead-loop`) will switch the lead routine on with no extra step, once default-on ships (slice 2). The routine's progress is recorded and shown in `status`, `overview` and `doctor`. A team that does not want it runs one command to switch it off, with a reason. The choice survives restarts, `reset`, `managed-lead-loop set` and `init --force` (sections 4 and 8). (ASSUMPTION: "starting a managed lead" means the controller acquiring its lease.)

**An existing team that already has a managed lead.** After the slice 2 upgrade the first controller start turns the routine on, writes one visible notice (recorded in `lead_routine.<agent>.default_on_notice`, section 4) and sends it to the operator-facing seat. A team with no managed lead gets nothing switched on.

**An existing team whose lead is an interactive session** (the usual Claude Code or Codex window). Nothing starts by itself, because an interactive session cannot be driven from outside. The routine stays a written procedure; what is new is the record of what completed.

**The seats waiting on a result.** A builder that waits on a review verdict or a gate result gets the lead's decision, or an explicit "nothing needed", sent once. If the lead is slow, a reminder follows and then an escalation until the obligation closes. The design promises a best-effort target, not a deadline (section 6).

**What ships when.** Slice 1 is the relay obligations, the atomic hand-off, coverage of every consuming path, visible owed and overdue records, best-effort reminders and a last-completion field that says exactly what completed. Default-on, the routine-health label, snapshots and rule watching come later; their contracts are settled in sections 7 to 9 now, because default-on is the operator's requirement.

## 2. What exists today (all FACT, read at the commit above)

| Part | What it does | Where |
|---|---|---|
| Lead skill, "Lead routine" | A 7-step check-in "for example every 30 minutes", a handover note every two hours, one line per timer, renew timers before they expire. It says it cannot promise a timer never lapses. | `src/agenttalk/skills/claude/agenttalk.lead.md`; the Codex copy differs only in command spelling (diff of the section) in `skills/codex/agenttalk-lead/SKILL.md` |
| Timers in the skill | Claude Code `/loop 30m`; Codex "has no built-in timer", use an operating-system task. | same files |
| Managed lead loop | An agent in config `managed_lead_loop` is consumed by a wrapped controller (`wrap --loop --lead-loop`) holding a renewable lease; a second consumer is refused on `recv`, `drain`, `wait`, `ack`. | `cli.py` `_guard_lead_loop_consumer`; `store.py` lease functions |
| Per-record ownership check | `_lead_loop_drive` wraps the **normal message turn** (not a synthetic one): lease check, then the model turn. | `cli.py` near line 12748 |
| Cadence sweep | When no message is pending and `cadence_seconds` (default 300) passed, a bounded read-only snapshot is built and a model turn runs only for `outbound_reminder` (thread older than 1800 s), `dead_letter`, `unrouted_escalation`. The sweep never advances a cursor or dead-letters. A sweep with nothing actionable is recorded as a success. | `lead_loop_cadence.py`; `cli.py` near line 12828; `wrapper/loop.py` idle branch near line 1607 |
| Sweep reads degrade to empty | Each snapshot section that fails to read becomes an empty collection and the sweep still counts as successful. | `lead_loop_cadence.py` (`except Exception` blocks of `build_cadence_snapshot`) |
| Cadence only when idle | `run_loop` consults the cadence hook only when there is no pending record, so sustained traffic starves it. | `wrapper/loop.py` idle branch |
| Turn watchdog | Not a hard deadline: it needs the turn to be 1800 s old **and** a live tool-like descendant alive 600 s, and it never kills when the process snapshot is unavailable (fail-open). Default-on only for a continuous wrapped Codex loop, not Claude. | `wrapper/turn_watchdog.py` (header and decision function); `cli.py` near line 13474 |
| Every consuming path ends in `Store.advance_cursor` | `recv --ack` and `drain` (`_do_recv`), `wait`, `ack`, the wrapper's `recv_api`, the owed-action path, and the store's recovery all call it. | `cli.py` `_do_recv`, `cmd_wait`, `cmd_ack`; `wrapper/recv_api.py`; `wrapper/obligations.py`; `store.py` |
| Locked, deduplicated publication | `send_operation(operation_nonce, operation_digest)` takes `state/operation-publication.lock` (rank 100), persists an intent, scans `valid_messages()` for the nonce, returns the existing message if the digest matches, refuses a different payload under the same nonce, otherwise sends (taking the rank-160 message-publication mutex) and marks the intent published. | `store.py` `send_operation`; ranks in `docs/LOCK-ORDER.md` |
| Terminal result semantics | A `task-response` (done, declined, or a verdict without status), a `review-result` (approved, rejected) or a `proposal-response` closes a thread; `needs-info` and `accepted` pass the ball instead. | `threads.py` `_classify_event` |
| Compaction | `compact` archives messages below a keep floor; defaults keep the newest 1000 and 30 days, automatic mode is off. The floor never archives unread messages and keeps the whole request group of any protected thread state. | `cli.py` `_compute_keep_floor`, `COMPACT_DEFAULTS` |
| Reserved relay metadata | The relay verbs scrub `operator_command`, `operator_answer`, `operator_origin`, `operator_command_override`, `override_reason`, `needs_operator`, `broadcast_id`, `in_reply_to`, `target_msg_id`. The keys this design uses are not among them. | `cli.py` `_RELAY_RESERVED_META` |
| Relay verbs | Only `operator-answer` and `operator-command`. Nothing forwards a result to a waiting seat. | `cli.py` `cmd_relay` |
| Waiting seat | No field says "seat S waits for request R" (no `waiting_on`, `blocked_by` or `depends_on` in `work_board.py` or `threads.py`). | `threads.py`, `work_board.py` |
| Config traps | `set_managed_lead_loop(enabled=True)` rebuilds the agent's whole entry from three fields. `init --force` builds a fresh config and carries only the `retired` tombstones and the external trust classes. | `store.py` `set_managed_lead_loop`, `init` |
| Reset | `reset` deletes `messages/`, `state/`, `checkpoints/`; `config.json` stays. | `store.py` `reset` |
| Health today | `lead_loop_state`; `doctor` check `lead_loop` (unarmed managed lead = ERROR, legacy lead with open work and no live heartbeat = WARN); `status` rows carry `lead_loop`; the dashboard lists "lead-loop unarmed". | `store.py`, `doctor.py`, `cli.py`, `web.py` |
| Checkpoints and hooks | Claude hooks: heartbeat on PostToolUse, `checkpoint save` on PreCompact, `checkpoint resume` on SessionStart (compact). Codex gets only the heartbeat hook. | `docs/USER-MANUAL.md`; `checkpoint.py` |
| Hosts and systems | `wrap --lead-loop` is refused for backend profile `ovh-qwen`. The bundled supervisor needs Windows and PowerShell 7; no restarter exists on Linux and macOS (#356). | `cli.py`; `README.md`; `docs/supervisor-hosting.md` |
| Owed-action ledger | A signed-policy ledger that enforces that a wrapped turn commits; considered and not reused, because relay obligations are per-recipient hand-offs that must be reconstructable from the bus (ASSUMPTION about fit; I read the module header and its lock rank, not the whole module). | `wrapper/obligations.py`, rank 170 |

## 3. The procedure: generic steps, and where a project adds its own

One versioned text, shipped inside the two lead skills (ASSUMPTION: a constant `LEAD_ROUTINE_VERSION` beside it so code can compare). It names **parts**. Each part has a machine half (cheap, no model turn) and a judgement half (a turn, and only if the machine half found something). The 13-step template from the lead's own checklist maps onto these generic parts; nothing project-specific is copied.

| Part | Machine half | Judgement half |
|---|---|---|
| 1 Bus | read-only snapshot of threads (exists) | answer what is owed |
| 2 Relay | owed and overdue obligations (section 5) | forward the decision, or record "nothing needed" |
| 3 Seat health | `status` health states and heartbeats (exist) | look into a stuck or parked seat |
| 4 Spend | budget feed if the team has one (exists, optional) | tell the person in charge before the limit |
| 5 Merge gates | review-results with GO not yet merged; `board verify-merges` (exist) | merge or hold, read inline review comments |
| 6 Learning | count of uncurated lessons (`knowledge pull`, exists) | verify or retract |
| 7 Memory delta | none | write the handover note |
| 8 Machine resources | none today (FACT, skill: agenttalk does not check memory) | the lead's own OS check |
| 9 Scheduled items | the project's own list (below) | act on what is due |
| 10 Self-check | procedure version and project rule comparison (section 9) | read the shown change, acknowledge it |

**Where a project adds its own.** A project keeps its rules in its own files. The procedure reads them, never edits them, and fingerprints them (section 9). Optional: `.agenttalk/lead-routine.project.md` (ASSUMPTION: this name; config may point elsewhere), whose text is added to the prompt after the generic text, labelled as the project's additions.

**What is enforced and what is an instruction** (the rule for this design):
- *Enforced in code and tested:* the loop never writes a rule file; a rule file is read once per turn and the same bytes are fingerprinted and put in the prompt; every unacknowledged change is shown, with its difference, in the prompt and in `status`; the relay obligations and health states below.
- *Instruction only, not enforced:* that a project's additions must not weaken a generic part. The prompt says so; nothing mechanical checks the prose.

## 4. Records and where they live

| Record | Where | Authority | Survives `reset`? |
|---|---|---|---|
| Relay obligations | **derived from the bus** every time (section 5); an optional index `state/<lead>.relay-index.json` only speeds the derivation | the bus messages | No, because the messages go too (FACT: reset deletes `messages/` and `state/`) |
| Routine record: procedure version seen, mode and controller start it belongs to, sweep coverage, completion per part | `state/<lead>.lead-routine.json`, one writer (the controller, or `lead-routine complete`) | this file | No |
| Acknowledged rule copies | `state/<lead>.rules-acked/` (size-capped copies, to show a difference) | this folder | No |
| Opt-out and default-on notice | config key `lead_routine`, a map by agent name: `{enabled, reason, by, at, default_on_notice: {at, version, message_id}}` | `config.json` | **Yes** (FACT: config stays); carried by `init --force` (section 8) |

**A missing or torn file.** The routine record and the index are caches or counters, so a missing or torn one reads as "nothing recorded" (as the existing cadence state does). The obligation is not stored anywhere that can be lost: it is derived, so there is nothing to read back (finding 2). A **corrupt or future-dated** routine record is never read as healthy (section 7).

## 5. The relay obligation: derived from the bus, closed by an atomic hand-off

**Definitions.**
- *Result:* a message to the lead that `_classify_event` classes as terminal on a thread the lead opened (FACT: that function; ASSUMPTION: a small public helper wraps it).
- *Waiter declaration:* a message from seat S with metadata `waiting_on=<request id>`, or `relay_to=<seats>` on the lead's own opening message of that request. `waiting_off=<request id>` from S cancels S's declaration. None of these keys is reserved (FACT, section 2). Any seat can declare; a declaration only creates an obligation for the lead to answer it, never an action by the lead.
- *Obligation* (lead L, result R, seat S): S has a declaration for R's request, no cancel after it, S is not retired (FACT: `derive_threads` drops retired peers), and there is no closing message.
- *Closing message:* a message **from L** to S carrying `relay_of=R` and `relay_nonce` (below), either the decision text or an explicit note `relay_outcome=not-needed` with a reason. The sender must be L; signature-valid messages only (FACT: `valid_messages()` applies the roster and signature gate), so another seat cannot close or forge a hand-off.

**Per-recipient states** (all derived): `owed`, `closed-forwarded`, `closed-not-needed`, `closed-recipient-retired`, `cancelled`. `--none-needed` closes only the named recipient. A declaration that arrives **after** the result was handled creates a new owed obligation (membership is **not** frozen at delivery; the limit is the other way round: a seat that never declares is unknown to the system). A retirement closes the obligation as `closed-recipient-retired`; a cancel before a hand-off removes it.

**The atomic operation.** `agenttalk relay result --result-id R --to S (-m TEXT | --none-needed --reason TEXT)` calls one store function modelled on `send_operation` (FACT precedent), with `operation="relay"` in the intent identity:
1. identity: nonce = first 32 hex of sha256 of `relay`, L, R, S; digest = sha256 over the canonical intent plus the body;
2. take `state/operation-publication.lock` (rank 100, FACT);
3. **inside the lock**, re-derive: R exists and is a result for L, S is a valid recipient; refuse with a typed error otherwise;
4. record the intent, scan `valid_messages()` for sender L and this nonce: same digest returns the existing message and repairs the intent without sending; a different digest is refused as a payload conflict (FACT behaviour of `send_operation`);
5. otherwise `send` (rank 160 inside rank 100, the same order `send_operation` already uses), then mark the intent published.

So two processes that race, a crash between send and intent update, and a rerun all end in exactly one message. No lock is added in slice 1 (the existing rank 100 lock is reused); any new lock needs a rank in `docs/LOCK-ORDER.md` and an inventory test (FACT: that file says so).

**Why there is no journal to lose, and what recovery looks like at each boundary.**

| Interruption | What is left | What happens next |
|---|---|---|
| after the result arrives, before the cursor moves | result unread, declaration on the bus | normal redelivery; the obligation is derived when the result is shown |
| after the cursor moved, before the lead acts | obligation derived `owed` from the bus | shown again by `status`, the next prompt and the sweep |
| index file missing, torn or stale | derived from the bus | index rebuilt; no error |
| crash after the intent, before `send` | intent `prepared`, no message | the rerun sends once |
| crash after `send`, before the intent update | message on the bus | the rerun finds it, repairs the intent, sends nothing |
| two commands at once | one wins the lock | the other returns the first message |
| messages archived by `compact` | result or declaration gone | prevented: slice 1 adds a protected component to `_compute_keep_floor` so a request group with an owed obligation is never archived (ASSUMPTION: a small, testable change); if a message is nevertheless missing the obligation is simply not derived, and the routine record's `bus_floor` shows what the derivation could see |
| `reset` | messages gone | obligations gone with them, consistently |

**Every consuming path.** Because no write is needed at consumption, every path is covered by the same rule: the obligation exists from the moment the declaration and the result are on the bus. What the paths add is the *notice*. `drain`, `recv --ack`, `wait` and `ack` all end in `Store.advance_cursor` (FACT). The first slice makes `drain`, `recv`, `wait` print an "owed relay" block after the messages they show when the agent is a lead with an obligation (ASSUMPTION: each prints from its existing render loop), and `status` and `lead-routine status` always list them. The wrapped controller adds the same block to **every** message prompt and to the sweep prompt while an obligation is owed. A path that consumes silently (`ack`) loses nothing, because the next block, status or sweep derives the obligation again.

**The cursor, stated exactly.** A delivered result is consumed once through the normal path, as today. Its obligation is separate, derived, state. A reminder is a synthetic sweep turn and never advances a cursor (FACT). A result is never replayed until someone forwards it.

## 6. Reminders, the delivery target, and where no time can be promised

**The promise.** A *best-effort target*: once the lead is free (not inside a turn), an owed obligation is shown in the next prompt, and if it is older than `relay_deadline_seconds` (default 600; ESTIMATE, twice the default sweep interval) the sweep raises `relay_overdue`. This is a target, not a deadline.

**Retry and escalation until the obligation closes.** Reminders are bucketed by age: raised at 1, 2, 4, 8 times the deadline, then every 24 hours, so a reminder turn that ignores the hand-off is followed by another one. A successful reminder turn does **not** close anything or latch a dedup; only a derived `closed-*` state does. After 3 reminders (default; ESTIMATE) the sweep escalates once to the operator through `escalate`, and again each 24 hours while open. Dedup keys are per (lead, result, seat, bucket).

**Every case where the target is unbounded or unavailable** (each is a stated limit and a test):
1. *Long turn.* A wrapped lead handles one record at a time. During a long turn nothing is delivered and nothing is reminded. The watchdog does not bound this: it needs an aged tool descendant and fails open, and it is off by default for Claude (FACT, section 2). A long reasoning turn without tools is unbounded.
2. *Continuous traffic.* The sweep runs only when no message is pending (FACT), so it can be starved. The per-turn prompt block (section 5) is the mitigation, not a guarantee: a turn can ignore it.
3. *Watchdog off or unsupported* (process snapshot unavailable): same as 1.
4. *A reminder turn that ignores the hand-off:* handled by the repeat and escalation above; the delay is the bucket length.
5. *The lead is down, unarmed or in failure backoff* (up to 1800 s, FACT): nothing runs. The existing `lead_loop` doctor ERROR covers an unarmed managed lead; the new state shows `overdue` with the reason.
6. *Interactive lead:* the block appears only when the lead consumes or runs `status`.
7. *Linux and macOS:* no restarter (FACT), so a crashed controller stays down.
8. *A waiter that never declared:* unknown to the system.

No second mailbox consumer is added: the derivation reads messages without a cursor (FACT: the cadence snapshot already does), and sending is not consuming.

## 7. Health: exhaustive states, precedence, and what each shows

Two things are tracked **separately** and shown separately: the *machine sweep* (what the controller attempted and covered) and the *lead's routine* (which judgement parts were completed by whom). A sweep never renews the freshness of a judgement part.

**Records.** The sweep writes `{at, mode, controller_start, attempted: [sections], failed: [sections]}` (this needs `build_cadence_snapshot` to report which sections failed instead of hiding them, section 2; ASSUMPTION: a small change, testable). `lead-routine complete --part <name>` and the controller's turns write `completion[part] = {at, kind: sweep|turn|self-reported, covered, failed}`.

**Precedence** (first matching row wins, one state per agent):

| # | Condition | State | Reason code |
|---|---|---|---|
| 1 | a valid opt-out exists | **deliberately disabled** | `opt-out` |
| 2 | no automatic driver exists for this host and mode (table in section 10) and no completion was ever recorded | **unsupported** | `no-driver` / `backend-refused` |
| 3 | managed and the lease is not armed (`lead_loop_state`) | **overdue** | `controller-not-armed` (a recent sweep does not rescue it) |
| 4 | the routine record is corrupt, or any timestamp is in the future beyond a small skew | **overdue** | `record-unreadable` / `record-future-dated` (never read as healthy) |
| 5 | the record belongs to another mode or controller start than now (mode change, restart) | treated as **never completed** | `record-other-mode` |
| 6 | managed, never completed, and inside the grace (2 x cadence from controller start; ESTIMATE) | **starting** | `first-sweep-pending` |
| 7 | managed, never completed, past the grace | **overdue** | `never-completed` |
| 8 | a sweep section is in `failed` on its latest run, or no sweep within 3 x cadence | **overdue** | `sweep-incomplete` / `sweep-stale` |
| 9 | any relay obligation past its deadline | **overdue** | `relay-overdue` |
| 10 | a judgement part owed because its machine half found something and it has not completed since | **overdue** | `part-owed:<name>` |
| 11 | a rule change shown and not acknowledged for longer than one interval | **overdue** | `rules-unacknowledged` |
| 12 | none of the above and at least one completion within 1.5 x interval | **running** | evidence: last sweep, last completion per part, open obligations |
| 13 | none of the above and no completion at all (interactive, no records) | **unsupported** | `not-recorded` |

A registered timer never appears in this table. For an interactive lead, `running` needs a self-reported completion; without one the state is row 13.

**What each screen shows.** `status` row `lead_routine`: `state`, `reasons`, `sweep: {at, attempted, failed}`, `parts: {name: {at, kind}}`, `open_relays: n`, `overdue_relays: n`, and for `disabled` the `by`, `at`, `reason`. `overview`: one plain line ("Lead routine: running, last sweep 4 min ago, 0 owed hand-offs" / "OVERDUE: controller not armed" / "off on purpose since <date>" / "not available here: <why>. Fallback: <fallback>"). `doctor`: check `lead_routine`, WARN for overdue (the existing `lead_loop` ERROR is unchanged), INFO for disabled and unsupported.

## 8. Defaults and the opt-out (commands, persistence, lifecycle)

**Commands** (slice 2 except `complete`): `agenttalk lead-routine status|complete|disable|enable|ack-rules --for <lead>`; `disable` needs `--reason`.

**Persistence.** The opt-out lives in config key `lead_routine.<agent>`, separate from `managed_lead_loop`, because `managed-lead-loop set` rebuilds its own entry (FACT). A validator next to `validate_managed_lead_loop` checks the shape (ASSUMPTION: unknown top-level keys are otherwise tolerated).

**Force initialisation (decision).** A valid opt-out **survives** `init --force`: `init` carries `lead_routine` the way it already carries `retired` and `trust_classes` (FACT: `retired_carry`, `active_external`). An entry for an agent that is not in the new roster is dropped, and the command prints the dropped names; it is never silent. The only ways to clear an opt-out are `lead-routine enable --for <lead>`, or, to clear it during a re-initialisation, an explicit destructive flag `init --force --forget-lead-routine-optout <agent>` (one agent per flag; ASSUMPTION: this name), or removing `.agenttalk/` entirely (FACT: the existing message for tombstones says the same). A test covers a disabled agent reconfigured with `init --force` and restarted.

**The one-time default-on notice** is recorded in `lead_routine.<agent>.default_on_notice = {at, version, message_id}` in config, so it survives `reset` and `init --force` and is sent once. Absence of the field means "not yet shown".

## 9. The self-check: the procedure and the project's rules

1. **Procedure version.** The routine record stores the version last run. A newer shipped version raises `procedure_stale` once per version; `lead-routine complete --part self-check` clears it.
2. **Project rules: notify, do not gate (decision).** The project's rule file is the project's own authority, so a change is **active from the next turn**; there is no activation gate and no suspension of project additions. What is promised, and enforced:
   - the loop never writes a rule file (test: hash and mtime unchanged after a sweep and after a turn);
   - each turn reads each rule file once; those exact bytes are fingerprinted and placed in the prompt (test: a file changed between the fingerprint and the prompt build shows in the next turn, not a mixture);
   - every unacknowledged change is shown with its difference (against the stored acknowledged copy) in the prompt and in `status` until `lead-routine ack-rules` (test: shown on the next turn, still shown until acknowledged, gone after);
   - a rule change is also escalated to the operator once (existing `escalate`).
   Prose limits on project additions are instructions, not enforcement (section 3); the earlier idea of refusing a project file by matching part names is dropped.
3. **Derived notes.** The routine record (which parts apply, the timer lines of an interactive lead) is regenerated automatically; this is the only thing the self-check rewrites.
4. **Timers.** A managed lead has none to renew (the cycle is in-process and the lease renews with it, FACT). An interactive lead keeps the skill's rule; health never depends on it, because agenttalk cannot read a session timer (ASSUMPTION; the skill itself says nothing tells you when one is gone).

## 10. Support by host, mode and operating system

| Host and mode | Driver | Compaction | Fallback and health |
|---|---|---|---|
| Claude Code, wrapped managed lead | the cadence sweep (FACT) plus the new items | the model child resumes its session across turns (FACT: `make_cadence_drive` shares session state); the controller saves a **recovery snapshot** per sweep (ASSUMPTION: `checkpoint save --trigger auto` callable there) | none needed |
| Claude Code, interactive | none by agenttalk; `/loop` is session-scoped (FACT, skill) | hooks: save on PreCompact, resume on SessionStart (FACT); resume text gains owed relays (ASSUMPTION) | the routine's last step runs `lead-routine complete`; health `self-reported` |
| Codex, wrapped managed lead | the same sweep (FACT: `--lead-loop` is generic by agent name, refused only for `ovh-qwen`) | no Codex checkpoint hook (FACT): recovery snapshots per sweep | none needed |
| Codex, interactive | none (FACT, skill) | none | state `unsupported`, fallback "an operating-system task that nudges the lead, or run `lead-routine complete`" |
| `ovh-qwen` | none: `wrap --lead-loop` refused (FACT) | n/a | `unsupported`, `backend-refused` |
| Windows | all above; the bundled supervisor restarts a crashed controller (FACT) | as above | as above |
| Linux, macOS | `wrap --lead-loop` as a command (ASSUMPTION: nothing in it is Windows-only); **no restarter** (FACT, #356) | as above; Codex needs `reply_shell` (FACT, README) | `overdue` with `controller-not-armed`, plus the existing `lead_loop` ERROR; fallback text "restart `wrap --lead-loop`"; default-on means "on while the controller runs" |

## 11. The acceptance demonstration

Fixture store, fake clock, fake model child (ASSUMPTION: the existing wrapper tests' fake-spawn seams serve). Seats `lead`, `reviewer`, `builder`. Agreed target: the best-effort target of section 6, with the unbounded cases printed.

1. `builder` sends a message with `waiting_on=<request id>`; `lead` issued that request to `reviewer`.
2. `lead` is busy: the fake child holds a turn open.
3. `reviewer` sends a `review-result` GO. Expected: nothing delivered yet; the obligation is already derivable (declaration and result are on the bus); health `running`, no reminder (limit 1, stated).
4. The turn ends; the result is delivered once through the normal path; the prompt carries the owed block.
5. **Restart** mid-turn: kill the controller, start a new process on the same store. Expected: still `owed` (derived), the result is not replayed, no duplicate message.
6. The child runs `relay result --to builder`. Expected: exactly one message with `relay_of`, state `closed-forwarded`.
7. **No duplicate, three ways:** the command run twice; two processes at once through a barrier; a crash injected between the send and the intent update. Expected: one message each time.
8. **Index and journal loss:** delete the index and routine record. Expected: the obligation is still derived; no error.
9. **A reminder turn that ignores the hand-off:** expected: the next bucket raises it again; after 3 the operator escalation; closing the obligation stops it.
10. **Continuous traffic:** results keep arriving so the sweep never runs. Expected: the per-turn block still shows the obligation; the sweep-starved case is reported as the stated limit.
11. **Late declaration, cancel, retire:** a declaration after the result creates an owed obligation; `waiting_off` removes it; retiring the seat closes it as `closed-recipient-retired`; `--none-needed` closes only the named seat.
12. **Compaction:** `compact` with a very low keep count keeps the request group of an owed obligation.
13. **Stale procedure, changed rule (slice 2/3):** a newer shipped version raises `procedure_stale` once; a changed rule file is active next turn, shown with its difference until `ack-rules`.
14. **Opt-out lifecycle (slice 2):** `disable`, then `managed-lead-loop set`, `reset`, `init --force` with the same roster, restart: still disabled; `--forget-lead-routine-optout` clears it.
15. **Honest health:** a sweep section that fails to read is `sweep-incomplete`, not running; a controller killed right after a sweep is `controller-not-armed`; a corrupt or future-dated record is overdue; a record from another mode is never completed; interactive with no records is `unsupported`; none of these is `running`.

## 12. How each finding of the read was answered

| # | Finding | Answer |
|---|---|---|
| 1 P2 | two callers could send the same hand-off twice | one atomic operation under the existing rank-100 publication lock, with nonce, digest, in-lock re-derivation and payload-conflict refusal; two-process barrier and crash tests (section 5) |
| 2 P2 | obligations can disappear; only `drain` covered | no journal is the authority: obligations are derived from the bus, so there is nothing to lose; every consuming path ends in `advance_cursor` and shows the block; recovery table per boundary; compaction protection (section 5) |
| 3 P2 | worst-case delivery time not supported | best-effort target; eight named unbounded or unavailable cases; bucketed repeat and escalation until closed; success of a reminder turn closes nothing (section 6). Not a second consumer |
| 4 P2 | health undefined or overclaiming | exhaustive 13-row precedence table; sweep coverage with failed sections; machine sweep and judgement parts tracked separately; every mode tested (section 7) |
| 5 P2 | changed rules active before acknowledgement | decision: notify, do not gate; promise narrowed to three enforced items; the pattern-matching claim dropped; single-read test (section 9) |
| 6 P2 | opt-out lost on `init --force`; notice field unnamed | carried by `init --force`; destructive clearing only by explicit flag; field `lead_routine.<agent>.default_on_notice` (section 8) |
| P3 | waiting-seat model incomplete | per-recipient states, late declaration creates a new obligation, `waiting_off`, retirement, `--none-needed` per recipient; membership is not frozen (section 5) |
| P3 | cursor test wrong | stated: the result is consumed once through the normal path, the obligation is separate derived state, a reminder never advances a cursor; the old "moves no cursor" test line is replaced (sections 5, 15) |

## 13. How the challenge's seven points are met

1. **Extend, no new timer, one consumer:** the existing sweep, lease and controller; the derivation and the sending are not consumption.
2. **Decisions on the message path:** the block is in every prompt while owed and the closing command is typed; the sweep catches omissions.
3. **Honest states:** section 7; never from a timer.
4. **On by default for a managed lead, persistent opt-out:** section 8 (slice 2); skills alone start nothing.
5. **Versioned, project-agnostic, exposes rule changes:** section 9; rules are shown, never written by the loop.
6. **Compaction and host support:** section 10.
7. **Kill signals:** no second consumer; no health from a timer; no rule written by the loop. If slice 1 needs a second reader to meet any target, the target is withdrawn, not the rule.

## 14. Assumptions to verify, risks, open questions

1. A small public helper around `_classify_event` can name a result.
2. `drain`, `recv`, `wait` can print the block from their existing render loops without changing their cursor behaviour.
3. `_compute_keep_floor` can take one more protected component without changing its fail-safe returns.
4. `build_cadence_snapshot` can report failed sections without breaking the "partial snapshot still drives" behaviour.
5. The turn prompt assembly can carry a block that appears on every message turn.
6. `relay_to`, `waiting_on`, `waiting_off`, `relay_of`, `relay_nonce`, `relay_outcome` pass the send path as ordinary metadata (they are not in `_RELAY_RESERVED_META`; the send path may have other limits).
7. `LEAD_ROUTINE_VERSION` can be read by code without reading the installed skill file.
8. `checkpoint save --trigger auto` is callable from the sweep.
9. Nothing in `wrap --lead-loop` is Windows-only.
10. The owed-action ledger really does not fit (section 2).
11. Seats will set `waiting_on`. If they do not, only `relay_to` from the lead counts; this is the design's largest honest gap and the skill text must say so.
12. Cost of default-on: no model turn when nothing is actionable (FACT); new items add turns only while an obligation is overdue or a change is shown. ESTIMATE: a quiet team adds none; not measured.
13. The busy-lead delay is a real limit (section 6, case 1). If the operator needs a hard bound during long turns, that needs a decision on turn bounds for leads, not a design workaround.

## 15. The smallest first slice, tests, estimate, files

**Slice 1** (the read's slice, adopted):
1. relay obligations derived from the bus, per recipient, with waiter declarations and cancel;
2. the atomic `relay result` operation (forward or `--none-needed`) reusing the rank-100 publication pattern;
3. the notice on every consuming path (`drain`, `recv`, `wait`; the wrapped prompt on every turn) plus `status` and `lead-routine status`, with the compaction protection that the derivation needs;
4. owed and overdue visibility and best-effort bucketed reminders and escalation through one new sweep item, `relay_overdue`;
5. `lead-routine complete`, and a last-completion field that names exactly what completed (`part`, `kind`, `covered`, `failed`) and never renews another part.

Later: slice 2 default-on, the opt-out, the routine-health label and its table, the `init --force` carry; slice 3 snapshots and rule watching.

**Tests, slice 1.**
- Derivation: declarations, cancel, late declaration, retirement, forged closing message (wrong sender), unsigned message dropped, empty set; torn and missing index.
- Atomic operation: sequential rerun; **two real processes released by a barrier**; crash injected before the send, between the send and the intent update, and after; payload conflict; invalid recipient; lock-order inventory unchanged.
- Consuming paths: result shown through `drain`, `recv --ack`, `wait`, `ack`, the wrapper's `recv_api` path, with the block present or the obligation re-derived.
- Reminders: bucket schedule, reminder turn that ignores the hand-off, escalation count, continuous traffic with the per-turn block, long turn (fake clock), watchdog disabled, lead unarmed.
- Compaction protection; `reset` consistency.
- Last-completion: a sweep does not renew a judgement part; `failed` sections are recorded.
- Skill lint and currency tests (`test_skill_lint.py`, `test_skill_currency.py`): the new commands resolve; both lead skills carry the same step.
- Mutation per rule: remove the in-lock re-derivation, the nonce scan, the sender check, the protection, the bucket growth, the per-turn block: each turns a test red.

**Estimate (ESTIMATE, reasoned, not measured).** Code: about 700 to 900 lines (derivation 200, atomic operation and intent 150, notice blocks across four paths 150, compaction protection 40, sweep item and bucketed reminders 120, `lead-routine complete` and status field 120, skill and doc text 100). Tests: about 1,400 to 1,800 lines, of which the two-process barrier, the crash-injection cases and the consuming-path matrix are the expensive part. About 5 to 7 builder-days for one builder including the locking and recovery tests and one read-and-fix round; the earlier "400 lines, one to two days" did not count any of that and is withdrawn.

**Files touched, slice 1.** New `src/agenttalk/lead_relay.py` (derivation, states), new `src/agenttalk/lead_routine.py` (completion record, status field); `src/agenttalk/store.py` (relay publication function, path helpers); `src/agenttalk/cli.py` (`relay result`, `lead-routine complete`, notice blocks in `_do_recv`, `cmd_wait`, `_lead_loop_drive` prompt, `_compute_keep_floor` component, `status` row); `src/agenttalk/lead_loop_cadence.py` (`relay_overdue`, failed-section reporting); `src/agenttalk/wrapper/prompt.py` (`_CADENCE_RULES`, the per-turn block); `docs/LOCK-ORDER.md` only if a lock is added (none planned); `src/agenttalk/overview.py`, `src/agenttalk/web.py` (one field, one line); both lead skills, `docs/LEAD-GUIDE.md`, `docs/AGENT-MANUAL.md`, `CHANGELOG.md`; tests as above. Slice 2 adds `store.py` (the `lead_routine` key, validator, `init` carry), `doctor.py`, `checkpoint.py`, the `lead-routine` command group and the manuals.

This document itself: `docs/DESIGN-lead-loop-default.md` only. No test opens it and it is not in the source package list (FACT: `tests/test_sdist_docs.py` requires only docs a test opens to be listed; the other `DESIGN-*.md` files are not listed either).
