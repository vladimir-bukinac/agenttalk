# Contributing to agenttalk

**In plain words:** you are welcome to report problems, suggest changes and send pull requests. Work from your own copy (a fork) of the repository: you do not need write access. For anything bigger than a small fix, open an issue first so we can agree on the idea before you spend time on it. The maintainers' team of AI agents reviews every pull request, automated checks run on it, and only the maintainers merge it. We promise no response time. Never put secrets, credentials, or private or client data into an issue, a pull request or a commit.

## Start here

1. Install a release and try it. The [README](README.md) says what agenttalk is and how to install it. For a first setup, the [lead setup brief](docs/LEAD-SETUP-BRIEF.md) is written to be handed to your AI assistant, and the [new-user manual](docs/AGENTTALK-NEW-USER-MANUAL.md) explains the ideas first. We do not repeat them here.
2. Read what is already known. The README has an "Honest limits" section, and the [issue list](https://github.com/zoolok17/agenttalk/issues) shows what is open. Your problem may already be there.

## Proposing a change

- **A small fix** (a typo, a clear bug with an obvious fix, a wrong sentence in the docs) can go straight to a pull request.
- **Anything larger** (a new command, a changed behaviour, a new document, a rewrite) starts with an issue. Please include:
  - what you were trying to do, and what happened instead (or what is missing);
  - the agenttalk version (`agenttalk --version`), your operating system and Python version;
  - the exact commands you ran and the messages you saw, with any private details removed (see the next section);
  - for a suggestion, the problem you want solved before the solution you have in mind.
- There is no issue or pull request template in the repository today, so those headings are a request, not a form.

## What must never go into an issue, a pull request or a commit

- Passwords, keys, tokens, or any credential, even an expired one. Refer to a secret by where it lives, never by its value.
- Private data, and anything that belongs to a client or an employer: names, records, logs or code that you are not free to publish.
- Internal hostnames, paths, addresses, or account names. Replace them with placeholders such as `<host>` or `<path>`.

Everything you post here is public, and a commit stays in the history even after you delete it. If you posted something by mistake, change it at its source (rotate the credential) first, and tell us.

The repository also runs a check that rejects added text matching a private list of names. We cannot publish that list. If the check blocks your pull request, say so in the pull request and a maintainer will help.

**A security problem is different.** Do not open a public issue with exploit details. Follow [SECURITY.md](SECURITY.md): open a private security advisory on GitHub, or email the maintainer.

## What happens to a pull request

1. **You send it from a fork,** to the `master` branch. You do not need write access to this repository. In the description, say what changed and why in plain words, and how you checked it.
2. **Automated checks run.** On every pull request the `tests` workflow runs the project's development gate (the tests on Linux, macOS and Windows with Python 3.10 to 3.13, packaging checks and security scanners), and the `security` workflow runs CodeQL and the client-reference check. Some documentation-only changes qualify for a lighter set (documentation wording tests, a secret scan, workflow checks, CodeQL and the client-reference check). Not every documentation file does: the exclusions are in the technical details below, and the README and this file run the full matrix. [docs/DEV-GATE.md](docs/DEV-GATE.md) explains both.
3. **The maintainers' agent team reviews it.** A reader who did not write the change reads it, from a different AI vendor than the author when one is available. An automated reviewer on the code host also comments, and the maintainers answer each of its serious comments. [docs/ROLES-SKILLS-PROCEDURES.md](docs/ROLES-SKILLS-PROCEDURES.md) (sections 4.2 and 4.3) describes the cycle.
4. **Expect at least one round of fixes when the review finds something.** The reader lists what it found, the change is fixed, and it is read again. A change is not read once and passed: each fix is read too.
5. **Only the maintainers merge.** A change merges when it has a recorded approval for its exact last commit, the serious automated comments are answered, and the checks are green. If you push another commit after an approval, the approval no longer covers it.

Two things to know about forks. First, GitHub does not give a fork's pull request the repository's secrets, so the client-reference check cannot run on it. It shows as a hold, not a pass, and a maintainer runs it on their side before merging. You do not need to do anything. Second, a first-time contributor's workflows may wait for a maintainer's approval before they start: that is GitHub's own rule for forks, not something this repository adds.

## Before you send a pull request

- Install your copy for development: `python -m pip install -e ".[dev]"` from the top of your clone (this installs pytest and the build tool). agenttalk itself has no other runtime dependency and needs Python 3.10 or newer.
- Run the tests that cover what you changed: `python -m pytest tests/<the file>`. A documentation change should run `tests/test_docs_plain_voice.py`.
- The full gate is `agenttalk dev-gate`. It needs CPython 3.10 and 3.14, `gitleaks` on your PATH and the packages in `dev-gate-requirements.txt`, so most contributors will let CI run it. [docs/DEV-GATE.md](docs/DEV-GATE.md) lists the prerequisites if you want it locally.
- Keep a pull request to one subject. Add a line to the `Unreleased` section of `CHANGELOG.md` for a change that a user will notice, and only add lines: do not edit older entries.
- Write for a reader who does not program. The documents here use plain words first, and the technical detail last.

## The licence

agenttalk is released under the [MIT licence](LICENSE). By sending a contribution you agree that it may be used, copied and distributed under that licence. There is no separate contributor agreement to sign.

## What to expect from us

There is no promised response time. agenttalk is maintained by a small team that works through its agents, and it is young: expect a first answer in days rather than minutes, and sometimes longer. If an issue or a pull request has had no answer for a while, a short, polite reminder on it is fine.

## Technical details

- The `tests` workflow is `.github/workflows/tests.yml` and the `security` workflow is `.github/workflows/security.yml`. Both run on pull requests to `master`, and weekly. The gate's plan is `dev-gate.json`.
- The lighter documentation path covers `README.md`, `CHANGELOG.md`, `SECURITY.md` and Markdown files under `docs/`, except documents that a test names (`scripts/ci_scope.py`). `README.md` and `CHANGELOG.md` are named by tests, so a change to either runs the full matrix, and `CONTRIBUTING.md` is not in that list, so a change to this file does too.
- The client-reference check is `scripts/client_reference_tripwire.py`. A local pre-commit hook for it lives in `scripts/githooks/`; it needs a private salt that contributors do not have, so you can skip it.
- The review cycle in `docs/ROLES-SKILLS-PROCEDURES.md` is written for the maintainers' own team. An outside contributor is not part of it and does not need to follow its commands.
