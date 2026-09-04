# The whole code, reviewed against the references and the product

Date: 2026-09-03. Direct Claude session, after 4.6b closed. Read in full:
`app/agent/*`, `app/tools/*`, `app/models/*`, `app/context/*`, `app/memory/*`,
`app/web.py`, `app/capabilities.py`, `app/config.py`, `app/attachments.py`,
`app/documents.py`, `app/preflight.py`, `app/instructions.py`,
`app/checkpoints.py`, `app/telemetry/{trace,base}.py`, `ui/telegram/*`,
`ui/chainlit_app.py`, `deploy/modal/*`. About 17k lines of application code,
1007 offline tests. Nothing here is approved; every item is an option with a
size, for the human to pick from. Referenced as shapes: Claude Code, Codex
CLI, OpenClaw, Hermes Agent, DeepSeek's harness and Anthropic's API, as read
for `reports/2026-09-03_v2_tool_system_references_and_queue.md` and the two
4.6 reviews. Where a reference detail is from memory it says *(recalled)*.

## 1. What holds up

Said first because it decides what the rest is measured against.

- **The loop is one loop** (`app/agent/graph.py`): four nodes, budget in
  three units, a stop read between steps, a repeat-failure guard, a
  delivery that runs past the ceiling, an overflow path that folds and
  retries once. Every one of those came from a live failure with a run id
  next to it. The references have the same pieces; none of them has fewer.
- **The tool seam is typed** (`app/tools/execution.py`, `base.py`): one
  lifecycle, one `ToolOutcome`, failure codes a reader groups by, a
  sanitized failure text, a per-result backstop, coercion for what
  open-weight models get wrong. This is the DeepSeek/OpenClaw shape and it
  is cleaner than either.
- **History is canonical and the surface is a projection**
  (`app/context/window.py`, `DECISIONS.md` 2026-08-30): folding never
  deletes, stubbing never writes back, and since today the way back is a
  position. Anthropic's context editing and Claude Code's compaction are
  both lossy on the transcript; this is not.
