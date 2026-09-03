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

## The same request again, through the loop, on the fixed code

Run `live-70`, the person's request verbatim, local loop against the deployed
model, a browser on this machine, 84 s, 7 model calls, 6 tool calls, no tool
failure. Checked, not only read:

| check | result |
| --- | --- |
| a plan was written | yes, and updated twice: three items done after the write, the fourth after the look |
| `index.html` under the plain name, no junk file | yes |
| `inspect_page` ran and the model read a structure with a ref | yes |
| something was sent | `index.html`, by `send_file` |
| the repeat guard did not end the turn | correct |

Two things the run showed that the checks did not ask about.

**The look lied about the app (ISS-0014).** `inspect_page` reported
`SecurityError: … Storage is disabled inside 'data:' URLs`. The app is fine;
the page was opened as a `data:` URL, which has no origin. The model read the
error, said nothing, and marked "verify" done. Fixed the same day: the
offline session now serves the workspace at a synthetic origin and fails every
other request, so the page has storage and its sibling files. Re-inspected on
the fixed code: no console error, no refused request. Then driven through the
session itself: a task typed and entered appears in "To Do" and is still there
after a reload. The app the model made works.

**The screenshot was handed over as markdown (ISS-0003).** `send_file` was
called for `index.html` and not for the PNG; the answer ends with
`![Screenshot](.agent/browser/index-e7fd9c44.png)`.

Also seen: the written file ends with a literal markdown fence after
`</html>` (ISS-0015), visible on the page and in the snapshot the model read.

## The person's turn on the served-origin code: Task Board test 5

Thread `5cee5866`, run `b100a27a`, 79 s, 10 model calls, 8 tool calls, no
failure. Three files this time (`index.html`, `style.css`, `script.js`), a
six-item plan, one needless rewrite of `index.html`, one look that reported
no console error and no refused request — the served origin worked in the
container, Chrome 151. Then the answer: files as bullet paths and
`![Screenshot](.agent/browser/index-d100867a.png)`; nothing sent. The files
came on "в чат пришли файлы" (three `send_file`), the PNG on "скрин" (a
second `inspect_page`, then `send_file`).

What the brief had not told the model: where the person is. The delivery
sentence said what the interface can carry and that a request for a
screenshot means `send_file`; it never said the person cannot see the
workspace, so a path or a markdown image looked like a way to hand something
over. `Delivery` now carries `place`, declared by each adapter ("Telegram",
"the Chainlit web app"), and the brief says the person sees only this chat,
cannot open or browse the workspace, and that a path, link or markdown image
of a workspace file delivers nothing; the send is one call per item.

**An option the human has not decided:** a mechanical backstop in the
adapters, where a markdown image in the final answer that names an existing
workspace image is taken as the model's explicit decision to show it and is
delivered as one. It is not automatic forwarding of tool media, which
2026-08-29 rejected: the model wrote the embed itself. It is also a second
way to send, next to `send_file`. Left as an option in this report.

On the plan: six phases, five ticked in one call, "verify" ticked after a
look that pressed nothing (ISS-0016).

## The person's turn on the brief with `place`: thread `46c6a9c3`

Run `253ede5d`, 88 s, 5 model calls, 4 tool calls. One `write_file` refused
for a missing `path` (the parser again), the retry landed. One look: the page
pulls Tailwind from a CDN, which the offline session refused and reported.
Then the answer with `send_file` of the PNG attached — the screenshot arrived
unprompted, which the previous three turns never did — and the single file
listed as a path, not sent. The human rejected an adapter backstop for the
markdown case as a crutch; the brief stays the only lever until 4.7.

Two things measured here that were only described before:

- **ISS-0009, the vanishing text, costs real tokens.** The answer was written
  with the send attached (169 tokens), withdrawn from the chat, and written
  again after the send (134 tokens, 3.8 s), word for word. The first copy
  stays in the turn's messages and is re-read as input on the next call.
- **ISS-0017, the sent screenshot is not what the person's browser shows.**
  The CDN was refused by design; the picture is of the unstyled page; the
  model called it "Tailwind CSS" anyway.

