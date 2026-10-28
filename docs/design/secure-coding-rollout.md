# Design: rolling out the secure-coding standard

Status: proposed. Written on 2026-10-28 for work order tk-6f367777d3cc, after the challenge ch-651fb888 returned RESHAPE and the lead accepted it. Nothing here is built: no skill, template or workflow changes until the operator says OK and a reader from another AI vendor has read this branch. Where this page describes agenttalk today, it matches master `eebe3460`. Owner: the lead.

## In plain words

[The secure-coding standard](../SECURE-CODING.md) asks a builder to write a short security note before coding, choose protections while coding, and show at handoff which code and which executed checks carry each choice. This page plans how the standard would reach everyone who writes or reads code: which skills, briefs and contributor pages would point to it, and how someone working from a fork, without our tools, sees it. It also plans a small trial, one real Python change and one generic Java example, that measures what the standard costs the author and the reader and whether it changes what gets built. It decides the order of the work and the bar the trial must pass; it leaves open the questions in section 7.

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
4. **One pull request that wires the standard in** (section 2), only if the trial meets its bar and no kill signal fired. It goes through the normal review cycle.
5. **Review** of the standard by 2027-04-28, or earlier on the triggers in its section 9.

The standard adds no approval at any step. The rule conflict that the challenge named is settled first, on this branch: `docs/ASSURANCE.md` section 1 now follows the definition of done and `CONTRIBUTING.md`.

## 2. Where the standard would be loaded

**One source, short pointers.** The rules live in `docs/SECURE-CODING.md`. Each entry point gets a pointer and, at most, one line saying when to use it, never a copy of the rules. The one exception is a shipped copy for people who install the skills (the first row), kept identical by a test.

**A pinned version.** A task names the version it works under (`secure-coding@1`), the way it already names its definition-of-done profile. A later version then never changes what work already started owes. This follows the team's lesson that obligations belong on the work's own dispatch record (`design.pin-obligations-on-the-immutable-work-record`).

| Entry point | File | Who uses it | Proposed change |
|---|---|---|---|
| A shipped copy of the rules | new: `src/agenttalk/skills/devkit/_shared/references/secure-coding.md` | anyone who installs the skills with `agenttalk install-skills`, who has the package but no `docs/` folder | sections 1 to 4 of the standard, with its version line, as an exact copy. A repository test fails when the copy and the page differ. |
| craft-code | `src/agenttalk/skills/devkit/craft-code/SKILL.md` | every builder, Claude and Codex | three one-line items: BEFORE, write the security note (step 1); WHILE, choose protections from P1 to P10 (step 2); AFTER, add the security lines to the handoff (step 3). Each points at the shipped copy. |
| refactor-code | `src/agenttalk/skills/devkit/refactor-code/SKILL.md` | builders of refactors | one line: a refactor that moves a trust boundary writes the note; otherwise one line, `security-note: no trust boundary - behaviour unchanged`. |
| fix-ci | `src/agenttalk/skills/devkit/fix-ci/SKILL.md` | builders of CI fixes | one line: a fix that changes a workflow, a scanner setting or a dependency writes the note (P7, P10). |
| test-security | `src/agenttalk/skills/devkit/test-security/SKILL.md` | testers | name the principle (`P<n>`) in its abuse-case evidence, so that the builder's handoff lines can cite those checks. |
| definition-of-done | `src/agenttalk/skills/devkit/definition-of-done/SKILL.md` | everyone at handoff | one sentence under "Where the record goes": the security lines go in `evidence`, the commands in `tests_executed`, the open lines in `residual_risk`. No new field and no new profile row. |
| review-code | `src/agenttalk/skills/devkit/review-code/SKILL.md` and `references/security.md` | every reader | the security pass also checks the builder's lines (the list "What the reader checks" in step 3), and findings name the principle they break. The existing OWASP-based checklist stays as it is. |
| The lead's skill | `src/agenttalk/skills/claude/agenttalk.lead.md` and `src/agenttalk/skills/codex/agenttalk-lead/` | the lead | a build or fix brief names `secure-coding@1` next to the done profile; a read brief asks the reader to check the security lines. |
| The procedures | `docs/ROLES-SKILLS-PROCEDURES.md`, sections 4.1 and 4.2 | the team | one sentence each: the brief pins the version; the reader checks the lines. |
| The contributor guide | `CONTRIBUTING.md`, "Before you send a pull request" and "Proposing a change" | outside contributors | one bullet each: for a code change, read the standard (linked by its web address) and put the three-line note in the issue; add the security lines under "How you checked it". |
| The pull request template | `.github/pull_request_template.md` | everyone who opens a pull request | widen the existing prompt "How you checked it" with "(for code: the security lines, see SECURE-CODING.md)". It stays four prompts. |

**Left out on purpose:** `review-failure-injection` (it already covers what P7 and P8 ask), `write-docs` and the other documentation skills (documentation needs no note), and the README.

