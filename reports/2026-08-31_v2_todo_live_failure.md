# Version 2 step 4.4 — the first live turns, and what they cost

**Date:** 2026-08-31
**Agent:** Claude, direct session
**Status:** two live turns failed, and a four-variant GPU measurement then
overturned both explanations this report first gave. **The cause is a tool-call
parser defect in the served vLLM, upstream of this repository and intermittent**
— vLLM issues 51284 and 53431. `todo_write` is exonerated and stays. Read the
last two sections first; the earlier ones are kept because the corrections are
part of the evidence.

## The first turn

`assistant-control` was deployed with `todo_write` at 23:36. The first live
request was *«Создай html с игрой змейка, Назови Снейк_Гейм, проверь что
работает»*. The turn ran for **264 seconds and ten model calls** and produced
nothing; the person ended it with `/stop` about thirty seconds before the turn
budget would have.

```text
23:39:24  todo_write   success   one item, "Create snake_game.html…"
23:39:52  write_file   failed    0 ms
…         write_file   failed    0 ms   ×8, one every ~27 s
23:43:38  turn_stopped           step 10, 71,439 input tokens
```

`duration_ms: 0` and no `path` in the trace: these never reached the filesystem.
They failed argument validation.

## What the arguments were

The stored conversation has what the trace does not. The **first** `write_file`
call was this, and it was identical in both turns:

```json
{"content": "<!DOCTYPE html>\n<html lang=\"ru\">…",
 "Create snake_game.html with a basic snake game implementation.<|\"|>,status": "completed",
 "},{content": "Inspect the game to ensure it works.", "status": "pending"}
```

That is a `write_file` call and a `todo_write` list run together into one
object. The model had two things to do in one step — write the file, and update
the plan — and what arrived was one call, named for the first tool, holding both
sets of fields, with `path` gone.

The keys are the evidence: `},{content` and `…<|"|>,status` are fragments of
another call's arguments, and `<|"|>` is not something a model types inside a
JSON string — it is a quote that was encoded and never decoded. **This report
first read that as nesting being the trigger, because `todos` was the only
nested argument here. The measurement below shows it is not.**

The eight repeats afterwards carry no todo text at all — just
`{"content": "<!DOCTYPE html>…"}`, over and over, each one regenerating the
whole page. `path` never reappears, which is consistent with the arguments being
truncated after the long `content` string rather than with the model forgetting
it.

## A wrong diagnosis, corrected

The first version of this report said `StreamedCompletion._fragment` caused it,
by treating a fragment without an `index` as a continuation of the call in
progress. That was wrong. It is a real defect and it is fixed and tested — a
server that opens a second call without a fresh index used to have its arguments
appended to the first — but it is not what happened here. **The second live turn,
after the fix was deployed, produced a byte-identical corruption.**

So the damage happens before anything in this repository sees it: in the
model's own emission, or in the server's tool-call parser, or in the pair. This
report does not claim which, because nothing measured here can tell them apart.

## What the three fixes actually did

**The assembler tells calls apart by identity, not only by position.** Correct,
tested, and aimed at the wrong layer for this failure. It stays.

**A rejected call is told the shape it should have had.** The error now ends
with `write_file takes: path (string), content (string)`. Live, the model read
it five times and never added `path`. Not proven useless — the argument is
plausibly being cut off before `path` can survive — but it did not rescue this
turn.

**A call that has failed twice identically is refused a third attempt.**
Proven live. `turn_repeating` fired at 00:15:10 with `attempts: 2`, the turn
stopped offering tools, and the model was asked once for the answer the person
was owed. **151 seconds instead of 264, and an answer instead of a `/stop`.**

## What the second turn ended up telling the person

Worse than the first, and this is the part that matters most:

```text
"Я создал файл Снейк_Гейм.html с игрой «Змейка». К сожалению, из-за
 технической ошибки … не могу выполнить автоматическую визуальную проверку"
```

The file was never created. Asked for it afterwards, `send_file` failed with
`path 'Снейк_Гейм.html' is not a file`. So the assistant asserted an artifact
that does not exist, and only the person asking for it revealed that. This is
the 4.5.5 failure — saying what was not observed — reached from a new direction:
not describing an unseen artifact, but describing an unmade one.

`inspect_page` was never called, for three reasons worth separating: there was
no file to open; the last model call was offered no tools at all, by the repeat
rule; and the plan item that said to inspect it was one of the fields eaten by
the corrupted call, so it never reached the stored list. The stopping extension
was not asked either — a turn already ending on a harder reason is not asked
whether it would like to keep going.

