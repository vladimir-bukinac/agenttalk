# Refactoring review: improve two boundaries, then reassess

Audience: the operator and contributors deciding where maintenance work pays. Status: independent assessment and proposed work; nothing implemented.

**In plain words:** agenttalk would benefit from a little internal reorganisation, but the evidence does not justify a broad rewrite. Some individual routines make readers hold too many unrelated details in mind. Two small changes can give those routines clearer boundaries while preserving everything users and other programs observe. Start with one change, check whether it makes review easier, and proceed only if that benefit survives the extra checking and coordination cost.

## Assessment

The size is real: I counted 125 Python source files containing 151,773 lines and 253 test files containing 245,876 lines. Size alone is not a defect. Much of the code records careful handling of malformed data, Windows processes and interrupted work. Removing that detail because it looks repetitive could remove protection.

There are useful existing boundaries. Saved data, command handling, background supervision and code analysis already have separate homes. The Java analyser receives text without opening files. Supervision separates a decision routine from actions that affect processes. The proposal should strengthen these boundaries, rather than replace them with a new framework.

The clearest maintenance problem is a handful of long routines. One routine constructs all command options in 2,769 lines; another analyses Java source in 1,775 lines. Smaller named stages would help a reviewer follow a change. However, the saved-data module's 9,183 lines are spread across many routines: its longest is 258 lines. Splitting that file merely to reduce its size has a weaker case and greater safety cost.

Change frequency matters too. The last 600 changes in the project's history (10 October to 10 November) touched the command module 129 times. Moving most of that module would make both teams repeatedly reconcile their work. That count measures edits, not defects or actual conflicts; it supports caution, not a claim that the module is broken.

For people using agenttalk, both proposed changes must be invisible. Every command, option, message, help page, exit status, machine-readable result and saved file, and the names other programs import must stay the same. Contributors should gain smaller pieces to inspect. There is no supported claim that these changes would make agenttalk faster or reduce a measured defect rate.

## Ranked proposal

The sizes below count deleted and added lines separately, including moved lines and focused checks. They are estimates, not permission to enlarge the work. Each change is one pull request: a separately reviewed change that can merge alongside other work.

### 1. Give basic Java dependency reading three named stages

**Change:** give three existing stages their own internal functions, meaning small named pieces of code within the same file. These stages read references to other code, relationships between types, and calls to named code. Each receives the facts it needs and returns its ordered findings. Keep their calls where the stages run today.

**Keep:** the way other code calls the analyser, returned data, recognition rules, warning wording, source positions and ordering. Leave web-request interpretation, deployment settings, text cleaning and the final suppression of unsupported results alone. Do not add a parsing library, general extension mechanism or shared object carrying changing state.

**Evidence and benefit:** the three adjacent loops occupy 174 lines inside the 1,775-line source routine. They already represent distinct tasks. Aim to remove at least 125 lines from the enclosing routine and keep each extracted stage below about 100 lines, without shortening explanations or changing logic. The benefit is a named reading boundary, not fewer total lines. This avoids moving the busiest command file.

**Size and risk:** roughly 400–550 changed lines across the analyser and its existing test file, including before/after evidence checks. Risk is moderate: a change could silently lose a dependency or attach it to the wrong declaration. Stop if extraction requires moving web-request logic or introducing a large object merely to carry local values.

**Proof:** before editing, capture complete current results for representative existing sample cases. Compare every named item and list order after editing, not just the number of findings. Retain reference/classification edge cases, several declarations, malformed input and files with no recoverable declarations. Run the analyser tests and affected background-worker, saved-result and end-to-end scanning tests before and after. Demonstrate that deliberately dropping a reference or changing its owner fails the relevant check. The temporary wrong versions must never ship.

**Order:** first trial, after the leads confirm its lines are free of overlapping work. It is separable from command changes. If reviewers cannot explain its benefit from the resulting code, stop here rather than expanding the trial.

### 2. Isolate one command's option setup without moving its public functions

**Change:** put the knowledge command's existing option setup into one internal function within the current command file. Invoke it at exactly the same point in the overall setup. Move its small local option helper with it.

