# Replay of the definition-of-done draft on six finished jobs (2026-10)

**Verdict: GO for `definition-of-done@1`, as a thin base with profiles, with named limits.** It
makes a few checks unambiguous at the moment the doer hands work over. It does not catch the
largest class of late findings in these jobs (logic that depends on the order of events); an
independent read is still what finds those.

## In plain words
The challenge to this skill asked for one test before it is adopted: apply the draft to
finished jobs from this repository and see which late findings it would have caught. Six jobs
were replayed, one each for a bug fix, a feature, a release, a migration slice, a migration
close and a documentation job. Between them they have 61 late findings (things found after
the doer first handed the work over). The draft would have made 11 of them unambiguous
checks, would have helped with 15 more if the person applying it used judgement, and would not
have caught 35. Most of the 11 were already rules in the review skills; the draft moves them
to the doer's side, before the review. No time or cost figure is claimed: none was measured.

No investigation job with recorded late findings was found in the history, so the
`investigation` profile was **not replayed**. Its rows are the base plus the question,
method and confidence, and it should be judged on its first real use.

## Method
- Source of each job: the pull request, its review comments and commit messages on GitHub
  (public), plus the review reports on the team's bus for the feature job.
- A "late finding" is a defect or gap reported after the doer's first handoff of that job,
  by a reviewer, a field run or the doer's own later read.
- For each finding, the draft's rows for that job's profile were read as written and one
  question asked: does a specific row name this? **Unambiguous**: the row, applied as
  written, forces the check. **With judgement**: the row points at the area but a person
  could satisfy it without finding the defect. **Not caught**: no row points at it.
- The challenge asked to separate "missing requirement" from "ignored existing rule". That
  split is shown in the last column of the summary table.

