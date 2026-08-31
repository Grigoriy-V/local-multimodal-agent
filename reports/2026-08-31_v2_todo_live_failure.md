# Version 2 step 4.4 — the first live turn, and the bug it exposed

**Date:** 2026-08-31
**Agent:** Claude, direct session
**Status:** diagnosed from the deployed trace and the stored conversation;
three fixes implemented and tested offline. Not deployed, not measured live.

## What happened

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

## The cause

The stored conversation has the arguments the trace does not. The **first**
`write_file` call was this:

```json
{"content": "<!DOCTYPE html>\n<html lang=\"ru\">…",
 "Create snake_game.html with a basic snake game implementation.<|\"|>,status": "completed",
 "},{content": "Inspect the game to ensure it works.", "status": "pending"}
```

That is a `write_file` call and a `todo_write` list **run together into one
object**. The model had emitted two tool calls — write the file, and mark the
first item done — and they arrived as one call whose name was the first tool's,
whose arguments were both, and in which `path` no longer existed.

`StreamedCompletion._fragment` assembled them. It keyed fragments by the
server's `index` and treated a fragment without one as a continuation of the
call in progress, which is documented and was believed safe: *"a server that
omits it can only be describing the call already in progress"*. It cannot. A
fragment that names a different tool, or carries a different id, is the next
call. Concatenating its arguments onto the previous one usually produces invalid
JSON and fails loudly — and sometimes, as here, produces a valid object that is
a call the model never made.

This is why it worked the day before with the same request. Nothing about the
page changed. What changed is that the agent acquired a second tool worth
calling in the same step as the first, so a turn with two tool calls in it went
from rare to ordinary. `todo_write` did not cause the bug; it exposed one that
had been there since answer streaming landed.

The eight repeats afterwards are the model's own: each attempt regenerated the
whole page, was told `missing required argument(s): path`, and tried again.

## Three fixes

**The assembler tells calls apart by identity, not only by position.** A
fragment carrying a different name or a different id opens a new call, at the
next free position, whatever index the server gave it. A server that echoes the
same id and name on every fragment is still one call, which is the other real
shape and is now tested.

**A rejected call is told the shape it should have had.** The error was
accurate and useless: it named what was missing beside a schema the model was
plainly no longer reading. It now ends with `write_file takes: path (string),
content (string)`. A few tokens, at the moment they are the only thing being
read.

**The loop stops paying for a call that keeps failing identically.** Two
attempts are a retry; a third attempt at a call that has already failed twice
with the same arguments is a loop. It is refused before it runs, the turn stops
offering tools, and the model is asked once more for the answer the person is
owed — the same path a spent budget takes, with its own reason: *the same call
kept failing in the same way*. Identity is name plus arguments, and only
failures count, so writing the same file twice is unaffected.

Offline: **856 passed, 27 skipped**, 10 of them new in
`tests/test_repeated_failure.py`.

## What this does not settle

Whether the model emits two calls in one step *more often* because of
`todo_write`, and whether that is good, is unmeasured. The scenario runner's
`plan` scenario is where that gets looked at, and it needs a GPU run.

The 264 seconds were bounded only by a person. With the repeat rule the same
turn would have ended after three attempts, roughly 80 seconds, with an answer
saying what failed.
