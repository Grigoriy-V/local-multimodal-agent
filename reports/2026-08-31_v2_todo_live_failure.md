# Version 2 step 4.4 — the first live turns, and what they cost

**Date:** 2026-08-31
**Agent:** Claude, direct session
**Status:** two live turns, both failed, both read from the deployed trace and
the stored conversation. Three fixes implemented, tested and deployed; one of
them is proven live, one is untested, and **the cause of the failure is still
upstream of this repository.** `todo_write` is deployed and currently breaks
file writing.

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

The keys are the evidence about where it broke: `},{content` and
`…<|"|>,status` are fragments of **an array of objects**, cut at the places
where nesting and quoting begin. `<|"|>` is not something a model types inside a
JSON string; it is a quote that was encoded and never decoded. `todos` is this
project's first and only argument with that shape.

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

## Where this leaves 4.4

`todo_write` is deployed and, on the evidence of two turns, makes a multi-step
request fail. It did not break the parser; a second tool worth calling in the
same step as `write_file` is what makes the fragile path ordinary.

Two options, neither taken yet:

- **Unwire it** from the granted toolbox and redeploy. Restores file writing
  immediately; leaves 4.4 unaccepted.
- **Flatten the schema** so nothing nests — a checklist as one string, or an
  array of strings — and measure. A deliberate departure from the reference,
  whose whole-list-of-objects shape is fine on a different server and a
  different model.

Either way the measurement is the same scenario run: the same request with the
nested schema, with a flat one, and with no planning tool at all. It needs a
GPU and is its own permission.

## Ledger

Offline after the fixes: **856 passed, 27 skipped**, ten new in
`tests/test_repeated_failure.py`. Two deploys of `assistant-control` (19.560 s
and 34.873 s), control plane only, no model App and no GPU worker started by
either. The two failed turns cost roughly 415 seconds of A10 time between them.
Commits `24f7057`, `17f81ea`.
