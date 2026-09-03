# Issues

Known defects. One entry per defect, newest first.

## What belongs here, and what does not

A defect is a place where the system does something other than what it was
built to do, and where that difference has been **observed**, not suspected.
This file is the list of those, whether or not anyone has decided to fix them.

It is not a plan and it does not authorize work. `ROADMAP.md` remains the only
source of direction, order and approved work; an issue here becomes work only
when the roadmap says so. It is also not a place for evidence: a run, a
measurement or a diagnosis lives in `reports/`, and the entry links to it.

Missing capability is not a defect. "The assistant cannot yet do X" belongs in
the roadmap. "The assistant claims to have done X and did not" belongs here.

## How to write one

Add the entry at the top of the list, take the next free number, and never
reuse a number — a closed issue keeps its id so that a report referring to it
stays readable.

```markdown
### ISS-0000 — one line, in the words of what goes wrong

- **Status:** open | mitigated | fixed | won't fix
- **Seen:** YYYY-MM-DD, where it was observed
- **Costs:** what it does to the person using the assistant
- **Reproduce:** the shortest thing that shows it, or "not reproduced"
- **Cause:** what is actually wrong, or "unknown"
- **Evidence:** reports/... , or a log identifier
- **Related:** other ids, roadmap queue items
```

Rules that keep the file honest:

- **Status is about the defect, not the effort.** `mitigated` means the harm is
  reduced and the defect is still there; only a verified fix is `fixed`.
- **Do not delete a fixed entry.** Set the status, add the date and what fixed
  it, and leave it. A defect that comes back is easier to recognise than to
  rediscover.
- **Cause stays "unknown" until it is proven.** A hypothesis written in the
  cause field becomes a fact for the next reader. Put it in `Reproduce` as a
  question or leave it out.
- **One defect per entry.** Two symptoms of one cause are one issue; one symptom
  with two causes is two.
- **A severity word is not a field here on purpose.** `Costs` says what it does
  to the person, which is the only ranking that survives disagreement.

---

### ISS-0021 — the end-of-turn token reaches the chat as a message

- **Status:** fixed in the tree, 2026-09-03 — the streamed-completion reader
  drops `<eos>`, `<end_of_turn>`, `<|im_end|>` and `<|eot_id|>` from the
  text, so a completion made of one such token is empty and ends the turn
  without a message. Deployed and held on run `af0370cb`: the turn ended on its answer, nothing after it.
- **Seen:** 2026-09-03, deployed, run `9c42241c`: the last model request of
  a spent turn answered with the single token `<eos>`, which was delivered
  to the person as its own message.
- **Costs:** a message that says `<eos>`.
- **Reproduce:** a turn whose last request has nothing to add; the served
  Gemma returns its end token as text.
- **Cause:** the server hands the end-of-turn token over as content and the
  client took every content chunk as text.
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0020

### ISS-0020 — a delivery is refused when the turn's budget is spent

- **Status:** fixed in the tree, 2026-09-03 — a tool marked `delivers`
  (`send_file`) still runs when the step, call or time ceiling is reached;
  every other call in that batch is halted as before, and the turn still
  ends. `tests/test_turn_bounds.py`. Deployed; run `af0370cb` never reached the ceiling, so the live check of the exemption is still to come.
- **Seen:** 2026-09-03, deployed, run `9c42241c`: after eleven tool calls
  the model wrote its answer together with one `send_file` of all four
  items — three files and the screenshot, one call, as asked for that
  morning — and the call was the twelfth step, refused with "answer now
  with what you already have". The person received the answer naming the
  files and none of the files.
- **Costs:** finished work stays in the workspace with a sentence saying it
  is done.
- **Reproduce:** any turn whose delivery is the step at the ceiling.
- **Cause:** the ceiling halted every call in the batch, a delivery among
  them, although a delivery costs no model time and is the outcome the
  ceiling exists to protect.
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0019, ISS-0003

### ISS-0019 — the page is written twice, identically, after the plan is updated

- **Status:** open
- **Seen:** 2026-09-03, deployed, five turns in a row (runs `b100a27a`,
  `f41278c9`, `af276ed7`, `752486c1`, `7673ce55`)