## Summary
| # | Job | Profile | Late findings | Unambiguous | With judgement | Not caught | Row would be new or existing |
|---|---|---|---:|---:|---:|---:|---|
| 1 | Bug fix: a long silent model reply (PR #478) | `bug-fix` | 1 | 0 | 1 | 0 | existing (test-coverage) |
| 2 | Feature: the lead loop, slice 1 (PR #528) | `feature` | 39 | 2 | 7 | 30 | 1 new, 1 existing |
| 3 | Release: v0.101.0 (PR #467) | `project-or-release` | 5 | 2 | 3 | 0 | existing (review-release-readiness) |
| 4 | Migration slice: quota-lease schema 4 (PR #309) | `migration-slice` | 5 | 0 | 1 | 4 | none |
| 5 | Migration close: the 0.91.x upgrade path (PRs #188, #191, #193) | `migration` | 8 | 4 | 3 | 1 | existing (review-docs) |
| 6 | Documentation: the README front page (PR #364) | `documentation` | 3 | 3 | 0 | 0 | existing (review-docs) |
| | **Total** | | **61** | **11** | **15** | **35** | |

## Job by job

### 1. Bug fix, PR #478 (a long silent reply ended as an uncertain paid attempt)
- Late finding: the first fix timed the whole read call, so the recorded wait was the
  stream's length, not the gap between bytes (review P2, fixed in a second commit with a real
  socket that trickles a chunked reply).
- Row: `bug-fix`, "the test uses the real behaviour, not a stand-in". The first commit's tests
  used a fake clock, a fake socket and a fake response whose read call takes the whole
  silence. **With judgement**: the row points straight at it, but a doer could call the
  stand-in faithful.
- Not new: `test-coverage` already asks for behaviour-focused tests.

### 2. Feature, PR #528 (lead loop, slice 1): 39 late findings in five fix rounds and one CI run
Classes (each finding in one class; rounds named in the PR and its review reports):
- **Order-dependent logic, 30:** a re-ask dropping the old result; a closed hand-off
  reopened after cleanup in batches; a stale controller overwriting a newer record; a
  partial closing marker closing a wait; a rescinded request or a half-answered broadcast
  giving a result; a closing for an old wait closing a newer one (four rounds of
  neighbouring cases); a cancellation losing to a closing; the lead role moving; and so on.
  **Not caught.** No row of the draft points at them. They were found by independent
  readers, which is what the process is for; this is not a failure of the draft.
- **Test evidence weaker than claimed, 2:** a "restart" test that never restarted
  (**unambiguous**: the `feature` row "anything that must survive an interruption or a
  restart" is tested), and two-process tests that used a clock deadline instead of a
  readiness barrier (**with judgement**).
- **Project checks not run before the handoff, 2:** two repository tests that mirror the
  command list and the prompt rules failed in CI after the targeted tests passed.
  **With judgement**: the `feature` row "no new warnings from the project's checks" covers
  it only if the project's checks mean the whole CI set; this project's own rule was
  "targeted tests in the turn, CI is the gate", which is what an overlay would have to
  reconcile (see the limits below).
- **Input classes, 4:** a request id with shell characters in command text, non-finite
  numbers in a state file, a mistyped seat name, a comma in an identifier. **With judgement**:
  "the failure paths" row points at them without naming input classes.
- **Wrong claims in text, 1:** a memory-bound sentence in code and design. **Unambiguous**
  once the multi-part rule applies (the feature ships a design page, so the documentation
  rows apply to it).

### 3. Release, PR #467 (v0.101.0): 5 late findings
- The operations guide still named 0.100.0 and told operators to expect it; the roadmap's
  status column still read 0.100.0: both are places that name the version.
  **Unambiguous**: the row "every place that names the version agrees" is a search.
- Three summary sentences stated a guarantee without its exception (a failed start keeps its
  stop file only before the task-start request is accepted; throwaway-store isolation is
  opt-in; an acceptance close whose runner has left needs a new attempt).
  **With judgement**: the row "the summary states each guarantee exactly, with its
  exceptions" names the failure, but needs a reader.
- The team left the roadmap label for later because changing it would restart the release CI,
  and wrote that down. That is the exception rule working: a recorded scope reduction by the
  person with authority, not a silent skip.
- Not new: `review-release-readiness` already lists version, changelog and pins.

### 4. Migration slice, PR #309 (child-cap schema 4 and its migration): 5 late findings
- Older code could still write an upgraded ledger (it refused the new version in one place
  only). **With judgement**: row A9 lists launch paths including the rollback path; it
  finds this only if "rollback path" is read as "the original code against the migrated
  data".
- A receipt could be replaced by a replacing insert; the migration accepted a clock
  rollback when a table was empty; an oversized number and a deeply nested record escaped as
  tracebacks. **Not caught**: no migration row points at data-integrity guards or at hostile
  input.
- The draft's strong rows (same results test by test, same behaviour from outside, mutation
  testing) have nothing to compare in a slice whose point is a new data format.

### 5. Migration close, PRs #188, #191 and #193 (a gateway upgrade path): 8 late findings
- The service layer fingerprinted its files with the default price policy while the ledger
  held the real one; every piece agreed with the others, so it ran (a field finding). **Not caught**: nothing compares the layers with each other.
- The written upgrade path missed three things found in a real upgrade (stop must run with
  the runtime that registered the task; an old task must be unregistered when the
  interpreter changes; a slow first start can exit non-zero while the service comes up), and
  its review found a circular step, a wrong query for one request, a stale marker and a wrong
  "stopped" test. **Unambiguous for four** (the three field gaps and the circular step): the
  `documentation` row "every command and example was run" and `migration` row B9 ("run and
  upgrade instructions are written, and labelled rehearsals where not proven") force running
  the steps in order from the starting state. **With judgement for three** (query, marker,
  listener test): they need the right scenario, not only the run.

### 6. Documentation, PR #364 (README front page): 3 late findings
- A setting described as needed by every Codex seat when only wrapped ones read it; a
  statement about lanes that ignored the advisory mode; a check-in command without its
  prerequisite. **Unambiguous (3)**: each is a claim contradicted by the command's own help
  text or the code, and the row "every factual claim is checked against the code or marked
  unverified" forces that check.
- Not new: `review-docs` already says to verify every claim; the draft asks the doer to do it
  before the review.

## What the draft would have changed, and what it would not
- It makes explicit, at the doer's handoff, checks that already exist for reviewers:
  versions and pins, claims against code, commands run in order, tests that use the real
  thing. In four of the six jobs the late findings were of this kind.
- It names the exact artifact each check ran on, which none of the six handoffs did in the
  same way.
- It does not find order-dependent logic, data-integrity guards or hostile input; those
  need an independent read or a different kind of test. That is by design (the challenge
  warned that more checklist rows do not stand in for review).
- Two of its rows could be read two ways, and the replay showed how: "the project's checks"
  in the `feature` profile (whole CI set, or the targeted set the project allows in a turn)
  and "rollback path" in a migration slice (old code on new data). Both are left to the
  project overlay and the exception rules in v1; they are listed below for the maintainer.

## Candidates for a later version (proposals only, not applied)
Under the skill's own rule, a lesson changes the policy only after the maintainer reviews it.
The replay suggests three proposals; none is in `@1`:
1. **Order-dependent state:** a model test over event orderings against a short reference
   model (the lead-loop work found that case-by-case fixes did not converge).
2. **Data-format migration slice:** run the original code against the new data and the new
   code against the old data.
3. **Project checks before handoff:** state in the overlay which checks run in the turn and
   which gate runs in CI, so "the project's checks" is not read two ways.

## Limits of this replay
- Six jobs from one repository and one team; the late findings were reconstructed from the
  public pull request threads, commit messages and the team's review reports. A finding
  that was never written down is not counted.
- "Unambiguous" and "with judgement" are the replayer's reading. A second reader could move a
  few findings between the two columns; the totals of "not caught" are the firmer figure.
- No timing or overhead was measured and none is claimed.
- The investigation profile was not replayed (no suitable job).
