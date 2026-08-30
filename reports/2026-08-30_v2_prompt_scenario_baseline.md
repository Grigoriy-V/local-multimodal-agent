# The prompt correction did not cause the 4.3 regression

**Date:** 2026-08-30
**Agent:** Claude, direct session
**Status:** first measured comparison; one attribution in the 4.3 report is
withdrawn

## What was run

`tools/prompt_scenarios.py`, five fixed natural requests through the same
`Agent` the bot uses — no Telegram, no queue — once against the prompt as it
was **before** the 4.3 correction and once against the prompt as it is now.
Both variants ran back to back in one warm window against the deployed
endpoint. Reports and the exact prompts:

```text
reports/prompt_runs/2026-08-30_0727_baseline/   prompt e8c70ff28d7e, 4549 chars
reports/prompt_runs/2026-08-30_0729_current/    prompt 5c4cb811133f, 4695 chars
```

Derived GPU cost, upper bound: **$0.0370 each, $0.074 for both.** No deploy, no
model App change, no third-party service — the web scenario spends a search
provider's credit and was left out.

## Result

| scenario | baseline | current |
| --- | --- | --- |
| chat | 1 model, no tools | 1 model, no tools |
| capabilities | 1 model, no tools | 1 model, no tools |
| note | 3 model, `list_files`, `write_file` | 3 model, `list_files`, `write_file` |
| castle | **1 model, no tools** | **1 model, no tools** |
| broken_page | 3 model, `list_files`, `read_file` | 3 model, `list_files`, `read_file` |

The two prompts produced the **same shape on every scenario**. Where they
differ is wording and length of the answer, not what the agent did.

## The withdrawn attribution

`reports/2026-08-30_v2_turn_stopping.md` records that the stronger system
prompt regressed "Создай HTML с средневековым замком" from `write_file` into
inline code with zero tool calls, and names the prompt as the leading cause on
one live sample per version. **That is not what happens.** The pre-correction
prompt produces the identical failure, in nearly identical words:

```text
1. Скопируйте код ниже.
2. Сохраните его как файл `castle.html`.
3. Откройте этот файл в любом браузере.
```

followed by the whole page in a fenced block. 1,737 output tokens on the
baseline, 1,925 on the current prompt, no tool call in either.

So the prompt correction is not the cause, and rolling it back would not
restore the behaviour. The live evidence was two samples that differed in more
than the prompt, and this is the first comparison that holds everything else
still.

## What is left as the likely cause

The live turns that *did* call `write_file(castle.html)` ran in a thread where
an earlier turn had already created a named HTML file in the workspace. These
scenarios each start on a fresh thread with an empty workspace and a request
that names no file. The system prompt tells the model, in a sentence that
predates all of this, to ask where a file goes rather than invent a location
when its directory "is not already established". A request with no filename at
all in an empty workspace is the case where the model has nothing established
and no question is asked either — it simply stops treating the outcome as a
file.

That is a hypothesis with a cheap test: the same request in a thread where a
file was written first, and the same request naming a file explicitly. It has
not been run — every run wakes the GPU and is its own gate.

## A finding about the instrument, not the agent

`broken_page` was scored "off" in both runs because it expected `inspect_page`
and the agent used `read_file`. Reading the source of a six-line page is the
proportional choice, and both runs found both defects from it — the white-on-
white price and the `textContnet` typo. The expectation is wrong, not the
trajectory. A scenario that needs rendering to answer has to be one whose
answer is not in the source; this one is being rewritten before it is trusted.

`castle` and `note` also spend a `list_files` call before writing. That is the
same "establish where the file goes" instinct, and it costs a model step.

## Method

Each scenario runs on its own thread with the workspace emptied first, so no
scenario sees what another wrote. The run keeps its own store, checkpoints and
telemetry file; the deployed database is cleared explicitly in the settings
rather than left to the environment. Tool expectations are the only automatic
check and they judge the shape of a turn, never the quality of an answer, which
is why the full text of every answer is in the report beside it.
