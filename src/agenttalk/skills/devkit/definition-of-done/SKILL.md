---
name: definition-of-done
description: >-
  State what "done" means for a task, check it with executed evidence, and record it
  in one short done record, before you hand work over or call it finished. One small
  base for every task (scope, exact artifact, executed checks, limits, next owner),
  plus stricter profiles by kind of work and risk (review, documentation,
  investigation, bug fix, feature or greenfield slice, greenfield project or release,
  migration slice, whole migration). Use at assignment (to pin the profile) and at
  handoff (to write the record). Do NOT use it to accept a product (use the close
  flow), to decide a release (use review-release-readiness), or as an extra review
  round.
reviewed-against: "0.102"
category: assurance
evidence-profile:
  - production-handoff
---

# definition-of-done

In plain words: "done" means three different things, and teams lose time when one is
mistaken for another. This skill is about the first one only: **the assigned task is
finished**. It gives every task the same short list of things to show, and asks for a
little more when the work is bigger or riskier. It does not accept the product and it does
not allow a release; other rules do that.

## QUICK START
1. At assignment, the lead names the profile (table below) and the policy version in the
   task text, for example `done-profile: bug-fix, risk: normal, definition-of-done@1`. The
   profile does not change while the task runs.
2. Work. Keep a list of the checks the profile asks for.
3. At handoff, write the done record (next section): five lines, plus one line for each
   exception.
4. Hand it to the next owner named in the record. The record says what is finished; it
   never says "accepted" or "ready to release".
5. A check that could not run is not "not applicable". It stays open (EXCEPTIONS).

## The three things kept apart
| Question | Who answers it | Where it lives |
|---|---|---|
| Is the assigned task finished? | The person who did it, with evidence, checked by someone else where the profile says so | this skill |
| Is the product accepted? | The lead, from reviews and the close | the `close` flow and its definition-of-done dimensions (assurance, coverage, knowledge, acceptance) |
| May it be released? | The lead, on evidence for the actual revision | `review-release-readiness` |

A review-only or investigation task can be finished with a negative result. It never needs
product acceptance or release checks to be finished. This skill adds no new verdict, no
extra review round and no approval step.

## The base: the done record (every task)
Write these five lines at handoff. Say each in plain words first.
1. **Scope and outcome.** What was asked and what came out of it, in two sentences. Name
   what was left out.
2. **Artifact.** The exact thing delivered: the repository and full revision, or the file
   and its hash. Every check below says which artifact it ran on. For comparisons, give the
   role of each build: **original** (the starting point), **candidate** (what is
   delivered), **derived** (made from the candidate for a check, for example a test build).
   Evidence about a different build does not count.
3. **Checks.** One row per check the profile asks for: the check, the exact command or run
   id, the result. "Referenced" is not "executed": a test you only read is listed as
   referenced.
4. **Limits and open items.** Everything not done, not run or not known, each with a reason
   and an owner. An empty list is a claim: write "none" only if it is true.
5. **Next owner.** Who acts next and on what (review, acceptance, fix, release decision).

Evidence fields: use the evidence profile of the task's kind (`production-handoff`,
`review-result`, `qa-result`, `planning-artifact`); the record is the same facts under
those names, see "Reuse" below.

## Profiles: pick by kind of work, raise by risk
Each profile is the base plus the extra rows shown. A profile never removes a base row.

| Profile | Use it for | Extra rows |
|---|---|---|
| `review-only` | A review or audit that reads, and maybe runs, someone else's work | The reviewed revision is named in full. What was read and what was run are listed apart. A negative verdict is a finished task. No release or acceptance rows. |
| `documentation` | A README, guide, manual, design or policy text | Every factual claim is checked against the code or marked unverified. Every command and example was run, or is marked not run with the reason. Version pins and counts agree with the release. The audience is named. |
| `investigation` | A question to answer, with no change to deliver | The question, the method, what was ruled out, how sure the answer is and what would change it, with pointers to the evidence. A next step is recommended, not done. |
| `bug-fix` | A defect to remove | The defect is shown on the original revision. A test fails without the fix and passes with it. The test uses the real behaviour, not a stand-in. Nearby cases are named. The affected suites ran. |
| `feature` | A feature or a slice of a new project | The acceptance criteria are listed. Each behaviour has a test, including the failure paths and anything that must survive an interruption or a restart. User-visible change is in the changelog. No new warnings from the project's checks. A different seat reviewed it. |
| `project-or-release` | A whole new project, or a release candidate | Exit criteria agreed at the start. A clean checkout builds, and the built artifact installs and runs. Every place that names the version agrees. The summary states each guarantee exactly, with its exceptions. Known limits are listed. CI ran on this revision (run id). Rollback is stated. |
| `migration-slice` | One piece of a platform or data migration | See `references/migration.md`, part 1. |
| `migration` | A whole migration | See `references/migration.md`, part 2. |