- **Costs:** after the three files are written and the plan is ticked, the
  model writes `index.html` again with byte-identical content (1245
  characters both times, compared in run `7673ce55`): one model call of
  about 9 s and 368 output tokens per turn for nothing.
- **Reproduce:** the Task Board request with a plan; compare the two
  `write_file` calls on `index.html`.
- **Cause:** unknown. It follows the `todo_write` update every time, as if
  the model re-executes the step it just marked done.
- **Also seen, without a plan:** 2026-09-03, run `9c42241c`, the worst so
  far: `index.html` written seven times, `styles.css` and `app.js` twice
  each, ten `write_file` calls where three were the work, 125 s and 5000
  output tokens before the page was inspected; then the ceiling. Not the
  plan, then. The identical writes were byte-identical each time.
- **Mitigated:** 2026-09-03, `write_file` with content the file already has
  answers `unchanged: … already had exactly this content … nothing was
  written` instead of `overwrote`, so a rewrite no longer reads as progress.
  Whether the model stops on that word is for the next live turn.
- **Held:** run `af0370cb`, "Task Board test 8": one identical rewrite of
  `index.html`, answered `unchanged`, and the model went straight to
  `inspect_page`. One wasted call of 8 s instead of seven.
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0016

### ISS-0018 — an existing folder is replaced without a word

- **Status:** open
- **Seen:** 2026-09-03, deployed, three turns in a row asking for "Task Board
  test 5" in the folder `Task Board test 5` (runs `f41278c9`, `af276ed7`,
  `752486c1`)
- **Costs:** the folder already held the previous attempt. The assistant
  wrote over all three files, read `overwrote Task Board test 5/index.html`
  four times per turn in its own tool results, and answered "Приложение
  готово" as if the place had been empty. The person is told nothing about
  what was there, what was kept or what was replaced. Work of theirs in a
  folder of the same name would go the same way.
- **Reproduce:** ask for an app in a folder that already has one.
- **Cause:** unknown. `list_files` was available and never called; the
  result word "overwrote" was read and ignored. The brief says workspace
  writes are autonomous and says nothing about what to do when the place is
  taken.
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0004; roadmap 4.7 is where the wording "if the place
  already holds files, say so and decide — keep, replace or a new name —
  never replace silently" would be accepted

### ISS-0017 — the screenshot the person receives is of the page without its CDN styles

- **Status:** fixed in the tree, 2026-09-03 — the human allowed the local artifact the public internet under the renderer's policy; not yet deployed
- **Seen:** 2026-09-03, deployed, thread `46c6a9c3`, run `253ede5d`
- **Costs:** the page loads Tailwind from `https://cdn.tailwindcss.com/`. The
  offline session refuses it, as it should, and says so in the report; the
  screenshot that `send_file` then delivers is of the unstyled page, while
  the person's own browser, which is online, shows the styled one. The
  model read "requests refused: https://cdn.tailwindcss.com/" and still wrote
  "Адаптивный дизайн (Tailwind CSS)".
- **Reproduce:** a page with a stylesheet or script from a CDN; inspect it;
  send the screenshot.
- **Cause:** the local artifact is rendered with no network by design
  (`DECISIONS.md` 2026-09-03: the boundary is a property of the session), and
  nothing tells the person or the model that the picture differs from what a
  browser with internet would show. Whether a local artifact may fetch from
  a public CDN through the same policy the public renderer uses is undecided.
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0014, ISS-0004; 4.5.5

### ISS-0016 — the plan is a list of phases, ticked in bulk

- **Status:** open
- **Seen:** 2026-09-03, live, three turns: thread `3261ae8f` (Task Board
  test 4), loop run `live-70`, thread `5cee5866` (Task Board test 5)
- **Costs:** the list is written before the work as generic phases —
  "create structure", "implement CSS", "verify and take screenshot" — and
  not as the request's own requirements (three columns, drag and drop,
  persistence, filter, responsive). It is then updated in bulk: five items
  marked completed in one call after the files are written, and "verify"
  marked completed after one look that exercised nothing. In test 4 it was
  never updated at all. The person sees a plan that says everything is done
  and reads nothing that was checked.
- **Reproduce:** any request with several requirements; compare the list to
  the request and the ticks to the tool calls.
