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

## Step 1: the parser, offline

`tools/gemma4_parser.py` holds `vllm/parser/gemma4.py` at v0.26.0 verbatim
(Apache-2.0, logger removed) beside a corrected copy, and
`tests/test_gemma4_parser.py` drives both on strings. No model, no server, no
GPU. Twenty tests, three subjects.

**A gap in the plan, stated rather than hidden.** There are no captured raw
emissions. vLLM hands over parsed arguments and never the text behind them, and
nothing was logging that text. So the raw span was *reconstructed by inversion
and verified by reproduction*: a candidate counts only if the vendored parser
turns it into the corrupted call this project recorded. One does, exactly, using
the 3,303-character page the model really wrote —
`tests/fixtures/gemma4_merged_call.txt`.

```text
content:<|"|>{the page}<|"|>Create snake_game.html…<|"|>,status:<|"|>completed<|"|>},{…
```

The closing delimiter of `content` is also the opening delimiter of the next
string. From there every following name is read out of somebody's value:
`content` (the whole page, intact), then
`Create snake_game.html with a basic snake game implementation.<|"|>,status`,
then `},{content`, then `status` — the recorded call, key for key, and no
`path`.

So the failure is **not** 51284 and not 53431. It is a third thing in the same
file: a lost delimiter, after which the argument scan cannot tell a name from a
value. What 51284 predicted — nesting, value length — the GPU run had already
ruled out.

**51284 reproduced anyway**, because it is real and will be met later:
`content:"a, b",path:"page.html"` gives the vendored parser `content` = `"a` and
no `path` at all; `style:{css:"body{margin:0}"}` closes the object on the page's
own brace. The corrected copy reads a quoted literal as a string, honours
backslash escapes, and returns both correctly.

**53431 reproduced and fixed**: `<|tool_call>:name{…}` is accepted beside
`<|tool_call>call:name{…}`, calls closed with `<turn|>` are accepted, and the
extraction scans balanced braces instead of matching a lazy pattern that ends a
call inside the page's own CSS.

**And the correction for our own case is a refusal, not a repair.** Once the
delimiter is gone no reading of that span is the model's intent, so guessing
would be inventing. What can be said is that a parameter name never contains a
brace, a newline or the delimiter token; a span whose names do is not a call,
and `parse_arguments` raises instead of returning one. A partial streaming span
is never refused — half a span is not corrupt. On the calls that work the guard
costs nothing, which is its own test.

That is the whole of step 1. Nothing is deployed, and the served model still has
the shipped parser.

## The fix, in the client

Step 1 ended with a parser that could refuse a corrupt call but not complete the
work, which is not a fix. Re-reading the evidence showed why one is possible.

**`path` was never lost from the stream.** It is in the span, at the end of the
`content` value stored in the database: `…</html>\n```,path:`. The model wrote
it. What was lost is the *closing* delimiter of `content` — the page ended in a
markdown fence — so the parser read to the next delimiter, which was the opening
one of `path`'s value, and everything after is off by one. The earlier reading
in this report, that a contiguous chunk of the stream went missing, was wrong.

That makes the accident recognisable from what the client already receives, with
no access to the raw text: a required argument is missing, and another string
value ends in `,<that argument>:`. One follows from the other.

`app/models/openai_compatible.py` now does three things:

- **`unreadable`** names why a call cannot be what the model asked for: a value
  ending in `,name:` for an argument that is then absent, or a parameter name
  containing a brace, a newline or the delimiter token. Narrow on purpose — only
  at the very end, only after a comma, only for an identifier — so it recognises
  one accident rather than reading text.
- **`repaired`** gives a value its own tail back. `content` did end at the page.
  The missing argument is *not* invented: its value went into the next name and
  is not in the call at all.
- **the retry.** A corrupt completion is thrown away before the loop or the
  conversation sees it, and asked for once more **without streaming**. The model
  never reads its own malformed call, which is what it imitated eight times. One
  retry, not a loop: a second corruption is a broken server, and finding that out
  must not cost the turn's budget. A second corrupt answer is repaired as far as
  is honest and delivered, so the floor is the tool error that exists today.

Offline: **892 passed, 27 skipped**, sixteen new in
`tests/test_unreadable_tool_call.py`, including the whole path through a stubbed
transport — corrupt stream, retry not streamed, the intended call delivered; and
a clean stream never asked for twice.

The standing weakness: **the non-streamed response is assumed healthy on one
observation.** If it corrupts too, the retry buys nothing and the served-side
parser plugin in `tools/gemma4_parser.py` is the next move.

## The retry was measured, and it failed

Deployed at 01:0x and tried on the same request. Every failing step took **51
seconds instead of 27** — two requests, so the corruption was recognised, the
completion discarded and the question asked again without streaming. **The
non-streamed answer was corrupt in the same way.** The assumption this report
flagged as resting on one observation was wrong, and the retry bought nothing
for twenty-five seconds a step.

What the same turn did show is the trigger. The `content` of the first call ends:

```text
…</script></body></html>\n```\n<|tool_call>call:todo_write{todos:[{content:
```

No `path` anywhere: the string runs from the page straight into the *next tool
call's opener*. And the page carries exactly one markdown fence, a closing one,
while starting at `<!DOCTYPE html>` — there is no opening fence. So the model
ends the page with a stray ``` and the string's closing delimiter never arrives.

The second half of the failure is imitation: once one malformed call is in the
history, the next three attempts are byte-identical copies of it, 3,459
characters each.

### Three changes

- **The fence is forbidden where it does the damage.** `write_file` now says to
  give `path` first and `content` last, and that content is the exact bytes of
  the file with no markdown fence before or after it. If the fence is the
  trigger, this removes it, and one live turn says whether it is.
- **The retry is gone.** Measured, unhelpful, expensive.
- **The history stays clean.** `repaired` now drops names that cannot be
  parameter names as well as the swallowed tail, so fragments of another call
  never reach the conversation and there is nothing for the model to copy. The
  missing argument is still never invented. The cleaning runs on the
  non-streamed path too, which is no longer assumed healthy.

Offline: **893 passed, 27 skipped**.
