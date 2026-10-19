# The team playbook

**In plain words:** this is the set of standing rules a team of AI agents works by, written down with the reason behind each one. Each rule says what to do, why (the mishap that taught it, told without names), and how to apply it. They were learned the hard way while running real teams, and they are written so that any team can use them, whatever its project. Nothing here is a law of nature: it is where we ended up, and the operator's instructions always win.

The playbook sits beside the other pages and does not replace them. [Roles, skills and procedures](../ROLES-SKILLS-PROCEDURES.md) says who does what and lists the step-by-step procedures, and the shipped skills carry the detailed practice. The playbook is the "why" and the "watch out for" behind them. Where a skill already says a thing, the page links to it instead of repeating it.

## The pages

| Page | What it covers | Rules |
|---|---|---|
| [The review rule](review.md) | How rounds of review are set up, how to brief a reader without steering them, what a reader checks, and review hygiene | 35 |
| [Challenges](challenges.md) | Keeping a "should we do this at all?" challenge honest | 6 |
| [Dispatch mechanics](dispatch.md) | Sending work and replies so they publish and survive; how a seat's turn works; routing and boundaries | 21 |
| [The merge gate](merge-gate.md) | Reading CI and the automated reviewer honestly, merging approved changes together, releasing | 15 |
| [Learning and curation](learning.md) | Capturing, curating, looking up and sharing lessons | 6 |
| [Machine safety](machine-safety.md) | Disks, deletions, processes, recovery, cost and the machine environment | 21 |
| [Writing for people](writing-for-people.md) | Plain-language reports, documentation, client material | 6 |
| [Build and test](build-and-test.md) | Tests that tell the truth, tool traps, a written definition of done | 11 |
| [Lead conduct](lead-conduct.md) | How a lead decides, what it asks the operator, and how its routines stay honest | 8 |

## How to read a rule

Each rule has the same three parts:

- **The rule:** what to do, in one or two sentences.
- **Why:** the reason, usually a small incident told in neutral words.
- **How to apply:** what it means in practice, including the check that shows you followed it.

Where a rule names a command, it is a command of the installed tool (`agenttalk ...`); the [lead guide](../LEAD-GUIDE.md) says how to run it.

## Keeping it honest

- A rule here that a shipped skill or procedure contradicts is a bug in one of them: fix it in the same change.
- A rule is added only with its reason. If you cannot say what went wrong without it, it is a preference, not a rule.
- Keep the text free of names of clients, people, machines, addresses and private paths. The client-reference check catches only the references on its known denylist, so it does not replace a privacy read: review every new page for private details yourself.