- **Cause:** unknown. The 4.4 brief says what a list costs and when to use
  one; it says nothing about what an item is or what marks one done.
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0004, ISS-0008; roadmap 4.4 "known problems", 4.7

### ISS-0015 — a written page ends with a markdown fence

- **Status:** open
- **Seen:** 2026-09-03, live, `Task Board test 4/index.html` made through the
  loop against the deployed model
- **Costs:** the file ends with a literal ```` ``` ```` line after `</html>`,
  which the browser shows as text at the bottom of the page. The model read
  its own snapshot with `text: ```` ``` ```` in it and did not mention it.
- **Reproduce:** ask for a self-contained page; look at the last line.
- **Cause:** unknown. The same shape — a page that ends in a fence — is what
  the 2026-08-31 parser corruption was first measured on, so it may be the
  model closing a fence it never opened in the served format.
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0001, ISS-0008

### ISS-0014 — the page was looked at without storage or its own files

- **Status:** fixed in the tree, 2026-09-03 — not yet deployed
- **Seen:** 2026-09-03, live, twice: thread `afb9d76a` (an app with
  `styles.css` and `app.js`), and the loop re-run of "Task Board test 4"
- **Costs:** `inspect_page` opened the file as a `data:` URL. A `data:` page
  has no origin, so `localStorage` throws a SecurityError the app does not
  have in the person's browser, and a relative `styles.css` or `app.js`
  resolves to nothing, so a multi-file app is looked at unstyled and without
  its logic. The model was handed a false error and an unfair picture, and
  either ignored it or described what it saw.
- **Reproduce:** a page with `<link href="styles.css">` or a script using
  `localStorage`; inspect it on code before this fix.
- **Cause:** the document was passed as a URL instead of being served.
- **Fixed by:** the offline session serves the workspace at
  `http://artifact.local/` through request interception and fails everything
  else; the page has an origin, storage and its siblings, and a request the
  page makes elsewhere is reported as refused rather than as an error
  (`app/tools/chromium.py` `serve_directory`, `tests/test_browser_session.py`).
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0008; 4.5.5

### ISS-0013 — the repeat guard refused the call that would have worked

- **Status:** fixed in the tree, 2026-09-03 — not yet deployed
- **Seen:** 2026-09-03, deployed, thread `3261ae8f`, run `30fe463c`
- **Costs:** a look at a file failed twice because the file was not there,
  the model then wrote the file, and the third look — identical arguments, a
  file that now exists — was counted as the third identical failure. Every
  tool was halted for the turn, so the person got neither the screenshot nor
  the files they had asked for, after 261 s.
- **Reproduce:** make a call fail twice on a missing precondition, satisfy the
  precondition with another tool, repeat the call.
- **Cause:** `failed_before` counted identical failures across the whole turn,
  as if nothing could change between them.
- **Fixed by:** the count starts over when any tool has succeeded since the
  last identical failure (`app/agent/graph.py`,
  `tests/test_repeated_failure.py`).
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0012, which is what made the first two looks fail

### ISS-0012 — a corrupted path was obeyed, and a file nobody named was made

- **Status:** fixed in the tree, 2026-09-03 — not yet deployed
- **Seen:** 2026-09-03, deployed, thread `3261ae8f`, run `30fe463c`, twice
- **Costs:** `write_file` received the path `"Task Board test 4/index.html"<|"|>`
  — the served parser's leftovers around the real name — and created a file
  called exactly that on the person's volume. Every later call by the real
  name found nothing; the page was written four times; the junk file is still
  there beside the real one.
- **Reproduce:** call any path-taking tool with a path wrapped in quotes or
  carrying `<|`/`|>`.
- **Cause:** the fragment removal of 2026-08-31 recognises a fragment in a
  parameter name or as a `,name:` tail, not inside a string value; the
  filesystem accepted any characters the OS accepts.
- **Fixed by:** `resolve_in_root` refuses such a path as `bad_arguments` and
  asks for it again plainly (`app/tools/filesystem.py`, `tests/test_tools.py`).