**Keep:** command order, defaults, the routines that execute commands, when components load, accepted abbreviations, which options can be combined, and all text. Keep the option reader and command routines available through the same names other programs use today. Do not extend this trial into moving every command or generating option tables.

**Evidence and benefit:** this block occupies about 190 lines and contains its own small helper and choices list. It can become one named unit without changing saved-data or process logic. Target at least 175 fewer lines in the central builder. Total module size will barely change, and this alone will not eliminate conflicts; it tests whether smaller setup units improve review enough to justify further work.

**Size and risk:** roughly 450–600 changed lines across the command module and an existing test file. Risk is moderate because option order affects help and ambiguous input. Only one such extraction should be in flight. Wait for an overlapping command change to merge; do not ask both teams to reorganise this file concurrently.

**Proof:** compare the complete list of commands and subcommands, option properties and which routine each command runs before and after. Compare help text byte for byte under the same environment, plus representative valid, missing, invalid and abbreviated arguments. Preserve outputs and exit statuses separately. Run the command, knowledge and coordination tests, including exact sets of machine-readable fields: an extra field is a change even when it seems helpful. Preserve tests that temporarily substitute a function to observe which code gets called.

**Order:** second trial, after the first has supplied a useful review pattern and a clear command-file merge slot exists. Postpone it if current feature work makes its coordination cost greater than its modest benefit.

## Conditions for either change

Follow the contribution process: agree the work in an issue before implementation, write the short security note, and keep each change to its one subject. The present review creates neither an issue nor implementation approval. Known bugs or tempting wording improvements belong in separate work.

Use the same behaviour checks on the old and new code. For an internal reorganisation, the old version should already pass; a failing test on the old version would describe a different task. Add only missing boundary checks. Keep comparisons from the old version in review evidence; do not ship a second copy of the old code just so the tests can compare against it.

The existing full development checks, installed-package checks and independent review remain required. Run the relevant tests locally before paying for the full automated run. Keep temporary stores and process resources isolated. Returning the original code in the next change is the recovery route; neither proposal needs a data conversion or new dependency.

Automated checking is already expensive. The committed checking configuration records a historical Windows job lasting 4 hours 18 minutes against a 330-minute ceiling. Reuse existing sample setups and build the option reader once when inspecting its commands. Do not launch a separate process for every help page or duplicate the full test suite. Record added-case duration and the resulting full-job duration against the same kind of baseline; investigate any repeatable increase before proceeding. No specific speed saving has been established by this review.

After both trials, compare actual review size, time spent reconciling changes and whether a reviewer can understand the extracted topic without reading the whole routine. Do not turn a lower line count into a success criterion on its own. Further extraction needs evidence from these trials or repeated costly changes in a particular area.

## What to leave alone

- Do not split the whole command, saved-data or supervisor file, rename packages, or delay loading components to pursue an unmeasured startup gain. Existing callers must keep finding the same functions.
- Preserve the locks and their acquisition order, process ownership checks, restart/termination authority, recovery from repeated requests, paid-call accounting and deletion rules. Similar-looking readers or writers can have different failure obligations; do not unify them just because their text resembles one another.
- Keep the current test organisation, platform coverage, which tests run together, time limits, minimum tool versions and security checks. Test-file moves can change which tests run together or collide over shared resources.
- Keep historical explanations unless a separate review establishes they are obsolete. Do not mix comment cleanup, broad formatting or bug fixes into these changes.

These exclusions include large files that remain difficult to read. In this time box I found no concrete, low-cost justification for restructuring their safety-critical state handling. That is a reason to defer, not proof that they have no maintenance problems.

## Cost of doing nothing

There is no demonstrated urgent failure caused by the current structure. Deferring a broad rewrite avoids immediate conflict and checking costs. Existing feature work should retain priority.

Doing absolutely nothing leaves contributors navigating long routines, and leaves command changes concentrated in one heavily edited file. Review mistakes and slow onboarding are plausible consequences, but this review cannot price them or attribute past bugs to file size. A sensible alternative to either trial is to make the same narrow extraction only when a planned change already needs that code. Do not freeze both teams for an architectural cleanup programme.

