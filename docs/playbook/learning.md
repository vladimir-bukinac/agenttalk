# Playbook: learning and curation

**In plain words:** agents forget everything when a session ends. What a team has learned survives only if somebody writes it into the knowledge store and somebody keeps that store in order. This page holds the rules for capturing lessons, for looking them up before a risky step, and for sharing them between teams without leaking anything private. The commands are in [Roles, skills and procedures, sections 4.7 and 4.8](../ROLES-SKILLS-PROCEDURES.md#47-the-lessons-lookup) and the [agent manual](../AGENT-MANUAL.md).

### L1. Use all the features, and above all capture learning
- **The rule.** Every team uses every feature of the tool, most of all captured learning: onboard before each work order, publish before replying, and reply with `lessons=<ids or none>` and `lessons_used=<ids or none>`.
- **Why.** Learning that is not in the store is lost at every session reset, and teams forget it because nothing forces it. A new team's store held no notes at all 35 minutes into its first phase, and another team had published almost nothing in months because its seats had no instruction files and the briefs skipped the step.
- **How to apply.** Put the rule where it survives a reset: a mandatory "capture learning" section in each seat's own instruction file, and a line in every brief naming the step. Name the features that fit the task: skills, gates, the onboarding run, close and challenge.

### L2. Curate on every tick, and measure growth
- **The rule.** Leads curate the store on every loop tick, and check its counts.
- **Why.** Uncurated lessons do not appear in the default onboarding digest, so without curation the learning never reaches the next seat. Zero growth during active work is a finding, not a quiet day.
- **How to apply.** Every gate report has a "learning" section: lessons published, verified and retracted, and the top lessons. Count notes by type, how many are uncurated, onboarding runs and domains.

### L3. Verify the consumer, not the write
- **The rule.** After publishing, check that the note shows up where it is meant to be read.
- **Why.** Notes anchored to a path or commit published without error, yet were marked stale at once and hidden from the default digest, because the store was not in the code repository. The test had only checked that publishing succeeded.
- **How to apply.** Run the onboarding or search command and look for the note. If anchors cannot resolve, anchor the note to the work order and put the path and commit in its text.

### L4. Search the store before a risky one-off
- **The rule.** Before writing or running a one-off script that deletes, moves or overwrites files, edits files containing Windows paths, changes permissions, or touches a live service, run `agenttalk knowledge search <topic words>` and read the matching lessons. Do the same before writing a brief that sets a bar on deletion, links or races.
- **Why.** The lead is not a wrapped seat and receives no injected lessons. After verifying a lesson about writing path-heavy edits as script files, it hit the same trap twice more within hours.
- **How to apply.** When a matching lesson exists, follow it and say so in the step that uses it. Write any memory edit that contains a backslash through a file-writing tool, and finish each memory write with a control-character check.

### L5. Share lessons across teams only without confidential data
- **The rule.** Lessons may be shared between teams only if they hold no confidential data: no client names, no client systems or paths, no secrets, no product details of another team, and nothing that would carry a blind team's earlier findings into it.
- **Why.** Cross-team sharing is valuable and the operator allowed it on exactly that condition.
- **How to apply.** Nothing is shared until a filter and a review step guarantee it. Treat sharing without the filter as forbidden. Retag generic lessons that apply on every turn, and keep their wording neutral.

### L6. Put what is learned in a mechanism
- **The rule.** "I will do better" is gone at the next compaction. A lesson counts only once it lands in a memory file, a skill, a template or a script.
- **Why.** An agent's resolve does not persist across sessions; written rules and mechanical checks did.
- **How to apply.** Codify lead lessons in the shipped lead skill, phrased so that they apply to any project. Keep skills free of repository-specific names, versions and internals, and put the concrete story in the commit message.