- **Evidence:** `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0001, the upstream cause; ISS-0013

### ISS-0011 — every look at a page carried the whole page back as its address

- **Status:** fixed, 2026-09-03 — deployed the same day, `/check` 9/9 on that container
- **Seen:** 2026-09-03, deployed, thread `afb9d76a`, runs `8ffab1aa` and
  `240f09ea`
- **Costs:** `inspect_page` reported `url: location.href`, and for a local
  document that is the `data:` URL — the entire page, base64. A 7 KB page put
  about 9 KB of base64 into the model's context on every look, for nothing
  the model can read; the third call of run `8ffab1aa` was 17 764 input
  tokens. Stored history carries it too.
- **Reproduce:** `inspect_page` on any local file, on code before 4.5.5.
- **Cause:** the old evidence script returned the location of a data URL.
- **Fixed by:** roadmap 4.5.5, `page_report` in `app/tools/browser.py`, which
  reports no address for a local document. Fixed status once seen in the
  deployed profile.
- **Related:** 4.6a, which will have to shorten such results anyway

### ISS-0010 — "here is the screenshot", and nothing was sent

- **Status:** open
- **Seen:** 2026-09-03, deployed, thread `afb9d76a`, twice in one session
- **Costs:** asked "пришли скрин", the assistant calls `inspect_page`, sees
  the screenshot itself, and answers "Вот скриншот вашего приложения". The
  person receives text. Told "Я не получил изображение", it answers that it
  cannot attach an image to the chat and offers the workspace path instead.
  Only "скриншот отправь", the third request, produced a `send_file` and the
  picture. Both claims are false: `send_file` delivered that same PNG one turn
  later, and the brief says so in words ("a direct request to receive a
  screenshot or file is such a decision: perform the send_file call").
- **Reproduce:** make a page, then ask for a screenshot in one word.
- **Cause:** unknown. The 2026-08-29 note in `app/capabilities.py` records the
  same belief ("output supports only text") before the brief was written to
  contradict it, so the brief has not displaced it.
- **Also seen:** 2026-09-03, thread `3261ae8f`: "не могу напрямую отправить
  скриншот из системы", this time with every tool halted by ISS-0013 so no
  send was possible — the honest sentence was that the look had been refused.
- **Evidence:** runs `8ffab1aa` (inspect, "вот скриншот", nothing outbound),
  `240f09ea` (same), `eda12665` ("не могу прикрепить"), `29c2bd17`
  (`send_file` of the PNG, delivered), 2026-09-03T04:06–04:09Z; `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Related:** ISS-0003 is the same shape for a file; 4.7 scenario suite is
  where a prompt change would be accepted

### ISS-0009 — the person reads an answer for a minute and then it is deleted

- **Status:** fixed in the tree, 2026-09-03 — text that comes with a tool call is delivered and kept; a draft a steering refuses is held on the screen; and the plan seam, the only live source of steerings, no longer objects by the human's decision, so the second generation it caused is gone with it. Deployed the same day; to be seen live
- **Seen:** 2026-08-31, live, four turns in a row
- **Costs:** text appears and grows while the work happens, the person reads
  it, and then it vanishes and a file arrives instead. What is said afterwards
  is almost nothing: 17 output tokens in one turn, **one** in another. The
  assistant has already explained itself in a message it then took back.
- **Reproduce:** ask for anything the model narrates before writing. The
  narration is streamed, previewed, and withdrawn when the same completion
  turns out to end in a tool call.
- **Cause:** known and half deliberate. A completion that carries both text and
  a tool call has its preview discarded — added on 2026-08-30 so that a
  narrated tool call would not become a second answer in the chat. That fix is
  right about the end state and wrong about the middle: the preview should not
  have been shown, and by the time we know it should not have been, the person
  has been reading it for up to 58 s. Nothing in a stream says in advance
  whether it will end in a tool call.
- **Also seen:** 2026-09-03, run `7673ce55`, after the sends: the answer
  was delivered with the screenshot attached, three sends followed, and the
  model closed with the same functional list again plus "файлы отправлены"
  (108 tokens) — not verbatim, so the display rule let it through. The
  core prompt's "add only what is new" is not obeyed; a second bubble with
  the same list is what the person sees.
