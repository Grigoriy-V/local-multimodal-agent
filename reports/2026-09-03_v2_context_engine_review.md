# 4.6a before it starts: what exists, what the references do, what to build

**Date:** 2026-09-03
**Agent:** Claude, direct session
**Status:** analysis and options. Nothing here is approved; `ROADMAP.md` 4.6a
stays "next, not approved" until the human says otherwise.

The question asked: before 4.6a begins, review what is already built against
the architecture the canonical documents fix and against how the reference
harnesses handle context, so the step is built clean the first time.

## 1. What is already there

Read from `app/context/`, `app/agent/graph.py`, `app/agent/runtime.py`,
`app/models/openai_compatible.py`, `app/tools/execution.py`, `app/memory/`.

**The request, layer by layer, in the order sent.**

```text
tools schemas          rendered by the chat template; stable per grant
system core + brief    DEFAULT_SYSTEM_PROMPT + capability_brief; stable per grant
standing instructions  the person's AGENTS.md; changes when they edit it
rolling summary        changes at every fold
retrieved facts        5 by bm25 on the newest user text; changes EVERY turn
stored history         verbatim, media-budgeted (4 images, 1 audio, newest kept)
the current turn       never trimmed, its own images re-sent on every step
```

**Folding.** `fold_older_messages` writes a summary and the position it covers,
never deletes (`DECISIONS.md` 2026-08-30). Two triggers: more than 16 pending
messages, or an estimated request above the budget. The cut lands on a user
turn, keeps the newest 8 messages. Called from two places: `fitted`, before the
model call, from an estimate; and `persist`, after the turn, from the reported
size. `ContextOverflowError` underneath forces a fold and then refuses.

**The budget.** The ceiling is read from `/v1/models` (65,536) and spent at
`AGENT_CONTEXT_FRACTION` 0.8: about 52k tokens. Today's heaviest turn reached
9.4k at step 12. Folding by size has not fired on the deployed profile since the
ceiling was raised; folding by count is what actually runs.

**The estimate.** Characters divided by a ratio calibrated from every reported
`prompt_tokens`, plus a constant per media item. It counts messages only; the
tool schemas and the brief, about 2.5k tokens on a short request (step 1 of
test 7: 2,993 tokens for a two-line ask), are not in the count and are absorbed
into the ratio as if they were text.

**Per-result backstop.** `post_execute` cuts a single result at 32,000
characters, head and 2,000-character tail, and counts image parts. Per-tool
caps exist (`read_file` and `view_pages` 12,000 characters, the browser
snapshot 12,000). No aggregate: twelve results of 10k each are 120k characters
in one turn and nothing objects until the estimate crosses 52k tokens.

