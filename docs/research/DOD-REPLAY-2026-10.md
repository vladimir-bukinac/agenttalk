# Replay of the definition-of-done draft on six finished jobs (2026-10)

**Verdict: GO for `definition-of-done@1`, as a thin base with profiles, with named limits.** It
makes a few checks unambiguous at the moment the doer hands work over. Most of those checks
were already rules in the review skills; three are new in this version. It does not catch the
largest class of late findings in these jobs (logic that depends on the order of events); an
independent read is still what finds those.

Revision note: this report was first written against the draft at `da8a2075`. An independent
read of that draft found that the replay credited the documentation and migration rows with a
stronger rule than they contained, and asked for a checkable ledger. Both are fixed here: the
rows now say what the replay needed (a procedure is followed in order from its stated starting
state), the counts below are recomputed against the rows as they now read, and every counted
finding has one entry in `DOD-REPLAY-2026-10-ledger.csv` (a test recomputes the totals from it).

## In plain words
The challenge to this skill asked for one test before it is adopted: apply the draft to
finished jobs from this repository and see which late findings it would have caught. Six jobs
were replayed, one each for a bug fix, a feature, a release, a migration slice, a migration
close and a documentation job. Between them they have 61 late findings (things found after
the doer first handed the work over). The draft makes 10 of them unambiguous checks, would
help with 17 more if the person applying it used judgement, and does not catch 34. Of the 10,
seven were already rules in the review skills (the draft moves them to the doer's side, before
the review); three exist only because this fix round added an explicit row. No time or cost
figure is claimed: none was measured.

No investigation job with recorded late findings was found in the history, so the
`investigation` profile was **not replayed**. Judge it on its first real use.

## Method
- Source of each job: the pull request, its review comments and commit messages on GitHub
  (public), plus the review reports on the team's bus for the feature job (cited by bus request
  id and item number).
- A "late finding" is a defect or gap reported after the doer's first handoff of that job, by
  a reviewer, a field run, the repository's CI or the doer's own later read. Findings that two
  reviewers reported once each are counted once; findings that were only wording or style are
  not counted. The feature job's window ends at head `f2219d65`; a later review comment on
  that PR is outside it.
- For each finding, the **literal row** of the profile (as it now reads) was read as written and
  one question asked. **Unambiguous**: a person who does what the row says performs the check.
  **With judgement**: the row points at the area, but a person could satisfy it without finding
  the defect. **Not caught**: no row points at it.
- "Origin" separates a rule that already existed in another skill or in CI ("existing rule")
  from one that exists only in this skill ("no existing rule"), and marks the three rows added
  by this fix round. Findings no row reaches are labelled "review value": independent review
  working as designed.
- Every counted finding is one line of the ledger with its source, the literal row, the
  classification and the origin. The classification is the replayer's reading; a second reader
  could move findings between the first two columns. The "not caught" total is the firmer figure.

