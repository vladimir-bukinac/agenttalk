# Playbook: build and test

**In plain words:** a green test run only means something if the tests could have been red. This page holds the rules for writing tests and code so that a green result tells the truth: tests that check the real thing, limits that are tested where they bite, output that does not break its readers, and a clear idea of when a task is done. The shipped skills [craft-code](../../src/agenttalk/skills/devkit/craft-code/SKILL.md), [test-coverage](../../src/agenttalk/skills/devkit/test-coverage/SKILL.md) and [tester-qa](../../src/agenttalk/skills/devkit/tester-qa/SKILL.md) carry the detailed practice. This page adds the rules the team learned the hard way.

### B1. Every task has a written definition of done
- **The rule.** Every task, greenfield work included, has a written definition of done. A migration has an official checklist that is versioned and updated whenever a review or lesson shows a gap.
- **Why.** "Done" meant different things to different agents, and reviewers found the gaps late: one programme's reads found a dozen blocking and dozens of lesser problems that a shared checklist would have caught earlier.
- **How to apply.** Keep a general definition with profiles (any task, bug fix, greenfield feature, greenfield project or release, migration slice, whole migration). A shipped checklist skill stays project-agnostic and gets its challenge first (see [challenges](challenges.md)).

### B2. A test's stated mechanism must be the one that fires
- **The rule.** For every test case that names a mechanism, apply one change that disables only that mechanism and require that case to fail for the intended reason. Other cases that exercise the same mechanism may fail too; that is overlapping coverage, not a defect.
- **Why.** Three cases in one night were green for the wrong reason: the input was rejected by an earlier check before the named one ran, so removing the named check left every case green.
- **How to apply.** The discriminating input is one that every other clause accepts. Write the explanation from the mutation's result, not from intent. Apply mutations by searching for text, never by line number.

### B3. Pin the whole surface, not some points
- **The rule.** When the input space can be listed (media types, methods, status codes, matcher kinds), write one table of input and expected result, asserted in a loop, and derive it from the original version's behaviour.
- **Why.** A few point tests passed an expert review while another value diverged from the baseline.
- **How to apply.** In a review, if you write "only k of n pins are load-bearing", the next sentence must list the values not pinned.

### B4. Test the limit where it bites
- **The rule.** A test for a timeout or bound must force the bound to trigger, and check that what hung was killed or released and that the caller ended in the intended state.
- **Why.** A test that only shows normal operation finishing inside the bound shows that the bound is not in the way, not that it works. A hard timeout on a probe was tested with a fake that sleeps far longer than a short bound.
- **How to apply.** Make the underlying operation exceed the bound (a sleep, a blocking read, a process that never exits). Assert both that the time was bounded and that no child, thread, handle or lock was left behind.

### B5. Test against the real record shape
- **The rule.** When a fix reads a field, check the test's fixture against a real artifact: load an actual stored record and see where the field lives.
- **Why.** Unit tests used a record with the field at the top level, while real messages carried it inside the metadata. The tests were green and the feature rendered an unfillable placeholder in production.
- **How to apply.** Do not type a fixture from memory, and render the exact artifact a paid agent would consume before you spend on it.

### B6. Check the proxy is not the property
- **The rule.** Ask what the cheapest way to make an assertion true without doing the work is, and close it. Prefer a witness the mechanism itself writes (a file the child produced, a counter it incremented) over an outcome you infer.
- **Why.** A guard test matched text in a comment; a test could name the fixture it was supposed to hide; a dual-shell test checked the outcome, not that the interpreter ran, and passed when a branch returned early.
- **How to apply.** Use fixtures the code under test cannot predict. Enumerate the branches: "it passes" is not "the class passes". Run the mutation yourself before you say a guard has teeth.

### B7. A watcher waits for the good state
- **The rule.** Every monitor or waiter asserts that the good state is present, never that a bad signal is absent.
- **Why.** "Nothing is failing" is true of a system that never started, has died or was deleted. Three different watchers produced false greens: one deduplicated on a key that silenced it after the first success, one read "no pending checks" as complete when only one of many checks had registered, and one read "none of the old processes exist" as "all restarted".
- **How to apply.** Count the thing you want ("at least N up, none stale"). Pair every negative clause with a positive one. Name the good state in the success message. When two waiters report one event, reconcile their timings before believing either.

### B8. A diagnostic can break the stream it prints to
- **The rule.** Before adding a human-readable line to an output stream, find every consumer of that stream. If any parses it strictly, use the structured form, or gate the new output to the path that needs it.
- **Why.** A diagnostic printed on a path whose stream is read as strict one-record-per-line JSON broke an unrelated test and would have broken a reader.
- **How to apply.** Run the whole test module, not the targeted test. A measurement add-on that attaches to the process that votes can change its verdict: write to a location the gate itself creates, export after the verdict, keep it outside every bound or evidence path, and make its step continue on error. Test it with a real subprocess and an invalid destination.

### B9. Tool traps that cost a round each
- **The rule.** Know these quirks.
  - **Scanner suppression comments.** With the Bandit security scanner (checked on 1.9.4), a comma list without a space, `# nosec B603,B607`, selects only the last id, while `# nosec B603, B607` and `# nosec B603 B607` select both; prose after the ids is read as test ids. A bare `# nosec` suppresses every check on the line, including unrelated future findings, so use the selective form with a separate comment for the reason. Other scanners have their own suppression syntax (one treats the text after its marker as rule ids): check each one's rules before copying a form.
  - **Shell scripts and quoting.** A backslash, a backtick or a dollar sign inside a heredoc or a double-quoted string is changed by the shell: a path lost its backslashes, a command in backticks ran as a command and opened an interactive session. Write such files with a file-writing tool, quote heredocs, and scan the result for control characters, including tabs.
  - **PowerShell.** An if/else used as an expression collapses a one-element array to a scalar; a parameter named `$args` shadows the automatic variable; variables are case-insensitive, so a local can overwrite a parameter; a file launched with `-File` receives a comma list as one string; `Start-Process` strips inner double quotes from an argument. Generated scripts are ASCII only. Files that generated PowerShell writes or that a tool must read back (scripts, JSON, TOML) are written as UTF-8 without a byte-order mark, and readers of files that people or older tools wrote stay tolerant of one: the older Windows PowerShell's default UTF-8 writer adds a mark that strict readers reject. See [the hosting guide](../supervisor-hosting.md) for the project's rule.
  - **Line endings.** A CRLF written by one tool into a loop that reads lines leaves a stray character on the last field, so a whole batch fails identically; a failing batch that includes an item known to be fine points at the input bytes.
- **Why.** Each fails silently with a wrong result and surfaces much later.
- **How to apply.** Put these in the briefs for seats that write launch scripts. Parse-check every PowerShell script before shipping it.

### B10. Skills and shared texts stay universal
- **The rule.** A skill or other shared text names no repository-specific names, versions or internals. Phrase it as a general principle and put the concrete story in the commit message.
- **Why.** Skills are a reusable pack dropped into any project; a project name in the text makes it wrong elsewhere.
- **How to apply.** Test the wording by asking "would this make sense in a repository that has never heard of us?"

### B11. Stage explicitly, and keep generated files plain
- **The rule.** Stage files by name, never "everything". Make generated scripts ASCII only and write them without a byte-order mark (see B9).
- **Why.** Stage-all once swept an untracked private file into a release commit; a script with a non-ASCII dash character was misread by an older shell, and a byte-order mark written by an older shell made generated configuration invalid.
- **How to apply.** Add ignore rules for the files that keep appearing, and review the staged list before each commit.
