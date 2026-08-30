# Version 2 step 4.3: turn stopping and proportional validation

**Date:** 2026-08-30  
**State:** deployed; live acceptance failed

## Product boundary

The single agent loop now has one typed extension point immediately before an
ordinary model answer would end the turn. The default stops immediately. A turn
continues only when an injected extension returns explicit structured steering.

The implementation adds no validator model, finish tool, text heuristic,
obligation state, mandatory repair lifecycle or task-specific workflow. HTML is
only an offline scenario in which the scripted model chooses `inspect_page`.
PDF creation remains deferred until generic sandbox execution exists.

## Implementation

- `app/agent/stopping.py` defines `Candidate`, `Steering`, `Steered`, the
  `TurnStopping` protocol and the stop-by-default implementation.
- `app/agent/graph.py` asks the extension only for an ordinary would-be final
  answer and only when another step fits the existing turn budget. Structured
  steering stays in transient graph state for one further model step; the draft
  is not appended to conversation messages or persisted.
- `app/agent/runtime.py` emits `AnswerWithdrawn` when a streamed candidate is
  steered instead of settled.
- `ui/telegram/adapter.py` discards the corresponding preview, preserving one
  final Telegram answer.
- `docs/CODEMAP.md` records the new owner and streaming event boundary.

The Supervisor review found and returned three defects to the same Claude
session: an empty toolbox was mistaken for budget finalization, steering text
was written into privacy-bounded telemetry, and the current model call's elapsed
time was absent from the next-step budget decision. The corrected implementation
separates finalization from tool availability, traces structure without content,
and prices the completed call before allowing steering.

## Offline evidence

The focused scenarios prove:

- default stopping costs one model call;
- explicit steering performs another step but persists and delivers only the
  accepted answer;
- steering also works for an agent with no tools;
- simple file writing gains no automatic validation pass;
- the model may choose `inspect_page` after steering without HTML-specific
  infrastructure policy;
- a failed tool result reaches the model, which can adapt in the same loop;
- a steered streamed candidate is withdrawn before the Telegram final answer;
- turn budgets include the model call being judged;
- traces contain no draft, steering instruction, user request or exception
  message content.

Worker verification: full offline suite **770 passed, 27 skipped**. The skips
are the environment-gated PostgreSQL contracts requiring
`AGENT_TEST_DATABASE_URL`.

Supervisor verification:

```text
python -m pytest tests/test_turn_stopping.py tests/test_turn_bounds.py \
  tests/test_agent_graph.py tests/test_answer_streaming.py \
  tests/test_turn_telemetry.py tests/test_telegram_adapter.py -q
156 passed

independent no-tools reproduction
extension_calls=2, model_calls=2, stored=[user request, accepted final]

git diff --check
passed (line-ending warnings only)
```

One supervised Claude Opus/medium development session was used through Orca and
reused for the correction Task. No product-runtime worker, application model
endpoint or application network service was invoked during implementation.

The control plane was initially deployed with:

```text
modal deploy deploy/modal/control_app.py
assistant-control deployed in 21.874 s
```

The deployment rebuilt the CPU/control functions and retained the existing
Telegram webhook and renderer URLs. The model/GPU App was not deployed or
invoked during deployment.

## Live evidence

The implementation seam behaved cleanly at the interface boundary, but the
agent did not choose proportional visual inspection autonomously.

### First generated-page scenario

Run `31977c1292bd413797c44807051e6c3e` received a natural request to create
`turn-stopping-live.html`, briefly describe the result and not send the file.
It made two model calls and one `write_file` call, but no `inspect_page` call and
no structured steering. It then described the page visually and asked whether
the person wanted it inspected, exposing the internal tool name. The turn had
one preview and one final delivery, with no duplicate answer.

```text
total: 30.14 s
model/tool calls: 2m / 1t
tool: write_file(turn-stopping-live.html)
inspect_page: absent
turn_steered: absent
derived GPU cost upper bound: $0.0094
```

This failed product acceptance: safe observation should not require another
user turn, and an artifact must not be described from intent rather than visual
evidence.

### Natural castle scenario

Four consecutive turns showed that the underlying capabilities worked but the
same autonomy gap remained:

- `df6c432257cd4f0094cb5872e9c34075`: `write_file(castle.html)`, followed by a
  request for permission to open it;
- `c4348322c08f4cb58019cfc4546fb6e7`: after the person replied "да", the model
  called `inspect_page(castle.html)`;
- `a4fbb2a427d24de3be06dd372bf19828`: after "покажи мне", it called
  `send_file(castle.html)`;
- `334c9bd7d8cc4ae18ad98f44746eebde`: after "скриншот", it called `send_file`
  on the PNG already saved by `inspect_page`.

Observation remained private until the model explicitly presented a file, the
saved screenshot was reused intelligently, and every turn produced one final
answer. The product failure was the unnecessary permission round-trip before
safe inspection.

### Prompt correction and regression

The soft system instruction to use `inspect_page` when browser evidence would
help was replaced with a stronger general rule:

- safe observation needs no permission;
- inspect a visual result before describing how it looks or works;
- use `inspect_page` for local HTML;
- do not expose internal tool names or make unobserved visual claims.

Focused prompt/context checks passed, **43 tests** in total, and
`assistant-control` was redeployed successfully in **19.154 s**. The deployment
did not deploy or wake the GPU App.

The immediate natural regression check used the same request, "Создай HTML с
средневековым замком". Run `a53ae00c46f946929803ad28abfe035c`
made one model call and **zero tool calls**. It neither wrote nor inspected a
file. Instead it emitted the complete HTML as chat text, told the person to
save and open it manually, and inaccurately said that it had created the
artifact.

```text
outcome: answer_delivered
total: 67.25 s
model/tool calls: 1m / 0t
tokens: 2617 in / 1629 out
first model token: 29.30 s from run start
model time: 37.69 s
derived GPU cost upper bound: $0.0152
```

The response was delivered once, so this is not a Telegram delivery or turn
stopping regression. It is an agent-action regression: the creation step that
had worked degraded into instructions for the user.

**The cause named here was wrong and is withdrawn.** This section originally
concluded that the prompt correction was the leading cause, on the grounds that
it was the material change between the two deployments. A measured comparison
the same day ran the same request against both prompts, everything else held
still, and got the identical failure from each: 1 model call, no tool call, the
whole page in a fenced block with "сохраните его как файл `castle.html`". The
two live samples differed in more than the prompt — the turns that did call
`write_file` ran in a thread where a named HTML file already existed — and one
sample per version could not tell those apart.
`reports/2026-08-30_v2_prompt_scenario_baseline.md`.

Step 4.3 therefore remains open. Its minimal `TurnStopping` seam is verified
offline and its one-answer interface behavior survived live use, but there is
still no production source of structured steering and the default stop accepts
an inadequate model answer. The next correction should remain at the general
agent/prompt boundary first: an artifact request must perform the available
workspace action rather than substitute code or instructions, and visual claims
must follow inspection. It must not add an HTML-specific workflow, validator or
obligation state to the stopping seam.
