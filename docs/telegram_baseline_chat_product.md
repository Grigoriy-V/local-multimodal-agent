# Telegram Baseline Chat Product — UX / Rich Text / Streaming

## Purpose

This document defines the desired shape of **ROADMAP queue item 2: Baseline chat product and live evidence**.

The goal of this item is to make the Telegram interface feel like a normal, readable assistant product before deeper harness work begins.

This is primarily a **Telegram UX / presentation task**, not a new agent architecture. Do not move product decisions into Telegram that belong to the agent, and do not create new general abstractions unless the existing boundaries cannot support the requirement.

Implementation still follows `AGENTS.md`, `ROADMAP.md`, the four canonical docs, and normal human gates.

---

## Product outcome

A person opens the Telegram bot and immediately understands:

- what the assistant is;
- that they can simply talk to it in natural language;
- which small set of commands exists;
- that answers are formatted cleanly;
- that code, lists, emphasis, quotes and links are readable;
- that longer responses feel responsive rather than dead;
- that plans/results from autonomous work are readable.

The Telegram UI should not expose internal distinctions such as “chat mode”, “agent mode”, tool selection, or workflow selection.

---

# 1. Telegram command shell

## Desired behavior

Use Telegram’s native bot command/menu surface rather than inventing a custom command UI.

The visible product commands should be approximately:

```text
/new   — start a new conversation
/can   — show currently available capabilities
/stop  — stop the current task
/help  — show help
```

`/check` should remain available as a diagnostic command, but it does not need to be a primary user-facing menu item.

The current command owners are already in:

- `ui/telegram/adapter.py`
- `ui/telegram/api.py`
- `tools/telegram_webhook.py`

Do not create another command registry/service unless the existing ownership cannot support native Telegram command registration cleanly.

## `/start`

`/start` should send one concise onboarding message.

It should explain, in user-facing language:

- this is a personal multimodal assistant;
- the user can talk normally;
- images, voice and supported documents may be sent;
- the assistant may use tools or perform longer work when needed;
- consequential actions require approval;
- the main commands.

Do **not** dump the internal tool inventory into `/start`. `/can` already exists for truthful runtime capability reporting.

`/help` may reuse the same content or a slightly more command-oriented version.

---

# 2. Canonical answer format: ordinary Markdown

## Decision

The assistant should continue to produce **ordinary Markdown-style text** as its canonical textual answer format.

Plain prose is simply Markdown with no markup.

The model should not be prompted to emit Telegram-specific MarkdownV2 or Telegram HTML.

Examples of normal model output:

```md
## Основные моменты

1. **Cordis** — основной framework.
2. **Profiles** — композиции bundles.

Пример:

~~~python
print("hello")
~~~
```

This same conceptual answer should remain usable by any interface.

---

# 3. Telegram owns rendering, not content semantics

Telegram should render the model’s ordinary Markdown into a **safe Telegram-native representation**.

Preferred conceptual flow:

```text
assistant text
    ↓
ordinary Markdown
    ↓
Telegram renderer
    ↓
safe Telegram HTML/entities
    ↓
sendMessage
```

This rendering belongs in the Telegram interface layer.

Do not put Telegram markup rules into:

- the model system prompt;
- `Message` / `ContentPart`;
- the agent graph;
- the task runtime;
- persistence.

The persisted assistant text should remain the canonical model text, not a Telegram-transformed copy.

---

# 4. Supported rich-text subset

The first version does **not** need a complete CommonMark implementation.

Support only the structures that materially improve assistant UX:

- bold;
- italic;
- headings;
- inline code;
- fenced code blocks;
- ordered and unordered lists;
- block quotes;
- links.

Anything unsupported should degrade into readable text rather than fail the answer.

Tables, deeply nested Markdown, custom HTML, unusual extensions and perfect CommonMark compatibility are explicitly not required for this baseline.

---

# 5. Safety / degradation rule

Formatting is presentation polish. It must never become a new failure mode for the assistant.

Required invariant:

```text
valid render
→ send formatted message

renderer/parser failure
or unsafe/unbalanced output
or formatting cannot survive splitting
→ send readable plain text
```

A model response must not be lost because of malformed Markdown or Telegram parser rejection.

The current code already follows this philosophy for project-authored `Formatted` messages: model-derived bodies are escaped and overly long formatted messages fall back to plain text.

Relevant current owners:

- `ui/telegram/api.py`
  - `Formatted`
  - `TelegramClient.send_message`
  - `_render`
  - `split_message`
- `ui/telegram/adapter.py`
  - normal assistant delivery
  - task plan/result presentation

Extend/reuse these owners rather than creating a second Telegram rendering path.

---

# 6. Existing `Formatted` messages

Task plans and task results already have structured Telegram formatting through `Formatted`.

Preserve this behavior.

The new ordinary Markdown renderer should not make task-specific structured output less reliable.

A simple implementation may keep both concepts:

```text
project-authored structured UI text
→ Formatted

model-authored ordinary answer
→ Markdown renderer → Telegram-safe format
```

Do not force these into one abstraction unless doing so is clearly simpler.

---

# 7. Long-message behavior

Telegram has message-size limits. Rich text must remain correct when a response is long.

The implementation should prefer readable boundaries when splitting:

1. paragraph / line break;
2. whitespace;
3. hard cut only as a last resort.

Do not split in a way that causes Telegram markup to become invalid.

Acceptable baseline strategies include:

- render each independently safe chunk;
- or fall back to plain text when a formatted answer cannot be split safely.

Correctness and delivery are more important than preserving every formatting token.

---

# 8. Streaming is part of the product baseline, but a separate sub-step

## Important distinction

There are two different problems:

### Telegram display streaming

Telegram can show an updating/draft message while the answer is being generated.

This is primarily interface work.

### Correct agent-runtime streaming

The current agent path is not yet a true streaming execution path.

Current facts:

- `ModelBackend.stream()` yields only text chunks;
- the current OpenAI-compatible streaming parser extracts text delta content;
- streamed tool-call deltas and final usage are not part of that contract;
- the ordinary agent graph currently uses `backend.invoke()` and receives a complete `Completion`;
- tool decisions therefore happen after a complete model result.

Relevant owners:

- `app/models/base.py`
  - `ModelBackend.stream`
  - `Completion`
- `app/models/openai_compatible.py`
  - streaming request/parsing
- `app/agent/graph.py`
  - current `backend.invoke()` loop
- `ui/telegram/api.py`
  - Telegram send/edit/draft transport
- `ui/telegram/adapter.py`
  - UI delivery

## Requirement

Do **not** implement fake streaming by bypassing the agent graph and calling the backend directly from Telegram.

The final architecture must preserve:

- tool calls;
- tool results;
- usage;
- finish reason;
- persistence;
- approvals;
- the same final assistant `Message`;
- the same agent loop semantics as non-streaming execution.

Streaming is presentation of an existing execution, not a parallel Telegram-only inference path.

---

# 9. Suggested implementation order

## 2A — Telegram UX baseline

Implement first:

1. native Telegram command menu;
2. concise `/start` / `/help`;
3. ordinary Markdown → safe Telegram rendering;
4. safe fallback to plain text;
5. readable long-message handling;
6. preserve existing task plan/result formatting;
7. live UX acceptance.

This should remain mostly inside `ui/telegram/` and existing operational Telegram setup.

## 2B — Real answer streaming

Then design/implement streaming through the normal runtime.

Desired conceptual behavior:

```text
turn starts
    ↓
Telegram typing indicator while no answer text exists
    ↓
first assistant text delta
    ↓
draft/update visible message
    ↓
more deltas
    ↓
tool call may interrupt textual answer
    ↓
tool execution / subsequent model step
    ↓
final answer
    ↓
final normal Telegram message
    ↓
canonical final Message persisted normally
```

The user should never receive a final answer that disagrees with the persisted assistant result.

---

# 10. Streaming UX constraints