**What the model sees of its own turn.** Everything, every step. Test 7:
2,993 → 9,363 input tokens across twelve steps, with the full text of every
`write_file` argument (the model's own 1–2k-character files) and both
screenshots re-sent each time. The prefix cache makes the repeats cheap within
a turn: only the new suffix is prefilled. That is why a 12-step turn costs 137 s
of model time and not several minutes.

**Summarizer.** One call, one instruction: rewrite to at most 150 words of
prose, keep names, decisions, numbers, open questions. No structure.

**Storage.** Schema 2 in both stores. `Message.failure` is checkpointed and
not stored (`DECISIONS.md` 2026-09-03). No record of what a compaction did.

**Assessment.** The bones are right and match the decisions: history canonical,
surface a projection, fold-never-delete, ceiling read not configured, estimate
calibrated not tokenized. What is missing is exactly what the roadmap names:
nothing shortens tool results on the surface, nothing bounds a turn's own
growth except the ceiling, the one volatile layer sits ahead of the stable
bulk, and nothing records what the surface was.

## 2. The measured facts that decide the shape

From `reports/2026-08-29_v2_gpu_baseline_measured.md` and today's runs.

- Prefill is dominant and superlinear: 2,425 tok/s at 853 tokens, 2,084 at
  9,773. A long request is paid in seconds, not only in room.
- The prefix cache is real: 98% reuse on a repeated 3,277-token prefix,
  prefill 1,370 ms → 82 ms.
- Within a turn the prefix is already stable: nothing in the prelude changes
  between steps (the facts query is the newest *user* text). So steps are
  cached today. The cache is lost **between turns**, where the facts change,
  and that loss is the whole history behind them.
- Today's turns are 3k–9k tokens against a 52k budget. 4.6a is not about
  overflow on this hardware; it is about seconds per step and per turn, and
  about a turn that could run to the ceiling once 5 (shell, packages) exists.

So the two levers, in order of measured value: keep the prefix stable across
turns; keep the suffix short across steps.

## 3. What the references do

The three harnesses compared for the tool system
(`reports/2026-09-03_v2_tool_system_references_and_queue.md`) and the shape
Anthropic's own API exposes for context editing. Stated as shapes, not as
endorsements of any code.

| Concern | Reference shape | Ours today |
|---|---|---|
| Old tool results | Cleared or stubbed first, newest N kept verbatim, a placeholder says what was there. Summarization only after that. | Nothing until a fold; the fold summarizes everything past the window at once |
| Per-result bound | Per-tool cap, head/marker/tail, full text kept somewhere retrievable (spill file or log) | Per-tool caps and the 32k backstop; full text in history |
| Aggregate bound | A share of the window per turn (Hermes 200k chars, OpenClaw a fraction) | None |
| Trigger | A threshold on measured input tokens, often with hysteresis | Count of messages, or estimate above 0.8 of ceiling |
| Summary | A structured prompt: goal, what was done, files touched, decisions, next; the last user turn kept verbatim | 150 words of prose |
| Record | The compaction and what it covered are logged; the transcript survives | Summary + position stored; no record of stubbing, no `failure` column |
| Cache | Stable prefix, volatile material appended last | Facts ahead of history |
| Loop guard after compaction | OpenClaw aborts when compaction did not break a loop | ISS-0019 today; 4.7 |

Two of the reference ideas do **not** fit here and should stay out:

- **Spill files.** The full result is already canonical in history and 4.6b
  recovers it by search. A second copy on disk is a second source of truth.
- **A separate summarizer model or a tokenizer in the application.**
  `DECISIONS.md` forbids provider-specific tokenizers; the calibrated estimate
  is within a few percent and the fraction absorbs the rest.

## 4. The engine, as a small design

One function, run before every model step, that turns canonical history plus
the current turn into the surface, and records what it did. It replaces the
two fold call sites with one place.

```text
prepare(state) -> Context
  1. assemble  system, instructions, summary, history, turn, facts  (facts LAST)
  2. measure   estimate per layer; schemas counted explicitly, once per toolbox
  3. stub      tool results outside the newest K steps -> one-line stubs
               images outside the media budget -> placeholders (turn included)
  4. summarize only if still above budget: fold history to a user boundary
  5. record    trace event with per-layer sizes and what was stubbed;
               a durable compaction row when a fold happened
```

**Step 1, order.** Facts go after history, immediately before the current
turn. The model reads them just before the question they were retrieved for,
which is also where they are most useful. Everything ahead of them is now
stable between turns and the prefix survives. Acceptance is the roadmap's own:
a warm repeat turn shows `cached_tokens` close to the previous request's size.
vLLM reports `prompt_tokens_details.cached_tokens` in usage; the client does
not read it yet, and reading it is the measurement for free.

**Step 3, stubbing.** A projection-only rule; history is untouched. A tool
result older than the newest K steps of the current turn, or in any previous
turn, becomes:

```text
[read_file notes.txt: 3,412 characters, shortened; call the tool again for the full text]
```

The stub names the tool, the path or argument that identifies it, the size,
and the way back. This is the head/marker/tail idea reduced to its marker,
because our results are small and the assistant's own following message
already says what it made of them. K is a policy number with a default of 2
and a measured reason to move it. The turn's own images join the media
budget: the newest survive, older ones become the same placeholder history
already uses.

What stubbing does to today's failures: test 7's twelve steps carried every
earlier `write_file` argument verbatim; stubbed, the suffix stays around the
last two results and the request stops growing by 600 tokens a step.

**Step 4, summary.** Only when stubbing was not enough, which on this hardware
means long conversations, not long turns. The instruction becomes structured:
what the person wants, what has been done, files and paths named, decisions,
what is open. The newest user turn is never folded. Same one call, same store
contract, same position semantics.

**Step 5, record.** `context_prepared` on the trace with the layer sizes,
stub count and cached tokens, every step. A `compactions` row in the store
when a fold happens: thread, covered-through, summary length, the trigger.
That row is what 4.6b reads; without it there is nothing to recover from.

**The person's context size, and two commands** (asked for on 2026-09-03).
`/context` answers without the model: the last request by layer — core and
schemas, instructions, summary, facts, history, the current turn — how much
of it came from the cache, and the chosen size against the ceiling. It is
the `context_prepared` event shown to a person. `/compact` forces a fold
now, one summarizer call, and answers with what was folded into how many
words; it wakes the model, which by a direct command is fine.
`/context small|normal|large` sets the size: a user-state value read by
`Agent.budget`, shown as a trade in the engine's real numbers ("small keeps
about 4 turns verbatim and costs less per message"). Not a setting file,
not a deploy. Belongs here because before the engine the number changed
nothing.

## 5. Schema 3, once

One migration, one gate on the populated Neon database, carrying everything
that has been waiting for it:

- `messages.failure` (the tool system's typed outcome, checkpointed today)
- `compactions` (thread, through, trigger, summary length, created)
- user-state key for the chosen context size (no schema change, listed for
  completeness)

SQLite and Postgres move together; the `ConversationStore` contract suite is
the check. Tests keep using temporary databases.

## 6. Drift found during the review

Not defects, but things the step should settle rather than inherit.

- **Two fold sites.** `fitted` before the call and `persist` after it call the
  same function on different measurements. The engine leaves one.
- **The estimate skips the schemas.** About 2.5k tokens counted as a lower
  ratio instead of as tokens. Count them once per toolbox and the ratio stops
  absorbing them.
- **The turn's images are outside the media budget.** Two screenshots re-sent
  on every step of test 8 at ~320 tokens each. Small, and wrong in principle.
- **`facts` are retrieved on the newest user text only.** Fine for the order
  change; a later question is whether the assistant's own last message should
  join the query. Not 4.6a.

## 7. What 4.6a should not become

- No spill store, no vector store, no second model, no tokenizer.
- No rewriting of stored history, ever; the stub is on the surface only.
- No per-tool "importance" heuristics: the rule is age and size, nothing else,
  so it can be explained in one sentence and measured in one number.
- No fold triggered by wording or by what the model seems to be doing.

## 8. Order of work, if approved

1. Read `cached_tokens` from usage into the trace; add `context_prepared` with
   per-layer estimates. Measure a warm repeat turn as the "before". No gate.
2. Move facts last. Measure the same turn again. This alone is the roadmap's
   acceptance for cache-friendly assembly.
3. Stub old tool results and budget the turn's images. Offline tests on the
   projection; one live turn of the Task Board request to compare step sizes
   against test 8.
4. Structured summary instruction; `compactions` record; schema 3 migration
   prepared and run on the local profile. **Gate:** the Neon migration.
5. `/context` and `/compact` in Telegram, budget from user state.
6. Live: a long conversation that folds, and a turn that stubs, both read back
   through `tools/show_run.py`.

Each of 1–3 is small and independently measurable; 4 is the one with a gate;
5 is product and last. 4.6b follows on the record 4 leaves.

## Built, 2026-09-03

Approved in the human's word the same afternoon and built in this order, with
one change to it: the commands (5) went out with 1–3 because they need no
schema, and the summary and the record (4) wait in the tree for the gate.

**Deployed (`0ce9e0a`).**

- `Usage.cached_tokens` from `prompt_tokens_details`; `model_finished`
  carries it; `tools/show_run.py` prints `cached N` per call.
- `context_prepared` before every model step: estimated tokens for schemas,
  prelude, history, facts and turn, plus how many results were stubbed and
  how many pictures became placeholders. The schemas are now counted in the
  fold's estimate too, once per graph, instead of being absorbed into the
  characters-per-token ratio.
- `Context.surface`: facts after history; `shortened` stubs tool results
  older than the newest `keep_results` (two) and the long string arguments
  of the calls that produced them, failures and short results untouched;
  one media budget across history and the current turn, newest kept.
  Everything is projection: the store and the checkpoint keep the whole
  messages. `AGENT_KEEP_RESULTS` is the setting.
- `/context`: the next request by layer, the last request's count and cache
  hits, the size against the ceiling when the worker has already read it.
  `/context small|normal|large` writes `.agent/context`; `Agent.budget`
  reads it. `/compact` folds now and says how many messages it covered.

**Deployed after the gate, the same day.** The human said the word; the
migration ran against Neon in one call (version 2 → 3, `failure` column and
`compactions` table added, 854 messages untouched, verified by reading the
schema back), and `75245bc` was deployed.

- The summary instruction is four sections — Goal, Done, Open,
  Preferences — at most 200 words, names kept exactly.
- Every fold records a `Compaction` (through, folded, trigger, summary
  chars); `/compact` records `asked`. `messages.failure` is stored. Schema 3
  in both stores, additive, contract-tested; the version-0 file migrates
  through it.

**Not done.** The live numbers. Both acceptances need the human's own turns:
a repeat question in one thread to read `cached_tokens` against the previous
request's size, and the Task Board request to compare step sizes with test
8, where the request grew by roughly 600 tokens a step. `ROADMAP.md` 4.6a
carries the gate and the acceptance.
