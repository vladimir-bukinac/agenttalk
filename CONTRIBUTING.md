# Contributing to agenttalk

**In plain words:** you are welcome to report problems, suggest changes and send pull requests. Work from your own copy (a fork) of the repository: you do not need write access. For anything bigger than a small fix, open an issue first so we can agree on the idea before you spend time on it. The maintainers' team of AI agents reviews every pull request, automated checks run on it, and only the maintainers merge it. We promise no response time. Never put secrets, credentials, or private or client data into an issue, a pull request or a commit.

## Start here

1. Install a release and try it. The [README](README.md) says what agenttalk is and how to install it. For a first setup, the [lead setup brief](https://github.com/zoolok17/agenttalk/blob/master/docs/LEAD-SETUP-BRIEF.md) is written to be handed to your AI assistant, and the [new-user manual](https://github.com/zoolok17/agenttalk/blob/master/docs/AGENTTALK-NEW-USER-MANUAL.md) explains the ideas first. We do not repeat them here.
2. Read what is already known. The README has an "Honest limits" section, and the [issue list](https://github.com/zoolok17/agenttalk/issues) shows what is open. Your problem may already be there.

## Proposing a change

- **A small fix** (a typo, a clear bug with an obvious fix, a wrong sentence in the docs) can go straight to a pull request.
- **Anything larger** (a new command, a changed behaviour, a new document, a rewrite) starts with an issue. Please include:
  - what you were trying to do, and what happened instead (or what is missing);
  - the agenttalk version (`agenttalk --version`), your operating system and Python version;
  - the exact commands you ran and the messages you saw, with any private details removed (see the next section);
  - for a suggestion, the problem you want solved before the solution you have in mind.
- A pull request starts with a short template (four prompts, see the checklist below). There is no issue template, so the issue headings above are a request, not a form.

## What must never go into an issue, a pull request or a commit

- Passwords, keys, tokens, or any credential, even an expired one. Refer to a secret by where it lives, never by its value.
- Private data, and anything that belongs to a client or an employer: names, records, logs or code that you are not free to publish.
- Internal hostnames, paths, addresses, or account names. Replace them with placeholders such as `<host>` or `<path>`.

Everything you post here is public, and a commit stays in the history even after you delete it. If you posted something by mistake, change it at its source (rotate the credential) first, and tell us.

The repository also runs a check that rejects added text matching a private list of names. We cannot publish that list. If the check blocks your pull request, say so in the pull request and a maintainer will help.

**A security problem is different.** Do not open a public issue with exploit details. Follow [SECURITY.md](SECURITY.md): open a private security advisory on GitHub, or email the maintainer.

## What happens to a pull request

The list below is the story in plain words. [The pull-request checklist](#the-pull-request-checklist) after it is the same path as a table, step by step, with who acts and what proof each step leaves.

1. **You send it from a fork,** to the `master` branch. You do not need write access to this repository. In the description, say what changed and why in plain words, and how you checked it.
2. **Automated checks run.** On every pull request the `tests` workflow runs the project's development gate (the tests on Linux, macOS and Windows with Python 3.10 to 3.13, packaging checks and security scanners), and the `security` workflow runs CodeQL and the client-reference check. A third workflow, `comprehension-network-deny`, also runs on every pull request, documentation-only ones included: it tests agenttalk's code-analysis worker on Linux and Windows with external networking blocked, and it has nothing to do with your change unless you touch that worker. Some documentation-only changes qualify for a lighter set (documentation wording tests, a secret scan, workflow checks, CodeQL and the client-reference check). Not every documentation file does: the exclusions are in the technical details below, and the README and this file run the full matrix. [docs/DEV-GATE.md](https://github.com/zoolok17/agenttalk/blob/master/docs/DEV-GATE.md) explains both.
3. **The maintainers' agent team reviews it.** A reader who did not write the change reads it, from a different AI vendor than the author when one is available. An automated reviewer on the code host also comments, and the maintainers answer each of its serious comments. [docs/ROLES-SKILLS-PROCEDURES.md](https://github.com/zoolok17/agenttalk/blob/master/docs/ROLES-SKILLS-PROCEDURES.md) (sections 4.2 and 4.3) describes the cycle.
4. **Expect at least one round of fixes when the review finds something.** The reader lists what it found, the change is fixed, and it is read again. A change is not read once and passed: each fix is read too.
5. **Only the maintainers merge.** A change merges when it has a recorded approval for its exact last commit, the serious automated comments are answered, and the checks are green. If you push another commit after an approval, the approval no longer covers it.

Two things to know about forks. First, GitHub does not give a fork's pull request the repository's secrets, so the client-reference check cannot run on it. Its log says HOLD and the job ends with a failure, so GitHub shows it as a red failed check. That red mark means "this check did not run", which is a hold: it is not a finding and it is not a pass. A maintainer runs the check on their side before merging, but that run cannot turn the red mark green. You do not need to do anything. Any other red check on a fork is a real failure to fix. Second, a first-time contributor's workflows may wait for a maintainer's approval before they start: that is GitHub's own rule for forks, not something this repository adds.

## The pull-request checklist

**In plain words:** this is the one list every pull request follows, in the same order, whoever sends it. Each row says who acts, what they leave on the pull request as proof, and what makes that proof out of date. It describes the team's rules. GitHub enforces only some of them, and a list after the table says which. "The lead" is the maintainers' lead agent, who does the merging. Nothing here adds an approval or asks you to use anything private: the maintainer rows are done by the maintainers.

| Step | Who acts | Proof left on the pull request | What makes it stale |
|---|---|---|---|
| 1. Propose | Contributor | For anything bigger than a small fix, an issue with the scope agreed in it. Claim the issue with a comment first, so two people do not do the same work. A small fix (a typo, an obvious bug, a wrong sentence) may go straight to a pull request. | The scope changes. |
| 2. Send | Contributor, from a fork. The maintainers, and the second team when the maintainers agree to it, may use a branch in this repository instead (the second team's branches are named `neuro/<topic>`). | One subject: a side finding becomes a follow-up pull request after the merge. A description in plain words: what changed, why, and how it was checked (the tests actually run, and the commit they ran on). A line in the `Unreleased` section of `CHANGELOG.md` for a change a user will notice, in the style of the entries already there: under `### Added`, `### Changed` or `### Fixed`, a bold plain sentence that ends with the pull request number, then "what you will notice" as before and now (a tooling-only change, such as raising a development tool's minimum version, has none). Nothing private. Before you open it, and before each push, look at the open pull requests for ones that change the same files, above all the `Unreleased` section of `CHANGELOG.md` and tests that read the file you change. | Any new push: the description then names the new commit. Another pull request that lands on the same lines. |
| 3. Checks | The checks run by themselves. A maintainer handles the one that cannot run on a fork. | `dev-gate aggregate` and `codeql (security-extended)` green. `client-reference-tripwire` green on a pull request from this repository; on a fork it is red with HOLD (see below), and the maintainer runs it on the final head and writes the result, and the commit it covered, in a comment. A comment from the maintainers also names which path the change gets: the lighter documentation path, or the full matrix (see the technical details; the full matrix includes Windows and can take several hours). | Any new push. Master moving (see the merge rule below). |
| 4. Review | Our reviewer: a reader who did not write the change, from a different AI vendor than its author when one is available. Findings are tagged P1, P2 or P3. | Before a read starts, the lead posts "hold, review coming" on the pull request, and the author does not push until the verdict is posted. The read gives a recorded GO (the reader's written approval) that names the full commit ID, or the findings. After each fix round the fixes are read again, until GO. The verdict is posted on the pull request, which is the record. | Any push after the GO, including a push that only brings master into the branch. |
| 5. Final read | The lead names it as the final read, in a comment. | After a read is named final, the author pushes only for a P1 or because a maintainer asks. A P1 is a wrong result, lost data, a security problem, or a requirement the change was meant to meet and does not. Every P2 and P3 becomes a follow-up issue, linked from the pull request, unless it shows that such a requirement is not met. | A push that changes more than the fixes the read asked for. |
| 6. Automated reviewer's comments | The maintainers' side answers them (the lead, or the reviewer). The author does not need to chase them. | Before the final read, each comment of P2 or higher gets an answer on the pull request: fixed (with the commit), already closed, or the premise is wrong (with the reason from the code), and a P2 is normally fixed. After the final read, a P2 or P3 from the automated reviewer does not block: it becomes a follow-up issue, and only a P1 stops the merge. A comment is triaged by the commit it was first posted on, because GitHub moves it to the newest commit and the reviewer reads every push again. | A new push brings new comments. |
| 7. Merge | The lead only. Contributors, and the second team, never merge. | A merge commit, never a squash. Just before it: the GO names the current head, the checks are green for that head, and the request is still current. The lead posts the approvals and the merge order on the pull request; nobody else needs to. | Any push. Master moving. |
| 8. After a merge | The lead | One comment on every other open pull request: master moved and what changed on it; which other pull requests touch the same files; and the merge order as one line (for example "#559, then #560, #562, #563"), posted again whenever the order changes. Pull requests that the merge made redundant are closed with a note. The finished checkout is released. | The next merge to master. |
| 9. What each side can expect | The lead | When a pull request waits, a comment names the next owner and the next checkpoint. Reviews and decisions reach the author as the verdict comment on the pull request; the author can read the merge order there. A push after a GO means a new read of that push and a new run of the checks, even for one line, so batch fixes into one push. No response time is promised beyond the one in "What to expect from us". | The checkpoint passes. |

**The merge rule.** If master has moved since the last full run on this head, run the checks again before merging. The one exception: the lead writes on the pull request, before merging, why the change cannot interact with what moved (the files it touches, compared with the files that changed on master). While another open pull request changes the same lines, hold your push; after it merges, bring master in once (a rebase or a merge of master, either) and push once. The lead names the pull request to wait for. GitHub does not enforce the merge rule. The setting that would ("branch must be up to date") is off on purpose, because every merge would then force every other open pull request to run the full gate again.

**What red means on a fork.** The client-reference check needs a secret that a fork's run never receives, so it prints HOLD and ends with a failure. GitHub shows a failure, not "hold", and a maintainer's own run cannot change that mark. So a fork pull request is never green on that line. Pull requests from Dependabot also end red on it, and are handled the same way. The maintainer runs the check on the pull request's added text and writes the result and the commit on the pull request. A repository administrator then merges using the bypass described next, after every other row is done. How a fork pull request merges while that check is red is a maintainers' decision: they may later change the check for forks instead, and this paragraph will then change.

**What GitHub enforces, and what only the team does.**

- GitHub (the ruleset "Merge to master") requires one approval, requires approval of the last push, dismisses an approval when a new commit is pushed, and requires `dev-gate aggregate` and `codeql (security-extended)`.
- Separately, the older branch protection requires `client-reference-tripwire`; administrators are exempt from it.
- Repository administrators can bypass the ruleset. That is how a maintainer's own change merges, because an author cannot approve their own pull request. A bypass is only a way to carry out the merge once the checklist is satisfied: it never replaces a row.
- GitHub allows merge commits, squash merges and rebase merges. The team uses merge commits only: a squash would break the proof that a branch was merged, which the cleanup of a finished checkout needs. If the repository setting is changed to allow merge commits only, this line changes.
- GitHub does not check the rerun after master moved, the reader from another vendor, the answers to the automated comments, or the final-read rule. It does not require review threads to be resolved either: the written answer counts.

**Reviews that come from the second team.** A read supplied by the second team counts as the independent read for a pull request when it names the exact commit, comes from a reader who did not write the change, and is from a different AI vendor than the author when one is available. The lead records on the pull request that it was accepted, and does not add another round of its own automatically. The lead adds a read when the supplied one does not meet that bar, or when a later push changes what it covered.

**Who keeps this list true.** The lead. A pull request that changes a rule this list summarises (sections 4.2 and 4.3 of the [procedures](https://github.com/zoolok17/agenttalk/blob/master/docs/ROLES-SKILLS-PROCEDURES.md), [docs/DEV-GATE.md](https://github.com/zoolok17/agenttalk/blob/master/docs/DEV-GATE.md), or a GitHub setting) changes this section in the same pull request. The commands to check the GitHub settings are in the technical details below.

## Two teams, one repository

**In plain words:** agenttalk is now built by two teams in parallel. The maintainers' team works on this desktop under its lead. A second team of agents on another machine, with its own lead, also changes the repository. This section says how they stay out of each other's way.

- **GitHub is the record** for issues, pull requests and reviews. A finding may reach the second team through its lead first, because that is faster, but the lead posts the written verdict on the pull request, so whatever a reader needs to follow a change is there.
- **The second team works through its lead,** and the maintainers' lead works with that lead. The second team's lead tells the maintainers' lead the number of each pull request it opens. A question or a finding about the second team's pull request goes to the maintainers' lead, who passes it on; reviewers do not contact the second team directly.
- **Both teams change the same files.** When master moves, the maintainers' lead comments on every other open pull request (step 8 above). The later sender rebases and runs the checks again, unless the lead has recorded why the change cannot interact. Never assume an earlier green run still holds.
- **The rules are the same for both teams:** the checklist above, the same review, and merging by the maintainers' lead only.

## Before you send a pull request

- Install your copy for development: `python -m pip install -e ".[dev]"` from the top of your clone (this installs pytest and the build tool). agenttalk itself has no other runtime dependency and needs Python 3.10 or newer. Some tests, and the full gate, need more tools than that: install `dev-gate-requirements.txt` (`python -m pip install -r dev-gate-requirements.txt`; it lists `pytest-xdist`) before you run them, as the gate documentation describes.
- Run the tests that cover what you changed: `python -m pytest tests/<the file>`. `tests/test_docs_plain_voice.py` reads only `README.md` and `docs/AGENTTALK-NEW-USER-MANUAL.md`, so it says nothing about other pages. For a different document, search `tests/` for its file name to find a test that reads it; if there is none, CI's documentation checks are the check.
- The full gate is `agenttalk dev-gate`. It needs CPython 3.10 and 3.14, `gitleaks` on your PATH and the packages in `dev-gate-requirements.txt`, so most contributors will let CI run it. [docs/DEV-GATE.md](https://github.com/zoolok17/agenttalk/blob/master/docs/DEV-GATE.md) lists the prerequisites if you want it locally.
- Keep a pull request to one subject. Add a line to the `Unreleased` section of `CHANGELOG.md` for a change that a user will notice, and only add lines: do not edit older entries.
- Write for a reader who does not program. The documents here use plain words first, and the technical detail last.

## The licence

agenttalk is released under the [MIT licence](LICENSE). By sending a contribution you agree that it may be used, copied and distributed under that licence. There is no separate contributor agreement to sign.

## What to expect from us

There is no promised response time. agenttalk is maintained by a small team that works through its agents, and it is young: expect a first answer in days rather than minutes, and sometimes longer. If an issue or a pull request has had no answer for a while, a short, polite reminder on it is fine.

## Technical details

- The `tests` workflow is `.github/workflows/tests.yml` and the `security` workflow is `.github/workflows/security.yml`. Both run on pull requests to `master`, and weekly. `comprehension-network-deny` is `.github/workflows/comprehension-network-deny.yml`; it runs on pull requests, pushes to `master` and by hand, and covers only the analysis worker and its adapter. The gate's plan is `dev-gate.json`.
- The lighter documentation path covers `README.md`, `CHANGELOG.md`, `SECURITY.md` and Markdown files under `docs/`, except documents that a test names (`scripts/ci_scope.py`). `README.md` and `CHANGELOG.md` are named by tests, so a change to either runs the full matrix, and `CONTRIBUTING.md` is not in that list, so a change to this file does too.
- To check the GitHub settings the checklist describes (read access is enough for the repository and the rulesets; the branch protection needs a maintainer): `gh api repos/zoolok17/agenttalk --jq '{allow_merge_commit,allow_squash_merge,allow_rebase_merge}'`, `gh api repos/zoolok17/agenttalk/rulesets` (then `.../rulesets/<id>` for the rules and the bypass list) and `gh api repos/zoolok17/agenttalk/branches/master/protection`. Last checked on 2026-10-26.
- On a fork the client-reference job exits with code 1 after printing HOLD when the salt secret is missing (`.github/workflows/security.yml`, `scripts/client_reference_tripwire.py`).
- To change the description of a pull request when `gh pr edit` fails for lack of the `read:org` scope, use `gh api -X PATCH repos/zoolok17/agenttalk/pulls/<number> -F body=@<file>`; it works without that scope.
- The client-reference check is `scripts/client_reference_tripwire.py`. A local pre-commit hook for it lives in `scripts/githooks/`; it needs a private salt that contributors do not have, so you can skip it.
- The review cycle in `docs/ROLES-SKILLS-PROCEDURES.md` is written for the maintainers' own team. An outside contributor is not part of it and does not need to follow its commands.