## Both decided and fixed the same day

The human allowed the CDN and called the double generation unacceptable
(`DECISIONS.md` 2026-09-03, second entry). In the tree and deployed:

- the core prompt says text written beside a tool call reaches the person at
  once, and that after the tool's result the model adds only what is new;
- the Telegram adapter keeps the preview as the answer when a call rides
  with it, as Chainlit already did, and does not send a verbatim repeat later
  in the same turn;
- the offline session serves the workspace and lets the page reach public
  addresses under the `view_web_page` policy; private ones are refused and
  reported.

The repeat guard on delivery is a display rule, not the fix: the fix is the
model not writing the text twice, which only a live turn shows.

## The next turn: the plan seam produced the same double generation

Thread `052869f2`, run `f41278c9`, 10 model calls, 8 tool calls. The person
saw the answer appear, then a planning step, then the answer again — and the
markdown image once more, with no `send_file` this time at all. The trace
says `turn_steered step=8 source=todo`: the model's answer was refused as an
ending because "Verify and take screenshot" was still in progress; the draft
was withdrawn from the chat; the model closed the item with `todo_write` and
wrote the same answer again. 117 + 164 output tokens and 7 s for a plan tick.

The seam was right to object and wrong about what it cost. Fixed the same
day, in the tree: the steering tells the model its answer is kept; an empty
completion after a steering hands the draft back as the answer; the Telegram
preview holds the draft on the screen instead of deleting it and edits it in
place if the model writes something new; an empty completion with nothing
steered ends the turn quietly, which the core prompt now asks for after a
tool when nothing is new. `tests/test_turn_stopping.py`,
`tests/test_telegram_adapter.py`.

The markdown image is ISS-0003 and stays open: two turns on the placed brief
and it held in neither. Nothing in the runtime changes that without the
backstop the human rejected; the lever left is 4.7.

Also seen again: `index.html` rewritten with the same content right after the
plan update, the third turn in a row.

## The turn after that: the hold was defeated, and the model ignored "nothing"

Thread `d88734a2`, run `af276ed7`, the same shape: `turn_steered step=8
source=todo`, then `todo_write`, then the answer again — 162 output tokens,
word for word. Two findings.

The held draft was deleted anyway. The bare `todo_write` completion that
followed the steering went through the adapter's "no spoken text" path, which
discards the preview; the hold did not survive it. Fixed: a held draft is not
that completion's preview and waits for the answer that ends the turn.
`tests/test_telegram_adapter.py`.

The model did not answer with nothing. Told "your answer above is kept … if
nothing is new, answer with nothing", it ticked the item and wrote the answer
again. With the hold fixed the person sees one bubble edited into the same
words, so the vanish is gone; the second generation is not. In every live
turn the plan seam has objected — four now — its objection produced a
bookkeeping tick and a duplicate answer, and never more work. Whether the
seam should keep objecting is the human's decision; the option is to set its
limit to zero and let an open plan item end the turn, which is what the
person's own eyes already accept.

The human decided the same day: an open plan item may end the turn; the plan
is gone at the next message anyway. `FinishesItsOwnList` defaults to no
objection; the seam and the class stay for an extension whose objection is
worth a second generation. `DECISIONS.md` 2026-09-03.

## The turn on the seam-free code, and what the tools now say

Thread of 07:36Z, run `752486c1`: 8 model calls, 7 tool calls, no steering,
no failure, the answer written once and delivered once, 74 s. Clean, except
the markdown image and the paths again, and the same needless rewrite of
`index.html` after the plan update. "Пришли скриншот в чат" then produced
`send_file` at once (run `a2e69c53`): with a direct command the model sends
without hesitation; it is the unprompted delivery it gets wrong.

Every tool that leaves something in the workspace now names the action in its
result: `to hand it to the person: send_file(path="…"); nothing is sent
otherwise` — `write_file`, `inspect_page`, `view_pages`, `view_web_page`, one
phrase in `app/tools/base.py`. `DECISIONS.md` 2026-09-03 makes it the rule:
a tool result names the action its output enables. The human's condition for
the adapter fallback, if this does not hold: one delivery path never blocks
another.

