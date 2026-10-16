---
name: thinking-games
description: >-
  Play one short thinking game or role at a few named moments to get a second, different
  list of candidate ideas, then merge it with a plain list. Use at the start of a new
  design or initiative (before its challenge), after two failed attempts on one
  assumption (the reality probe only), or as a side round on product ideas after plain
  experts. Do NOT use on routine work, review-ordered fixes, releases or every task, to
  decide scope, or for a premortem or "should we do this at all" (use the challenge
  skill, agenttalk.challenge or agenttalk-challenge).
reviewed-against: "0.101"
category: production
evidence-profile:
  - planning-artifact
---

# thinking-games

A thinking game is a few minutes of structured thinking that ends in a short list of
ideas you can test. Its job is to make a second list that really differs from the first,
not to be clever. There are two axes: **games** (a way to think) and **roles** (a seat to
think from); a player may combine one of each. The deck is a menu, not a checklist: one
game or role per moment is enough (in a team round, one per pair or group). Play
sometimes, at the moments below; never as a habit.

## WHEN to play
- [ ] **A design start:** a new design, practice or initiative that will get a challenge.
      One game, at most 10 minutes, before the challenge. It works best when the work
      order names the game and the time box, so nobody has to remember.
- [ ] **Two failed attempts on the same assumption:** only the reality probe (card 3).
      What helps now is a checked fact, not more ideas.
- [ ] **Product ideas:** plain experts first, then one game as a side round. Plain experts
      judge worth and fit better; a game mostly adds unusual items.

**Never** on routine work, a fix ordered by a review, a release or a rollback, or every
task. If you are unsure whether the moment counts, it does not.

## EVERY ITEM: four parts
Each item a game, a role or the plain pass produces states, in a line or two:
- **mechanism** - what we would do or change;
- **expected benefit** - what gets better, for whom;
- **main failure mode** - how it most likely goes wrong or misleads us;
- **cheap test** - the smallest check, question or run that would tell.

*Example, in that order:* batch the per-row lookups into one query | page time stops
growing with the row count | one huge query on the largest account | time the page on a
copy of the largest account, before and after. Aim for 3-5 items per list.

## METHOD: two independent lists, then merge
1. **Frame it.** The decision in two or three sentences, plus the plan as it stands.
   Both passes get the same frame. Pick ONE card or role; rotate between rounds.
2. **Plain pass:** "List the 3-5 most important ideas for this plan", in four parts,
   with no card.
3. **Game pass:** the same frame plus the chosen card or role.
4. **Keep the passes blind to each other.** Best: two agents in fresh contexts that never
   see the other list. Alone: write the plain list, put it away unread, then play the
   card from the frame only.
5. **Merge:** take the union and group items by their underlying mechanism, so
   paraphrases collapse into one (keep the clearer wording). Note each item's source.
6. **Mark:** someone other than the lists' author (another agent, the lead or the plan's
   owner) asks of each item: is it useful, is it new compared with the plan, is it
   feasible, can it be tested? Then marks it **adopt**, **reject** or **already in the
   plan**, with one line why. At most one uncertain item may be kept as a **wildcard**
   beside the strongest practical ones. Hide the sources when that is cheap; keep the
   marking to one line per item.
7. **Hand over.** End with the smallest experiment that checks the adopted items (often
   their cheap tests). The plan's owner puts them into the plan. "Nothing useful" is an
   accepted result: record it and move on. A game never decides scope, never approves
   or blocks work, and never replaces the challenge or a review.

## TEAM ROUND: pairs or small groups at one moment
For a large design start or a product-ideas side round, team members can play together:
1. **The lead names the moment and the target:** the frame from step 1 of the method.
2. **Each pair or small group chooses one card, one role format, or a role with a card.**
   No two groups pick the same card or format in one round, so two or more different
   games run at the same time; never the whole deck at once. One group, or one extra
   agent, writes the plain list with no card. A solo agent plays one card.
3. **Play privately and independently,** with no talk between groups until every list
   is written. Seeing the first plausible idea anchors everything after it.
4. **Exchange and transform.** Each group takes items from another group's list and
   reworks them with its own card. Keep the originals too.