**PARTLY: trial two small internal extractions, preserve every external contract, and expand only when their review benefit exceeds their coordination and checking cost.**

## Technical details and evidence

**Scope and provenance.** Reviewed upstream master `6f1a040d53c9264f925b72dd95157b25df62004d` (a second reviewer confirmed that the reviewed source and tests are identical to that commit). No network calls, product edits or full test suite were run. This is an assessment, not a release or correctness approval.

**Executed evidence.** Standard-library Python scripts counted all source/test lines, parsed source syntax, mapped long routines and compared function bodies after removing their leading documentation string. There were no exact repeated function bodies spanning at least 16 lines by that narrow method; renamed variables and near-duplicates were not detected. This does not establish that duplication is absent.

Explicit import statements reference `agenttalk.cli` in 116 test files, `agenttalk.store` in 142 and `agenttalk.supervisor` in 33. These counts exclude dynamic imports and do not count outside users. The console entry is `agenttalk.cli:console_main`; the module entry delegates to it. Existing tests also replace objects through those modules. Moving a function and merely re-exporting its name can change which replaced object it uses.

A read-only exercise constructed the parser's **192 command paths** (the top-level command and its 191 subcommands), including **13 knowledge paths**, rendered their help, and parsed a knowledge-search argument list bound to the existing handler. No handler executed or store opened. A separate copied-adapter exercise used eight synthetic Java inputs, compared complete serialised results across three repetitions and checked positive/negative main-method controls. These are baseline observations, not proof of a future candidate's equivalence or a performance benchmark.

**Exact candidate locations and checks.**

| Proposal | Source evidence | Required checks, not executed here |
| --- | --- | --- |
| 1 | `src/agenttalk/comprehension/adapters/java.py`: `parse_java_source`, lines 3484–5258; proposed import, inheritance/test and qualified-call loops 3687–3860 | `tests/test_comprehension_adapter_java.py`, affected `test_comprehension_worker.py`, `test_comprehension_dependencies_artifact.py`, `test_comprehension_scan_pipeline.py`; full result comparisons including static/wildcard imports, test-source phase and zero-unit suppression; dropped-static-import and wrong-owner fault witnesses |
| 2 | `src/agenttalk/cli.py`: `build_parser`, lines 16951–19719; knowledge registration around 17982–18170 | `tests/test_cli.py`, `tests/test_knowledge.py`, `tests/test_coordination.py`; parser/help/error comparisons, entry-point and replacement-hook checks |

`tests/test_coordination.py::test_backcompat_json_shapes_without_new_features` and `test_additivity_gates_extended_0150`, plus `tests/test_cli.py::test_json_outputs_have_no_new_keys_without_new_features`, explicitly constrain field sets. Do not weaken them to subset checks. New helpers remain private in their current modules; public signatures and result dataclasses stay put. Apply the existing Ruff, security, source/wheel and platform gates to each implementation.

**Costs and limits checked against the tree.** The last 600 non-merge commits touch `CHANGELOG.md` 244 times, command handling 129, the gate experiment 38 and saved data 36. The list of most-touched files ends at five touches: a file missing from it may still have been changed a few times. Commit counts cannot establish how many pull requests conflict. `CONTRIBUTING.md` requires a changelog entry for a user-noticeable change; it does not require inventing one for an invisible reorganisation. If maintainers request an internal note, append it and coordinate that shared file; never rewrite older entries.

`pyproject.toml` declares no runtime dependencies. `dev-gate.json` and `.github/workflows/tests.yml` specify hosted Python 3.10–3.13 on three systems; local gate minors are 3.10 and 3.14. The Windows ceiling and historical duration are recorded there, not freshly observed in hosted runs. `tests/conftest.py` deliberately groups tests sharing process/port resources. `docs/DANGER-AREAS.md` documents why saved records, launches and deletion require broader checks than isolated unit tests.

**Open points.** Current overlapping work and fresh hosted CI timings were not checked; check both before scheduling either change. This reviewer will not implement the resulting plan.
