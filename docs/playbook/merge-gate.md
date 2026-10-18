# Playbook: the merge gate

**In plain words:** the merge gate is the last look before a change joins the main line, and the release ritual is the last look before it ships. A gate only helps if every signal it relies on is read, not just present. This page holds the rules for reading CI honestly, for handling the automated reviewer, for merging several approved changes together, and for releasing. The step lists are in [Roles, skills and procedures, sections 4.3 and 4.4](../ROLES-SKILLS-PROCEDURES.md#43-the-merge-gate) and in [the dev gate](../DEV-GATE.md); the shipped skills [fix-ci](../../src/agenttalk/skills/devkit/fix-ci/SKILL.md) and [review-release-readiness](../../src/agenttalk/skills/devkit/review-release-readiness/SKILL.md) cover the diagnosis and the release check.

### M1. Green CI is necessary, not sufficient
- **The rule.** Before merging, read the automated reviewer's priority comments on the exact head and confirm each is fixed, consciously accepted, or based on a wrong premise.
- **Why.** A pull request was merged on green CI alone while six priority comments sat unread. Luck made that harmless. Later, 18 unresolved comments at a release head were assumed "probably stale"; classified one by one, nine were still open and seven reproduced release-blocking failures.
- **How to apply.** Do not estimate. Hand the full list of unresolved, not-outdated threads to a reviewer and ask for a verdict per item: FIXED (with the evidence), STILL OPEN (reproduce and grade it), or NEVER VALID (the premise is wrong). "Cannot verify" is an acceptable answer.

### M2. An empty summary is not a pass
- **The rule.** Never judge the automated reviewer from its summary text. List the inline threads on the head.
- **Why.** A review whose body was empty boilerplate had attached two new findings to specific lines, and the empty body read as clean.
- **How to apply.** Query the unresolved threads (not outdated, not resolved). A thread being "outdated" proves only that its line moved, not that the defect was fixed. Check new versus carried-forward comments: a comment's commit moves forward with the head, so only comments whose original commit is the head are new.

### M3. Read the reviewer's comments and merge in separate steps
- **The rule.** Never chain "count the comments" and "merge" in one command.
- **Why.** The count printed one more than the round before, and the merge had already run before it could be read; the extra comment was a real regression now in the main line. The same thing happened again later.
- **How to apply.** Count and read every comment on the exact head in one step. Merge in a separate command only after reading. Drain the whole review-comment stream to zero undispositioned items at every gate: fixed, declared, or refuted with evidence; never unread.

### M4. CI must have run against the current target
- **The rule.** A green run against an older main line does not prove the merged result. If the main line moved after the run, run CI again, or merge through an integration branch whose CI ran on the current main line.
- **Why.** CI tests a temporary merge of the head into the target. When the target moves, that result is for an older merge.
- **How to apply.** Check before merging. Read the reviewer on every integration head the first time its summary names that head, and start the fixes then.

### M5. Merge approved changes together
- **The rule.** When two or more approved pull requests wait on CI and edit the same changelog section, merge them together through one integration pull request.
- **Why.** Merging one made all the others conflict, and each fix of a conflict is a new head with another multi-hour run on the slowest platform. Serial merging costs about one extra round per pull request.
- **How to apply.** Verify each branch, build one integration branch with merge commits of the approved heads only, run the combined targeted tests, open one pull request, and comment on each member. Never include an unreviewed head, and never bypass the repository's ruleset.

### M6. Long documentation pull requests converge with one triage round
- **The rule.** The automated reviewer re-reads the whole change at every push, so finding-by-finding fixes do not end. Do one triage round: the author answers every open comment ("fixed in <commit>", "not changed: <reason>", "moved to a follow-up"), true blockers are always fixed, then one final read of that round's changes. Afterwards a new comment on unchanged text goes to a follow-up unless it is a true blocker.
- **Why.** Docs-only pull requests went five to eight rounds.
- **How to apply.** Quality first, but rounds must end. Every blocker and priority comment is triaged, not necessarily fixed.

### M7. Budget the automated reviewer
- **The rule.** Trigger it two or three times per pull request, at the pre-merge gate, on a head that is genuinely ready. Never on a head that is about to move.
- **Why.** It keeps no memory between runs, so each run re-reads the whole diff, and it shares a credit pool with the team's own reviewers. One pull request used 20 triggers and 11 reviews on a 14,000-line diff.
- **How to apply.** The real lever is diff size: one theme per release, split before the change grows. Replace extra triggers with one unbriefed read by your own reviewer, which can also run the code.

### M8. Read CI at the source
- **The rule.** Do not call a red leg a "silent stall" without downloading its per-leg evidence artifact. An "incomplete" flag in a leg's evidence is by design. A failure across a whole operating-system family is more likely a platform-specific test than infrastructure.
- **Why.** Two consecutive "blackouts" were classified as an infrastructure stall by three people. The evidence showed the whole suite had run and a real platform-specific assertion had failed. A healthy two-hour Windows leg was cancelled as hung, costing about an hour and a half.
- **How to apply.** Read each check's status, reason code and duration in the artifact. A real timeout has a duration at the cap. Compare durations with a green baseline of the same leg. A leg is overdue only past its job ceiling, or when its log stopped moving. A single red cell among green ones is usually a flaky test; know the known flaky classes. Verify a "watch" command's exit against the run's real conclusion. If a new commit shows no runs at all, check whether the pull request is in conflict, because then no pull-request CI runs.

### M9. Common causes of "green about the wrong code"
- **The rule.** Gate in an isolated environment, and verify the reader of any result.
- **Why.** A stale global install shadowed the source, so test failures were not real and diagnostics from an older reader printed a confident green for states it did not know. Another time CI turned red because the version bump landed after the gate ran.
- **How to apply.**
  - Use a clean virtual environment per interpreter, with the package installed from the commit under test, and check where the package resolves before trusting a run.
  - Run diagnostics through the installed console script, and print its version next to the result you report.
  - Run the full CI security suite locally, including the secret scan; a lead gate that runs only lint and a scanner misses the rest.
  - List the fast lint check in every build and fix brief before the push, because the lint runs on one CI leg only.
  - On a machine whose runtime is an editable install, installing a release means advancing the checkout, done attended and never while agents are mid-task.

### M10. Tests belong to the agent, the build belongs to CI
- **The rule.** A wrapped agent writes and runs targeted tests for its diff and never runs the full gate, the build, the wheel legs or the security stack in its turn. It pushes, waits for CI, and reads each lane. A blocked or skipped lane is not a passing lane.
- **Why.** The full gate satisfies the per-turn watchdog's kill conditions by construction: one agent froze four times near the 30-minute boundary, always on a gate-running turn. Raising the watchdog's thresholds was rejected as a fix.
- **How to apply.** Say which lanes ran and which did not. If a job would outlive the turn, stop and say so; the answer is CI.

### M11. Changelog entries go in the right place
- **The rule.** Tell seats: "under Unreleased; search the whole Unreleased section for the subsection you need and create it only if it appears nowhere there; never edit a released section."
- **Why.** Entries landed in a released section because the named subsection did not exist yet, and duplicate subsections appeared. A merge that "keeps both sides" also duplicates an entry the branch had reworded, and a release pull request can silently move an entry into a release.
- **How to apply.** Run the released-section guard on every pull-request head at the gate. Check the branch's own changelog diff for removed lines. After a release pull request merges, re-check every open one. Brief sibling pull requests to insert at the start and the end of a list so they do not collide. A reply that cites a guard script gives its full path.

### M12. Re-gate the real release commit
- **The rule.** After a version bump, gate the release commit itself, and change every version-coupled item in the same commit.
- **Why.** A release shipped red because bundled skills carried a stamp from the previous version and a ratchet test read the version. The version also lives in two places, and the gate reads one; an error about a "runner" turned out to be a version mismatch. A release summary overclaimed three guarantees and a new page still pinned the old version.
- **How to apply.** Bump both version sites, the install pins and the docs pins. Read the preflight artifact first: a block that fails every leg at once in seconds is a binding problem, not a flake. Write the summary from each detailed entry's limits, not from memory, and read the automated reviewer on the release head as for any change.

### M13. Handing over an outside team's package
- **The rule.** Apply it on its stated base, check that the tree equals their final head, scan for leaked words, re-author under the repository's identity, run lint and the targeted tests, open the pull request, and have a cold read with the head pinned.
- **Why.** An outside package arrived with a placeholder identity and failed lint.
- **How to apply.** Treat it as an unreviewed head until the cold read says otherwise.

### M14. Git habits that protect the main line
- **The rule.** Stage files explicitly, never "everything". Push by explicit full commit id (`git push origin <sha>:refs/heads/<branch>`), never by `HEAD` from a folder you did not mean. After a push, check the pull request's head and state. Do not rewrite the history of a pushed branch; open a new branch and a new pull request instead.
- **Why.** Stage-all swept an untracked private file into a release commit. A push of `HEAD` from the main checkout overwrote a pull request branch with the main line and the host closed the pull request as already merged; recovery worked only by luck of ancestry.
- **How to apply.** Serve any preview from outside the folder you commit, or its access log gets committed. When a message from a tool says success, verify the state (see the review page, R27).

### M15. Windows gating hygiene
- **The rule.** Use a short temporary base path, run gate legs in the foreground, never run two full suites at once on one repository, and watch CI turn green before tagging a release.
- **Why.** Long paths made worktree creation fail, background legs were killed, and a release was tagged on a local gate and shipped red.
- **How to apply.** The lead's local gate is not the cross-platform check; CI's matrix is.