- **The web boundary is right** (`app/web.py`): resolved-address pinning
  with `Host` and SNI kept, every redirect re-checked, ports 80/443 only,
  the browser's every request through the same policy, and the one thing it
  cannot close (Chromium's own resolver) named and moved to a container
  that holds nothing. Few personal-assistant harnesses do the pinning at
  all.
- **The deployed control plane** (`ui/telegram/{inbox,webhook}.py`,
  `deploy/modal/control_app.py`): durable inbox, per-conversation lease with
  an advisory lock, control lane for `/stop`, drain with hand-off, abandon
  after three attempts, the GPU woken in parallel with the write. Measured
  cold starts in the comments. This is more careful than a personal bot
  needs and it is why the live tests today were about the model, not the
  transport.
- **Telemetry that never fails a turn**, with per-layer context sizes and a
  reader (`tools/show_run.py`) that made every diagnosis today a one-minute
  read.
- **The product principle is visibly enforced**: the capability brief is
  generated from wiring, `/can` and `/check` read the same registry,
  observation and presentation are different tools, the UI decides nothing.

## 2. Findings, ranked by what they cost the product

Each: where, what, why it matters, what the references do, the smallest
fix, its size. Severity is about the person's experience, not code taste.

### 2.1 The summarizer is fed whole tool results — and can overflow

`app/context/summary.py` `summarize()` → `transcript(pending[:cut])` in
`window.py` renders every part with `describe(part)`: the full text of every
tool result, up to the 32k backstop each. A fold of twelve messages holding
three page fetches is ~100k characters, ~30k tokens, sent to the summarizer
whole. Two consequences. The summary call is the most expensive prefill of
the conversation and it is spent on text the summary needs a sentence of.
And in `persist()` (`graph.py`) and in `fitted()` the fold is **not**
wrapped for `ContextOverflowError`: a summarizer request that does not fit
raises out of the node — after the answer was already streamed, so the
person sees the answer and then "That request failed: ContextOverflowError".
Only the overflow-recovery branch of `_ask` catches it.

References: Claude Code and Anthropic's context editing clear or truncate
tool results *before* the summary sees them; Hermes summarizes over its
already-pruned view *(recalled)*.

Fix: summarize the **surface**, not the history — run `pending[:cut]`
through `shortened(…, keep=0)` (every result a stub, failures kept) before
`transcript`, or cap each result to ~1,500 characters in `transcript`. And
catch `ContextOverflowError` around the two unguarded folds, logging a
trace event and leaving the summary as it was. Size: ~20 lines, two tests.
**Highest value per line in this review.**

### 2.2 Folding by count is premature, and every fold is a rewrite

`ContextPolicy.summarize_after=16, keep_recent=8`: the conversation folds
every ~12 messages whatever their size. The human's session today folded
four times in sixteen turns with requests at 4–10k tokens in a 52k budget.
Each fold is a model call, invalidates the served prefix cache for
everything after the summary, and rewrites the summary from the previous
summary — compounding loss; "сова" survived, a file's exact name or an
error's wording is what goes next.

References fold by size only: Claude Code at a high fraction of the window,
Codex the same, OpenClaw by token threshold with hysteresis *(recalled)*.
None folds on a message count.

Fix: make the count trigger a fallback (e.g. 80 messages) and let the size
trigger — already exact from `usage.input_tokens`, already estimated before
each step — drive folding, with `/compact` for the person. Size: one number
and the tests that assert the count. Watch: the first long conversation
after the change, read through `/context`.

### 2.3 A tool call cut by `max_tokens` is reported as the model's error

`ModelSettings.max_tokens=4096` bounds output; a `write_file` of a 15k
character page is ~5k tokens and is cut. The stream ends with
`finish_reason="length"`, the argument JSON is unterminated, `read_arguments`
returns `None`, and the executor tells the model "bad arguments … could not
be read as a JSON object" (`execution.py` `pre_execute`). Nothing in
`graph.py` or the backend looks at `finish_reason`. The model is told it
wrote bad JSON when the server stopped it mid-word, and its natural retry
is the same file again, cut again — the shape of ISS-0019's rewrite loop
with a different cause. Not yet seen live because today's files were under
the cap; the Task Board with three files is close.

References: every harness surfaces `stop_reason`/`finish_reason="length"`
to the model as its own message (Claude Code: "output truncated"; OpenClaw
*(recalled)* re-asks with a continuation).

Fix: in `readable()`/`parse_completion`, when `finish_reason == "length"`
and a call is unreadable, name the cause in the refusal ("the answer was
cut at the output limit of N tokens; write the file in smaller pieces with
edit_file, or shorten it") and set a distinct code. Consider `max_tokens`
8192: the ceiling is 64k and output is cheap next to prefill. Size: ~15
lines, one test.

### 2.4 The repeat guard only sees failures; the rewrite loop is successes

`failed_before()` counts identical *failed* calls. The most expensive loop
seen live (ISS-0019, run `9c42241c`: the same page written seven times, each
a full generation) was identical *successful* calls. `unchanged:` in
`write_file` softened it and the after-deploy runs show 3 writes now, but
nothing bounds it.

References: OpenClaw's loop detection counts identical tool calls whatever
the result, with a warning at N and a stop at M *(recalled)*; DeepSeek's
`repeat-tool-reminder` injects a reminder on repeats.

Fix: a second, gentler guard in `run_tools`: the third identical successful
call in one turn gets a `not_run` result saying "already done with exactly
these arguments; the file is as you wrote it — move on or change it". Same
identity function, one more counter. Size: ~20 lines, one test. Cheaper
than a steering objection and it does not read the answer.

### 2.5 No tool has a timeout; the executor's deadline is unused

`Tool.timeout_seconds` exists and nothing sets it (`grep timeout_seconds=`
finds no tool). Web tools carry their own httpx deadlines and the browser
its own, but `read_document` on a 20 MB PDF, `view_pages`, `search_history`
on a slow database and every filesystem call run on the event loop with no
bound. The turn's `max_seconds` is only read at step boundaries, so a tool
that hangs hangs the worker until Modal's 600 s kill — which the inbox then
sees as a dead lease 300 s later (2.7).

References: Claude Code and Hermes give every tool a default timeout;
DeepSeek's pipeline has a per-tool deadline in the executor, which is the
shape this code already has.

Fix: a default in `Tool` (say 60 s) and explicit longer values on the
browser and document tools; sync tools then run in a worker thread, which
also stops a PDF parse from blocking the streaming preview. Size: one
default, four numbers, one test. Check the `asyncio.to_thread` path with
the SQLite store (it is `check_same_thread=False`, so fine).

### 2.6 Facts cannot be corrected or forgotten

`remember_fact` appends; nothing deletes, edits or lists. A wrong fact —
"the secret word is сова" after it changed — is retrieved on every matching
turn for ever, and the person has no `/memory` to see what is held. The
decision of 2026-08-01 (explicit save) is right and does not need
reopening; it just has no other half.

References: Anthropic's memory tool has view/create/str_replace/delete;
Claude Code's memory is files the person can open; OpenClaw's `MEMORY.md`
is editable by both.

Fix: `forget_fact(text)` for the model (exact match, refuses ambiguity like
`edit_file` does) and `/memory` in Telegram to list and delete by number,
model-free. Size: one store method on the contract (both backends), one
tool, one command, tests. The store already has `facts(user_id)`.

### 2.7 A worker's lease outlives its own kill by five minutes

`claim(..., lease_seconds=900)` while the worker's Modal `timeout=600` and a
turn's `max_seconds=300`. A container killed mid-turn leaves `running` with
a live lease until 900 s after the claim; `_busy` and the claim both refuse
the conversation until then. Rare (a crash), but the symptom is the worst
kind — the person's next messages are silently queued for up to fifteen
minutes with no reply — and the fix is arithmetic.

Fix: `lease_seconds` = turn ceiling + margin (e.g. 420 s), or renew the
lease at each step through the trace's `loop_step`. The first is one
number. Size: trivial; one contract test asserting the ordering
`turn_max_seconds < lease < worker timeout`.

### 2.8 The consent-resume path has drifted from the answer path

`TelegramAdapter._on_callback` re-implements the event loop of `_answer`:
preview, activity, deliver, and today the fold notice — but not the
`delivered` set that drops the model's verbatim repeat (ISS-0009's
mitigation), and it discards a withdrawn draft where `_answer` holds it.
Two copies of one loop, already unequal.

Fix: one `_drive(agent_events, chat_id, …)` used by both; the callback
branch adds `_settle` on the first event. Size: a refactor of ~60 lines
with no behaviour change except the two omissions closing. The 105 adapter
tests carry it.

### 2.9 A transient failure before the first token fails the turn

`OpenAICompatibleBackend.stream()`: "a failure before the first delta could
be retried safely, and is not, for now". `invoke()` retries 408/429/5xx with
backoff; the streamed path — which is every conversational call — retries
nothing. A 503 from a proxy while the GPU wakes is a failed turn with an
error message in the chat.

Fix: retry the stream on `TRANSIENT_STATUS` while no `TextDelta` has been
yielded, with the same backoff; a failure after the first delta stays a
failure. Size: ~20 lines, two tests with a scripted transport.

### 2.10 Error text reaches the person unfiltered

`handle_update` sends `f"That request failed: {type}: {error}"`. A
`BackendError` carries the model endpoint URL and the server's response
body; a `psycopg` error can carry the host. For the owner this is useful;
under `open_access` it is infrastructure detail handed to strangers, and it
is also the only place the product speaks in tracebacks.

Fix: a short mapping — endpoint unreachable, model refused, database
unavailable, something else — with the type kept and the text logged, not
sent. Size: ~15 lines.

### 2.11 Evidence before claims: the harness can catch one case for free

ISS-0004 (a page described without a fetch) and ISS-0028 ("I checked my
memory" with no call) are the model's; 4.9 owns them and prompt wording
has not moved them. One sub-case is detectable without reading the answer:
**the person's message contains a URL and the turn made no tool call.**
That is a fact about the turn, not about the wording, and the steering
seam (`app/agent/stopping.py`) exists for exactly this — an objection at
the ending, once, with a way out: "the message contains an address you did
not open: open it with fetch_page, or say plainly that you did not read it."
It chooses no tool and encodes no workflow; it refuses one ending that
ignores evidence, the same way `FinishesItsOwnList` refuses one that
ignores the plan.

Fix: `AnswersWhatItWasHanded` as a `TurnStopping`, limit 1, composed with
the todo one. Measured on the two runs of today (`45f78d7e` would have been
sent back once). Size: ~40 lines, three tests; belongs to 4.9 and needs a
live run to accept.

### 2.12 Tool calls run one after another

`run_tools` awaits each call in order. When the model does emit several —
three `fetch_page`, or `inspect_page` plus a read — the second waits for
the first. Claude Code runs read-only tools of one batch concurrently;
Codex the same for reads. Here the served model mostly emits one call per
step, so the gain is small today and grows with a better model.

Fix: `Tool.parallel: bool` on the read-only tools and `asyncio.gather` over
the safe prefix of a batch, results kept in call order. Size: ~25 lines,
one test. Low priority; note it for when the model changes.

### 2.13 Small things, each a few lines

- `validation_error` ignores `enum`, `minimum`, `maximum` and array `items`;
  the schemas promise them and the tools re-check by hand. Either enforce
  the four keywords or stop declaring what is not checked.
- `Toolbox.resolve` strips one prefix; fine. `LEGACY_NAMES` is empty and
  documented as a place; fine.
- `adapter.allows` and `ui/telegram/run.py` say open-access accounts "share
  one workspace"; `user_workspace` gives each their own since the volume
  landed. Stale wording in two places.
- `ModelSettings.temperature=0.0`: every identical retry is identical.
  Consider a small temperature on the second attempt of the same call, or
  leave it and rely on the guards — a choice to record, not a bug.
- `MEDIA_TOKENS["audio"]=1500` is a guess named as one; the calibration
  skips media requests, so a voice-heavy conversation is estimated blind.
  Read one real audio request's `prompt_tokens` and set it.
- No CI: 1007 tests run only when someone runs them. A workflow that runs
  the offline suite on push costs nothing and would have caught nothing
  today, but the day it matters it will.
- `scripts/v1_live.py`, `scripts/stage3_live.py`, `tools/vllm_baseline.py`,
  `tools/prompt_scenarios.py`: Version 1 scripts still in the tree. Keep
  or move under `scripts/legacy/`; today they are read by a newcomer as
  current entry points.
- `MODEL_FREE_COMMANDS` and the adapter's dispatch are kept equal by a
  test; good. `/compact` is not in the set on purpose; documented.
- `context_report` estimates schemas by `json.dumps`; the template renders
  them differently. It is an estimate and says so; fine.

## 3. Against the references, in one table

| Concern | Claude Code / Codex | OpenClaw / Hermes / DeepSeek | Here |
|---|---|---|---|
| Loop bound | steps, tokens, permission modes | steps, time, loop detection | steps, tool calls, seconds; delivery past the ceiling ✔ |
| Repeats | — | identical-call detection incl. successes | failures only (2.4) |
| Tool outcome | typed, `is_error` | typed union, sanitized | typed union, codes, sanitized ✔ |
| Timeouts | per tool default | per tool | field exists, unused (2.5) |
| Parallel tools | read-only in parallel | — | serial (2.12) |
| Context | compact at threshold, clear old results | prune, spill, threshold | stub by age, fold by size **and count** (2.2), summary over full results (2.1) |
| Recovery of detail | transcript on disk, no tool | spill locator / session search | `search_history`, `read_history`, positions in stubs ✔ |
| Memory | files the person edits | editable file + search | append-only facts, no delete (2.6) |
| Truncated output | surfaced to the model | surfaced | not read (2.3) |
| Web safety | domain allowlist, sandbox | — | pinned resolution, re-checked redirects, isolated renderer ✔ |
| Sandbox / shell | yes, central | yes | not yet (roadmap 5) |
| Transport | terminal | gateway / bot | durable inbox, leases, control lane ✔ |
| Observability | OpenTelemetry hooks | logs | per-turn trace with layer sizes ✔ |

The largest product gap against the references is not on this list of
findings: **no execution capability** (roadmap item 5). Without a shell or
Python the assistant cannot run what it wrote, produce a PDF, or check a
number. Everything above it is polish next to that, and the roadmap already
has it in the right place.

## 4. What I would do, in order, if asked

1. **2.1 + 2.2 together** — summarize the surface, guard the fold, fold by
   size. One afternoon, offline tests, one live conversation read through
   `/context`. Changes what every long conversation costs and remembers.
2. **2.3 + 2.4** — the two ways a write loop starts: name the output cut,
   bound identical successes. Small; both have run ids to test against.
3. **2.5 + 2.7 + 2.9** — the three timeouts and the retry: robustness of the
   deployed profile on a bad day. Small each.
4. **2.8 + 2.10** — one adapter loop, one error voice. Refactor and wording.
5. **2.6** — `forget_fact` and `/memory`. A schema-free change, both stores.
6. **2.11** — the URL objection, as the first piece of 4.9 that is not
   prompt wording; accepted by a live run.
7. 2.12 and 2.13 as they come up.

None of these needs a migration or a gate beyond the usual deploy; 2.3's
`max_tokens` change is a model-request setting, not a redeploy of the model
app. Items 1–4 are each "small" in `AGENTS.md`'s sense; 5 and 6 are a step's
worth of work with a live acceptance.

## 5. What this review did not do

No code changed. No worker, endpoint or GPU was started. The references
were not re-read today; their shapes are as recorded in the two earlier
reports and marked where recalled. The Chainlit path was read, not run.
Postgres-specific paths were read against the contract suite, which runs on
SQLite here.

## Built, 2026-09-04: items 1 and 2 of §4

After the human's "да" and "заканчивай 1 и 2 пункт и всё":

- **2.1** `summarize()` reads `shortened(messages, keep=0)` — every tool
  result a stub with its stored position — and the instruction's word cap is
  `150 + 15 × messages`, at most 600, so a fold by size that covers forty
  messages is not asked to fit them into two hundred words. Both folds
  (`fitted`, `persist`) catch `BackendError`, record `context_fold_failed`
  and go on; a delivered answer is never followed by a failure.
- **2.2** `summarize_after` 16 → 60 in `ContextPolicy` and `AgentSettings`,
  a fallback for a server that reports no window; folding is by size, as
  the 2026-09-03 decision already said.
- **2.3** `ToolCall.cut`, set by `readable()` when `finish_reason ==
  "length"` and the arguments could not be read; `pre_execute` refuses such a
  call as `output_cut` — "your answer was cut at the output limit before the
  arguments ended … send it in smaller pieces". `MODEL_MAX_TOKENS` default
  4096 → 8192.
- **2.4** `succeeded_before` beside `failed_before`: the third identical
  successful call of a turn is answered `not_run` ("already succeeded twice
  … the earlier result stands") without running, and the turn goes on. A
  model that keeps sending it then meets the failure guard two halts later,
  which ends the turn — the cascade is deliberate.

Tests: eleven new; the offline suite green (count in the commit). Not done
here: 2.5–2.13, by the human's word; the live check is the after-deploy run.
