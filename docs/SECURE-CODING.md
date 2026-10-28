# Writing secure code: the agenttalk standard, version 1

Status: proposed. Version 1, written on 2026-10-28 for work order tk-6f367777d3cc, after the challenge ch-651fb888 returned RESHAPE and the lead accepted it. No skill, template or checklist loads this page yet: that waits for the operator's OK, a read from another AI vendor and a small trial, all described in the [rollout plan](design/secure-coding-rollout.md). Owner: the lead. Next review: by 2027-04-28.

## In plain words

This page says how to keep security in mind while you write code for agenttalk, not only when the code is tested afterwards. Before you write, you note in three lines where something from outside reaches your change, how it could be misused, and what the code must do instead. While you write, you choose protections from a short list of ten principles. When you hand the work over, you point each choice at the code and at a check that ran, and say why the other principles do not apply; the reader who already checks every change checks these claims too. It is for everyone who writes code here, agents and people, maintainers and outside contributors, and it needs no private tools. It adds no approval and no new scanner, and it claims to be in line with the NIST and OWASP guidance it cites, not to comply with it.

## Contents

1. [When it applies](#1-when-it-applies)
2. [The three steps](#2-the-three-steps)
3. [The ten principles](#3-the-ten-principles)
4. [Code written by an AI agent](#4-code-written-by-an-ai-agent)
5. [Examples in Python](#5-examples-in-python)
6. [Examples in Java](#6-examples-in-java)
7. [What already exists and stays](#7-what-already-exists-and-stays)
8. [How this maps to outside frameworks](#8-how-this-maps-to-outside-frameworks)
9. [Owner, versions and review](#9-owner-versions-and-review)

## 1. When it applies

- **Every change to code:** product code (`src/`), scripts (`scripts/`), CI workflows (`.github/`) and tests. A change to documentation only needs nothing from this page.
- **Who does it:** whoever writes the change (the builder). The independent reader that [the review cycle](ROLES-SKILLS-PROCEDURES.md#42-the-review-cycle) already requires checks the builder's claims. No one else is added, and no approval is added.
- **Small changes stay small.** A change that touches no trust boundary needs one line that says so, and why.

A **trust boundary** is a place where something agenttalk does not control reaches code that acts. In agenttalk the things it does not control are:

- message bodies and metadata on the bus, and every file under `.agenttalk/` (anyone who can write to that folder can forge them; see the trust model in [SECURITY.md](../SECURITY.md));
- command-line arguments, environment variables and configuration files;
- requests to the local dashboard and to the paid gateway's front;
- whatever an AI tool or a model returns;
- repository content: branch names, file names, commit messages;
- downloaded files, and anything read over a network.

Code **acts** when it starts a process, reads, writes or deletes a file, opens a network connection, shows a page, merges, releases or deletes work, or spends money.

## 2. The three steps

### Step 1: before you write, the security note

Write three short lines before you write the code:

1. **Boundary:** which outside source reaches which action in your change.
2. **Misuse:** the most plausible way a person, or a confused agent, could misuse it.
3. **Safe behaviour:** what the code must do instead (refuse, escape, limit), said so that a test can check it.

If the change touches no trust boundary, write one line instead: `security-note: no trust boundary - <reason>`.

Put the note somewhere that records when it was written, before the code exists: a comment on the issue, a progress note on your task (`agenttalk progress`), or the description of a draft pull request opened before the first code commit. If you could only write it afterwards, say so in the note. A late note that says it is late is acceptable; a note that pretends to be early is not.

### Step 2: while you write, choose the protections

Go through the ten principles in section 3. For each one your boundary needs, choose a concrete protection, build it, and add a test that would fail without it. Prefer a safe interface that already exists (a list of arguments instead of a shell command, a parameterised query, the standard library's comparison function) to code of your own. If the note turns out to be wrong, correct it and say what changed.

### Step 3: at handoff, point each choice at code and at a check that ran

In the handoff you already write, add one line for each principle you considered:

- `security P<n>: executed <command or run id> -> pass <what it shows>`: the protection is built, and a check that ran on the exact commit you hand over shows it.
- `security P<n>: does not apply - <reason>`: the principle has nothing to protect in this change, and why.
- `security P<n>: open - <reason>, <owner>`: not done yet, and who will do it.

Add the note itself as `security-note: <where it is and when it was written>`.

The maintainers' agents put these lines in the evidence fields that already exist (the done record of the [definition-of-done skill](../src/agenttalk/skills/devkit/definition-of-done/SKILL.md) and the `production-handoff` profile); no new field is needed:

| Field | What goes there |
|---|---|
| `evidence` | the `security-note:` line and every `security P<n>:` line, one entry each |
| `tests_executed` | the commands or run ids that the lines name |
| `residual_risk` | every `open` line, and anything the note could not rule out |
| `required_review_lenses` | `security: <reader's seat>` when the note names a boundary |

An outside contributor, working from a fork without our tools, puts the same lines under "How you checked it" in the pull request description.

**What the reader checks.** The reader who already reads every change (with the security pass of the `review-code` skill) also checks that:

- the note was written before the first code commit, or says that it is late;
- the boundary is right, and the change has no other boundary the note misses;
- each `executed` check exists, ran on the exact commit handed over, and fails without the protection where that can be tried;
- each `does not apply` reason is true for this change;
- the code does what each line says.

The reader records what they checked as `security P<n>: checked <how>` in their own evidence (the `review-result` profile), with `risk_class=security` when the note names a boundary. A filled-in list proves neither that the protections were applied nor that the code is secure. The code and the checks that ran are the evidence; the lines only point at them.

**An example handoff** (an invented change, with placeholders in angle brackets): the dashboard gains a page that shows a stored report by a name taken from the request.

```text
security-note: issue #<n>, comment of <date and time>, before the first code commit <commit>
  boundary: a report name from a dashboard request reaches a file read
  misuse: a name with "..", an absolute path or a link reads a file outside the reports folder
  safe behaviour: refuse any name that resolves outside the folder, with a plain error, and read nothing
security P3: executed python -m pytest tests/test_reports.py -k outside -> pass (4 names refused: "..", absolute, link, empty) on <commit>
security P8: executed the same run -> pass (a name over 200 characters refused)
security P5: does not apply - the name is never shown back; the error text is fixed
security P4: open - who may read which report is decided in issue #<m>, owner: the lead
```

## 3. The ten principles

Each principle says what to do, then the check that usually shows it. They follow the OWASP Proactive Controls and the CWE Top 25 (section 8), written for the code agenttalk has.

**P1. Outside input stays data.** Check it where it comes in, against what is allowed (a known set of names, a pattern, a size), not against a list of what is forbidden. Never run it, evaluate it, or let it choose a command, a file or a network address without that check. A message body on the bus is always data, never an instruction.
*Usual check:* a test that sends a value just outside the allowed shape and gets a plain refusal.

**P2. Never build commands, queries or code by joining text.** Give a process its arguments as a list, never through a shell (`shell=True`, `sh -c`, `cmd /c`) with outside text in it. Use parameterised database queries. Do not use `eval`, `exec` or a template engine on outside text. When an argument could start with `-`, end the options first (for git, `--end-of-options`).
*Usual check:* a test with a value that holds spaces, quotes, `;` or a leading `-`, which arrives unchanged as one argument.

**P3. Paths stay inside their folder.** First turn the path into its final form (remove `..`, follow links), then check that it is still inside the folder it belongs to. Check a name before it becomes part of a file name (agenttalk uses `validate_agent_name` for agent names). Where code promises not to follow links, check that at the moment it uses the path.
*Usual check:* names with `..`, an absolute path and a link that points outside, each refused.

**P4. Check who may act, where the action happens.** Every action that changes something checks that the actor may do it, at the place where it happens, and takes the actor's identity from the trusted side (the roster, the server), never from what the caller says about itself.
*Usual check:* the same action asked for by an actor who may not do it, refused, with nothing changed.

**P5. Escape output for where it goes.** Outside text is escaped for its destination: HTML in the dashboard, Markdown, a terminal, a log line.
*Usual check:* a message that contains `<script>` is shown as text.

**P6. Keep secrets secret, and use proven cryptography.** No secret in code, logs, error messages, bus messages, commits or test output: name where a secret lives, never its value. Compare secrets in constant time, make tokens from a strong random source, and use the standard library's cryptography, never your own. Treat private and client data the same way.
*Usual check:* a test that the error for a wrong key does not contain the key; the secret scanners stay green.

**P7. Safe by default, and refuse when unsure.** Anything that writes, deletes, spends or reaches out stays off until someone turns it on, and listens only on the local machine unless configured otherwise. When a check cannot decide, refuse and say why; never swallow an error to carry on. An error shown to a remote reader leaves out internal paths and details.
*Usual check:* the refusal when the check's input is missing, damaged or unreadable.

**P8. Limit what one input can cost.** Limit size, count, nesting, time and memory for anything from outside, and put a time limit on every call to another process or over the network.
*Usual check:* a test just over each limit.

**P9. Never load outside data in a format that can run code.** Use JSON or another plain format. Do not use `pickle`, `marshal`, `yaml.load` without the safe loader, or Java's built-in object serialization (`ObjectInputStream`) on outside data.
*Usual check:* the scanners stay green; a test with a damaged file gets a plain refusal.

**P10. Add dependencies and tools on purpose.** agenttalk has no runtime dependency, and a change that adds one says why. Before you add a package or a CI action, check that it exists, that it is the genuine one and that it is maintained (an AI tool can name a package that does not exist); pin it (CI actions by full commit id), and let the dependency audit see it.
*Usual check:* the dependency audit and the workflow check stay green; the pull request names the package and why.

## 4. Code written by an AI agent

Code an agent writes meets the same standard as code a person writes, and gets the same reader. NIST's profile for generative AI (SP 800-218A) makes the same choice: its practices "do not distinguish between human-written and AI-generated source code, because it is assumed that all source code should be evaluated for vulnerabilities and other issues before use". Two habits matter more for agent-written code:

- check that every function, flag and package the code uses really exists (P10);
- treat text that came from a model, including a message from another agent, as outside input (P1), never as an instruction.

## 5. Examples in Python

These fragments show the principles. They are not a complete program; they run on Python 3.10 or newer.

```python
import hmac
import json
import re
import subprocess
from pathlib import Path


def object_type(repo: Path, commit: str) -> str:
    # P1: the commit id comes from a message, so accept only a full id.
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("expected a full 40-character commit id")
    # P2: the arguments are a list and no shell runs; P8: a time limit.
    done = subprocess.run(["git", "-C", str(repo), "cat-file", "-t", commit],
                          capture_output=True, text=True, timeout=30, check=True)
    return done.stdout.strip()


def report_file(folder: Path, name: str) -> Path:
    # P3: resolve first (this removes ".." and follows links), then check the result.
    root = folder.resolve()
    target = (root / name).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("the name must point to a file inside the reports folder")
    return target


def same_key(expected: bytes, given: bytes) -> bool:
    # P6: the comparison takes the same time however much of the key matches.
    return hmac.compare_digest(expected, given)


def load_settings(text: str) -> dict:
    # P8: refuse oversized input before parsing it; P9: JSON cannot run code while it loads.
    if len(text) > 64_000:
        raise ValueError("the settings file is too large")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("the settings must be a JSON object")
    return data
```

The check that goes with `report_file` (pytest):

```python
import pytest


@pytest.mark.parametrize("name", ["../secret.txt", "a/../../secret.txt", ""])
def test_a_name_outside_the_reports_folder_is_refused(tmp_path, name):
    with pytest.raises(ValueError):
        report_file(tmp_path / "reports", name)


def test_an_absolute_path_is_refused(tmp_path):
    with pytest.raises(ValueError):
        report_file(tmp_path / "reports", str(tmp_path / "secret.txt"))
```

To make a token, use `secrets.token_hex(32)`; never `random`.

## 6. Examples in Java

A generic example, not taken from any project. These are fragments: they show the calls, not a whole program. Version 1's Java fragments have been checked by reading only; the trial in the rollout plan compiles and tests them.

```java
// P1 + P2: accept only a full commit id, then pass each argument separately; no shell runs.
if (!commitId.matches("[0-9a-f]{40}")) {
    throw new IllegalArgumentException("expected a full 40-character commit id");
}
Process git = new ProcessBuilder("git", "-C", repo.toString(), "cat-file", "-t", commitId).start();
// P8: a time limit.
if (!git.waitFor(30, TimeUnit.SECONDS)) {
    git.destroyForcibly();
    throw new IllegalStateException("git did not answer within 30 seconds");
}

// P2 + P4: a parameterised query; the owner comes from the signed-in session, not from the request.
try (PreparedStatement query = connection.prepareStatement(
        "SELECT title FROM report WHERE id = ? AND owner = ?")) {
    query.setLong(1, reportId);
    query.setString(2, session.userName());
    try (ResultSet rows = query.executeQuery()) {
        // read the rows
    }
}

// P3: resolve against the real folder, normalise, then check that the result is still inside it.
Path root = reportsFolder.toRealPath();
Path target = root.resolve(name).normalize();
if (target.equals(root) || !target.startsWith(root)) {
    throw new IllegalArgumentException("the name must point to a file inside the reports folder");
}
// If the folder can hold links, check target.toRealPath() the same way before opening the file.

// P6: a comparison that takes the same time however much matches, and a strong random source.
boolean same = MessageDigest.isEqual(expectedKey, givenKey);
byte[] token = new byte[32];
new SecureRandom().nextBytes(token);

// P9: never ObjectInputStream on outside data: read a plain format such as JSON and check its shape.
```

## 7. What already exists and stays

Version 1 adds no scanner, no hosted service and no check that runs while agenttalk runs. A new check comes only for a risk that the trial or a review finding shows is not yet covered. These stay as they are; the last column names the practice of the NIST Secure Software Development Framework (SSDF, section 8.1) that each one serves.

| What | Where it runs | What it finds or does | SSDF practice |
|---|---|---|---|
| ruff's `S` rules | the development gate, on the CI leg that runs the static checks (Linux, Python 3.12), on every pull request that takes the full path, and weekly | Python patterns known to be unsafe (the rules come from bandit), in `src/` and `tests/` | PW.5, PW.7 |
| bandit | the same | Python security patterns in `src/` (the shipped skills are left out) | PW.7 |
| semgrep | the same, with the `p/python` and `p/security-audit` rule sets and three project rules in `.semgrep/agenttalk.yml` | unsafe patterns, and three agenttalk rules: agent names are validated before they become file names, messages are written only through the store, and a message body never reaches code execution | PW.5, PW.7 |
| gitleaks | the development gate, over the full history, and on the documentation-only path | credentials committed by mistake | PW.7, PS.1 |
| pip-audit (strict) | the development gate | published vulnerabilities in the installed packages; agenttalk itself has none at runtime, so this covers the development tools | PW.4, RV.1 |
| zizmor | the development gate, and on the documentation-only path | unsafe GitHub Actions workflows | PO.3, PO.5 |
| CodeQL (`security-extended`) | the `security` workflow, on every pull request and weekly | data flows from outside input to dangerous calls | PW.7, RV.1 |
| The client-reference check | the `security` workflow; for a fork, the lead runs it | private client names in added text and in the whole tree | none: it protects other people's private data, which the SSDF does not cover |
| The security pass of `review-code` (`references/security.md`) | the independent reader, on every change that touches a sensitive area | an OWASP-based checklist: access control, input, output, secrets, errors, dependencies, paths, resources | PW.7 |
| [SECURITY.md](../SECURITY.md) | public | how to report a vulnerability privately; the trust model; four threat scenarios | RV.1, PW.1 |
| The review cycle and the merge rules ([CONTRIBUTING.md](../CONTRIBUTING.md#the-pull-request-checklist)) | every pull request | an independent reader from another AI vendor when one is available, fix rounds, required checks, merges by the lead only | PW.2, PW.7, PS.1 |

## 8. How this maps to outside frameworks

**Alignment, not compliance.** This standard was written with the frameworks below open, and the tables show where it meets them and where it does not. It adopts none of them in full, nobody outside the team has assessed it, and nothing here may be described as compliant with or certified against any of them. Every page was read on 2026-10-28.

### 8.1 NIST Secure Software Development Framework (SSDF) 1.1

- **Version:** SSDF version 1.1, NIST SP 800-218, final, February 2022. NIST still lists it as final. Version 1.2 (NIST SP 800-218 Rev. 1) is an initial public draft of 17 December 2025; its comment period closed on 30 January 2026. The draft adds two practices: PO.6 (a plan for continuous improvement) and PS.4 (robust and reliable updates). We map to 1.1 and will map again when 1.2 is final.
- **Sources:** <https://csrc.nist.gov/Projects/ssdf/publications>, <https://csrc.nist.gov/pubs/sp/800/218/r1/ipd>, and the text of both documents.

| Practice | What agenttalk has | Gap |
|---|---|---|
| PO.1 Define security requirements | this standard; the trust model in SECURITY.md | the standard is new and untried |
| PO.2 Roles and responsibilities | owner (the lead), builder, reader (ROLES-SKILLS-PROCEDURES.md) | no training beyond the skills and lessons |
| PO.3 Supporting toolchains | the development gate and CI; actions pinned by commit | none known |
| PO.4 Criteria for security checks | required checks green; each handoff line names a check that ran | criteria are per change, not one written list |
| PO.5 Secure development environments | zizmor; fork runs get no secrets; scratch stores and the store fence keep tests off the live store | none known |
| PS.1 Protect code from tampering | the master ruleset (approval of the last push, required checks), merges by the lead only, gitleaks | none known |
| PS.2 Verify release integrity | releases are git tags installed from GitHub | **gap:** no signed release, published hash or build provenance |
| PS.3 Archive each release | git tags and GitHub releases | partial: no separate archive |
| PW.1 Design to meet security requirements | step 1, the challenge, design reads | none known |
| PW.2 Review the design | a design read by another seat | none known |
| PW.4 Reuse well-secured software | no runtime dependencies; P10; pip-audit; Dependabot | none known |
| PW.5 Secure coding practices | step 2 and the ten principles; ruff `S`; semgrep project rules | the principles are untried |
| PW.6 Harden the build | not applicable to pure Python | **gap** for Java code: compiler and build settings are not covered |
| PW.7 Review and analyse code | the independent reader and the security pass; ruff, bandit, semgrep, CodeQL, gitleaks | none known |
| PW.8 Test executable code | the development gate's tests; the `test-security` skill; step 3's executed checks | none known |
| PW.9 Secure default settings | P7 (the dashboard binds the local machine; actions are off unless turned on) | none known |
| RV.1 Identify vulnerabilities | the private reporting route in SECURITY.md; weekly CodeQL and gate runs; Dependabot | none known |
| RV.2 Assess and fix vulnerabilities | issues and fix rounds | **gap:** no stated response time |
| RV.3 Find root causes | reviewers record each recurring class of mistake as a lesson in the team's knowledge store | the store is private to the team; outside readers see only the issues |

### 8.2 NIST SP 800-218A: secure development for generative AI

- **Version:** SP 800-218A, final, 26 July 2024. Source: <https://csrc.nist.gov/pubs/sp/800/218/a/final>.
- **Does it apply?** In part. Its scope is AI model development, "as well as incorporating and integrating AI models into other software". agenttalk trains no model, so the tasks about training data and model weights do not apply. It does run AI agents and a gateway to a paid model, which makes it software that uses generative AI models, one of the profile's audiences.
- **What we map:** section 4 follows its rule that human-written and AI-written code are treated alike; P1 treats model output as outside input.
- **Gaps:** the defence against instructions hidden in messages (prompt injection) lives in SECURITY.md (scenario S-2), not in this standard; the profile's tasks for systems that use models have not been mapped one by one.

### 8.3 OWASP Top 10 Proactive Controls, 2024 edition

- **Version:** the 2024 edition. On 2026-10-28 the project site shows it under "Top 10 2024" in its archive, and shows a next edition as "Future Top 10 (WIP)" with the same ten control names. Source: <https://top10proactive.owasp.org/>. The page says the document "is primarily written for developers": it is guidance, not a standard to comply with.

| Control | Principle | Gap |
|---|---|---|
| C1 Implement Access Control | P4 | none known |
| C2 Use Cryptography to Protect Data | P6 | none known |
| C3 Validate all Input & Handle Exceptions | P1, P7 | none known |
| C4 Address Security from the Start | step 1 | none known |
| C5 Secure By Default Configurations | P7 | none known |
| C6 Keep your Components Secure | P10 | none known |
| C7 Secure Digital Identities | P4, P6 in part | **gap:** agenttalk has no sign-in for people; its trust model is the local machine |
| C8 Leverage Browser Security Features | P5 in part | **gap:** browser security headers for the dashboard are not covered |
| C9 Implement Security Logging and Monitoring | P7 in part (a refusal says why) | **gap:** no principle for security logging |
| C10 Stop Server Side Request Forgery | P1 (outside input never chooses a network address unchecked) | none known |

### 8.4 OWASP Application Security Verification Standard (ASVS) 5.0.0

- **Version:** 5.0.0, released 30 May 2025. Sources: <https://asvs.owasp.org/> and the chapter files at <https://github.com/OWASP/ASVS/tree/master/5.0/en>.
- **How it is used:** ASVS sets requirements for web applications and web services, and invites each organisation to make its own tailored version, "omitting irrelevant sections". agenttalk is mostly a command-line tool, so only its two local web services are in scope: the dashboard and the paid gateway's front. We select chapters, claim no ASVS level (it has three), and have not yet selected requirements one by one.

| Chapter | Selected? | Where in agenttalk |
|---|---|---|
| V1 Encoding and Sanitization | yes | dashboard pages that show message text (P5) |
| V2 Validation and Business Logic | yes | every request (P1) |
| V3 Web Frontend Security | yes | dashboard pages |
| V4 API and Web Service | yes | the dashboard's data and action requests; the gateway front |
| V5 File Handling | yes | paths built from requests (P3) |
| V6 Authentication | no | no sign-in for people; the gateway front checks a shared token, which P4 and P6 cover; both services listen on the local machine only (gap, see C7) |
| V7 Session Management | no | no sessions |
| V8 Authorization | yes | dashboard actions; the gateway front's token check (P4) |
| V9 Self-contained Tokens | no | no self-contained tokens |
| V10 OAuth and OIDC | no | not used |
| V11 Cryptography | yes | message signing, key comparison (P6) |
| V12 Secure Communication | no | the services listen locally; **gap:** agenttalk's own outgoing network calls are not covered |
| V13 Configuration | yes | defaults and stored secrets (P6, P7) |
| V14 Data Protection | yes | private and client data (P6) |
| V15 Secure Coding and Architecture | yes | P2, P9, P10 |
| V16 Security Logging and Error Handling | yes, in part | P7 (see C9) |
| V17 WebRTC | no | not used |

### 8.5 CWE Top 25 Most Dangerous Software Weaknesses, 2025

- **Version:** the 2025 list. Source: <https://cwe.mitre.org/top25/> (page last updated 29 January 2026) and the list itself, <https://cwe.mitre.org/top25/archive/2025/2025_cwe_top25.html>.

| Principle | Weaknesses it addresses |
|---|---|
| P1 | CWE-20 improper input validation, CWE-918 server-side request forgery, CWE-434 unrestricted upload |
| P2 | CWE-78 OS command injection, CWE-77 command injection, CWE-89 SQL injection, CWE-94 code injection |
| P3 | CWE-22 path traversal |
| P4 | CWE-862 missing authorization, CWE-863 incorrect authorization, CWE-284 improper access control, CWE-639 authorization bypass through a user-controlled key, CWE-306 missing authentication for a critical function, CWE-352 cross-site request forgery (for the dashboard's actions) |
| P5 | CWE-79 cross-site scripting |
| P6 | CWE-200 exposure of sensitive information |
| P8 | CWE-770 allocation of resources without limits |
| P9 | CWE-502 deserialization of untrusted data |

**Gap:** seven entries are memory-safety errors (CWE-787, 416, 125, 120, 121, 122 and 476). Python and Java code cannot make the first six without native code, which agenttalk does not have; CWE-476 (a null dereference) in Java ends in an exception, which P7 says to handle. CWE-352 is named only through P4; no principle spells out request forgery for the dashboard.

### 8.6 SLSA (Supply-chain Levels for Software Artifacts) 1.2

- **Version:** 1.2, status "Approved". Source: <https://slsa.dev/spec/>.
- **Does it add an obligation?** No. SLSA is voluntary. agenttalk is installed from git tags on GitHub, and it publishes no built packages and no build provenance, so it meets no SLSA build level today. That is the same gap as SSDF PS.2. Version 1 adds nothing here; a signed or attested release is a separate decision.

### 8.7 EU Cyber Resilience Act (CRA)

- **Version:** Regulation (EU) 2024/2847. It entered into force on 10 December 2024; reporting obligations apply from 11 September 2026 and the main obligations from 11 December 2027. Sources: <https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act>, <https://digital-strategy.ec.europa.eu/en/policies/cra-summary> and <https://digital-strategy.ec.europa.eu/en/policies/cra-open-source>.
- **Does it add an obligation?** Not today, on the team's reading; this is not legal advice, and the operator decides. The CRA covers products "made available on the market" in the course of a commercial activity. agenttalk is free under the MIT licence, is not sold, and is installed from its public repository, so it is published but not made available on the market in that sense. The Commission's page also says the Act does not apply to developers who contribute code to projects that are not under their responsibility.
- **What would change it:** selling agenttalk, charging for support beyond its cost, using it to sell other services, or a company supporting it for commercial use as an "open-source software steward" (a steward has lighter duties: a cybersecurity policy, cooperation with the authorities, and reporting of actively exploited vulnerabilities). The [proposal to make the console sellable to clients](PROPOSAL-console-client-sellability.md) is such a case and would need this question answered first.

## 9. Owner, versions and review

- **Owner:** the lead. A change to the steps or the principles needs the same review as any other change, and makes a new version.
- **Versions:** version 1, 2026-10-28. A task names the version it works under (for example `secure-coding@1`), and work already started keeps that version when a new one appears.
- **Review:** by 2027-04-28, or earlier when NIST publishes SSDF 1.2 as final, OWASP publishes the next Proactive Controls, MITRE publishes a new CWE Top 25, a review finds a class of mistake the principles miss, or agenttalk starts to be supplied commercially (section 8.7).
