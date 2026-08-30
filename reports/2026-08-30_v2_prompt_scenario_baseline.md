# The prompt correction did not cause the 4.3 regression

**Date:** 2026-08-30
**Agent:** Claude, direct session
**Status:** first measured comparison; one attribution in the 4.3 report is
withdrawn and the real cause is isolated

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

## The cause, isolated

That hypothesis was then run. Four cases, same request, same prompt, one warm
window — `reports/prompt_runs/2026-08-30_0736_castle_causes/`:

| case | what is established | result |
| --- | --- | --- |
| `castle` | nothing | 1 model, **no tools** |
| `castle_named` | the request names `castle.html` | 2 model, `write_file` |
| `castle_seeded` | an HTML file is already in the workspace | 1 model, **no tools** |
| `castle_after` | the previous turn in the thread created a file | 2 model, `write_file` |

The deciding factor is whether a place for the file is **established in what
the model can see**: named in the request, or made by the turn before. A file
merely lying in the workspace changes nothing, because in that case the model
never calls `list_files` and so never learns it is there.

This matches a sentence that predates 4.3 entirely: *"If the user names only a
file, such as snake.html, and its directory is not already established, ask
where it is instead of inventing a location."* Written for the case where a
filename arrives without a directory, it is being generalised to *no filename →
invent nothing → write nothing*. And the model does not do the one thing that
sentence actually asks for: it never asks where the file should go. It silently
stops treating the outcome as a file.

Cost of the isolation: **$0.0594**, four turns.

## What still fails when the write succeeds

Both working cases wrote the file and then described the result — towers, a
flag, the sky — with no `inspect_page` call. `castle_named` ends by telling the
person to open the file in a browser. So the write is only half of 4.3's
acceptance, and the other half — inspect before claiming how something looks —
fails identically whether or not the file gets written.

## A finding about the instrument, not the agent

`broken_page` was scored "off" in both runs because it expected `inspect_page`
and the agent used `read_file`. Reading the source of a six-line page is the
proportional choice, and both runs found both defects from it — the white-on-
white price and the `textContnet` typo. The scenario is deliberately left as it
is: whether the agent chooses to look is the question it exists to ask, and an
expectation it keeps missing is a question to read rather than a verdict to
act on.

`castle` and `note` also spend a `list_files` call before writing. That is the
same "establish where the file goes" instinct, and it costs a model step.

## Method

Each scenario runs on its own thread with the workspace emptied first, so no
scenario sees what another wrote. The run keeps its own store, checkpoints and
telemetry file; the deployed database is cleared explicitly in the settings
rather than left to the environment. Tool expectations are the only automatic
check and they judge the shape of a turn, never the quality of an answer, which
is why the full text of every answer is in the report beside it.