Streaming does not need token-by-token UI updates.

Prefer throttled/coalesced updates to avoid excessive Telegram API calls.

For example, update when either:

- enough new text accumulated; or
- a short time interval elapsed.

Exact cadence should be chosen empirically and kept simple.

While the model is cold-starting or no textual output exists yet, retain the existing Telegram `typing…` indicator.

Do not add Telegram stop-generation support in this baseline unless separately justified. Existing `/stop` semantics and future streaming cancellation are different control paths.

---

# 11. Architecture boundary

This item should **not** become a general presentation framework.

Current intended ownership:

```text
agent/runtime
    owns semantic answer and tool behavior

Message / ContentPart
    owns interface-neutral domain content

Telegram adapter/API
    owns Telegram rendering and Telegram UX

Chainlit
    keeps its own rendering behavior
```

The main product rule remains:

> The model decides what to say. The interface decides how to render that same semantic content on its platform.

Do not make the adapter decide which internal evidence should be exposed to the user. Observation versus explicit presentation remains unchanged.

---

# 12. Acceptance criteria

## Command / onboarding

- Telegram exposes the intended command list through the native bot menu.
- `/start` gives a short useful onboarding message.
- `/help` clearly explains commands.
- `/can` remains the truthful capability source.
- `/check` remains available for diagnostics without becoming prominent product UI.

## Rich text

A normal model response containing all of the following renders readably:

- plain paragraphs;
- bold;
- italic;
- heading;
- ordered list;
- unordered list;
- inline code;
- fenced code block;
- quote;
- link.

A malformed or unsupported Markdown response is still delivered as readable text.

A long response is delivered fully without Telegram parse failures.

## Task UX

- existing task plan approval remains readable;
- existing task result/check presentation remains readable;
- approval buttons still attach to the intended final message.

## Streaming

When streaming is implemented:

- text becomes visible before full generation finishes;
- tool-capable turns still work;
- tool calls are not lost;
- usage/final completion data remain available;
- the persisted final assistant message matches the completed answer;
- Telegram transport does not bypass the normal agent runtime;
- a stream failure does not create a false successful final answer.

---

# 13. Live evidence for queue closure

The live Telegram acceptance should be small and product-facing.

Suggested scenarios:

### Scenario A — onboarding

Fresh/open bot:

- command menu is visible;
- `/start` is readable and concise.

### Scenario B — formatting

Ask for an answer that naturally contains:

- a heading;
- a numbered list;
- bold emphasis;
- inline code;
- one code block.

Verify visually in Telegram that no raw `**`, broken fences, or parse errors remain unless intentionally shown as code.

### Scenario C — capability truth

Ask the assistant in natural language what it can do.

Compare against `/can`.

The two do not need identical wording, but they must not materially contradict each other.

### Scenario D — ordinary tool-capable answer

Use a normal request that causes a tool call and then a final textual answer.

Verify that presentation remains readable and no tool/result semantics are broken.

### Scenario E — streaming, once implemented

Use one sufficiently long answer.

Verify:

- `typing…` covers initial waiting;
- draft text appears during generation;
- final message replaces/completes the draft cleanly;
- no duplicated answer;
- formatting is correct in the final message.

One warm live run may exercise several of these together where practical.

---

# 14. Explicit non-goals for this item

Do not use this queue item to redesign:

- `GeneralHarness`;
- task planning architecture;
- session event storage;
- subagents;
- sandbox execution;
- permission model;
- conversation serialization;
- general UI abstraction across all platforms.

If correct streaming exposes a small necessary runtime seam, change only what is needed to support the same agent execution with incremental output.

Deeper harness redesign belongs to the later harness/loop roadmap item after baseline observability exists.

---

# Desired result

After this item, Telegram should feel like a real assistant rather than a debug transport:

```text
native commands
+ concise onboarding
+ readable rich text
+ safe code/list formatting
+ existing task UI
+ responsive generation
```

without compromising the existing product boundaries or turning Telegram UX into a new architecture layer.