## Summary
| # | Job | Profile | Late findings | Unambiguous | With judgement | Not caught |
|---|---|---|---:|---:|---:|---:|
| 1 | Bug fix: a long silent model reply (PR #478) | `bug-fix` | 1 | 0 | 1 | 0 |
| 2 | Feature: the lead loop, slice 1 (PR #528) | `feature` | 39 | 2 | 8 | 29 |
| 3 | Release: v0.101.0 (PR #467) | `project-or-release` | 5 | 2 | 3 | 0 |
| 4 | Migration slice: quota-lease schema 4 (PR #309) | `migration-slice` | 5 | 0 | 1 | 4 |
| 5 | Migration close: the 0.91.x upgrade path (PRs #188, #191, #193) | `migration` | 8 | 3 | 4 | 1 |
| 6 | Documentation: the README front page (PR #364) | `documentation` | 3 | 3 | 0 | 0 |
| | **Total** | | **61** | **10** | **17** | **34** |

Origin of the 27 that are not "not caught": 21 point at an existing rule (7 unambiguous, 14
with judgement), 3 unambiguous ones are the rows added by this fix round, and 3 with judgement
have no existing rule (the reading of "rollback path" in a migration slice, and two procedure
details that depend on the scenario). The restart test and the clock deadline look like gaps of
this skill but are covered by rules the test skills already hold (test-integration: exercise the
real process boundary; bounded polling or an injected clock; test-coverage: deterministic tests);
the final read of the first fix round corrected their origin.

## Job by job

### 1. Bug fix, PR #478
The first fix timed the whole read call, so the recorded wait was the stream's length, not the
gap between bytes. Row: `bug-fix`, "the test uses the real behaviour, not a stand-in". The
first commit's tests used a fake clock, a fake socket and a fake response. **With judgement**:
the row points straight at it, but a doer could call the stand-in faithful.

### 2. Feature, PR #528 (lead loop, slice 1): 39 late findings
- **Order-dependent logic, 29:** a re-ask keeping the old result; a closed hand-off reopened
  by cleanup in batches; a stale controller overwriting a newer record; a partial closing
  marker closing a wait; a rescinded request or half-answered broadcast giving a result; a
  closing for an old wait closing a newer one (four rounds of neighbouring cases); a
  cancellation losing to a closing; the lead role moving; and the rest in the ledger. **Not
  caught.** No row points at them; independent readers found them, which is the process
  working. The three rounds of neighbouring cases are the strongest argument for the first
  proposal below.
- **Tests weaker than claimed, 2 (with judgement):** a "restart" test that never restarted
  (row: anything that must survive an interruption or a restart has a test; a person could
  call a test that never restarts a test of it) and two-process tests that used a clock
  deadline.
- **Project checks not run before the handoff, 2 (with judgement):** two repository tests that
  mirror the command list and the prompt rules failed in CI after the targeted tests passed.
  The row "no new warnings from the project's checks" covers it only if "the project's checks"
  means the whole CI set; this project's own rule was "targeted tests in the turn, CI is the
  gate", which an overlay has to reconcile.
- **Input classes, 4 (with judgement):** shell characters in command text, non-finite numbers in
  a state file, a mistyped seat name, a comma in an identifier. "The failure paths" points at
  them without naming input classes.
- **Claims in text contradicting the code, 2 (unambiguous, documentation part):** a documented
  escalation schedule that the code did not follow, and a memory-bound sentence. The feature
  ships a design page, so the documentation row "every factual claim is checked against the
  code" applies to it.

### 3. Release, PR #467 (v0.101.0): 5 late findings
- The operations guide and the roadmap status column still named the previous version.
  **Unambiguous**: "every place that names the version agrees" is a search.
- Three summary sentences stated a guarantee without its exception. **With judgement**: "the
  summary states each guarantee exactly, with its exceptions" names the failure but needs a
  reader.
- The team left the roadmap label for later because changing it would restart the release CI,
  and wrote that down: the exception rule working (a recorded scope reduction), not a silent
  skip.
- Existing rule: `review-release-readiness` already lists version, changelog and pins.

### 4. Migration slice, PR #309 (child-cap schema 4 and its migration): 5 late findings
- Older code could still write an upgraded ledger. **With judgement**: row A9 lists launch
  paths including the rollback path; it finds this only if "rollback path" is read as "the
  original code against the migrated data".
- A receipt replaceable by a replacing insert, a clock rollback accepted on an empty table, an
  oversized number and a deeply nested record escaping as tracebacks. **Not caught**: no
  migration row points at data-integrity guards or hostile input.
- The strong rows (same results test by test, same behaviour from outside, mutation testing)
  have nothing to compare in a slice whose point is a new data format.

### 5. Migration close, PRs #188, #191 and #193 (a gateway upgrade path): 8 late findings
- The service layer used the default price policy while the ledger held the real one; every
  piece agreed with the others, so it ran (a field finding). **Not caught**: nothing compares
  the layers with each other.
- Written upgrade path, three gaps found in a real upgrade and a review. **Unambiguous for
  three**: stop must run with the runtime that registered the task; an old task must be
  unregistered when the interpreter changes; a step that needed a canary the blocked wrapper
  must create (circular). These are unambiguous **only because of the row added in this fix
  round**: a procedure is followed in order, from its stated starting state, by a fresh run or
  by someone who did not write it (documentation profile; migration B9). The first draft said
  only that every command was run, which separately successful commands satisfy while the
  assembled sequence stays circular; under that wording these three would have been "with
  judgement". **With judgement for four:** a slow first start that exits non-zero (timing), a
  query that picks one of several attempts, a stale marker after an unclean exit, a wrong
  "stopped" test: each needs the right scenario, not only the in-order run.

### 6. Documentation, PR #364 (README front page): 3 late findings
A setting described as needed by every Codex seat when only wrapped ones read it; a statement
about lanes that ignored the advisory mode; a check-in command without its prerequisite.
**Unambiguous (3)**: each is a claim contradicted by the command's own help text or the code,
and "every factual claim is checked against the code or marked unverified" forces that check.
Existing rule: `review-docs` already says to verify every claim; the draft asks the doer to do it
before the review.

## What the draft changes, and what it does not
- It makes explicit, at the doer's handoff, checks that already exist for reviewers: versions
  and pins, claims against code, tests that use the real thing. In four of the six jobs the late
  findings were largely of this kind.
- It adds one real requirement, the in-order procedure rehearsal, which the replay shows
  matters for upgrade guides.
- It names the exact artifact each check ran on, which none of the six handoffs did in the same
  way.
- It does not find order-dependent logic, data-integrity guards or hostile input; those need an
  independent read or a different kind of test. That is by design: the challenge warned that
  more checklist rows do not stand in for review.
- Two of its rows can be read two ways, which the replay showed: "the project's checks" in the
  `feature` profile and "rollback path" in a migration slice. Both are left to the project
  overlay and the exception rules in v1; they are in the proposals below.

## Candidates for a later version (proposals only, not applied)
Under the skill's own rule, a lesson changes the policy only after the maintainer reviews it.
The replay suggests three proposals; none is in `@1`:
1. **Order-dependent state:** a model test over event orderings against a short reference model.
2. **Data-format migration slice:** run the original code against the new data and the new code
   against the old data.
3. **Project checks before handoff:** state in the overlay which checks run in the turn and
   which gate runs in CI, so "the project's checks" is not read two ways.

## Limits of this replay
- Six jobs from one repository and one team; late findings were reconstructed from the public
  pull request threads, commit messages and the team's review reports (bus request ids and item
  numbers). A finding that was never written down is not counted, and completeness of the 61
  was not independently checked.
- The classification is one reader's; the ledger makes each call visible so another reader can
  change it and recompute.
- No timing or overhead was measured and none is claimed.
- The investigation profile was not replayed (no suitable job).