5. **Group by mechanism,** collapsing paraphrases, as in the merge above.
6. **Judge as a separate step,** by someone who did not write the items, on each of the
   four questions separately (useful, new compared with the plan, feasible, testable),
   never as one blended score; then mark as in step 6 of the method.
7. **Keep one uncertain wildcard** beside the strongest practical ideas.
8. **End with the smallest experiment** that can check the chosen ideas.

## THE CARDS
Pick by the situation: the goal may be wrong (1, 8); everyone already knows the answer
(2, 7, 11, 12); a key assumption is untested (3); the problem feels new (4, 9); a good
idea was dismissed (10); size or lifetime matters (6); only the builder's view so far (5,
or a role). Card 13 needs a team.
1. **Change the question.** Restate the goal for the user, the operator and the system;
   which version changes what we build? *Example:* "faster export" becomes "the report
   before my morning meeting", which a scheduled export solves.
2. **Forbid the favourite.** Ban the mechanism everyone reaches for first, plan without
   it, then lift the ban and keep what the detour found. *Example:* without "add a
   cache", the page's one query per row shows up; batching it may be enough.
3. **Reality probe.** Name the smallest real run that settles the key assumption today
   (clean checkout, fresh database, another operating system, production-like data),
   then run it. The only card after two failed attempts.
4. **Borrow a mechanism.** How does another field or tool solve this shape of problem?
   Test: explain it without the source's words, or it is decoration. *Example:* a circuit
   breaker is "after five failures in a row, pause calls for a minute, then try one".
5. **The absent person.** Concrete circumstances, not personas: a connection that keeps
   dropping, distrust of the service, never opening the tool unless made to, an auditor
   to answer to. Pull out one improvement that helps everyone.
6. **Extremes.** Ten times the size or a tenth, zero users or ten thousand, an hour or a
   year? *Example:* "in a year" asks who deletes the old logs.
7. **Assumption Jenga.** List the assumptions everyone makes; each player removes one and
   asks what would have to exist for the plan to work without it. *Example:* without
   "the nightly job ends by morning", the page must show the date of its data.
8. **Change the representation.** Describe the problem as a queue, a market, a control
   loop, a negotiation, an information bottleneck or a coordination problem; each view
   must yield a different intervention (as a queue, slow reviews say: limit open work).
9. **Evidence from the future.** Write a short release note, support ticket, incident
   report or complaint ("I love it, but...") from a future where an unusual idea works,
   then work back to the mechanism that made it true.
10. **Rescue the rejected idea.** Name the circumstances in which a dismissed idea is the
    best option, adapt it, and name a cheap test. *Example:* "just use a spreadsheet"
    wins while one person makes a few edits a week; ship it and count the edits.