## The "needless rewrite" was a silent replacement

The three turns asking for "Task Board test 5" all named the same folder,
which held the previous attempt each time. The tool results said `overwrote`
four times per turn; the answer said "готово" and nothing about what had
been there. Recorded as ISS-0018. The person's expectation: notice the place
is taken, say so, and decide or ask — never replace in silence.

## First turn on the handover phrase: delivered, with a tail

Run `7673ce55`, "Task Board test 6", 90 s, 12 model calls, 11 tool calls, no
failure, no steering. The answer was written once with `send_file` of the
screenshot attached and delivered in place; then `index.html`, `style.css`
and `script.js` were sent, one call each; no markdown image, no path list
offered as delivery. That is what the phrase was for, and it held on the
first turn.

What got worse: the model closed with a second message — the same functional
list again, minus the files, plus "Файлы приложения отправлены в чат", 108
tokens — which the exact-match display rule does not catch, so the person
sees the list twice. And the three sends went one per model call, about
1.2 s and 6.6 k input tokens each, where one completion could carry all
three. Neither is a runtime defect: both are the model not doing what the
core prompt says after a tool.

Also settled: the second `index.html` write is byte-identical to the first,
in a fresh folder, so it is not ISS-0018 but its own thing (ISS-0019).

## The same request with the plan off

`/plan off`, then "Task Board test 7", run `5ed7fc4c`: 5 model calls, 4 tool
calls, 62 s. One file written once, one look, `index.html` and the screenshot
sent unprompted, one answer. Against `7673ce55` with the plan on: 12 model
calls, 11 tool calls, 90 s, the page written twice, the answer written twice.
What the plan added in this run was cost: ISS-0016 and ISS-0019 by
construction, the closing duplicate with them. The single-file shape is the
model's own choice this time, not the switch's doing.

## Test 7: the album call came, and the ceiling refused it

Run `9c42241c`, plan off, 13 model calls, 11 tool calls, 156 s, the person's
own request. Three things, in order of what they cost.

The model wrote `index.html` seven times and the other two files twice each
(ISS-0019, now seen without the plan and worse): ten `write_file` calls,
byte-identical in each pair, 125 s of model time before `inspect_page`. The
tool result said `overwrote … (1070 characters)` every time, which reads
like progress. `write_file` now answers `unchanged: … already had exactly
this content, so nothing was written` when the bytes are the same.

Then the thing that was asked for that morning happened: one `send_file`
with four paths — three files and the screenshot — beside the answer text.
And the ceiling refused it: step twelve of twelve, "no further tools will
run, answer now with what you already have". The text was delivered; the
files were not (ISS-0020). A tool now carries `delivers`, `send_file` sets
it, and a delivery runs past the ceiling while the rest of the batch is
halted: the ceiling bounds work, not the handover.

The last request, offered no tools, answered with one token: `<eos>`, and
the adapter sent it as a message (ISS-0021). The client now drops end-of-turn
markers from text, and an empty completion ends the turn quietly.

Not touched: the twelve-step ceiling itself. Seven wasted writes would have
fit under any ceiling worth having; the fix is the word `unchanged`, and if
the model does not stop on it, that is model behaviour for 4.7.

## Test 8: the best turn of the day

Run `af0370cb`, plan off, 7 model calls, 6 tool calls, 62 s, $0.02 derived.
Three writes, one identical rewrite of `index.html` answered `unchanged`,
then `inspect_page` at once, then the answer's first line beside one
`send_file` with all four paths, delivered as an album, then a closing
message that says what was built and that the files are in the chat. No
`<eos>`, no steering, no ceiling, no markdown image, no path handed over as
prose. Against test 7: 13 calls and 156 s down to 7 and 62; the one wasted
call is ISS-0019 at its floor.

What the person saw: one short message, the screenshot, the three files, the
summary. That is the product as `docs/PRODUCT.md` describes it.

## Next gate

The person's own turn in Telegram on this code; the plan's own defects wait
for 4.7 with the switch off in the meantime.
