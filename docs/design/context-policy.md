# Design note: context policy for wrapped seats (resume, summary, or fresh)

Status: DESIGN ONLY, written 2026-09-22 during the agenttalk freeze, from the codex and claude usage
measurements of 2026-09-21/22 (see the lead's investigation note). Nothing here is implemented.
Owner: lead. First post-freeze design, together with the acceptance feature.

Added to the repository on 2026-10-13 unchanged, as the starting point for #475 and the roadmap's §6.11.
It predates the attempt-bound completion record (#178) and the 2026-10-13 case of a lead at 830 turns, so it is
refreshed before steps 2 and 3 are built, and they get their own challenge. Step 1 (#475: a supported fresh start
for one agent, and a size warning) does not depend on it.

## 1. The problem, measured

A wrapped seat runs one CLI session for as long as the wrapper lives, and resumes it on every turn.
The session grows with every tool output until it sits at the CLI's ceiling (codex: 250-280K tokens
per call; claude: the 1M window, where compaction then fails). Every tool step of a turn re-sends the
whole context. Result, measured on this fleet: one codex dispatch averaged 1.6M input tokens; three
codex seats consumed 890M input tokens in nine days; two claude seats reached the ceiling and looped
on failed compactions. Retries of a failed turn re-sent the same context up to twenty times.

The fix is not a cheaper model. It is deciding, per turn, how much of the past the seat needs.

## 2. Three modes

| Mode | What the seat gets | When it is right |
|---|---|---|
| RESUME | its full thread | it is continuing its own multi-part work and the thread is still small |
| SUMMARY | a fresh session seeded with its own handoff note + the context pack | a new work order, a retry, a thread past the ceiling |
| FRESH | a fresh session with the dispatch only | a cold read (no memory of the author's claims), a new seat, onboarding |

## 3. The decision, made by the wrapper at turn start

Inputs, in order of authority:

1. **The sender's declaration.** `send`/`task`/`handoff` gain `--context resume|summary|fresh`.
   Defaults by kind when absent: `task` -> summary; `review-request` -> fresh; a `reply` inside a
   thread the seat itself opened -> resume; `nudge`/`ack`/notices -> resume, or skipped entirely
   when the seat is idle with nothing owed.
2. **The measured context.** The wrapper already sees the CLI's stream (`capacity.py` reads the
   claude `context_window` block; the codex stream carries `token_count.last_token_usage`). Rule:
   if the last turn's context exceeded the per-CLI rotation ceiling (proposed: codex 60K, claude
   200K) or is more than five times the size of the incoming dispatch, RESUME is downgraded to
   SUMMARY. The ceiling is config, per CLI and per seat.
3. **Failure state.** A retry of a failed turn is never a RESUME (it was the resume that failed):
   it goes SUMMARY, and no compaction is attempted on a retry. A usage-limit or quota error is
   terminal until the CLI's own `resets_at`; the seat pauses instead of retrying.
4. **Role default.** Reviewers default to FRESH (a cold read must not remember the author's
   earlier claims - this is the "no expectation" rule made structural). Workers default to SUMMARY
   per dispatch. The lead resumes, and rotates through SUMMARY at its own compaction.

## 4. The handoff note (what a SUMMARY carries)

Two halves, both small:

- **Deterministic half, written by the wrapper** (extends `checkpoint.py`, which already snapshots
  capacity, validated threads and git plumbing): seat name and role, worktree path, branch and tip,
  dirty files, open threads the seat owes a reply on, the last three message ids it handled.
- **Agent half, written by the seat at the END of every turn** (a required last action, at most
  ~800 tokens, refused if longer): what is done, what is next, open questions, commands that worked
  with their exact flags, decisions taken and why. Stored at `.agenttalk/state/<seat>.handoff.md`,
  versioned per turn. A turn that ends without it is flagged, the way an unsent reply is today.