11. **The constraint lottery.** Draw two constraints and one advantage at random ("must
    work offline", "no new storage", "unlimited computing power"), solve under them,
    then keep only what also improves the real, unconstrained case.
12. **Deliberately terrible ideas.** Each player writes the worst plausible solution, then
    pulls one useful mechanism out of someone else's. *Example:* "email every error to
    everyone" yields "a person sees each new kind of error once".
13. **Mutation relay (team game).** One agent proposes a basic idea; each next agent
    transforms the latest version: invert, subtract a part, transfer, scale, combine or
    shift in time. Keep every version; the best may sit halfway.

## ROLES: the second axis
A role is a seat to think from. A player may combine one role with one game ("the
attacker plays Assumption Jenga") or play a role on its own.

**Role cards.** Each gives circumstances, a goal and a constraint; never a stereotype and
never a real person's name.
- **The attacker:** an ordinary account and plenty of patience; wants data or money out
  without being noticed.
- **The auditor or regulator:** reviews it months later and must sign it off; accepts
  only what is written down and can be traced.
- **The on-call engineer woken at 3 a.m. by it:** no author to ask; needs it safe in
  minutes.
- **The new team member on day one:** must make a small change with only the docs and
  the code.
- **The maintainer two years from now:** must change it after its authors have left.
- **The person who has to undo it:** rolls it back under pressure, with new data already
  written.
- **The competitor explaining why they lost:** sees only what is visible from outside;
  names what they could not copy.
- **The budget owner:** must justify the running cost every quarter, within a fixed
  budget.
- **The support person answering the angry ticket:** must find out what happened without
  a developer.
- **The user who never reads instructions:** clicks the first plausible thing and must
  not lose work.
- **A domain expert:** knows the subject the code models (an accountant for money logic);
  spots the rules the code breaks.
- **The decision-maker:** the person who will decide (the operator, a budget owner, a
  sceptical executive at a demo), built only from the role's documented priorities and
  quoted statements: no names, and no invented opinion presented as theirs. Uses:
  (1) before asking the real person, predict their follow-up questions, so the question
  arrives complete; (2) read a report or plan as them (on a phone, short on time, not a
  programmer) and flag what they would not understand; (3) rehearse a demo with a
  decision-maker who doubts AI, and list the objections to prepare for. **Hard rules:**
  the output is a prediction, labelled "simulated", never a decision. It never replaces
  asking the real person; anything that needs their decision still goes to them. It is
  never sent through a channel that carries their identity or authority (such as a
  message that claims to come from the operator or the lead). Play it in a fresh
  context, ideally on a different vendor, given only the quoted statements, so it does
  not just mirror the author's own assumptions.

**Role formats for a pair or group.** Each fits the team round: different pairs can play
different formats at the same time.
- **Steelman pair:** one argues for, one against, then they swap sides; the output is the
  strongest version of each side.
- **Courtroom:** prosecution, defence and a judge on one proposal; the judge writes the
  verdict and the evidence each side would need.
- **Interview:** one plays a user in concrete circumstances; the other asks questions and
  may NOT propose solutions during the interview. Afterwards both list what surprised them.
- **Stakeholder council:** each player speaks for one stakeholder with a stated interest;
  together they agree a design every stakeholder can live with and record the trade-offs.
- **Red team / blue team:** red attacks the plan (misuse, failure, abuse), blue defends
  and patches; the output is the attacks that survived.

**Rules for roles.**
- A role produces hypotheses, not facts. Anything a role claims about users, attackers or
  regulators is marked as an assumption and gets a cheap test before anyone acts on it.
- Items keep the four parts. A role never decides scope.
- Never impersonate a real person or organisation.
- Give different roles to different vendors (say a Claude seat and a Codex seat) when you
  can: it is a cheap way to get views that really differ.

## NOT HERE: the challenger, the premortem and "do nothing"
The standing challenger role belongs to the challenge skill (agenttalk.challenge in
Claude Code, agenttalk-challenge in Codex): its "Case against" is the premortem, and its
"Alternatives, including doing nothing" covers subtracting the work. Do not rebuild them
here. A game feeds the plan before the challenge; it never answers whether the work
should be done at all.

## KEEP SCORE
After each round, write one line per list (the plain list counts as card `plain`) where
the team keeps notes for that decision, even when nothing was adopted:

```text
thinking-games | <date> | <decision, a few words> | card: <name> | role or format: <name or none> | items: <n> | adopted: <n> | adopted only from this list: <n> | wildcard: yes/no | minutes: play <n>, mark <n>
```

Over time this gives each card, role and format an adoption score. One that never adds
an adopted item that only it found is a candidate to change or drop; say so in your
report rather than quietly stop playing it.

## WHAT THE EVIDENCE SAYS
Games like these are sometimes said to use "different neural pathways". That is a
metaphor nobody can check. The practical target is candidate solutions that really
differ. In a small blind trial, the gain came from two independent lists more than from
any single game: no game beat the plain list, but in every run each list added adopted
items the other missed. The games are a cheap way to make the second list different.

## Evidence

A round feeds a plan and never approves anything. When it is part of other work (a
design, a challenge brief, a work order), record it there and emit that work's evidence.
Only when the round is the whole job, emit the `planning-artifact` profile (full rules +
bus-validated vs skill-policy: ../_shared/references/evidence.md), with the marks as the
`decision`, never a scope decision.

Required fields:

- `artifact_type`
- `scope`
- `decision`
- `assumptions`
- `alternatives`
- `risks`
- `required_reviews`
- `open_questions`
- `evidence`
