# The first live session on the new tool system, 2026-09-03

Thread `3261ae8f`, run `30fe463c`, Telegram, the first turn after
`assistant-control` was deployed with 4.5 and 4.5.5. One request: make "Task
Board test 4" and send the screenshot and the files. The person's verdict on
the answer: bad. Read back from the stored history and the telemetry, nothing
here was observed in the chat itself.

## What happened, call by call

| # | call | result |
| --- | --- | --- |
| 1 | `todo_write`, four items | ok; never updated again |
| 2 | `write_file` with `content` only | `bad_arguments`, signature returned |
| 3 | the same | the same |
| 4 | `write_file`, path `"Task Board test 4/index.html"<|"|>` | **created a file of that name** |
| 5 | `inspect_page` on the real name | `fs.not_found` |
| 6 | `write_file`, the corrupted path again | overwrote the wrong file |
| 7 | `inspect_page` on the real name | `fs.not_found` |
| 8 | `write_file`, the real name | created |
| 9 | `inspect_page` on the real name | **refused by the repeat guard**, no further tools |
| 10 | answer | "не могу напрямую отправить скриншот", no `send_file` |

261 s, 10 model calls, 85 089 input tokens, derived cost about $0.08. Four of
the model calls were 45 s each: the page written four times.

## Three defects, and what each one is

**The served parser, again (ISS-0001).** Calls 2 to 4 and 6 are its shape: the
string delimiter lost at the end of `content`, then `path` swallowed, then a
path that is the literal text `"…"<|"|>`. The runtime did what 4.5 promised
for 2 and 3 — one refused call with the signature, the turn went on. It did
not for 4 and 6, because the fragment there sat inside a string value, and the
fragment removal looks at parameter names and at a `,name:` tail. A file with
quotes and a delimiter in its name was created on the person's volume, and
every honest later call by the real name could not find it.

**The repeat guard refused the call that would have worked (new, ISS-0013).**
Two looks at a file that did not exist, then the file is written, then the
third look — identical arguments, a different world — is what the guard
counted as the third identical failure. It ended every tool for the turn. That
is why there was no screenshot and no `send_file`: the model could not have
sent anything after call 9. The guard was right on 2026-08-30 about a call
that cannot come out differently and wrong here about one that can.

**The answer (ISS-0010).** "Так как я не могу напрямую отправить скриншот" is
the same false belief as in thread `afb9d76a`. This time it is also half
true: tools were halted, so nothing could be sent. The honest sentence was
"the look at the page was refused, so I have no screenshot"; the guard's own
message asks for exactly that. What it said instead names a capability it
does have as one it lacks.

The plan was written and never touched: four items, all still pending at the
end, none marked in progress or done. `todo_write` was called because the
request listed steps; it did not then drive the work (ISS-0004 territory,
4.4's known problem).

## Fixed in the tree the same day

- `failed_before` in `app/agent/graph.py` starts the count over when any tool
  has succeeded since the last identical failure. A repeat is only a repeat if
  nothing changed in between. `tests/test_repeated_failure.py`: the unit rule
  and a turn through the graph where a read fails twice, a write lands, and
  the third read runs.
- `resolve_in_root` in `app/tools/filesystem.py` refuses a path that carries
  `<|`, `|>` or wrapping quotes as `bad_arguments` with "send it again with the
  plain path". Every path-taking tool goes through it. `tests/test_tools.py`.

Not changed: the fragment removal in the adapter, which stays narrow on
purpose; the guard's limit of two; anything about what the model says.

## Checks

| check | result |
| --- | --- |
| `pytest` offline | 958 passed, 27 skipped |
| `ruff` on changed files | clean |
| the source guard in `tests/test_turn_stopping.py` | caught a tool name in a graph docstring; reworded |

## Left on the volume

`"Task Board test 4/index.html"<|"|>` in the person's workspace, next to the
real `Task Board test 4/index.html`. Deleting it is a destructive action on
the deployed volume and needs the person's word.

## Next gate

Deploy of this fix, and one more live turn of the same request.