**Risk.** Add a risk word to the profile: `normal` or `high`. High means money, security,
data that cannot be recovered, many users, or an action that cannot be undone. High adds:
a reader from a different vendor than the doer; the undo or rollback path stated and
tried where it can be; no exception without the exception authority's written decision.

## EXCEPTIONS
- **Not applicable** is decided at assignment, in the task text, with the reason, and
  accepted by a named checker who is not the doer. Deciding it afterwards, because the
  check is inconvenient, is a scope reduction (below).
- **A required check that could not run stays open.** The record says "not run", why, and
  what that leaves unknown. It becomes closed only through a **recorded scope reduction**:
  the exception authority writes what is dropped, why, who accepts the risk and until when.
  A reason alone never waives a check.
- **Never waivable:** the exact artifact is named; secrets are referred to by location and
  never copied; the record is honest (nothing unfinished is called finished).
- **Who:** the project names a **maintainer** of this policy and an **exception authority**
  in its overlay. Until it does, the lead is both, and the operator decides when the lead
  is the doer.

## Pinning, change and overlays
- **Pinned.** The policy version and the profile are written in the task when it is
  assigned. A later version changes new tasks, not running ones. An urgent safety change
  may be applied to a running task only by the maintainer, in writing, with the reason.
- **Version and delivery.** This text is `definition-of-done@1`. Every vendor's seat gets it
  through the installed devkit skills, so a task that names `@1` can be checked against the
  same text by anyone.
- **Lessons change it only after review.** A lesson never edits the policy by itself. The
  maintainer reads the proposed change, decides, and bumps the version. A proposal that
  adds a row to every task needs a reason that is not "it happened once".
- **Project overlays.** A project adds what is specific to it in a short overlay file it
  owns (`references/project-overlay.md` shows the shape): offline or isolated builds,
  branch rules, a named mutation tool, hosts that must never be touched, vendor rules. An
  overlay can add rows and name people. It cannot remove a base row or a profile row.

## Reuse
- Evidence fields and rules: `../_shared/references/evidence.md`. Do not invent new field
  names; map the record onto them: scope and outcome to `summary` or `scope`; artifact to
  `base_ref`, `head_ref` or `reviewed_ref`; checks to `tests_referenced` and
  `tests_executed`; limits to `residual_risk`; next owner to `required_review_lenses` or
  the reply's next step.
- Acceptance and close: the `close` command and its definition-of-done dimensions. This
  skill does not repeat them.
- Release: `review-release-readiness`.
- Plain writing: `../_shared/references/plain-language.md`.

## Technical detail
- The done record is text in the handoff or reply. Nothing in the bus enforces it today
  (SKILL-POLICY). The `close` flow is the enforced part.
- A check's "result" is the exit code and the counts, not "passed".
- A task made of several kinds of work meets the rows of each part: a feature that also
  ships a manual page meets the documentation rows for that page. The base record is written
  once, and the stricter row wins where two rows overlap.
- Replay evidence for this version: `docs/research/DOD-REPLAY-2026-10.md`.

## Evidence

Emit the `production-handoff` profile (full rules + bus-validated vs skill-policy: ../_shared/references/evidence.md).

Required fields:

- `changed_files`
- `base_ref`
- `head_ref`
- `summary`
- `tests_referenced`
- `tests_executed`
- `residual_risk`
- `required_review_lenses`
- `evidence`
