# Playbook: machine safety

**In plain words:** a team of agents runs on real machines with real disks, real memory and real accounts. Most of the worst hours were lost not to bad code but to a machine going wrong: a disk full of leftovers, a terminal closed by an update, a restart that threw away queued work, a command that killed every agent at once. This page holds the rules for keeping the machines and the people's data safe. The cleanup and recovery commands are in [the operations guide](../OPERATIONS.md), [backup and recovery](../BACKUP.md) and the [lead guide](../LEAD-GUIDE.md).

Contents: [work and data](#work-and-data) · [processes and recovery](#processes-and-recovery) · [cost and context](#cost-and-context) · [environment](#environment)

## Work and data

### S1. A team's work stays in the team's own folder
- **The rule.** All of a team's work, including its message bus, scratch files, clones and temporary files, stays inside the team's own folder. Exceptions are declared, and never cover general work or the bus.
- **Why.** On a machine shared by several teams, base temporary folders, tool caches and session transcripts land in shared places. Nobody can tell whose files are whose, so safe cleanup becomes impossible, and one team's data can end up next to another's.
- **How to apply.** Point temporary and cache folders at the team's folder through the launcher. Run a read-only census of what lands outside before designing a deleter.

### S2. Check free space in the lead's loop, and clean up carefully
- **The rule.** Read free disk space on every tick. Clean up when it drops under a set level, and at least daily, in report mode first, then apply, after reading the report. Every lead does this inside its own folder and double-checks before deleting.
- **Why.** Scratch and test leftovers grow without an owner. One machine accumulated an enormous number of files in a scratch folder, and a full disk breaks tests, git and agents.
- **How to apply.** Never delete session histories, seat homes, message stores, runtimes in use, other projects, or anything that is not plainly your own scratch. If space stays low after your cleanup, tell the operator; most of the disk may not be yours. When unsure, keep it and ask.

### S3. Cleanup after a batch, and worktrees after a merge
- **The rule.** After every batch of work the lead runs a scratch cleanup, and seats never leave worktrees or temporary folders behind. Remove a worktree once everything in it is merged and its work is done.
- **Why.** Months of seats using shared scratch and the repository root as test folders left a large pile of worktrees and stray folders, some holding uncommitted work, and some with permissions that needed an elevated shell to remove. Another team kept forgetting, leaving a large amount of disk every few days.
- **How to apply.** Every dispatch names the seat's own scratch folder; the close-out says "scratch removed". A closing step checks for a clean worktree, work already in the main line and no links, and uses a plain, non-forced removal. Keep a folder whose delete fails rather than forcing it.

### S4. A deleter never follows a link
- **The rule.** A delete step must not follow a junction or symbolic link out of the folder it is cleaning.
- **Why.** A "stubborn delete" fallback that took ownership recursively and mirrored an empty folder could follow a junction and delete files outside its folder. The automatic cleanup was suspended until a link-safe fix was reviewed.
- **How to apply.** Delete only what is plainly yours, by explicit list. Never run recursive ownership-and-permission commands on a folder you cannot fully account for.

### S5. Destructive actions on shared resources need the operator
- **The rule.** Mass branch deletes, removing worktrees you did not create, and force-pushes in a shared repository need the operator's own authorisation. A peer or lead message is not enough.
- **Why.** The safety classifier allowed a worktree sweep a lead had greenlit, then denied the mass branch delete: peer authorisation is not the user's intent.
- **How to apply.** Surface the request to the operator and let them decide. Never work around a denial. A standing approval names exactly what it covers and what it never covers (the operator's other projects, named volumes that offline builds need, running containers, images in use, blanket "prune everything" commands), is carried out by an explicit list, and keeps that list on record. Compacting a runtime's data disk is separate, because it needs the runtime stopped.

### S6. Back up the conversation that records the decisions
- **The rule.** Back up the lead-and-operator conversation regularly. It is the only verbatim record of the operator's decisions; memory is a summary. Check your session provider's current retention for these files and where to verify it.
- **Why.** Some tools delete old session files after a retention period, so a retired session can vanish once that period passes. Which tools do this, and after how long, differs by tool and version.
- **How to apply.** Keep encrypted copies in two places, never in a public or cloud service when the sessions hold client details. Give the password in the terminal only. Test a restore.

### S7. On a real client migration, no code leaves the boundary
- **The rule.** Legacy code must not be sent to an external model or service. Validate any comprehension tool with a cheap spike before betting a core capability on it, especially one with a single maintainer.
- **Why.** A client's code is confidential, and a migration programme's local-only promise is worthless if one tool phones home.
- **How to apply.** In a programme that must contact nothing, enumerate and disable library telemetry and "phone home" defaults in the runtime environment before the first gate, run one gate behind a capture proxy that logs and closes connections, and require zero captured lines. One upgraded library had been sending cloud-metadata probes and a vendor call on every start through days of gates.

## Processes and recovery

### S8. Stop processes by exact id, never by name
- **The rule.** Use the platform's native stop command with a specific process id. Never stop by image name, and tell subagents so in their briefs.
- **Why.** A cold-read subagent cleaned up with a name-wide kill of the interpreter, and killed every wrapped agent on the host, because every wrapper is one.
- **How to apply.** Add "never kill processes by image name; if you must stop something you started, kill it by its own id" to every review and cold-read brief. When you hunt for a process by its command line, exclude your own shell, or your hunt will kill it.

### S9. Never run a foreground copy of your own tool inside a session
- **The rule.** Do not launch a nested copy of the same command-line tool (or a wrapper loop) in the foreground from inside a session.
- **Why.** When the nested copy hung, the harness's two-minute timeout killed the parent session too, because they shared a process group.
- **How to apply.** Run any nested CLI or gateway-hitting call in the background. For a one-shot probe, use a different client, such as a plain HTTP request, so a kill cannot reach the session.

### S10. Recover a wedged wrapped worker without discarding work
- **The rule.** Stop the wrapper by its exact process id, start a fresh session, and clear stale liveness files. Keep the message cursor when the queued work is still wanted: advancing the cursor discards the queued messages, and only an explicitly authorised abandonment of a message may do that. Never describe "empty the inbox" as a general recipe.
- **Why.** A relaunch of a worker with failure baggage at the head of its inbox wedges again. But the standard clean-slate recipe, which advances the cursor, also drops the dispatches. A mid-turn kill is safe for the mail: the message was read but not committed, so it is redelivered on the fresh session.
- **How to apply.** Check the whole picture first:
  - **Delivered already?** Before clearing retry state and relaunching, check whether the work was already delivered (a commit on its branch, a reply on the bus). If it was, do not relaunch: the cursor still precedes the message and the whole task would run again. If completion is unclear, ask the owner of the work.
  - **Retry loop?** A message that keeps being retried is gated by its dead-letter attempt record, not by the cursor. Read that record first, and verify that the attempt count stops rising before you claim a fix. A reboot does not clear it.
  - **Scope.** Use the supported, narrowly scoped operations: a fresh session between turns, or acknowledging one message. The bus-wide reset command is not a per-agent repair.
  - **Changing a model or effort.** Set an explicit model id rather than an alias, and verify the change in the wrapper's session record: the effective runtime fingerprint, a new or cleared conversation identity and the continuity reason. The turn count is kept, so do not wait for it to reset; configuration alone is not proof.
  - **Verify absence.** A restart request does not relaunch a wrapper while the old process is alive; check that the old wrapper is gone before you ask again.

### S11. A frozen counter on an active agent is a fault
- **The rule.** A progress counter that stands still while the agent is marked active is a fault on its own. Do not average it into "working slowly".
- **Why.** Two agents lost about two hours each to a freeze that was unambiguous on first sight; the per-turn watchdog had killed the child, and the wrapper did not survive its own watchdog kill.
- **How to apply.** On every status pass compare the last-progress time with now, per agent. If it equals the previous reading, diagnose. Compare the freeze time with the turn's start time: a gap near the watchdog limit means the watchdog fired. A frozen wrapper is not lost work: files persist, and a death costs session context, not the filesystem.

### S12. Diagnose fleet health with independent evidence
- **The rule.** Do not infer a shared outage from one agent's auto-classified health. Read all of what you consumed. Health-check before you launch or rely on a seat. Keep observed facts apart from inferred causes.
- **Why.** One misclassified spawn failure was reported as "the provider is throttled" while the operator's own working session was the disproof. A reader that drained the whole inbox then blamed a reviewer who had already answered. A long-dead reviewer was relaunched into a panel without a check.
- **How to apply.** Before escalating a cause, run the cheapest disproof: is a peer on the same dependency working? Did I read the whole output? Is the heartbeat fresh? "A reply is waiting for you to read" does not mean "no reply yet". For supervisor incidents read the durable event log first; per-attempt snapshots are overwritten.

### S13. Run long-lived processes outside the terminal app
- **The rule.** Turn off automatic updates of the terminal app that hosts the lead and the gateway consoles, or run long-lived processes outside it.
- **Why.** An automatic update of the terminal app closed every console it hosted: the lead's session and the gateway died, and the hidden seat wrappers sat idle for many hours because nobody dispatched.
- **How to apply.** Set the default console host to the plain one, pause or disable store updates, run the gateway without a window, and add an alert for "lead silent", "gateway not ready" or "no wrapper running". A runtime switch must list every caller pinned to the old runtime, including the alert path, and a scheduled watcher follows the runtime it watches.

### S14. A lead must be able to restart its own team
- **The rule.** A lead must be able to start and restart its members, directly or through a supervisor the operator starts. The permission change that allows it is applied by the operator: the lead never edits its own permissions and never routes around a denial. It reports the exact change needed.
- **Why.** Seats died twice and only the operator could relaunch them.
- **How to apply.** Prefer a narrow allow rule for the exact launch command. Compound commands are judged per step. Write Windows paths in settings text with forward slashes and read the result back; a backslash-letter in a string turned into a control character once.

### S15. Do not fight the Windows sandbox, plan around it
- **The rule.** A sandboxed Codex seat on Windows fails atomic temporary-file writes, blocks some interpreters and aliases, forks launchers, and needs a Git repository as its working folder and an unattended sandbox setting in its configuration. Plan writes and launches around that.
- **Why.** Each of these looked like a silent turn: a seat with commits and no reply may have been blocked by its own approval layer, not slow. A never-started turn looks like silence.
- **How to apply.**
  - Run the tool as `python -m agenttalk` where the alias is denied.
  - Make the seat's folder a Git repository, with a trusted entry and an unattended sandbox setting.
  - Re-inherit permissions on a file a long-lived process holds open before launching a new seat.
  - Do not stop at the first fix: a resumed thread keeps its old settings, so check the real cause.
  - Check health after a dispatch.

### S16. Run stable releases of the tools
- **The rule.** Run the latest stable releases of the command-line tools, never alpha or beta builds.
- **Why.** A beta changed the flags the supervisor depends on and broke a preflight.
- **How to apply.** Treat beta-only breakage as future-proofing work, not a fire drill, and point launch settings at the stable install.

### S17. Headless runs and permissions
- **The rule.** A headless run hangs in every permission mode that prompts, and print mode needs a no-prompt mode. A mode does not persist between runs.
- **Why.** A prompt with no terminal waits forever.
- **How to apply.** Set the mode at each launch. Prove a deny rule with a real turn in the seat's real mode: a deny rule in a seat's settings was enforced even in bypass mode.

## Cost and context

### S18. Long conversations cost more at every step
- **The rule.** Every turn re-sends the whole conversation, so cost and failure risk grow with the age of a long-running agent. Preserve work: refresh an agent only between turns, through the supported path, with a backup and an audit record, within the authority given, and never route around a denial.
- **Why.** The cost of a long task grows much faster than its length, because the whole conversation is sent again at every step, and a very large session file can crash the seat.
- **How to apply.** Use a fresh thread per dispatch or per work arc, keep reads narrow, and put a ceiling on retries. A restart threshold such as "restart an idle agent past a few hundred turns" is a local, interim number each team sets; it is not a universal rule. A seat's very long session can also hit a provider's request-size cap, so give long-running seats a fresh session between large tasks.

### S19. A usage-limit error is terminal until the limit resets
- **The rule.** Do not retry a usage-limit error. Pause the seat and re-route the work.
- **Why.** A wrapper that re-sent the same large message many times burned a share of the allowance on messages that could not succeed.
- **How to apply.** Cap retries low, with no compaction on retry. Run tool-heavy work on seats that are not short of allowance. Several seats going quiet in the same window with the wrappers alive points to an account limit, not a fault.

## Environment

### S20. Check memory the right way, and keep other jobs away
- **The rule.** Check free memory before a wave of work, and do not read "memory used" as a leak.
- **Why.** A container host's virtual machine kept file cache as used memory, so a machine looked out of memory with one container running. A broad find-and-search over the live message store stalled publication for minutes.
- **How to apply.** Compare the virtual machine's use with the containers' real use before calling the machine full; dropping clean cache is safe. Do not run broad scans over a live store.

### S21. Build releases from a clean checkout
- **The rule.** Build a release package from a checkout with automatic line-ending conversion turned off.
- **Why.** A package built from a converting checkout carried the wrong line endings and made dozens of skills "differ".
- **How to apply.** Check by diffing the installed skills against a dry run.