On SUMMARY the wrapper prepends: the handoff note, the context pack for the arc (#158: guardrail
sections, record paths, toolchain paths), and the dispatch. Nothing else. The old session is kept on
disk for audit and is never resumed again.

## 5. What the lead sees

- `agenttalk status` shows per seat: session age (turns since fresh), last context size, tokens in
  the last 24 h and 7 days, rotations, and the mode of the last turn.
- A usage ledger per seat, built from the same stream events, so "why did we burn the allowance"
  is a query, not an investigation.

## 6. Interaction with existing pieces

- `reset-bloated-wrapped-agent` (the manual ritual) becomes the SUMMARY mode done by hand.
- `capacity.py` already normalizes both CLIs' budget and context signals; the decision reads it.
- `lesson_context.py` already renders accepted lessons per turn; they ride in the context pack.
- The dead-letter caps (`escalate_after_attempts`) stay, but rule 3 makes most retries unnecessary.
- Nothing here touches the bus format; a seat on an older wrapper ignores `--context`.

## 7. Open questions for the adversarial read

- Rotation ceiling per CLI: measured defaults or per-project config only?
- Can a seat refuse SUMMARY (it knows it is mid-way through an uncommitted change)? Proposal: it
  cannot refuse, but its handoff note says so and the fresh session recovers from disk.
- Does the agent half of the handoff note leak client identifiers into a shared file? The same sweep
  rule as records applies; the note is per project root.

## 8. Added 2026-09-22 (operator question): project knowledge and per-seat memory as the starting point

The operator asked whether domain knowledge can be stored per project, fresh agents can start from it, and
team members can keep their own memory across restarts. Yes; the pieces exist, the assembly does not.

**What exists today.**
- Project knowledge: `agenttalk knowledge` (durable pointer notes with an anchor into the code or a
  thread, marked stale when the anchor changes) and `agenttalk onboarding` (the ledger of what was read,
  claims with evidence, drift, open unknowns). Both are per project root, both survive every restart,
  neither is put in front of a fresh seat automatically.
- Accepted lessons: `lesson_context.py` renders them into wrapped turns already.
- The migration folder in a client project (guardrails, register, decisions, step records) is the real
  domain knowledge of that programme; it is read by seats only when a dispatch tells them which file.
- The lead's own memory (a directory of one-fact files with an index loaded at session start) is the
  working model of per-agent memory; it is what let the lead resume across four compactions today.

**Proposal: two stores, one loader.**
1. **Project knowledge store**, `.agenttalk/knowledge/` in the project root (already the home of notes):
   add a curated `PROJECT.md` (what the system is, the stack, the toolchain roots, the rules that every
   task cites, the record paths) kept short and versioned, plus the notes and the onboarding ledger. This is
   the domain knowledge. The lead curates it at every slice close (the same moment the register is closed).
2. **Per-seat memory store**, `.agenttalk/memory/<seat>/`: `MEMORY.md` as an index of one-line pointers and
   one file per fact, the same shape as the lead's memory, written by the seat as a required last action of
   each turn (the handoff note of section 4 is its newest entry; older facts are promoted into it when they
   prove durable: commands that work, gotchas of this codebase, decisions the seat took and why). It is
   project-scoped, survives restarts and resets, and is never shared between seats except by the lead
   copying a fact into the project store.
3. **The loader** is the SUMMARY/FRESH mode of section 2: a fresh session gets `PROJECT.md` + the arc's
   context pack + the seat's own `MEMORY.md` index (not the fact files; it reads those on demand) + the
   dispatch. Size is bounded: `PROJECT.md` and the index together stay under a few thousand tokens.

**Policy.** FRESH-with-knowledge becomes the default for every dispatch; RESUME is the exception a sender
asks for. That inverts today's default and is what makes the token numbers of 2026-09-21 impossible.

**Discipline that comes with it** (learned from the lead's own memory): one fact per file; the index never
holds content; a fact names the file or command it is about so a fresh seat can verify it still holds;
stale facts are deleted, not accumulated; client identifiers never enter a store that could be exported.

