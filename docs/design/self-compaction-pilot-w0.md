# Self-compaction pilot: step 0 (W0) report

Status: done on 2026-10-18 for work order tk-d186aa0d56a3. It belongs to the design `docs/design/self-compaction-pilot.md` (head `a25b3981`, pull request #531), which the final read tk-e78baa38e6a0 passed with no P1. Code checked at master `7a613aeb` (release 0.102.0), with Claude Code 2.1.300.

**In plain words:** before anything is built, step 0 checks six assumptions the design could not settle by reading code. Five of them hold. Two hold only with changes that the build must make, and the probes found three details that change how the pilot counts and prices model calls. The sixth, measuring the size of each request without a proxy that sees the credential, cannot be done for this kind of agent: request size stays **not measured**, as an explicit exception for the lead's decision. This report is for the lead, the Codex reader and the builders of W1 to W12.

## Results at a glance

| Item | Assumption | Result |
|---|---|---|
| (a) | The stream reports usage, with the three input fields, for every model call | **Pass, with two corrections** to how calls and output are counted |
| (b) | `--resume <id> --fork-session` leaves the original conversation unchanged | **Pass** |
| (c) | Applying the fresh-start request before the prompt is built breaks no existing test | **Pass** |
| (d) | A per-turn `AGENTTALK_TURN_ID` can reach the model process on both backend paths | **Pass, with two required changes** |
| (e) | The stream reports the model's context window | **Pass** |
| (f) | Request sizes can be recorded without contents and without a credential-bearing proxy | **Not measured:** no such observer exists for this backend |

## How it was run

- **Where:** a throwaway folder under this agent's scratch area, outside every project store. The agenttalk variables of the agent's own environment (`AGENTTALK_ROOT`, `AGENTTALK_SELF` and the per-turn ones) were cleared for each probe, and Claude Code has no user-level hooks on this machine, so no probe could reach the live bus.
- **What ran:**
  - two one-off Claude Code runs (`claude -p`, model alias `haiku`, which resolved to `claude-haiku-5-5`): one turn with one tool call, then one forked turn. Claude Code's own list-price figure for the two runs together was 0.0073 USD;
  - one pure Python call of `_child_env` per backend path;
  - the targeted wrapper tests, twice, in a detached worktree at master.
- **What did not run:** no seat was started, restarted or fresh-started; no store other than test stores was written; no proxy or observer was installed or inserted; no client code was touched.
- **Evidence kept** in the scratch folder: the two raw streams, a summary of their usage fields (counts only), the probe script for (d), and the two test logs.

## (a) Usage on every model call

- **Pass rule:** in a turn with at least two model calls, every call reports `input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens`, and the number of calls can be counted.
- **What ran:** one turn whose model called a tool once and then answered, with the stream options the wrapper uses today (`--output-format stream-json --verbose --include-partial-messages`).
- **Result: pass.** Every `assistant` event carried the three input fields, and the stream's `result` event said `num_turns: 2`, matching the two calls.
- **Two corrections** for the counting in W1 and W2:
  1. **One call can produce several `assistant` events.** The second call produced two (a thinking block, then a text block) with the same message id and the same usage repeated. Counting `assistant` events would have counted 3 calls instead of 2. Calls are counted by distinct message id, or from `num_turns`.
  2. **The output count on an `assistant` event is not final.** It said 3 output tokens where the call's final count, in the `message_delta` stream event, was 59. The input side can be read from the first event of a call (`message_start`), but output must come from `message_delta`.
- **Three more details found:**
  - **Reasoning tokens** are part of the output count: `message_delta.usage.output_tokens_details.thinking_tokens` was 56 of the 59. They are priced as output and can be recorded separately (this answers one of the final read's P3 questions for W2).
  - **Cache writes come in two kinds:** `cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`. In this probe all cache writes were the one-hour kind. Claude Code's own price table prices a five-minute write at 1.25 times plain input and a one-hour write at 2 times (for example 6.25 and 10 per million tokens against 5 for plain input; reads 0.5, output 25). The design's input-equivalent formula prices every cache write at 1.25, so it undercounts one-hour writes.
  - **Claude Code reports its own cost figure:** `total_cost_usd` and, per model, `costUSD` with `costBasis: "list"` (list prices, not a bill). Its price table also has a tier for long prompts (`longPrompt.abovePromptTokens`, filled from pricing data the program loads), which the token formula ignores; that matters for conversations of several hundred thousand tokens.

## (b) A fork leaves the original conversation unchanged

- **Pass rule:** `--resume <id> --fork-session` starts a conversation with a new session id that carries the original's history, and the original's transcript file is byte-for-byte unchanged afterwards.
- **What ran:** the conversation from (a) was fingerprinted (SHA-256 of its transcript file), resumed with `--fork-session` for one short turn, and fingerprinted again.
- **Result: pass.**
  - The fork got a new session id.
  - The original's fingerprint was the same before and after.
  - The fork's transcript held the original's tool call.
- **Found:** the fork's first call read 31,568 tokens from the prompt cache that the original had written minutes earlier. A fork shares the original's cache while that cache lives (one hour here), so the bench must record each arm's cache state (section "What W0 changes").

## (c) Applying the request before building the prompt

- **Pass rule:** with `_apply_fresh_request` moved before `assemble_turn_prompt` in `make_drive` and before `assemble_cadence_prompt` in `make_cadence_drive`, every test that exercises those drives, the fresh-start request, the prompt text or the golden scenarios gives the same result as on unchanged master.
- **What ran:** 36 test files, selected by searching the tests for the two drives, the fresh-start functions, the two prompt functions and the golden scenario modules. They ran once on unchanged master and once with the four moved lines, in a detached worktree, with the local app-data folder redirected to scratch.
- **Result: pass.** Unchanged master: 1,447 passed, 1 expected failure. With the reorder: 1,447 passed, 1 expected failure, the same tests with the same outcomes.
- **Why it is safe:** neither prompt function reads the session state; they take the message, the rules, the rejoin block, the lessons, the sender fact and the relay notice. So the move changes nothing today.
- **What it does not show:** no existing test fails when the order is wrong either. W7 must add a test that pins the new order: the first prompt after an applied request knows the conversation is new.

## (d) A per-turn value reaches the model process

- **Pass rule:** a value passed to `_child_env` for one turn reaches the model process's environment on the default path and on the `ovh-qwen` path, and a stale value of the same name inherited by the wrapper does not.
- **What ran:** `_child_env` was called for both paths with a throwaway workspace, with `AGENTTALK_TURN_ID` and `AGENTTALK_INBOUND_REQUEST_ID` set to stale values in the calling environment, and a fresh `inbound_request_id` passed in.
- **Result: pass for the mechanism, with two required changes.**
  - On both paths the passed-in request id replaced the stale one. That is the mechanism a turn id needs: both paths remove the wrapper's own per-turn names (`AGENTTALK_WRAPPER_GENERATION`, `AGENTTALK_INBOUND_REQUEST_ID`) and set the passed values at the end.
  - **Change 1:** a stale `AGENTTALK_TURN_ID` passed through unchanged on both paths today, because it is not one of the removed names. The build must add it to those names and set it only from the turn that is starting.
  - **Change 2:** the message turn's spawner calls `_child_env` with the request id, generation and backend profile, but the cadence turn's spawner calls it with the agent name only. A lead's cadence turns would therefore get no turn id, so that call must pass it too.

## (e) The model's context window

- **Pass rule:** the stream states the context window of the model the turn used.
- **Result: pass.** The `result` event's `modelUsage.<model>.contextWindow` said 1,000,000 for the model used, with `maxOutputTokens`.
- **Effect:** the design's "too large" rule can use this figure. The per-agent `too_large_tokens` setting is only a fallback for a stream that lacks it.

## (f) Request size

- **Pass rule (from the design and the final read):** an observer records the byte size of every request the agent sends, without keeping any content, and without a proxy that holds the credential.
- **What was checked, without installing or inserting anything:**
  1. **Claude Code's own telemetry.** Its `api_request` event (read from the installed program) carries the model, the four token counts, the two kinds of cache write, cost, durations and request ids, and no size. Its `claude_code.llm_request` trace span, as far as its attributes are visible in the program, carries the model, the request's context kind and speed, and attempt events with request ids, and no size. The size fields that do exist in the program belong to other features (file uploads, a browser bridge) or are general telemetry constants, not the model request.
  2. **Debug logging.** It would print request contents, so it is excluded by the rule.
  3. **Operating-system network counters** (per-process byte counts or kernel network tracing). They need no proxy and see no content, but they count all of the process's traffic. They cannot split one model request from another on a shared encrypted connection, so they measure something else.
  4. **A transcript or a rebuilt request.** Both are estimates, not measurements, and the design already excludes the transcript.
- **Result: not measured.** No observer meets the rule for this backend. The pilot records request size as an explicit exception: it makes no claim about oversized requests, and W14's decision record must say that the reshape's request-size measurement was not met.
- **What a measurement would take, for the operator's decision later.** The only way that measures the real request is a local pass-through set through `ANTHROPIC_BASE_URL`. It would:
  - **touch** the subscription's credential (the sign-in token passes through it on every request) and every request's full content in memory, even if it stores only sizes;
  - **sit on the path** of every model call of the pilot agent: if it stops, the agent stops;
  - need checking whether Claude Code accepts a changed base address while it signs in with a subscription;
  - need its own security read, a rule that it never writes bodies or headers anywhere, and the operator's explicit approval.

  Nothing of this was built or tried.
- **Where the reported failure happened:** the "Request too large (max 32MB)" of 2026-10-18 was on a Qwen agent behind agenttalk's own gateway. That gateway's front reads each request's `Content-Length` on the path it serves and refuses anything above its own limit (`MAX_REQUEST_BYTES`, 512 KiB, in `ovh_gateway.py`), so a size record there needs no new proxy. Whether every model request of that backend passes that check, and where the 32 MB limit was enforced, was not checked here. It is a separate item, outside this pilot.

## What W0 changes in the later work orders

| Work order | Change |
|---|---|
| W1 (the measurement) | Read a call's input side from its first event (`message_start` or the first `assistant` event of that message id), never by summing `assistant` events. |
| W2 (telemetry) | Count calls by distinct message id and check against `num_turns`. Take output from `message_delta`. Record reasoning tokens apart. Record five-minute and one-hour cache writes apart. Price one-hour writes at 2 times plain input, not 1.25. Also record Claude Code's `total_cost_usd` (list prices, including its long-prompt tier) beside the input-equivalent figure, both labelled as estimates; whether A1 and B5 should use the list figure instead is a question for the lead. Record `contextWindow`. |
| W4 and W6 (notes, guards) | Add `AGENTTALK_TURN_ID` to the names `_child_env` removes from the inherited environment on both paths, and set it per spawn. Pass it in the cadence spawner's call too. |
| W7 (loader) | Add a test that pins apply-before-assemble in both drives (none fails today when the order is wrong). |
| W8 (every path) | Use `modelUsage.<model>.contextWindow` for the too-large rule; `too_large_tokens` only as a fallback. |
| W12 (phase A bench) | Record whether each arm's first call read or wrote the prompt cache, and compare arms only in the same cache state: a fork shares the original's cache for up to an hour. |
| W14 (the decision) | State the request-size exception: not measured, no oversized-request claim. |
| Every Claude Code upgrade during the pilot | Run probes (a), (b) and (e) again, because the stream format is the program's, not ours. |

## The final read's binding requirements, by work order

The final read (tk-e78baa38e6a0) made four P2s and one P3 binding on the build. In short:

| Work order | Requirement |
|---|---|
| W5 (facts read) | A deleted message must make the read incomplete: use the store's public completeness reader (`validated_messages_with_problems(since_id=None)`) or its equivalent publication-inventory check, and test a published-but-deleted task opener. |
| W6, W7 (transition, loader) | Specify the final clean-up of a rolled-back transition and its crash recovery; give the lead's `--no-handover` release a way into the queue while another request is pending; say whether a rollback after a model change may resume the old conversation. |
| W6, W11 (records, report) | Keep, per transition, the completeness result, the obligations and the note's identity and check outcome, without note text; detect a lost final append; never certify zero losses over unobserved transitions. |
| W0, W14 (request size) | Keep "not measured" as an explicit exception (this report does). |
| W2, W11 (telemetry, report) | Define the note-cost attribution cases (reasoning tokens, several writes, a last write with no following call, shell writes, repeated events, missing usage); keep B6's two denominators apart; treat the open top bucket of B4 as inconclusive. |

## Limits

- Each probe ran once, on one short turn, with one model, on one Claude Code version (2.1.300) on Windows. The model alias `haiku` was used to keep the cost small; the usage fields are those of the provider's API, but W2's tests must not assume the counts of a larger model.
- (f) was checked by reading the installed program and by reasoning about the other options, not by running an observer, as the order required.
- The tests in (c) are the ones found by searching for the touched functions; the full suite is CI's job on pull request #531.