- **Also seen:** 2026-09-03, thread `d88734a2`, run `af276ed7`, after the
  hold: the bare `todo_write` that followed the steering deleted the held
  draft through the adapter's no-text path (fixed the same day), and the
  model, told its answer was kept and to add nothing, wrote it again anyway
  (162 tokens). The vanish is fixed; the second generation needs a decision
  on the plan seam's objection.
- **Also seen:** 2026-09-03, thread `052869f2`, run `f41278c9`, the other
  way in: the answer (166 tokens) was refused as an ending by the plan seam
  because "verify" was still in progress, withdrawn from the chat, the model
  ticked the item and wrote the same answer again (164 tokens). The seam was
  right to object and wrong to cost a second generation: the draft is now
  held and handed back as the answer when the model adds nothing.
- **Also seen:** 2026-09-03, thread `46c6a9c3`, run `253ede5d`, with the
  cost now measured. The model wrote the whole answer (410 characters, 169
  output tokens) and attached a `send_file` to it; the preview was withdrawn;
  the send ran; the next model call produced the same 409 characters again
  as a new message, 134 output tokens and 3.8 s. The first copy is not lost
  to the model — it stays in the turn as the assistant message that carried
  the call and is read as input on every later call — but the person watched
  it vanish and then paid for it twice.
- **Evidence:** runs `94e8bd24` (preview at 15.9 s, 2,075 tokens, withdrawn,
  final answer 17 tokens) and `3e5690ae` (preview at 67.1 s, withdrawn, final
  answer 1 token), 2026-08-31T05:06–05:11Z; `reports/2026-09-03_v2_first_session_on_the_tool_system.md`

### ISS-0008 — a generated app is delivered as working without ever being used

- **Status:** open
- **Seen:** 2026-08-31, live, "Personal Task Board 2" via Telegram
- **Costs:** the person receives an application described as ready, and the
  first thing they try does nothing. The task board saved new tasks and never
  drew them, because the render selector was `#todo.task-list` — one element
  with both an id and a class — where the list is a child of `#todo`.
- **Reproduce:** ask for an interactive page, open it, use the primary control.
- **Cause:** nothing in the loop exercises the artifact. `inspect_page` renders
  and looks; it does not click, type or read the console, so a defect that only
  appears on interaction cannot be seen by the only tool that looks. In this run
  the model did not call it at all, and had rewritten the same file twice.
- **Also seen:** 2026-08-31, run `cc98b3e0`. The request ended with the words
  "проверь что всё работает". Four files were written and nothing was opened,
  rendered or read back; the answer described the application as working. So
  the gap is not only that the loop cannot exercise an artifact — an explicit
  instruction to check did not produce a look either.
- **Also seen:** 2026-09-03, thread `afb9d76a`, "Task Board test 3": written
  in one call and described as done without a look (run `0bf67569`). Asked
  for a screenshot, the assistant first **rewrote the person's file** to seed
  it with sample tasks so the picture would show columns in use (run
  `8ffab1aa`) — an unasked change to the deliverable made for the sake of the
  evidence. The person reports the application itself works.
- **Evidence:** `reports/2026-08-31_v2_todo_live_failure.md`, section "Three
  live tests on a task big enough for a plan"
- **Related:** ISS-0004; roadmap 4.5.5. Since 2026-09-03 `BrowserSession`
  can click, type, press and select on a ref from its snapshot, and
  `inspect_page` returns that snapshot; no action is exposed to the model
  yet, so the defect stands as described.

### ISS-0007 — `tool_failed` carries no reason

- **Status:** fixed, 2026-09-03 — seen live the same day in `scripts/loop_live.py` E
- **Seen:** 2026-08-31, deployed telemetry
- **Costs:** nobody investigating a live failure can tell from the logs why a
  tool refused. Diagnosing ISS-0006 needed the volume and an offline
  reproduction to recover a message the process already had in hand.
- **Reproduce:** make any tool raise, then read the `tool_failed` event: tool,
  call index, stage, path, duration, and no error text.
- **Cause:** the event is emitted without the error the caller already holds.
- **Fixed by:** the typed outcome of roadmap 4.5. The executor records
  `code` and `message` on every `tool_failed`, and `tools/show_run.py` prints
  them under the call. `tests/test_tool_outcomes.py`.
