# Playbook: writing for people

**In plain words:** much of what a team of agents writes is read by people who do not program: the operator, a director, a client. Text that squeezes the most facts into the fewest words is useless to them. This page holds the rules for writing so that someone who does not program understands what changed, why it matters and what they must do, with the technical detail kept for the end. The shipped skills do the detailed work: [write-for-humans](../../src/agenttalk/skills/devkit/write-for-humans/SKILL.md) for notes, pull requests, comments and status reports, [write-docs](../../src/agenttalk/skills/devkit/write-docs/SKILL.md) for documentation and [review-docs](../../src/agenttalk/skills/devkit/review-docs/SKILL.md) for reviewing it. This page adds the standing rules and the reasons.

### W1. Write for someone who does not program
- **The rule.** Everything a person reads (release notes, changelog, pull request texts, comments, reports) leads with what changed for the user, then why it matters, then what they will notice ("before" and "now"), then anything they must do. Use simple words and short sentences; length is allowed. Explain each technical term the first time, or avoid it. Put file paths, commit ids and function and test names only in a "technical details" section at the end.
- **Why.** The team's notes and pull requests had become dense and jargon-heavy, which hid what the tool did from the people who needed to understand it. Readers judged the plain samples "much better".
- **How to apply.** Same facts, explained; never drop a fact. Write a summary by reading each detailed entry's limits, not from memory. Messages between agents and briefs stay compact, because input tokens cost money.

### W2. Report to the operator in behaviour, risk and decisions
- **The rule.** Lead with what the software does, what the risk is and what decision is open. Name risk in consequences ("if it wrongly concludes nothing is running, it starts a duplicate"), not in identifiers. End with what needs the operator and what does not.
- **Why.** The operator directs the work but does not read its source. Function names, line references and reason codes are the right currency for briefing agents, and they made accurate reports unusable to the person they were for.
- **How to apply.** General technical words (branches, review, CI, race conditions) are fine; it is this codebase's internals that need translating. Keep identifiers only where the operator may need to act on one: a pull request number, a task number, a command to paste. Still report failures and process breaches plainly; a simpler register must not soften the substance. Do not over-correct into explaining what the reader already knows.

### W3. Documentation is a first-class deliverable
- **The rule.** Write documentation alongside every feature, covering what the product is and how the team works, to a standard that passes a third-party review: every claim traceable to evidence, and verification that can be repeated without tribal knowledge.
- **Why.** The operator asked for it explicitly, and docs written afterwards from memory drift from the code.
- **How to apply.** Follow the [write-docs](../../src/agenttalk/skills/devkit/write-docs/SKILL.md) skill. Cold-read each new page by someone who has not seen the code. Use one plain-language voice across docs, comments, interface text and reports. Comments say why, in a sentence or two. Interface text says what to do next, briefly.

### W4. Committed text never names a client
- **The rule.** Nothing committed or pushed names a client or a client's internals: genericise it or keep it local. A slip is repaired with a forward fix and by editing the host's text, not by rewriting history, unless the operator decides otherwise.
- **Why.** A sweep found a client codename already committed in several public files, and a later slip put a name in a test. A client-reference check blocked the merge, and the fix was a forward fix.
- **How to apply.** Every delta and read brief asks the reviewer to run `gh pr checks <pr>` on the head and report any red check, the client-reference check first; reviewers who reread five rounds had not noticed that one was red. A never-committed denylist drives the tripwire. Evidence from another client stays unnamed and is labelled as another system.

### W5. Material for a client is tactful, and all dark
- **The rule.** Never state a client's code problems bluntly. Describe the general pattern (most long-lived software grows that way and nobody failed) and invite the room to say what feels familiar. Facts about the client come only from public sources or the operator, never from code you have not seen.
- **Why.** The operator thought it "not very nice" to put a client's issues so bluntly in front of its own technical staff.
- **How to apply.** Write the text with the plain-words skill. Whatever the operator prefers for visual style (for instance every slide dark) is an operator preference; ask once and keep it.

### W6. Do not hand the reader the code to read
- **The rule.** When the reader is not a programmer, never make them follow a code snippet, hash or table of identifiers to understand an outcome.
- **Why.** An accurate but unreadable report is the same failure as no report.
- **How to apply.** Use a structural analogy for control flow when it carries the risk faithfully ("two doors between deciding to start and starting; the first is fixed, the second is not").