**A known gap:** seats on the paid gateway do not see the shipped skills (issue #468). Until that is fixed they get the standard only through the text of their brief.

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

**Goal.** Before the standard is wired in, show three things: that it changes what is built and checked; what it costs the author and the reader; and that someone with only public text can follow it.

**T1, a real Python change in agenttalk.** The recommended candidate is issue #427: under the test-and-probe store fence, taking a backup without `AGENTTALK_RECOVERY_DIR` writes outside the fence, into the real per-user recovery folder. It has a clear trust boundary (the fence), a plausible misuse (a test leaves files outside its own temporary folder), and a safe behaviour a test can check (refuse plainly, or write only inside the fence). A fallback is issue #571 (`broadcast --resume` accepts an empty `-m` and `--file`), which is a plain input-validation case. The lead picks. A maintainer builds it with the standard, a reader from another vendor reads it in the normal review cycle, and it merges through the normal gate if it passes: the trial is real work.

**T2, a generic Java example, by the outsider's path.** A small stand-alone Java class written for the trial, with nothing behind it: a method that returns a stored report by a name taken from a request, and a JUnit test. It lives only in the trial's scratch folder, never in the repository, and draws on no project of anyone's. The author gets only what a fork contributor sees: the public text of `docs/SECURE-CODING.md`, `CONTRIBUTING.md` and the pull request template; no skills, no bus commands, no knowledge store. T2 also compiles and tests the Java fragments of the standard's section 6. The lead names the JDK in the brief.

**A baseline for T2.** Run T2 twice, each time by a seat that has not seen the task: first without the standard, then with it. Compare what each built and tested. The second run may benefit from a better brief, and the result says so. T1 has no baseline: it is a real change, and the reader judges which protections the standard caused.

**What is measured, per example.** The team's lesson `process.agent-seat-timing-is-not-human-effort` applies: an agent's seconds are not a person's minutes, so the result reports agent-seat time and counts, and leaves the question of a person's time to the operator.

- **Author:** seconds spent on the security work only (the note, the choice of protections beyond the plain implementation, the handoff lines), timed apart from the implementation; the number of note lines, handoff lines, extra tests and extra commands.
- **Reader:** seconds spent checking the security lines; how many lines were checked, how many held, how many failed, and any boundary the note missed.
- **Timing of the note:** whether its recorded time comes before the first code commit.
- **Effect:** the implementation choice and the check that the standard caused, or "none". A null result is reported as a result, never dressed up.

**The bar for going ahead.** All of these must hold:

1. In each example, at least one implementation choice and at least one executed check name a principle, and the reader confirms them on the exact head.
2. Each note was recorded before the first code commit.
3. T2 was finished with public text only.
4. No text produced in the trial claims compliance with a framework.
5. No approval was added: the reader was the normal reader.
6. The trial stays within about three hours of seat time in total; the measured cost goes to the operator, who decides whether it is acceptable.

**Kill signals** (the challenge's, with how each is detected). If one fires, the wiring pauses, the lead reports it, and the team falls back to the cheaper alternative in section 6.

| Signal | How it shows |
|---|---|
| Only after-the-fact attestations | a note recorded after the first code commit that does not say it is late, or a handoff line that no executed check backs |
| Private tooling needed by outsiders | T2 could not be finished with public text only |
| A claim of whole-framework compliance | any text in the standard, the trial or the wiring that says "compliant" or "certified" |
| Approvals added without settling the rule conflict | any new sign-off, or the wiring proposed before `docs/ASSURANCE.md` section 1 is corrected |

**Output.** A one-page result in the trial's scratch folder, and lessons in the knowledge store for what the trial taught. The T2 Java code is deleted once the lead accepts the result.

## 6. Alternatives considered

- **The cheaper path the challenge named:** turn the review skill's security reference into prompts for builders, plus a small framework map, without the three steps. It costs less, but it has no before step, so it cannot tell planned protections from paperwork written afterwards. It is the fallback if a kill signal fires.
- **A security section in every pull request, without a before step:** rejected. It invites exactly the after-the-fact attestation the kill signal names.
- **New scanners or hosted services** (for example a second dependency scanner): out of the first delivery, as the challenge required. The existing checks are listed in the standard's section 7; a new one comes only for a risk shown to be uncovered.
- **Adopting ASVS in full, or claiming SSDF compliance:** rejected. ASVS is written for web applications; agenttalk is mostly a command-line tool, and the standard selects only the chapters that apply.
- **The standard only in the skills, or only in `docs/`:** rejected. Outside contributors read GitHub, and people who install the skills have no `docs/` folder; hence one page plus one shipped copy kept identical by a test.

## 7. Open questions

1. **The shipped copy:** keep the page as the source with a copy in the skills, checked by a test (recommended), or make the skill reference the source and have the page link to it?
2. **Tests-only changes:** should they need the note? The standard says yes; usually it is the one line "no trust boundary".
3. **The review date:** is 2027-04-28 right, or should the review wait for SSDF 1.2 to be final?
4. **The Cyber Resilience Act:** the team reads it as not applying today, because agenttalk is not supplied commercially. The operator decides, and knows whether any commercial plan exists, such as the proposal to sell the console to clients.
5. **T1:** issue #427 (recommended) or #571?
6. **T2:** which JDK the trial uses.
7. **Gateway seats:** wait for issue #468, or add the standard to their brief text meanwhile?

## 8. Technical details

- **Read at master `eebe3460`:** `docs/ASSURANCE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/ROLES-SKILLS-PROCEDURES.md` (sections 4.1 to 4.4), `dev-gate.json`, `pyproject.toml` (ruff settings, source package list), `.github/workflows/tests.yml` and `security.yml`, `.github/pull_request_template.md`, `.semgrep/agenttalk.yml`, and the skills `craft-code`, `definition-of-done`, `review-code` (with `references/security.md`), `test-security` and `_shared/references/evidence.md`.
- **The development flows design** was read on the branch `origin/docs/dev-flows-design`, file `docs/DESIGN-dev-flows.md`, sections 6.2 and 6.3.
- **The challenge's verdict** is in the lead's briefs folder: `challenge-secure-coding-standard-verdict.txt`, request ch-651fb888-3d04-48ed-bf23-d6b81a4faff3.
- **Framework pages** were read on 2026-10-28; the standard's section 8 lists each one with its address.