- **Evidence:** run `e9bae9a5`, two `write_file` failures, 2026-08-31T04:14Z

### ISS-0006 — a path meant as a directory becomes a file, and poisons the folder

- **Status:** fixed, 2026-08-31 — offline only, not yet seen live
- **Seen:** 2026-08-31, live, "Personal Task Board 3" via Telegram
- **Costs:** two turns and about 155 s produced no folder. Every later write
  into that name failed, `list_files` on it failed, and the model gave up and
  scattered `index.html`, `app.js`, `styles.css` and `README.md` into the root
  of the person's workspace, where they still are.
- **Reproduce:**

  ```text
  write_file "Board 3/" "# Task board"   -> created Board 3/ (13 characters)
  Board 3 is now a file
  write_file "Board 3/index.html" ...    -> FileExistsError [WinError 183]
  list_files "Board 3"                   -> path 'Board 3' is not a directory
  ```

- **Cause:** `pathlib` drops a trailing separator, so `_write_file` in
  `app/tools/filesystem.py` treats `Board 3/` as an ordinary file name and
  creates it. There is nothing wrong with the model's call: a trailing slash is
  how everyone writes a directory.
- **Fixed by:** `write_file` refuses a path ending in a separator and says that
  directories are made for you, which is also now in the tool's description; an
  ancestor standing in the way is named instead of a platform error code. Seen
  twice more before the fix, in the only two live turns that opened a plan:
  runs `1763523c` and `3af91a0c`, 2026-08-31T05:27–05:30Z — a plan whose first
  item is "create the folder" produces exactly this call.
- **Evidence:** run `e9bae9a5` and run `28daa249`, 2026-08-31T04:14–04:17Z;
  offline reproduction as above; `tests/test_tools.py`
- **Related:** ISS-0005, which is why the model saw only an OS error and could
  not route around it; the repeat rule ended the first turn correctly at 52 s

### ISS-0005 — an OS error escapes the filesystem tools unwrapped

- **Status:** fixed, 2026-08-31 — offline only, not yet seen live
- **Seen:** 2026-08-31, live and offline
- **Costs:** the model is handed a raw platform error with a platform error
  code, instead of a sentence naming what it should do differently. It cannot
  act on it, and the wording differs by operating system.
- **Reproduce:** the ISS-0006 sequence raises `FileExistsError`, not `ToolError`.
- **Cause:** `resolve_in_root` wrapped `OSError`; the write, the `mkdir`, the
  read and the listing did not.
- **Fixed by:** wrapping them, in `app/tools/filesystem.py`. Since 2026-09-03
  every filesystem failure is an `fs.*` code with the `strerror` as detail,
  `write_file` is atomic like `edit_file`, and an exception that still escapes
  any tool becomes an `internal` result with the traceback in the log rather
  than a failed turn.
- **Related:** ISS-0006

### ISS-0004 — the assistant describes what it did not observe

- **Status:** open
- **Seen:** 2026-08-30, live
- **Costs:** the person is told about a page's contents that nobody looked at.
  Once the assistant reported a file it had never created, and only `send_file`
  failing revealed it.
- **Cause:** unknown. Three rounds of prompt wording made it better and worse in
  turn, which is evidence that wording is not the lever.
- **Evidence:** `reports/2026-08-30_v2_prompt_assembly.md`,
  `reports/2026-08-31_v2_todo_live_failure.md`
- **Related:** ISS-0008; roadmap step 4.5.5

### ISS-0003 — a made file is handed over as prose instead of sent

- **Status:** open
- **Seen:** 2026-08-30, live, twice in one session
- **Costs:** the person is given the literal text `[house.html](house.html)`
  and no file. A relative path is not a link the renderer will make clickable,
  so the delivery silently does not happen; the file arrives only when asked for
  by name.
- **Cause:** handing something over is `send_file`, and the model reaches for a
  link. Why it prefers the link is unknown.
- **Also seen:** 2026-09-03, deployed, thread `afb9d76a`, run `00e46d2a`:
  "и файл приложения" answered with the path `Task Board test 3/index.html`
  and "you can open it in any browser"; the file came only after "пришли
  файлы" (run `fb42cdb7`, `send_file`, delivered).
