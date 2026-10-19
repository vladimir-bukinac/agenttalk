# Playbook: dispatch mechanics

**In plain words:** most lost work in a team of agents is lost in the handover: a message that never published, a reply that never closed the task, a seat that waited for something that could not arrive. This page holds the rules for sending work and replies so that they publish and survive. The commands and step lists are in [Roles, skills and procedures, section 4.1](../ROLES-SKILLS-PROCEDURES.md#41-handing-out-work), the [agent manual](../AGENT-MANUAL.md) and the shipped skills [agenttalk.lead](../../src/agenttalk/skills/claude/agenttalk.lead.md) and [agenttalk.handoff](../../src/agenttalk/skills/claude/agenttalk.handoff.md). This page adds the reasons and the habits.

Contents: [sending](#sending) · [the seat's turn](#the-seats-turn) · [boundaries and routing](#boundaries-and-routing)

## Sending

### D1. One bus publication per tool call
- **The rule.** Send one task, acknowledgement, withdrawal or reply per tool call, spaced out. Never loop sends inside one command.
- **Why.** Each send holds a guard on the message store while it scans it. A seat whose turn ended inside that window died without a trace. Seats died within minutes of a batch of sends fired from one shell, and a week of earlier deaths had been blamed on session limits because the exit line was never captured.
- **How to apply.** Space sends across turns, especially right after acknowledging a seat. Launch wrappers with their output redirected to a log, and check liveness by looking for the wrapper process, not for a health file.

### D2. Check that a send was published, not that it printed an id
- **The rule.** After every task or message, read the output for "refused", "must", "error" or "invalid", check the send's exit status, and confirm publication of this very message: find the message or request id the command reported in the store and check it is there with the content you sent. A store-wide timestamp or an unread count can change because of other traffic, so neither proves that your send succeeded.
- **Why.** A refused send (a bad work-item name with a dot in it, a stage word that does not exist) still printed an automatic request id, and a pipe to another command hid the exit code. A review was never delivered and cost a long delay.
- **How to apply.** Use `set -o pipefail` or no pipe on send commands. Keep work-item names to lowercase letters, digits and dashes, and use only the stage words the tool lists (design, build, read, fix, delta, sweep).

### D3. Do not put a short timeout on a send, and drain to a file
- **The rule.** Never wrap a send in a short timeout, and never read the inbox through a filter on the terminal.
- **Why.** A timeout killed a send mid-publication and left an unpublished orphan. A filtered read let a reviewer's verdict scroll out of sight, and the lead told the operator it was still waiting for a rejection that had already arrived.
- **How to apply.** Drain to a file and search the file. When several answers are expected, reconcile each request: a request that is neither still open nor seen as answered means you missed the reply. Never judge a stuck agent from a status label's wording or a hand-made search; read the real inbox.

### D4. Every task's reply line carries `status=done`
- **The rule.** Close a task with a typed task response whose status is done or declined, and put `--meta status=done` in every brief's reply line, even when the verdict is FIX: the task is done.
- **Why.** A brief template asked for a verdict but no status, so seats copied it literally and many answered tasks stayed open; the lead's waiting count filled with tasks that had already been answered, and a real unanswered task hid among them.
- **How to apply.** Write the reply line out in full in the brief, including the work item, stage and commit. Know the real behaviour too: the tool also treats a response with no status but a non-blank verdict as finished (a compatibility path), while a response with status accepted, or an empty response, leaves the task open. So check the thread's actual state before you decide a task is still owed.

### D5. One task, one reply
- **The rule.** Never ask one task for two replies. Split it into two tasks.
- **Why.** Two terminal replies are a thread conflict.
- **How to apply.** If you want an interim note, ask for a progress message, which does not close anything.

### D6. The message kind is a contract
- **The rule.** Choose the kind from the verb of what you want back. A branch and a commit means a work dispatch; a verdict and findings means a review request. A review request is read-only, and a worker will refuse to write files under it.
- **Why.** Two builds were sent as review requests, and both workers correctly refused. The briefs looked almost the same.
- **How to apply.** If a reply comes back as analysis where you expected a commit, check the kind before assuming the worker under-delivered.

### D7. A review task names the commit it reviews
- **The rule.** Put the commit to be read on the review task itself. Build and fix tasks do not need one.
- **Why.** Without it, a reply naming a commit is refused as contradicting the opener, and a seat can fall back to a path that closes the task but loses the typed verdict.
- **How to apply.** Pin the head in the brief. A task reply and a typed review verdict are not the same thing.

### D8. Correlate by request id, and name things exactly
- **The rule.** Match a follow-up to a build by the thread's request id, not by the send's message id. Check every name and identifier in the code before handing it to another team. Keep double quotes out of message bodies and use a file for the body.
- **Why.** A wrong key name was passed to another team; a quoting mix-up truncated a brief; message ids differ from request ids.
- **How to apply.** Look the name up in the code at the moment you write the brief, not only the claims you doubt.

### D9. A denied compound command denied every step
- **The rule.** If a harness refuses a command made of several steps, it refused all of them. Re-check what actually landed before telling anyone it was done.
- **Why.** A copy step inside a refused command never ran, and the operator was told the file was in place.
- **How to apply.** Run steps separately, and verify the result, not the reply.

## The seat's turn

### D10. Give every dispatch its own context
- **The rule.** Every brief to a wrapped seat carries a context header: which checkout and branch, the tip commit, the folder with the files to read, the toolchain, and the seat's conventions. Say "first verify each item is still true at your master; if it is already fixed, say so with evidence and skip."
- **Why.** Several wrapped seats lost their session context mid-task and woke up in the wrapper's folder, unable to find the commits the brief referred to. The ones that escalated instead of inventing an answer did the right thing; the programme should make refusal unnecessary. A stale ticket also sent one seat to rebuild work that was merged days earlier.
- **How to apply.** Keep re-onboarding text ready to reuse. If a seat says a commit does not exist, treat it as a reset, verify its worktree yourself, and re-onboard; never tell it to recreate the work.

### D11. A background job dies with the turn
- **The rule.** Tell wrapped seats: no background runs, every command in the foreground, no single step over about eight minutes, and never end a turn waiting for a background notification. Finish, or reply "blocked".
- **Why.** A wrapped turn is one CLI run; when the model's last reply arrives the run exits and its children go with it. Seats ended turns "waiting for the test run", sat idle, and lost the run. The tool also quietly moves any command over about ten minutes to the background.
- **How to apply.** For a long job, start it detached with its output in a file, then poll in the foreground with bounded waits, each poll its own command, and reply only at the end. Ask for a progress line after every N items. Split long jobs into chunks, and make runners restore what they change atomically.

### D12. A turn is started by a message, so acknowledge promptly
- **The rule.** A wrapped agent that closes a turn saying it will "continue next turn" idles until something arrives. Acknowledge each close-out at once, and never batch acknowledgements behind a slower cadence.
- **Why.** An hour was lost to a pipeline that waited for acknowledgements the lead was holding for its next status round.
- **How to apply.** The lead's acknowledgement is the turn trigger. When a gate or review result arrives, send it the same moment to every seat whose task depends on it; one builder waited for hours for a result the lead never relayed.

### D13. Check a quiet seat, do not wait
- **The rule.** A seat that has been idle for more than about an hour after a build order, with no reply, gets its branch checked and a question.
- **Why.** Silence after an order is information. Several seats had finished, or had been blocked by their own approval layer, and said nothing.
- **How to apply.** Look at the branch and the process. An idle seat with commits and no reply may have been blocked, not slow.

### D14. Stagger fleet-wide asks
- **The rule.** For an ask to every seat, send in waves of two or three and wait for replies before the next wave. Do not start a wave when free memory is below the floor you have set for the host.
- **Why.** Several seats sent the same brief within minutes all worked at once, and host memory fell low enough that the harness kills commands and wrappers.
- **How to apply.** Check free memory in a separate call first. A check printed in the same command as the send gates nothing. Ask only the seats whose vantage point matters unless the operator asked for the whole team.

### D15. Listen honestly
- **The rule.** Say "listening" only as a best effort. A background wait does not survive a compaction, and some harnesses end idle background processes. The durable bus holds every message, and the wrapper is the real always-on listener.
- **Why.** Over-claiming continuous listening misled the operator about reliability, more than once.
- **How to apply.** After a compaction or a resume, re-arm the wait and read the roster again, and tell the operator that one line brings you back after any gap.

### D16. Read the action a state machine decided
- **The rule.** When something will not start, read the action it decided, not the loudest warning it printed.
- **Why.** Two hosts spent hours on a long, well-written warning about a different concern, while a one-word action field said "warn and do nothing", which was the actual block.
- **How to apply.** Dump the machine's plan, find the field that says what it will do, and trace which condition produced it before reading the warnings. A state whose name promises a move may be terminal: ask what can move it.

## Boundaries and routing

### D17. Name exact folders when you ask another team to read files
- **The rule.** A request to another team (or a seat) that involves reading or searching files names exact folders inside that team's own area, and forbids starting from a user profile, a tool home, a temporary folder or a drive root.
- **Why.** A vague "search your logs" request ran across a shared folder holding another team's confidential transcripts. It was killed in time and nothing was kept, but it crossed the line.
- **How to apply.** Prefer data the product already records over reading transcripts. Each team's exported data is written only inside that team's own folder; check any helper script that touches two team folders for writes before you run it.

### D18. A throwaway store covers tests and probes, not your own bus commands
- **The rule.** In a brief, say that the "throwaway store, never the live store" rule is for tests and probes. The seat's own reply and its lesson publish and search go to the live bus.
- **Why.** A reader obeyed a blanket "never the live store" literally and published no lessons.
- **How to apply.** Use the wording: "Tests and probes use a throwaway store. Your own bus commands (the reply below, `agenttalk knowledge publish` for lessons) go to the live bus as normal."

### D19. Route decisions through the lead, and flag shared changes first
- **The rule.** A seat routes decisions and questions through the lead who owns the operator's single voice. Even when the operator types in a seat's window, give status and send the decision to the lead. Flag shared or infrastructure changes before working on them.
- **Why.** A seat asked the operator two decisions directly, and another prepared a parallel fix for a problem the lead had already fixed.
- **How to apply.** Use `agenttalk escalate` when no liaison exists.

### D20. The live roster is the truth
- **The rule.** Read the roster and your identity from the live store before acting on team membership. A roster remembered from earlier is stale by construction.
- **Why.** A resumed session acted on a remembered roster and had to re-sync after members had been added and the lead identity had moved.
- **How to apply.** Run the roster command at the moment you dispatch, gate or route.