## Where this left 4.4, before the measurement

Written before the run below, and kept because it is what the two live turns on
their own supported: that `todo_write` made a multi-step request fail, and the
choice was to unwire it or to flatten its schema. Both readings were wrong. The
run is the next section.

## Ledger

Offline after the fixes: **856 passed, 27 skipped**, ten new in
`tests/test_repeated_failure.py`. Two deploys of `assistant-control` (19.560 s
and 34.873 s), control plane only, no model App and no GPU worker started by
either. The two failed turns cost roughly 415 seconds of A10 time between them.
Commits `24f7057`, `17f81ea`.

## The measurement, and what it exonerates

One GPU run, four variants of the same live request, one scenario each.
`reports/prompt_runs/2026-08-31_00*`.

| variant | shape | model calls | tools | seconds | derived $ |
| --- | --- | --- | --- | --- | --- |
| nested todo + streaming | ok | 7 | todo_write, write_file, todo_write, inspect_page, todo_write | 55.9 | 0.0181 |
| nested todo + non-streaming | ok | 7 | the same five, same order | 42.5 | 0.0164 |
| flat todo + streaming | **off** | 6 | todo_write, write_file ×3, all failed | 134.6 | 0.0446 |
| no todo + streaming | ok | 3 | write_file, inspect_page | 37.0 | 0.0148 |

**Nesting is not the cause.** The nested schema — the one blamed in the section
above — wrote the file, inspected it and kept its plan, twice. `write_file`
arrived as `{"content": …, "path": "Снейк_Гейм.html"}` and created 3,578
characters.

**Streaming is not the cause.** Non-streaming reproduced the successful run
exactly, and the failure never needed streaming to appear.

**The planning tool is not the cause either.** The variant that failed is the
*flat* one, whose `todo_write` takes a single string and nests nothing. Its
failing calls are `{"content": "<!DOCTYPE html>…"}` — no `path` — which is the
same shape as both live failures.

So the flatten-the-schema proposal is dead: it was measured and it failed.

## What the evidence actually says

Every failure is one call that carried a long string value and lost what came
after it. The successful call's own key order says the model writes `content`
first and `path` last, whatever order the schema declares. When the tail
survives, the write succeeds. When it does not, `path` is gone — and in the
first live turn the space it left was filled by fields of the *next* call the
model was emitting, which is why that one looked like a merge.

That is vLLM issue 51284, read after the fact: the Gemma 4 tool parser
mishandles string values written as plain quoted literals instead of the
grammar's `<|"|>` delimiter, `_parse_gemma4_args` copies raw text verbatim
instead of decoding it, and *the occurrence rate climbs sharply with the length
of the value*. Our `<|"|>` in a parsed key is the same fingerprint. Issue 53431
is a second parser defect in the same file, present in 0.26.0 and still in
0.27.1, and confirms the mode is not something a client flag turns off.

It is intermittent, and this run shows how intermittent: the same request, the
same temperature 0, four attempts, one failure. Content length does not separate
them — 3,578 characters succeeded and 3,463 failed.

Two things the run also measured, worth keeping:

- **A plan costs.** Seven model calls against three for the same outcome, and
  three of the seven are `todo_write` on work whose whole plan was two steps.
- **The repeat rule held again**, in the failing variant: three attempts, the
  fourth refused, an honest answer. It cost $0.0446 against $0.0148 for the
  clean run — the price of failing well.

## The minimal compatibility fix

The parse is broken upstream and cannot be fixed from this repository. What can
be done here, cheapest first:

1. **Tell the model how to get around it.** The current argument error names
   what is missing and the signature; it was read five times without effect
   because it does not say the one thing that would help — resend with `path`
   first and `content` last, so the value that may swallow the rest is last.
   Ten lines, offline-testable, and it either changes the retry or it does not.
2. **Stop requiring a long value and another argument in the same call.** A
   write that names its target in one call and takes the text in another cannot
   lose the target to the text. It is a real product change and costs a call.
3. **Fix it where it is broken.** A tool-parser plugin on the served model, the
   way 53431's reporter did, or guided decoding for tool calls. This is a model
   App redeploy and its own gate, and it is the only option that removes the
   defect rather than routing around it.

`todo_write` stays as it is. It is not what breaks, its cost is now measured,
and 4.4's acceptance question — does an unfinished plan hold a turn open — is
still unanswered, because in every successful variant the model closed its own
list before answering.