- **Also seen:** 2026-09-03, loop re-run `live-70`: asked for the screenshot
  and the files in one request, the model sent `index.html` with `send_file`
  and handed the screenshot over as `![Screenshot](.agent/browser/….png)` —
  a markdown image of a workspace path, which no interface renders. Then in
  Telegram, thread `5cee5866`, the same request: three files listed as paths,
  the screenshot as the same markdown image, nothing sent; both arrived only
  when asked again in two more turns. `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Mitigated:** 2026-09-03, the brief now says where the person is (the
  adapter declares `Delivery.place`), that they cannot see the workspace, and
  that a path, link or markdown image delivers nothing. First live turn on it
  (thread `46c6a9c3`): the screenshot was sent with `send_file` unprompted;
  the one file was still listed as a path and not sent. Second (thread
  `052869f2`): three files as paths and the markdown image again, no send at
  all. The brief does not hold; the status stays open.
- **Mitigated again:** 2026-09-03, every tool that leaves a workspace item
  now says in its result `to hand it to the person: send_file(path="…")`
  (`DECISIONS.md` 2026-09-03). If that does not hold live, the human has
  reopened an adapter delivery of a markdown image, on the condition that
  no delivery path blocks another.
- **Held, first turn:** run `7673ce55`, "Task Board test 6": the screenshot
  sent with the answer, then the three files, all unprompted, no markdown
  image. One turn is not a rate; the status stays mitigated.
- **Decided:** 2026-09-03, the human rejected a mechanical backstop in the
  adapter (delivering a markdown image the model wrote) as a crutch.
- **Evidence:** `reports/2026-08-30_v2_prompt_assembly.md`

### ISS-0002 — a picture someone sends is never kept

- **Status:** open
- **Seen:** 2026-08-30, verified against the deployed volume
- **Costs:** a document survives in the person's workspace; a photo, voice
  message or image is used inside that one turn and written nowhere, so `/new`
  loses it. The person reasonably believes what they sent is theirs to point at
  again. 22 entries on the volume, not one of them an image.
- **Cause:** the split lives in `admit_uploads` and is invisible to the person.

### ISS-0001 — the served tool parser loses what follows a long string argument

- **Status:** mitigated, 2026-08-31 — not fixed
- **Seen:** 2026-08-30 and 2026-08-31, live, three failed turns
- **Costs:** `write_file` arrived with `content` and no `path`, so nothing was
  written and the turn burned up to 264 s. The model then repeated the identical
  malformed call up to eight times.
- **Reproduce:** end a long `content` value with a stray markdown fence. The
  string's closing delimiter never arrives, the parser reads on to the next one
  — which is inside the following tool call — and the argument after it is
  swallowed. A four-variant GPU run cleared nesting, streaming and the planning
  tool of causing it.
- **Cause:** upstream, in vLLM's Gemma 4 tool parser; vLLM 51284 and 53431, both
  open, present in 0.26.0 and 0.27.1. Nothing constrains the emission on our
  side: tool schemas are advice, because the served model does not use guided
  decoding for tool calls.
- **What the mitigation is:** `write_file` forbids the fence in words; a call
  the parser mangled is cleaned before it reaches the conversation; an argument
  error now carries the tool's signature; and a call that failed twice
  identically is refused a third time. Live afterwards, the model recovered by
  itself after one refusal. A corrected parser exists and is tested offline in
  `tools/gemma4_parser.py`. Deploying it was rejected on 2026-09-03 as a fix for
  one model on one server; the runtime is instead made to survive any model's
  emission (`DECISIONS.md` 2026-09-03): since 2026-09-03 a call whose arguments
  are not a JSON object is delivered and refused as one `bad_arguments` result
  with the tool's signature, where until then the adapter raised and the whole
  request failed. Seen live 2026-09-03, thread `3261ae8f`: two calls missing
  `path` were each refused once with the signature and the turn went on; a
  third carried the leftovers inside the path itself and was obeyed
  (ISS-0012). The defect itself stays upstream and open. `reports/2026-09-03_v2_first_session_on_the_tool_system.md`
- **Evidence:** `reports/2026-08-31_v2_todo_live_failure.md`
