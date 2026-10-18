# Playbook: challenges

**In plain words:** a challenge asks someone independent, before work starts, whether the work should be done at all, and whether a smaller or different job would do. The answer is only worth having if the challenger really did not know what you were hoping to hear. This page holds the rules that keep a challenge honest. The full step list is in [Roles, skills and procedures, section 4.5](../ROLES-SKILLS-PROCEDURES.md#45-the-challenge) and in the shipped skill [agenttalk.challenge](../../src/agenttalk/skills/claude/agenttalk.challenge.md); the idea-generation game cards are in [thinking-games](../../src/agenttalk/skills/devkit/thinking-games/SKILL.md). This page adds the habits around them.

### C1. Put a premortem question in every challenge
- **The rule.** Every challenge brief asks the challenger to assume the work failed and say why, including "which environment or system has nobody run this on?"
- **Why.** Challengers tend to judge the plan as written. A failed-future question draws out the cases the plan never mentions.
- **How to apply.** Add the question to the standard brief. A premortem belongs to the challenge; it is not a thinking game (see C5).

### C2. Quote supplied facts in full
- **The rule.** Quote any sentence the operator supplied word for word, mark it "operator-supplied, not checkable from the repository", and say which parts may be reworded.
- **Why.** A summary of the operator's sentence silently left out two clauses. A reviewer then correctly flagged the unquoted clauses as unsupported claims in the public text, and the mistake was the brief's, not the author's.
- **How to apply.** Paste the sentence, do not paraphrase it, in author briefs and reviewer briefs alike.

### C3. A challenge brief must not point at a recommendation
- **The rule.** Check every pointer in a challenge brief. Point to raw sources (vendor documents, issues, data), or put the facts in the brief labelled FACT, ESTIMATE or ASSUMPTION.
- **Why.** A pointer to a research page that ended with a recommended pilot was the pitch by another route. The challenger answered "exposed", which the process counts as unassessed, so the challenge was wasted.
- **How to apply.** Before sending, open each pointer and ask: does this document already say what to do?

### C4. Choose the challenger first
- **The rule.** Pick the challenger before the plan names its owners and reviewers, and keep that seat out of the plan and out of related earlier work.
- **Why.** Two challenges came back "exposed" because the challenger had written the code, and because the plan named every available seat of the other vendor as an owner or reviewer. A cross-vendor challenge became impossible by construction.
- **How to apply.** Write the challenger's name down first. If the plan later needs that seat, choose another challenger.

### C5. Games and extra lists are for named moments only
- **The rule.** Use thinking games only at named moments (the start of a design, before its challenge; after two failed attempts on one assumption outside a review-ordered fix round), never as a routine step and never to decide scope.
- **Why.** In a trial, a game list was not better than a plain list, and judging them cost more time than playing. What did help: two independent lists, one plain and one with a game, merged by someone who wrote neither.
- **How to apply.** Run two independent lists from the same short frame, merge by mechanism, and let a third party mark what is adopted. "Nothing useful" is an accepted result.

### C6. A shipped skill or a public text needs its challenge first
- **The rule.** New or changed skills, and any new kind of public content, go through a challenge before building.
- **Why.** They reach every user of the tool, and a mistake in them is copied everywhere.
- **How to apply.** Count the whole initiative when you decide whether a challenge is required, and record the verdict and your disposition on the dispatch.
