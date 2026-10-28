# Design: rolling out the secure-coding standard

Status: proposed. Written on 2026-10-28 for work order tk-6f367777d3cc, after the challenge ch-651fb888 returned RESHAPE and the lead accepted it, and revised in fix round tk-4f0f5ca4e611 after the read tk-1297b29787e4. Nothing here is built: no skill, template or workflow changes until the operator says OK and a reader from another AI vendor has read this branch. Where this page describes agenttalk today, it matches master `eebe3460`. Owner: the lead.

## In plain words

[The secure-coding standard](../SECURE-CODING.md) asks a builder to write a short security note before coding, choose protections while coding, and show at handoff which code and which executed checks carry each choice. This page plans how the standard would reach everyone who writes or reads code: which skills, briefs and contributor pages would point to it, and how someone working from a fork, without our tools, sees it. It also plans a small trial that can fail: one real Python change, and a generic Java example built twice over, with and without the standard, so that any difference can be put down to the standard. It decides the order of the work, the bar the trial must pass and what happens when the standard makes no difference; it leaves open the questions in section 7.

## Contents

1. [Order of work](#1-order-of-work)
2. [Where the standard would be loaded](#2-where-the-standard-would-be-loaded)
3. [What a contributor from a fork sees](#3-what-a-contributor-from-a-fork-sees)
4. [Evidence wording, shared with the development flows design](#4-evidence-wording-shared-with-the-development-flows-design)
5. [The trial](#5-the-trial)
6. [Alternatives considered](#6-alternatives-considered)
7. [Open questions](#7-open-questions)
8. [Technical details](#8-technical-details)

## 1. Order of work

1. **This branch** (`docs/secure-coding-standard`): the standard (`docs/SECURE-CODING.md`), the corrected section 1 of `docs/ASSURANCE.md`, and this plan. A reader from another AI vendor reads it.
2. **The operator's OK** on the standard and on this plan.
3. **The trial** (section 5). Its authors get the standard from this branch, not from a skill, so the trial needs no skill change.
4. **One pull request that wires the standard in** (section 2), only if the trial meets its bar and no kill signal fired. It goes through the normal review cycle. If the trial shows no difference, there is no such pull request: the team takes the smaller alternative in section 6 instead.
5. **Review** of the standard by 2027-04-28, or earlier on the triggers in its section 10.

The standard adds no approval at any step. The rule conflict that the challenge named is settled first, on this branch: `docs/ASSURANCE.md` section 1 now follows the definition of done and `CONTRIBUTING.md`, and marks the standard as proposed.

## 2. Where the standard would be loaded

**Every route that writes code loads the rules first.** The standard applies to every change to code, tests included (its section 1). So every skill whose output is a change to code or tests points to the rules in its *first* step, before anything is written; a pointer only at handoff, or only in a lead's brief, is too late for a skill that is used on its own. Skills that only read, plan or write documentation get no pointer.

**One source, and a general part that any project can use.** The standard has two parts. Part 1, between two marker lines, holds the general rules: the three steps, the ten principles, agent-written code and the examples. It names no project, path or tool of agenttalk's, so it follows the playbook rule that skills and shared texts stay universal (`docs/playbook/build-and-test.md`, B10). Part 2 holds what is agenttalk's own: its trust boundaries, its project rules under the principles, where the lines go here, the existing checks and the framework map. The skills carry only part 1.

**A pinned version.** A task names the version it works under (`secure-coding@1`), the way it already names its definition-of-done profile. A later version then never changes what work already started owes. This follows the team's lesson that obligations belong on the work's own dispatch record (`design.pin-obligations-on-the-immutable-work-record`).

| Entry point | File | Who uses it | Proposed change |
|---|---|---|---|
| A shipped copy of part 1 | new: `src/agenttalk/skills/devkit/_shared/references/secure-coding.md` | anyone who installs the skills with `agenttalk install-skills`, in any project | the text between the marker lines of `docs/SECURE-CODING.md`, with its version line. Two repository tests: the copy is identical to the marked text, and the marked text contains none of a list of agenttalk-specific words (its name, its state folder, its source paths, its bus terms). |
| craft-code | `src/agenttalk/skills/devkit/craft-code/SKILL.md` | builders of production code | BEFORE: write the security note (step 1). WHILE: choose protections from P1 to P10 (step 2). AFTER: add the security lines to the handoff (step 3). Each item points at the shared copy. |
| refactor-code | `src/agenttalk/skills/devkit/refactor-code/SKILL.md` | builders of refactors | first step: the note, like any change. A refactor that moves, merges or simplifies code at a boundary (a path check, a permission check) names that boundary, and its handoff shows that the protection still holds, with the same check before and after. Only a refactor that touches no boundary writes `no trust boundary`. |
| fix-ci | `src/agenttalk/skills/devkit/fix-ci/SKILL.md` | builders of fixes for red checks | first step: the note, for every fix that changes code or tests, not only workflows. A fix that changes a workflow, a scanner setting or a dependency also checks P7 and P10. |
| test-coverage, tester-qa, test-security, test-integration, test-performance | each skill's `SKILL.md` | whoever writes tests, test harnesses or benchmarks | first step: the note. For most tests it is one line, `no trust boundary`; a test or fixture that starts processes, writes outside its own temporary folder, uses the network or handles a secret names that boundary. test-security also names the principle (`P<n>`) in its abuse-case evidence, so that handoff lines can cite those checks. |
| test-docs | `src/agenttalk/skills/devkit/test-docs/SKILL.md` | whoever checks documentation by running it | the same first-step pointer, used only when it adds check code to the repository. |
| definition-of-done | `src/agenttalk/skills/devkit/definition-of-done/SKILL.md` | everyone at handoff | one sentence under "Where the record goes": the security lines go in `evidence`, the commands in `tests_executed`, the open lines in `residual_risk`. No new field and no new profile row. |
| review-code | `src/agenttalk/skills/devkit/review-code/SKILL.md` and `references/security.md` | every reader | the security pass also checks the builder's lines (the list "What the reader checks" in step 3), and findings name the principle they break. The existing OWASP-based checklist stays as it is. |
| The lead's skill | `src/agenttalk/skills/claude/agenttalk.lead.md` and `src/agenttalk/skills/codex/agenttalk-lead/` | the lead | a build, fix or test brief names `secure-coding@1` next to the done profile; a read brief asks the reader to check the security lines. A brief to a seat that has no skills carries the pointer to part 1 itself. |
| The procedures | `docs/ROLES-SKILLS-PROCEDURES.md`, sections 4.1 and 4.2 | the team | one sentence each: the brief pins the version; the reader checks the lines. |
| The contributor guide | `CONTRIBUTING.md`, "Before you send a pull request" and "Proposing a change" | outside contributors | one bullet each: for a change to code or tests, read the standard (linked by its web address) and put the three-line note in the issue; add the security lines under "How you checked it". |
| The pull request template | `.github/pull_request_template.md` | everyone who opens a pull request | widen the existing prompt "How you checked it" with "(for code: the security lines, see SECURE-CODING.md)". It stays four prompts. |

**Left out on purpose:** the review lenses other than `review-code` (`review-failure-injection` already covers what P7 and P8 ask), `qa-strategy` (it plans and writes no code; its risk list can feed a builder's note), `assurance-scan` (it runs the existing scanners), the documentation skills (documentation needs no note), and the README.

**A known gap:** seats on the paid gateway do not see the shipped skills (issue #468). Until that is fixed they get part 1 only through the text of their brief, as the lead's row says.

## 3. What a contributor from a fork sees

- **What they read:** `CONTRIBUTING.md` links to the standard by its web address; the pull request template points to it. Both are public on GitHub. They need no bus, no agenttalk installation beyond the development install they already make, no private tool and no extra approval.
- **What they write:** the three-line note in the issue they open for a larger change (or in a draft pull request), and the security lines under "How you checked it". The checks the lines name run with pytest, which the development install already provides.
- **Who checks it:** the maintainers' reader who reads every pull request. If the lines are missing, the reader asks for them, as for any missing "How you checked it"; it is not a new refusal.
- **What does not change for them:** the client-reference check and its fork route. The standard does not depend on the team's private knowledge store.

## 4. Evidence wording, shared with the development flows design

The development flows design (`docs/DESIGN-dev-flows.md` on the branch `docs/dev-flows-design`, not merged) proposes handoff lines of the form `criterion <number>: executed <check> -> pass <details>`, `criterion <number>: executed <check> -> fail <details>` and `criterion <number>: open - <reason>`, and reader lines of the form `criterion <number>: checked <how>`. The standard uses the same grammar with `security P<n>` in place of `criterion <number>`, so one handoff can carry both kinds of line, and a later parser can read both. This does not wait for that design to be built.

Three differences are on purpose:

- **"Does not apply" is the builder's claim here.** The standard has `security P<n>: does not apply - <reason>`, a claim the reader checks. In the development flows design, and in the definition of done, a check is made "not applicable" at dispatch instead. The two do not conflict: a principle that does not apply is the result of the builder's analysis, not a check waived.
- **A failing check is handed over as open.** The standard lists `open` and leaves out `-> fail`; a builder whose protection check fails hands it over as `open`, with the failing output.
- **No refusal in version 1.** A principle is not an acceptance criterion, and version 1 adds no refusal at handoff or at acceptance (the challenge kept enforcement out of the first delivery). If a later version adds one, it refuses only what a handoff itself contradicts, such as an `executed` line that names no command, or a line about a commit other than the one handed over (the team's lesson `design.handoff-refusals-refuse-only-self-contradiction`).

## 5. The trial

**Goal.** Before the standard is wired in, find out three things: whether it changes what is built and checked, what it costs the author and the reader, and whether someone with only public text can follow it. The trial can fail, and a result of "no difference" stops the rollout.

**Observed order, not claimed order.** In every run the note and the code are two separate dispatches. The first task gives the change and asks for the note only, with no code written; the lead records the reply and checks that the author's working copy has no change at that point. Only then does the lead send the second task, to build. The order is then shown by two dispatches the lead made, not by a time the author wrote down. A trial run whose order was not observed this way counts as "order not shown", and does not count towards the bar.

**T1, a real Python change in agenttalk.** The recommended candidate is issue #427: under the test-and-probe store fence, taking a backup without `AGENTTALK_RECOVERY_DIR` writes outside the fence, into the real per-user recovery folder. It has a clear trust boundary (the fence), a plausible misuse (a test leaves files outside its own temporary folder), and a safe behaviour a test can check (refuse plainly, or write only inside the fence). A fallback is issue #571 (`broadcast --resume` accepts an empty `-m` and `--file`), which is a plain input-validation case. Both were open on 2026-10-28; the lead checks again before choosing. A maintainer builds it with the standard, a reader from another vendor reads it in the normal review cycle, and it merges through the normal gate if it passes. T1 shows whether the lines can be checked on a real change and what that costs. With no run without the standard to compare against, it cannot show that the standard made a difference, so it cannot meet the bar on its own.

**T2, a generic Java example, built with and without the standard.** A small stand-alone Java task written for the trial, with nothing behind it: a method that returns a stored report by a name taken from a request, for the signed-in user only, with JUnit tests. It lives only in the trial's scratch folder, never in the repository, and draws on no project of anyone's. The lead names the JDK in the brief. T2 also compiles and tests the Java fragments of the standard's section 6.

- **Two pairs of runs.** Each pair has a run without the standard and a run with it, by two seats that have not seen the task. The run without the standard goes first. Two pairs instead of one make a chance difference less likely; they are still a small sample.
- **Equal briefs.** The two briefs of a pair are the same text, with one difference: the run with the standard gets the public page `docs/SECURE-CODING.md` and a first step asking for its security note; the run without it gets the same first step asking for "a three-line plan of the change". Nothing else differs: no better wording, no extra hints.
- **The outsider's path.** Both authors get only what a fork contributor sees: the public text of `CONTRIBUTING.md` and the pull request template, plus, for the run with the standard, `docs/SECURE-CODING.md`. No skills, no bus commands beyond receiving and answering the two tasks, no knowledge store.
- **A blind comparison.** The reader compares the code and the tests of the two runs of each pair, without the handoff text and without being told which run had the standard. For each run, the reader lists the protections built and the checks that fail without them, then names every protection or check present in one run and missing from the other.

**What is measured, per run.** The team's lesson `process.agent-seat-timing-is-not-human-effort` applies: an agent's seconds are not a person's minutes, so the result reports agent-seat time and counts, and leaves the question of a person's time to the operator.

- **Author:** seconds spent on the note step, and seconds spent on the build step; the number of note lines, handoff lines, tests and commands.
- **Reader:** seconds spent on the blind comparison and on checking the handoff lines; how many lines were checked, how many held, how many failed, and any boundary the note missed.
- **Order:** whether the note step was observed before the build step, as above.
- **Effect:** the differences the blind comparison found, each confirmed by running the check on the run's final code.

**The bar for going ahead.** All of these must hold:

1. In each of the two T2 pairs, the blind comparison finds at least one protection, with a check that fails without it, in the run with the standard and missing from the run without it, and the reader confirms it by running that check.
2. Every run that counts had its order observed (note step first, no code in the working copy at that point).
3. The T2 runs with the standard were finished with public text only.
4. In T1, the reader checked every handoff line on the exact head and reports how many held.
5. No text produced in the trial claims compliance with a framework.
6. No approval was added: the reader was the normal reader.
7. The trial stays within about four hours of seat time in total; the lead stops at that limit and reports what was done. The measured cost goes to the operator, who decides whether it is acceptable.

**When the standard made no difference.** If either T2 pair shows no difference, or only differences the reader could not confirm by running a check, the result says so in plain words: "In this trial, the standard did not change what was built or tested." The rollout stops there: no wiring pull request, and the team takes the smaller alternative in section 6. A difference in only one pair is reported as a weak sign, with the same stop.

**Kill signals** (the challenge's, with how each is detected). If one fires, the wiring pauses, the lead reports it, and the team falls back to the smaller alternative in section 6.

| Signal | How it shows |
|---|---|
| Only after-the-fact attestations | a run whose note step was not observed before its build step, or a handoff line that no executed check backs. A late note counts against the trial even when it says it is late |
| Private tooling needed by outsiders | a T2 run with the standard could not be finished with public text only |
| A claim of whole-framework compliance | any text in the standard, the trial or the wiring that says "compliant" or "certified" |
| Approvals added without settling the rule conflict | any new sign-off, or the wiring proposed before `docs/ASSURANCE.md` section 1 is corrected |

**Output.** A one-page result in the trial's scratch folder that states its uncertainty (two pairs and one real change show an effect in this trial, not a general one), and lessons in the knowledge store for what the trial taught. The T2 Java code is deleted once the lead accepts the result.

## 6. Alternatives considered

- **The smaller path the challenge named:** turn the review skill's security reference into prompts for builders, plus a small framework map, without the three steps. It costs less, but it has no before step, so it cannot tell planned protections from paperwork written afterwards. It is the fallback if the trial shows no difference or a kill signal fires.
- **A security section in every pull request, without a before step:** rejected. It invites exactly the after-the-fact attestation the kill signal names.
- **New scanners or hosted services** (for example a second dependency scanner, or one for the development tools): out of the first delivery, as the challenge required. The existing checks and their gaps are listed in the standard's section 8; a new one comes only for a risk shown to be uncovered.
- **Adopting ASVS in full, or claiming SSDF compliance:** rejected. ASVS is written for web applications; agenttalk is mostly a command-line tool, and the standard selects only the chapters that apply.
- **The whole standard in the skills:** rejected. Part 2 is agenttalk's own, and the playbook keeps shared skills universal (B10). **The standard only in `docs/`:** rejected too, because people who install the skills have no `docs/` folder. Hence part 1 in the skills, checked against the page by a test.

## 7. Open questions

1. **The shipped copy:** keep the page as the source with part 1 copied into the skills and checked by tests (recommended), or make the skill reference the source and have the page include it by a link?
2. **Tests-only changes:** should they need the note? The standard says yes; usually it is the one line "no trust boundary".
3. **The review date:** is 2027-04-28 right, or should the review wait for SSDF 1.2 to be final?
4. **The Cyber Resilience Act:** the team reads it as not applying today, on the facts it knows (see the standard's section 9.7). The operator must confirm those facts (no paid support, no money made from agenttalk through other services, no company supporting it as a steward) and decides.
5. **T1:** issue #427 (recommended) or #571?
6. **T2:** which JDK the trial uses.
7. **Gateway seats:** wait for issue #468, or add part 1 to their brief text meanwhile?

## 8. Technical details

- **Read at master `eebe3460`:** `docs/ASSURANCE.md`, `docs/DESIGN.md` (section 6), `CONTRIBUTING.md`, `SECURITY.md`, `docs/ROLES-SKILLS-PROCEDURES.md` (sections 4.1 to 4.4), `docs/playbook/build-and-test.md` (B10), `dev-gate.json`, `src/agenttalk/dev_gate.py` (`_runtime_dependency_snapshot`, `_pip_audit_check`, `isolated_tool_argv`), `pyproject.toml` (ruff settings, source package list), `.github/workflows/tests.yml` and `security.yml`, `.github/pull_request_template.md`, `.github/dependabot.yml`, `.semgrep/agenttalk.yml`, and the skills `craft-code`, `definition-of-done`, `review-code` (with `references/security.md`), `test-security` and `_shared/references/evidence.md`.
- **The development flows design** was read on the branch `origin/docs/dev-flows-design`, file `docs/DESIGN-dev-flows.md`, sections 6.2 and 6.3.
- **The challenge's verdict** is in the lead's briefs folder: `challenge-secure-coding-standard-verdict.txt`, request ch-651fb888-3d04-48ed-bf23-d6b81a4faff3. **The read** this revision answers is tk-1297b29787e4.
- **Framework pages** were read on 2026-10-28; the standard's section 9 lists each one with its address.
